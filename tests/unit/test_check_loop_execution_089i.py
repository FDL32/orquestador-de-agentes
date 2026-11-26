"""Tests for the non-blocking laboratory-diversity warning (WOT-2026-089i)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_loop_execution as cle  # noqa: E402


def _emitted(nonce: str = "N1", commit: str = "abc") -> dict:
    return {
        "ts": "2026-07-24T10:00:00+00:00",
        "issuer_role": "orchestrator",
        "issuer_backend_key": "BA01",
        "issued_before_ts": "2026-07-24T10:00:00+00:00",
        "commit_sha": commit,
        "loop_id": "L700",
        "challenge_nonce": nonce,
    }


def _round(
    backend_key: str,
    *,
    nonce: str = "N1",
    commit: str = "abc",
    output_chars: int = 20,
) -> dict:
    return {
        "event": "ronda",
        "commit_sha": commit,
        "backend_key": backend_key,
        "challenge_nonce": nonce,
        "ts": "2026-07-24T10:05:00+00:00",
        "output_chars": output_chars,
        "evidencia": "hallazgo",
    }


def _config(labs: dict[str, object]) -> dict:
    return {
        "ensemble_registry": {
            "backend_keys": {key: {"lab": lab} for key, lab in labs.items()}
        }
    }


def _audit_commit(rows, emitted, labs, *, min_distinct=2):
    return cle.audit_commit(
        rows,
        emitted,
        commit_sha="abc",
        min_distinct=min_distinct,
        backend_labs=labs,
    )


def test_backend_labs_from_config_accepts_only_nonempty_string_labs():
    config = _config(
        {
            "BA10": "Lab A",
            "BA11": "",
            "BA12": "   ",
            "BA13": 42,
        }
    )

    assert cle.backend_labs_from_config(config) == {"BA10": "Lab A"}


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"ensemble_registry": {}},
        {"ensemble_registry": {"backend_keys": []}},
        {"ensemble_registry": {"backend_keys": {"BA10": {}}}},
        {"ensemble_registry": {"backend_keys": {"BA10": {"lab": None}}}},
    ],
)
def test_backend_labs_from_config_is_fail_open_for_degenerate_config(config):
    assert cle.backend_labs_from_config(config) == {}


def test_backend_labs_from_config_is_fail_open_when_loading_fails(monkeypatch):
    def fail_to_load():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(cle, "load_motor_config", fail_to_load)

    assert cle.backend_labs_from_config() == {}


def test_lab_warning_is_printed_but_does_not_change_ok_and_clean_verdict_is_legacy(
    capsys,
):
    rows = [_round("BA10"), _round("BA11")]
    emitted = [_emitted()]

    warning = _audit_commit(rows, emitted, {"BA10": "Lab A", "BA11": "Lab A"})
    assert warning["ok"] is True
    assert warning["lab_warnings"] == [
        {
            "nonce": "N1",
            "backends": ["BA10", "BA11"],
            "labs": ["Lab A"],
            "distinct_backends": 2,
            "distinct_labs": 1,
        }
    ]
    cle._print_verdict(warning)
    assert "WARN-LAB" in capsys.readouterr().out

    clean = _audit_commit(rows, emitted, {"BA10": "Lab A", "BA11": "Lab B"})
    assert clean["ok"] is True
    assert "lab_warnings" not in clean
    cle._print_verdict(clean)
    assert "WARN-LAB" not in capsys.readouterr().out


def test_four_backends_in_three_labs_warn_and_four_labs_do_not():
    rows = [_round(key) for key in ("BA10", "BA11", "BA12", "BA13")]
    emitted = [_emitted()]

    three_labs = {
        "BA10": "Lab A",
        "BA11": "Lab A",
        "BA12": "Lab B",
        "BA13": "Lab C",
    }
    warning = _audit_commit(rows, emitted, three_labs, min_distinct=4)
    assert warning["ok"] is True
    assert len(warning["lab_warnings"]) == 1

    four_labs = {key: f"Lab {key}" for key in ("BA10", "BA11", "BA12", "BA13")}
    clean = _audit_commit(rows, emitted, four_labs, min_distinct=4)
    assert clean["ok"] is True
    assert "lab_warnings" not in clean


def test_unknown_backend_keys_are_independent_laboratories():
    rows = [_round("BA11"), _round("BA12")]
    emitted = [_emitted()]

    verdict = _audit_commit(rows, emitted, {"BA10": "Known Lab"})

    assert verdict["ok"] is True
    assert "lab_warnings" not in verdict


def test_lab_warning_evaluates_each_nonce_separately():
    emitted = [_emitted("N1"), _emitted("N2")]
    rows = [
        _round("BA10", nonce="N1"),
        _round("BA11", nonce="N1"),
        _round("BA12", nonce="N2"),
        _round("BA13", nonce="N2"),
    ]
    labs = {
        "BA10": "Lab A",
        "BA11": "Lab A",
        "BA12": "Lab A",
        "BA13": "Lab B",
    }

    warnings = _audit_commit(rows, emitted, labs)["lab_warnings"]

    assert [warning["nonce"] for warning in warnings] == ["N1"]


def test_lab_warning_reuses_issuer_and_silent_round_exclusions():
    emitted = [_emitted()]
    rows = [
        _round("BA01"),
        _round("BA10"),
        _round("BA11"),
        _round("BA12", output_chars=0),
    ]
    labs = {
        "BA01": "Lab A",
        "BA10": "Lab A",
        "BA11": "Lab B",
        "BA12": "Lab A",
    }

    verdict = _audit_commit(rows, emitted, labs)

    assert "lab_warnings" not in verdict


def test_audit_loads_and_propagates_labs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cle, "_read_scorecard", lambda root: ([_round("BA10"), _round("BA11")], "x")
    )
    monkeypatch.setattr(cle, "read_emitted_nonces", lambda root: [_emitted()])
    monkeypatch.setattr(
        cle,
        "load_motor_config",
        lambda: _config({"BA10": "Lab A", "BA11": "Lab A"}),
    )

    verdict = cle.audit(tmp_path, commit_shas=["abc"], min_distinct=2)[0]

    assert verdict["ok"] is True
    assert len(verdict["lab_warnings"]) == 1
