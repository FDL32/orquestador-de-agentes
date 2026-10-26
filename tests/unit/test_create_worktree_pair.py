"""Tests for create_worktree_pair.py (WOT-2026-110b).

Uses temporary git repos and a fake uv binary to test hermetically.
All tests reuse the _git_init_main + _isolate_git_discovery pattern.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from scripts.create_worktree_pair import (
    is_git_repo,
    main,
)


# Session-scoped short temp dir for bare origins (avoids Windows MAX_PATH).
# Tests that need it: all 8 existing tests + the 4 new tests.
_origin_base: Path | None = None


@pytest.fixture(scope="session", autouse=True)
def _short_origin_base() -> Path:
    """Create one short temp directory shared by all tests for bare origins."""
    global _origin_base
    import tempfile

    td = tempfile.mkdtemp(prefix="kilo_origin_")
    _origin_base = Path(td)
    yield _origin_base
    import shutil

    if _origin_base and _origin_base.exists():
        shutil.rmtree(_origin_base, ignore_errors=True)


def _git_init_main(repo_path: Path, origin_base: Path | None = None) -> None:
    """Init a git repo at repo_path with the branch forced to 'main',
    plus a hermetic bare local ``origin`` remote so that ``origin/main``
    resolves without network.

    ``origin_base`` lets callers override where the bare origin is created;
    on Windows long paths (pytest sandbox) pass a short temp dir to avoid
    MAX_PATH errors.  Defaults to the session-scoped ``_origin_base``
    (a short temp dir) falling back to ``repo_path.parent``.
    """
    if origin_base is None:
        origin_base = _origin_base or repo_path.parent
    unique_suffix = uuid.uuid4().hex[:8]
    origin_path = origin_base / f"{repo_path.name}_{unique_suffix}_origin.git"
    origin_path.mkdir(exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare"],
        cwd=origin_path,
        check=True,
        capture_output=True,
    )
    # 2. Init the real repo and create initial commit
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    # 3. Wire up origin remote, push initial commit to populate the bare repo
    subprocess.run(
        ["git", "-C", str(repo_path), "remote", "add", "origin", str(origin_path)],
        check=True,
        capture_output=True,
    )
    push_result = subprocess.run(
        ["git", "-C", str(repo_path), "push", "-u", "--force", "origin", "main"],
        capture_output=True,
        text=True,
    )
    if push_result.returncode != 0:
        raise RuntimeError(f"git push to origin failed: {push_result.stderr}")
    # Verify origin/main actually resolves
    r = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "origin/main"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"origin/main did not resolve after push: {r.stderr}")


@pytest.fixture(autouse=True)
def _isolate_git_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop git's ambient upward directory-discovery walk at tmp_path."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


def _make_fake_uv(tmp_path: Path, fail: bool = False) -> Path:
    """Create a fake uv script that logs its invocation and exits 0 (or != 0)."""
    fake_uv = tmp_path / "fake_uv.py"
    log_file = tmp_path / "uv_log.txt"
    fake_uv.write_text(
        (
            f"import sys\n"
            f"log = open(r'{log_file}', 'a')\n"
            f"log.write('uv-invoked\\n')\n"
            f"log.close()\n"
            f"sys.exit(1 if '{fail}' == 'True' else 0)\n"
        ),
        encoding="utf-8",
    )
    return fake_uv


def _run_pair(
    motor: Path,
    destino: Path,
    suffix: str,
    worktrees_root: Path,
    uv_bin: list[str],
    extra_args: list[str] | None = None,
    dry_run: bool = False,
) -> tuple[int, str]:
    """Helper to run main() with common args and collect stdout+stderr."""
    argv = [
        "--motor-repo",
        str(motor),
        "--destino-repo",
        str(destino),
        "--suffix",
        suffix,
        "--owner",
        "test-owner",
        "--worktrees-root",
        str(worktrees_root),
        "--uv-bin",
        " ".join(uv_bin),
    ]
    if dry_run:
        argv.append("--dry-run")
    if extra_args:
        argv.extend(extra_args)
    import io
    from contextlib import redirect_stderr, redirect_stdout

    out_buffer = io.StringIO()
    err_buffer = io.StringIO()
    with redirect_stdout(out_buffer), redirect_stderr(err_buffer):
        rc = main(argv)
    combined = out_buffer.getvalue() + err_buffer.getvalue()
    return rc, combined


# -------------------------------------------------------------------
# Test 1: Par ausente -> crea (rc 0)
# -------------------------------------------------------------------
def test_absent_creates_pair(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"
    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path))]

    rc, combined = _run_pair(motor, destino, suffix, worktrees_root, uv_bin)

    assert rc == 0
    motor_wt = worktrees_root / motor.name / suffix
    destino_wt = worktrees_root / destino.name / suffix

    assert motor_wt.exists(), f"Motor worktree should exist: {motor_wt}"
    assert destino_wt.exists(), f"Destino worktree should exist: {destino_wt}"
    assert is_git_repo(motor_wt)
    assert is_git_repo(destino_wt)

    # Link has forward slashes
    link_file = destino_wt / ".agent" / "config" / "motor_destination_link.json"
    assert link_file.exists()
    link_content = link_file.read_text(encoding="utf-8")
    assert "\\" not in link_content, "Link should not contain backslashes"
    link_data = json.loads(link_content)
    assert link_data["motor_root"] == motor_wt.as_posix()
    assert link_data["destination_root"] == destino_wt.as_posix()
    assert "motor_sha" in link_data
    assert link_data["motor_sha"] != "unknown"

    # Fake uv was invoked (log has a line)
    log_file = tmp_path / "uv_log.txt"
    assert log_file.exists(), "Fake uv should have been invoked"
    assert log_file.read_text(encoding="utf-8").strip() == "uv-invoked"

    # Summary lines in output
    assert "creado" in combined.lower()


# -------------------------------------------------------------------
# Test 2: Par completo y coherente -> no-op (rc 0), segunda corrida
# -------------------------------------------------------------------
def test_complete_pair_noop(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"

    # First run: create the pair
    uv_bin1 = [sys.executable, str(_make_fake_uv(tmp_path))]
    _rc1, _combined1 = _run_pair(motor, destino, suffix, worktrees_root, uv_bin1)
    assert _rc1 == 0

    motor_wt = worktrees_root / motor.name / suffix
    destino_wt = worktrees_root / destino.name / suffix
    assert motor_wt.exists()
    assert destino_wt.exists()

    # Second run: should be no-op
    # Create a new fake uv log to verify it's NOT invoked again
    uv_bin2 = [sys.executable, str(_make_fake_uv(tmp_path))]
    rc2, combined2 = _run_pair(motor, destino, suffix, worktrees_root, uv_bin2)
    assert rc2 == 0

    # uv should NOT have been called a second time
    log_file = tmp_path / "uv_log.txt"
    content = log_file.read_text(encoding="utf-8").strip()
    assert content == "uv-invoked", (
        "uv should not have been re-invoked (only once from first run)"
    )

    # Should contain no-op message
    assert (
        "no-op" in combined2.lower()
        or "ya existe" in combined2.lower()
        or "coherente" in combined2.lower()
    )


# -------------------------------------------------------------------
# Test 3: Par parcial (falta el destino) -> rc != 0
# -------------------------------------------------------------------
def test_partial_missing_destino(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"

    # Create only the motor worktree by hand (not via the script)
    motor_wt = worktrees_root / motor.name / suffix
    subprocess.run(
        [
            "git",
            "-C",
            str(motor),
            "worktree",
            "add",
            "-b",
            f"test-owner/{suffix}",
            str(motor_wt),
        ],
        check=True,
        capture_output=True,
    )
    # Do NOT create destino worktree

    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path))]
    rc, combined = _run_pair(motor, destino, suffix, worktrees_root, uv_bin)

    assert rc == 1
    # Motor worktree should still exist (was not deleted)
    assert motor_wt.exists()
    # Should mention repair instructions
    assert (
        "reparacion" in combined.lower()
        or "repar" in combined.lower()
        or "error" in combined.lower()
    )


# -------------------------------------------------------------------
# Test 4: Negativo "destino que no es checkout" (rc == 1)
# -------------------------------------------------------------------
def test_destino_not_git_checkout(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    # destino is a plain directory, NOT a git repo

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"
    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path))]

    rc, combined = _run_pair(motor, destino, suffix, worktrees_root, uv_bin)

    assert rc == 1
    # No worktrees should have been created
    motor_wt = worktrees_root / motor.name / suffix
    destino_wt = worktrees_root / destino.name / suffix
    assert not motor_wt.exists(), (
        "Motor worktree should not exist after precondition failure"
    )
    assert not destino_wt.exists(), (
        "Destino worktree should not exist after precondition failure"
    )
    # Should mention clear error
    assert "error" in combined.lower() or "no es" in combined.lower()


# -------------------------------------------------------------------
# Test 5: Negativo "sufijo ya usado" (dir exists but not a git worktree)
# -------------------------------------------------------------------
def test_suffix_already_used(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"

    # Manually create the destino worktree dir as a plain folder (not a worktree)
    destino_wt = worktrees_root / destino.name / suffix
    destino_wt.mkdir(parents=True)
    (destino_wt / "ocupado.txt").write_text("x", encoding="utf-8")

    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path))]
    rc, combined = _run_pair(motor, destino, suffix, worktrees_root, uv_bin)

    assert rc == 1
    # Should diagnose that the path exists but is not a valid worktree
    assert "exist" in combined.lower() and "worktree" in combined.lower()
    # Should NOT have overwritten the folder
    assert (destino_wt / "ocupado.txt").exists()


# -------------------------------------------------------------------
# Test 6: Negativo "link previo incoherente" (both worktrees exist, link points elsewhere)
# -------------------------------------------------------------------
def test_incoherent_link(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"

    # First run: create the pair successfully
    uv_bin1 = [sys.executable, str(_make_fake_uv(tmp_path))]
    _rc1, _ = _run_pair(motor, destino, suffix, worktrees_root, uv_bin1)
    assert _rc1 == 0

    destino_wt = worktrees_root / destino.name / suffix

    # Now edit the link to point to a wrong motor path
    link_file = destino_wt / ".agent" / "config" / "motor_destination_link.json"
    link_data = json.loads(link_file.read_text(encoding="utf-8"))
    link_data["motor_root"] = "/fake/fake/motor/path/as_posix"
    link_file.write_text(
        json.dumps(link_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Second run: should detect incoherence
    uv_bin2 = [sys.executable, str(_make_fake_uv(tmp_path))]
    rc2, combined2 = _run_pair(motor, destino, suffix, worktrees_root, uv_bin2)

    assert rc2 == 1
    assert (
        "incoher" in combined2.lower()
        or "link" in combined2.lower()
        or "apunta" in combined2.lower()
        or "coherente" in combined2.lower()
    )


# -------------------------------------------------------------------
# Test 7: --dry-run sobre par ausente (rc==0, no crea nada)
# -------------------------------------------------------------------
def test_dry_run_absent(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"
    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path))]

    rc, combined = _run_pair(
        motor, destino, suffix, worktrees_root, uv_bin, dry_run=True
    )

    assert rc == 0
    # No worktrees should exist
    motor_wt = worktrees_root / motor.name / suffix
    destino_wt = worktrees_root / destino.name / suffix
    assert not motor_wt.exists()
    assert not destino_wt.exists()
    # Fake uv should not have been invoked
    log_file = tmp_path / "uv_log.txt"
    assert not log_file.exists(), "Fake uv should not have been called in dry-run"
    # Output should contain [DRY-RUN]
    assert "[DRY-RUN]" in combined


# -------------------------------------------------------------------
# Test 8: Fallo de uv sync no revierte los worktrees creados
# -------------------------------------------------------------------
def test_uv_sync_failure_preserves_worktrees(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"

    # Fake uv that FAILS
    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path, fail=True))]

    rc, combined = _run_pair(motor, destino, suffix, worktrees_root, uv_bin)

    assert rc == 1  # uv sync failure makes main() return 1
    # But worktrees AND link should still exist
    motor_wt = worktrees_root / motor.name / suffix
    destino_wt = worktrees_root / destino.name / suffix
    assert motor_wt.exists(), "Motor worktree should exist despite uv sync failure"
    assert destino_wt.exists(), "Destino worktree should exist despite uv sync failure"
    assert is_git_repo(motor_wt)
    assert is_git_repo(destino_wt)

    link_file = destino_wt / ".agent" / "config" / "motor_destination_link.json"
    assert link_file.exists(), "Link should exist despite uv sync failure"

    # Should mention uv failure in output
    assert "uv" in combined.lower() and (
        "fall" in combined.lower()
        or "warn" in combined.lower()
        or "error" in combined.lower()
    )


# -------------------------------------------------------------------
# Test 9: base-ref usado, no el HEAD del principal
# -------------------------------------------------------------------
def test_base_ref_used_not_principal_head(tmp_path: Path) -> None:
    """origin/main debe ser el punto de partida del worktree, NO el HEAD
    actual del repositorio principal (que puede avanzar tras el clon bare)."""
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    # Avanza el HEAD del principal SIN afectar origin/main
    (motor / "extra.txt").write_text("extra\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(motor), "add", "extra.txt"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(motor), "commit", "-m", "Second commit"],
        check=True,
        capture_output=True,
    )

    # Verificar que origin/main y HEAD difieren en el principal
    origin_head = subprocess.run(
        ["git", "-C", str(motor), "rev-parse", "origin/main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    main_head = subprocess.run(
        ["git", "-C", str(motor), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert origin_head != main_head, "Fixture debe tener origin/main != HEAD"

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"
    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path))]

    rc, combined = _run_pair(
        motor,
        destino,
        suffix,
        worktrees_root,
        uv_bin,
        extra_args=["--base-ref", "origin/main"],
    )

    assert rc == 0, combined
    motor_wt = worktrees_root / motor.name / suffix
    assert motor_wt.exists()

    # El worktree debe nacer en origin/main, NO en el HEAD del principal
    wt_head = subprocess.run(
        ["git", "-C", str(motor_wt), "rev-parse", "HEAD^{commit}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert wt_head == origin_head, (
        f"Worktree debe estar en origin/main ({origin_head}), no en HEAD "
        f"del principal ({main_head})"
    )
    assert wt_head != main_head


# -------------------------------------------------------------------
# Test 10: base-ref inexistente -> error claro, nada parcial
# -------------------------------------------------------------------
def test_base_ref_missing_errors_clearly(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"
    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path))]

    rc, combined = _run_pair(
        motor,
        destino,
        suffix,
        worktrees_root,
        uv_bin,
        extra_args=["--base-ref", "no-existe-nunca"],
    )

    assert rc == 1
    assert "no-existe-nunca" in combined
    # Debe nombrar el repo en el error
    assert motor.name in combined
    # Ningun worktree nuevo
    motor_wt = worktrees_root / motor.name / suffix
    destino_wt = worktrees_root / destino.name / suffix
    assert not motor_wt.exists()
    assert not destino_wt.exists()


# -------------------------------------------------------------------
# Test 11: verify-failure bloquea el mensaje de exito
# -------------------------------------------------------------------
def test_verify_failure_blocks_success_message(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"
    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path))]

    from scripts import create_worktree_pair

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            create_worktree_pair,
            "run_verify",
            lambda _destino: 1,  # type: ignore[assignment]
        )
        rc, combined = _run_pair(
            motor,
            destino,
            suffix,
            worktrees_root,
            uv_bin,
            extra_args=[],
        )

    assert rc == 1  # verify_rc != 0 debe propagar al rc final
    # "worktree pair creado" NO debe aparecer
    assert "worktree pair creado" not in combined
    # Debe haber un mensaje [ERROR] que mencione la verificacion
    assert "[ERROR]" in combined or "verificacion" in combined.lower()


# -------------------------------------------------------------------
# Test 12: dry-run nunca llama al verify real
# -------------------------------------------------------------------
def test_dry_run_never_calls_real_verify(tmp_path: Path) -> None:
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"
    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path))]

    from scripts import create_worktree_pair

    def _verify_raises(_destino: Path) -> int:
        raise AssertionError("run_verify no debio llamarse en dry-run")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(create_worktree_pair, "run_verify", _verify_raises)  # type: ignore[arg-type]
        rc, combined = _run_pair(
            motor,
            destino,
            suffix,
            worktrees_root,
            uv_bin,
            extra_args=["--base-ref", "main"],  # ref local, sin red
            dry_run=True,
        )

    assert rc == 0
    # "worktree pair creado" (sin prefijo DRY-RUN) NO aparece
    assert "worktree pair creado" not in combined
    assert "[DRY-RUN]" in combined


# -------------------------------------------------------------------
# Test 13: fetch real falla pero origin/main sigue resuelto localmente (stale)
# -------------------------------------------------------------------
def test_fetch_failure_warns_on_stale_ref(tmp_path: Path) -> None:
    """fetch falla (remoto roto) pero origin/main sigue resolviendo localmente;
    debe imprimirse [WARN] y el par se crea igual (rc==0)."""
    motor = tmp_path / "motor_primary"
    destino = tmp_path / "destino_primary"
    motor.mkdir()
    destino.mkdir()
    _git_init_main(motor)
    _git_init_main(destino)

    # Romper el remoto: apuntar a una ruta que no existe
    subprocess.run(
        ["git", "-C", str(motor), "remote", "set-url", "origin", "/no/existe/ruta"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(destino), "remote", "set-url", "origin", "/no/existe/ruta"],
        check=True,
        capture_output=True,
    )

    # origin/main sigue resolviendo localmente (es un ref local, no se borra)
    r = subprocess.run(
        ["git", "-C", str(motor), "rev-parse", "origin/main"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, "origin/main debe seguir resolviendo localmente"

    worktrees_root = tmp_path / "worktrees"
    suffix = "test-session"
    uv_bin = [sys.executable, str(_make_fake_uv(tmp_path))]

    rc, combined = _run_pair(
        motor,
        destino,
        suffix,
        worktrees_root,
        uv_bin,
        extra_args=["--base-ref", "origin/main"],
    )

    assert rc == 0, combined
    assert "[WARN]" in combined
    lower_combined = combined.lower()
    assert (
        "origin/main" in lower_combined
        or "stale" in lower_combined
        or "desactualizado" in lower_combined
    )
