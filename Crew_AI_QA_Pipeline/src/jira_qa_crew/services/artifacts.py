"""Artifact rendering, safe file layout and ZIP packaging.

Every path segment is sanitised before it touches the filesystem, so ticket
input can never escape the run directory or create arbitrary paths.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from jira_qa_crew.exceptions import ArtifactError
from jira_qa_crew.logging_utils import get_logger
from jira_qa_crew.models import ArtifactRef, RunResult, TicketResult
from jira_qa_crew.services.renderers import (
    render_playwright_markdown,
    render_requirements_markdown,
    render_run_summary_markdown,
    render_test_cases_csv,
    render_test_cases_markdown,
    render_test_plan_markdown,
    render_traceability_csv,
    render_traceability_markdown,
    run_manifest,
    ticket_manifest,
)

logger = get_logger(__name__)

_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_SEGMENT_LEN = 80
_ALLOWED_CODE_SUFFIXES = (".ts", ".tsx", ".json", ".md", ".txt")

#: Hard ceiling for a generated ZIP so the browser download stays sane.
MAX_ZIP_BYTES = 40 * 1024 * 1024


def sanitise_segment(segment: str, *, fallback: str = "item") -> str:
    """Reduce one path segment to a safe, bounded token."""
    text = (segment or "").strip().replace("\\", "/").rstrip("/").split("/")[-1]
    text = _SAFE_SEGMENT_RE.sub("-", text).strip("-. ")
    if text in ("", ".", ".."):
        return fallback
    return text[:_MAX_SEGMENT_LEN]


def sanitise_relative_path(path: str, *, fallback: str = "tests/generated.spec.ts") -> str:
    """Sanitise every segment of a relative path and forbid traversal."""
    raw = (path or "").replace("\\", "/")
    parts = [segment for segment in raw.split("/") if segment not in ("", ".", "..")]
    if not parts:
        return fallback
    cleaned = [sanitise_segment(part) for part in parts[:-1]]
    leaf = sanitise_segment(parts[-1], fallback="generated.spec.ts")
    if not leaf.endswith(_ALLOWED_CODE_SUFFIXES):
        leaf = f"{leaf}.ts"
    cleaned.append(leaf)
    return "/".join(cleaned)


def new_run_id(now: datetime | None = None) -> str:
    """``RUN-YYYYMMDD-HHMMSS`` in UTC."""
    moment = now or datetime.now(UTC)
    return f"RUN-{moment.strftime('%Y%m%d-%H%M%S')}"


def _write(path: Path, content: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    path.write_bytes(data)
    return len(data)


def _media_type(name: str) -> str:
    if name.endswith(".md"):
        return "text/markdown"
    if name.endswith(".csv"):
        return "text/csv"
    if name.endswith(".json"):
        return "application/json"
    if name.endswith(".ts"):
        return "text/plain"
    return "text/plain"


def write_ticket_artifacts(ticket: TicketResult, run_dir: Path) -> list[ArtifactRef]:
    """Render and write every artifact for one ticket.

    Returns the artifact index; artifacts whose source object is missing are
    simply skipped, which is how partially completed tickets stay honest.
    """
    ticket_dir = run_dir / sanitise_segment(ticket.ticket_key, fallback="TICKET")
    refs: list[ArtifactRef] = []

    def add(relative: str, content: str) -> None:
        target = ticket_dir / relative
        try:
            size = _write(target, content)
        except OSError as exc:
            raise ArtifactError(f"Could not write {relative}: {exc}") from exc
        refs.append(
            ArtifactRef(
                name=Path(relative).name,
                relative_path=str(
                    Path(sanitise_segment(ticket.ticket_key, fallback="TICKET"))
                    / relative
                ).replace("\\", "/"),
                media_type=_media_type(relative),
                bytes=size,
            )
        )

    if ticket.analysis is not None:
        add(
            "requirements_analysis.md",
            render_requirements_markdown(ticket.analysis, ticket.issue),
        )
        add(
            "requirements_analysis.json",
            json.dumps(
                ticket.analysis.model_dump(mode="json"), indent=2, ensure_ascii=False
            ),
        )
    if ticket.test_plan is not None and ticket.analysis is not None:
        add("test_plan.md", render_test_plan_markdown(ticket.test_plan, ticket.analysis))
    if ticket.test_cases is not None:
        add("test_cases.md", render_test_cases_markdown(ticket.test_cases))
        add("test_cases.csv", render_test_cases_csv(ticket.test_cases))
    if ticket.traceability is not None:
        add("traceability_matrix.csv", render_traceability_csv(ticket.traceability))
        add("traceability_matrix.md", render_traceability_markdown(ticket.traceability))
    if ticket.playwright is not None and ticket.test_cases is not None:
        add(
            "playwright_tests.md",
            render_playwright_markdown(ticket.playwright, ticket.test_cases),
        )
        for file in ticket.playwright.files:
            relative = f"playwright/{sanitise_relative_path(file.path)}"
            add(relative, file.content)

    ticket.artifacts = refs
    add(
        "manifest.json",
        json.dumps(ticket_manifest(ticket), indent=2, ensure_ascii=False),
    )
    ticket.output_dir = str(ticket_dir)
    return refs


def write_run_artifacts(run: RunResult, run_dir: Path) -> None:
    """Write the run level summary and manifest."""
    _write(run_dir / "run_summary.md", render_run_summary_markdown(run))
    _write(
        run_dir / "manifest.json",
        json.dumps(run_manifest(run), indent=2, ensure_ascii=False),
    )
    run.output_dir = str(run_dir)


def build_run_zip(run: RunResult, run_dir: Path) -> bytes:
    """Package the whole run directory into an in-memory ZIP.

    Built on demand only, and refused above :data:`MAX_ZIP_BYTES`.
    """
    if not run_dir.is_dir():
        raise ArtifactError(f"Run directory does not exist: {run_dir}")

    total = sum(path.stat().st_size for path in run_dir.rglob("*") if path.is_file())
    if total > MAX_ZIP_BYTES:
        raise ArtifactError(
            f"The run output is {total // (1024 * 1024)} MB, which exceeds the "
            f"{MAX_ZIP_BYTES // (1024 * 1024)} MB download limit."
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(run_dir)))
    logger.info("Built ZIP for %s (%s bytes)", run.run_id, buffer.tell())
    return buffer.getvalue()


def build_ticket_zip(ticket: TicketResult) -> bytes:
    """Package a single ticket's artifacts, used for the per-ticket download."""
    ticket_dir = Path(ticket.output_dir)
    if not ticket_dir.is_dir():
        raise ArtifactError(f"Ticket directory does not exist: {ticket_dir}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ticket_dir.rglob("*")):
            if path.is_file():
                archive.write(
                    path, arcname=f"{ticket.ticket_key}/{path.relative_to(ticket_dir)}"
                )
    return buffer.getvalue()


def read_artifact(ticket: TicketResult, relative_path: str) -> str:
    """Read one artifact by its run-relative path (``<TICKET>/<file>``)."""
    base = Path(ticket.output_dir).resolve().parent
    target = (base / relative_path).resolve()
    if not str(target).startswith(str(base)):
        raise ArtifactError("Refusing to read outside the ticket directory.")
    if not target.is_file():
        raise ArtifactError(f"Artifact not found: {relative_path}")
    return target.read_text(encoding="utf-8")
