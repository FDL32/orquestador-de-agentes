"""Tests for scripts/check_flight_plan_collision.py (WOT-2026-027h).

CONTRATO: dado el DIRECTORIO queued/ de planes de vuelo, el check FALLA
(exit!=0) si (i) un ticket.id aparece en >=2 planes, o (ii) dos planes declaran
la misma shared_surface (normalizada). validate_batch_dag es CIEGO al conjunto
(un dag_path posicional, un veredicto); este es el CHECK HERMANO que mira el
conjunto de queued/.

Rojo de mutacion (DoD):
  T-TICKET-COLLIDE : 2 planes que comparten un ticket.id -> exit 1, mensaje
                     nombra el ticket y ambos planes. Separarlos -> exit 0.
  T-SURFACE-COLLIDE: 2 planes con la misma shared_surface (normalizada, distinto
                     case/separador) -> exit 1. Separarlas -> exit 0.
  T-NO-ALLOWLIST   : una colision "declarada/coordinada" NO se amnistia: sigue
                     fallando. El check DETECTA, no coordina (defecto cazado por
                     Codex: un allowlist convertiria el check en coordinador y
                     esconderia el fallo).
  T-ROBUST-IDS     : extraccion robusta de ids -- placeholders de grupo (G-000),
                     tickets top-level como dicts {'id':...}, y tickets=None no
                     rompen ni generan falsos ids.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_flight_plan_collision.py"
_SPEC = importlib.util.spec_from_file_location("check_flight_plan_collision", _SCRIPT)
cfpc = importlib.util.module_from_spec(_SPEC)
# Register before exec: the module defines a @dataclass with a forward-ref
# annotation, and dataclasses resolves it via sys.modules[cls.__module__].
sys.modules["check_flight_plan_collision"] = cfpc
_SPEC.loader.exec_module(cfpc)


# --------------------------------------------------------------------- helpers
def _write_link(destino_root: Path, prefix: str = "WOT") -> Path:
    """Instala el motor_destination_link.json del destino (WOT-2026-068k).

    El gate resuelve su patron de ids desde el ticket_prefix declarado en ese
    link; sin él falla explicito. Los fixtures lo instalan como lo haria el
    instalador en un destino real."""
    cfg = destino_root / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    link = cfg / "motor_destination_link.json"
    link.write_text(json.dumps({"ticket_prefix": prefix}), encoding="utf-8")
    return link


def _queued(tmp_path: Path, *, prefix: str | None = "WOT") -> Path:
    d = tmp_path / "queued"
    d.mkdir(parents=True, exist_ok=True)
    if prefix is not None:
        _write_link(tmp_path, prefix)
    return d


def _plan(
    queued: Path,
    name: str,
    *,
    tickets: list | None = None,
    surfaces: list | None = None,
    top_tickets: object = "__unset__",
) -> Path:
    """Write a minimal plan JSON. tickets/surfaces go into a single group;
    top_tickets sets the polymorphic top-level `tickets` key when provided."""
    group: dict = {"id": f"G-{name}"}
    if tickets is not None:
        group["tickets"] = tickets
    if surfaces is not None:
        group["shared_surfaces"] = surfaces
    data: dict = {"groups": [group]}
    if top_tickets != "__unset__":
        data["tickets"] = top_tickets
    path = queued / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _run_cli(queued: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--queued-dir", str(queued)],
        capture_output=True,
        text=True,
    )


# ------------------------------------------------------------- T-TICKET-COLLIDE
def test_shared_ticket_across_two_plans_fails(tmp_path):
    q = _queued(tmp_path)
    _plan(q, "planA", tickets=["WOT-2026-999a"], surfaces=["scripts/a.py"])
    _plan(q, "planB", tickets=["WOT-2026-999a"], surfaces=["scripts/b.py"])

    collisions = cfpc.find_collisions(q)
    assert collisions, "un ticket en 2 planes debe producir una colision"

    proc = _run_cli(q)
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "WOT-2026-999a" in out
    assert "planA.json" in out
    assert "planB.json" in out


def test_disjoint_tickets_pass(tmp_path):
    q = _queued(tmp_path)
    _plan(q, "planA", tickets=["WOT-2026-999a"], surfaces=["scripts/a.py"])
    _plan(q, "planB", tickets=["WOT-2026-999b"], surfaces=["scripts/b.py"])

    assert cfpc.find_collisions(q) == []
    assert _run_cli(q).returncode == 0


# ------------------------------------------------------------ T-SURFACE-COLLIDE
def test_shared_surface_normalized_fails(tmp_path):
    q = _queued(tmp_path)
    # Distinto case y separador: en Windows es EL MISMO fichero. _normalize_surface
    # (reutilizado de validate_batch_dag) debe cazarlo.
    _plan(q, "planA", tickets=["WOT-2026-999a"], surfaces=["scripts/Shared.py"])
    _plan(q, "planB", tickets=["WOT-2026-999b"], surfaces=["scripts\\shared.py"])

    collisions = cfpc.find_collisions(q)
    assert collisions, "misma shared_surface normalizada debe colisionar"

    proc = _run_cli(q)
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "planA.json" in out and "planB.json" in out


def test_disjoint_surfaces_pass(tmp_path):
    q = _queued(tmp_path)
    _plan(q, "planA", tickets=["WOT-2026-999a"], surfaces=["scripts/a.py"])
    _plan(q, "planB", tickets=["WOT-2026-999b"], surfaces=["scripts/b.py"])
    assert cfpc.find_collisions(q) == []
    assert _run_cli(q).returncode == 0


# --------------------------------------------------------------- T-NO-ALLOWLIST
def test_coordinated_collision_is_not_amnestied(tmp_path):
    """Una colision 'coordinada/declarada' SIGUE fallando: no hay allowlist.
    El check DETECTA, no coordina (defecto cazado por Codex 2026-07-24)."""
    q = _queued(tmp_path)
    _plan(q, "planA", tickets=["WOT-2026-027h"], surfaces=["scripts/prepush_check.py"])
    _plan(q, "planB", tickets=["WOT-2026-025i"], surfaces=["scripts/prepush_check.py"])
    assert cfpc.find_collisions(q), "colision coordinada tambien debe fallar"
    assert _run_cli(q).returncode != 0


# ---------------------------------------------------------------- T-ROBUST-IDS
def test_group_placeholders_and_polymorphic_top_tickets(tmp_path):
    """G-000 (placeholder de grupo) no es un ticket; tickets top-level como
    lista de dicts {'id':...} se extraen; tickets=None no rompe."""
    q = _queued(tmp_path)
    _plan(q, "planA", tickets=["G-000", "WOT-2026-111a"], surfaces=["scripts/a.py"])
    p = q / "planB.json"
    p.write_text(
        json.dumps(
            {
                "tickets": [{"id": "WOT-2026-222b"}],
                "groups": [{"id": "G-planB", "shared_surfaces": ["scripts/b.py"]}],
            }
        ),
        encoding="utf-8",
    )
    (q / "planC.json").write_text(
        json.dumps({"tickets": None, "groups": [{"id": "G-planC"}]}),
        encoding="utf-8",
    )

    assert cfpc.find_collisions(q) == []
    assert _run_cli(q).returncode == 0

    index = cfpc.build_ticket_index(q)
    assert "G-000" not in index
    assert "WOT-2026-111a" in index


def test_empty_queued_dir_passes(tmp_path):
    q = _queued(tmp_path)
    assert cfpc.find_collisions(q) == []
    assert _run_cli(q).returncode == 0


def test_reuses_validate_batch_dag_normalize_surface():
    """Contrato de reuso: NO reescribir la normalizacion -- importarla."""
    from validate_batch_dag import _normalize_surface as vbd_norm

    assert cfpc._normalize_surface is vbd_norm


# ------------------------------------------- WOT-2026-068k: prefijo por-destino
def test_prefijo_no_canonico_rds_es_detectado(tmp_path):
    """ROJO previo del defecto: con el patron cableado WOT|WP|WT|CTL la colision
    de un destino RDS era INVISIBLE (find_collisions == [] -- el gate ni ve la
    fila). Con el fix, el patron se construye desde el link y la colision sale."""
    q = _queued(tmp_path, prefix="RDS")
    _plan(q, "planA", tickets=["RDS-2026-001a"], surfaces=["scripts/a.py"])
    _plan(q, "planB", tickets=["RDS-2026-001a"], surfaces=["scripts/b.py"])

    collisions = cfpc.find_collisions(q)
    assert collisions, "una colision RDS debe detectarse con prefijo RDS declarado"
    assert any(c.key == "RDS-2026-001a" for c in collisions)

    proc = _run_cli(q)
    assert proc.returncode != 0
    assert "RDS-2026-001a" in proc.stdout + proc.stderr


def test_prefijo_legacy_wot_sigue_visible_en_destino_rds(tmp_path):
    """Compatibilidad legacy: la triada WOT|WP|WT se incluye SIEMPRE ademas del
    prefijo declarado (contrato frozen 061a, opcion A)."""
    q = _queued(tmp_path, prefix="RDS")
    _plan(q, "planA", tickets=["WOT-2026-999a"], surfaces=["scripts/a.py"])
    _plan(q, "planB", tickets=["WOT-2026-999a"], surfaces=["scripts/b.py"])

    collisions = cfpc.find_collisions(q)
    assert any(c.key == "WOT-2026-999a" for c in collisions)


def test_link_sin_ticket_prefix_falla_explicito(tmp_path, monkeypatch):
    """CONTROL NEGATIVO fail-closed (WOT-2026-068k DoD): un link SIN
    ticket_prefix (o ausente) produce un veredicto EXPLICITO -- kind "prefix"
    con el motivo -- nunca un verde silencioso ni un default WOT."""
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    q = _queued(tmp_path, prefix=None)  # sin link
    _plan(q, "planA", tickets=["WOT-2026-999a"], surfaces=["scripts/a.py"])
    _plan(q, "planB", tickets=["WOT-2026-999b"], surfaces=["scripts/b.py"])

    collisions = cfpc.find_collisions(q)
    assert len(collisions) == 1
    assert collisions[0].kind == "prefix"
    assert "ticket_prefix" in collisions[0].render()

    proc = _run_cli(q)
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "ticket_prefix" in out

    proc_json = subprocess.run(
        [sys.executable, str(_SCRIPT), "--queued-dir", str(q), "--json"],
        capture_output=True,
        text=True,
    )
    assert proc_json.returncode != 0
    payload = json.loads(proc_json.stdout)
    assert payload["ok"] is False
    assert any(c["kind"] == "prefix" for c in payload["collisions"])


def test_link_vacio_ticket_prefix_tambien_falla_explicito(tmp_path, monkeypatch):
    """El caso literal del DoD: el link EXISTE pero su ticket_prefix esta vacio."""
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "motor_destination_link.json").write_text(
        json.dumps({"ticket_prefix": ""}), encoding="utf-8"
    )
    q = _queued(tmp_path, prefix=None)
    _plan(q, "planA", tickets=["WOT-2026-999a"], surfaces=["scripts/a.py"])

    collisions = cfpc.find_collisions(q)
    assert len(collisions) == 1
    assert collisions[0].kind == "prefix"
    assert "no declara ticket_prefix" in collisions[0].render()
