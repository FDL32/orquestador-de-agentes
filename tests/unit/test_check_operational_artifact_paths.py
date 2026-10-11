"""Tests for scripts/check_operational_artifact_paths.py (WOT-2026-054g).

Un artefacto OPERATIVO del destino (orchestrator_pipeline/reports|arranques|
flight_plans) no puede llevar <MOTOR_ROOT>/<DESTINO_ROOT> sin resolver. A
diferencia del guard hermano (check_distribution_agnostic.py, linea a linea),
este mide CONTEO POR FICHERO contra un baseline JSON -- la deuda historica
(121 ficheros, 918 hits) se hereda sin re-escribirla; solo falla lo NUEVO
(fichero ausente del baseline) o lo EMPEORADO (un fichero ya en el baseline
que gana hits por encima de lo declarado).

Cobertura (una idea por test):
  T-SCOPE      : solo las 3 rutas operativas cuentan; fuera de ellas no se mide.
  T-WARN-VACIO : ninguna de las 3 rutas existe -> WARN, exit 0 (nunca ERROR).
  T-NUEVO      : fichero fuera del baseline con hit -> ROJO; resuelto -> VERDE.
  T-EMPEORA    : fichero del baseline sin cambios -> VERDE; con hit NUEVO -> ROJO.
  T-STALE      : entrada de baseline con 0 hits actuales -> AVISO, nunca bloqueante.
  T-NO-UTF8    : bytes invalidos se auditan (decode replace), no se saltan.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_operational_artifact_paths",
    _ROOT / "scripts" / "check_operational_artifact_paths.py",
)
coap = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(coap)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


# ---------------------------------------------------------------- T-SCOPE
def test_scope_only_operational_dirs_count(tmp_path: Path):
    _write(
        tmp_path / "orchestrator_pipeline" / "reports" / "a.md",
        "resolved line only",
    )
    _write(
        tmp_path / "prompts" / "orchestrator_launch_builder.md",
        "command: python x.py --project-root <DESTINO_ROOT>",
    )
    code, out = coap.audit(tmp_path, baseline={})
    assert code == 0
    assert "0 ficheros sin eximir" in "\n".join(out)


# ---------------------------------------------------------------- T-WARN-VACIO
def test_warn_when_no_operational_dir_exists(tmp_path: Path):
    code, out = coap.audit(tmp_path, baseline={})
    assert code == 0
    assert any("WARN" in ln for ln in out)


# ---------------------------------------------------------------- T-NUEVO
def test_new_file_outside_baseline_with_role_fails(tmp_path: Path):
    _write(
        tmp_path / "orchestrator_pipeline" / "reports" / "new.md",
        "command: python x.py --project-root <DESTINO_ROOT>",
    )
    code, out = coap.audit(tmp_path, baseline={})
    assert code == 1
    assert "orchestrator_pipeline/reports/new.md" in "\n".join(out)


def test_new_file_resolved_passes(tmp_path: Path):
    _write(
        tmp_path / "orchestrator_pipeline" / "reports" / "new.md",
        r"command: python x.py --project-root C:\real\path",
    )
    code, _out = coap.audit(tmp_path, baseline={})
    assert code == 0


# ---------------------------------------------------------------- T-EMPEORA
def test_baseline_file_unchanged_passes(tmp_path: Path):
    _write(
        tmp_path / "orchestrator_pipeline" / "reports" / "legacy.md",
        "line 1\ncommand: python x.py --project-root <DESTINO_ROOT>\n",
    )
    baseline = {"orchestrator_pipeline/reports/legacy.md": 1}
    code, out = coap.audit(tmp_path, baseline=baseline)
    assert code == 0
    assert "0 ficheros sin eximir" in "\n".join(out)


def test_baseline_file_with_new_hit_added_fails(tmp_path: Path):
    _write(
        tmp_path / "orchestrator_pipeline" / "reports" / "legacy.md",
        "line 1\n"
        "command: python x.py --project-root <DESTINO_ROOT>\n"
        "extra: python y.py --motor-root <MOTOR_ROOT>\n",
    )
    baseline = {"orchestrator_pipeline/reports/legacy.md": 1}
    code, out = coap.audit(tmp_path, baseline=baseline)
    assert code == 1
    joined = "\n".join(out)
    assert "legacy.md: 2 hits (baseline declara 1)" in joined


# ---------------------------------------------------------------- T-STALE
def test_stale_baseline_entry_is_warned_not_blocking(tmp_path: Path):
    _write(
        tmp_path / "orchestrator_pipeline" / "reports" / "cleaned.md",
        "no roles here anymore\n",
    )
    baseline = {"orchestrator_pipeline/reports/cleaned.md": 3}
    code, out = coap.audit(tmp_path, baseline=baseline)
    assert code == 0
    joined = "\n".join(out)
    assert "STALE" in joined
    assert "orchestrator_pipeline/reports/cleaned.md" in joined


# ---------------------------------------------------------------- T-NO-UTF8
def test_non_utf8_file_is_audited_not_skipped(tmp_path: Path):
    p = tmp_path / "orchestrator_pipeline" / "reports" / "bin.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xff\xfe<DESTINO_ROOT> garbage bytes")
    _files, counts = coap.scan(tmp_path)
    assert "orchestrator_pipeline/reports/bin.md" in counts


# ---------------------------------------------------------------- misc
def test_flight_plans_and_arranques_also_scoped(tmp_path: Path):
    _write(
        tmp_path / "orchestrator_pipeline" / "arranques" / "ARRANQUE_x.md",
        "root: <MOTOR_ROOT>",
    )
    _write(
        tmp_path / "orchestrator_pipeline" / "flight_plans" / "FP-x.json",
        '{"root": "<DESTINO_ROOT>"}',
    )
    code, out = coap.audit(tmp_path, baseline={})
    assert code == 1
    joined = "\n".join(out)
    assert "arranques/ARRANQUE_x.md" in joined
    assert "flight_plans/FP-x.json" in joined


@pytest.mark.parametrize(
    "load_path_exists",
    [True, False],
)
def test_load_baseline_missing_file_returns_empty(
    tmp_path: Path, load_path_exists: bool
):
    p = tmp_path / "baseline.json"
    if load_path_exists:
        p.write_text('{"a": 1}', encoding="utf-8")
        assert coap.load_baseline(p) == {"a": 1}
    else:
        assert coap.load_baseline(p) == {}
