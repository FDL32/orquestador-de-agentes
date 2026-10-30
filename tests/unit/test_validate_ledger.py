#!/usr/bin/env python3
"""Tests for scripts/flight/validate_ledger.py (WOT-2026-136h).

Tests the validator: legacy reported without blocking (rc 0),
rc 2 only if unreadable, never fixes a count as criterion.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
_VALIDATE_LEDGER = _SCRIPTS_DIR / "flight" / "validate_ledger.py"

# Fixed schema keys (N3).
FIXED_KEYS = {
    "ts",
    "by",
    "a",
    "modo",
    "resultado",
    "error",
    "providerInstanceId",
    "mensaje_id",
    "nota",
}


def _run_validator(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    """Run the validator CLI and return the result."""
    env = dict(__import__("os").environ)
    env.pop("FLIGHT_ROSTER_PATH", None)
    return subprocess.run(
        [sys.executable, str(_VALIDATE_LEDGER), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        cwd=str(tmp_path),
    )


class TestValidatorLegacyReportedNotBlocked:
    """Legacy lines are INFORMED, not blocked (rc 0)."""

    def test_validator_empty_ledger_rc0(self, tmp_path):
        """Empty ledger -> rc 0, informs 0 lines."""
        ledger = tmp_path / "empty.jsonl"
        ledger.write_text("", encoding="utf-8")
        proc = _run_validator(["--ledger", str(ledger)], tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "0 linea(s) total" in proc.stdout

    def test_validator_all_fixed_schema_rc0(self, tmp_path):
        """All lines with fixed schema -> rc 0, no legacy."""
        ledger = tmp_path / "comms.jsonl"
        record = json.dumps(
            {
                "ts": "2026-01-01",
                "by": "test",
                "a": "mcp:x",
                "modo": "auto",
                "resultado": "enviado",
                "error": "",
                "providerInstanceId": "",
                "mensaje_id": "m1",
                "nota": "",
            },
            ensure_ascii=False,
        )
        ledger.write_text(record + "\n", encoding="utf-8")
        proc = _run_validator(["--ledger", str(ledger)], tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (
            "legacy: 0 linea(s)" not in proc.stdout and "legacy:" not in proc.stdout
        ), "When all lines match the fixed schema, no legacy section should appear"

    def test_validator_has_legacy_reports_rc0(self, tmp_path):
        """Lines with different key sets are classified as legacy and REPORTED, rc 0."""
        ledger = tmp_path / "mixed.jsonl"
        # Write BOTH lines to the same file (fixed schema + legacy)
        with open(ledger, "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": "2026-01-01",
                        "by": "test",
                        "a": "mcp:x",
                        "modo": "auto",
                        "resultado": "enviado",
                        "error": "",
                        "providerInstanceId": "",
                        "mensaje_id": "m1",
                        "nota": "",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "ts": "2026-01-01",
                        "por": "old_actor",
                        "cambio": "test",
                        "motivo": "old reason",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        proc = _run_validator(["--ledger", str(ledger)], tmp_path)
        assert proc.returncode == 0, (
            proc.stdout + proc.stderr
        )  # Never rc != 0 with legacy
        assert "legacy: 1 linea(s)" in proc.stdout

    def test_validator_all_legacy_reports_rc0(self, tmp_path):
        """All lines are legacy -> rc 0, all reported."""
        ledger = tmp_path / "all_legacy.jsonl"
        ledger.write_text(
            json.dumps({"old_key": "old_value"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        proc = _run_validator(["--ledger", str(ledger)], tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "legacy: 1 linea(s)" in proc.stdout

    def test_validator_multiple_key_sets(self, tmp_path):
        """Multiple distinct key sets are all counted and reported as legacy."""
        ledger = tmp_path / "multi_legacy.jsonl"
        ledger.write_text(
            json.dumps({"a": 1, "b": 2}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps({"x": 1, "y": 2, "z": 3}, ensure_ascii=False) + "\n")
        proc = _run_validator(["--ledger", str(ledger)], tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "legacy: 2 linea(s)" in proc.stdout


class TestValidatorIllegible:
    """rc 2 only when the file cannot be read."""

    def test_validator_nonexistent_file_rc2(self, tmp_path):
        """Nonexistent ledger -> rc 2."""
        proc = _run_validator(["--ledger", str(tmp_path / "no.jsonl")], tmp_path)
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "ilegible" in proc.stdout

    def test_validator_non_utf8_file_rc2_no_traceback(self, tmp_path):
        """A ledger that is not valid UTF-8 -> rc 2 'ilegible', never a Traceback."""
        ledger = tmp_path / "non_utf8.jsonl"
        ledger.write_bytes(b"\xff\xfe\x00 bad bytes\n")
        proc = _run_validator(["--ledger", str(ledger)], tmp_path)
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "Traceback" not in proc.stderr, proc.stderr
        assert "ilegible" in proc.stdout
        assert "UTF-8" in proc.stdout

    def test_validator_empty_file_is_readable_rc0(self, tmp_path):
        """Positive control for the previous test: an EMPTY file is readable (rc 0)."""
        ledger = tmp_path / "empty_ok.jsonl"
        ledger.write_bytes(b"")
        proc = _run_validator(["--ledger", str(ledger)], tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_validator_invalid_json_lines_not_rc2(self, tmp_path):
        """Non-JSON lines -> rc 0, not rc 2."""
        ledger = tmp_path / "invalid.jsonl"
        ledger.write_text("this is not json\n" + "neither is this\n", encoding="utf-8")
        proc = _run_validator(["--ledger", str(ledger)], tmp_path)
        assert proc.returncode == 0, (
            proc.stdout + proc.stderr
        )  # Non-JSON is not illegible


class TestValidatorNoCountAsCriterion:
    """The validator never fixes a count as a criterion."""

    def test_validator_never_blocks_on_legacy_count(self, tmp_path):
        """Even with many legacy lines, rc is always 0."""
        ledger = tmp_path / "many_legacy.jsonl"
        ledger.write_text("", encoding="utf-8")
        for i in range(20):
            with open(ledger, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps({"legacy_key_" + str(i): i}, ensure_ascii=False) + "\n"
                )
        proc = _run_validator(["--ledger", str(ledger)], tmp_path)
        assert proc.returncode == 0, "validator must never block on legacy count"
        assert "legacy: 20 linea(s)" in proc.stdout
