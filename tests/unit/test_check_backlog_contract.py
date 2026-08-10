"""Barrier tests for check_backlog_contract.py (WOT-2026-012b).

The gate must: read the active 'Vista rapida' table only, enforce the closed
Status / Reactivation vocabulary, and FAIL CLOSED when no project root is given.
Every test reproduces a concrete contract violation and proves the gate blocks.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "check_backlog_contract.py"

_spec = importlib.util.spec_from_file_location("check_backlog_contract", MODULE_PATH)
cbc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cbc)


_HEADER = (
    "# Backlog (cola viva)\n\n"
    "## Vista rapida\n\n"
    "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
    "|-----------|--------|--------|-------|--------|------------|--------|--------------|\n"
)


def _write_backlog(tmp_path: Path, rows: str, fichas: str = "") -> Path:
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "backlog.md").write_text(_HEADER + rows + "\n" + fichas, encoding="utf-8")
    return tmp_path


_VALID_ROWS = (
    "| Alta | WOT-2026-001a | Bien | s | pending | - | x | - |\n"
    "| Media | WOT-2026-001b | Diferido | s | deferred | - | x | condition:algo-resuelto |\n"
    "| Baja | WOT-2026-001c | Bloqueado | s | blocked | - | x | external:cve-fix |\n"
    "| Alta | WOT-2026-001d | Parcial | s | completed-partial | - | x | WOT-2026-099z |\n"
)


def test_valid_backlog_passes(tmp_path: Path) -> None:
    root = _write_backlog(tmp_path, _VALID_ROWS, "### WOT-2026-001a - ficha bien\n")
    assert cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md") == []


def test_cola_vacia_es_estado_terminal_legitimo(tmp_path: Path) -> None:
    """Una tabla SIN filas es un proyecto acabado, no una violacion.

    Medido 2026-08-02 en el cierre real del destino LEA: `--session-close`
    dejo la cola vacia -- que era el OBJETIVO de la sesion -- y este checker
    devolvio rc=1 con "active 'Vista rapida' table has no rows". El contrato
    prohibia el estado terminal legitimo del proyecto: vaciar la cola es
    exactamente lo que hace un destino que termina su trabajo.

    La regla original protegia de otra cosa -- una tabla vacia por ERROR de
    parseo o por seccion mal formada --, y esa proteccion la da
    `_extract_active_table`, que ya devuelve `table_error` cuando la seccion
    no existe o no se puede leer (ver
    `test_missing_vista_rapida_section_blocks`). Distinguir "no hay seccion"
    de "la seccion existe y esta vacia" es lo que faltaba.
    """
    root = _write_backlog(tmp_path, "", "")
    errors = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert errors == [], (
        "una cola vacia con su cabecera intacta es el estado terminal de un "
        f"proyecto acabado, no un defecto. Errores: {errors}"
    )


def test_seccion_ausente_sigue_bloqueando(tmp_path: Path) -> None:
    """Mutacion inversa: la cola vacia se permite, la seccion rota NO.

    Sin este test, el fix de la cola vacia podria haberse hecho aflojando
    `_extract_active_table` y perdiendo la deteccion de un backlog corrupto.
    """
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "backlog.md").write_text("# Backlog sin seccion\n", encoding="utf-8")
    errors = cbc.validate_backlog(collab / "backlog.md")
    assert errors, "un backlog sin la seccion 'Vista rapida' sigue siendo invalido"


def test_el_centinela_de_sesion_cerrada_no_es_un_ticket_fantasma(
    tmp_path: Path,
) -> None:
    """`ACTIVE_TICKET: -` significa "ninguno", no un ticket llamado "-".

    Medido 2026-08-02, y es el motor contradiciendose a si mismo:
    `.agent/agent_controller.py:6176` ESCRIBE `ACTIVE_TICKET: -` al cerrar la
    sesion, y su propio docstring lo declara centinela ("tras cerrar la
    sesion ya no hay ticket activo"). Pero `_ACTIVE_TICKET_RE` captura `\\S+`,
    asi que `-` entraba como id de ticket y el checker lo denunciaba como
    fantasma: "STATE.md ACTIVE_TICKET '-' has NO row en backlog.md".

    Un cierre correcto producia rc=1 por su propia escritura.
    """
    root = _write_backlog(tmp_path, "", "")
    state = root / ".agent" / "collaboration" / "STATE.md"
    state.write_text("ACTIVE_TICKET: -\nSTATUS: COMPLETED\n", encoding="utf-8")

    ticket, status = cbc._read_active_ticket(root)
    assert ticket is None, (
        f"el centinela de 'ninguno' no puede leerse como ticket (leido: {ticket!r})"
    )
    assert status is None


def test_un_ticket_real_ausente_del_backlog_sigue_siendo_fantasma(
    tmp_path: Path,
) -> None:
    """Mutacion inversa: exceptuar el centinela NO puede apagar la deteccion."""
    root = _write_backlog(tmp_path, _VALID_ROWS, "")
    state = root / ".agent" / "collaboration" / "STATE.md"
    state.write_text(
        "ACTIVE_TICKET: WOT-2026-999z\nSTATUS: IN_PROGRESS\n", encoding="utf-8"
    )

    ticket, status = cbc._read_active_ticket(root)
    assert ticket == "WOT-2026-999z", "un ticket REAL debe seguir leyendose"
    assert status == "IN_PROGRESS"


def test_fail_closed_without_project_root(monkeypatch) -> None:
    # No --project-root and no AGENT_PROJECT_ROOT -> fail closed (no cwd fallback).
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    root, error = cbc.resolve_destino_root(None)
    assert root is None
    assert error is not None and "fail-closed" in error
    # And the CLI returns the dedicated exit code 2.
    assert cbc.main([]) == 2


def test_project_root_via_env(tmp_path: Path, monkeypatch) -> None:
    _write_backlog(tmp_path, _VALID_ROWS)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path))
    assert cbc.main([]) == 0


def test_terminal_status_in_live_queue_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path, "| Alta | WOT-2026-002a | Mal | s | completed | - | x | - |\n"
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("not in live vocabulary" in e for e in errs)


def test_deferred_without_trigger_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path, "| Alta | WOT-2026-002b | Mal | s | deferred | - | x | - |\n"
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("requires a structured Reactivation" in e for e in errs)


def test_vague_reactivation_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path, "| Alta | WOT-2026-002c | Mal | s | blocked | - | x | N/A |\n"
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("vague Reactivation" in e for e in errs)


def test_unstructured_reactivation_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path,
        "| Alta | WOT-2026-002d | Mal | s | deferred | - | x | cuando se pueda |\n",
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("is not structured" in e for e in errs)


def test_wrong_column_count_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path, "| Alta | WOT-2026-002e | Falta col | pending | - | x | - |\n"
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("columns" in e for e in errs)


def test_malformed_ficha_header_blocks(tmp_path: Path) -> None:
    root = _write_backlog(
        tmp_path,
        _VALID_ROWS,
        "### WOT-bad ficha sin id valido\n",
    )
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("malformed ficha header" in e for e in errs)


def test_ficha_redeclaring_flt_blocks(tmp_path: Path) -> None:
    """WOT-2026-013j: a detailed ficha that re-declares 'Files Likely Touched'
    must be blocked. The FLT is owned by the frozen contract, not the backlog.

    FAIL-without-fix: the gate only checked the table + ficha headers, so a
    declarative FLT bullet in the ficha body passed silently (the recurring
    013h/013i drift). PASS-with-fix: the gate fails closed naming the ficha.
    """
    ficha = (
        "### WOT-2026-001a - ficha que re-declara FLT\n"
        "- **Problema:** algo\n"
        "- **Files Likely Touched:**\n"
        "  - repo_motor: `scripts/foo.py`\n"
    )
    root = _write_backlog(tmp_path, _VALID_ROWS, ficha)
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("re-declares 'Files Likely Touched'" in e for e in errs), errs
    assert any("WOT-2026-001a" in e for e in errs), errs


def test_ficha_prose_mention_of_flt_is_allowed(tmp_path: Path) -> None:
    """Negative companion: merely MENTIONING 'Files Likely Touched' in prose
    inside another bullet (not as a declarative key) must NOT be blocked. The
    ficha may reference the concept; it just may not own the FLT declaration.
    """
    ficha = (
        "### WOT-2026-001a - ficha que solo menciona FLT en prosa\n"
        "- **Problema:** las fichas re-declaran el `Files Likely Touched` "
        "que vive en el contrato frozen.\n"
        "- **Objetivo:** definir una sola fuente de verdad.\n"
    )
    root = _write_backlog(tmp_path, _VALID_ROWS, ficha)
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert not any("re-declares 'Files Likely Touched'" in e for e in errs), errs


def test_missing_vista_rapida_section_blocks(tmp_path: Path) -> None:
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "backlog.md").write_text("# Backlog\n\nno table here\n", encoding="utf-8")
    errs = cbc.validate_backlog(collab / "backlog.md")
    assert any("Vista rapida" in e for e in errs)


def test_header_column_mismatch_blocks(tmp_path: Path) -> None:
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    # Missing the Reactivation column (the 012a addition).
    (collab / "backlog.md").write_text(
        "## Vista rapida\n\n"
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Alta | WOT-2026-003a | x | s | pending | - | x |\n",
        encoding="utf-8",
    )
    errs = cbc.validate_backlog(collab / "backlog.md")
    assert any("header columns mismatch" in e for e in errs)


def test_gate_invocable_by_absolute_path_from_foreign_cwd(tmp_path: Path) -> None:
    """WOT-2026-012b integration barrier (Manager CHANGES): run_gates_dispatch must
    invoke the gate by the MOTOR's absolute path, because PROJECT_ROOT resolves to
    repo_destino in the destino-motor topology. A relative 'scripts/...' path with
    cwd=repo_destino fails 'can't open file' (the BLOCKER). This test ejerce the real
    integrated path: invoke the gate by absolute motor path from a foreign cwd
    (the destino), and require it to actually RUN (rc in {0,1,2}), never the
    interpreter's exit 2 'can't open file'."""
    import subprocess
    import sys

    # A valid destino fixture so the gate itself returns 0.
    _write_backlog(tmp_path, _VALID_ROWS, "### WOT-2026-001a - ficha\n")

    # Foreign cwd = the destino (NOT the motor): the relative-path bug would fail here.
    r = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),  # absolute motor path, as the fixed dispatcher uses
            "--project-root",
            str(tmp_path),
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    # The gate ran (its own contract verdict), not a "can't open file" interpreter error.
    assert "can't open file" not in (r.stderr or ""), r.stderr
    assert r.returncode == 0, f"gate should pass on valid backlog; stderr={r.stderr}"


def test_relative_path_from_destino_cwd_is_the_bug(tmp_path: Path) -> None:
    """Negative companion: invoking the gate by RELATIVE 'scripts/...' from a destino
    cwd (the pre-fix behavior) fails to open the file. Documents the BLOCKER so a
    regression to relative-path invocation is caught."""
    import subprocess
    import sys

    _write_backlog(tmp_path, _VALID_ROWS)
    r = subprocess.run(
        [
            sys.executable,
            "scripts/check_backlog_contract.py",
            "--project-root",
            str(tmp_path),
        ],
        cwd=str(tmp_path),  # destino has no scripts/check_backlog_contract.py
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "can't open file" in (r.stderr or "") or "No such file" in (r.stderr or "")


# ---------------------------------------------------------------------------
# WOT-2026-027t: the live queue must not fragment -- a ticket row OUTSIDE the
# 'Vista rapida' table (e.g. drifted under '## Fichas detalladas') is fail-closed.
# ---------------------------------------------------------------------------


def test_ticket_row_outside_table_blocks(tmp_path: Path) -> None:
    """The fragmentation trap: a well-formed 8-cell ticket row placed AFTER the
    Vista rapida table (under a later section) is invisible to the extractor, so
    the old contract 'held' over half the queue. The guard now fails closed and
    names the drifted row and its line.

    FAIL-without-fix (mutation): remove the `_ticket_rows_outside_table` call from
    validate_backlog -> this row passes silently, exactly the WOT-2026-027t defect.
    """
    fichas = (
        "### WOT-2026-001a - ficha\n\n"
        "| Alta | WOT-2026-099z | fuera de tabla | s | pending | - | x | - |\n"
    )
    root = _write_backlog(tmp_path, _VALID_ROWS, fichas)
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert any("WOT-2026-099z" in e and "OUTSIDE" in e for e in errs), errs


def test_all_ticket_rows_inside_table_passes(tmp_path: Path) -> None:
    """Negative companion: when every ticket row lives inside the Vista rapida
    table, the fragmentation check adds no violation."""
    root = _write_backlog(tmp_path, _VALID_ROWS, "### WOT-2026-001a - ficha\n")
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    assert not any("OUTSIDE" in e for e in errs), errs


def test_dependency_cell_citing_ticket_id_is_not_a_stray_row(tmp_path: Path) -> None:
    """Cell-based, never substring: a ficha bullet or a table cell that MENTIONS a
    ticket id in prose (e.g. a 'Depende de' reference) is NOT a ticket row -- only
    a row whose SECOND cell IS a bare id counts. A substring scan would false-flag
    the mention; this test dies under that mutation."""
    fichas = (
        "### WOT-2026-001a - ficha\n"
        "- **Depende de:** WOT-2026-099z (citado en prosa, no es una fila)\n"
        "- Una tabla ajena de otro esquema:\n"
        "| campo | WOT-2026-099z como dato | otro |\n"
    )
    root = _write_backlog(tmp_path, _VALID_ROWS, fichas)
    errs = cbc.validate_backlog(root / ".agent" / "collaboration" / "backlog.md")
    # The prose mention and the foreign-table cell (id in cell[2] but as free text
    # 'WOT-2026-099z como dato', not a bare id) must not be flagged as stray rows.
    assert not any("OUTSIDE" in e for e in errs), errs


# ---------------------------------------------------------------------------
# WOT-2026-027i: duplicate ids across (live<->archive) and within the archive.
# ---------------------------------------------------------------------------

_ARCHIVE_HEADER = "# Backlog -- historico\n\n"


def _write_archive_prioridad(root: Path, rows: str) -> None:
    """Archive with the Prioridad-led snapshot layout (id at raw index 2), the
    layout 027i's guard scopes to."""
    arch = root / ".agent" / "collaboration" / "_archive"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "backlog_done.md").write_text(
        _ARCHIVE_HEADER
        + "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        + "|--|--|--|--|--|--|--|--|\n"
        + rows,
        encoding="utf-8",
    )


def test_live_and_archive_duplicate_blocks(tmp_path: Path) -> None:
    """An id present as a LIVE row AND an archived row lies in both directions.

    FAIL-without-fix (mutation): drop validate_live_archive_integrity from main's
    violation list -> this duplicate passes, the exact WOT-2026-027i defect.
    """
    _write_backlog(tmp_path, _VALID_ROWS)  # 001a is a live 'pending' row
    _write_archive_prioridad(
        tmp_path,
        "| Alta | WOT-2026-001a | dup | s | completed-partial | - | x | commit:abc |\n",
    )
    errs = cbc.validate_live_archive_integrity(tmp_path)
    assert any("WOT-2026-001a" in e and "both directions" in e for e in errs), errs


def test_archive_internal_duplicate_blocks(tmp_path: Path) -> None:
    """An id present TWICE inside the archive (the WOT-2026-011b contradiction:
    a 'pending' and a 'completed' row for one ticket) is fail-closed."""
    _write_backlog(tmp_path, _VALID_ROWS)
    _write_archive_prioridad(
        tmp_path,
        "| Alta | WOT-2026-070z | v1 | s | pending | - | x | - |\n"
        "| Alta | WOT-2026-070z | v2 | s | completed-partial | - | x | commit:abc |\n",
    )
    errs = cbc.validate_live_archive_integrity(tmp_path)
    assert any("WOT-2026-070z" in e and "2 times" in e for e in errs), errs


def test_no_duplicate_passes(tmp_path: Path) -> None:
    """Clean surfaces: no id crosses live<->archive and none repeats in archive."""
    _write_backlog(tmp_path, _VALID_ROWS)
    _write_archive_prioridad(
        tmp_path,
        "| Alta | WOT-2026-070z | closed | s | completed-partial | - | x | commit:abc |\n",
    )
    assert cbc.validate_live_archive_integrity(tmp_path) == []


def test_compact_closurelog_row_is_out_of_scope(tmp_path: Path) -> None:
    """SCOPE (aplicate tu propia vara): a ticket legitimately appears BOTH in the
    archive's compact ``| Ticket | Estado | Nota |`` closure-log (id at raw index
    1) AND in a Prioridad-led snapshot -- that is normal archive layering, NOT the
    027i contradiction. The guard scopes to the Prioridad-led position (raw index
    2), so the compact row is not counted and does not false-flag. A cell[:2]
    scan would raise a false positive here; this test dies under that widening."""
    _write_backlog(tmp_path, _VALID_ROWS)
    arch = tmp_path / ".agent" / "collaboration" / "_archive"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "backlog_done.md").write_text(
        _ARCHIVE_HEADER
        + "| Ticket | Estado | Nota |\n|--|--|--|\n"
        + "| WOT-2026-070z | completed | cerrado canonico |\n\n"
        + "## snapshot historico\n\n"
        + "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        + "|--|--|--|--|--|--|--|--|\n"
        + "| Alta | WOT-2026-070z | snap | s | completed-partial | - | x | commit:abc |\n",
        encoding="utf-8",
    )
    # 070z appears once compact (index 1, ignored) + once Prioridad-led (index 2):
    # counted exactly once -> no internal-dup violation.
    assert cbc.validate_live_archive_integrity(tmp_path) == []


# ---------------------------------------------------------------------------
# WOT-2026-026z: arity of NEW Prioridad-led rows in the archive.
# ---------------------------------------------------------------------------


def _write_archive_arity(root: Path, rows: str) -> None:
    arch = root / ".agent" / "collaboration" / "_archive"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "backlog_done.md").write_text(
        _ARCHIVE_HEADER
        + "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        + "|--|--|--|--|--|--|--|--|\n"
        + rows,
        encoding="utf-8",
    )


def test_new_archive_row_broken_by_pipe_blocks(tmp_path: Path) -> None:
    """A NEW Prioridad-led archive row with an unescaped pipe gains cells and its
    terminal commit: cell drifts out of the table -- fail closed naming it.

    FAIL-without-fix (mutation): drop validate_archive_row_arity from main's
    violations -> this broken row passes, the exact WOT-2026-026z defect.
    """
    _write_backlog(tmp_path, _VALID_ROWS)
    _write_archive_arity(
        tmp_path,
        "| Alta | WOT-2026-088z | rompe grep -qE 'a | b' aqui | s | completed | - | x | commit:abc |\n",
    )
    errs = cbc.validate_archive_row_arity(tmp_path)
    assert any("WOT-2026-088z" in e and "cells, expected 8" in e for e in errs), errs


def test_clean_new_archive_row_passes(tmp_path: Path) -> None:
    """A NEW Prioridad-led row with the canonical 8 cells (no stray pipe) passes."""
    _write_backlog(tmp_path, _VALID_ROWS)
    _write_archive_arity(
        tmp_path,
        "| Alta | WOT-2026-088z | titulo limpio sin pipe | s | completed | - | x | commit:abc |\n",
    )
    assert cbc.validate_archive_row_arity(tmp_path) == []


def test_legacy_baseline_row_is_exempt(tmp_path: Path) -> None:
    """A ticket id in the declared legacy baseline (a historical pipe-break or an
    old 7-column row) is EXEMPT: the guard mira lo que se ANADE, never demands
    arity of history. This test dies if the baseline exemption is removed."""
    _write_backlog(tmp_path, _VALID_ROWS)
    # WOT-2026-004b is in the baseline: a 10-cell row for it must NOT be flagged.
    _write_archive_arity(
        tmp_path,
        "| Alta | WOT-2026-004b | fila legacy rota | s | completed | - | x | y | z | commit:abc |\n",
    )
    assert cbc.validate_archive_row_arity(tmp_path) == []


def test_baseline_id_at_other_arity_is_a_fresh_break(tmp_path: Path) -> None:
    """The RESTRICTIVE side of the exemption: a baseline id is forgiven ONLY at the
    arity actually censused. A brand-new row under a baseline id at a DIFFERENT
    arity is a fresh break and MUST fail.

    Governance loop 2026-07-23: while the baseline was an id-only frozenset, this
    case passed silently -- replacing a legacy row with a fresh broken one under
    the same id exempted it forever. This test dies if the exemption is ever
    widened back to id-only.
    """
    _write_backlog(tmp_path, _VALID_ROWS)
    # WOT-2026-004b is censused at 10 cells; this NEW row has 9 -> fresh break.
    row = "| Alta | WOT-2026-004b | fila NUEVA | rota | s | completed | - | x | commit:abc |\n"
    # Self-verify the fixture's own premise before trusting the guard's verdict:
    # a miscounted row silently turns this test into a no-op.
    assert len(row.strip().strip("|").split("|")) == 9
    _write_archive_arity(tmp_path, row)
    errors = cbc.validate_archive_row_arity(tmp_path)
    assert len(errors) == 1, errors
    assert "WOT-2026-004b" in errors[0]
    assert "9 cells" in errors[0]


def test_archive_arity_baseline_is_pinned() -> None:
    """Pin the declared census so it cannot be widened in silence.

    The module comment states "nothing may ADD an entry to silence a FRESH break",
    but prose is not a mechanism: adding an id was a one-line edit that stayed
    green everywhere. This test makes that edit fail loudly.

    REDUCING the baseline (repairing a row and removing its entry) is legitimate
    and SHOULD update this test. ADDING an entry to silence a fresh break is not.
    """
    baseline = cbc._ARCHIVE_ARITY_LEGACY_BASELINE
    assert len(baseline) == 20, (
        f"baseline moved to {len(baseline)} entries: repairing a row is legitimate "
        "(update this test); ADDING one to silence a fresh break is not."
    )
    # The prose above the dict states the census breakdown. A comment that drifts
    # from the code is the very defect 026z exists to catch, so pin the shape too:
    # 17 pipe-break rows (15 at 9 cells, 2 at 10) + 3 legacy 7-column rows = 20.
    by_arity = {n: list(baseline.values()).count(n) for n in set(baseline.values())}
    assert by_arity == {9: 15, 10: 2, 7: 3}, (
        f"census breakdown is now {by_arity}; update the comment above "
        "_ARCHIVE_ARITY_LEGACY_BASELINE so prose and code stay in lockstep."
    )
    # Arity is part of the contract: the pair (id, arity) is what grants exemption.
    assert sorted(baseline.items()) == sorted(
        {
            "WOT-2026-004b": 10,
            "WOT-2026-010h": 10,
            "WOT-2026-013b": 9,
            "WOT-2026-011i": 9,
            "WOT-2026-011h": 9,
            "WOT-2026-013c": 9,
            "WOT-2026-014c": 9,
            "WOT-2026-014a": 9,
            "WOT-2026-014b": 9,
            "WOT-2026-014d": 9,
            "WOT-2026-014e": 9,
            "WOT-2026-014f": 9,
            "WOT-2026-014g": 9,
            "WOT-2026-014h": 9,
            "WOT-2026-014i": 9,
            "WOT-2026-015n": 9,
            "WOT-2026-021i": 9,
            "WT-2026-250c": 7,
            "WOT-2026-008e": 7,
            "WOT-2026-008j": 7,
        }.items()
    )


# ---------------------------------------------------------------------------
# WOT-2026-023o: STATE.md ACTIVE_TICKET vs the scheduling surfaces (bus projection)
# ---------------------------------------------------------------------------


def _write_state(root: Path, ticket: str, status: str) -> None:
    collab = root / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "STATE.md").write_text(
        f"ACTIVE_TICKET: {ticket}\nSTATUS: {status}\n", encoding="utf-8"
    )


def _write_archive(root: Path, rows: str) -> None:
    """Archive layout: ID in the FIRST cell (no Prioridad column), unlike the
    live backlog where it is the SECOND cell. This is the two-layout trap."""
    arch = root / ".agent" / "collaboration" / "_archive"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "backlog_done.md").write_text(_ARCHIVE_HEADER + rows, encoding="utf-8")


def test_active_ticket_ghost_blocks(tmp_path: Path) -> None:
    """A ghost ACTIVE_TICKET (no row in backlog nor archive) is a violation
    regardless of STATUS: the bus projection declares active something no
    scheduling surface knows."""
    _write_backlog(tmp_path, _VALID_ROWS)
    _write_state(tmp_path, "WOT-2026-999z", "IN_PROGRESS")
    errs = cbc.validate_active_ticket_state(tmp_path)
    assert any("ghost" in e and "WOT-2026-999z" in e for e in errs), errs


def test_active_ticket_non_terminal_archive_only_blocks(tmp_path: Path) -> None:
    """The WOT-2026-022i incident: STATE.md declares a NON-terminal STATUS
    (READY_FOR_REVIEW) over a ticket that only exists in the archive."""
    _write_backlog(tmp_path, _VALID_ROWS)  # no live row for the archived ticket
    _write_archive(
        tmp_path, "| WOT-2026-022i | completed | archived | - | x | commit:9b852a1 |\n"
    )
    _write_state(tmp_path, "WOT-2026-022i", "READY_FOR_REVIEW")
    errs = cbc.validate_active_ticket_state(tmp_path)
    assert any(
        "only exists in the archive" in e and "WOT-2026-022i" in e for e in errs
    ), errs


def test_active_ticket_terminal_archive_only_passes(tmp_path: Path) -> None:
    """Complement: a COMPLETED (terminal) STATUS pointing to an archived ticket
    is the normal post-close residual -- must NOT block. Distinguishing this from
    the non-terminal case above is the whole point of the STATUS sensitivity."""
    _write_backlog(tmp_path, _VALID_ROWS)
    _write_archive(
        tmp_path, "| WOT-2026-022i | completed | archived | - | x | commit:9b852a1 |\n"
    )
    _write_state(tmp_path, "WOT-2026-022i", "COMPLETED")
    assert cbc.validate_active_ticket_state(tmp_path) == []


def test_active_ticket_live_row_passes(tmp_path: Path) -> None:
    """A non-terminal STATUS pointing to a ticket present in the LIVE backlog is
    exactly the healthy case."""
    _write_backlog(tmp_path, _VALID_ROWS)  # 001a is a live 'pending' row
    _write_state(tmp_path, "WOT-2026-001a", "IN_PROGRESS")
    assert cbc.validate_active_ticket_state(tmp_path) == []


def test_layout_archive_id_first_cell_is_found(tmp_path: Path) -> None:
    """Two-layout trap: the archived ID sits in the FIRST cell. The cell-scan
    finds it (terminal STATUS -> passes). A parser anchored on cell[1] would miss
    it and raise a false ghost -- this test dies under that positional mutation."""
    _write_backlog(tmp_path, _VALID_ROWS)
    _write_archive(
        tmp_path, "| WOT-2026-070x | completed | nota | - | x | commit:abc |\n"
    )
    _write_state(tmp_path, "WOT-2026-070x", "COMPLETED")
    assert cbc.validate_active_ticket_state(tmp_path) == []


def test_layout_backlog_id_second_cell_is_found(tmp_path: Path) -> None:
    """Two-layout trap, other side: the live-backlog ID sits in the SECOND cell
    (after Prioridad). A parser anchored on cell[0] would read the priority and
    raise a false ghost -- this test dies under that positional mutation."""
    _write_backlog(tmp_path, _VALID_ROWS)  # 001b in cell[1] after 'Media'
    _write_state(tmp_path, "WOT-2026-001b", "IN_PROGRESS")
    assert cbc.validate_active_ticket_state(tmp_path) == []


def test_no_state_md_not_applicable(tmp_path: Path) -> None:
    _write_backlog(tmp_path, _VALID_ROWS)
    assert cbc.validate_active_ticket_state(tmp_path) == []


def test_state_md_without_active_ticket_not_applicable(tmp_path: Path) -> None:
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    (collab / "STATE.md").write_text("STATUS: UNKNOWN\n", encoding="utf-8")
    _write_backlog(tmp_path, _VALID_ROWS)
    assert cbc.validate_active_ticket_state(tmp_path) == []


# --------------------------------------------------------------------------- #
# WOT-2026-043t (fase 3): comprimir una fila gorda a "puntero + criterio
# invariante" convierte el PUNTERO en parte del contrato. Si la ficha se borra o
# se duplica, la fila conserva un criterio que ya no puede justificar y NADA lo
# nota: la fila sigue parseando, asi que el resto de checks siguen verdes. Lo
# levantaron las DOS lentes del bucle L4500 de forma independiente.
# --------------------------------------------------------------------------- #
_PTR_ROW = (
    "| Media | WOT-2026-0p9z | resumen. ver ficha `### WOT-2026-0p9z` abajo. "
    "| motor/x | pending | - | origen | - |"
)


def test_043t_pointer_with_reachable_ficha_passes() -> None:
    """CONTROL POSITIVO: fila que delega + ficha presente -> sin errores."""
    content = "\n".join([_PTR_ROW, "", "### WOT-2026-0p9z - resumen"])
    assert cbc._check_ficha_pointers(content, [_PTR_ROW]) == []


def test_043t_dangling_pointer_is_an_error() -> None:
    """El defecto: la fila delega en una ficha que NO existe.

    Mutacion alcanzable: retirar la llamada a _check_ficha_pointers de
    validate_backlog (o devolver [] siempre) -> este test se pone ROJO.
    """
    errors = cbc._check_ficha_pointers(_PTR_ROW, [_PTR_ROW])
    assert len(errors) == 1
    assert "WOT-2026-0p9z" in errors[0]
    assert "dangling" in errors[0]


def test_043t_duplicate_ficha_is_an_error() -> None:
    """Dos fichas con el mismo id: el puntero no puede decir cual manda."""
    content = "\n".join([_PTR_ROW, "### WOT-2026-0p9z - a", "### WOT-2026-0p9z - b"])
    errors = cbc._check_ficha_pointers(content, [_PTR_ROW])
    assert len(errors) == 1
    assert "2 fichas" in errors[0]


def test_043t_row_without_pointer_needs_no_ficha() -> None:
    """CONTROL NEGATIVO: una fila autosuficiente no exige ficha.

    Mutacion alcanzable: exigir ficha a TODA fila -> ROJO. Sin este test, el
    guard obligaria a crear 180 fichas vacias para las filas que no delegan.
    """
    row = "| Media | WOT-2026-0q8y | todo el criterio aqui | s | pending | - | o | - |"
    assert cbc._check_ficha_pointers(row, [row]) == []


def test_043t_citing_another_tickets_ficha_does_not_claim_own_completeness() -> None:
    """Una fila que MENCIONA la ficha de OTRO ticket no delega la suya.

    Mutacion alcanzable: casar 'ver ficha' sin comprobar que el id citado es el
    de la propia fila -> ROJO (pediria una ficha que esta fila nunca prometio).
    """
    row = (
        "| Media | WOT-2026-0r7x | criterio propio; contexto en ver ficha "
        "`### WOT-2026-0p9z` | s | pending | - | o | - |"
    )
    assert cbc._check_ficha_pointers(row, [row]) == []


# ---------------------------------------------------------------------------
# WOT-2026-026t: una fila ARCHIVADA con estado NO-TERMINAL es trabajo pendiente
# archivado como historia -- invisible en las dos superficies. Medido 2026-08-04:
# 18 filas asi (9 de 8 celdas + 9 rotas por un pipe), ninguna era trabajo perdido
# pero todas llevaban semanas fuera de la vista.
# ---------------------------------------------------------------------------


def _archive_row(ticket: str, estado: str, extra_pipe: bool = False) -> str:
    """Fila Prioridad-led de archivo. Con ``extra_pipe`` simula el pipe sin
    escapar que rompe la arity y desplaza las columnas una posicion."""
    titulo = "titulo | partido" if extra_pipe else "titulo"
    return f"| Media | {ticket} | {titulo} | motor/scope | {estado} | - | origen | - |"


def test_026t_archived_row_with_live_state_is_a_violation(tmp_path) -> None:
    """El defecto fundacional: `pending` archivado.

    Mutacion alcanzable: quitar la comprobacion `state in LIVE_STATES` -> el
    caso pasa en verde y las 18 filas medidas siguen invisibles.
    """
    collab = tmp_path / ".agent" / "collaboration" / "_archive"
    collab.mkdir(parents=True)
    (collab / "backlog_done.md").write_text(
        _archive_row("WOT-2026-0a1a", "pending") + "\n", encoding="utf-8"
    )
    errors = cbc.validate_archive_states(tmp_path)
    assert len(errors) == 1
    assert "NON-terminal state 'pending'" in errors[0]


def test_026t_archived_row_with_terminal_state_passes(tmp_path) -> None:
    """CONTROL POSITIVO: un cierre normal no debe molestar."""
    collab = tmp_path / ".agent" / "collaboration" / "_archive"
    collab.mkdir(parents=True)
    (collab / "backlog_done.md").write_text(
        _archive_row("WOT-2026-0a2a", "completed") + "\n", encoding="utf-8"
    )
    assert cbc.validate_archive_states(tmp_path) == []


def test_026t_typo_state_does_not_pass_as_terminal(tmp_path) -> None:
    """Una ERRATA no puede colarse por 'no ser un estado live'.

    Este test existe por una REGRESION real: la primera version derivaba
    'terminal' por complemento de LIVE_STATES, y `competed` (typo de
    `completed`) pasaba en verde. Mutacion alcanzable: volver al complemento
    -> ROJO.
    """
    collab = tmp_path / ".agent" / "collaboration" / "_archive"
    collab.mkdir(parents=True)
    (collab / "backlog_done.md").write_text(
        _archive_row("WOT-2026-0a3a", "competed") + "\n", encoding="utf-8"
    )
    errors = cbc.validate_archive_states(tmp_path)
    assert len(errors) == 1
    assert "UNKNOWN state 'competed'" in errors[0]


def test_026t_pipe_broken_row_is_still_audited(tmp_path) -> None:
    """Una fila ROTA por un pipe no queda fuera de alcance.

    Hallazgo de un bucle adversarial: la primera version hacia `continue` si la
    arity no era 8, heredando el scope del guard de aridad; eso dejaba 9 filas
    con estado live invisibles. Mutacion alcanzable: reponer ese `continue`
    -> ROJO.
    """
    collab = tmp_path / ".agent" / "collaboration" / "_archive"
    collab.mkdir(parents=True)
    (collab / "backlog_done.md").write_text(
        _archive_row("WOT-2026-0a4a", "pending", extra_pipe=True) + "\n",
        encoding="utf-8",
    )
    errors = cbc.validate_archive_states(tmp_path)
    assert len(errors) == 1
    assert "NON-terminal state 'pending'" in errors[0]


def test_026t_shifted_row_reads_its_real_state_not_the_scope(tmp_path) -> None:
    """Una fila desplazada NO debe acusarse por leer el Scope como Estado.

    Medido: `WOT-2026-015n` y `WOT-2026-021i` estan bien cerradas (`completed`
    en el indice 5), pero el indice 4 contiene su Scope (`motor/...`). Leer la
    posicion a ciegas las denunciaba como estado desconocido. Mutacion
    alcanzable: quitar el desplazamiento por forma-de-Scope -> ROJO.
    """
    collab = tmp_path / ".agent" / "collaboration" / "_archive"
    collab.mkdir(parents=True)
    (collab / "backlog_done.md").write_text(
        _archive_row("WOT-2026-0a5a", "completed", extra_pipe=True) + "\n",
        encoding="utf-8",
    )
    assert cbc.validate_archive_states(tmp_path) == []


def test_026t_missing_archive_is_not_a_violation(tmp_path) -> None:
    """Un destino sin archivo todavia no incumple nada."""
    (tmp_path / ".agent" / "collaboration").mkdir(parents=True)
    assert cbc.validate_archive_states(tmp_path) == []


def test_026t_compact_closure_log_row_with_live_state_is_a_violation(tmp_path) -> None:
    """El closure-log compacto tampoco puede declarar trabajo vivo.

    Hueco levantado por una pasada adversarial: el check Prioridad-led ignora las
    filas compactas (`| Ticket | Estado | Nota |`) a proposito, asi que una
    compacta con `pending` no la veia nadie. Medido: 124 compactas, 0 con estado
    live -- se cierra la puerta ANTES de que alguien la cruce. Mutacion
    alcanzable: quitar la llamada a `_compact_closure_log_states` -> ROJO.
    """
    collab = tmp_path / ".agent" / "collaboration" / "_archive"
    collab.mkdir(parents=True)
    (collab / "backlog_done.md").write_text(
        "| WOT-2026-0a6a | pending | nota de cierre |\n", encoding="utf-8"
    )
    errors = cbc.validate_archive_states(tmp_path)
    assert len(errors) == 1
    assert "compact closure-log row" in errors[0]


def test_026t_compact_closure_log_row_with_terminal_state_passes(tmp_path) -> None:
    """CONTROL POSITIVO: una nota de cierre normal no molesta."""
    collab = tmp_path / ".agent" / "collaboration" / "_archive"
    collab.mkdir(parents=True)
    (collab / "backlog_done.md").write_text(
        "| WOT-2026-0a7a | completed | cerrado canonico |\n", encoding="utf-8"
    )
    assert cbc.validate_archive_states(tmp_path) == []


def test_049c_live_row_depending_on_a_closed_ticket_is_a_violation(tmp_path) -> None:
    """Una fila VIVA no puede depender de un ticket ya cerrado.

    Caso real que la origina: `049g` quedo `pending` con `Depende de:
    WOT-2026-049c` DESPUES de que `049c` se cerrara con `commit:4199f17`. El
    contrato salia rc=0 porque la celda `Depende de` solo se nombraba para
    EXCLUIRLA del matching de ids -- se conocia y se evitaba a proposito, pero
    nada validaba el ESTADO del ticket citado. Un bloqueo que apunta a un
    difunto es indistinguible de uno real y congela al heredero.

    Mutacion alcanzable: quitar la llamada a `validate_live_dependencies` en
    `main()` -> este test queda en ROJO.
    """
    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0b1a | titulo | scope | pending | WOT-2026-0b1b | x | - |\n",
        encoding="utf-8",
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Alta | WOT-2026-0b1b | titulo | scope | completed | - | x | commit:abc1234 |\n",
        encoding="utf-8",
    )
    errors = cbc.validate_live_dependencies(tmp_path)
    assert len(errors) == 1
    assert "WOT-2026-0b1a" in errors[0]
    assert "WOT-2026-0b1b" in errors[0]
    assert "CERRADO" in errors[0]


def test_049c_live_row_depending_on_a_live_ticket_passes(tmp_path) -> None:
    """CONTROL NEGATIVO: un bloqueo REAL no debe dispararse.

    Sin este control el guard podria estar marcando toda dependencia, un falso
    positivo que haria inservible la celda `Depende de`.
    """
    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0b2a | titulo | scope | pending | WOT-2026-0b2b | x | - |\n"
        "| Alta | WOT-2026-0b2b | titulo | scope | pending | - | x | - |\n",
        encoding="utf-8",
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Alta | WOT-2026-0b2c | titulo | scope | completed | - | x | commit:abc1234 |\n",
        encoding="utf-8",
    )
    assert cbc.validate_live_dependencies(tmp_path) == []


def test_049c_multi_dependency_cell_resolves_each_id(tmp_path) -> None:
    """La celda puede citar VARIOS ids (precedente real: `WOT-2026-013b`).

    Discriminante: con un solo id cerrado entre dos, dispara UNA vez y nombra
    exactamente el cerrado, no la celda entera.
    """
    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0b3a | t | s | pending | WOT-2026-0b3b, WOT-2026-0b3c | x | - |\n"
        "| Alta | WOT-2026-0b3c | t | s | pending | - | x | - |\n",
        encoding="utf-8",
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Alta | WOT-2026-0b3b | t | s | completed | - | x | commit:abc1234 |\n",
        encoding="utf-8",
    )
    errors = cbc.validate_live_dependencies(tmp_path)
    assert len(errors) == 1
    assert "WOT-2026-0b3b" in errors[0]
    assert "WOT-2026-0b3c" not in errors[0]


def test_049c_no_dependency_or_missing_archive_is_silent(tmp_path) -> None:
    """CONTROL: '-' y archive ausente no son violaciones (destino recien creado)."""
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0b4a | t | s | pending | - | x | - |\n",
        encoding="utf-8",
    )
    assert cbc.validate_live_dependencies(tmp_path) == []


def test_049c_main_wires_the_dependency_check(tmp_path, capsys) -> None:
    """El cableado en `main()`, no solo la funcion.

    MUTACION QUE ESTE TEST MATA Y LOS OTROS NO: si se retira la linea
    `violations + validate_live_dependencies(root)` de `main()`, los tests que
    invocan la funcion directamente siguen VERDES -- el mutante sobrevive porque
    no alcanzan la rama del cableado. Medido: con el cableado retirado, el guard
    sobre el destino real pasaba de exit 1 a exit 0. Por eso este test entra por
    `main()` y afirma sobre su EXIT CODE.
    """
    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0b5a | t | s | pending | WOT-2026-0b5b | x | - |\n",
        encoding="utf-8",
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Alta | WOT-2026-0b5b | t | s | completed | - | x | commit:abc1234 |\n",
        encoding="utf-8",
    )
    rc = cbc.main(["--project-root", str(tmp_path)])
    assert rc == 1
    assert "WOT-2026-0b5b" in capsys.readouterr().err


def test_049c_terminal_census_reads_the_compact_closure_log(tmp_path) -> None:
    """El censo de cerrados cubre los DOS layouts del archive.

    MUTACION QUE ESTE TEST MATA: si `_terminal_ticket_states` vuelve a leer solo
    filas Prioridad-led, un ticket cerrado con NOTA "| WOT-2026-0c1b | completed | cerrado con nota compacta |\n"A
    (`| Ticket | Estado | Nota |`) desaparece del denominador y la fila viva que
    depende de el pasa DESAPERCIBIDA. Es el mismo defecto que este guard
    denuncia, cometido por el guard. Medido antes del arreglo: 77 tickets
    cerrados solo en compacto e invisibles -> 13 falsos negativos reales.
    """
    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0c1a | t | s | pending | WOT-2026-0c1b | x | - |\n",
        encoding="utf-8",
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        "| WOT-2026-0c1b | completed | cerrado con nota compacta |\n", encoding="utf-8"
    )
    errors = cbc.validate_live_dependencies(tmp_path)
    assert len(errors) == 1
    assert "WOT-2026-0c1b" in errors[0]


def test_049c_dependency_cell_with_prose_still_resolves_the_id(tmp_path) -> None:
    """La celda `Depende de` admite PROSA pegada al id, y el id debe resolverse.

    Caso real medido: `WOT-2026-029e` cita
    `WOT-2026-026j [026h SATISFECHA 2026-07-21: ...]`. Con `split(",")` + lookup
    EXACTO ese token no resuelve NUNCA y se descarta EN SILENCIO -- un falso
    negativo invisible, el mismo patron del denominador en su tercera forma.

    MUTACION ALCANZABLE: volver a `raw.split(",")` -> este test queda ROJO.
    """
    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0d1a | t | s | pending | WOT-2026-0d1b [0D1C SATISFECHA: archivada] | x | - |\n",
        encoding="utf-8",
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Alta | WOT-2026-0d1b | t | s | completed | - | x | commit:abc1234 |\n",
        encoding="utf-8",
    )
    errors = cbc.validate_live_dependencies(tmp_path)
    assert len(errors) == 1
    assert "WOT-2026-0d1b" in errors[0]


def test_049c_dash_with_historical_prose_is_not_a_dependency(tmp_path) -> None:
    """CONTROL ANTI-FALSO-POSITIVO: `-` con traza historica NO es un bloqueo.

    Caso real: `WOT-2026-026u` declara
    `- [028a SATISFECHA 2026-07-21: archivada ...]`. El `-` dice "sin
    dependencia" y la prosa es la traza de una dependencia YA satisfecha, que se
    conserva a proposito. Extraer un id de ahi seria inventar un bloqueo que la
    fila declara resuelto. Por eso el patron exige el PREFIJO COMPLETO
    (`WOT-YYYY-`), no un sufijo suelto como `028a`.
    """
    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0d2a | t | s | pending | - [0D2B SATISFECHA 2026-07-21: archivada] | x | - |\n",
        encoding="utf-8",
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Alta | WOT-2026-0d2b | t | s | completed | - | x | commit:abc1234 |\n",
        encoding="utf-8",
    )
    assert cbc.validate_live_dependencies(tmp_path) == []


def test_049c_namespaced_id_is_not_a_backlog_dependency(tmp_path) -> None:
    """`DEC-WOT-...` es una DECISION, no un ticket de backlog.

    Con `\b` como frontera, `DEC-WOT-2026-047b` se trocea y se extrae el
    `WOT-2026-047b` de dentro: una dependencia INVENTADA que la celda no
    declara. Caso vivo en la fila de `WOT-2026-047c`.
    MUTACION: quitar la frontera izquierda del patron -> ROJO.
    """
    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0e1a | t | s | pending | DEC-WOT-2026-0e1b | x | - |\n",
        encoding="utf-8",
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Alta | WOT-2026-0e1b | t | s | completed | - | x | commit:abc1234 |\n",
        encoding="utf-8",
    )
    assert cbc.validate_live_dependencies(tmp_path) == []


def test_049c_uppercase_suffix_id_is_not_split(tmp_path) -> None:
    """`WOT-2026-STATE-RECON-A` no debe producir el fantasma `WOT-2026-STATE`.

    Con un sufijo permisivo, el patron corta en el primer guion y fabrica un id
    que no existe. Caso vivo en la fila de `WOT-2026-030b`.
    MUTACION: ampliar la clase del sufijo -> ROJO.
    """
    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0e2a | t | s | pending | WOT-2026-STATE-RECON-A | x | - |\n",
        encoding="utf-8",
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Alta | WOT-2026-0e9z | t | s | completed | - | x | commit:abc1234 |\n",
        encoding="utf-8",
    )
    assert cbc.validate_live_dependencies(tmp_path) == []


def test_049c_dangling_dependency_is_reported(tmp_path) -> None:
    """Un id que no existe en NINGUNA superficie congela la fila igual.

    `terminal.get()` daria None y se leeria como "no cerrado": silencio sobre una
    fila igualmente bloqueada. Casos vivos: `044u/044y/044x` -> `WOT-2026-044t`.
    MUTACION: quitar la rama del colgante -> ROJO.
    """
    collab = tmp_path / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(
        "| Alta | WOT-2026-0e3a | t | s | pending | WOT-2026-0e3z | x | - |\n",
        encoding="utf-8",
    )
    (collab / "_archive" / "backlog_done.md").write_text(
        "| Alta | WOT-2026-0e9z | t | s | completed | - | x | commit:abc1234 |\n",
        encoding="utf-8",
    )
    errors = cbc.validate_live_dependencies(tmp_path)
    assert len(errors) == 1
    assert "NO EXISTE" in errors[0]


# ---------------------------------------------------------------------------
# WOT-2026-054b: structural integrity of the Vista rapida table
# ---------------------------------------------------------------------------


def test_054b_orphan_fragment_in_table_region_is_detected(tmp_path) -> None:
    """DoD (b): a line inside the table region that doesn't start with '|'
    but contains '|' is an orphan fragment (decapitated row tail).

    MUTATION: remove the orphan -> VERDE; insert it -> ROJO.
    """
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    content = (
        _HEADER
        + "| Alta | WOT-2026-054a | test | s | pending | - | x | - |\n"
        + "test | s | pending | - | x | - |\n"
        + "| Baja | WOT-2026-054b | test2 | s | pending | - | x | - |\n"
        + "\n"
    )
    (collab / "backlog.md").write_text(content, encoding="utf-8")
    errors = cbc.validate_backlog(collab / "backlog.md")
    orphan_errors = [e for e in errors if "orphan fragment" in e]
    assert len(orphan_errors) == 1, (
        f"Expected exactly 1 orphan fragment error, got {len(orphan_errors)}: {errors}"
    )
    assert "orphan fragment" in orphan_errors[0]


def test_054b_clean_table_no_orphan(tmp_path) -> None:
    """Control positivo: a clean table with no orphan fragments passes."""
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    content = (
        _HEADER
        + "| Alta | WOT-2026-054a | test | s | pending | - | x | - |\n"
        + "| Baja | WOT-2026-054b | test2 | s | pending | - | x | - |\n"
        + "\n"
    )
    (collab / "backlog.md").write_text(content, encoding="utf-8")
    errors = cbc.validate_backlog(collab / "backlog.md")
    orphan_errors = [e for e in errors if "orphan fragment" in e]
    assert orphan_errors == []


def test_054b_bom_at_start_is_handled(tmp_path) -> None:
    """DoD (c): BOM at file start is transparent via utf-8-sig encoding.

    The file is read with utf-8-sig, so the BOM is stripped before parsing.
    If the BOM were NOT stripped, the header check would fail.
    """
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    content = (
        "\ufeff"
        + _HEADER
        + "| Alta | WOT-2026-054a | test | s | pending | - | x | - |\n"
        + "\n"
    )
    (collab / "backlog.md").write_text(content, encoding="utf-8")
    errors = cbc.validate_backlog(collab / "backlog.md")
    bom_errors = [e for e in errors if "BOM" in e.upper() or "header" in e.lower()]
    assert bom_errors == [], f"BOM should be transparent via utf-8-sig, got: {errors}"


def test_054b_regression_decapitated_row_with_orphan(tmp_path) -> None:
    """DoD (e): regression test reproducing the incident backlog.

    A backlog with a decapitated row (missing header columns) AND an orphan
    fragment line should be detected by the guard.
    """
    collab = tmp_path / ".agent" / "collaboration"
    collab.mkdir(parents=True, exist_ok=True)
    content = (
        _HEADER
        + "| Alta | WOT-2026-054a | intact | s | pending | - | x | - |\n"
        + "ticket descripcion scope estado depende de origen reactivation |\n"
        + "| Baja | WOT-2026-054b | also intact | s | pending | - | x | - |\n"
        + "\n"
    )
    (collab / "backlog.md").write_text(content, encoding="utf-8")
    errors = cbc.validate_backlog(collab / "backlog.md")
    orphan_errors = [e for e in errors if "orphan fragment" in e]
    assert len(orphan_errors) == 1, (
        f"Expected 1 orphan fragment in regression test, got {len(orphan_errors)}: {errors}"
    )
