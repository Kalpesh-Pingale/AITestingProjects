"""Fixture backed provider used only when DEMO_MODE is explicitly enabled.

This provider is never selected as a fallback for a failed live integration.
:class:`jira_qa_crew.jira.gateway.JiraGateway` only constructs it when
``DEMO_MODE=true``, and every issue it returns is stamped with
``ProviderSource.DEMO`` so the UI and the artifacts stay honest.
"""

from __future__ import annotations

import json
from pathlib import Path

from jira_qa_crew.config import PROJECT_ROOT, AppSettings
from jira_qa_crew.exceptions import JiraNotFoundError, JiraResponseError
from jira_qa_crew.jira.base import JiraProvider, normalise_issue_payload
from jira_qa_crew.models import JiraIssue, ProviderSource

DEFAULT_FIXTURE_DIR = PROJECT_ROOT / "fixtures" / "jira"


class JiraDemoProvider(JiraProvider):
    """Serve Jira issues from local JSON fixtures."""

    source = ProviderSource.DEMO

    def __init__(self, settings: AppSettings, fixture_dir: Path | None = None) -> None:
        super().__init__(settings)
        self.fixture_dir = fixture_dir or DEFAULT_FIXTURE_DIR

    @property
    def name(self) -> str:
        return "Demo fixtures"

    def health_check(self) -> None:
        if not self.fixture_dir.is_dir():
            raise JiraResponseError(
                f"Demo fixture directory not found: {self.fixture_dir}",
                provider=self.name,
                remediation="Add JSON fixtures or disable DEMO_MODE.",
            )

    def available_keys(self) -> list[str]:
        if not self.fixture_dir.is_dir():
            return []
        return sorted(path.stem.upper() for path in self.fixture_dir.glob("*.json"))

    def fetch_issue(self, key: str) -> JiraIssue:
        self.health_check()
        path = self.fixture_dir / f"{key.upper()}.json"
        if not path.is_file():
            available = ", ".join(self.available_keys()) or "none"
            raise JiraNotFoundError(
                f"No demo fixture for {key}. Available fixtures: {available}.",
                provider=self.name,
                remediation="Add fixtures/jira/<KEY>.json or disable DEMO_MODE.",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise JiraResponseError(
                f"Demo fixture {path.name} is not valid JSON.", provider=self.name
            ) from exc
        return normalise_issue_payload(
            payload, key=key, source=self.source, settings=self.settings
        )
