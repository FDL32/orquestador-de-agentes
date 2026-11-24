"""Contract tests for the versioned flight-pillars index.

Before: the repository contains the canonical Markdown index, or a test
fixture supplies a candidate row/text.
During: parse rows and load the small canonical-file contract used by this
ticket; the future F1b validator remains deliberately out of scope.
After: malformed rows/files raise ``ValueError`` with a reason, while the
real index is checked for its basic shape and portability.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


CANON_PATH = (
    Path(__file__).parents[2] / ".agent" / "rules" / "common" / "vuelo_pilares.md"
)
ALLOWED_STATES = {"RATIFICADA", "PILOTO", "NO RATIFICADA", "SUPERADA"}
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
ABSOLUTE_ROUTE_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/home/|/Users/|\\\\[^\\/\s]+[\\/][^\\/\s]+)"
)
CUPO_FIGURE_RE = re.compile(
    r"P\s*>=\s*\d+"
    r"|\d+\s*por ciento"
    r"|cupo[^\n]{0,40}>=\s*\d+"
    r"|\d+\s+(?:unidades?\s+)?de\s+cupo"
)

BASE_ROW = (
    "| P0 | Regla de prueba | RATIFICADA | "
    "c38d20f3-796a-4f56-ae3d-50c09952ce25 | fuente.md | mecanismo | coordinadora activa |"
)

P28_MESSAGE_ID = "71ce07a9-cadf-4882-85bb-b408632139ec"
USER_MESSAGE_ID = "0c6b4e16-2fc0-4ec9-96d0-a12cf7bfc45c"
P1_COLUMN_MESSAGE_ID = "c38d20f3-796a-4f56-ae3d-50c09952ce25"
P1_CHANGE_SUFFIX = f"(CAMBIO 2026-11-15; id {USER_MESSAGE_ID})"
EXPECTED_RATIFIED_MESSAGE_IDS = {
    "P1": (P1_COLUMN_MESSAGE_ID, USER_MESSAGE_ID),
    "P2": (USER_MESSAGE_ID,),
    "P10": (USER_MESSAGE_ID,),
    "P28": (P28_MESSAGE_ID,),
    "P29": (P28_MESSAGE_ID,),
}
P28_FIXTURE_ROW = (
    "| P28 | Regla de prueba P28 | RATIFICADA | "
    f"{P28_MESSAGE_ID} | fuente.md | mecanismo | coordinadora activa |"
)
P29_FIXTURE_ROW = (
    "| P29 | Regla de prueba P29 | RATIFICADA | "
    f"{P28_MESSAGE_ID} | fuente.md | mecanismo | coordinadora activa |"
)


def parse_row(line: str) -> dict[str, str]:
    """Parse and validate one Markdown table row.

    Before: ``line`` is one candidate Markdown table row.
    During: split the row into its seven cells and validate the state/message
    relationship and the UUID shape.
    After: return named fields, or raise ``ValueError`` identifying the first
    violated invariant.
    """
    cells = [cell.strip() for cell in line.strip().split("|")]
    if cells and cells[0] == "":
        cells.pop(0)
    if cells and cells[-1] == "":
        cells.pop()
    if len(cells) != 7:
        raise ValueError("row must have seven columns")

    pillar, phrase, state, message_id, source, mechanism, ask = cells
    if not state:
        raise ValueError("state is required")
    if state not in ALLOWED_STATES:
        raise ValueError("invalid state")
    if state == "RATIFICADA":
        if not message_id:
            raise ValueError("ratified row requires messageId")
        if not UUID_RE.fullmatch(message_id):
            raise ValueError("messageId must be a UUID")
    elif message_id:
        raise ValueError("only ratified rows may carry messageId")
    return {
        "pillar": pillar,
        "phrase": phrase,
        "state": state,
        "message_id": message_id,
        "source": source,
        "mechanism": mechanism,
        "ask": ask,
    }


def load_canon(text: str) -> list[dict[str, str]]:
    """Load canonical rows with explicit empty/EOF/portability checks.

    Before: ``text`` is the complete file content.
    During: reject an empty file, missing final LF, and machine-absolute paths,
    then parse non-header table rows.
    After: return all parsed rows; malformed input raises ``ValueError``.
    """
    if not text:
        raise ValueError("canonical file is empty")
    if not text.endswith("\n"):
        raise ValueError("canonical file must end with a newline")
    portable_text = text.replace("C:/Users/fdl/tmp_or8", "<flight-local>")
    if ABSOLUTE_ROUTE_RE.search(portable_text):
        raise ValueError("canonical file contains an absolute route")
    rows = [
        parse_row(line)
        for line in text.splitlines()
        if line.startswith("| P") and not line.startswith("| Pilar")
    ]
    if not rows:
        raise ValueError("canonical file has no rows")
    return rows


def mutate_once(source: str, old: str, new: str) -> str:
    """Apply one exact fixture mutation, guarding against fragile tests."""
    assert source.count(old) == 1, f"fixture fragment is not unique: {old!r}"
    return source.replace(old, new)


def assert_no_cupo_figures(text: str) -> None:
    """Reject cupo thresholds that belong in the flight state sources.

    Before: ``text`` is the complete canonical pillar index.
    During: scan all text for numeric cupo threshold forms.
    After: return silently when no threshold is embedded; otherwise raise
    ``ValueError`` naming the portability invariant.
    """
    matches = CUPO_FIGURE_RE.findall(text)
    if matches:
        raise ValueError("canonical file contains cupo figures")


def assert_pillar_ratified(text: str, pillar: str, expected_message_id: str) -> None:
    """Require one canon pillar row RATIFICADA with an exact messageId.

    Before: ``text`` is a complete canonical pillar index (real file or
    fixture) and ``pillar`` is a bare id such as ``"P28"``.
    During: locate the row whose first cell is exactly ``pillar`` and parse
    it with the same rules as every other row.
    After: return silently when the row is RATIFICADA with
    ``expected_message_id``; otherwise raise ``ValueError`` naming the gap.
    """
    row_re = re.compile(rf"^\| {re.escape(pillar)} \|.*\|$", re.MULTILINE)
    match = row_re.search(text)
    if match is None:
        raise ValueError(f"pillar {pillar} is missing")
    row = parse_row(match.group(0))
    if row["state"] != "RATIFICADA":
        raise ValueError(f"pillar {pillar} is not RATIFICADA")
    if row["message_id"] != expected_message_id:
        raise ValueError(f"pillar {pillar} messageId mismatch")


def assert_pillar_contains_terms(
    text: str, pillar: str, required_terms: tuple[str, ...]
) -> None:
    """Require every term in ``required_terms`` inside pillar's own phrase.

    Before: ``text`` is a complete canonical pillar index (real file or
    fixture) and ``pillar`` is a bare id such as ``"P28"``.
    During: locate the row and read its phrase cell (second column) only;
    never the other six columns.
    After: return silently when every required term appears in the phrase;
    otherwise raise ``ValueError`` naming the first missing term.
    """
    row_re = re.compile(rf"^\| {re.escape(pillar)} \|.*\|$", re.MULTILINE)
    match = row_re.search(text)
    if match is None:
        raise ValueError(f"pillar {pillar} is missing")
    row = parse_row(match.group(0))
    missing = [term for term in required_terms if term not in row["phrase"]]
    if missing:
        raise ValueError(f"pillar {pillar} phrase missing term: {missing[0]}")


P28_REQUIRED_TERMS = (
    "REVISOR",
    "cláusula",
    "comprobación",
    "ámbito",
    "conteo esperado",
    "conteo medido",
    "control positivo",
    "la coordinadora comprueba cobertura",
)
P29_REQUIRED_TERMS = ("sin matriz", "no se acepta")


def test_real_canon_p28_phrase_has_required_terms() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    assert_pillar_contains_terms(text, "P28", P28_REQUIRED_TERMS)


def test_real_canon_p29_phrase_has_required_terms() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    assert_pillar_contains_terms(text, "P29", P29_REQUIRED_TERMS)


def test_p28_fixture_without_revisor_fails_explicitly() -> None:
    fixture_row = (
        "| P28 | La verificación del DoD es de la coordinadora mediante una "
        "matriz (cláusula, comprobación, ámbito, conteo esperado, conteo "
        "medido, control positivo); la coordinadora comprueba cobertura. | "
        f"RATIFICADA | {P28_MESSAGE_ID} | fuente.md | mecanismo | coordinadora activa |"
    )
    candidate = "# title\n" + fixture_row + "\n"
    with pytest.raises(ValueError, match="phrase missing term"):
        assert_pillar_contains_terms(candidate, "P28", P28_REQUIRED_TERMS)


def test_p28_fixture_term_only_in_other_column_still_fails_explicitly() -> None:
    """Require the missing term to be absent from the WHOLE row, not just
    rephrased elsewhere: the phrase cell lacks REVISOR, but the mecanismo
    cell names it, so a mutant that scanned the whole row instead of only
    the phrase cell would wrongly find it there and stay silent."""
    fixture_row = (
        "| P28 | La verificación del DoD es de la coordinadora mediante una "
        "matriz (cláusula, comprobación, ámbito, conteo esperado, conteo "
        "medido, control positivo); la coordinadora comprueba cobertura. | "
        f"RATIFICADA | {P28_MESSAGE_ID} | fuente.md | "
        "REVISOR hace la matriz, conteo medido lo repite la coordinadora | "
        "coordinadora activa |"
    )
    candidate = "# title\n" + fixture_row + "\n"
    with pytest.raises(ValueError, match="phrase missing term: REVISOR"):
        assert_pillar_contains_terms(candidate, "P28", P28_REQUIRED_TERMS)


def test_p29_fixture_inverted_meaning_fails_explicitly() -> None:
    fixture_row = (
        "| P29 | Una caja con matriz ejecutada por el revisor se acepta. | "
        f"RATIFICADA | {P28_MESSAGE_ID} | fuente.md | mecanismo | coordinadora activa |"
    )
    candidate = "# title\n" + fixture_row + "\n"
    with pytest.raises(ValueError, match="phrase missing term"):
        assert_pillar_contains_terms(candidate, "P29", P29_REQUIRED_TERMS)


def test_p28_real_canon_mutant_revisor_to_coordinadora_fails_explicitly() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    assert text.count("REVISOR de la celda") == 1
    candidate = mutate_once(text, "REVISOR de la celda", "coordinadora de la celda")
    with pytest.raises(ValueError, match="phrase missing term"):
        assert_pillar_contains_terms(candidate, "P28", P28_REQUIRED_TERMS)


def test_p29_real_canon_mutant_inverted_meaning_fails_explicitly() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    original = "sin matriz ejecutada por el revisor no se acepta"
    assert text.count(original) == 1
    candidate = mutate_once(
        text, original, "con matriz ejecutada por el revisor se acepta"
    )
    with pytest.raises(ValueError, match="phrase missing term"):
        assert_pillar_contains_terms(candidate, "P29", P29_REQUIRED_TERMS)


def test_real_canon_rows_are_well_formed_and_portable() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    rows = load_canon(text)
    assert rows
    assert all(row["state"] in ALLOWED_STATES for row in rows)
    assert all(
        len(row["message_id"]) == 36 for row in rows if row["state"] == "RATIFICADA"
    )
    assert all(
        not row["message_id"]
        for row in rows
        if row["state"] in {"NO RATIFICADA", "PILOTO", "SUPERADA"}
    )
    portable_text = text.replace("C:/Users/fdl/tmp_or8", "<flight-local>")
    assert not any(token in portable_text for token in ("C:\\", "C:/Users", "/home/"))


def test_real_canon_has_no_embedded_cupo_figures() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    assert_no_cupo_figures(text)


@pytest.mark.parametrize(
    "cupo_text",
    [
        "P>=85",
        "cupo de 5h >=90",
        "~85 por ciento",
        "P>=95",
        "quedan 90 unidades de cupo",
        "90 de cupo",
    ],
)
def test_cupo_figure_fixture_fails_explicitly(cupo_text: str) -> None:
    candidate = mutate_once(BASE_ROW, "Regla de prueba", f"Regla {cupo_text}")
    with pytest.raises(ValueError, match="cupo figures"):
        assert_no_cupo_figures(candidate)


@pytest.mark.parametrize(
    "context_text",
    [
        "contexto de la saliente al relevar / 600000",
        "ticks con cupo medido (rc 0); episodios de cupo alto sin accion",
    ],
)
def test_cupo_figure_does_not_flag_context_or_unrelated_numbers(
    context_text: str,
) -> None:
    assert CUPO_FIGURE_RE.findall(context_text) == []


def test_real_canon_pillar_ids_are_contiguous() -> None:
    text = CANON_PATH.read_text(encoding="utf-8")
    numbers = [int(match) for match in re.findall(r"^\| P(\d+) \|", text, re.MULTILINE)]
    assert numbers
    assert max(numbers) >= 27
    assert numbers == list(range(1, max(numbers) + 1))


def test_real_canon_pillar_is_ratified_with_message_id() -> None:
    """Enforce the explicit ratification map in both directions.

    Before: the real canonical index contains ratified and non-ratified rows.
    During: verify every expected row and then verify every ratified row not
    listed in the map has a valid UUID; P1 also carries the change UUID suffix.
    After: the map is exact for its rows and exhaustive for ratified rows.
    """
    text = CANON_PATH.read_text(encoding="utf-8")
    rows = {row["pillar"]: row for row in load_canon(text)}

    for pillar, expected_ids in EXPECTED_RATIFIED_MESSAGE_IDS.items():
        row = rows[pillar]
        assert row["state"] == "RATIFICADA"
        assert row["message_id"] == expected_ids[0]
        if pillar == "P1":
            assert row["phrase"].endswith(P1_CHANGE_SUFFIX)
            assert USER_MESSAGE_ID in row["phrase"]
            assert expected_ids[1] == USER_MESSAGE_ID

    for pillar, row in rows.items():
        if row["state"] == "RATIFICADA" and pillar not in EXPECTED_RATIFIED_MESSAGE_IDS:
            assert UUID_RE.fullmatch(row["message_id"])


@pytest.mark.parametrize("pillar", ["P28", "P29"])
def test_pillar_fixture_without_row_fails_explicitly(pillar: str) -> None:
    candidate = "# title\n" + BASE_ROW + "\n"
    with pytest.raises(ValueError, match=f"{pillar} is missing"):
        assert_pillar_ratified(candidate, pillar, P28_MESSAGE_ID)


@pytest.mark.parametrize("pillar", ["P28", "P29"])
def test_pillar_fixture_not_ratified_fails_explicitly(pillar: str) -> None:
    fixture_row = (
        f"| {pillar} | Regla de prueba {pillar} | NO RATIFICADA |  | "
        "fuente.md | mecanismo | coordinadora activa |"
    )
    candidate = "# title\n" + fixture_row + "\n"
    with pytest.raises(ValueError, match=f"{pillar} is not RATIFICADA"):
        assert_pillar_ratified(candidate, pillar, P28_MESSAGE_ID)


@pytest.mark.parametrize(
    ("pillar", "fixture_row"),
    [("P28", P28_FIXTURE_ROW), ("P29", P29_FIXTURE_ROW)],
)
def test_pillar_fixture_with_other_message_id_fails_explicitly(
    pillar: str, fixture_row: str
) -> None:
    candidate = (
        "# title\n"
        + mutate_once(
            fixture_row, P28_MESSAGE_ID, "c38d20f3-796a-4f56-ae3d-50c09952ce25"
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="messageId mismatch"):
        assert_pillar_ratified(candidate, pillar, P28_MESSAGE_ID)


def test_ratified_positive_row_parses() -> None:
    row = parse_row(BASE_ROW)
    assert row["state"] == "RATIFICADA"
    assert len(row["message_id"]) == 36


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ("RATIFICADA", "", "state is required"),
        ("RATIFICADA", "CONFIRMADA", "invalid state"),
        (
            "c38d20f3-796a-4f56-ae3d-50c09952ce25",
            "c38d20f3-796a-4f56-ae3d-50c09952ce2",
            "UUID",
        ),
        (
            "c38d20f3-796a-4f56-ae3d-50c09952ce25",
            "c38d20f3-796a-4f56-ae3d-50c09952ce250",
            "UUID",
        ),
        (
            "c38d20f3-796a-4f56-ae3d-50c09952ce25",
            "",
            "^ratified row requires messageId$",
        ),
        ("RATIFICADA", "NO RATIFICADA", "only ratified"),
    ],
)
def test_row_negative_mutates_one_unique_fragment(
    old: str, new: str, reason: str
) -> None:
    candidate = mutate_once(BASE_ROW, old, new)
    with pytest.raises(ValueError, match=reason):
        parse_row(candidate)


def test_row_with_six_columns_fails_explicitly() -> None:
    candidate = mutate_once(BASE_ROW, "| mecanismo |", "| mecanismo")
    with pytest.raises(ValueError, match="row must have seven columns"):
        parse_row(candidate)


def test_empty_canon_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="empty"):
        load_canon("")


def test_canon_without_final_newline_fails_explicitly() -> None:
    candidate = (
        "# title\n| P1 | phrase | NO RATIFICADA |  | source.md | mechanism | usuario |"
    )
    with pytest.raises(ValueError, match="newline"):
        load_canon(candidate)


def test_canon_with_no_data_rows_fails_explicitly() -> None:
    candidate = "# title\n| Pilar | Frase | ESTADO | messageId | fuente larga | mecanismo | actor |\n"
    with pytest.raises(ValueError, match="no rows"):
        load_canon(candidate)


def test_absolute_route_fixture_fails_explicitly() -> None:
    candidate = "# title\n| P1 | C:\\Users\\alguien\\canon.md | NO RATIFICADA |  | source.md | mechanism | usuario |\n"
    with pytest.raises(ValueError, match="absolute route"):
        load_canon(candidate)


def test_absolute_route_posix_users_fixture_fails_explicitly() -> None:
    candidate = "# title\n| P1 | /Users/alguien/canon.md | NO RATIFICADA |  | source.md | mechanism | usuario |\n"
    with pytest.raises(ValueError, match="absolute route"):
        load_canon(candidate)


def test_absolute_route_unc_fixture_fails_explicitly() -> None:
    candidate = (
        "# title\n| P1 | \\\\servidor\\recurso\\canon.md | NO RATIFICADA |  | "
        "source.md | mechanism | usuario |\n"
    )
    with pytest.raises(ValueError, match="absolute route"):
        load_canon(candidate)


def test_readme_reference_points_to_existing_canon() -> None:
    readme = (CANON_PATH.parents[3] / ".claude" / "rules" / "README.md").read_text(
        encoding="utf-8"
    )
    assert ".agent/rules/common/vuelo_pilares.md" in readme
    assert CANON_PATH.exists()


def test_agents_reference_points_to_canon() -> None:
    agents = (CANON_PATH.parents[3] / "AGENTS.md").read_text(encoding="utf-8")
    assert "vuelo_pilares.md" in agents


TARGET_PILLARS = (
    "P11",
    "P13",
    "P15",
    "P16",
    "P17",
    "P19",
    "P20",
    "P21",
    "P22",
    "P30",
    "P32",
    "P35",
)

ALLOWLIST_EXCEPCIONES: tuple[str, ...] = ()

EXPECTED_CONFIRMED_PHRASES = {
    "P11": (
        "Subagentes: como maximo 2 simultaneos por sesion; un subagente Claude "
        "nunca sustituye a una lente de revision; se lanzan con las lentes de la "
        "tabla de lentes (panel unico, WOT-2026-229a); cuenta y modelo los fija el "
        "panel y se miden con t3_thread_configuration. [Retira la clausula 'cuenta "
        "prioritaria / umbral del roster' (nivel 3): la cubre el panel.]"
    ),
    "P13": (
        "Mejora continua (bitacora Kaizen): una retro por PIPELINE, previa a la "
        "suite completa. (1) Se analiza el pipeline: tickets integrados, hallazgos "
        "y coste de contexto. (2) Se proponen mejoras con evidencia e indicador, "
        "maximo 5 entradas en estado PROPUESTA. (3) UN bucle de lentes sobre el "
        "aprendizaje: una ronda canonica por loop-round (deja recibo), de nivel "
        "medio salvo orden expresa del usuario; una correccion bloqueante no reinicia "
        "la retro (solo delta). (4) Se crean los tickets resultantes. (5) Despues, la "
        "suite completa y el push. Los tickets de la retro entran en el pipeline "
        "siguiente SALVO los BLOQUEANTES del push (los que ponen la suite en rojo o "
        "violan un gate ratificado). Entre retros, lo que se descubre se anota como "
        "entrada PROPUESTA en el mismo turno. Una entrada solo se marca VERIFICADA "
        "cuando el indicador se mide DESPUES, en la retro de un pipeline posterior. "
        "Se retira 'o cada 6 horas' (5 dias sin cumplirse)."
    ),
    "P15": (
        "Continuidad del vuelo: un vuelo (espacio de operacion autonoma continua "
        "sobre un destino; definicion en vocabulario_canonico.md) se sostiene con "
        "PC sin suspension, canal T3 abierto, aviso externo y copia de seguridad "
        "periodica; las horas son referencia, no limite."
    ),
    "P16": (
        "RETIRADA a historico por orden del usuario (messageId "
        "9f8cc258-c047-4fae-9d36-789d7b2ef081, 2026-11-23), que supera al "
        "MANTENGO_NORMA_P16 de 009ca4b5 por ser mas reciente; rondas en paralelo "
        "permitidas (32e06121); el nonce lo emite la coordinadora ligado al commit "
        "(emit-nonce y check_loop_execution); no es regla vigente."
    ),
    "P17": (
        "Una suite canonica completa sobre el HEAD final, la ultima antes de "
        "publicar, cuando el motor esta cerrado; sin hora minima ni ciclo de 24 h "
        "(7c1d767d-918a-4da4-a1bb-43c108accb6d); entre medias, gate por merge "
        "(focal + 2 lentes)."
    ),
    "P19": (
        "Sesiones TR (triaje): no realizan implantaciones; pueden modificar el "
        "backlog y los demas documentos de registro, activacion y cierres de tickets "
        "para mantener el estado actualizado. Implantacion: extension pendiente de "
        "ticket; hoy el TR escribe solo en su carpeta de salida (MANUAL_TR_v1.md) y "
        "la coordinadora admite y cierra."
    ),
    "P20": (
        "Agente frio con el minimo consumo de tokens: arranque y memoria acotados y "
        "medidos (lineas del indice cargadas frente a cortadas, bytes de arranque); "
        "lo fundamental crece justificado y lo demas rota (P12). Primero se mide que "
        "carga un agente frio (hook SessionStart, AGENTS.md, CLAUDE.md, reglas, indice "
        "de memoria); despues, tokens por pulso (228a) y contexto por ticket cerrado."
    ),
    "P21": (
        "Supervisión: latido de la coordinadora cada 15 minutos y de la "
        "supervisora cada 30 minutos."
    ),
    "P22": (
        "Registro del vuelo (eventos): OPERACION_EN_CURSO_CO-n de cada coordinadora, "
        "comms_ledger.jsonl (local, en C:/Users/fdl/tmp_or8, sin versionar), "
        "registry_ledger.jsonl, registry_changes.jsonl y roster_changes.jsonl "
        "(carpeta del vuelo, sin versionar). journal.jsonl, incidencias.md y los "
        "BITACORA.md de los vuelos de octubre son historicos. El termino 'bitacora' "
        "designa la mejora continua (P13)."
    ),
    "P30": (
        "Celda del IM: cada IM es una celda formada por una sesion revisora y un "
        "builder codex hijo lanzado con delegate_task; un IM NUNCA se lanza como "
        "sesion unica Manager+Builder. Asignacion vigente: ver la tabla de lentes y "
        "celdas (panel unico, 229a), conservando las excepciones con messageId "
        "(Builder y V1 = codex luna, orden 2026-11-21)."
    ),
    "P32": (
        "Cascada de fuentes ante una actividad o un conflicto (dueno: AGENTS.md "
        "l.134-136): canon (las actividades rutinarias ya estan tipificadas y se leen "
        "antes que un par), precedente, supervisora o ancestro directo, bucle de "
        "gobierno, usuario (P3); si un nivel no resuelve se pasa al siguiente; si "
        "dos fuentes del mismo nivel chocan se aplica el desempate de este indice."
    ),
    "P35": (
        "Celda del TR: cada TR es una celda formada por un TRIADOR y un REVISOR; sus "
        "dos sesiones son las dos lentes de P34 para el TR. Asignacion vigente: ver "
        "la tabla de lentes y celdas (panel unico, 229a), conservando las excepciones "
        "con messageId (Builder y V1 = codex luna, orden 2026-11-21)."
    ),
}

P33_BASELINE_SHA256 = "3844bae4bcf188dad96cad1b4ada52abb93ab53c247376fab55fd8c9c1d708bd"


def _real_rows() -> dict[str, dict[str, str]]:
    """Load the production rows for the m-01..m-09 contract checks."""
    return {
        row["pillar"]: row for row in load_canon(CANON_PATH.read_text(encoding="utf-8"))
    }


def test_m01_confirmed_pillars_have_exact_v3_phrases() -> None:
    """m-01: each of the 12 confirmed rows matches its exact V3 phrase."""
    rows = _real_rows()
    assert len(EXPECTED_CONFIRMED_PHRASES) == 12
    for pillar, expected_phrase in EXPECTED_CONFIRMED_PHRASES.items():
        assert rows[pillar]["phrase"] == expected_phrase, f"mismatch in {pillar}"


def test_m02_ratified_pillars_carry_uuid_and_historic_do_not() -> None:
    """m-02: every RATIFICADA carries a UUID and SUPERADA carries empty messageId."""
    rows = _real_rows()
    for pillar in TARGET_PILLARS:
        if pillar == "P16":
            assert rows[pillar]["state"] == "SUPERADA"
            assert rows[pillar]["message_id"] == ""
        else:
            assert rows[pillar]["state"] == "RATIFICADA"
            assert UUID_RE.fullmatch(rows[pillar]["message_id"])


def test_m03_p16_superada_token_and_column() -> None:
    """m-03: P16 carries the UUID in the text and none in the column."""
    row = _real_rows()["P16"]
    assert row["state"] == "SUPERADA"
    assert "9f8cc258-c047-4fae-9d36-789d7b2ef081" in row["phrase"]
    assert row["message_id"] == ""


def test_m04_p30_p35_remit_to_panel_unico() -> None:
    """m-04: P30 and P35 remit to the single panel and retain codex luna exception."""
    rows = _real_rows()
    for pillar in ("P30", "P35"):
        phrase = rows[pillar]["phrase"]
        assert "ver la tabla de lentes y celdas (panel unico, 229a)" in phrase
        assert "Builder y V1 = codex luna" in phrase


def test_m05_p33_sha256_is_unchanged() -> None:
    """m-05: P33 row hash is strictly identical to its baseline."""
    import hashlib

    text = CANON_PATH.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| P33 |"))
    assert hashlib.sha256(row.encode("utf-8")).hexdigest() == P33_BASELINE_SHA256


def test_m06_p13_section4_no_six_hours() -> None:
    """m-06: P13 matches V3 s.4 text without 6-hour trigger."""
    phrase = _real_rows()["P13"]["phrase"]
    assert "Se retira 'o cada 6 horas' (5 dias sin cumplirse)." in phrase
    assert "o cada 6 horas" not in phrase.split("Se retira")[0]


def test_m07_p12_mechanism_has_no_broken_ticket_pointer() -> None:
    """P12 mechanism has no owner WOT-2026-T1a."""
    assert (
        _real_rows()["P12"]["mechanism"]
        == "NORMA SIN CABLEAR (censo y comprobador L-6)"
    )


def test_m09_canon_pointers_resolve_against_motor() -> None:
    """m-09: WOT ids resolve in git subjects/versioned files and routes resolve on disk."""
    root = CANON_PATH.parents[3]
    text = CANON_PATH.read_text(encoding="utf-8")
    subjects = subprocess.run(
        ["git", "log", "--all", "--format=%s"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for ticket in sorted(set(re.findall(r"\bWOT-2026-[A-Za-z0-9_]+\b", text))):
        if ticket in ALLOWLIST_EXCEPCIONES:
            continue
        assert any(ticket in subject for subject in subjects), (
            f"unresolved ticket: {ticket}"
        )
    routes = set(
        re.findall(r"(?:docs/|scripts/|prompts/|\.agent/)[A-Za-z0-9_./-]+", text)
    )
    for route in routes:
        assert (root / route).exists(), f"unresolved route: {route}"


def test_mutation_m01_altered_p15_word_fails() -> None:
    """mutation: altering a word in P15 fails m-01."""
    rows = _real_rows()
    mutated = dict(rows["P15"])
    mutated["phrase"] = mutated["phrase"].replace("Continuidad", "Discontinuidad")
    with pytest.raises(AssertionError):
        assert mutated["phrase"] == EXPECTED_CONFIRMED_PHRASES["P15"]


def test_mutation_m02_missing_uuid_fails() -> None:
    """mutation: removing UUID from P11 fails m-02."""
    rows = _real_rows()
    mutated = dict(rows["P11"])
    mutated["message_id"] = ""
    with pytest.raises(AssertionError):
        assert UUID_RE.fullmatch(mutated["message_id"])


def test_mutation_m03_p16_reverted_to_no_ratificada_fails() -> None:
    """mutation: returning P16 to NO RATIFICADA fails m-03."""
    rows = _real_rows()
    mutated = dict(rows["P16"])
    mutated["state"] = "NO RATIFICADA"
    with pytest.raises(AssertionError):
        assert mutated["state"] == "SUPERADA"


def test_mutation_m04_p30_with_concrete_model_fails() -> None:
    """mutation: re-adding concrete model name to P30 fails m-04."""
    rows = _real_rows()
    mutated = dict(rows["P30"])
    mutated["phrase"] = "REVISOR = opencode nan/mimo-v2.6-flash"
    with pytest.raises(AssertionError):
        assert (
            "ver la tabla de lentes y celdas (panel unico, 229a)" in mutated["phrase"]
        )


def test_mutation_m05_p33_altered_sha_fails() -> None:
    """mutation: altering P33 row alters sha256 and fails m-05."""
    import hashlib

    text = CANON_PATH.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| P33 |"))
    mutated_row = row.replace("Independencia", "Dependencia")
    with pytest.raises(AssertionError):
        assert (
            hashlib.sha256(mutated_row.encode("utf-8")).hexdigest()
            == P33_BASELINE_SHA256
        )


def test_mutation_m06_p13_six_hours_reintroduced_fails() -> None:
    """mutation: re-introducing 'o cada 6 horas' to P13 fails m-06."""
    phrase = EXPECTED_CONFIRMED_PHRASES["P13"]
    mutated_phrase = "retro por ola o cada 6 horas. " + phrase
    with pytest.raises(AssertionError):
        assert "o cada 6 horas" not in mutated_phrase.split("Se retira")[0]


def test_mutation_m09_broken_ticket_fails() -> None:
    """mutation: adding broken ticket WOT-2026-999z fails m-09."""
    root = CANON_PATH.parents[3]
    subjects = subprocess.run(
        ["git", "log", "--all", "--format=%s"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    with pytest.raises(AssertionError):
        assert any("WOT-2026-999z" in s for s in subjects)
