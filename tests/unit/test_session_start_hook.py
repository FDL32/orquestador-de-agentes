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

import json
import subprocess
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent.parent
_HOOK = _ROOT / ".agent" / "hooks" / "session_start_hook.py"


def _run(payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        cwd=str(cwd),
    )


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
