"""El filtro de salida de lente CABLEADO a run_pipeline (WOT-2026-039c).

027o entrego el mecanismo (`filter_lens_output`) y NADIE lo consumia: un guard
que nadie invoca es una norma, no una barrera. Estos tests fijan el cableado
productivo, que es lo unico que convierte el mecanismo en barrera:

  - el flag `lens_output_filter` gobierna: AUSENTE = OFF = conducta heredada
    (aditividad real: los pipelines que no lo declaran no cambian);
  - con el flag ON, una salida de challenger que no cumple el schema
    lens-answer/v1 se marca `discarded_reason`, NO alimenta el prior de la
    ronda siguiente, y se registra en el scorecard como no-aportacion;
  - la RONDA 0 (premise_check, invariante del dispatcher) queda EXENTA: su
    respuesta legitima no trae bloque cite y quedaria siempre descartada.

Hermetico: transport inyectado, sin red ni backends.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT / "scripts"))

import ensemble_dispatch as ed  # noqa: E402


_CITED_FILE = "scripts/real_module.py"


def _config(*, filter_on: bool) -> dict:
    pipe = {
        "proposer": "p",
        "challenger": "c",
        "rubric": "r.md",
        "max_rounds": 1,
    }
    if filter_on:
        pipe["lens_output_filter"] = True
    return {
        "backends": {
            "fake": {"type": "api", "base_url": "http://x", "api_key_env": "NONE"}
        },
        "ensemble_profiles": {
            "p": {"backend": "fake", "channel": "api", "data_sensitivity": "public"},
            "c": {"backend": "fake", "channel": "api", "data_sensitivity": "public"},
        },
        "ensemble_pipelines": {"pipe": pipe},
        "ensemble_private_roots": [],
    }


def _workspace(tmp_path: Path) -> Path:
    """Destino-rol con el fichero que las citas legitimas apuntan."""
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "scripts" / "real_module.py").write_text(
        "import os\nDEFAULT_ENCODING = 'utf-8'\ndef run():\n    return 42\n",
        encoding="utf-8",
    )
    return tmp_path


def _run(tmp_path: Path, replies: list[str], *, filter_on: bool) -> list[dict]:
    root = _workspace(tmp_path)
    seq = iter(replies)

    def transport(profile, backend_cfg, messages, timeout):
        return next(seq)

    return ed.run_pipeline(
        "pipe",
        config=_config(filter_on=filter_on),
        project_root=root,
        ticket="WOT-2026-039c",
        task_type="code-review",
        payload="material",
        sensitivity="public",
        transport=transport,
        max_rounds=1,
    )


def _scorecard_rows(root: Path) -> list[dict]:
    path = root / ed.SCORECARD_REL
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_flag_absent_keeps_legacy_behaviour(tmp_path: Path):
    """ADITIVIDAD: sin la clave, ninguna salida se descarta.

    Es la aditividad REAL, no nominal: los pipelines existentes usan replies
    en prosa que el filtro nuevo descartaria. Si el default fuera ON, este
    test (y los del dispatcher) caerian -- que es exactamente lo que el
    CF-audit exigio evitar.
    """
    transcript = _run(tmp_path, ["prosa", "prosa", "prosa", "prosa"], filter_on=False)

    assert transcript
    assert not any("discarded_reason" in t for t in transcript)


def test_challenger_output_without_cite_is_discarded(tmp_path: Path):
    """Con el flag ON, la salida sin schema se marca y no alimenta el prior."""
    transcript = _run(
        tmp_path,
        [
            "PREMISES-OK",  # r0 proposer
            "PREMISES-OK",  # r0 challenger (EXENTO del filtro)
            "propuesta del proposer",  # r1 proposer
            "Hay un bug, creeme.",  # r1 challenger: prosa sin cite
        ],
        filter_on=True,
    )

    challenger_r1 = [
        t for t in transcript if t["ronda"] == 1 and t["rol"] == "challenger"
    ]
    assert challenger_r1, transcript
    entry = challenger_r1[0]
    assert "discarded_reason" in entry, entry
    assert "no_contribution" in entry["discarded_reason"]
    # La salida se CONSERVA integra (auditabilidad): no se omite ni se vacia.
    assert entry["reply"] == "Hay un bug, creeme."


def test_round_zero_challenger_is_exempt(tmp_path: Path):
    """La ronda 0 es premise_check: su respuesta legitima no trae cite.

    Sin la exencion, el filtro vaciaria SIEMPRE el premise_check, que es
    invariante del dispatcher y la unica defensa contra premisas falsas.
    """
    transcript = _run(
        tmp_path,
        ["PREMISES-OK", "PREMISES-OK", "propuesta", "Hay un bug, creeme."],
        filter_on=True,
    )

    round_zero = [t for t in transcript if t["ronda"] == 0]
    assert round_zero
    assert not any("discarded_reason" in t for t in round_zero)


def test_valid_cite_objection_is_not_discarded(tmp_path: Path):
    """Anti-falso-positivo: una objecion con cita verificada SI pasa.

    Un filtro que descarta aportacion legitima ensena al operador a apagarlo.
    """
    good = (
        "Incorrecto: la premisa es falsa, devuelve un literal.\n\n"
        "```cite\n"
        f"path: {_CITED_FILE}\n"
        "line: 4\n"
        "quote: return 42\n"
        "```\n"
    )
    transcript = _run(
        tmp_path, ["PREMISES-OK", "PREMISES-OK", "propuesta", good], filter_on=True
    )

    challenger_r1 = [
        t for t in transcript if t["ronda"] == 1 and t["rol"] == "challenger"
    ]
    assert challenger_r1
    assert "discarded_reason" not in challenger_r1[0], challenger_r1[0]


def test_discarded_output_recorded_as_no_aportacion(tmp_path: Path):
    """El scorecard registra la salida descartada SIN vaciar la evidencia.

    Vaciar `reply` para forzar el outcome mentiria sobre lo que respondio el
    backend; por eso el registro usa `outcome_override` y conserva el texto.
    """
    root = _workspace(tmp_path)
    seq = iter(["PREMISES-OK", "PREMISES-OK", "propuesta", "Hay un bug, creeme."])

    def transport(profile, backend_cfg, messages, timeout):
        return next(seq)

    ed.run_pipeline(
        "pipe",
        config=_config(filter_on=True),
        project_root=root,
        ticket="WOT-2026-039c",
        task_type="code-review",
        payload="material",
        sensitivity="public",
        transport=transport,
        max_rounds=1,
    )

    rows = _scorecard_rows(root)
    discarded = [
        r
        for r in rows
        if r.get("rol") == "challenger"
        and r.get("ronda") == 1
        and r.get("outcome") == "no-aportacion"
    ]
    assert discarded, rows
    assert discarded[0]["failure_mode"]
    assert "creeme" in discarded[0]["evidencia"]


def test_041c_cite_to_a_real_motor_file_survives_the_production_route(tmp_path: Path):
    """WOT-2026-041c DoD (a) EN LA RUTA DE PRODUCCION, no en un unit test.

    `run_pipeline` pasa `project_root` (el DESTINO) como root del filtro, pero
    las lentes auditan artefactos del MOTOR. Antes del fix, esta cita -- a un
    fichero REAL del motor, con quote REAL leido del disco -- se descartaba
    como `fabricated_citation`, perdiendo justo la contribucion que cita
    codigo real.

    El quote se DERIVA del fichero vivo, nunca de un numero de linea recordado:
    una linea hardcodeada caduca en cuanto alguien edita el modulo, y el test
    se pondria rojo por staleness del fixture en vez de por el defecto (paso
    de verdad al medir este ticket).
    """
    cited_rel = "scripts/filter_lens_output.py"
    lines = (_MOTOR_ROOT / cited_rel).read_text(encoding="utf-8").splitlines()
    lineno = next(
        i for i, ln in enumerate(lines, 1) if ln.startswith("def classify_verdict")
    )

    good = (
        "Incorrecto: el validador resuelve las citas contra un unico root.\n\n"
        "```cite\n"
        f"path: {cited_rel}\n"
        f"line: {lineno}\n"
        f"quote: {lines[lineno - 1].strip()}\n"
        "```\n"
    )
    transcript = _run(
        tmp_path, ["PREMISES-OK", "PREMISES-OK", "propuesta", good], filter_on=True
    )

    challenger_r1 = [
        t for t in transcript if t["ronda"] == 1 and t["rol"] == "challenger"
    ]
    assert challenger_r1, transcript
    assert "discarded_reason" not in challenger_r1[0], challenger_r1[0]


def test_041c_fabricated_cite_still_discarded_in_the_production_route(tmp_path: Path):
    """WOT-2026-041c DoD (c) en la ruta real: el multi-root NO abre la puerta.

    Control negativo del test anterior: si el fix hubiera relajado la
    validacion (aceptar cualquier root, o rutas sin resolver), esta cita
    inventada tambien pasaria -- y el guard seria fail-open, PEOR que el
    defecto que arregla.
    """
    bad = (
        "Incorrecto: hay un bug grave aqui.\n\n"
        "```cite\n"
        "path: scripts/no_existe_ni_en_motor_ni_en_destino.py\n"
        "line: 3\n"
        "quote: def totalmente_inventado()\n"
        "```\n"
    )
    transcript = _run(
        tmp_path, ["PREMISES-OK", "PREMISES-OK", "propuesta", bad], filter_on=True
    )

    challenger_r1 = [
        t for t in transcript if t["ronda"] == 1 and t["rol"] == "challenger"
    ]
    assert challenger_r1, transcript
    entry = challenger_r1[0]
    assert "discarded_reason" in entry, entry
    assert "fabricated_citation" in entry["discarded_reason"], entry
