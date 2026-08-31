"""Jira provider contract and shared payload normalisation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from jira_qa_crew.config import AppSettings
from jira_qa_crew.jira.adf import field_to_text, truncate
from jira_qa_crew.models import JiraComment, JiraIssue, ProviderSource

#: Custom field names that commonly carry acceptance criteria.
ACCEPTANCE_CRITERIA_HINTS: tuple[str, ...] = (
    "acceptance criteria",
    "acceptance_criteria",
    "acceptancecriteria",
    "ac",
)


class JiraProvider(ABC):
    """A read-only source of Jira issues."""

    #: Value recorded on the issue so the UI can show where data came from.
    source: ProviderSource

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    @property
    @abstractmethod
    def name(self) -> str:
        """Human readable provider name used in logs and errors."""

    @abstractmethod
    def health_check(self) -> None:
        """Raise a :class:`JiraProviderError` when the provider is unusable."""

    @abstractmethod
    def fetch_issue(self, key: str) -> JiraIssue:
        """Fetch and normalise a single issue. Never mutates Jira."""


def normalise_issue_payload(
    payload: dict[str, Any],
    *,
    key: str,
    source: ProviderSource,
    settings: AppSettings,
) -> JiraIssue:
    """Turn a Jira Cloud ``/issue`` style payload into a :class:`JiraIssue`.

    The function is tolerant: MCP servers frequently return a reshaped
    subset of the REST schema, so both ``payload["fields"]["summary"]`` and a
    flat ``payload["summary"]`` are accepted.
    """
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    merged: dict[str, Any] = {**fields}
    for flat_key, value in payload.items():
        if flat_key not in ("fields", "self", "expand") and flat_key not in merged:
            merged[flat_key] = value

    limit = settings.pipeline_max_field_chars
    issue_key = str(payload.get("key") or merged.get("key") or key).strip().upper()

    description = truncate(field_to_text(merged.get("description")), limit)
    summary = field_to_text(merged.get("summary"))

    return JiraIssue(
        key=issue_key or key.upper(),
        summary=summary,
        description=description,
        issue_type=_nested_name(merged.get("issuetype") or merged.get("issueType")),
        status=_nested_name(merged.get("status")),
        priority=_nested_name(merged.get("priority")),
        labels=_string_list(merged.get("labels")),
        components=[_nested_name(item) for item in _as_list(merged.get("components"))],
        parent_key=_parent_key(merged.get("parent")),
        subtasks=[
            str(item.get("key", "")).upper()
            for item in _as_list(merged.get("subtasks"))
            if isinstance(item, dict) and item.get("key")
        ],
        linked_issues=_linked_issues(merged.get("issuelinks")),
        acceptance_criteria_raw=truncate(
            _acceptance_criteria(merged, settings), limit
        ),
        comments=_comments(merged, settings),
        url=_browse_url(settings, issue_key or key),
        source=source,
        raw=payload,
    )


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


def _nested_name(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "value", "displayName", "key"):
            if value.get(key):
                return str(value[key])
        return ""
    if value in (None, ""):
        return ""
    return str(value)


def _parent_key(value: Any) -> str:
    if isinstance(value, dict) and value.get("key"):
        return str(value["key"]).upper()
    if isinstance(value, str):
        return value.strip().upper()
    return ""


def _linked_issues(value: Any) -> list[str]:
    links: list[str] = []
    for link in _as_list(value):
        if not isinstance(link, dict):
            if isinstance(link, str) and link.strip():
                links.append(link.strip().upper())
            continue
        link_type = ""
        type_info = link.get("type")
        if isinstance(type_info, dict):
            link_type = str(type_info.get("outward") or type_info.get("name") or "")
        for direction in ("outwardIssue", "inwardIssue"):
            target = link.get(direction)
            if isinstance(target, dict) and target.get("key"):
                label = f"{link_type} {str(target['key']).upper()}".strip()
                if label not in links:
                    links.append(label)
    return links


def _acceptance_criteria(fields: dict[str, Any], settings: AppSettings) -> str:
    configured = settings.jira_acceptance_criteria_field.strip()
    if configured and configured in fields:
        text = field_to_text(fields[configured])
        if text:
            return text
    for key, value in fields.items():
        if not key.lower().startswith("customfield"):
            continue
        text = field_to_text(value)
        if text and _looks_like_acceptance_criteria(text):
            return text
    for key, value in fields.items():
        if key.lower().replace(" ", "_") in ACCEPTANCE_CRITERIA_HINTS:
            text = field_to_text(value)
            if text:
                return text
    return ""


def _looks_like_acceptance_criteria(text: str) -> bool:
    lowered = text.lower()
    markers = ("given ", "when ", "then ", "acceptance criteria", "- [ ]")
    return any(marker in lowered for marker in markers) and len(text) > 40


def _comments(fields: dict[str, Any], settings: AppSettings) -> list[JiraComment]:
    if not settings.jira_include_comments:
        return []
    container = fields.get("comment")
    raw_comments = (
        container.get("comments", []) if isinstance(container, dict) else _as_list(container)
    )
    result: list[JiraComment] = []
    for item in raw_comments[: max(0, settings.jira_max_comments)]:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        result.append(
            JiraComment(
                author=_nested_name(author) or "unknown",
                created=str(item.get("created", "")),
                body=truncate(field_to_text(item.get("body")), 4000),
            )
        )
    return result


def _browse_url(settings: AppSettings, key: str) -> str:
    if not settings.jira_url or not key:
        return ""
    return f"{settings.jira_url}/browse/{key}"
