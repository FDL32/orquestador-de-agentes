"""Tests del helper de siguiente id libre (WOT-2026-040f).

Los tests usan worktrees reales en ``tmp_path`` con cola viva + archive, y
fuerzan transiciones reales: la politica de sucesor del maximo global, el
cruce de AMBAS superficies y la mutation (id cerrado solo en el archive no se
propone).
"""

from __future__ import annotations

from pathlib import Path

from bus.ticket_id import (
    TICKET_ID_RE,
    collect_surface_ticket_ids,
    next_free_ticket_id,
)


def _collab(tmp_path: Path, live: str = "", archive: str = "") -> Path:
    """Monta un directorio .agent/collaboration con backlog.md y el archive."""
    collab = tmp_path / "collaboration"
    collab.mkdir(parents=True)
    archive_dir = collab / "_archive"
    archive_dir.mkdir()
    (collab / "backlog.md").write_text(live, encoding="utf-8")
    (collab / "_archive" / "backlog_done.md").write_text(archive, encoding="utf-8")
    return collab


def test_next_free_base_case_no_ids(tmp_path):
    """Sin ids del prefijo/ano en NINGUNA superficie -> <PREFIX>-<YEAR>-001a."""
    collab = _collab(tmp_path, live="| Ticket |\n|---|---|\n", archive="")
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-001a"


def test_next_free_advances_letter_after_max(tmp_path):
    """El maximo global (400, x) en la COLA VIVA -> siguiente letra 400y."""
    collab = _collab(
        tmp_path,
        live=(
            "| Prioridad | Ticket |\n|---|---|\n"
            "| Media | WOT-2026-400w | ficha live |\n"
            "| Media | WOT-2026-400x | ficha live |\n"
        ),
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-400y"


def test_next_free_skips_archived_id_mutation(tmp_path):
    """MUTATION (DoD c): un id CERRADO solo en el archive NO se propone.

    El fallo que este helper previene (WOT-2026-027t): con `400x` solo en
    `_archive/backlog_done.md` (ausente en la cola viva), un calculo que mirara
    UNA sola superficie lo propondria. El helper barre AMBAS y devuelve el
    sucesor del maximo global, no el id ocupado.
    """
    collab = _collab(
        tmp_path,
        live="| Ticket |\n|---|---|\n| WOT-2026-400w | pendiente |\n",
        archive=(
            "| Ticket | Estado | Nota |\n|---|---|---|\n"
            "| WOT-2026-400x | completed | cerrado |\n"
        ),
    )
    result = next_free_ticket_id("WOT", 2026, collab)
    assert result != "WOT-2026-400x", (
        "el id cerrado en el archive se esta proponiendo: la asignacion barre "
        f"una sola superficie; resultado real: {result}"
    )
    assert result == "WOT-2026-400y"


def test_next_free_successor_wins_over_lower_live_gap(tmp_path):
    """La politica es sucesor del maximo global, NO rellenar huecos.

    Con `400a` y `400n` en la cola viva, el maximo global por (numero, letra) es
    `400n` y hay huecos (`400b`..`400m`). El siguiente es `400o`, NO `400b`: la
    politica declarada no rellena huecos historicos sino que avanza desde el
    maximo.
    """
    collab = _collab(
        tmp_path,
        live=(
            "| Ticket |\n|---|---|\n"
            "| WOT-2026-400a | inicial |\n"
            "| WOT-2026-400n | maximo |\n"
        ),
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-400o"


def test_next_free_letter_z_advances_number(tmp_path):
    """`400z` -> el siguiente numero `401a` (no se sale del alfabeto)."""
    collab = _collab(
        tmp_path,
        live="| Ticket |\n|---|---|\n| WOT-2026-400z | maximo |\n",
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-401a"


def test_next_free_pure_numeric_legacy_advances_number(tmp_path):
    """Un id legacy `400` sin letra -> siguiente numero `401a` (WT-2026-251a)."""
    collab = _collab(
        tmp_path,
        live="| Ticket |\n|---|---|\n| WOT-2026-400 | legacy sin letra |\n",
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-401a"


def test_next_free_filters_by_prefix_and_year(tmp_path):
    """Un id de OTRO prefijo o ano no cuenta para el maximo global."""
    collab = _collab(
        tmp_path,
        live=(
            "| Ticket |\n|---|---|\n"
            "| CTL-2026-900z | otro prefijo |\n"
            "| WOT-2025-100z | otro ano |\n"
        ),
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-001a"


def test_collect_surface_ticket_ids_crosses_both_surfaces(tmp_path):
    """El enumerador compartido lee AMBAS superficies en una sola llamada."""
    collab = _collab(
        tmp_path,
        live="| Ticket |\n|---|---|\n| WOT-2026-400a | viva |\n",
        archive=("| Ticket |\n|---|---|\n| WOT-2026-401z | archivada |\n"),
    )
    ids = collect_surface_ticket_ids(collab)
    assert ids == {"WOT-2026-400a", "WOT-2026-401z"}


def test_next_free_skips_archived_id_if_only_archive_has_higher(tmp_path):
    """Caso espejo del 027t: el id cerrado es el MAXIMO absoluto del archive."""
    collab = _collab(
        tmp_path,
        live="| Ticket |\n|---|---|\n| WOT-2026-400w | pendiente |\n",
        archive=("| Ticket | Estado |\n|---|---|\n| WOT-2026-401a | completed |\n"),
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-401b"


def test_find_similar_uses_canonical_pattern_not_private(tmp_path, monkeypatch):
    """DoD (b): el etiquetado delega en el patron CANONICO del bus."""
    import scripts.find_similar_signals as fss

    assert not hasattr(fss, "_TICKET_RE"), (
        "el patron privado debe desaparecer: el repositorio del patron vive en "
        "bus/ticket_id.py (una sola implementacion)"
    )
    assert fss.TICKET_ID_RE is TICKET_ID_RE, (
        "debe importar el MISMO objeto del bus, no una copia"
    )
