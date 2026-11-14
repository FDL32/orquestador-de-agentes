"""Before: identify every tracked check guard and load its declaration.

During: validate the declarative policy, safely execute declared hermetic probes,
and publish denominators even when a validation error occurs.

After: return zero only when the measured universe is fully declared and every
probe passed; diagnostics explain the failure, reproduction, and re-validation.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


CLASSES = {"no_denominator", "fixed_denominator", "staged_files", "external_targets"}
SKIP_VALUES = {"si", "no", "desconocido"}
PREPARATIONS = {"git-init", "mkdir"}
FLOWS = {"stdout", "stderr", "both"}
MARKER = "[guard-denominator]"


def _universe(root: Path) -> list[str]:
    """Before: receive a motor root that should be a Git checkout.

    During: measure both tracked check-script globs with Git, without shell
    interpretation, and merge their normalized paths.

    After: return sorted relative POSIX paths, or raise a self-service error.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "scripts/check_*.py", "scripts/**/check_*.py"],  # noqa: S607
            cwd=root,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(
            f"cannot measure check_*.py with git ({exc}); reproduce with git ls-files "
            "scripts/check_*.py scripts/**/check_*.py from the motor root"
        ) from exc
    if result.returncode:
        raise RuntimeError(
            f"git ls-files failed rc={result.returncode}: {result.stderr.strip()}; "
            "run the same command from --motor-root and revalidate"
        )
    return sorted(
        {line.replace("\\", "/") for line in result.stdout.splitlines() if line}
    )


def _load_policy(path: Path) -> dict[str, Any]:
    """Before: receive the declared YAML path.

    During: parse it as a mapping and enforce the top-level schema boundary.

    After: return the parsed mapping; malformed or unreadable input fails closed.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(
            f"policy is absent or unreadable: {path} ({exc}); fix YAML and rerun "
            "python scripts/check_guard_denominator_policy.py"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError("policy must be a YAML mapping with version and guards")
    return data


def _render(token: str, root: Path, tmpdir: Path) -> str:
    return (
        token.replace("{python}", sys.executable)
        .replace("{root}", str(root))
        .replace("{tmpdir}", str(tmpdir))
    )


def _validate_probe(  # noqa: C901
    probe: Any, root: Path, tmpdir: Path
) -> tuple[list[str], Path, int, str]:
    """Before: receive one untrusted declarative probe.

    During: enforce the closed command, path, preparation, cwd, flow, and
    timeout contracts before any subprocess is started.

    After: return a safe argv, cwd, timeout, and selected output flow.
    """
    if not isinstance(probe, dict):
        raise RuntimeError("probe must be a mapping")
    command = probe.get("comando")
    if not isinstance(command, list) or not command or command[0] != "{python}":
        raise RuntimeError(
            "probe comando[0] must be exactly {python}; no probe executed"
        )
    if any(not isinstance(token, str) for token in command):
        raise RuntimeError("probe command tokens must be strings; no probe executed")
    cwd_token = probe.get("cwd")
    if cwd_token not in ("{tmpdir}",) and not (
        isinstance(cwd_token, str) and cwd_token.startswith("{tmpdir}/")
    ):
        raise RuntimeError(
            "probe cwd must be {tmpdir} or its subdirectory; no probe executed"
        )
    cwd = Path(_render(cwd_token, root, tmpdir)).resolve()
    if tmpdir.resolve() not in (cwd, *cwd.parents):
        raise RuntimeError("probe cwd escapes tmpdir; no probe executed")
    preparations = probe.get("preparacion", [])
    if not isinstance(preparations, list) or any(
        item not in PREPARATIONS for item in preparations
    ):
        raise RuntimeError(
            "probe preparacion contains an unsupported action; no probe executed"
        )
    timeout = probe.get("timeout_s")
    if (
        not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or not 1 <= timeout <= 300
    ):
        raise RuntimeError(
            "probe timeout_s must be an integer from 1 to 300; no probe executed"
        )
    flow = probe.get("flujo")
    if flow not in FLOWS:
        raise RuntimeError(
            "probe flujo must be stdout, stderr, or both; no probe executed"
        )
    marker = probe.get("marcador")
    if not isinstance(marker, str) or not marker:
        raise RuntimeError(
            "probe marcador must be a non-empty string; no probe executed"
        )
    argv = [_render(token, root, tmpdir) for token in command]
    script = Path(argv[1]).resolve() if len(argv) > 1 else Path()
    scripts_root = (root / "scripts").resolve()
    if (
        len(argv) < 2
        or script.suffix != ".py"
        or scripts_root not in (script, *script.parents)
    ):
        raise RuntimeError(
            "probe script must be a .py inside <root>/scripts; no probe executed"
        )
    for token in command[2:]:
        if token.startswith("{") and token.endswith("}"):
            continue
        rendered = Path(_render(token, root, tmpdir))
        if rendered.suffix.lower() in {".exe", ".bat", ".cmd", ".ps1", ".py"}:
            resolved = rendered.resolve()
            if scripts_root not in (
                resolved,
                *resolved.parents,
            ) and tmpdir.resolve() not in (
                resolved,
                *resolved.parents,
            ):
                raise RuntimeError(
                    "probe token references an executable outside allowed roots"
                )
    return argv, cwd, timeout, flow


def _run_probe(probe: dict[str, Any], root: Path, counter: list[int]) -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="guard-denominator-"))
    try:
        argv, cwd, timeout, flow = _validate_probe(probe, root, tmpdir)
        for action in probe.get("preparacion", []):
            if action == "git-init":
                subprocess.run(
                    ["git", "init"],  # noqa: S607
                    cwd=tmpdir,
                    shell=False,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            elif action == "mkdir":
                cwd.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(  # noqa: S603
            argv,
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        counter[0] += 1
        output = (
            result.stdout
            if flow == "stdout"
            else result.stderr
            if flow == "stderr"
            else result.stdout + result.stderr
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"probe crashed rc={result.returncode}: {output.strip()}"
            )
        if probe["marcador"] not in output:
            raise RuntimeError(
                f"probe marker {probe['marcador']!r} absent from declared {flow}; "
                "check stdout/stderr flow and rerun"
            )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"probe timed out after {probe.get('timeout_s')}s: {exc}"
        ) from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"probe preparation/execution failed: {exc}") from exc
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    """Before: parse motor and policy paths.

    During: measure, validate declarations, execute declared probes in fresh
    temporary directories, and publish N/M/P/S before the final verdict.

    After: return 0 for a complete declaration and successful probes, otherwise
    return 1 with instructions to reproduce and re-run the meta-check.
    """
    parser = argparse.ArgumentParser(
        description="Validate declarative guard denominator policy."
    )
    parser.add_argument(
        "--motor-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="accepted for topology callers; never written",
    )
    args = parser.parse_args(argv)
    root = args.motor_root.resolve()
    policy_path = (
        args.policy or root / "scripts" / "guard_denominator_policy.yaml"
    ).resolve()
    universe: list[str] = []
    entries = 0
    probes = [0]
    skipped = 0
    errors: list[str] = []
    try:
        universe = _universe(root)
        data = _load_policy(policy_path)
        if data.get("version") != 1:
            errors.append("policy version must be 1")
        guards = data.get("guards")
        if not isinstance(guards, dict):
            errors.append("policy guards must be a mapping")
            guards = {}
        entries = len(guards)
        errors.extend(
            f"guard without policy entry: {path}"
            for path in universe
            if path not in guards
        )
        errors.extend(
            f"stale policy entry: {path}"
            for path in guards
            if not (root / path).is_file()
        )
        for path, declaration in guards.items():
            if (
                not isinstance(declaration, dict)
                or declaration.get("clase") not in CLASSES
            ):
                errors.append(f"invalid or absent class for {path}")
            if (
                not isinstance(declaration, dict)
                or declaration.get("skip_explicito") not in SKIP_VALUES
            ):
                errors.append(
                    f"invalid or absent skip_explicito for {path}: expected one of "
                    "si, no, desconocido; add the field and re-run"
                )
            if isinstance(declaration, dict) and declaration.get("probe") is not None:
                try:
                    _run_probe(declaration["probe"], root, probes)
                except RuntimeError as exc:
                    errors.append(f"{path}: {exc}")
            else:
                skipped += 1
        if not universe:
            print(
                f"{MARKER} N check_*.py auditados=0, M entradas={entries}, P probes ejecutados={probes[0]}, S saltados={skipped}"
            )
            print(f"{MARKER} SKIP EXPLICITO: universo vacio. No es un PASS.")
            return 0
    except RuntimeError as exc:
        errors.append(str(exc))
    print(
        f"{MARKER} N check_*.py auditados={len(universe)}, M entradas={entries}, P probes ejecutados={probes[0]}, S saltados={skipped}"
    )
    if errors:
        for error in errors:
            print(f"{MARKER} FAIL: {error}", file=sys.stderr)
        return 1
    print(f"{MARKER} OK: policy completa y probes validos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
