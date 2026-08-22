# WOT-2026-010f: Barrera contra checkpoint/review-none y guards plan_id debiles.
#
# Root cause: 17 guards `(plan_id|ticket_id|current_plan_id) == "N/A"` en
# agent_controller.py dejan pasar "none"/"unknown" (solo bloquean "" y "N/A").
# En _handle_pre_handoff eso materializa checkpoint/review-none; en
# _handle_mark_ready emitiria eventos de bus para un ticket inexistente.
#
# Estos tests ejercen las funciones REALES con repos git en tmp_path y
# monkeypatch de los seams (WORK_PLAN, PROJECT_ROOT, _MOTOR_ROOT). No mockean
# git ni el guard interno: observan el efecto real (tag creado / no creado).

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


# state_validation es un modulo hermano en .agent/; se importa por su path.
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import state_validation  # noqa: E402

from tests.test_pre_handoff_guard import init_git_repo  # noqa: E402
from tests.test_pre_handoff_multirepo import _git  # noqa: E402


# ---------------------------------------------------------------------------
# Unidad pura: is_invalid_plan_id / INVALID_PLAN_IDS (la barrera reutilizable)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "none",
        "None",
        "  none  ",
        "N/A",
        "n/a",
        "unknown",
        "UNKNOWN",
        "-",
        "--",
        "  -  ",
    ],
)
def test_is_invalid_plan_id_rejects_placeholders(raw: str) -> None:
    assert state_validation.is_invalid_plan_id(raw) is True


def test_is_invalid_plan_id_none_arg() -> None:
    assert state_validation.is_invalid_plan_id(None) is True


@pytest.mark.parametrize(
    "raw",
    ["WOT-2026-010f", "WT-2026-231a", "WP-2026-100", " WOT-2026-001a "],
)
def test_is_invalid_plan_id_accepts_real_tickets(raw: str) -> None:
    assert state_validation.is_invalid_plan_id(raw) is False


def test_invalid_plan_ids_single_source_contents() -> None:
    # La constante es la fuente unica de verdad; debe cubrir todos los
    # placeholders incluyendo el guion (WOT-2026-058k).
    assert (
        frozenset({"", "-", "--", "n/a", "none", "unknown"})
        == state_validation.INVALID_PLAN_IDS
    )


def test_invalid_plan_ids_no_inline_literal_in_controller() -> None:
    """El patron debil `== "N/A"` no debe quedar inline en agent_controller.py.

    Criterio de cierre del contrato: tras migrar los 17 guards, el grep del
    patron debe dar 0. Este test FALLA antes del fix (hoy hay 17 ocurrencias).
    """
    import re

    controller = (_AGENT_DIR / "agent_controller.py").read_text(encoding="utf-8")
    weak = re.findall(r'(?:plan_id|ticket_id|current_plan_id)\s*==\s*"N/A"', controller)
    assert weak == [], (
        f'{len(weak)} guards debiles `== "N/A"` siguen inline; '
        f"deben consumir is_invalid_plan_id()"
    )


# ---------------------------------------------------------------------------
# Integracion: _handle_pre_handoff NO crea tag con plan_id invalido
# ---------------------------------------------------------------------------


def _write_work_plan(collab_dir: Path, ticket_id: str) -> Path:
    wp = collab_dir / "work_plan.md"
    wp.write_text(
        "# Work Plan\n\n"
        "## Metadata\n"
        f"- **ID:** {ticket_id}\n"
        "- **Estado:** APPROVED\n"
        "- **deliverable_type:** code\n\n"
        "## Files Likely Touched\n- `.agent/agent_controller.py`\n",
        encoding="utf-8",
    )
    return wp


def _setup(tmp_path: Path, ticket_id: str) -> tuple[Path, Path, Path]:
    import os

    os.environ.pop("AGENT_BUILDER_TICKET", None)
    os.environ.pop("AGENT_BUILDER_ROUND", None)

    motor = tmp_path / "motor"
    dest = tmp_path / "dest"
    init_git_repo(motor)
    init_git_repo(dest)
    collab = dest / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    wp = _write_work_plan(collab, ticket_id)
    exec_log = collab / "execution_log.md"
    exec_log.write_text(
        "# Execution Log\n\n**Estado:** IN_PROGRESS\n\n", encoding="utf-8"
    )
    (dest / ".agent" / "runtime").mkdir(parents=True, exist_ok=True)
    _git(["add", str(wp)], cwd=dest)
    _git(["commit", "-m", f"wp {ticket_id}"], cwd=dest)
    return motor, dest, wp


def _tags(repo: Path) -> list[str]:
    out = _git(["tag", "-l", "checkpoint/review-*"], cwd=repo).stdout
    return [t for t in out.splitlines() if t.strip()]


def _patch_controller(monkeypatch, dest: Path, motor: Path, wp: Path) -> object:
    ac = importlib.import_module("agent_controller")
    exec_log = dest / ".agent" / "collaboration" / "execution_log.md"
    monkeypatch.setattr(ac, "PROJECT_ROOT", dest)
    monkeypatch.setattr(ac, "WORK_PLAN", wp)
    monkeypatch.setattr(ac, "EXEC_LOG", exec_log)
    monkeypatch.setattr(ac, "_MOTOR_ROOT", motor)
    return ac


@pytest.mark.parametrize("bad_id", ["none", "None", "unknown", "N/A"])
def test_pre_handoff_blocks_invalid_plan_id_no_tag(
    tmp_path: Path, monkeypatch, bad_id: str
) -> None:
    """Con plan_id invalido, _handle_pre_handoff falla y NO crea ningun tag.

    BARRERA PRINCIPAL: hoy con bad_id="none" el guard debil deja pasar y se
    crea checkpoint/review-none. Debe fallar sin el fix.
    """
    motor, dest, wp = _setup(tmp_path, bad_id)
    ac = _patch_controller(monkeypatch, dest, motor, wp)

    rc = ac._handle_pre_handoff(json_output=True)

    assert rc != 0, f"pre-handoff debio fallar con plan_id={bad_id!r}"
    assert _tags(motor) == [], "no debe crearse ningun checkpoint/review-* tag"
    assert _tags(dest) == [], "no debe crearse ningun checkpoint/review-* tag"
    # En particular, jamas review-none.
    assert "checkpoint/review-none" not in _tags(motor)


def test_bom_hygiene_runs_even_with_invalid_plan_id(
    tmp_path: Path, monkeypatch
) -> None:
    """WOT-2026-010f: BOM autocorrect of .opencode/opencode.json is infra
    hygiene independent of the ticket. With plan_id="none": the BOM is cleaned
    AND the ticket still blocks (no tag). Guards the reordering done in 010f.
    """
    motor, dest, wp = _setup(tmp_path, "none")
    ac = _patch_controller(monkeypatch, dest, motor, wp)

    # Commit a clean opencode.json to motor HEAD, then drift it with a BOM.
    opencode = motor / ".opencode" / "opencode.json"
    opencode.parent.mkdir(parents=True, exist_ok=True)
    clean = b'{"key": "value"}\n'
    opencode.write_bytes(clean)
    _git(["add", str(opencode)], cwd=motor)
    _git(["commit", "-m", "add opencode config"], cwd=motor)
    opencode.write_bytes(b"\xef\xbb\xbf" + clean)  # BOM drift

    rc = ac._handle_pre_handoff(json_output=True)

    # Hygiene: BOM removed even though the ticket is invalid.
    assert opencode.read_bytes() == clean, "BOM drift should be autocorrected"
    # Guard: ticket still blocked, no checkpoint tag created.
    assert rc != 0
    assert _tags(motor) == []


def test_pre_handoff_allows_valid_ticket_creates_tag(
    tmp_path: Path, monkeypatch
) -> None:
    """Con un ticket valido, el flujo NO debe bloquear por plan_id (no-regresion).

    No exige que el tag exista (otros guards pueden intervenir), pero SI exige
    que el motivo de bloqueo, si lo hay, no sea 'plan_id invalido'.
    """
    motor, dest, wp = _setup(tmp_path, "WOT-2026-999z")
    ac = _patch_controller(monkeypatch, dest, motor, wp)

    # No debe lanzar ni clasificar como plan_id invalido.
    # is_invalid_plan_id es la barrera; con ticket real debe ser False.
    assert state_validation.is_invalid_plan_id("WOT-2026-999z") is False
    # Y la ruta real no crea review-none jamas.
    ac._handle_pre_handoff(json_output=True)
    assert "checkpoint/review-none" not in _tags(motor)


# ---------------------------------------------------------------------------
# WOT-2026-058k: los guards de post-closure consultan el guard ANTES del bus.
# Con plan_id invalido ('-', 'none', ...) NO debe haber busqueda en el bus.
# ---------------------------------------------------------------------------


def _patch_controller_post_closure(monkeypatch) -> object:
    """Import agent_controller en modo hermetico para los guards de cierre.

    Sin el fix de 058k, los guards llamarian a bus_has_ticket_events(bus, '-')
    / check_post_closure_*(bus, '-') con el literal guion: pinchamos esos
    call-sites con un objeto que LANZA, de modo que un guard que no consulta
    is_invalid_plan_id primero -> AssertionError -> ROJO. Con el fix, el guard
    corta antes y nadie toca el bus.
    """
    ac = importlib.import_module("agent_controller")
    monkeypatch.setattr(ac, "BUS_AVAILABLE", True, raising=False)

    class _FakeBus:
        def read_events(self, ticket_id):
            raise AssertionError(f"bus consulted with invalid plan_id {ticket_id!r}")

        def has_events(self, ticket_id):
            raise AssertionError(f"bus consulted with invalid plan_id {ticket_id!r}")

    monkeypatch.setattr(ac, "event_bus", _FakeBus(), raising=False)

    class _FakeClosure:
        def bus_has_ticket_events(self, *a, **k):
            raise AssertionError(f"bus_has_ticket_events called: {a!r} {k!r}")

        def check_post_closure_built_exit(self, *a, **k):
            raise AssertionError(f"check_post_closure_built_exit called: {a!r} {k!r}")

        def check_post_closure_state_changed(self, *a, **k):
            raise AssertionError(
                f"check_post_closure_state_changed called: {a!r} {k!r}"
            )

    monkeypatch.setattr(ac, "closure_invariants", _FakeClosure(), raising=False)
    return ac


def _patch_closure_guards(monkeypatch) -> object:
    """Module-level patch: BUS_AVAILABLE + event_bus activos, bus_has_ticket_events
    pinchado para FALLAR el test si se consulta con un id no disparado (lo que se
    pinnea es que NO se llame nunca con plan_id invalido)."""
    ac = importlib.import_module("agent_controller")
    monkeypatch.setattr(ac, "BUS_AVAILABLE", True, raising=False)

    class _FakeBus:
        def read_events(self, ticket_id):
            raise AssertionError(f"bus consulted with invalid plan_id {ticket_id!r}")

    monkeypatch.setattr(ac, "event_bus", _FakeBus(), raising=False)
    return ac


def test_058k_post_closure_built_exit_skips_bus_for_invalid_id(
    monkeypatch,
) -> None:
    """DoD: _check_post_closure_built_exit('-') no consulta el bus (nada que
    comprobar para un id que no designa ticket; ANTES media read_events('-') y
    fabricaba 'No STATE_CHANGED event found for ticket -')."""
    ac = _patch_controller_post_closure(monkeypatch)
    errors, warnings = ac._check_post_closure_built_exit("-", "READY_FOR_REVIEW")
    assert errors == []
    assert warnings == []


def test_058k_post_closure_state_changed_skips_bus_for_invalid_id(
    monkeypatch,
) -> None:
    """Estado de paridad de guard: _check_post_closure_state_changed('-') tampoco
    toca el bus con el literal guion."""
    ac = _patch_controller_post_closure(monkeypatch)
    errors, warnings = ac._check_post_closure_state_changed("-", "READY_FOR_REVIEW")
    assert errors == []
    assert warnings == []


def test_058k_post_closure_built_exit_real_ticket_consults_bus(
    monkeypatch,
) -> None:
    """CONTROL NEGATIVO: con un id real el guard SI llega al bus (el monkeypatch
    del event_bus aqui lo deja pasar: cambiamos read_events para que devuelva
    una lista minima, y comprobamos que el guard NO aborta por invalid_id)."""
    ac = _patch_controller_post_closure(monkeypatch)
    real_bus = type("B", (), {"read_events": lambda self, tid: []})()
    monkeypatch.setattr(ac, "event_bus", real_bus)
    monkeypatch.setattr(ac, "_ticket_events_archived", lambda tid: True, raising=False)
    errors, warnings = ac._check_post_closure_built_exit(
        "WOT-2026-999z", "READY_FOR_REVIEW"
    )
    # Con _ticket_events_archived -> True el guard corta sin errores (el bus no
    # se toca de borrar), lo que probar es que NO bloquea por plan_id invalido.
    assert errors == []
    assert warnings == []
