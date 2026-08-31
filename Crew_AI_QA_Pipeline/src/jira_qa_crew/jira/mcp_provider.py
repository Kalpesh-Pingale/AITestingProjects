"""Jira MCP provider (read only).

A contained MCP client is used rather than handing raw MCP tools to the LLM.
The application - not the model - decides which provider runs, which tool is
called and which arguments are sent, which is what makes the MCP -> REST
fallback deterministic.

Supported transports: streamable HTTP, SSE and stdio. Tool discovery is
configurable because Jira MCP servers do not agree on tool names or input
schemas.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import re
from contextlib import AsyncExitStack
from typing import Any

from jira_qa_crew.config import AppSettings, MCPTransport
from jira_qa_crew.exceptions import (
    JiraNotFoundError,
    JiraResponseError,
    JiraTimeoutError,
    MCPUnavailableError,
)
from jira_qa_crew.jira.base import JiraProvider, normalise_issue_payload
from jira_qa_crew.logging_utils import get_logger, redact
from jira_qa_crew.models import JiraIssue, ProviderSource

logger = get_logger(__name__)

#: Ordered candidates for the "fetch one issue" tool, most specific first.
GET_ISSUE_TOOL_CANDIDATES: tuple[str, ...] = (
    "jira_get_issue",
    "getjiraissue",
    "get_jira_issue",
    "atlassian_get_jira_issue",
    "get_issue",
    "getissue",
    "jira_issue",
    "read_issue",
    "fetch_issue",
)

#: Argument names commonly used for the issue key.
ISSUE_KEY_ARG_CANDIDATES: tuple[str, ...] = (
    "issueIdOrKey",
    "issue_id_or_key",
    "issueKey",
    "issue_key",
    "issueId",
    "issue",
    "key",
    "id",
    "ticket",
)

#: Any tool whose name matches this is refused, whatever the server offers.
_WRITE_TOOL_RE = re.compile(
    r"(create|update|delete|remove|edit|write|transition|assign|move|rank|"
    r"add_|set_|post_|put_|patch_|archive|clone|attach|upload|comment_on|"
    r"admin|execute|run_)",
    re.IGNORECASE,
)


def is_read_only_tool(name: str) -> bool:
    """True when a tool name is safe to call from this application."""
    lowered = (name or "").strip().lower()
    if not lowered:
        return False
    return not _WRITE_TOOL_RE.search(lowered)


class JiraMCPProvider(JiraProvider):
    """Fetch Jira issues through an MCP server, read only."""

    source = ProviderSource.MCP

    def __init__(self, settings: AppSettings) -> None:
        super().__init__(settings)
        self._resolved_tool: str | None = None
        self._resolved_arg: str | None = None

    @property
    def name(self) -> str:
        return "Jira MCP"

    # -- public API -----------------------------------------------------
    def health_check(self) -> None:
        settings = self.settings
        if not settings.mcp_configured():
            target = (
                "JIRA_MCP_COMMAND"
                if settings.jira_mcp_transport is MCPTransport.STDIO
                else "JIRA_MCP_URL"
            )
            raise MCPUnavailableError(
                f"Jira MCP is not configured ({target} is empty).",
                provider=self.name,
                remediation=f"Set {target} or use JIRA_INTEGRATION_MODE=rest.",
            )
        tools = self.list_tools()
        if not tools:
            raise MCPUnavailableError(
                "The Jira MCP server exposed no tools.",
                provider=self.name,
                remediation="Verify the MCP server URL, auth headers and scopes.",
            )

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the server tool list as plain dictionaries."""
        return self._run(self._list_tools_async())

    def fetch_issue(self, key: str) -> JiraIssue:
        payload = self._run(self._fetch_issue_async(key))
        return normalise_issue_payload(
            payload, key=key, source=self.source, settings=self.settings
        )

    # -- async plumbing -------------------------------------------------
    def _run(self, coro: Any) -> Any:
        """Run an MCP coroutine on a private event loop with a hard timeout.

        A dedicated worker thread keeps the MCP client isolated from the
        Streamlit script thread, which may or may not already own a loop.
        """
        timeout = max(1.0, self.settings.jira_mcp_timeout_seconds)

        def runner() -> Any:
            return asyncio.run(asyncio.wait_for(coro, timeout=timeout))

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(runner)
            try:
                return future.result(timeout=timeout + 15)
            except concurrent.futures.TimeoutError as exc:
                raise JiraTimeoutError(
                    f"Jira MCP call exceeded {timeout}s.",
                    provider=self.name,
                    remediation="Increase JIRA_MCP_TIMEOUT_SECONDS or check the server.",
                ) from exc
            except TimeoutError as exc:
                raise JiraTimeoutError(
                    f"Jira MCP call exceeded {timeout}s.",
                    provider=self.name,
                    remediation="Increase JIRA_MCP_TIMEOUT_SECONDS or check the server.",
                ) from exc
            except (MCPUnavailableError, JiraNotFoundError, JiraResponseError):
                raise
            except Exception as exc:  # noqa: BLE001 - surfaced as a typed error
                raise MCPUnavailableError(
                    f"Jira MCP call failed: {redact(exc)}",
                    provider=self.name,
                    remediation="Check the MCP transport, URL, headers and server logs.",
                ) from exc

    async def _session(self, stack: AsyncExitStack) -> Any:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        settings = self.settings
        transport = settings.jira_mcp_transport

        if transport is MCPTransport.STDIO:
            params = StdioServerParameters(
                command=settings.jira_mcp_command,
                args=settings.mcp_args,
                env=settings.mcp_env or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        elif transport is MCPTransport.SSE:
            from mcp.client.sse import sse_client

            read, write = await stack.enter_async_context(
                sse_client(
                    settings.jira_mcp_url,
                    headers=settings.mcp_headers or None,
                    timeout=settings.jira_mcp_timeout_seconds,
                )
            )
        else:
            from mcp.client.streamable_http import streamablehttp_client

            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(
                    settings.jira_mcp_url,
                    headers=settings.mcp_headers or None,
                    timeout=settings.jira_mcp_timeout_seconds,
                )
            )

        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def _list_tools_async(self) -> list[dict[str, Any]]:
        async with AsyncExitStack() as stack:
            session = await self._session(stack)
            listing = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": getattr(tool, "inputSchema", None) or {},
                }
                for tool in listing.tools
            ]
        return []  # pragma: no cover - defensive

    async def _fetch_issue_async(self, key: str) -> dict[str, Any]:
        async with AsyncExitStack() as stack:
            session = await self._session(stack)
            listing = await session.list_tools()
            tools = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": getattr(tool, "inputSchema", None) or {},
                }
                for tool in listing.tools
            ]
            tool = self._select_tool(tools)
            arg_name = self._select_argument(tool)
            arguments: dict[str, Any] = {arg_name: key}
            arguments.update(self.settings.mcp_extra_args)
            self._resolved_tool = tool["name"]
            self._resolved_arg = arg_name
            logger.info("Calling MCP tool %s for %s", tool["name"], key)
            result = await session.call_tool(tool["name"], arguments)
            return _extract_issue_payload(result, key=key, provider=self.name)
        raise MCPUnavailableError(  # pragma: no cover - defensive
            "Jira MCP session closed unexpectedly.", provider=self.name
        )

    # -- discovery ------------------------------------------------------
    def _select_tool(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        configured = self.settings.jira_mcp_get_issue_tool.strip()
        by_name = {tool["name"].lower(): tool for tool in tools}

        if configured:
            tool = by_name.get(configured.lower())
            if tool is None:
                available = ", ".join(sorted(by_name)) or "none"
                raise MCPUnavailableError(
                    f"Configured MCP tool '{configured}' is not exposed by the "
                    f"server. Available: {available}.",
                    provider=self.name,
                    remediation="Fix JIRA_MCP_GET_ISSUE_TOOL.",
                )
            if not is_read_only_tool(tool["name"]):
                raise MCPUnavailableError(
                    f"Configured MCP tool '{configured}' looks like a write tool "
                    "and was refused.",
                    provider=self.name,
                    remediation="Point JIRA_MCP_GET_ISSUE_TOOL at a read-only tool.",
                )
            return tool

        readable = [tool for tool in tools if is_read_only_tool(tool["name"])]
        normalised = {
            tool["name"].lower().replace("-", "_").replace(" ", "_"): tool
            for tool in readable
        }
        for candidate in GET_ISSUE_TOOL_CANDIDATES:
            for name, tool in normalised.items():
                if candidate in name:
                    return tool
        raise MCPUnavailableError(
            "Could not identify a read-only 'get issue' tool on the MCP server. "
            f"Read-only tools seen: {', '.join(sorted(normalised)) or 'none'}.",
            provider=self.name,
            remediation="Set JIRA_MCP_GET_ISSUE_TOOL explicitly.",
        )

    def _select_argument(self, tool: dict[str, Any]) -> str:
        schema = tool.get("input_schema") or {}
        properties = schema.get("properties") if isinstance(schema, dict) else None
        configured = self.settings.jira_mcp_issue_key_arg.strip()

        if isinstance(properties, dict) and properties:
            if configured and configured in properties:
                return configured
            for candidate in ISSUE_KEY_ARG_CANDIDATES:
                if candidate in properties:
                    return candidate
            lowered = {name.lower(): name for name in properties}
            for candidate in ISSUE_KEY_ARG_CANDIDATES:
                if candidate.lower() in lowered:
                    return lowered[candidate.lower()]
            required = schema.get("required")
            if isinstance(required, list) and required:
                return str(required[0])
            return next(iter(properties))
        return configured or "issueIdOrKey"


def _extract_issue_payload(result: Any, *, key: str, provider: str) -> dict[str, Any]:
    """Pull a Jira issue dict out of an MCP ``CallToolResult``."""
    if getattr(result, "isError", False):
        text = _result_text(result)
        if "not found" in text.lower() or "404" in text:
            raise JiraNotFoundError(
                f"MCP server reported that {key} was not found.", provider=provider
            )
        raise JiraResponseError(
            f"MCP tool returned an error for {key}: {redact(text)[:400]}",
            provider=provider,
        )

    structured = getattr(result, "structuredContent", None)
    candidates: list[Any] = []
    if isinstance(structured, dict):
        candidates.append(structured)

    text = _result_text(result)
    if text:
        with contextlib.suppress(ValueError, TypeError):
            candidates.append(json.loads(text))

    for candidate in candidates:
        issue = _coerce_issue_dict(candidate, key)
        if issue is not None:
            return issue

    if text.strip():
        # The server returned prose. Keep it as a description so the run can
        # continue, but only when it plausibly describes the requested issue.
        if key.lower() in text.lower():
            return {"key": key, "fields": {"summary": "", "description": text}}
        raise JiraResponseError(
            f"MCP tool returned text that does not reference {key}.",
            provider=provider,
            remediation="Check JIRA_MCP_GET_ISSUE_TOOL and its argument mapping.",
        )

    raise JiraResponseError(
        f"MCP tool returned an empty response for {key}.", provider=provider
    )


def _coerce_issue_dict(candidate: Any, key: str) -> dict[str, Any] | None:
    """Find the issue object inside common MCP response wrappers."""
    if not isinstance(candidate, dict):
        return None
    if candidate.get("fields") or candidate.get("summary") or candidate.get("key"):
        return candidate
    for wrapper in ("issue", "data", "result", "value", "content"):
        inner = candidate.get(wrapper)
        if isinstance(inner, dict):
            found = _coerce_issue_dict(inner, key)
            if found is not None:
                return found
        if isinstance(inner, list):
            for item in inner:
                found = _coerce_issue_dict(item, key)
                if found is not None:
                    return found
    return None


def _result_text(result: Any) -> str:
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)
