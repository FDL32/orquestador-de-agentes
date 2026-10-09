"""Unit tests for scripts/check_worktree_divergence.py (WOT-2026-038d).

Covers the DoD: (a) a check that compares worktree archives by EXACTLY
(topic, source_ticket) -- the ticket's own wording, adjudicated after Codex
Review 2 on commit ad2b461 found the original whole-file-hash
implementation lost granularity (a 500-record file with one changed record
reported only "the file differs", not which record); (d) mutation --
introduce a record in only one worktree and confirm the check detects it,
AND a record with the SAME key but different content is detected as
divergent (not just presence/absence).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.check_worktree_divergence import compare_worktrees, main


def _seed_archive(worktree: Path, name: str, records: list[dict]) -> None:
    archive_dir = worktree / ".agent" / "runtime" / "memory" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / name).write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )


def _seed_prompt(worktree: Path, name: str, content: str) -> None:
    prompts_dir = worktree / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / name).write_text(content, encoding="utf-8")


def test_identical_worktrees_report_no_divergence(tmp_path: Path) -> None:
    """Baseline: two worktrees with identical scoped records/files -> no divergence."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    record = {"topic": "x", "source_ticket": "WOT-2026-001a", "signal": "same"}
    for wt in (a, b):
        _seed_archive(wt, "observations.2026-07.jsonl", [record])
        _seed_prompt(wt, "orchestrator_pipeline.md", "# same content\n")

    result = compare_worktrees(a, b)
    assert result["divergent_records"] == []
    assert result["only_in_a_records"] == []
    assert result["only_in_b_records"] == []
    assert result["divergent_files"] == []
    assert result["only_in_a"] == []
    assert result["only_in_b"] == []
    assert result["scanned_records"] == 1
    assert result["scanned_files"] == 1


def test_mutation_record_only_in_one_worktree_is_detected(tmp_path: Path) -> None:
    """(d) DoD mutation: a record present in B but absent in A (by
    (topic, source_ticket) key) must be flagged as only_in_b_records,
    identifying the exact file + key, not just "the file differs"."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    shared = {"topic": "x", "source_ticket": "WOT-2026-001a", "signal": "s"}
    extra = {"topic": "y", "source_ticket": "WOT-2026-030a", "signal": "s2"}
    _seed_archive(a, "observations.2026-07.jsonl", [shared])
    _seed_archive(b, "observations.2026-07.jsonl", [shared, extra])

    result = compare_worktrees(a, b)
    assert result["only_in_b_records"] == [
        ".agent/runtime/memory/archive/observations.2026-07.jsonl::y::WOT-2026-030a"
    ]
    assert result["only_in_a_records"] == []
    assert result["divergent_records"] == []


def test_mutation_same_key_different_content_is_a_divergent_record(
    tmp_path: Path,
) -> None:
    """Codex Review 2 finding (ad2b461): a record with the SAME
    (topic, source_ticket) key but DIFFERENT content (e.g. signal text
    edited in one worktree) must be reported as `divergent_records`, naming
    the exact key -- not silently absorbed as "present in both" because the
    key matched, and not reported as a vague whole-file hash mismatch."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    base = {"topic": "x", "source_ticket": "WOT-2026-001a", "signal": "version A"}
    edited = {"topic": "x", "source_ticket": "WOT-2026-001a", "signal": "version B"}
    _seed_archive(a, "observations.2026-07.jsonl", [base])
    _seed_archive(b, "observations.2026-07.jsonl", [edited])

    result = compare_worktrees(a, b)
    assert result["divergent_records"] == [
        ".agent/runtime/memory/archive/observations.2026-07.jsonl::x::WOT-2026-001a"
    ]
    assert result["only_in_a_records"] == []
    assert result["only_in_b_records"] == []


def test_mutation_prompt_identical_line_count_different_content_is_detected(
    tmp_path: Path,
) -> None:
    """(a) The CONSEQUENCE that forced hash-comparison for prompts
    (2026-07-28 amendment): two prompts with the SAME line count but
    DIFFERENT content must be flagged. `wc -l` or mtime-based comparison
    would miss this; sha256 of the exact bytes does not."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _seed_prompt(
        a,
        "orchestrator_session_close_full_audit.md",
        "line one\nold normative clause\nline three\n",
    )
    _seed_prompt(
        b,
        "orchestrator_session_close_full_audit.md",
        "line one\nNEW normative clause\nline three\n",
    )

    result = compare_worktrees(a, b)
    assert result["divergent_files"] == [
        "prompts/orchestrator_session_close_full_audit.md"
    ]


def test_record_present_only_in_a_is_reported(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _seed_archive(
        a, "observations.2026-08.jsonl", [{"topic": "solo-a", "source_ticket": None}]
    )

    result = compare_worktrees(a, b)
    assert result["only_in_a_records"] == [
        ".agent/runtime/memory/archive/observations.2026-08.jsonl::solo-a::None"
    ]
    assert result["only_in_b_records"] == []
    assert result["divergent_records"] == []


def test_prompt_present_only_in_b_is_reported(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _seed_prompt(b, "nuevo_prompt.md", "solo existe en b\n")

    result = compare_worktrees(a, b)
    assert result["only_in_b"] == ["prompts/nuevo_prompt.md"]
    assert result["only_in_a"] == []
    assert result["divergent_files"] == []


def test_corrupt_archive_line_fails_closed(tmp_path: Path) -> None:
    """A JSONL line that fails to parse must raise, not silently skip the
    line or treat the file as empty -- a corrupt archive is a signal in
    itself, never absorbed into "no divergence found"."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    archive_dir = a / ".agent" / "runtime" / "memory" / "archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "observations.2026-07.jsonl").write_text(
        "{not valid json\n", encoding="utf-8"
    )
    _seed_archive(b, "observations.2026-07.jsonl", [])

    with pytest.raises(ValueError, match="linea JSONL invalida"):
        compare_worktrees(a, b)


def test_main_exits_1_on_divergence_and_0_when_clean(tmp_path: Path) -> None:
    """CLI contract: exit 0 = no divergence, exit 1 = divergence found."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    clean_rc = main(["--worktree-a", str(a), "--worktree-b", str(b)])
    assert clean_rc == 0

    _seed_prompt(a, "only_a.md", "x\n")
    diverged_rc = main(["--worktree-a", str(a), "--worktree-b", str(b)])
    assert diverged_rc == 1


def test_main_exits_2_on_missing_worktree(tmp_path: Path) -> None:
    """Usage/config error: a worktree path that does not exist -> exit 2,
    distinguishable from exit 1 (content divergence found)."""
    a = tmp_path / "a"
    a.mkdir()
    missing = tmp_path / "does-not-exist"

    rc = main(["--worktree-a", str(a), "--worktree-b", str(missing)])
    assert rc == 2


def test_main_exits_2_on_corrupt_archive(tmp_path: Path) -> None:
    """Corrupt archive surfaces as exit 2 (config/data error), distinct from
    exit 1 (genuine content divergence)."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    archive_dir = a / ".agent" / "runtime" / "memory" / "archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "observations.2026-07.jsonl").write_text("{bad\n", encoding="utf-8")

    rc = main(["--worktree-a", str(a), "--worktree-b", str(b)])
    assert rc == 2


def test_main_json_output_is_parseable(tmp_path: Path, capsys) -> None:
    """--json emits a single parseable JSON object with the expected keys."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _seed_prompt(a, "only_a.md", "x\n")

    rc = main(["--worktree-a", str(a), "--worktree-b", str(b), "--json"])
    assert rc == 1
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert set(parsed.keys()) == {
        "divergent_records",
        "only_in_a_records",
        "only_in_b_records",
        "scanned_records",
        "divergent_files",
        "only_in_a",
        "only_in_b",
        "scanned_files",
        "scanned",
    }
    assert parsed["only_in_a"] == ["prompts/only_a.md"]
