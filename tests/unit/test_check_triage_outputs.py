"""Tests de scripts/check_triage_outputs.py (WOT-2026-071b).

Fixtures hermeticos en `tmp_path`: NO se tocan los reportes reales del
workspace. El guard invoca el `validate_batch_dag.py` y el
`check_encoding_guard.py` REALES (resueltos junto al propio guard), asi que la
cadena que se ejercita es la productiva, no un stub.

TP Check:
- T1/T2 pinnean el ROJO y el VERDE (par ausente de `groups` -> falla; par
  canonico valido -> exit 0 con el recibo).
- T3 pinnea los DIENTES PROPIOS del guard: un DAG /v1 que `validate_batch_dag`
  ACEPTA pero con grupo sin `surface_scan` -> el guard falla. Fixture
  otherwise-valid: la mutacion de la rama (e) es la UNICA explicacion del rojo.
- T7-T9 pinnean el localizador (regex anclada, variante batch, recencia y
  desempate no-batch) sin los cuales una regresion del localizador sobrevive.
- T10-T12 pinnean los caminos de fallo de (a)/(c)/(d).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_triage_outputs", _ROOT / "scripts" / "check_triage_outputs.py"
)
cto = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(cto)

_VALIDATOR = _ROOT / "scripts" / "validate_batch_dag.py"


def _valid_dag(*, surface_scan: bool = True) -> dict:
    """DAG /v1 que `validate_batch_dag` acepta (grupo con todas sus claves)."""
    group: dict = {
        "id": "G-1",
        "tickets": ["WOT-2026-999a"],
        "depends_on_groups": [],
        "blocks_groups": [],
        "shared_surfaces": [],
        "class": "S",
        "autonomy_mode": "autonomous",
        "common_gate": "python scripts/run_pytest_safe.py --level all",
        "recovery_owner_stage": "BUILDER",
        "max_recovery_attempts": 1,
    }
    if surface_scan:
        group["surface_scan"] = {"executed": True, "coverage": "1/1", "method": "probe"}
    return {
        "schema": "autonomous-batch-dag/v1",
        "generated_at": "2026-01-01T12:00:00+00:00",
        "state_at_triage": {"motor": "a" * 40, "workspace": "b" * 40, "dirty": "0"},
        "groups": [group],
        "stop_policy": {
            "hard_stop_causes": [],
            "recoverable_causes": [],
            "max_unclassified_stops": 0,
        },
        "budget": {"max_tickets_closed": 1, "max_group_recoveries": 0},
    }


def _reports(tmp_path: Path) -> Path:
    reports = tmp_path / "orchestrator_pipeline" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    return reports


def _write_pair(reports: Path, name: str, data: dict, md: str = "narrative\n") -> Path:
    json_path = reports / name
    json_path.write_text(json.dumps(data), encoding="utf-8")
    json_path.with_suffix(".md").write_text(md, encoding="utf-8")
    return json_path


def _validator_rc(json_path: Path) -> int:
    proc = subprocess.run(
        [sys.executable, str(_VALIDATOR), str(json_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.returncode


def test_t1_json_without_groups_fails(tmp_path: Path, capsys) -> None:
    data = _valid_dag()
    del data["groups"]
    reports = _reports(tmp_path)
    json_path = _write_pair(reports, "backlog_triage_20260101-120000.json", data)

    rc = cto.check_triage_outputs(tmp_path)
    captured = capsys.readouterr()
    assert rc != 0
    assert json_path.name in captured.err
    assert "FAIL" in captured.err


def test_t2_valid_pair_ok_names_json(tmp_path: Path, capsys) -> None:
    reports = _reports(tmp_path)
    json_path = _write_pair(
        reports, "backlog_triage_20260101-120000.json", _valid_dag()
    )

    rc = cto.check_triage_outputs(tmp_path)
    captured = capsys.readouterr()
    assert rc == 0
    assert "ficheros auditados: 2" in captured.out
    assert json_path.name in captured.out


def test_t3_group_without_surface_scan_fails_isolated(tmp_path: Path, capsys) -> None:
    reports = _reports(tmp_path)
    json_path = _write_pair(
        reports,
        "backlog_triage_20260101-120000.json",
        _valid_dag(surface_scan=False),
    )
    # Aislamiento: el validador del CONSUMIDOR acepta el fixture (v1 no exige
    # surface_scan); la unica rama que puede producir el rojo es (e) del guard.
    assert _validator_rc(json_path) == 0

    rc = cto.check_triage_outputs(tmp_path)
    captured = capsys.readouterr()
    assert rc != 0
    assert "surface_scan" in captured.err


def test_t4_no_artifact_skip_then_require_fails(tmp_path: Path, capsys) -> None:
    reports = _reports(tmp_path)
    (reports / "backlog_triage_output.json").write_text("{}", encoding="utf-8")

    rc_skip = cto.check_triage_outputs(tmp_path, require_artifact=False)
    out = capsys.readouterr()
    assert rc_skip == 0
    assert "SKIP" in out.out

    rc_require = cto.check_triage_outputs(tmp_path, require_artifact=True)
    err = capsys.readouterr()
    assert rc_require != 0
    assert "backlog_triage_output.json" in err.err


def test_t5_invalid_evidence_label_fails(tmp_path: Path) -> None:
    data = _valid_dag()
    data["tickets"] = [
        {
            "id": "WOT-2026-999a",
            "classification": "APTO_AUTONOMO",
            "evidence_label": "NO_VERIFICADO",
            "artifact": None,
        }
    ]
    reports = _reports(tmp_path)
    _write_pair(reports, "backlog_triage_20260101-120000.json", data)

    rc = cto.check_triage_outputs(tmp_path)
    assert rc != 0


def test_t6_mojibake_md_fails(tmp_path: Path, capsys) -> None:
    reports = _reports(tmp_path)
    _write_pair(
        reports,
        "backlog_triage_20260101-120000.json",
        _valid_dag(),
        md="informe con mojibake: caf\u00c3\u00a9\n",
    )

    rc = cto.check_triage_outputs(tmp_path)
    captured = capsys.readouterr()
    assert rc != 0
    assert "encoding" in captured.err.lower()


def test_t7_decoys_excluded_picks_dag(tmp_path: Path) -> None:
    reports = _reports(tmp_path)
    (reports / "backlog_triage_20260101-120000.json").write_text("{}", encoding="utf-8")
    decoys = [
        "backlog_triage_20260101-120000_priority_score_evidence.json",
        "backlog_triage_20260101-120000_corrected_v2.json",
        "backlog_triage_output.20260101-120000.json",
        "backlog_triage_20260101-120000.PRESERVED.json",
        "backlog_triage_20260101.json",
    ]
    for name in decoys:
        (reports / name).write_text("{}", encoding="utf-8")

    located, others = cto.locate_latest_triage(reports)
    assert located is not None
    assert located.name == "backlog_triage_20260101-120000.json"
    for name in decoys:
        assert name in others


def test_t8_batch_variant_accepted(tmp_path: Path, capsys) -> None:
    reports = _reports(tmp_path)
    json_path = _write_pair(
        reports, "backlog_triage_batch_20260101-120000.json", _valid_dag()
    )

    located, _others = cto.locate_latest_triage(reports)
    assert located == json_path

    rc = cto.check_triage_outputs(tmp_path)
    assert rc == 0
    assert json_path.name in capsys.readouterr().out


def test_t9_recency_ordering(tmp_path: Path) -> None:
    reports = _reports(tmp_path)
    (reports / "backlog_triage_20260101-120000.json").write_text("{}", encoding="utf-8")
    (reports / "backlog_triage_20260102-000000.json").write_text("{}", encoding="utf-8")

    located, _others = cto.locate_latest_triage(reports)
    assert located is not None
    assert located.name == "backlog_triage_20260102-000000.json"


def test_t9b_tie_prefers_non_batch(tmp_path: Path) -> None:
    reports = _reports(tmp_path)
    (reports / "backlog_triage_20260101-120000.json").write_text("{}", encoding="utf-8")
    (reports / "backlog_triage_batch_20260101-120000.json").write_text(
        "{}", encoding="utf-8"
    )

    located, _others = cto.locate_latest_triage(reports)
    assert located is not None
    assert located.name == "backlog_triage_20260101-120000.json"


def test_t10_missing_md_fails(tmp_path: Path, capsys) -> None:
    reports = _reports(tmp_path)
    (reports / "backlog_triage_20260101-120000.json").write_text(
        json.dumps(_valid_dag()), encoding="utf-8"
    )

    rc = cto.check_triage_outputs(tmp_path)
    captured = capsys.readouterr()
    assert rc != 0
    assert "par incompleto" in captured.err


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda d: d.__setitem__("generated_at", "no-es-fecha"),
            id="generated_at",
        ),
        pytest.param(lambda d: d.pop("state_at_triage"), id="state_at_triage"),
        pytest.param(lambda d: d.pop("stop_policy"), id="stop_policy"),
        pytest.param(lambda d: d.pop("budget"), id="budget"),
    ],
)
def test_t11_top_level_keys_fail(tmp_path: Path, mutate) -> None:
    data = _valid_dag()
    mutate(data)
    reports = _reports(tmp_path)
    json_path = _write_pair(reports, "backlog_triage_20260101-120000.json", data)
    # El validador del consumidor NO mira estas claves: el fixture le pasa.
    assert _validator_rc(json_path) == 0

    rc = cto.check_triage_outputs(tmp_path)
    assert rc != 0


def test_t12_roster_without_artifact_fails_isolated(tmp_path: Path, capsys) -> None:
    data = _valid_dag()
    data["tickets"] = [
        {
            "id": "WOT-2026-999a",
            "classification": "APTO_AUTONOMO",
            "evidence_label": "VERIFICADO",
        }
    ]
    reports = _reports(tmp_path)
    json_path = _write_pair(reports, "backlog_triage_20260101-120000.json", data)
    # Aislamiento: el validador acepta (no mira `artifact`); la rama (d) del
    # guard es la unica que puede producir el rojo.
    assert _validator_rc(json_path) == 0

    rc = cto.check_triage_outputs(tmp_path)
    captured = capsys.readouterr()
    assert rc != 0
    assert "artifact" in captured.err
