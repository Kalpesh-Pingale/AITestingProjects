"""Parsing, normalisation and validation of user supplied ticket input."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jira_qa_crew.exceptions import TicketInputError

#: Commas, semicolons, pipes, whitespace and newlines all separate keys.
_SPLIT_RE = re.compile(r"[,;|\s]+")


@dataclass(slots=True)
class TicketInput:
    """Result of parsing the ticket text area."""

    keys: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)

    @property
    def has_valid_keys(self) -> bool:
        return bool(self.keys)

    def summary(self) -> str:
        parts = [f"{len(self.keys)} valid"]
        if self.duplicates:
            parts.append(f"{len(self.duplicates)} duplicate")
        if self.invalid:
            parts.append(f"{len(self.invalid)} invalid")
        if self.truncated:
            parts.append(f"{len(self.truncated)} dropped by the ticket limit")
        return ", ".join(parts)


def parse_ticket_input(
    raw: str,
    *,
    pattern: str = r"^[A-Z][A-Z0-9]{1,19}-\d{1,9}$",
    max_tickets: int = 20,
    max_chars: int = 4000,
) -> TicketInput:
    """Split, upper-case, de-duplicate and validate a ticket id blob.

    Accepts commas, semicolons, pipes, spaces and newlines as separators.
    Order of first appearance is preserved. Anything that does not match the
    configured Jira key pattern is reported rather than silently dropped.
    """
    text = raw or ""
    if len(text) > max_chars:
        raise TicketInputError(
            f"Ticket input is {len(text)} characters, the limit is {max_chars}.",
            remediation="Paste fewer ticket ids.",
        )

    try:
        key_re = re.compile(pattern)
    except re.error as exc:
        raise TicketInputError(
            f"Configured Jira key pattern is not a valid regular expression: {exc}",
            remediation="Fix JIRA_KEY_PATTERN.",
        ) from exc

    result = TicketInput()
    seen: set[str] = set()
    for token in _SPLIT_RE.split(text.strip()):
        candidate = token.strip().strip(".").upper()
        if not candidate:
            continue
        if not key_re.match(candidate):
            if candidate not in result.invalid:
                result.invalid.append(candidate)
            continue
        if candidate in seen:
            if candidate not in result.duplicates:
                result.duplicates.append(candidate)
            continue
        seen.add(candidate)
        if len(result.keys) >= max_tickets:
            result.truncated.append(candidate)
            continue
        result.keys.append(candidate)
    return result


def require_keys(parsed: TicketInput) -> list[str]:
    """Return the valid keys or raise a user facing error."""
    if not parsed.has_valid_keys:
        detail = (
            f" Unrecognised input: {', '.join(parsed.invalid[:5])}."
            if parsed.invalid
            else ""
        )
        raise TicketInputError(
            "No valid Jira ticket ids were found." + detail,
            remediation="Use keys like PROJ-123, separated by commas or new lines.",
        )
    return list(parsed.keys)
