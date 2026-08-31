"""Ticket parsing, normalisation, validation and de-duplication."""

from __future__ import annotations

import pytest

from jira_qa_crew.exceptions import TicketInputError
from jira_qa_crew.tickets import parse_ticket_input, require_keys


def test_splits_on_commas_spaces_newlines_and_semicolons() -> None:
    parsed = parse_ticket_input("VWO-48\nVWO-49, VWO-50; VWO-51 VWO-52")
    assert parsed.keys == ["VWO-48", "VWO-49", "VWO-50", "VWO-51", "VWO-52"]


def test_normalises_case_and_preserves_first_seen_order() -> None:
    parsed = parse_ticket_input("vwo-49, VWO-48")
    assert parsed.keys == ["VWO-49", "VWO-48"]


def test_removes_duplicates_and_reports_them() -> None:
    parsed = parse_ticket_input("VWO-48, vwo-48, VWO-49")
    assert parsed.keys == ["VWO-48", "VWO-49"]
    assert parsed.duplicates == ["VWO-48"]


def test_reports_invalid_keys_instead_of_dropping_them_silently() -> None:
    parsed = parse_ticket_input("VWO-48, not-a-key, 12345, VWO_49")
    assert parsed.keys == ["VWO-48"]
    assert "NOT-A-KEY" in parsed.invalid
    assert "12345" in parsed.invalid
    assert "VWO_49" in parsed.invalid


def test_enforces_the_ticket_limit() -> None:
    parsed = parse_ticket_input(
        ", ".join(f"VWO-{index}" for index in range(1, 8)), max_tickets=3
    )
    assert len(parsed.keys) == 3
    assert len(parsed.truncated) == 4


def test_rejects_oversized_input() -> None:
    with pytest.raises(TicketInputError):
        parse_ticket_input("VWO-48 " * 1000, max_chars=100)


def test_custom_key_pattern_is_honoured() -> None:
    parsed = parse_ticket_input("AB-1, ABCD-99", pattern=r"^AB-\d+$")
    assert parsed.keys == ["AB-1"]
    assert parsed.invalid == ["ABCD-99"]


def test_require_keys_raises_when_nothing_is_valid() -> None:
    with pytest.raises(TicketInputError) as exc:
        require_keys(parse_ticket_input("garbage input"))
    assert "No valid Jira ticket ids" in str(exc.value)


def test_summary_is_human_readable() -> None:
    parsed = parse_ticket_input("VWO-48, VWO-48, oops")
    assert "1 valid" in parsed.summary()
    assert "duplicate" in parsed.summary()
