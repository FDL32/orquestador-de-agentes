"""Tests del filtro de RUIDO sobre la salida de una lente (WOT-2026-027o).

Fija los dos huecos MEDIDOS sobre revisiones REALES de la sesion anterior:
  - FABRICACION: reviews que citan ficheros/commits/variables inexistentes.
  - ANCLAJE: cita REAL + veredicto de CONFIRMACION -> no es aportacion.

El caso de ANCLAJE es el que ningun filtro de "exige fichero:linea" detecta,
porque el puntero SI resuelve. Por eso los dos mecanismos son independientes y
la mutation (DoD (d)) los ataca por separado.

Hermetico: todo corre contra `tmp_path`, sin red y sin tocar el arbol.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]


def _load_filter():
    path = _MOTOR_ROOT / "scripts" / "filter_lens_output.py"
    spec = importlib.util.spec_from_file_location("filter_lens_output", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["filter_lens_output"] = module
    spec.loader.exec_module(module)
    return module


flo = _load_filter()


def _receipt(path: str, *, verdict: str) -> str:
    """Salida de lente con bloque ```receipt (el schema que valida el reuso)."""
    return (
        f"{verdict}\n\n"
        "```receipt\n"
        "command: python -m pytest tests/unit/test_x.py\n"
        "exit_code: 0\n"
        f"path: {path}\n"
        "```\n"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Arbol minimo con UN fichero real que las lentes pueden citar."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "real_module.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def test_027o_dod_a_fabricated_citation_is_discarded(repo: Path):
    """DoD (a): cita FABRICADA -> descartada, con reason y exit code.

    Reproduce la fabricacion MEDIDA: la lente cito `tests/test_transport.py`,
    un fichero que no existe en el arbol que decia revisar.
    """
    text = _receipt("tests/test_transport.py", verdict="El transporte falla porque X.")
    accepted, reason, problems = flo.filter_lens_output(text, repo)

    assert accepted is False
    assert reason == "fabricated_citation"
    assert any("does not resolve" in p for p in problems), problems


def test_027o_dod_a_citation_escaping_root_is_discarded(repo: Path):
    """DoD (a): una cita que ESCAPA del root tampoco vale.

    Sin esto, `../../otro_repo/fichero.py` podria existir en la maquina y dar
    un falso verde de wrong-root.
    """
    text = _receipt("../fuera_del_repo.py", verdict="Hay un bug real aqui.")
    accepted, reason, _ = flo.filter_lens_output(text, repo)

    assert accepted is False
    assert reason == "fabricated_citation"


def test_027o_dod_b_real_citation_but_confirmation_is_not_a_contribution(repo: Path):
    """DoD (b): cita REAL + veredicto de CONFIRMACION -> no-aportacion.

    Este es el caso de ANCLAJE medido: qwen y gemma citaron la linea CORRECTA
    y aun asi abrieron con "Confirmado". El puntero resuelve, asi que la
    verificacion de cita (mecanismo 1) lo deja pasar: lo caza la clasificacion
    de forma (mecanismo 2).
    """
    text = _receipt(
        "scripts/real_module.py", verdict="Confirmado, la premisa es correcta."
    )
    accepted, reason, _ = flo.filter_lens_output(text, repo)

    assert accepted is False
    assert reason == "confirmation_no_objection"


def test_027o_dod_c_objection_with_real_citation_passes(repo: Path):
    """DoD (c): objecion + cita real -> PASA. Es la unica salida que aporta."""
    text = _receipt(
        "scripts/real_module.py",
        verdict="Incorrecto: la premisa es falsa, el modulo no hace lo que dices.",
    )
    accepted, reason, problems = flo.filter_lens_output(text, repo)

    assert accepted is True, (reason, problems)
    # WOT-2026-039c renombra el reason de aceptacion a 'accepted' (el enum de
    # 4 razones del contrato). Cambio DECLARADO en el CF-audit (O7), no deriva.
    assert reason == "accepted"


def test_027o_objection_after_polite_opening_is_still_an_objection(repo: Path):
    """Anti-falso-positivo: la cortesia previa no convierte una objecion en
    confirmacion. Sin esto, el filtro descartaria aportacion legitima -- y un
    filtro que descarta trabajo bueno ensena al operador a apagarlo."""
    text = _receipt(
        "scripts/real_module.py",
        verdict="De acuerdo en el diagnostico general, pero el fix es incorrecto.",
    )
    accepted, _, _ = flo.filter_lens_output(text, repo)

    assert accepted is True


def test_027o_output_without_receipt_is_discarded(repo: Path):
    """Una afirmacion SIN recibo NI cita no es un probe: no puede verificarse.

    WOT-2026-039c afina la RAZON: prosa sin ningun bloque verificable ya no es
    'fabricated_citation' (no hay cita que fabricar) sino 'no_contribution'
    con el problema 'missing_cite_block'. Es el H10 medido: las lentes
    responden prosa y el diagnostico antiguo confundia "no cumple el schema"
    con "minti sobre una cita".
    """
    accepted, reason, problems = flo.filter_lens_output("Hay un bug, creeme.", repo)

    assert accepted is False
    assert reason == "no_contribution"
    assert any(p.startswith("missing_cite_block") for p in problems), problems


def _cite(path: str, line: int, quote: str, *, verdict: str) -> str:
    """Salida de lente con bloque ```cite (schema lens-answer/v1, 039c)."""
    return f"{verdict}\n\n```cite\npath: {path}\nline: {line}\nquote: {quote}\n```\n"


@pytest.fixture
def cite_repo(tmp_path: Path) -> Path:
    """Arbol con un fichero de contenido conocido para verificar quotes."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "real_module.py").write_text(
        "import os\nDEFAULT_ENCODING = 'utf-8'\ndef run():\n    return 42\n",
        encoding="utf-8",
    )
    return tmp_path


def test_039c_missing_cite_block_is_no_contribution(cite_repo: Path):
    """DoD (b): salida sin bloque cite -> no_contribution/missing_cite_block.

    Es H10 medido: las 6 salidas del bucle de cierre eran prosa sin schema.
    Sin contrato de salida DEFINIDO el filtro no tiene sobre que morder.
    """
    accepted, reason, problems = flo.filter_lens_output(
        "La funcion falla porque no valida el encoding.", cite_repo, cite_only=True
    )

    assert accepted is False
    assert reason == "no_contribution"
    assert any(p.startswith("missing_cite_block") for p in problems), problems


def test_039c_h7_neutral_noise_is_not_an_objection(cite_repo: Path):
    """H7: ruido NEUTRO -> 'neutral' -> no-aportacion.

    Antes el default del clasificador era 'objection', asi que una salida sin
    marcador ninguno se contaba como aportacion: fail-open del clasificador de
    forma (obs-clasificador-de-forma-fail-open-acepta-ruido-neutro).
    """
    assert flo.classify_verdict("El fichero usa utf-8 al abrir.") == "neutral"

    text = _cite(
        "scripts/real_module.py",
        2,
        "DEFAULT_ENCODING",
        verdict="El fichero declara su encoding en una constante.",
    )
    accepted, reason, _ = flo.filter_lens_output(text, cite_repo, cite_only=True)

    assert accepted is False
    assert reason == "no_contribution"


def test_039c_h8_negated_marker_is_not_an_objection(cite_repo: Path):
    """H8: la NEGACION ya no invierte el filtro.

    'Confirmado: no hay bug' matchea el marcador 'bug' y salia como objecion,
    que es lo CONTRARIO de lo que dice. Es el caso peligroso: una confirmacion
    disfrazada de aportacion.
    """
    assert flo.classify_verdict("Confirmado: no hay bug aqui") != "objection"

    text = _cite(
        "scripts/real_module.py",
        4,
        "return 42",
        verdict="Confirmado: no hay bug en el valor de retorno.",
    )
    accepted, reason, _ = flo.filter_lens_output(text, cite_repo, cite_only=True)

    assert accepted is False
    assert reason in ("confirmation_no_objection", "no_contribution")


@pytest.mark.parametrize(
    ("expected", "text"),
    [
        # El negador niega OTRA cosa: el marcador NO esta negado.
        ("objection", "No valida el encoding, por eso el modulo falla."),
        ("objection", "Sin validacion previa, el codigo es incorrecto."),
        ("objection", "Ningun test cubre esa rama: hay un bug."),
        ("objection", "El fix no funciona: la premisa es falsa."),
        ("objection", "Incorrecto: no hay validacion de entrada."),
        # El negador SI niega al marcador (adyacente).
        ("confirmation", "Confirmado: no hay bug aqui."),
        ("confirmation", "Confirmado, no hay ningun riesgo."),
        ("neutral", "No encuentro problemas."),
    ],
)
def test_039c_h8_negation_window_does_not_eat_legit_objections(
    expected: str, text: str
):
    """El supresor de negados NO puede desclasificar objeciones legitimas.

    FALSO POSITIVO MEDIDO 2026-07-22 antes de cerrar el ticket: la primera
    version suprimia TODO marcador tras el primer negador hasta el fin de la
    oracion, asi que "No valida el encoding, por eso el modulo falla" (el
    negador niega 'valida'; el marcador 'falla' NO esta negado) salia
    'neutral' y se descartaba. Un filtro que descarta trabajo bueno ensena al
    operador a apagarlo, y un filtro apagado no es barrera -- por eso este
    caso vale tanto como los de descarte.

    La correccion fue acotar la negacion a una VENTANA de adyacencia; estos
    fixtures fijan ambos lados del limite para que no pueda revertirse en
    silencio.
    """
    assert flo.classify_verdict(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "No parece haber bug",
        "No creo que exista un bug",
    ],
)
def test_039c_h8_inverse_false_positive_is_pinned(text: str):
    """La ventana MUEVE un falso positivo, no solo lo reduce (medido).

    Estas son NEGACIONES que salen clasificadas como objecion porque la
    distancia negador-marcador (14 y 17 chars) excede _NEGATION_WINDOW. Con la
    version anterior (suprimir hasta fin de oracion) salian 'neutral'.

    Se PINNEA la direccion que el residuo original NO declaraba. El coste es
    asimetrico y por eso se acepta: este lado gasta trabajo del brazo caro, el
    defecto original PERDIA aportacion legitima. Si algun dia se cierra, este
    test cae y obliga a actualizar WOT-2026-039e -- cambio consciente, no deriva.
    """
    assert flo.classify_verdict(text) == "objection"


@pytest.mark.parametrize(
    "text",
    [
        "El guard no muerde, contradice lo que afirma el docstring",
        "No cierra H9, en realidad el receipt sigue vivo",
    ],
)
def test_039c_h8_residual_false_positive_is_pinned_not_hidden(text: str):
    """RESIDUO DECLARADO del mecanismo H8 (WOT-2026-039e), no defecto oculto.

    La ventana de adyacencia es una heuristica POSICIONAL, no de alcance
    sintactico: un negador que gobierna otro sujeto pero cae cerca de un
    marcador legitimo sigue suprimiendolo. Cerrar el resto exige analisis
    sintactico, que la STOP condition del contrato PROHIBE.

    Este test PINNEA el limite conocido con casos medidos por el brazo
    lector-con-filesystem del MANAGER_REVIEW (2026-07-22). Si algun dia
    clasifican bien, este test cae y obliga a actualizar la declaracion: es
    un cambio de contrato consciente, nunca una deriva silenciosa. Mitigante
    vivo: la salida descartada se APPENDEA con discarded_reason -- auditable
    y recuperable, no se pierde.
    """
    assert flo.classify_verdict(text) == "neutral"


def test_039c_h8_sin_embargo_is_still_an_objection(cite_repo: Path):
    """Anti-falso-positivo de H8: 'sin embargo' es un MARCADOR, no una
    negacion. El negador 'sin' no debe desactivarlo -- si lo hiciera, el fix
    de H8 descartaria objeciones legitimas (caso borde del CF-audit)."""
    assert flo.classify_verdict("Sin embargo, el valor de retorno es erroneo.") == (
        "objection"
    )


def test_039c_h9_fabricated_execution_receipt_is_not_a_cite(cite_repo: Path):
    """H9: un receipt de EJECUCION emitido por una lente SIN filesystem no
    puede verificarse. En modo cite_only se IGNORA como prosa: la salida se
    descarta por no traer cite, no se acepta por traer un receipt inventado.
    """
    text = _receipt("scripts/real_module.py", verdict="Hay un bug incorrecto aqui.")
    accepted, reason, problems = flo.filter_lens_output(text, cite_repo, cite_only=True)

    assert accepted is False
    assert reason == "no_contribution"
    assert any(p.startswith("missing_cite_block") for p in problems), problems


def test_039c_fabricated_quote_at_real_line_is_discarded(cite_repo: Path):
    """La linea EXISTE pero no dice lo que la lente afirma -> descartada.

    Este es el salto sobre 027o: alli bastaba que el PATH resolviera. Aqui se
    verifica el CONTENIDO de la linea citada, que es lo que convierte la cita
    en evidencia y no en un puntero decorativo.
    """
    text = _cite(
        "scripts/real_module.py",
        2,
        "mock_subprocess",
        verdict="Incorrecto: el modulo parchea subprocess.",
    )
    accepted, reason, problems = flo.filter_lens_output(text, cite_repo, cite_only=True)

    assert accepted is False
    assert reason == "fabricated_citation"
    assert any("quote not found" in p for p in problems), problems


def test_039c_short_quote_is_rejected(cite_repo: Path):
    """Un quote de 1-2 caracteres casaria con cualquier linea: sello de goma."""
    text = _cite(
        "scripts/real_module.py", 2, "=", verdict="Incorrecto: hay un bug aqui."
    )
    accepted, _reason, problems = flo.filter_lens_output(
        text, cite_repo, cite_only=True
    )

    assert accepted is False
    assert any("quote too short" in p for p in problems), problems


def test_039c_objection_with_verified_quote_is_accepted(cite_repo: Path):
    """La UNICA salida que aporta: objecion + cita cuyo quote esta en la linea."""
    text = _cite(
        "scripts/real_module.py",
        4,
        "return 42",
        verdict="Incorrecto: la premisa es falsa, devuelve un literal.",
    )
    accepted, reason, problems = flo.filter_lens_output(text, cite_repo, cite_only=True)

    assert accepted is True, (reason, problems)
    assert reason == "accepted"


def test_027o_cli_exit_code_discriminates(repo: Path, capsys):
    """La salida es AUDITABLE por exit code, no solo por texto."""
    good = repo / "good.md"
    good.write_text(
        _receipt("scripts/real_module.py", verdict="Incorrecto: esto falla."),
        encoding="utf-8",
    )
    bad = repo / "bad.md"
    bad.write_text(
        _receipt("no/existe.py", verdict="Incorrecto: esto falla."), encoding="utf-8"
    )

    assert flo.main(["--lens-output", str(good), "--root", str(repo)]) == 0
    assert flo.main(["--lens-output", str(bad), "--root", str(repo)]) == 1


# --------------------------------------------------------------------------
# WOT-2026-041c: el filtro resolvia las citas contra UN SOLO root.
#
# En la ruta de PRODUCCION (`ensemble_dispatch.py`) el root pasado es el
# DESTINO, pero los artefactos que las lentes auditan (`scripts/`, `bus/`,
# `prompts/`, `tests/`) viven en el MOTOR: toda cita legitima al motor se
# descartaba como `fabricated_citation`, perdiendo justo la contribucion mas
# valiosa (la que cita codigo real) y dejando pasar las respuestas vagas.
# --------------------------------------------------------------------------


@pytest.fixture
def destino_root(tmp_path: Path) -> Path:
    """Root PRIMARIO (rol destino): tiene runtime, no los artefactos citados."""
    root = tmp_path / "destino"
    (root / ".agent").mkdir(parents=True)
    (root / ".agent" / "state.md").write_text(
        "ticket: WOT-2026-041c\n", encoding="utf-8"
    )
    return root


@pytest.fixture
def motor_root(tmp_path: Path) -> Path:
    """Root EXTRA (rol motor): aqui viven los artefactos que la lente cita."""
    root = tmp_path / "motor"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "filter_lens_output.py").write_text(
        "import os\ndef validate_lens_cites(text, root):\n    return True, []\n",
        encoding="utf-8",
    )
    return root


def test_041c_dod_a_cite_to_motor_file_is_accepted(
    destino_root: Path, motor_root: Path
):
    """DoD (a): cita a un fichero del MOTOR, ACEPTADA con root primario=DESTINO.

    Es el defecto exacto: sin `extra_roots` esta misma salida se descartaba
    como `fabricated_citation`, que es lo que el test hermano de abajo pinnea.
    """
    text = _cite(
        "scripts/filter_lens_output.py",
        2,
        "def validate_lens_cites",
        verdict="Incorrecto: el validador resuelve contra un unico root.",
    )

    accepted, reason, problems = flo.filter_lens_output(
        text, destino_root, cite_only=True, extra_roots=[motor_root]
    )

    assert accepted is True, (reason, problems)
    assert reason == "accepted"


def test_041c_dod_a_same_cite_without_extra_root_is_the_measured_rojo(
    destino_root: Path, motor_root: Path
):
    """El ROJO de referencia: MISMO texto, sin `extra_roots` -> fabricada.

    Fija que el test de (a) mide el AMBITO DE ROOT y no otra cosa: la unica
    diferencia entre ambos es el root extra. Sin este par, un (a) verde no
    probaria que el defecto existia.
    """
    text = _cite(
        "scripts/filter_lens_output.py",
        2,
        "def validate_lens_cites",
        verdict="Incorrecto: el validador resuelve contra un unico root.",
    )

    accepted, reason, problems = flo.filter_lens_output(
        text, destino_root, cite_only=True
    )

    assert accepted is False
    assert reason == "fabricated_citation"
    assert any("does not resolve" in p for p in problems), problems


def test_041c_dod_b_cite_to_destino_file_still_accepted(
    destino_root: Path, motor_root: Path
):
    """DoD (b): la cita al root PRIMARIO sigue aceptada (no se rompe lo que va).

    El fix no puede convertirse en "solo mira el motor": el destino es el root
    canonico del call-site y debe seguir resolviendo.
    """
    (destino_root / "scripts").mkdir()
    (destino_root / "scripts" / "local_only.py").write_text(
        "def solo_en_destino():\n    return 1\n", encoding="utf-8"
    )
    text = _cite(
        "scripts/local_only.py",
        1,
        "def solo_en_destino",
        verdict="Incorrecto: la premisa es falsa en el destino.",
    )

    accepted, reason, problems = flo.filter_lens_output(
        text, destino_root, cite_only=True, extra_roots=[motor_root]
    )

    assert accepted is True, (reason, problems)
    assert reason == "accepted"


def test_041c_dod_c_path_absent_in_both_roots_is_still_fabricated(
    destino_root: Path, motor_root: Path
):
    """DoD (c): INVARIANTE ANTI-FABRICACION. Ausente en AMBOS -> fabricada.

    Relajar esto convertiria el guard en fail-open, que es PEOR que el defecto
    que arregla: el guard existe para cazar citas inventadas.
    """
    text = _cite(
        "scripts/no_existe_en_ningun_root.py",
        3,
        "def totalmente_inventado",
        verdict="Incorrecto: hay un bug grave aqui.",
    )

    accepted, reason, problems = flo.filter_lens_output(
        text, destino_root, cite_only=True, extra_roots=[motor_root]
    )

    assert accepted is False
    assert reason == "fabricated_citation"
    assert any("does not resolve" in p for p in problems), problems


def test_041c_dod_c_fabricated_quote_in_extra_root_is_still_fabricated(
    destino_root: Path, motor_root: Path
):
    """DoD (c), segunda mitad: la ruta RESUELVE (en el motor) pero el quote NO
    esta en la linea citada -> sigue siendo fabricacion.

    Es el caso que el multi-root podria haber ENMASCARADO: el problema del root
    primario es "does not resolve", que ESCONDERIA que el defecto real es un
    quote inventado. `_most_informative_problem` prefiere el de contenido.
    """
    text = _cite(
        "scripts/filter_lens_output.py",
        2,
        "mock_subprocess_inventado",
        verdict="Incorrecto: el modulo parchea subprocess.",
    )

    accepted, reason, problems = flo.filter_lens_output(
        text, destino_root, cite_only=True, extra_roots=[motor_root]
    )

    assert accepted is False
    assert reason == "fabricated_citation"
    assert any("quote not found" in p for p in problems), problems


def test_041c_dod_c_escape_from_all_roots_is_still_rejected(
    destino_root: Path, motor_root: Path
):
    """DoD (c): el escape-de-root sigue vivo con multi-root.

    Un `../` que existiera en la maquina no puede colarse por la puerta nueva.
    """
    text = _cite(
        "../fuera.py", 1, "def cualquier_cosa", verdict="Incorrecto: esto falla."
    )

    accepted, reason, _ = flo.filter_lens_output(
        text, destino_root, cite_only=True, extra_roots=[motor_root]
    )

    assert accepted is False
    assert reason == "fabricated_citation"


def test_041c_dod_d_signature_is_additive_for_existing_consumers(
    destino_root: Path, motor_root: Path
):
    """DoD (d): ADITIVIDAD. Sin `extra_roots` la conducta es la heredada.

    CENSO de consumidores REALES (invocacion, no mencion), verificado por grep
    `filter_lens_output(` el 2026-07-30: `scripts/ensemble_dispatch.py:1664` y
    el propio CLI de este modulo. `build_extraction_prompt.py` NO es consumidor:
    solo NOMBRA la funcion en un docstring (`:56`) como ejemplo del patron de
    reuso, y nunca la invoca -- premisa falsa del bundle de MANAGER_REVIEW,
    cazada por la lente y corregida aqui en vez de dejarse viva.

    `extra_roots` es kwarg-only (`*`), asi que ninguna llamada POSICIONAL
    existente puede romperse; omitir el kwarg debe dar EXACTAMENTE el mismo
    veredicto que antes del fix.
    """
    (destino_root / "scripts").mkdir()
    (destino_root / "scripts" / "local_only.py").write_text(
        "def solo_en_destino():\n    return 1\n", encoding="utf-8"
    )
    text = _cite(
        "scripts/local_only.py",
        1,
        "def solo_en_destino",
        verdict="Incorrecto: la premisa es falsa en el destino.",
    )

    sin_kwarg = flo.filter_lens_output(text, destino_root, cite_only=True)
    con_none = flo.filter_lens_output(
        text, destino_root, cite_only=True, extra_roots=None
    )

    assert sin_kwarg == con_none
    assert sin_kwarg[0] is True, sin_kwarg


def test_041c_duplicated_root_does_not_duplicate_problems(destino_root: Path):
    """Pasar el MISMO root dos veces no duplica el mensaje de problema."""
    text = _cite(
        "scripts/ausente.py", 1, "def ausente_del_todo", verdict="Incorrecto: falla."
    )

    accepted, _reason, problems = flo.filter_lens_output(
        text, destino_root, cite_only=True, extra_roots=[destino_root]
    )

    assert accepted is False
    assert len(problems) == 1, problems


def test_041c_empty_extra_roots_behaves_like_none(destino_root: Path):
    """`extra_roots=[]` == `extra_roots=None` (hallazgo P5-3 del MANAGER_REVIEW).

    Hoy ambos caen en `*(extra_roots or ())`. Un refactor a `if extra_roots is
    not None:` cambiaria la semantica de la lista vacia sin que nada cayera:
    este test lo pinnea.
    """
    text = _cite(
        "scripts/ausente.py", 1, "def ausente_del_todo", verdict="Incorrecto: falla."
    )

    assert flo.filter_lens_output(
        text, destino_root, cite_only=True, extra_roots=[]
    ) == flo.filter_lens_output(text, destino_root, cite_only=True, extra_roots=None)


def test_041c_duplicate_inside_extra_roots_is_deduplicated(
    destino_root: Path, motor_root: Path
):
    """El duplicado en posicion NO-primera tambien se deduplica (P5-2).

    El test hermano cubre `root` repetido en `extra_roots`; este cubre el mismo
    root repetido DENTRO de la lista extra, que recorre otra rama del `seen`.
    """
    text = _cite(
        "scripts/ausente.py", 1, "def ausente_del_todo", verdict="Incorrecto: falla."
    )

    accepted, _reason, problems = flo.filter_lens_output(
        text, destino_root, cite_only=True, extra_roots=[motor_root, motor_root]
    )

    assert accepted is False
    assert len(problems) == 1, problems
    assert flo._candidate_roots(destino_root, [motor_root, motor_root]) == [
        destino_root,
        motor_root,
    ]


def test_041c_same_relative_path_in_both_roots_verifies_against_either(
    destino_root: Path, motor_root: Path
):
    """COLISION DE NOMBRES entre roots (hallazgo P5-1 del MANAGER_REVIEW).

    El MISMO path relativo existe en AMBOS roots con contenido DISTINTO. La
    cita debe aceptarse si su quote verifica contra CUALQUIERA de los dos, y
    rechazarse si no verifica contra NINGUNO. Sin este test, un cambio en el
    orden de iteracion alteraria el veredicto en silencio.
    """
    (destino_root / "scripts").mkdir()
    (destino_root / "scripts" / "colision.py").write_text(
        "SOLO_EN_DESTINO = 1\n", encoding="utf-8"
    )
    (motor_root / "scripts" / "colision.py").write_text(
        "SOLO_EN_MOTOR = 2\n", encoding="utf-8"
    )
    kwargs = {"cite_only": True, "extra_roots": [motor_root]}

    # Verifica contra el root PRIMARIO (destino).
    ok_destino, _, _ = flo.filter_lens_output(
        _cite(
            "scripts/colision.py", 1, "SOLO_EN_DESTINO", verdict="Incorrecto: falla."
        ),
        destino_root,
        **kwargs,
    )
    # Verifica contra el root EXTRA (motor), mismo path relativo.
    ok_motor, _, _ = flo.filter_lens_output(
        _cite("scripts/colision.py", 1, "SOLO_EN_MOTOR", verdict="Incorrecto: falla."),
        destino_root,
        **kwargs,
    )
    # No verifica contra NINGUNO -> sigue siendo fabricacion.
    ok_ninguno, reason, _ = flo.filter_lens_output(
        _cite("scripts/colision.py", 1, "EN_NINGUNO_DE_LOS_DOS", verdict="Incorrecto."),
        destino_root,
        **kwargs,
    )

    assert ok_destino is True
    assert ok_motor is True
    assert ok_ninguno is False
    assert reason == "fabricated_citation"


def test_041c_cli_extra_root_flag_flips_the_verdict(
    destino_root: Path, motor_root: Path
):
    """La ruta CLI expone el fix y su exit code DISCRIMINA.

    Barrera de cableado: el mecanismo no vale si el call-site no puede
    alcanzarlo. Mismo fichero, misma cita; solo cambia `--extra-root`.
    """
    lens = destino_root / "lens.md"
    lens.write_text(
        _cite(
            "scripts/filter_lens_output.py",
            2,
            "def validate_lens_cites",
            verdict="Incorrecto: resuelve contra un unico root.",
        ),
        encoding="utf-8",
    )

    assert flo.main(["--lens-output", str(lens), "--root", str(destino_root)]) == 1
    assert (
        flo.main(
            [
                "--lens-output",
                str(lens),
                "--root",
                str(destino_root),
                "--extra-root",
                str(motor_root),
            ]
        )
        == 0
    )
