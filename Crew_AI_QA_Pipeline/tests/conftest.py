"""Shared pytest fixtures.

No test in this suite may reach a live Jira instance or a paid LLM. The
``clean_env`` autouse fixture strips every credential from the environment so
an accidental network call fails loudly instead of quietly succeeding.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
for path in (str(PROJECT_ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from jira_qa_crew.config import AppSettings, reset_settings_cache  # noqa: E402

_MANAGED_ENV = (
    "APP_NAME",
    "APP_ENV",
    "OUTPUT_DIR",
    "LOG_LEVEL",
    "DEMO_MODE",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_TEMPERATURE",
    "JIRA_INTEGRATION_MODE",
    "JIRA_URL",
    "JIRA_AUTH_MODE",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "JIRA_BEARER_TOKEN",
    "JIRA_ACCEPTANCE_CRITERIA_FIELD",
    "JIRA_INCLUDE_COMMENTS",
    "JIRA_MCP_URL",
    "JIRA_MCP_COMMAND",
    "JIRA_MCP_TRANSPORT",
    "JIRA_MCP_GET_ISSUE_TOOL",
    "JIRA_MCP_HEADERS_JSON",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "ANTHROPIC_API_KEY",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove real credentials and reset the settings cache for every test."""
    for key in _MANAGED_ENV:
        monkeypatch.delenv(key, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    """Settings wired to a temporary output directory and REST credentials."""
    return AppSettings(
        APP_NAME="Jira QA Crew",
        OUTPUT_DIR=tmp_path / "outputs",
        LLM_MODEL="openai/test-model",
        LLM_API_KEY="test-llm-key-value",
        JIRA_URL="https://example.atlassian.net",
        JIRA_EMAIL="qa@example.com",
        JIRA_API_TOKEN="ATATTtest-token-value-1234567890",
        JIRA_MAX_ATTEMPTS=2,
        JIRA_TIMEOUT_SECONDS=1.0,
    )


@pytest.fixture
def demo_settings(tmp_path: Path) -> AppSettings:
    """Settings with demo mode explicitly enabled."""
    return AppSettings(
        OUTPUT_DIR=tmp_path / "outputs",
        LLM_MODEL="openai/test-model",
        LLM_API_KEY="test-llm-key-value",
        DEMO_MODE=True,
    )


@pytest.fixture
def fixture_dir() -> Path:
    return PROJECT_ROOT / "fixtures" / "jira"
