"""WOT-2026-057b: el hook de SessionStart convierte la NORMA en BARRERA.

Contexto. El prompt de arranque dice que expandir la memoria con `--recall`
"NO es opcional", pero por la propia definicion de este repo eso es una NORMA:
*"Citarlo en un prompt, una skill o este AGENTS.md no es cableado: es una
norma, y una norma depende de que alguien se acuerde"*. Medido en el bucle
L914: `--recall` llevaba COMENTADO en el prompt de bootstrap sin que nadie lo
notara, y la memoria solo entraba automaticamente en `PreCompact` -- es decir,
cuando la sesion ya se estaba quedando sin contexto, nunca al empezar.

Este hook es el mecanismo que faltaba: inyecta el indice de memoria al ABRIR
sesion, sin depender de que el agente ejecute nada.

POLITICA DE FALLO -- fail-OPEN, y es deliberado (objecion BA12-H7 del bucle
L914): un `SessionStart` que fallase cerrado ante un archive corrupto impediria
arrancar *la sesion que vendria a arreglarlo*. Deadlock autoinfligido. Hereda la
politica que `_read_portable_archive` ya declara: degradar el contexto, nunca
romper al llamante. La barrera fail-CLOSED para un archive corrupto es
`validate_observations --strict`, cableada en prepush.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parent.parent.parent
_HOOK = _ROOT / ".agent" / "hooks" / "session_start_hook.py"


def _hook_module():
    """Carga el hook como modulo importable (in-process) para monkeypatch."""
    spec = importlib.util.spec_from_file_location("ssh_hook_wot_100a", _HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_stdin_bytes(monkeypatch, payload: bytes) -> None:
    """Sustituye `sys.stdin` por uno con `.buffer.read()` que devuelve payload."""

    class _Buffer:
        def read(self, *_args, **_kwargs) -> bytes:
            return payload

    class _Stdin:
        buffer = _Buffer()

    monkeypatch.setattr(sys, "stdin", _Stdin())


def _run(payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        cwd=str(cwd),
    )


RAYA = "\u2014"


def _settings_hook_code(event: str) -> str:
    """Codigo del comando REAL de `settings.json` para un evento de hook.

    WOT-2026-110a. El DoD exige ejecutar "el comando REAL", y el comando real
    es el wrapper `python -c "<code>"` que Claude Code lanza; aqui se extrae
    `<code>` para lanzarlo con el MISMO interprete del test, en vez de
    depender del `python` que resuelva el PATH.
    """
    settings = json.loads(
        (_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    command = settings["hooks"][event][0]["hooks"][0]["command"]
    prefix = 'python -c "'
    assert command.startswith(prefix) and command.endswith('"'), command[:80]
    return command[len(prefix) : -1]


def _run_settings_hook(
    event: str,
    payload: bytes,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Ejecuta el comando REAL del hook con el entorno que reproduce el defecto.

    `PYTHONUTF8` se RETIRA (no se pone a "0"): con `PYTHONUTF8=1` el hijo
    emitiria UTF-8 valido y el fallo dejaria de ser el medido en produccion
    (bytes invalidos), que es lo que el test debe reproducir. `PYTHONIOENCODING`
    se FUERZA a cp1252 porque esa es la codepage del pipe en Windows y la unica
    forma de que la asercion de UTF-8 estricto muerda por el motivo real.
    """
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp1252"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", _settings_hook_code(event)],
        input=payload,
        capture_output=True,
        cwd=str(cwd),
        env=env,
    )


def _destino_with_em_dash_archive(tmp_path: Path) -> Path:
    """Destino sintetico con una leccion que contiene U+2014.

    Dos piezas obligatorias:

    1. `motor_destination_link.json`: el wrapper de settings resuelve el hook
       contra `<destino>/.agent/hooks/...` y, si no existe, contra
       `motor_root`. Sin link, el wrapper imprime "HOOK INACTIVE" y sale 2.
       Se escribe con forward slashes (convencion WOT-2026-104g).
    2. La entrada de archive con U+2014 en `signal`, dentro del tramo que el
       indice no trunca: es el caracter que debe atravesar la serializacion.

    El destino declara UN solo origen local; el loader puede unirlo con el
    archive del motor, y el cupo por origen (`_cap_preserving_origins`)
    garantiza que esta entrada no la expulsa la recencia del motor.
    """
    destino = tmp_path / "destino"
    (destino / ".claude").mkdir(parents=True)
    (destino / ".agent" / "config").mkdir(parents=True)
    (destino / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": _ROOT.as_posix()}, ensure_ascii=False),
        encoding="utf-8",
    )
    archive = destino / ".agent" / "runtime" / "memory" / "archive"
    archive.mkdir(parents=True)
    entry = {
        "timestamp": "2026-05-07T18:45:00Z",
        "topic": "em-dash-wot-110a",
        "signal": f"antes{RAYA}despues",
        "source": "test",
        "category": "convention",
        "confidence": 0.6,
        "applies_to": "all",
    }
    (archive / "observations.2026-07.jsonl").write_text(
        json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return destino


def test_hook_exists_and_is_wired() -> None:
    """El fichero existe Y esta declarado en settings.json.

    Las dos mitades: un hook que existe pero nadie invoca es exactamente la
    "norma disfrazada de barrera" que este ticket cierra.
    """
    assert _HOOK.exists(), f"falta el hook: {_HOOK}"
    settings = json.loads(
        (_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert "SessionStart" in settings.get("hooks", {}), (
        "el hook existe pero NADIE lo invoca: sigue siendo una norma"
    )
    wired = json.dumps(settings["hooks"]["SessionStart"])
    assert "session_start_hook.py" in wired


def test_hook_emits_memory_context(tmp_path: Path) -> None:
    """DoD: el hook inyecta el indice de memoria en additionalContext."""
    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, _ROOT)

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[:400]
    payload = json.loads(result.stdout.decode("utf-8", "replace"))
    ctx = payload.get("additionalContext", "")
    assert "Portable Memory" in ctx or "memory_context.py" in ctx, (
        "el hook no inyecta memoria: su unica razon de ser"
    )


def test_hook_fails_open_on_broken_memory(tmp_path: Path) -> None:
    """BARRERA INVERSA: con la memoria rota, el hook NO bloquea la sesion.

    Es la mitad que mas importa. Un `SessionStart` fail-CLOSED ante un archive
    corrupto impide abrir la sesion que vendria a repararlo.

    MUTACION ALCANZABLE: hacer que el hook propague la excepcion (o devuelva
    exit 2 como los guards de escritura) -> este test cae.
    """
    roto = tmp_path / "destino_roto"
    (roto / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    (
        roto
        / ".agent"
        / "runtime"
        / "memory"
        / "archive"
        / "observations.2026-07.jsonl"
    ).write_text("{ esto no es json valido\n", encoding="utf-8")
    (roto / ".claude").mkdir()

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, roto)

    assert result.returncode == 0, (
        "el hook fallo CERRADO con la memoria rota: eso impide abrir la sesion "
        "que vendria a arreglarla -- deadlock autoinfligido"
    )
    # No basta el rc: el `except` de ultimo recurso del `__main__` lo mantiene
    # en 0 aunque `_load_context` propague, asi que `rc == 0` a secas es un
    # FLOOR ASSERTION -- medido, la mutacion fail-closed lo dejaba verde. El
    # discriminante es que el hook siga ENTREGANDO la puerta de expansion: ese
    # texto solo se emite por la ruta degradada de `main()`, no por el catch
    # final, que devuelve contexto vacio.
    payload = json.loads(result.stdout.decode("utf-8", "replace"))
    assert "--recall" in payload.get("additionalContext", ""), (
        "el hook degrado hasta perder la instruccion de expansion: un arranque "
        "sin memoria DEBE seguir diciendo como recuperarla"
    )


def test_hook_anchors_memory_at_the_root_it_runs_in(tmp_path: Path) -> None:
    """DoD: el hook ancla la memoria en el root DONDE CORRE, no en el motor.

    Medido en la ruta productiva (2026-08-17): ejecutado desde el destino y sin
    `AGENT_PROJECT_ROOT`, el loader resolvia al MOTOR (207 entradas) en vez de
    al destino (342 = 135 locales + 207 del motor), asi que el indice perdia
    las lecciones locales -- entre ellas las de topologia motor/destino, que son
    justo las que necesita quien opera alli.

    Es la asimetria INVERSA de D1: alli se perdia el motor, aqui el destino.

    MUTACION ALCANZABLE: quitar el anclaje del root -> el canario local
    desaparece del contexto y el assert cae.
    """
    destino = tmp_path / "destino"
    (destino / ".claude").mkdir(parents=True)
    archive = destino / ".agent" / "runtime" / "memory" / "archive"
    archive.mkdir(parents=True)
    (archive / "observations.2026-07.jsonl").write_text(
        json.dumps(
            {
                "id": "obs-canary-solo-de-este-destino",
                "timestamp": "2026-07-28T00:00:00+00:00",
                "topic": "canario-local",
                "signal": "CANARIO-LOCAL-DEL-DESTINO",
                "source": "test",
                "source_ticket": "WOT-2026-057b",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)

    assert result.returncode == 0
    ctx = json.loads(result.stdout.decode("utf-8", "replace")).get(
        "additionalContext", ""
    )
    assert "CANARIO-LOCAL-DEL-DESTINO" in ctx, (
        "el hook no vio el archive del root donde corre: resolvio a otra raiz y "
        "perdio las lecciones locales"
    )


def test_launcher_is_canonical_and_fails_red_when_absent() -> None:
    """El LANZADOR falla ROJO si el hook no existe; el fail-open vive DENTRO.

    Leccion que costo una suite roja (2026-08-17). La primera version puso el
    fail-open en el lanzador de `settings.json` (`sys.exit(0)` cuando el fichero
    no existia) buscando "que el arranque nunca se bloquee". Confundia dos
    fallos que exigen politicas OPUESTAS:

      - hook AUSENTE     -> instalacion rota   -> rc=2, como todos los demas
      - memoria ILEGIBLE -> degradacion normal -> rc=0, resuelto DENTRO del script

    Con el fail-open en el lanzador, una instalacion rota se veia igual que un
    arranque sano. `check_claude_settings_portability` lo caza por eso: exige el
    bootstrap canonico y prohibe el `exit 0` silencioso.

    MUTACION ALCANZABLE: devolver el comando a `sys.exit(0)` -> cae el assert.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cge", _ROOT / ".agent" / "hooks" / "claude_guard_entry.py"
    )
    cge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cge)

    settings = json.loads(
        (_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    command = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]

    assert command == cge.canonical_command_for(
        "session_start_hook.py", "agent_hooks"
    ), "el lanzador de SessionStart no es el bootstrap canonico"
    assert "sys.exit(2)" in command, (
        "el lanzador sale con 0 cuando el hook no existe: una instalacion rota "
        "queda indistinguible de un arranque sano"
    )


def test_hook_from_the_motor_also_loads_its_dogfooding_workspace(
    tmp_path: Path,
) -> None:
    """DoD: abrir sesion EN EL MOTOR no puede perder la memoria del destino.

    Medido en la ruta productiva (2026-08-17), y es la asimetria INVERSA de D1:

        cwd=DESTINO -> declara 342 | trae lecciones del destino: SI
        cwd=MOTOR   -> declara 207 | trae lecciones del destino: NO

    Un agente que abre sesion en el motor -- el caso normal cuando se programa el
    MOTOR -- perdia las 135 entradas del destino, incluidas las 14 de TOPOLOGIA
    motor/destino que son las unicas que explican donde vive cada cosa. Arreglar
    la ceguera en un sentido y dejarla en el otro no es arreglarla.

    El mecanismo NO se inventa aqui: `.agent/config/motor_workspace.txt` ya
    existe (WOT-2026-053h) y declara el workspace de dogfooding del motor como
    un NOMBRE resuelto contra `parent(motor_root)` -- deliberadamente un nombre y
    no una ruta absoluta, para no pinear la maquina. El hook solo lo LEE.

    MUTACION ALCANZABLE: quitar la lectura de `motor_workspace.txt` -> el canario
    del workspace desaparece y el assert cae.
    """
    motor = tmp_path / "motor_fixture"
    workspace = tmp_path / "workspace_fixture"
    (motor / ".claude").mkdir(parents=True)
    (motor / ".agent" / "config").mkdir(parents=True)
    (motor / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    (workspace / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)

    (motor / ".agent" / "config" / "motor_workspace.txt").write_text(
        "# comentario que el contrato manda saltar\nworkspace_fixture\n",
        encoding="utf-8",
    )
    # El link del workspace hacia su motor: es lo que permite al loader UNIR los
    # dos archives. Un motor real y su workspace de dogfooding siempre lo tienen
    # (lo escribe el instalador); omitirlo haria del fixture un caso imposible.
    (workspace / ".agent" / "config").mkdir(parents=True)
    (workspace / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps(
            {
                "motor_root": str(motor),
                "destination_root": str(workspace),
                "destination_id": "workspace_fixture",
                "ticket_prefix": "WOT",
            }
        ),
        encoding="utf-8",
    )

    def _entry(canary: str, topic: str) -> str:
        return (
            json.dumps(
                {
                    "id": f"obs-{topic}",
                    "timestamp": "2026-07-28T00:00:00+00:00",
                    "topic": topic,
                    "signal": canary,
                    "source": "test",
                    "source_ticket": "WOT-2026-057b",
                }
            )
            + "\n"
        )

    (motor / ".agent/runtime/memory/archive/observations.2026-07.jsonl").write_text(
        _entry("CANARIO-DEL-MOTOR", "solo-motor"), encoding="utf-8"
    )
    (workspace / ".agent/runtime/memory/archive/observations.2026-07.jsonl").write_text(
        _entry("CANARIO-DEL-WORKSPACE", "solo-workspace"), encoding="utf-8"
    )

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, motor)

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[:300]
    ctx = json.loads(result.stdout.decode("utf-8", "replace")).get(
        "additionalContext", ""
    )
    assert "CANARIO-DEL-MOTOR" in ctx, "el hook perdio la memoria del propio motor"
    assert "CANARIO-DEL-WORKSPACE" in ctx, (
        "abriendo en el MOTOR se pierde la memoria del workspace de dogfooding: "
        "es la ceguera de D1 con el signo invertido"
    )


def test_057b_dogfooding_workspace_rejects_paths_and_non_workspaces(
    tmp_path: Path,
) -> None:
    """DoD: el declarante acepta un NOMBRE de workspace, no cualquier directorio.

    Medido en el bucle L917 (BA41): el unico predicado era `is_dir()`, asi que
    aceptaba cualquier cosa que existiera --

        'basura'     -> <tmp>/basura        ACEPTADO (existe, no es workspace)
        '../..'      -> <tmp>/../..         ACEPTADO (traversal)
        'C:/Windows' -> C:/Windows          ACEPTADO (ruta absoluta: en Windows
                                            `Path(a) / 'C:/x'` DESCARTA la izquierda)

    El tercero es el mas probable: el fichero pide un NOMBRE y su propio
    comentario tiene que explicarlo, asi que escribir una ruta es el error de
    tipeo natural. Y el daño no es teorico: `_load_context` hace asignacion
    DIRECTA de `AGENT_PROJECT_ROOT` al ancla, asi que un ancla basura deja al
    agente arrancando SIN memoria -- el fallo que este hook existe para eliminar,
    causado por una linea mal escrita en un fichero que nadie validaba.

    MUTACION ALCANZABLE: volver al `is_dir()` desnudo -> los tres vuelven a
    aceptarse y el test cae.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("h", _HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)

    motor = tmp_path / "motor"
    (motor / ".agent" / "config").mkdir(parents=True)
    (tmp_path / "basura").mkdir()
    decl = motor / ".agent" / "config" / "motor_workspace.txt"

    for nombre in ("basura", "../..", "C:/Windows", "sub/dir", ""):
        decl.write_text(nombre + "\n", encoding="utf-8")
        assert hook._dogfooding_workspace(motor) is None, (
            f"acepto {nombre!r}: el declarante toma un NOMBRE de workspace "
            "hermano, no una ruta ni un directorio cualquiera"
        )

    # CONTROL POSITIVO: un workspace REAL (con `.agent/`) si se acepta. Sin esta
    # mitad, un `return None` incondicional pasaria los asserts de arriba.
    ws = tmp_path / "workspace_real"
    (ws / ".agent").mkdir(parents=True)
    decl.write_text("workspace_real\n", encoding="utf-8")
    assert hook._dogfooding_workspace(motor) == ws


def test_089e_hook_shows_the_memory_health_of_both_roots(tmp_path: Path) -> None:
    """WOT-2026-089e (P0): el arranque muestra el estado de memoria, motor y destino.

    El disparador de la optimizacion de memoria era prosa opcional; este hook es lo
    unico que se ejecuta solo en cada arranque. Un destino sintetico con 600 lineas
    de ruido tiene que aparecer como tal (hermetico respecto al L1 real del motor).

    MUTACION ALCANZABLE: quitar `_health_line` de `main` -> este test cae.
    """
    destino = tmp_path / "destino"
    mem = destino / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    (destino / ".claude").mkdir()
    noise = {
        "topic": "tool_usage",
        "signal": "Tool view_file called",
        "source": "post_tool_hook",
    }
    (mem / "observations.jsonl").write_text(
        "".join(json.dumps(noise) + "\n" for _ in range(600)), encoding="utf-8"
    )

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[:400]
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    assert "Salud de la memoria:" in ctx
    assert "motor: L1" in ctx
    assert "destino: L1 600 entradas (ruido 600)" in ctx
    assert "DISPARA (d)" in ctx
    assert "memory_optimization.md" in ctx


def test_089e_the_health_line_is_fail_open(tmp_path: Path) -> None:
    """Si la medicion no puede ejecutarse, el arranque sigue entregando la memoria.

    Un motor declarado en el link que no tiene `check_memory_health.py` no puede
    romper ni callar el hook: sin linea de salud y con la puerta de expansion.
    """
    destino = tmp_path / "destino"
    (destino / ".agent" / "config").mkdir(parents=True)
    (destino / ".claude").mkdir()
    falso_motor = tmp_path / "motor_sin_scripts"
    falso_motor.mkdir()
    (destino / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(falso_motor)}), encoding="utf-8"
    )

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)

    assert result.returncode == 0
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    assert "--recall" in ctx
    assert "Salud de la memoria" not in ctx


def _destino_health_part(destino: Path) -> str:
    """Tramo `destino: ...` de la linea de salud (hermetico respecto al motor real).

    La linea une las raices con "; " y ningun aviso contiene ";" (lo fija
    `test_layer_warning_never_recommends_a_command_or_the_optimization`).
    """
    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[:400]
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    line = next(ln for ln in ctx.splitlines() if ln.startswith("Salud de la memoria:"))
    return next(p for p in line.split("; ") if "destino:" in p)


def _destino_with_l1(tmp_path: Path) -> Path:
    destino = tmp_path / "destino"
    mem = destino / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    (destino / ".claude").mkdir()
    lesson = {
        "id": "obs-x",
        "topic": "t",
        "signal": "leccion valida larga",
        "source": "s",
    }
    (mem / "observations.jsonl").write_text(json.dumps(lesson) + "\n", encoding="utf-8")
    return destino


def test_layer_warning_reaches_the_cold_agent_when_l2_l3_are_missing(tmp_path) -> None:
    """El aviso de capas llega al contexto de arranque cuando faltan L2/L3.

    MUTACION ALCANZABLE: quitar el bucle `for warning in measure.get("warnings")` de
    `_health_line` -> este test cae.
    """
    part = _destino_health_part(_destino_with_l1(tmp_path))
    assert " - AVISO: " in part
    assert "L2/L3" in part


def test_layer_warning_is_silent_in_the_hook_when_l2_l3_exist(tmp_path) -> None:
    """Control negativo: con L2 y L3 presentes la linea de salud no lleva aviso."""
    destino = _destino_with_l1(tmp_path)
    mem = destino / ".agent" / "runtime" / "memory"
    (mem / "memory_rules.md").write_text("#### R-001\ntexto\n", encoding="utf-8")
    (mem / "memory_profile.md").write_text("# Perfil\n", encoding="utf-8")
    part = _destino_health_part(destino)
    assert "AVISO" not in part
    assert part.startswith("destino: L1 1 entradas")


# --------------------------------------------------------------------------- #
# WOT-2026-098b: la seccion de roles de capa, DESPUES de la memoria, sin romper
# el contrato fail-open del hook. El agente en frio debe poder descubrir el
# backend/modelo de orchestrator/manager/revisor/builder desde el arranque.
# --------------------------------------------------------------------------- #


def _valid_agents_config(with_role_mapping: bool = True) -> dict:
    """agents.json minimo que PASA `load_agents_config` (schema 1.4)."""
    backends = {
        name: {
            "executable": name,
            "args": ["run"],
            "discovery": {"method": "path_only"},
        }
        for name in ("opencode", "nan_api", "claude")
    }
    cfg: dict = {
        "schema_version": "1.4",
        "backends": backends,
        "role_assignments": {"BUILDER": "opencode"},
        "role_models": {
            "BUILDER": "nan/deepseek-v4-flash",
            "MANAGER": None,
            "REVISOR": "nan/glm5.3-flash",
        },
    }
    if with_role_mapping:
        cfg["role_mapping"] = {
            "orchestrator": {"backend": "claude"},
            "manager": {"backend": "opencode", "model": "openai/gpt-5.5"},
            "revisor": {"backend": "nan_api", "model": "nan/glm5.3-flash"},
            "builder": {"backend": "opencode"},
        }
    return cfg


def _destino_with_config(tmp_path: Path, config: dict | None, name: str = "destino"):
    destino = tmp_path / name
    (destino / ".claude").mkdir(parents=True)
    if config is not None:
        cfg_dir = destino / ".agent" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "agents.json").write_text(
            config if isinstance(config, str) else json.dumps(config),
            encoding="utf-8",
        )
    return destino


def test_098b_injects_role_mapping_after_memory(tmp_path: Path) -> None:
    """DoD (c): el hook inyecta el backend/modelo de cada rol de capa, tras la memoria.

    El destino declara `role_mapping` (incluido `revisor`) y el hook debe exponerlo
    resuelto. MUTACION: quitar `_role_section(root)` de `main()` -> no hay bloque
    "Roles del sistema" y el assert cae.
    """
    destino = _destino_with_config(tmp_path, _valid_agents_config())

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[:400]
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    assert "Roles del sistema" in ctx
    assert "revisor: backend=nan_api, modelo=nan/glm5.3-flash" in ctx
    assert "builder: backend=opencode" in ctx
    # DESPUES de la memoria: la puerta de expansion (hint) precede a los roles.
    assert ctx.index("--recall") < ctx.index("Roles del sistema")


def test_098b_omits_section_when_agents_json_absent(tmp_path: Path) -> None:
    """DoD (e): sin `agents.json` el hook sigue en exit 0 con la memoria intacta.

    MUTACION: si la seccion nueva PROPAGARA la excepcion (en vez de capturarla),
    `main()` degradaria al catch final (contexto vacio) y `--recall` desapareceria.
    """
    destino = _destino_with_config(tmp_path, None)

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)

    assert result.returncode == 0
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    assert "--recall" in ctx
    assert "Roles del sistema" not in ctx


def test_098b_omits_section_when_agents_json_corrupt(tmp_path: Path) -> None:
    """DoD (e): JSON invalido -> seccion omitida, arranque y memoria intactos."""
    destino = _destino_with_config(tmp_path, "{ esto no es json valido")

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)

    assert result.returncode == 0
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    assert "--recall" in ctx
    assert "Roles del sistema" not in ctx


def test_098b_omits_section_when_role_mapping_missing(tmp_path: Path) -> None:
    """DoD (e): agents.json valido SIN `role_mapping` -> seccion omitida, exit 0."""
    destino = _destino_with_config(
        tmp_path, _valid_agents_config(with_role_mapping=False)
    )

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)

    assert result.returncode == 0
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    assert "--recall" in ctx
    assert "Roles del sistema" not in ctx


# --------------------------------------------------------------------------- #
# Fase 0 + Via A (M4/M5 integration, 2026-10-15): la norma de invocacion
# "contrato citado => leelo ENTERO antes de actuar" (M4) y "exit code real,
# nunca $? tras un pipe" (M5) vivia SOLO dentro de
# orchestrator_launch_builder.md:327-383, un prompt de Builder que un agente
# operando una herramienta con contrato propio desde chat normal (fuera del
# flujo Builder) nunca carga. Esta seccion la inyecta el hook SIEMPRE, leida
# EN VIVO desde el prompt fuente -- nunca se OMITE como roles/salud, porque
# la norma aplica aunque la lectura falle (cae a su propio fallback).
# --------------------------------------------------------------------------- #


def test_m4_m5_section_present_after_memory_with_live_content(
    tmp_path: Path,
) -> None:
    """DoD (a): el hook inyecta M4/M5, leidos EN VIVO del prompt fuente.

    Sin `motor_destination_link.json`, `_motor_root` cae al motor que aloja
    el propio hook (este repo) -- su `orchestrator_launch_builder.md` real
    SI contiene M4/M5, asi que el contenido debe ser el LITERAL del fichero,
    no el fallback.
    """
    destino = _destino_with_config(tmp_path, None)

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[:400]
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    assert "lectura en vivo de prompts/orchestrator_launch_builder.md" in ctx
    assert "M4. Validador o CONTRATO citado" in ctx
    assert "M5. Exit code REAL" in ctx
    assert "nunca `$?` tras una tuberia" in ctx
    # DESPUES de memoria y de cualquier seccion de roles (aqui ausente).
    assert ctx.index("--recall") < ctx.index("M4. Validador o CONTRATO citado")


def test_m4_m5_section_falls_back_when_source_prompt_absent(
    tmp_path: Path,
) -> None:
    """MUTACION ALCANZABLE: si la lectura en vivo no encuentra el prompt
    fuente (motor_root resuelto apunta a un directorio sin `prompts/`), la
    seccion cae al fallback -- NUNCA se omite, a diferencia de roles/salud.
    """
    destino = tmp_path / "destino"
    (destino / ".claude").mkdir(parents=True)
    (destino / ".agent" / "config").mkdir(parents=True)
    falso_motor = tmp_path / "motor_sin_prompts"
    falso_motor.mkdir()
    (destino / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(falso_motor)}), encoding="utf-8"
    )

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)

    assert result.returncode == 0
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    assert "--recall" in ctx
    assert "Contratos de invocacion (M4/M5)" in ctx
    assert "lectura en vivo" not in ctx
    assert "no resoluble en este arranque" in ctx


def test_m4_m5_section_always_present_even_when_roles_omitted(
    tmp_path: Path,
) -> None:
    """La seccion M4/M5 NUNCA se omite, a diferencia de WOT-2026-098b (roles),
    que si se omite sin `agents.json`. Mismo destino, dos contratos distintos.
    """
    destino = _destino_with_config(tmp_path, None)

    result = _run({"session_id": "t", "hook_event_name": "SessionStart"}, destino)

    assert result.returncode == 0
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    assert "Roles del sistema" not in ctx
    assert "M4. Validador o CONTRATO citado" in ctx


# --------------------------------------------------------------------------- #
# _print_context_safely (encoding hardening, 2026-10-15): un SOLO caracter no
# codificable en la codepage del terminal (medido: Windows cp1252 + una "o"
# cirilica corrupta en observations.2026-07.jsonl) no debe vaciar TODO el
# contexto (memoria + salud + roles + M4/M5) via el fail-open absoluto de
# __main__. Debe degradar el CARACTER, no la sesion entera.
# --------------------------------------------------------------------------- #


def test_print_context_safely_falls_back_on_unencodable_char(
    monkeypatch, capsys
) -> None:
    """La rama de reintento `backslashreplace` sigue cubierta.

    WOT-2026-110a: con `ensure_ascii=True` el payload ya es ASCII, asi que un
    stdout cp1252 real NO fallaria por un caracter no codificable. El fake
    fuerza el `UnicodeEncodeError` para mantener la rama cubierta (el DoD la
    exige conservada); el recorrido de un caracter REAL hasta la salida lo
    prueba `test_real_session_start_command_emits_ascii_with_cp1252_forced`.

    MUTACION ALCANZABLE: quitar el `try/except` de `_print_context_safely` ->
    la excepcion sale del hook y este test cae.
    """
    import importlib
    import sys as _sys

    sys_path_hooks = str(_HOOK.parent)
    if sys_path_hooks not in _sys.path:
        _sys.path.insert(0, sys_path_hooks)
    hook_module = importlib.import_module("session_start_hook")

    class _FakeStdoutBuffer:
        def __init__(self):
            self._written = b""

        def write(self, data):
            self._written += data

    class _FakeStdout:
        encoding = "cp1252"

        def __init__(self):
            self.buffer = _FakeStdoutBuffer()

        def write(self, data):
            # Fuerza el fallo que el contrato exige seguir cubriendo: un
            # stdout cuya codificacion no admite NI el payload escapado.
            raise UnicodeEncodeError(self.encoding, data, 0, 1, "simulado")

        def flush(self):
            pass

    fake_stdout = _FakeStdout()
    monkeypatch.setattr(hook_module.sys, "stdout", fake_stdout)

    # "o" cirilica (U+043E): no representable en cp1252.
    context_with_cyrillic = "texto normal canonic" + "\u043e" + "o mas texto"

    hook_module._print_context_safely(context_with_cyrillic)

    written = fake_stdout.buffer._written
    assert isinstance(written, bytes)
    assert rb"\u043e" in written
    assert b"texto normal canonic" in written
    assert all(byte < 0x80 for byte in written), (
        "la rama de reintento debe emitir ASCII, nunca bytes de la codepage"
    )


def test_print_context_safely_passes_through_ascii_unchanged(capsys) -> None:
    """Control negativo: un contexto puramente ASCII no activa el fallback,
    y `print()` normal funciona (misma ruta que hoy, sin regresion)."""
    import importlib
    import sys as _sys

    sys_path_hooks = str(_HOOK.parent)
    if sys_path_hooks not in _sys.path:
        _sys.path.insert(0, sys_path_hooks)
    hook_module = importlib.import_module("session_start_hook")

    hook_module._print_context_safely("solo texto ascii, nada raro aqui")

    out = capsys.readouterr().out
    assert "solo texto ascii, nada raro aqui" in out


def test_hook_survives_unencodable_memory_entry_end_to_end(
    tmp_path: Path,
) -> None:
    """Integracion real: el hook completo, invocado como subproceso con
    PYTHONIOENCODING=cp1252 (reproduce Windows sin terminal UTF-8), debe
    emitir el contexto completo (memoria + M4/M5) aunque el archive portable
    contenga un caracter no codificable -- NO debe degradar a
    `additionalContext: ""`, que es el bug original medido en produccion.
    """
    import os

    destino = tmp_path / "destino"
    (destino / ".claude").mkdir(parents=True)
    archive_dir = destino / ".agent" / "runtime" / "memory" / "archive"
    archive_dir.mkdir(parents=True)
    corrupt_entry = {
        "timestamp": "2026-05-07T18:45:00Z",
        "topic": "test-entry",
        "signal": "texto con caracter corrupto: canonic" + "\u043e" + "o",
        "source": "test",
        "category": "convention",
        "confidence": 0.6,
        "applies_to": "all",
    }
    (archive_dir / "observations.2026-07.jsonl").write_text(
        json.dumps(corrupt_entry, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps({"session_id": "t", "hook_event_name": "SessionStart"}).encode(
            "utf-8"
        ),
        capture_output=True,
        cwd=str(destino),
        env=env,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[:400]
    ctx = json.loads(result.stdout.decode("utf-8", "replace"))["additionalContext"]
    assert ctx != "", (
        "BUG ORIGINAL: el contexto se vacio por completo por un solo "
        "caracter no codificable -- perdida total de memoria/M4/M5"
    )
    assert "--recall" in ctx
    assert "M4. Validador o CONTRATO citado" in ctx


# WOT-2026-110a (2026-10-21): el hardening de 2026-10-15 reaccionaba al
# UnicodeEncodeError pero SEGUIA emitiendo bytes de la codepage del pipe. Este
# test ejecuta el COMANDO REAL de settings.json con el entorno que reproduce el
# defecto y exige las tres cosas a la vez: ASCII, UTF-8 estricto y caracter
# original tras `json.loads`.


def test_real_session_start_command_emits_ascii_with_cp1252_forced(
    tmp_path: Path,
) -> None:
    """DoD WOT-2026-110a: el comando REAL de SessionStart emite SOLO ASCII.

    Medido 2026-10-21 antes del fix: con cwd=destino, `PYTHONUTF8` retirado y
    `PYTHONIOENCODING=cp1252`, una raya (U+2014) del archive salia como el byte
    0x97 y `stdout.decode("utf-8")` fallaba.

    MUTACION ALCANZABLE: `ensure_ascii=False` en `_print_context_safely` ->
    reaparece el byte 0x97 y caen las tres aserciones.
    """
    destino = _destino_with_em_dash_archive(tmp_path)

    result = _run_settings_hook(
        "SessionStart",
        json.dumps({"session_id": "t", "hook_event_name": "SessionStart"}).encode(
            "utf-8"
        ),
        destino,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[:400]
    raw = result.stdout
    assert all(byte < 0x80 for byte in raw), (
        "el hook emitio bytes no-ASCII: con ensure_ascii=False el JSON sale en "
        f"la codepage del pipe; sospechosos={[b for b in raw if b >= 0x80][:5]}"
    )
    text = raw.decode("utf-8")  # estricto: cualquier 0x97 revienta aqui
    ctx = json.loads(text)["additionalContext"]
    assert "em-dash-wot-110a" in ctx, "la leccion con U+2014 no llego al contexto"
    assert RAYA in ctx, (
        "json.loads debe recuperar el caracter ORIGINAL (U+2014), no un "
        "sustituto: el escape \\uXXXX de ensure_ascii=True es reversible"
    )


# WOT-2026-100a ------------------------------------------------------------
# El hook deja de ignorar el campo `source` del payload: `resume`/`compact`/
# `fork` (sesion que CONTINUA, con historial ya presente) pasan a recibir el
# contexto acotado por recencia (`get_compact_context`), mientras que
# `startup`/`clear` y todo lo ilegible/desconocido conservan el indice completo
# (`get_bootstrap_context`). Fail-open: la deteccion de `source` NUNCA puede
# dejar a una sesion sin memoria.

_BOOTSTRAP_CASES = [
    b"",  # stdin vacio
    b"{}",  # payload sin `source`
    b"not-json",  # payload no-JSON
    b'{"source":"startup"}',
    b'{"source":"clear"}',
    b'{"other":"x"}',  # campo ausente
    b'{"source":"unknown"}',  # valor desconocido
    b'{"source":123}',  # `source` no-string
    b"[1, 2, 3]",  # JSON valido pero no-dict
]
_COMPACT_CASES = [
    b'{"source":"resume"}',
    b'{"source":"compact"}',
    b'{"source":"fork"}',
]


class TestSourceRouting:
    """DoD (2): el `source` del payload decide QUE puerta de memoria se abre."""

    @pytest.mark.parametrize("payload", _BOOTSTRAP_CASES)
    def test_bootstrap_sources_open_the_full_index(
        self, payload, monkeypatch, tmp_path, capsys
    ):
        hook = _hook_module()
        import bus.memory_loader as ml

        calls: list[str] = []
        monkeypatch.setattr(
            ml,
            "get_bootstrap_context",
            lambda: (calls.append("bootstrap"), "BOOTSTRAP-CTX")[1],
        )
        monkeypatch.setattr(
            ml,
            "get_compact_context",
            lambda: (calls.append("compact"), "COMPACT-CTX")[1],
        )
        monkeypatch.setattr(hook, "_health_line", lambda root: "")
        _set_stdin_bytes(monkeypatch, payload)
        monkeypatch.chdir(tmp_path)

        assert hook.main() == 0
        out = json.loads(capsys.readouterr().out)

        assert calls == ["bootstrap"], (
            f"{payload!r}: debe abrir el indice completo (fail-open para "
            "payload ausente/ilegible/desconocido), no la puerta acotada"
        )
        assert "BOOTSTRAP-CTX" in out["additionalContext"]
        assert set(out.keys()) == {"additionalContext"}, (
            "el esquema de salida debe seguir siendo EXACTAMENTE "
            '{"additionalContext": ...}'
        )

    @pytest.mark.parametrize("payload", _COMPACT_CASES)
    def test_continuing_sources_open_the_compact_context(
        self, payload, monkeypatch, tmp_path, capsys
    ):
        hook = _hook_module()
        import bus.memory_loader as ml

        calls: list[str] = []
        monkeypatch.setattr(
            ml,
            "get_bootstrap_context",
            lambda: (calls.append("bootstrap"), "BOOTSTRAP-CTX")[1],
        )
        monkeypatch.setattr(
            ml,
            "get_compact_context",
            lambda: (calls.append("compact"), "COMPACT-CTX")[1],
        )
        monkeypatch.setattr(hook, "_health_line", lambda root: "")
        _set_stdin_bytes(monkeypatch, payload)
        monkeypatch.chdir(tmp_path)

        assert hook.main() == 0
        out = json.loads(capsys.readouterr().out)

        assert calls == ["compact"], (
            f"{payload!r}: una sesion que CONTINUA hereda historial, asi que "
            "debe recibir el contexto acotado, no el indice completo reinyectado"
        )
        assert "COMPACT-CTX" in out["additionalContext"]
        assert set(out.keys()) == {"additionalContext"}

    def test_compact_failure_falls_back_to_full_index(
        self, monkeypatch, tmp_path, capsys
    ):
        """DoD (3, fail-open): si la puerta acotada LANZA, se degrada al indice.

        MUTACION ALCANZABLE: quitar el `except` interno que degrada -> este test
        cae con excepcion en vez de devolver contexto.
        """
        hook = _hook_module()
        import bus.memory_loader as ml

        monkeypatch.setattr(ml, "get_bootstrap_context", lambda: "BOOTSTRAP-CTX")
        monkeypatch.setattr(
            ml,
            "get_compact_context",
            lambda: (_ for _ in ()).throw(RuntimeError("loader roto")),
        )
        monkeypatch.setattr(hook, "_health_line", lambda root: "")
        _set_stdin_bytes(monkeypatch, b'{"source":"resume"}')
        monkeypatch.chdir(tmp_path)

        assert hook.main() == 0
        out = json.loads(capsys.readouterr().out)
        assert "BOOTSTRAP-CTX" in out["additionalContext"], (
            "la deteccion de `source` no puede dejar la sesion sin memoria"
        )

    def test_fail_open_when_the_payload_cannot_be_parsed(
        self, monkeypatch, tmp_path, capsys
    ):
        """DoD (3, MUTATION): `json.loads` lanza al parsear `source`.

        `main()` debe seguir entregando `additionalContext` no vacio via
        `get_bootstrap_context()`, sin propagar y con exit 0. Hoy NO existe el
        guard de fail-open, asi que este test falla ANTES de implementarlo y pasa
        DESPUES.

        MUTACION ALCANZABLE: revertir el guard (dejar que `json.loads` propague
        desde `_read_source`) -> la excepcion sale de `main()` y el test cae.
        """
        hook = _hook_module()
        import bus.memory_loader as ml

        monkeypatch.setattr(ml, "get_bootstrap_context", lambda: "BOOTSTRAP-CTX")
        monkeypatch.setattr(ml, "get_compact_context", lambda: "COMPACT-CTX")
        monkeypatch.setattr(hook, "_health_line", lambda root: "")
        _set_stdin_bytes(monkeypatch, b'{"source":"resume"}')

        class _FakeJson:
            dumps = staticmethod(json.dumps)

            @staticmethod
            def loads(*_args, **_kwargs):
                raise ValueError("payload no parseable")

        monkeypatch.setattr(hook, "json", _FakeJson)
        monkeypatch.chdir(tmp_path)

        assert hook.main() == 0
        out = json.loads(capsys.readouterr().out)
        assert out["additionalContext"], "el contexto no puede quedar vacio"
        assert "BOOTSTRAP-CTX" in out["additionalContext"]
