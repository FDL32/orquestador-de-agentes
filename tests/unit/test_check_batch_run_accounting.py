"""Tests for scripts/check_batch_run_accounting.py (WOT-2026-025k).

Contract under test: in a `batch_run_<ts>.json` from the autonomous batch,
`group_stop_reports` (GSR) must never reference a ticket ABSENT from the
`tickets{}` index. Origin (F1 2026-07-16): PREDICATE #3
(`contabilidad_completa`) self-declared PASS with an incomplete `tickets{}`;
an auditor re-deriving the universe solely from `tickets{}` would silently
lose GSR-only tickets -- a false green.

`tickets` may appear as a dict keyed by ticket-id, a list of
`{id, ...}` objects, or be entirely absent (empty universe).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_batch_run(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "batch_run_20260716-0900.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_orphan_gsr_ticket_fails(tmp_path: Path) -> None:
    """GSR references a ticket absent from tickets{} (dict form) -> orphan detected."""
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {
        "tickets": {
            "WOT-2026-021r": {"state": "closed"},
        },
        "group_stop_reports": [
            {"group": "G-X", "ticket": "WOT-2026-021r", "state": "closed"},
            {"group": "G-Y", "ticket": "WOT-2026-099z", "state": "frozen"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == ["WOT-2026-099z"]


def test_complete_legitimate_batch_run_passes(tmp_path: Path) -> None:
    """Positive fixture: every GSR ticket is present in tickets{} -> no orphans.

    Guards against gate_false_positive_legitimate_input: a correct, complete
    batch_run must never be flagged.
    """
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {
        "tickets": {
            "WOT-2026-021q": {"state": "frozen-with-GROUP_STOP_REPORT"},
            "WOT-2026-016r": {"state": "frozen-with-GROUP_STOP_REPORT"},
            "WOT-2026-022f": {"state": "closed"},
        },
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-021q", "state": "frozen"},
            {"group": "G-B", "ticket": "WOT-2026-016r", "state": "frozen"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == []


def test_tickets_as_list_form(tmp_path: Path) -> None:
    """tickets{} may be a list of {id, ...} objects instead of a dict."""
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {
        "tickets": [
            {"id": "WOT-2026-021r", "state": "closed"},
            {"id": "WOT-2026-024g", "state": "closed"},
        ],
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-021r", "state": "closed"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == []


def test_tickets_as_list_form_detects_orphan(tmp_path: Path) -> None:
    """List form: an orphan GSR ticket is still detected."""
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {
        "tickets": [
            {"id": "WOT-2026-021r", "state": "closed"},
        ],
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-099z", "state": "frozen"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == ["WOT-2026-099z"]


def test_tickets_absent_means_empty_universe(tmp_path: Path) -> None:
    """tickets{} entirely absent -> empty universe; any GSR ticket is orphan."""
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-021r", "state": "frozen"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == ["WOT-2026-021r"]


def test_no_group_stop_reports_is_trivially_clean(tmp_path: Path) -> None:
    """Absent group_stop_reports -> nothing to reconcile, no orphans."""
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    payload = {"tickets": {"WOT-2026-021r": {"state": "closed"}}}
    batch_run = _write_batch_run(tmp_path, payload)

    orphans = check_batch_run_accounting(batch_run)

    assert orphans == []


def test_cli_exit_code_1_prints_orphans(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """CLI contract: orphan(s) present -> exit 1, orphan ticket name(s) printed."""
    from scripts.check_batch_run_accounting import main

    payload = {
        "tickets": {"WOT-2026-021r": {"state": "closed"}},
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-099z", "state": "frozen"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    rc = main([str(batch_run)])

    assert rc == 1
    captured = capsys.readouterr()
    assert "WOT-2026-099z" in captured.out


def test_cli_exit_code_0_when_complete(tmp_path: Path) -> None:
    """CLI contract: complete accounting -> exit 0."""
    from scripts.check_batch_run_accounting import main

    payload = {
        "tickets": {"WOT-2026-021r": {"state": "closed"}},
        "group_stop_reports": [
            {"group": "G-A", "ticket": "WOT-2026-021r", "state": "closed"},
        ],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    rc = main([str(batch_run)])

    assert rc == 0


def test_cli_accepts_dash_dash_file_flag(tmp_path: Path) -> None:
    """CLI also accepts --file as an alternative to the positional arg."""
    from scripts.check_batch_run_accounting import main

    payload = {
        "tickets": {"WOT-2026-021r": {"state": "closed"}},
        "group_stop_reports": [],
    }
    batch_run = _write_batch_run(tmp_path, payload)

    rc = main(["--file", str(batch_run)])

    assert rc == 0
