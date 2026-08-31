"""CrewAI task construction.

Tasks are chained with explicit ``context`` so each stage receives the
validated output of the previous one, and every task declares a Pydantic
structured output plus a deterministic guardrail.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from crewai import Agent, Task

from jira_qa_crew.models import (
    PlaywrightBundle,
    RequirementAnalysis,
    TestCaseSuite,
    TestPlan,
)
from jira_qa_crew.prompts import task_spec

#: CrewAI task name -> pipeline stage key. Used for progress tracking.
TASK_STAGE_MAP: dict[str, str] = {
    "analyse_requirements": "jira_analyst",
    "write_test_plan": "test_plan_writer",
    "write_test_cases": "test_case_writer",
    "write_playwright": "playwright_coder",
}


def _task(
    name: str,
    agent: Agent,
    output_model: type,
    guardrail: Callable[[Any], tuple[bool, Any]],
    context: list[Task] | None = None,
    **tokens: Any,
) -> Task:
    spec = task_spec(name, **tokens)
    return Task(
        name=name,
        description=spec["description"],
        expected_output=spec["expected_output"],
        agent=agent,
        context=context or [],
        output_pydantic=output_model,
        guardrail=guardrail,
        guardrail_max_retries=1,
        markdown=False,
    )


def build_analysis_task(
    agent: Agent,
    guardrail: Callable[[Any], tuple[bool, Any]],
    *,
    ticket_key: str,
    provider_source: str,
    issue_block: str,
) -> Task:
    """Stage 1 task: fetch context is injected, the tool allows a re-read."""
    return _task(
        "analyse_requirements",
        agent,
        RequirementAnalysis,
        guardrail,
        ticket_key=ticket_key,
        provider_source=provider_source,
        issue_block=issue_block,
    )


def build_test_plan_task(
    agent: Agent,
    guardrail: Callable[[Any], tuple[bool, Any]],
    *,
    ticket_key: str,
    context: list[Task],
) -> Task:
    """Stage 2 task."""
    return _task(
        "write_test_plan",
        agent,
        TestPlan,
        guardrail,
        context=context,
        ticket_key=ticket_key,
    )


def build_test_cases_task(
    agent: Agent,
    guardrail: Callable[[Any], tuple[bool, Any]],
    *,
    ticket_key: str,
    context: list[Task],
) -> Task:
    """Stage 3 task."""
    return _task(
        "write_test_cases",
        agent,
        TestCaseSuite,
        guardrail,
        context=context,
        ticket_key=ticket_key,
    )


def build_playwright_task(
    agent: Agent,
    guardrail: Callable[[Any], tuple[bool, Any]],
    *,
    ticket_key: str,
    ticket_slug: str,
    context: list[Task],
) -> Task:
    """Stage 4 task."""
    return _task(
        "write_playwright",
        agent,
        PlaywrightBundle,
        guardrail,
        context=context,
        ticket_key=ticket_key,
        ticket_slug=ticket_slug,
    )
