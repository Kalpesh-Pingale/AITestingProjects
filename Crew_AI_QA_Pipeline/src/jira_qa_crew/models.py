"""Pydantic models shared by the providers, the crew and the renderers.

Three families of models live here:

* **Transport models** (:class:`JiraIssue`) - what a Jira provider returns.
* **Agent output models** (:class:`RequirementAnalysis`, :class:`TestPlan`,
  :class:`TestCaseSuite`, :class:`PlaywrightBundle`) - the structured output
  contract for each CrewAI stage. These are the internal source of truth;
  raw LLM markdown is never used for rendering.
* **Run models** (:class:`TicketResult`, :class:`RunResult`) - deterministic
  pipeline bookkeeping.

Validators are deliberately forgiving about formatting (case, ``REQ-1`` vs
``REQ-001``) and strict about structure. Anything a validator cannot repair
mechanically is reported by :mod:`jira_qa_crew.services.validation` so the
pipeline can attempt one controlled repair pass.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class InfoClassification(str, Enum):
    """Where a piece of information came from."""

    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"
    MISSING = "MISSING"
    ASSUMPTION_REQUIRING_CONFIRMATION = "ASSUMPTION_REQUIRING_CONFIRMATION"


class RequirementCategory(str, Enum):
    """Coarse requirement bucket used for grouping and reporting."""

    FUNCTIONAL = "FUNCTIONAL"
    NON_FUNCTIONAL = "NON_FUNCTIONAL"
    BUSINESS_RULE = "BUSINESS_RULE"
    CONSTRAINT = "CONSTRAINT"
    DEPENDENCY = "DEPENDENCY"


class Priority(str, Enum):
    """Test priority."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AutomationCandidate(str, Enum):
    """Whether a test case should be automated."""

    YES = "YES"
    NO = "NO"
    PARTIAL = "PARTIAL"


class AutomationReadiness(str, Enum):
    """Whether generated Playwright code can run without further input."""

    READY = "READY"
    NEEDS_CONFIGURATION = "NEEDS_CONFIGURATION"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProviderSource(str, Enum):
    """Which provider actually produced a Jira issue."""

    MCP = "MCP"
    REST = "REST"
    DEMO = "DEMO"


class StageStatus(str, Enum):
    """Lifecycle of a single pipeline stage."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    WARNING = "WARNING"
    FAILED = "FAILED"


class TicketStatus(str, Enum):
    """Outcome of a whole ticket."""

    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    FAILED = "FAILED"


class CoverageStatus(str, Enum):
    """Coverage verdict for a traceability row."""

    COVERED = "COVERED"
    PARTIAL = "PARTIAL"
    NOT_COVERED = "NOT_COVERED"


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*?)-(\d+)$")


def normalise_identifier(value: str, prefix: str, width: int = 3) -> str:
    """Normalise ``req-1`` / ``REQ 1`` / ``REQ-001`` to ``REQ-001``.

    Values that do not look like ``<prefix>-<number>`` are returned trimmed
    and upper-cased so that deterministic validation can flag them.
    """
    text = str(value or "").strip().replace(" ", "-").replace("_", "-")
    if not text:
        return ""
    match = _ID_RE.match(text)
    if not match:
        return text.upper()
    body, number = match.groups()
    body = body.upper()
    if body == prefix.upper():
        return f"{prefix.upper()}-{int(number):0{width}d}"
    return f"{body}-{number}"


def _normalise_id_list(values: list[str] | None, prefix: str) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        ident = normalise_identifier(value, prefix)
        if ident and ident not in seen:
            seen.append(ident)
    return seen


def _coerce_enum(enum_cls: type[Enum], value: Any, default: Enum) -> Enum:
    """Best-effort mapping of loose LLM strings onto an enum member."""
    if isinstance(value, enum_cls):
        return value
    text = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    if not text:
        return default
    for member in enum_cls:
        if text == member.value or text == member.name:
            return member
    aliases: dict[str, str] = {
        "P0": "CRITICAL",
        "P1": "HIGH",
        "P2": "MEDIUM",
        "P3": "LOW",
        "BLOCKER": "CRITICAL",
        "HIGHEST": "CRITICAL",
        "MAJOR": "HIGH",
        "MINOR": "LOW",
        "LOWEST": "LOW",
        "TRIVIAL": "LOW",
        "TRUE": "YES",
        "FALSE": "NO",
        "Y": "YES",
        "N": "NO",
        "NONE": "NO",
        "FULL": "YES",
        "NONFUNCTIONAL": "NON_FUNCTIONAL",
        "NFR": "NON_FUNCTIONAL",
        "ASSUMPTION": "ASSUMPTION_REQUIRING_CONFIRMATION",
        "NEEDS_CONFIG": "NEEDS_CONFIGURATION",
        "NOT_READY": "NEEDS_CONFIGURATION",
    }
    mapped = aliases.get(text)
    if mapped:
        for member in enum_cls:
            if member.value == mapped:
                return member
    return default


def utc_now() -> datetime:
    """Timezone aware ``now`` used for every timestamp in the app."""
    return datetime.now(UTC)


class _Base(BaseModel):
    """Shared model configuration."""

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        use_enum_values=False,
        validate_assignment=False,
    )


# ---------------------------------------------------------------------------
# Jira transport models
# ---------------------------------------------------------------------------


class JiraComment(_Base):
    """A single Jira comment rendered to plain text."""

    author: str = ""
    created: str = ""
    body: str = ""


class JiraIssue(_Base):
    """Normalised Jira issue returned by a provider.

    ``raw`` keeps the provider payload for the run details tab; it is never
    fed to the LLM verbatim.
    """

    key: str
    summary: str = ""
    description: str = ""
    issue_type: str = ""
    status: str = ""
    priority: str = ""
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    parent_key: str = ""
    subtasks: list[str] = Field(default_factory=list)
    linked_issues: list[str] = Field(default_factory=list)
    acceptance_criteria_raw: str = ""
    comments: list[JiraComment] = Field(default_factory=list)
    url: str = ""
    source: ProviderSource = ProviderSource.REST
    fetched_at: datetime = Field(default_factory=utc_now)
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @field_validator("key")
    @classmethod
    def _upper_key(cls, value: str) -> str:
        return str(value or "").strip().upper()


# ---------------------------------------------------------------------------
# Stage 1 - requirement analysis
# ---------------------------------------------------------------------------


class ClassifiedItem(_Base):
    """A short statement plus where it came from."""

    id: str = Field(default="", description="Optional stable id, e.g. BR-001.")
    statement: str = Field(description="One sentence describing the item.")
    classification: InfoClassification = Field(
        default=InfoClassification.EXPLICIT,
        description="EXPLICIT, INFERRED, MISSING or ASSUMPTION_REQUIRING_CONFIRMATION.",
    )
    source: str = Field(
        default="",
        description="Jira field or text fragment this item was taken from.",
    )

    @field_validator("classification", mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        return _coerce_enum(InfoClassification, value, InfoClassification.EXPLICIT)


class Requirement(_Base):
    """One testable requirement extracted from the ticket."""

    id: str = Field(description="Stable identifier such as REQ-001.")
    statement: str = Field(description="The requirement in one sentence.")
    category: RequirementCategory = Field(default=RequirementCategory.FUNCTIONAL)
    classification: InfoClassification = Field(default=InfoClassification.EXPLICIT)
    source: str = Field(default="", description="Originating Jira field.")

    @field_validator("id")
    @classmethod
    def _norm_id(cls, value: str) -> str:
        return normalise_identifier(value, "REQ")

    @field_validator("category", mode="before")
    @classmethod
    def _coerce_category(cls, value: Any) -> Any:
        return _coerce_enum(
            RequirementCategory, value, RequirementCategory.FUNCTIONAL
        )

    @field_validator("classification", mode="before")
    @classmethod
    def _coerce_classification(cls, value: Any) -> Any:
        return _coerce_enum(InfoClassification, value, InfoClassification.EXPLICIT)


class AcceptanceCriterion(_Base):
    """One acceptance criterion, ideally quoted from the ticket."""

    id: str = Field(description="Stable identifier such as AC-001.")
    statement: str = Field(description="The acceptance criterion.")
    requirement_ids: list[str] = Field(
        default_factory=list, description="Related REQ ids."
    )
    classification: InfoClassification = Field(default=InfoClassification.EXPLICIT)

    @field_validator("id")
    @classmethod
    def _norm_id(cls, value: str) -> str:
        return normalise_identifier(value, "AC")

    @field_validator("requirement_ids")
    @classmethod
    def _norm_reqs(cls, value: list[str]) -> list[str]:
        return _normalise_id_list(value, "REQ")

    @field_validator("classification", mode="before")
    @classmethod
    def _coerce_classification(cls, value: Any) -> Any:
        return _coerce_enum(InfoClassification, value, InfoClassification.EXPLICIT)


class RequirementAnalysis(_Base):
    """Structured output of the Jira Analyst agent."""

    ticket_key: str
    summary: str = ""
    issue_type: str = ""
    status: str = ""
    priority: str = ""
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    parent_key: str = ""
    subtasks: list[str] = Field(default_factory=list)
    linked_issues: list[str] = Field(default_factory=list)
    description_digest: str = Field(
        default="", description="Neutral 3-6 sentence restatement of the ticket."
    )
    requirements: list[Requirement] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    business_rules: list[ClassifiedItem] = Field(default_factory=list)
    non_functional_requirements: list[ClassifiedItem] = Field(default_factory=list)
    dependencies: list[ClassifiedItem] = Field(default_factory=list)
    constraints: list[ClassifiedItem] = Field(default_factory=list)
    risks: list[ClassifiedItem] = Field(default_factory=list)
    assumptions: list[ClassifiedItem] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    provider_source: ProviderSource = ProviderSource.REST
    analysed_at: datetime = Field(default_factory=utc_now)

    @field_validator("ticket_key")
    @classmethod
    def _upper(cls, value: str) -> str:
        return str(value or "").strip().upper()

    @property
    def requirement_ids(self) -> list[str]:
        return [req.id for req in self.requirements]

    @property
    def acceptance_criteria_ids(self) -> list[str]:
        return [criterion.id for criterion in self.acceptance_criteria]

    @property
    def explicit_acceptance_criteria(self) -> list[AcceptanceCriterion]:
        return [
            criterion
            for criterion in self.acceptance_criteria
            if criterion.classification is InfoClassification.EXPLICIT
        ]


# ---------------------------------------------------------------------------
# Stage 2 - test plan
# ---------------------------------------------------------------------------

TEST_PLAN_SECTION_TITLES: tuple[str, ...] = (
    "Executive Summary",
    "Test Objectives",
    "In Scope",
    "Out of Scope",
    "Requirements and Acceptance-Criteria Coverage",
    "Test Strategy, Levels, and Test Types",
    "Test Environment, Tools, and Browser Coverage",
    "Test Data Requirements",
    "High-Level Test Scenarios",
    "Entry and Exit Criteria",
    "Risks, Dependencies, Assumptions, and Mitigations",
    "Execution, Defect Management, Reporting, and Deliverables",
)


class TestPlanSection(_Base):
    """One of the twelve mandated test plan sections."""

    # Not a pytest test class.
    __test__ = False

    number: int = Field(ge=1, le=12, description="Section number, 1-12.")
    title: str = Field(description="Section title.")
    content: str = Field(description="Markdown body for the section.")


class TestScenario(_Base):
    """High level scenario referenced by section 9 of the plan."""

    # Not a pytest test class.
    __test__ = False

    id: str = Field(description="Stable identifier such as SC-001.")
    title: str
    description: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    acceptance_criteria_ids: list[str] = Field(default_factory=list)
    test_types: list[str] = Field(default_factory=list)
    priority: Priority = Priority.MEDIUM

    @field_validator("id")
    @classmethod
    def _norm_id(cls, value: str) -> str:
        return normalise_identifier(value, "SC")

    @field_validator("requirement_ids")
    @classmethod
    def _norm_reqs(cls, value: list[str]) -> list[str]:
        return _normalise_id_list(value, "REQ")

    @field_validator("acceptance_criteria_ids")
    @classmethod
    def _norm_acs(cls, value: list[str]) -> list[str]:
        return _normalise_id_list(value, "AC")

    @field_validator("priority", mode="before")
    @classmethod
    def _coerce_priority(cls, value: Any) -> Any:
        return _coerce_enum(Priority, value, Priority.MEDIUM)


class TestPlan(_Base):
    """Structured output of the Test Plan Writer agent."""

    # Not a pytest test class.
    __test__ = False

    ticket_key: str
    title: str = ""
    sections: list[TestPlanSection] = Field(default_factory=list)
    scenarios: list[TestScenario] = Field(default_factory=list)

    @field_validator("ticket_key")
    @classmethod
    def _upper(cls, value: str) -> str:
        return str(value or "").strip().upper()

    @model_validator(mode="after")
    def _sort_sections(self) -> TestPlan:
        self.sections.sort(key=lambda section: section.number)
        return self


# ---------------------------------------------------------------------------
# Stage 3 - test cases
# ---------------------------------------------------------------------------


class TestStep(_Base):
    """One ordered step of a test case."""

    # Not a pytest test class.
    __test__ = False

    step_number: int = Field(ge=1)
    action: str
    expected_result: str = ""


class TestCase(_Base):
    """A single detailed, traceable test case."""

    # Not a pytest test class.
    __test__ = False

    id: str = Field(description="Identifier such as VWO-48-TC-001.")
    ticket_key: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    acceptance_criteria_ids: list[str] = Field(default_factory=list)
    title: str
    objective: str = ""
    priority: Priority = Priority.MEDIUM
    test_type: str = Field(
        default="Functional",
        description="Happy path, Negative, Boundary, Accessibility, API, ...",
    )
    preconditions: list[str] = Field(default_factory=list)
    test_data: list[str] = Field(default_factory=list)
    steps: list[TestStep] = Field(default_factory=list)
    expected_result: str = ""
    automation_candidate: AutomationCandidate = AutomationCandidate.NO
    automation_rationale: str = ""
    tags: list[str] = Field(default_factory=list)
    assumptions_or_blockers: list[str] = Field(default_factory=list)

    @field_validator("id", "ticket_key")
    @classmethod
    def _upper(cls, value: str) -> str:
        return str(value or "").strip().upper()

    @field_validator("requirement_ids")
    @classmethod
    def _norm_reqs(cls, value: list[str]) -> list[str]:
        return _normalise_id_list(value, "REQ")

    @field_validator("acceptance_criteria_ids")
    @classmethod
    def _norm_acs(cls, value: list[str]) -> list[str]:
        return _normalise_id_list(value, "AC")

    @field_validator("priority", mode="before")
    @classmethod
    def _coerce_priority(cls, value: Any) -> Any:
        return _coerce_enum(Priority, value, Priority.MEDIUM)

    @field_validator("automation_candidate", mode="before")
    @classmethod
    def _coerce_automation(cls, value: Any) -> Any:
        return _coerce_enum(AutomationCandidate, value, AutomationCandidate.NO)

    @model_validator(mode="after")
    def _renumber_steps(self) -> TestCase:
        for index, step in enumerate(self.steps, start=1):
            step.step_number = index
        return self

    @property
    def is_automatable(self) -> bool:
        return self.automation_candidate in (
            AutomationCandidate.YES,
            AutomationCandidate.PARTIAL,
        )


class TestCaseSuite(_Base):
    """Structured output of the Test Case Writer agent."""

    # Not a pytest test class.
    __test__ = False

    ticket_key: str
    test_cases: list[TestCase] = Field(default_factory=list)
    coverage_notes: str = ""
    uncovered_acceptance_criteria: list[str] = Field(default_factory=list)

    @field_validator("ticket_key")
    @classmethod
    def _upper(cls, value: str) -> str:
        return str(value or "").strip().upper()

    @field_validator("uncovered_acceptance_criteria")
    @classmethod
    def _norm_acs(cls, value: list[str]) -> list[str]:
        return _normalise_id_list(value, "AC")

    @property
    def case_ids(self) -> list[str]:
        return [case.id for case in self.test_cases]

    def automatable_cases(self) -> list[TestCase]:
        return [case for case in self.test_cases if case.is_automatable]


# ---------------------------------------------------------------------------
# Stage 4 - Playwright automation
# ---------------------------------------------------------------------------


class PlaywrightFile(_Base):
    """A single generated TypeScript file."""

    path: str = Field(
        description="Relative path such as tests/vwo-48.spec.ts or pages/login.page.ts."
    )
    content: str = Field(description="Full file content, no markdown fences.")
    kind: str = Field(default="spec", description="spec, page, fixture or config.")

    @field_validator("path")
    @classmethod
    def _clean_path(cls, value: str) -> str:
        text = str(value or "").strip().replace("\\", "/").lstrip("/")
        parts = [part for part in text.split("/") if part not in ("", ".", "..")]
        return "/".join(parts) or "tests/generated.spec.ts"


class AutomationMapping(_Base):
    """Trace from an automated Playwright test back to Jira."""

    test_case_id: str = ""
    spec_file: str = ""
    test_title: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    acceptance_criteria_ids: list[str] = Field(default_factory=list)

    @field_validator("test_case_id")
    @classmethod
    def _upper(cls, value: str) -> str:
        return str(value or "").strip().upper()

    @field_validator("requirement_ids")
    @classmethod
    def _norm_reqs(cls, value: list[str]) -> list[str]:
        return _normalise_id_list(value, "REQ")

    @field_validator("acceptance_criteria_ids")
    @classmethod
    def _norm_acs(cls, value: list[str]) -> list[str]:
        return _normalise_id_list(value, "AC")


class PlaywrightBundle(_Base):
    """Structured output of the Playwright Coder agent."""

    ticket_key: str
    files: list[PlaywrightFile] = Field(default_factory=list)
    mappings: list[AutomationMapping] = Field(default_factory=list)
    readiness: AutomationReadiness = AutomationReadiness.NEEDS_CONFIGURATION
    missing_information: list[str] = Field(default_factory=list)
    setup_notes: str = ""
    coverage_notes: str = ""

    @field_validator("ticket_key")
    @classmethod
    def _upper(cls, value: str) -> str:
        return str(value or "").strip().upper()

    @field_validator("readiness", mode="before")
    @classmethod
    def _coerce_readiness(cls, value: Any) -> Any:
        return _coerce_enum(
            AutomationReadiness, value, AutomationReadiness.NEEDS_CONFIGURATION
        )

    @property
    def spec_files(self) -> list[PlaywrightFile]:
        return [file for file in self.files if file.path.endswith(".spec.ts")]


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------


class TraceabilityRow(_Base):
    """One requirement / acceptance-criterion row of the matrix."""

    requirement_id: str = ""
    requirement_text: str = ""
    acceptance_criterion_id: str = ""
    acceptance_criterion_text: str = ""
    test_case_ids: list[str] = Field(default_factory=list)
    automated_test_case_ids: list[str] = Field(default_factory=list)
    coverage_status: CoverageStatus = CoverageStatus.NOT_COVERED
    reason: str = ""


class CoverageMetrics(_Base):
    """Deterministically computed coverage numbers."""

    total_requirements: int = 0
    covered_requirements: int = 0
    total_acceptance_criteria: int = 0
    covered_acceptance_criteria: int = 0
    total_test_cases: int = 0
    automatable_test_cases: int = 0
    automated_test_cases: int = 0
    orphan_requirements: list[str] = Field(default_factory=list)
    orphan_acceptance_criteria: list[str] = Field(default_factory=list)
    orphan_test_cases: list[str] = Field(default_factory=list)

    @property
    def requirement_coverage_pct(self) -> float:
        return _pct(self.covered_requirements, self.total_requirements)

    @property
    def acceptance_criteria_coverage_pct(self) -> float:
        return _pct(self.covered_acceptance_criteria, self.total_acceptance_criteria)

    @property
    def automation_coverage_pct(self) -> float:
        return _pct(self.automated_test_cases, self.automatable_test_cases)


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 1)


class TraceabilityMatrix(_Base):
    """Full traceability matrix for one ticket."""

    ticket_key: str
    rows: list[TraceabilityRow] = Field(default_factory=list)
    metrics: CoverageMetrics = Field(default_factory=CoverageMetrics)


# ---------------------------------------------------------------------------
# Run bookkeeping
# ---------------------------------------------------------------------------


class StageState(_Base):
    """Progress record for one agent stage of one ticket."""

    key: str
    label: str
    status: StageStatus = StageStatus.PENDING
    message: str = ""
    warnings: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            return round((self.completed_at - self.started_at).total_seconds(), 2)
        return None


STAGE_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("jira_analyst", "Jira Analyst"),
    ("test_plan_writer", "Test Plan Writer"),
    ("test_case_writer", "Test Case Writer"),
    ("playwright_coder", "Playwright Coder"),
)


def new_stage_states() -> list[StageState]:
    """Fresh, pending stage records for a ticket."""
    return [StageState(key=key, label=label) for key, label in STAGE_DEFINITIONS]


class ArtifactRef(_Base):
    """A generated artifact on disk."""

    name: str
    relative_path: str
    media_type: str = "text/plain"
    bytes: int = 0


class TicketResult(_Base):
    """Everything produced for a single ticket."""

    ticket_key: str
    status: TicketStatus = TicketStatus.FAILED
    provider_source: ProviderSource | None = None
    issue: JiraIssue | None = None
    analysis: RequirementAnalysis | None = None
    test_plan: TestPlan | None = None
    test_cases: TestCaseSuite | None = None
    playwright: PlaywrightBundle | None = None
    traceability: TraceabilityMatrix | None = None
    stages: list[StageState] = Field(default_factory=new_stage_states)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    output_dir: str = ""
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    log: list[str] = Field(default_factory=list)

    @property
    def automation_readiness(self) -> AutomationReadiness:
        if self.playwright is None:
            return AutomationReadiness.NOT_APPLICABLE
        return self.playwright.readiness

    @property
    def duration_seconds(self) -> float | None:
        if self.completed_at:
            return round((self.completed_at - self.started_at).total_seconds(), 2)
        return None

    def stage(self, key: str) -> StageState | None:
        for state in self.stages:
            if state.key == key:
                return state
        return None


class RunResult(_Base):
    """Aggregate result of one pipeline run over one or more tickets."""

    run_id: str
    requested_keys: list[str] = Field(default_factory=list)
    integration_mode: str = "auto"
    demo_mode: bool = False
    tickets: list[TicketResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    output_dir: str = ""
    errors: list[str] = Field(default_factory=list)

    @property
    def completed(self) -> list[TicketResult]:
        return [t for t in self.tickets if t.status is TicketStatus.COMPLETED]

    @property
    def completed_with_warnings(self) -> list[TicketResult]:
        return [
            t for t in self.tickets if t.status is TicketStatus.COMPLETED_WITH_WARNINGS
        ]

    @property
    def failed(self) -> list[TicketResult]:
        return [t for t in self.tickets if t.status is TicketStatus.FAILED]

    @property
    def successful(self) -> bool:
        """A run succeeds when at least one ticket produced a full artifact set."""
        return bool(self.completed or self.completed_with_warnings)

    def ticket(self, key: str) -> TicketResult | None:
        for result in self.tickets:
            if result.ticket_key == key:
                return result
        return None
