"""Tests for scripts/census_dogfooding_narrative.py (WOT-2026-025h).

The census CLASSIFIES ticket citations on the distributed surface as ANCLA
(traceability anchor, keep) vs NARRATIVA (dogfooding prose, prunable), plus a
LOW_CONFIDENCE review tier. It NEVER prunes. Design contract (CONTRACT_AUDIT
1->9->2, Codex refuter PROCEED_code_gap_closeable): a DETERMINISTIC, high-
precision, NON-EXHAUSTIVE classifier -- not a semantic oracle.

MUTATION WITH TEETH (the core DoD): a NEW file that travels with dogfooding prose
must be classified NARRATIVA, and its marker-removed TWIN must be ANCLA. The
assertion is on the LABEL, not on file-existence -- a classifier that only
inventoried files (or a bare `WOT-\\d+` regex) would FAIL the twin.

Fixtures are REAL git repos under the system temp (git init + MANIFEST.distribute
+ tracked file), mirroring test_check_distribution_agnostic (build_denominator is
shared and calls `git ls-files`; a non-git tmp would ascend into the real repo --
the WOT-2026-020r walk-up vector).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import REAL_SYSTEM_TEMP


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "census_dogfooding_narrative",
    _ROOT / "scripts" / "census_dogfooding_narrative.py",
)
census = importlib.util.module_from_spec(_SPEC)
# Register before exec so @dataclass can introspect cls.__module__ (it reads
# sys.modules[cls.__module__].__dict__; an unregistered module makes that None).
sys.modules[_SPEC.name] = census
_SPEC.loader.exec_module(census)


# --------------------------------------------------------------------- helpers
def _wb(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30
    )


def _rmtree_ro(path: Path) -> None:
    import shutil
    import stat

    def _onerror(func, p, _exc):
        Path(p).chmod(stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=_onerror)


@pytest.fixture
def fake_motor(request: pytest.FixtureRequest):
    base = REAL_SYSTEM_TEMP / f"cens_{abs(hash(request.node.name)) % 10**8}"
    if base.exists():
        _rmtree_ro(base)
    base.mkdir(parents=True)
    _git(base, "init", "-q")
    _git(base, "config", "user.email", "t@t.t")
    _git(base, "config", "user.name", "t")
    yield base
    request.addfinalizer(lambda: _rmtree_ro(base))


def _commit_all(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "x")


def _census_of(root: Path) -> dict:
    report, err = census.run_census(root)
    assert err is None, err
    return report


def _classes_for(report: dict, file: str) -> dict[int, str]:
    return {h["line"]: h["classification"] for h in report["hits"] if h["file"] == file}


# ------------------------------------------------------------ classify_line unit
def test_code_comment_anchor_wins_over_incident_verb():
    """A `# <TICKET>: ...` code comment is ANCLA even if it carries an incident
    verb -- protects ids asserted by tests (e.g. guard_wiring corpus)."""
    cls, marker = census.classify_line(
        "    # WOT-2026-020o: midio python en PowerShell y disparado por el stale"
    )
    assert cls == census.ANCLA
    assert marker == "code-comment-anchor"


def test_bare_anchor_with_origin_date_is_ancla():
    """Codex G3: a date ALONE is not a narrative marker; a rule anchor with an
    origin date stays ANCLA (else PROJECT.md status rows become false narrative)."""
    cls, _ = census.classify_line(
        "- **Regla:** el numero es evidencia (WOT-2026-024t, 2026-07-19)."
    )
    assert cls == census.ANCLA


def test_narrative_marker_flags_narrativa():
    for line in (
        "Caso historico: WOT-2026-024x dejo dos fugas sin detectar en AGENTS.md.",
        "Caso fundacional (2026-07-15): WOT-2026-020o-B pasaba los 8 gates.",
        "Casos: WOT-2026-020o midio python en PowerShell, no Git Bash.",
        "Evidencia origen: WOT-2026-015e D4 -- EXCLUDE_PATTERNS creaba zona ciega.",
    ):
        cls, _ = census.classify_line(line)
        assert cls == census.NARRATIVA, line


def test_line_without_ticket_is_not_a_hit():
    assert (
        census.classify_line("Caso: algo paso pero sin ticket citado (2026-07-15).")
        is None
    )


def test_soft_verb_is_low_confidence_not_narrativa():
    """Past-fix verb + ticket id, no hard marker -> review candidate, NOT auto
    narrative (the safe, non-oracle direction)."""
    cls, marker = census.classify_line(
        "La causa raiz se corrigio en WP-2026-120 (parser JSON del bridge)."
    )
    assert cls == census.LOW_CONFIDENCE
    assert marker == "soft-verb"


# ------------------------------------------------------------ MUTATION WITH TEETH
def test_mutation_new_narrative_file_is_detected_as_narrativa(fake_motor: Path):
    """DoD mutation: a NEW distributed file carrying dogfooding prose is classified
    NARRATIVA (label assertion, not mere presence)."""
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\nDOGFOOD.md\n")
    _wb(fake_motor / "AGENTS.md", "# rules\nregla estable (WOT-2026-001a).\n")
    # Realistic narrative shape: marker + ticket on the SAME line (the census is
    # deterministically line-scoped; cross-line narrative is an accepted
    # false-negative under the non-exhaustive contract).
    _wb(
        fake_motor / "DOGFOOD.md",
        "Caso historico (2026-07-19): el censo detecto que WOT-2026-999z"
        " tenia narrativa prunable de dogfooding.\n",
    )
    _commit_all(fake_motor)

    report = _census_of(fake_motor)
    dog = _classes_for(report, "DOGFOOD.md")
    assert census.NARRATIVA in dog.values(), report["counts"]
    assert "DOGFOOD.md" in report["files_with_narrative"]
    assert report["counts"]["narrativa"] >= 1


def test_mutation_twin_without_marker_is_ancla_not_narrativa(fake_motor: Path):
    """The NEGATIVE twin: same ticket id, narrative MARKER removed -> ANCLA. A
    classifier that only regex-matched `WOT-\\d+` (no context) would FAIL here by
    calling it NARRATIVA -- this is what gives the mutation teeth."""
    _wb(fake_motor / "MANIFEST.distribute", "DOGFOOD.md\n")
    _wb(
        fake_motor / "DOGFOOD.md",
        "El censo encontro una referencia a WOT-2026-999z (WOT-2026-999z).\n",
    )
    _commit_all(fake_motor)

    report = _census_of(fake_motor)
    dog = _classes_for(report, "DOGFOOD.md")
    assert dog, "expected a hit line"
    assert census.NARRATIVA not in dog.values()
    assert all(c == census.ANCLA for c in dog.values()), dog


def test_denominator_and_counts_published(fake_motor: Path):
    """Census publishes denominator/inspected/skipped + per-class counts."""
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(fake_motor / "AGENTS.md", "Caso historico: WOT-2026-001a fue un incidente.\n")
    _commit_all(fake_motor)

    report = _census_of(fake_motor)
    d = report["denominator"]
    assert d["manifest_entries"] == 1
    assert d["distributed_files_inspected"] == 1
    assert d["files_skipped"] == 0
    assert set(report["counts"]) == {
        "hit_lines_total",
        "narrativa",
        "ancla",
        "low_confidence",
    }


def test_census_is_read_only_never_writes(fake_motor: Path):
    """NON-GOAL guard: running the census mutates nothing on disk (it classifies,
    it never prunes)."""
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(
        fake_motor / "AGENTS.md",
        "Caso historico: WOT-2026-001a.\nregla (WOT-2026-002b).\n",
    )
    _commit_all(fake_motor)
    before = _git(fake_motor, "status", "--porcelain").stdout

    _census_of(fake_motor)

    after = _git(fake_motor, "status", "--porcelain").stdout
    assert before == after == ""


def test_json_output_survives_captured_stdout(fake_motor: Path):
    """Regression (Codex MANAGER_REVIEW 2026-07-19): run(--json) must NOT assume
    sys.stdout.buffer exists. Under an io.StringIO capture (no .buffer) it must
    still emit valid JSON, not crash with AttributeError."""
    import contextlib
    import io

    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(fake_motor / "AGENTS.md", "Caso historico: WOT-2026-001a fue un caso.\n")
    _commit_all(fake_motor)

    buf = io.StringIO()
    assert not hasattr(buf, "buffer")  # the exact failure precondition
    with contextlib.redirect_stdout(buf):
        rc = census.run(["--root", str(fake_motor), "--json"])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert parsed["ticket"] == "WOT-2026-025h"
    assert parsed["counts"]["narrativa"] >= 1


def test_fail_closed_on_missing_manifest(fake_motor: Path):
    """No MANIFEST.distribute -> error, never a silent green 0-file census."""
    report, err = census.run_census(fake_motor)
    assert report == {}
    assert err is not None
