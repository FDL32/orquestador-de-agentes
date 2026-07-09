"""Mutation-verified barrier tests for CTL-2026-012j (de-acentuacion lossy).

Guards:
(a) A MIXTO document (accented blocks + one de-accented block, >= 100 lines so
    it yields >= 2 blocks of DEACCENT_BLOCK_LINES=50) is flagged by
    find_deaccentuation_lossy / file_issues (the fix).  The OLD structural
    layer (find_text_corruption) does NOT catch it -- that is the false green
    of CTL-2026-012h (de-accented Spanish is valid ASCII and passed the guard).
(b) NEGATIVE cases (no false positives): English/code (baseline ~0), fully
    accented Spanish, a .py file with de-accented Spanish in a docstring
    (extension filter), and a too-short document (< 2 valid blocks).
(c) KNOWN LIMITATION: a COMPLETELY de-accented document has baseline ~0 and is
    NOT flagged (no intra-document baseline) -- documented, not a bug.
(d) Extension filter is not .md-only: a MIXTO .html is flagged.
(e) CLI: check_encoding_guard.py exits 1 on the MIXTO fixture (con fix) and
    exits 0 on a fully accented fixture (no false positive).

Reference convention: tests/unit/test_encoding_guard_c1.py.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_CLI = _MOTOR_ROOT / "scripts" / "check_encoding_guard.py"

from encoding_guard import (  # noqa: E402
    ACCENTED_CHARS,
    DEACCENT_BASELINE_MIN,
    DEACCENT_BLOCK_LINES,
    DEACCENT_MIN_BLOCK_CHARS,
    DEACCENT_PROSE_EXTENSIONS,
    DEACCENT_RATIO_THRESHOLD,
    file_issues,
    find_deaccentuation_lossy,
    find_text_corruption,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _write_utf8(tmp_path: Path, name: str, content: str) -> Path:
    """Write *content* as UTF-8 (no BOM) to a temp file and return the Path."""
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _accented_line(i: int) -> str:
    """A line of accented Spanish prose (carries tildes + n-tilde)."""
    return (
        f"La liturgia católica celebra la solemnidad del Sagrado Corazón con "
        f"himnos y oraciones que reflejan devoción profunda; el incienso "
        f"aromático simboliza la elevación del alma hacia Dios en la "
        f"celebración eucarística número {i} de la composición litúrgica "
        f"tradicional de la parroquia."
    )


def _deaccented_line(i: int) -> str:
    """The same line with all Spanish accents stripped (valid ASCII)."""
    return (
        f"La liturgia catolica celebra la solemnidad del Sagrado Corazon con "
        f"himnos y oraciones que reflejan devocion profunda; el incienso "
        f"aromatico simboliza la elevacion del alma hacia Dios en la "
        f"celebracion eucaristica numero {i} de la composicion liturgica "
        f"tradicional de la parroquia."
    )


# MIXTO fixture: 3 accented blocks (150 lines) + 1 de-accented block (50 lines)
# = 200 lines -> 4 blocks of DEACCENT_BLOCK_LINES=50.  The accented majority
# makes the median baseline reflect the accented norm (robust against the one
# de-accented outlier), mirroring the real 012h case (one de-accented H2 among
# several accented ones).  >= 100 lines and >= 2 blocks per the contract.
def _mixto_text() -> str:
    nl = "\n"
    accented = nl.join(_accented_line(i) for i in range(150))
    deaccented = nl.join(_deaccented_line(i) for i in range(150, 200))
    return accented + nl + deaccented + nl


def _fully_accented_text() -> str:
    nl = "\n"
    return nl.join(_accented_line(i) for i in range(200)) + nl


def _fully_deaccented_text() -> str:
    nl = "\n"
    return nl.join(_deaccented_line(i) for i in range(200)) + nl


def _english_code_text() -> str:
    nl = "\n"
    return (
        nl.join(
            f"The quick brown fox jumps over the lazy dog {i} times in the "
            f"park with code like `def foo(x): return x + 1` and more prose."
            for i in range(200)
        )
        + nl
    )


# ---------------------------------------------------------------------------
# Barrier (a): MIXTO document is flagged (mutation-verify)
# ---------------------------------------------------------------------------


class TestMixtoBarrier:
    """The fix flags a de-accented block inside an accented document."""

    def test_mixto_fixture_has_expected_shape(self) -> None:
        """Fixture is >= 100 lines and yields >= 2 valid blocks."""
        text = _mixto_text()
        lines = text.splitlines()
        assert len(lines) >= 100, f"Fixture too short: {len(lines)} lines"
        valid_blocks = 0
        for start in range(0, len(lines), DEACCENT_BLOCK_LINES):
            block = "\n".join(lines[start : start + DEACCENT_BLOCK_LINES])
            if len(block) >= DEACCENT_MIN_BLOCK_CHARS:
                valid_blocks += 1
        assert valid_blocks >= 2, f"Need >= 2 valid blocks, got {valid_blocks}"

    def test_old_structural_layer_is_false_green(self) -> None:
        """BEFORE the fix: find_text_corruption does NOT catch de-accentuation.

        This is the false green of CTL-2026-012h: de-accented Spanish is valid
        ASCII, so the structural-corruption layer returns nothing.
        """
        assert find_text_corruption(_mixto_text()) == [], (
            "PREMISE BROKEN: find_text_corruption should not flag de-accented "
            "Spanish (it is valid ASCII). This is the gap the fix closes."
        )

    def test_find_deaccentuation_flags_mixto(self) -> None:
        """AFTER the fix: find_deaccentuation_lossy flags the de-accented block."""
        result = find_deaccentuation_lossy(_mixto_text())
        assert result, (
            "BARRIER FAILURE: find_deaccentuation_lossy did not flag the "
            f"de-accented block in the MIXTO fixture. result={result!r}"
        )

    def test_deaccent_snippet_is_descriptive(self) -> None:
        """The snippet names the line, the ratio and the baseline."""
        result = find_deaccentuation_lossy(_mixto_text())
        snippet = result[0]
        assert "deaccent-lossy" in snippet, f"Missing marker: {snippet!r}"
        assert "line" in snippet and "ratio" in snippet and "baseline" in snippet, (
            f"Snippet lacks line/ratio/baseline: {snippet!r}"
        )

    def test_file_issues_flags_mixto_md(self, tmp_path: Path) -> None:
        """file_issues reports the de-accented block in text_corruption (.md)."""
        p = _write_utf8(tmp_path, "mixto.md", _mixto_text())
        _mj, _qm, corruption = file_issues(p)
        assert corruption, (
            "BARRIER FAILURE: file_issues did not report the de-accented block "
            f"in text_corruption. corruption={corruption!r}"
        )
        assert any("deaccent-lossy" in s for s in corruption), (
            f"Expected a deaccent-lossy snippet, got: {corruption!r}"
        )

    def test_only_the_deaccented_block_is_flagged(self) -> None:
        """The accented blocks are NOT flagged; only the de-accented one is."""
        result = find_deaccentuation_lossy(_mixto_text())
        # The de-accented block starts at line 151 (3 * 50 + 1).
        assert len(result) == 1, (
            f"Expected exactly 1 flagged block, got {len(result)}: {result!r}"
        )
        assert "line 151" in result[0], f"Expected line 151, got: {result!r}"


# ---------------------------------------------------------------------------
# Barrier (b): NEGATIVE cases (no false positives)
# ---------------------------------------------------------------------------


class TestNegativeCases:
    """Legitimate low-accent content is NOT flagged."""

    def test_english_code_not_flagged(self) -> None:
        """English/code has baseline ~0 -> not flagged (no false positive)."""
        assert find_deaccentuation_lossy(_english_code_text()) == [], (
            "FALSE POSITIVE: English/code text was flagged."
        )

    def test_fully_accented_spanish_not_flagged(self) -> None:
        """A fully accented Spanish document is NOT flagged."""
        assert find_deaccentuation_lossy(_fully_accented_text()) == [], (
            "FALSE POSITIVE: fully accented Spanish was flagged."
        )

    def test_py_deaccented_docstring_not_flagged(self, tmp_path: Path) -> None:
        """A .py file with de-accented Spanish in a docstring is NOT flagged.

        The extension filter excludes .py from the de-accentuation check.
        """
        py_content = '"""\n' + _fully_deaccented_text() + '"""\n'
        p = _write_utf8(tmp_path, "module.py", py_content)
        _mj, _qm, corruption = file_issues(p)
        deaccent = [s for s in corruption if "deaccent-lossy" in s]
        assert deaccent == [], (
            "FALSE POSITIVE: .py with de-accented docstring was flagged "
            f"(extension filter failed): {deaccent!r}"
        )

    def test_short_document_not_flagged(self) -> None:
        """A document with fewer than 2 valid blocks is NOT flagged."""
        # 10 short lines -> 1 block, well under DEACCENT_MIN_BLOCK_CHARS.
        short = "\n".join(f"linea corta numero {i}" for i in range(10)) + "\n"
        assert find_deaccentuation_lossy(short) == [], (
            "FALSE POSITIVE: short document was flagged."
        )

    def test_empty_text_not_flagged(self) -> None:
        """Empty text is NOT flagged."""
        assert find_deaccentuation_lossy("") == []
        assert find_deaccentuation_lossy("\n\n\n") == []


# ---------------------------------------------------------------------------
# Barrier (c): KNOWN LIMITATION -- completely de-accented document
# ---------------------------------------------------------------------------


class TestKnownLimitationFullyDeaccented:
    """A COMPLETELY de-accented document is NOT flagged (known limitation).

    The detector compares blocks against the intra-document baseline.  When
    every block is de-accented, the baseline is ~0 (< DEACCENT_BASELINE_MIN),
    so there is no accented norm to compare against.  Catching fully
    de-accented Spanish needs a global repo baseline or a Spanish dictionary
    (follow-up).  This is a documented limitation, NOT a bug.
    """

    def test_fully_deaccented_not_flagged(self) -> None:
        result = find_deaccentuation_lossy(_fully_deaccented_text())
        assert result == [], (
            "LIMITATION CHECK: a fully de-accented document should NOT be "
            f"flagged (no intra-document baseline). result={result!r}"
        )

    def test_fully_deaccented_baseline_below_min(self) -> None:
        """The baseline of a fully de-accented doc is < DEACCENT_BASELINE_MIN."""
        import statistics

        lines = _fully_deaccented_text().splitlines()
        ratios = []
        for start in range(0, len(lines), DEACCENT_BLOCK_LINES):
            block = "\n".join(lines[start : start + DEACCENT_BLOCK_LINES])
            if len(block) < DEACCENT_MIN_BLOCK_CHARS:
                continue
            alpha = sum(1 for ch in block if ch.isalpha())
            if alpha:
                ratios.append(sum(1 for ch in block if ch in ACCENTED_CHARS) / alpha)
        baseline = statistics.median(ratios) if ratios else 0.0
        assert baseline < DEACCENT_BASELINE_MIN, (
            f"Fully de-accented baseline should be < {DEACCENT_BASELINE_MIN}, "
            f"got {baseline!r}"
        )


# ---------------------------------------------------------------------------
# Barrier (d): extension filter is not .md-only
# ---------------------------------------------------------------------------


class TestExtensionFilter:
    """The de-accentuation check applies to .md/.html/.txt/.xml, not just .md."""

    @pytest.mark.parametrize("ext", [".html", ".txt", ".xml"])
    def test_prose_extension_mixto_flagged(self, ext: str, tmp_path: Path) -> None:
        """A MIXTO fixture with a non-.md prose extension IS flagged.

        A filter misconfigured to only accept .md would pass the other tests
        but fail this one.
        """
        p = _write_utf8(tmp_path, f"mixto{ext}", _mixto_text())
        _mj, _qm, corruption = file_issues(p)
        assert any("deaccent-lossy" in s for s in corruption), (
            f"BARRIER FAILURE: extension {ext} was NOT flagged (filter not "
            f"applied to non-.md prose). corruption={corruption!r}"
        )

    def test_py_extension_not_in_prose_set(self) -> None:
        """.py is NOT in DEACCENT_PROSE_EXTENSIONS (code is excluded)."""
        assert ".py" not in DEACCENT_PROSE_EXTENSIONS
        assert ".json" not in DEACCENT_PROSE_EXTENSIONS
        assert ".yaml" not in DEACCENT_PROSE_EXTENSIONS

    def test_prose_extensions_exact_set(self) -> None:
        """DEACCENT_PROSE_EXTENSIONS is exactly {.md, .html, .txt, .xml}."""
        assert frozenset({".md", ".html", ".txt", ".xml"}) == DEACCENT_PROSE_EXTENSIONS


# ---------------------------------------------------------------------------
# Barrier (e): CLI exit codes (check_encoding_guard.py)
# ---------------------------------------------------------------------------


class TestCliExitCodes:
    """check_encoding_guard.py exits 1 on the MIXTO fixture, 0 on accented."""

    def _run_cli(self, fixture: Path) -> int:
        return subprocess.run(
            [sys.executable, str(_CLI), str(fixture)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).returncode

    def test_cli_mixto_md_exit1(self, tmp_path: Path) -> None:
        """Con fix: the MIXTO .md fixture makes the CLI exit 1 (blocked)."""
        p = _write_utf8(tmp_path, "mixto.md", _mixto_text())
        rc = self._run_cli(p)
        assert rc == 1, (
            f"BARRIER FAILURE: CLI should exit 1 on MIXTO fixture (con fix), "
            f"got {rc}. (sin fix this was 0 = the false green of 012h.)"
        )

    def test_cli_accented_md_exit0(self, tmp_path: Path) -> None:
        """A fully accented .md fixture makes the CLI exit 0 (no false positive)."""
        p = _write_utf8(tmp_path, "acento.md", _fully_accented_text())
        rc = self._run_cli(p)
        assert rc == 0, (
            f"FALSE POSITIVE: CLI should exit 0 on accented fixture, got {rc}."
        )

    def test_cli_html_mixto_exit1(self, tmp_path: Path) -> None:
        """The CLI also blocks a MIXTO .html fixture (extension not .md-only)."""
        p = _write_utf8(tmp_path, "mixto.html", _mixto_text())
        rc = self._run_cli(p)
        assert rc == 1, f"CLI should exit 1 on MIXTO .html, got {rc}."


# ---------------------------------------------------------------------------
# Barrier (f): thresholds are the measured constants (not magic literals)
# ---------------------------------------------------------------------------


class TestThresholdConstants:
    """The thresholds exist as named constants with the measured values."""

    def test_constants_exist(self) -> None:
        assert frozenset("áéíóúüñÁÉÍÓÚÜÑ") == ACCENTED_CHARS
        assert DEACCENT_BLOCK_LINES == 50
        assert DEACCENT_MIN_BLOCK_CHARS == 200
        assert DEACCENT_BASELINE_MIN == 0.015
        assert DEACCENT_RATIO_THRESHOLD == 0.10

    def test_accented_chars_spanish_only(self) -> None:
        """ACCENTED_CHARS covers Spanish acute + diaeresis + n-tilde, no others."""
        for ch in "áéíóúüñÁÉÍÓÚÜÑ":
            assert ch in ACCENTED_CHARS
        # Grave/circumflex diacritics of other languages are NOT included.
        for ch in "àèìòùÀÈÌÒÙâêîôûç":
            assert ch not in ACCENTED_CHARS
