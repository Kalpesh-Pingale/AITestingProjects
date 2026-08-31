"""Jira Cloud REST provider (read only).

Uses ``GET /rest/api/{version}/issue/{issueIdOrKey}``. Only GET requests are
ever issued - there is no code path in this module that can write, transition
or delete a Jira issue.
"""

from __future__ import annotations

import random
import time
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from jira_qa_crew.config import AppSettings, AuthMode
from jira_qa_crew.exceptions import (
    JiraAuthError,
    JiraNotFoundError,
    JiraProviderError,
    JiraRateLimitError,
    JiraResponseError,
    JiraTimeoutError,
)
from jira_qa_crew.jira.base import JiraProvider, normalise_issue_payload
from jira_qa_crew.logging_utils import get_logger, redact
from jira_qa_crew.models import JiraIssue, ProviderSource

logger = get_logger(__name__)

#: HTTP statuses that are worth retrying.
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class JiraRestProvider(JiraProvider):
    """Read-only Jira Cloud REST client with bounded retries."""

    source = ProviderSource.REST

    def __init__(self, settings: AppSettings, session: requests.Session | None = None) -> None:
        super().__init__(settings)
        self._session = session or requests.Session()
        self._session.headers.update(
            {"Accept": "application/json", "User-Agent": "jira-qa-crew/1.0"}
        )

    @property
    def name(self) -> str:
        return "Jira REST"

    # -- public API -----------------------------------------------------
    def health_check(self) -> None:
        settings = self.settings
        if not settings.jira_url:
            raise JiraProviderError(
                "JIRA_URL is not configured.",
                provider=self.name,
                remediation="Set JIRA_URL to https://your-domain.atlassian.net",
            )
        if not settings.rest_configured():
            missing = (
                "JIRA_BEARER_TOKEN"
                if settings.jira_auth_mode is AuthMode.BEARER
                else "JIRA_EMAIL and JIRA_API_TOKEN"
            )
            raise JiraAuthError(
                f"Jira REST credentials are incomplete: {missing} missing.",
                provider=self.name,
                remediation="Provide credentials via environment or Streamlit secrets.",
            )

    def fetch_issue(self, key: str) -> JiraIssue:
        self.health_check()
        url = (
            f"{self.settings.jira_url}/rest/api/"
            f"{self.settings.jira_api_version}/issue/{key}"
        )
        params: dict[str, str] = {"expand": "names"}
        payload = self._get_json(url, params)
        if not isinstance(payload, dict) or not (
            payload.get("fields") or payload.get("key")
        ):
            raise JiraResponseError(
                f"Jira REST returned an unusable payload for {key}.",
                provider=self.name,
                remediation="Check the API version and the issue permissions.",
            )
        payload = _apply_field_names(payload)
        return normalise_issue_payload(
            payload, key=key, source=self.source, settings=self.settings
        )

    # -- internals ------------------------------------------------------
    def _auth(self) -> HTTPBasicAuth | None:
        if self.settings.jira_auth_mode is AuthMode.BASIC:
            return HTTPBasicAuth(self.settings.jira_email, self.settings.jira_api_token)
        return None

    def _headers(self) -> dict[str, str]:
        if self.settings.jira_auth_mode is AuthMode.BEARER:
            return {"Authorization": f"Bearer {self.settings.jira_bearer_token}"}
        return {}

    def _get_json(self, url: str, params: dict[str, str]) -> Any:
        attempts = max(1, self.settings.jira_max_attempts)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    auth=self._auth(),
                    headers=self._headers(),
                    timeout=self.settings.jira_timeout_seconds,
                )
            except requests.Timeout as exc:
                last_error = JiraTimeoutError(
                    f"Jira REST timed out after {self.settings.jira_timeout_seconds}s.",
                    provider=self.name,
                    remediation="Increase JIRA_TIMEOUT_SECONDS or check connectivity.",
                )
                logger.warning("REST timeout on attempt %s: %s", attempt, redact(exc))
            except requests.RequestException as exc:
                last_error = JiraProviderError(
                    f"Jira REST connection error: {redact(exc)}",
                    provider=self.name,
                    remediation="Verify JIRA_URL and network access.",
                )
                logger.warning("REST connection error on attempt %s", attempt)
            else:
                terminal = self._raise_for_status(response)
                if terminal is None:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise JiraResponseError(
                            "Jira REST returned a response that is not valid JSON.",
                            provider=self.name,
                        ) from exc
                last_error = terminal

            if attempt < attempts:
                self._sleep_backoff(attempt)

        assert last_error is not None  # noqa: S101 - loop always sets it
        raise last_error

    def _raise_for_status(self, response: requests.Response) -> Exception | None:
        """Return a retryable error, raise a terminal one, or return ``None``."""
        status = response.status_code
        if status < 400:
            return None
        if status in (401, 403):
            raise JiraAuthError(
                f"Jira REST rejected the credentials (HTTP {status}).",
                provider=self.name,
                remediation="Check JIRA_EMAIL / JIRA_API_TOKEN and project permissions.",
            )
        if status == 404:
            raise JiraNotFoundError(
                "Issue not found or not visible to this account (HTTP 404).",
                provider=self.name,
                remediation="Verify the ticket key and the account's browse permission.",
            )
        if status == 429:
            return JiraRateLimitError(
                "Jira REST rate limited the request (HTTP 429).",
                provider=self.name,
                remediation="Retry later or reduce the ticket count.",
            )
        if status in _RETRYABLE_STATUSES:
            return JiraProviderError(
                f"Jira REST returned HTTP {status}.", provider=self.name
            )
        raise JiraProviderError(
            f"Jira REST returned HTTP {status}.",
            provider=self.name,
            remediation="Inspect the Jira instance status and the request URL.",
        )

    def _sleep_backoff(self, attempt: int) -> None:
        delay = min(8.0, (2 ** (attempt - 1))) + random.uniform(0, 0.3)  # noqa: S311
        time.sleep(delay)


def _apply_field_names(payload: dict[str, Any]) -> dict[str, Any]:
    """Add human readable aliases for custom fields using ``expand=names``.

    Jira returns ``{"names": {"customfield_10011": "Acceptance Criteria"}}``.
    Copying those into the ``fields`` map lets the acceptance-criteria
    detection work without hard-coding a custom field id.
    """
    names = payload.get("names")
    fields = payload.get("fields")
    if not isinstance(names, dict) or not isinstance(fields, dict):
        return payload
    for field_id, label in names.items():
        if not isinstance(label, str):
            continue
        alias = label.strip().lower().replace(" ", "_")
        if alias and alias not in fields and field_id in fields:
            fields[alias] = fields[field_id]
    return payload
