"""Contrato del guard de rutas en prompts de arranque (WOT-2026-067n).

Lo que estos tests fijan:

- El ROJO REAL: la linea que detuvo un vuelo el 2026-09-10 produce hallazgo.
- El CONTROL POSITIVO: la misma linea CON ruta absoluta NO lo produce -- sin esto,
  un guard que marcara todo tambien pasaria el test del rojo.
- El BARRIDO de falsos positivos: las clases de prosa que solo MENCIONAN un fichero
  de runtime se dejan pasar. Medido: una regla sin este filtro daba 69% de FP.
- El DENOMINADOR: universo vacio es exit != 0, nunca un verde vacuo.
"""

from __future__ import annotations

import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MOTOR_ROOT / "scripts"))

from check_launch_prompt_paths import (  # noqa: E402
    audit,
    main,
    scan_prompt,
)


def _prompt(root: Path, name: str, body: str) -> Path:
    planning = root / ".agent" / "planning"
    planning.mkdir(parents=True, exist_ok=True)
    path = planning / name
    path.write_text(body, encoding="utf-8")
    return path


def test_la_linea_que_detuvo_el_vuelo_produce_hallazgo(tmp_path):
    """ROJO REAL, no inventado: es la linea literal de `builder_prompt_WOT-2026-067m.md`
    (version pre-fix, `git show 7158aa9`) que hizo que un Builder leyera el
    `work_plan.md` del WORKTREE en vez del DESTINO y reportara
    `RUNTIME_NOT_BOOTSTRAPPED` en falso.

    Su razonamiento fue correcto: en esta topologia hay DOS `.agent/collaboration/` y
    el prompt no decia cual. Este test pinea que el guard lo caza.
    """
    path = _prompt(
        tmp_path,
        "builder_prompt_WOT-2026-067m.md",
        "Confirma que `work_plan.md` activo apunta a `WOT-2026-067m` y que las\n"
        "proyecciones no siguen ancladas a `060j`.\n",
    )
    findings = scan_prompt(path)
    assert len(findings) == 1, [f.render() for f in findings]
    assert findings[0].rule == "R1-ruta-ambigua"
    assert findings[0].lineno == 1


def test_la_misma_orden_con_ruta_absoluta_no_produce_hallazgo(tmp_path):
    """CONTROL POSITIVO, y es el test que da valor al anterior.

    Sin este, un guard que marcara CUALQUIER linea pasaria igualmente el test del
    rojo. Aqui la orden es identica en intencion pero lleva la raiz explicita, que es
    exactamente la correccion que se pide al autor del prompt.
    """
    path = _prompt(
        tmp_path,
        "builder_prompt_WOT-2026-067m.md",
        "Confirma que C:/destino/.agent/collaboration/work_plan.md apunta a 067m.\n",
    )
    assert scan_prompt(path) == []


def test_la_prosa_que_solo_menciona_runtime_no_es_hallazgo(tmp_path):
    """BARRIDO DE FALSOS POSITIVOS -- las cuatro clases medidas sobre prompts reales.

    Una regla literal ("toda mencion de work_plan.md lleva ruta") daba 13 hits sobre
    los 3 prompts vivos, de los que 9 eran prosa: rotulos de evidencia, criterios de
    DoD, condiciones de STOP y referencias al contrato. Un guard con 69% de FP muere
    por ruido, y una barrera muerta no es una barrera.
    """
    path = _prompt(
        tmp_path,
        "builder_prompt_WOT-2026-000a.md",
        "- `<DESTINO_ROOT>/.agent/collaboration/work_plan.md` (proyeccion operativa)\n"
        "DoD (a)-(j) del `work_plan.md`, cada uno con evidencia literal.\n"
        "o si `STATE.md` / `work_plan.md` dejan de apuntar al ticket (DRIFT).\n"
        "los artefactos de PROCESO -- `execution_log.md`, `CG-*.md` -- NO cuentan.\n",
    )
    assert scan_prompt(path) == []


def test_placeholder_sin_expandir_es_hallazgo(tmp_path):
    """R2: un prompt de arranque con la plantilla sin expandir no es un arranque.

    El Builder del 2026-09-10 reporto 8 placeholders literales: le habian pasado el
    prompt CANONICO del motor en vez de la proyeccion del ticket.
    """
    path = _prompt(
        tmp_path,
        "builder_prompt_WOT-2026-000b.md",
        "Eres el BUILDER del ticket `{{TICKET_ID}}`.\n",
    )
    findings = scan_prompt(path)
    assert [f.rule for f in findings] == ["R2-placeholder"]


def test_universo_vacio_es_rojo_no_verde_vacuo(tmp_path, capsys):
    """DENOMINADOR: sin prompts, `exit 0` seria indistinguible de "0 hallazgos sobre 3".

    Es la familia de fallo que esta casa ya midio en `check_encoding_guard`: un verde
    sobre universo vacio. Aqui es rojo explicito.
    """
    (tmp_path / ".agent" / "planning").mkdir(parents=True)
    rc = main(["--project-root", str(tmp_path)])
    assert rc == 1
    assert "universo VACIO" in capsys.readouterr().err


def test_el_denominador_se_publica_siempre(tmp_path, capsys):
    """Un probe que no publica su denominador no es una barrera: no distingue
    "0 hallazgos sobre N" de "no mire nada"."""
    _prompt(
        tmp_path,
        "builder_prompt_WOT-2026-000c.md",
        "Verifica C:/destino/.agent/collaboration/STATE.md antes de empezar.\n",
    )
    rc = main(["--project-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 prompt(s) auditado(s), 0 hallazgo(s)" in out


def test_los_prompts_del_motor_no_entran_en_el_denominador(tmp_path):
    """CONTROL NEGATIVO DE DENOMINADOR: `prompts/` del MOTOR son PLANTILLAS y DEBEN
    llevar `{{...}}` (22 en `orchestrator_launch_builder.md`). Meterlos en el
    denominador seria un falso rojo masivo; el guard solo mira
    `<destino>/.agent/planning/builder_prompt_*.md`.
    """
    motor_prompts = tmp_path / "prompts"
    motor_prompts.mkdir()
    (motor_prompts / "orchestrator_launch_builder.md").write_text(
        "Eres el BUILDER del ticket `{{TICKET_ID}}`.\n", encoding="utf-8"
    )
    _prompt(tmp_path, "builder_prompt_WOT-2026-000d.md", "Sin menciones de runtime.\n")

    findings, prompts = audit(tmp_path)
    assert [p.name for p in prompts] == ["builder_prompt_WOT-2026-000d.md"]
    assert findings == []
