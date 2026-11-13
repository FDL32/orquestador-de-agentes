#!/usr/bin/env python3
r"""Census destination settings drift and emit a non-blocking WARN.

Before (Pre-condiciones):
    - ``project_root`` (motor checkout) is resolvable from ``cwd`` or CLI.
    - The gate script is in the motor and reads destination settings statically.

During (Proceso y Recursos):
    - Census destinations on every execution using D2 root precedence
      (CLI > ``AGENT_DESTINOS_ROOT`` > default), independent of git diff.
    - Run the sole destination subprocess gate for each existing settings file,
      count violation lines, and inspect workflows statically for CI coverage.

After (Post-condiciones y Errores):
    - Always print the census denominator; empty census and unreadable links are
      fail-visible, never silent.
    - Name each failing destination with problem count, CI status, and resync
      command; healthy destinations are not named.
    - Return rc 0 in all expected cases, including WARNs and internal errors.
      This remains a WARN and never becomes blocking through ``prepush_check``.

The destination is never asked to execute a command or resync itself.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


try:
    try:
        from scripts.prefix_resolver import _read_link
    except ImportError:
        from prefix_resolver import _read_link  # type: ignore[no-redef]
except Exception as _import_exc:  # fail-closed: nothing may escape
    _READ_LINK_IMPORT_FAILURE = f"import: {_import_exc}"

    def _read_link(link_path: Path) -> tuple[dict | None, str | None]:
        """Report that the link reader could not be imported."""
        return None, _READ_LINK_IMPORT_FAILURE


_GATE_SCRIPT = "scripts/check_claude_settings_portability.py"


def _try_root(path_str: str) -> Path | None:
    """Resolve a path string; return Path if dir exists, else None."""
    try:
        path = Path(path_str).resolve()
        return path if path.is_dir() else None
    except (OSError, ValueError):
        return None


def resolve_destino_roots(
    cli_roots: list[str] | None,
    env_value: str | None,
    motor_checkout_root: Path,
) -> list[Path]:
    """Resolve roots using D2 precedence: CLI, env, then motor parent."""
    if cli_roots:
        roots = [_try_root(value) for value in cli_roots]
        valid = [root for root in roots if root is not None]
        if valid:
            return valid

    if env_value:
        roots = [_try_root(part.strip()) for part in env_value.split(os.pathsep)]
        valid = [root for root in roots if root is not None]
        if valid:
            return valid

    default = motor_checkout_root.parent
    return [default] if default.is_dir() else []


def discover_destinos(
    roots: Sequence[Path],
) -> tuple[list[Path], list[str]]:
    """Discover linked destinations and expose unreadable links as problems."""
    destinos: list[Path] = []
    problemas: list[str] = []
    for root in roots:
        try:
            worktrees = sorted(root.glob("*"))
        except OSError:
            problemas.append(f"raiz {root}: acceso denegado o inexistente")
            continue
        for worktree_dir in worktrees:
            if not worktree_dir.is_dir():
                continue
            json_path = (
                worktree_dir / ".agent" / "config" / "motor_destination_link.json"
            )
            if not json_path.exists():
                continue
            data, reason = _read_link(json_path)
            if data is None:
                problemas.append(f"{json_path}: JSON invalido o ilegible ({reason})")
                continue
            try:
                destination = data.get("destination_root")
                destination_path = Path(destination) if destination else None
                if destination_path is not None and destination_path.is_dir():
                    destinos.append(destination_path)
                else:
                    problemas.append(
                        f"{json_path}: destination_root ausente o no es directorio"
                    )
            except (OSError, TypeError, ValueError) as exc:
                problemas.append(f"{json_path}: JSON invalido o ilegible ({exc})")
    return destinos, problemas


def _ci_has_gate(destination: Path) -> bool:
    """Return whether a destination workflow references the portability gate."""
    workflows = destination / ".github" / "workflows"
    try:
        candidates = list(workflows.glob("*.yml")) + list(workflows.glob("*.yaml"))
    except OSError:
        return False

    def workflow_has_gate(workflow: Path) -> bool:
        """Read one workflow without allowing an inaccessible file to escape."""
        try:
            return "check_claude_settings_portability.py" in workflow.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return False

    return any(workflow_has_gate(workflow) for workflow in candidates)


def _count_violations(stdout: str) -> int:
    """Count gate violation lines whose stripped form starts with ``- ``."""
    return sum(line.strip().startswith("- ") for line in stdout.splitlines())


def gate_failing_destinos(
    destinos: list[Path],
    gate_script: Path,
) -> tuple[list[tuple[Path, int, str, bool]], int, bool]:
    """Run the real gate for settings files and return failures plus census."""
    fallas: list[tuple[Path, int, str, bool]] = []
    al_dia = 0
    if not gate_script.exists():
        return fallas, al_dia, True

    for destino in destinos:
        settings_path = destino / ".claude" / "settings.json"
        if not settings_path.exists():
            continue
        try:
            result = subprocess.run(  # noqa: S603
                [sys.executable, str(gate_script), str(settings_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                stdout = result.stdout or ""
                violations = _count_violations(stdout) or 1
                first_line = stdout.strip().splitlines()
                summary = (
                    first_line[0]
                    if first_line
                    else f"gate fallo (rc={result.returncode})"
                )
                fallas.append((destino, violations, summary, _ci_has_gate(destino)))
            else:
                al_dia += 1
        except (OSError, subprocess.TimeoutExpired) as exc:
            fallas.append(
                (destino, 1, f"gate NO EJECUTABLE ({exc})", _ci_has_gate(destino))
            )
    return fallas, al_dia, False


def build_warn(
    failing: list[tuple[Path, int, str, bool]],
    census: int,
    healthy: int,
    problemas_links: list[str],
    gate_script_missing: bool = False,
) -> list[str]:
    """Build the always-visible census, warning, and link-problem lines."""
    lines = [
        f"[settings-canonical-drift] censo: {census} destino(s) con "
        ".claude/settings.json evaluados."
    ]
    if census == 0:
        lines.append(
            "[settings-canonical-drift] WARN: censo VACIO (0 destinos evaluables)."
        )
    elif not failing:
        lines.append(
            f"[settings-canonical-drift] OK: {healthy} destino(s) al dia de {census}."
        )
    else:
        lines.append(
            f"[settings-canonical-drift] WARN: {len(failing)} de {census} "
            "destino(s) fallan el gate canonico."
        )
        for destino, count, summary, has_ci in failing:
            ci_status = (
                "CI: con gate en .github/workflows"
                if has_ci
                else "CI: sin gate en .github/workflows"
            )
            lines.append(
                f"AVISO [settings-canonical-drift]: {destino.name} - "
                f"{count} problema(s); {ci_status}; {summary}"
            )
            lines.append(
                "  -> resync: python scripts/install_agent_system.py --sync --dest "
                f"{destino}"
            )
    lines.extend(
        f"[settings-canonical-drift] WARN: link ilegible: {problem}"
        for problem in problemas_links
    )
    if gate_script_missing:
        lines.append(
            "[settings-canonical-drift] WARN: gate script ausente; no hay destinos evaluables."
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Census and report settings drift; return zero because this is a WARN.

    Before: CLI roots and the motor checkout are available or defaultable.
    During: discover linked destinations, run the gate only for static settings
        files, and print census, failures, problem counts, and CI state.
    After: return rc 0 for warnings and convert unexpected errors to a visible
        internal-error line without blocking the caller.
    """
    parser = argparse.ArgumentParser(description="Settings canonical drift census")
    parser.add_argument("--destino-root", action="append", default=None)
    parser.add_argument("--project-root", type=Path, default=None)
    try:
        args = parser.parse_args(argv)
        motor_root = (args.project_root or Path.cwd()).resolve()
        gate_script = motor_root / _GATE_SCRIPT
        roots = resolve_destino_roots(
            args.destino_root,
            os.environ.get("AGENT_DESTINOS_ROOT"),
            motor_root,
        )
        destinos, link_problems = discover_destinos(roots)
        failures, healthy, gate_missing = gate_failing_destinos(destinos, gate_script)
        evaluated = healthy + len(failures)
        for line in build_warn(
            failures, evaluated, healthy, link_problems, gate_missing
        ):
            print(line)
        return 0
    except Exception as exc:
        print(f"[settings-canonical-drift] ERROR INTERNO: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
