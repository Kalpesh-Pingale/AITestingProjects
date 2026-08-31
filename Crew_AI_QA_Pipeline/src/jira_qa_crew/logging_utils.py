"""Structured logging with secret redaction.

Every log record and every user facing error string passes through
:func:`redact` so that API tokens, bearer tokens and basic-auth headers can
never reach the Streamlit UI, the artifacts, or the log file.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from jira_qa_crew.config import SECRET_ENV_KEYS

REDACTED = "***REDACTED***"

#: Patterns for secrets that are recognisable by shape rather than by value.
#: Order matters: the specific token shapes run before the generic
#: ``key = value`` rule, otherwise ``Authorization: Bearer <token>`` would be
#: reduced to ``Authorization=***`` and leave the token itself in the string.
_SHAPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{10,}=*"),
    re.compile(r"\bBasic\s+[A-Za-z0-9+/]{10,}=*"),
    re.compile(r"\bATATT[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bgsk_[A-Za-z0-9_\-]{10,}"),
    re.compile(
        r"(?i)\b(authorization|x-api-key|api[-_]?key|token|password|secret)"
        r"\s*[:=]\s*[\"']?([^\s\"',}]{6,})"
    ),
)

_MIN_LITERAL_SECRET_LEN = 6


def _literal_secrets() -> list[str]:
    values: list[str] = []
    for key in SECRET_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if len(value) >= _MIN_LITERAL_SECRET_LEN:
            values.append(value)
    # Longest first so that overlapping values are replaced completely.
    return sorted(set(values), key=len, reverse=True)


def redact(value: Any) -> str:
    """Return ``value`` as a string with known and shaped secrets removed."""
    text = value if isinstance(value, str) else str(value)
    if not text:
        return text

    for secret in _literal_secrets():
        text = text.replace(secret, REDACTED)

    for pattern in _SHAPE_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


def redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Redact every value of a mapping, keeping keys intact."""
    return {key: redact(val) for key, val in mapping.items()}


class RedactingFilter(logging.Filter):
    """Logging filter that redacts the formatted message and its arguments."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:  # noqa: BLE001 - logging must never raise
            record.msg = REDACTED
            record.args = ()
        return True


_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Install a redacting stream handler once per process."""
    global _CONFIGURED
    root = logging.getLogger("jira_qa_crew")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if _CONFIGURED:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under the application root logger."""
    suffix = name.split(".")[-1]
    return logging.getLogger(f"jira_qa_crew.{suffix}")
