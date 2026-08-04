"""Tests del aviso pre-commit de frescura de suite (WOT-2026-026t).

Lo que pinean: el aviso aparece SOLO cuando es accionable (hay una suite verde
COMPLETA en el HEAD actual que este commit invalidaria) y NUNCA bloquea.

El caso fundacional (`test_avisa_cuando_hay_suite_verde_en_head`) reproduce la
secuencia medida el 2026-08-04: tres corridas de suite en una sesion porque cada
commit invalidaba la anterior, ~15 minutos tirados.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_suite_freshness.py"
)
_spec = importlib.util.spec_from_file_location("check_suite_freshness", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

_HEAD = "d9a4f96dbce9459b0a93aaaaaaaaaaaaaaaaaaaa"


def _write_last_run(tmp_path: Path, **overrides) -> Path:
    """last-run.json con una corrida COMPLETA y VERDE, salvo overrides."""
    data = {
        "status": "finished",
        "exit_code": 0,
        "level": "all",
        "args_mode": "default_discovery",
        "tested_commit_sha": _HEAD,
        "passed": 5438,
    }
    data.update(overrides)
    path = tmp_path / "last-run.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Apunta el guard al fixture y fija el HEAD, sin tocar el repo real."""

    def _apply(**overrides):
        monkeypatch.setattr(guard, "LAST_RUN", _write_last_run(tmp_path, **overrides))
        monkeypatch.setattr(guard, "_head", lambda: _HEAD)

    return _apply


class TestAvisaCuandoProcede:
    """El unico caso en que el aviso sirve para ahorrar trabajo."""

    def test_avisa_cuando_hay_suite_verde_en_head(self, wired, capsys):
        """Caso fundacional: suite verde en HEAD -> este commit la invalida.

        MUTACION ALCANZABLE: quitar la comparacion `tested == head` -> el guard
        calla y se repite la secuencia de 3 corridas que costo ~15 min.
        """
        wired()
        assert guard.main() == 0
        out = capsys.readouterr().out
        assert "AVISO" in out
        assert "5438 passed" in out, "el aviso cita la corrida que se pierde"
        assert "No bloquea" in out, "debe dejar claro que commitear es legitimo"


class TestNoAvisaCuandoNoProcede:
    """Ruido cero: un aviso que salta siempre se ignora siempre."""

    def test_sin_last_run_calla(self, monkeypatch, tmp_path):
        monkeypatch.setattr(guard, "LAST_RUN", tmp_path / "no-existe.json")
        assert guard.main() == 0

    def test_json_corrupto_calla(self, monkeypatch, tmp_path):
        p = tmp_path / "last-run.json"
        p.write_text("{roto", encoding="utf-8")
        monkeypatch.setattr(guard, "LAST_RUN", p)
        assert guard.main() == 0

    @pytest.mark.parametrize(
        ("campo", "valor"),
        [
            ("status", "started"),  # corrida en curso: aun no es un activo
            ("exit_code", 1),  # roja: no hay nada que perder
            ("level", "unit"),  # parcial: no es la canonica
            ("args_mode", "explicit_args"),  # filtrada (WOT-2026-044o)
        ],
    )
    def test_corrida_no_aprovechable_calla(self, wired, capsys, campo, valor):
        """Solo una corrida COMPLETA y VERDE es un activo que merezca aviso."""
        wired(**{campo: valor})
        assert guard.main() == 0
        assert capsys.readouterr().out == ""

    def test_suite_ya_desfasada_calla(self, wired, capsys):
        """Si ya estaba stale, el aviso llega tarde: no lo repitas.

        CONTROL NEGATIVO: sin esta rama el guard gritaria en CADA commit
        posterior, y un aviso constante se vuelve invisible.
        """
        wired(tested_commit_sha="0000000000000000000000000000000000000000")
        assert guard.main() == 0
        assert capsys.readouterr().out == ""

    def test_sin_git_calla(self, wired, monkeypatch, capsys):
        """git indisponible no debe impedir commitear."""
        wired()
        monkeypatch.setattr(guard, "_head", lambda: None)
        assert guard.main() == 0
        assert capsys.readouterr().out == ""


class TestNuncaBloquea:
    """Es telemetria accionable, no una barrera de correccion."""

    def test_exit_cero_en_todos_los_escenarios(self, wired):
        """MUTACION: devolver 1 al avisar -> obligaria a correr la suite entre
        cada par de commits, que es JUSTAMENTE el desperdicio que se evita.
        La barrera bloqueante ya existe y vive en `pre_handoff_guard`.
        """
        for override in ({}, {"status": "started"}, {"exit_code": 1}):
            wired(**override)
            assert guard.main() == 0
