"""Contract tests for the DEDUPE clause of step 8 (own follow-ups) in
`prompts/orchestrator_session_close_full_audit.md` (WOT-2026-047w).

Que protege
-----------
El paso 8 -- el alta de los follow-ups que genera la PROPIA sesion -- tenia gate
de evidencia pero NINGUNA clausula de deduplicacion, mientras su hermano 8.bis
(fusion del `backlog_inbox/`) SI hacia un barrido de tres superficies con lectura
completa. Es decir: la via mas frecuente para fichar hallazgos era exactamente la
que no comprobaba si el hallazgo ya estaba fichado.

Medido 2026-08-03 (lector-FS del bucle L700, nonce 9fd7ad51) y re-verificado el
2026-08-05: un grep de `dedup|duplic|find_similar` sobre la linea del paso 8
devolvia 0 hits; sobre la de 8.bis, >=1.

Por que un test de PROSA y no un guard ejecutable
--------------------------------------------------
NON-GOAL explicito de la ficha: no se construye un guard de duplicado semantico
automatico. El bucle establecio que el dedupe es NORMA asistida por
`find_similar_signals.py` (generador de SENAL, nunca veredicto). Ningun guard del
arbol caza un duplicado semantico: `check_backlog_contract.py` solo detecta ids
EXACTOS, asi que dos ids distintos con el mismo contenido pasan. Lo unico
fijable de forma barata y con dientes es que la NORMA este escrita y remita a un
unico criterio.

Fixture CONCRETO (exigido por el DoD (b), no "equivalente a juicio")
--------------------------------------------------------------------
El test no juzga similitud: ancla nombres literales que deben aparecer en el
prompt -- la ficha existente `memory_upload.md:18-52` (donde se escribio la
leccion del incidente fundacional) y las tres superficies del barrido -- y exige
las TRES marcas de salida EXACTAS del vocabulario cerrado
(`YA CUBIERTO` / `AMPLIAR` / `SIN VECINOS`).

Mutacion que lo pone en ROJO (DoD: "retirar el barrido del paso 8")
-------------------------------------------------------------------
  borrar la clausula DEDUPE del paso 8   -> ROJO en
    test_step8_requires_dedupe_over_three_surfaces
  borrar las marcas de salida exactas    -> ROJO en
    test_step8_declares_exact_dedupe_verdicts
  duplicar el criterio en vez de remitir -> ROJO en
    test_step8_points_to_single_criterion_instead_of_redeclaring

Par de exit-codes del revert, en el formato obligatorio del Paso 3 de
`prompts/manager_review.md` (medido 2026-08-05 sobre HEAD 8f4c423; la mutacion
retira el bloque "DEDUPE OBLIGATORIO" del paso 8 y restaura despues)::

    mutation-verify:
      sin_fix:  command: python -m pytest tests/unit/test_step8_followup_dedupe_contract.py -q   exit_code: 1   # 4 failed, 5 passed
      con_fix:  command: python -m pytest tests/unit/test_step8_followup_dedupe_contract.py -q   exit_code: 0   # 9 passed

Los 5 que sobreviven a la mutacion son los de CONTROL (8.bis intacto + el flujo
ejecutable), y esa asimetria es la prueba de aislamiento: si cayeran TODOS, el
test estaria midiendo el fichero entero y no la clausula.

Before / During / After
-----------------------
Before: el prompt existe en `<motor>/prompts/`.
During: se lee en UTF-8 y se aisla el bloque del paso 8 (desde la linea que
    empieza por "8. Con `--session-close`" hasta "8.bis"). Sin red, sin
    subprocess, sin escritura.
After: exit 0 sii el paso 8 declara el dedupe de tres superficies, remite al
    criterio unico de 8.bis y fija las tres marcas de salida. No muta nada.
"""

from pathlib import Path

import pytest


MOTOR_ROOT = Path(__file__).resolve().parents[2]
PROMPT = MOTOR_ROOT / "prompts" / "orchestrator_session_close_full_audit.md"

# Fixture CONCRETO: las tres superficies que el barrido de 8.bis cubre.
THREE_SURFACES = (
    "backlog.md",
    "_archive/backlog_done.md",
    "observations.YYYY-MM.jsonl",
)

# Vocabulario CERRADO de salida del dedupe (DoD (b): salida EXACTA).
EXACT_VERDICTS = ("YA CUBIERTO", "AMPLIAR", "SIN VECINOS")


def _read_prompt() -> str:
    assert PROMPT.is_file(), f"prompt canonico ausente: {PROMPT}"
    return PROMPT.read_text(encoding="utf-8")


def _step8_block(text: str) -> str:
    """Aisla el bloque del paso 8, excluyendo el bloque de 8.bis.

    Ancla al inicio literal del paso 8 y corta en el ENCABEZADO de 8.bis, para
    que un test del paso 8 NUNCA pase por lo que declara su hermano -- que es
    justamente el hueco que este ticket cierra.

    El corte usa el encabezado real de la seccion (`8.bis FUSIoN`) y NO la
    subcadena "8.bis" a secas: el propio paso 8 REMITE a 8.bis por nombre (DoD
    (c)), asi que cortar en la primera aparicion truncaba el bloque en la
    remision y dejaba fuera las clausulas que este test debe leer.
    """
    start = text.find("8. Con `--session-close`")
    assert start != -1, "no se encontro el inicio del paso 8 en el prompt"
    end = text.find("\n8.bis FUSIoN", start)
    assert end != -1, "no se encontro el encabezado de la seccion 8.bis"
    block = text[start:end]
    assert block.strip(), "el bloque del paso 8 quedo vacio"
    return block


def test_step8_requires_dedupe_over_three_surfaces() -> None:
    """El paso 8 exige el barrido, y sobre las TRES superficies nombradas."""
    block = _step8_block(_read_prompt())

    assert "DEDUPE" in block, (
        "el paso 8 no menciona DEDUPE: es el agujero de WOT-2026-047w "
        "(la via mas frecuente de alta era la que no deduplicaba)"
    )

    missing = [s for s in THREE_SURFACES if s not in block]
    assert not missing, (
        f"el dedupe del paso 8 no nombra estas superficies: {missing}. "
        "El barrido debe cubrir las MISMAS tres que 8.bis; medido 2026-07-22, "
        "deduplicar solo contra el archive de memoria dejo pasar un duplicado."
    )


def test_step8_declares_exact_dedupe_verdicts() -> None:
    """Las tres marcas de salida son EXACTAS, no 'equivalentes a juicio'."""
    block = _step8_block(_read_prompt())

    missing = [v for v in EXACT_VERDICTS if v not in block]
    assert not missing, (
        f"faltan marcas de salida exactas del dedupe: {missing}. "
        "Sin vocabulario cerrado, 'he deduplicado' no es verificable: en el "
        "incidente fundacional (2026-07-22) TRES de los cuatro duplicados "
        "declaraban haber buscado duplicados."
    )


def test_step8_points_to_single_criterion_instead_of_redeclaring() -> None:
    """El criterio vive en UN solo sitio (8.bis) y el paso 8 REMITE a el.

    DoD (c). Si el paso 8 redeclarase el criterio, tendriamos dos copias que
    pueden divergir -- el defecto que este repo persigue como
    'skill apunta, prompt gobierna' aplicado dentro del mismo prompt.
    """
    block = _step8_block(_read_prompt())

    assert "8.bis" in block, (
        "el paso 8 no remite a 8.bis: el criterio debe vivir UNA vez y "
        "el paso 8 apuntar a el, no redeclararlo"
    )
    assert "prevalece 8.bis" in block, (
        "falta la regla de precedencia explicita ('prevalece 8.bis'): sin ella, "
        "una divergencia futura entre ambos no tiene arbitro"
    )


def test_step8_records_that_no_guard_catches_semantic_duplicates() -> None:
    """La norma declara su propio limite: ningun guard caza esto.

    NON-GOAL de la ficha. Que quede escrito evita que una sesion futura asuma
    que `check_backlog_contract.py` la cubre -- solo detecta ids EXACTOS.
    """
    block = _step8_block(_read_prompt())
    assert "check_backlog_contract.py" in block and "id EXACTO" in block, (
        "el paso 8 debe declarar que ningun guard caza el duplicado SEMANTICO "
        "(check_backlog_contract solo mira ids exactos); si no, la norma se "
        "confunde con una barrera"
    )


@pytest.mark.parametrize("surface", THREE_SURFACES)
def test_8bis_still_declares_the_same_surfaces(surface: str) -> None:
    """Control: 8.bis conserva el criterio original.

    Si este test cae, el paso 8 no gano dedupe: es 8.bis quien lo PERDIO, y el
    remite del paso 8 apuntaria a un criterio inexistente.
    """
    text = _read_prompt()
    start = text.find("8.bis")
    end = text.find("8.ter", start)
    assert start != -1 and end != -1, "no se pudo aislar el bloque 8.bis"
    assert surface in text[start:end], (
        f"8.bis dejo de nombrar la superficie {surface!r}: el paso 8 remite a "
        "un criterio que ya no declara lo que promete"
    )


# ---------------------------------------------------------------------------
# DoD (b) PROPIAMENTE DICHO: fixture CONCRETO + flujo EJECUTADO + salida EXACTA.
#
# Los tests de arriba fijan la NORMA (que la clausula exista y remita a un unico
# criterio). Eso NO es el DoD (b): un test que grepea prosa no asevera "una
# salida del flujo". Blocker #1 del MANAGER REVIEW (codex, nonce ba348ceb).
#
# Este bloque ejecuta el flujo real -- `find_similar_signals.py`, la ayuda
# mecanica que la clausula DEDUPE nombra -- con un candidato NOMBRADO contra una
# ficha existente NOMBRADA, y asevera el veredicto EXACTO que el paso 8 obliga a
# emitir. El fixture esta fijado en el test, no juzgado "por equivalencia".
# ---------------------------------------------------------------------------

# Ficha EXISTENTE nombrada (vive en la cola viva del destino).
FIXTURE_EXISTING_TICKET = "WOT-2026-047w"

# Candidato de follow-up NOMBRADO: reformulacion del MISMO hallazgo que ya
# ficha 047w. Un dedupe correcto debe reconocerlo y NO dar de alta fila nueva.
FIXTURE_CANDIDATE = (
    "EL ALTA DE FOLLOW-UPS PROPIOS (PASO 8) NO TIENE DEDUP: el paso 8 del "
    "cierre no comprueba si el follow-up ya estaba fichado, a diferencia de "
    "8.bis que si barre tres superficies."
)


def _resolve_live_backlog() -> Path | None:
    """Localiza el `backlog.md` del destino de forma PORTABLE.

    Via `AGENT_PROJECT_ROOT` o `motor_destination_link.json`, NUNCA por nombre
    de directorio fijo: el motor es agnostico del destino (`manager_review.md`
    Paso 1b). Devuelve None si no hay destino resoluble -> el test se salta,
    porque su objeto es el flujo, no la instalacion.
    """
    import json
    import os

    env = os.environ.get("AGENT_PROJECT_ROOT")
    candidates = []
    if env:
        candidates.append(Path(env))

    # El link vive en el DESTINO, no en el motor. Sin AGENT_PROJECT_ROOT hay que
    # descubrir el destino: se buscan hermanos del motor que declaren un link
    # cuyo `motor_root` apunte de vuelta a este motor (relacion bidireccional
    # verificada, no un nombre de directorio adivinado).
    for sibling in MOTOR_ROOT.parent.iterdir():
        if not sibling.is_dir() or sibling == MOTOR_ROOT:
            continue
        link = sibling / ".agent" / "config" / "motor_destination_link.json"
        if not link.is_file():
            continue
        try:
            data = json.loads(link.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        declared = data.get("motor_root")
        if not declared or Path(declared).resolve() != MOTOR_ROOT.resolve():
            continue
        # Un mismo motor puede servir a VARIOS destinos (medido: uno con prefijo
        # WOT y otro con CTL). El fixture de este test vive en la cola del
        # destino cuyo `ticket_prefix` es WOT; elegir "el primero que aparezca"
        # haria el test dependiente del orden del filesystem.
        if data.get("ticket_prefix") == FIXTURE_EXISTING_TICKET.split("-")[0]:
            candidates.append(sibling)

    for root in candidates:
        backlog = root / ".agent" / "collaboration" / "backlog.md"
        if backlog.is_file():
            return backlog
    return None


def test_dedupe_flow_emits_ya_cubierto_for_a_known_duplicate() -> None:
    """DoD (b): el flujo REAL sobre un candidato duplicado nombra la ficha viva.

    Ejecuta `find_similar_signals.py` -- la ayuda mecanica que la clausula
    DEDUPE nombra -- con el candidato fijado arriba contra el backlog vivo, y
    exige que `WOT-2026-047w` salga como vecino de MAYOR score. Ese es el hit
    que obliga al operador a emitir `[DEDUPE: YA CUBIERTO por WOT-2026-047w ...]`
    en vez de dar de alta una fila nueva.

    NO se asevera un veredicto emitido por el script: el script genera SENAL y
    NUNCA veredicto (NON-GOAL de la ficha). Lo que se asevera es que la senal
    IDENTIFICA la ficha correcta -- sin eso, la norma del paso 8 seria
    inaplicable en la practica.
    """
    import json
    import subprocess
    import sys

    backlog = _resolve_live_backlog()
    if backlog is None:
        pytest.skip(
            "no hay destino resoluble (AGENT_PROJECT_ROOT / link): "
            "el flujo necesita un backlog vivo"
        )

    script = MOTOR_ROOT / "scripts" / "find_similar_signals.py"
    assert script.is_file(), f"ayuda mecanica ausente: {script}"

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--text",
            FIXTURE_CANDIDATE,
            "--backlog",
            str(backlog),
            "--top",
            "3",
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"el generador de senal debe salir 0 SIEMPRE (con o sin vecinos); "
        f"rc={proc.returncode} stderr={proc.stderr[:300]}"
    )

    payload = json.loads(proc.stdout)
    neighbours = payload.get("neighbours") or []
    assert neighbours, (
        "el flujo no devolvio NINGUN vecino para un candidato que reformula un "
        f"hallazgo YA fichado como {FIXTURE_EXISTING_TICKET}: el dedupe del "
        "paso 8 seria inaplicable y el duplicado entraria"
    )

    top = neighbours[0]
    assert top.get("label") == FIXTURE_EXISTING_TICKET, (
        f"el vecino de mayor score fue {top.get('label')!r}, se esperaba "
        f"{FIXTURE_EXISTING_TICKET!r}. Sin este hit, un operador que aplique la "
        "clausula DEDUPE del paso 8 concluiria SIN VECINOS y daria de alta un "
        "duplicado -- exactamente el incidente de 2026-07-22."
    )
    assert top.get("score", 0) > 0, "score no positivo: la senal no discrimina"


def test_dedupe_flow_reports_its_own_denominator() -> None:
    """El flujo publica CUANTO escaneo: un probe sin denominador no cuenta.

    Norma del repo ("un probe que no publica su denominador no cuenta"). Si el
    dedupe barriera 0 filas, `SIN VECINOS` seria verdadero y vacio a la vez.
    """
    import json
    import subprocess
    import sys

    backlog = _resolve_live_backlog()
    if backlog is None:
        pytest.skip("no hay destino resoluble (AGENT_PROJECT_ROOT / link)")

    proc = subprocess.run(
        [
            sys.executable,
            str(MOTOR_ROOT / "scripts" / "find_similar_signals.py"),
            "--text",
            FIXTURE_CANDIDATE,
            "--backlog",
            str(backlog),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    payload = json.loads(proc.stdout)
    assert payload.get("scanned", 0) > 0, (
        "el flujo declara scanned=0: estaria deduplicando contra la nada"
    )
    assert payload.get("coverage"), "el flujo no declara que superficies cubrio"
