"""Atlassian Document Format (ADF) to readable plain text.

Jira Cloud returns rich text fields as ADF documents. The conversion here is
deliberately lossless enough for requirement analysis (lists, headings,
tables, code blocks and links survive) and strictly textual - no HTML is
produced and no node is ever executed or evaluated.
"""

from __future__ import annotations

from typing import Any

_MAX_DEPTH = 30


def adf_to_text(node: Any, *, depth: int = 0) -> str:
    """Convert an ADF document (or any sub-node) into markdown-ish text."""
    if depth > _MAX_DEPTH:
        return ""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(item, depth=depth + 1) for item in node)
    if not isinstance(node, dict):
        return str(node)

    node_type = node.get("type", "")
    content = node.get("content", [])

    if node_type == "text":
        return _apply_marks(node.get("text", ""), node.get("marks", []))
    if node_type == "hardBreak":
        return "\n"
    if node_type == "rule":
        return "\n---\n"
    if node_type == "emoji":
        attrs = node.get("attrs", {})
        return attrs.get("shortName") or attrs.get("text") or ""
    if node_type == "mention":
        return f"@{node.get('attrs', {}).get('text', 'user').lstrip('@')}"
    if node_type == "date":
        return node.get("attrs", {}).get("timestamp", "")
    if node_type == "status":
        return f"[{node.get('attrs', {}).get('text', '')}]"
    if node_type in ("inlineCard", "blockCard", "embedCard"):
        return node.get("attrs", {}).get("url", "")
    if node_type == "mediaSingle" or node_type == "mediaGroup":
        return "[media attachment]"
    if node_type == "media":
        attrs = node.get("attrs", {})
        return f"[media: {attrs.get('id', 'attachment')}]"

    if node_type == "doc":
        return _join_blocks(content, depth)
    if node_type == "paragraph":
        return adf_to_text(content, depth=depth + 1)
    if node_type == "heading":
        level = int(node.get("attrs", {}).get("level", 1))
        return f"{'#' * max(1, min(6, level))} {adf_to_text(content, depth=depth + 1)}"
    if node_type == "blockquote":
        inner = _join_blocks(content, depth)
        return "\n".join(f"> {line}" for line in inner.splitlines())
    if node_type == "codeBlock":
        language = node.get("attrs", {}).get("language", "")
        return f"```{language}\n{adf_to_text(content, depth=depth + 1)}\n```"
    if node_type == "panel":
        panel_type = node.get("attrs", {}).get("panelType", "info")
        return f"[{panel_type.upper()}] {_join_blocks(content, depth)}"
    if node_type == "bulletList":
        return _render_list(content, depth, ordered=False)
    if node_type == "orderedList":
        return _render_list(content, depth, ordered=True)
    if node_type == "listItem":
        return _join_blocks(content, depth)
    if node_type == "taskList":
        return _render_task_list(content, depth)
    if node_type == "taskItem":
        state = node.get("attrs", {}).get("state", "TODO")
        mark = "x" if str(state).upper() == "DONE" else " "
        return f"[{mark}] {adf_to_text(content, depth=depth + 1)}"
    if node_type == "table":
        return _render_table(content, depth)
    if node_type in ("tableRow", "tableCell", "tableHeader"):
        return _join_blocks(content, depth)

    # Unknown node: keep the text of its children rather than losing content.
    return _join_blocks(content, depth) if content else ""


def _join_blocks(content: Any, depth: int) -> str:
    parts = [adf_to_text(item, depth=depth + 1) for item in content or []]
    return "\n".join(part for part in parts if part.strip())


def _apply_marks(text: str, marks: list[dict[str, Any]] | None) -> str:
    for mark in marks or []:
        mark_type = mark.get("type")
        if mark_type == "strong":
            text = f"**{text}**"
        elif mark_type == "em":
            text = f"*{text}*"
        elif mark_type == "code":
            text = f"`{text}`"
        elif mark_type == "strike":
            text = f"~~{text}~~"
        elif mark_type == "link":
            href = mark.get("attrs", {}).get("href", "")
            if href:
                text = f"[{text}]({href})"
    return text


def _render_list(content: Any, depth: int, *, ordered: bool) -> str:
    lines: list[str] = []
    for index, item in enumerate(content or [], start=1):
        body = adf_to_text(item, depth=depth + 1)
        bullet = f"{index}." if ordered else "-"
        item_lines = body.splitlines() or [""]
        lines.append(f"{bullet} {item_lines[0]}")
        lines.extend(f"  {line}" for line in item_lines[1:])
    return "\n".join(lines)


def _render_task_list(content: Any, depth: int) -> str:
    return "\n".join(
        f"- {adf_to_text(item, depth=depth + 1)}" for item in content or []
    )


def _render_table(content: Any, depth: int) -> str:
    rows: list[list[str]] = []
    for row in content or []:
        if not isinstance(row, dict) or row.get("type") != "tableRow":
            continue
        cells = [
            adf_to_text(cell, depth=depth + 1).replace("\n", " ").strip()
            for cell in row.get("content", [])
        ]
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    header, *body = padded
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def field_to_text(value: Any) -> str:
    """Convert an arbitrary Jira field value to text.

    Handles ADF documents, plain strings, ``{"value": ...}`` option objects,
    lists of any of those, and numbers.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [field_to_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        if value.get("type") == "doc" or "content" in value:
            return adf_to_text(value).strip()
        for key in ("value", "name", "displayName", "text", "key"):
            if key in value and isinstance(value[key], (str, int, float)):
                return str(value[key]).strip()
        return ""
    return str(value)


def truncate(text: str, limit: int, *, marker: str = "\n...[truncated]") -> str:
    """Hard-limit a field so a huge ticket cannot blow up the prompt."""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - len(marker))] + marker
