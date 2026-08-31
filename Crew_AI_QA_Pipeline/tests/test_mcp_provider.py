"""Jira MCP provider: tool discovery, read-only enforcement, payload parsing."""

from __future__ import annotations

from typing import Any

import pytest

from jira_qa_crew.config import AppSettings, MCPTransport
from jira_qa_crew.exceptions import (
    JiraNotFoundError,
    JiraResponseError,
    MCPUnavailableError,
)
from jira_qa_crew.jira.mcp_provider import (
    JiraMCPProvider,
    _extract_issue_payload,
    is_read_only_tool,
)


class Block:
    def __init__(self, text: str) -> None:
        self.text = text


class Result:
    def __init__(self, *, text: str = "", structured: Any = None, is_error: bool = False) -> None:
        self.content = [Block(text)] if text else []
        self.structuredContent = structured  # noqa: N815 - mirrors the MCP SDK
        self.isError = is_error  # noqa: N815 - mirrors the MCP SDK


@pytest.fixture
def mcp_settings(tmp_path) -> AppSettings:
    return AppSettings(
        OUTPUT_DIR=tmp_path,
        JIRA_MCP_URL="https://mcp.example.com/jira",
        JIRA_MCP_TRANSPORT=MCPTransport.STREAMABLE_HTTP,
        JIRA_URL="https://example.atlassian.net",
    )


# -- read-only enforcement -------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["jira_get_issue", "getJiraIssue", "search_issues", "read_issue", "list_projects"],
)
def test_read_only_tools_are_allowed(name: str) -> None:
    assert is_read_only_tool(name)


@pytest.mark.parametrize(
    "name",
    [
        "jira_create_issue",
        "update_issue",
        "delete_issue",
        "transition_issue",
        "add_comment",
        "assign_issue",
        "admin_reindex",
    ],
)
def test_write_tools_are_refused(name: str) -> None:
    assert not is_read_only_tool(name)


# -- tool selection --------------------------------------------------------


def _tool(name: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": "",
        "input_schema": {"properties": properties or {}},
    }


def test_auto_discovers_a_get_issue_tool(mcp_settings: AppSettings) -> None:
    provider = JiraMCPProvider(mcp_settings)
    tools = [_tool("jira_search"), _tool("jira_get_issue", {"issueIdOrKey": {}})]
    assert provider._select_tool(tools)["name"] == "jira_get_issue"


def test_auto_discovery_skips_write_tools(mcp_settings: AppSettings) -> None:
    provider = JiraMCPProvider(mcp_settings)
    tools = [_tool("jira_update_issue"), _tool("atlassian_get_jira_issue", {"key": {}})]
    assert provider._select_tool(tools)["name"] == "atlassian_get_jira_issue"


def test_configured_tool_must_exist(mcp_settings: AppSettings) -> None:
    mcp_settings.jira_mcp_get_issue_tool = "not_there"
    provider = JiraMCPProvider(mcp_settings)
    with pytest.raises(MCPUnavailableError) as exc:
        provider._select_tool([_tool("jira_get_issue")])
    assert "not exposed" in str(exc.value)


def test_configured_write_tool_is_refused(mcp_settings: AppSettings) -> None:
    mcp_settings.jira_mcp_get_issue_tool = "jira_delete_issue"
    provider = JiraMCPProvider(mcp_settings)
    with pytest.raises(MCPUnavailableError):
        provider._select_tool([_tool("jira_delete_issue")])


def test_missing_get_issue_tool_is_actionable(mcp_settings: AppSettings) -> None:
    provider = JiraMCPProvider(mcp_settings)
    with pytest.raises(MCPUnavailableError) as exc:
        provider._select_tool([_tool("jira_search_boards")])
    assert "JIRA_MCP_GET_ISSUE_TOOL" in str(exc.value)


# -- argument mapping ------------------------------------------------------


def test_argument_mapping_prefers_the_schema(mcp_settings: AppSettings) -> None:
    provider = JiraMCPProvider(mcp_settings)
    assert provider._select_argument(_tool("t", {"issue_key": {}})) == "issue_key"
    assert provider._select_argument(_tool("t", {"issueIdOrKey": {}})) == "issueIdOrKey"


def test_configured_argument_wins_when_present(mcp_settings: AppSettings) -> None:
    mcp_settings.jira_mcp_issue_key_arg = "ticket"
    provider = JiraMCPProvider(mcp_settings)
    assert provider._select_argument(_tool("t", {"ticket": {}, "key": {}})) == "ticket"


def test_argument_falls_back_to_configuration_without_a_schema(
    mcp_settings: AppSettings,
) -> None:
    mcp_settings.jira_mcp_issue_key_arg = "issueKey"
    provider = JiraMCPProvider(mcp_settings)
    assert provider._select_argument({"name": "t", "input_schema": {}}) == "issueKey"


# -- payload extraction ----------------------------------------------------


def test_extracts_structured_content() -> None:
    result = Result(structured={"key": "VWO-48", "fields": {"summary": "s"}})
    assert _extract_issue_payload(result, key="VWO-48", provider="mcp")["key"] == "VWO-48"


def test_extracts_json_text_content() -> None:
    result = Result(text='{"key": "VWO-48", "fields": {"summary": "s"}}')
    assert _extract_issue_payload(result, key="VWO-48", provider="mcp")["key"] == "VWO-48"


def test_unwraps_common_response_envelopes() -> None:
    result = Result(structured={"data": {"issue": {"key": "VWO-48", "fields": {}}}})
    assert _extract_issue_payload(result, key="VWO-48", provider="mcp")["key"] == "VWO-48"


def test_prose_about_the_right_ticket_is_kept_as_a_description() -> None:
    result = Result(text="VWO-48 is about password reset link expiry.")
    payload = _extract_issue_payload(result, key="VWO-48", provider="mcp")
    assert "password reset" in payload["fields"]["description"]


def test_prose_about_another_ticket_is_rejected() -> None:
    with pytest.raises(JiraResponseError):
        _extract_issue_payload(Result(text="Some unrelated prose"), key="VWO-48", provider="mcp")


def test_empty_result_is_rejected() -> None:
    with pytest.raises(JiraResponseError):
        _extract_issue_payload(Result(), key="VWO-48", provider="mcp")


def test_tool_errors_are_mapped_to_typed_exceptions() -> None:
    with pytest.raises(JiraNotFoundError):
        _extract_issue_payload(
            Result(text="Issue not found", is_error=True), key="VWO-48", provider="mcp"
        )
    with pytest.raises(JiraResponseError):
        _extract_issue_payload(
            Result(text="upstream exploded", is_error=True), key="VWO-48", provider="mcp"
        )


# -- configuration ---------------------------------------------------------


def test_health_check_requires_configuration(tmp_path) -> None:
    provider = JiraMCPProvider(AppSettings(OUTPUT_DIR=tmp_path))
    with pytest.raises(MCPUnavailableError) as exc:
        provider.health_check()
    assert "JIRA_MCP_URL" in str(exc.value)


def test_stdio_transport_requires_a_command(tmp_path) -> None:
    settings = AppSettings(OUTPUT_DIR=tmp_path, JIRA_MCP_TRANSPORT=MCPTransport.STDIO)
    assert not settings.mcp_configured()
    settings.jira_mcp_command = "npx"
    assert settings.mcp_configured()


def test_failures_inside_the_worker_are_wrapped(mcp_settings: AppSettings) -> None:
    provider = JiraMCPProvider(mcp_settings)

    async def boom() -> None:
        raise RuntimeError("transport exploded")

    with pytest.raises(MCPUnavailableError) as exc:
        provider._run(boom())
    assert "transport exploded" in str(exc.value)
