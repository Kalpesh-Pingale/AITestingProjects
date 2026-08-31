"""Genuine stage level progress from the CrewAI event bus.

Progress is derived from real events - task started, task completed, tool
usage, LLM calls - and never from a simulated token stream.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from jira_qa_crew.logging_utils import get_logger, redact
from jira_qa_crew.models import StageStatus, TicketResult, utc_now

logger = get_logger(__name__)

#: ``(ticket_key, stage_key, status, message)`` -> None
ProgressCallback = Callable[[str, str, StageStatus, str], None]


class StageTracker:
    """Maps CrewAI task names onto pipeline stages and updates the result."""

    def __init__(
        self,
        result: TicketResult,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.result = result
        self.on_progress = on_progress
        self._active: str | None = None

    # -- stage transitions ---------------------------------------------
    def start(self, stage_key: str, message: str = "") -> None:
        stage = self.result.stage(stage_key)
        if stage is None:
            return
        self._active = stage_key
        stage.status = StageStatus.RUNNING
        stage.started_at = stage.started_at or utc_now()
        stage.message = message or "Running"
        self._emit(stage_key, stage.status, stage.message)

    def complete(self, stage_key: str, message: str, warnings: list[str]) -> None:
        stage = self.result.stage(stage_key)
        if stage is None:
            return
        stage.completed_at = utc_now()
        stage.warnings = list(warnings)
        stage.status = StageStatus.WARNING if warnings else StageStatus.COMPLETED
        stage.message = message
        self._emit(stage_key, stage.status, message)

    def fail(self, stage_key: str, message: str) -> None:
        stage = self.result.stage(stage_key)
        if stage is None:
            return
        stage.completed_at = utc_now()
        stage.status = StageStatus.FAILED
        stage.message = redact(message)
        self._emit(stage_key, stage.status, stage.message)

    def activity(self, message: str) -> None:
        """Record a real activity message against the running stage."""
        text = redact(message).strip()
        if not text:
            return
        self.result.log.append(f"{utc_now().isoformat(timespec='seconds')} {text}")
        if self._active is None:
            return
        stage = self.result.stage(self._active)
        if stage and stage.status is StageStatus.RUNNING:
            stage.message = text[:200]
            self._emit(self._active, stage.status, stage.message)

    def _emit(self, stage_key: str, status: StageStatus, message: str) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(self.result.ticket_key, stage_key, status, message)
        except Exception as exc:  # noqa: BLE001 - UI callbacks must not break a run
            logger.debug("Progress callback failed: %s", redact(exc))


@contextmanager
def crew_event_listeners(tracker: StageTracker, task_stage_map: dict[str, str]) -> Iterator[None]:
    """Attach scoped CrewAI event handlers for the duration of one crew run.

    ``scoped_handlers`` guarantees the handlers are removed afterwards, so a
    second ticket never receives the previous ticket's listeners.
    """
    try:
        from crewai.events import crewai_event_bus
        from crewai.events.types.task_events import (
            TaskCompletedEvent,
            TaskFailedEvent,
            TaskStartedEvent,
        )
        from crewai.events.types.tool_usage_events import (
            ToolUsageErrorEvent,
            ToolUsageStartedEvent,
        )
    except Exception as exc:  # noqa: BLE001 - event API is optional
        logger.debug("CrewAI event bus unavailable: %s", redact(exc))
        yield
        return

    def _stage_for(event: Any) -> str | None:
        name = getattr(event, "task_name", None)
        if name and name in task_stage_map:
            return task_stage_map[name]
        task = getattr(event, "task", None)
        task_name = getattr(task, "name", None)
        if task_name and task_name in task_stage_map:
            return task_stage_map[task_name]
        return None

    with crewai_event_bus.scoped_handlers():

        @crewai_event_bus.on(TaskStartedEvent)
        def _on_task_started(_source: Any, event: Any) -> None:
            stage_key = _stage_for(event)
            if stage_key:
                tracker.start(stage_key, "Agent working")

        @crewai_event_bus.on(TaskCompletedEvent)
        def _on_task_completed(_source: Any, event: Any) -> None:
            stage_key = _stage_for(event)
            if stage_key:
                tracker.activity(f"{stage_key} produced structured output")

        @crewai_event_bus.on(TaskFailedEvent)
        def _on_task_failed(_source: Any, event: Any) -> None:
            stage_key = _stage_for(event)
            if stage_key:
                tracker.fail(stage_key, str(getattr(event, "error", "task failed")))

        @crewai_event_bus.on(ToolUsageStartedEvent)
        def _on_tool_started(_source: Any, event: Any) -> None:
            tool_name = getattr(event, "tool_name", "tool")
            tracker.activity(f"Calling tool {tool_name}")

        @crewai_event_bus.on(ToolUsageErrorEvent)
        def _on_tool_error(_source: Any, event: Any) -> None:
            tracker.activity(
                f"Tool {getattr(event, 'tool_name', 'tool')} failed: "
                f"{getattr(event, 'error', '')}"
            )

        yield
