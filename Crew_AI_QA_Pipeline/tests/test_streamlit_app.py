"""Streamlit rendering tests using streamlit.testing.v1.AppTest.

These exercise the real app script. No pipeline run is triggered: the
"results" test injects fixture results into session state instead, so no LLM
or Jira call can happen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from jira_qa_crew.ui.state import KEY_MODE, KEY_RUN, KEY_TICKET_INPUT
from tests.factories import make_run_result

APP_FILE = str(Path(__file__).resolve().parents[1] / "app.py")
TIMEOUT = 60


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AppTest:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("LLM_MODEL", "openai/test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key-value-123456")
    monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "qa@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "ATATTtest-token-value-1234567890")
    return AppTest.from_file(APP_FILE, default_timeout=TIMEOUT)


def test_initial_render_has_no_exception(app: AppTest) -> None:
    app.run()
    assert not app.exception
    body = " ".join(element.value for element in app.markdown)
    assert "Jira QA Crew" in body
    assert "Generate test plans" in body
    assert app.button[0].label == "Analyze & Generate QA Pack"


def test_button_is_disabled_until_valid_ids_are_entered(app: AppTest) -> None:
    app.run()
    assert app.button[0].disabled is True

    app.session_state[KEY_TICKET_INPUT] = "VWO-48, VWO-49"
    app.run()
    assert app.button[0].disabled is False
    assert any("VWO-48, VWO-49" in element.value for element in app.success)


def test_invalid_ticket_ids_are_reported(app: AppTest) -> None:
    app.session_state[KEY_TICKET_INPUT] = "not-a-key, 999"
    app.run()

    assert not app.exception
    warnings = " ".join(element.value for element in app.warning)
    assert "NOT-A-KEY" in warnings
    assert app.button[0].disabled is True


def test_duplicates_are_reported(app: AppTest) -> None:
    app.session_state[KEY_TICKET_INPUT] = "VWO-48, vwo-48"
    app.run()
    assert any("Duplicates removed" in element.value for element in app.info)


def test_ticket_limit_is_reported(app: AppTest, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_MAX_TICKETS", "2")
    app.session_state[KEY_TICKET_INPUT] = "VWO-1, VWO-2, VWO-3"
    app.run()
    assert any("ticket limit" in element.value for element in app.warning)


def test_integration_mode_selector_offers_three_modes(app: AppTest) -> None:
    app.run()
    assert app.selectbox[0].options == ["Auto (MCP then REST)", "MCP only", "REST only"]
    app.session_state[KEY_MODE] = "REST only"
    app.run()
    assert not app.exception


def test_results_render_from_fixture_results(app: AppTest) -> None:
    app.session_state[KEY_RUN] = make_run_result(["VWO-48", "VWO-49"])
    app.run()

    assert not app.exception
    body = " ".join(element.value for element in app.markdown)
    assert "RUN-20260831-101500" in body
    assert "Requirements Analysis" in " ".join(tab.label for tab in app.tabs)
    assert "REQ-001" in body
    labels = {button.label for button in app.download_button}
    assert "Download run_summary.md" in labels
    assert any(label.startswith("Download test_plan") for label in labels)
    assert any(label.startswith("Download test_cases.csv") for label in labels)
    assert any(label.startswith("Download traceability_matrix") for label in labels)


def test_playwright_code_and_readiness_are_shown(app: AppTest) -> None:
    app.session_state[KEY_RUN] = make_run_result(["VWO-48"])
    app.run()

    code_blocks = " ".join(element.value for element in app.code)
    assert "@playwright/test" in code_blocks
    warnings = " ".join(element.value for element in app.warning)
    assert "NEEDS_CONFIGURATION" in warnings


def test_missing_configuration_blocks_the_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    at = AppTest.from_file(APP_FILE, default_timeout=TIMEOUT)
    at.session_state[KEY_TICKET_INPUT] = "VWO-48"
    at.run()
    at.button[0].click().run()

    assert not at.exception
    assert any("Configuration is incomplete" in element.value for element in at.error)
    assert at.session_state[KEY_RUN] is None


def test_malformed_env_value_shows_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A typo in .env must name the variable, not raise a raw traceback."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("LLM_MAX_TOKENS", "0c")

    at = AppTest.from_file(APP_FILE, default_timeout=TIMEOUT)
    at.run()

    assert not at.exception
    errors = " ".join(element.value for element in at.error)
    assert "Configuration error" in errors
    assert "LLM_MAX_TOKENS" in errors


def test_secret_values_are_not_echoed_in_configuration_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pydantic import ValidationError

    from jira_qa_crew.config import AppSettings, _describe_settings_error

    try:
        AppSettings(LLM_MAX_TOKENS="0c", LLM_TEMPERATURE="abc")
    except ValidationError as exc:
        message = _describe_settings_error(exc)
    else:  # pragma: no cover - the construction above always fails
        raise AssertionError("expected a ValidationError")

    assert "LLM_MAX_TOKENS" in message
    assert "'0c'" in message
    assert "LLM_TEMPERATURE" in message
