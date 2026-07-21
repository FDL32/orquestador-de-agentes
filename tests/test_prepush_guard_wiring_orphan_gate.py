"""Barrera: WOT-2026-026v -- la deuda huerfana se comprueba donde HAY destino.

`check_guard_wiring` corre en pre-commit, pero alli no hay repo_destino que
consultar: el hook corre sobre el motor y cablearle una ruta de esta maquina lo
haria no-portable (justo lo que prohibe check_distribution_agnostic). Sin destino
la deteccion SKIPEA, y un SKIP permanente convierte la capacidad en una NORMA que
depende de que alguien recuerde pasar la flag -- no en una barrera.

El cierre SI conoce el destino, asi que es la superficie que corre sola donde la
comprobacion puede ser REAL. Estos tests son la barrera de esa barrera: con un
owner archivado el check REPORTA; con el owner vivo NO; y sin destino resoluble
SKIPEA explicitamente en vez de inventar huerfanos o reventar.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.prepush_check import run_guard_wiring_orphan_check


LIVE_HEADER = (
    "# Backlog (cola viva)\n\n## Vista rapida\n\n"
    "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def _write_backlog(root: Path, rows: str) -> None:
    p = root / ".agent" / "collaboration" / "backlog.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(LIVE_HEADER + rows, encoding="utf-8")


def _owners_of_declared_debt() -> list[str]:
    """Los owners-ticket de la deuda declarada REAL del motor (no un fixture).

    El test se ata al INVARIANTE, no a un conteo (WOT-2026-024t): sea cual sea la
    deuda declarada hoy, con su owner VIVO no puede haber huerfanos, y con el owner
    archivado si.
    """
    from scripts.check_guard_wiring import _TICKET, _load_policy

    known = _load_policy()["known_unwired"]
    return sorted({str(o) for o in known.values() if _TICKET.match(str(o))})


def test_orphan_debt_is_reported_when_owner_is_archived(tmp_path: Path):
    """Backlog vivo SIN los owners -> estan archivados -> se reportan como huerfanos."""
    _write_backlog(
        tmp_path, "| Alta | WOT-2026-999z | otra cosa | s | pending | - | t | - |\n"
    )
    result = run_guard_wiring_orphan_check(tmp_path)
    assert not result.passed, result.output
    assert "owner is archived" in result.output
    # WARN, no bloqueante: la deuda huerfana de hoy es historica
    assert result.is_blocking is False


def test_no_orphan_when_every_owner_is_live(tmp_path: Path):
    """Con TODOS los owners en la cola viva no hay huerfanos: la deuda esta acotada.

    Es la mitad que impide un guard que siempre grita (un check que no puede salir
    verde no informa de nada).
    """
    rows = "".join(
        f"| Alta | {owner} | vivo | s | pending | - | t | - |\n"
        for owner in _owners_of_declared_debt()
    )
    _write_backlog(tmp_path, rows)
    result = run_guard_wiring_orphan_check(tmp_path)
    assert result.passed, result.output
    assert "no orphan debt" in result.output


def test_skips_explicitly_without_a_resolvable_destino(tmp_path: Path):
    """Destino sin backlog -> SKIP IMPRESO, passed=True. Nunca crash ni verde mudo.

    Un guard del motor que reviente en un destino recien instalado seria peor que
    la deuda que cierra; y un backlog ausente NO significa "todos archivados".
    """
    result = run_guard_wiring_orphan_check(tmp_path / "no_existe")
    assert result.passed
    assert result.output.startswith("SKIP:")


def test_non_utf8_backlog_skips_instead_of_inventing_orphans(tmp_path: Path):
    """Backlog no-UTF8 -> SKIP nombrado, NO un informe de huerfanos falso.

    Hallazgo del auditor adversarial con FS. Con `errors="replace"` la lectura no
    lanzaba: devolvia mojibake, no se encontraba NINGUN ticket, y ese conjunto
    vacio era indistinguible de "todos archivados". Medido entonces: 6 huerfanos
    falsos -- incluido un owner LITERALMENTE presente y vivo en el fichero. La
    lectura estricta es lo que hace ALCANZABLE el SKIP que el contrato promete.
    """
    p = tmp_path / ".agent" / "collaboration" / "backlog.md"
    p.parent.mkdir(parents=True)
    fila = "| Alta | WOT-2026-023t | VIVO en la cola | s | pending | - | t | - |\n"
    p.write_bytes(fila.encode("utf-16"))

    result = run_guard_wiring_orphan_check(tmp_path)
    assert result.passed, result.output
    assert "not valid UTF-8" in result.output
    assert "023t" not in result.output, "un owner vivo jamas puede salir como huerfano"


def test_backlog_without_any_ticket_skips(tmp_path: Path):
    """Una cola viva sin UN SOLO ticket no sostiene "todos archivados".

    Es mucho mas probable un backlog truncado o a medio escribir. Fail-safe hacia
    el SKIP nombrado antes que acusar de huerfana a toda la deuda declarada.
    """
    p = tmp_path / ".agent" / "collaboration" / "backlog.md"
    p.parent.mkdir(parents=True)
    p.write_text(LIVE_HEADER, encoding="utf-8")

    result = run_guard_wiring_orphan_check(tmp_path)
    assert result.passed, result.output
    assert "names no ticket at all" in result.output


@pytest.mark.parametrize("owner_kind", ["by-design", "ticket-vivo"])
def test_by_design_and_live_owners_never_count_as_orphans(owner_kind: str):
    """BY-DESIGN no tiene dueno que archivar; un ticket vivo esta acotado."""
    from scripts.check_guard_wiring import _orphan_owners

    owner = "BY-DESIGN: razon" if owner_kind == "by-design" else "WOT-2026-019o"
    known = {"check_x": owner}
    assert _orphan_owners(known, ["check_x"], {"WOT-2026-019o"}) == []
