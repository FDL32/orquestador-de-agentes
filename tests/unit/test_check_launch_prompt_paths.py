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
    ABSOLUTE_HINT_RE,
    audit,
    find_stray_prompts,
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
        "contract_id: `cid-bui-implement-v1`\n"
        "- `<DESTINO_ROOT>/.agent/collaboration/work_plan.md` (proyeccion operativa)\n"
        "DoD (a)-(j) del `work_plan.md`, cada uno con evidencia literal.\n"
        "o si `STATE.md` / `work_plan.md` dejan de apuntar al ticket (DRIFT).\n"
        "los artefactos de PROCESO -- `execution_log.md`, `CG-*.md` -- NO cuentan.\n",
    )
    # El fix (b) caza <DESTINO_ROOT> como R2 (placeholder angular sin resolver);
    # no hay R1 porque ninguna linea tiene un verbo de lectura con runtime sin raiz.
    findings = scan_prompt(path)
    assert len(findings) == 1
    assert findings[0].rule == "R2-placeholder"


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
        "contract_id: `cid-bui-implement-v1`\n"
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
        "Eres el BUILDER del ticket `{{TICKET_ID}}`." + NL, encoding="utf-8"
    )
    _prompt(
        tmp_path,
        "builder_prompt_WOT-2026-000d.md",
        "contract_id: `cid-bui-implement-v1`" + NL + "Sin menciones de runtime." + NL,
    )

    findings, prompts = audit(tmp_path)
    assert [p.name for p in prompts] == ["builder_prompt_WOT-2026-000d.md"]
    assert findings == []


NL = chr(10)


def _stray_prompt(root, relpath, body):
    """Escribe un prompt de arranque FUERA de la ubicacion canonica."""
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


BUILDER_PROMPT_BODY = (
    "# Launch Builder Prompt"
    + NL
    + NL
    + "contract_id: cid-bui-implement-v1"
    + NL
    + NL
    + "Registra en `C:/destino/.agent/collaboration/execution_log.md` los gates."
    + NL
)


def test_prompt_de_arranque_fuera_de_la_canonica_es_hallazgo(tmp_path):
    """R3: un prompt de arranque se reconoce por su CONTENIDO, no por su nombre.

    El fallo medido (2026-09-16): un prompt llamado `launch_builder_*.md` en
    `orchestrator_pipeline/reports/` quedaba FUERA del universo del guard, que
    solo miraba `planning/builder_prompt_*.md`. El guard salio VERDE y el
    Builder escribio estado operativo en el seed neutro del motor.

    Ampliar la ENUMERACION de patrones no cierra la clase: un tercer nombre
    evade igual. El discriminante es el `contract_id` del contrato de Builder,
    presente en 10 de 10 prompts reales medidos.
    """
    _stray_prompt(
        tmp_path,
        "orchestrator_pipeline/reports/launch_builder_WOT-2026-999z.md",
        BUILDER_PROMPT_BODY,
    )
    findings, prompts = audit(tmp_path)
    codes = {f.rule for f in findings}
    assert "R3-ubicacion-no-canonica" in codes, (
        "un prompt de arranque fuera de .agent/planning/ debe producir hallazgo; "
        f"hallazgos={[f.rule for f in findings]} prompts={[p.name for p in prompts]}"
    )


def test_prompt_de_arranque_en_la_canonica_no_dispara_r3(tmp_path):
    """CONTROL POSITIVO: el mismo contenido EN su sitio no produce R3.

    Sin este control, un guard que marcara todo pasaria el test de arriba.
    """
    _prompt(tmp_path, "builder_prompt_WOT-2026-999z.md", BUILDER_PROMPT_BODY)
    findings, _prompts = audit(tmp_path)
    codes = {f.rule for f in findings}
    assert "R3-ubicacion-no-canonica" not in codes, (
        f"falso positivo en la ubicacion canonica: {[f.rule for f in findings]}"
    )


def test_fichero_ajeno_fuera_de_la_canonica_no_dispara_r3(tmp_path):
    """CONTROL NEGATIVO: un .md cualquiera NO es un prompt de arranque.

    Sin esto, el guard marcaria cada informe de `reports/` y se volveria ruido.
    """
    _stray_prompt(
        tmp_path,
        "orchestrator_pipeline/reports/AUDIT_algo_20260916.md",
        "# Informe de auditoria" + NL + NL + "No instruye a ningun Builder." + NL,
    )
    findings, _prompts = audit(tmp_path)
    codes = {f.rule for f in findings}
    assert "R3-ubicacion-no-canonica" not in codes, (
        f"un informe corriente no debe disparar R3: {[f.rule for f in findings]}"
    )


def test_el_stray_tambien_se_escanea_por_contenido(tmp_path):
    """El HUECO que cierra WOT-2026-067w-b: a un stray solo se le ponia R3.

    Medido 2026-09-17 (bucle L1018, cazado por la lente BA06 leyendo `audit()`):
    el bucle de `scan_prompt` recorre `prompts` ANTES de que los strays se anadan
    a esa lista, asi que un prompt fuera de la canonica recibia UNICAMENTE el
    hallazgo de ubicacion. Su CONTENIDO no se miraba.

    Consecuencia real, no hipotetica: `launch_builder_016r_20260915.md` (ticket
    VIVO) ordena en su linea 25 `Lee: .agent/collaboration/work_plan.md` -- ruta
    RELATIVA, el defecto R1 exacto que originó esta barrera. El guard lo
    reportaba como simple "ubicacion no canonica"; el defecto grave lo encontro
    una lectura humana. El hallazgo peligroso se presentaba como el mas benigno.

    Este test pinea que un stray recibe AMBAS reglas.
    """
    _stray_prompt(
        tmp_path,
        "orchestrator_pipeline/reports/launch_builder_WOT-2026-998y.md",
        "# Launch Builder Prompt"
        + NL
        + NL
        + "contract_id: cid-bui-implement-v1"
        + NL
        + NL
        + "- Lee: `.agent/collaboration/work_plan.md`, STRATEGY si existe."
        + NL,
    )
    findings, _prompts = audit(tmp_path)
    codes = {f.rule for f in findings}
    assert "R3-ubicacion-no-canonica" in codes, (
        f"el stray debe seguir marcando ubicacion: {[f.rule for f in findings]}"
    )
    assert "R1-ruta-ambigua" in codes, (
        "un stray con runtime SIN raiz debe producir R1 ademas de R3; "
        f"hallazgos={[f.render() for f in findings]}"
    )


def test_el_stray_correcto_no_inventa_r1(tmp_path):
    """CONTROL POSITIVO del test anterior.

    Sin esto, extender `scan_prompt` a los strays podria marcarlos todos y el
    test de arriba pasaria igual. Un stray que SI ancla su ruta recibe R3 (esta
    fuera de sitio) pero NO R1 (su contenido es correcto).
    """
    _stray_prompt(
        tmp_path,
        "orchestrator_pipeline/reports/launch_builder_WOT-2026-997x.md",
        BUILDER_PROMPT_BODY,
    )
    findings, _prompts = audit(tmp_path)
    codes = {f.rule for f in findings}
    assert "R3-ubicacion-no-canonica" in codes, (
        f"sigue estando fuera de sitio: {[f.rule for f in findings]}"
    )
    assert "R1-ruta-ambigua" not in codes, (
        f"falso positivo de R1 sobre un stray correcto: {[f.render() for f in findings]}"
    )


NL = chr(10)


BUILDER_LAUNCH_BODY = (
    "# Launch Builder Prompt"
    + NL
    + NL
    + "contract_id: cid-bui-implement-v1"
    + NL
    + NL
    + "Confirma que `work_plan.md` activo apunta a `WOT-2026-999a`."
    + NL
)


def test_positivo_a_launchnamed_in_planning_entra_al_universo(tmp_path):
    """Control positivo (a): un LAUNCH_BUILDER_*.md en .agent/planning/
    entra al universo auditado via deteccion por contenido.

    Antes del fix (a), solo builder_prompt_*.md entraba via glob; un
    LAUNCH_BUILDER_*.md con el contract_id era invisible por ambas vias.
    """
    planning = tmp_path / ".agent" / "planning"
    planning.mkdir(parents=True)
    path = planning / "LAUNCH_BUILDER_test.md"
    path.write_text(BUILDER_LAUNCH_BODY, encoding="utf-8")

    _, prompts = audit(tmp_path)
    names = [p.name for p in prompts]
    assert "LAUNCH_BUILDER_test.md" in names, (
        f"LAUNCH_BUILDER_*.md con contract_id debe entrar; prompts={[p.name for p in prompts]}"
    )


def test_positivo_b_angular_placeholder_es_hallazgo(tmp_path):
    """Control positivo (b): un metavalor angular sin resolver <MOTOR_ROOT>
    dispara R2 y pierde la exencion de R1.

    Antes del fix (b), PLACEHOLDER_RE solo casaba {{MAYUS}}; los angulares
    <MOTOR_ROOT>, <DESTINO_ROOT>, <MOTOR>, <DESTINO> eran invisibles a R2.
    """
    path = _prompt(
        tmp_path,
        "builder_prompt_WOT-2026-999b.md",
        "Lee: <MOTOR_ROOT>/foo.md\n",
    )
    findings = scan_prompt(path)
    rules = [f.rule for f in findings]
    assert "R2-placeholder" in rules, (
        f"<MOTOR_ROOT> debe disparar R2; reglas={[f.rule for f in findings]}"
    )


def test_control_negativo_ruta_absoluta_windows_no_rompe(tmp_path):
    """Control negativo: una linea con ruta absoluta real
    C:\\Users\\x\\destino\\work_plan.md sigue EXENTA de R1.

    Esta es la unica forma valida de "ruta absoluta" que debe seguir
    satisfaciendo el fix (c).
    """
    path = _prompt(
        tmp_path,
        "builder_prompt_WOT-2026-999c.md",
        "Lee: C:\\Users\\x\\destino\\work_plan.md\n",
    )
    assert scan_prompt(path) == [], (
        f"ruta absoluta Windows debe eximir de R1; hallazgos={[f.render() for f in scan_prompt(path)]}"
    )


def test_control_negativo_motor_template_no_entra(tmp_path):
    """Control negativo: una plantilla del motor con {{DESTINO_ROOT}}
    sigue excluida de find_stray_prompts().

    Rama YA existente, linea ~234 del fichero original. Si una plantilla
    del motor fuera detectada como prompt de arranque, seria un falso rojo
    masivo (22 placeholders en orchestrator_launch_builder.md).
    """
    motor_prompts = tmp_path / "prompts"
    motor_prompts.mkdir()
    motor_path = motor_prompts / "orchestrator_template.md"
    motor_path.write_text(
        "Eres el BUILDER del ticket `{{TICKET_ID}}`." + NL, encoding="utf-8"
    )
    _prompt(
        tmp_path, "builder_prompt_WOT-2026-999d.md", "Sin menciones de runtime." + NL
    )

    _, prompts = audit(tmp_path)
    assert motor_path not in prompts, (
        "plantilla con {{...}} no debe entrar al universo auditado"
    )


def test_control_angular_r1pierde_exencion(tmp_path):
    """Control del fix (c): un metavalor angular ya no exime de R1.

    Antes del fix, <DESTINO_ROOT>/.agent/collaboration/work_plan.md
    eximia de R1 (falso positivo). Despues del fix, debe perder la
    exencion -- aunque en este caso especifico, "Lee:" con un path no
    es runtime file, asi que no genera R1 de todos modos. Lo que importa
    es la estructura del patron: ya no casan los angulares.
    """
    assert "DESTINO_ROOT" not in ABSOLUTE_HINT_RE.pattern, (
        "ABSOLUTE_HINT_RE no debe contener <DESTINO_ROOT>"
    )
    assert (
        "destino" not in ABSOLUTE_HINT_RE.pattern
        or "Windows" in ABSOLUTE_HINT_RE.pattern
    ), "ABSOLUTE_HINT_RE no debe contener <destino>"


def test_el_verbo_no_se_pierde_por_su_puntuacion(tmp_path):
    """El AGUJERO DE UN CARACTER (medido 2026-09-17).

    `_READ_VERBS` contenia `"lee "` -- con espacio final. Eso casaba
    ``Lee `work_plan.md` `` pero NO ``Lee: `work_plan.md` ``, que es exactamente
    la forma del defecto VIVO de `launch_builder_016r_20260915.md:25`. Tres de
    cinco formas imperativas reales se escapaban por su puntuacion.

    Pinea las DOS direcciones: la orden con dos puntos se caza, y la palabra
    que solo CONTIENE el verbo (`leemos`, prosa) sigue sin cazarse -- sin ese
    segundo extremo, acortar el verbo habria reabierto los falsos positivos que
    el barrido de 2026-09-10 cerro.
    """
    ordenes = (
        "- Lee: `work_plan.md` antes de nada.",
        "Leer: `STATE.md` del destino.",
        "- Lee:`TURN.md`",
        "- Lee `execution_log.md`",
    )
    for linea in ordenes:
        path = _prompt(tmp_path, "builder_prompt_WOT-2026-996w.md", linea + NL)
        findings = scan_prompt(path)
        assert [f.rule for f in findings] == ["R1-ruta-ambigua"], (
            f"orden no cazada por su puntuacion: {linea!r} -> "
            f"{[f.render() for f in findings]}"
        )

    prosa = "Cuando leemos `work_plan.md` conviene mirar la fecha."
    path = _prompt(tmp_path, "builder_prompt_WOT-2026-995v.md", prosa + NL)
    assert scan_prompt(path) == [], (
        f"falso positivo sobre prosa: {[f.render() for f in scan_prompt(path)]}"
    )


# Extracto LITERAL (lineas 1-6 y 50-58) del fichero real de destino
# builder_prompt_WOT-2026-062e.md, tal como existia en
# .agent/planning/ del workspace en el momento de WOT-2026-068s. Embebido
# para que la mutacion no dependa de un worktree de sesion efimero (regla
# "CLI barrier must be hermetic": un test de CLI/guard necesita su propio
# fixture, no el estado vivo externo).
_FIXTURE_62E_EXCERPT = (
    "# BUILDER -- WOT-2026-062e (telemetria de entorno de corrida)"
    + NL
    + NL
    + "Eres el **rol BUILDER** del ticket `WOT-2026-062e` en el motor `orquestador_de_agentes`."
    + NL
    + NL
    + "Skill canonica: `skills/builder-implement-from-plan/SKILL.md`"
    + NL
    + "contract_id: `cid-bui-implement-v1`"
    + NL
    + NL
    + "**Verifica ademas que el runtime esta bootstrappeado para ESTE ticket:**"
    + NL
    + NL
    + "- `<DESTINO>/.agent/collaboration/work_plan.md` activo apunta a `WOT-2026-062e`;"
    + NL
    + "- `<DESTINO>/.agent/collaboration/STATE.md` dice `ACTIVE_TICKET: WOT-2026-062e`;"
    + NL
    + "- `<DESTINO>/.agent/collaboration/TURN.md` dice `ROL: BUILDER`;"
    + NL
    + "- el bus (`<DESTINO>/.agent/runtime/events/events.jsonl`) no describe otro ticket activo."
    + NL
)


def test_fixture_62e_line55_angular_placeholder_sin_resolver(tmp_path):
    """Mutation obligatoria WOT-2026-068s: un extracto LITERAL del fichero
    real de destino builder_prompt_WOT-2026-062e.md tiene
    `<DESTINO>/.agent/...` SIN ruta absoluta resuelta -- el placeholder
    angular sin expandir que el probe de la ficha encontro con 0 hallazgos.

    Antes del fix, este extracto daba 0 hallazgos (invisible a R1 por la
    exencion erronea de <DESTINO_ROOT>/<destino> y a R2 por PLACEHOLDER_RE
    ciego a angulares). Despues del fix, >= 1 hallazgo.
    """
    fixture_dst = tmp_path / ".agent" / "planning" / "builder_prompt_WOT-2026-062e.md"
    fixture_dst.parent.mkdir(parents=True, exist_ok=True)
    fixture_dst.write_text(_FIXTURE_62E_EXCERPT, encoding="utf-8")

    findings, prompts = audit(tmp_path)
    assert len(prompts) >= 1, (
        f"el fixture debe entrar al universo; prompts={[p.name for p in prompts]}"
    )
    findings_on_fixture = [
        f for f in findings if f.path.name == "builder_prompt_WOT-2026-062e.md"
    ]
    assert len(findings_on_fixture) >= 1, (
        f"el extracto con <DESTINO> sin resolver debe producir >= 1 hallazgo; "
        f"hallazgos={[f.render() for f in findings_on_fixture]}"
    )


def test_stray_con_angular_sin_resolver_no_se_confunde_con_plantilla(tmp_path):
    """Regresion encontrada por el Manager al ampliar PLACEHOLDER_RE (b).

    find_stray_prompts() excluye del universo cualquier .md que "parezca
    plantilla del motor" -- originalmente, esa decision usaba el MISMO
    PLACEHOLDER_RE que (b) acaba de ampliar con la familia angular. Si se
    reusara sin cambios, un stray real (fuera de .agent/planning/) con un
    `<DESTINO>` sin resolver pasaria a ser tratado como "plantilla" y
    desaparecer -- exactamente la clase de arranque roto que esta ficha
    existe para cazar. find_stray_prompts debe seguir usando SOLO la forma
    `{{MAYUS}}` para esa clasificacion (constante dedicada
    `_TEMPLATE_PLACEHOLDER_RE`, mas estrecha que PLACEHOLDER_RE).
    """
    stray_dir = tmp_path / "orchestrator_pipeline" / "arranques"
    stray_dir.mkdir(parents=True)
    path = stray_dir / "ARRANQUE_stray_test.md"
    path.write_text(
        "contract_id: cid-bui-implement-v1"
        + NL
        + NL
        + "Lee: <DESTINO>/.agent/collaboration/work_plan.md"
        + NL,
        encoding="utf-8",
    )

    strays = find_stray_prompts(tmp_path)
    assert [p.name for p in strays] == ["ARRANQUE_stray_test.md"], (
        f"un stray con <DESTINO> sin resolver debe seguir detectandose como stray; "
        f"strays={[p.name for p in strays]}"
    )
