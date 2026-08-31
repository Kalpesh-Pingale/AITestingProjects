"""Prompt catalogue.

Agent and task prompts live in YAML next to this module, never inside the
Streamlit UI code. Placeholders use ``{{token}}`` and are substituted here so
that JSON or TypeScript braces inside a prompt are never mistaken for
template variables.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROMPT_DIR = Path(__file__).resolve().parent
AGENTS_FILE = PROMPT_DIR / "agents.yaml"
TASKS_FILE = PROMPT_DIR / "tasks.yaml"

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@lru_cache(maxsize=2)
def _load(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a mapping at the top level.")
    return data


def agent_prompts() -> dict[str, Any]:
    """Role, goal and backstory for every agent."""
    return _load(str(AGENTS_FILE))


def task_prompts() -> dict[str, Any]:
    """Description and expected output for every task."""
    return _load(str(TASKS_FILE))


def render(template: str, **tokens: Any) -> str:
    """Substitute ``{{token}}`` placeholders, leaving unknown ones intact."""
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in tokens:
            return str(tokens[name])
        return match.group(0)

    return _TOKEN_RE.sub(replace, template or "").strip()


def agent_spec(key: str, **tokens: Any) -> dict[str, str]:
    """Return a rendered ``{role, goal, backstory}`` mapping."""
    spec = agent_prompts().get(key)
    if not isinstance(spec, dict):
        raise KeyError(f"Unknown agent prompt: {key}")
    return {
        field: render(str(spec.get(field, "")), **tokens)
        for field in ("role", "goal", "backstory")
    }


def task_spec(key: str, **tokens: Any) -> dict[str, str]:
    """Return a rendered ``{description, expected_output}`` mapping."""
    spec = task_prompts().get(key)
    if not isinstance(spec, dict):
        raise KeyError(f"Unknown task prompt: {key}")
    return {
        field: render(str(spec.get(field, "")), **tokens)
        for field in ("description", "expected_output")
    }


def repair_suffix(validation_errors: list[str]) -> str:
    """Return the repair instruction appended for a single retry."""
    template = str(task_prompts().get("repair_suffix", ""))
    bullets = "\n".join(f"- {error}" for error in validation_errors) or "- unknown"
    return render(template, validation_errors=bullets)


__all__ = [
    "agent_prompts",
    "agent_spec",
    "render",
    "repair_suffix",
    "task_prompts",
    "task_spec",
]
