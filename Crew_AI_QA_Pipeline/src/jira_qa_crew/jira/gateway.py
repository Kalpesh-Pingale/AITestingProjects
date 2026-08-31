"""Deterministic provider selection for Jira reads.

The gateway - not the LLM - decides which provider runs:

* ``auto``: try MCP, fall back to REST when MCP fails or returns unusable data.
* ``mcp``: MCP only.
* ``rest``: REST only.

When ``DEMO_MODE`` is enabled the demo provider replaces the live ones
entirely; it is never used as a silent fallback for a failed live call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jira_qa_crew.config import AppSettings, IntegrationMode
from jira_qa_crew.exceptions import (
    AllProvidersFailedError,
    JiraProviderError,
    MCPUnavailableError,
)
from jira_qa_crew.jira.base import JiraProvider
from jira_qa_crew.jira.demo_provider import JiraDemoProvider
from jira_qa_crew.jira.mcp_provider import JiraMCPProvider
from jira_qa_crew.jira.rest_provider import JiraRestProvider
from jira_qa_crew.logging_utils import get_logger, redact
from jira_qa_crew.models import JiraIssue

logger = get_logger(__name__)


@dataclass(slots=True)
class FetchAttempt:
    """One provider attempt, kept for the run details tab."""

    provider: str
    ok: bool
    detail: str = ""


@dataclass(slots=True)
class FetchOutcome:
    """Result of a gateway fetch, including the attempt trail."""

    issue: JiraIssue
    attempts: list[FetchAttempt] = field(default_factory=list)

    @property
    def source(self) -> str:
        return self.issue.source.value


class JiraGateway:
    """Read-only Jira access with deterministic MCP -> REST fallback."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        mode: IntegrationMode | None = None,
        mcp_provider: JiraProvider | None = None,
        rest_provider: JiraProvider | None = None,
        demo_provider: JiraProvider | None = None,
    ) -> None:
        self.settings = settings
        self.mode = mode or settings.jira_integration_mode
        self._mcp = mcp_provider
        self._rest = rest_provider
        self._demo = demo_provider

    # -- provider construction -----------------------------------------
    @property
    def mcp(self) -> JiraProvider:
        if self._mcp is None:
            self._mcp = JiraMCPProvider(self.settings)
        return self._mcp

    @property
    def rest(self) -> JiraProvider:
        if self._rest is None:
            self._rest = JiraRestProvider(self.settings)
        return self._rest

    @property
    def demo(self) -> JiraProvider:
        if self._demo is None:
            self._demo = JiraDemoProvider(self.settings)
        return self._demo

    # -- public API -----------------------------------------------------
    def fetch(self, key: str) -> FetchOutcome:
        """Fetch one issue, honouring the configured integration mode."""
        if self.settings.demo_mode:
            issue = self.demo.fetch_issue(key)
            return FetchOutcome(
                issue=issue,
                attempts=[FetchAttempt("Demo fixtures", True, "DEMO_MODE is enabled")],
            )

        if self.mode is IntegrationMode.MCP:
            return self._single(self.mcp, key)
        if self.mode is IntegrationMode.REST:
            return self._single(self.rest, key)
        return self._auto(key)

    def health_report(self) -> dict[str, str]:
        """Best-effort provider health used by the advanced settings panel."""
        report: dict[str, str] = {}
        if self.settings.demo_mode:
            report["demo"] = _health_string(self.demo)
            return report
        if self.mode in (IntegrationMode.AUTO, IntegrationMode.MCP):
            report["mcp"] = _health_string(self.mcp)
        if self.mode in (IntegrationMode.AUTO, IntegrationMode.REST):
            report["rest"] = _health_string(self.rest)
        return report

    # -- internals ------------------------------------------------------
    def _single(self, provider: JiraProvider, key: str) -> FetchOutcome:
        try:
            issue = provider.fetch_issue(key)
        except JiraProviderError as exc:
            logger.warning("%s failed for %s: %s", provider.name, key, redact(exc))
            raise
        return FetchOutcome(issue=issue, attempts=[FetchAttempt(provider.name, True)])

    def _auto(self, key: str) -> FetchOutcome:
        attempts: list[FetchAttempt] = []
        failures: dict[str, str] = {}

        if self.settings.mcp_configured():
            try:
                issue = self.mcp.fetch_issue(key)
            except JiraProviderError as exc:
                message = redact(str(exc))
                attempts.append(FetchAttempt(self.mcp.name, False, message))
                failures[self.mcp.name] = message
                logger.info("MCP failed for %s, falling back to REST: %s", key, message)
            else:
                attempts.append(FetchAttempt(self.mcp.name, True))
                return FetchOutcome(issue=issue, attempts=attempts)
        else:
            reason = "not configured"
            attempts.append(FetchAttempt("Jira MCP", False, reason))
            failures["Jira MCP"] = reason

        if self.settings.rest_configured():
            try:
                issue = self.rest.fetch_issue(key)
            except JiraProviderError as exc:
                message = redact(str(exc))
                attempts.append(FetchAttempt(self.rest.name, False, message))
                failures[self.rest.name] = message
            else:
                attempts.append(FetchAttempt(self.rest.name, True))
                return FetchOutcome(issue=issue, attempts=attempts)
        else:
            reason = "not configured"
            attempts.append(FetchAttempt("Jira REST", False, reason))
            failures["Jira REST"] = reason

        detail = "; ".join(f"{name}: {reason}" for name, reason in failures.items())
        raise AllProvidersFailedError(
            f"Could not fetch {key} from any configured provider. {detail}",
            failures=failures,
        )


def _health_string(provider: JiraProvider) -> str:
    try:
        provider.health_check()
    except MCPUnavailableError as exc:
        return f"unavailable - {redact(exc.message)}"
    except JiraProviderError as exc:
        return f"error - {redact(exc.message)}"
    except Exception as exc:  # noqa: BLE001 - health checks must not crash the UI
        return f"error - {redact(exc)}"
    return "ok"
