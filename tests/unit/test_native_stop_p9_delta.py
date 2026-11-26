#!/usr/bin/env python3
"""Delta de WOT-2026-215b sobre la antigua superficie P9.

Before: el hook conserva los helpers de topologia necesarios por el vuelo.
During: se prueban fail-open, resolucion CO, descubrimiento y retirada lexica.
After: no queda predicado P9 ni razon de aviso, y la nueva rama no usa runtime
del motor como salida.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / ".agent" / "hooks" / "native_stop_hook.py"
sys.path.insert(0, str(ROOT / ".agent" / "hooks"))
import native_stop_hook as hook  # noqa: E402


def _root(tmp_path: Path) -> Path:
    """Before: tmp_path is empty; During: creates repo marker; After: returns isolated root."""
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    return root


def _flight(root: Path, name: str = "flight-1") -> Path:
    """Before: root exists; During: writes roster; After: returns flight directory."""
    flight = root / ".agent" / "runtime" / "flight" / name
    flight.mkdir(parents=True)
    (flight / "flight_roster.json").write_text(
        json.dumps(
            {
                "active_roles": {
                    "orquestador": {"session_code": "CO-1", "estado": "ACTIVO"}
                }
            }
        ),
        encoding="utf-8",
    )
    return flight


def test_fail_open_consult_exception_never_changes_decision(tmp_path, monkeypatch):
    """Before: consult helper raises; During: _decide catches it; After: continue is preserved."""
    root = _root(tmp_path)
    flight = _flight(root)
    (flight / "stop_consult_mode.json").write_text(
        json.dumps({"mode": "block"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        hook,
        "_consult_branch",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("x")),
    )
    result = hook._decide({"cwd": str(root), "stop_hook_active": True})
    assert result == {"continue": True}


def test_m04_no_forbidden_stop_literals():
    """Before: source is loaded; During: scans the actual hook; After: old P9 channel literals stay absent."""
    source = HOOK_PATH.read_text(encoding="utf-8")
    assert all(
        token not in source
        for token in (
            "additionalContext",
            "permissionDecision",
            "sys.exit(2",
            "SystemExit(2",
        )
    )


def test_co_resolution_preserved(tmp_path):
    """Before: roster has one coordinator alias; During: resolves it; After: code is retained."""
    flight = _flight(_root(tmp_path))
    assert hook._p9_resolve_co_activa(flight) == "CO-1"


def test_co_resolution_ambiguous_fails_open(tmp_path):
    """Before: both aliases are present; During: shared resolver rejects ambiguity; After: no code is selected."""
    flight = _flight(_root(tmp_path))
    (flight / "flight_roster.json").write_text(
        json.dumps(
            {
                "active_roles": {
                    "orquestador": {"session_code": "CO-1"},
                    "coordinadora": {"session_code": "CO-2"},
                }
            }
        ),
        encoding="utf-8",
    )
    assert hook._p9_resolve_co_activa(flight) is None


def test_flight_discovery_zero_one_many(tmp_path):
    """Before: linked topology contains zero, one, then two rosters; After: helper distinguishes all cases."""
    root = _root(tmp_path)
    assert hook._p9_flight_dir(root) is None
    _flight(root, "one")
    assert hook._p9_flight_dir(root).name == "one"
    _flight(root, "two")
    assert hook._p9_flight_dir(root) is None


def test_p9_lexical_branch_removed():
    """Before: source is the production hook; During: checks retired names; After: zero occurrences."""
    source = HOOK_PATH.read_text(encoding="utf-8")
    assert source.count("P9_ANNOUNCE_ANCHORS") == 0
    assert source.count("_p9_cola_no_vacia") == 0


def test_consult_branch_has_explicit_fail_open_boundary(tmp_path):
    """Before: active flight has malformed mode; During: direct process run; After: continue and no row."""
    root = _root(tmp_path)
    flight = _flight(root)
    (flight / "stop_consult_mode.json").write_text("{roto", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(HOOK_PATH)],
        input=json.dumps({"cwd": str(root), "stop_hook_active": False}).encode(),
        cwd=root,
        capture_output=True,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"continue": True}
    assert not (flight / "stop_consult_observations.jsonl").exists()
