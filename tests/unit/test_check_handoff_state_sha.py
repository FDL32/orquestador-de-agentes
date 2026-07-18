"""Barrier tests for check_handoff_state_sha.py (WOT-2026-024t, surface 2).

The check flags a commit SHA embedded in a handoff's STATE section (it rots when
HEAD moves) while leaving SHAs in historical-commits sections, command examples and
code fences alone. Scope is BY SECTION (heading), never by file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.check_handoff_state_sha import (
    _strip_accents,
    find_state_section_shas,
    main,
    scan_handoffs,
)
from scripts.prepush_check import run_handoff_state_sha_check


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = PROJECT_ROOT / "scripts" / "check_handoff_state_sha.py"

_STATE_SHA = "3721537"  # 7-hex short SHA shape

_STATE_SECTION = (
    f"## Donde esta el vuelo\n\n- HEAD esperado `{_STATE_SHA}`, arbol limpio\n"
)
_HISTORY_SECTION = (
    f"## Historia de commits\n\n| {_STATE_SHA} | fix algo |\n| abcdef1 | otro |\n"
)


def test_sha_in_state_section_is_flagged() -> None:
    hits = find_state_section_shas(_STATE_SECTION)
    assert len(hits) == 1
    assert hits[0]["sha"] == _STATE_SHA
    assert "Donde esta" in hits[0]["heading"]


def test_same_sha_in_history_section_is_not_flagged() -> None:
    """DoD (d): the SAME SHA under a historical-commits heading is legitimate.

    Mutation-to-prove: drop the section scoping and this SHA gets flagged (false red).
    """
    assert find_state_section_shas(_HISTORY_SECTION) == []


def test_both_sections_only_state_is_flagged() -> None:
    text = _STATE_SECTION + "\n" + _HISTORY_SECTION
    hits = find_state_section_shas(text)
    assert len(hits) == 1  # only the state-section occurrence
    assert "Donde esta" in hits[0]["heading"]


def test_sha_in_code_fence_is_not_flagged() -> None:
    text = f"## Estado\n\n```\ngit show {_STATE_SHA}\n```\n"
    assert find_state_section_shas(text) == []


def test_clean_state_section_no_hits() -> None:
    assert (
        find_state_section_shas("## Estado\n\nHEAD verificado con git, sin SHA.\n")
        == []
    )


def test_accented_state_heading_is_flagged() -> None:
    """WOT-2026-034b defect (1): an ACCENTED state heading must be flagged.

    `## Donde esta el vuelo` with the accents present did NOT match the
    unaccented regex (IGNORECASE does not fold accents), so a SHA under it
    escaped the guard -- the motivating flight's own handoff bug. After the
    accent-folding fix it is flagged like its unaccented twin.
    Mutation: drop `_strip_accents` and this test goes red.
    """
    accented = f"## Dónde está el vuelo\n\n- HEAD esperado `{_STATE_SHA}`\n"
    hits = find_state_section_shas(accented)
    assert len(hits) == 1
    assert hits[0]["sha"] == _STATE_SHA
    assert "nde est" in _strip_accents(hits[0]["heading"])


def test_prose_leading_genitive_state_word_is_not_flagged() -> None:
    """WOT-2026-034b defect (2): a state word subordinated by a LEADING genitive is prose.

    In `## Resumen del estado del arte` the subject is "Resumen"; "estado" is its
    genitive object -> prose, not a state section, so its SHA is a legitimate
    reference. Before the fix, `.search()` matched the substring and produced a
    false red. Mutation: drop the leading-genitive guard and this test goes red.
    """
    prose = f"## Resumen del estado del arte de la implementacion\n\ncommit `{_STATE_SHA}`\n"
    assert find_state_section_shas(prose) == []
    # Another genitive-prefixed prose heading:
    prose2 = f"## Analisis del estado de la cuestion\n\nref `{_STATE_SHA}`\n"
    assert find_state_section_shas(prose2) == []


def test_trailing_genitive_state_heading_stays_flagged() -> None:
    """WOT-2026-034b (adversarial audit): `Estado del <thing>` IS a state section.

    `## Estado del motor` / `## Estado del vuelo` / `## Estado de la sesion` are
    the most natural way to write a real state heading in Spanish -- the state
    term is the SUBJECT and `de(l) X` names what is in that state. An earlier,
    over-broad version of this guard suppressed all `<term> de(l) X` as idiom,
    which let a real `## Estado del motor` heading with an embedded HEAD SHA
    escape (found live in flight_20260717/ARRANQUE_NUEVA_SESION.md). These must
    stay flagged. Mutation: re-add a trailing-genitive suppression and this
    regression test goes red.
    """
    for heading in (
        "## Estado del motor (VERIFICA con git; NO confies en este texto)",
        "## Estado del vuelo",
        "## Estado de la sesion",
    ):
        text = f"{heading}\n\n- HEAD esperado `{_STATE_SHA}`\n"
        hits = find_state_section_shas(text)
        assert len(hits) == 1, f"{heading!r} must be a flagged state heading: {hits}"
        assert hits[0]["sha"] == _STATE_SHA


def test_scan_handoffs_finds_arranque(tmp_path: Path) -> None:
    reports = tmp_path / "orchestrator_pipeline" / "reports" / "flight_x"
    reports.mkdir(parents=True)
    (reports / "ARRANQUE_X.md").write_text(_STATE_SECTION, encoding="utf-8")
    findings = scan_handoffs(tmp_path)
    assert len(findings) == 1
    assert findings[0]["sha"] == _STATE_SHA
    assert "ARRANQUE_X.md" in findings[0]["file"]


def test_scan_handoffs_empty_when_no_reports(tmp_path: Path) -> None:
    assert scan_handoffs(tmp_path) == []


def test_main_exit_codes(tmp_path: Path) -> None:
    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True)
    (reports / "ARRANQUE_clean.md").write_text(
        "## Estado\n\nverificado con git\n", encoding="utf-8"
    )
    assert main(["--project-root", str(tmp_path)]) == 0
    (reports / "ARRANQUE_bad.md").write_text(_STATE_SECTION, encoding="utf-8")
    assert main(["--project-root", str(tmp_path)]) == 1


def test_cli_import_runs_by_subprocess(tmp_path: Path) -> None:
    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True)
    (reports / "ARRANQUE_X.md").write_text(_STATE_SECTION, encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(GUARD_PATH), "--project-root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert "Traceback" not in (r.stderr or ""), r.stderr
    assert r.returncode == 1  # the state SHA is flagged


# --- Wiring: WARN default vs FAIL opt-in (anti-M20) ---------------------------


def _handoff_root(tmp_path: Path) -> Path:
    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True)
    (reports / "ARRANQUE_X.md").write_text(_STATE_SECTION, encoding="utf-8")
    return tmp_path


def test_wiring_warn_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HANDOFF_STATE_SHA_STRICT", raising=False)
    res = run_handoff_state_sha_check(_handoff_root(tmp_path))
    assert res.passed is False
    assert res.is_blocking is False
    assert _STATE_SHA in res.output


def test_wiring_strict_opt_in_blocks(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HANDOFF_STATE_SHA_STRICT", "1")
    res = run_handoff_state_sha_check(_handoff_root(tmp_path))
    assert res.passed is False
    assert res.is_blocking is True
    assert _STATE_SHA in res.output
