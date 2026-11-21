#!/usr/bin/env python3
"""Tests del delta P9 de native_stop_hook.py (WOT-2026-215a).

Before (pre-condiciones)
------------------------
- Contrato de la rama P9 (ficha WOT-2026-215a s.2 y s.6): aviso LOCAL
  aditivo y fail-open, condicionado al centinela de espera
  ``ESPERA_SENTINEL_RELPATH``, sin deny/permissionDecision/exit 2, con la
  rama 044t conservando precedencia en el veredicto final y con el hook
  siguiendo emitiendo rc 0 + ``{"continue": true}`` ante cualquier anomalia.
- El caso positivo esta DESHABILITADO por defecto: las anclas mecanicas del
  predicado "anuncia una accion futura sin ejecutar" son DECISION_USUARIO
  pendiente (ficha s.2); hasta que se ratifiquen, ``P9_ANCHORS_RATIFIED`` es
  False y ``p9_announces_without_acting`` devuelve False SIEMPRE. Este fichero
  NO ratifica nada: los tests de emision usan un control de MUTACION que
  sustituye el predicado dentro del propio test.
- El stdin de subprocess se construye con la forma EXACTA del volcado real
  hook_dump_174657.json (m-01). Ningun test toca sesiones vivas.

During (proceso)
----------------
1. Contrato fail-open y barrera m-04: pasan tambien sobre la base (no-regresion).
2. Unidades de la maquinaria P9 (resolucion de CO-activa, cola de OPERACION,
   descubrimiento del vuelo, predicado con anclas): en ROJO sobre la base
   porque la maquinaria aun no existe.
3. Integracion: la rama nunca emite aviso con las compuertas por defecto
   (centinela ausente, anclas sin ratificar, cola vacia) y el veredicto
   permanece ``{"continue": true}``; con el predicado forzado, el aviso
   lleva el literal "ejecuta o programa la espera" y 044t sigue ganando.

After (post-condiciones)
-----------------------
- Un fallo aqui significa que la implementacion P9 no cumple el contrato de
  la ficha; la maquinaria debe existir con estos nombres exactos:
  ``_p9_flight_dir``, ``_p9_resolve_co_activa``, ``_p9_cola_no_vacia``,
  ``_p9_notice``, ``p9_announces_without_acting``, ``P9_ANCHORS_RATIFIED``,
  ``P9_ANNOUNCE_ANCHORS`` y ``P9_EXECUTION_ANCHORS``.
"""

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone


HOOK_DIR = pathlib.Path(__file__).parent.parent.parent / ".agent" / "hooks"
HOOK_PATH = HOOK_DIR / "native_stop_hook.py"
sys.path.insert(0, str(HOOK_DIR))

import native_stop_hook as hook  # noqa: E402


#: Forma EXACTA del stdin real capturado en hook_dump_174657.json (m-01).
VOLCADO_REAL_FIELDS = {
    "session_id": "9d58447b-7723-48c5-b82b-b6cddcdcfa23",
    "prompt_id": "0e126a1e-2314-472c-be10-b3065e3406e8",
    "permission_mode": "default",
    "effort": {"level": "medium"},
    "hook_event_name": "Stop",
    "stop_hook_active": False,
    "background_tasks": [],
    "session_crons": [],
}

#: Literal que el aviso P9 debe contener (ficha s.2).
AVISO_LITERAL = "ejecuta o programa la espera"


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


def make_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """Raiz sintetica SOLO con `.claude/` (sin centinelas: 044t y 160z inactivos)."""
    (tmp_path / ".claude").mkdir()
    return tmp_path


def git_init(root: pathlib.Path) -> None:
    """Repo git REAL y hermetico (patron de test_native_stop_hook.py)."""
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "seed"], check=True)


def arm_espera(
    root: pathlib.Path, mode: str = "observe", age_days: float = 0.0
) -> None:
    """Arma el centinela de espera con fecha ISO UTC real (patron 160z)."""
    target = root / hook.ESPERA_SENTINEL_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    activated = datetime.now(timezone.utc).timestamp() - age_days * 86400
    target.write_text(
        json.dumps(
            {
                "mode": mode,
                "activated_at": datetime.fromtimestamp(
                    activated, tz=timezone.utc
                ).isoformat(),
            }
        ),
        encoding="utf-8",
    )


def write_roster(
    flight_dir: pathlib.Path,
    active_roles: object = None,
    *,
    raw: str | None = None,
) -> pathlib.Path:
    """Escribe un flight_roster.json sintetico (o bytes crudos si `raw` va)."""
    flight_dir.mkdir(parents=True, exist_ok=True)
    target = flight_dir / "flight_roster.json"
    if raw is not None:
        target.write_text(raw, encoding="utf-8")
        return flight_dir
    if active_roles is None:
        active_roles = {"orquestador": {"session_code": "CO-77", "status": "active"}}
    target.write_text(
        json.dumps({"schema_version": 1, "active_roles": active_roles}),
        encoding="utf-8",
    )
    return flight_dir


def write_operacion(flight_dir: pathlib.Path, co: str, text: str) -> None:
    """Escribe OPERACION_EN_CURSO_<co>.md dentro del vuelo sintetico."""
    diseno = flight_dir / "diseno"
    diseno.mkdir(parents=True, exist_ok=True)
    (diseno / f"OPERACION_EN_CURSO_{co}.md").write_text(text, encoding="utf-8")


def cola_con_items() -> str:
    """Ultima Entrada con el campo literal y items numerados (forma CO-141)."""
    return (
        "# OPERACION_EN_CURSO_CO-77\n"
        "\n"
        "## Entrada 1 (2026-11-21 09:00 date) - ACTIVO\n"
        "- Estado: CO-77 ACTIVO.\n"
        "- COLA (orden): 1 WOT-2026-176e PASO 1 y despues IM fresco; "
        "2 TERNA P24; 3 suite canonica al final.\n"
        "- Primer tick: guard rc 0.\n"
    )


def make_p9_root(tmp_path: pathlib.Path, *, cola: str | None = None) -> pathlib.Path:
    """Raiz completa para la rama P9: .claude + centinela espera + vuelo con cola."""
    root = make_root(tmp_path)
    arm_espera(root, "observe")
    flight = root / ".agent" / "runtime" / "flight" / "vuelo-p9-test"
    write_roster(flight)
    write_operacion(flight, "CO-77", cola if cola is not None else cola_con_items())
    return root


def p9_payload(root: pathlib.Path, message: str = "ahora hago X") -> dict:
    """Payload Stop con la forma EXACTA del volcado real (m-01)."""
    return {
        **VOLCADO_REAL_FIELDS,
        "cwd": str(root),
        "transcript_path": str(root / "transcript.json"),
        "last_assistant_message": message,
    }


class TestContratoFailOpenDelta:
    """m-02: la rama P9 no degrada el contrato fail-open del hook."""

    def test_stdin_vacio_da_continue(self, tmp_path):
        root = make_root(tmp_path)
        rc, result, _ = run_hook("{}", root)
        assert rc == 0
        assert result == {"continue": True}

    def test_stdin_ilegible_da_continue(self, tmp_path):
        root = make_root(tmp_path)
        rc, result, stderr = run_hook("not-json", root)
        assert rc == 0
        assert result == {"continue": True}
        assert "native_stop_hook" in stderr

    def test_payload_forma_del_volcado_real(self, tmp_path):
        """El stdin sintetico replica el volcado real y sigue fail-open."""
        root = make_root(tmp_path)
        payload = p9_payload(root)
        assert set(payload) == {
            "background_tasks",
            "cwd",
            "effort",
            "hook_event_name",
            "last_assistant_message",
            "permission_mode",
            "prompt_id",
            "session_crons",
            "session_id",
            "stop_hook_active",
            "transcript_path",
        }
        rc, result, stderr = run_hook(json.dumps(payload), root)
        assert rc == 0
        assert result == {"continue": True}
        assert AVISO_LITERAL not in stderr


class TestBarreraM04Delta:
    """m-04: la rama P9 nunca introduce literales de bloqueo o de otro canal."""

    def test_hook_sin_literales_prohibidos(self):
        source = HOOK_PATH.read_text(encoding="utf-8")
        forbidden = (
            "additionalContext",
            "permissionDecision",
            "sys.exit(2",
            "SystemExit(2",
        )
        assert [x for x in forbidden if x in source] == []


class TestResolucionCoActiva:
    """CO-activa: cero o varios candidatos -> None (fail-open sin aviso)."""

    def test_unico_orquestador_activo(self, tmp_path):
        flight = write_roster(tmp_path)
        assert hook._p9_resolve_co_activa(flight) == "CO-77"

    def test_supervisor_no_cuenta_como_segundo_candidato(self, tmp_path):
        flight = write_roster(
            tmp_path,
            {
                "orquestador": {"session_code": "CO-77", "status": "active"},
                "supervisor": {"session_code": "CO-70", "status": "active"},
            },
        )
        assert hook._p9_resolve_co_activa(flight) == "CO-77"

    def test_clave_active_roles_ausente(self, tmp_path):
        (tmp_path / "flight_roster.json").write_text(
            json.dumps({"schema_version": 1}), encoding="utf-8"
        )
        assert hook._p9_resolve_co_activa(tmp_path) is None

    def test_roster_json_ilegible(self, tmp_path):
        flight = write_roster(tmp_path, raw="{roto")
        assert hook._p9_resolve_co_activa(flight) is None

    def test_session_code_vacio(self, tmp_path):
        flight = write_roster(
            tmp_path, {"orquestador": {"session_code": "   ", "status": "active"}}
        )
        assert hook._p9_resolve_co_activa(flight) is None

    def test_dos_orquestadores_candidatos(self, tmp_path):
        """'mas de un orquestador activo' -> None, nunca desempate."""
        flight = write_roster(
            tmp_path,
            {
                "orquestador": {"session_code": "CO-77", "status": "active"},
                "orquestador_suplente": {"session_code": "CO-78", "status": "active"},
            },
        )
        assert hook._p9_resolve_co_activa(flight) is None

    def test_orquestador_como_lista_de_candidatos(self, tmp_path):
        flight = write_roster(
            tmp_path,
            {"orquestador": [{"session_code": "CO-77"}, {"session_code": "CO-78"}]},
        )
        assert hook._p9_resolve_co_activa(flight) is None


class TestColaOperacion:
    """Cola: campo literal '- COLA (orden):' de la ULTIMA Entrada (ficha s.1)."""

    def test_cola_con_items_es_no_vacia(self, tmp_path):
        flight = write_roster(tmp_path)
        write_operacion(flight, "CO-77", cola_con_items())
        assert hook._p9_cola_no_vacia(flight, "CO-77") is True

    def test_cola_en_entrada_antigua_no_cuenta(self, tmp_path):
        """Interpretacion literal: el campo se busca en la ULTIMA Entrada."""
        flight = write_roster(tmp_path)
        write_operacion(
            flight,
            "CO-77",
            "## Entrada 1 (2026-11-21 09:00 date)\n"
            "- COLA (orden): 1 WOT-x PASO 1\n"
            "\n"
            "## Entrada 2 (2026-11-21 10:00 date)\n"
            "- Estado: sin campo de cola aqui.\n",
        )
        assert hook._p9_cola_no_vacia(flight, "CO-77") is False

    def test_campo_sin_items_numerados_es_vacia(self, tmp_path):
        flight = write_roster(tmp_path)
        write_operacion(
            flight,
            "CO-77",
            "## Entrada 1 (2026-11-21 09:00 date)\n"
            "- COLA (orden):\n"
            "- Siguiente campo: nada.\n",
        )
        assert hook._p9_cola_no_vacia(flight, "CO-77") is False

    def test_campo_con_texto_sin_numero_es_vacia(self, tmp_path):
        flight = write_roster(tmp_path)
        write_operacion(
            flight,
            "CO-77",
            "## Entrada 1 (2026-11-21 09:00 date)\n"
            "- COLA (orden): (sin cola)\n"
            "- Siguiente campo: nada.\n",
        )
        assert hook._p9_cola_no_vacia(flight, "CO-77") is False

    def test_items_en_lineas_siguientes(self, tmp_path):
        flight = write_roster(tmp_path)
        write_operacion(
            flight,
            "CO-77",
            "## Entrada 1 (2026-11-21 09:00 date)\n"
            "- COLA (orden):\n"
            "1 WOT-a PASO 1\n"
            "2 WOT-b PASO 2\n"
            "- Siguiente campo: nada.\n",
        )
        assert hook._p9_cola_no_vacia(flight, "CO-77") is True

    def test_encabezado_colahandoff_no_es_el_campo(self, tmp_path):
        """La forma '### COLA (HANDOFF ...)' NO es el literal de la ficha."""
        flight = write_roster(tmp_path)
        write_operacion(
            flight,
            "CO-77",
            "## Entrada 1 (2026-11-21 09:00 date)\n"
            "### COLA (HANDOFF s.2)\n"
            "1 WOT-a PASO 1\n",
        )
        assert hook._p9_cola_no_vacia(flight, "CO-77") is False

    def test_fichero_operacion_ausente(self, tmp_path):
        flight = write_roster(tmp_path)
        assert hook._p9_cola_no_vacia(flight, "CO-99") is False


class TestDescubrimientoVuelo:
    """Descubrimiento del vuelo SIN variables de entorno (patron 176e)."""

    def test_unico_vuelo_bajo_root(self, tmp_path):
        root = make_root(tmp_path)
        write_roster(root / ".agent" / "runtime" / "flight" / "vuelo-a")
        found = hook._p9_flight_dir(root)
        assert found is not None
        assert found.name == "vuelo-a"

    def test_sin_vuelos_da_none(self, tmp_path):
        root = make_root(tmp_path)
        assert hook._p9_flight_dir(root) is None

    def test_dos_vuelos_da_none(self, tmp_path):
        """Cero o varios candidatos de vuelo -> None (fail-open)."""
        root = make_root(tmp_path)
        write_roster(root / ".agent" / "runtime" / "flight" / "vuelo-a")
        write_roster(root / ".agent" / "runtime" / "flight" / "vuelo-b")
        assert hook._p9_flight_dir(root) is None

    def test_resuelve_via_link_destination_root(self, tmp_path):
        """Root sin vuelo propio: el link motor-destination aporta el destino."""
        root = make_root(tmp_path)
        dest = tmp_path / "destino"
        write_roster(dest / ".agent" / "runtime" / "flight" / "vuelo-link")
        (root / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (root / ".agent" / "config" / "motor_destination_link.json").write_text(
            json.dumps({"destination_root": str(dest)}), encoding="utf-8"
        )
        found = hook._p9_flight_dir(root)
        assert found is not None
        assert found.name == "vuelo-link"

    def test_resuelve_via_gitdir_al_checkout_principal(self, tmp_path):
        """Worktree del motor: el gitdir apunta al checkout con el link (176e)."""
        root = make_root(tmp_path)
        main = tmp_path / "principal"
        gitdir = main / ".git" / "worktrees" / "wt1"
        gitdir.mkdir(parents=True)
        (root / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        dest = tmp_path / "destino"
        write_roster(dest / ".agent" / "runtime" / "flight" / "vuelo-gitdir")
        (main / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (main / ".agent" / "config" / "motor_destination_link.json").write_text(
            json.dumps({"destination_root": str(dest)}), encoding="utf-8"
        )
        found = hook._p9_flight_dir(root)
        assert found is not None
        assert found.name == "vuelo-gitdir"


class TestPredicadoAnclas:
    """DECISION_USUARIO pendiente: el caso positivo queda deshabilitado."""

    def test_flag_deshabilitado_por_defecto(self):
        assert hook.P9_ANCHORS_RATIFIED is False

    def test_anclas_vacias_por_defecto(self):
        assert hook.P9_ANNOUNCE_ANCHORS == ()
        assert hook.P9_EXECUTION_ANCHORS == ()

    def test_predicado_false_incluso_con_mensaje_de_anuncio(self):
        """Sin ratificar, NINGUN mensaje clasifica como anuncio sin ejecutar."""
        mensajes = (
            "ahora hago X y luego verifico",
            "sigo con el paso 2 en el siguiente turno",
            "",
        )
        for message in mensajes:
            assert hook.p9_announces_without_acting(message) is False


class TestRamaP9Integracion:
    """La rama P9 es aditiva: aviso local nunca toca el veredicto."""

    def test_sin_centinela_espera_no_emite(self, tmp_path):
        root = make_root(tmp_path)
        flight = root / ".agent" / "runtime" / "flight" / "vuelo-p9-test"
        write_roster(flight)
        write_operacion(flight, "CO-77", cola_con_items())
        rc, result, stderr = run_hook(json.dumps(p9_payload(root)), root)
        assert rc == 0
        assert result == {"continue": True}
        assert AVISO_LITERAL not in stderr

    def test_con_centinela_y_cola_no_emite_por_anclas(self, tmp_path):
        """Default de la ficha: anclas sin ratificar -> cero aviso, rc 0."""
        root = make_p9_root(tmp_path)
        rc, result, stderr = run_hook(json.dumps(p9_payload(root)), root)
        assert rc == 0
        assert result == {"continue": True}
        assert AVISO_LITERAL not in stderr

    def test_roster_roto_no_emite(self, tmp_path, monkeypatch):
        root = make_root(tmp_path)
        arm_espera(root, "observe")
        flight = root / ".agent" / "runtime" / "flight" / "vuelo-p9-test"
        write_roster(flight, raw="{roto")
        write_operacion(flight, "CO-77", cola_con_items())
        monkeypatch.setattr(hook, "p9_announces_without_acting", lambda message: True)
        assert hook._p9_notice(root, p9_payload(root)) is None

    def test_aviso_emitido_con_predicado_forzado(self, tmp_path, monkeypatch):
        """Control de MUTACION: el predicado se sustituye SOLO en el test."""
        root = make_p9_root(tmp_path)
        monkeypatch.setattr(hook, "p9_announces_without_acting", lambda message: True)
        notice = hook._p9_notice(root, p9_payload(root))
        assert notice is not None
        assert AVISO_LITERAL in notice

    def test_aviso_no_emite_sin_centinela(self, tmp_path, monkeypatch):
        root = make_p9_root(tmp_path)
        (root / hook.ESPERA_SENTINEL_RELPATH).unlink()
        monkeypatch.setattr(hook, "p9_announces_without_acting", lambda message: True)
        assert hook._p9_notice(root, p9_payload(root)) is None

    def test_aviso_no_emite_con_centinela_caducado(self, tmp_path, monkeypatch):
        root = make_p9_root(tmp_path)
        arm_espera(root, "observe", age_days=3.0)
        monkeypatch.setattr(hook, "p9_announces_without_acting", lambda message: True)
        assert hook._p9_notice(root, p9_payload(root)) is None

    def test_aviso_no_emite_con_cola_vacia(self, tmp_path, monkeypatch):
        root = make_p9_root(
            tmp_path,
            cola=(
                "## Entrada 1 (2026-11-21 09:00 date)\n"
                "- COLA (orden):\n"
                "- Siguiente campo: nada.\n"
            ),
        )
        monkeypatch.setattr(hook, "p9_announces_without_acting", lambda message: True)
        assert hook._p9_notice(root, p9_payload(root)) is None

    def test_aviso_no_emite_sin_guard_reentrada(self, tmp_path, monkeypatch):
        root = make_p9_root(tmp_path)
        monkeypatch.setattr(hook, "p9_announces_without_acting", lambda message: True)
        payload = p9_payload(root)
        payload.pop("stop_hook_active")
        assert hook._p9_notice(root, payload) is None

    def test_p9_nunca_bloquea(self, tmp_path, monkeypatch):
        """Con el predicado forzado, el veredicto sigue siendo continue."""
        root = make_p9_root(tmp_path)
        monkeypatch.setattr(hook, "p9_announces_without_acting", lambda message: True)
        result = hook._decide(p9_payload(root))
        assert result == {"continue": True}

    def test_044t_conserva_precedencia_sobre_p9(self, tmp_path, monkeypatch):
        """044t armado y con prueba de mutacion: el bloqueo sigue ganando."""
        root = make_root(tmp_path)
        git_init(root)
        (root / hook.SENTINEL_RELPATH).parent.mkdir(parents=True, exist_ok=True)
        (root / hook.SENTINEL_RELPATH).write_text(
            json.dumps(
                {
                    # HEAD real != baseline: hay prueba de mutacion para 044t.
                    "baseline_head": "0" * 40,
                    "baseline_status_hash": hook.status_hash(""),
                    "activated_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        arm_espera(root, "observe")
        flight = root / ".agent" / "runtime" / "flight" / "vuelo-p9-test"
        write_roster(flight)
        write_operacion(flight, "CO-77", cola_con_items())
        monkeypatch.setattr(hook, "p9_announces_without_acting", lambda message: True)
        payload = p9_payload(root, message="El fallo se debe a que nada cambio.")
        result = hook._decide(payload)
        assert result["decision"] == "block"
        assert result["reason"] == hook._REASON[: hook.REASON_MAX_LEN]


class TestDeltaP34Round2:
    """Delta P34 r2 (CO-151): mata los mutantes (a) y (b) que sobrevivian.

    (a) quitar el try/except del call-site de _p9_notice en _decide;
    (b) quitar 'not P9_ANCHORS_RATIFIED' de la guarda del predicado.
    Los mutantes (c) y (d) ya los mataban los tests previos.
    """

    def test_excepcion_en_p9_no_escapa_de_decide(self, tmp_path, monkeypatch):
        """T1: una excepcion en _p9_notice no escapa de _decide (call-site).

        Con el try/except, la decision es la MISMA que sin P9 en los dos
        escenarios: sin bloqueo y con un block de 044t ya calculado (que debe
        seguir bloqueando). Sin la guarda (mutante a), el RuntimeError
        propagaria aqui y este test caeria.
        """
        # Escenario 1: sin bloqueo -> misma decision que con P9 inerte.
        root = make_root(tmp_path)
        payload = p9_payload(root)
        monkeypatch.setattr(hook, "_p9_notice", lambda root_arg, pl: None)
        baseline = hook._decide(payload)
        assert baseline == {"continue": True}

        def boom(root_arg, pl):
            raise RuntimeError("p9 inyectado para el mutante (a)")

        monkeypatch.setattr(hook, "_p9_notice", boom)
        assert hook._decide(payload) == baseline

        # Escenario 2: 044t ya calculo un block -> debe seguir bloqueando.
        block_root = tmp_path / "caso_block"
        block_root.mkdir()
        (block_root / ".claude").mkdir()
        git_init(block_root)
        (block_root / hook.SENTINEL_RELPATH).parent.mkdir(parents=True, exist_ok=True)
        (block_root / hook.SENTINEL_RELPATH).write_text(
            json.dumps(
                {
                    "baseline_head": "0" * 40,
                    "baseline_status_hash": hook.status_hash(""),
                    "activated_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        block_payload = p9_payload(
            block_root, message="El fallo se debe a que nada cambio."
        )
        monkeypatch.setattr(hook, "_p9_notice", lambda root_arg, pl: None)
        baseline_block = hook._decide(block_payload)
        assert baseline_block["decision"] == "block"
        monkeypatch.setattr(hook, "_p9_notice", boom)
        result = hook._decide(block_payload)
        assert result == baseline_block
        assert result["reason"] == hook._REASON[: hook.REASON_MAX_LEN]

    def test_flag_ratificado_gobierna_el_predicado(self, monkeypatch):
        """T2: el flag manda cuando ambas tuplas de anclas estan no vacias.

        Con anclas no vacias, un mensaje que anuncia sin ejecutar clasifica
        SOLO con P9_ANCHORS_RATIFIED=True; con el flag en False (estado real
        del artefacto) devuelve False. Sin el termino 'not
        P9_ANCHORS_RATIFIED' de la guarda (mutante b) el caso False dejaria
        de distinguirse y este test caeria. monkeypatch restaura las
        constantes al terminar.
        """
        monkeypatch.setattr(hook, "P9_ANNOUNCE_ANCHORS", (r"\bahora hago\b",))
        monkeypatch.setattr(hook, "P9_EXECUTION_ANCHORS", (r"\btermine\b",))
        anuncia_sin_ejecutar = "ahora hago X y luego verifico"
        monkeypatch.setattr(hook, "P9_ANCHORS_RATIFIED", False)
        assert hook.p9_announces_without_acting(anuncia_sin_ejecutar) is False
        monkeypatch.setattr(hook, "P9_ANCHORS_RATIFIED", True)
        assert hook.p9_announces_without_acting(anuncia_sin_ejecutar) is True
        # La ancla de ejecucion veta el aviso aunque el flag este True.
        assert (
            hook.p9_announces_without_acting("ahora hago X, termine lo otro") is False
        )
