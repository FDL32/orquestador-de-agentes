"""Mutation-verified barrier tests for WOT-2026-014d.

Guards:
(a) Reinjecting ANY C1 codepoint into a fixture -> file_issues / guard flags it.
(b) Reinjecting an invalid UTF-8 byte -> flagged by the strict-decode layer.
(c) NEGATIVE CASE (the crux): a string that IS valid UTF-8 but contains a C1
    codepoint (U+0094) PASSES decode('utf-8', errors='strict') AND is STILL
    flagged by the C1-range check (proves strict alone is insufficient).
(d) Demonstrate the guard BEFORE the fix lets the real builder-self-audit
    corruption pass; the HARDENED guard blocks it (mutation-verify against a
    fixture identical to the pre-fix content).

Reference healthy skills: skills/test-driven-development/SKILL.md and
    skills/systematic-debugging/SKILL.md.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Import the module under test.  Use the scripts/ path so this works both
# from the motor root and via run_pytest_safe.
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

import pytest


_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from encoding_guard import (  # noqa: E402
    check_utf8_strict,
    file_issues,
    find_c1_controls,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_utf8(tmp_path: Path, name: str, content: str) -> Path:
    """Write *content* as UTF-8 (no BOM) to a temp file and return the Path."""
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _write_raw(tmp_path: Path, name: str, raw_bytes: bytes) -> Path:
    """Write *raw_bytes* directly to a temp file and return the Path."""
    p = tmp_path / name
    p.write_bytes(raw_bytes)
    return p


# ---------------------------------------------------------------------------
# Barrier (a): reinjecting ANY C1 codepoint -> guard flags it
# ---------------------------------------------------------------------------


class TestC1RangeBarrierInjection:
    """Reinjecting a C1 codepoint into a fixture makes the hardened guard flag it."""

    @pytest.mark.parametrize(
        "c1_cp",
        [
            0x0080,
            0x0085,
            0x008C,
            0x0092,
            0x0094,
            0x009F,
        ],
    )
    def test_c1_codepoint_flagged_by_find_c1_controls(self, c1_cp: int) -> None:
        """find_c1_controls returns a non-empty list for any C1 codepoint."""
        text = "clean prefix " + chr(c1_cp) + " clean suffix"
        result = find_c1_controls(text)
        assert result, (
            f"BARRIER FAILURE: C1 codepoint U+{c1_cp:04X} was NOT flagged by "
            f"find_c1_controls.  Result: {result!r}"
        )
        assert f"<U+{c1_cp:04X}>" in result[0], (
            f"Expected <U+{c1_cp:04X}> in snippet, got: {result!r}"
        )

    @pytest.mark.parametrize("c1_cp", [0x0085, 0x008C, 0x0092, 0x0094])
    def test_c1_codepoint_flagged_via_file_issues(
        self, c1_cp: int, tmp_path: Path
    ) -> None:
        """file_issues reports the C1 codepoint in the third (text_corruption) element."""
        text = "some markdown content " + chr(c1_cp) + " more content"
        p = _write_utf8(tmp_path, "fixture.md", text)
        _mj, _qm, corruption = file_issues(p)
        assert corruption, (
            f"BARRIER FAILURE: file_issues did not report corruption for "
            f"C1 codepoint U+{c1_cp:04X}.  corruption={corruption!r}"
        )
        assert any(f"<U+{c1_cp:04X}>" in s for s in corruption), (
            f"Expected <U+{c1_cp:04X}> in corruption snippets, got: {corruption!r}"
        )

    def test_clean_text_no_false_positive(self) -> None:
        """Clean ASCII + valid Latin-1 supplement do NOT trigger the C1 guard."""
        # Include legitimate Latin chars (Spanish accents, em-dash, arrows)
        clean = (
            "Paso 1 — Verificacion tipo-especifica\n"
            "- ✅ Sin output → OK\n"
            "- ❌ Hay output → Error\n"
            "El codigo original maneja errores, accion, solucion\n"
            "\xe1 \xe9 \xed \xf3 \xfa \xf1"
        )
        result = find_c1_controls(clean)
        assert result == [], (
            f"FALSE POSITIVE: find_c1_controls flagged clean text: {result!r}"
        )

    def test_latin1_supplement_letters_not_flagged(self) -> None:
        """Latin-1 Supplement letters (U+00A0-U+00FF) are NOT flagged.

        The guard must NOT ban legitimate accented chars; only the C1 CONTROL
        range (U+0080-U+009F) is prohibited.
        """
        # U+00A0 = no-break space, U+00C0-U+00FF = various Latin letters/symbols
        # None of these are in C1 (U+0080-U+009F)
        non_c1_latin = "".join(chr(cp) for cp in range(0x00A0, 0x0100))
        result = find_c1_controls(non_c1_latin)
        assert result == [], (
            f"FALSE POSITIVE: Latin-1 Supplement chars (U+00A0-U+00FF) were "
            f"flagged as C1 controls: {result!r}"
        )


# ---------------------------------------------------------------------------
# Barrier (b): invalid UTF-8 bytes -> strict-decode layer flags it
# ---------------------------------------------------------------------------


class TestStrictDecodeBarrier:
    """Reinjecting an invalid UTF-8 byte sequence triggers the strict-decode check."""

    def test_invalid_utf8_lone_continuation_flagged(self, tmp_path: Path) -> None:
        """A lone continuation byte (0x80) is not valid UTF-8 -> flagged."""
        # 0x80 as a lone byte is invalid UTF-8 (continuation byte without lead)
        raw = b"clean content " + b"\x80" + b" more content"
        p = _write_raw(tmp_path, "invalid.md", raw)
        result = check_utf8_strict(p)
        assert result, (
            f"BARRIER FAILURE: check_utf8_strict did not flag invalid UTF-8 "
            f"lone continuation byte 0x80.  Result: {result!r}"
        )
        assert "invalid-utf8" in result[0], f"Expected diagnostic, got: {result!r}"

    def test_invalid_utf8_overlong_flagged(self, tmp_path: Path) -> None:
        r"""An overlong sequence (0xC0 0x80 = NUL) is not valid UTF-8 -> flagged."""
        raw = b"text " + b"\xc0\x80" + b" end"
        p = _write_raw(tmp_path, "overlong.md", raw)
        result = check_utf8_strict(p)
        assert result, (
            r"BARRIER FAILURE: check_utf8_strict did not flag overlong sequence "
            r"\xc0\x80.  Result: " + repr(result)
        )

    def test_invalid_utf8_flagged_via_file_issues(self, tmp_path: Path) -> None:
        """file_issues includes the strict-decode diagnostic in the third element.

        When the file has invalid UTF-8 bytes, file_issues returns early with
        only the strict-decode diagnostic to avoid a UnicodeDecodeError from
        load_text.  The third element (text_corruption) contains the diagnostic.
        """
        raw = b"markdown " + b"\xff" + b" content"  # 0xFF is invalid UTF-8 start
        p = _write_raw(tmp_path, "bad.md", raw)
        mojibake, _qm, corruption = file_issues(p)
        assert corruption, (
            f"BARRIER FAILURE: file_issues did not report corruption for "
            f"invalid UTF-8 byte 0xFF.  corruption={corruption!r}"
        )
        assert any("invalid-utf8" in s for s in corruption), (
            f"Expected invalid-utf8 diagnostic in corruption, got: {corruption!r}"
        )
        # When strict-decode fails, mojibake is empty (early return)
        assert mojibake == [], (
            f"Expected empty mojibake for invalid-UTF-8 file: {mojibake!r}"
        )

    def test_valid_utf8_no_false_positive(self, tmp_path: Path) -> None:
        """A clean UTF-8 file does NOT trigger check_utf8_strict."""
        text = "valid UTF-8: — → ✅ ❌ \xe1 \xf3"
        p = _write_utf8(tmp_path, "clean.md", text)
        result = check_utf8_strict(p)
        assert result == [], f"FALSE POSITIVE on valid UTF-8: {result!r}"


# ---------------------------------------------------------------------------
# Barrier (c): NEGATIVE CASE - valid UTF-8 + C1 passes strict but IS flagged
# ---------------------------------------------------------------------------


class TestValidUtf8WithC1NegativeCase:
    """THE CRUX: proves that strict-decode alone is insufficient.

    A string containing a C1 codepoint (e.g. U+0094) encodes to valid UTF-8
    bytes (C2 94), so decode('utf-8', errors='strict') succeeds WITHOUT error.
    The file would be silently corrupted.  The C1-range check catches what
    strict alone misses.
    """

    def test_valid_utf8_with_c1_passes_strict_decode(self) -> None:
        """Premise: U+0094 encoded as UTF-8 passes strict decode (no exception)."""
        c1_char = chr(0x0094)
        encoded_bytes = c1_char.encode("utf-8")
        assert encoded_bytes == b"\xc2\x94", (
            f"Unexpected encoding for U+0094: {encoded_bytes!r}"
        )
        # This must NOT raise - that is the whole point
        decoded = encoded_bytes.decode("utf-8", errors="strict")
        assert decoded == c1_char, f"Decoded value mismatch: {decoded!r}"

    def test_strict_decode_alone_does_not_flag_c1(self, tmp_path: Path) -> None:
        """Strict-decode of a file with C1 content returns NO error (silent drift)."""
        text = "step header " + chr(0x0094) + " Verificacion"
        p = _write_utf8(tmp_path, "c1_file.md", text)
        # This is the behavior for strict decode alone: no flag raised
        strict_result = check_utf8_strict(p)
        assert strict_result == [], (
            "PREMISE BROKEN: strict-decode should not flag valid UTF-8+C1 content; "
            "this test validates the gap that makes strict alone insufficient."
        )

    def test_c1_range_check_catches_what_strict_misses(self, tmp_path: Path) -> None:
        """While strict-decode passes, find_c1_controls DOES flag the C1 char.

        This is the core mutation-verification: the hardened guard catches the
        corruption that strict-decode alone would silently allow.
        """
        c1_char = chr(0x0094)
        text = "step header " + c1_char + " Verificacion"
        p = _write_utf8(tmp_path, "c1_file.md", text)

        # Strict decode: PASSES (no error) - the gap
        strict_result = check_utf8_strict(p)
        assert strict_result == [], "Strict decode should pass for valid UTF-8+C1"

        # C1 range check: CATCHES IT - the hardened barrier
        c1_result = find_c1_controls(text)
        assert c1_result, (
            "BARRIER FAILURE: find_c1_controls did not catch U+0094 that passed "
            "strict decode.  This is the crux mutation-verification."
        )
        assert "<U+0094>" in c1_result[0], f"Expected <U+0094>, got: {c1_result!r}"

    def test_file_issues_catches_what_strict_misses(self, tmp_path: Path) -> None:
        """file_issues flags C1 content even though strict-decode passes silently."""
        text = (
            "### Paso 1 "
            + chr(0x0094)
            + " Verificacion\n"
            + "- "
            + chr(0x00DC)
            + chr(0x0085)
            + " Sin output\n"
        )
        p = _write_utf8(tmp_path, "c1_markers.md", text)

        # Strict check: no error (UTF-8 is valid)
        assert check_utf8_strict(p) == [], "Strict should pass for valid UTF-8+C1"

        # file_issues third element: flags the C1 chars via find_c1_controls
        _mj, _qm, corruption = file_issues(p)
        assert corruption, (
            "BARRIER FAILURE: file_issues did not flag C1 content that passed "
            "strict-decode.  corruption=" + repr(corruption)
        )
        c1_snippets = [s for s in corruption if "<U+" in s]
        assert c1_snippets, (
            f"Expected <U+xxxx> C1 snippets in corruption, got: {corruption!r}"
        )


# ---------------------------------------------------------------------------
# Barrier (d): before fix vs after fix mutation-verify
# ---------------------------------------------------------------------------


class TestBeforeAfterFixMutation:
    """Guard before the fix lets the real builder-self-audit corruption pass
    silently; the hardened guard blocks it.

    This uses a fixture IDENTICAL to the pre-fix builder-self-audit content
    (pairs of non-C1 Latin + C1 codepoints).
    """

    # Pre-fix fixture: the 4 corruption pairs as seen in builder-self-audit
    # before WOT-2026-014d was applied.
    _PREFX_FRAGMENT = (
        "### Paso 1 "
        + chr(0x00C0)
        + chr(0x0094)  # A-grave + C1 = corrupted em-dash
        + " Verificacion tipo-especifica\n"
        "\n"
        "- "
        + chr(0x00DC)
        + chr(0x0085)  # U-umlaut + C1 = corrupted checkmark
        + " Sin output "
        + chr(0x00C6)
        + chr(0x0092)  # AE + C1 = corrupted arrow
        + " OK\n"
        "- "
        + chr(0x00DD)
        + chr(0x008C)  # Y-acute + C1 = corrupted cross
        + " Hay output "
        + chr(0x00C6)
        + chr(0x0092)  # AE + C1 = corrupted arrow
        + " Error de sintaxis\n"
    )

    def test_prefx_fragment_has_expected_c1_codepoints(self) -> None:
        """The pre-fix fixture contains exactly the 4 C1 codepoints."""
        c1_in_fixture = sorted(
            {hex(ord(c)) for c in self._PREFX_FRAGMENT if 0x80 <= ord(c) <= 0x9F}
        )
        assert c1_in_fixture == ["0x85", "0x8c", "0x92", "0x94"], (
            f"Fixture C1 mismatch: {c1_in_fixture!r}"
        )

    def test_pre_fix_behavior_strict_decode_passes_silently(
        self, tmp_path: Path
    ) -> None:
        """BEFORE the fix: strict-decode passes the pre-fix content (silent drift).

        This demonstrates the OLD behavior: no exception from strict-decode,
        so the corruption would have been undetected by a strict-only guard.
        """
        p = _write_utf8(tmp_path, "pre_fix.md", self._PREFX_FRAGMENT)
        strict_result = check_utf8_strict(p)
        assert strict_result == [], (
            "PREMISE BROKEN: strict-decode should not flag valid UTF-8 with C1 "
            f"content.  Got: {strict_result!r}"
        )

    def test_hardened_guard_blocks_pre_fix_content(self, tmp_path: Path) -> None:
        """AFTER hardening: file_issues flags the pre-fix C1 content.

        This is the mutation-verification: the same content that the old guard
        (strict-decode only) would have allowed silently is now CAUGHT by the
        hardened C1-range check.
        """
        p = _write_utf8(tmp_path, "pre_fix.md", self._PREFX_FRAGMENT)
        _mj, _qm, corruption = file_issues(p)
        assert corruption, (
            "BARRIER FAILURE: hardened guard did not flag the pre-fix builder-"
            "self-audit corruption fixture.  corruption=" + repr(corruption)
        )
        # Verify all 4 C1 codepoints are flagged
        reported_c1 = {s.split(">")[0][1:] for s in corruption if s.startswith("<U+")}
        expected_c1 = {"U+0085", "U+008C", "U+0092", "U+0094"}
        assert expected_c1 <= reported_c1, (
            f"Not all C1 codepoints reported.  Expected subset {expected_c1}, "
            f"got {reported_c1}"
        )

    def test_post_fix_builder_self_audit_passes_hardened_guard(self) -> None:
        """The re-encoded (post-fix) builder-self-audit has 0 C1 -> guard green.

        Reads the ACTUAL file from disk (not a fixture) to confirm the guard
        is green over the real file after WOT-2026-014d re-encoding.
        """
        motor_root = Path(__file__).resolve().parents[2]
        skill_path = motor_root / "skills" / "builder-self-audit" / "SKILL.md"
        assert skill_path.exists(), (
            f"builder-self-audit/SKILL.md not found at {skill_path}"
        )

        text = skill_path.read_text(encoding="utf-8")
        c1_in_file = [hex(ord(c)) for c in set(text) if 0x80 <= ord(c) <= 0x9F]
        assert c1_in_file == [], (
            f"REGRESSION: post-fix builder-self-audit still has C1 codepoints: "
            f"{sorted(c1_in_file)}"
        )

        _mj, _qm, corruption = file_issues(skill_path)
        c1_corruption = [s for s in corruption if s.startswith("<U+")]
        assert c1_corruption == [], (
            f"REGRESSION: hardened guard flags C1 in post-fix file: {c1_corruption!r}"
        )
