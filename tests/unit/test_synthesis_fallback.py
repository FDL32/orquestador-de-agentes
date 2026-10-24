import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import ensemble_dispatch as ed  # noqa: E402


@pytest.fixture
def mock_config(tmp_path):
    config = {
        "ensemble_profiles": {
            "challenger_opencode_glm_flash": {
                "backend": "opencode",
                "model": "opencode-go/glm-5.3-flash",
                "backend_key": "BA06",
            },
            "challenger_opencode_glm_5_2": {
                "backend": "opencode",
                "model": "opencode-go/glm-5.3-flash",
                "backend_key": "BA06",
                "status": "legacy",
                "replaced_by": "challenger_opencode_glm_flash",
            },
            "challenger_nan_qwen": {
                "backend": "nan_api",
                "model": "qwen3.6",
                "backend_key": "BA11",
            },
            "challenger_nan_deepseek": {
                "backend": "nan_api",
                "model": "deepseek-v4-flash",
                "backend_key": "BA12",
            },
        },
        "backends": {
            "opencode": {"executable": "echo", "args": []},
            "nan_api": {"executable": "echo", "args": []},
        },
    }
    # Fixture realista: schema REAL de `regenerate_leaders` (nunca una clave
    # inventada "profile" -- esa clave no existe en ningun productor del
    # fichero). El lider se declara como {"backend", "model"}, no por nombre
    # de perfil; dos perfiles nan_api conviven aqui a proposito para que un
    # test que solo cayera por rotacion PONG (en vez de por el lider
    # declarado) pueda distinguirse de uno que SI respeta backend_leaders.
    leaders_dir = tmp_path / ".agent" / "runtime" / "ensemble"
    leaders_dir.mkdir(parents=True)
    leaders_file = leaders_dir / "backend_leaders.json"
    # El lider declarado es el SEGUNDO perfil nan_api en orden de insercion
    # de `ensemble_profiles` a proposito: la rotacion PONG (fallback cuando
    # NO hay lider o el selector esta roto) recorre el dict en orden y
    # encontraria `challenger_nan_qwen` (el primero) ANTES que el lider real
    # `challenger_nan_deepseek` -- si el test solo pasara por rotacion ciega
    # en vez de por el lider declarado, esta asimetria lo delataria.
    leaders_file.write_text(
        json.dumps(
            {
                "por_task_type": {
                    "code-gen": {
                        "lider": {"backend": "nan_api", "model": "deepseek-v4-flash"},
                        "n_muestras": 7,
                    }
                }
            }
        )
    )
    return config, tmp_path


def test_synthesis_fallback_on_empty_reply(mock_config):
    config, tmp_path = mock_config

    # We want to mock send_to_profile to return "" on the first call (the glm one)
    # and "ok" on the second call (the nan one)
    with (
        patch("ensemble_dispatch.send_to_profile") as mock_send,
        patch("ensemble_dispatch.smoke_profile") as mock_smoke,
        patch("ensemble_dispatch.append_fallback_event") as mock_append,
    ):
        # First call: glm (empty)
        # Second call: nan (ok)
        mock_send.side_effect = ["", "ok"]
        mock_smoke.return_value = {"alive": True, "outcome": "ok"}

        reply = ed.run_loop_round(
            profile_name="challenger_opencode_glm_flash",
            content="material",
            config=config,
            project_root=tmp_path,
            ticket="WOT-TEST-FALLBACK",
            task_type="code-gen",
            rol="challenger",
            phase="close",
            loop_id="L999",
            backend_key="BA06",
            sensitivity="public",
            ronda=0,
            context_kind="diff",
            transport=None,
            session_id="S1",
            commit_sha="sha123",
            challenge_nonce="nonce123",
            _tried_profiles=frozenset(),
        )

        assert reply == "ok"
        assert mock_send.call_count == 2
        assert mock_append.called, "Fallback event should be recorded"
        fallback_event = mock_append.call_args[0][1]
        assert fallback_event["fallback_profile"] == "challenger_nan_deepseek", (
            "debe elegir el LIDER declarado en backend_leaders.json, no el "
            "primer nan_api vivo por rotacion PONG (seria challenger_nan_qwen)"
        )


def test_synthesis_fallback_on_unexpected_exception(mock_config):
    config, tmp_path = mock_config

    with (
        patch("ensemble_dispatch.send_to_profile") as mock_send,
        patch("ensemble_dispatch.smoke_profile") as mock_smoke,
        patch("ensemble_dispatch.append_fallback_event") as mock_append,
    ):
        # First call: glm (RuntimeError)
        # Second call: nan (ok)
        mock_send.side_effect = [RuntimeError("Unexpected error"), "ok"]
        mock_smoke.return_value = {"alive": True, "outcome": "ok"}

        reply = ed.run_loop_round(
            profile_name="challenger_opencode_glm_flash",
            content="material",
            config=config,
            project_root=tmp_path,
            ticket="WOT-TEST-FALLBACK-EXC",
            task_type="code-gen",
            rol="challenger",
            phase="close",
            loop_id="L999",
            backend_key="BA06",
            sensitivity="public",
            ronda=0,
            context_kind="diff",
            transport=None,
            session_id="S1",
            commit_sha="sha123",
            challenge_nonce="nonce123",
            _tried_profiles=frozenset(),
        )

        assert reply == "ok"
        assert mock_send.call_count == 2
        assert mock_append.called
        fallback_event = mock_append.call_args[0][1]
        assert fallback_event["fallback_profile"] == "challenger_nan_deepseek"


def test_synthesis_fallback_on_rc_nonzero_text(mock_config):
    """Revisor H1: el canal `agent` no lanza ante rc!=0 (cuota/auth/crash del
    CLI) -- devuelve TEXTO `[transport-failed] rc=N...`. Antes del fix este
    texto se devolvia tal cual como "sintesis", el modo de fallo ("fin de
    cuota") que motivo el alta del ticket."""
    config, tmp_path = mock_config

    with (
        patch("ensemble_dispatch.send_to_profile") as mock_send,
        patch("ensemble_dispatch.smoke_profile") as mock_smoke,
        patch("ensemble_dispatch.append_fallback_event") as mock_append,
    ):
        mock_send.side_effect = [
            "[transport-failed] rc=1\nError: quota exhausted",
            "ok",
        ]
        mock_smoke.return_value = {"alive": True, "outcome": "ok"}

        reply = ed.run_loop_round(
            profile_name="challenger_opencode_glm_flash",
            content="material",
            config=config,
            project_root=tmp_path,
            ticket="WOT-TEST-FALLBACK-RC",
            task_type="code-gen",
            rol="challenger",
            phase="close",
            loop_id="L999",
            backend_key="BA06",
            sensitivity="public",
            ronda=0,
            context_kind="diff",
            transport=None,
            session_id="S1",
            commit_sha="sha123",
            challenge_nonce="nonce123",
            _tried_profiles=frozenset(),
        )

        assert reply == "ok", (
            "un rc!=0 del canal agent NO debe devolverse tal cual como sintesis"
        )
        assert mock_send.call_count == 2
        assert mock_append.called
        fallback_event = mock_append.call_args[0][1]
        assert fallback_event["fallback_profile"] == "challenger_nan_deepseek"
        assert fallback_event["selection"] == "lider"


def test_synthesis_fallback_fires_for_legacy_glm_profile_name(mock_config):
    """Revisor H2: el despacho canonico de close documentado en
    `prompts/orchestrator_autonomous_ticket_batch.md` usa el nombre de perfil
    LEGACY `challenger_opencode_glm_5_2` (mismo backend/model, `replaced_by`
    apunta al activo). El gatillo debe disparar tambien con ese nombre, o el
    fallback queda muerto en la ruta de despacho real."""
    config, tmp_path = mock_config

    with (
        patch("ensemble_dispatch.send_to_profile") as mock_send,
        patch("ensemble_dispatch.smoke_profile") as mock_smoke,
        patch("ensemble_dispatch.append_fallback_event") as mock_append,
    ):
        mock_send.side_effect = ["", "ok"]
        mock_smoke.return_value = {"alive": True, "outcome": "ok"}

        reply = ed.run_loop_round(
            profile_name="challenger_opencode_glm_5_2",
            content="material",
            config=config,
            project_root=tmp_path,
            ticket="WOT-TEST-FALLBACK-LEGACY",
            task_type="code-gen",
            rol="challenger",
            phase="close",
            loop_id="L999",
            backend_key="BA06",
            sensitivity="public",
            ronda=0,
            context_kind="diff",
            transport=None,
            session_id="S1",
            commit_sha="sha123",
            challenge_nonce="nonce123",
            _tried_profiles=frozenset(),
        )

        assert reply == "ok", (
            "el fallback debe disparar tambien para el nombre de perfil "
            "legacy que usa el despacho canonico documentado"
        )
        assert mock_send.call_count == 2
        assert mock_append.called
