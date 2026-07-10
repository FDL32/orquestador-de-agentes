"""Tests for scripts/preflight_codeonly_pipeline.py warnings taxonomy (WOT-2026-021u).

Covers `classify_warnings`: raw `validate --json` warnings (a dict keyed by CATEGORY --
ticket_prose/bus_drift/invariants) are split into accepted_advisories vs
actionable_warnings. The load-bearing rules (each with a mutation that a test catches):
  - bus_drift/invariants -> accepted ONLY if code_only (a destination with a broken bus
    is NOT advisory);
  - ticket_prose [TP-PROSE-*] -> accepted ONLY if the work_plan is TERMINAL;
  - [TP-FATAL-01] -> ALWAYS actionable (a missing-work_plan signal is never advisory);
  - unknown category / unparseable code -> actionable (fail-closed).
The counts are always derived from the classification, never hardcoded.
"""

from __future__ import annotations

import sys
from pathlib import Path


# scripts/ is not a package: insert it on sys.path as the script itself does.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import preflight_codeonly_pipeline as pcp  # noqa: E402


# The exact 8-warning shape that `validate --json` emits on the motor with a
# COMPLETED work_plan (5 ticket_prose + 1 bus_drift + 2 invariants).
_REAL_WARNINGS = {
    "ticket_prose": [
        "[TP-PROSE-04] extremos-lazy: enumera los elementos concretos",
        "[TP-PROSE-04] extremos-lazy: enumera los elementos concretos",
        "[TP-PROSE-04] extremos-lazy: enumera los elementos concretos",
        "[TP-PROSE-06] non-goals-ausentes: anade una seccion Non-goals",
        "[TP-PROSE-10] decision-arquitectonica-ausente: anade una seccion",
    ],
    "bus_drift": ["No STATE_CHANGED event found in bus for ticket WOT-2026-021i"],
    "invariants": [
        "Cannot verify BUILDER_EXIT for ticket WOT-2026-021i in state COMPLETED",
        "Cannot verify STATE_CHANGED for ticket WOT-2026-021i",
    ],
}

_WP_COMPLETED = (
    "# Plan\n\n## Metadata\n- **ID:** WOT-2026-021i\n- **Estado:** COMPLETED\n"
)
_WP_IN_PROGRESS = (
    "# Plan\n\n## Metadata\n- **ID:** WOT-2026-021i\n- **Estado:** IN_PROGRESS\n"
)


def _counts(result):
    return len(result["accepted_advisories"]), len(result["actionable_warnings"])


# --------------------------------------------------------------------------- #
# Fixture 1: code-only + work_plan COMPLETED + bus absent + TP-PROSE -> all accepted
# --------------------------------------------------------------------------- #
def test_code_only_terminal_plan_all_accepted():
    result = pcp.classify_warnings(
        _REAL_WARNINGS, code_only=True, work_plan_content=_WP_COMPLETED
    )
    accepted, actionable = _counts(result)
    # count is DERIVED from the input, never hardcoded to 8
    total = sum(len(v) for v in _REAL_WARNINGS.values())
    assert accepted == total
    assert actionable == 0
    # every input string is classified into exactly one bucket
    assert accepted + actionable == total


# --------------------------------------------------------------------------- #
# Fixture 2: TP-PROSE on a NON-terminal (IN_PROGRESS) plan -> prose is actionable
# (bus/invariants stay accepted because code_only is still True)
# --------------------------------------------------------------------------- #
def test_prose_on_active_plan_is_actionable():
    result = pcp.classify_warnings(
        _REAL_WARNINGS, code_only=True, work_plan_content=_WP_IN_PROGRESS
    )
    accepted, actionable = _counts(result)
    # 3 bus/invariants accepted; 5 ticket_prose now actionable
    assert actionable == 5
    assert accepted == 3
    assert all("TP-PROSE" in w for w in result["actionable_warnings"])


# --------------------------------------------------------------------------- #
# Fixture 3: TP-FATAL-01 (missing work_plan) -> ALWAYS actionable, never accepted
# --------------------------------------------------------------------------- #
def test_tp_fatal_is_always_actionable():
    warnings = {
        "ticket_prose": [
            "[TP-FATAL-01] work-plan-not-found: asegurate de que work_plan.md existe"
        ],
        "bus_drift": ["No active ticket found for bus drift check"],
        "invariants": ["No active plan for invariant check"],
    }
    # even code_only=True and no work_plan: the FATAL prose must be actionable
    result = pcp.classify_warnings(warnings, code_only=True, work_plan_content=None)
    assert any("TP-FATAL-01" in w for w in result["actionable_warnings"])
    assert not any("TP-FATAL-01" in w for w in result["accepted_advisories"])


def test_tp_fatal_actionable_even_when_plan_is_terminal():
    # ISOLATES the `code == "TP-FATAL-01"` special-case: with a TERMINAL work_plan,
    # a plain TP-PROSE would be accepted, so if the FATAL special-case were removed
    # TP-FATAL-01 would wrongly fall into accepted via the terminal branch. This
    # fixture kills that mutation (the chain meta-audit caught that the
    # work_plan=None fixture alone did NOT -- FATAL fell to actionable via the
    # non-terminal `else`, masking the special-case removal).
    warnings = {
        "ticket_prose": [
            "[TP-FATAL-01] work-plan-not-found: asegurate de que work_plan.md existe"
        ]
    }
    result = pcp.classify_warnings(
        warnings, code_only=True, work_plan_content=_WP_COMPLETED
    )
    assert any("TP-FATAL-01" in w for w in result["actionable_warnings"])
    assert not any("TP-FATAL-01" in w for w in result["accepted_advisories"])


# --------------------------------------------------------------------------- #
# Fixture 4 (synthetic N2): code_only False (destination with a broken bus) ->
# bus_drift/invariants are actionable. In THIS preflight is_motor_code_only is
# always True, so this is a unit test of the classifier LOGIC, not a real flow.
# --------------------------------------------------------------------------- #
def test_bus_warnings_actionable_when_not_code_only():
    result = pcp.classify_warnings(
        _REAL_WARNINGS, code_only=False, work_plan_content=_WP_COMPLETED
    )
    # bus_drift + invariants (3) now actionable; TP-PROSE (5) still accepted (terminal)
    assert all(
        w in result["actionable_warnings"]
        for w in _REAL_WARNINGS["bus_drift"] + _REAL_WARNINGS["invariants"]
    )
    assert len(result["actionable_warnings"]) == 3
    assert len(result["accepted_advisories"]) == 5


# --------------------------------------------------------------------------- #
# Fail-closed: an unknown category is never silently accepted
# --------------------------------------------------------------------------- #
def test_unknown_category_is_actionable():
    warnings = {"deliverable_type": ["some new validator warning we do not know"]}
    result = pcp.classify_warnings(
        warnings, code_only=True, work_plan_content=_WP_COMPLETED
    )
    assert result["accepted_advisories"] == []
    assert len(result["actionable_warnings"]) == 1


# --------------------------------------------------------------------------- #
# No work_plan content -> prose cannot be terminal -> TP-PROSE actionable
# (guards the `work_plan_content is not None` half of plan_is_terminal)
# --------------------------------------------------------------------------- #
def test_prose_actionable_when_no_work_plan_content():
    warnings = {"ticket_prose": ["[TP-PROSE-04] extremos-lazy: ..."]}
    result = pcp.classify_warnings(warnings, code_only=True, work_plan_content=None)
    assert len(result["actionable_warnings"]) == 1
    assert result["accepted_advisories"] == []


# --------------------------------------------------------------------------- #
# ticket_prose WITHOUT a [TP-...] prefix (code is None) -> actionable, never
# silently accepted. Guards the fail-closed `or code is None` branch even when
# the work_plan is terminal (so the terminal path cannot swallow it).
# --------------------------------------------------------------------------- #
def test_prose_without_tp_prefix_is_actionable():
    warnings = {"ticket_prose": ["malformed prose warning with no TP code prefix"]}
    result = pcp.classify_warnings(
        warnings, code_only=True, work_plan_content=_WP_COMPLETED
    )
    assert len(result["actionable_warnings"]) == 1
    assert result["accepted_advisories"] == []


# --------------------------------------------------------------------------- #
# is_completed_plan (extracted to a public function in validate_ticket_prose)
# --------------------------------------------------------------------------- #
def test_is_completed_plan_public_helper():
    from validate_ticket_prose import is_completed_plan

    assert is_completed_plan(_WP_COMPLETED) is True
    assert is_completed_plan(_WP_IN_PROGRESS) is False
    assert is_completed_plan("no metadata here") is False
