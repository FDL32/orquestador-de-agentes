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
from datetime import datetime, timezone
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


def _mk_link(dest: Path, motor: Path = MOTOR_ROOT) -> None:
    cfg = dest / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(motor)}), encoding="utf-8"
    )


def _mk_events(dest: Path, lines: list[dict]) -> Path:
    ens = dest / ".agent" / "runtime" / "ensemble"
    ens.mkdir(parents=True, exist_ok=True)
    path = ens / "fallback_events.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in lines), encoding="utf-8")
    return path


def _quota_event(
    profile: str = "challenger_nan_qwen", backend: str = "nan_api"
) -> dict:
    return {
        "failure_class": "quota_exhausted",
        "failed_backend": backend,
        "failed_profile": profile,
        "ts": datetime.now(timezone.utc).isoformat(),
        "failure_detail": "quota exceeded (account limit)",
    }


def test_085a_cuarentena_vigente_se_declara(tmp_path):
    """D1: la cuarentena vigente se declara EN MEMORIA, jamas via `--sync`."""
    dest = _mkdest(tmp_path / "q_vigente")
    _mk_link(dest)
    _mk_events(dest, [_quota_event()])

    proc = _run(dest, "--json")
    assert proc.returncode == 0, proc.stderr
    q = json.loads(proc.stdout)["quarantine"]
    assert "challenger_nan_qwen" in q["by_profile"], q
    expires_at = q["by_profile"]["challenger_nan_qwen"]["expires_at"]
    assert expires_at

    md = _run(dest).stdout
    assert "challenger_nan_qwen" in md
    assert expires_at in md

    # D1: NUNCA se escribe `backend_quarantine.json` (jamas se invoca --sync).
    assert not (
        dest / ".agent" / "runtime" / "ensemble" / "backend_quarantine.json"
    ).exists()


def test_085a_sin_evento_no_se_declara(tmp_path):
    """D2: sin eventos, no hay cuarentena y se declara "fuente vacia"."""
    dest = _mkdest(tmp_path / "q_sin_evento")
    _mk_link(dest)
    _mk_events(dest, [])

    proc = _run(dest)
    assert proc.returncode == 0, proc.stderr
    assert "fuente vacia (0 eventos)" in proc.stdout
    assert "challenger_nan_qwen" not in proc.stdout
    assert "no medido" not in proc.stdout


def test_085a_fuente_ausente_declara_cero_eventos(tmp_path):
    """D3: sin fichero fuente = 0 eventos (medicion valida), NO "no medido"."""
    dest = _mkdest(tmp_path / "q_ausente")
    _mk_link(dest)

    proc = _run(dest)
    assert proc.returncode == 0, proc.stderr
    assert "fuente vacia (0 eventos)" in proc.stdout
    assert "no medido" not in proc.stdout


def test_085a_subprocess_falla_declara_no_medido(tmp_path, monkeypatch):
    """D3: rc!=0 se declara "no medido", texto DISTINTO de "fuente vacia"."""
    import scripts.collect_session_state as css

    monkeypatch.setattr(
        css,
        "_run",
        lambda *a, **k: {
            "command": "x",
            "exit_code": 3,
            "stdout": "",
            "stderr": "boom",
        },
    )
    q = css.collect_quarantine(MOTOR_ROOT, tmp_path)
    assert q["cause"] == "no medido (rc=3)"
    assert q["by_profile"] == {}
    assert q["by_backend"] == {}

    rep = css.build_report(MOTOR_ROOT, _mkdest(tmp_path / "d"), [])
    md = css.render_markdown(rep)
    assert "no medido (rc=3)" in md
    assert "fuente vacia" not in md


def test_085a_import_ensemble_dispatch_falla(tmp_path):
    """D7 generico: import fallido -> causa declarada y rc GLOBAL = 0."""
    fake_motor = tmp_path / "motor_sin_modulo"
    fake_motor.mkdir()
    dest = _mkdest(tmp_path / "d_modulo")
    _mk_link(dest, motor=fake_motor)

    proc = _run(dest)
    assert proc.returncode == 0, proc.stderr
    assert "cuarentena: modulo no disponible" in proc.stdout


def test_085a_enlace_motor_destino_ausente(tmp_path):
    """D7 especifico: sin enlace resoluble -> mensaje LITERAL y rc GLOBAL = 0."""
    dest = _mkdest(tmp_path / "d_sin_enlace")

    proc = _run(dest)
    assert proc.returncode == 0, proc.stderr
    assert "cuarentena: enlace motor-destino no disponible" in proc.stdout
    assert "modulo no disponible" not in proc.stdout


def test_085a_declara_antiguedad_del_artefacto_en_disco(tmp_path):
    """D4: el artefacto en disco se declara por sha256, nunca se asume vigente."""
    dest = _mkdest(tmp_path / "d_disco")
    _mk_link(dest)
    _mk_events(dest, [_quota_event()])
    (dest / ".agent" / "runtime" / "ensemble" / "backend_quarantine.json").write_text(
        json.dumps(
            {
                "generated_at": "2020-01-01T00:00:00+00:00",
                "fallback_events_sha256": "deadbeef",
            }
        ),
        encoding="utf-8",
    )

    q = json.loads(_run(dest, "--json").stdout)["quarantine"]
    assert q["disk"]["coincide_fuente"] is False

    md = _run(dest).stdout
    assert "coincide_fuente: false" in md
    assert "2020-01-01T00:00:00+00:00" in md


def test_085a_timeout_del_subprocess_no_bloquea_el_arranque(
    tmp_path, monkeypatch, capsys
):
    """D7: timeout/OSError nunca tumba el arranque; rc GLOBAL sigue 0."""
    import scripts.collect_session_state as css

    monkeypatch.setattr(
        css,
        "_run",
        lambda *a, **k: {
            "command": "x",
            "exit_code": None,
            "stdout": "",
            "stderr": "no ejecutable: TimeoutExpired",
        },
    )
    dest = _mkdest(tmp_path / "d_timeout")
    monkeypatch.setattr(
        sys, "argv", ["collect_session_state.py", "--project-root", str(dest)]
    )
    rc = css.main()
    assert rc == 0
    assert "no medido" in capsys.readouterr().out


def test_085a_no_invoca_quarantine_sync(tmp_path, monkeypatch):
    """Forbidden Surface: el recolector JAMAS construye `quarantine --sync`."""
    import scripts.collect_session_state as css

    captured: dict = {}

    def fake(cmd, cwd=None, timeout=120):
        captured["cmd"] = list(cmd)
        return {
            "command": " ".join(cmd),
            "exit_code": 0,
            "stdout": json.dumps(
                {
                    "status": "empty",
                    "cause": None,
                    "by_backend": {},
                    "by_profile": {},
                    "events": 0,
                }
            ),
            "stderr": "",
        }

    monkeypatch.setattr(css, "_run", fake)
    css.collect_quarantine(MOTOR_ROOT, tmp_path)
    cmd = captured["cmd"]
    joined = " ".join(cmd)
    assert "quarantine" not in cmd  # ningun token `quarantine` suelto
    assert "--sync" not in joined
    assert "quarantine --sync" not in joined


def test_085a_timeout_explicito_declarado(tmp_path, monkeypatch):
    """D7/M3: el subprocess lleva un timeout EXPLICITO y bajo, no el default."""
    import scripts.collect_session_state as css

    captured: dict = {}

    def fake(cmd, cwd=None, timeout=120):
        captured["timeout"] = timeout
        return {
            "command": " ".join(cmd),
            "exit_code": 0,
            "stdout": json.dumps(
                {
                    "status": "empty",
                    "cause": None,
                    "by_backend": {},
                    "by_profile": {},
                    "events": 0,
                }
            ),
            "stderr": "",
        }

    monkeypatch.setattr(css, "_run", fake)
    css.collect_quarantine(MOTOR_ROOT, tmp_path)
    assert captured["timeout"] == css.QUARANTINE_TIMEOUT_S
    assert css.QUARANTINE_TIMEOUT_S <= 5


def test_085a_control_negativo_backend_sano_no_se_declara(tmp_path):
    """Con evento presente pero clase no-cuarentenable, no se declara en cuarentena."""
    dest = _mkdest(tmp_path / "d_sano")
    _mk_link(dest)
    _mk_events(
        dest,
        [
            {
                "failure_class": "auth_error",
                "failed_backend": "nan_api",
                "failed_profile": "challenger_nan_qwen",
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        ],
    )

    proc = _run(dest)
    assert proc.returncode == 0, proc.stderr
    assert "challenger_nan_qwen" not in proc.stdout
    assert "fuente vacia" not in proc.stdout


def test_085a_lista_de_veredictos_cerrada_sigue_pasando(tmp_path):
    """La seccion nueva NO declara veredictos: la lista cerrada sigue pasando."""
    from scripts.collect_session_state import FORBIDDEN_VERDICTS

    dest = _mkdest(tmp_path / "d_veredictos")
    _mk_link(dest)
    _mk_events(dest, [_quota_event()])

    for extra in ([], ["--json"]):
        proc = _run(dest, *extra)
        assert proc.returncode == 0, proc.stderr
        blob = proc.stdout.upper()
        for verdict in FORBIDDEN_VERDICTS:
            assert verdict.upper() not in blob, f"veredicto filtrado: {verdict}"


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
