"""Jira QA Crew - Streamlit entry point.

This module is presentation only. Orchestration lives in
``jira_qa_crew.services.pipeline`` and provider logic in ``jira_qa_crew.jira``.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(SRC))

import streamlit as st  # noqa: E402

from jira_qa_crew.config import get_settings, load_environment  # noqa: E402
from jira_qa_crew.exceptions import JiraQACrewError  # noqa: E402
from jira_qa_crew.logging_utils import configure_logging, redact  # noqa: E402
from jira_qa_crew.models import STAGE_DEFINITIONS, StageStatus  # noqa: E402
from jira_qa_crew.services.pipeline import QAPipeline  # noqa: E402
from jira_qa_crew.tickets import require_keys  # noqa: E402
from jira_qa_crew.ui.components import (  # noqa: E402
    APP_TITLE,
    render_header,
    render_input_area,
    render_live_board,
)
from jira_qa_crew.ui.results import render_results  # noqa: E402
from jira_qa_crew.ui.state import (  # noqa: E402
    get_error,
    get_run,
    init_state,
    is_running,
    set_error,
    set_run,
    set_running,
)


def _configure_page() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🧪",
        layout="wide",
        initial_sidebar_state="collapsed",
    )


def _execute(pipeline: QAPipeline, keys: list[str]) -> None:
    """Run the pipeline while streaming genuine stage progress into the UI."""
    total_stages = max(1, len(keys) * len(STAGE_DEFINITIONS))
    finished = {"count": 0}
    live: dict[str, dict[str, tuple[StageStatus, str]]] = {key: {} for key in keys}
    current = {"key": keys[0]}

    st.subheader("Pipeline")
    bar = st.progress(0.0, text="Starting")
    board = st.empty()

    def on_progress(
        ticket_key: str, stage_key: str, status: StageStatus, message: str
    ) -> None:
        current["key"] = ticket_key
        previous = live.setdefault(ticket_key, {}).get(stage_key)
        live[ticket_key][stage_key] = (status, message)
        if status in (
            StageStatus.COMPLETED,
            StageStatus.WARNING,
            StageStatus.FAILED,
        ) and (previous is None or previous[0] != status):
            finished["count"] += 1
        ratio = min(1.0, finished["count"] / total_stages)
        bar.progress(ratio, text=f"{ticket_key} · {message[:80]}")
        with board.container():
            render_live_board(ticket_key, live[ticket_key])

    with st.spinner("Running the CrewAI pipeline. This calls a real LLM."):
        run = pipeline.run(keys, on_progress=on_progress)

    bar.progress(1.0, text="Finished")
    board.empty()
    set_run(run)


def main() -> None:
    """Render one pass of the application."""
    _configure_page()
    load_environment()
    settings = get_settings()
    configure_logging(settings.log_level)
    init_state()

    render_header()
    form = render_input_area(settings, disabled=is_running())

    if error := get_error():
        st.error(error)

    if form.submitted and form.parsed is not None:
        set_error("")
        set_running(True)
        try:
            keys = require_keys(form.parsed)
            pipeline = QAPipeline(settings, mode=form.mode)
            problems = pipeline.preflight()
            if problems:
                set_error(
                    "Configuration is incomplete:\n"
                    + "\n".join(f"- {item}" for item in problems)
                )
            else:
                _execute(pipeline, keys)
        except JiraQACrewError as exc:
            set_error(redact(exc))
        except Exception as exc:  # noqa: BLE001 - surfaced, never leaked raw
            set_error(f"Unexpected error: {redact(exc)}")
        finally:
            set_running(False)
        st.rerun()

    run = get_run()
    if run is not None:
        render_results(run)
    else:
        st.info(
            "Enter one or more Jira ticket ids and select an integration mode to "
            "generate a QA pack."
        )


main()
