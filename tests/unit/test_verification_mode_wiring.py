#!/usr/bin/env python3
"""Tests de CABLEADO del modo verificacion (WOT-2026-044u).

Por que existen
---------------
`native_stop_hook.py` solo muerde si el centinela `.agent/runtime/verification_mode`
existe. Si NADIE lo enciende ni lo apaga desde un camino que corre solo, la barrera
es "una norma, no un mecanismo" (AGENTS.md) -- que es exactamente como nacio inerte
WOT-2026-040b.

Estos tests son la barrera de la barrera: si alguien descablea el encendido o el
apagado en un refactor, CAEN. No comprueban texto: ejecutan la ruta.

Cubre:
- ensure-on NO rebaselinea si el centinela ya existe (evita borrar la prueba de mutacion)
- ensure-on SI enciende cuando no existe
- el closeout invoca el apagado y lo reporta como step
- el apagado es idempotente y NO bloqueante
"""

import json
import pathlib
import subprocess
import sys

import pytest


REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

import verification_mode  # noqa: E402


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)


@pytest.fixture
def repo(tmp_path):
    """Repo git REAL y hermetico: tiene su propio .git, no hace walk-up."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(tmp_path, "add", "seed.txt")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


class TestEnsureOn:
    """`ensure-on` debe ser idempotente SIN rebaselinear."""

    def test_enciende_si_no_existe(self, repo):
        rc = verification_mode.ensure_on(repo)
        sentinel = repo / verification_mode.SENTINEL_RELPATH
        assert rc == 0
        assert sentinel.is_file()
        data = json.loads(sentinel.read_text(encoding="utf-8"))
        assert data["baseline_head"]
        assert data["baseline_status_hash"]

    def test_no_rebaselinea_si_ya_estaba_on(self, repo):
        """El caso que Codex exigio: un resume NO puede borrar la prueba.

        Si `ensure-on` re-midiera el baseline contra el estado actual -- que ya
        incluye el trabajo hecho -- la mutacion dejaria de verse y la barrera
        quedaria muda justo en la sesion que mas la necesita.
        """
        verification_mode.ensure_on(repo)
        sentinel = repo / verification_mode.SENTINEL_RELPATH
        antes = sentinel.read_text(encoding="utf-8")

        # Trabajo posterior: muta el arbol.
        (repo / "trabajo.py").write_text("x = 1\n", encoding="utf-8")

        rc = verification_mode.ensure_on(repo)
        despues = sentinel.read_text(encoding="utf-8")

        assert rc == 0
        assert antes == despues, "ensure-on rebaselineo: la mutacion dejaria de verse"

    def test_turn_on_si_rebaselinea(self, repo):
        """Contraste deliberado: `on` a secas SI re-mide. Son comandos distintos."""
        verification_mode.turn_on(repo)
        sentinel = repo / verification_mode.SENTINEL_RELPATH
        antes = json.loads(sentinel.read_text(encoding="utf-8"))
        (repo / "trabajo.py").write_text("x = 1\n", encoding="utf-8")
        verification_mode.turn_on(repo)
        despues = json.loads(sentinel.read_text(encoding="utf-8"))
        assert antes["baseline_status_hash"] != despues["baseline_status_hash"]


class TestEncendidoEnInit:
    """`init` debe encender el modo SIN corromper su salida JSON."""

    def test_init_invoca_el_encendido(self):
        """CABLEADO: si se borra la llamada, esto CAE (AST, no grep de texto)."""
        import ast

        source = (REPO_ROOT / "scripts" / "init_session_scratch.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        cmd_init = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "cmd_init"
        )
        llamadas = {
            n.func.id
            for n in ast.walk(cmd_init)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_ensure_verification_mode" in llamadas, (
            "cmd_init dejo de encender el modo verificacion: la barrera vuelve "
            "a depender de que alguien se acuerde"
        )

    def test_quiet_no_contamina_stdout(self, repo, capsys):
        """Medido en vivo: sin quiet, `init` imprimia texto ANTES de su JSON.

        `cmd_init` emite JSON que otros consumen; un mensaje humano por delante
        rompe a cualquiera que parsee la salida entera.
        """
        verification_mode.ensure_on(repo, quiet=True)
        assert capsys.readouterr().out == ""

        # Segunda llamada (ya encendido) tampoco puede hablar.
        verification_mode.ensure_on(repo, quiet=True)
        assert capsys.readouterr().out == ""

    def test_sin_quiet_si_informa(self, repo, capsys):
        """Contraste: en uso manual el operador SI debe ver el estado."""
        verification_mode.ensure_on(repo, quiet=False)
        assert "verification_mode ON" in capsys.readouterr().out


class TestApagadoEnCloseout:
    """El cierre debe apagar el modo. Si se descablea, estos tests CAEN."""

    def test_step_apaga_el_centinela(self, repo):
        import session_closeout

        sentinel = repo / verification_mode.SENTINEL_RELPATH
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("{}", encoding="utf-8")

        result = session_closeout._step_verification_mode_off(repo, dry_run=False)
        assert result.status == "PASS"
        assert not sentinel.exists()

    def test_step_es_idempotente(self, repo):
        import session_closeout

        result = session_closeout._step_verification_mode_off(repo, dry_run=False)
        assert result.status == "PASS"
        assert "already off" in result.detail

    def test_step_no_es_bloqueante(self, repo):
        """Un fallo de higiene jamas debe tumbar un cierre."""
        import session_closeout

        result = session_closeout._step_verification_mode_off(repo, dry_run=False)
        assert result.blocking is False

    def test_dry_run_no_borra(self, repo):
        import session_closeout

        sentinel = repo / verification_mode.SENTINEL_RELPATH
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("{}", encoding="utf-8")

        result = session_closeout._step_verification_mode_off(repo, dry_run=True)
        assert result.status == "SKIP"
        assert sentinel.exists(), "dry-run no puede mutar estado"

    def test_closeout_registra_el_step(self):
        """CABLEADO: el step debe estar invocado en run_closeout.

        Se comprueba sobre el AST del modulo, no por grep de texto: si alguien
        borra la llamada, esto cae aunque el nombre siga apareciendo en un
        comentario o un docstring.
        """
        import ast

        source = (REPO_ROOT / "scripts" / "session_closeout.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        llamadas = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_step_verification_mode_off" in llamadas, (
            "el closeout dejo de invocar el apagado: la barrera queda encendida "
            "entre sesiones"
        )
