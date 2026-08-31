"""Results rendering: one tab per ticket, six tabs inside each ticket."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from jira_qa_crew.exceptions import ArtifactError
from jira_qa_crew.models import (
    AutomationReadiness,
    RunResult,
    TicketResult,
    TicketStatus,
)
from jira_qa_crew.services.artifacts import build_run_zip, build_ticket_zip
from jira_qa_crew.services.renderers import (
    render_playwright_markdown,
    render_requirements_markdown,
    render_run_summary_markdown,
    render_test_cases_csv,
    render_test_cases_markdown,
    render_test_plan_markdown,
    render_traceability_csv,
    run_manifest,
    test_case_rows,
    ticket_manifest,
)
from jira_qa_crew.ui.components import (
    provider_badge,
    render_run_header,
    render_stage_board,
    status_badge,
)
from jira_qa_crew.ui.state import cache_zip, cached_zip


def render_results(run: RunResult) -> None:
    """Render the whole results area for a finished run."""
    st.subheader("Results")
    render_run_header(run)
    _render_run_downloads(run)
    st.divider()

    if not run.tickets:
        st.info("No tickets were processed.")
        return

    labels = [f"{t.ticket_key} · {_short_status(t.status)}" for t in run.tickets]
    for tab, ticket in zip(st.tabs(labels), run.tickets, strict=True):
        with tab:
            _render_ticket(ticket, run)


def _short_status(status: TicketStatus) -> str:
    return {
        TicketStatus.COMPLETED: "ok",
        TicketStatus.COMPLETED_WITH_WARNINGS: "warnings",
        TicketStatus.FAILED: "failed",
    }[status]


def _render_run_downloads(run: RunResult) -> None:
    columns = st.columns(3)
    columns[0].download_button(
        "Download run_summary.md",
        data=render_run_summary_markdown(run),
        file_name="run_summary.md",
        mime="text/markdown",
        key=f"dl-summary-{run.run_id}",
    )
    columns[1].download_button(
        "Download manifest.json",
        data=json.dumps(run_manifest(run), indent=2, ensure_ascii=False),
        file_name="manifest.json",
        mime="application/json",
        key=f"dl-manifest-{run.run_id}",
    )
    with columns[2]:
        if st.button("Build ZIP of all artifacts", key=f"zip-btn-{run.run_id}"):
            try:
                data = build_run_zip(run, Path(run.output_dir))
            except ArtifactError as exc:
                st.error(str(exc))
            else:
                cache_zip(run.run_id, data)
        data = cached_zip(run.run_id)
        if data:
            st.download_button(
                f"Download {run.run_id}.zip ({len(data) // 1024} KB)",
                data=data,
                file_name=f"{run.run_id}.zip",
                mime="application/zip",
                key=f"dl-zip-{run.run_id}",
            )


def _render_ticket(ticket: TicketResult, run: RunResult) -> None:
    header = st.columns([2, 2, 3])
    header[0].markdown(status_badge(ticket.status), unsafe_allow_html=True)
    header[1].markdown(provider_badge(ticket), unsafe_allow_html=True)
    header[2].markdown(
        f'<span class="jqc-badge '
        f'{"ok" if ticket.automation_readiness is AutomationReadiness.READY else "warn"}">'
        f"Automation: {ticket.automation_readiness.value}</span>",
        unsafe_allow_html=True,
    )

    render_stage_board(ticket)

    if ticket.errors:
        st.error("\n\n".join(f"- {item}" for item in ticket.errors))
    if ticket.warnings:
        with st.expander(f"{len(ticket.warnings)} warning(s)", expanded=False):
            for warning in ticket.warnings:
                st.markdown(f"- {warning}")

    tabs = st.tabs(
        [
            "Requirements Analysis",
            "Test Plan",
            "Test Cases",
            "Playwright",
            "Traceability",
            "Run Details",
        ]
    )
    with tabs[0]:
        _tab_requirements(ticket)
    with tabs[1]:
        _tab_test_plan(ticket)
    with tabs[2]:
        _tab_test_cases(ticket)
    with tabs[3]:
        _tab_playwright(ticket)
    with tabs[4]:
        _tab_traceability(ticket)
    with tabs[5]:
        _tab_run_details(ticket, run)


def _tab_requirements(ticket: TicketResult) -> None:
    if ticket.analysis is None:
        st.info("No requirement analysis was produced for this ticket.")
        return
    analysis = ticket.analysis
    markdown = render_requirements_markdown(analysis, ticket.issue)

    columns = st.columns(4)
    columns[0].metric("Requirements", len(analysis.requirements))
    columns[1].metric("Acceptance criteria", len(analysis.acceptance_criteria))
    columns[2].metric("Missing info", len(analysis.missing_information))
    columns[3].metric("Open questions", len(analysis.open_questions))

    if analysis.missing_information:
        st.warning(
            "Missing information:\n"
            + "\n".join(f"- {item}" for item in analysis.missing_information)
        )
    st.markdown(markdown)
    st.download_button(
        "Download requirements_analysis.md",
        data=markdown,
        file_name=f"{ticket.ticket_key}_requirements_analysis.md",
        mime="text/markdown",
        key=f"dl-req-{ticket.ticket_key}",
    )


def _tab_test_plan(ticket: TicketResult) -> None:
    if ticket.test_plan is None or ticket.analysis is None:
        st.info("No test plan was produced for this ticket.")
        return
    markdown = render_test_plan_markdown(ticket.test_plan, ticket.analysis)
    st.markdown(markdown)
    st.download_button(
        "Download test_plan.md",
        data=markdown,
        file_name=f"{ticket.ticket_key}_test_plan.md",
        mime="text/markdown",
        key=f"dl-plan-{ticket.ticket_key}",
    )


def _tab_test_cases(ticket: TicketResult) -> None:
    if ticket.test_cases is None:
        st.info("No test cases were produced for this ticket.")
        return
    suite = ticket.test_cases
    rows = test_case_rows(suite)
    frame = pd.DataFrame(rows)

    st.caption(f"{len(rows)} test case(s)")
    filters = st.columns(5)
    query = filters[0].text_input(
        "Search", key=f"tc-q-{ticket.ticket_key}", placeholder="text in any column"
    )
    priorities = filters[1].multiselect(
        "Priority",
        sorted(frame["priority"].unique()) if not frame.empty else [],
        key=f"tc-p-{ticket.ticket_key}",
    )
    types = filters[2].multiselect(
        "Test type",
        sorted(frame["test_type"].unique()) if not frame.empty else [],
        key=f"tc-t-{ticket.ticket_key}",
    )
    automation = filters[3].multiselect(
        "Automation",
        sorted(frame["automation_candidate"].unique()) if not frame.empty else [],
        key=f"tc-a-{ticket.ticket_key}",
    )
    requirement_ids = sorted(
        {
            rid
            for case in suite.test_cases
            for rid in case.requirement_ids + case.acceptance_criteria_ids
        }
    )
    traced = filters[4].multiselect(
        "REQ / AC",
        requirement_ids,
        key=f"tc-r-{ticket.ticket_key}",
    )
    tags = sorted({tag for case in suite.test_cases for tag in case.tags})
    selected_tags = st.multiselect("Tags", tags, key=f"tc-g-{ticket.ticket_key}")

    view = frame
    if not view.empty:
        if query:
            mask = view.apply(
                lambda row: query.lower() in " ".join(map(str, row.values)).lower(),
                axis=1,
            )
            view = view[mask]
        if priorities:
            view = view[view["priority"].isin(priorities)]
        if types:
            view = view[view["test_type"].isin(types)]
        if automation:
            view = view[view["automation_candidate"].isin(automation)]
        if traced:
            view = view[
                view.apply(
                    lambda row: any(
                        ident
                        in f"{row['requirement_ids']} {row['acceptance_criteria_ids']}"
                        for ident in traced
                    ),
                    axis=1,
                )
            ]
        if selected_tags:
            view = view[
                view["tags"].apply(
                    lambda value: any(tag in str(value) for tag in selected_tags)
                )
            ]

    st.dataframe(view, use_container_width=True, hide_index=True)

    markdown = render_test_cases_markdown(suite)
    csv_data = render_test_cases_csv(suite)
    columns = st.columns(2)
    columns[0].download_button(
        "Download test_cases.md",
        data=markdown,
        file_name=f"{ticket.ticket_key}_test_cases.md",
        mime="text/markdown",
        key=f"dl-tcmd-{ticket.ticket_key}",
    )
    columns[1].download_button(
        "Download test_cases.csv",
        data=csv_data,
        file_name=f"{ticket.ticket_key}_test_cases.csv",
        mime="text/csv",
        key=f"dl-tccsv-{ticket.ticket_key}",
    )
    with st.expander("Full test case detail (markdown)"):
        st.markdown(markdown)


def _tab_playwright(ticket: TicketResult) -> None:
    if ticket.playwright is None or ticket.test_cases is None:
        st.info("No Playwright automation was produced for this ticket.")
        return
    bundle = ticket.playwright

    if bundle.readiness is AutomationReadiness.READY:
        st.success("Automation readiness: READY")
    else:
        st.warning(f"Automation readiness: {bundle.readiness.value}")
    if bundle.missing_information:
        st.error(
            "Missing information before this suite can run:\n"
            + "\n".join(f"- {item}" for item in bundle.missing_information)
        )
    if bundle.setup_notes:
        with st.expander("Setup notes", expanded=False):
            st.markdown(bundle.setup_notes)

    for index, file in enumerate(bundle.files):
        st.markdown(f"**`{file.path}`**")
        st.code(file.content, language="typescript")
        st.download_button(
            f"Download {Path(file.path).name}",
            data=file.content,
            file_name=Path(file.path).name,
            mime="text/plain",
            key=f"dl-spec-{ticket.ticket_key}-{index}",
        )

    markdown = render_playwright_markdown(bundle, ticket.test_cases)
    st.download_button(
        "Download playwright_tests.md",
        data=markdown,
        file_name=f"{ticket.ticket_key}_playwright_tests.md",
        mime="text/markdown",
        key=f"dl-pwmd-{ticket.ticket_key}",
    )


def _tab_traceability(ticket: TicketResult) -> None:
    if ticket.traceability is None:
        st.info("No traceability matrix was produced for this ticket.")
        return
    matrix = ticket.traceability
    metrics = matrix.metrics

    columns = st.columns(4)
    columns[0].metric(
        "Requirement coverage",
        f"{metrics.requirement_coverage_pct}%",
        f"{metrics.covered_requirements}/{metrics.total_requirements}",
    )
    columns[1].metric(
        "AC coverage",
        f"{metrics.acceptance_criteria_coverage_pct}%",
        f"{metrics.covered_acceptance_criteria}/{metrics.total_acceptance_criteria}",
    )
    columns[2].metric(
        "Automation coverage",
        f"{metrics.automation_coverage_pct}%",
        f"{metrics.automated_test_cases}/{metrics.automatable_test_cases}",
    )
    columns[3].metric("Test cases", metrics.total_test_cases)

    if metrics.orphan_requirements:
        st.warning(
            "Requirements with no test case: " + ", ".join(metrics.orphan_requirements)
        )
    if metrics.orphan_acceptance_criteria:
        st.warning(
            "Acceptance criteria with no test case: "
            + ", ".join(metrics.orphan_acceptance_criteria)
        )
    if metrics.orphan_test_cases:
        st.warning(
            "Test cases with no requirement link: "
            + ", ".join(metrics.orphan_test_cases)
        )

    frame = pd.DataFrame(
        [
            {
                "requirement_id": row.requirement_id,
                "acceptance_criterion_id": row.acceptance_criterion_id,
                "requirement": row.requirement_text,
                "test_case_ids": ", ".join(row.test_case_ids),
                "automated": ", ".join(row.automated_test_case_ids),
                "coverage_status": row.coverage_status.value,
                "reason": row.reason,
            }
            for row in matrix.rows
        ]
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)
    st.download_button(
        "Download traceability_matrix.csv",
        data=render_traceability_csv(matrix),
        file_name=f"{ticket.ticket_key}_traceability_matrix.csv",
        mime="text/csv",
        key=f"dl-trace-{ticket.ticket_key}",
    )


def _tab_run_details(ticket: TicketResult, run: RunResult) -> None:
    issue = ticket.issue
    st.markdown(
        f"""
- **Ticket:** `{ticket.ticket_key}`
- **Status:** `{ticket.status.value}`
- **Provider source:** `{ticket.provider_source.value if ticket.provider_source else '-'}`
- **Started:** `{ticket.started_at.isoformat(timespec='seconds')}`
- **Completed:** `{ticket.completed_at.isoformat(timespec='seconds') if ticket.completed_at else '-'}`
- **Duration:** `{ticket.duration_seconds if ticket.duration_seconds is not None else '-'} s`
- **Jira URL:** {issue.url if issue and issue.url else '_not available_'}
- **Output directory:** `{ticket.output_dir or '-'}`
        """.strip()
    )

    st.markdown("**Stages**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "stage": stage.label,
                    "status": stage.status.value,
                    "message": stage.message,
                    "warnings": len(stage.warnings),
                    "seconds": stage.duration_seconds,
                }
                for stage in ticket.stages
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    if ticket.artifacts:
        st.markdown("**Artifacts**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "artifact": artifact.name,
                        "path": artifact.relative_path,
                        "bytes": artifact.bytes,
                    }
                    for artifact in ticket.artifacts
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        if ticket.output_dir:
            key = f"{run.run_id}:{ticket.ticket_key}"
            if st.button("Build ticket ZIP", key=f"zip-t-{ticket.ticket_key}"):
                try:
                    cache_zip(key, build_ticket_zip(ticket))
                except ArtifactError as exc:
                    st.error(str(exc))
            data = cached_zip(key)
            if data:
                st.download_button(
                    f"Download {ticket.ticket_key}.zip",
                    data=data,
                    file_name=f"{ticket.ticket_key}.zip",
                    mime="application/zip",
                    key=f"dl-tzip-{ticket.ticket_key}",
                )

    with st.expander("Activity log (redacted)"):
        st.code("\n".join(ticket.log) or "No log entries.", language="text")

    with st.expander("Ticket manifest"):
        st.json(ticket_manifest(ticket))
