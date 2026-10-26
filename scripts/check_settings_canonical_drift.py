#!/usr/bin/env python3
r"""Settings canonical drift check - prepush WARN for hook drift (WOT-2026-129l).

Before (Pre-condiciones):
    - ``project_root`` (motor checkout) resoluble desde ``cwd`` o CLI.
    - ``gate_script`` apunta a ``scripts/check_claude_settings_portability.py``
      del motor (lectura estatica, nunca ejecuta comandos de destino).

During (Proceso y Recursos):
    - Lee ``git diff --name-only origin/main...HEAD`` en el motor.
    - Si el diff toca ``.agent/hooks/claude_guard_entry.py`` o
      ``scripts/check_claude_settings_portability.py``: dispara evaluacion.
    - Barredo universos de destino desde raices canonicas (D2: cli > env > default).
    - Por cada destino resoluble: corre el gate contra su ``settings.json``.
    - Compose aviso NOMBRADO con destinos fallidos + comando de resync.

After (Post-condiciones y Errores):
    - Imprime bloque ``[settings-canonical-drift] WARN ...`` si hay alertas.
    - Declara universo vacio, links ilegibles, diff indeterminado (fail-visible).
    - **rc 0 siempre** (salvo error interno del script): es un WARN, nunca bloquea.
    - Nunca lanza excepcion no capturada al cliente (prepush_check envuelve en
      try/except amplio con `is_blocking=False`).

NOTA: En topologia de worktrees, el default (`parents[1].parent`) puede no
alcanzar el destino activo y que el remedio es `--destino-root` o la env
`AGENT_DESTINOS_ROOT`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


# Trigger: ficheros cuya modificacion puede alterar comandos canonicos de hooks.
TRIGGER_PATHS: frozenset[str] = frozenset(
    {
        ".agent/hooks/claude_guard_entry.py",
        "scripts/check_claude_settings_portability.py",
    }
)

# Ruta al gate que valida settings.json por destino.
_GATE_SCRIPT = "scripts/check_claude_settings_portability.py"


def touched_paths(project_root: Path) -> tuple[list[str], str | None]:
    """`git diff --name-only origin/main...HEAD` en project_root.

    Returns (paths, motive) donde motive != None declara indeterminado
    (sin origin/main, git fallo) -> fail-visible (D4).
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main...HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_root),
        )
        if result.returncode != 0:
            # origin/main no existe o git fallo -> indeterminado
            return [], "no origin/main disponible (diff indeterminado)"
        paths = [p for p in result.stdout.strip().splitlines() if p]
        return paths, None
    except subprocess.TimeoutExpired:
        return [], "timeout ejecutando git diff (indeterminado)"
    except OSError:
        return [], "git no disponible (indeterminado)"


def is_trigger(touched: Sequence[str]) -> bool:
    """True si alguna ruta normalizada esta en TRIGGER_PATHS."""
    touched_set = {Path(p).as_posix() for p in touched}
    return bool(touched_set & TRIGGER_PATHS)


def _try_root(path_str: str) -> Path | None:
    """Resolve a path string; return Path if dir exists, else None."""
    try:
        p = Path(path_str).resolve()
        return p if p.is_dir() else None
    except (OSError, ValueError):
        return None


def resolve_destino_roots(
    cli_roots: list[str] | None,
    env_value: str | None,
    motor_checkout_root: Path,
) -> list[Path]:
    """D2: cli > AGENT_DESTINOS_ROOT (os.pathsep) > padre del checkout.

    Devuelve lista NO vacia de Path, o lista vacia si nada resuelve.
    """
    # 1. CLI --destino-root (repetible)
    if cli_roots:
        roots = [_try_root(r) for r in cli_roots]
        valid = [r for r in roots if r is not None]
        if valid:
            return valid

    # 2. Env AGENT_DESTINOS_ROOT (separada por os.pathsep)
    if env_value:
        roots = []
        for part in env_value.split(os.pathsep):
            p = _try_root(part.strip())
            if p is not None:
                roots.append(p)
        if roots:
            return roots

    # 3. Default: padre del checkout del motor (topologia worktrees)
    default = motor_checkout_root.parent
    if default.is_dir():
        return [default]

    return []


def discover_destinos(
    roots: Sequence[Path],
) -> tuple[list[Path], list[str]]:
    """Barredo <root>/*/.agent/config/motor_destination_link.json.

    Returns (destinos_resolubles, problemas) - problemas declara links
    ilegibles/JSON invalido (DoD 3); nunca excepcion no capturada.
    """
    destinos: list[Path] = []
    problemas: list[str] = []

    for root in roots:
        try:
            # Buscar <root>/*/ (carpetas worktree) y luego verificar el JSON dentro
            for worktree_dir in sorted(root.glob("*")):
                if not worktree_dir.is_dir():
                    continue
                json_path = (
                    worktree_dir / ".agent" / "config" / "motor_destination_link.json"
                )
                if not json_path.exists():
                    continue
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    dest_path = data.get("destination_root")
                    if dest_path and Path(dest_path).is_dir():
                        destinos.append(Path(dest_path))
                    else:
                        problemas.append(
                            f"{json_path}: destination_root ausente o no es directorio"
                        )
                except (json.JSONDecodeError, OSError) as exc:
                    problemas.append(f"{json_path}: JSON invalido o ilegible ({exc})")
        except OSError:
            problemas.append(f"raiz {root}: acceso denegado o inexistente")

    return destinos, problemas


def gate_failing_destinos(
    destinos: list[Path],
    gate_script: Path,
) -> tuple[list[tuple[Path, str]], int, bool]:
    """Por destino con settings.json: gate -> falla si rc!=0.

    Args:
        destinos: lista de raices de destino (repo_destino).
        gate_script: ruta absoluta al script de gate del motor.

    Returns:
        (fallas, al_dia, gate_script_missing) donde fallas =
        [(destino, resumen_linea), ...], al_dia = conteo de destinos que
        pasaron el gate, y gate_script_missing = True si el gate script
        no existe (fall-visible, no bloquea).
    """
    fallas: list[tuple[Path, str]] = []
    al_dia: int = 0

    if not gate_script.exists():
        return fallas, al_dia, True

    for dest in destinos:
        settings_path = dest / ".claude" / "settings.json"
        if not settings_path.exists():
            continue  # sin settings -> no se puede evaluar, no se cuenta

        try:
            result = subprocess.run(  # noqa: S603
                [sys.executable, str(gate_script), str(settings_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                # Tomar la primera linea del stdout como resumen
                stdout_lines = (result.stdout or "").strip().splitlines()
                summary = (
                    stdout_lines[0]
                    if stdout_lines
                    else f"gate fallo (rc={result.returncode})"
                )
                fallas.append((dest, summary))
            else:
                al_dia += 1
        except (subprocess.TimeoutExpired, OSError):
            fallas.append((dest, "gate NO EJECUTABLE (timeout/OSError)"))

    return fallas, al_dia, False


def build_warn(
    failing: list[tuple[Path, str]],
    al_dia: int,
    universo_vacio: bool,
    problemas_links: list[str],
    diff_indeterminado: str | None,
    gate_script_missing: bool = False,
) -> tuple[str, list[str]]:
    """Compone el bloque NOMBRADO.

    Returns (cabecera, lineas_destino) donde cabecera incluye el tag
    [settings-canonical-drift] WARN y lineas_destino son las lineas de
    detalle por destino (en rojo).
    """
    lines: list[str] = []

    if universo_vacio:
        lines.append(
            "AVISO [settings-canonical-drift] (WOT-2026-129l): "
            "diff toca trigger canonico, pero universo de destinos vacio."
        )
        if diff_indeterminado:
            lines.append(
                f"AVISO [settings-canonical-drift] (WOT-2026-129l): "
                f"diff indeterminado: {diff_indeterminado}"
            )
        return "\n".join(lines), []

    # Detalles por destino fallido
    for dest, resumen in failing:
        dest_name = dest.name if dest.name else str(dest)
        lines.append(
            f"AVISO [settings-canonical-drift] (WOT-2026-129l): "
            f"{dest_name} - {resumen}\n"
            f"  -> re-sync: python scripts/install_agent_system.py --sync --dest {dest}"
        )

    cabecera_parts: list[str] = [
        f"[settings-canonical-drift] WARN (WOT-2026-129l): "
        f"{len(failing)} destino(s) con settings.json NO pasa el gate canonico "
        f"tras cambio en trigger."
    ]

    if al_dia > 0:
        cabecera_parts.append(f"{al_dia} destino(s) al dia.")

    if problemas_links:
        cabecera_parts.extend(f"  link ilegitimo: {p}" for p in problemas_links[:5])
        if len(problemas_links) > 5:
            cabecera_parts.append(
                f"  ... y {len(problemas_links) - 5} problemas de link mas omitidos."
            )

    if diff_indeterminado:
        cabecera_parts.append(f"  diff indeterminado: {diff_indeterminado}")

    if gate_script_missing:
        cabecera_parts.append(
            "  gate script ausente: no se pudo evaluar ningun destino"
        )

    return "\n".join(cabecera_parts), lines


def main(argv: list[str] | None = None) -> int:
    """rc 0 siempre salvo error interno (es un WARN, DoD 3).

    CLI:
        --destino-root: raiz alternativa para buscar destinos (repetible).
        --project-root: raiz del motor (default: cwd).
    """
    parser = argparse.ArgumentParser(
        description="Settings canonical drift check (WOT-2026-129l)"
    )
    parser.add_argument(
        "--destino-root",
        action="append",
        default=None,
        help="Raiz para buscar destinos (repetible).",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Raiz del checkout del motor (default: cwd).",
    )

    try:
        args = parser.parse_args(argv)
        project_root = args.project_root or Path.cwd()
        motor_checkout_root = project_root.resolve()

        # Resolver gate script
        gate_script = motor_checkout_root / _GATE_SCRIPT

        # Paso 1: touched_paths (coste minimo primero)
        touched, diff_motive = touched_paths(motor_checkout_root)

        # Paso 2: decidir dispara/no-dispara ANTES de tocar universo/gate
        # (a) motive (indeterminado) -> procede a evaluar/declarar (D4)
        # (b) not motive and not is_trigger -> return 0 SILENCIOSO (coste cero)
        # (c) trigger -> evalua universo/gate y declara todo (C1 fix)
        if not diff_motive and not is_trigger(touched):
            return 0

        # Paso 3: resolver universo de destinos (solo si trigger o indeterminado)
        destino_roots = resolve_destino_roots(
            args.destino_root,
            os.environ.get("AGENT_DESTINOS_ROOT"),
            motor_checkout_root,
        )

        if not destino_roots:
            # Universo vacio declarado (fail-visible)
            header, _ = build_warn([], 0, True, [], diff_motive, False)
            print(header)
            return 0

        destinos, problemas_links = discover_destinos(destino_roots)

        # Si no hay destinos resolubles y no hay problemas, universo vacio
        if not destinos and not problemas_links:
            header, _ = build_warn([], 0, True, [], diff_motive, False)
            print(header)
            return 0

        # Paso 4: ejecutar gate contra cada destino (siempre que haya destinos)
        fallas, al_dia, gate_missing = gate_failing_destinos(destinos, gate_script)

        # Paso 5: componer y emitir aviso
        if not is_trigger(touched):
            # No es trigger, pero diff_motive existe (indeterminado) o problemas_links
            header, _ = build_warn(
                [], 0, False, problemas_links, diff_motive, gate_missing
            )
            print(header)
            return 0

        if fallas:
            # Hay destinos fallidos -> imprimir aviso completo
            header, details = build_warn(
                fallas, al_dia, False, problemas_links, diff_motive, gate_missing
            )
            print(header)
            for d in details:
                print(d)
        elif problemas_links or diff_motive:
            # Solo problemas de link o diff indeterminado -> declarar
            header, _ = build_warn(
                [], 0, False, problemas_links, diff_motive, gate_missing
            )
            print(header)
        elif al_dia > 0:
            # Al menos algunos destinos al dia -> mensaje OK
            print(
                f"[settings-canonical-drift] OK (WOT-2026-129l): "
                f"{al_dia} destino(s) al dia tras cambio en trigger."
            )
        else:
            # Trigger positivo, sin destinos, sin problemas, sin al dia
            header, _ = build_warn([], 0, True, [], diff_motive, gate_missing)
            print(header)

        return 0

    except Exception as exc:
        # Error interno: declarar pero no bloquear
        print(f"[settings-canonical-drift] ERROR INTERNO (WOT-2026-129l): {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
