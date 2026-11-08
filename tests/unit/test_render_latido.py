import hashlib
import json
import re
from pathlib import Path

import pytest
import scripts.flight.render_latido as render_latido_module
from scripts.flight.render_latido import (
    _main,
    predecessor_sha12,
    reduce_roster,
    render_latido,
)


ROOT = Path(__file__).parents[2]
PREDECESSOR = ROOT / "tests/fixtures/render_latido/latido_predecesor.md"
SUCCESSOR = ROOT / "tests/fixtures/render_latido/latido_sucesor.md"
ROSTER = ROOT / "tests/fixtures/render_latido/flight_roster.json"


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
    for literal in ("fila b1", "Go relevo 24h 1", "Go relevo 24h 2"):
        assert step9.count(literal) == 1
    mutated_step9 = (
        step9.replace("fila b1", "fila b4")
        .replace("Go relevo 24h 1", "Go relevo 24h 4")
        .replace("Go relevo 24h 2", "Go relevo 24h 5")
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
    assert "Go relevo 24h 8" in rendered_step9.group(0)
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
        "mcp:99999999-9999-4999-8999-999999999999"
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
    assert predecessor_sha12(PREDECESSOR) == "fadc9966e810"


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
            "mcp:0355d3c5-08e9-427a-ba65-e6e3ab43b7ce",
            "mcp:11111111-1111-4111-8111-111111111111",
        )
        .replace(
            "mcp:d0cbb70f-c8f3-444d-a15d-ce28235cc26c",
            "mcp:33333333-3333-4333-8333-333333333333",
        )
        .replace(
            "mcp:a3854955-09b6-4647-a647-d96a935442dc",
            "mcp:44444444-4444-4444-8444-444444444444",
        )
    )
    predecessor = tmp_path / "synthetic.md"
    predecessor.write_text(synthetic, encoding="utf-8")
    roster = {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:11111111-1111-4111-8111-111111111112",
                "session_code": "CO-57",
            },
            "supervisor": {
                "threadId": "mcp:22222222-2222-4222-8222-222222222222",
                "session_code": "CO-56",
            },
        },
        "cadena_contexto": [
            {
                "threadId": "mcp:33333333-3333-4333-8333-333333333333",
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
        "Tu supervisora es CO-56 (mcp:22222222-2222-4222-8222-222222222222," in output
    )
    assert "cascada directa CO-55" in output
    assert "o 'CO-55'" in output
    assert "cascada directa CO-54" not in output
    assert "o 'CO-54'" not in output
    assert "cascada directa CO-55 (mcp:33333333-3333-4333-8333-333333333333)" in output
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
    predecessor = tmp_path / "uppercase-id.md"
    predecessor.write_text(
        PREDECESSOR.read_text(encoding="utf-8")
        + "\nmcp:ABCDEF12-1234-4123-8123-123456789012\n",
        encoding="utf-8",
    )
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    rc, output = render_latido(predecessor, roster, 2, _juicios_sucesor())

    assert rc == 2
    assert "id mcp ajeno al roster: mcp:ABCDEF12-1234-4123-8123-123456789012" in output


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
    args = [
        "--predecessor",
        str(PREDECESSOR),
        "--roster",
        str(ROSTER),
        "--go-index",
        "2",
        "--out",
        str(out),
    ]
    for name, path in paths:
        args.extend(["--juicio", f"{name}=@{path}"])

    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    expected_rc, expected_output = render_latido(PREDECESSOR, roster, 2, juicios)
    actual_rc = _main(args)

    assert actual_rc == expected_rc == 0
    assert out.read_text(encoding="utf-8") == expected_output


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
                "threadId": "mcp:5c3353f8-5d71-4efc-bfa5-38164d851130",
                "session_code": "CO-56",
                "since": "2026-11-08T08:44:56+01:00",
                "set_by": "CO-54",
                "predecessor_threadId": "mcp:0355d3c5-08e9-427a-ba65-e6e3ab43b7ce",
                "version": 147,
                "status": "active",
                "approved_by": "CO-54",
                "nota": "known",
                "estado": "ACTIVO",
            },
            "supervisor": {
                "threadId": "mcp:0355d3c5-08e9-427a-ba65-e6e3ab43b7ce",
                "session_code": "CO-55",
                "since": "2026-11-08T08:44:56+01:00",
                "set_by": "CO-54",
                "predecessor_threadId": "mcp:d0cbb70f-c8f3-444d-a15d-ce28235cc26c",
                "version": 48,
                "status": "active",
            },
        },
        "cadena_contexto": [
            {
                "threadId": "mcp:d0cbb70f-c8f3-444d-a15d-ce28235cc26c",
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
