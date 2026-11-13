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

from scripts.flight.render_latido import render_latido


ROOT = Path(__file__).parents[2]
PREDECESSOR = ROOT / "tests/fixtures/render_latido/latido_predecesor.md"
SUCCESSOR = ROOT / "tests/fixtures/render_latido/latido_sucesor.md"
ROSTER = ROOT / "tests/fixtures/render_latido/flight_roster.json"


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
