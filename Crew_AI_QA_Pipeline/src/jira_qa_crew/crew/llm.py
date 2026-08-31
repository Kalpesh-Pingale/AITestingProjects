"""LLM construction.

The model identifier is configuration, never a constant: provider naming
changes and the app must not need a code edit to follow it.
"""

from __future__ import annotations

from typing import Any

from crewai import LLM

from jira_qa_crew.config import AppSettings
from jira_qa_crew.exceptions import ConfigurationError


def build_llm(settings: AppSettings) -> LLM:
    """Return a configured CrewAI :class:`LLM`."""
    if not settings.llm_model:
        raise ConfigurationError(
            "LLM_MODEL is not configured.",
            remediation=(
                "Set LLM_MODEL to a LiteLLM/CrewAI model id such as "
                "'openai/gpt-4.1-mini', 'openai/gpt-oss-120b' or "
                "'anthropic/claude-sonnet-4-5'."
            ),
        )

    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
    }
    if settings.llm_api_key:
        kwargs["api_key"] = settings.llm_api_key
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url
    if settings.llm_max_tokens > 0:
        kwargs["max_tokens"] = settings.llm_max_tokens

    try:
        return LLM(**kwargs)
    except Exception as exc:  # noqa: BLE001 - reported as configuration
        raise ConfigurationError(
            f"Could not initialise the LLM '{settings.llm_model}': {exc}",
            remediation=(
                "Check LLM_MODEL. CrewAI routes known providers to their native "
                "SDK; other providers need LiteLLM installed (pip install litellm)."
            ),
        ) from exc
