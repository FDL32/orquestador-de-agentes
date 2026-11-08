import json
import re
from pathlib import Path

from scripts.flight.render_latido import render_latido


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
