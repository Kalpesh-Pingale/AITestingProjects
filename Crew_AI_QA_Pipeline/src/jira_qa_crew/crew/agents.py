"""CrewAI agent construction.

Only the Jira Analyst is given Jira access; the downstream agents work from
the validated output of the previous stage.
"""

from __future__ import annotations

from crewai import LLM, Agent
from crewai.tools import BaseTool

from jira_qa_crew.prompts import agent_spec


def _agent(key: str, llm: LLM, ticket_key: str, tools: list[BaseTool] | None = None) -> Agent:
    spec = agent_spec(key, ticket_key=ticket_key)
    return Agent(
        role=spec["role"],
        goal=spec["goal"],
        backstory=spec["backstory"],
        llm=llm,
        tools=tools or [],
        allow_delegation=False,
        allow_code_execution=False,
        max_iter=12,
        verbose=False,
        inject_date=False,
        respect_context_window=True,
        max_retry_limit=1,
    )


def build_jira_analyst(llm: LLM, ticket_key: str, jira_tool: BaseTool) -> Agent:
    """Stage 1 agent. The only agent that can read Jira."""
    return _agent("jira_analyst", llm, ticket_key, tools=[jira_tool])


def build_test_plan_writer(llm: LLM, ticket_key: str) -> Agent:
    """Stage 2 agent."""
    return _agent("test_plan_writer", llm, ticket_key)


def build_test_case_writer(llm: LLM, ticket_key: str) -> Agent:
    """Stage 3 agent."""
    return _agent("test_case_writer", llm, ticket_key)


def build_playwright_coder(llm: LLM, ticket_key: str) -> Agent:
    """Stage 4 agent."""
    return _agent("playwright_coder", llm, ticket_key)
