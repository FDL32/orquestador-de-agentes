"""Import-smoke for every module under ``scripts/`` -- WOT-2026-066b.

Motivo (OBJ-002): la suite ``--level all`` puede quedar VERDE con un modulo
productivo de ``scripts/`` unimporable si ningun test lo importa. Caso medido:
``scripts/builder_agent.py`` importaba ``publish_state_changed_event`` (simbolo
eliminado de ``agent_controller``), quedando unimporable desde el commit
baseline; ningun test lo ejercitaba, asi que la rotura de PRODUCCION viajaba
oculta bajo una suite verde.

Este modulo cierra ese hueco de COBERTURA (no del runner): importa CADA modulo
``.py`` bajo ``scripts/`` -- recursivo, incluidos ``closeout_steps/`` y
``tools/`` -- y FALLA nombrando el modulo concreto que no importa.

No toca ``scripts/run_pytest_safe.py`` (superficie prohibida por el contrato).

Pin adicional (DoD-4): ``STATE_CHANGED`` debe poder emitirse por la API canonica
actual (``EventBus.emit``). El test reproduce la emision REAL sobre un bus en
``tmp_path`` y la re-lee de DISCO, en vez de aseverar una equivalencia de
helper.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _discover_script_modules() -> list[str]:
    """Return the dotted path of every importable ``.py`` module under scripts/.

    Before: requires ``SCRIPTS_DIR`` to exist.
    During: walks ``scripts/**/*.py`` (skipping ``__pycache__``), converting each
        file to its dotted module path relative to ``REPO_ROOT``; a trailing
        ``__init__`` collapses to the package name.
    After: returns a sorted, de-duplicated list of dotted module names.
    """
    modules: set[str] = set()
    if not SCRIPTS_DIR.is_dir():
        return []
    for path in sorted(SCRIPTS_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(REPO_ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        modules.add(".".join(parts))
    return sorted(modules)


_SCRIPT_MODULES = _discover_script_modules()


def test_scripts_modules_are_discovered() -> None:
    """Guard: the discovery itself must find modules (a silent empty list would
    make the parametrized smoke vacuously green)."""
    assert _SCRIPT_MODULES, "no modules discovered under scripts/ -- discovery broke"
    assert "scripts.builder_agent" in _SCRIPT_MODULES, (
        "scripts.builder_agent must be part of the smoke surface"
    )


@pytest.mark.parametrize("module_name", _SCRIPT_MODULES)
def test_scripts_module_imports(module_name: str) -> None:
    """Every module under ``scripts/`` must be importable.

    FALLA nombrando el modulo si alguno no importa (DoD-1). La mutacion de
    referencia es romper un ``import``/simbolo en un modulo cualquiera: su
    parametro correspondiente pasa a ROJO y lo nombra en el mensaje.
    """
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        pytest.fail(
            f"script module {module_name!r} is not importable: "
            f"{type(exc).__name__}: {exc}"
        )


def test_state_changed_emission_via_canonical_api(tmp_path: Path) -> None:
    """DoD-4: pin ``STATE_CHANGED`` emission through the canonical API.

    Reproduce la emision REAL (``EventBus.emit``, la misma que ``builder_agent``
    usa tras la reparacion de WOT-2026-058v) sobre un bus en ``tmp_path`` y la
    re-lee del fichero ``events.jsonl`` en DISCO -- no asevera equivalencia de un
    helper eliminado, ejercita la emision y verifica la persistencia observable.
    """
    from bus.event_bus import EventBus

    runtime_dir = tmp_path / "runtime"
    bus = EventBus(runtime_dir)

    ticket_id = "WOT-2026-066b"
    record = bus.emit(
        event_type="STATE_CHANGED",
        ticket_id=ticket_id,
        actor="BUILDER",
        payload={
            "from_state": "IN_PROGRESS",
            "to_state": "READY_FOR_REVIEW",
            "reason": "Builder completed implementation",
            "source": "builder_agent",
        },
    )
    assert record is not None, "canonical emit returned None (blocked unexpectedly)"

    events_path = runtime_dir / "events.jsonl"
    raw_lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 1, "exactly one STATE_CHANGED must be persisted"
    persisted = json.loads(raw_lines[0])
    assert persisted["event_type"] == "STATE_CHANGED"
    assert persisted["ticket_id"] == ticket_id
    assert persisted["actor"] == "BUILDER"
    assert persisted["payload"]["from_state"] == "IN_PROGRESS"
    assert persisted["payload"]["to_state"] == "READY_FOR_REVIEW"

    consumed = bus.read_events(ticket_id=ticket_id, event_type="STATE_CHANGED")
    assert len(consumed) == 1, "the persisted emission must be consumable by readers"
    assert consumed[0].payload["to_state"] == "READY_FOR_REVIEW"
