"""Unit tests for scripts/check_worktree_divergence.py (WOT-2026-038d).

Covers the DoD: (a) a check that compares worktree archives/prompts by
(topic, source_ticket)-equivalent content and FAILS/warns on divergence;
(d) mutation -- introduce a record in only one worktree and confirm the
check detects it.
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.check_worktree_divergence import compare_worktrees, main


def _seed(
    worktree: Path,
    archive_name: str | None = None,
    archive_lines: list[str] | None = None,
    prompt_name: str | None = None,
    prompt_content: str | None = None,
) -> None:
    if archive_name is not None:
        archive_dir = worktree / ".agent" / "runtime" / "memory" / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / archive_name).write_text(
            "\n".join(archive_lines or []) + ("\n" if archive_lines else ""),
            encoding="utf-8",
        )
    if prompt_name is not None:
        prompts_dir = worktree / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        (prompts_dir / prompt_name).write_text(prompt_content or "", encoding="utf-8")


def test_identical_worktrees_report_no_divergence(tmp_path: Path) -> None:
    """Baseline: two worktrees with byte-identical scoped files -> no divergence."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    for wt in (a, b):
        _seed(
            wt,
            archive_name="observations.2026-07.jsonl",
            archive_lines=['{"topic": "x", "source_ticket": "WOT-2026-001a"}'],
            prompt_name="orchestrator_pipeline.md",
            prompt_content="# same content\n",
        )

    result = compare_worktrees(a, b)
    assert result["divergent_files"] == []
    assert result["only_in_a"] == []
    assert result["only_in_b"] == []
    assert result["scanned"] == 2


def test_mutation_record_only_in_one_worktree_is_detected(tmp_path: Path) -> None:
    """(d) DoD mutation: a record added in ONLY one worktree's archive makes
    the files content-differ -- the check must flag divergent_files."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _seed(
        a,
        archive_name="observations.2026-07.jsonl",
        archive_lines=['{"topic": "x", "source_ticket": "WOT-2026-001a"}'],
    )
    _seed(
        b,
        archive_name="observations.2026-07.jsonl",
        archive_lines=[
            '{"topic": "x", "source_ticket": "WOT-2026-001a"}',
            '{"topic": "y", "source_ticket": "WOT-2026-030a"}',
        ],
    )

    result = compare_worktrees(a, b)
    assert "observations.2026-07.jsonl" in [
        Path(rel).name for rel in result["divergent_files"]
    ]


def test_mutation_prompt_identical_line_count_different_content_is_detected(
    tmp_path: Path,
) -> None:
    """(a) The CONSEQUENCE that forced hash-comparison (2026-07-28 amendment):
    two prompts with the SAME line count but DIFFERENT content must be
    flagged. `wc -l` or mtime-based comparison would miss this; sha256 of
    the exact bytes does not."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    # Same line count (3 lines each), one word differs on line 2.
    _seed(
        a,
        prompt_name="orchestrator_session_close_full_audit.md",
        prompt_content="line one\nold normative clause\nline three\n",
    )
    _seed(
        b,
        prompt_name="orchestrator_session_close_full_audit.md",
        prompt_content="line one\nNEW normative clause\nline three\n",
    )

    result = compare_worktrees(a, b)
    assert result["divergent_files"] == [
        "prompts/orchestrator_session_close_full_audit.md"
    ]


def test_file_present_only_in_a_is_reported_as_only_in_a(tmp_path: Path) -> None:
    """A file that exists in one worktree's scope but not the other's is a
    distinct signal from content divergence: `only_in_a`/`only_in_b`, never
    silently ignored or merged into `divergent_files`."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _seed(
        a,
        archive_name="observations.2026-08.jsonl",
        archive_lines=['{"topic": "solo-en-a"}'],
    )

    result = compare_worktrees(a, b)
    assert result["only_in_a"] == [
        ".agent/runtime/memory/archive/observations.2026-08.jsonl"
    ]
    assert result["only_in_b"] == []
    assert result["divergent_files"] == []


def test_file_present_only_in_b_is_reported_as_only_in_b(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _seed(
        b,
        prompt_name="nuevo_prompt.md",
        prompt_content="solo existe en b\n",
    )

    result = compare_worktrees(a, b)
    assert result["only_in_b"] == ["prompts/nuevo_prompt.md"]
    assert result["only_in_a"] == []
    assert result["divergent_files"] == []


def test_main_exits_1_on_divergence_and_0_when_clean(tmp_path: Path) -> None:
    """CLI contract: exit 0 = no divergence, exit 1 = divergence found."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    clean_rc = main(["--worktree-a", str(a), "--worktree-b", str(b)])
    assert clean_rc == 0

    _seed(a, prompt_name="only_a.md", prompt_content="x\n")
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


def test_main_json_output_is_parseable(tmp_path: Path, capsys) -> None:
    """--json emits a single parseable JSON object with the 4 expected keys."""
    import json

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _seed(a, prompt_name="only_a.md", prompt_content="x\n")

    rc = main(["--worktree-a", str(a), "--worktree-b", str(b), "--json"])
    assert rc == 1
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert set(parsed.keys()) == {
        "divergent_files",
        "only_in_a",
        "only_in_b",
        "scanned",
    }
    assert parsed["only_in_a"] == ["prompts/only_a.md"]
