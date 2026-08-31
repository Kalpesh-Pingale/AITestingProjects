"""Opt-in integration tests that use real credentials.

These are deselected by default (``addopts = -m "not integration"``). Run them
deliberately, with a real ``.env`` in place:

    pytest -m integration

Each test skips itself when the configuration it needs is absent, so the
suite never fails merely because credentials are not present.
"""

from __future__ import annotations

import os

import pytest

from jira_qa_crew.config import AppSettings, IntegrationMode, load_environment
from jira_qa_crew.jira.gateway import JiraGateway
from jira_qa_crew.jira.mcp_provider import JiraMCPProvider, is_read_only_tool
from jira_qa_crew.jira.rest_provider import JiraRestProvider
from jira_qa_crew.models import ProviderSource

pytestmark = pytest.mark.integration

LIVE_KEY_ENV = "INTEGRATION_JIRA_KEY"


@pytest.fixture
def live_settings() -> AppSettings:
    load_environment()
    return AppSettings()


@pytest.fixture
def live_key() -> str:
    key = os.environ.get(LIVE_KEY_ENV, "").strip().upper()
    if not key:
        pytest.skip(f"Set {LIVE_KEY_ENV} to a readable Jira issue key.")
    return key


def test_live_rest_fetch(live_settings: AppSettings, live_key: str) -> None:
    if not live_settings.rest_configured():
        pytest.skip("Jira REST is not configured.")

    issue = JiraRestProvider(live_settings).fetch_issue(live_key)

    assert issue.key == live_key
    assert issue.source is ProviderSource.REST
    assert issue.summary


def test_live_mcp_exposes_only_read_tools_we_use(live_settings: AppSettings) -> None:
    if not live_settings.mcp_configured():
        pytest.skip("Jira MCP is not configured.")

    provider = JiraMCPProvider(live_settings)
    tools = provider.list_tools()

    assert tools, "The MCP server exposed no tools."
    selected = provider._select_tool(tools)
    assert is_read_only_tool(selected["name"])


def test_live_mcp_fetch(live_settings: AppSettings, live_key: str) -> None:
    if not live_settings.mcp_configured():
        pytest.skip("Jira MCP is not configured.")

    issue = JiraMCPProvider(live_settings).fetch_issue(live_key)

    assert issue.key.upper() == live_key
    assert issue.source is ProviderSource.MCP


def test_live_gateway_records_the_provider_that_answered(
    live_settings: AppSettings, live_key: str
) -> None:
    if not (live_settings.mcp_configured() or live_settings.rest_configured()):
        pytest.skip("No Jira provider is configured.")

    outcome = JiraGateway(live_settings, mode=IntegrationMode.AUTO).fetch(live_key)

    assert outcome.source in ("MCP", "REST")
    assert outcome.attempts
