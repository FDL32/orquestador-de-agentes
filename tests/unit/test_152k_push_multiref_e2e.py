"""Tests WOT-2026-152k: la autoridad de push ve TODAS las refs (E2E con hook REAL).

Cada test monta un repo de trabajo y un repo bare desechables bajo tmp_path,
instala el hook REAL de pre-commit (`pre-commit install -t pre-push`) y empuja
con `git push`. Nunca toca el repo del motor ni ningun remoto real: el
`pre-commit install` y `--install-native-hook` ocurren SOLO dentro de tmp_path.

Contexto del blocker (040z-r1): pre-commit no reenvia el stdin de git al hook y
solo expone UNA ref (la primera con remote existente), asi que `git push
origin feature-x main` y `git push origin --all` empujaban main. Estos tests
fijan el comportamiento con el hook nativo (`pre-push.legacy`) y el modo
fail-closed sin el.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from scripts import check_push_authority as cpa


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_SRC = REPO_ROOT / "scripts" / "check_push_authority.py"


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "PRE_COMMIT", "DESIGN_PUSH"))
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    if extra:
        env.update(extra)
    return env


@dataclass
class Rig:
    work: Path
    bare: Path
    env: dict[str, str]

    def git(self, *args: str, check: bool = True, env: dict[str, str] | None = None):
        proc = subprocess.run(
            ["git", *args],
            cwd=self.work,
            env=env or self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and proc.returncode != 0:
            raise AssertionError(f"git {args} rc={proc.returncode}: {proc.stderr}")
        return proc

    def push(self, *args: str, reason: str | None = None):
        env = dict(self.env)
        if reason is not None:
            env["DESIGN_PUSH_REASON"] = reason
        return self.git("push", "bare", *args, check=False, env=env)

    def remote_refs(self) -> dict[str, str]:
        out = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname) %(objectname)"],
            cwd=self.bare,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return dict(line.split() for line in out.splitlines() if line.strip())

    def declare(self, tipo: str) -> None:
        path = self.work / ".agent" / "runtime" / "session" / "session_type.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"tipo": tipo, "declared_at": "2026-11-02T00:00:00+00:00"}),
            encoding="utf-8",
        )

    def install_native(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                "scripts/check_push_authority.py",
                "--install-native-hook",
            ],
            cwd=self.work,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    @property
    def common_dir(self) -> Path:
        return self.work / ".git"


def _build_rig(tmp_path: Path) -> Rig:
    bare = tmp_path / "bare.git"
    work = tmp_path / "work"
    env = _clean_env({"PRE_COMMIT_HOME": str(tmp_path / "pc_home")})
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(bare)], env=env, check=True
    )
    # HEAD del bare fuera de main: si no, git rechaza por si solo borrar la rama
    # actual (receive.denyDeleteCurrent) y el test de borrado seria vacuo.
    subprocess.run(
        ["git", "--git-dir", str(bare), "symbolic-ref", "HEAD", "refs/heads/feature-x"],
        env=env,
        check=True,
    )
    work.mkdir()
    rig = Rig(work=work, bare=bare, env=env)
    rig.git("init", "-q", "-b", "main")
    rig.git("config", "user.email", "t@example.invalid")
    rig.git("config", "user.name", "t")
    rig.git("config", "core.autocrlf", "false")
    (work / "scripts").mkdir()
    shutil.copyfile(SCRIPT_SRC, work / "scripts" / "check_push_authority.py")
    entry = json.dumps(
        f"{Path(sys.executable).as_posix()} scripts/check_push_authority.py"
    )
    (work / ".pre-commit-config.yaml").write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: check-push-authority\n"
        "        name: check push authority\n"
        f"        entry: {entry}\n"
        "        language: system\n"
        "        pass_filenames: false\n"
        "        always_run: true\n"
        "        stages: [pre-push]\n",
        encoding="utf-8",
        newline="\n",
    )
    rig.git("add", "-A")
    rig.git("commit", "-q", "-m", "base")
    rig.git("remote", "add", "bare", bare.as_posix())
    rig.git("push", "-q", "--no-verify", "bare", "main")
    # feature-x YA existe en el remoto: es la condicion del blocker (pre-commit
    # expone la primera ref con remote existente = feature-x, y main queda oculta).
    rig.git("switch", "-q", "-c", "feature-x")
    (work / "fx.txt").write_text("1\n", encoding="utf-8", newline="\n")
    rig.git("add", "fx.txt")
    rig.git("commit", "-q", "-m", "fx1")
    rig.git("push", "-q", "--no-verify", "bare", "feature-x")
    (work / "fx.txt").write_text("2\n", encoding="utf-8", newline="\n")
    rig.git("commit", "-q", "-am", "fx2")
    # zz-branch ordena DESPUES de main: un guard que mire solo la primera o solo
    # la ultima ref no puede ver main cuando esta en medio.
    rig.git("switch", "-q", "-c", "zz-branch", "main")
    (work / "zz.txt").write_text("1\n", encoding="utf-8", newline="\n")
    rig.git("add", "zz.txt")
    rig.git("commit", "-q", "-m", "zz1")
    rig.git("push", "-q", "--no-verify", "bare", "zz-branch")
    (work / "zz.txt").write_text("2\n", encoding="utf-8", newline="\n")
    rig.git("commit", "-q", "-am", "zz2")
    rig.git("switch", "-q", "main")
    (work / "m.txt").write_text("m\n", encoding="utf-8", newline="\n")
    rig.git("add", "m.txt")
    rig.git("commit", "-q", "-m", "main2")
    installed = subprocess.run(
        [sys.executable, "-m", "pre_commit", "install", "-t", "pre-push"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    return rig


@pytest.fixture()
def rig(tmp_path: Path) -> Rig:
    """Repo desechable CON sesion `diseno` y SIN hook nativo."""
    built = _build_rig(tmp_path)
    built.declare("diseno")
    return built


@pytest.fixture()
def native_rig(rig: Rig) -> Rig:
    """Igual que `rig` pero con el hook nativo instalado (solo en tmp_path)."""
    done = rig.install_native()
    assert done.returncode == 0, done.stdout + done.stderr
    return rig


def _main_unchanged(rig: Rig, before: dict[str, str]) -> bool:
    return rig.remote_refs()["refs/heads/main"] == before["refs/heads/main"]


# ---------------------------------------------------------------- rama multi-ref


def test_multiref_feature_then_main_is_blocked(native_rig: Rig) -> None:
    before = native_rig.remote_refs()
    proc = native_rig.push("feature-x", "main")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "diseno" in proc.stderr
    assert _main_unchanged(native_rig, before)
    assert native_rig.remote_refs() == before


def test_multiref_main_then_feature_is_blocked(native_rig: Rig) -> None:
    before = native_rig.remote_refs()
    proc = native_rig.push("main", "feature-x")
    assert proc.returncode != 0
    assert _main_unchanged(native_rig, before)


def test_multiref_main_in_the_middle_is_blocked(native_rig: Rig) -> None:
    """main entre dos ramas (antes y despues por orden de refname)."""
    before = native_rig.remote_refs()
    proc = native_rig.push("feature-x", "main", "zz-branch")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert native_rig.remote_refs() == before


def test_push_all_is_blocked(native_rig: Rig) -> None:
    before = native_rig.remote_refs()
    proc = native_rig.push("--all")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert native_rig.remote_refs() == before


def test_push_main_alone_is_blocked(native_rig: Rig) -> None:
    before = native_rig.remote_refs()
    assert native_rig.push("main").returncode != 0
    assert native_rig.remote_refs() == before


def test_delete_remote_main_is_blocked(native_rig: Rig) -> None:
    """pre-commit NO ejecuta sus hooks en un borrado puro: solo el nativo lo ve."""
    before = native_rig.remote_refs()
    proc = native_rig.push(":main")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert native_rig.remote_refs() == before


# ------------------------------------------------------------- control negativo


def test_delete_remote_main_is_allowed_for_desarrollo_control(native_rig: Rig) -> None:
    """Control positivo: sin el guard git SI borra main (el test de arriba no es vacuo)."""
    native_rig.declare("desarrollo")
    proc = native_rig.push(":main")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "refs/heads/main" not in native_rig.remote_refs()


def test_push_feature_branch_only_is_allowed(native_rig: Rig) -> None:
    before = native_rig.remote_refs()
    proc = native_rig.push("feature-x")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    after = native_rig.remote_refs()
    assert after["refs/heads/feature-x"] != before["refs/heads/feature-x"]
    assert after["refs/heads/main"] == before["refs/heads/main"]


def test_push_two_feature_branches_without_main_is_allowed(native_rig: Rig) -> None:
    before = native_rig.remote_refs()
    proc = native_rig.push("feature-x", "zz-branch")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    after = native_rig.remote_refs()
    assert after["refs/heads/zz-branch"] != before["refs/heads/zz-branch"]
    assert after["refs/heads/main"] == before["refs/heads/main"]


def test_feature_slash_main_is_not_main(native_rig: Rig) -> None:
    """Igualdad exacta con refs/heads/main: feature/main no es main."""
    native_rig.git("branch", "feature/main", "feature-x")
    proc = native_rig.push("feature/main")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "refs/heads/feature/main" in native_rig.remote_refs()


# ------------------------------------------------------------------ fail-closed


def test_without_native_hook_diseno_push_fails_closed(rig: Rig) -> None:
    """Sin hook nativo las refs son desconocidas: diseno NO pasa ni a una rama."""
    before = rig.remote_refs()
    proc = rig.push("feature-x")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "--install-native-hook" in proc.stdout + proc.stderr
    assert rig.remote_refs() == before


def test_without_native_hook_reason_escape_is_logged(rig: Rig) -> None:
    proc = rig.push("feature-x", reason="prueba de escape 152k")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    log = rig.work / ".agent" / "runtime" / "session" / "design_push_log.jsonl"
    entries = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert entries[-1]["reason"] == "prueba de escape 152k"


def _manifest_for(
    rig: Rig,
    *,
    ts: float,
    url: str | None = None,
    name: str = "bare",
    local_sha: str | None = None,
) -> None:
    """Manifiesto con las refs/shas REALES del push `feature-x` (o variantes ajenas)."""
    local = local_sha or rig.git("rev-parse", "feature-x").stdout.strip()
    remote = rig.remote_refs()["refs/heads/feature-x"]
    remote_url = rig.git("remote", "get-url", "bare").stdout.strip()
    directory = rig.common_dir / cpa.MANIFEST_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "1-1.json").write_text(
        json.dumps(
            {
                "ts": ts,
                "remote_name": name,
                "remote_url": url if url is not None else remote_url,
                "lines": [
                    {
                        "local_ref": "refs/heads/feature-x",
                        "local_sha": local,
                        "remote_ref": "refs/heads/feature-x",
                        "remote_sha": remote,
                    }
                ],
                "verdict": 0,
            }
        ),
        encoding="utf-8",
    )


def test_fresh_matching_manifest_without_native_is_consumed_once(rig: Rig) -> None:
    """Control positivo del consumidor: manifiesto fresco de ESTE push pasa y se borra."""
    _manifest_for(rig, ts=time.time())
    proc = rig.push("feature-x")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not list((rig.common_dir / cpa.MANIFEST_DIRNAME).glob("*.json"))


def test_stale_manifest_is_not_accepted(rig: Rig) -> None:
    _manifest_for(rig, ts=time.time() - 3600)
    before = rig.remote_refs()
    proc = rig.push("feature-x")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert rig.remote_refs() == before


def test_manifest_of_another_push_is_not_accepted(rig: Rig) -> None:
    """Manifiesto fresco de OTRO remoto (push concurrente) no vale para este."""
    _manifest_for(rig, ts=time.time(), url="C:/otro/remoto.git")
    before = rig.remote_refs()
    proc = rig.push("feature-x")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert rig.remote_refs() == before


def test_manifest_with_another_remote_name_is_not_accepted(rig: Rig) -> None:
    _manifest_for(rig, ts=time.time(), name="otro-remoto")
    before = rig.remote_refs()
    proc = rig.push("feature-x")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert rig.remote_refs() == before


def test_manifest_without_this_pushs_sha_is_not_accepted(rig: Rig) -> None:
    """Mismo remoto y fresco, pero de OTRO push (otra sha local): no vale."""
    _manifest_for(rig, ts=time.time(), local_sha="e" * 40)
    before = rig.remote_refs()
    proc = rig.push("feature-x")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert rig.remote_refs() == before


def test_unwritable_manifest_fails_the_push_for_any_session(native_rig: Rig) -> None:
    """El nativo que no puede escribir el manifiesto hace FALLAR el push."""
    native_rig.declare("desarrollo")
    (native_rig.common_dir / cpa.MANIFEST_DIRNAME).write_text("x", encoding="utf-8")
    before = native_rig.remote_refs()
    proc = native_rig.push("feature-x")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert native_rig.remote_refs() == before


# ------------------------------------- las demas sesiones NO cambian (decision (c))


@pytest.mark.parametrize("tipo", ["desarrollo", "orquestacion"])
def test_non_diseno_sessions_push_main_unchanged_without_native(
    rig: Rig, tipo: str
) -> None:
    rig.declare(tipo)
    proc = rig.push("feature-x", "main")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (
        rig.remote_refs()["refs/heads/main"]
        == rig.git("rev-parse", "main").stdout.strip()
    )


def test_undeclared_session_is_warn_and_pushes_without_native(rig: Rig) -> None:
    (rig.work / ".agent" / "runtime" / "session" / "session_type.json").unlink()
    proc = rig.push("feature-x", "main")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    log = rig.work / ".agent" / "runtime" / "session" / "design_push_log.jsonl"
    assert not log.exists()  # sin declaracion no hay escape que registrar


def test_fail_closed_is_only_for_diseno_in_process(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refs desconocidas (None): diseno e invalida bloquean; el resto no cambia."""
    session = tmp_path / ".agent" / "runtime" / "session"
    session.mkdir(parents=True)
    f = session / "session_type.json"
    f.write_text(json.dumps({"tipo": "diseno"}), encoding="utf-8")
    assert cpa.evaluate(tmp_path, None, {}) == 1
    f.write_text(json.dumps({"tipo": "improvisado"}), encoding="utf-8")
    assert cpa.evaluate(tmp_path, None, {}) == 1
    for tipo in ("desarrollo", "orquestacion"):
        f.write_text(json.dumps({"tipo": tipo}), encoding="utf-8")
        assert cpa.evaluate(tmp_path, None, {}) == 0
    f.unlink()
    assert cpa.evaluate(tmp_path, None, {}) == 0
    assert "WARN" in capsys.readouterr().out  # decision (c): sin declaracion avisa


# -------------------------------------------------------- instalador y shim nativo


def test_installer_requires_precommit_pre_push_and_keeps_foreign_legacy(
    tmp_path: Path,
) -> None:
    built = _build_rig(tmp_path)
    legacy = built.work / ".git" / "hooks" / "pre-push.legacy"
    legacy.write_text("#!/usr/bin/env python\nprint('ajeno')\n", encoding="utf-8")
    done = built.install_native()
    assert done.returncode == 1
    assert "ajeno" in legacy.read_text(encoding="utf-8")
    legacy.unlink()
    (built.work / ".git" / "hooks" / "pre-push").unlink()
    assert built.install_native().returncode == 1  # sin el pre-push de pre-commit
    assert not legacy.exists()


def test_native_shim_is_minimal_and_exits_zero_without_script(tmp_path: Path) -> None:
    shim = cpa.NATIVE_SHIM
    assert shim.startswith("#!/usr/bin/env python\n")
    assert "import scripts" not in shim and "from scripts" not in shim
    path = tmp_path / "shim.py"
    path.write_text(shim, encoding="utf-8", newline="\n")
    proc = subprocess.run(
        [sys.executable, str(path), "bare", "url"],
        cwd=tmp_path,
        input="x\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0  # checkout antiguo sin scripts/: legacy, no bloquea


def test_parse_push_lines_keeps_every_line_and_rejects_malformed() -> None:
    z = "0" * 40
    raw = f"refs/heads/a {'1' * 40} refs/heads/a {z}\nrefs/heads/main {'2' * 40} refs/heads/main {'3' * 40}\n"
    lines = cpa.parse_push_lines(raw)
    assert [x["remote_ref"] for x in lines] == ["refs/heads/a", "refs/heads/main"]
    with pytest.raises(cpa.PushRefsError):
        cpa.parse_push_lines("refs/heads/a only-two\n")


# ------------------------------------- ronda 2: declaracion corrupta no es legacy

_Z = "0" * 40


def _stdin_for(*remote_refs: str) -> str:
    return "".join(f"{r} {'1' * 40} {r} {'2' * 40}\n" for r in remote_refs)


def _git_repo_with_declaration(tmp_path: Path, content: str | None) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    if content is not None:
        path = tmp_path / ".agent" / "runtime" / "session" / "session_type.json"
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("content", ['{"tipo":"diseno"', "[]", ""])
def test_existing_but_unreadable_declaration_is_invalid_not_legacy(
    tmp_path: Path, content: str
) -> None:
    """Un session_type.json que EXISTE pero no se puede leer NO es 'sin declarar'."""
    root = _git_repo_with_declaration(tmp_path, content)
    main, feature = "refs/heads/main", "refs/heads/feature-x"
    # modo evaluate (refs inyectadas)
    assert cpa.evaluate(root, [main], {}) == 1
    assert cpa.evaluate(root, [feature], {}) == 0
    assert cpa.evaluate(root, None, {}) == 1  # refs desconocidas: fail-closed
    # modo nativo (stdin completo de git)
    assert cpa.native_gate(root, "o", "u", _stdin_for(feature, main), {}) == 1
    assert cpa.native_gate(root, "o", "u", _stdin_for(feature), {}) == 0
    # modo hook de pre-commit sin manifiesto: necesita refs => fail-closed
    assert cpa.run(root, None, {}) == 1


def test_absent_declaration_is_still_legacy_warn(tmp_path: Path) -> None:
    """Decision (c) de 040z intacta: AUSENTE sigue siendo WARN y pasa."""
    root = _git_repo_with_declaration(tmp_path, None)
    assert cpa.evaluate(root, ["refs/heads/main"], {}) == 0
    assert cpa.native_gate(root, "o", "u", _stdin_for("refs/heads/main"), {}) == 0


def test_residual_manifest_does_not_let_a_new_main_push_through(
    tmp_path: Path,
) -> None:
    """Un manifiesto residual de feature-x no afecta a un push NUEVO feature-x+main."""
    root = _git_repo_with_declaration(tmp_path, json.dumps({"tipo": "diseno"}))
    assert cpa.native_gate(root, "o", "u", _stdin_for("refs/heads/feature-x"), {}) == 0
    assert list((root / ".git" / cpa.MANIFEST_DIRNAME).glob("*.json"))  # residuo
    both = _stdin_for("refs/heads/feature-x", "refs/heads/main")
    assert cpa.native_gate(root, "o", "u", both, {}) == 1


def test_delete_line_of_main_parses_with_four_fields() -> None:
    """Git manda el borrado como `(delete) <ceros> refs/heads/main <sha>`: 4 campos."""
    raw = f"(delete) {_Z} refs/heads/main {'3' * 40}\n"
    lines = cpa.parse_push_lines(raw)
    assert [x["remote_ref"] for x in lines] == ["refs/heads/main"]
    assert lines[0]["local_sha"] == _Z


def _git_repo_with_node_at_declaration_path(tmp_path: Path, kind: str) -> Path:
    """Crea en la ruta de session_type.json algo que NO es un fichero regular."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / ".agent" / "runtime" / "session" / "session_type.json"
    path.parent.mkdir(parents=True)
    if kind == "dir":
        path.mkdir()
    else:
        try:
            os.symlink(tmp_path / "no-existe-destino", path)
        except (OSError, NotImplementedError):
            pytest.skip("sin permiso para crear symlinks en este host")
    return tmp_path


@pytest.mark.parametrize("kind", ["dir", "broken_symlink"])
def test_declaration_path_that_exists_but_is_not_a_file_is_invalid_not_legacy(
    tmp_path: Path, kind: str
) -> None:
    """Un directorio (o symlink roto) en la ruta de la declaracion EXISTE: no es legacy."""
    root = _git_repo_with_node_at_declaration_path(tmp_path, kind)
    main, feature = "refs/heads/main", "refs/heads/feature-x"
    assert cpa.evaluate(root, [main], {}) == 1
    assert cpa.evaluate(root, [feature], {}) == 0
    assert cpa.evaluate(root, None, {}) == 1
    assert cpa.native_gate(root, "o", "u", _stdin_for(feature, main), {}) == 1
    assert cpa.native_gate(root, "o", "u", _stdin_for(feature), {}) == 0
    assert cpa.run(root, None, {}) == 1


# ------------------------------------ ronda 4: el instalador no anuncia exito en falso


@pytest.mark.parametrize("relative", [False, True])
def test_installer_writes_the_shim_in_the_effective_hooks_dir(
    tmp_path: Path, relative: bool
) -> None:
    """Con core.hooksPath el shim va al dir EFECTIVO, nunca al por defecto."""
    built = _build_rig(tmp_path)
    default_dir = built.work / ".git" / "hooks"
    effective = built.work / "hp"
    effective.mkdir()
    shutil.copyfile(default_dir / "pre-push", effective / "pre-push")
    built.git("config", "core.hooksPath", "hp" if relative else str(effective))
    done = built.install_native()
    assert done.returncode == 0, done.stdout + done.stderr
    assert (effective / "pre-push.legacy").is_file()
    assert not (default_dir / "pre-push.legacy").exists()


def test_installer_fails_when_effective_hooks_dir_does_not_exist(
    tmp_path: Path,
) -> None:
    built = _build_rig(tmp_path)
    built.git("config", "core.hooksPath", str(built.work / "no-existe"))
    done = built.install_native()
    assert done.returncode == 2, done.stdout + done.stderr
    assert not (built.work / ".git" / "hooks" / "pre-push.legacy").exists()


def test_installer_does_not_follow_a_broken_symlink_at_legacy(
    tmp_path: Path,
) -> None:
    """Un symlink roto en pre-push.legacy EXISTE: no se pisa ni se crea su destino."""
    built = _build_rig(tmp_path)
    legacy = built.work / ".git" / "hooks" / "pre-push.legacy"
    target = tmp_path / "destino-que-no-debe-crearse"
    try:
        os.symlink(target, legacy)
    except (OSError, NotImplementedError):
        pytest.skip("sin permiso para crear symlinks en este host")
    done = built.install_native()
    assert done.returncode == 1, done.stdout + done.stderr
    assert not target.exists()
