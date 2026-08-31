"""Pydantic normalisation plus the deterministic stage validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jira_qa_crew.models import (
    AcceptanceCriterion,
    AutomationCandidate,
    AutomationReadiness,
    InfoClassification,
    PlaywrightBundle,
    PlaywrightFile,
    Priority,
    Requirement,
    RequirementCategory,
    TestCase,
    TestStep,
    normalise_identifier,
)
from jira_qa_crew.services.validation import (
    normalise_bundle,
    validate_analysis,
    validate_playwright,
    validate_test_cases,
    validate_test_plan,
)
from tests.factories import (
    TICKET,
    make_analysis,
    make_bundle,
    make_issue,
    make_suite,
    make_test_plan,
)

# -- normalisation ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("req-1", "REQ-001"), ("REQ 12", "REQ-012"), ("REQ-003", "REQ-003"), ("req_7", "REQ-007")],
)
def test_identifier_normalisation(raw: str, expected: str) -> None:
    assert normalise_identifier(raw, "REQ") == expected


def test_enum_coercion_is_forgiving_about_llm_wording() -> None:
    case = TestCase.model_validate(
        {
            "id": "vwo-48-tc-001",
            "title": "t",
            "priority": "p1",
            "automation_candidate": "true",
            "requirement_ids": ["req-1"],
            "acceptance_criteria_ids": ["ac-2"],
            "steps": [{"step_number": 7, "action": "do"}],
        }
    )
    assert case.id == "VWO-48-TC-001"
    assert case.priority is Priority.HIGH
    assert case.automation_candidate is AutomationCandidate.YES
    assert case.requirement_ids == ["REQ-001"]
    assert case.acceptance_criteria_ids == ["AC-002"]
    assert case.steps[0].step_number == 1  # renumbered deterministically


def test_unknown_enum_values_fall_back_to_the_default() -> None:
    requirement = Requirement(id="REQ-001", statement="x", category="weird", classification="huh")
    assert requirement.category is RequirementCategory.FUNCTIONAL
    assert requirement.classification is InfoClassification.EXPLICIT


def test_playwright_paths_cannot_escape_the_bundle() -> None:
    file = PlaywrightFile(path="../../etc/passwd", content="x")
    assert file.path == "etc/passwd"


def test_step_requires_a_positive_number() -> None:
    with pytest.raises(ValidationError):
        TestStep(step_number=0, action="x")


# -- stage 1 ---------------------------------------------------------------


def test_valid_analysis_passes() -> None:
    report = validate_analysis(make_analysis(), make_issue(), TICKET)
    assert report.ok, report.errors


def test_analysis_ticket_mismatch_is_an_error() -> None:
    analysis = make_analysis()
    analysis.ticket_key = "OTHER-1"
    report = validate_analysis(analysis, make_issue(), TICKET)
    assert not report.ok
    assert "OTHER-1" in report.errors[0]


def test_duplicate_requirement_ids_are_detected() -> None:
    analysis = make_analysis()
    analysis.requirements[1].id = "REQ-001"
    report = validate_analysis(analysis, make_issue(), TICKET)
    assert any("Duplicate requirement id" in error for error in report.errors)


def test_malformed_identifiers_are_detected() -> None:
    analysis = make_analysis()
    analysis.requirements[0].id = "REQUIREMENT-ONE"
    report = validate_analysis(analysis, make_issue(), TICKET)
    assert any("Malformed requirement id" in error for error in report.errors)


def test_empty_analysis_is_an_error() -> None:
    analysis = make_analysis()
    analysis.requirements = []
    report = validate_analysis(analysis, make_issue(), TICKET)
    assert not report.ok


def test_ungrounded_explicit_criteria_are_flagged_as_warnings() -> None:
    analysis = make_analysis()
    analysis.acceptance_criteria.append(
        AcceptanceCriterion(
            id="AC-002",
            statement="Invoices must be exported to the accounting ledger nightly.",
            classification=InfoClassification.EXPLICIT,
        )
    )
    report = validate_analysis(analysis, make_issue(), TICKET)
    assert any("AC-002" in warning for warning in report.warnings)


# -- stage 2 ---------------------------------------------------------------


def test_valid_plan_passes() -> None:
    report = validate_test_plan(make_test_plan(), make_analysis(), TICKET)
    assert report.ok, report.errors


def test_plan_must_have_exactly_twelve_sections() -> None:
    plan = make_test_plan()
    plan.sections.pop()
    report = validate_test_plan(plan, make_analysis(), TICKET)
    assert any("exactly 12 sections" in error for error in report.errors)


def test_empty_sections_are_errors() -> None:
    plan = make_test_plan()
    plan.sections[0].content = "too short"
    report = validate_test_plan(plan, make_analysis(), TICKET)
    assert any("too short" in error or "empty" in error for error in report.errors)


def test_scenarios_referencing_unknown_ids_fail() -> None:
    plan = make_test_plan()
    plan.scenarios[0].requirement_ids = ["REQ-999"]
    report = validate_test_plan(plan, make_analysis(), TICKET)
    assert any("REQ-999" in error for error in report.errors)


def test_unreferenced_requirement_is_a_warning_not_an_error() -> None:
    plan = make_test_plan()
    plan.scenarios = plan.scenarios[:1]
    report = validate_test_plan(plan, make_analysis(), TICKET)
    assert report.ok
    assert any("REQ-002" in warning for warning in report.warnings)


# -- stage 3 ---------------------------------------------------------------


def test_valid_suite_passes() -> None:
    report = validate_test_cases(make_suite(), make_analysis(), TICKET)
    assert report.ok, report.errors


def test_duplicate_test_case_ids_are_detected() -> None:
    suite = make_suite()
    suite.test_cases[1].id = suite.test_cases[0].id
    report = validate_test_cases(suite, make_analysis(), TICKET)
    assert any("Duplicate test case id" in error for error in report.errors)


def test_test_case_id_format_is_enforced() -> None:
    suite = make_suite()
    suite.test_cases[0].id = "TC-1"
    report = validate_test_cases(suite, make_analysis(), TICKET)
    assert any("VWO-48-TC-001" in error for error in report.errors)


def test_unknown_requirement_reference_is_an_error() -> None:
    suite = make_suite()
    suite.test_cases[0].requirement_ids = ["REQ-404"]
    report = validate_test_cases(suite, make_analysis(), TICKET)
    assert any("REQ-404" in error for error in report.errors)


def test_uncovered_explicit_criterion_must_be_declared() -> None:
    suite = make_suite()
    suite.test_cases[0].acceptance_criteria_ids = []
    report = validate_test_cases(suite, make_analysis(), TICKET)
    assert any("AC-001" in error for error in report.errors)

    suite.uncovered_acceptance_criteria = ["AC-001"]
    assert validate_test_cases(suite, make_analysis(), TICKET).ok


def test_case_without_steps_is_an_error() -> None:
    suite = make_suite()
    suite.test_cases[0].steps = []
    report = validate_test_cases(suite, make_analysis(), TICKET)
    assert any("no test steps" in error for error in report.errors)


# -- stage 4 ---------------------------------------------------------------


def test_valid_bundle_passes() -> None:
    report = validate_playwright(make_bundle(), make_suite(), TICKET)
    assert report.ok, report.errors


def test_wait_for_timeout_is_rejected() -> None:
    bundle = make_bundle()
    bundle.files[0].content += "\nawait page.waitForTimeout(1000);\n"
    report = validate_playwright(bundle, make_suite(), TICKET)
    assert any("waitForTimeout" in error for error in report.errors)


def test_xpath_selectors_are_rejected() -> None:
    bundle = make_bundle()
    bundle.files[0].content += "\nawait page.locator('//div[@id=\"x\"]').click();\n"
    report = validate_playwright(bundle, make_suite(), TICKET)
    assert any("XPath" in error for error in report.errors)


def test_hard_coded_environment_urls_are_rejected() -> None:
    bundle = make_bundle()
    bundle.files[0].content += "\nawait page.goto('https://staging.example.com/reset');\n"
    report = validate_playwright(bundle, make_suite(), TICKET)
    assert any("absolute environment URL" in error for error in report.errors)


def test_hard_coded_credentials_are_rejected() -> None:
    bundle = make_bundle()
    bundle.files[0].content += "\nconst password = 'hunter2secret';\n"
    report = validate_playwright(bundle, make_suite(), TICKET)
    assert any("credential" in error for error in report.errors)


def test_missing_code_for_automatable_cases_is_an_error() -> None:
    bundle = make_bundle()
    bundle.files = []
    report = validate_playwright(bundle, make_suite(), TICKET)
    assert not report.ok


def test_ready_with_missing_information_is_contradictory() -> None:
    bundle = make_bundle()
    bundle.readiness = AutomationReadiness.READY
    report = validate_playwright(bundle, make_suite(), TICKET)
    assert any("READY but missing_information" in error for error in report.errors)


def test_markdown_fences_are_stripped_before_validation() -> None:
    bundle = make_bundle()
    bundle.files[0].content = "```typescript\n" + bundle.files[0].content + "\n```"
    normalise_bundle(bundle)
    assert "```" not in bundle.files[0].content
    assert validate_playwright(bundle, make_suite(), TICKET).ok


def test_mapping_to_an_unknown_case_is_an_error() -> None:
    bundle = make_bundle()
    bundle.mappings[0].test_case_id = "VWO-48-TC-999"
    report = validate_playwright(bundle, make_suite(), TICKET)
    assert any("unknown test case id" in error for error in report.errors)


def test_bundle_is_not_required_when_nothing_is_automatable() -> None:
    suite = make_suite()
    for case in suite.test_cases:
        case.automation_candidate = AutomationCandidate.NO
    empty = PlaywrightBundle(ticket_key=TICKET)
    assert validate_playwright(empty, suite, TICKET).ok
