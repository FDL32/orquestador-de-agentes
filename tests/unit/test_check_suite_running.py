"""Tests del aviso pre-commit de suite EN CURSO (WOT-2026-NOTICKET-lock-suite).

Lo que pinean: el aviso aparece SOLO cuando hay una suite canonica
ACTIVAMENTE corriendo (lock presente y PID dueno vivo) en el momento del
commit, nunca bloquea, y es fail-open ante cualquier fallo de lectura.

Hallazgo que origina este guard: `scripts/run_pytest_safe.py` ya tiene un
lock completo (`acquire_lock`/`get_lock_status`), pero ningun hook de
pre-commit lo consultaba -- un commit en el motor mientras otra sesion
corria la suite invalidaba la medicion en curso sin ningun aviso (medido en
el canal manual entre sesiones, turnos T3-T9: 2 corridas invalidadas antes
de la 3a definitiva).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_suite_running.py"
)
_spec = importlib.util.spec_from_file_location("check_suite_running", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _write_lock(tmp_path: Path, **overrides) -> Path:
    """pytest.lock con un lock ACTIVO (PID propio, started_at valido), salvo overrides."""
    import os
    from datetime import datetime, timezone

    data = {
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cwd": str(tmp_path),
    }
    data.update(overrides)
    path = tmp_path / "pytest.lock"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Apunta el guard a un LOCK_FILE de fixture, sin tocar el repo real."""

    def _apply(**overrides):
        monkeypatch.setattr(guard, "LOCK_FILE", _write_lock(tmp_path, **overrides))

    return _apply


class TestAvisaCuandoHayLockActivo:
    """El unico caso en que el aviso sirve: una suite esta corriendo AHORA."""

    def test_avisa_cuando_el_pid_dueno_esta_vivo(self, wired, capsys):
        """Caso fundacional: lock presente, PID (el propio proceso de test,
        vivo por definicion) activo -> avisa.

        MUTACION ALCANZABLE: quitar la llamada a get_lock_status() -> el
        guard calla siempre y el aviso deja de cumplir su proposito.
        """
        wired()
        assert guard.main() == 0
        out = capsys.readouterr().out
        assert "AVISO" in out
        assert "No bloquea" in out, "debe dejar claro que commitear es legitimo"

    def test_el_aviso_nombra_el_pid(self, wired, capsys):
        import os

        wired()
        guard.main()
        out = capsys.readouterr().out
        assert str(os.getpid()) in out


class TestNoAvisaCuandoNoProcede:
    """Ruido cero: un aviso que salta siempre se ignora siempre."""

    def test_sin_lock_calla(self, monkeypatch, tmp_path):
        monkeypatch.setattr(guard, "LOCK_FILE", tmp_path / "no-existe.lock")
        assert guard.main() == 0

    def test_json_corrupto_calla_fail_open(self, monkeypatch, tmp_path):
        """Fail-open explicito (correccion de la ronda de gobierno, codex):
        un lock ilegible NUNCA debe bloquear ni reventar el hook."""
        p = tmp_path / "pytest.lock"
        p.write_text("{roto", encoding="utf-8")
        monkeypatch.setattr(guard, "LOCK_FILE", p)
        assert guard.main() == 0

    def test_pid_invalido_no_numerico_calla_fail_open(self, wired, monkeypatch):
        wired(pid="no-es-un-pid")
        assert guard.main() == 0

    def test_lock_con_pid_muerto_calla(self, wired, capsys):
        """PID inequivocamente invalido (<=0): is_pid_running lo trata como
        muerto por construccion -- no hace falta un PID real del SO."""
        wired(pid=-1)
        assert guard.main() == 0
        assert capsys.readouterr().out == ""


class TestNuncaBloquea:
    """Es telemetria accionable, no una barrera de correccion."""

    def test_exit_cero_en_todos_los_escenarios(self, wired, monkeypatch, tmp_path):
        """MUTACION: devolver 1 al avisar obligaria a parar el commit cada
        vez que otra sesion corre la suite -- justo el acoplamiento fragil
        que el propio bucle de gobierno descarto (Via C, solo protocolo)."""
        wired()
        assert guard.main() == 0

        monkeypatch.setattr(guard, "LOCK_FILE", tmp_path / "ausente.lock")
        assert guard.main() == 0

        p = tmp_path / "roto.lock"
        p.write_text("{", encoding="utf-8")
        monkeypatch.setattr(guard, "LOCK_FILE", p)
        assert guard.main() == 0


class TestNoMuta:
    """El hook es READ-ONLY: nunca debe crear, tocar ni borrar pytest.lock."""

    def test_no_crea_el_lock_si_no_existia(self, monkeypatch, tmp_path):
        lock_path = tmp_path / "pytest-safe" / "pytest.lock"
        monkeypatch.setattr(guard, "LOCK_FILE", lock_path)
        guard.main()
        assert not lock_path.exists(), (
            "el guard de verificacion jamas debe CREAR el lock "
            "(eso seria usar acquire_lock(), prohibido por contrato: "
            "debe ser read-only)"
        )

    def test_no_modifica_un_lock_existente(self, wired, tmp_path):
        wired()
        lock_path = tmp_path / "pytest.lock"
        before = lock_path.read_bytes()
        guard.main()
        after = lock_path.read_bytes()
        assert before == after, "el guard no debe escribir en un lock ajeno"
