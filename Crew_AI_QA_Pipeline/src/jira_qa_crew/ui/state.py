"""Streamlit session state helpers.

All mutable UI state lives behind these accessors so that a rerun (which
Streamlit triggers on every widget interaction) never loses a completed run.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from jira_qa_crew.models import RunResult

KEY_RUN = "jqc_run_result"
KEY_RUNNING = "jqc_running"
KEY_TICKET_INPUT = "jqc_ticket_input"
KEY_MODE = "jqc_integration_mode"
KEY_LAST_ERROR = "jqc_last_error"
KEY_ZIP_CACHE = "jqc_zip_cache"


def init_state() -> None:
    """Create every session key once, with a safe default."""
    defaults: dict[str, Any] = {
        KEY_RUN: None,
        KEY_RUNNING: False,
        KEY_TICKET_INPUT: "",
        KEY_MODE: "Auto (MCP then REST)",
        KEY_LAST_ERROR: "",
        KEY_ZIP_CACHE: {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_run() -> RunResult | None:
    """The most recent completed or in-progress run."""
    return st.session_state.get(KEY_RUN)


def set_run(run: RunResult | None) -> None:
    st.session_state[KEY_RUN] = run
    st.session_state[KEY_ZIP_CACHE] = {}


def is_running() -> bool:
    return bool(st.session_state.get(KEY_RUNNING))


def set_running(value: bool) -> None:
    st.session_state[KEY_RUNNING] = value


def set_error(message: str) -> None:
    st.session_state[KEY_LAST_ERROR] = message


def get_error() -> str:
    return str(st.session_state.get(KEY_LAST_ERROR) or "")


def cache_zip(key: str, data: bytes) -> None:
    """Cache generated ZIP bytes so a rerun does not rebuild them."""
    cache = st.session_state.setdefault(KEY_ZIP_CACHE, {})
    cache[key] = data


def cached_zip(key: str) -> bytes | None:
    return st.session_state.get(KEY_ZIP_CACHE, {}).get(key)
