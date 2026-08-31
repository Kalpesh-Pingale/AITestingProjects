"""Builders for valid stage outputs, shared by the unit and UI tests."""

from __future__ import annotations

from jira_qa_crew.models import (
    TEST_PLAN_SECTION_TITLES,
    AcceptanceCriterion,
    AutomationCandidate,
    AutomationMapping,
    AutomationReadiness,
    JiraIssue,
    PlaywrightBundle,
    PlaywrightFile,
    Priority,
    ProviderSource,
    Requirement,
    RequirementAnalysis,
    RunResult,
    TestCase,
    TestCaseSuite,
    TestPlan,
    TestPlanSection,
    TestScenario,
    TestStep,
    TicketResult,
    TicketStatus,
)

TICKET = "VWO-48"

SPEC_SOURCE = """import { test, expect } from '@playwright/test';

const RESET_PATH = process.env.RESET_PATH ?? '/reset-password';

test.describe('VWO-48 password reset link expiry', () => {
  // Jira: VWO-48 | Case: VWO-48-TC-001 | REQ: REQ-001 | AC: AC-001
  test('VWO-48-TC-001: a fresh link opens the set-password form', async ({ page }) => {
    await test.step('open the reset link', async () => {
      await page.goto(RESET_PATH);
    });
    await expect(page.getByRole('heading', { name: 'Set a new password' })).toBeVisible();
  });
});
"""


def make_issue(key: str = TICKET, source: ProviderSource = ProviderSource.REST) -> JiraIssue:
    return JiraIssue(
        key=key,
        summary="Password reset link must expire after 15 minutes",
        description=(
            "Password reset links currently stay valid for 24 hours. The link "
            "must expire 15 minutes after it is issued and show the message "
            "'This link has expired. Request a new one.'"
        ),
        issue_type="Story",
        status="In Progress",
        priority="High",
        labels=["security"],
        components=["Account Management"],
        acceptance_criteria_raw=(
            "Given a reset link issued less than 15 minutes ago, when the user "
            "opens it, then the set-new-password form is shown."
        ),
        url="https://example.atlassian.net/browse/" + key,
        source=source,
    )


def make_analysis(key: str = TICKET) -> RequirementAnalysis:
    return RequirementAnalysis(
        ticket_key=key,
        summary="Password reset link must expire after 15 minutes",
        issue_type="Story",
        status="In Progress",
        priority="High",
        description_digest="The reset link must expire fifteen minutes after issue.",
        requirements=[
            Requirement(
                id="REQ-001",
                statement="A password reset link expires 15 minutes after it is issued.",
                source="description",
            ),
            Requirement(
                id="REQ-002",
                statement="An expired reset link shows 'This link has expired. Request a new one.'",
                source="description",
            ),
        ],
        acceptance_criteria=[
            AcceptanceCriterion(
                id="AC-001",
                statement=(
                    "Given a reset link issued less than 15 minutes ago, when the "
                    "user opens it, then the set-new-password form is shown."
                ),
                requirement_ids=["REQ-001"],
            ),
        ],
        missing_information=["The exact reset URL path is not stated in the ticket."],
        open_questions=["Which environment hosts the reset page?"],
        provider_source=ProviderSource.REST,
    )


def make_test_plan(key: str = TICKET) -> TestPlan:
    return TestPlan(
        ticket_key=key,
        title=f"Test Plan - {key}",
        sections=[
            TestPlanSection(
                number=index + 1,
                title=title,
                content=(
                    f"Content for {title} that is specific to {key} and long "
                    "enough to pass the deterministic minimum length check."
                ),
            )
            for index, title in enumerate(TEST_PLAN_SECTION_TITLES)
        ],
        scenarios=[
            TestScenario(
                id="SC-001",
                title="Reset link expiry window",
                requirement_ids=["REQ-001"],
                acceptance_criteria_ids=["AC-001"],
                test_types=["Functional"],
                priority=Priority.HIGH,
            ),
            TestScenario(
                id="SC-002",
                title="Expired link messaging",
                requirement_ids=["REQ-002"],
                test_types=["Negative"],
            ),
        ],
    )


def make_suite(key: str = TICKET) -> TestCaseSuite:
    return TestCaseSuite(
        ticket_key=key,
        test_cases=[
            TestCase(
                id=f"{key}-TC-001",
                ticket_key=key,
                requirement_ids=["REQ-001"],
                acceptance_criteria_ids=["AC-001"],
                title="A fresh reset link opens the set-password form",
                objective="Verify a link younger than 15 minutes is accepted.",
                priority=Priority.HIGH,
                test_type="Happy path",
                preconditions=["A reset email was requested less than a minute ago."],
                test_data=["A registered account."],
                steps=[
                    TestStep(step_number=1, action="Open the reset link.", expected_result="The form loads."),
                ],
                expected_result="The set-new-password form is shown.",
                automation_candidate=AutomationCandidate.YES,
                automation_rationale="Deterministic UI flow.",
                tags=["auth"],
            ),
            TestCase(
                id=f"{key}-TC-002",
                ticket_key=key,
                requirement_ids=["REQ-002"],
                title="An expired reset link is rejected",
                objective="Verify the expiry message.",
                priority=Priority.HIGH,
                test_type="Negative",
                steps=[
                    TestStep(step_number=1, action="Open a 16 minute old link.", expected_result="Error is shown."),
                ],
                expected_result="'This link has expired. Request a new one.' is shown.",
                automation_candidate=AutomationCandidate.NO,
                automation_rationale="Requires clock manipulation.",
            ),
        ],
        coverage_notes="Every explicit acceptance criterion has a positive test.",
    )


def make_bundle(key: str = TICKET) -> PlaywrightBundle:
    return PlaywrightBundle(
        ticket_key=key,
        files=[
            PlaywrightFile(
                path=f"tests/{key.lower()}.spec.ts", content=SPEC_SOURCE, kind="spec"
            )
        ],
        mappings=[
            AutomationMapping(
                test_case_id=f"{key}-TC-001",
                spec_file=f"tests/{key.lower()}.spec.ts",
                test_title=f"{key}-TC-001: a fresh link opens the set-password form",
                requirement_ids=["REQ-001"],
                acceptance_criteria_ids=["AC-001"],
            )
        ],
        readiness=AutomationReadiness.NEEDS_CONFIGURATION,
        missing_information=["The reset page path is not documented in the ticket."],
        setup_notes="npm i -D @playwright/test && npx playwright install",
        coverage_notes="One of one automatable cases covered.",
    )


def make_ticket_result(key: str = TICKET, status: TicketStatus = TicketStatus.COMPLETED_WITH_WARNINGS) -> TicketResult:
    from jira_qa_crew.services.traceability import build_traceability

    analysis = make_analysis(key)
    suite = make_suite(key)
    bundle = make_bundle(key)
    ticket = TicketResult(
        ticket_key=key,
        status=status,
        provider_source=ProviderSource.REST,
        issue=make_issue(key),
        analysis=analysis,
        test_plan=make_test_plan(key),
        test_cases=suite,
        playwright=bundle,
        traceability=build_traceability(analysis, suite, bundle),
        warnings=["[playwright_coder] readiness is NEEDS_CONFIGURATION."],
    )
    for stage in ticket.stages:
        stage.status = stage.status.__class__.COMPLETED
        stage.message = "done"
    return ticket


def make_run_result(keys: list[str] | None = None) -> RunResult:
    keys = keys or [TICKET]
    return RunResult(
        run_id="RUN-20260831-101500",
        requested_keys=keys,
        integration_mode="auto",
        tickets=[make_ticket_result(key) for key in keys],
    )
