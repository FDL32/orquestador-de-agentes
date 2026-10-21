#!/usr/bin/env python
"""Create the worktree pair for a session (motor + destino with shared suffix).

WOT-2026-104f/104g: the pair must share the SAME suffix so that
``git worktree list`` on either repo identifies the session at a glance.
``motor_destination_link.json`` must use forward slashes (``.as_posix()``),
never backslashes.

Before: primary checkouts of motor_repo and destino_repo exist and are valid
    git repos. No worktrees with the target suffix exist yet.
During: creates motor worktree, destino worktree, writes the link with
    forward-slash paths, runs ``uv sync --frozen`` on the motor worktree,
    and optionally verifies with ``collect_session_state.py``.
After: pair exists, link is coherent, or an error diagnostic with
    repair instructions is printed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


THIS_SCRIPT_DIR = Path(__file__).resolve().parent


def is_git_repo(path: Path) -> bool:
    """True if ``<path>/.git`` exists (dir or file) and
    ``git -C path rev-parse --is-inside-work-tree`` succeeds."""
    if not (path / ".git").exists():
        return False
    try:
        subprocess.run(  # noqa: S603
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],  # noqa: S607
            capture_output=True,
            check=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def worktree_paths(
    motor_repo: Path, destino_repo: Path, suffix: str, worktrees_root: Path
) -> tuple[Path, Path]:
    """Return ``(motor_worktree, destino_worktree)`` using the WOT-2026-104f
    convention: ``worktrees_root/<repo.name>/<suffix>`` for each."""
    motor_wt = worktrees_root / motor_repo.name / suffix
    destino_wt = worktrees_root / destino_repo.name / suffix
    return (motor_wt, destino_wt)


def classify_pair_state(motor_worktree: Path, destino_worktree: Path) -> str:
    """Return one of:

    - ``"absent"``: neither exists.
    - ``"complete"``: both exist AND the link in destino points exactly to
      ``motor_worktree.as_posix()`` and ``destino_worktree.as_posix()``.
    - ``"partial"``: any other combination (only one exists, link missing/mismatch,
      or one directory exists but is not a valid git worktree of its repo).
    """
    motor_exists = motor_worktree.exists()
    destino_exists = destino_worktree.exists()

    if not motor_exists and not destino_exists:
        return "absent"

    if motor_exists and destino_exists:
        link_file = (
            destino_worktree / ".agent" / "config" / "motor_destination_link.json"
        )
        if not link_file.exists():
            return "partial"
        try:
            link_data = json.loads(link_file.read_text(encoding="utf-8"))
            motor_root = link_data.get("motor_root", "")
            dest_root = link_data.get("destination_root", "")
            if (
                motor_root == motor_worktree.as_posix()
                and dest_root == destino_worktree.as_posix()
            ):
                return "complete"
        except (OSError, ValueError, KeyError):
            pass
        return "partial"

    # Only one exists
    return "partial"


def git_worktree_add(repo: Path, worktree: Path, branch: str, dry_run: bool) -> None:
    """``git -C repo worktree add -b <branch> <worktree>``. If the branch
    already exists (git fails with 'already exists'), retries without ``-b``:
    ``git -C repo worktree add <worktree> <branch>``. Propagates
    ``CalledProcessError`` on any other failure."""
    if dry_run:
        print(f"[DRY-RUN] haria: git worktree add -b {branch} {worktree} (en {repo})")
        return

    # Try with -b first (create new branch)
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(worktree)],  # noqa: S607
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 and "already exists" in (result.stderr or ""):
        # Branch exists, retry without -b (use existing branch)
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), "worktree", "add", str(worktree), branch],  # noqa: S607
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )


def write_link(destino_worktree: Path, motor_worktree: Path, dry_run: bool) -> None:
    """Write ``<destino_worktree>/.agent/config/motor_destination_link.json``
    with forward-slash paths using ``.as_posix()``. ``motor_sha`` is
    best-effort (``'unknown'`` if not resolvable)."""
    # Best-effort: resolve motor_sha from motor_worktree
    motor_sha = "unknown"
    if not dry_run:
        try:
            sha_result = subprocess.run(  # noqa: S603
                ["git", "-C", str(motor_worktree), "rev-parse", "HEAD"],  # noqa: S607
                capture_output=True,
                text=True,
            )
            if sha_result.returncode == 0 and sha_result.stdout.strip():
                motor_sha = sha_result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            motor_sha = "unknown"

    payload = {
        "motor_root": motor_worktree.as_posix(),
        "destination_root": destino_worktree.as_posix(),
        "motor_sha": motor_sha,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        print(
            f"[DRY-RUN] Would write motor-destination link: {destino_worktree}/.agent/config/motor_destination_link.json"
        )
        print(f"[DRY-RUN] Link payload: {json.dumps(payload, indent=2)}")
        return

    config_dir = destino_worktree / ".agent" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    link_file = config_dir / "motor_destination_link.json"
    link_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[INFO] Wrote motor-destination link: {link_file}")


def run_uv_sync(motor_worktree: Path, uv_bin: list[str], dry_run: bool) -> int:
    """``subprocess.run([*uv_bin, 'sync', '--frozen'], cwd=motor_worktree)``.
    Returns the returncode (never swallows or converts to exception)."""
    if dry_run:
        print(
            f"[DRY-RUN] haria: {' '.join([*uv_bin, 'sync', '--frozen'])} (en {motor_worktree})"
        )
        return 0

    result = subprocess.run(  # noqa: S603
        [*uv_bin, "sync", "--frozen"],
        cwd=str(motor_worktree),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"[WARN] uv sync returned {result.returncode}: {' '.join([*uv_bin, 'sync', '--frozen'])}"
        )
        if result.stderr:
            print(f"[WARN] stderr: {result.stderr.strip()}")
    return result.returncode


def run_verify(destino_worktree: Path) -> int:
    """``subprocess.run([sys.executable, collect_session_state.py,
    '--project-root', destino_worktree])``. Returns the returncode.
    This is a collector, not a gate: its returncode does not abort main()."""
    script_path = THIS_SCRIPT_DIR / "collect_session_state.py"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(script_path), "--project-root", str(destino_worktree)],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    """Orchestrate: validate preconditions -> calculate paths -> classify state ->
    dispatch (absent: create all; complete: no-op; partial: diagnostic + exit 1)."""
    ap = argparse.ArgumentParser(
        description=(
            "Create the worktree pair for a session (motor + destino with "
            "shared suffix, WOT-2026-104f/104g)."
        )
    )
    ap.add_argument(
        "--motor-repo",
        required=True,
        help="Primary checkout of the motor repo (git worktree add source).",
    )
    ap.add_argument(
        "--destino-repo",
        required=True,
        help="Primary checkout of the destination repo.",
    )
    ap.add_argument(
        "--suffix",
        required=True,
        help="Shared suffix (session name), e.g. 'FDL32-mi-sesion-20261021'.",
    )
    ap.add_argument(
        "--owner",
        required=True,
        help="Branch prefix for the motor worktree: '<owner>/<suffix>'.",
    )
    ap.add_argument(
        "--destino-branch",
        default=None,
        help="Optional branch override for the destino worktree.",
    )
    ap.add_argument(
        "--worktrees-root",
        default=None,
        help="Root for worktree directories (default: ~/.t3/worktrees).",
    )
    ap.add_argument(
        "--uv-bin",
        default=None,
        dest="uv_bin",
        help="uv binary or command (default: 'uv'). Tests can pass a fake.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print actions without executing any real writes.",
    )

    args = ap.parse_args(argv)

    motor_repo = Path(args.motor_repo).resolve()
    destino_repo = Path(args.destino_repo).resolve()
    suffix = args.suffix
    owner = args.owner
    destino_branch = args.destino_branch or f"{owner}/{suffix}"
    worktrees_root = (
        Path(args.worktrees_root).resolve()
        if args.worktrees_root
        else Path.home() / ".t3" / "worktrees"
    )
    uv_bin_raw = args.uv_bin or "uv"
    uv_bin: list[str] = (
        uv_bin_raw.split() if isinstance(uv_bin_raw, str) else [uv_bin_raw]
    )
    dry_run = args.dry_run

    # Step 1: Validate preconditions
    if not is_git_repo(motor_repo):
        print(
            f"ERROR: {motor_repo} no es un checkout git valido. "
            f"Asegurate de que {motor_repo} es un repositorio git.",
            file=sys.stderr,
        )
        return 1
    if not is_git_repo(destino_repo):
        print(
            f"ERROR: {destino_repo} no es un checkout git valido. "
            f"Asegurate de que {destino_repo} es un repositorio git.",
            file=sys.stderr,
        )
        return 1

    # Step 2: Calculate worktree paths
    motor_worktree, destino_worktree = worktree_paths(
        motor_repo, destino_repo, suffix, worktrees_root
    )

    # Step 3: Classify pair state
    state = classify_pair_state(motor_worktree, destino_worktree)

    if state == "complete":
        print(
            f"[create-worktree-pair] Par ya existe y es coherente: "
            f"{motor_worktree}, {destino_worktree}"
        )
        return 0

    if state == "partial":
        _print_partial_diagnostic(
            motor_worktree, destino_worktree, motor_repo, destino_repo
        )
        return 1

    # state == "absent" — create the pair
    # Step 4: Create motor worktree
    print(f"[INFO] Creating motor worktree: {motor_worktree}")
    try:
        git_worktree_add(motor_repo, motor_worktree, f"{owner}/{suffix}", dry_run)
    except subprocess.CalledProcessError as exc:
        print(
            f"ERROR: No se pudo crear el worktree del motor: {exc.stderr or exc}".strip(),
            file=sys.stderr,
        )
        return 1

    # Step 5: Create destino worktree
    print(f"[INFO] Creating destino worktree: {destino_worktree}")
    try:
        git_worktree_add(destino_repo, destino_worktree, destino_branch, dry_run)
    except subprocess.CalledProcessError as exc:
        print(
            f"ERROR: No se pudo crear el worktree de destino: {exc.stderr or exc}".strip(),
            file=sys.stderr,
        )
        return 1

    # Step 6: Write link
    write_link(destino_worktree, motor_worktree, dry_run)

    uv_sync_failed = False

    # Step 7: Run uv sync (if not dry-run)
    if uv_bin:
        uv_rc = run_uv_sync(motor_worktree, uv_bin, dry_run)
        if uv_rc != 0:
            uv_sync_failed = True
            print(
                f"[WARN] uv sync falló con rc={uv_rc} (comando: "
                f"{' '.join([*uv_bin, 'sync', '--frozen'])}). "
                f"Los worktrees se crearon; el trabajo previo es util pero "
                f"el entorno puede necesitar reparacion manual.",
                file=sys.stderr,
            )
            # Fall through to verify — uv failure does not undo worktrees
        else:
            print("[INFO] uv sync completed successfully.")

    # Step 8: Verify (collector only, does not abort)
    print("\n[INFO] Running verification (collect_session_state.py):")
    run_verify(destino_worktree)

    # Step 9: Summary
    print(
        f"\n[INFO] worktree pair creado:\n"
        f"  Motor:      {motor_worktree}\n"
        f"  Destino:    {destino_worktree}\n"
        f"  Link:       {destino_worktree}/.agent/config/motor_destination_link.json"
    )
    return 1 if uv_sync_failed else 0


def _print_partial_diagnostic(
    motor_worktree: Path,
    destino_worktree: Path,
    motor_repo: Path,
    destino_repo: Path,
) -> None:
    """Print specific diagnostic for a partial/Incoherent pair state."""
    motor_exists = motor_worktree.exists()
    destino_exists = destino_worktree.exists()

    if motor_exists and not destino_exists:
        owner_suffix = motor_worktree.parts[-1] if motor_worktree.parts else "unknown"
        print(
            f"[ERROR] Par parcial: falta el worktree de destino en {destino_worktree}. "
            f"El worktree del motor existe en {motor_worktree}.\n"
            f"Reparacion:\n"
            f"  Opcion 1: Crear el worktree de destino con:\n"
            f"    git -C {destino_repo} worktree add -b {owner_suffix} {destino_worktree}\n"
            f"  Opcion 2: Borrar el worktree del motor y volver a correr este script:\n"
            f"    rm -rf {motor_worktree}\n"
            f"    {sys.argv[0]} ..."
        )
        return

    if not motor_exists and destino_exists:
        print(
            f"[ERROR] Par parcial: falta el worktree del motor en {motor_worktree}. "
            f"El worktree de destino existe en {destino_worktree}.\n"
            f"Reparacion:\n"
            f"  Borrar el worktree de destino y volver a correr este script:\n"
            f"    rm -rf {destino_worktree}\n"
            f"    {sys.argv[0]} ..."
        )
        return

    # Both exist — check link coherence
    link_file = destino_worktree / ".agent" / "config" / "motor_destination_link.json"
    if not link_file.exists():
        print(
            f"[ERROR] Par parcial: el link en {link_file} no existe.\n"
            f"Reparacion: vuelve a correr este script para recrearlo."
        )
        return

    try:
        link_data = json.loads(link_file.read_text(encoding="utf-8"))
        stored_motor = link_data.get("motor_root", "")
        expected = motor_worktree.as_posix()
        if stored_motor != expected:
            print(
                f"[ERROR] Par parcial: el link en {link_file} apunta a "
                f"{stored_motor} pero se esperaba {expected}.\n"
                f"Reparacion:\n"
                f"  Corrige el motor_root a mano, o borra el fichero y vuelve "
                f"a correr este script:\n"
                f"    rm {link_file}\n"
                f"    {sys.argv[0]} ..."
            )
            return
    except (OSError, ValueError):
        print(
            f"[ERROR] Par parcial: no se pudo leer el link en {link_file}.\n"
            f"Reparacion: borra el fichero y vuelve a correr este script."
        )
        return

    # Check if directories are valid git worktrees
    if motor_exists and not is_git_repo(motor_worktree):
        print(
            f"[ERROR] Par parcial: {motor_worktree} existe pero no es un worktree "
            f"git valido de {motor_repo}. El sufijo puede estar usado por otra cosa.\n"
            f"Reparacion: elige otro --suffix o libera esa ruta."
        )
        return

    if destino_exists and not is_git_repo(destino_worktree):
        print(
            f"[ERROR] Par parcial: {destino_worktree} existe pero no es un worktree "
            f"git valido de {destino_repo}. El sufijo puede estar usado por otra cosa.\n"
            f"Reparacion: elige otro --suffix o libera esa ruta."
        )
        return

    # Fallback: both exist but link coherence check failed
    print(
        f"[ERROR] Par parcial: ambos worktrees existen pero la coherencia falla. "
        f"Revisa el link:\n"
        f"  {link_file}\n"
        f"Reparacion: borra el link y vuelve a correr este script."
    )


if __name__ == "__main__":
    raise SystemExit(main())
