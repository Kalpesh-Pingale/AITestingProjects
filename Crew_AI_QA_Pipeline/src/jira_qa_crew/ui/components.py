"""Reusable Streamlit components: header, input form, readiness and progress."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from jira_qa_crew.config import AppSettings, IntegrationMode
from jira_qa_crew.models import (
    STAGE_DEFINITIONS,
    RunResult,
    StageStatus,
    TicketResult,
    TicketStatus,
)
from jira_qa_crew.tickets import TicketInput, parse_ticket_input

APP_TITLE = "Jira QA Crew"
APP_SUBTITLE = (
    "Generate test plans, test cases, traceability, and Playwright automation "
    "directly from Jira."
)

MODE_LABELS: dict[str, IntegrationMode] = {
    "Auto (MCP then REST)": IntegrationMode.AUTO,
    "MCP only": IntegrationMode.MCP,
    "REST only": IntegrationMode.REST,
}

_STAGE_ICONS: dict[StageStatus, str] = {
    StageStatus.PENDING: "○",
    StageStatus.RUNNING: "◐",
    StageStatus.COMPLETED: "●",
    StageStatus.WARNING: "▲",
    StageStatus.FAILED: "✕",
}

_STAGE_CLASSES: dict[StageStatus, str] = {
    StageStatus.PENDING: "pending",
    StageStatus.RUNNING: "running",
    StageStatus.COMPLETED: "done",
    StageStatus.WARNING: "warn",
    StageStatus.FAILED: "fail",
}

CSS = """
<style>
:root {
  --jqc-blue: #1264d4;
  --jqc-blue-dark: #0b3d85;
  --jqc-ink: #0f1c2e;
}
.jqc-header {
  border-left: 6px solid var(--jqc-blue);
  padding: 0.4rem 0 0.4rem 1rem;
  margin-bottom: 0.75rem;
}
.jqc-header h1 { margin: 0; font-size: 2rem; color: var(--jqc-blue-dark); }
.jqc-header p { margin: 0.25rem 0 0; color: #5a6b80; font-size: 1rem; }
.jqc-badge {
  display: inline-block; padding: 2px 10px; border-radius: 12px;
  font-size: 0.75rem; font-weight: 600; letter-spacing: 0.02em;
  border: 1px solid transparent;
}
.jqc-badge.mcp  { background: #e3f0ff; color: #0b3d85; border-color: #b9d6ff; }
.jqc-badge.rest { background: #eef3f8; color: #34495e; border-color: #cfdbe6; }
.jqc-badge.demo { background: #fff4e0; color: #8a5a00; border-color: #ffd894; }
.jqc-badge.ok   { background: #e6f6ec; color: #1c6b3c; border-color: #bde5cb; }
.jqc-badge.warn { background: #fff6e0; color: #8a6100; border-color: #ffe0a3; }
.jqc-badge.fail { background: #fdecec; color: #a01b1b; border-color: #f5c2c2; }
.jqc-stage {
  border: 1px solid #dfe6ee; border-radius: 8px; padding: 0.6rem 0.75rem;
  background: #ffffff; min-height: 92px;
}
.jqc-stage .name { font-weight: 600; color: var(--jqc-ink); font-size: 0.9rem; }
.jqc-stage .msg  { color: #5a6b80; font-size: 0.78rem; margin-top: 0.3rem;
                   word-break: break-word; }
.jqc-stage.running { border-color: var(--jqc-blue); background: #f5f9ff; }
.jqc-stage.done    { border-color: #9fd6b4; background: #f4fbf7; }
.jqc-stage.warn    { border-color: #ffd894; background: #fffaf0; }
.jqc-stage.fail    { border-color: #f0b4b4; background: #fdf5f5; }
.jqc-metric { font-size: 0.8rem; color: #5a6b80; }
</style>
"""


def render_header() -> None:
    """Application title block."""
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="jqc-header"><h1>{APP_TITLE}</h1><p>{APP_SUBTITLE}</p></div>',
        unsafe_allow_html=True,
    )


def render_readiness(settings: AppSettings) -> None:
    """Redacted configuration readiness indicators."""
    items = settings.readiness()
    columns = st.columns(len(items))
    for column, item in zip(columns, items.values(), strict=True):
        with column:
            state = "ok" if item.ready else "warn"
            label = "ready" if item.ready else "not configured"
            st.markdown(
                f'<span class="jqc-badge {state}">{item.name}: {label}</span>',
                unsafe_allow_html=True,
            )
            st.caption(item.detail)


@dataclass(slots=True)
class InputResult:
    """What the input form produced on this rerun."""

    submitted: bool
    parsed: TicketInput | None
    mode: IntegrationMode


def render_input_area(settings: AppSettings, disabled: bool = False) -> InputResult:
    """Ticket input, mode selector and advanced settings."""
    from jira_qa_crew.ui.state import KEY_MODE, KEY_TICKET_INPUT

    left, right = st.columns([3, 1])
    with left:
        raw = st.text_area(
            "Jira ticket IDs",
            key=KEY_TICKET_INPUT,
            height=120,
            placeholder="VWO-48\nVWO-49, VWO-50",
            help="Separate ids with commas, semicolons, spaces or new lines.",
            disabled=disabled,
        )
    with right:
        selected_mode = st.selectbox(
            "Integration mode",
            list(MODE_LABELS),
            key=KEY_MODE,
            disabled=disabled,
            help="Auto tries Jira MCP first and falls back to the REST API.",
        )
        st.caption(f"Ticket limit: {settings.pipeline_max_tickets}")

    parsed: TicketInput | None = None
    if raw.strip():
        try:
            parsed = parse_ticket_input(
                raw,
                pattern=settings.jira_key_pattern,
                max_tickets=settings.pipeline_max_tickets,
                max_chars=settings.pipeline_max_input_chars,
            )
        except Exception as exc:  # noqa: BLE001 - shown to the user
            st.error(str(exc))
            parsed = None
        else:
            if parsed.keys:
                st.success(f"Tickets to process: {', '.join(parsed.keys)}")
            if parsed.duplicates:
                st.info(f"Duplicates removed: {', '.join(parsed.duplicates)}")
            if parsed.invalid:
                st.warning(f"Ignored invalid ids: {', '.join(parsed.invalid)}")
            if parsed.truncated:
                st.warning(
                    "Dropped by the ticket limit: " + ", ".join(parsed.truncated)
                )

    with st.expander("Advanced settings and configuration status", expanded=False):
        render_readiness(settings)
        st.divider()
        st.markdown(
            f"""
- **Output directory:** `{settings.output_path}`
- **LLM model:** `{settings.llm_model or 'not set'}` at temperature
  `{settings.llm_temperature}`
- **Jira API version:** `{settings.jira_api_version}`
- **Acceptance criteria field:** `{settings.jira_acceptance_criteria_field or 'auto-detect'}`
- **MCP transport:** `{settings.jira_mcp_transport.value}`
- **MCP issue tool:** `{settings.jira_mcp_get_issue_tool or 'auto-discover'}`
- **Ticket timeout:** `{settings.pipeline_ticket_timeout_seconds}s`
- **Include comments:** `{settings.jira_include_comments}`
            """.strip()
        )
        st.caption(
            "Secrets are loaded from environment variables or Streamlit secrets "
            "and are never displayed here."
        )
        if settings.demo_mode:
            st.warning(
                "DEMO MODE is enabled. Tickets are read from local fixtures, not "
                "from Jira. Disable DEMO_MODE for live runs."
            )

    submitted = st.button(
        "Analyze & Generate QA Pack",
        type="primary",
        disabled=disabled or not (parsed and parsed.keys),
        use_container_width=False,
    )
    return InputResult(
        submitted=submitted,
        parsed=parsed,
        mode=MODE_LABELS.get(selected_mode, IntegrationMode.AUTO),
    )


def provider_badge(ticket: TicketResult) -> str:
    """HTML badge naming the provider that answered for a ticket."""
    if ticket.provider_source is None:
        return '<span class="jqc-badge rest">Source: none</span>'
    value = ticket.provider_source.value
    css = {"MCP": "mcp", "REST": "rest", "DEMO": "demo"}.get(value, "rest")
    return f'<span class="jqc-badge {css}">Source: {value}</span>'


def status_badge(status: TicketStatus) -> str:
    """HTML badge for a ticket outcome."""
    css = {
        TicketStatus.COMPLETED: "ok",
        TicketStatus.COMPLETED_WITH_WARNINGS: "warn",
        TicketStatus.FAILED: "fail",
    }[status]
    return f'<span class="jqc-badge {css}">{status.value.replace("_", " ").title()}</span>'


def render_stage_board(ticket: TicketResult) -> None:
    """The four agent stages with their real state and activity message."""
    columns = st.columns(len(STAGE_DEFINITIONS))
    for column, (key, label) in zip(columns, STAGE_DEFINITIONS, strict=True):
        stage = ticket.stage(key)
        status = stage.status if stage else StageStatus.PENDING
        message = (stage.message if stage else "") or status.value.title()
        duration = stage.duration_seconds if stage else None
        suffix = f" · {duration}s" if duration is not None else ""
        with column:
            st.markdown(
                f'<div class="jqc-stage {_STAGE_CLASSES[status]}">'
                f'<div class="name">{_STAGE_ICONS[status]} {label}</div>'
                f'<div class="msg">{_escape(message)}{suffix}</div></div>',
                unsafe_allow_html=True,
            )


def render_live_board(
    ticket_key: str, stages: dict[str, tuple[StageStatus, str]]
) -> None:
    """Render the stage board from live progress events during a run."""
    st.markdown(f"**Current ticket:** `{ticket_key}`")
    columns = st.columns(len(STAGE_DEFINITIONS))
    for column, (key, label) in zip(columns, STAGE_DEFINITIONS, strict=True):
        status, message = stages.get(key, (StageStatus.PENDING, "Pending"))
        with column:
            st.markdown(
                f'<div class="jqc-stage {_STAGE_CLASSES[status]}">'
                f'<div class="name">{_STAGE_ICONS[status]} {label}</div>'
                f'<div class="msg">{_escape(message)}</div></div>',
                unsafe_allow_html=True,
            )


def render_run_header(run: RunResult) -> None:
    """Run level counters and identity."""
    st.markdown(f"**Run ID:** `{run.run_id}`")
    columns = st.columns(5)
    columns[0].metric("Tickets", len(run.tickets))
    columns[1].metric("Completed", len(run.completed))
    columns[2].metric("With warnings", len(run.completed_with_warnings))
    columns[3].metric("Failed", len(run.failed))
    columns[4].metric("Mode", run.integration_mode.upper())
    if run.demo_mode:
        st.warning("This run used DEMO MODE fixtures, not live Jira data.")


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
