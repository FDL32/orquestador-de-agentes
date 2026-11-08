import hashlib
import json
import re
from pathlib import Path

from scripts.flight.render_latido import predecessor_sha12, render_latido


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
        .replace(
            "mcp:0355d3c5-08e9-427a-ba65-e6e3ab43b7ce",
            "mcp:11111111-1111-4111-8111-111111111111",
        )
        .replace(
            "mcp:d0cbb70f-c8f3-444d-a15d-ce28235cc26c",
            "mcp:33333333-3333-4333-8333-333333333333",
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
    assert "Go relevo 24h 9" in output
