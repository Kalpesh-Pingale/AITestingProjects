"""Run orchestration.

The pipeline owns everything the LLM must not decide: which provider is
used, whether a stage passed validation, how coverage is calculated, what is
written to disk, and whether a ticket counts as successful.

Per ticket:

1. fetch the issue deterministically through :class:`JiraGateway`;
2. build a fresh four-agent crew for that ticket only;
3. run it sequentially with guardrail-backed validation after each stage;
4. compute traceability in Python;
5. render and write artifacts;
6. classify the ticket as completed, completed-with-warnings or failed.

A failure in one ticket never stops the remaining tickets.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
from collections.abc import Callable
from pathlib import Path

from jira_qa_crew.config import AppSettings, IntegrationMode, get_settings
from jira_qa_crew.crew.callbacks import ProgressCallback, StageTracker, crew_event_listeners
from jira_qa_crew.crew.factory import build_ticket_crew
from jira_qa_crew.exceptions import (
    ConfigurationError,
    JiraProviderError,
    JiraQACrewError,
)
from jira_qa_crew.jira.gateway import JiraGateway
from jira_qa_crew.logging_utils import configure_logging, get_logger, redact
from jira_qa_crew.models import (
    ProviderSource,
    RunResult,
    StageStatus,
    TicketResult,
    TicketStatus,
    utc_now,
)
from jira_qa_crew.services.artifacts import (
    new_run_id,
    sanitise_segment,
    write_run_artifacts,
    write_ticket_artifacts,
)
from jira_qa_crew.services.traceability import build_traceability

logger = get_logger(__name__)

#: ``(run_result)`` -> None, called after every ticket so the UI can refresh.
RunCallback = Callable[[RunResult], None]


class QAPipeline:
    """Deterministic orchestration around the CrewAI stages."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        *,
        gateway: JiraGateway | None = None,
        mode: IntegrationMode | None = None,
        crew_builder: Callable[..., object] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        configure_logging(self.settings.log_level)
        self.mode = mode or self.settings.jira_integration_mode
        self.gateway = gateway or JiraGateway(self.settings, mode=self.mode)
        self._crew_builder = crew_builder or build_ticket_crew

    # -- public API -----------------------------------------------------
    def preflight(self) -> list[str]:
        """Blocking configuration problems for the selected mode."""
        return self.settings.validate_for_run(self.mode)

    def run(
        self,
        ticket_keys: list[str],
        *,
        on_progress: ProgressCallback | None = None,
        on_ticket_done: RunCallback | None = None,
    ) -> RunResult:
        """Process every ticket, continuing past individual failures."""
        problems = self.preflight()
        if problems:
            raise ConfigurationError("; ".join(problems))

        run = RunResult(
            run_id=new_run_id(),
            requested_keys=list(ticket_keys),
            integration_mode=self.mode.value,
            demo_mode=self.settings.demo_mode,
        )
        run_dir = self.settings.output_path / sanitise_segment(run.run_id, fallback="RUN")
        run.output_dir = str(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        for key in ticket_keys:
            ticket = TicketResult(ticket_key=key)
            run.tickets.append(ticket)
            try:
                self._process_ticket(ticket, on_progress)
            except Exception as exc:  # noqa: BLE001 - one ticket must not stop the run
                message = redact(exc)
                logger.exception("Unhandled error while processing %s", key)
                ticket.errors.append(f"Unhandled error: {message}")
                ticket.status = TicketStatus.FAILED
            finally:
                ticket.completed_at = ticket.completed_at or utc_now()
                self._finalise_ticket(ticket, run_dir)
                if on_ticket_done is not None:
                    try:
                        on_ticket_done(run)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("Run callback failed: %s", redact(exc))

        run.completed_at = utc_now()
        try:
            write_run_artifacts(run, run_dir)
        except JiraQACrewError as exc:
            run.errors.append(redact(exc))
        return run

    # -- per ticket -----------------------------------------------------
    def _process_ticket(
        self,
        ticket: TicketResult,
        on_progress: ProgressCallback | None,
    ) -> None:
        tracker = StageTracker(ticket, on_progress=on_progress)
        tracker.start("jira_analyst", "Fetching the ticket from Jira")

        try:
            outcome = self.gateway.fetch(ticket.ticket_key)
        except JiraProviderError as exc:
            message = redact(exc)
            tracker.fail("jira_analyst", message)
            ticket.errors.append(message)
            ticket.status = TicketStatus.FAILED
            return

        ticket.issue = outcome.issue
        ticket.provider_source = outcome.issue.source
        for attempt in outcome.attempts:
            tracker.activity(
                f"{attempt.provider}: {'ok' if attempt.ok else 'failed'}"
                + (f" - {attempt.detail}" if attempt.detail else "")
            )
        tracker.activity(
            f"Fetched {ticket.ticket_key} via {outcome.issue.source.value}"
        )

        if outcome.issue.source is ProviderSource.DEMO:
            ticket.warnings.append(
                "DEMO MODE: this ticket was read from a local fixture, not from Jira."
            )

        ticket_crew = self._crew_builder(
            self.settings,
            self.gateway,
            ticket_key=ticket.ticket_key,
            issue=outcome.issue,
            fetch_outcome=outcome,
            tracker=tracker,
        )
        tracker.start("jira_analyst", "Analysing requirements")

        try:
            self._kickoff(ticket_crew, tracker)
        except concurrent.futures.TimeoutError:
            message = (
                f"The ticket exceeded PIPELINE_TICKET_TIMEOUT_SECONDS "
                f"({self.settings.pipeline_ticket_timeout_seconds}s)."
            )
            ticket.errors.append(message)
            self._fail_open_stages(ticket, tracker, "Timed out")
        except Exception as exc:  # noqa: BLE001 - reported per ticket
            message = redact(exc)
            logger.warning("Crew failed for %s: %s", ticket.ticket_key, message)
            ticket.errors.append(message)
            self._fail_open_stages(ticket, tracker, message)

        context = ticket_crew.context
        ticket.analysis = context.analysis
        ticket.test_plan = context.test_plan
        ticket.test_cases = context.test_cases
        ticket.playwright = context.playwright
        ticket.warnings.extend(context.warnings())

        if ticket.analysis is not None:
            ticket.traceability = build_traceability(
                ticket.analysis, ticket.test_cases, ticket.playwright
            )

    def _kickoff(self, ticket_crew: object, tracker: StageTracker) -> None:
        """Run the crew with a hard wall-clock budget for the ticket."""
        crew = ticket_crew.crew  # type: ignore[attr-defined]
        stage_map = ticket_crew.task_stage_map  # type: ignore[attr-defined]
        timeout = max(30, self.settings.pipeline_ticket_timeout_seconds)

        def runner() -> None:
            with crew_event_listeners(tracker, stage_map):
                crew.kickoff()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(runner)
            future.result(timeout=timeout)

    def _fail_open_stages(
        self, ticket: TicketResult, tracker: StageTracker, message: str
    ) -> None:
        for stage in ticket.stages:
            if stage.status in (StageStatus.PENDING, StageStatus.RUNNING):
                tracker.fail(stage.key, message)

    def _finalise_ticket(self, ticket: TicketResult, run_dir: Path) -> None:
        """Write artifacts and decide the ticket outcome."""
        try:
            write_ticket_artifacts(ticket, run_dir)
        except JiraQACrewError as exc:
            ticket.errors.append(redact(exc))

        required = (
            ticket.analysis,
            ticket.test_plan,
            ticket.test_cases,
            ticket.playwright,
        )
        missing = [
            name
            for name, value in zip(
                ("requirement analysis", "test plan", "test cases", "playwright bundle"),
                required,
                strict=True,
            )
            if value is None
        ]

        if missing or ticket.errors:
            if missing:
                ticket.errors.append(
                    "Required output missing: " + ", ".join(missing) + "."
                )
            ticket.status = TicketStatus.FAILED
        elif ticket.warnings or any(
            stage.status is StageStatus.WARNING for stage in ticket.stages
        ):
            ticket.status = TicketStatus.COMPLETED_WITH_WARNINGS
        else:
            ticket.status = TicketStatus.COMPLETED

        # Rewrite the manifest so it reflects the final status.
        if ticket.artifacts:
            with contextlib.suppress(JiraQACrewError):
                write_ticket_artifacts(ticket, run_dir)
