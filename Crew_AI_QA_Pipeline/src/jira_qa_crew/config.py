"""Application configuration.

Configuration is environment driven. Values are loaded, in order, from:

1. real process environment variables,
2. a ``.env`` file at the project root,
3. ``st.secrets`` when the app runs under Streamlit (copied into the
   environment before the settings object is built).

Secrets are never rendered directly in the UI; only redacted status is shown.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from jira_qa_crew.exceptions import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

#: Environment variables that may hold secrets and must never be logged raw.
SECRET_ENV_KEYS: tuple[str, ...] = (
    "LLM_API_KEY",
    "JIRA_API_TOKEN",
    "JIRA_BEARER_TOKEN",
    "JIRA_MCP_HEADERS_JSON",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "ANTHROPIC_API_KEY",
)


class IntegrationMode(str, Enum):
    """How the gateway is allowed to reach Jira."""

    AUTO = "auto"
    MCP = "mcp"
    REST = "rest"


class AuthMode(str, Enum):
    """Jira REST authentication style."""

    BASIC = "basic"
    BEARER = "bearer"


class MCPTransport(str, Enum):
    """Supported MCP transports."""

    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"
    STDIO = "stdio"


class ReadinessItem:
    """Small value object describing one configuration readiness row."""

    __slots__ = ("name", "ready", "detail")

    def __init__(self, name: str, ready: bool, detail: str) -> None:
        self.name = name
        self.ready = ready
        self.detail = detail

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"ReadinessItem(name={self.name!r}, ready={self.ready!r})"


def _load_env_file_manually(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_environment(env_file: Path | None = None) -> None:
    """Populate ``os.environ`` from ``.env`` and Streamlit secrets.

    Existing process environment variables always win. Missing values are
    filled from ``.env`` first and then from ``st.secrets`` when available.
    Importing Streamlit is optional so the library also works from plain
    Python and from tests.
    """
    path = env_file or DEFAULT_ENV_FILE
    if path.is_file():
        try:
            from dotenv import load_dotenv

            load_dotenv(path, override=False)
        except ImportError:  # pragma: no cover - dotenv is a hard dependency
            _load_env_file_manually(path)

    try:  # pragma: no cover - depends on the Streamlit runtime
        import streamlit as st

        secrets = st.secrets
        for key in secrets:
            value = secrets[key]
            if isinstance(value, (dict, list)):
                continue
            os.environ.setdefault(str(key), str(value))
    except Exception:  # noqa: BLE001 - Streamlit raises varied types when absent
        return


def _parse_json(raw: str, expected: type, env_key: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return expected()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"{env_key} is not valid JSON: {exc.msg}",
            remediation=f"Set {env_key} to a valid JSON {expected.__name__}.",
        ) from exc
    if not isinstance(value, expected):
        raise ConfigurationError(
            f"{env_key} must be a JSON {expected.__name__}.",
            remediation=f"Set {env_key} to a JSON {expected.__name__} literal.",
        )
    return value


def _any_provider_key_present() -> bool:
    return any(
        os.environ.get(key)
        for key in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY")
    )


class AppSettings(BaseSettings):
    """Typed view over the application environment."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # -- Application ----------------------------------------------------
    app_name: str = Field(default="Jira QA Crew", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    output_dir: Path = Field(default=Path("outputs"), alias="OUTPUT_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    demo_mode: bool = Field(default=False, alias="DEMO_MODE")

    # -- LLM ------------------------------------------------------------
    llm_model: str = Field(default="", alias="LLM_MODEL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=0, alias="LLM_MAX_TOKENS")

    # -- Jira core ------------------------------------------------------
    jira_integration_mode: IntegrationMode = Field(
        default=IntegrationMode.AUTO, alias="JIRA_INTEGRATION_MODE"
    )
    jira_url: str = Field(default="", alias="JIRA_URL")
    jira_auth_mode: AuthMode = Field(default=AuthMode.BASIC, alias="JIRA_AUTH_MODE")
    jira_email: str = Field(default="", alias="JIRA_EMAIL")
    jira_api_token: str = Field(default="", alias="JIRA_API_TOKEN")
    jira_bearer_token: str = Field(default="", alias="JIRA_BEARER_TOKEN")
    jira_api_version: str = Field(default="3", alias="JIRA_API_VERSION")
    jira_acceptance_criteria_field: str = Field(
        default="", alias="JIRA_ACCEPTANCE_CRITERIA_FIELD"
    )
    jira_include_comments: bool = Field(default=False, alias="JIRA_INCLUDE_COMMENTS")
    jira_max_comments: int = Field(default=20, alias="JIRA_MAX_COMMENTS")
    jira_timeout_seconds: float = Field(default=20.0, alias="JIRA_TIMEOUT_SECONDS")
    jira_max_attempts: int = Field(default=3, alias="JIRA_MAX_ATTEMPTS")
    jira_key_pattern: str = Field(
        default=r"^[A-Z][A-Z0-9]{1,19}-\d{1,9}$", alias="JIRA_KEY_PATTERN"
    )

    # -- Jira MCP -------------------------------------------------------
    jira_mcp_transport: MCPTransport = Field(
        default=MCPTransport.STREAMABLE_HTTP, alias="JIRA_MCP_TRANSPORT"
    )
    jira_mcp_url: str = Field(default="", alias="JIRA_MCP_URL")
    jira_mcp_command: str = Field(default="", alias="JIRA_MCP_COMMAND")
    jira_mcp_args_json: str = Field(default="[]", alias="JIRA_MCP_ARGS_JSON")
    jira_mcp_headers_json: str = Field(default="{}", alias="JIRA_MCP_HEADERS_JSON")
    jira_mcp_env_json: str = Field(default="{}", alias="JIRA_MCP_ENV_JSON")
    jira_mcp_get_issue_tool: str = Field(default="", alias="JIRA_MCP_GET_ISSUE_TOOL")
    jira_mcp_issue_key_arg: str = Field(
        default="issueIdOrKey", alias="JIRA_MCP_ISSUE_KEY_ARG"
    )
    jira_mcp_extra_args_json: str = Field(
        default="{}", alias="JIRA_MCP_EXTRA_ARGS_JSON"
    )
    jira_mcp_timeout_seconds: float = Field(
        default=20.0, alias="JIRA_MCP_TIMEOUT_SECONDS"
    )

    # -- Pipeline -------------------------------------------------------
    pipeline_max_tickets: int = Field(default=20, alias="PIPELINE_MAX_TICKETS")
    pipeline_max_retries: int = Field(default=2, alias="PIPELINE_MAX_RETRIES")
    pipeline_ticket_timeout_seconds: int = Field(
        default=600, alias="PIPELINE_TICKET_TIMEOUT_SECONDS"
    )
    pipeline_max_input_chars: int = Field(
        default=4000, alias="PIPELINE_MAX_INPUT_CHARS"
    )
    pipeline_max_field_chars: int = Field(
        default=20000, alias="PIPELINE_MAX_FIELD_CHARS"
    )

    @field_validator("llm_temperature")
    @classmethod
    def _clamp_temperature(cls, value: float) -> float:
        return max(0.0, min(2.0, value))

    @field_validator("jira_url", "llm_base_url", "jira_mcp_url", mode="before")
    @classmethod
    def _strip_trailing_slash(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return value

    # -- Derived helpers ------------------------------------------------
    @property
    def mcp_args(self) -> list[str]:
        return [
            str(item)
            for item in _parse_json(self.jira_mcp_args_json, list, "JIRA_MCP_ARGS_JSON")
        ]

    @property
    def mcp_headers(self) -> dict[str, str]:
        raw = _parse_json(self.jira_mcp_headers_json, dict, "JIRA_MCP_HEADERS_JSON")
        return {str(k): str(v) for k, v in raw.items()}

    @property
    def mcp_env(self) -> dict[str, str]:
        raw = _parse_json(self.jira_mcp_env_json, dict, "JIRA_MCP_ENV_JSON")
        return {str(k): str(v) for k, v in raw.items()}

    @property
    def mcp_extra_args(self) -> dict[str, Any]:
        return _parse_json(
            self.jira_mcp_extra_args_json, dict, "JIRA_MCP_EXTRA_ARGS_JSON"
        )

    @property
    def output_path(self) -> Path:
        path = self.output_dir
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def mcp_configured(self) -> bool:
        """True when enough MCP configuration exists to attempt a connection."""
        if self.jira_mcp_transport is MCPTransport.STDIO:
            return bool(self.jira_mcp_command)
        return bool(self.jira_mcp_url)

    def rest_configured(self) -> bool:
        """True when enough REST configuration exists to attempt a call."""
        if not self.jira_url:
            return False
        if self.jira_auth_mode is AuthMode.BEARER:
            return bool(self.jira_bearer_token)
        return bool(self.jira_email and self.jira_api_token)

    def llm_configured(self) -> bool:
        return bool(self.llm_model)

    def readiness(self) -> dict[str, ReadinessItem]:
        """Return redacted readiness indicators for the UI."""
        key_state = "set" if (self.llm_api_key or _any_provider_key_present()) else "missing"
        return {
            "llm": ReadinessItem(
                name="LLM",
                ready=self.llm_configured() and key_state == "set",
                detail=(
                    f"model={self.llm_model or 'unset'} "
                    f"temperature={self.llm_temperature} api_key={key_state}"
                ),
            ),
            "mcp": ReadinessItem(
                name="Jira MCP",
                ready=self.mcp_configured(),
                detail=(
                    f"transport={self.jira_mcp_transport.value} "
                    f"target={'set' if self.mcp_configured() else 'unset'} "
                    f"tool={self.jira_mcp_get_issue_tool or 'auto-discover'}"
                ),
            ),
            "rest": ReadinessItem(
                name="Jira REST",
                ready=self.rest_configured(),
                detail=(
                    f"url={self.jira_url or 'unset'} auth={self.jira_auth_mode.value} "
                    f"credentials={'set' if self.rest_configured() else 'missing'}"
                ),
            ),
            "demo": ReadinessItem(
                name="Demo mode",
                ready=self.demo_mode,
                detail="enabled - local fixtures only" if self.demo_mode else "disabled",
            ),
        }

    def validate_for_run(self, mode: IntegrationMode) -> list[str]:
        """Return blocking configuration problems for the requested run mode."""
        problems: list[str] = []
        if not self.llm_configured():
            problems.append(
                "LLM_MODEL is not set. Set it to a CrewAI/LiteLLM model id, "
                "for example 'openai/gpt-4.1-mini' or 'openai/gpt-oss-120b'."
            )
        if not self.llm_api_key and not _any_provider_key_present():
            problems.append(
                "LLM_API_KEY is not set and no provider specific key "
                "(OPENAI_API_KEY / GROQ_API_KEY / ANTHROPIC_API_KEY) was found."
            )
        if self.demo_mode:
            return problems

        if mode is IntegrationMode.MCP and not self.mcp_configured():
            problems.append(
                "Integration mode 'MCP only' was selected but no MCP endpoint is "
                "configured. Set JIRA_MCP_URL, or JIRA_MCP_COMMAND for stdio."
            )
        if mode is IntegrationMode.REST and not self.rest_configured():
            problems.append(
                "Integration mode 'REST only' was selected but JIRA_URL and "
                "credentials are incomplete."
            )
        if mode is IntegrationMode.AUTO and not (
            self.mcp_configured() or self.rest_configured()
        ):
            problems.append(
                "No Jira provider is configured. Configure Jira MCP, Jira REST, "
                "or enable DEMO_MODE explicitly."
            )
        return problems


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return the process wide settings singleton."""
    load_environment()
    return AppSettings()


def reset_settings_cache() -> None:
    """Clear the settings cache. Used by tests and configuration reloads."""
    get_settings.cache_clear()
