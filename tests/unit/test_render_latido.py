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


def test_golden_render_is_byte_exact() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    rc, output = render_latido(PREDECESSOR, roster, 2, _juicios_sucesor())

    assert rc == 0
    assert output == SUCCESSOR.read_text(encoding="utf-8")
    assert output.encode("utf-8") == SUCCESSOR.read_bytes()


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
    assert predecessor_sha12(PREDECESSOR) == "79b55776207c"


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
