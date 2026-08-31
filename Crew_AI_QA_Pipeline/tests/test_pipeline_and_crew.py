"""Pipeline orchestration, guardrails and the read-only Jira tool.

No LLM is called: the crew builder is replaced by a stub that plays back
validated stage outputs, so the deterministic half of the pipeline is tested
end to end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from jira_qa_crew.config import AppSettings, IntegrationMode
from jira_qa_crew.crew.callbacks import StageTracker
from jira_qa_crew.crew.factory import ticket_slug
from jira_qa_crew.crew.guardrails import (
    TicketCrewContext,
    analysis_guardrail,
    playwright_guardrail,
)
from jira_qa_crew.crew.guardrails import (
    test_cases_guardrail as cases_guardrail,  # aliased: pytest collects test_* names
)
from jira_qa_crew.crew.guardrails import (
    test_plan_guardrail as plan_guardrail,
)
from jira_qa_crew.exceptions import (
    ConfigurationError,
    JiraNotFoundError,
    JiraProviderError,
)
from jira_qa_crew.jira.base import JiraProvider
from jira_qa_crew.jira.gateway import JiraGateway
from jira_qa_crew.models import (
    JiraIssue,
    ProviderSource,
    StageStatus,
    TicketResult,
    TicketStatus,
)
from jira_qa_crew.services.pipeline import QAPipeline
from jira_qa_crew.tools.jira_tool import FetchJiraIssueTool
from tests.factories import (
    TICKET,
    make_analysis,
    make_bundle,
    make_issue,
    make_suite,
    make_test_plan,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubProvider(JiraProvider):
    source = ProviderSource.REST

    def __init__(self, settings: AppSettings, *, fail_keys: set[str] | None = None) -> None:
        super().__init__(settings)
        self.fail_keys = fail_keys or set()

    @property
    def name(self) -> str:
        return "Stub REST"

    def health_check(self) -> None:
        return None

    def fetch_issue(self, key: str) -> JiraIssue:
        if key in self.fail_keys:
            raise JiraNotFoundError(f"{key} not found", provider=self.name)
        issue = make_issue(key)
        issue.source = ProviderSource.REST
        return issue


class FakeCrew:
    """Replays validated stage outputs onto the shared context."""

    def __init__(self, context: TicketCrewContext, tracker: StageTracker, *, stop_after: int = 4):
        self.context = context
        self.tracker = tracker
        self.stop_after = stop_after
        self.kicked = 0

    def kickoff(self) -> None:
        self.kicked += 1
        key = self.context.ticket_key
        steps = [
            ("jira_analyst", "analysis", make_analysis(key), "2 requirements"),
            ("test_plan_writer", "test_plan", make_test_plan(key), "12 sections"),
            ("test_case_writer", "test_cases", make_suite(key), "2 test cases"),
            ("playwright_coder", "playwright", make_bundle(key), "1 file"),
        ]
        for index, (stage_key, attribute, value, message) in enumerate(steps):
            if index >= self.stop_after:
                raise RuntimeError("stage exploded")
            self.tracker.start(stage_key)
            setattr(self.context, attribute, value)
            self.tracker.complete(stage_key, message, [])


@dataclass
class FakeTicketCrew:
    crew: FakeCrew
    context: TicketCrewContext
    task_stage_map: dict[str, str]


def make_crew_builder(stop_after: int = 4):
    def builder(settings, gateway, *, ticket_key, issue, fetch_outcome=None, tracker=None):
        context = TicketCrewContext(ticket_key=ticket_key, issue=issue)
        return FakeTicketCrew(
            crew=FakeCrew(context, tracker, stop_after=stop_after),
            context=context,
            task_stage_map={},
        )

    return builder


@pytest.fixture
def pipeline_settings(settings: AppSettings) -> AppSettings:
    settings.jira_integration_mode = IntegrationMode.REST
    return settings


def build_pipeline(settings: AppSettings, *, stop_after: int = 4, fail_keys=None) -> QAPipeline:
    gateway = JiraGateway(
        settings,
        mode=IntegrationMode.REST,
        rest_provider=StubProvider(settings, fail_keys=fail_keys),
    )
    return QAPipeline(
        settings,
        gateway=gateway,
        mode=IntegrationMode.REST,
        crew_builder=make_crew_builder(stop_after),
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def test_successful_run_produces_every_artifact(pipeline_settings: AppSettings) -> None:
    run = build_pipeline(pipeline_settings).run([TICKET])

    ticket = run.tickets[0]
    assert ticket.status in (TicketStatus.COMPLETED, TicketStatus.COMPLETED_WITH_WARNINGS)
    assert ticket.provider_source is ProviderSource.REST
    assert ticket.traceability is not None
    assert run.successful

    run_dir = Path(run.output_dir)
    assert (run_dir / "run_summary.md").is_file()
    assert (run_dir / TICKET / "test_cases.csv").is_file()
    assert (run_dir / TICKET / "playwright" / "tests" / "vwo-48.spec.ts").is_file()


def test_all_four_stages_are_reported(pipeline_settings: AppSettings) -> None:
    run = build_pipeline(pipeline_settings).run([TICKET])
    stages = run.tickets[0].stages
    assert [stage.key for stage in stages] == [
        "jira_analyst",
        "test_plan_writer",
        "test_case_writer",
        "playwright_coder",
    ]
    assert all(stage.status is StageStatus.COMPLETED for stage in stages)
    assert all(stage.duration_seconds is not None for stage in stages)


def test_progress_callbacks_receive_real_transitions(pipeline_settings: AppSettings) -> None:
    events: list[tuple[str, str, StageStatus]] = []

    def on_progress(key: str, stage: str, status: StageStatus, _message: str) -> None:
        events.append((key, stage, status))

    build_pipeline(pipeline_settings).run([TICKET], on_progress=on_progress)

    assert (TICKET, "jira_analyst", StageStatus.RUNNING) in events
    assert (TICKET, "playwright_coder", StageStatus.COMPLETED) in events


def test_one_failing_ticket_does_not_stop_the_others(pipeline_settings: AppSettings) -> None:
    pipeline = build_pipeline(pipeline_settings, fail_keys={"VWO-49"})
    run = pipeline.run(["VWO-48", "VWO-49", "VWO-50"])

    assert [t.ticket_key for t in run.tickets] == ["VWO-48", "VWO-49", "VWO-50"]
    assert run.ticket("VWO-49").status is TicketStatus.FAILED
    assert run.ticket("VWO-48").status is not TicketStatus.FAILED
    assert run.ticket("VWO-50").status is not TicketStatus.FAILED
    assert run.successful
    assert len(run.failed) == 1


def test_failed_fetch_marks_the_first_stage_failed(pipeline_settings: AppSettings) -> None:
    run = build_pipeline(pipeline_settings, fail_keys={TICKET}).run([TICKET])
    ticket = run.tickets[0]
    assert ticket.stage("jira_analyst").status is StageStatus.FAILED
    assert "not found" in " ".join(ticket.errors)
    assert ticket.analysis is None


def test_ticket_is_never_successful_with_missing_output(pipeline_settings: AppSettings) -> None:
    run = build_pipeline(pipeline_settings, stop_after=2).run([TICKET])
    ticket = run.tickets[0]

    assert ticket.status is TicketStatus.FAILED
    assert ticket.analysis is not None and ticket.playwright is None
    assert any("Required output missing" in error for error in ticket.errors)
    # Partial artifacts are still written for review.
    assert (Path(run.output_dir) / TICKET / "requirements_analysis.md").is_file()


def test_tickets_do_not_share_context(pipeline_settings: AppSettings) -> None:
    run = build_pipeline(pipeline_settings).run(["VWO-48", "VWO-49"])
    first, second = run.tickets
    assert first.analysis.ticket_key == "VWO-48"
    assert second.analysis.ticket_key == "VWO-49"
    assert first.analysis is not second.analysis
    for case in second.test_cases.test_cases:
        assert case.id.startswith("VWO-49")


def test_run_manifest_is_written_and_indexes_tickets(pipeline_settings: AppSettings) -> None:
    run = build_pipeline(pipeline_settings).run(["VWO-48", "VWO-49"])
    manifest = json.loads((Path(run.output_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == run.run_id
    assert [t["ticket_key"] for t in manifest["tickets"]] == ["VWO-48", "VWO-49"]
    assert manifest["successful"] is True


def test_demo_mode_is_labelled_in_the_result(demo_settings: AppSettings, fixture_dir) -> None:
    from jira_qa_crew.jira.demo_provider import JiraDemoProvider

    gateway = JiraGateway(
        demo_settings,
        mode=IntegrationMode.AUTO,
        demo_provider=JiraDemoProvider(demo_settings, fixture_dir=fixture_dir),
    )
    pipeline = QAPipeline(
        demo_settings,
        gateway=gateway,
        mode=IntegrationMode.AUTO,
        crew_builder=make_crew_builder(),
    )

    run = pipeline.run([TICKET])

    assert run.demo_mode is True
    assert run.tickets[0].provider_source is ProviderSource.DEMO
    assert any("DEMO MODE" in warning for warning in run.tickets[0].warnings)


def test_preflight_blocks_a_run_without_an_llm(tmp_path: Path) -> None:
    settings = AppSettings(OUTPUT_DIR=tmp_path, JIRA_URL="https://example.atlassian.net")
    pipeline = QAPipeline(settings, gateway=JiraGateway(settings), mode=IntegrationMode.REST)

    problems = pipeline.preflight()

    assert any("LLM_MODEL" in problem for problem in problems)
    with pytest.raises(ConfigurationError):
        pipeline.run([TICKET])


def test_ticket_slug_is_filename_safe() -> None:
    assert ticket_slug("VWO-48") == "vwo-48"
    assert ticket_slug("../../evil") == "evil"


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------


class Output:
    """Minimal stand-in for a CrewAI TaskOutput."""

    def __init__(self, pydantic: Any = None, json_dict: dict | None = None) -> None:
        self.pydantic = pydantic
        self.json_dict = json_dict
        self.raw = ""


@pytest.fixture
def context() -> TicketCrewContext:
    return TicketCrewContext(ticket_key=TICKET, issue=make_issue())


def test_analysis_guardrail_accepts_valid_output(context: TicketCrewContext) -> None:
    ok, _detail = analysis_guardrail(context)(Output(make_analysis()))
    assert ok
    assert context.analysis is not None


def test_analysis_guardrail_rejects_unparseable_output(context: TicketCrewContext) -> None:
    ok, message = analysis_guardrail(context)(Output(None))
    assert not ok
    assert "RequirementAnalysis" in message
    assert context.analysis is None


def test_analysis_guardrail_recovers_from_json_dict(context: TicketCrewContext) -> None:
    payload = make_analysis().model_dump(mode="json")
    ok, _detail = analysis_guardrail(context)(Output(None, json_dict=payload))
    assert ok


def test_analysis_guardrail_reports_validation_errors(context: TicketCrewContext) -> None:
    analysis = make_analysis()
    analysis.requirements[1].id = "REQ-001"
    ok, message = analysis_guardrail(context)(Output(analysis))
    assert not ok
    assert "Duplicate requirement id" in message


def test_downstream_guardrails_require_the_previous_stage(context: TicketCrewContext) -> None:
    ok, message = plan_guardrail(context)(Output(make_test_plan()))
    assert not ok
    assert "stage 1" in message


def test_full_guardrail_chain_populates_the_context(context: TicketCrewContext) -> None:
    assert analysis_guardrail(context)(Output(make_analysis()))[0]
    assert plan_guardrail(context)(Output(make_test_plan()))[0]
    assert cases_guardrail(context)(Output(make_suite()))[0]
    assert playwright_guardrail(context)(Output(make_bundle()))[0]
    assert context.playwright is not None
    assert context.reports.keys() == {
        "jira_analyst",
        "test_plan_writer",
        "test_case_writer",
        "playwright_coder",
    }


def test_guardrail_warnings_do_not_block(context: TicketCrewContext) -> None:
    analysis_guardrail(context)(Output(make_analysis()))
    plan = make_test_plan()
    plan.scenarios = plan.scenarios[:1]
    ok, _detail = plan_guardrail(context)(Output(plan))
    assert ok
    assert any("REQ-002" in warning for warning in context.warnings())


def test_guardrail_normalises_markdown_fences(context: TicketCrewContext) -> None:
    analysis_guardrail(context)(Output(make_analysis()))
    plan_guardrail(context)(Output(make_test_plan()))
    cases_guardrail(context)(Output(make_suite()))
    bundle = make_bundle()
    bundle.files[0].content = "```ts\n" + bundle.files[0].content + "```"
    ok, _detail = playwright_guardrail(context)(Output(bundle))
    assert ok
    assert "```" not in context.playwright.files[0].content


# ---------------------------------------------------------------------------
# Read-only Jira tool
# ---------------------------------------------------------------------------


def test_tool_returns_the_scoped_ticket(settings: AppSettings) -> None:
    gateway = JiraGateway(settings, mode=IntegrationMode.REST, rest_provider=StubProvider(settings))
    tool = FetchJiraIssueTool(gateway, TICKET)

    output = tool._run(ticket_key=TICKET)

    assert "Ticket key: VWO-48" in output
    assert tool.outcome is not None


def test_tool_refuses_any_other_ticket(settings: AppSettings) -> None:
    gateway = JiraGateway(settings, mode=IntegrationMode.REST, rest_provider=StubProvider(settings))
    tool = FetchJiraIssueTool(gateway, TICKET)

    output = tool._run(ticket_key="SECRET-1")

    assert output.startswith("REFUSED")
    assert "SECRET-1" in output
    assert tool.outcome is None


def test_tool_reports_provider_errors_without_raising(settings: AppSettings) -> None:
    class Failing(StubProvider):
        def fetch_issue(self, key: str) -> JiraIssue:
            raise JiraProviderError("jira exploded", provider="Stub REST")

    gateway = JiraGateway(settings, mode=IntegrationMode.REST, rest_provider=Failing(settings))
    output = FetchJiraIssueTool(gateway, TICKET)._run(ticket_key=TICKET)

    assert output.startswith("ERROR")
    assert "jira exploded" in output


def test_tool_uses_the_prefetched_issue_without_a_second_call(settings: AppSettings) -> None:
    from jira_qa_crew.jira.gateway import FetchAttempt, FetchOutcome

    class Counting(StubProvider):
        calls = 0

        def fetch_issue(self, key: str) -> JiraIssue:
            Counting.calls += 1
            return super().fetch_issue(key)

    provider = Counting(settings)
    gateway = JiraGateway(settings, mode=IntegrationMode.REST, rest_provider=provider)
    prefetched = FetchOutcome(issue=make_issue(), attempts=[FetchAttempt("Stub REST", True)])
    tool = FetchJiraIssueTool(gateway, TICKET, prefetched=prefetched)

    tool._run(ticket_key=TICKET)

    assert Counting.calls == 0


def test_tracker_records_redacted_activity(monkeypatch) -> None:
    monkeypatch.setenv("JIRA_API_TOKEN", "ATATTsupersecrettoken123")
    ticket = TicketResult(ticket_key=TICKET)
    tracker = StageTracker(ticket)
    tracker.start("jira_analyst")
    tracker.activity("calling jira with ATATTsupersecrettoken123")

    assert "ATATTsupersecrettoken123" not in " ".join(ticket.log)
    assert ticket.stage("jira_analyst").status is StageStatus.RUNNING


# ---------------------------------------------------------------------------
# Real CrewAI wiring (construction only - no LLM call)
# ---------------------------------------------------------------------------


def test_real_crew_is_constructible_and_wired_correctly(settings: AppSettings) -> None:
    """Guards the CrewAI contract: guardrails, structured output and context.

    CrewAI validates guardrail signatures at Task construction time, so this
    catches regressions such as postponed annotations breaking the guardrail
    check without ever calling a model.
    """
    from jira_qa_crew.crew.factory import build_ticket_crew

    # A real provider/model id: CrewAI resolves the model at construction.
    settings.llm_model = "openai/gpt-4.1-mini"
    gateway = JiraGateway(settings, mode=IntegrationMode.REST, rest_provider=StubProvider(settings))
    tracker = StageTracker(TicketResult(ticket_key=TICKET))

    built = build_ticket_crew(
        settings, gateway, ticket_key=TICKET, issue=make_issue(), tracker=tracker
    )
    crew = built.crew

    assert crew.process.value == "sequential"
    assert len(crew.agents) == 4
    assert [task.name for task in crew.tasks] == [
        "analyse_requirements",
        "write_test_plan",
        "write_test_cases",
        "write_playwright",
    ]
    assert [task.output_pydantic.__name__ for task in crew.tasks] == [
        "RequirementAnalysis",
        "TestPlan",
        "TestCaseSuite",
        "PlaywrightBundle",
    ]
    # Exactly one controlled repair attempt per stage.
    assert all(task.guardrail_max_retries == 1 for task in crew.tasks)
    assert all(task.guardrail is not None for task in crew.tasks)
    # Later stages receive the earlier validated outputs as explicit context.
    assert [c.name for c in crew.tasks[1].context] == ["analyse_requirements"]
    assert [c.name for c in crew.tasks[3].context] == [
        "analyse_requirements",
        "write_test_cases",
    ]
    # Only the analyst can reach Jira.
    assert [tool.name for tool in crew.agents[0].tools] == ["fetch_jira_issue"]
    assert all(not agent.tools for agent in crew.agents[1:])
    # The ticket is injected as clearly marked untrusted data.
    assert "UNTRUSTED_JIRA_DATA" in crew.tasks[0].description
    assert not any(agent.allow_delegation for agent in crew.agents)
