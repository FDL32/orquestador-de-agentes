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
