"""Barrera: WOT-2026-043t -- evidencia de aterrizaje que el censo NO puede leer.

Antecedente medido (2026-08-03, archivando WOT-2026-040u): el SHA se escribio en
la celda de ESTADO en vez de en la suya. ``census_archived`` descarta toda fila
sin estado terminal, asi que la fila no entro en NINGUNO de sus cuatro
contadores -- required, audited, skipped_required, skipped_legacy -- y
``check_backlog_commits_landed`` siguio imprimiendo ``ERROR=0``. La fila tenia un
ticket real y un SHA real, y ningun contador la vio.

El detector se anadio en el censo, pero ESO SOLO ERA UNA NORMA:
``census_archived`` lo llama unicamente el CLI de ese script, y ese CLI no corre
en ningun hook. Estos tests son la mitad de CABLEADO: prueban que el check de
prepush -- un camino que corre solo -- se pone ROJO ante la fila malformada.
"""

from __future__ import annotations

from pathlib import Path

from scripts.prepush_check import run_landed_evidence_shape_check


ARCHIVE_REL = Path(".agent/collaboration/_archive/backlog_done.md")

# Fila BIEN formada: estado terminal en su celda, SHA en la celda de commit.
ROW_OK = (
    "| Media | WOT-2026-990a | trabajo deliverable_type: code | motor/x | done "
    "| commit:abc1234 | origen | - |\n"
)
# Fila MALFORMADA: el SHA ocupa la celda de estado -> no hay estado terminal.
ROW_MALFORMED = (
    "| Media | WOT-2026-991b | trabajo deliverable_type: code | motor/x "
    "| commit:def5678 | - | origen | - |\n"
)
# `superseded` NO es terminal, pero es un cierre legitimo que no aterriza; el
# archive real tiene filas asi CON celda commit (WOT-2026-027b, WOT-2026-040j).
ROW_SUPERSEDED = (
    "| Alta | WOT-2026-992c | movido deliverable_type: code | motor/x "
    "| superseded | WOT-2026-993d | origen | commit:abc1234 |\n"
)


def _write_archive(root: Path, rows: str) -> None:
    p = root / ARCHIVE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(rows, encoding="utf-8")


def test_readable_evidence_passes(tmp_path: Path) -> None:
    """Fila bien formada -> el gate pasa. Guarda contra un fix que siempre falla."""
    _write_archive(tmp_path, ROW_OK)
    result = run_landed_evidence_shape_check(tmp_path)
    assert result.passed is True
    assert "readable by the census" in result.output


def test_malformed_evidence_blocks_the_push(tmp_path: Path) -> None:
    """El caso que motiva la barrera: el SHA en la celda de estado pone ROJO.

    Mutacion alcanzable: devolver siempre ``passed=True`` (o retirar el registro
    en ``main``) -> este test se pone ROJO. Sin el, la fila desaparece del censo
    y el guard hermano sigue diciendo ``ERROR=0``.
    """
    _write_archive(tmp_path, ROW_MALFORMED)
    result = run_landed_evidence_shape_check(tmp_path)
    assert result.passed is False
    assert "WOT-2026-991b" in result.output, (
        f"el gate debe NOMBRAR la fila ofensora; got: {result.output}"
    )
    assert "false green" in result.output


def test_superseded_row_with_commit_does_not_block(tmp_path: Path) -> None:
    """CONTROL NEGATIVO. ``superseded`` es cierre legitimo sin aterrizaje.

    Mutacion alcanzable: retirar la exclusion de ``superseded`` en
    ``census_archived`` -> este test se pone ROJO. Sin el, la barrera daria dos
    falsos positivos en su PRIMERA corrida real contra el archive del destino,
    que es como una barrera nueva acaba desactivada.
    """
    _write_archive(tmp_path, ROW_SUPERSEDED)
    result = run_landed_evidence_shape_check(tmp_path)
    assert result.passed is True, (
        f"una fila superseded no es evidencia malformada; got: {result.output}"
    )


def test_missing_archive_is_a_named_skip_not_a_failure(tmp_path: Path) -> None:
    """Un destino sin archive todavia no ha cerrado nada: PASS con SKIP nombrado.

    Mutacion alcanzable: tratar el fichero ausente como fallo -> ROJO. Un gate
    que inventa un fallo sobre un destino recien instalado es un falso rojo.
    """
    result = run_landed_evidence_shape_check(tmp_path)
    assert result.passed is True
    assert "SKIP" in result.output


def test_gate_is_registered_in_the_closeout_run() -> None:
    """El detector solo es BARRERA si algo lo INVOCA (AGENTS.md, barrera cableada).

    Ancla en el registro real de ``main``: una cita en un prompt no cuenta. Esta
    asercion es lo que distingue este ticket del detector que ya existia.
    """
    source = Path(__file__).resolve().parents[1] / "scripts" / "prepush_check.py"
    text = source.read_text(encoding="utf-8")
    assert "results.append(run_landed_evidence_shape_check(project_root))" in text, (
        "el check existe pero NADIE lo invoca: eso es una norma, no una barrera"
    )
