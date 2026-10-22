"""Barrier tests end-to-end de scripts/check_override_registry.py (WOT-2026-119a).

Hermeticidad (vector git CEM, misma disciplina que
tests/unit/test_check_cuspide_growth_and_drift.py): cada fixture hace
`git init` en SU PROPIA raiz temporal y verifica que `git rev-parse
--show-toplevel` resuelve a esa misma raiz antes de confiar en nada. El CLI
real se invoca con `--repo-root <fixture>` para que `staged_files()` lea el
repo temporal, nunca el repo real de la sesion.

Cada test ataca UNA de las 4 salvaguardas end-to-end: (a) self-approval,
(b) expiry barrido por el hook, (c) scope estricto, (d) fail-closed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_override_registry.py"
_GIT = shutil.which("git") or "git"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "core.autocrlf", "false")
    probe = _git(root, "rev-parse", "--show-toplevel")
    assert probe.returncode == 0, probe.stderr
    assert Path(probe.stdout.strip()).resolve() == root.resolve(), (
        "walk-up de git alcanzo OTRO repo: el test NO es hermetico"
    )


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))
    return path


def _stage(root: Path, *rels: str) -> None:
    result = _git(root, "add", *rels)
    assert result.returncode == 0, result.stderr


def _valid_override_yaml(override_id: str, scope_path: str, expiry: str) -> str:
    return (
        f"id: {override_id}\n"
        f"scope:\n  - {scope_path}\n"
        f"expiry: {expiry}\n"
        "aprobador: tester\n"
        "justificacion: motivo de prueba no vacio\n"
    )


def _run_cli(root: Path, phase: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--phase",
            phase,
            "--repo-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


# --- Camino silencioso -------------------------------------------------------


def test_no_overrides_directory_is_silent_in_both_phases(tmp_path: Path):
    _init_repo(tmp_path)
    for phase in ("pre-commit", "commit-msg"):
        result = _run_cli(tmp_path, phase)
        assert result.returncode == 0, result.stderr


def test_healthy_override_alone_is_silent_in_both_phases(tmp_path: Path):
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".agent/overrides/ok.yaml",
        _valid_override_yaml("OVERRIDE-OK-001", "scripts/guarded.py", "2099-01-01"),
    )
    _stage(tmp_path, ".agent/overrides/ok.yaml")
    for phase in ("pre-commit", "commit-msg"):
        result = _run_cli(tmp_path, phase)
        assert result.returncode == 0, result.stderr


# --- Salvaguarda (a): anti-auto-aprobacion ----------------------------------


def test_self_approval_same_commit_blocks_at_commit_msg(tmp_path: Path):
    _init_repo(tmp_path)
    _write(tmp_path, "scripts/guarded.py", "x = 1\n")
    _stage(tmp_path, "scripts/guarded.py")
    assert _run_cli(tmp_path, "commit-msg").returncode == 0  # sin override todavia

    _write(
        tmp_path,
        ".agent/overrides/self.yaml",
        _valid_override_yaml("OVERRIDE-SELF-001", "scripts/guarded.py", "2099-01-01"),
    )
    _stage(tmp_path, ".agent/overrides/self.yaml")

    result = _run_cli(tmp_path, "commit-msg")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "self-approval" in (result.stdout + result.stderr).lower()


def test_override_in_prior_commit_then_scoped_change_does_not_violate_self_approval(
    tmp_path: Path,
):
    """Mutation-verify positivo: el override aterrizado ANTES, en su propio
    commit, no dispara (a) cuando luego se stagea el fichero de su scope."""
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".agent/overrides/prior.yaml",
        _valid_override_yaml("OVERRIDE-PRIOR-001", "scripts/guarded.py", "2099-01-01"),
    )
    _stage(tmp_path, ".agent/overrides/prior.yaml")
    commit = _git(tmp_path, "commit", "-q", "-m", "add override")
    assert commit.returncode == 0, commit.stderr

    _write(tmp_path, "scripts/guarded.py", "x = 1\n")
    _stage(tmp_path, "scripts/guarded.py")

    result = _run_cli(tmp_path, "commit-msg")
    assert result.returncode == 0, result.stdout + result.stderr


# --- Salvaguarda (b): expiry barrido por el proceso -------------------------


def test_expired_unarchived_override_warns_precommit_blocks_commitmsg(tmp_path: Path):
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".agent/overrides/stale.yaml",
        _valid_override_yaml("OVERRIDE-STALE-001", "scripts/other.py", "2000-01-01"),
    )
    _stage(tmp_path, ".agent/overrides/stale.yaml")

    warn = _run_cli(tmp_path, "pre-commit")
    assert warn.returncode == 0, warn.stderr
    assert "expiro" in (warn.stdout + warn.stderr).lower()

    gate = _run_cli(tmp_path, "commit-msg")
    assert gate.returncode == 1, gate.stdout + gate.stderr
    assert "expiro" in (gate.stdout + gate.stderr).lower()


def test_expired_override_moved_to_archive_no_longer_blocks(tmp_path: Path):
    """Mutation-verify positivo de (b): archivar el override vencido lo saca
    del censo activo y el commit-msg vuelve a estar limpio."""
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".agent/overrides/stale.yaml",
        _valid_override_yaml("OVERRIDE-STALE-002", "scripts/other.py", "2000-01-01"),
    )
    _stage(tmp_path, ".agent/overrides/stale.yaml")
    assert _run_cli(tmp_path, "commit-msg").returncode == 1

    archived = tmp_path / ".agent" / "overrides" / "_archive" / "stale.yaml"
    archived.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".agent" / "overrides" / "stale.yaml").rename(archived)
    _stage(tmp_path, ".")

    result = _run_cli(tmp_path, "commit-msg")
    assert result.returncode == 0, result.stdout + result.stderr


# --- Salvaguarda (c): scope estricto, verificado contra el guard real ------


def test_misscoped_override_does_not_flag_unrelated_file_as_violation(tmp_path: Path):
    """(c) acoplado a (a): un scope mal especificado (demasiado estrecho) NO
    debe casar fuera de su alcance -- staged un fichero FUERA del scope junto
    al override no es self-approval."""
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".agent/overrides/narrow.yaml",
        _valid_override_yaml(
            "OVERRIDE-NARROW-001", "scripts/exact_target.py", "2099-01-01"
        ),
    )
    _write(tmp_path, "scripts/exact_target_other.py", "x = 1\n")
    _stage(tmp_path, ".agent/overrides/narrow.yaml", "scripts/exact_target_other.py")

    result = _run_cli(tmp_path, "commit-msg")
    assert result.returncode == 0, result.stdout + result.stderr


def test_exact_scoped_file_staged_with_override_is_violation(tmp_path: Path):
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".agent/overrides/narrow.yaml",
        _valid_override_yaml(
            "OVERRIDE-NARROW-002", "scripts/exact_target.py", "2099-01-01"
        ),
    )
    _write(tmp_path, "scripts/exact_target.py", "x = 1\n")
    _stage(tmp_path, ".agent/overrides/narrow.yaml", "scripts/exact_target.py")

    result = _run_cli(tmp_path, "commit-msg")
    assert result.returncode == 1, result.stdout + result.stderr


# --- Salvaguarda (d): fail-closed -------------------------------------------


def test_corrupt_yaml_fixture_fails_closed_in_both_phases(tmp_path: Path):
    _init_repo(tmp_path)
    _write(tmp_path, ".agent/overrides/corrupt.yaml", "id: [unterminated\n:::\n")
    _stage(tmp_path, ".agent/overrides/corrupt.yaml")

    for phase in ("pre-commit", "commit-msg"):
        result = _run_cli(tmp_path, phase)
        assert result.returncode == 1, (phase, result.stdout + result.stderr)
        assert "FAIL-CLOSED" in (result.stdout + result.stderr)


def test_missing_field_yaml_fixture_fails_closed(tmp_path: Path):
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".agent/overrides/incomplete.yaml",
        "id: OVERRIDE-INCOMPLETE\nscope:\n  - scripts/x.py\n",
    )
    _stage(tmp_path, ".agent/overrides/incomplete.yaml")

    result = _run_cli(tmp_path, "commit-msg")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL-CLOSED" in (result.stdout + result.stderr)


def test_one_corrupt_override_blocks_even_though_another_is_healthy(tmp_path: Path):
    """(d) no se limita al fichero tocado por el commit: TODO el registro
    activo se valida, asi que un override corrupto YA existente bloquea un
    commit que ni lo toca."""
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".agent/overrides/ok.yaml",
        _valid_override_yaml("OVERRIDE-OK-002", "scripts/guarded.py", "2099-01-01"),
    )
    _write(tmp_path, ".agent/overrides/corrupt.yaml", "id: [unterminated\n:::\n")
    _stage(tmp_path, ".agent/overrides/ok.yaml", ".agent/overrides/corrupt.yaml")
    commit = _git(tmp_path, "commit", "-q", "-m", "seed both overrides")
    assert commit.returncode == 0, commit.stderr

    _write(tmp_path, "unrelated.py", "x = 1\n")
    _stage(tmp_path, "unrelated.py")

    result = _run_cli(tmp_path, "commit-msg")
    assert result.returncode == 1, result.stdout + result.stderr
