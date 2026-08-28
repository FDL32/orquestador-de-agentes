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
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

import pytest


HOOK_DIR = pathlib.Path(__file__).parent.parent.parent / ".agent" / "hooks"
HOOK_PATH = HOOK_DIR / "native_stop_hook.py"
sys.path.insert(0, str(HOOK_DIR))

import native_stop_hook as hook  # noqa: E402


def _run_git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)


def make_git_repo(tmp_path):
    """Repo git REAL y hermetico (tiene su propio .git, no hace walk-up)."""
    _run_git(tmp_path, "init", "-q")
    _run_git(tmp_path, "config", "user.email", "t@example.invalid")
    _run_git(tmp_path, "config", "user.name", "T")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _run_git(tmp_path, "add", "seed.txt")
    _run_git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def current_baseline(root):
    """Baseline git tal y como lo escribe scripts/verification_mode.py.

    WOT-2026-044x: incluye `activated_at` fresco, porque el escritor real
    (turn_on) siempre lo escribe y el hook ahora lo lee para decidir
    caducidad. Los tests que quieren centinela VIEJO escriben su propio
    sentinel_text.
    """
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True
    ).stdout.decode()
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"], capture_output=True
    ).stdout.decode()
    return {
        "baseline_head": head.strip(),
        "baseline_status_hash": hook.status_hash(status),
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }


def make_root(
    tmp_path,
    *,
    sentinel: bool = False,
    sentinel_as_dir: bool = False,
    mutated: bool = True,
    baseline: dict | None = None,
    sentinel_text: str | None = None,
):
    """Raiz sintetica con `.claude/`, repo git y centinela opcional.

    `mutated=True` (por defecto) deja el arbol CAMBIADO respecto al baseline,
    que es la condicion bajo la cual el hook debe exigir clasificacion.
    """
    (tmp_path / ".claude").mkdir()
    make_git_repo(tmp_path)

    if sentinel or sentinel_as_dir or sentinel_text is not None:
        target = tmp_path / hook.SENTINEL_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        if sentinel_as_dir:
            target.mkdir()
        elif sentinel_text is not None:
            target.write_text(sentinel_text, encoding="utf-8")
        else:
            data = baseline if baseline is not None else current_baseline(tmp_path)
            target.write_text(json.dumps(data), encoding="utf-8")

    if mutated:
        # Mutacion estructural posterior al baseline: fichero nuevo sin trackear.
        (tmp_path / "mutacion.txt").write_text("cambio\n", encoding="utf-8")
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


class TestPuertaMutacion:
    """Proporcionalidad: sin mutacion del repo NO se exige recibo.

    Justificacion medida (2026-07-31): sobre 33.476 mensajes finales reales de
    1654 transcripts, el criterio "falta el marcador" bloqueaba 33.473 (100,0%).
    Sin esta puerta la barrera es un denial-of-service, no un mecanismo.
    """

    def test_sin_mutacion_no_bloquea(self, tmp_path):
        root = make_root(tmp_path, sentinel=True, mutated=False)
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": UNMARKED,
            }
        )
        _, result, _ = run_hook(payload, root)
        assert result.get("continue") is True
        assert "decision" not in result

    def test_head_distinto_es_mutacion(self, tmp_path):
        """Un commit nuevo mueve HEAD: eso basta como prueba de mutacion."""
        root = make_root(tmp_path, sentinel=True, mutated=False)
        (root / "otro.txt").write_text("x\n", encoding="utf-8")
        _run_git(root, "add", "otro.txt")
        _run_git(root, "commit", "-q", "-m", "cambio")
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": UNMARKED,
            }
        )
        _, result, _ = run_hook(payload, root)
        assert result.get("decision") == "block"

    def test_baseline_ausente_no_bloquea(self, tmp_path):
        """Centinela sin baseline -> no se puede probar mutacion -> fail-open."""
        root = make_root(tmp_path, sentinel_text="")
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": UNMARKED,
            }
        )
        _, result, _ = run_hook(payload, root)
        assert result.get("continue") is True

    def test_centinela_json_invalido_no_bloquea(self, tmp_path):
        root = make_root(tmp_path, sentinel_text="{roto")
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": UNMARKED,
            }
        )
        _, result, _ = run_hook(payload, root)
        assert result.get("continue") is True

    def test_sin_repo_git_no_bloquea(self, tmp_path):
        """Sin git medible no hay prueba de mutacion: fail-open."""
        root = tmp_path / "sinrepo"
        root.mkdir()
        (root / ".claude").mkdir()
        target = root / hook.SENTINEL_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"baseline_head": "deadbeef", "baseline_status_hash": "x"}),
            encoding="utf-8",
        )
        payload = json.dumps(
            {
                "cwd": str(root),
                "stop_hook_active": False,
                "last_assistant_message": UNMARKED,
            }
        )
        _, result, _ = run_hook(payload, root)
        assert result.get("continue") is True


class TestCoherenciaScriptHook:
    """El script que enciende y el hook que lee deben hashear IGUAL.

    Si divergieran, el baseline nunca casaria y la barrera bloquearia siempre
    o nunca. Este test pinea el acoplamiento deliberado.
    """

    def test_status_hash_es_el_mismo(self):
        sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "scripts"))
        import verification_mode

        muestra = "?? nuevo.txt\n M editado.py\n"
        assert verification_mode.status_hash(muestra) == hook.status_hash(muestra)

    def test_centinela_no_cuenta_como_mutacion(self):
        """El centinela vive DENTRO del arbol; no debe verse a si mismo."""
        assert hook.status_hash("") == hook.status_hash("?? .agent/\n")
        assert hook.status_hash("") == hook.status_hash(
            "?? .agent/runtime/verification_mode.json\n"
        )
        assert hook.status_hash("") == hook.status_hash(
            "?? .agent/runtime/verification_observations.json\n"
        )
        # Un fichero real SI cuenta.
        assert hook.status_hash("") != hook.status_hash("?? codigo.py\n")


class TestMarcadorDebeClasificar:
    """El marcador CLASIFICA solo si abre linea; mencionarlo no basta.

    DEFECTO REAL cazado por el canario de WOT-2026-044y (2026-07-31), no por
    revision ni por los tests previos: al explicar el mecanismo en un cierre, el
    propio texto contenia los literales y el hook lo dio por clasificado
    (`has_marker: true` en canary_stop.jsonl). Los tests anteriores no podian
    verlo porque usaban mensajes que o clasificaban de verdad o no mencionaban
    el marcador -- ninguno cubria el caso intermedio.
    """

    def _bloquea(self, message):
        return hook.needs_classification(
            {"stop_hook_active": False, "last_assistant_message": message}
        )

    @pytest.mark.parametrize(
        "message",
        [
            "El hook exige [EVIDENCIA] o [HIPOTESIS] al cerrar.",
            "Marca el mensaje final con [EVIDENCIA] cuando midas algo.",
            "Los marcadores son [EVIDENCIA] y [HIPOTESIS].",
        ],
    )
    def test_mencion_no_clasifica(self, message):
        assert self._bloquea(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "[EVIDENCIA] pytest -> 25 passed",
            "[HIPOTESIS] no comprobado en CI",
            "**[EVIDENCIA]** ruff check exit 0",
            "> [HIPOTESIS] sin medir todavia",
            "He terminado el ajuste.\n\n[EVIDENCIA] suite verde, exit 0",
        ],
    )
    def test_marcador_en_linea_si_clasifica(self, message):
        assert self._bloquea(message) is False

    @pytest.mark.parametrize(
        "message",
        [
            "```\n[EVIDENCIA] ejemplo dentro de codigo\n```",
            "```bash\n[HIPOTESIS] ejemplo\n```",
            "  ```\n  [EVIDENCIA] fence indentado\n  ```",
            "| col |\n|-----|\n| [EVIDENCIA] en tabla |",
            "        [EVIDENCIA] indentado 8 espacios",
            "ok [EVIDENCIA] con texto antes en la misma linea",
        ],
    )
    def test_marcador_no_clasificable_bloquea(self, message):
        """Un marcador que no ABRE linea util no clasifica.

        Incluye el hueco de los code fences: mostrar un EJEMPLO dentro de ```
        no es clasificar el cierre. Salio del barrido exhaustivo, no del corpus:
        sobre 33.476 mensajes reales hay 871 con fence (2,6%) y CERO con su
        unico marcador dentro de uno -- pero el caso natural donde aparece es
        documentar el propio mecanismo, que es justo lo que ya fallo una vez.
        """
        assert self._bloquea(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "```\ncode\n```\n\n[EVIDENCIA] fuera del fence, exit 0",
            "[EVIDENCIA] real\n\n```\n[EVIDENCIA] ejemplo\n```",
            "[EVIDENCIA] real\n\n```\nfence sin cerrar",
            "Hecho.\r\n[EVIDENCIA] con CRLF",
            "_[EVIDENCIA]_ cursiva",
            "> **[EVIDENCIA]** cita con negrita",
        ],
    )
    def test_marcador_fuera_de_fence_si_clasifica(self, message):
        """Control negativo del fence: lo de fuera sigue valiendo."""
        assert self._bloquea(message) is False

    def test_el_propio_reason_no_se_autoaprueba(self):
        """El texto que el hook devuelve al agente no puede valer como cierre.

        Si el agente reenviara el `reason` tal cual, seguiria sin clasificar.
        """
        assert self._bloquea(hook._REASON) is True


class TestObserveOnly:
    """Escape por entorno: mide pero NO bloquea (WOT-2026-044t).

    Existe para que un vuelo autonomo -- sin humano delante -- no estrene una
    barrera bloqueante en la corrida que debe salir sola. Exigido por revision
    adversarial Codex: "no es defendible estrenarla en el vuelo autonomo".
    """

    def _payload(self, root):
        return json.dumps(
            {
                "cwd": str(root),
                "session_id": "s-test",
                "stop_hook_active": False,
                "last_assistant_message": UNMARKED,
            }
        )

    @pytest.mark.parametrize(
        "env",
        [
            {"AGENT_VERIFICATION_MODE": "observe"},
            {"AGENT_VERIFICATION_MODE": "OBSERVE"},
            {"AGENT_DISABLE_VERIFICATION_STOP_HOOK": "1"},
        ],
    )
    def test_observe_no_bloquea(self, tmp_path, env):
        root = make_root(tmp_path, sentinel=True)
        proc = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=self._payload(root).encode("utf-8"),
            capture_output=True,
            cwd=str(root),
            env={**os.environ, **env},
        )
        result = json.loads(proc.stdout.decode("utf-8").strip())
        assert result.get("continue") is True
        assert "decision" not in result

    def test_observe_registra_la_observacion(self, tmp_path):
        """La medicion es el motivo de observe-only frente a un apagado seco."""
        root = make_root(tmp_path, sentinel=True)
        subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=self._payload(root).encode("utf-8"),
            capture_output=True,
            cwd=str(root),
            env={**os.environ, "AGENT_VERIFICATION_MODE": "observe"},
        )
        log = root / ".agent" / "runtime" / "verification_observations.json"
        assert log.is_file()
        record = json.loads(log.read_text(encoding="utf-8").strip())
        assert record["would_have_blocked"] is True
        assert record["message_len"] == len(UNMARKED)

    def test_observacion_no_vuelca_el_mensaje(self, tmp_path):
        """Telemetria SIN contenido de sesion: solo la longitud."""
        root = make_root(tmp_path, sentinel=True)
        subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=self._payload(root).encode("utf-8"),
            capture_output=True,
            cwd=str(root),
            env={**os.environ, "AGENT_VERIFICATION_MODE": "observe"},
        )
        log = root / ".agent" / "runtime" / "verification_observations.json"
        assert UNMARKED not in log.read_text(encoding="utf-8")

    def test_sin_env_si_bloquea(self, tmp_path):
        """Control negativo: el escape debe ser explicito, no el default."""
        root = make_root(tmp_path, sentinel=True)
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in ("AGENT_VERIFICATION_MODE", "AGENT_DISABLE_VERIFICATION_STOP_HOOK")
        }
        proc = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=self._payload(root).encode("utf-8"),
            capture_output=True,
            cwd=str(root),
            env=env,
        )
        result = json.loads(proc.stdout.decode("utf-8").strip())
        assert result.get("decision") == "block"

    def test_valor_arbitrario_no_activa_el_escape(self, tmp_path):
        """`AGENT_VERIFICATION_MODE=on` NO es `observe`: no debe abrir."""
        root = make_root(tmp_path, sentinel=True)
        proc = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=self._payload(root).encode("utf-8"),
            capture_output=True,
            cwd=str(root),
            env={**os.environ, "AGENT_VERIFICATION_MODE": "on"},
        )
        result = json.loads(proc.stdout.decode("utf-8").strip())
        assert result.get("decision") == "block"


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
