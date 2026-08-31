"""Deterministic provider selection and the MCP -> REST fallback."""

from __future__ import annotations

import pytest

from jira_qa_crew.config import AppSettings, IntegrationMode
from jira_qa_crew.exceptions import (
    AllProvidersFailedError,
    JiraProviderError,
    MCPUnavailableError,
)
from jira_qa_crew.jira.base import JiraProvider
from jira_qa_crew.jira.gateway import JiraGateway
from jira_qa_crew.models import JiraIssue, ProviderSource


class StubProvider(JiraProvider):
    """A provider that either returns an issue or raises."""

    def __init__(self, settings, *, source: ProviderSource, error: Exception | None = None):
        super().__init__(settings)
        self.source = source
        self.error = error
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return f"Stub {self.source.value}"

    def health_check(self) -> None:
        if self.error:
            raise self.error

    def fetch_issue(self, key: str) -> JiraIssue:
        self.calls.append(key)
        if self.error:
            raise self.error
        return JiraIssue(key=key, summary="stub", source=self.source)


@pytest.fixture
def both_configured(settings: AppSettings) -> AppSettings:
    settings.jira_mcp_url = "https://mcp.example.com"
    return settings


def _gateway(settings, mode, mcp=None, rest=None, demo=None) -> JiraGateway:
    return JiraGateway(
        settings, mode=mode, mcp_provider=mcp, rest_provider=rest, demo_provider=demo
    )


def test_auto_uses_mcp_when_it_succeeds(both_configured: AppSettings) -> None:
    mcp = StubProvider(both_configured, source=ProviderSource.MCP)
    rest = StubProvider(both_configured, source=ProviderSource.REST)

    outcome = _gateway(both_configured, IntegrationMode.AUTO, mcp, rest).fetch("VWO-48")

    assert outcome.issue.source is ProviderSource.MCP
    assert outcome.source == "MCP"
    assert rest.calls == []
    assert outcome.attempts[0].ok


def test_auto_falls_back_to_rest_when_mcp_fails(both_configured: AppSettings) -> None:
    mcp = StubProvider(
        both_configured,
        source=ProviderSource.MCP,
        error=MCPUnavailableError("server down", provider="Jira MCP"),
    )
    rest = StubProvider(both_configured, source=ProviderSource.REST)

    outcome = _gateway(both_configured, IntegrationMode.AUTO, mcp, rest).fetch("VWO-48")

    assert outcome.issue.source is ProviderSource.REST
    assert rest.calls == ["VWO-48"]
    assert outcome.attempts[0].ok is False
    assert "server down" in outcome.attempts[0].detail
    assert outcome.attempts[1].ok is True


def test_auto_skips_mcp_entirely_when_it_is_not_configured(settings: AppSettings) -> None:
    rest = StubProvider(settings, source=ProviderSource.REST)
    mcp = StubProvider(settings, source=ProviderSource.MCP)

    outcome = _gateway(settings, IntegrationMode.AUTO, mcp, rest).fetch("VWO-48")

    assert mcp.calls == []
    assert outcome.issue.source is ProviderSource.REST


def test_mcp_only_never_touches_rest(both_configured: AppSettings) -> None:
    mcp = StubProvider(
        both_configured, source=ProviderSource.MCP, error=MCPUnavailableError("no")
    )
    rest = StubProvider(both_configured, source=ProviderSource.REST)

    with pytest.raises(MCPUnavailableError):
        _gateway(both_configured, IntegrationMode.MCP, mcp, rest).fetch("VWO-48")
    assert rest.calls == []


def test_rest_only_never_touches_mcp(both_configured: AppSettings) -> None:
    mcp = StubProvider(both_configured, source=ProviderSource.MCP)
    rest = StubProvider(both_configured, source=ProviderSource.REST)

    outcome = _gateway(both_configured, IntegrationMode.REST, mcp, rest).fetch("VWO-48")

    assert mcp.calls == []
    assert outcome.issue.source is ProviderSource.REST


def test_both_providers_failing_raises_a_typed_error(both_configured: AppSettings) -> None:
    mcp = StubProvider(both_configured, source=ProviderSource.MCP, error=MCPUnavailableError("mcp bad"))
    rest = StubProvider(
        both_configured, source=ProviderSource.REST, error=JiraProviderError("rest bad")
    )

    with pytest.raises(AllProvidersFailedError) as exc:
        _gateway(both_configured, IntegrationMode.AUTO, mcp, rest).fetch("VWO-48")

    assert len(exc.value.failures) == 2
    assert "mcp bad" in str(exc.value)
    assert "rest bad" in str(exc.value)


def test_demo_fixtures_are_never_a_silent_fallback(both_configured: AppSettings) -> None:
    """With DEMO_MODE off, a total failure must fail - not serve fixtures."""
    demo = StubProvider(both_configured, source=ProviderSource.DEMO)
    mcp = StubProvider(both_configured, source=ProviderSource.MCP, error=MCPUnavailableError("x"))
    rest = StubProvider(both_configured, source=ProviderSource.REST, error=JiraProviderError("y"))

    with pytest.raises(AllProvidersFailedError):
        _gateway(both_configured, IntegrationMode.AUTO, mcp, rest, demo).fetch("VWO-48")
    assert demo.calls == []


def test_demo_mode_bypasses_live_providers_when_explicitly_enabled(
    demo_settings: AppSettings,
) -> None:
    demo = StubProvider(demo_settings, source=ProviderSource.DEMO)
    mcp = StubProvider(demo_settings, source=ProviderSource.MCP)

    outcome = _gateway(demo_settings, IntegrationMode.AUTO, mcp, None, demo).fetch("VWO-48")

    assert outcome.issue.source is ProviderSource.DEMO
    assert mcp.calls == []


def test_demo_provider_reads_the_real_fixtures(demo_settings: AppSettings, fixture_dir) -> None:
    from jira_qa_crew.jira.demo_provider import JiraDemoProvider

    provider = JiraDemoProvider(demo_settings, fixture_dir=fixture_dir)
    issue = provider.fetch_issue("VWO-48")

    assert issue.source is ProviderSource.DEMO
    assert "15 minutes" in issue.description
    assert "VWO-48" in provider.available_keys()


def test_demo_provider_reports_missing_fixtures(demo_settings: AppSettings, fixture_dir) -> None:
    from jira_qa_crew.exceptions import JiraNotFoundError
    from jira_qa_crew.jira.demo_provider import JiraDemoProvider

    with pytest.raises(JiraNotFoundError) as exc:
        JiraDemoProvider(demo_settings, fixture_dir=fixture_dir).fetch_issue("ZZZ-1")
    assert "VWO-48" in str(exc.value)


def test_health_report_summarises_configured_providers(both_configured: AppSettings) -> None:
    mcp = StubProvider(both_configured, source=ProviderSource.MCP, error=MCPUnavailableError("down"))
    rest = StubProvider(both_configured, source=ProviderSource.REST)

    report = _gateway(both_configured, IntegrationMode.AUTO, mcp, rest).health_report()

    assert report["mcp"].startswith("unavailable")
    assert report["rest"] == "ok"
