"""Tests for scripts/check_backlog_debt_ownership.py (WOT-2026-068y).

Sibling of tests/unit/test_check_guard_wiring.py's orphan-owner tests
(WOT-2026-026v), same invariant ("a declaration bounds debt only while
SOMEONE is still tracking it") applied to backlog rows instead of guards:

(a) `_strict_live_ticket_ids` extracts ONLY a row's own id from the live
    '## Vista rapida' table -- never a ticket merely CITED in another row's
    prose (the exact laxness `check_guard_wiring._live_owner_tickets` has by
    design, which WOT-2026-068y measured as 111 false-alive owners).
(b) `debt_findings` classifies every `declared_debt` entry: row-liveness
    first (a closed debt row makes its entry moot regardless of owner), then
    owner-liveness (ticket must be alive, BY-DESIGN never fails), then
    baseline membership for still-ownerless entries (grandfathered -> WARN,
    new -> FAIL, the actual barrier).
(c) CONTROL NEGATIVO: a live row with a live owner never fires.
(d) Contract/parity: the strict set is always a SUBSET of the laxer
    `_live_owner_tickets` scrape on the same backlog.
(e) `run_backlog_debt_ownership_check` (prepush_check.py) wires it the same
    way `run_guard_wiring_orphan_check` wires its sibling.
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.check_backlog_debt_ownership as cbdo
import scripts.check_guard_wiring as cgw


_VISTA_HEADER = (
    "## Vista rapida\n\n"
    "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
    "|-----------|--------|--------|-------|--------|------------|--------|--------------|\n"
)


def _destino(tmp_path: Path, rows: str, name: str = "destino") -> Path:
    """repo_destino minimo con una Vista rapida valida (filas 8-celdas)."""
    dest = tmp_path / name
    (dest / ".agent" / "collaboration").mkdir(parents=True, exist_ok=True)
    (dest / ".agent" / "collaboration" / "backlog.md").write_text(
        f"# Backlog\n\n{_VISTA_HEADER}{rows}", encoding="utf-8"
    )
    return dest


_ROW = "| Media | {tid} | {titulo} | motor/x | pending | - | s | - |\n"


# --------------------------------------------------------------------------- #
# (a) _strict_live_ticket_ids: own-row-only extraction
# --------------------------------------------------------------------------- #


def test_strict_extractor_reads_own_row_ids(tmp_path):
    dest = _destino(
        tmp_path,
        _ROW.format(tid="WOT-2026-900a", titulo="x")
        + _ROW.format(tid="WOT-2026-900b", titulo="y"),
    )
    live, err = cbdo._strict_live_ticket_ids(dest)
    assert err is None
    assert live == {"WOT-2026-900a", "WOT-2026-900b"}


def test_strict_extractor_ignores_prose_only_citations(tmp_path):
    """ANTI-FALSE-POSITIVE: a ticket named only in ANOTHER row's prose (never
    as its own row) must NOT count as live -- the exact laxness measured in
    `_live_owner_tickets` (111 false-alive owners, WOT-2026-068y)."""
    dest = _destino(
        tmp_path,
        _ROW.format(
            tid="WOT-2026-900a",
            titulo="cites WOT-2026-900b-archived in prose, never its own row",
        ),
    )
    live, err = cbdo._strict_live_ticket_ids(dest)
    assert err is None
    assert live == {"WOT-2026-900a"}
    assert "WOT-2026-900b" not in live


def test_strict_extractor_skips_missing_backlog(tmp_path):
    dest = tmp_path / "empty"
    (dest / ".agent" / "collaboration").mkdir(parents=True)
    live, err = cbdo._strict_live_ticket_ids(dest)
    assert live is None
    assert "cannot read" in err


def test_strict_extractor_refuses_non_utf8(tmp_path):
    dest = tmp_path / "bad_encoding"
    (dest / ".agent" / "collaboration").mkdir(parents=True)
    backlog = dest / ".agent" / "collaboration" / "backlog.md"
    backlog.write_bytes("WOT-2026-900a".encode("utf-16"))
    live, err = cbdo._strict_live_ticket_ids(dest)
    assert live is None
    assert "not valid UTF-8" in err


def test_strict_extractor_skips_when_no_canonical_id_found(tmp_path):
    dest = _destino(tmp_path, "")
    live, err = cbdo._strict_live_ticket_ids(dest)
    assert live is None
    assert "no canonical ticket id" in err


# --------------------------------------------------------------------------- #
# (d) contract/parity: strict is always a SUBSET of the laxer scrape
# --------------------------------------------------------------------------- #


def test_strict_set_is_subset_of_laxer_live_owner_tickets(tmp_path):
    dest = _destino(
        tmp_path,
        _ROW.format(tid="WOT-2026-900a", titulo="x")
        + _ROW.format(tid="WOT-2026-900b", titulo="cites WOT-2026-777z too"),
    )
    content = (dest / ".agent" / "collaboration" / "backlog.md").read_text(
        encoding="utf-8"
    )
    strict, err = cbdo._strict_live_ticket_ids(dest)
    laxer = set(cgw._TICKET_ANYWHERE.findall(content))
    assert err is None
    assert strict <= laxer
    # the laxer scrape also catches the prose-only citation; strict must not
    assert "WOT-2026-777z" in laxer
    assert "WOT-2026-777z" not in strict


# --------------------------------------------------------------------------- #
# (b)(c) debt_findings: row-liveness, owner-liveness, baseline membership
# --------------------------------------------------------------------------- #


def test_row_with_dead_owner_reports():
    """DoD(g): fila con deuda y dueno muerto -> reporta."""
    policy = {"WOT-2026-061a": "WOT-2026-023t"}
    live = {"WOT-2026-061a"}  # the debt row is live; the owner is NOT
    fails, warns = cbdo.debt_findings(policy, baseline=[], live=live)
    assert any("WOT-2026-061a" in f and "archived" in f for f in fails)
    assert warns == []


def test_row_with_live_owner_is_silent():
    """DoD(g): misma con dueno vivo -> silencio."""
    policy = {"WOT-2026-061a": "WOT-2026-023t"}
    live = {"WOT-2026-061a", "WOT-2026-023t"}
    fails, warns = cbdo.debt_findings(policy, baseline=[], live=live)
    assert fails == []
    assert warns == []


def test_empty_policy_is_silent():
    """DoD(g): cola sin deuda declarada -> silencio."""
    fails, warns = cbdo.debt_findings({}, baseline=[], live={"WOT-2026-061a"})
    assert fails == []
    assert warns == []


def test_baseline_entry_whose_row_archived_fails():
    """DoD(g): entrada de baseline cuya fila se archivo -> FALLA.

    Row-liveness is checked BEFORE owner/baseline -- a closed debt row makes
    the whole entry moot regardless of baseline membership.
    """
    policy = {"WOT-2026-061a": ""}
    fails, warns = cbdo.debt_findings(
        policy,
        baseline=["WOT-2026-061a"],
        live=set(),  # the row itself is archived
    )
    assert any("WOT-2026-061a" in f and "no longer live" in f for f in fails)
    assert warns == []


def test_by_design_owner_never_fails_regardless_of_liveness():
    policy = {"WOT-2026-061a": "BY-DESIGN: circular por diseno"}
    fails, warns = cbdo.debt_findings(policy, baseline=[], live={"WOT-2026-061a"})
    assert fails == []
    assert warns == []


def test_ownerless_in_baseline_warns_not_fails():
    policy = {"WOT-2026-061a": ""}
    fails, warns = cbdo.debt_findings(
        policy, baseline=["WOT-2026-061a"], live={"WOT-2026-061a"}
    )
    assert fails == []
    assert any("WOT-2026-061a" in w and "grandfathered" in w for w in warns)


def test_ownerless_not_in_baseline_fails():
    """The actual barrier: NEW undeclared debt, never grandfathered."""
    policy = {"WOT-2026-061a": ""}
    fails, warns = cbdo.debt_findings(policy, baseline=[], live={"WOT-2026-061a"})
    assert any(
        "WOT-2026-061a" in f and "NOT in the frozen baseline" in f for f in fails
    )
    assert warns == []


def test_mutation_row_liveness_checked_before_owner_check():
    """Mutation-verify: if row-liveness were NOT checked first (or at all), an
    archived debt row with a dead owner would report the WRONG reason (owner
    dead) instead of the right one (row itself archived) -- or, worse, an
    archived row with NO owner declared would silently fall into the
    baseline/ownerless branch instead of failing as stale. Assert the actual
    message names the row, not the owner, proving the order is real."""
    policy = {"WOT-2026-061a": "WOT-2026-023t"}  # owner ALSO happens to be dead
    fails, _warns = cbdo.debt_findings(policy, baseline=[], live=set())
    assert len(fails) == 1
    assert "no longer live" in fails[0], (
        "row-liveness must short-circuit BEFORE the owner check is reached"
    )
    assert "WOT-2026-023t" not in fails[0]


# --------------------------------------------------------------------------- #
# _load_debt_policy / _load_debt_baseline: real I/O, default-empty fallback
# --------------------------------------------------------------------------- #


def test_load_debt_policy_reads_the_real_registry():
    policy = cbdo._load_debt_policy()
    assert isinstance(policy, dict)


def test_load_debt_policy_missing_file_is_empty(tmp_path):
    assert cbdo._load_debt_policy(tmp_path / "nope.yaml") == {}


def test_load_debt_baseline_reads_the_real_fixture():
    baseline = cbdo._load_debt_baseline()
    assert isinstance(baseline, list)


def test_load_debt_baseline_missing_file_is_empty(tmp_path):
    assert cbdo._load_debt_baseline(tmp_path / "nope.yaml") == []


def test_real_registry_and_baseline_ship_empty():
    """DoD-explicit NON-GOAL: the registry and baseline ship EMPTY -- population
    is a separate, deliberate triage step, never auto-detected from prose."""
    assert cbdo._load_debt_policy() == {}
    assert cbdo._load_debt_baseline() == []


# --------------------------------------------------------------------------- #
# (e) prepush_check.py wiring
# --------------------------------------------------------------------------- #


def test_prepush_wiring_skips_without_resolvable_destino(tmp_path):
    import scripts.prepush_check as pc

    result = pc.run_backlog_debt_ownership_check(tmp_path / "nonexistent")
    assert result.passed is True
    assert result.is_blocking is False
    assert "SKIP" in result.output


def test_prepush_wiring_passes_clean_destino(tmp_path, monkeypatch):
    import scripts.prepush_check as pc

    dest = _destino(tmp_path, _ROW.format(tid="WOT-2026-900a", titulo="x"))
    monkeypatch.setattr(cbdo, "_load_debt_policy", lambda *a, **k: {})
    result = pc.run_backlog_debt_ownership_check(dest)
    assert result.passed is True
    assert result.is_blocking is False


def test_prepush_wiring_blocks_on_new_ownerless_debt(tmp_path, monkeypatch):
    import scripts.prepush_check as pc

    dest = _destino(tmp_path, _ROW.format(tid="WOT-2026-900a", titulo="x"))
    monkeypatch.setattr(
        cbdo, "_load_debt_policy", lambda *a, **k: {"WOT-2026-900a": ""}
    )
    monkeypatch.setattr(cbdo, "_load_debt_baseline", lambda *a, **k: [])
    result = pc.run_backlog_debt_ownership_check(dest)
    assert result.passed is False
    assert result.is_blocking is True
    assert "WOT-2026-900a" in result.output


def test_prepush_wiring_warns_only_for_baseline_entry(tmp_path, monkeypatch):
    import scripts.prepush_check as pc

    dest = _destino(tmp_path, _ROW.format(tid="WOT-2026-900a", titulo="x"))
    monkeypatch.setattr(
        cbdo, "_load_debt_policy", lambda *a, **k: {"WOT-2026-900a": ""}
    )
    monkeypatch.setattr(cbdo, "_load_debt_baseline", lambda *a, **k: ["WOT-2026-900a"])
    result = pc.run_backlog_debt_ownership_check(dest)
    assert result.passed is True
    assert result.is_blocking is False
    assert "grandfathered" in result.output


def test_prepush_wiring_is_silent_against_the_real_empty_registry(tmp_path):
    """Against the REAL (shipped, empty) registry+baseline, the check must be
    a no-op -- proves shipping empty does not accidentally block anything."""
    import scripts.prepush_check as pc

    dest = _destino(tmp_path, _ROW.format(tid="WOT-2026-900a", titulo="x"))
    result = pc.run_backlog_debt_ownership_check(dest)
    assert result.passed is True
    assert result.is_blocking is False
    assert "no declared debt registered" in result.output
