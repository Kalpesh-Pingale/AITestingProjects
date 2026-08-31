"""Typed exceptions for the Jira QA Crew application.

Every error raised by application code derives from :class:`JiraQACrewError`
so that the pipeline can distinguish expected, actionable failures from
programming errors.
"""

from __future__ import annotations


class JiraQACrewError(Exception):
    """Base class for all application errors."""

    #: Short, stable code surfaced in the UI and in artifacts.
    code: str = "APP_ERROR"

    def __init__(self, message: str, *, remediation: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.remediation = remediation

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.remediation:
            return f"{self.message} ({self.remediation})"
        return self.message


class ConfigurationError(JiraQACrewError):
    """Raised when required configuration is missing or inconsistent."""

    code = "CONFIG_ERROR"


class TicketInputError(JiraQACrewError):
    """Raised when the user supplied ticket input cannot be used."""

    code = "TICKET_INPUT_ERROR"


class JiraProviderError(JiraQACrewError):
    """Base class for provider level failures (MCP or REST)."""

    code = "JIRA_PROVIDER_ERROR"

    def __init__(
        self,
        message: str,
        *,
        provider: str = "unknown",
        remediation: str | None = None,
    ) -> None:
        super().__init__(message, remediation=remediation)
        self.provider = provider


class JiraAuthError(JiraProviderError):
    """Authentication or authorization failure against Jira."""

    code = "JIRA_AUTH_ERROR"


class JiraNotFoundError(JiraProviderError):
    """The requested issue does not exist or is not visible."""

    code = "JIRA_NOT_FOUND"


class JiraRateLimitError(JiraProviderError):
    """Jira replied with HTTP 429 after the configured retries."""

    code = "JIRA_RATE_LIMITED"


class JiraTimeoutError(JiraProviderError):
    """A provider call exceeded its configured timeout."""

    code = "JIRA_TIMEOUT"


class JiraResponseError(JiraProviderError):
    """A provider returned a malformed or unusable payload."""

    code = "JIRA_BAD_RESPONSE"


class MCPUnavailableError(JiraProviderError):
    """The Jira MCP server is disabled, unreachable, or misconfigured."""

    code = "MCP_UNAVAILABLE"


class AllProvidersFailedError(JiraProviderError):
    """Every configured provider failed for a ticket."""

    code = "ALL_PROVIDERS_FAILED"

    def __init__(self, message: str, *, failures: dict[str, str] | None = None) -> None:
        super().__init__(message, provider="gateway")
        self.failures = failures or {}


class StageValidationError(JiraQACrewError):
    """A CrewAI stage produced output that failed deterministic validation."""

    code = "STAGE_VALIDATION_ERROR"

    def __init__(self, stage: str, issues: list[str]) -> None:
        detail = "; ".join(issues) if issues else "unknown validation failure"
        super().__init__(f"Stage '{stage}' failed validation: {detail}")
        self.stage = stage
        self.issues = list(issues)


class PipelineError(JiraQACrewError):
    """A ticket level pipeline failure that is not stage specific."""

    code = "PIPELINE_ERROR"


class ArtifactError(JiraQACrewError):
    """Artifact rendering or writing failed."""

    code = "ARTIFACT_ERROR"
