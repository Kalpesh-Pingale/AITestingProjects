"""Atlassian Document Format conversion."""

from __future__ import annotations

import json

from jira_qa_crew.jira.adf import adf_to_text, field_to_text, truncate


def _doc(*content: dict) -> dict:
    return {"type": "doc", "version": 1, "content": list(content)}


def test_paragraph_and_marks() -> None:
    doc = _doc(
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Reset "},
                {"type": "text", "text": "must", "marks": [{"type": "strong"}]},
                {"type": "text", "text": " expire"},
            ],
        }
    )
    assert adf_to_text(doc) == "Reset **must** expire"


def test_headings_lists_and_code_blocks() -> None:
    doc = _doc(
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Rules"}]},
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "first"}]}
                    ],
                },
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "second"}]}
                    ],
                },
            ],
        },
        {"type": "codeBlock", "attrs": {"language": "ts"}, "content": [{"type": "text", "text": "const a = 1;"}]},
    )
    text = adf_to_text(doc)
    assert "## Rules" in text
    assert "- first" in text and "- second" in text
    assert "```ts" in text and "const a = 1;" in text


def test_ordered_lists_tables_and_links() -> None:
    doc = _doc(
        {
            "type": "orderedList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "step"}]}
                    ],
                }
            ],
        },
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Field"}]}]},
                        {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Value"}]}]},
                    ],
                },
                {
                    "type": "tableRow",
                    "content": [
                        {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "TTL"}]}]},
                        {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "15"}]}]},
                    ],
                },
            ],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "spec",
                    "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}],
                }
            ],
        },
    )
    text = adf_to_text(doc)
    assert "1. step" in text
    assert "| Field | Value |" in text
    assert "| TTL | 15 |" in text
    assert "[spec](https://example.com)" in text


def test_unknown_nodes_keep_their_children() -> None:
    doc = _doc(
        {
            "type": "someFutureNode",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "kept"}]}],
        }
    )
    assert "kept" in adf_to_text(doc)


def test_deeply_nested_documents_do_not_recurse_forever() -> None:
    node: dict = {"type": "paragraph", "content": [{"type": "text", "text": "deep"}]}
    for _ in range(60):
        node = {"type": "blockquote", "content": [node]}
    assert isinstance(adf_to_text(node), str)


def test_field_to_text_handles_strings_options_and_lists() -> None:
    assert field_to_text("plain") == "plain"
    assert field_to_text({"value": "Option A"}) == "Option A"
    assert field_to_text([{"name": "one"}, {"name": "two"}]) == "one\ntwo"
    assert field_to_text(None) == ""
    assert field_to_text(15) == "15"


def test_field_to_text_parses_a_real_fixture(fixture_dir) -> None:
    payload = json.loads((fixture_dir / "VWO-48.json").read_text(encoding="utf-8"))
    description = field_to_text(payload["fields"]["description"])
    assert "15 minutes" in description
    assert "RESET_LINK_TTL_MINUTES" in description


def test_truncate_marks_truncated_content() -> None:
    assert truncate("abcdef", 0) == "abcdef"
    result = truncate("x" * 500, 100)
    assert len(result) == 100
    assert result.endswith("[truncated]")
