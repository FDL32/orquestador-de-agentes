"""Contrato del recolector de estado de sesion (session-hop).

Lo que estos tests fijan:

- El script **RECOLECTA, no juzga**: su salida no contiene ningun termino de veredicto.
  La lista es CERRADA a proposito -- una lista abierta ("ninguna palabra de juicio") no
  seria testeable de forma reproducible, y por tanto tampoco seria un contrato. Mismo
  patron que `test_backlog_reconcile.py::test_041f_divergences_reach_findings_and_carry_no_verdict`.
- El **contrato de fallo**: con arbol sucio o suite stale sigue en rc=0 y lo REPORTA.
  `rc != 0` queda reservado a fallo del propio recolector.
- La **paridad prompt<->skill** (X-09): la skill es puntero, el prompt gobierna.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = MOTOR_ROOT / "scripts" / "collect_session_state.py"
PROMPT = MOTOR_ROOT / "prompts" / "session_hop.md"
SKILL = MOTOR_ROOT / "skills" / "session-hop" / "SKILL.md"
COMMAND = MOTOR_ROOT / ".claude" / "commands" / "session-hop.md"


def _mkdest(root: Path) -> Path:
    (root / ".agent" / "collaboration" / "backlog_inbox").mkdir(
        parents=True, exist_ok=True
    )
    (root / "orchestrator_pipeline" / "flight_plans" / "queued").mkdir(
        parents=True, exist_ok=True
    )
    return root


def _run(dest: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(dest), *extra],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def test_las_cuatro_piezas_existen(tmp_path):
    """D1+D5: sin el command, `/session-hop` no seria invocable como sus vecinos."""
    for piece in (SCRIPT, PROMPT, SKILL, COMMAND):
        assert piece.exists(), f"pieza ausente: {piece}"


def test_recolector_no_emite_veredictos(tmp_path):
    """DoD(b): el script RECOLECTA, el agente juzga.

    Lista CERRADA de terminos, al modo del precedente en test_backlog_reconcile.py.
    Si el recolector empezara a clasificar, se convertiria en el juez que audita su
    propia recoleccion -- falso verde estructural.
    """
    from scripts.collect_session_state import FORBIDDEN_VERDICTS

    dest = _mkdest(tmp_path / "d1")

    # LAS DOS RAMAS DE SALIDA, y el orden importa: markdown es el DEFECTO -- la que
    # un agente lee de verdad. La primera version de este test solo cubria `--json`
    # y su mutation-verify SOBREVIVIO (se inyecto "VEREDICTO: APROBADO" en
    # `render_markdown` y el test siguio verde). Un test que no ALCANZA la rama que
    # muta no clasifica nada: es el falso verde que el propio contrato persigue.
    for extra in ([], ["--json"]):
        proc = _run(dest, *extra)
        assert proc.returncode == 0, proc.stderr

        blob = proc.stdout.upper()
        rama = "json" if extra else "markdown"
        for verdict in FORBIDDEN_VERDICTS:
            assert verdict.upper() not in blob, (
                f"veredicto filtrado en la salida ({rama}): {verdict}"
            )


def test_contrato_de_fallo_arbol_no_sano_sigue_rc0(tmp_path):
    """DoD(a-bis): un destino sin git ni gates verdes NO tumba al recolector.

    Es el caso que MAS importa: un recolector que se cae cuando el arbol no esta sano
    es inutil justo cuando hace falta. Los hechos adversos se REPORTAN, no se lanzan.
    """
    dest = _mkdest(tmp_path / "sin_git")  # no es repo git: git fallara dentro
    proc = _run(dest)
    assert proc.returncode == 0, f"el recolector no debe caerse: {proc.stderr}"
    assert "ESTADO MEDIDO" in proc.stdout


def test_rc_distinto_de_cero_solo_por_fallo_del_recolector(tmp_path):
    """rc!=0 se reserva a fallo PROPIO (ruta irresoluble), nunca a un hallazgo."""
    proc = _run(tmp_path / "no_existe_este_destino")
    assert proc.returncode == 2
    assert "no existe" in (proc.stderr or "").lower()


def test_estado_va_etiquetado_como_snapshot_fechado(tmp_path):
    """DoD(g): el estado es EVIDENCIA FECHADA, jamas criterio.

    Sin la etiqueta, el consumidor copia el numero y nace la premisa falsa heredada
    que esta herramienta existe para evitar.
    """
    dest = _mkdest(tmp_path / "d2")
    proc = _run(dest)
    assert proc.returncode == 0
    assert "snapshot" in proc.stdout.lower()
    assert "no criterio" in proc.stdout.lower()


def test_slugs_de_memoria_se_verifican_antes_de_citarse(tmp_path):
    """Un slug inexistente NO puede salir como citable: seria un paso imposible."""
    dest = _mkdest(tmp_path / "d3")
    proc = _run(dest, "--json", "--slug", "obs-este-slug-no-existe-jamas")
    assert proc.returncode == 0
    rep = json.loads(proc.stdout)
    entry = next(m for m in rep["memory_slugs"] if "no-existe-jamas" in m["slug"])
    assert entry["citable"] is False


def test_dirty_tracked_y_untracked_van_separados(tmp_path):
    """Sumarlos reporta 'sucio' cuando solo hay artefactos nuevos de otra sesion.

    Medido en esta casa: un destino con 7 untracked (artefactos de una sesion de
    diseno) y 0 tracked se leyo como arbol sucio del ejecutor.
    """
    dest = _mkdest(tmp_path / "d4")
    proc = _run(dest, "--json")
    rep = json.loads(proc.stdout)
    destino = next(r for r in rep["repos"] if r["role"] == "repo_destino")
    assert "dirty_tracked" in destino
    assert "dirty_untracked" in destino


def test_skill_es_puntero_no_redeclara_criterios(tmp_path):
    """X-09 (AGENTS.md:472-476): la skill APUNTA, el prompt GOBIERNA."""
    skill = SKILL.read_text(encoding="utf-8")
    assert "source_prompt: prompts/session_hop.md" in skill
    assert "contract_id: cid-session-hop-v1" in skill
    assert "prevalece el prompt" in skill

    prompt = PROMPT.read_text(encoding="utf-8")
    assert "contract_id: cid-session-hop-v1" in prompt
    assert "source_of_truth" in prompt


def test_el_prompt_no_cristaliza_estado(tmp_path):
    """El prompt versionado no puede llevar un SHA de esta maquina.

    Es el defecto que el propio prompt existe para cerrar; cometerlo AL ESCRIBIRLO
    seria la ironia que ya se cazo una vez en su propuesta.
    """
    import re

    prompt = PROMPT.read_text(encoding="utf-8")
    # un sha de 7-40 hex aislado seria estado cristalizado
    assert not re.search(r"\b[0-9a-f]{7,40}\b", prompt), "el prompt cristaliza un SHA"
    assert "C:\\Users" not in prompt and "C:/Users" not in prompt


def test_060j_la_suite_y_el_modo_nombran_el_repo_que_midieron(tmp_path):
    """WOT-2026-060j (a)(b)(c): la atribucion de raiz no puede ser AMBIGUA.

    El recolector mide la suite canonica y el modo SIEMPRE contra `motor_root`,
    aunque se le invoque con `--project-root <destino>`. La tabla de Topologia SI
    distingue ambos repos, asi que un lector razonable ATRIBUYE al destino un dato
    que es del motor.

    Por que importa, medido 2026-09-10: coexisten TRES `last-run.json` en esta
    topologia (motor, destino y worktree) con veredictos DISTINTOS. Sin etiqueta,
    el bloque de arranque reporto la suite como STALE cuando la real estaba VERDE
    y fresca en el worktree, y el lector no tenia forma de saberlo.

    El test corre sobre DOS raices DISTINTAS (`--project-root` != `--motor-root`)
    porque con una sola raiz la atribucion correcta y la ambigua son
    indistinguibles: es justo el caso que el defecto produce.

    Mutacion que debe matarlo (DoD (e1)(e2)): retirar la etiqueta de CUALQUIERA de
    las dos secciones deja este test ROJO.
    """
    dest = _mkdest(tmp_path / "destino")
    motor = tmp_path / "motor_falso"
    (motor / ".agent" / "runtime" / "pytest-safe").mkdir(parents=True)

    proc = _run(dest, "--motor-root", str(motor))
    assert proc.returncode == 0, proc.stderr

    out = proc.stdout
    suite_idx = out.find("### Suite canonica")
    # La linea del modo se localiza por su PREFIJO, no por "Modo:" literal:
    # la etiqueta de raiz se inserta entre el rotulo y los dos puntos, y un
    # find("Modo:") volveria -1 justo cuando el fix ESTA aplicado.
    modo_line = next(
        (ln for ln in out.splitlines() if ln.lstrip().startswith("Modo")), None
    )
    assert suite_idx != -1, "falta la seccion Suite canonica"
    assert modo_line is not None, "falta la linea Modo"

    # (a) La seccion Suite canonica declara de que repo es su dato.
    suite_block = out[suite_idx : suite_idx + 600]
    assert "repo medido:" in suite_block, (
        "`### Suite canonica` no NOMBRA el repo del que procede su dato: con TRES "
        f"last-run.json coexistiendo, el lector no puede atribuirlo. Bloque:{chr(10)}{suite_block[:300]}"
    )

    # (b) La linea Modo: hace lo mismo.
    modo_block = modo_line
    assert "repo medido:" in modo_block, (
        "la linea `Modo:` no NOMBRA el repo sobre el que se detecto "
        f"is_motor_code_only(). Bloque:{chr(10)}{modo_block[:300]}"
    )

    # El rol declarado es el vocabulario canonico, no una ruta improvisada.
    assert "repo medido: repo_motor" in out, (
        "el rol debe ser literalmente `repo_motor` o `repo_destino` (formato fijado "
        "por contrato para que el Builder no lo elija)"
    )
