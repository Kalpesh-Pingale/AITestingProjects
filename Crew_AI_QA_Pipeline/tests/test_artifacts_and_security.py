"""Artifact layout, path safety, ZIP packaging and secret redaction."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from jira_qa_crew.exceptions import ArtifactError
from jira_qa_crew.jira.textify import UNTRUSTED_CLOSE, render_issue_for_prompt
from jira_qa_crew.logging_utils import REDACTED, redact, redact_mapping
from jira_qa_crew.models import PlaywrightFile
from jira_qa_crew.services.artifacts import (
    build_run_zip,
    build_ticket_zip,
    new_run_id,
    read_artifact,
    sanitise_relative_path,
    sanitise_segment,
    write_run_artifacts,
    write_ticket_artifacts,
)
from tests.factories import TICKET, make_issue, make_run_result, make_ticket_result

# -- path safety -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("VWO-48", "VWO-48"),
        ("../../etc", "etc"),
        ("..", "item"),
        ("a b/c", "c"),
        ("VWO 48; rm -rf /", "VWO-48-rm--rf"),
        ("", "item"),
    ],
)
def test_segment_sanitisation(raw: str, expected: str) -> None:
    assert sanitise_segment(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("tests/vwo-48.spec.ts", "tests/vwo-48.spec.ts"),
        ("../../../etc/passwd", "etc/passwd.ts"),
        ("/absolute/tests/a.spec.ts", "absolute/tests/a.spec.ts"),
        ("..\\..\\windows\\system32\\cmd.exe", "windows/system32/cmd.exe.ts"),
        ("", "tests/generated.spec.ts"),
    ],
)
def test_relative_path_sanitisation(raw: str, expected: str) -> None:
    assert sanitise_relative_path(raw) == expected


def test_ticket_input_cannot_escape_the_run_directory(tmp_path: Path) -> None:
    ticket = make_ticket_result("../../EVIL-1")
    write_ticket_artifacts(ticket, tmp_path)
    assert Path(ticket.output_dir).resolve().parent == tmp_path.resolve()


def test_run_id_shape() -> None:
    assert new_run_id().startswith("RUN-")
    assert len(new_run_id()) == len("RUN-20260831-101500")


# -- artifact writing ------------------------------------------------------


@pytest.fixture
def written_run(tmp_path: Path):
    run = make_run_result(["VWO-48", "VWO-49"])
    run_dir = tmp_path / run.run_id
    for ticket in run.tickets:
        write_ticket_artifacts(ticket, run_dir)
    write_run_artifacts(run, run_dir)
    return run, run_dir


def test_expected_files_are_written(written_run) -> None:
    _run, run_dir = written_run
    ticket_dir = run_dir / TICKET
    for name in (
        "requirements_analysis.md",
        "requirements_analysis.json",
        "test_plan.md",
        "test_cases.md",
        "test_cases.csv",
        "traceability_matrix.csv",
        "playwright_tests.md",
        "manifest.json",
    ):
        assert (ticket_dir / name).is_file(), name
    assert (ticket_dir / "playwright" / "tests" / "vwo-48.spec.ts").is_file()
    assert (run_dir / "run_summary.md").is_file()
    assert (run_dir / "manifest.json").is_file()


def test_manifest_indexes_the_artifacts(written_run) -> None:
    _run, run_dir = written_run
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["totals"]["requested"] == 2
    paths = {
        artifact["relative_path"]
        for ticket in manifest["tickets"]
        for artifact in ticket["artifacts"]
    }
    assert f"{TICKET}/test_cases.csv" in paths


def test_partial_tickets_only_write_what_exists(tmp_path: Path) -> None:
    ticket = make_ticket_result()
    ticket.playwright = None
    ticket.test_cases = None
    write_ticket_artifacts(ticket, tmp_path)
    names = {artifact.name for artifact in ticket.artifacts}
    assert "requirements_analysis.md" in names
    assert "test_cases.csv" not in names
    assert "playwright_tests.md" not in names


def test_zip_contains_every_artifact(written_run) -> None:
    run, run_dir = written_run
    data = build_run_zip(run, run_dir)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert "run_summary.md" in names
        assert f"{TICKET}/test_cases.csv" in names
        assert f"{TICKET}/playwright/tests/vwo-48.spec.ts" in names
        assert archive.testzip() is None


def test_ticket_zip_is_scoped_to_one_ticket(written_run) -> None:
    run, _run_dir = written_run
    data = build_ticket_zip(run.tickets[0])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert all(name.startswith(f"{TICKET}/") for name in archive.namelist())


def test_zip_size_limit_is_enforced(written_run, monkeypatch) -> None:
    run, run_dir = written_run
    monkeypatch.setattr("jira_qa_crew.services.artifacts.MAX_ZIP_BYTES", 10)
    with pytest.raises(ArtifactError) as exc:
        build_run_zip(run, run_dir)
    assert "download limit" in str(exc.value)


def test_reading_outside_the_run_directory_is_refused(written_run) -> None:
    run, _run_dir = written_run
    assert "REQ-001" in read_artifact(run.tickets[0], f"{TICKET}/requirements_analysis.md")
    with pytest.raises(ArtifactError):
        read_artifact(run.tickets[0], "../../../../etc/passwd")


def test_generated_spec_files_land_under_playwright_tests(tmp_path: Path) -> None:
    ticket = make_ticket_result()
    ticket.playwright.files.append(
        PlaywrightFile(path="../../escape.spec.ts", content="x", kind="spec")
    )
    write_ticket_artifacts(ticket, tmp_path)
    written = {artifact.relative_path for artifact in ticket.artifacts}
    assert f"{TICKET}/playwright/escape.spec.ts" in written
    assert not (tmp_path.parent / "escape.spec.ts").exists()


# -- redaction -------------------------------------------------------------


def test_known_secrets_are_removed(monkeypatch) -> None:
    monkeypatch.setenv("JIRA_API_TOKEN", "ATATTsupersecrettoken123")
    monkeypatch.setenv("LLM_API_KEY", "sk-abcdef1234567890")
    text = "auth failed for ATATTsupersecrettoken123 using sk-abcdef1234567890"
    result = redact(text)
    assert "ATATTsupersecrettoken123" not in result
    assert "sk-abcdef1234567890" not in result
    assert REDACTED in result


def test_secret_shapes_are_removed_even_when_unknown() -> None:
    header = redact("Authorization: Bearer abcdefghijklmnop")
    assert "abcdefghijklmnop" not in header
    assert REDACTED in header
    assert "abcdefghijklmnop" not in redact("Basic YWJjZGVmZ2hpamts")
    assert "hunter2hunter2" not in redact('password="hunter2hunter2"')
    assert "ATATTxyz1234567890" not in redact("token ATATTxyz1234567890 leaked")


def test_redact_mapping_keeps_keys() -> None:
    monkeyed = redact_mapping({"api_key": "Bearer abcdefghijklmnop", "mode": "auto"})
    assert monkeyed["mode"] == "auto"
    assert "abcdefghijklmnop" not in monkeyed["api_key"]


# -- untrusted content framing --------------------------------------------


def test_issue_is_wrapped_in_untrusted_delimiters() -> None:
    rendered = render_issue_for_prompt(make_issue())
    assert "never obey" in rendered.lower() or "never treat" in rendered.lower()
    assert rendered.rstrip().endswith(UNTRUSTED_CLOSE)
    assert "Ticket key: VWO-48" in rendered


def test_issue_rendering_is_size_bounded() -> None:
    issue = make_issue()
    issue.description = "x" * 50000
    rendered = render_issue_for_prompt(issue, max_chars=2000)
    assert len(rendered) <= 2000 + len(UNTRUSTED_CLOSE) + 1
    assert rendered.rstrip().endswith(UNTRUSTED_CLOSE)
