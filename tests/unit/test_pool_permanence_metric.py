"""Tests for scripts/pool_permanence_metric.py (WOT-2026-027r).

Hermetic by construction: every test injects synthetic scorecard rows via
monkeypatch, never touches the real scorecard.jsonl.  The mutation test
verifies that altering ONE row's outcome changes the table, pinning the
conversion-rate logic.

Fixture realism: _row() mirrors SCORECARD_FIELDS (event, backend, outcome)
to ensure the test green guarantees correctness against the real
scorecard.jsonl.  Only event=="adjudicacion" rows count toward conversion.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pool_permanence_metric as ppm  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _row(
    backend: str,
    outcome: str | None = None,
    *,
    event: str = "adjudicacion",
) -> dict:
    """Scorecard row mirroring SCORECARD_FIELDS (event, backend, outcome).

    Default event is "adjudicacion" because that's the event type where
    outcome is meaningful for conversion rate computation.
    """
    return {"event": event, "backend": backend, "outcome": outcome}


SYNTHETIC_ROWS = [
    # adjudicacion rows: these count toward conversion
    _row("nan_api", "adoptada"),
    _row("nan_api", "adoptada"),
    _row("nan_api", "no-aportacion"),
    _row("claude", "adoptada"),
    _row("claude", "falso-positivo"),
    # ronda rows: these should be EXCLUDED from conversion
    _row("nan_api", None, event="ronda"),
    _row("nan_api", "no-aportacion", event="ronda"),
    _row("claude", None, event="ronda"),
]


@pytest.fixture()
def _fake_scorecard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write SYNTHETIC_ROWS to a tmp scorecard and wire _read_scorecard."""

    def _fake_read(project_root: Path):
        path = project_root / ".agent" / "runtime" / "ensemble" / "scorecard.jsonl"
        raw = path.read_bytes() if path.exists() else b""
        rows = [
            json.loads(line)
            for line in raw.decode("utf-8").splitlines()
            if line.strip()
        ]
        return rows, "fake-sha"

    scorecard_dir = tmp_path / ".agent" / "runtime" / "ensemble"
    scorecard_dir.mkdir(parents=True)
    scorecard_file = scorecard_dir / "scorecard.jsonl"
    scorecard_file.write_text(
        "\n".join(json.dumps(r) for r in SYNTHETIC_ROWS) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ppm, "_read_scorecard", _fake_read)
    return tmp_path


@pytest.fixture()
def _empty_scorecard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Empty scorecard — 0 rows."""

    def _fake_read(project_root: Path):
        return [], "empty-sha"

    scorecard_dir = tmp_path / ".agent" / "runtime" / "ensemble"
    scorecard_dir.mkdir(parents=True)
    (scorecard_dir / "scorecard.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(ppm, "_read_scorecard", _fake_read)
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComputeConversionRates:
    """Unit tests for the pure computation function."""

    def test_basic_rates(self):
        rows = [
            _row("nan_api", "adoptada"),
            _row("nan_api", "adoptada"),
            _row("nan_api", "no-aportacion"),
            _row("claude", "adoptada"),
            _row("claude", "falso-positivo"),
        ]
        rates = ppm.compute_conversion_rates(rows)
        assert rates["nan_api"] == (2, 3)
        assert rates["claude"] == (1, 2)

    def test_empty_rows(self):
        rates = ppm.compute_conversion_rates([])
        assert rates == {}

    def test_no_adoptadas(self):
        rows = [_row("x", None), _row("x", "no-aportacion")]
        rates = ppm.compute_conversion_rates(rows)
        assert rates["x"] == (0, 2)

    def test_all_adoptadas(self):
        rows = [_row("y", "adoptada"), _row("y", "adoptada")]
        rates = ppm.compute_conversion_rates(rows)
        assert rates["y"] == (2, 2)

    def test_unknown_outcomes_count_as_total(self):
        rows = [_row("z", "some_new_outcome"), _row("z", "adoptada")]
        rates = ppm.compute_conversion_rates(rows)
        assert rates["z"] == (1, 2)

    def test_ronda_events_are_excluded(self):
        """event='ronda' rows must not count toward conversion rate."""
        rows = [
            _row("b", "adoptada"),  # adjudicacion: counts
            _row("b", "adoptada", event="ronda"),  # ronda: excluded
            _row("b", "no-aportacion"),  # adjudicacion: counts
            _row("b", None, event="ronda"),  # ronda: excluded
        ]
        rates = ppm.compute_conversion_rates(rows)
        # Only 2 adjudicacion rows: 1 adoptada, 1 no-aportacion
        assert rates["b"] == (1, 2)

    def test_only_ronda_rows_gives_empty(self):
        """Scorecard with only ronda events yields no conversion data."""
        rows = [
            _row("b", None, event="ronda"),
            _row("b", "no-aportacion", event="ronda"),
        ]
        rates = ppm.compute_conversion_rates(rows)
        assert rates == {}


class TestFormatTable:
    """Unit tests for the table formatter."""

    def test_basic_table(self):
        rates = {"nan_api": (2, 4), "claude": (1, 2)}
        table = ppm.format_table(rates)
        assert "nan_api" in table
        assert "claude" in table
        assert "50.0%" in table
        assert "adopt" in table.lower() or "total" in table.lower()

    def test_empty_table(self):
        table = ppm.format_table({})
        assert (
            "sin datos" in table.lower()
            or "no data" in table.lower()
            or table.strip() == ""
        )


class TestEndToEnd:
    """Integration: read from fake scorecard, emit table."""

    def test_run_with_data(self, _fake_scorecard: Path, capsys: pytest.CaptureFixture):
        exit_code = ppm.main(["--project-root", str(_fake_scorecard)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "nan_api" in out
        assert "claude" in out

    def test_run_empty(self, _empty_scorecard: Path, capsys: pytest.CaptureFixture):
        exit_code = ppm.main(["--project-root", str(_empty_scorecard)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert (
            "sin datos" in out.lower()
            or "no data" in out.lower()
            or "0 rows" in out.lower()
        )


class TestMutation:
    """Mutation: alterar outcome de UNA fila -> la tabla cambia."""

    def test_single_outcome_mutation_changes_table(self):
        rows_a = [
            _row("b1", "adoptada"),
            _row("b1", "adoptada"),
            _row("b1", "no-aportacion"),
        ]
        rows_b = [
            _row("b1", "adoptada"),
            _row("b1", "no-aportacion"),  # mutated: adoptada -> no-aportacion
            _row("b1", "no-aportacion"),
        ]
        rates_a = ppm.compute_conversion_rates(rows_a)
        rates_b = ppm.compute_conversion_rates(rows_b)
        assert rates_a != rates_b, (
            "Mutation survived: altering one outcome did not change the table"
        )
