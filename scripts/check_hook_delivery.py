#!/usr/bin/env python3
"""Guard (WARN): la memoria que emite el hook SessionStart LLEGA al modelo en Claude Code.

Que protege
-----------
Diseno v6 (2026-10-23), P0. Durante meses `session_start_hook.py` emitio
`{"additionalContext": ...}` en la RAIZ del JSON, y Claude Code solo lee
`hookSpecificOutput.additionalContext`. Censo de transcripts: 577 ejecuciones
`hook_success` en 219 sesiones y CERO `hook_additional_context`. El emisor
funcionaba; el CONSUMIDOR descartaba el contenido. Un log del emisor habria
dicho "todo bien" (E3 de la propuesta): solo el lado del consumidor -- el
transcript -- prueba la entrega.

Que mide
--------
En los transcripts de Claude Code (`<config>/projects/*/*.jsonl`, `config` =
`CLAUDE_CONFIG_DIR` o `~/.claude`) de sesiones cuyo `cwd` registrado cae bajo
``--project-root`` y POSTERIORES a la ultima modificacion del hook, busca un
attachment `{"type": "hook_additional_context", "content": [str, ...]}` que
contenga el marcador del indice (`MEMORY_INDEX_OPEN`) y la seccion M4/M5.

- Filtra por `attachment.type`, no por `hookName`: el attachment de contexto
  NO nombra el hook que lo produjo, y `content` es una LISTA.
- Casa por el `cwd` registrado en el transcript, no por el slug del directorio
  ni por el mtime "mas reciente": hay transcripts concurrentes (subagentes,
  otras sesiones) en el mismo directorio y slugs distintos para subdirectorios.

ALCANCE DECLARADO
-----------------
Solo Claude Code (el unico backend con hook SessionStart en este motor). Para
backends sin hook (Codex, Kilo, OpenCode) el detector de entrega es la
comprobacion por PRESENCIA que ordena AGENTS.md ("si tu contexto no trae el
bloque delimitado del indice de memoria, ejecuta --bootstrap"). El formato del
transcript no esta documentado: el guard distingue "no hay transcript que
juzgar" (SKIP) de "hay sesiones y ninguna recibio el indice" (WARN), y nunca
bloquea.

Before: ``--project-root`` existe; el hook vive en el motor.
During: solo lectura de transcripts (los `_MAX_TRANSCRIPTS` mas recientes) y
    un `git log` de solo lectura para fechar el hook; sin red, sin escrituras.
    Una sesion cuenta si su `hook_success` es POSTERIOR al ultimo commit del hook.
After: imprime una linea ``OK:``/``WARN:``/``SKIP:``; exit 0 siempre (exit 2
    solo por error de uso).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_HOOK = _MOTOR_ROOT / ".agent" / "hooks" / "session_start_hook.py"

# Duplicado a proposito de `bus.memory_loader.MEMORY_INDEX_OPEN` (este guard no
# importa `bus/` para poder correr sin el entorno del motor); un test fija que
# ambos coinciden.
MEMORY_INDEX_MARKER = "<memory-index readonly>"
M4_M5_MARKER = "M4/M5"


def _norm(path: str | Path) -> str:
    """Ruta comparable: separadores `/`, sin barra final, minusculas en Windows."""
    text = str(path).replace("\\", "/").rstrip("/")
    return text.lower() if os.name == "nt" else text


def _config_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


#: Transcripts revisados como maximo (los mas recientes por mtime). Acota el
#: coste en pre-push: `~/.claude/projects` medido en 2,8 GB (ronda 5, sonnet).
_MAX_TRANSCRIPTS = 200


def _line_epoch(line: str) -> float | None:
    """Epoch del campo `timestamp` de una linea de transcript, o ``None``.

    ``None`` (no legible) NO es "antiguo" (ronda 6, sonnet): con 0.0 la sesion
    contaba como no ejecutada y el detector se callaba (SKIP) justo cuando no
    podia leer la fecha.
    """
    try:
        stamp = json.loads(line).get("timestamp")
        if isinstance(stamp, str) and stamp:
            return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        pass
    return None


def _hook_since(hook: Path) -> float:
    """Momento desde el que el hook vigente existe: su ultimo commit, o su mtime.

    El mtime es el del CHECKOUT, no el del cambio (ronda 5, sonnet); el commit
    es la referencia correcta cuando git esta disponible.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - git con argumentos fijos
            [  # noqa: S607 - `git` por PATH, como el resto de guards del motor
                "git",
                "-C",
                str(hook.parent),
                "log",
                "-1",
                "--format=%ct",
                "--",
                hook.name,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip().isdigit():
            return float(proc.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return hook.stat().st_mtime if hook.is_file() else 0.0


def _scan_transcript(  # noqa: C901 - un recorrido por linea con 3 detectores; partirlo releeria el fichero
    path: Path, root: str, since: float = 0.0
) -> tuple[bool, bool, bool]:
    """``(es_de_este_root, hook_de_memoria_corrio, indice_entregado)``."""
    belongs = ran = delivered = False
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not belongs and '"cwd"' in line:
                    try:
                        cwd = json.loads(line).get("cwd")
                    except ValueError:
                        cwd = None
                    if isinstance(cwd, str):
                        ncwd = _norm(cwd)
                        if ncwd != root and not ncwd.startswith(root + "/"):
                            return False, False, False
                        belongs = True
                if (
                    not ran
                    and '"hook_success"' in line
                    and "session_start_hook" in line
                ):
                    # Cuenta solo si ESTE arranque es posterior al hook vigente
                    # (ronda 5, sonnet): una sesion abierta con el hook viejo y
                    # escrita despues no es un fallo de entrega del nuevo.
                    # Sin fecha legible manda el criterio del transcript: el
                    # prefiltro de `evaluate` ya exige mtime >= since.
                    epoch = _line_epoch(line)
                    ran = epoch is None or epoch >= since
                if '"hook_additional_context"' not in line:
                    continue
                try:
                    attachment = json.loads(line).get("attachment") or {}
                except ValueError:
                    continue
                if attachment.get("type") != "hook_additional_context":
                    continue
                content = attachment.get("content")
                chunks = content if isinstance(content, list) else [content]
                text = "\n".join(str(c) for c in chunks if c)
                if MEMORY_INDEX_MARKER in text and M4_M5_MARKER in text:
                    delivered = True
                    break
    except OSError:
        return False, False, False
    return belongs, ran, delivered


def _tally(
    stamped: list[tuple[float, Path]], root: str, since: float
) -> tuple[int, int, int]:
    """``(sesiones, con_hook, con_entrega)`` de este root, como maximo `_MAX_TRANSCRIPTS`.

    El tope cuenta sesiones DE ESTE ROOT (ronda 6, kilo): aplicado antes del
    filtro, las sesiones de otros proyectos podian dejar fuera una entrega
    real. Descartar una ajena es barato: `_scan_transcript` corta en su primera
    linea con `cwd`.
    """
    sessions = ran_count = delivered_count = 0
    for _mtime, transcript in stamped:
        if sessions >= _MAX_TRANSCRIPTS:
            break
        belongs, ran, delivered = _scan_transcript(transcript, root, since)
        if not belongs:
            continue
        sessions += 1
        ran_count += ran
        delivered_count += delivered
    return sessions, ran_count, delivered_count


def evaluate(
    project_root: Path,
    config_dir: Path | None = None,
    hook_path: Path | None = None,
) -> tuple[str, str]:
    """``(estado, mensaje)`` con estado en ``OK``/``WARN``/``SKIP``. Nunca lanza."""
    try:
        config = config_dir or _config_dir(None)
        projects = config / "projects"
        if not projects.is_dir():
            return "SKIP", f"no hay transcripts de Claude Code en {projects}"
        hook = hook_path or _DEFAULT_HOOK
        since = _hook_since(hook)
        root = _norm(project_root.resolve())

        stamped: list[tuple[float, Path]] = []
        for transcript in projects.glob("*/*.jsonl"):
            try:
                mtime = transcript.stat().st_mtime
            except OSError:
                continue
            if mtime >= since:  # prefiltro barato: no se escribio tras el hook
                stamped.append((mtime, transcript))
        stamped.sort(reverse=True)

        sessions, ran_count, delivered_count = _tally(stamped, root, since)

        if delivered_count:
            return (
                "OK",
                f"indice de memoria entregado en {delivered_count}/{sessions} "
                "sesion(es) posteriores al hook",
            )
        if not ran_count:
            return (
                "SKIP",
                f"{sessions} sesion(es) de este root posteriores al hook, ninguna "
                "con el hook de memoria ejecutado: nada que juzgar todavia",
            )
        return (
            "WARN",
            f"el hook de memoria corrio en {ran_count} sesion(es) de este root y "
            "NINGUNA recibio el indice como contexto (hook_additional_context "
            "sin el marcador del indice): revisa el esquema de salida del hook "
            "(hookSpecificOutput.additionalContext) y el tope de 10k chars",
        )
    except Exception as exc:  # fail-open: un detector WARN nunca rompe el cierre
        return "SKIP", f"no verificable ({type(exc).__name__}: {exc})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--hook", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.project_root.is_dir():
        print(f"ERROR: --project-root no existe: {args.project_root}", file=sys.stderr)
        return 2
    status, message = evaluate(
        args.project_root,
        _config_dir(str(args.config_dir) if args.config_dir else None),
        args.hook,
    )
    print(f"{status}: {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
