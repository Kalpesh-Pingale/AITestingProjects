"""Deterministic validation of every CrewAI stage output.

Nothing here calls an LLM. Each validator returns a :class:`ValidationReport`
whose *errors* trigger the single controlled repair attempt (through the
CrewAI task guardrail) and whose *warnings* are surfaced in the UI and the
artifacts without failing the ticket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jira_qa_crew.models import (
    TEST_PLAN_SECTION_TITLES,
    AutomationReadiness,
    InfoClassification,
    JiraIssue,
    PlaywrightBundle,
    RequirementAnalysis,
    TestCaseSuite,
    TestPlan,
)

REQ_ID_RE = re.compile(r"^REQ-\d{3,}$")
AC_ID_RE = re.compile(r"^AC-\d{3,}$")
SC_ID_RE = re.compile(r"^SC-\d{3,}$")

_MIN_SECTION_CHARS = 40
_STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have in into is it its of on or that
    the their there these this to was were will with when then given should
    must shall can could would user users system page screen
    """.split()  # noqa: SIM905 - a text block is more readable than a list literal
)

#: Patterns that must never appear in generated Playwright code.
_FORBIDDEN_CODE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"page\s*\.\s*waitForTimeout\s*\("),
        "uses page.waitForTimeout(), which is forbidden",
    ),
    (
        re.compile(r"""(?:locator|click|fill)\s*\(\s*['"]\s*(?://|xpath=)"""),
        "uses an XPath selector",
    ),
    (
        re.compile(r"""goto\s*\(\s*[`'"]https?://"""),
        "hard-codes an absolute environment URL in page.goto()",
    ),
    (
        re.compile(
            r"""(?i)(password|api[_-]?key|token|secret)\s*[:=]\s*['"][^'"]{4,}['"]"""
        ),
        "appears to hard-code a credential",
    ),
)

_PLACEHOLDER_ENV_RE = re.compile(r"process\s*\.\s*env")


@dataclass(slots=True)
class ValidationReport:
    """Outcome of validating one stage."""

    stage: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: ValidationReport) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def summary(self) -> str:
        if self.errors:
            return f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        if self.warnings:
            return f"{len(self.warnings)} warning(s)"
        return "valid"


# ---------------------------------------------------------------------------
# Stage 1
# ---------------------------------------------------------------------------


def validate_analysis(
    analysis: RequirementAnalysis, issue: JiraIssue, ticket_key: str
) -> ValidationReport:
    """Schema, identifier, duplication and grounding checks for stage 1."""
    report = ValidationReport(stage="jira_analyst")

    if analysis.ticket_key != ticket_key:
        report.errors.append(
            f"ticket_key is '{analysis.ticket_key}' but this run analyses '{ticket_key}'."
        )
    if not analysis.requirements:
        report.errors.append(
            "No requirements were extracted. Every ticket with a description "
            "must yield at least one requirement, or the ticket must be "
            "reported as empty in missing_information."
        )

    _check_ids(report, [r.id for r in analysis.requirements], REQ_ID_RE, "requirement")
    _check_ids(
        report,
        [c.id for c in analysis.acceptance_criteria],
        AC_ID_RE,
        "acceptance criterion",
    )

    for requirement in analysis.requirements:
        if len(requirement.statement.strip()) < 8:
            report.errors.append(
                f"{requirement.id} has an empty or unusable statement."
            )

    known_reqs = set(analysis.requirement_ids)
    for criterion in analysis.acceptance_criteria:
        unknown = [rid for rid in criterion.requirement_ids if rid not in known_reqs]
        if unknown:
            report.warnings.append(
                f"{criterion.id} references unknown requirement ids: {', '.join(unknown)}."
            )

    if not analysis.acceptance_criteria and not analysis.missing_information:
        report.warnings.append(
            "No acceptance criteria and no missing_information entries. "
            "An absent acceptance criteria section should be reported as a gap."
        )

    ungrounded = _ungrounded_explicit_items(analysis, issue)
    for item_id in ungrounded:
        report.warnings.append(
            f"{item_id} is classified EXPLICIT but its wording was not found in "
            "the ticket text; it may be inferred rather than stated."
        )

    return report


def _ungrounded_explicit_items(
    analysis: RequirementAnalysis, issue: JiraIssue
) -> list[str]:
    """Flag EXPLICIT items whose significant words are absent from the ticket."""
    haystack = " ".join(
        [
            issue.summary,
            issue.description,
            issue.acceptance_criteria_raw,
            " ".join(comment.body for comment in issue.comments),
        ]
    ).lower()
    if len(haystack.strip()) < 40:
        return []

    flagged: list[str] = []
    explicit_items: list[tuple[str, str]] = [
        (req.id, req.statement)
        for req in analysis.requirements
        if req.classification is InfoClassification.EXPLICIT
    ] + [
        (criterion.id, criterion.statement)
        for criterion in analysis.explicit_acceptance_criteria
    ]

    for item_id, statement in explicit_items:
        tokens = [
            word
            for word in re.findall(r"[a-z0-9]{4,}", statement.lower())
            if word not in _STOPWORDS
        ]
        if len(tokens) < 3:
            continue
        hits = sum(1 for token in tokens if token in haystack)
        if hits / len(tokens) < 0.3:
            flagged.append(item_id)
    return flagged


# ---------------------------------------------------------------------------
# Stage 2
# ---------------------------------------------------------------------------


def validate_test_plan(
    plan: TestPlan, analysis: RequirementAnalysis, ticket_key: str
) -> ValidationReport:
    """Section completeness and identifier resolution checks for stage 2."""
    report = ValidationReport(stage="test_plan_writer")

    if plan.ticket_key != ticket_key:
        report.errors.append(
            f"ticket_key is '{plan.ticket_key}' but this run plans '{ticket_key}'."
        )

    numbers = [section.number for section in plan.sections]
    if len(plan.sections) != 12 or sorted(numbers) != list(range(1, 13)):
        report.errors.append(
            "The plan must contain exactly 12 sections numbered 1 to 12; got "
            f"{len(plan.sections)} section(s) numbered {sorted(numbers)}."
        )

    for section in plan.sections:
        if len(section.content.strip()) < _MIN_SECTION_CHARS:
            report.errors.append(
                f"Section {section.number} ('{section.title}') is empty or too short."
            )
        expected = (
            TEST_PLAN_SECTION_TITLES[section.number - 1]
            if 1 <= section.number <= 12
            else ""
        )
        if expected and _slug(section.title) != _slug(expected):
            report.warnings.append(
                f"Section {section.number} is titled '{section.title}' instead of "
                f"'{expected}'."
            )

    if not plan.scenarios:
        report.errors.append("The plan contains no high-level test scenarios.")

    known_reqs = set(analysis.requirement_ids)
    known_acs = set(analysis.acceptance_criteria_ids)
    for scenario in plan.scenarios:
        if not SC_ID_RE.match(scenario.id):
            report.warnings.append(
                f"Scenario id '{scenario.id}' does not follow the SC-001 format."
            )
        unknown_reqs = [r for r in scenario.requirement_ids if r not in known_reqs]
        unknown_acs = [a for a in scenario.acceptance_criteria_ids if a not in known_acs]
        if unknown_reqs or unknown_acs:
            report.errors.append(
                f"Scenario {scenario.id} references identifiers that do not exist "
                f"in the analysis: {', '.join(unknown_reqs + unknown_acs)}."
            )
        if not scenario.requirement_ids and not scenario.acceptance_criteria_ids:
            report.errors.append(
                f"Scenario {scenario.id} references no REQ or AC identifier."
            )

    covered = {rid for scenario in plan.scenarios for rid in scenario.requirement_ids}
    out_of_scope = next(
        (s.content.upper() for s in plan.sections if s.number == 4), ""
    )
    for requirement_id in known_reqs - covered:
        if requirement_id not in out_of_scope:
            report.warnings.append(
                f"{requirement_id} is not referenced by any scenario and is not "
                "listed as out of scope."
            )

    return report


# ---------------------------------------------------------------------------
# Stage 3
# ---------------------------------------------------------------------------


def validate_test_cases(
    suite: TestCaseSuite, analysis: RequirementAnalysis, ticket_key: str
) -> ValidationReport:
    """Identifier, traceability and acceptance-criteria coverage checks."""
    report = ValidationReport(stage="test_case_writer")

    if suite.ticket_key != ticket_key:
        report.errors.append(
            f"ticket_key is '{suite.ticket_key}' but this run covers '{ticket_key}'."
        )
    if not suite.test_cases:
        report.errors.append("The suite contains no test cases.")

    id_pattern = re.compile(rf"^{re.escape(ticket_key)}-TC-\d{{3,}}$")
    seen: set[str] = set()
    for case in suite.test_cases:
        if case.id in seen:
            report.errors.append(f"Duplicate test case id: {case.id}.")
        seen.add(case.id)
        if not id_pattern.match(case.id):
            report.errors.append(
                f"Test case id '{case.id}' must look like {ticket_key}-TC-001."
            )
        if case.ticket_key and case.ticket_key != ticket_key:
            report.errors.append(
                f"{case.id} carries ticket_key '{case.ticket_key}'."
            )
        if not case.steps:
            report.errors.append(f"{case.id} has no test steps.")
        if not case.expected_result.strip() and not any(
            step.expected_result.strip() for step in case.steps
        ):
            report.errors.append(f"{case.id} has no expected result.")
        if not case.title.strip():
            report.errors.append(f"{case.id} has no title.")

    known_reqs = set(analysis.requirement_ids)
    known_acs = set(analysis.acceptance_criteria_ids)
    for case in suite.test_cases:
        unknown = [r for r in case.requirement_ids if r not in known_reqs]
        unknown += [a for a in case.acceptance_criteria_ids if a not in known_acs]
        if unknown:
            report.errors.append(
                f"{case.id} references identifiers that do not exist in the "
                f"analysis: {', '.join(unknown)}."
            )
        if not case.requirement_ids and not case.acceptance_criteria_ids:
            report.warnings.append(f"{case.id} is not traced to any REQ or AC id.")
        if case.is_automatable and not case.automation_rationale.strip():
            report.warnings.append(
                f"{case.id} is marked automatable but gives no rationale."
            )

    covered_acs = {
        ac for case in suite.test_cases for ac in case.acceptance_criteria_ids
    }
    declared_gaps = set(suite.uncovered_acceptance_criteria)
    for criterion in analysis.explicit_acceptance_criteria:
        if criterion.id not in covered_acs and criterion.id not in declared_gaps:
            report.errors.append(
                f"Explicit acceptance criterion {criterion.id} has no test case "
                "and is not listed in uncovered_acceptance_criteria."
            )

    return report


# ---------------------------------------------------------------------------
# Stage 4
# ---------------------------------------------------------------------------


def normalise_bundle(bundle: PlaywrightBundle) -> PlaywrightBundle:
    """Mechanically clean generated code before validating it.

    Removes markdown fences that models add out of habit and normalises line
    endings. Anything that cannot be fixed mechanically is left for the
    validator to report.
    """
    for file in bundle.files:
        content = file.content.replace("\r\n", "\n").strip()
        content = re.sub(r"^```[A-Za-z0-9_+-]*[ \t]*\n", "", content)
        content = re.sub(r"\n?[ \t]*```\s*$", "", content)
        file.content = content.strip() + "\n"
    return bundle


def validate_playwright(
    bundle: PlaywrightBundle, suite: TestCaseSuite, ticket_key: str
) -> ValidationReport:
    """Structure, safety and traceability checks for generated automation."""
    report = ValidationReport(stage="playwright_coder")

    if bundle.ticket_key != ticket_key:
        report.errors.append(
            f"ticket_key is '{bundle.ticket_key}' but this run automates '{ticket_key}'."
        )

    automatable = suite.automatable_cases()
    if not automatable:
        if bundle.files:
            report.warnings.append(
                "No test case was marked automatable, but code was generated anyway."
            )
        return report

    if not bundle.files:
        report.errors.append(
            f"{len(automatable)} test case(s) are automatable but no file was generated."
        )
        return report

    if not bundle.spec_files:
        report.errors.append("No .spec.ts file was generated.")

    for file in bundle.files:
        content = file.content
        if not content.strip():
            report.errors.append(f"{file.path} is empty.")
            continue
        if "```" in content:
            report.errors.append(f"{file.path} still contains markdown fences.")
        for pattern, message in _FORBIDDEN_CODE_PATTERNS:
            if pattern.search(content):
                report.errors.append(f"{file.path} {message}.")
        if file.path.endswith(".spec.ts"):
            if "@playwright/test" not in content:
                report.errors.append(
                    f"{file.path} does not import from '@playwright/test'."
                )
            if "test(" not in content:
                report.errors.append(f"{file.path} declares no test().")
            if "expect(" not in content:
                report.warnings.append(f"{file.path} contains no expect() assertion.")
            if not re.search(r"getBy(Role|Label|Placeholder|TestId|Text)", content):
                report.warnings.append(
                    f"{file.path} uses no getByRole/getByLabel/getByTestId locator."
                )

    case_ids = set(suite.case_ids)
    mapped: set[str] = set()
    for mapping in bundle.mappings:
        if mapping.test_case_id and mapping.test_case_id not in case_ids:
            report.errors.append(
                f"Mapping references unknown test case id {mapping.test_case_id}."
            )
        else:
            mapped.add(mapping.test_case_id)

    missing = [case.id for case in automatable if case.id not in mapped]
    if missing:
        report.warnings.append(
            "Automatable test cases without a Playwright mapping: "
            f"{', '.join(missing[:10])}."
        )

    if bundle.readiness is AutomationReadiness.READY and bundle.missing_information:
        report.errors.append(
            "readiness is READY but missing_information is not empty. Set "
            "NEEDS_CONFIGURATION or clear the missing information."
        )
    if bundle.readiness is AutomationReadiness.NEEDS_CONFIGURATION and not (
        bundle.missing_information
        or any(_PLACEHOLDER_ENV_RE.search(file.content) for file in bundle.files)
    ):
        report.warnings.append(
            "readiness is NEEDS_CONFIGURATION but nothing was listed as missing."
        )
    if not bundle.setup_notes.strip():
        report.warnings.append("setup_notes is empty.")

    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_ids(
    report: ValidationReport,
    ids: list[str],
    pattern: re.Pattern[str],
    label: str,
) -> None:
    seen: set[str] = set()
    for identifier in ids:
        if identifier in seen:
            report.errors.append(f"Duplicate {label} id: {identifier}.")
        seen.add(identifier)
        if not pattern.match(identifier):
            report.errors.append(
                f"Malformed {label} id '{identifier}'; expected the "
                f"{pattern.pattern.strip('^$').replace(chr(92) + 'd', 'N')} format."
            )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())
