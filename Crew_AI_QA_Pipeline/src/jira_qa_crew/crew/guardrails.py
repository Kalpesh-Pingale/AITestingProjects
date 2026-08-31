"""Task guardrails: deterministic validation wired into CrewAI.

Each guardrail runs the matching validator from
:mod:`jira_qa_crew.services.validation` against the structured output of a
task. Errors make the guardrail fail, which CrewAI turns into exactly one
repair attempt (``guardrail_max_retries=1``) before the stage fails for good.
Warnings never block; they are collected for the UI and the artifacts.
"""

# NOTE: this module deliberately does not use `from __future__ import
# annotations`. CrewAI validates a guardrail by reading its return annotation
# with inspect.signature(), which sees a plain string when annotations are
# postponed and then rejects the callable. The annotations here must stay as
# real runtime objects.

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from jira_qa_crew.crew.callbacks import StageTracker
from jira_qa_crew.models import (
    JiraIssue,
    PlaywrightBundle,
    RequirementAnalysis,
    TestCaseSuite,
    TestPlan,
)
from jira_qa_crew.services.validation import (
    ValidationReport,
    normalise_bundle,
    validate_analysis,
    validate_playwright,
    validate_test_cases,
    validate_test_plan,
)


@dataclass
class TicketCrewContext:
    """Mutable per-ticket state shared by the four guardrails.

    A fresh instance is created for every ticket, which is what keeps one
    ticket's requirements out of another ticket's artifacts.
    """

    ticket_key: str
    issue: JiraIssue
    analysis: RequirementAnalysis | None = None
    test_plan: TestPlan | None = None
    test_cases: TestCaseSuite | None = None
    playwright: PlaywrightBundle | None = None
    reports: dict[str, ValidationReport] = field(default_factory=dict)

    def warnings(self) -> list[str]:
        collected: list[str] = []
        for stage, report in self.reports.items():
            collected.extend(f"[{stage}] {warning}" for warning in report.warnings)
        return collected


GuardrailResult = tuple[bool, Any]


def _extract(output: Any, model: type[BaseModel]) -> BaseModel | None:
    """Pull the structured object out of a CrewAI task output."""
    candidate = getattr(output, "pydantic", None)
    if isinstance(candidate, model):
        return candidate
    json_dict = getattr(output, "json_dict", None)
    if isinstance(json_dict, dict):
        try:
            return model.model_validate(json_dict)
        except Exception:  # noqa: BLE001 - reported as a guardrail failure
            return None
    return None


def _failure(model_name: str) -> str:
    return (
        f"The output could not be parsed into a valid {model_name} object. "
        "Return one JSON object that matches the schema exactly, with no "
        "surrounding prose or markdown."
    )


def _finish(
    context: TicketCrewContext,
    tracker: StageTracker | None,
    report: ValidationReport,
    stage_key: str,
    detail: str,
) -> GuardrailResult:
    context.reports[stage_key] = report
    if not report.ok:
        if tracker is not None:
            tracker.activity(f"{stage_key}: validation failed - {report.summary()}")
        return False, "\n".join(report.errors)
    if tracker is not None:
        tracker.complete(stage_key, detail, report.warnings)
    return True, detail


def analysis_guardrail(
    context: TicketCrewContext, tracker: StageTracker | None = None
) -> Callable[[Any], GuardrailResult]:
    """Validate stage 1 output and store it on the context."""

    def guardrail(output: Any) -> tuple[bool, Any]:
        analysis = _extract(output, RequirementAnalysis)
        if analysis is None:
            return False, _failure("RequirementAnalysis")
        analysis.ticket_key = analysis.ticket_key or context.ticket_key
        report = validate_analysis(analysis, context.issue, context.ticket_key)
        if report.ok:
            context.analysis = analysis
        return _finish(
            context,
            tracker,
            report,
            "jira_analyst",
            f"{len(analysis.requirements)} requirement(s), "
            f"{len(analysis.acceptance_criteria)} acceptance criterion/criteria",
        )

    return guardrail


def test_plan_guardrail(
    context: TicketCrewContext, tracker: StageTracker | None = None
) -> Callable[[Any], GuardrailResult]:
    """Validate stage 2 output against the validated analysis."""

    def guardrail(output: Any) -> tuple[bool, Any]:
        plan = _extract(output, TestPlan)
        if plan is None:
            return False, _failure("TestPlan")
        if context.analysis is None:
            return False, "The requirement analysis is missing; stage 1 must run first."
        plan.ticket_key = plan.ticket_key or context.ticket_key
        report = validate_test_plan(plan, context.analysis, context.ticket_key)
        if report.ok:
            context.test_plan = plan
        return _finish(
            context,
            tracker,
            report,
            "test_plan_writer",
            f"12 sections, {len(plan.scenarios)} scenario(s)",
        )

    return guardrail


def test_cases_guardrail(
    context: TicketCrewContext, tracker: StageTracker | None = None
) -> Callable[[Any], GuardrailResult]:
    """Validate stage 3 output against the validated analysis."""

    def guardrail(output: Any) -> tuple[bool, Any]:
        suite = _extract(output, TestCaseSuite)
        if suite is None:
            return False, _failure("TestCaseSuite")
        if context.analysis is None:
            return False, "The requirement analysis is missing; stage 1 must run first."
        suite.ticket_key = suite.ticket_key or context.ticket_key
        for case in suite.test_cases:
            case.ticket_key = case.ticket_key or context.ticket_key
        report = validate_test_cases(suite, context.analysis, context.ticket_key)
        if report.ok:
            context.test_cases = suite
        return _finish(
            context,
            tracker,
            report,
            "test_case_writer",
            f"{len(suite.test_cases)} test case(s), "
            f"{len(suite.automatable_cases())} automatable",
        )

    return guardrail


def playwright_guardrail(
    context: TicketCrewContext, tracker: StageTracker | None = None
) -> Callable[[Any], GuardrailResult]:
    """Validate stage 4 output against the validated test case suite."""

    def guardrail(output: Any) -> tuple[bool, Any]:
        bundle = _extract(output, PlaywrightBundle)
        if bundle is None:
            return False, _failure("PlaywrightBundle")
        if context.test_cases is None:
            return False, "The test case suite is missing; stage 3 must run first."
        bundle.ticket_key = bundle.ticket_key or context.ticket_key
        bundle = normalise_bundle(bundle)
        report = validate_playwright(bundle, context.test_cases, context.ticket_key)
        if report.ok:
            context.playwright = bundle
        return _finish(
            context,
            tracker,
            report,
            "playwright_coder",
            f"{len(bundle.files)} file(s), readiness {bundle.readiness.value}",
        )

    return guardrail
