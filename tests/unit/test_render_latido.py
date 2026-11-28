import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import scripts.flight.render_latido as render_latido_module
from scripts.flight.render_latido import (
    _main,
    check_post_derivacion,
    predecessor_sha12,
    reduce_roster,
    render_latido,
)


ROOT = Path(__file__).parents[2]
PREDECESSOR = ROOT / "tests/fixtures/render_latido/latido_predecesor.md"
SUCCESSOR = ROOT / "tests/fixtures/render_latido/latido_sucesor.md"
ROSTER = ROOT / "tests/fixtures/render_latido/flight_roster.json"
REAL_CO_143 = Path(
    "C:/Users/fdl/Proyectos_Python/orquestador_de_agentes_workspace/"
    ".agent/runtime/flight/vuelo-20261026b/diseno/"
    "LATIDO_CO-143_v7.1_20261120.md"
)
_REAL_STEP9_CO_72 = "Procedimiento: ARRANQUE_CO-72 s.1 y PROTOCOLO_POSTCOMPACTACION_CO-54.md s.2 y PROTOCOLO_POSTCOMPACTACION_CO-55.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-56.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-57.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-58.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-59.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-60.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-61.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-62.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-63.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-64.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-65.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-66.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-67.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-68.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-69.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-70.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-71.md s.3 y s.4 (procedimiento de ticket; el ARRANQUE de CO-72 no tiene s.8) y prompts/t3_role_session_relief.md s.9; el rotador (rotate_coordinator_v2.py) lo ejecuta la SUPERVISORA vigente con --actor. (procedimiento de ticket; el ARRANQUE de CO-72 no tiene s.8) y prompts/t3_role_session_relief.md s.9; el rotador (rotate_coordinator_v2.py) lo ejecuta la SUPERVISORA vigente con --actor. (procedimiento de ticket; el ARRANQUE de CO-72 no tiene s.8) y prompts/t3_role_session_relief.md s.9; el rotador (rotate_coordinator_v2.py) lo ejecuta la SUPERVISORA vigente con --actor. (procedimiento de ticket; el ARRANQUE de CO-72 no tiene s.8) y prompts/t3_role_session_relief.md s.9; el rotador (rotate_coordinator_v2.py) lo ejecuta la SUPERVISORA vigente con --actor. (procedimiento de ticket; el ARRANQUE de CO-72 no tiene s.8) y prompts/t3_role_session_relief.md s.9; el rotador (rotate_coordinator_v2.py) lo ejecuta la SUPERVISORA vigente con --actor. (procedimiento de ticket; el ARRANQUE de CO-72 no tiene s.8) y prompts/t3_role_session_relief.md s.9; el rotador (rotate_coordinator_v2.py) lo ejecuta la SUPERVISORA vigente con --actor. (procedimiento de ticket; el ARRANQUE de CO-72 no tiene s.8) y prompts/t3_role_session_relief.md s.9; el rotador (rotate_coordinator_v2.py) lo ejecuta la SUPERVISORA vigente con --actor."
_REAL_STEP9_CO_67 = "Procedimiento: ARRANQUE_CO-67 s.1 y PROTOCOLO_POSTCOMPACTACION_CO-54.md s.2 y PROTOCOLO_POSTCOMPACTACION_CO-55.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-56.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-57.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-58.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-59.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-60.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-61.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-62.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-63.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-64.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-65.md s.3 y s.4 y PROTOCOLO_POSTCOMPACTACION_CO-66.md s.3 y s.4 (procedimiento de ticket; el ARRANQUE de CO-67 no tiene s.8) y prompts/t3_role_session_relief.md s.9; el rotador (rotate_coordinator_v2.py) lo ejecuta la SUPERVISORA vigente con --actor. (procedimiento de ticket; el ARRANQUE de CO-67 no tiene s.8) y prompts/t3_role_session_relief.md s.9; el rotador (rotate_coordinator_v2.py) lo ejecuta la SUPERVISORA vigente con --actor."


def _juicios_sucesor() -> dict[str, str]:
    text = SUCCESSOR.read_text(encoding="utf-8")
    header = text.splitlines()[1]
    note_start = header.index("[")
    note_end = header.rfind("]", note_start) + 1
    objective = re.search(r"\(ARRANQUE_CO-\d+_20261108\.md s\.2: .*?\)", text)
    assert objective is not None
    postcompactacion = re.search(
        r" y PROTOCOLO_POSTCOMPACTACION_CO-55\.md (s\.3 y s\.4)(?= \(procedimiento de ticket)",
        text,
    )
    assert postcompactacion is not None
    return {
        "nota_derivacion": header[note_start:note_end],
        "objetivo_en_curso": objective.group(0),
        "secciones_postcompactacion_nueva": postcompactacion.group(1),
    }


def _real_co_143_predecessor(tmp_path: Path) -> Path:
    """Prepare the real CO-143 heartbeat without changing its source file.

    Before: the registered real heartbeat exists and carries the measured
    cascade, step-9 citations, and postcompaction history.
    During: apply only the three structural adaptations required by the
    renderer's current judgement and identity anchors, then write a copy.
    After: return a temporary predecessor path suitable for render_latido.
    """

    if not REAL_CO_143.is_file():
        pytest.skip(f"fixture real ausente: {REAL_CO_143}")
    lines = REAL_CO_143.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[1] = lines[1].rstrip("\r\n") + " [nota_derivacion de prueba]" + "\n"
    lines.insert(2, "(ARRANQUE_CO-143_20261120.md s.2: objetivo de prueba)\n")
    for index, line in enumerate(lines):
        if line.startswith("CO-143, sesion coordinadora ACTIVA"):
            adapted = "Eres " + line
            adapted = re.sub(
                r"la cascada es (CO-\d+ \(mcp:[0-9A-Za-z-]+),",
                r"la cascada es \1),",
                adapted,
                count=1,
            )
            prefix, separator, suffix = adapted.rpartition("Go_Relevo_88")
            if separator:
                adapted = prefix + "Go_Relevo_N" + suffix
            lines[index] = adapted
            break
    else:
        pytest.fail("no se encontró la identidad CO-143 en el fixture real")
    for index, line in enumerate(lines):
        if line.startswith("9. Contexto propio:"):
            prefix, separator, suffix = line.rpartition("Go_Relevo_88")
            if separator:
                lines[index] = prefix + "Go_Relevo_N" + suffix
            break
    predecessor = tmp_path / REAL_CO_143.name
    predecessor.write_text("".join(lines), encoding="utf-8")
    return predecessor


def _real_co_144_roster() -> dict[str, object]:
    """Return the reduced roster for the CO-143 to CO-144 derivation.

    Before: the real predecessor cites CO-142 as its supervisor.
    During: provide the exact three consumed identities for the next render.
    After: return a closed reduced roster with no extra fields.
    """

    return {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:c5b34b85-b820-41f2-968d-0583b0f76097",
                "session_code": "CO-144",
            },
            "supervisor": {
                "threadId": "mcp:19416fe9-fd41-4d52-ba69-fff75ce7e614",
                "session_code": "CO-143",
            },
        },
        "cadena_contexto": [
            {
                "threadId": "mcp:eda3ddb7-7b47-4488-b07c-6d76cd9408ec",
                "session_code": "CO-142",
            }
        ],
    }


def _real_derivation_judgements() -> dict[str, str]:
    """Return non-empty judgements for the real CO-143 derivation.

    Before: render_latido requires all three named judgement values.
    During: use valid single-line values that do not add foreign identifiers.
    After: return the complete judgement mapping for a successful baseline.
    """

    return {
        "nota_derivacion": "[nota_derivacion de prueba]",
        "objetivo_en_curso": "(ARRANQUE_CO-144_20261120.md s.2: objetivo en curso)",
        "secciones_postcompactacion_nueva": "s.3 y s.4",
    }


def _step9_line(text: str) -> str:
    """Extract the single step-9 line from a rendered heartbeat.

    Before: ``text`` is a rendered heartbeat with the documented step-9 line.
    During: find the line by its rule heading.
    After: return that line or fail with a useful test diagnostic.
    """

    match = re.search(r"(?m)^9\. Contexto propio:.*$", text)
    assert match is not None, "m-02: falta el paso 9"
    return match.group(0)


def _cascade_text(text: str) -> str:
    """Extract the protected cascade span from a rendered heartbeat.

    Before: ``text`` contains one R2 cascade start and one R2b-fin marker.
    During: slice between those markers.
    After: return only the cascade content used by the bound assertion.
    """

    start_marker = render_latido_module._CASCADE_START
    end_marker = render_latido_module._CASCADE_END
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def _synthetic_predecessor(tmp_path: Path) -> Path:
    """Build the synthetic high-cardinality predecessor in ``tmp_path``.

    Before: the repository predecessor fixture supplies the renderer's real
    anchors, identities, and tick block.
    During: expand only the protected cascade, step-9 salto citations, and
    postcompaction span to the measured snapshot sizes, without adding any
    foreign MCP identifiers outside the frozen cascade.
    After: return a UTF-8 temporary predecessor with exactly 106 cascade entries,
    26 salto citations, and 86 postcompaction protocol references.
    """

    text = PREDECESSOR.read_text(encoding="utf-8")
    cascade_start = text.index(render_latido_module._CASCADE_START) + len(
        render_latido_module._CASCADE_START
    )
    cascade_end = text.index(render_latido_module._CASCADE_END, cascade_start)
    cascade = text[cascade_start:cascade_end]
    cascade_entries = re.findall(r"CO-\d+ \(mcp:", cascade)
    assert len(cascade_entries) == 18
    generated_cascade = ", luego ".join(
        f"CO-{code} (mcp:00000000-0000-4000-8000-{code:012d})"
        for code in range(200, 200 + (106 - len(cascade_entries)))
    )
    text = text[:cascade_end] + ", luego " + generated_cascade + text[cascade_end:]

    step9_match = re.search(r"(?m)^9\. Contexto propio:.*$", text)
    assert step9_match is not None
    step9 = step9_match.group(0)
    citations = " ".join(
        f"El salto CO-{code} -> CO-{code + 1} usa la linea 'Go_Relevo_{code}' "
        f"(fila b{code} de diseno/GO_RELEVO_24H_REGISTRO.md)."
        for code in range(60, 85)
    )
    insertion = " " + citations
    step9 = step9.replace(" El lote NO CADUCA", insertion + " El lote NO CADUCA", 1)
    text = text[: step9_match.start()] + step9 + text[step9_match.end() :]

    post_anchor = "ARRANQUE_CO-55 s.1"
    post_start = text.index(post_anchor) + len(post_anchor)
    if text[post_start : post_start + 3] == " y ":
        post_start += 1
    post_end = text.index(" (procedimiento de ticket", post_start)
    post = text[post_start:post_end]
    assert len(re.findall(r"PROTOCOLO_POSTCOMPACTACION_CO-\d+\.md", post)) == 1
    generated_protocols = " y ".join(
        f"PROTOCOLO_POSTCOMPACTACION_CO-{code}.md s.3 y s.4" for code in range(57, 142)
    )
    text = text[:post_end] + " y " + generated_protocols + text[post_end:]

    predecessor = tmp_path / "LATIDO_CO-55_synthetic.md"
    predecessor.write_text(text, encoding="utf-8", newline="")
    return predecessor


def _synthetic_roster() -> dict[str, object]:
    """Return the reduced fixture roster consumed by the synthetic render."""

    return json.loads(ROSTER.read_text(encoding="utf-8"))


def _synthetic_derivation_judgements() -> dict[str, str]:
    """Return valid judgements for the CO-55-to-CO-56 synthetic render."""

    return {
        "nota_derivacion": "[synthetic nota_derivacion]",
        "objetivo_en_curso": "(ARRANQUE_CO-56_20261108.md s.2: synthetic)",
        "secciones_postcompactacion_nueva": "s.3 y s.4",
    }


def _synthetic_second_case() -> tuple[dict[str, object], dict[str, str]]:
    """Return the synthetic CO-57 roster and its own judgement values."""

    return (
        {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:00000000-0000-4000-8000-000000000057",
                    "session_code": "CO-57",
                },
                "supervisor": {
                    "threadId": "mcp:00000000-0000-4000-8000-000000000002",
                    "session_code": "CO-56",
                },
            },
            "cadena_contexto": [
                {
                    "threadId": "mcp:00000000-0000-4000-8000-000000000002",
                    "session_code": "CO-55",
                }
            ],
        },
        {
            "nota_derivacion": "[segunda synthetic derivacion]",
            "objetivo_en_curso": "(ARRANQUE_CO-57_20261108.md s.2: synthetic)",
            "secciones_postcompactacion_nueva": "s.3 y s.4",
        },
    )


def _bounded_render_cases(tmp_path: Path):
    """Yield the mandatory synthetic case followed by the optional real one."""

    yield (
        "synthetic",
        _synthetic_predecessor(tmp_path),
        _synthetic_roster(),
        2,
        _synthetic_derivation_judgements(),
    )
    if REAL_CO_143.is_file():
        yield (
            "real",
            _real_co_143_predecessor(tmp_path),
            _real_co_144_roster(),
            89,
            _real_derivation_judgements(),
        )


def test_golden_render_is_byte_exact() -> None:
    """Compare the golden outside the three contract-bounded regions.

    Before: the predecessor and successor fixtures differ in the bounded
    cascade, step-9 citations/remission, and procedure region.
    During: remove exactly those literal regions from both renderings.
    After: the remaining text is compared as text and UTF-8 bytes.
    """

    def comparable(text: str) -> str:
        cascade_start = text.index(render_latido_module._CASCADE_START) + len(
            render_latido_module._CASCADE_START
        )
        cascade_end = text.index(render_latido_module._CASCADE_END, cascade_start)
        text = text[:cascade_start] + text[cascade_end:]
        step9_match = re.search(r"(?m)^9\. Contexto propio:.*$", text)
        assert step9_match is not None
        step9 = step9_match.group(0)
        step9 = render_latido_module._SALTO_CITATION_PATTERN.sub("", step9)
        step9 = re.sub(
            r"\(historico de saltos.*?session_registry\.json\)\. ?", "", step9
        )
        procedure_start = step9.index("Procedimiento: ")
        procedure_end = step9.index(" (procedimiento de ticket", procedure_start)
        step9 = step9[:procedure_start] + step9[procedure_end:]
        return text[: step9_match.start()] + step9 + text[step9_match.end() :]

    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())
    expected_text = comparable(SUCCESSOR.read_text(encoding="utf-8"))
    expected_bytes = expected_text.encode("utf-8")
    output = comparable(output)

    assert rc == 0
    assert output == expected_text
    assert output.encode("utf-8") == expected_bytes


def test_missing_judgment_is_rc3_and_named() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    rc, output = render_latido(PREDECESSOR, roster, 2, {})

    assert rc == 3
    assert "hueco de JUICIO no rellenado: nota_derivacion" in output
    assert "hueco de JUICIO no rellenado: objetivo_en_curso" in output
    assert "hueco de JUICIO no rellenado: secciones_postcompactacion_nueva" in output
    assert "DIFERENCIAS:" in output


def test_foreign_mcp_id_is_rc2(tmp_path: Path) -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    predecessor = tmp_path / "predecessor.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "\nmcp:foreign-id\n", encoding="utf-8"
    )
    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "id mcp ajeno al roster: mcp:foreign-id" in output


def test_extra_roster_field_is_rc2() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    roster["active_roles"]["orquestador"]["extra"] = "not consumed"
    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "campo de roster no consumido: extra en active_roles.orquestador" in output


def test_go_index_is_derived_from_a_non_one_predecessor(tmp_path: Path) -> None:
    fixture = PREDECESSOR.read_text(encoding="utf-8")
    match = re.search(r"(?m)^9\. Contexto propio:.*$", fixture)
    assert match is not None
    step9 = match.group(0)
    for literal in ("fila b1", "Go relevo 24h 1"):
        assert step9.count(literal) == 1
    mutated_step9 = step9.replace("fila b1", "fila b4").replace(
        "Go relevo 24h 1", "Go relevo 24h 4"
    )
    predecessor = tmp_path / "go-index-4.md"
    predecessor.write_text(
        fixture[: match.start()] + mutated_step9 + fixture[match.end() :],
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 7, _juicios_sucesor())

    assert rc == 0
    rendered_step9 = re.search(r"(?m)^9\. Contexto propio:.*$", output)
    assert rendered_step9 is not None
    assert "fila b7" in rendered_step9.group(0)
    assert "Go relevo 24h 7" in rendered_step9.group(0)
    for literal in ("fila b4", "fila b1", "Go relevo 24h 4", "Go relevo 24h 1"):
        assert literal not in rendered_step9.group(0)


def test_context_code_must_match_cited_supervisor() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    roster["cadena_contexto"][0]["session_code"] = "CO-99"

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert (
        "roster.cadena_contexto[0] no coincide con la identidad de supervisora "
        "citada en el predecesor"
    ) in output


def test_context_thread_id_must_match_cited_supervisor() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    roster["cadena_contexto"][0]["threadId"] = (
        "mcp:00000000-0000-4000-8000-000000000025"
    )

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert (
        "roster.cadena_contexto[0] no coincide con la identidad de supervisora "
        "citada en el predecesor"
    ) in output


def test_duplicate_cascade_anchor_is_rc2(tmp_path: Path) -> None:
    predecessor = tmp_path / "duplicate-cascade.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "la cascada es ", encoding="utf-8"
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "regla R2: esperado 1, encontrado 2" in output


def test_duplicate_r6_anchor_is_rc2(tmp_path: Path) -> None:
    predecessor = tmp_path / "duplicate-r6.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "ARRANQUE_CO-55 s.1",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "regla R6: esperado 1, encontrado 2" in output


def test_duplicate_step9_r3_anchor_is_rc2(tmp_path: Path) -> None:
    fixture = PREDECESSOR.read_text(encoding="utf-8")
    match = re.search(r"(?m)^9\. Contexto propio:.*$", fixture)
    assert match is not None
    step9 = match.group(0)
    assert step9.count("fila b1") == 1
    predecessor = tmp_path / "duplicate-r3.md"
    predecessor.write_text(
        fixture[: match.end()] + " fila b1" + fixture[match.end() :],
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "regla R3 fila b1: esperado 1, encontrado 2" in output


def test_status_line_is_forced_to_vigente(tmp_path: Path) -> None:
    predecessor = tmp_path / "other-status.md"
    fixture = PREDECESSOR.read_text(encoding="utf-8")
    predecessor.write_text(
        fixture.replace("ESTADO: VIGENTE", "ESTADO: OTRA_COSA", 1), encoding="utf-8"
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert output.splitlines()[0] == "ESTADO: VIGENTE"


def test_predecessor_sha12_matches_independent_hash() -> None:
    expected = hashlib.sha256(PREDECESSOR.read_bytes()).hexdigest()[:12]

    assert predecessor_sha12(PREDECESSOR) == expected
    assert predecessor_sha12(PREDECESSOR) == "0dfa47ca7bc9"


def test_render_blindado_for_salto_x_to_x_mas_uno(tmp_path: Path) -> None:
    predecessor = tmp_path / "salto.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "\npara el salto CO-55 -> CO-55\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert "para el salto CO-56 -> CO-57" in output


def test_judgement_span_preserves_literal_salto_phrase(tmp_path: Path) -> None:
    predecessor = tmp_path / "judgement-salto.md"
    predecessor.write_text(PREDECESSOR.read_text(encoding="utf-8"), encoding="utf-8")
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    juicios = _juicios_sucesor()
    juicios["nota_derivacion"] = (
        "[literal para el salto CO-56 -> CO-56] " + juicios["nota_derivacion"]
    )

    rc, output = render_latido(predecessor, roster, 2, juicios)

    assert rc == 0
    assert "literal para el salto CO-56 -> CO-56" in output
    assert "para el salto CO-56 -> CO-57" in output


def test_r3_does_not_corrupt_objective_judgement_with_step9_literals() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    juicios = _juicios_sucesor()
    juicios["objetivo_en_curso"] = (
        "(ARRANQUE_CO-56_20261108.md s.2: conservar Go relevo 24h 1 y fila b1)"
    )

    rc, output = render_latido(PREDECESSOR, roster, 2, juicios)

    assert rc == 0
    assert juicios["objetivo_en_curso"] in output


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ("fila b10", "fila b10"),
        ("fila b11", "fila b11"),
        ("Go relevo 24h 10", "Go relevo 24h 10"),
        ("Go relevo 24h 11", "Go relevo 24h 11"),
        ("xfila b1", "xfila b1"),
        ("fila b1x", "fila b1x"),
        ("Go relevo 24h 1.", "Go relevo 24h 2."),
    ],
)
def test_r3_replaces_only_bounded_references(
    tmp_path: Path, literal: str, expected: str
) -> None:
    predecessor = tmp_path / "r3-boundaries.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + f"\nReferencia: {literal}\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert f"Referencia: {expected}" in output


def test_r3_preserves_literal_sentinel_names(tmp_path: Path) -> None:
    predecessor = tmp_path / "r3-sentinels.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8")
        + "\nConservar literalmente __GO_INDEX__ y __GO_NEXT__.\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert "Conservar literalmente __GO_INDEX__ y __GO_NEXT__." in output


def test_r3_successor_reference_uses_next_successor(
    tmp_path: Path,
) -> None:
    predecessor = tmp_path / "r3-successor.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8")
        + "\nReferencia futura: Go relevo 24h 2.\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert "Referencia futura: Go relevo 24h 3." in output


@pytest.mark.parametrize(
    ("marker", "expected_rc", "message"),
    [
        ("[[JUICIO:pendiente", 2, "marcador de JUICIO desconocido: pendiente"),
        (
            "[[JUICIO:nota_derivacion",
            3,
            "hueco de JUICIO no rellenado: nota_derivacion",
        ),
    ],
)
def test_unclosed_predecessor_judgement_marker_is_detected(
    tmp_path: Path, marker: str, expected_rc: int, message: str
) -> None:
    predecessor = tmp_path / "unclosed-marker.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + f"\n{marker}\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == expected_rc
    assert message in output


def test_api_rejects_multiline_judgement_before_filling_spans() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    juicios = _juicios_sucesor()
    juicios["nota_derivacion"] = "[x]\ny"

    rc, output = render_latido(PREDECESSOR, roster, 2, juicios)

    assert rc == 2
    assert "juicio multilinea: nota_derivacion" in output


def test_cli_trims_one_final_newline_but_preserves_internal_newline(
    tmp_path: Path,
) -> None:
    juicio_paths = {}
    juicios = _juicios_sucesor()
    for name, value in juicios.items():
        path = tmp_path / f"{name}.txt"
        path.write_text(value, encoding="utf-8")
        juicio_paths[name] = path
    juicio_paths["nota_derivacion"].write_bytes(b"[x]\ny\n")
    command = [
        sys.executable,
        str(ROOT / "scripts/flight/render_latido.py"),
        "--predecessor",
        str(PREDECESSOR),
        "--roster",
        str(ROSTER),
        "--go-index",
        "2",
    ]
    for name, path in juicio_paths.items():
        command.extend(["--juicio", f"{name}=@{path}"])

    result = subprocess.run(command, capture_output=True, check=False)

    assert result.returncode == 2
    assert "juicio multilinea: nota_derivacion" in result.stdout.decode("utf-8")

    juicio_paths["nota_derivacion"].write_bytes(b"[x]\n")
    valid_result = subprocess.run(command, capture_output=True, check=False)

    assert valid_result.returncode == 0


def test_cli_trims_only_one_final_lf_from_juicio_file(tmp_path: Path) -> None:
    juicio_paths = {}
    for name, value in _juicios_sucesor().items():
        path = tmp_path / f"{name}.txt"
        path.write_text(value, encoding="utf-8")
        juicio_paths[name] = path
    juicio_paths["nota_derivacion"].write_bytes(b"[x]\n\n")
    command = [
        sys.executable,
        str(ROOT / "scripts/flight/render_latido.py"),
        "--predecessor",
        str(PREDECESSOR),
        "--roster",
        str(ROSTER),
        "--go-index",
        "2",
    ]
    for name, path in juicio_paths.items():
        command.extend(["--juicio", f"{name}=@{path}"])

    result = subprocess.run(command, capture_output=True, check=False)

    assert result.returncode == 2
    assert "juicio multilinea: nota_derivacion" in result.stdout.decode("utf-8")


def test_cli_trims_only_one_final_crlf_from_juicio_file(tmp_path: Path) -> None:
    juicio_paths = {}
    for name, value in _juicios_sucesor().items():
        path = tmp_path / f"{name}.txt"
        path.write_text(value, encoding="utf-8")
        juicio_paths[name] = path
    juicio_paths["nota_derivacion"].write_bytes(b"[x]\r\n\r\n")
    command = [
        sys.executable,
        str(ROOT / "scripts/flight/render_latido.py"),
        "--predecessor",
        str(PREDECESSOR),
        "--roster",
        str(ROSTER),
        "--go-index",
        "2",
    ]
    for name, path in juicio_paths.items():
        command.extend(["--juicio", f"{name}=@{path}"])

    result = subprocess.run(command, capture_output=True, check=False)

    assert result.returncode == 2
    assert "juicio multilinea: nota_derivacion" in result.stdout.decode("utf-8")


def test_module_docstring_lists_r4_status_rule() -> None:
    assert "R4" in render_latido_module.__doc__
    assert "ESTADO" in render_latido_module.__doc__


def test_nested_parentheses_in_objective_judgement_are_replaced_as_one_span(
    tmp_path: Path,
) -> None:
    fixture = PREDECESSOR.read_text(encoding="utf-8")
    old_objective = re.search(r"\(ARRANQUE_CO-55_20261108\.md s\.2: .*?\)", fixture)
    assert old_objective is not None
    nested_objective = "(ARRANQUE_CO-55_20261108.md s.2: tarea (anidada) pendiente)"
    predecessor = tmp_path / "nested-objective.md"
    predecessor.write_text(
        fixture[: old_objective.start()]
        + nested_objective
        + fixture[old_objective.end() :],
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    replacement = "(ARRANQUE_CO-56_20261108.md s.2: objetivo nuevo)"
    juicios = _juicios_sucesor()
    juicios["objetivo_en_curso"] = replacement

    rc, output = render_latido(predecessor, roster, 2, juicios)

    assert rc == 0
    assert replacement in output
    assert "tarea (anidada) pendiente" not in output
    assert f"{replacement} pendiente)" not in output


def test_cli_stdout_is_exact_utf8_without_crlf_translation(tmp_path: Path) -> None:
    juicios = _juicios_sucesor()
    juicios["nota_derivacion"] = "[derivación ñ] á"
    command = [
        sys.executable,
        str(ROOT / "scripts/flight/render_latido.py"),
        "--predecessor",
        str(PREDECESSOR),
        "--roster",
        str(ROSTER),
        "--go-index",
        "2",
    ]
    for name, value in juicios.items():
        path = tmp_path / f"{name}.txt"
        path.write_text(value, encoding="utf-8", newline="")
        command.extend(["--juicio", f"{name}=@{path}"])

    result = subprocess.run(command, capture_output=True, check=False)

    assert result.returncode == 0
    assert "[derivación ñ] á".encode() in result.stdout
    assert b"\r\n" not in result.stdout


def test_predecessor_free_text_unknown_judgement_marker_is_rc2(tmp_path: Path) -> None:
    predecessor = tmp_path / "unknown-marker.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "\n[[JUICIO:pendiente]]\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "marcador de JUICIO desconocido: pendiente" in output


def test_predecessor_free_text_known_judgement_marker_is_rc3(tmp_path: Path) -> None:
    predecessor = tmp_path / "known-marker.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "\n[[JUICIO:nota_derivacion]]\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 3
    assert "hueco de JUICIO no rellenado: nota_derivacion" in output


def test_predecessor_free_text_known_single_close_marker_with_text_is_rc3(
    tmp_path: Path,
) -> None:
    predecessor = tmp_path / "known-single-close-marker.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8")
        + "\n[[JUICIO:nota_derivacion] y resto.\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 3
    assert "hueco de JUICIO no rellenado: nota_derivacion" in output


def test_predecessor_free_text_unknown_single_close_marker_with_text_is_rc2(
    tmp_path: Path,
) -> None:
    predecessor = tmp_path / "unknown-single-close-marker.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "\n[[JUICIO:pendiente] y resto.\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "marcador de JUICIO desconocido: pendiente" in output


def test_salto_x_to_x_after_last_protected_span_is_corrected(
    tmp_path: Path,
) -> None:
    predecessor = tmp_path / "late-salto.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8")
        + "\nTexto posterior al ultimo span protegido: "
        + "para el salto CO-55 -> CO-55\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert (
        "Texto posterior al ultimo span protegido: para el salto CO-56 -> CO-57"
        in output
    )
    assert (
        "Texto posterior al ultimo span protegido: para el salto CO-55 -> CO-55"
        not in output
    )


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda text: text.replace(
                "Eres CO-55, sesion coordinadora ACTIVA",
                "Eres CO-55, sesion coordinadora",
            ),
            "identidades o paso 9 no derivables del predecesor",
        ),
        (
            lambda text: text.replace(
                "Tu supervisora es CO-54 (mcp:", "Tu supervisora es CO-54 sin mcp:"
            ),
            "identidades o paso 9 no derivables del predecesor",
        ),
        (
            lambda text: text.replace(
                "fila b1 de diseno/GO_RELEVO_24H_REGISTRO.md",
                "fila b1 de diseno/registro.md",
            ),
            "go_index_predecesor no derivable del paso 9",
        ),
        (
            lambda text: text.replace(
                "ARRANQUE_CO-55 s.1 y ", "ARRANQUE_CO-55 s.1 ", 1
            ),
            "ancla R2b 'y ' no encontrada",
        ),
        (
            lambda text: text.replace(
                " (procedimiento de ticket", " (procedimiento de caso", 1
            ),
            "ancla final R2b no encontrada",
        ),
    ],
)
def test_missing_required_predecessor_anchor_is_rc2(
    tmp_path: Path, mutate, message: str
) -> None:
    predecessor = tmp_path / "missing-anchor.md"
    predecessor.write_text(
        mutate(PREDECESSOR.read_text(encoding="utf-8")), encoding="utf-8"
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert message in output


@pytest.mark.parametrize("content", ["", "una sola linea"])
def test_predecessor_without_judgement_header_is_rc2(
    tmp_path: Path, content: str
) -> None:
    predecessor = tmp_path / "short.md"
    predecessor.write_text(content, encoding="utf-8")
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "el predecesor no tiene linea de cabecera JUICIO" in output


@pytest.mark.parametrize("location", ["orquestador", "supervisor"])
def test_missing_role_roster_identity_is_rc2(location: str) -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    del roster["active_roles"][location]["threadId"]

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert f"campo de roster ausente: threadId en active_roles.{location}" in output


def test_missing_context_roster_identity_is_rc2() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    del roster["cadena_contexto"][0]["session_code"]

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "campo de roster ausente: session_code en cadena_contexto[0]" in output


@pytest.mark.parametrize("value", ["CO-56\n", "CO 56"])
def test_roster_session_code_requires_strict_form(value: str) -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    roster["active_roles"]["orquestador"]["session_code"] = value

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert (
        "session_code en active_roles.orquestador no tiene la forma esperada" in output
    )


@pytest.mark.parametrize("value", ["mcp:ABCDEF12", "ABCDEF12"])
def test_roster_thread_id_requires_strict_form(value: str) -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    roster["active_roles"]["orquestador"]["threadId"] = value

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "threadId en active_roles.orquestador no tiene la forma esperada" in output


def test_cli_rejects_unknown_judgement_name(tmp_path: Path, capsys) -> None:
    juicio = tmp_path / "juicio.txt"
    juicio.write_text("texto", encoding="utf-8")

    rc = _main(
        [
            "--predecessor",
            str(PREDECESSOR),
            "--roster",
            str(ROSTER),
            "--go-index",
            "2",
            "--juicio",
            f"foo=@{juicio}",
        ]
    )

    assert rc == 2
    assert "--juicio con nombre desconocido: foo" in capsys.readouterr().out


def test_cli_rejects_valid_json_roster_that_is_not_dict(tmp_path: Path, capsys) -> None:
    roster = tmp_path / "list.json"
    roster.write_text("[]", encoding="utf-8")

    rc = _main(
        [
            "--predecessor",
            str(PREDECESSOR),
            "--roster",
            str(roster),
            "--go-index",
            "2",
        ]
    )

    assert rc == 2
    assert (
        "campo de roster no consumido: roster debe ser dict" in capsys.readouterr().out
    )


def test_synthetic_pair_derives_identities_without_pair_literals(
    tmp_path: Path,
) -> None:
    source = (ROOT / "scripts/flight/render_latido.py").read_text(encoding="utf-8")
    fixture = PREDECESSOR.read_text(encoding="utf-8")
    assert all(
        literal not in source
        for literal in ("CO-55", "CO-54", "mcp:0355d3c5", "mcp:d0cbb70f")
    )
    assert any(
        literal in fixture
        for literal in ("CO-55", "CO-54", "mcp:0355d3c5", "mcp:d0cbb70f")
    )

    synthetic = (
        fixture.replace("CO-55", "CO-56")
        .replace("CO-54", "CO-55")
        .replace("CO-53", "CO-54")
        .replace(
            "mcp:00000000-0000-4000-8000-000000000002",
            "mcp:00000000-0000-4000-8000-000000000005",
        )
        .replace(
            "mcp:00000000-0000-4000-8000-000000000032",
            "mcp:00000000-0000-4000-8000-000000000012",
        )
        .replace(
            "mcp:00000000-0000-4000-8000-000000000028",
            "mcp:00000000-0000-4000-8000-000000000015",
        )
    )
    predecessor = tmp_path / "synthetic.md"
    predecessor.write_text(synthetic, encoding="utf-8")
    roster = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:00000000-0000-4000-8000-000000000006",
                "session_code": "CO-57",
            },
            "supervisor": {
                "threadId": "mcp:00000000-0000-4000-8000-000000000009",
                "session_code": "CO-56",
            },
        },
        "cadena_contexto": [
            {
                "threadId": "mcp:00000000-0000-4000-8000-000000000012",
                "session_code": "CO-55",
            }
        ],
    }
    rc, output = render_latido(
        predecessor,
        roster,
        9,
        {
            "nota_derivacion": "[synthetic]",
            "objetivo_en_curso": "(ARRANQUE_CO-57_20261108.md s.2: synthetic)",
            "secciones_postcompactacion_nueva": "s.8",
        },
    )

    assert rc == 0
    assert "Eres CO-57" in output
    assert (
        "Tu supervisora es CO-56 (mcp:00000000-0000-4000-8000-000000000009," in output
    )
    assert "cascada directa CO-55" in output
    assert "o 'CO-55'" in output
    assert "cascada directa CO-54" not in output
    assert "o 'CO-54'" not in output
    assert "cascada directa CO-55 (mcp:00000000-0000-4000-8000-000000000012)" in output
    assert "Go relevo 24h 9" in output


def test_module_docstring_declares_saliente_handoff_trigger() -> None:
    assert "saliente" in render_latido_module.__doc__
    assert "paquete de relevo" in render_latido_module.__doc__
    assert "lifecycle of scheduled tasks" in render_latido_module.__doc__


def test_module_and_function_docstrings_describe_three_judgement_values() -> None:
    assert "three judgement values" in render_latido_module.__doc__
    assert "three judgement values" in render_latido.__doc__


def test_objective_judgement_accepts_a_different_eight_digit_date(
    tmp_path: Path,
) -> None:
    predecessor_text = PREDECESSOR.read_text(encoding="utf-8").replace(
        "ARRANQUE_CO-55_20261108.md s.2", "ARRANQUE_CO-55_20270101.md s.2"
    )
    predecessor = tmp_path / "date.md"
    predecessor.write_text(predecessor_text, encoding="utf-8")
    juicios = _juicios_sucesor()
    juicios["objetivo_en_curso"] = juicios["objetivo_en_curso"].replace(
        "20261108", "20270101"
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, juicios)

    assert rc == 0
    assert "ARRANQUE_CO-56_20270101.md s.2" in output


def test_token_boundary_preserves_historical_code(tmp_path: Path) -> None:
    predecessor = tmp_path / "boundary.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "\nReferencia historica CO-550\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert "Referencia historica CO-550" in output


def test_token_boundary_preserves_prefixed_historical_code(tmp_path: Path) -> None:
    predecessor = tmp_path / "prefix-boundary.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "\nReferencia historica XCO-55\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert "Referencia historica XCO-55" in output


def test_token_boundary_allows_variable_length_successor_code(tmp_path: Path) -> None:
    predecessor = tmp_path / "variable-code.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "\nReferencia ficticia CO-550\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    roster["active_roles"]["orquestador"]["session_code"] = "CO-100"
    juicios = _juicios_sucesor()
    juicios["objetivo_en_curso"] = juicios["objetivo_en_curso"].replace(
        "CO-56", "CO-100"
    )

    rc, output = render_latido(predecessor, roster, 2, juicios)

    assert rc == 0
    assert "Eres CO-100" in output
    assert "Referencia ficticia CO-550" in output


@pytest.mark.parametrize("value", ["", "   ", "[[JUICIO:objetivo_en_curso]]"])
def test_empty_or_literal_judgement_is_rc3(value: str) -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    juicios = _juicios_sucesor()
    juicios["objetivo_en_curso"] = value

    rc, output = render_latido(PREDECESSOR, roster, 2, juicios)

    assert rc == 3
    assert "hueco de JUICIO no rellenado: objetivo_en_curso" in output


def test_partial_judgements_name_only_the_missing_block() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    juicios = _juicios_sucesor()
    del juicios["objetivo_en_curso"]

    rc, output = render_latido(PREDECESSOR, roster, 2, juicios)

    assert rc == 3
    assert "hueco de JUICIO no rellenado: objetivo_en_curso" in output
    assert "hueco de JUICIO no rellenado: nota_derivacion" not in output
    assert (
        "hueco de JUICIO no rellenado: secciones_postcompactacion_nueva" not in output
    )


def test_non_dict_roster_is_rc2_without_traceback() -> None:
    rc, output = render_latido(PREDECESSOR, 5, 2, _juicios_sucesor())

    assert rc == 2
    assert "campo de roster no consumido" in output


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("nota_derivacion", 5),
        ("objetivo_en_curso", ["x"]),
        ("secciones_postcompactacion_nueva", True),
    ],
)
def test_non_string_judgement_is_rc2_without_traceback(
    name: str, value: object
) -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    juicios = _juicios_sucesor()
    juicios[name] = value  # type: ignore[assignment]

    rc, output = render_latido(PREDECESSOR, roster, 2, juicios)

    assert rc == 2
    assert f"juicio no es texto: {name}" in output
    assert "Traceback" not in output


def test_non_string_roster_thread_id_is_rc2_without_traceback() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    roster["active_roles"]["supervisor"]["threadId"] = 5

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "threadId" in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda roster: roster.update({"schema_version": 1}), "raiz"),
        (
            lambda roster: roster["active_roles"].update({"ancestro_directo": {}}),
            "active_roles",
        ),
        (
            lambda roster: roster["cadena_contexto"].append(
                roster["cadena_contexto"][0].copy()
            ),
            "cadena_contexto",
        ),
    ],
)
def test_reduced_roster_shape_is_exact(mutate, expected: str) -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    mutate(roster)

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "campo de roster no consumido:" in output
    assert expected in output


def test_uppercase_foreign_mcp_id_is_rejected(tmp_path: Path) -> None:
    foreign_id = "mcp:" + "abcdef12-1234-4123-8123-123456789012".upper()
    predecessor = tmp_path / "uppercase-id.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + f"\n{foreign_id}\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert f"id mcp ajeno al roster: {foreign_id}" in output


def test_go_index_zero_is_rejected() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(PREDECESSOR, roster, 0, _juicios_sucesor())

    assert rc == 2
    assert "go_index debe ser entero >= 1, recibido: 0" in output


def test_cli_missing_roster_returns_rc2(capsys) -> None:
    rc = _main(
        [
            "--predecessor",
            str(PREDECESSOR),
            "--roster",
            str(PREDECESSOR.parent / "missing.json"),
            "--go-index",
            "2",
        ]
    )

    assert rc == 2
    assert "no se pudo leer --roster" in capsys.readouterr().out


def test_cli_missing_juicio_file_returns_rc2(tmp_path: Path, capsys) -> None:
    rc = _main(
        [
            "--predecessor",
            str(PREDECESSOR),
            "--roster",
            str(ROSTER),
            "--go-index",
            "2",
            "--juicio",
            f"nota_derivacion=@{tmp_path / 'missing.txt'}",
        ]
    )

    assert rc == 2
    assert "no se pudo leer --juicio" in capsys.readouterr().out


def test_cli_unwritable_out_returns_rc2(tmp_path: Path, capsys) -> None:
    rc = _main(
        [
            "--predecessor",
            str(PREDECESSOR),
            "--roster",
            str(ROSTER),
            "--go-index",
            "2",
            "--out",
            str(tmp_path / "missing-parent" / "rendered.md"),
        ]
    )

    assert rc == 2
    assert "no se pudo escribir --out" in capsys.readouterr().out


def test_cli_success_propagates_render_rc_and_writes_out(tmp_path: Path) -> None:
    paths = []
    juicios = _juicios_sucesor()
    for name, value in juicios.items():
        path = tmp_path / f"{name}.txt"
        path.write_text(value, encoding="utf-8")
        paths.append((name, path))
    out = tmp_path / "rendered.md"
    for name in (
        "LATIDO_CO-55_v7.1_20261108.md",
        "LATIDO_CO-56_v7.1_20261108.md",
        "LATIDO_SUPERVISORA_CO-55_sobre_CO-56_20261108.md",
    ):
        (tmp_path / name).write_text("staged", encoding="utf-8")
    args = [
        "--predecessor",
        str(PREDECESSOR),
        "--roster",
        str(ROSTER),
        "--go-index",
        "2",
        "--out",
        str(out),
        "--resolve-dir",
        str(tmp_path),
    ]
    for name, path in paths:
        args.extend(["--juicio", f"{name}=@{path}"])

    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    expected_rc, expected_output = render_latido(PREDECESSOR, roster, 2, juicios)
    actual_rc = _main(args)

    assert actual_rc == expected_rc == 0
    assert out.read_text(encoding="utf-8") == expected_output


def test_post_derivacion_flags_adjacent_duplicate_sentences(tmp_path: Path) -> None:
    unit_match = re.search(
        r"\(procedimiento de ticket; el ARRANQUE de CO-72.*?actor\.",
        _REAL_STEP9_CO_72,
    )
    assert unit_match is not None
    unit = unit_match.group(0)
    esperado = _REAL_STEP9_CO_72.count(unit)
    problemas = check_post_derivacion(_REAL_STEP9_CO_72, tmp_path)

    assert esperado >= 2
    assert len(problemas) == 1
    assert str(esperado) in problemas[0]
    assert "parrafo repetido:" in problemas[0]
    assert "Procedimiento: ARRANQUE_CO-72" in problemas[0]


def test_post_derivacion_flags_minimal_two_repetitions(tmp_path: Path) -> None:
    unit_match = re.search(
        r"\(procedimiento de ticket; el ARRANQUE de CO-67.*?actor\.",
        _REAL_STEP9_CO_67,
    )
    assert unit_match is not None
    esperado = _REAL_STEP9_CO_67.count(unit_match.group(0))
    problemas = check_post_derivacion(_REAL_STEP9_CO_67, tmp_path)

    assert esperado >= 2
    assert len(problemas) == 1
    assert str(esperado) in problemas[0]


def test_post_derivacion_control_dedup_clean(tmp_path: Path) -> None:
    unit_match = re.search(
        r"\(procedimiento de ticket; el ARRANQUE de CO-72.*?actor\.",
        _REAL_STEP9_CO_72,
    )
    assert unit_match is not None
    unica = _REAL_STEP9_CO_72.split(unit_match.group(0))[0] + unit_match.group(0)

    assert check_post_derivacion(unica, tmp_path) == []
    assert unica.count(unit_match.group(0)) == 1

    unit_match = re.search(
        r"\(procedimiento de ticket; el ARRANQUE de CO-67.*?actor\.",
        _REAL_STEP9_CO_67,
    )
    assert unit_match is not None
    unidad = unit_match.group(0)

    # Falso negativo medido: mayusculas/minusculas usan igualdad exacta.
    assert check_post_derivacion(f"{unidad} {unidad.upper()}", tmp_path) == []

    # Falsos negativos medidos: ? y ! no crean fronteras de frase.
    interrogacion = (
        "Frase larga de prueba que termina con interrogacion? "
        "Frase larga de prueba que termina con interrogacion?"
    )
    exclamacion = (
        "Frase larga de prueba que termina con exclamacion! "
        "Frase larga de prueba que termina con exclamacion!"
    )
    assert check_post_derivacion(interrogacion, tmp_path) == []
    assert check_post_derivacion(exclamacion, tmp_path) == []

    # Falso negativo medido: quitar el punto final rompe el sufijo exacto.
    assert check_post_derivacion(_REAL_STEP9_CO_67[:-1], tmp_path) == []

    # Falso negativo medido: la repeticion intercalada ABAB no es adyacente.
    relleno = "Relleno distinto con mas de veinte caracteres para separar frases."
    assert (
        check_post_derivacion(f"{unidad} {relleno} {unidad} {relleno}", tmp_path) == []
    )

    # Falsos negativos medidos x3: NBSP, tabuladores y doble espacio se colapsan.
    for separador in ("\u00a0", "\t", "  "):
        problemas = check_post_derivacion(
            f"{unidad} {unidad.replace(' ', separador)}", tmp_path
        )
        assert len(problemas) == 1
        assert "parrafo repetido:" in problemas[0]


def test_post_derivacion_threshold_applies_to_both_sentences(tmp_path: Path) -> None:
    larga = "Esta frase de control supera el umbral de veinte caracteres y termina en corta."
    corta = "corta."
    assert larga.endswith(corta)
    assert len(larga) >= 20
    assert len(corta) < 20
    assert check_post_derivacion(f"{larga} {corta}", tmp_path) == []

    larga_b = "Prefijo distinto de relleno mas largo y luego la cola compartida que supera veinte."
    corta_b = "la cola compartida que supera veinte."
    assert len(corta_b) >= 20
    assert larga_b.endswith(corta_b)
    assert len(check_post_derivacion(f"{larga_b} {corta_b}", tmp_path)) == 1


def test_post_derivacion_flags_missing_latido_citation_and_control(
    tmp_path: Path,
) -> None:
    texto = "Referencia: LATIDO_CO-70_v7.1_20261109.md"
    kwargs = {
        "self_name": "LATIDO_CO-72_v7.1_20261111.md",
        "predecessor_name": "LATIDO_CO-71_v7.1_20261111.md",
    }
    problemas = check_post_derivacion(texto, tmp_path, **kwargs)

    assert len(problemas) == 1
    assert "cita LATIDO inexistente" in problemas[0]
    assert "LATIDO_CO-70_v7.1_20261109.md" in problemas[0]
    (tmp_path / "LATIDO_CO-70_v7.1_20261109.md").write_text("x", encoding="utf-8")
    assert check_post_derivacion(texto, tmp_path, **kwargs) == []
    assert check_post_derivacion(texto, tmp_path) == []


def test_post_derivacion_resolves_dates_and_absolute_paths(tmp_path: Path) -> None:
    old = tmp_path / "LATIDO_CO-70_v7.1_20261109.md"
    old.write_text("old", encoding="utf-8")
    kwargs = {
        "self_name": "LATIDO_CO-72_v7.1_20261111.md",
        "predecessor_name": "LATIDO_CO-71_v7.1_20261111.md",
    }
    assert (
        check_post_derivacion(
            ".../diseno/LATIDO_CO-70_v7.1_20261109.md", tmp_path, **kwargs
        )
        == []
    )
    assert check_post_derivacion(str(old.resolve()), tmp_path, **kwargs) == []
    missing = str(tmp_path / "no-existe" / "LATIDO_CO-71_v7.1_20261109.md")
    problemas = check_post_derivacion(missing, tmp_path, **kwargs)
    assert len(problemas) == 1
    assert missing in problemas[0]


def test_post_derivacion_pair_exemption_scenarios(tmp_path: Path) -> None:
    kwargs = {
        "self_name": "LATIDO_CO-72_v7.1_20261111.md",
        "predecessor_name": "LATIDO_CO-71_v7.1_20261111.md",
    }
    tokens = [
        "LATIDO_CO-70_v7.1_20261109.md",
        "LATIDO_CO-71_v7.1_20261109.md",
        "LATIDO_SUPERVISORA_CO-71_sobre_CO-72_20261111.md",
        "LATIDO_SUPERVISORA_CO-99_sobre_CO-72_20261111.md",
        "LATIDO_SUPERVISORA_CO-71_sobre_CO-72_20261109.md",
        "C:/Temp/directorio-que-no-existe/LATIDO_SUPERVISORA_CO-71_sobre_CO-72_20261111.md",
    ]
    problemas = check_post_derivacion(" ".join(tokens), tmp_path, **kwargs)
    assert len(problemas) == 4
    assert all(
        token in " ".join(problemas)
        for token in (tokens[0], tokens[1], tokens[3], tokens[4])
    )
    assert all(token not in " ".join(problemas) for token in (tokens[2], tokens[5]))


def test_post_derivacion_pair_exemption_fail_closed_pattern(tmp_path: Path) -> None:
    citation = "LATIDO_CO-72_v7.1_20261111.md"
    assert (
        len(
            check_post_derivacion(
                citation,
                tmp_path,
                self_name="LATIDO_CO-72_v7.1_20261111.md",
                predecessor_name="sin-patron.md",
            )
        )
        == 1
    )
    assert (
        len(
            check_post_derivacion(
                citation,
                tmp_path,
                self_name="rendered.md",
                predecessor_name="LATIDO_CO-71_v7.1_20261111.md",
            )
        )
        == 1
    )
    assert (
        check_post_derivacion(
            citation,
            tmp_path,
            self_name="LATIDO_CO-72_v7.1_20261111.md",
            predecessor_name="LATIDO_CO-71_v7.1_20261111.md",
        )
        == []
    )


def test_cli_post_derivacion_wiring_rc4_blocks_out_write(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    juicios = _juicios_sucesor()
    args = [
        "--predecessor",
        str(PREDECESSOR),
        "--roster",
        str(ROSTER),
        "--go-index",
        "2",
        "--out",
        str(tmp_path / "clean.md"),
        "--resolve-dir",
        str(tmp_path),
    ]
    for name, value in juicios.items():
        path = tmp_path / f"{name}.txt"
        path.write_text(value, encoding="utf-8")
        args.extend(["--juicio", f"{name}=@{path}"])
    for name in (
        "LATIDO_CO-55_v7.1_20261108.md",
        "LATIDO_CO-56_v7.1_20261108.md",
        "LATIDO_SUPERVISORA_CO-55_sobre_CO-56_20261108.md",
    ):
        (tmp_path / name).write_text("staged", encoding="utf-8")
    juicio_args = []
    for name in juicios:
        juicio_args.extend(["--juicio", f"{name}=@{tmp_path / name}.txt"])
    assert _main(args) == 0
    assert (tmp_path / "clean.md").is_file()
    assert (tmp_path / "clean.md").read_text(encoding="utf-8")

    calls = []
    monkeypatch.setattr(
        render_latido_module,
        "check_post_derivacion",
        lambda *args, **kwargs: calls.append(args) or [],
    )
    rc = _main(
        [
            "--predecessor",
            str(PREDECESSOR),
            "--roster",
            str(tmp_path / "missing.json"),
            "--go-index",
            "2",
        ]
    )
    assert rc == 2
    assert calls == []
    rc = _main(
        [
            "--predecessor",
            str(PREDECESSOR),
            "--roster",
            str(ROSTER),
            "--go-index",
            "2",
        ]
    )
    assert rc == 3
    assert calls == []
    monkeypatch.undo()

    repeated = tmp_path / "repeated.md"
    repeated.write_text(
        PREDECESSOR.read_text(encoding="utf-8")
        + "\nFrase repetida de control con mas de veinte caracteres. Frase repetida de control con mas de veinte caracteres.\n",
        encoding="utf-8",
    )
    rc = _main(
        [
            "--predecessor",
            str(repeated),
            "--roster",
            str(ROSTER),
            "--go-index",
            "2",
            "--out",
            str(tmp_path / "rc4.md"),
            "--resolve-dir",
            str(tmp_path),
            *juicio_args,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 4
    assert not (tmp_path / "rc4.md").exists()
    assert "CHECK POST-DERIVACION: " in captured.out
    assert "DIFERENCIAS:" in captured.out
    rc = _main(
        [
            "--predecessor",
            str(repeated),
            "--roster",
            str(ROSTER),
            "--go-index",
            "2",
            *juicio_args,
        ]
    )
    assert rc == 4
    assert "CHECK POST-DERIVACION: " in capsys.readouterr().out
    ghost = tmp_path / "ghost.md"
    ghost.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + "\nLATIDO_FANTASMA_20261111.md\n",
        encoding="utf-8",
    )
    assert (
        _main(
            [
                "--predecessor",
                str(ghost),
                "--roster",
                str(ROSTER),
                "--go-index",
                "2",
                *juicio_args,
            ]
        )
        == 0
    )


def test_module_docstring_declares_post_derivacion_and_rc4() -> None:
    doc = render_latido_module.__doc__
    assert "rc 4" in doc
    assert "CHECK POST-DERIVACION" in doc
    assert "CERRAR_Y_SALTAR" in doc
    assert "ctx_acumulado" in doc
    assert "--out" in doc


@pytest.mark.parametrize("thread_id", [[], {}, None])
def test_unhashable_or_none_thread_id_is_rc2_without_traceback(thread_id) -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    roster["active_roles"]["supervisor"]["threadId"] = thread_id

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "threadId" in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("nota_derivacion", "x [[JUICIO:otro]]"),
        ("objetivo_en_curso", "x [[JUICIO:otro]]"),
        ("secciones_postcompactacion_nueva", "x [[JUICIO:otro]]"),
    ],
)
def test_foreign_judgement_marker_is_named_for_its_own_block(name, value) -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    juicios = _juicios_sucesor()
    juicios[name] = value

    rc, output = render_latido(PREDECESSOR, roster, 2, juicios)

    assert rc == 3
    assert f"hueco de JUICIO no rellenado: {name}" in output
    assert "otro" not in output.split("DIFERENCIAS:", 1)[1]


def test_judgement_cannot_introduce_foreign_mcp_id() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    juicios = _juicios_sucesor()
    juicios["nota_derivacion"] = "[mcp:foreign-id]"

    rc, output = render_latido(PREDECESSOR, roster, 2, juicios)

    assert rc == 2
    assert "id mcp ajeno al roster introducido por JUICIO: mcp:foreign-id" in output


def test_crlf_predecessor_is_preserved(tmp_path: Path) -> None:
    predecessor = tmp_path / "crlf.md"
    predecessor.write_bytes(
        PREDECESSOR.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8")
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert "\r\n" in output
    assert "\n" not in output.replace("\r\n", "")


def _real_roster() -> dict:
    return {
        "schema_version": 1,
        "flight_id": "vuelo-test",
        "updated_at": "2026-11-08T08:44:56+01:00",
        "updated_by": "CO-9",
        "rules": {},
        "session_types": {},
        "sessions": {},
        "capacity": {},
        "excluded_lenses": {},
        "quota": {},
        "quarantine": {},
        "roster_fixes": [],
        "active_roles": {
            "_schema_note": "known metadata",
            "orquestador": {
                "threadId": "mcp:00000000-0000-4000-8000-000000000017",
                "session_code": "CO-56",
                "since": "2026-11-08T08:44:56+01:00",
                "set_by": "CO-54",
                "predecessor_threadId": "mcp:00000000-0000-4000-8000-000000000002",
                "version": 147,
                "status": "active",
                "approved_by": "CO-54",
                "nota": "known",
                "estado": "ACTIVO",
            },
            "supervisor": {
                "threadId": "mcp:00000000-0000-4000-8000-000000000002",
                "session_code": "CO-55",
                "since": "2026-11-08T08:44:56+01:00",
                "set_by": "CO-54",
                "predecessor_threadId": "mcp:00000000-0000-4000-8000-000000000032",
                "version": 48,
                "status": "active",
            },
        },
        "cadena_contexto": [
            {
                "threadId": "mcp:00000000-0000-4000-8000-000000000032",
                "session_code": "CO-54",
                "hasta": "2026-11-08T08:44:56+01:00",
                "cerrado_por": "CO-54",
            },
            {"threadId": "mcp:old", "session_code": "CO-53"},
        ],
    }


def test_reduce_real_roster_to_consumed_shape() -> None:
    reduced, errors = reduce_roster(_real_roster())

    assert errors == []
    assert reduced == json.loads(ROSTER.read_text(encoding="utf-8"))


def test_reduce_real_roster_rejects_unknown_field() -> None:
    real = _real_roster()
    real["active_roles"]["supervisor"]["new_field"] = "must fail"

    reduced, errors = reduce_roster(real)

    assert reduced is None
    assert (
        "campo de roster no consumido: new_field en active_roles.supervisor" in errors
    )


def test_cli_accepts_real_roster_shape(tmp_path: Path) -> None:
    roster_path = tmp_path / "real-roster.json"
    roster_path.write_text(json.dumps(_real_roster()), encoding="utf-8")
    args = [
        "--predecessor",
        str(PREDECESSOR),
        "--roster",
        str(roster_path),
        "--go-index",
        "2",
    ]
    for name, value in _juicios_sucesor().items():
        path = tmp_path / f"{name}.txt"
        path.write_text(value, encoding="utf-8")
        args.extend(["--juicio", f"{name}=@{path}"])

    assert _main(args) == 0


def test_missing_predecessor_is_rc2_in_core_and_cli(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing.md"
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(missing, roster, 2, _juicios_sucesor())
    cli_rc = _main(
        [
            "--predecessor",
            str(missing),
            "--roster",
            str(ROSTER),
            "--go-index",
            "2",
        ]
    )

    assert rc == cli_rc == 2
    assert "DIFERENCIAS:" in output
    assert "DIFERENCIAS:" in capsys.readouterr().out


def test_invalid_utf8_predecessor_is_rc2(tmp_path: Path) -> None:
    predecessor = tmp_path / "invalid.md"
    predecessor.write_bytes(b"\xff\xfe\x00ESTADO")
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "Traceback" not in output


def test_cli_malformed_roster_json_is_rc2(tmp_path: Path, capsys) -> None:
    roster = tmp_path / "bad.json"
    roster.write_text("{invalido", encoding="utf-8")

    rc = _main(
        [
            "--predecessor",
            str(PREDECESSOR),
            "--roster",
            str(roster),
            "--go-index",
            "2",
        ]
    )

    assert rc == 2
    assert "no se pudo leer --roster" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda text: text.replace(
                text.splitlines(keepends=True)[1], "VERSION\n", 1
            ),
            "nota_derivacion",
        ),
        (
            lambda text: re.sub(
                r"\(ARRANQUE_CO-55_20261108\.md s\.2: .*?\)",
                "",
                text,
                count=1,
            ),
            "objetivo_en_curso",
        ),
        (
            lambda text: text.replace("ARRANQUE_CO-55 s.1", "ARRANQUE_CO-55 s.0", 1),
            "ancla R2b de ARRANQUE no encontrada",
        ),
        (
            lambda text: text.replace("la cascada es CO-53", "la cascada es", 1),
            "primer elemento de cascada no derivable",
        ),
    ],
)
def test_missing_required_anchor_is_rc2(tmp_path: Path, mutate, message: str) -> None:
    predecessor = tmp_path / "mutated.md"
    predecessor.write_text(
        mutate(PREDECESSOR.read_text(encoding="utf-8")), encoding="utf-8"
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert message in output


def test_duplicate_cascade_end_anchor_is_rc2(tmp_path: Path) -> None:
    predecessor = tmp_path / "duplicate-end.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8") + " LATIDO DE PROGRESO",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "regla R2b-fin: esperado 1, encontrado 2" in output


def test_missing_cascade_end_anchor_is_rc2(tmp_path: Path) -> None:
    predecessor = tmp_path / "missing-end.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8").replace(" LATIDO DE PROGRESO", "", 1),
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "regla R2b-fin: esperado 1, encontrado 0" in output


def test_zombie_id_in_replaced_old_judgement_is_ignored(tmp_path: Path) -> None:
    predecessor = tmp_path / "zombie-judgement.md"
    text = PREDECESSOR.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    lines[1] = lines[1].replace(
        "]", " mcp:zombie-00000000-0000-4000-8000-000000000000]", 1
    )
    predecessor.write_text("".join(lines), encoding="utf-8")
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert "zombie-00000000" not in output


@pytest.mark.parametrize(
    ("first_line_end", "rest_end"), [("\n", "\r\n"), ("\r\n", "\n")]
)
def test_forced_status_uses_first_line_ending(
    tmp_path: Path, first_line_end: str, rest_end: str
) -> None:
    lines = PREDECESSOR.read_text(encoding="utf-8").splitlines()
    predecessor = tmp_path / "mixed-endings.md"
    predecessor.write_bytes(
        (
            first_line_end.join([lines[0], lines[1]])
            + rest_end
            + rest_end.join(lines[2:])
            + rest_end
        ).encode("utf-8")
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert output.startswith("ESTADO: VIGENTE" + first_line_end)


@pytest.mark.parametrize("go_index", [2.5, "2", -1, True, False])
def test_invalid_go_index_is_rc2(go_index) -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(PREDECESSOR, roster, go_index, _juicios_sucesor())

    assert rc == 2
    assert "go_index debe ser entero >= 1" in output


def test_non_numeric_session_code_is_rc2() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    roster["active_roles"]["orquestador"]["session_code"] = "CO-ABC"

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert (
        "session_code en active_roles.orquestador no tiene la forma esperada" in output
    )


def test_cli_malformed_juicio_keeps_argparse_error(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _main(
            [
                "--predecessor",
                str(PREDECESSOR),
                "--roster",
                str(ROSTER),
                "--go-index",
                "2",
                "--juicio",
                "malformado",
            ]
        )

    assert exc_info.value.code == 2
    assert "--juicio debe tener la forma nombre=@fichero" in capsys.readouterr().err


def test_late_exception_keeps_accumulated_problems(tmp_path: Path) -> None:
    predecessor = tmp_path / "multiple-errors.md"
    text = PREDECESSOR.read_text(encoding="utf-8")
    text = text.replace("ARRANQUE_CO-55 s.1", "ARRANQUE_CO-55 s.0", 1)
    text += "la cascada es "
    predecessor.write_text(text, encoding="utf-8")
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "regla R2: esperado 1, encontrado 2" in output
    assert "ancla R2b de ARRANQUE no encontrada" in output


def test_norm_and_latido_template_declare_the_same_go_format() -> None:
    norm = (ROOT / ".agent/rules/common/avisos_parada_vuelo.md").read_text(
        encoding="utf-8"
    )
    fixture = PREDECESSOR.read_text(encoding="utf-8")
    go_section = fixture.split("GO AL USUARIO:", 1)[1].split("```", 1)[0]
    step9_match = re.search(r"(?m)^9\. Contexto propio:.*$", fixture)
    assert step9_match is not None
    literals = (
        "Go_Relevo_N",
        "N desde 32",
        "TEXTO PLANO",
        "FUERA de bloques de codigo",
        "sin espacios finales",
        "b1-b31",
        "Go relevo 24h N",
    )

    for literal in literals:
        assert literal in norm
        assert literal in go_section
    assert "(hoy" not in step9_match.group(0)


def test_r3_preserves_new_format_citation(tmp_path: Path) -> None:
    fixture = PREDECESSOR.read_text(encoding="utf-8")
    match = re.search(r"(?m)^9\. Contexto propio:.*$", fixture)
    assert match is not None
    step9 = match.group(0)
    new_step9 = step9.replace("fila b1 de diseno", "fila b32 de diseno").replace(
        "'Go relevo 24h 1'", "'Go_Relevo_32'"
    )
    predecessor = tmp_path / "new-format.md"
    predecessor.write_text(
        fixture[: match.start()] + new_step9 + fixture[match.end() :],
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 33, _juicios_sucesor())

    assert rc == 0
    rendered_step9 = re.search(r"(?m)^9\. Contexto propio:.*$", output)
    assert rendered_step9 is not None
    assert "Go_Relevo_33" in rendered_step9.group(0)
    assert "fila b33" in rendered_step9.group(0)
    assert "Go relevo 24h 33" not in rendered_step9.group(0)

    future_step9 = step9.replace("fila b1 de diseno", "fila b2 de diseno").replace(
        "'Go relevo 24h 1'", "'Go_Relevo_2'"
    )
    future_predecessor = tmp_path / "future-reference.md"
    future_predecessor.write_text(
        fixture[: match.start()]
        + future_step9
        + fixture[match.end() :]
        + "\nReferencia futura: Go_Relevo_3.\n",
        encoding="utf-8",
    )
    rc, future_output = render_latido(future_predecessor, roster, 3, _juicios_sucesor())

    assert rc == 0
    assert "Referencia futura: Go_Relevo_4." in future_output


def test_duplicate_used_line_citation_is_rc2(tmp_path: Path) -> None:
    fixture = PREDECESSOR.read_text(encoding="utf-8")
    match = re.search(r"(?m)^9\. Contexto propio:.*$", fixture)
    assert match is not None
    step9 = match.group(0)
    duplicate_step9 = step9.replace("fila b1 de diseno", "fila b32 de diseno").replace(
        "'Go relevo 24h 1'", "'Go_Relevo_32' y 'Go_Relevo_32'"
    )
    predecessor = tmp_path / "duplicate-used-line.md"
    predecessor.write_text(
        fixture[: match.start()] + duplicate_step9 + fixture[match.end() :],
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 33, _juicios_sucesor())

    assert rc == 2
    assert "regla R3 linea del salto" in output


def test_r3_conteo_paso9_semantica_token(tmp_path: Path) -> None:
    text = (
        "xGo relevo 24h 1; Go relevo 24h 1; Go relevo 24h 12; "
        "Go relevo 24h 1x; Go_Relevo_1; Go_Relevo_12; fila b1; fila b12"
    )
    assert (
        render_latido_module._count_r3_index(text, 1, ("Go relevo 24h ", "Go_Relevo_"))
        == 2
    )
    assert render_latido_module._count_r3_index(text, 1, ("Go relevo 24h ",)) == 1
    assert render_latido_module._count_r3_index(text, 1, ("Go_Relevo_",)) == 1
    assert render_latido_module._count_r3_index(text, 1, ("fila b",)) == 1
    assert (
        render_latido_module._count_r3_index(text, 12, ("Go relevo 24h ", "Go_Relevo_"))
        == 2
    )
    assert render_latido_module._count_r3_index(text, 12, ("fila b",)) == 1
    assert (
        render_latido_module._count_r3_index("xGo relevo 24h 1", 1, ("Go relevo 24h ",))
        == 0
    )
    assert (
        render_latido_module._count_r3_index("Go relevo 24h 1x", 1, ("Go relevo 24h ",))
        == 0
    )
    assert (
        render_latido_module._count_r3_index("Go relevo 24h 01", 1, ("Go relevo 24h ",))
        == 1
    )

    predecessor = tmp_path / "r3-token.md"
    source = PREDECESSOR.read_text(encoding="utf-8")
    replacement = (
        "9. Contexto propio: Go relevo 24h 2; Go relevo 24h 21; fila b21; "
        "fila b2 de diseno/GO_RELEVO_24H_REGISTRO.md"
    )
    objective = re.search(r"\(ARRANQUE_[A-Z]+-\d+_\d{8}\.md s\.2: .*?\)", source)
    assert objective is not None
    original_step9 = re.search(r"(?m)^9\. Contexto propio:.*$", source)
    assert original_step9 is not None
    suffix = original_step9.group(0)[
        original_step9.group(0).find(" Procedimiento: ARRANQUE_") :
    ]
    updated = re.sub(
        r"(?m)^9\. Contexto propio:.*$",
        replacement + "\n" + objective.group(0) + "\n" + suffix,
        source,
        count=1,
    )
    predecessor.write_text(updated, encoding="utf-8")
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 3, _juicios_sucesor())

    assert rc == 0
    line9 = re.search(r"(?m)^9\. Contexto propio:.*$", output)
    assert line9 is not None
    assert "Go relevo 24h 3" in line9.group(0)


def test_error_juicio_objetivo_sin_cierre() -> None:
    text = PREDECESSOR.read_text(encoding="utf-8")
    objective = re.search(r"\(ARRANQUE_[A-Z]+-\d+_\d{8}\.md s\.2: .*?\)", text)
    assert objective is not None
    malformed = text.replace(objective.group(0), objective.group(0)[:-1], 1)

    with pytest.raises(
        ValueError, match="no se encontro cierre de JUICIO objetivo_en_curso"
    ):
        render_latido_module._judgement_spans(malformed)


def test_error_roster_values_active_roles_no_dict() -> None:
    _, _, _, errors = render_latido_module._roster_values(
        {"active_roles": [], "cadena_contexto": [{}]}
    )

    assert any("active_roles debe ser dict" in error for error in errors)


def test_error_roster_values_cadena_contexto_no_list() -> None:
    _, _, _, errors = render_latido_module._roster_values(
        {"active_roles": {}, "cadena_contexto": {}}
    )

    assert any("cadena_contexto debe ser list" in error for error in errors)


def test_error_roster_values_objeto_ausente() -> None:
    _, _, _, errors = render_latido_module._roster_values(
        {
            "active_roles": {"orquestador": None, "supervisor": {}},
            "cadena_contexto": [{}],
        }
    )

    assert any(
        "objeto ausente en active_roles.orquestador" in error for error in errors
    )


def test_error_reduce_roster_active_roles_no_dict() -> None:
    reduced, errors = reduce_roster({"active_roles": None, "cadena_contexto": []})

    assert reduced is None
    assert any("active_roles debe ser dict" in error for error in errors)


def test_error_reduce_roster_objeto_ausente() -> None:
    reduced, errors = reduce_roster(
        {"active_roles": {"orquestador": None}, "cadena_contexto": [{}]}
    )

    assert reduced is None
    assert any(
        "objeto ausente en active_roles.orquestador" in error for error in errors
    )


def test_error_reduce_roster_cadena_vacia() -> None:
    reduced, errors = reduce_roster({"active_roles": {}, "cadena_contexto": []})

    assert reduced is None
    assert any(
        "cadena_contexto debe tener al menos un elemento" in error for error in errors
    )


def test_error_reduce_roster_contexto_no_dict() -> None:
    reduced, errors = reduce_roster({"active_roles": {}, "cadena_contexto": ["x"]})

    assert reduced is None
    assert any("objeto ausente en cadena_contexto[0]" in error for error in errors)


def test_error_paso9_ausente_en_validacion(tmp_path: Path, monkeypatch) -> None:
    """Reachability requires stubbing _derive_predecessor with a valid mapping.

    The predecessor keeps every anchor but its step-9 line is renamed, so the
    validation site can only run when derivation is bypassed; without the stub
    the earlier derivation error wins and this branch stays unexecuted.
    """

    source = PREDECESSOR.read_text(encoding="utf-8")
    cascade_start = source.find(render_latido_module._CASCADE_START) + len(
        render_latido_module._CASCADE_START
    )
    cascade_end = source.find(render_latido_module._CASCADE_END, cascade_start)
    derived = render_latido_module._derive_predecessor(
        source, cascade_start, cascade_end
    )
    monkeypatch.setattr(
        render_latido_module, "_derive_predecessor", lambda text, start, end: derived
    )
    predecessor = tmp_path / "without-step9.md"
    predecessor.write_text(
        re.sub(r"(?m)^9\. Contexto propio:", "8. Contexto propio:", source),
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "regla R3: parrafo del paso 9 ausente" in output


def test_error_paso9_ausente_tras_derivacion(tmp_path: Path, monkeypatch) -> None:
    """Reachability requires monkeypatching replacement to remove line 9."""

    original = render_latido_module._replace_identity_tokens

    def remove_step9(*args, **kwargs):
        rendered = original(*args, **kwargs)
        return re.sub(r"(?m)^9\. Contexto propio:.*\r?\n?", "", rendered)

    monkeypatch.setattr(render_latido_module, "_replace_identity_tokens", remove_step9)
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "regla R3: parrafo del paso 9 ausente tras derivacion" in output


def test_error_session_code_no_numerico() -> None:
    """This branch is directly reachable because roster validation requires [A-Z]+-[0-9]+."""

    with pytest.raises(ValueError, match="session_code no numerico: CO-"):
        render_latido_module._next_session_code("CO-")


def test_fixtures_sin_identificadores_reales() -> None:
    texts = [
        path.read_text(encoding="utf-8") for path in (PREDECESSOR, SUCCESSOR, ROSTER)
    ]
    combined = "".join(texts)
    uuids = re.findall(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        combined,
    )

    assert all(uuid.startswith("00000000-0000-4000-8000-") for uuid in uuids)
    assert re.findall(r"[0-9a-fA-F]{32}", combined) == []
    assert len(uuids) >= 60


def _without_tick_block(text: str) -> str:
    """Remove every line carrying one of the versioned tick signatures.

    Before: ``text`` is the real predecessor fixture from this repository.
    During: remove command and explanatory lines that mention the three
    required signatures, leaving all derivation anchors intact.
    After: return a predecessor that exercises the missing-block branch.
    """

    signatures = render_latido_module._TICK_REQUIRED_SIGNATURES
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not any(signature in line for signature in signatures)
    )


def test_predecessor_tick_block_is_required_with_explicit_difference(
    tmp_path: Path,
) -> None:
    """Reject a real-fixture copy when its tick block is absent and unmarked."""

    predecessor = tmp_path / "without-tick.md"
    predecessor.write_text(
        _without_tick_block(PREDECESSOR.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "bloque de tick ausente" in output
    assert "LATIDO_TICK_BLOCK_VERSION" in output


def test_marked_predecessor_gets_tick_block_from_real_template(tmp_path: Path) -> None:
    """Inject the canonical block only for an explicitly marked predecessor."""

    predecessor = tmp_path / "marked-migration.md"
    source = _without_tick_block(PREDECESSOR.read_text(encoding="utf-8"))
    source = source.replace(
        "]\n",
        "] " + render_latido_module._TICK_VERSION_MARKER + "\n",
        1,
    )
    predecessor.write_text(source, encoding="utf-8")
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 0
    for signature in render_latido_module._TICK_REQUIRED_SIGNATURES:
        assert signature in output


def test_template_tick_mutant_fails_marked_migration(
    tmp_path: Path, monkeypatch
) -> None:
    """A copied template without its block cannot satisfy migration."""

    copied_template = tmp_path / "template-copy.md"
    template = (ROOT / "prompts/vuelo_pilares_templates/LATIDO_PLANTILLA.md").read_text(
        encoding="utf-8"
    )
    start = template.index(render_latido_module._TICK_VERSION_MARKER)
    end = template.index(render_latido_module._TICK_BLOCK_END, start)
    copied_template.write_text(
        template[:start] + template[end + len(render_latido_module._TICK_BLOCK_END) :],
        encoding="utf-8",
    )
    monkeypatch.setattr(render_latido_module, "_TICK_TEMPLATE_PATH", copied_template)
    predecessor = tmp_path / "marked-migration.md"
    source = _without_tick_block(PREDECESSOR.read_text(encoding="utf-8"))
    predecessor.write_text(
        source.replace(
            "]\n",
            "] " + render_latido_module._TICK_VERSION_MARKER + "\n",
            1,
        ),
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "plantilla no contiene el bloque de tick versionado completo" in output


def test_reduce_roster_tolera_ancestro_directo() -> None:
    real = _real_roster()
    real["active_roles"]["ancestro_directo"] = {
        "threadId": "mcp:00000000-0000-4000-8000-000000000001",
        "session_code": "CO-99",
    }

    reduced, errors = reduce_roster(real)

    assert errors == []
    assert reduced is not None
    assert set(reduced["active_roles"]) == {"orquestador", "supervisor"}


def test_m01_cascada_derivada_respeta_constante_nominal(tmp_path: Path) -> None:
    """Require R2 to retain at most the named cascade bound."""

    constant = getattr(render_latido_module, "_CASCADE_MAX_ENTRIES", None)
    measurements = []
    for label, predecessor, roster, go_index, judgements in _bounded_render_cases(
        tmp_path
    ):
        rc, output = render_latido(predecessor, roster, go_index, judgements)
        entries = len(re.findall(r"CO-\d+ \(mcp:", _cascade_text(output)))
        measurements.append((label, rc, output, entries))

    for label, rc, output, entries in measurements:
        assert rc == 0, output
        cascade = _cascade_text(output)
        assert cascade.rstrip().endswith(")"), (
            f"m-01[{label}]: cola de cascada sucia: {cascade[-80:]}"
        )
        assert constant is not None and entries == constant, (
            f"m-01[{label}]: entradas={entries} constante={constant}"
        )


def test_m02_citas_go_del_paso9_respetan_constante_nominal(tmp_path: Path) -> None:
    """Require R3 to retain only the named number of salto citations."""

    constant = getattr(render_latido_module, "_MAX_SALTO_CITATIONS", None)
    measurements = []
    for label, predecessor, roster, go_index, judgements in _bounded_render_cases(
        tmp_path
    ):
        rc, output = render_latido(predecessor, roster, go_index, judgements)
        citations = len(
            re.findall(
                r"El salto CO-\d+ -> CO-\d+ usa?o? la linea", _step9_line(output)
            )
        )
        measurements.append((label, rc, output, citations))

    for label, rc, output, citations in measurements:
        assert rc == 0, output
        assert constant is not None and citations <= constant, (
            f"m-02[{label}]: citas={citations} constante={constant}"
        )


def test_m03_postcompactacion_no_conserva_historia_foranea(tmp_path: Path) -> None:
    """Require R2b to retain no postcompaction reference to another CO."""

    measurements = []
    for label, predecessor, roster, go_index, judgements in _bounded_render_cases(
        tmp_path
    ):
        rc, output = render_latido(predecessor, roster, go_index, judgements)
        protocol_codes = re.findall(
            r"PROTOCOLO_POSTCOMPACTACION_(CO-\d+)\.md", _step9_line(output)
        )
        own_code = roster["active_roles"]["orquestador"]["session_code"]
        foreign = [code for code in protocol_codes if code != own_code]
        measurements.append((label, rc, output, protocol_codes, foreign, own_code))

    for label, rc, output, protocol_codes, foreign, own_code in measurements:
        assert rc == 0, output
        assert not foreign and len(protocol_codes) == 1, (
            f"m-03[{label}]: referencias_protocolo={len(protocol_codes)} "
            f"foraneas={len(foreign)} propio={own_code}"
        )


def test_m04_doble_derivacion_no_hace_crecer_cascada_ni_citas(
    tmp_path: Path,
) -> None:
    """Require successive R2/R3 derivations to remain bounded."""

    cascade_constant = getattr(render_latido_module, "_CASCADE_MAX_ENTRIES", None)
    citations_constant = getattr(render_latido_module, "_MAX_SALTO_CITATIONS", None)
    cases = list(_bounded_render_cases(tmp_path))
    measurements = []
    for label, first_predecessor, roster, go_index, judgements in cases:
        rc_first, first_output = render_latido(
            first_predecessor, roster, go_index, judgements
        )
        second_predecessor = tmp_path / f"LATIDO_{label}_derivado.md"
        second_predecessor.write_bytes(first_output.encode("utf-8"))
        if label == "synthetic":
            roster2, juicios2 = _synthetic_second_case()
            second_go_index = 10
        else:
            roster2 = {
                "active_roles": {
                    "orquestador": {
                        "threadId": "mcp:bed97f5c-c25c-401c-ab70-e3e4d33452a2",
                        "session_code": "CO-145",
                    },
                    "supervisor": {
                        "threadId": "mcp:c5b34b85-b820-41f2-968d-0583b0f76097",
                        "session_code": "CO-144",
                    },
                },
                "cadena_contexto": [
                    {
                        "threadId": "mcp:19416fe9-fd41-4d52-ba69-fff75ce7e614",
                        "session_code": "CO-143",
                    }
                ],
            }
            juicios2 = {
                "nota_derivacion": "[segunda derivacion]",
                "objetivo_en_curso": "(ARRANQUE_CO-145_20261120.md s.2: objetivo en curso)",
                "secciones_postcompactacion_nueva": "s.3 y s.4",
            }
            second_go_index = 90
        rc_second, second_output = render_latido(
            second_predecessor, roster2, second_go_index, juicios2
        )
        second_entries = len(re.findall(r"CO-\d+ \(mcp:", _cascade_text(second_output)))
        second_citations = len(
            re.findall(
                r"El salto CO-\d+ -> CO-\d+ usa?o? la linea",
                _step9_line(second_output),
            )
        )
        measurements.append(
            (
                label,
                rc_first,
                first_output,
                rc_second,
                second_output,
                second_entries,
                second_citations,
            )
        )

    for (
        label,
        rc_first,
        first_output,
        rc_second,
        second_output,
        second_entries,
        second_citations,
    ) in measurements:
        assert rc_first == 0, first_output
        assert rc_second == 0, second_output
        step9_second = _step9_line(second_output)
        assert "  (historico de saltos" not in step9_second, (
            f"m-04[{label}]: doble espacio en segunda derivacion: {step9_second}"
        )
        assert (
            cascade_constant is not None
            and citations_constant is not None
            and second_entries <= cascade_constant
            and second_citations <= citations_constant
        ), (
            f"m-04[{label}]: entradas={second_entries} "
            f"constante_cascada={cascade_constant}; citas={second_citations} "
            f"constante_citas={citations_constant}"
        )


def test_m05_hay_una_remision_conjunta_a_fuentes_vivas(tmp_path: Path) -> None:
    """Require one step-9 sentence naming both live source families."""

    measurements = []
    for label, predecessor, roster, go_index, judgements in _bounded_render_cases(
        tmp_path
    ):
        rc, output = render_latido(predecessor, roster, go_index, judgements)
        step9 = _step9_line(output)
        joint_sentences = [
            sentence
            for sentence in re.split(r"(?<=\.)\s+", step9)
            if "GO_RELEVO_24H_REGISTRO.md" in sentence and "cadena_contexto" in sentence
        ]
        remissions = len(joint_sentences)
        measurements.append(
            (label, rc, output, remissions, step9.count("cadena_contexto"))
        )

    for label, rc, output, remissions, context_count in measurements:
        assert rc == 0, output
        assert remissions == 1 and context_count == 1, (
            f"m-05[{label}]: remisiones={remissions} cadena_contexto={context_count}"
        )


def test_m01_m02_launch_thread_ids_are_accepted_and_not_truncated(
    tmp_path: Path,
) -> None:
    """Before: use a roster with production-shaped launch thread identifiers.

    During: render the existing valid predecessor with the three launch ids.

    After: rendering succeeds and every new identity remains complete in output.
    """
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    ids = {
        "orquestador": "mcp:launch:" + "a" * 64,
        "supervisor": "mcp:launch:" + "b" * 64,
        "contexto": "mcp:launch:" + "b" * 64,
    }
    roster["active_roles"]["orquestador"]["threadId"] = ids["orquestador"]
    roster["active_roles"]["supervisor"]["threadId"] = ids["supervisor"]
    roster["cadena_contexto"][0]["threadId"] = ids["contexto"]
    predecessor = tmp_path / PREDECESSOR.name
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8")
        .replace("mcp:00000000-0000-4000-8000-000000000002", ids["orquestador"])
        .replace("mcp:00000000-0000-4000-8000-000000000032", ids["supervisor"])
        .replace("mcp:00000000-0000-4000-8000-000000000017", ids["orquestador"]),
        encoding="utf-8",
    )

    judgements = {
        key: value.replace(
            "mcp:00000000-0000-4000-8000-000000000017", ids["orquestador"]
        )
        for key, value in _juicios_sucesor().items()
    }
    rc, output = render_latido(predecessor, roster, 2, judgements)

    assert rc == 0, output
    assert "no tiene la forma esperada" not in output
    assert all(thread_id in output for thread_id in ids.values())
    assert 'mcp:launch,"' not in output


@pytest.mark.parametrize(
    "value",
    [
        "mcp:launch:" + "a" * 63,
        "mcp:launch:" + "A" * 64,
        "mcp:launch:" + "a" * 63 + "g",
        "launch:" + "a" * 64,
    ],
)
def test_m04_launch_thread_id_invalid_forms_are_rejected(value: str) -> None:
    """Before: replace one roster thread identifier with a malformed value.

    During: validate the roster through the renderer.

    After: the renderer returns rc 2 with the named shape error.
    """
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    roster["active_roles"]["orquestador"]["threadId"] = value

    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "no tiene la forma esperada" in output
