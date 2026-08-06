"""Tests for scripts/check_guard_wiring.py v4 (WOT-2026-024u).

The corpus (test_guard_wiring_corpus.py) is the executable spec of the FORM/POSITION
axis. This file holds the tests that need the REAL repo or the policy machinery:

  T-REAL-BASELINE : audit(REAL_REPO) is exactly the expected wired/unwired split.
                    A synthetic corpus models the easy cross-function case; only the
                    real repo has `guard_paths` (return-with-name) and the injected
                    callable. This is the test the three previous versions lacked.
  T-DEWIRING      : delete a guard's real call-site -> it must go UNWIRED (the twin
                    asymmetry). v3 was blind: prose kept it WIRED.
  T-DENOM         : the recursive denominator sees a guard in a subdir and the
                    declared no-prefix guards.
  T-FRONTIER      : the derived frontier includes what settings.json/imports reach,
                    and BOTH .yml and .yaml.
  T-SELFDOS       : printing the debt (KNOWN_UNWIRED lives in YAML, not this .py) does
                    not wire the declared guards.
  T-STALE / owners: the policy format-checks (conserved from v2).

Hermetic where it can be; explicitly a LIVE contract on the real repo where the point
IS the real repo (the failure mode WOT-2026-020q: a synthetic-only test is blind to
the boundary with the real tree).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_guard_wiring", _ROOT / "scripts" / "check_guard_wiring.py"
)
cgw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cgw)


# --------------------------------------------------------------------- helpers
def _motor(
    tmp_path: Path, files: dict[str, str], guards: list[str] | None = None
) -> Path:
    (tmp_path / "scripts").mkdir(exist_ok=True)
    for g in guards or []:
        (tmp_path / "scripts" / f"{g}.py").write_text("# guard\n", encoding="utf-8")
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    if not (tmp_path / ".pre-commit-config.yaml").exists():
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "repos:\n  - repo: local\n    hooks:\n      []\n", encoding="utf-8"
        )
    return tmp_path


_EMPTY_POLICY = {"known_unwired": {}, "extra_guards": {}, "wired_via": {}}


# ---------------------------------------------------------------- T-REAL-BASELINE
# The guards genuinely wired in the real repo, each verified against its call-site.
# The COUNT is not the invariant -- the SAME set is (a classifier that drops a real
# call-site and picks up a bogus one prints the same number).
EXPECTED_WIRED_REAL = {
    "check_agent_write_enforced",  # WOT-2026-048h: cableado via import estatico en prepush_check.py::run_agent_write_enforced_check (closeout, WARN -- nace WARN porque la deuda claude/codex sin readonly_agent es PREEXISTENTE)
    "check_agents_accessible",  # WOT-2026-026e(A7): cableado por import en preflight_codeonly_pipeline.py
    "check_backlog_commits_landed",  # WOT-2026-024q: cableado via import estatico en agent_controller.py::_ticket_landed_by_archived_commit (retirado de known_unwired)
    "check_backlog_contract",
    "check_batch_run_accounting",  # WOT-2026-025k: cableado via import estatico en batch_destination_controller.py::_batch_run_orphan_gsr_tickets y prepush_check.py::run_batch_run_accounting_check (closeout, WARN)
    "check_claude_settings_portability",
    "check_commit_worktree",
    "check_closeout_reconciliation",  # WOT-2026-024w: cableado en prepush_check.py (closeout, WARN/STRICT)
    "check_contract_backlog_reconcile",  # WOT-2026-024e: cableado en prepush_check.py (closeout, WARN/FAIL)
    "check_dec_receipt",  # WOT-2026-042x: cableado en prepush_check.py::run_dec_receipt_check (closeout). Barrera de la NORMA de 042w (recibo DEC en las fichas de diseno). No es falso-WIRED: mutation-verify con par de exit-codes literal sobre la invocacion REAL (1 sin recibo / 1 con DEC-<id> inexistente -> 0 con `DEC-no-aplica: <motivo>`), y 14/14 fichas reales del destino degradan a WARN por el grandfathering.
    "check_deliverables_exist",
    "check_destination_pii_leak",  # WOT-2026-020t: cableado en prepush_check.py (closeout, WARN/FAIL)
    # WOT-2026-049c: NO es falso-WIRED, pero su `wired` es ACOTADO y hay que leerlo asi.
    # Declarado en extra_guards porque no lleva prefijo check_/validate_/guard_ y por eso
    # `find_guards()` NUNCA lo censaba (medido: in-censo False sin declarar / True con ello);
    # el exit 0 previo no lo aprobaba, es que no lo veia. Call-sites REALES verificados:
    # scripts/closeout_steps/gates.py:54,70,71,120 (step_prepush_check -> run_script_fn), y
    # session_closeout.py:921-923 CORTA el cierre si status == "FAIL" (probe: --session-close
    # --force con arbol sucio -> exit 1, report `| 3 | prepush_check | FAIL | Yes |`).
    # ALCANCE del "wired": alcanzable desde `session_closeout`, NO "corre solo ante cualquier
    # publicacion" -- un `git push` directo NO lo ejecuta (probe en remoto bare aislado: 9 hooks
    # de pre-push, prepush_check ausente de toda la salida). Si el contrato que se quiere es
    # "bloquea el push directo", el estado correcto seria unwired + deuda declarada; esa es una
    # decision de politica pendiente del operador, declarada en la ficha de WOT-2026-049c.
    "prepush_check",
    "check_destino_publish_ready",  # WOT-2026-024w (colateral): wired via check_motor_destination_integration en prepush
    "check_distributable_planning_clean",  # WOT-2026-024h(C4'): cableado via import estatico en prepush_check.py::run_distributable_planning_check (closeout, BLOQUEANTE). No es falso-WIRED: mutation-verify con par de exit-codes literal (0 limpio -> 1 al re-anadir un contrato WOT real a la superficie distribuible).
    "check_distribution_agnostic",  # WOT-2026-024z(d): cableado en pre-commit (entry: uv run python)
    "check_distribution_boundary",  # WOT-2026-025i: cableado en pre-commit (entry: uv run python)
    "check_encoding_guard",
    "check_flight_plan_collision",  # WOT-2026-027h: cableado via import estatico en prepush_check.py::run_flight_plan_collision_check (closeout, WARN). Check HERMANO de validate_batch_dag: colision inter-plan en queued/. Endurecer a bloqueante: 040r.
    "check_guard_wiring",
    "check_handoff_committed",  # WOT-2026-040t(P1): cableado en prepush_check.py (closeout, BLOQUEANTE)
    "check_handoff_state_sha",  # WOT-2026-024t(s2): cableado en prepush_check.py (closeout, WARN/FAIL)
    "check_loop_execution",  # WOT-2026-040b: cableado via import estatico en prepush_check.py::run_loop_execution_check (closeout, WARN). Barrera de ejecucion del bucle 1->9->2.
    "check_motor_destination_integration",  # WOT-2026-024w: cableado en prepush_check.py (closeout, WARN/STRICT)
    "check_no_history_truncation",
    "check_portable_memory_archive_schema",  # WOT-2026-035b: cableado en .pre-commit-config.yaml (always_run) + prepush_check.py
    "check_ruff_hook_scope",  # WOT-2026-024w: cableado en .pre-commit-config.yaml (always_run)
    "check_skill_collisions",  # WOT-2026-024w: cableado en .pre-commit-config.yaml (always_run)
    "check_ticket_nomenclature",  # WOT-2026-024w: cableado en .pre-commit-config.yaml (always_run)
    # WOT-2026-026t DoD-(c): cableado en .pre-commit-config.yaml (always_run,
    # stages: [pre-commit]). WIRED verificado a mano ademas del parseo: el hook
    # `check-stale-operational-note` invoca el script en cada commit, y su
    # mutation-verify demuestra que muerde (nota-prohibicion sin fecha -> rc=1).
    "check_stale_operational_note",
    # WOT-2026-026t: cableado en .pre-commit-config.yaml (hook
    # `check-suite-freshness`, always_run, stages: [pre-commit]). Es un AVISO, no
    # una barrera de correccion -- exit 0 SIEMPRE --, pero entra en el set WIRED
    # igual: el criterio de este baseline es "lo invoca un camino que corre solo",
    # no "bloquea". Su mutation-verify vive en test_check_suite_freshness.py.
    "check_suite_freshness",
    "check_worktree_topology",
    "delivery_hygiene_check",  # v4: denominador ve el guard sin prefijo, y lo cabla
    "guard_paths",
    "validate_batch_dag",  # WOT-2026-027h: wired via import estatico -- check_flight_plan_collision.py hace `from validate_batch_dag import _normalize_surface`, y ese check hermano corre en prepush closeout. Retirado de guard_wiring_policy.yaml (era declared-debt de WOT-2026-038b).
    "validate_all",
    "validate_contract_formation",  # WOT-2026-023m(c): cableado via import estatico en prepush_check.py::run_contract_formation_check (closeout; valida el CF triple del motor)
    "validate_observations",  # WOT-2026-035b: cableado via import estatico en check_portable_memory_archive_schema.py (retirado de known_unwired)
    "validate_ticket_prose",
}


def test_real_repo_wired_set_is_exactly_expected():
    """T-REAL-BASELINE. The decisive test: a synthetic corpus passed 32/32 while the
    real repo still lost guard_paths (return-with-name). Only the real repo exercises it."""
    wired, _unwired = cgw.audit(_ROOT)
    got = set(wired)
    missing = EXPECTED_WIRED_REAL - got  # un call-site real que dejo de verse
    extra = got - EXPECTED_WIRED_REAL  # algo nuevo, sospechoso de falso-WIRED
    assert not missing, (
        f"falso-UNWIRED (regresion sobre codigo vivo): {sorted(missing)}"
    )
    assert not extra, f"WIRED nuevo, revisar si es falso-WIRED: {sorted(extra)}"


def test_real_repo_audit_is_clean():
    """main() sobre el repo real -> rc 0 (exit real via subprocess, nunca tras un pipe)."""
    r = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "check_guard_wiring.py")],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


# ----------------------------------------------------------------- T-DEWIRING
DEWIRING_TARGETS = {
    # guard : (fichero, literal-a-romper, sustituto) -- borra el call-site REAL dejando
    # la prosa viva (docstring, mensaje de error). v3 seguia WIRED; v4 debe ir UNWIRED.
    "guard_paths": (
        ".agent/hooks/claude_guard_entry.py",
        "guard_paths.py",
        "OTRO_NO_GUARD.py",
    ),
}


@pytest.mark.parametrize("guard", sorted(DEWIRING_TARGETS))
def test_dewiring_is_caught(guard, tmp_path):
    """La asimetria gemela, ejecutada. Copiamos SOLO el fichero relevante a un motor
    sintetico minimo, rompemos el call-site real, y exigimos que _dewired lo cace.

    (No mutamos el repo real: WOT-2026-023x, un guard read-only no muta el arbol.)"""
    rel, literal, sub = DEWIRING_TARGETS[guard]
    src = (_ROOT / rel).read_text(encoding="utf-8")
    assert literal in src, f"el literal {literal} ya no esta en {rel} (test caducado)"

    # motor sintetico: el fichero mutado + la semilla que lo mete en frontera + el guard
    settings = (
        '{"hooks": {"PreToolUse": [{"hooks": [{"type": "command",'
        f' "command": "python {rel}"}}]}}]}}}}'
    )
    muted = src.replace(literal, sub)
    motor = _motor(
        tmp_path,
        {rel: muted, ".claude/settings.json": settings},
        guards=[],
    )
    # el guard existe en el motor (para estar en el denominador)
    (motor / ".agent" / "hooks" / f"{guard}.py").parent.mkdir(
        parents=True, exist_ok=True
    )
    (motor / ".agent" / "hooks" / f"{guard}.py").write_text(
        "# guard\n", encoding="utf-8"
    )

    edges = cgw.wiring_edges(motor, _EMPTY_POLICY)
    assert not edges.get(guard), (
        f"des-cableado NO detectado: {guard} sigue con arista {edges.get(guard)} tras "
        f"romper su unico call-site real (v3 era ciego a esto por la prosa viva)"
    )


def test_loop_execution_barrier_is_wired_from_prepush():
    """WOT-2026-040b, POSITIVO en el repo real: la barrera de ejecucion del bucle
    1->9->2 esta cableada desde prepush_check.py (import estatico). Si dejara de
    estarlo, `check_guard_wiring` la caeria como UNWIRED (la asimetria que este
    ticket EXTIENDE, no un subsistema nuevo)."""
    edges = cgw.wiring_edges(_ROOT)
    assert "scripts/prepush_check.py" in edges.get("check_loop_execution", set()), (
        "check_loop_execution debe estar cableado desde prepush_check.py: es la "
        "barrera de EJECUCION del bucle, no una norma en un prompt (WOT-2026-040b)."
    )


def test_loop_execution_dewiring_is_caught(tmp_path):
    """MUTATION del DoD de 040b, EJECUTADA: retirar la invocacion de
    check_loop_execution de prepush -> el guard sale UNWIRED en un motor sintetico.

    Prueba que la barrera del bucle NO es solo prosa: es un call-site REAL que
    check_guard_wiring cuenta. Copiamos prepush_check.py con la linea de import
    ROTA y exigimos que _python_invocations ya no vea el guard."""
    guard = "check_loop_execution"
    src = (_ROOT / "scripts" / "prepush_check.py").read_text(encoding="utf-8")
    literal = "check_loop_execution import audit"
    assert literal in src, (
        f"el literal del cableado {literal!r} ya no esta en prepush_check.py "
        "(test caducado: el call-site cambio de forma)"
    )
    # motor sintetico: prepush con el import ROTO + el guard en el denominador +
    # la semilla que mete prepush en la frontera (es un _DECLARED_ROOT).
    muted = src.replace(literal, "OTRO_MODULO_NO_GUARD import audit")
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "prepush_check.py").write_text(muted, encoding="utf-8")
    (tmp_path / "scripts" / "check_loop_execution.py").write_text(
        "# guard\n", encoding="utf-8"
    )
    edges = cgw.wiring_edges(tmp_path, _EMPTY_POLICY)
    assert not edges.get(guard), (
        f"des-cableado NO detectado: {guard} sigue con arista {edges.get(guard)} "
        "tras romper su import en prepush (la barrera seria falsa)."
    )


# ------------------------------------------------------------------- T-DENOM
def test_denominator_is_recursive(tmp_path):
    """rglob, no glob plano: un guard en un subdirectorio DEBE estar en el denominador
    (v3 era ciego a scripts/sandbox/check_wp_087_deliverable.py)."""
    (tmp_path / "scripts" / "sub").mkdir(parents=True)
    (tmp_path / "scripts" / "sub" / "check_nested.py").write_text(
        "# g\n", encoding="utf-8"
    )
    guards = cgw.find_guards(tmp_path)
    assert "check_nested" in guards


def test_denominator_includes_declared_no_prefix_guards(tmp_path):
    """Un guard REAL sin prefijo (pre_handoff_guard) solo entra si se DECLARA."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "pre_handoff_guard.py").write_text(
        "# g\n", encoding="utf-8"
    )
    without = cgw.find_guards(tmp_path)
    assert "pre_handoff_guard" not in without, "sin declarar no debe adivinarse"
    with_extra = cgw.find_guards(
        tmp_path, {"pre_handoff_guard": "scripts/pre_handoff_guard.py"}
    )
    assert "pre_handoff_guard" in with_extra


def test_real_denominator_sees_the_subdir_guard():
    """Contrato vivo: el denominador del repo real es RECURSIVO (rglob), no un glob
    plano de scripts/*.py. WOT-2026-024w retiro check_wp_087_deliverable (el unico
    guard en scripts/sandbox/), asi que este contrato ya no se ancla en un guard
    concreto: se verifica materializando un guard en un subdir temporal DENTRO del
    arbol de scripts/ real y comprobando que el denominador lo ve. El fixture se
    limpia; la propiedad (recursividad sobre el arbol vivo) es la que importa."""
    subdir = _ROOT / "scripts" / "sandbox"
    created_dir = not subdir.exists()
    probe = subdir / "check_recursion_probe_024w.py"
    subdir.mkdir(parents=True, exist_ok=True)
    probe.write_text("# recursion probe (WOT-2026-024w)\n", encoding="utf-8")
    try:
        guards = cgw.find_guards(_ROOT, cgw._load_policy()["extra_guards"])
        assert "check_recursion_probe_024w" in guards, (
            "denominador NO recursivo: un guard en scripts/sandbox/ no se ve"
        )
    finally:
        probe.unlink(missing_ok=True)
        if created_dir:
            subdir.rmdir()


# ----------------------------------------------------------------- T-FRONTIER
def test_frontier_includes_both_yml_and_yaml(tmp_path):
    """El glob de v3 solo veia *.yml. GitHub acepta ambos: un guard cableado en
    ci.yaml saldria falso-UNWIRED."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "a.yaml").write_text(
        "on:\n  push:\njobs:\n  j:\n    steps:\n      - run: python scripts/check_yaml.py\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "check_yaml.py").write_text("# g\n", encoding="utf-8")
    wired, _ = cgw.audit(tmp_path, _EMPTY_POLICY)
    assert "check_yaml" in wired, "un guard en *.yaml debe verse igual que en *.yml"


def test_frontier_derives_settings_hook_targets():
    """La frontera del repo real DERIVA claude_guard_entry.py del command de
    settings.json, y encoding_post_write_hook.py del otro hook."""
    fr = {p.name for p in cgw.self_running_paths(_ROOT)}
    assert "claude_guard_entry.py" in fr
    assert "encoding_post_write_hook.py" in fr


# ------------------------------------------------------------------ T-SELFDOS
def test_printing_the_debt_does_not_wire_it(tmp_path):
    """Auto-DoS: un fichero de la frontera que IMPRIME la deuda para reportarla NO
    debe cablear a los declarados. Con KNOWN_UNWIRED en YAML (no en este .py) pasa."""
    motor = _motor(
        tmp_path,
        {
            "scripts/prepush_check.py": (
                "DEBT = {\n"
                '    "check_declared_a": "WOT-2026-024w",\n'
                '    "check_declared_b": "WOT-2026-024w",\n'
                "}\n"
                "for g, owner in DEBT.items():\n"
                "    print(f'  {g} -> {owner}')\n"
            )
        },
        guards=["check_declared_a", "check_declared_b"],
    )
    wired, _ = cgw.audit(motor, _EMPTY_POLICY)
    assert "check_declared_a" not in wired
    assert "check_declared_b" not in wired


# ---------------------------------------------------- policy format-checks (v2)
def test_bad_owner_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_new.py").write_text("# g\n", encoding="utf-8")
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      []\n", encoding="utf-8"
    )
    policy_yaml = tmp_path / "scripts" / "guard_wiring_policy.yaml"
    policy_yaml.write_text(
        "known_unwired:\n  check_new: 'texto libre no es ticket'\n", encoding="utf-8"
    )
    monkeypatch.setattr(cgw, "POLICY_PATH", policy_yaml)
    assert cgw.main(["--motor-root", str(tmp_path)]) == 1


def test_stale_declaration_fails(tmp_path, monkeypatch):
    """Un guard DECLARADO unwired que en realidad ESTA cableado -> stale -> FALLA."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_wired.py").write_text("# g\n", encoding="utf-8")
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n"
        "      - id: h\n        entry: python scripts/check_wired.py\n"
        "        stages: [pre-commit]\n",
        encoding="utf-8",
    )
    policy_yaml = tmp_path / "scripts" / "guard_wiring_policy.yaml"
    policy_yaml.write_text(
        "known_unwired:\n  check_wired: WOT-2026-024w\n", encoding="utf-8"
    )
    baseline_yaml = tmp_path / "baseline.yaml"
    baseline_yaml.write_text("wired_baseline: {}\n", encoding="utf-8")
    monkeypatch.setattr(cgw, "POLICY_PATH", policy_yaml)
    monkeypatch.setattr(cgw, "BASELINE_PATH", baseline_yaml)
    assert cgw.main(["--motor-root", str(tmp_path)]) == 1


def test_prefix_is_not_a_substring_match(tmp_path):
    """Regresion de v1 conservada: check_backlog no casa check_backlog_commits_landed."""
    motor = _motor(
        tmp_path,
        {
            "scripts/prepush_check.py": (
                "import subprocess, sys\n"
                'subprocess.run([sys.executable, "scripts/check_backlog_long.py"])\n'
            )
        },
        guards=["check_backlog", "check_backlog_long"],
    )
    wired, unwired = cgw.audit(motor, _EMPTY_POLICY)
    assert "check_backlog_long" in wired
    assert "check_backlog" in unwired, "el prefijo no hereda el cableado del largo"


# ------------------------------------------- deuda HUERFANA (WOT-2026-026v)
# La declaracion acota la deuda solo mientras su dueno siga VIVO. Owner archivado
# + guard AUN sin cablear = la declaracion paso de ACOTAR la deuda a ESCONDERLA.
# El criterio es el INVARIANTE, nunca el conteo (WOT-2026-024t).
def _destino(tmp_path: Path, live_rows: str, name: str = "destino") -> Path:
    """repo_destino minimo con la cola VIVA que decide si un owner sigue vivo."""
    dest = tmp_path / name
    (dest / ".agent" / "collaboration").mkdir(parents=True, exist_ok=True)
    (dest / ".agent" / "collaboration" / "backlog.md").write_text(
        live_rows, encoding="utf-8"
    )
    return dest


@pytest.mark.parametrize(
    "owner, live_rows, expected",
    [
        # el fallo que este ticket cierra: dueno archivado, guard sin cablear
        ("WOT-2026-023t", "| Alta | WOT-2026-019o | otra cosa viva |\n", ["check_new"]),
        # con el dueno VIVO NO dispara: es deuda declarada y acotada, no huerfana
        ("WOT-2026-023t", "| Alta | WOT-2026-023t | sigue en cola |\n", []),
        # BY-DESIGN no tiene dueno que archivar -> nunca es huerfana
        ("BY-DESIGN: circular por diseno", "| Alta | WOT-2026-019o | x |\n", []),
    ],
    ids=["owner-archivado-dispara", "owner-vivo-no-dispara", "by-design-exento"],
)
def test_orphan_owner_invariant(owner, live_rows, expected):
    known = {"check_new": owner}
    got = cgw._orphan_owners(
        known, ["check_new"], set(cgw._TICKET_ANYWHERE.findall(live_rows))
    )
    assert [g.split(" -> ")[0] for g in got] == expected


def test_orphan_owner_ignores_guards_that_got_wired(tmp_path):
    """Un guard con owner archivado que YA esta cableado no es huerfano: es `stale`.

    Sin este limite el gate reportaria dos veces el mismo hecho con dos remedios
    contradictorios ("reabre el ticket" vs "borra la declaracion").
    """
    known = {"check_new": "WOT-2026-023t"}
    # `declared` solo contiene guards que esta pasada vio UNWIRED; si esta wired
    # no entra, y por tanto no puede salir como huerfano.
    assert cgw._orphan_owners(known, [], {"WOT-2026-019o"}) == []


def test_orphan_owner_fails_only_under_strict(tmp_path, monkeypatch):
    """Mutation-verify de EXTREMO A EXTREMO por el CLI real (no por la funcion pura).

    Mismo arbol, mismo destino: normal -> exit 0 (WARN nombrado);
    `--strict` -> exit 1. El par de exit codes ES la barrera.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_new.py").write_text("# g\n", encoding="utf-8")
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      []\n", encoding="utf-8"
    )
    policy_yaml = tmp_path / "scripts" / "guard_wiring_policy.yaml"
    policy_yaml.write_text(
        "known_unwired:\n  check_new: WOT-2026-023t\n", encoding="utf-8"
    )
    baseline_yaml = tmp_path / "baseline.yaml"
    baseline_yaml.write_text("wired_baseline: {}\n", encoding="utf-8")
    monkeypatch.setattr(cgw, "POLICY_PATH", policy_yaml)
    monkeypatch.setattr(cgw, "BASELINE_PATH", baseline_yaml)
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    dest = _destino(tmp_path, "| Alta | WOT-2026-019o | el dueno NO esta aqui |\n")
    argv = ["--motor-root", str(tmp_path), "--project-root", str(dest)]

    assert cgw.main(argv) == 0, (
        "en modo normal la huerfana es WARN, no rompe pre-commit"
    )
    assert cgw.main([*argv, "--strict"]) == 1, "en --strict la huerfana FALLA"


def test_orphan_check_skips_explicitly_without_destino(tmp_path, monkeypatch, capsys):
    """Sin destino resoluble: SKIP IMPRESO y exit 0 -- nunca crash, nunca silencio.

    Es la forma EXACTA del call-site real (`.pre-commit-config.yaml`, que no pasa
    ninguna de las dos flags). Un guard del motor que reviente en un destino sin
    backlog es peor que la deuda que cierra.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_new.py").write_text("# g\n", encoding="utf-8")
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      []\n", encoding="utf-8"
    )
    policy_yaml = tmp_path / "scripts" / "guard_wiring_policy.yaml"
    policy_yaml.write_text(
        "known_unwired:\n  check_new: WOT-2026-023t\n", encoding="utf-8"
    )
    baseline_yaml = tmp_path / "baseline.yaml"
    baseline_yaml.write_text("wired_baseline: {}\n", encoding="utf-8")
    monkeypatch.setattr(cgw, "POLICY_PATH", policy_yaml)
    monkeypatch.setattr(cgw, "BASELINE_PATH", baseline_yaml)
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)

    # SIN --strict a proposito: `--strict` falla por la deuda DECLARADA (regla
    # preexistente) y ese 1 enmascararia el veredicto que aqui se mide.
    assert cgw.main(["--motor-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "SKIP orphan-owner check" in out, "el skip se IMPRIME, no se calla"
    assert "HUERFANA" not in out, "sin destino no se puede afirmar que un owner murio"


def test_orphan_check_skips_when_destino_has_no_backlog(tmp_path, monkeypatch, capsys):
    """Destino RESUELTO pero sin backlog.md -> SKIP, no un mar de falsos huerfanos.

    Sin este limite un destino recien instalado veria TODA la deuda declarada
    reportada como huerfana: el backlog vacio no dice 'todos archivados'.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_new.py").write_text("# g\n", encoding="utf-8")
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      []\n", encoding="utf-8"
    )
    policy_yaml = tmp_path / "scripts" / "guard_wiring_policy.yaml"
    policy_yaml.write_text(
        "known_unwired:\n  check_new: WOT-2026-023t\n", encoding="utf-8"
    )
    baseline_yaml = tmp_path / "baseline.yaml"
    baseline_yaml.write_text("wired_baseline: {}\n", encoding="utf-8")
    monkeypatch.setattr(cgw, "POLICY_PATH", policy_yaml)
    monkeypatch.setattr(cgw, "BASELINE_PATH", baseline_yaml)
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    empty = tmp_path / "sin_backlog"
    empty.mkdir()

    assert cgw.main(["--motor-root", str(tmp_path), "--project-root", str(empty)]) == 0
    out = capsys.readouterr().out
    assert "SKIP orphan-owner check" in out
    assert "HUERFANA" not in out, "backlog ausente != 'todos los owners archivados'"


def test_ticket_anywhere_matches_the_owner_grammar():
    """Los dos regex son gemelos deliberados; si divergen, un owner VIVO se
    reportaria huerfano en falso por no casar con su propia fila del backlog."""
    owner = "WOT-2026-023t"
    assert cgw._TICKET.match(owner)
    assert cgw._TICKET_ANYWHERE.findall(f"| Alta | {owner} | prosa alrededor |") == [
        owner
    ]
