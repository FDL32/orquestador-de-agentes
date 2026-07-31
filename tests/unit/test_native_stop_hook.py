#!/usr/bin/env python3
"""Tests para native_stop_hook.py (WOT-2026-044t).

Cubre:
- Fail-open: payload vacio, no-JSON, JSON no-objeto, mensaje ausente/vacio
- Centinela: ausente -> no-op; presente pero no-regular -> fail-open
- Guard de reentrada: stop_hook_active truthy y AUSENTE -> no bloquea
- Bloqueo: centinela + marcador ausente -> decision == "block"
- Marcadores [EVIDENCIA] / [HIPOTESIS] -> no bloquean
- Contrato de salida: nunca continue:false, nunca refleja el payload
"""

import json
import pathlib
import subprocess
import sys

import pytest


HOOK_DIR = pathlib.Path(__file__).parent.parent.parent / ".agent" / "hooks"
HOOK_PATH = HOOK_DIR / "native_stop_hook.py"
sys.path.insert(0, str(HOOK_DIR))

import native_stop_hook as hook  # noqa: E402


def make_root(tmp_path, *, sentinel: bool = False, sentinel_as_dir: bool = False):
    """Crea una raiz de repo sintetica con `.claude/` y centinela opcional."""
    (tmp_path / ".claude").mkdir()
    if sentinel or sentinel_as_dir:
        target = tmp_path / hook.SENTINEL_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        if sentinel_as_dir:
            target.mkdir()
        else:
            target.write_text("on", encoding="utf-8")
    return tmp_path


def run_hook(payload_text: str, cwd: pathlib.Path) -> tuple[int, dict, str]:
    """Ejecuta el hook como PROCESO REAL, igual que lo lanza settings.json."""
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload_text.encode("utf-8"),
        capture_output=True,
        cwd=str(cwd),
    )
    out = proc.stdout.decode("utf-8").strip()
    parsed = json.loads(out) if out else {}
    return proc.returncode, parsed, proc.stderr.decode("utf-8")


UNMARKED = "El fallo se debe a que el manifiesto no propaga el archive."


class TestFailOpen:
    """Entrada anomala nunca debe bloquear."""

    def test_payload_vacio_no_bloquea(self, tmp_path):
        root = make_root(tmp_path, sentinel=True)
        rc, result, _ = run_hook("", root)
        assert rc == 0
        assert result.get("continue") is True
        assert "decision" not in result

    def test_payload_no_json_no_bloquea_con_diagnostico(self, tmp_path):
        root = make_root(tmp_path, sentinel=True)
        rc, result, stderr = run_hook("{no es json", root)
        assert rc == 0
        assert result.get("continue") is True
        assert "native_stop_hook" in stderr

    def test_json_no_objeto_no_bloquea(self, tmp_path):
        root = make_root(tmp_path, sentinel=True)
        rc, result, _ = run_hook("[1, 2, 3]", root)
        assert rc == 0
        assert result.get("continue") is True

    def test_diagnostico_no_refleja_payload(self, tmp_path):
        """El stderr no debe filtrar el contenido de la sesion."""
        root = make_root(tmp_path, sentinel=True)
        secreto = "TOKEN_SUPERSECRETO_42"
        _, _, stderr = run_hook("{roto " + secreto, root)
        assert secreto not in stderr


class TestCentinela:
    """El trigger opt-in gobierna si el hook actua."""

    def test_sin_centinela_no_bloquea_aunque_falte_marcador(self, tmp_path):
        root = make_root(tmp_path, sentinel=False)
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": UNMARKED,
            }
        )
        rc, result, _ = run_hook(payload, root)
        assert rc == 0
        assert result.get("continue") is True
        assert "decision" not in result

    def test_centinela_directorio_es_fail_open(self, tmp_path):
        root = make_root(tmp_path, sentinel_as_dir=True)
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": UNMARKED,
            }
        )
        _, result, _ = run_hook(payload, root)
        assert result.get("continue") is True


class TestBloqueo:
    """Con centinela activo, la ausencia de marcador bloquea."""

    def test_marcador_ausente_bloquea(self, tmp_path):
        root = make_root(tmp_path, sentinel=True)
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": UNMARKED,
            }
        )
        rc, result, _ = run_hook(payload, root)
        assert rc == 0
        assert result.get("decision") == "block"
        assert "[EVIDENCIA]" in result.get("reason", "")
        # Nunca debe usar continue:false, que pararia a Claude por completo.
        assert result.get("continue") is not False

    def test_reason_acotado(self, tmp_path):
        root = make_root(tmp_path, sentinel=True)
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": UNMARKED,
            }
        )
        _, result, _ = run_hook(payload, root)
        assert len(result.get("reason", "")) <= hook.REASON_MAX_LEN

    @pytest.mark.parametrize("marker", ["[EVIDENCIA]", "[HIPOTESIS]"])
    def test_con_marcador_no_bloquea(self, tmp_path, marker):
        root = make_root(tmp_path, sentinel=True)
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": f"{marker} ruff check . -> exit 0",
            }
        )
        rc, result, _ = run_hook(payload, root)
        assert rc == 0
        assert result.get("continue") is True
        assert "decision" not in result


class TestGuardReentrada:
    """Nunca debe encerrar al agente en un bucle de re-entrega."""

    def test_stop_hook_active_truthy_no_bloquea(self, tmp_path):
        root = make_root(tmp_path, sentinel=True)
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": True,
                "last_assistant_message": UNMARKED,
            }
        )
        _, result, _ = run_hook(payload, root)
        assert result.get("continue") is True
        assert "decision" not in result

    def test_stop_hook_active_ausente_no_bloquea(self, tmp_path):
        """Exigido por revision Codex: el campo NO esta documentado.

        Si desapareciera del payload, asumir "no activo" abriria un bucle de
        re-entrega. Su ausencia es fail-open.
        """
        root = make_root(tmp_path, sentinel=True)
        payload = json.dumps({"cwd": str(root), "last_assistant_message": UNMARKED})
        _, result, _ = run_hook(payload, root)
        assert result.get("continue") is True
        assert "decision" not in result


class TestMensajeInvalido:
    """Un mensaje ausente o vacio no es evidencia de infraccion."""

    @pytest.mark.parametrize("message", [None, "", "   \n  ", 42])
    def test_mensaje_no_utilizable_no_bloquea(self, tmp_path, message):
        root = make_root(tmp_path, sentinel=True)
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": message,
            }
        )
        _, result, _ = run_hook(payload, root)
        assert result.get("continue") is True


class TestMutacion:
    """MUTATION: aisla la deteccion de ausencia de marcador.

    Si se rompe el criterio (p.ej. MARKERS pasa a tupla vacia, o
    `needs_classification` devuelve siempre False), el node-id
    `TestBloqueo::test_marcador_ausente_bloquea` pasa a ROJO, mientras que
    los tests de fail-open siguen verdes. Este test pinea el invariante en
    la funcion pura, sin subprocess, para que la mutacion sea inequivoca.
    """

    def test_deteccion_discrimina_marcado_de_no_marcado(self):
        base = {"stop_hook_active": False}
        assert (
            hook.needs_classification({**base, "last_assistant_message": UNMARKED})
            is True
        )
        assert (
            hook.needs_classification(
                {**base, "last_assistant_message": "[EVIDENCIA] pytest -> 12 passed"}
            )
            is False
        )

    def test_markers_no_pueden_vaciarse(self):
        """Pinea que la lista de marcadores no se vacie silenciosamente."""
        assert len(hook.MARKERS) == 2
        assert "[EVIDENCIA]" in hook.MARKERS
        assert "[HIPOTESIS]" in hook.MARKERS
