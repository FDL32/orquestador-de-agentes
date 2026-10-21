"""Tests para check_process_decision_search.py (WOT-2026-104b).

Cablea la norma AGENTS.md "Decision de proceso sin instruccion exacta =>
BUSCA protocolo documentado antes de suponer uno" como barrera de FORMA.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parents[2]
GUARD = MOTOR_ROOT / "scripts" / "check_process_decision_search.py"

sys.path.insert(0, str(MOTOR_ROOT / "scripts"))
import check_process_decision_search as guard  # noqa: E402


_SIN_BUSQUEDA = "DECISION DE PROCESO: adoptamos X sin revisar nada antes.\n"


def _run(tmp_path: Path, text: str) -> subprocess.CompletedProcess:
    artefacto = tmp_path / "artefacto.md"
    artefacto.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(GUARD), str(artefacto)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_sin_marcador_no_aplica(tmp_path):
    r = _run(tmp_path, "Texto normal sin ningun marcador de proceso.\n")
    assert r.returncode == 0
    assert "no aplica" in r.stdout


def test_marcador_sin_busqueda_previa_bloquea(tmp_path):
    r = _run(tmp_path, _SIN_BUSQUEDA)
    assert r.returncode == 1
    assert "falta la seccion 'BUSQUEDA-PREVIA:'" in r.stderr


def test_marcador_con_no_encontre_protocolo_pasa(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: adoptamos X.\n"
        "BUSQUEDA-PREVIA: NO ENCONTRE PROTOCOLO tras grep en AGENTS.md.\n",
    )
    assert r.returncode == 0


def test_marcador_con_protocolo_encontrado_pasa(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: adoptamos X.\n"
        "BUSQUEDA-PREVIA: PROTOCOLO ENCONTRADO: prompts/ensemble_loop.md\n",
    )
    assert r.returncode == 0


def test_protocolo_encontrado_sin_ruta_bloquea(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: adoptamos X.\nBUSQUEDA-PREVIA: PROTOCOLO ENCONTRADO:\n",
    )
    assert r.returncode == 1
    assert "sin ruta" in r.stderr


def test_excepcion_trivial_con_texto_pasa(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: corrijo un typo en un comentario.\n"
        "BUSQUEDA-PREVIA: EXCEPCION: trivial -- typo sin ambiguedad de proceso.\n",
    )
    assert r.returncode == 0


def test_excepcion_trivial_sin_texto_bloquea(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: adoptamos X.\nBUSQUEDA-PREVIA: EXCEPCION: trivial\n",
    )
    assert r.returncode == 1
    assert "sin texto de justificacion" in r.stderr


def test_busqueda_previa_sin_forma_valida_bloquea(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: adoptamos X.\n"
        "BUSQUEDA-PREVIA: lo pense un rato y decidi que esta bien.\n",
    )
    assert r.returncode == 1
    assert "ninguna de las 3 formas validas" in r.stderr


def test_marcador_dentro_de_fence_no_dispara(tmp_path):
    r = _run(
        tmp_path,
        "Documentacion de ejemplo:\n"
        "```\n"
        "DECISION DE PROCESO: <texto>\n"
        "```\n"
        "Resto del documento sin BUSQUEDA-PREVIA.\n",
    )
    assert r.returncode == 0
    assert "no aplica" in r.stdout


def test_artefacto_inexistente_devuelve_2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(GUARD), str(tmp_path / "no_existe.md")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2


def test_mutacion_quitar_chequeo_busqueda_previa_invierte_el_veredicto(monkeypatch):
    """MUTACION (WOT-2026-104b, correccion de ambos lentes del bucle DBL-2):
    sin mutar, un documento con el marcador y sin BUSQUEDA-PREVIA: BLOQUEA
    (check_artifact devuelve un defecto, no None). Si se revierte el
    chequeo de busqueda_previa_defect() a 'siempre None' (equivalente a
    quitar la exigencia), el MISMO documento deja de bloquear. El test
    CLI bloqueante de arriba (test_marcador_sin_busqueda_previa_bloquea)
    fallaria contra esa version mutada -- esta prueba demuestra que la
    mutacion invierte el veredicto, confirmando que el test real depende
    del chequeo real y no es un falso verde."""
    veredicto_real = guard.check_artifact(_SIN_BUSQUEDA)
    assert veredicto_real is not None  # sin mutar: bloquea

    monkeypatch.setattr(guard, "busqueda_previa_defect", lambda text: None)
    veredicto_mutado = guard.check_artifact(_SIN_BUSQUEDA)
    assert veredicto_mutado is None  # mutado: deja de bloquear (veredicto invertido)
