"""Builds one isolated CrewAI crew per ticket."""

from __future__ import annotations

import re
from dataclasses import dataclass

from crewai import Crew, Process

from jira_qa_crew.config import AppSettings
from jira_qa_crew.crew.agents import (
    build_jira_analyst,
    build_playwright_coder,
    build_test_case_writer,
    build_test_plan_writer,
)
from jira_qa_crew.crew.callbacks import StageTracker
from jira_qa_crew.crew.guardrails import (
    TicketCrewContext,
    analysis_guardrail,
    playwright_guardrail,
    test_cases_guardrail,
    test_plan_guardrail,
)
from jira_qa_crew.crew.llm import build_llm
from jira_qa_crew.crew.tasks import (
    TASK_STAGE_MAP,
    build_analysis_task,
    build_playwright_task,
    build_test_cases_task,
    build_test_plan_task,
)
from jira_qa_crew.jira.gateway import FetchOutcome, JiraGateway
from jira_qa_crew.jira.textify import render_issue_for_prompt
from jira_qa_crew.models import JiraIssue
from jira_qa_crew.tools.jira_tool import FetchJiraIssueTool


@dataclass(slots=True)
class TicketCrew:
    """A ready-to-run crew plus the context its guardrails write into."""

    crew: Crew
    context: TicketCrewContext
    task_stage_map: dict[str, str]


def ticket_slug(ticket_key: str) -> str:
    """``VWO-48`` -> ``vwo-48``, safe for a file name."""
    return re.sub(r"[^a-z0-9]+", "-", ticket_key.lower()).strip("-") or "ticket"


def build_ticket_crew(
    settings: AppSettings,
    gateway: JiraGateway,
    *,
    ticket_key: str,
    issue: JiraIssue,
    fetch_outcome: FetchOutcome | None = None,
    tracker: StageTracker | None = None,
) -> TicketCrew:
    """Create a fresh four-agent sequential crew for a single ticket.

    Nothing is shared with a previous ticket: new LLM handle, new agents, new
    tasks, new tool instance scoped to this ticket key, new context object.
    """
    llm = build_llm(settings)
    context = TicketCrewContext(ticket_key=ticket_key, issue=issue)

    jira_tool = FetchJiraIssueTool(
        gateway,
        ticket_key,
        max_chars=settings.pipeline_max_field_chars,
        prefetched=fetch_outcome,
    )
    issue_block = render_issue_for_prompt(
        issue, max_chars=settings.pipeline_max_field_chars
    )

    analyst = build_jira_analyst(llm, ticket_key, jira_tool)
    planner = build_test_plan_writer(llm, ticket_key)
    case_writer = build_test_case_writer(llm, ticket_key)
    coder = build_playwright_coder(llm, ticket_key)

    analysis_task = build_analysis_task(
        analyst,
        analysis_guardrail(context, tracker),
        ticket_key=ticket_key,
        provider_source=issue.source.value,
        issue_block=issue_block,
    )
    plan_task = build_test_plan_task(
        planner,
        test_plan_guardrail(context, tracker),
        ticket_key=ticket_key,
        context=[analysis_task],
    )
    cases_task = build_test_cases_task(
        case_writer,
        test_cases_guardrail(context, tracker),
        ticket_key=ticket_key,
        context=[analysis_task, plan_task],
    )
    playwright_task = build_playwright_task(
        coder,
        playwright_guardrail(context, tracker),
        ticket_key=ticket_key,
        ticket_slug=ticket_slug(ticket_key),
        context=[analysis_task, cases_task],
    )

    crew = Crew(
        name=f"jira-qa-crew-{ticket_slug(ticket_key)}",
        agents=[analyst, planner, case_writer, coder],
        tasks=[analysis_task, plan_task, cases_task, playwright_task],
        process=Process.sequential,
        verbose=False,
        memory=False,
        cache=False,
        max_rpm=None,
    )
    return TicketCrew(crew=crew, context=context, task_stage_map=dict(TASK_STAGE_MAP))
