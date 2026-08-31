"""Jira REST provider: auth, errors, retries and normalisation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from jira_qa_crew.config import AppSettings, AuthMode
from jira_qa_crew.exceptions import (
    JiraAuthError,
    JiraNotFoundError,
    JiraProviderError,
    JiraRateLimitError,
    JiraResponseError,
    JiraTimeoutError,
)
from jira_qa_crew.jira.rest_provider import JiraRestProvider
from jira_qa_crew.models import ProviderSource


class FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, *, bad_json: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self) -> Any:
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Replays a scripted list of responses or exceptions."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def payload(fixture_dir: Path) -> dict:
    return json.loads((fixture_dir / "VWO-48.json").read_text(encoding="utf-8"))


def test_fetch_normalises_a_cloud_payload(settings: AppSettings, payload: dict) -> None:
    session = FakeSession([FakeResponse(200, payload)])
    provider = JiraRestProvider(settings, session=session)

    issue = provider.fetch_issue("VWO-48")

    assert issue.key == "VWO-48"
    assert issue.source is ProviderSource.REST
    assert issue.issue_type == "Story"
    assert issue.status == "In Progress"
    assert issue.priority == "High"
    assert issue.labels == ["security", "auth", "web"]
    assert issue.components == ["Account Management"]
    assert issue.parent_key == "VWO-30"
    assert issue.subtasks == ["VWO-51"]
    assert issue.linked_issues == ["blocks VWO-60"]
    assert "15 minutes" in issue.description
    assert "set-new-password form" in issue.acceptance_criteria_raw
    assert issue.url.endswith("/browse/VWO-48")
    assert session.calls[0]["url"].endswith("/rest/api/3/issue/VWO-48")


def test_acceptance_criteria_field_can_be_configured(settings: AppSettings, payload: dict) -> None:
    settings.jira_acceptance_criteria_field = "customfield_10011"
    provider = JiraRestProvider(settings, session=FakeSession([FakeResponse(200, payload)]))
    assert "set-new-password form" in provider.fetch_issue("VWO-48").acceptance_criteria_raw


def test_comments_are_excluded_unless_enabled(settings: AppSettings, payload: dict) -> None:
    provider = JiraRestProvider(settings, session=FakeSession([FakeResponse(200, payload)]))
    assert provider.fetch_issue("VWO-48").comments == []

    settings.jira_include_comments = True
    provider = JiraRestProvider(settings, session=FakeSession([FakeResponse(200, payload)]))
    assert len(provider.fetch_issue("VWO-48").comments) == 1


def test_basic_auth_is_used_by_default(settings: AppSettings, payload: dict) -> None:
    session = FakeSession([FakeResponse(200, payload)])
    JiraRestProvider(settings, session=session).fetch_issue("VWO-48")
    assert session.calls[0]["auth"] is not None
    assert "Authorization" not in session.calls[0]["headers"]


def test_bearer_auth_sets_the_header(settings: AppSettings, payload: dict) -> None:
    settings.jira_auth_mode = AuthMode.BEARER
    settings.jira_bearer_token = "bearer-token-value"
    session = FakeSession([FakeResponse(200, payload)])

    JiraRestProvider(settings, session=session).fetch_issue("VWO-48")

    assert session.calls[0]["auth"] is None
    assert session.calls[0]["headers"]["Authorization"].startswith("Bearer ")


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_are_terminal(settings: AppSettings, status: int) -> None:
    session = FakeSession([FakeResponse(status)])
    with pytest.raises(JiraAuthError):
        JiraRestProvider(settings, session=session).fetch_issue("VWO-48")
    assert len(session.calls) == 1


def test_missing_issue_raises_not_found(settings: AppSettings) -> None:
    with pytest.raises(JiraNotFoundError):
        JiraRestProvider(settings, session=FakeSession([FakeResponse(404)])).fetch_issue("VWO-48")


def test_rate_limit_is_retried_then_reported(settings: AppSettings, monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    session = FakeSession([FakeResponse(429), FakeResponse(429)])
    with pytest.raises(JiraRateLimitError):
        JiraRestProvider(settings, session=session).fetch_issue("VWO-48")
    assert len(session.calls) == settings.jira_max_attempts


def test_transient_server_error_recovers_on_retry(
    settings: AppSettings, payload: dict, monkeypatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    session = FakeSession([FakeResponse(503), FakeResponse(200, payload)])
    issue = JiraRestProvider(settings, session=session).fetch_issue("VWO-48")
    assert issue.key == "VWO-48"
    assert len(session.calls) == 2


def test_timeouts_are_typed(settings: AppSettings, monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    session = FakeSession([requests.Timeout("slow"), requests.Timeout("slow")])
    with pytest.raises(JiraTimeoutError):
        JiraRestProvider(settings, session=session).fetch_issue("VWO-48")


def test_connection_errors_are_typed(settings: AppSettings, monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    session = FakeSession([requests.ConnectionError("dns"), requests.ConnectionError("dns")])
    with pytest.raises(JiraProviderError):
        JiraRestProvider(settings, session=session).fetch_issue("VWO-48")


def test_malformed_json_is_reported(settings: AppSettings) -> None:
    session = FakeSession([FakeResponse(200, bad_json=True)])
    with pytest.raises(JiraResponseError):
        JiraRestProvider(settings, session=session).fetch_issue("VWO-48")


def test_unusable_payload_is_reported(settings: AppSettings) -> None:
    session = FakeSession([FakeResponse(200, {"unexpected": True})])
    with pytest.raises(JiraResponseError):
        JiraRestProvider(settings, session=session).fetch_issue("VWO-48")


def test_health_check_requires_credentials(tmp_path) -> None:
    incomplete = AppSettings(JIRA_URL="https://example.atlassian.net")
    with pytest.raises(JiraAuthError):
        JiraRestProvider(incomplete).health_check()

    with pytest.raises(JiraProviderError):
        JiraRestProvider(AppSettings()).health_check()
