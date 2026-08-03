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
    "| Media | WOT-2026-0P9Z | resumen. ver ficha `### WOT-2026-0P9Z` abajo. "
    "| motor/x | pending | - | origen | - |"
)


def test_043t_pointer_with_reachable_ficha_passes() -> None:
    """CONTROL POSITIVO: fila que delega + ficha presente -> sin errores."""
    content = "\n".join([_PTR_ROW, "", "### WOT-2026-0P9Z - resumen"])
    assert cbc._check_ficha_pointers(content, [_PTR_ROW]) == []


def test_043t_dangling_pointer_is_an_error() -> None:
    """El defecto: la fila delega en una ficha que NO existe.

    Mutacion alcanzable: retirar la llamada a _check_ficha_pointers de
    validate_backlog (o devolver [] siempre) -> este test se pone ROJO.
    """
    errors = cbc._check_ficha_pointers(_PTR_ROW, [_PTR_ROW])
    assert len(errors) == 1
    assert "WOT-2026-0P9Z" in errors[0]
    assert "dangling" in errors[0]


def test_043t_duplicate_ficha_is_an_error() -> None:
    """Dos fichas con el mismo id: el puntero no puede decir cual manda."""
    content = "\n".join([_PTR_ROW, "### WOT-2026-0P9Z - a", "### WOT-2026-0P9Z - b"])
    errors = cbc._check_ficha_pointers(content, [_PTR_ROW])
    assert len(errors) == 1
    assert "2 fichas" in errors[0]


def test_043t_row_without_pointer_needs_no_ficha() -> None:
    """CONTROL NEGATIVO: una fila autosuficiente no exige ficha.

    Mutacion alcanzable: exigir ficha a TODA fila -> ROJO. Sin este test, el
    guard obligaria a crear 180 fichas vacias para las filas que no delegan.
    """
    row = "| Media | WOT-2026-0Q8Y | todo el criterio aqui | s | pending | - | o | - |"
    assert cbc._check_ficha_pointers(row, [row]) == []


def test_043t_citing_another_tickets_ficha_does_not_claim_own_completeness() -> None:
    """Una fila que MENCIONA la ficha de OTRO ticket no delega la suya.

    Mutacion alcanzable: casar 'ver ficha' sin comprobar que el id citado es el
    de la propia fila -> ROJO (pediria una ficha que esta fila nunca prometio).
    """
    row = (
        "| Media | WOT-2026-0R7X | criterio propio; contexto en ver ficha "
        "`### WOT-2026-0P9Z` | s | pending | - | o | - |"
    )
    assert cbc._check_ficha_pointers(row, [row]) == []
