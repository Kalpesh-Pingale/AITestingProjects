"""Deterministic renderers.

Every artifact is produced in Python from validated Pydantic objects, so the
same run always yields the same markdown, CSV and TypeScript. Raw LLM
markdown is never used as the source of truth.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from jira_qa_crew.models import (
    JiraIssue,
    PlaywrightBundle,
    RequirementAnalysis,
    RunResult,
    TestCaseSuite,
    TestPlan,
    TicketResult,
    TraceabilityMatrix,
)

TEST_CASE_CSV_HEADER: tuple[str, ...] = (
    "test_case_id",
    "ticket_key",
    "title",
    "objective",
    "priority",
    "test_type",
    "requirement_ids",
    "acceptance_criteria_ids",
    "preconditions",
    "test_data",
    "steps",
    "expected_result",
    "automation_candidate",
    "automation_rationale",
    "tags",
    "assumptions_or_blockers",
)

TRACEABILITY_CSV_HEADER: tuple[str, ...] = (
    "requirement_id",
    "requirement",
    "acceptance_criterion_id",
    "acceptance_criterion",
    "test_case_ids",
    "automated_test_case_ids",
    "coverage_status",
    "reason",
)


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


def _fmt_list(values: list[str], empty: str = "_none_") -> str:
    return ", ".join(values) if values else empty


def _fmt_ts(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC") if value else "-"


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_No rows._"
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        cells = [str(cell).replace("\n", "<br>").replace("|", r"\|") for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _classified_section(title: str, items: list) -> str:
    if not items:
        return f"### {title}\n\n_None recorded._\n"
    lines = [f"### {title}", ""]
    for item in items:
        prefix = f"**{item.id}** " if getattr(item, "id", "") else ""
        source = f" _(source: {item.source})_" if getattr(item, "source", "") else ""
        lines.append(
            f"- {prefix}{item.statement} `[{item.classification.value}]`{source}"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Requirements analysis
# ---------------------------------------------------------------------------


def render_requirements_markdown(
    analysis: RequirementAnalysis, issue: JiraIssue | None = None
) -> str:
    """Render the requirement analysis artifact."""
    lines: list[str] = [
        f"# Requirements Analysis - {analysis.ticket_key}",
        "",
        f"**Summary:** {analysis.summary or '_not set_'}",
        "",
        _md_table(
            ["Field", "Value"],
            [
                ["Issue type", analysis.issue_type or "-"],
                ["Status", analysis.status or "-"],
                ["Priority", analysis.priority or "-"],
                ["Labels", _fmt_list(analysis.labels)],
                ["Components", _fmt_list(analysis.components)],
                ["Parent", analysis.parent_key or "-"],
                ["Subtasks", _fmt_list(analysis.subtasks)],
                ["Linked issues", _fmt_list(analysis.linked_issues)],
                ["Data source", analysis.provider_source.value],
                ["Analysed at", _fmt_ts(analysis.analysed_at)],
            ],
        ),
        "",
        "## Ticket Digest",
        "",
        analysis.description_digest or "_not provided_",
        "",
        "## Requirements",
        "",
        _md_table(
            ["ID", "Requirement", "Category", "Classification", "Source"],
            [
                [
                    req.id,
                    req.statement,
                    req.category.value,
                    req.classification.value,
                    req.source or "-",
                ]
                for req in analysis.requirements
            ],
        ),
        "",
        "## Acceptance Criteria",
        "",
        _md_table(
            ["ID", "Criterion", "Requirements", "Classification"],
            [
                [
                    criterion.id,
                    criterion.statement,
                    _fmt_list(criterion.requirement_ids, "-"),
                    criterion.classification.value,
                ]
                for criterion in analysis.acceptance_criteria
            ],
        ),
        "",
        "## Supporting Detail",
        "",
        _classified_section("Business Rules", analysis.business_rules),
        _classified_section(
            "Non-Functional Requirements", analysis.non_functional_requirements
        ),
        _classified_section("Dependencies", analysis.dependencies),
        _classified_section("Constraints", analysis.constraints),
        _classified_section("Risks", analysis.risks),
        _classified_section("Assumptions", analysis.assumptions),
        "## Missing Information",
        "",
    ]
    lines += (
        [f"- {item}" for item in analysis.missing_information]
        if analysis.missing_information
        else ["_Nothing recorded as missing._"]
    )
    lines += ["", "## Open Questions", ""]
    lines += (
        [f"- {item}" for item in analysis.open_questions]
        if analysis.open_questions
        else ["_No open questions recorded._"]
    )

    if issue is not None:
        lines += [
            "",
            "---",
            "",
            f"_Source: {issue.source.value}"
            + (f" | {issue.url}" if issue.url else "")
            + f" | fetched {_fmt_ts(issue.fetched_at)}_",
        ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Test plan
# ---------------------------------------------------------------------------


def render_test_plan_markdown(plan: TestPlan, analysis: RequirementAnalysis) -> str:
    """Render the twelve section test plan artifact."""
    title = plan.title or f"Test Plan - {plan.ticket_key}"
    lines = [f"# {title}", "", f"**Ticket:** {plan.ticket_key}", ""]

    for section in plan.sections:
        lines += [f"## {section.number}. {section.title}", "", section.content.strip(), ""]

    lines += ["## Scenario Index", ""]
    lines.append(
        _md_table(
            ["Scenario", "Title", "Requirements", "Acceptance Criteria", "Types", "Priority"],
            [
                [
                    scenario.id,
                    scenario.title,
                    _fmt_list(scenario.requirement_ids, "-"),
                    _fmt_list(scenario.acceptance_criteria_ids, "-"),
                    _fmt_list(scenario.test_types, "-"),
                    scenario.priority.value,
                ]
                for scenario in plan.scenarios
            ],
        )
    )
    lines += [
        "",
        "---",
        "",
        f"_Generated from {len(analysis.requirements)} requirement(s) and "
        f"{len(analysis.acceptance_criteria)} acceptance criterion/criteria._",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def render_test_cases_markdown(suite: TestCaseSuite) -> str:
    """Render the detailed test case artifact."""
    lines = [
        f"# Test Cases - {suite.ticket_key}",
        "",
        f"**Total:** {len(suite.test_cases)} | "
        f"**Automatable:** {len(suite.automatable_cases())}",
        "",
    ]
    if suite.coverage_notes:
        lines += ["> " + suite.coverage_notes.replace("\n", " "), ""]
    if suite.uncovered_acceptance_criteria:
        lines += [
            "**Acceptance criteria without a test case:** "
            + _fmt_list(suite.uncovered_acceptance_criteria),
            "",
        ]

    for case in suite.test_cases:
        lines += [
            f"## {case.id} - {case.title}",
            "",
            _md_table(
                ["Field", "Value"],
                [
                    ["Objective", case.objective or "-"],
                    ["Priority", case.priority.value],
                    ["Test type", case.test_type],
                    ["Requirements", _fmt_list(case.requirement_ids, "-")],
                    ["Acceptance criteria", _fmt_list(case.acceptance_criteria_ids, "-")],
                    ["Automation", case.automation_candidate.value],
                    ["Automation rationale", case.automation_rationale or "-"],
                    ["Tags", _fmt_list(case.tags, "-")],
                ],
            ),
            "",
            "**Preconditions**",
            "",
        ]
        lines += [f"- {item}" for item in case.preconditions] or ["_None._"]
        lines += ["", "**Test data**", ""]
        lines += [f"- {item}" for item in case.test_data] or ["_None._"]
        lines += ["", "**Steps**", ""]
        lines.append(
            _md_table(
                ["#", "Action", "Expected"],
                [
                    [str(step.step_number), step.action, step.expected_result or "-"]
                    for step in case.steps
                ],
            )
        )
        lines += ["", f"**Expected result:** {case.expected_result or '-'}", ""]
        if case.assumptions_or_blockers:
            lines += ["**Assumptions / blockers**", ""]
            lines += [f"- {item}" for item in case.assumptions_or_blockers]
            lines.append("")
    return "\n".join(lines) + "\n"


def test_case_rows(suite: TestCaseSuite) -> list[dict[str, str]]:
    """Flat rows used by both the CSV artifact and the Streamlit dataframe."""
    rows: list[dict[str, str]] = []
    for case in suite.test_cases:
        rows.append(
            {
                "test_case_id": case.id,
                "ticket_key": case.ticket_key or suite.ticket_key,
                "title": case.title,
                "objective": case.objective,
                "priority": case.priority.value,
                "test_type": case.test_type,
                "requirement_ids": "; ".join(case.requirement_ids),
                "acceptance_criteria_ids": "; ".join(case.acceptance_criteria_ids),
                "preconditions": " | ".join(case.preconditions),
                "test_data": " | ".join(case.test_data),
                "steps": " | ".join(
                    f"{step.step_number}. {step.action}"
                    + (f" -> {step.expected_result}" if step.expected_result else "")
                    for step in case.steps
                ),
                "expected_result": case.expected_result,
                "automation_candidate": case.automation_candidate.value,
                "automation_rationale": case.automation_rationale,
                "tags": "; ".join(case.tags),
                "assumptions_or_blockers": " | ".join(case.assumptions_or_blockers),
            }
        )
    return rows


def render_test_cases_csv(suite: TestCaseSuite) -> str:
    """Render the test case CSV artifact."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(TEST_CASE_CSV_HEADER), lineterminator="\n")
    writer.writeheader()
    for row in test_case_rows(suite):
        writer.writerow(row)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------


def render_traceability_csv(matrix: TraceabilityMatrix) -> str:
    """Render the traceability matrix CSV artifact."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TRACEABILITY_CSV_HEADER)
    for row in matrix.rows:
        writer.writerow(
            [
                row.requirement_id,
                row.requirement_text,
                row.acceptance_criterion_id,
                row.acceptance_criterion_text,
                "; ".join(row.test_case_ids),
                "; ".join(row.automated_test_case_ids),
                row.coverage_status.value,
                row.reason,
            ]
        )
    return buffer.getvalue()


def render_traceability_markdown(matrix: TraceabilityMatrix) -> str:
    """Render the traceability matrix as markdown for the run summary."""
    metrics = matrix.metrics
    lines = [
        f"# Traceability Matrix - {matrix.ticket_key}",
        "",
        _md_table(
            ["Metric", "Value"],
            [
                [
                    "Requirements covered",
                    f"{metrics.covered_requirements}/{metrics.total_requirements} "
                    f"({metrics.requirement_coverage_pct}%)",
                ],
                [
                    "Acceptance criteria covered",
                    f"{metrics.covered_acceptance_criteria}/"
                    f"{metrics.total_acceptance_criteria} "
                    f"({metrics.acceptance_criteria_coverage_pct}%)",
                ],
                [
                    "Automated of automatable",
                    f"{metrics.automated_test_cases}/{metrics.automatable_test_cases} "
                    f"({metrics.automation_coverage_pct}%)",
                ],
                ["Orphan requirements", _fmt_list(metrics.orphan_requirements)],
                [
                    "Orphan acceptance criteria",
                    _fmt_list(metrics.orphan_acceptance_criteria),
                ],
                ["Orphan test cases", _fmt_list(metrics.orphan_test_cases)],
            ],
        ),
        "",
        _md_table(
            ["REQ", "AC", "Test cases", "Automated", "Status", "Reason"],
            [
                [
                    row.requirement_id or "-",
                    row.acceptance_criterion_id or "-",
                    _fmt_list(row.test_case_ids, "-"),
                    _fmt_list(row.automated_test_case_ids, "-"),
                    row.coverage_status.value,
                    row.reason,
                ]
                for row in matrix.rows
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Playwright
# ---------------------------------------------------------------------------


def render_playwright_markdown(bundle: PlaywrightBundle, suite: TestCaseSuite) -> str:
    """Render playwright_tests.md with the generated files in code blocks."""
    lines = [
        f"# Playwright Automation - {bundle.ticket_key}",
        "",
        f"**Automation readiness:** `{bundle.readiness.value}`",
        "",
    ]
    if bundle.readiness.value == "NEEDS_CONFIGURATION":
        lines += [
            "> This bundle is **not** execution ready. The items under "
            "*Missing information* must be supplied before the suite can run.",
            "",
        ]

    lines += ["## Coverage", ""]
    lines += [
        _md_table(
            ["Test case", "Spec file", "Test title", "REQ", "AC"],
            [
                [
                    mapping.test_case_id or "-",
                    mapping.spec_file or "-",
                    mapping.test_title or "-",
                    _fmt_list(mapping.requirement_ids, "-"),
                    _fmt_list(mapping.acceptance_criteria_ids, "-"),
                ]
                for mapping in bundle.mappings
            ],
        ),
        "",
    ]
    automatable = {case.id for case in suite.automatable_cases()}
    mapped = {mapping.test_case_id for mapping in bundle.mappings}
    not_automated = sorted(automatable - mapped)
    if not_automated:
        lines += [
            "**Automatable test cases without generated code:** "
            + _fmt_list(not_automated),
            "",
        ]
    if bundle.coverage_notes:
        lines += [bundle.coverage_notes, ""]

    lines += ["## Missing information", ""]
    lines += (
        [f"- {item}" for item in bundle.missing_information]
        if bundle.missing_information
        else ["_None reported._"]
    )
    lines += ["", "## Setup", "", bundle.setup_notes or "_No setup notes provided._", ""]

    lines += ["## Generated files", ""]
    for file in bundle.files:
        lines += [f"### `{file.path}`", "", "```typescript", file.content.rstrip(), "```", ""]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Run summary
# ---------------------------------------------------------------------------


def render_run_summary_markdown(run: RunResult) -> str:
    """Render run_summary.md for the whole run."""
    lines = [
        "# Run Summary",
        "",
        _md_table(
            ["Field", "Value"],
            [
                ["Run ID", run.run_id],
                ["Integration mode", run.integration_mode],
                ["Demo mode", "yes" if run.demo_mode else "no"],
                ["Requested tickets", _fmt_list(run.requested_keys)],
                ["Completed", str(len(run.completed))],
                ["Completed with warnings", str(len(run.completed_with_warnings))],
                ["Failed", str(len(run.failed))],
                ["Started", _fmt_ts(run.started_at)],
                ["Finished", _fmt_ts(run.completed_at)],
            ],
        ),
        "",
        "## Tickets",
        "",
        _md_table(
            ["Ticket", "Status", "Source", "Automation", "Requirements", "Test cases", "Warnings"],
            [
                [
                    ticket.ticket_key,
                    ticket.status.value,
                    ticket.provider_source.value if ticket.provider_source else "-",
                    ticket.automation_readiness.value,
                    str(len(ticket.analysis.requirements)) if ticket.analysis else "-",
                    str(len(ticket.test_cases.test_cases)) if ticket.test_cases else "-",
                    str(len(ticket.warnings)),
                ]
                for ticket in run.tickets
            ],
        ),
        "",
    ]

    for ticket in run.tickets:
        lines += [f"## {ticket.ticket_key}", ""]
        if ticket.errors:
            lines += ["**Errors**", ""] + [f"- {item}" for item in ticket.errors] + [""]
        if ticket.warnings:
            lines += ["**Warnings**", ""] + [
                f"- {item}" for item in ticket.warnings
            ] + [""]
        if ticket.traceability:
            metrics = ticket.traceability.metrics
            lines += [
                f"- Requirement coverage: {metrics.requirement_coverage_pct}%",
                f"- Acceptance criteria coverage: "
                f"{metrics.acceptance_criteria_coverage_pct}%",
                f"- Automation coverage: {metrics.automation_coverage_pct}%",
                "",
            ]
        if ticket.artifacts:
            lines += ["**Artifacts**", ""]
            lines += [f"- `{artifact.relative_path}`" for artifact in ticket.artifacts]
            lines.append("")
    return "\n".join(lines) + "\n"


def ticket_manifest(ticket: TicketResult) -> dict:
    """Machine readable per-ticket manifest."""
    return {
        "ticket_key": ticket.ticket_key,
        "status": ticket.status.value,
        "provider_source": ticket.provider_source.value if ticket.provider_source else None,
        "automation_readiness": ticket.automation_readiness.value,
        "started_at": ticket.started_at.isoformat(),
        "completed_at": ticket.completed_at.isoformat() if ticket.completed_at else None,
        "duration_seconds": ticket.duration_seconds,
        "counts": {
            "requirements": len(ticket.analysis.requirements) if ticket.analysis else 0,
            "acceptance_criteria": (
                len(ticket.analysis.acceptance_criteria) if ticket.analysis else 0
            ),
            "test_cases": len(ticket.test_cases.test_cases) if ticket.test_cases else 0,
            "automatable_test_cases": (
                len(ticket.test_cases.automatable_cases()) if ticket.test_cases else 0
            ),
            "playwright_files": len(ticket.playwright.files) if ticket.playwright else 0,
        },
        "coverage": (
            ticket.traceability.metrics.model_dump() if ticket.traceability else None
        ),
        "stages": [
            {
                "key": stage.key,
                "label": stage.label,
                "status": stage.status.value,
                "message": stage.message,
                "warnings": stage.warnings,
                "started_at": stage.started_at.isoformat() if stage.started_at else None,
                "completed_at": (
                    stage.completed_at.isoformat() if stage.completed_at else None
                ),
                "duration_seconds": stage.duration_seconds,
            }
            for stage in ticket.stages
        ],
        "warnings": ticket.warnings,
        "errors": ticket.errors,
        "artifacts": [artifact.model_dump() for artifact in ticket.artifacts],
    }


def run_manifest(run: RunResult) -> dict:
    """Machine readable run manifest and artifact index."""
    return {
        "run_id": run.run_id,
        "integration_mode": run.integration_mode,
        "demo_mode": run.demo_mode,
        "requested_keys": run.requested_keys,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "successful": run.successful,
        "totals": {
            "requested": len(run.requested_keys),
            "completed": len(run.completed),
            "completed_with_warnings": len(run.completed_with_warnings),
            "failed": len(run.failed),
        },
        "errors": run.errors,
        "tickets": [ticket_manifest(ticket) for ticket in run.tickets],
    }
