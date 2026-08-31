"""Deterministic coverage maths and artifact rendering."""

from __future__ import annotations

import csv
import io

from jira_qa_crew.models import (
    AutomationCandidate,
    AutomationReadiness,
    CoverageStatus,
    TestCase,
    TestStep,
)
from jira_qa_crew.services.renderers import (
    TEST_CASE_CSV_HEADER,
    TRACEABILITY_CSV_HEADER,
    render_playwright_markdown,
    render_requirements_markdown,
    render_run_summary_markdown,
    render_test_cases_csv,
    render_test_cases_markdown,
    render_test_plan_markdown,
    render_traceability_csv,
    run_manifest,
    ticket_manifest,
)
from jira_qa_crew.services.traceability import build_traceability
from tests.factories import (
    TICKET,
    make_analysis,
    make_bundle,
    make_issue,
    make_run_result,
    make_suite,
    make_test_plan,
    make_ticket_result,
)

# -- traceability ----------------------------------------------------------


def test_matrix_links_requirements_criteria_cases_and_automation() -> None:
    matrix = build_traceability(make_analysis(), make_suite(), make_bundle())

    by_req = {row.requirement_id: row for row in matrix.rows}
    assert by_req["REQ-001"].acceptance_criterion_id == "AC-001"
    assert f"{TICKET}-TC-001" in by_req["REQ-001"].test_case_ids
    assert by_req["REQ-001"].automated_test_case_ids == [f"{TICKET}-TC-001"]


def test_needs_configuration_downgrades_coverage_to_partial() -> None:
    matrix = build_traceability(make_analysis(), make_suite(), make_bundle())
    row = next(row for row in matrix.rows if row.requirement_id == "REQ-001")
    assert row.coverage_status is CoverageStatus.PARTIAL
    assert "NEEDS_CONFIGURATION" in row.reason


def test_ready_bundle_yields_covered_rows() -> None:
    bundle = make_bundle()
    bundle.readiness = AutomationReadiness.READY
    bundle.missing_information = []
    matrix = build_traceability(make_analysis(), make_suite(), bundle)
    row = next(row for row in matrix.rows if row.requirement_id == "REQ-001")
    assert row.coverage_status is CoverageStatus.COVERED


def test_requirement_without_a_test_case_is_not_covered() -> None:
    suite = make_suite()
    suite.test_cases = suite.test_cases[:1]
    matrix = build_traceability(make_analysis(), suite, make_bundle())
    row = next(row for row in matrix.rows if row.requirement_id == "REQ-002")
    assert row.coverage_status is CoverageStatus.NOT_COVERED
    assert "REQ-002" in matrix.metrics.orphan_requirements


def test_automatable_case_without_generated_code_is_partial() -> None:
    bundle = make_bundle()
    bundle.mappings = []
    matrix = build_traceability(make_analysis(), make_suite(), bundle)
    row = next(row for row in matrix.rows if row.requirement_id == "REQ-001")
    assert row.coverage_status is CoverageStatus.PARTIAL
    assert matrix.metrics.automated_test_cases == 0


def test_orphan_test_cases_are_reported() -> None:
    suite = make_suite()
    suite.test_cases.append(
        TestCase(
            id=f"{TICKET}-TC-003",
            title="floating case",
            steps=[TestStep(step_number=1, action="do")],
            automation_candidate=AutomationCandidate.NO,
        )
    )
    matrix = build_traceability(make_analysis(), suite, make_bundle())
    assert f"{TICKET}-TC-003" in matrix.metrics.orphan_test_cases


def test_coverage_percentages_are_computed_in_python() -> None:
    metrics = build_traceability(make_analysis(), make_suite(), make_bundle()).metrics
    assert metrics.total_requirements == 2
    assert metrics.covered_requirements == 2
    assert metrics.requirement_coverage_pct == 100.0
    assert metrics.acceptance_criteria_coverage_pct == 100.0
    assert metrics.automation_coverage_pct == 100.0


def test_percentages_are_safe_when_nothing_exists() -> None:
    analysis = make_analysis()
    analysis.requirements = []
    analysis.acceptance_criteria = []
    metrics = build_traceability(analysis, None, None).metrics
    assert metrics.requirement_coverage_pct == 0.0
    assert metrics.automation_coverage_pct == 0.0


# -- renderers -------------------------------------------------------------


def test_requirements_markdown_contains_ids_and_gaps() -> None:
    markdown = render_requirements_markdown(make_analysis(), make_issue())
    assert "# Requirements Analysis - VWO-48" in markdown
    assert "REQ-001" in markdown and "AC-001" in markdown
    assert "## Missing Information" in markdown
    assert "reset URL path" in markdown


def test_test_plan_markdown_has_all_twelve_headings() -> None:
    markdown = render_test_plan_markdown(make_test_plan(), make_analysis())
    for number in range(1, 13):
        assert f"## {number}." in markdown
    assert "SC-001" in markdown


def test_test_cases_markdown_includes_steps_and_traceability() -> None:
    markdown = render_test_cases_markdown(make_suite())
    assert f"## {TICKET}-TC-001" in markdown
    assert "Open the reset link." in markdown
    assert "REQ-001" in markdown


def test_test_cases_csv_is_parseable_and_stable() -> None:
    data = render_test_cases_csv(make_suite())
    rows = list(csv.DictReader(io.StringIO(data)))
    assert list(rows[0]) == list(TEST_CASE_CSV_HEADER)
    assert rows[0]["test_case_id"] == f"{TICKET}-TC-001"
    assert rows[0]["automation_candidate"] == "YES"
    assert render_test_cases_csv(make_suite()) == data


def test_traceability_csv_header_and_rows() -> None:
    matrix = build_traceability(make_analysis(), make_suite(), make_bundle())
    rows = list(csv.reader(io.StringIO(render_traceability_csv(matrix))))
    assert tuple(rows[0]) == TRACEABILITY_CSV_HEADER
    assert any(row[0] == "REQ-001" for row in rows[1:])


def test_playwright_markdown_states_readiness_and_missing_information() -> None:
    markdown = render_playwright_markdown(make_bundle(), make_suite())
    assert "NEEDS_CONFIGURATION" in markdown
    assert "not** execution ready" in markdown
    assert "```typescript" in markdown
    assert "reset page path" in markdown


def test_run_summary_lists_every_ticket() -> None:
    run = make_run_result(["VWO-48", "VWO-49"])
    markdown = render_run_summary_markdown(run)
    assert "VWO-48" in markdown and "VWO-49" in markdown
    assert "Run ID" in markdown


def test_manifests_are_json_serialisable() -> None:
    import json

    run = make_run_result(["VWO-48"])
    payload = json.loads(json.dumps(run_manifest(run)))
    assert payload["totals"]["requested"] == 1
    ticket_payload = json.loads(json.dumps(ticket_manifest(make_ticket_result())))
    assert ticket_payload["counts"]["test_cases"] == 2
    assert ticket_payload["automation_readiness"] == "NEEDS_CONFIGURATION"
