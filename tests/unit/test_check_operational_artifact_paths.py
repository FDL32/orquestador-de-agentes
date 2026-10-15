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


# ---------------------------------------------------------------- T-INTEGRITY (WOT-2026-100l)
# Test de integridad del baseline real (no sintetico).
# Carga el baseline canonico desde DISCO via load_baseline() sin argumento,
# verifica >= 190 entradas, 69 claves nuevas de CTL con conteo valido,
# y no-regresion sobre las 121 originales (v2[k] >= v1[k]).
#
# Antes del fix de WOT-2026-100l: FALLA (solo 121 entradas, claves CTL ausentes).
# Despues del fix: PASA (190 entradas, merge max(v1, n) completo).


def test_integrity_of_production_baseline():
    """Baseline canonico: >=190 entradas, 69 nuevas de CTL, no-regresion."""
    v2 = coap.load_baseline()

    # >= 190 entradas (121 originales + 69 nuevas de CTL)
    assert len(v2) >= 190, (
        f"baseline tiene solo {len(v2)} entradas, se esperan >= 190 "
        f"(121 originales + 69 nuevas de CTL)"
    )

    # 69 claves nuevas de CTL presentes con conteo >= 1
    # Claves identificadas en baseline_v2_repro.json (WOT-2026-100l)
    ctl_keys_expected = [
        "orchestrator_pipeline/arranques/ARRANQUE_027u.md",
        "orchestrator_pipeline/arranques/ARRANQUE_batch_20260907c.md",
        "orchestrator_pipeline/arranques/ARRANQUE_continuacion_20260910.md",
        "orchestrator_pipeline/arranques/ARRANQUE_ctl-027e.md",
        "orchestrator_pipeline/arranques/ARRANQUE_ctl-027i.md",
        "orchestrator_pipeline/arranques/ARRANQUE_ctl-027j.md",
        "orchestrator_pipeline/arranques/ARRANQUE_ctl-027p.md",
        "orchestrator_pipeline/arranques/ARRANQUE_hop-027e.md",
        "orchestrator_pipeline/arranques/ARRANQUE_hop-027x.md",
        "orchestrator_pipeline/arranques/ARRANQUE_hop-028a.md",
        "orchestrator_pipeline/arranques/ARRANQUE_hop_027f.md",
        "orchestrator_pipeline/arranques/ARRANQUE_post-cierre-0907.md",
        "orchestrator_pipeline/arranques/ARRANQUE_vuelo_20260907d.md",
        "orchestrator_pipeline/arranques/PROMPT_ARRANQUE_CTL-2026-013z.md",
        "orchestrator_pipeline/arranques/PROMPT_ARRANQUE_CTL-2026-025f.md",
        "orchestrator_pipeline/arranques/PROMPT_ARRANQUE_CTL-2026-025k.md",
        "orchestrator_pipeline/arranques/PROMPT_ARRANQUE_CTL-2026-025p.md",
        "orchestrator_pipeline/arranques/PROMPT_ARRANQUE_CTL-2026-026a.md",
        "orchestrator_pipeline/arranques/PROMPT_ARRANQUE_CTL-2026-027ab.md",
        "orchestrator_pipeline/arranques/PROMPT_BUILDER_CTL-2026-025d.md",
        "orchestrator_pipeline/arranques/PROMPT_BUILDER_CTL-2026-025d_v2.md",
        "orchestrator_pipeline/arranques/PROMPT_BUILDER_CTL-2026-027f.md",
        "orchestrator_pipeline/arranques/PROMPT_BUILDER_CTL-2026-028f.md",
        "orchestrator_pipeline/arranques/PROMPT_MANAGER_habilitar_025d.md",
        "orchestrator_pipeline/arranques/WORK_PLAN_CTL-2026-027y.md",
        "orchestrator_pipeline/arranques/WORK_PLAN_CTL-2026-028f.md",
        "orchestrator_pipeline/reports/CTL-2026-009h/reporte_correccion_ortografica.md",
        "orchestrator_pipeline/reports/PLAN_EJECUCION_VIA_MIXTA.md",
        "orchestrator_pipeline/reports/PROMPT_ARRANQUE_CTL-2026-028g.md",
        "orchestrator_pipeline/reports/PROMPT_ARRANQUE_CTL-2026-028h.md",
        "orchestrator_pipeline/reports/PROPUESTA_20260907_deuda_residual_del_vuelo.md",
        "orchestrator_pipeline/reports/PROPUESTA_CTL-2026-027q.md",
        "orchestrator_pipeline/reports/PROPUESTA_MEMORIA_20260910.md",
        "orchestrator_pipeline/reports/PROPUESTA_doc_optimization_PROJECT_20260919.md",
        "orchestrator_pipeline/reports/_reconcile_ctl/findings.json",
        "orchestrator_pipeline/reports/_reconcile_ctl/raw/grep_hits.txt",
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260907-2214.json",
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260907-2214.md",
        "orchestrator_pipeline/reports/backlog_triage_20260907-170500.json",
        "orchestrator_pipeline/reports/backlog_triage_20260907-170500.md",
        "orchestrator_pipeline/reports/backlog_triage_20260911-005500.json",
        "orchestrator_pipeline/reports/backlog_triage_20260914-202103.md",
        "orchestrator_pipeline/reports/batch_run_20260908-230708.json",
        "orchestrator_pipeline/reports/bucle_cierre_20260921/bundle_arranque.md.txt",
        "orchestrator_pipeline/reports/bucle_cierre_20260921/bundle_cierre.md.txt",
        "orchestrator_pipeline/reports/bundle_l1000_arranque_v2.md",
        "orchestrator_pipeline/reports/bundle_l1050_ticket_prompt.md",
        "orchestrator_pipeline/reports/bundle_l1080_escalado.md",
        "orchestrator_pipeline/reports/bundle_l1120_r2.md",
        "orchestrator_pipeline/reports/bundle_l1120_r3.md",
        "orchestrator_pipeline/reports/bundle_l1140_plan.md",
        "orchestrator_pipeline/reports/bundle_l1140_r2.md",
        "orchestrator_pipeline/reports/bundle_l1140_r3.md",
        "orchestrator_pipeline/reports/bundle_l1150_027f.md",
        "orchestrator_pipeline/reports/bundle_l1160_paralelo.md",
        "orchestrator_pipeline/reports/bundle_l1160_r2.md",
        "orchestrator_pipeline/reports/bundle_l940_027r.md",
        "orchestrator_pipeline/reports/bundle_l940_027r_dif1.md",
        "orchestrator_pipeline/reports/bundle_l940_027r_dif2.md",
        "orchestrator_pipeline/reports/bundle_l940_027r_dif3.md",
        "orchestrator_pipeline/reports/bundle_l940_027r_dif4.md",
        "orchestrator_pipeline/reports/bundle_l990_arranque.md",
        "orchestrator_pipeline/reports/loop_L9710/bundle_4ecf025875b5.md",
        "orchestrator_pipeline/reports/loop_L9710/bundle_d26123b3dca9.md",
        "orchestrator_pipeline/reports/out_codex_l950.txt",
        "orchestrator_pipeline/reports/reconcile_20260914/findings.json",
        "orchestrator_pipeline/reports/reconcile_20260914/raw/grep_hits.txt",
        "orchestrator_pipeline/reports/triaje_20260913/reconcile/findings.json",
        "orchestrator_pipeline/reports/triaje_20260913/reconcile/raw/grep_hits.txt",
    ]

    missing_keys = [k for k in ctl_keys_expected if k not in v2]
    zero_count_keys = [k for k in ctl_keys_expected if v2.get(k, 0) < 1]

    assert not missing_keys, (
        f"{len(missing_keys)} claves CTL de CTL faltan del baseline: "
        f"{missing_keys[:10]}{'...' if len(missing_keys) > 10 else ''}"
    )
    assert not zero_count_keys, (
        f"{len(zero_count_keys)} claves CTL tienen conteo 0 o negativo: "
        f"{zero_count_keys[:10]}{'...' if len(zero_count_keys) > 10 else ''}"
    )

    # No-regresion: las 121 claves originales de v1 no decrecen en v2.
    # Se fijan como constante del test (baseline v1 congelado al escribirlo).
    # STRATEGY_100l §2.1: merge max(v1, n), nunca decrece lo heredado.
    v1_snapshot: dict[str, int] = {
        "orchestrator_pipeline/arranques/ARRANQUE_062j.md": 14,
        "orchestrator_pipeline/arranques/ARRANQUE_BUILDER_WOT-2026-066z.md": 9,
        "orchestrator_pipeline/arranques/ARRANQUE_BUILDER_WOT-2026-066z_v2.md": 11,
        "orchestrator_pipeline/arranques/ARRANQUE_FRIO_BATCH_CIERRE_20260812.md": 2,
        "orchestrator_pipeline/arranques/ARRANQUE_VUELO_G1_20260813.md": 7,
        "orchestrator_pipeline/arranques/ARRANQUE_auditoria_hermana_047s_20260909.md": 8,
        "orchestrator_pipeline/arranques/ARRANQUE_auditoria_linea_portable_memory_20261008.md": 7,
        "orchestrator_pipeline/arranques/ARRANQUE_builder_WOT-2026-067u.md": 2,
        "orchestrator_pipeline/arranques/ARRANQUE_censo_residuo_20260911a.md": 15,
        "orchestrator_pipeline/arranques/ARRANQUE_cierre_sesion_2026-10-08.md": 1,
        "orchestrator_pipeline/arranques/ARRANQUE_closeout_preflight.md": 20,
        "orchestrator_pipeline/arranques/ARRANQUE_closeout_preflight_v2.md": 22,
        "orchestrator_pipeline/arranques/ARRANQUE_closeout_preflight_v3.md": 6,
        "orchestrator_pipeline/arranques/ARRANQUE_cont_20261001.md": 20,
        "orchestrator_pipeline/arranques/ARRANQUE_continuacion_20260928.md": 8,
        "orchestrator_pipeline/arranques/ARRANQUE_continuidad_20260930_familia_086_v2.md": 3,
        "orchestrator_pipeline/arranques/ARRANQUE_continuidad_post_cg079a_20261002.md": 23,
        "orchestrator_pipeline/arranques/ARRANQUE_continuidad_post_cierre_20261002.md": 7,
        "orchestrator_pipeline/arranques/ARRANQUE_continuidad_post_commit_079a_20261002.md": 21,
        "orchestrator_pipeline/arranques/ARRANQUE_coordinadora.md": 14,
        "orchestrator_pipeline/arranques/ARRANQUE_hop_070b.md": 7,
        "orchestrator_pipeline/arranques/ARRANQUE_hop_20260909c.md": 13,
        "orchestrator_pipeline/arranques/ARRANQUE_hop_20260910d.md": 12,
        "orchestrator_pipeline/arranques/ARRANQUE_implementar_monitor_colisiones_20261008.md": 10,
        "orchestrator_pipeline/arranques/ARRANQUE_post_cierre_0919.md": 24,
        "orchestrator_pipeline/arranques/ARRANQUE_post_docopt.md": 1,
        "orchestrator_pipeline/arranques/ARRANQUE_session_hop_071a.md": 1,
        "orchestrator_pipeline/arranques/ARRANQUE_triaje_20260911a.md": 16,
        "orchestrator_pipeline/arranques/ARRANQUE_triaje_P2_20260911a.md": 14,
        "orchestrator_pipeline/arranques/ARRANQUE_vuelo_047s_20260909.md": 5,
        "orchestrator_pipeline/arranques/ARRANQUE_vuelo_linea_portable_memory_consolidacion_20261009.md": 6,
        "orchestrator_pipeline/arranques/ARRANQUE_vuelo_linea_portable_memory_continuacion_20261009.md": 22,
        "orchestrator_pipeline/arranques/ARRANQUE_wot_2026_073d_builder_20261002.md": 19,
        "orchestrator_pipeline/arranques/README.md": 3,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_053a_test.md": 1,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_20260913_tras_cierre_068q.md": 9,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_AUDITORIA_HERMANA_G1_20260813.md": 3,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_BUCLE_CONTRA_PROPUESTA_AUDITOR_20260812b.md": 2,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_BUILDER_WOT-2026-067e.md": 2,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_BUILDER_WOT-2026-068c.md": 27,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_CIERRE_ALTO1_20260812b.md": 6,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_CIERRE_ALTO1_FANOUT_CIEGO_20260812b.md": 6,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_CONTINUIDAD_068c.md": 13,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_CONTINUIDAD_20260927.md": 6,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_CORRECCION_TRIAJE_20260813.md": 1,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_DEVOLUCION_D6_20260813.md": 1,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_FANOUT_DIF_20260812b.md": 4,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_FP-20260824-052a.md": 5,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_FRIO_CONTINUACION_20260812b.md": 1,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_JUICIO_CIERRE_ALTO1_20260812b.md": 9,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_MANAGER_REVIEW_20260812b.md": 2,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_NUEVA_SESION_20260813.md": 6,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_RETRIAJE_20260813.md": 5,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_RETRIAJE_20260813b.md": 11,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_RETRIAJE_CIERRE72_20260813.md": 6,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_SESION_20260813_ARCHIVADO_Y_CIERRE.md": 6,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_TRIAGE_TICKETS_ANTIGUOS_20260927.md": 5,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_TRIAJE_20260824.md": 5,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_WOT-2026-055L_20260813.md": 4,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_WOT-2026-088b.md": 9,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_auditoria_FV-20260830-fresh-context.md": 1,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_builder_062d.md": 1,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_builder_WOT-2026-073e.md": 8,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_builder_WOT-2026-086f_20260930.md": 5,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_buzon.md": 4,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_continuacion_20260928b.md": 9,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_continuidad_086f_v2.md": 17,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop-063a.md": 20,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop-20260908.md": 10,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop-20260908b.md": 9,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop-cierre063a.md": 23,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop_073e_continuacion.md": 5,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop_0903.md": 1,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop_20260909b.md": 16,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop_20260910e.md": 14,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop_20260910f.md": 20,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop_20260910g.md": 19,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop_20260911a.md": 24,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_hop_20260911b.md": 16,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_lote_20260902.md": 5,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_memoria_20260910h.md": 13,
        "orchestrator_pipeline/arranques/_archive/ARRANQUE_vuelo_062d.md": 13,
        "orchestrator_pipeline/arranques/_archive/BUILDER_PROMPT_WOT-2026-025b.md": 6,
        "orchestrator_pipeline/arranques/_archive/ENCARGO_COMMIT_SUITE_PUSH_20260813.md": 19,
        "orchestrator_pipeline/arranques/_archive/ENCARGO_FANOUT_CONFORME_20260813.md": 8,
        "orchestrator_pipeline/arranques/_archive/INCIDENT_20260908-ficha-inbox-borrada-con-rm.md": 3,
        "orchestrator_pipeline/arranques/_archive/PROPUESTA_PUBLICACION_DESTINO_20260813.md": 1,
        "orchestrator_pipeline/arranques/_archive/launch_builder_WOT-2026-055o.md": 1,
        "orchestrator_pipeline/arranques/_archive/launch_builder_WOT-2026-084a.md": 2,
        "orchestrator_pipeline/arranques/_archive/launch_builder_WOT-2026-084a_CHANGES.md": 1,
        "orchestrator_pipeline/reports/PARADA_cierre_coordinadora_20261007.md": 3,
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260729-1945.json": 3,
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260729-1945.md": 3,
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260808-1018.json": 5,
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260808-1018.md": 1,
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260808-1149.json": 2,
        "orchestrator_pipeline/reports/audit_autonomous_batch_20260810-0903.md": 1,
        "orchestrator_pipeline/reports/audit_autonomous_batch_FP-20260722e_20260723.json": 1,
        "orchestrator_pipeline/reports/audit_autonomous_batch_FP-20260722e_20260723.md": 1,
        "orchestrator_pipeline/reports/backlog_triage_20260809-011108.json": 4,
        "orchestrator_pipeline/reports/backlog_triage_20260809-011108.md": 1,
        "orchestrator_pipeline/reports/backlog_triage_20260810-005248.json": 2,
        "orchestrator_pipeline/reports/backlog_triage_20260810-005248.md": 1,
        "orchestrator_pipeline/reports/backlog_triage_20260812-030040.md": 3,
        "orchestrator_pipeline/reports/backlog_triage_20260813-124200.md": 3,
        "orchestrator_pipeline/reports/backlog_triage_20260813-132400.md": 2,
        "orchestrator_pipeline/reports/backlog_triage_20260814-165708.json": 4,
        "orchestrator_pipeline/reports/backlog_triage_20260820-024142.json": 6,
        "orchestrator_pipeline/reports/backlog_triage_20260822-0340.json": 4,
        "orchestrator_pipeline/reports/backlog_triage_20260901-224854.json": 8,
        "orchestrator_pipeline/reports/backlog_triage_20260901-224854.md": 3,
        "orchestrator_pipeline/reports/backlog_triage_20260915-1556.json": 4,
        "orchestrator_pipeline/reports/backlog_triage_20260928-185000.json": 7,
        "orchestrator_pipeline/reports/backlog_triage_output_post_p1.json": 6,
        "orchestrator_pipeline/reports/batch_run_20260729_1930.json": 3,
        "orchestrator_pipeline/reports/batch_run_20260808-1030.json": 2,
        "orchestrator_pipeline/reports/batch_run_20260811-130246.json": 5,
        "orchestrator_pipeline/reports/batch_run_20260813-1540.json": 1,
        "orchestrator_pipeline/reports/close_full_audit_WOT-2026-086f_20261001.md": 1,
        "orchestrator_pipeline/reports/start_context_isolation.STALE-G1-20260810b.json": 3,
        "orchestrator_pipeline/reports/start_context_isolation.STALE-G1G2-20260811.json": 3,
    }
    assert len(v1_snapshot) == 121, (
        f"v1_snapshot espera 121 entradas, tiene {len(v1_snapshot)}"
    )

    decreced = [
        k for k, expected in v1_snapshot.items() if k in v2 and v2[k] < expected
    ]
    assert not decreced, (
        f"{len(decreced)} claves originales decrecieron entre v1 y v2: {decreced[:10]}"
    )
