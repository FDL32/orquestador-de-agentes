"""Contract tests for scripts/check_portable_memory_archive_schema.py (WOT-2026-035b).

The guard validates the SCHEMA of the tracked portable-memory archive
(`.agent/runtime/memory/archive/observations.YYYY-MM.jsonl`, the ONLY vehicle
that travels to destination projects). On 2026-07-18 that archive carried 2
entries with a NON-canonical schema (`task_type`/`lesson` instead of
`applies_to`/`signal`/`timestamp`/`source`/`confidence`/`source_ticket`,
commits 2f610e9+5df84ec) and no wired barrier caught it: `validate_observations.py`
existed but nothing that runs on its own invoked it over the archive.

Load-bearing properties:

1. The guard REUSES `validate_observations.validate_file` (imports it, does not
   reimplement schema logic). Test (a) uses the exact INCIDENT pattern as the
   broken fixture, not an arbitrary invalid value.

2. Exit codes are DIFFERENTIATED: 0 = schema OK (including the empty-glob case,
   which is INTENTIONAL for a schema guard: a fresh repo_destino has no
   portable memory yet, and that is not a schema finding), 1 = the TOOL
   failed, 4 = at least one archive entry is schema-invalid.

3. Mutation with teeth: removing the broken entry from the broken fixture must
   flip the same test from exit 4 to exit 0, proving the exit 4 verdict was
   actually caused by that entry and not by some other property of the fixture
   (e.g. an unrelated tool error).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "check_portable_memory_archive_schema.py"
)
ARCHIVE_DIR_REL = Path(".agent/runtime/memory/archive")

EXIT_OK = 0
EXIT_TOOL_ERROR = 1
EXIT_SCHEMA_INVALID = 4


def _valid_entry(source_ticket: str = "WOT-2026-035b") -> dict:
    """Shape copied from a real canonical entry in
    .agent/runtime/memory/archive/observations.2026-07.jsonl (motor)."""
    return {
        "timestamp": "2026-07-18T00:00:00Z",
        "topic": "archive-schema-guard",
        "signal": "entrada canonica valida para el contract-test del guard de schema",
        "source": "test",
        "domain": "delivery-hygiene",
        "confidence": 0.9,
        "applies_to": "mixed",
        "source_ticket": source_ticket,
    }


def _incident_pattern_entry() -> dict:
    """The EXACT non-canonical shape from the 2026-07-18 incident: wrong field
    NAMES (`task_type`/`lesson`), missing every required field of the
    canonical schema (topic/domain/applies_to/signal/confidence/source_ticket)."""
    return {
        "task_type": "refactor",
        "lesson": "x",
        "timestamp": "2026-07-18T00:00:00Z",
        "source": "y",
    }


def _write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8", newline="\n"
    )


def _make_repo(tmp_path: Path) -> Path:
    """A real git repo (the guard refuses to audit a non-repo: exit 1)."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*a: str) -> None:
        subprocess.run(
            ["git", *a], cwd=str(repo), capture_output=True, text=True, check=True
        )

    run("init", "-b", "main")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "README").write_text("x", encoding="utf-8")
    run("add", "-A")
    run("commit", "-m", "base")
    return repo


def _run(repo: Path) -> subprocess.CompletedProcess:
    # returncode read directly -- never `$?` after a pipe.
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--motor-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_incident_pattern_entry_is_a_schema_finding(tmp_path: Path) -> None:
    """(a) THE GUARD'S TEST: an archive entry shaped like the 2026-07-18
    incident (task_type/lesson instead of the canonical schema) must be
    caught -> exit 4, with a line-level "missing required field" message.
    """
    repo = _make_repo(tmp_path)
    _write(
        repo / ARCHIVE_DIR_REL / "observations.2026-07.jsonl",
        [_incident_pattern_entry()],
    )

    r = _run(repo)

    assert r.returncode == EXIT_SCHEMA_INVALID, (
        "an archive entry with the incident's non-canonical schema must be a "
        f"FINDING (exit 4); got {r.returncode}. stdout: {r.stdout} stderr: {r.stderr}"
    )
    combined = r.stdout + r.stderr
    assert "falta campo obligatorio" in combined, (
        "the guard must surface validate_observations' line-level "
        f"missing-required-field error. stdout: {r.stdout} stderr: {r.stderr}"
    )


def test_valid_entry_is_clean(tmp_path: Path) -> None:
    """(b) A single canonical entry -> exit 0."""
    repo = _make_repo(tmp_path)
    _write(
        repo / ARCHIVE_DIR_REL / "observations.2026-07.jsonl",
        [_valid_entry()],
    )

    r = _run(repo)
    assert r.returncode == EXIT_OK, (
        f"a canonical archive entry must pass; got {r.returncode}. "
        f"stdout: {r.stdout} stderr: {r.stderr}"
    )


def test_zero_archive_files_is_clean(tmp_path: Path) -> None:
    """(c) The archive dir exists but has no observations.*.jsonl -> exit 0.

    This is INTENTIONAL, not an oversight: the guard checks SCHEMA, not
    presence. A freshly cloned repo_destino has no portable memory yet, and
    that is not a schema violation. Presence/data-loss is a different
    property owned by check_portable_memory_promotion.py (NON-GOAL here).
    """
    repo = _make_repo(tmp_path)
    (repo / ARCHIVE_DIR_REL).mkdir(parents=True)

    r = _run(repo)
    assert r.returncode == EXIT_OK, (
        f"zero archive files must be clean (schema guard, not presence guard); "
        f"got {r.returncode}. stdout: {r.stdout} stderr: {r.stderr}"
    )


def test_mutation_removing_broken_entry_flips_finding_to_clean(tmp_path: Path) -> None:
    """MUTATION WITH TEETH: start from the exact broken fixture of (a), remove
    the incident-pattern entry, and the SAME test must now pass (exit 0). This
    proves the exit 4 verdict in (a) was caused by that entry specifically,
    not by an unrelated tool error or a fixture bug.
    """
    repo = _make_repo(tmp_path)
    archive_file = repo / ARCHIVE_DIR_REL / "observations.2026-07.jsonl"
    _write(archive_file, [_incident_pattern_entry()])

    broken = _run(repo)
    assert broken.returncode == EXIT_SCHEMA_INVALID, (
        "precondition: the broken fixture must fail before mutation; "
        f"got {broken.returncode}"
    )

    # Mutate: replace the broken entry with a CANONICAL valid one (not an empty
    # file). This proves POSITIVE schema compliance -- the fixed state passes
    # because the entry is valid, not merely because errors are absent -- so the
    # test does not silently rely on validate_file's "empty file == valid"
    # contract (MANAGER_REVIEW qwen3, WOT-2026-035b).
    _write(archive_file, [_valid_entry()])

    fixed = _run(repo)
    assert fixed.returncode == EXIT_OK, (
        "after replacing the incident-pattern entry with a valid one, the same "
        f"archive file must pass; got {fixed.returncode}. stdout: {fixed.stdout} "
        f"stderr: {fixed.stderr}"
    )


def test_non_repo_root_is_a_tool_error_not_a_finding(tmp_path: Path) -> None:
    """Exit 1 (tool failure) must NOT be confused with exit 4 (schema finding).

    `tmp_path` lives inside the motor tree, so a plain directory there still
    answers `git rev-parse --show-toplevel` with the MOTOR's root. The guard
    requires --motor-root to BE the toplevel (assert_git_repo), otherwise it
    would audit the wrong repository and call it clean.
    """
    not_a_repo = tmp_path / "plain"
    (not_a_repo / ARCHIVE_DIR_REL).mkdir(parents=True)
    _write(
        not_a_repo / ARCHIVE_DIR_REL / "observations.2026-07.jsonl",
        [_valid_entry()],
    )

    r = _run(not_a_repo)
    assert r.returncode == EXIT_TOOL_ERROR, (
        "a path that is not a git checkout root is a TOOL failure (exit 1), "
        f"not a finding; got {r.returncode}"
    )
