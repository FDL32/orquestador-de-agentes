"""Cover the heartbeat fixture rules through the deterministic renderer.

Before: the predecessor fixture, reduced roster, and successor judgements must
be available in the repository.
During: render the predecessor exactly as the golden test does and inspect the
two rule lines in the rendered output.
After: the four textual clauses are asserted with a successful render code.
"""

import json
import re
from pathlib import Path

import pytest
import scripts.flight.render_latido as render_latido_module
from scripts.flight.render_latido import render_latido

from tests.unit.test_render_latido import (
    _synthetic_derivation_judgements,
    _synthetic_predecessor,
    _synthetic_roster,
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


def _rendered_rule_lines() -> tuple[str, str]:
    """Render the fixture pair and return the step-3 and urgent lines.

    Before: the successor contains the three judgement values required by the
    renderer and the reduced roster is valid JSON.
    During: extract those judgements from the successor and render the
    predecessor with the same arguments as the byte-exact golden test.
    After: return exactly one rendered line for each requested rule, or fail
    with the renderer's non-zero result and diagnostic output.
    """

    successor = SUCCESSOR.read_text(encoding="utf-8")
    header = successor.splitlines()[1]
    note_start = header.index("[")
    note_end = header.rfind("]", note_start) + 1
    objective = re.search(r"\(ARRANQUE_CO-\d+_20261108\.md s\.2: .*?\)", successor)
    assert objective is not None
    postcompactacion = re.search(
        r" y PROTOCOLO_POSTCOMPACTACION_CO-55\.md (s\.3 y s\.4)(?= \(procedimiento de ticket)",
        successor,
    )
    assert postcompactacion is not None
    juicios = {
        "nota_derivacion": header[note_start:note_end],
        "objetivo_en_curso": objective.group(0),
        "secciones_postcompactacion_nueva": postcompactacion.group(1),
    }
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    rc, output = render_latido(PREDECESSOR, roster, 2, juicios)
    assert rc == 0, output
    step3 = [
        line
        for line in output.splitlines()
        if line.startswith("3. IMPLANTADORES VIVOS")
    ]
    urgent = [line for line in output.splitlines() if line.startswith("URGENTE")]
    assert len(step3) == 1
    assert len(urgent) == 1
    return step3[0], urgent[0]


def test_paso3_cubre_tr_im_hijos_registrados() -> None:
    """Require threadId-based coverage for TR, IM, and registered children.

    Before: the rendered step-3 rule must contain its operational clauses.
    During: inspect only the line that starts with ``3. IMPLANTADORES VIVOS``.
    After: threadId coexists with, and is not replaced by, titleContains IM-.
    """

    step3, _ = _rendered_rule_lines()

    assert "threadId" in step3
    assert (
        "Resuelve cada sesion VIVA por su threadId registrado en session_registry.json"
        in step3
    )
    assert "incluyendo TR-, IM- e hijos con threadId registrado" in step3
    assert "titleContains IM-" in step3
    assert step3.index("threadId") < step3.index("titleContains IM-")


def test_urgente_cubre_tr_im_hijos_con_hilo_failed() -> None:
    """Require the urgent rule to name all registered session classes.

    Before: the rendered urgent rule must retain its existing alert keys.
    During: inspect only the line that starts with ``URGENTE``.
    After: TR, IM, children, and hilo-failed are all covered together.
    """

    _, urgent = _rendered_rule_lines()

    assert "de la coordinadora TR-, de un implantador IM- o de un hijo" in urgent
    assert "(clave hilo-failed-<codigo>)" in urgent
    assert "(clave pregunta-<codigo>)" in urgent
    assert "(clave relevo-sin-go)" in urgent
    assert "clave im-parado-<codigo>" in urgent


def test_historicos_no_disparan() -> None:
    """Require the named terminal statuses and non-terminal triggers.

    Before: the rendered urgent rule must state the registry status policy.
    During: inspect the status and failed-thread clauses inside that line.
    After: all ten terminal names are non-disparaging, four other statuses are
    explicit triggers, and the exact set on each side fixes polarity.
    """

    _, urgent = _rendered_rule_lines()
    terminales = (
        "ASENTADA",
        "SETTLED",
        "CASCADA",
        "RELEVADA",
        "COMPLETADA",
        "SUPERSEDED",
        "CERRADA",
        "HISTORICO",
        "DESACTIVADA",
        "DESCARTADA",
    )
    disparadores = ("ACTIVA", "FALLIDA", "SUPERVISORA", "ENTREGADO")

    no_produce = "NO produce hilo-failed-<codigo>"
    si_disparan = "SI disparan"

    assert no_produce in urgent
    assert si_disparan in urgent
    lado_terminal = urgent.split("status ", 1)[1].split(no_produce, 1)[0]
    lado_disparador = urgent.split("los status ", 1)[1].split(si_disparan, 1)[0]
    terminales_lado = {
        token.strip(" ,;.")
        for token in lado_terminal.replace(" o ", ", ").split(",")
        if token.strip(" ,;.")
    }
    disparadores_lado = {
        token.strip(" ,;.")
        for token in lado_disparador.replace(" y ", ", ").split(",")
        if token.strip(" ,;.")
    }
    assert terminales_lado == set(terminales)
    assert disparadores_lado == set(disparadores)
    assert "status del registry es texto libre" in urgent


def test_limite_de_hijos_sin_threadid_declarado() -> None:
    """Require the explicit boundary for unregistered child threads.

    Before: the rendered step-3 rule must describe the child monitoring limit.
    During: inspect only the line that starts with ``3. IMPLANTADORES VIVOS``.
    After: a child lacking a registered threadId is explicitly not monitored.
    """

    step3, _ = _rendered_rule_lines()

    assert (
        "Un hijo sin threadId registrado en session_registry.json no se vigila" in step3
    )


def _real_rule_render(tmp_path: Path) -> str:
    """Render the real CO-143 heartbeat after the three required adaptations.

    Before: the registered real heartbeat must exist and contain the R2, R3,
    R6, and R2b-fin source anchors.
    During: copy it to ``tmp_path``, add only the renderer's required identity,
    judgement-header, and objective anchors, and derive CO-144.
    After: return the successful rendered heartbeat for rule assertions.
    """

    if not REAL_CO_143.is_file():
        pytest.skip(f"fixture real ausente: {REAL_CO_143}")
    lines = REAL_CO_143.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[1] = lines[1].rstrip("\r\n") + " [nota_derivacion de prueba]\n"
    lines.insert(2, "(ARRANQUE_CO-143_20261120.md s.2: objetivo de prueba)\n")
    for index, line in enumerate(lines):
        if line.startswith("CO-143, sesion coordinadora ACTIVA"):
            adapted = "Eres " + line
            lines[index] = re.sub(
                r"la cascada es (CO-\d+ \(mcp:[0-9A-Za-z-]+),",
                r"la cascada es \1),",
                adapted,
                count=1,
            )
            prefix, separator, suffix = lines[index].rpartition("Go_Relevo_88")
            if separator:
                lines[index] = prefix + "Go_Relevo_N" + suffix
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
    roster = {
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
    juicios = {
        "nota_derivacion": "[nota_derivacion de prueba]",
        "objetivo_en_curso": "(ARRANQUE_CO-144_20261120.md s.2: objetivo en curso)",
        "secciones_postcompactacion_nueva": "s.3 y s.4",
    }
    rc, output = render_latido(predecessor, roster, 89, juicios)
    assert rc == 0, output
    return output


def _synthetic_rule_render(tmp_path: Path) -> str:
    """Render the mandatory synthetic high-cardinality predecessor first."""

    predecessor = _synthetic_predecessor(tmp_path)
    rc, output = render_latido(
        predecessor,
        _synthetic_roster(),
        2,
        _synthetic_derivation_judgements(),
    )
    assert rc == 0, output
    return output


def test_r2_r2b_fin_r3_r6_mantienen_anclas_con_limites_nuevos(
    tmp_path: Path,
) -> None:
    """Cover R2, R2b-fin, R3, and R6 while enforcing the new bounds."""

    cascade_constant = getattr(render_latido_module, "_CASCADE_MAX_ENTRIES", None)
    citations_constant = getattr(render_latido_module, "_MAX_SALTO_CITATIONS", None)
    outputs = [("synthetic", _synthetic_rule_render(tmp_path))]
    if REAL_CO_143.is_file():
        outputs.append(("real", _real_rule_render(tmp_path)))
    for label, output in outputs:
        cascade = output.split(render_latido_module._CASCADE_START, 1)[1].split(
            render_latido_module._CASCADE_END, 1
        )[0]
        step9 = re.search(r"(?m)^9\. Contexto propio:.*$", output)
        assert step9 is not None
        entries = len(re.findall(r"CO-\d+ \(mcp:", cascade))
        citations = len(
            re.findall(r"El salto CO-\d+ -> CO-\d+ usa?o? la linea", step9.group(0))
        )

        assert output.count(render_latido_module._CASCADE_START) == 1
        assert output.count(render_latido_module._CASCADE_END) == 1
        assert cascade_constant is not None and entries == cascade_constant, (
            f"R2[{label}]: entradas={entries} constante={cascade_constant}"
        )
        assert citations_constant is not None and citations <= citations_constant, (
            f"R3[{label}]: citas={citations} constante={citations_constant}"
        )
        live_index = 2 if label == "synthetic" else 89
        live_own = "CO-56" if label == "synthetic" else "CO-144"
        assert step9.group(0).count(f"fila b{live_index}") == 1
        assert output.count(f"ARRANQUE_{live_own} s.1") == 1
