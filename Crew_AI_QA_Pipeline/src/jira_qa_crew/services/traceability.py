"""Deterministic traceability and coverage.

Coverage is computed in Python from the validated objects. The LLM never
reports its own coverage numbers.
"""

from __future__ import annotations

from jira_qa_crew.models import (
    AutomationReadiness,
    CoverageMetrics,
    CoverageStatus,
    PlaywrightBundle,
    RequirementAnalysis,
    TestCase,
    TestCaseSuite,
    TraceabilityMatrix,
    TraceabilityRow,
)


def build_traceability(
    analysis: RequirementAnalysis,
    suite: TestCaseSuite | None,
    bundle: PlaywrightBundle | None,
) -> TraceabilityMatrix:
    """Cross-reference requirements, acceptance criteria, tests and automation."""
    cases: list[TestCase] = list(suite.test_cases) if suite else []
    automated_ids = {
        mapping.test_case_id for mapping in (bundle.mappings if bundle else [])
    }
    readiness = bundle.readiness if bundle else AutomationReadiness.NOT_APPLICABLE

    cases_by_req: dict[str, list[str]] = {}
    cases_by_ac: dict[str, list[str]] = {}
    for case in cases:
        for req_id in case.requirement_ids:
            cases_by_req.setdefault(req_id, []).append(case.id)
        for ac_id in case.acceptance_criteria_ids:
            cases_by_ac.setdefault(ac_id, []).append(case.id)

    ac_text = {c.id: c.statement for c in analysis.acceptance_criteria}
    req_text = {r.id: r.statement for r in analysis.requirements}
    acs_by_req: dict[str, list[str]] = {}
    for criterion in analysis.acceptance_criteria:
        if criterion.requirement_ids:
            for req_id in criterion.requirement_ids:
                acs_by_req.setdefault(req_id, []).append(criterion.id)
        else:
            acs_by_req.setdefault("", []).append(criterion.id)

    rows: list[TraceabilityRow] = []
    for requirement in analysis.requirements:
        linked_acs = acs_by_req.get(requirement.id, [])
        if not linked_acs:
            rows.append(
                _row(
                    requirement_id=requirement.id,
                    requirement_text=requirement.statement,
                    ac_id="",
                    ac_text_value="",
                    case_ids=sorted(set(cases_by_req.get(requirement.id, []))),
                    automated_ids=automated_ids,
                    cases=cases,
                    readiness=readiness,
                )
            )
            continue
        for ac_id in linked_acs:
            case_ids = sorted(
                set(cases_by_ac.get(ac_id, []))
                | set(cases_by_req.get(requirement.id, []))
            )
            rows.append(
                _row(
                    requirement_id=requirement.id,
                    requirement_text=requirement.statement,
                    ac_id=ac_id,
                    ac_text_value=ac_text.get(ac_id, ""),
                    case_ids=case_ids,
                    automated_ids=automated_ids,
                    cases=cases,
                    readiness=readiness,
                )
            )

    # Acceptance criteria that are not attached to any requirement.
    for ac_id in acs_by_req.get("", []):
        rows.append(
            _row(
                requirement_id="",
                requirement_text="",
                ac_id=ac_id,
                ac_text_value=ac_text.get(ac_id, ""),
                case_ids=sorted(set(cases_by_ac.get(ac_id, []))),
                automated_ids=automated_ids,
                cases=cases,
                readiness=readiness,
            )
        )

    metrics = _metrics(
        cases=cases,
        automated_ids=automated_ids,
        cases_by_req=cases_by_req,
        cases_by_ac=cases_by_ac,
        known_reqs=set(req_text),
        known_acs=set(ac_text),
    )
    return TraceabilityMatrix(
        ticket_key=analysis.ticket_key, rows=rows, metrics=metrics
    )


def _row(
    *,
    requirement_id: str,
    requirement_text: str,
    ac_id: str,
    ac_text_value: str,
    case_ids: list[str],
    automated_ids: set[str],
    cases: list[TestCase],
    readiness: AutomationReadiness,
) -> TraceabilityRow:
    automated = sorted(case_id for case_id in case_ids if case_id in automated_ids)
    by_id = {case.id: case for case in cases}
    automatable = [
        case_id for case_id in case_ids if by_id.get(case_id) and by_id[case_id].is_automatable
    ]

    if not case_ids:
        status = CoverageStatus.NOT_COVERED
        reason = "No test case references this item."
    elif automatable and not automated:
        status = CoverageStatus.PARTIAL
        reason = (
            "Manual coverage exists; the automatable case(s) "
            f"{', '.join(automatable)} have no generated Playwright test."
        )
    elif automated and readiness is AutomationReadiness.NEEDS_CONFIGURATION:
        status = CoverageStatus.PARTIAL
        reason = (
            "Automation was generated but the bundle is NEEDS_CONFIGURATION, "
            "so the automated coverage is not yet executable."
        )
    else:
        status = CoverageStatus.COVERED
        reason = (
            "Covered by " + ", ".join(case_ids)
            if not automated
            else "Covered and automated by " + ", ".join(automated)
        )

    return TraceabilityRow(
        requirement_id=requirement_id,
        requirement_text=requirement_text,
        acceptance_criterion_id=ac_id,
        acceptance_criterion_text=ac_text_value,
        test_case_ids=case_ids,
        automated_test_case_ids=automated,
        coverage_status=status,
        reason=reason,
    )


def _metrics(
    *,
    cases: list[TestCase],
    automated_ids: set[str],
    cases_by_req: dict[str, list[str]],
    cases_by_ac: dict[str, list[str]],
    known_reqs: set[str],
    known_acs: set[str],
) -> CoverageMetrics:
    automatable = [case for case in cases if case.is_automatable]
    orphan_cases = [
        case.id
        for case in cases
        if not case.requirement_ids and not case.acceptance_criteria_ids
    ]
    return CoverageMetrics(
        total_requirements=len(known_reqs),
        covered_requirements=len([r for r in known_reqs if cases_by_req.get(r)]),
        total_acceptance_criteria=len(known_acs),
        covered_acceptance_criteria=len([a for a in known_acs if cases_by_ac.get(a)]),
        total_test_cases=len(cases),
        automatable_test_cases=len(automatable),
        automated_test_cases=len(
            [case for case in automatable if case.id in automated_ids]
        ),
        orphan_requirements=sorted(r for r in known_reqs if not cases_by_req.get(r)),
        orphan_acceptance_criteria=sorted(
            a for a in known_acs if not cases_by_ac.get(a)
        ),
        orphan_test_cases=sorted(orphan_cases),
    )
