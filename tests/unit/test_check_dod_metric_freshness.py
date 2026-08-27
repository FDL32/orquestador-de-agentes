"""WOT-2026-034c: teeth for the DoD metric-freshness detector.

The defect this guard exists for was MEASURED 2026-07-14: of the backlog fichas
carrying measurements embedded in their DoD, the 4 audited had their number
ALREADY obsolete (one demanded '243 auditorias' when there were 342; another
'177 filas' when 4 remained). A number pinned as a criterion expires in silence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.check_dod_metric_freshness import (
    EXIT_OK,
    EXIT_SELF_FAIL,
    EXIT_VIOLATIONS,
    find_violations,
    main,
)


HEADER = (
    "## Vista rapida\n\n"
    "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def _backlog(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "backlog.md"
    path.write_text(HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


def _row(ticket: str, notas: str) -> str:
    """A live Prioridad-led row; the claim under test rides in Origen."""
    return f"| Alta | {ticket} | titulo | motor | pending | - | {notas} | none |"


# --- ROJO: the defect the ticket names ------------------------------------


def test_unanchored_figure_is_a_violation():
    """A bare figure+noun in a live row is a criterion that expires."""
    rows = [_row("WOT-2026-900a", "quedan 177 filas por drenar")]
    violations = find_violations(rows)
    assert len(violations) == 1
    assert "WOT-2026-900a" in violations[0]
    assert "177 filas" in violations[0]


def test_violation_names_the_guilty_row_and_exits_1(tmp_path):
    """rc=1 and the offending ticket is NAMED, not merely counted."""
    backlog = _backlog(tmp_path, _row("WOT-2026-900b", "el censo da 243 entradas"))
    rc = main(["--backlog", str(backlog)])
    assert rc == EXIT_VIOLATIONS


# --- VERDE: the anchors that redeem a figure ------------------------------


def test_medido_date_anchor_redeems_the_figure():
    rows = [_row("WOT-2026-900c", "MEDIDO 2026-07-14: quedan 177 filas")]
    assert find_violations(rows) == []


def test_snapshot_sha_anchor_redeems_the_figure():
    rows = [_row("WOT-2026-900d", "snapshot eca1e16 -- 243 entradas auditadas")]
    assert find_violations(rows) == []


def test_short_sha_under_7_chars_does_not_redeem():
    """A 6-char sha is not the repo's short-sha convention: still a violation."""
    rows = [_row("WOT-2026-900e", "snapshot eca1e1 -- 243 entradas")]
    assert len(find_violations(rows)) == 1


# --- CONTROL NEGATIVO: no figure at all -----------------------------------


def test_row_without_any_figure_is_clean():
    rows = [_row("WOT-2026-900f", "ningun hit sin declarar; invariante puro")]
    assert find_violations(rows) == []


def test_clean_backlog_exits_0(tmp_path):
    backlog = _backlog(tmp_path, _row("WOT-2026-900g", "invariante sin cifras"))
    assert main(["--backlog", str(backlog)]) == EXIT_OK


# --- FALSO POSITIVO MEDIDO (2026-08-27): la cola de un ticket-id ----------


@pytest.mark.parametrize(
    "ticket_id", ["WOT-2026-027s", "WOT-2026-025s", "WOT-2026-020s", "WOT-2026-026s"]
)
def test_ticket_id_tail_is_not_a_measurement(ticket_id):
    r"""`WOT-2026-027s` must not yield the figure token `027s`.

    MEASURED on the live corpus 2026-08-27: 26 of 390 naive matches (6.7%) were
    ticket-id tails via the `\d+\s*s\b` branch. An identifier is never a metric.
    """
    rows = [_row("WOT-2026-901a", f"depende de {ticket_id} y de su cierre")]
    assert find_violations(rows) == []


def test_ticket_id_in_its_own_cell_is_not_a_measurement():
    """The id in the Ticket CELL must not trip the detector either."""
    assert find_violations([_row("WOT-2026-027s", "sin cifras aqui")]) == []


# --- allowlist versionada del historico -----------------------------------


def test_legacy_baseline_silences_only_its_own_ticket(monkeypatch):
    """An allowlisted ticket is silent; a NON-listed one still fires."""
    import scripts.check_dod_metric_freshness as mod

    monkeypatch.setattr(
        mod, "_DOD_METRIC_LEGACY_BASELINE", frozenset({"WOT-2026-902a"})
    )
    assert (
        mod.find_violations([_row("WOT-2026-902a", "quedan 11 hits y 5 filas")]) == []
    )
    assert len(mod.find_violations([_row("WOT-2026-902b", "quedan 5 filas")])) == 1


# --- fail-closed ----------------------------------------------------------


def test_unreadable_backlog_is_self_fail_never_pass_open(tmp_path):
    rc = main(["--backlog", str(tmp_path / "does_not_exist.md")])
    assert rc == EXIT_SELF_FAIL


def test_unparseable_table_is_self_fail_never_pass_open(tmp_path):
    path = tmp_path / "backlog.md"
    path.write_text("# sin Vista rapida\n", encoding="utf-8")
    assert main(["--backlog", str(path)]) == EXIT_SELF_FAIL


# --- el censo historico, anclado como SNAPSHOT FECHADO --------------------


def test_baseline_is_a_dated_census_not_an_empty_mute_button():
    """The allowlist must carry the historical rows, and stay well-formed.

    SNAPSHOT eca1e16 (MEDIDO 2026-08-27): 89 offending live rows of 268. The
    count is asserted as a FLOOR, never an equality -- pinning the exact number
    would make this test the very defect the guard exists to detect
    (a criterion that expires when the corpus moves).
    """
    import scripts.check_dod_metric_freshness as mod

    assert len(mod._DOD_METRIC_LEGACY_BASELINE) >= 80
    for entry in mod._DOD_METRIC_LEGACY_BASELINE:
        assert mod._TICKET_ID_SPAN_RE.fullmatch(entry), (
            f"malformed census entry {entry!r}"
        )


def test_baseline_does_not_silence_a_ticket_outside_it():
    """A ticket NOT in the census still fires: the allowlist is not a global off."""
    import scripts.check_dod_metric_freshness as mod

    row = _row("WOT-2026-999z", "quedan 177 filas por drenar")
    assert mod._row_ticket_id(row) not in mod._DOD_METRIC_LEGACY_BASELINE
    assert len(mod.find_violations([row])) == 1


def test_non_numeric_suffix_id_is_read_from_its_cell():
    """MEASURED 2026-08-27: `WOT-2026-STATE-RECON-A` is a real live row shape."""
    import scripts.check_dod_metric_freshness as mod

    row = "| Media | WOT-2026-STATE-RECON-A | t | motor | pending | - | x | none |"
    assert mod._row_ticket_id(row) == "WOT-2026-STATE-RECON-A"
