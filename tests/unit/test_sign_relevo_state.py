"""Before: define the observable contract for the relevo state signer.

During: exercise the future CLI only through hermetic subprocesses and temporary
Git repositories.

After: preserve a red test suite until the signer and its template exist.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "flight" / "sign_relevo_state.py"
TEMPLATE = REPO_ROOT / "prompts" / "vuelo_pilares_templates" / "HANDOFF_PLANTILLA.md"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _run_script(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Before: receive CLI arguments and an isolated current directory.

    During: execute the future script with deterministic UTF-8 environment
    settings and captured text output.

    After: return the complete subprocess result for explicit assertions.
    """
    environment = os.environ.copy()
    environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def _git(cwd: Path, *args: str) -> str:
    """Before: receive a temporary repository and a Git argument vector.

    During: run Git without shell interpretation and require success.

    After: return the normalized stdout needed by the test's real-state checks.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _git_repo(tmp_path: Path) -> Path:
    """Before: receive pytest's isolated temporary directory.

    During: initialize Git and create a real first commit with explicit identity.

    After: return a repository whose HEAD can be compared to emitted state.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init", "--quiet")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(tmp_path, "add", "seed.txt")
    _git(
        tmp_path,
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "user.name=Test User",
        "commit",
        "--quiet",
        "-m",
        "seed",
    )
    return tmp_path


def _digest(state: dict[str, object]) -> str:
    """Before: receive a decoded candidate state.

    During: independently reproduce the canonical sha256 input serialization.

    After: return the lowercase digest used to rehash test fixtures.
    """
    digest_fields = {
        key: state[key]
        for key in (
            "identidad",
            "autoridad",
            "fecha_utc",
            "recibo",
            "comando_verificacion",
            "sha_datos",
        )
    }
    payload = json.dumps(
        digest_fields,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load(path: Path) -> dict[str, object]:
    """Before: receive a JSON state path.

    During: decode the file into a mutable mapping for a focused mutation.

    After: return the decoded mapping without invoking the production module.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def _emit(repo: Path, out: Path, *args: str) -> dict[str, object]:
    """Before: receive a Git repository, destination, and optional CLI flags.

    During: invoke emit and require the fixture-producing command to succeed.

    After: return the independently decoded emitted state.
    """
    result = _run_script("--emit", "--out", str(out), *args, cwd=repo)
    assert result.returncode == 0, result.stderr or result.stdout
    return _load(out)


def _write_state(path: Path, state: dict[str, object]) -> None:
    """Before: receive a target path and a state mapping.

    During: serialize the candidate using the contract's UTF-8 JSON formatting.

    After: leave a newline-terminated candidate file for selection tests.
    """
    path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_script_file_exists() -> None:
    """Before: locate the future signer script.

    During: check the required path directly.

    After: fail clearly while the implementation file is absent.
    """
    assert SCRIPT.is_file(), "script no existe todavia"


def test_emit_bare_writes_valid_state(tmp_path: Path) -> None:
    """Before: create a real temporary Git repository.

    During: emit defaults and inspect both decoded fields and raw key counts.

    After: prove the output is tied to the repository's actual HEAD.
    """
    repo = _git_repo(tmp_path)
    out = repo / "estado.json"
    result = _run_script("--emit", "--out", str(out), cwd=repo)
    assert result.returncode == 0, result.stderr
    state = _load(out)
    assert state["identidad"]["rol"]
    assert state["identidad"]["hilo"]
    assert state["autoridad"]["runtimeMode"]
    assert state["autoridad"]["delivery_authority"]
    assert DATE_RE.fullmatch(state["fecha_utc"])
    dt.datetime.strptime(state["fecha_utc"], "%Y-%m-%dT%H:%M:%SZ")
    assert state["recibo"]["go_fila"]
    assert state["recibo"]["mensaje_id"]
    assert "sign_relevo_state.py" in state["comando_verificacion"]
    assert "\n" not in state["comando_verificacion"]
    assert SHA40.fullmatch(state["sha_datos"])
    assert state["sha_datos"] == _git(repo, "rev-parse", "HEAD")
    assert re.fullmatch(r"[0-9a-f]{64}", state["sha_estado"])
    raw = out.read_text(encoding="utf-8")
    assert raw.count('"identidad"') == 1
    assert raw.count('"autoridad"') == 1
    assert raw.count('"comando_verificacion"') == 1


def test_emit_explicit_campos_override(tmp_path: Path) -> None:
    """Before: create a repository and seven explicit CLI values.

    During: emit with every override flag and inspect its mapped field.

    After: prove overrides coexist with the repository-derived SHA.
    """
    repo = _git_repo(tmp_path)
    out = repo / "explicit.json"
    state = _emit(
        repo,
        out,
        "--rol",
        "builder",
        "--hilo",
        "IM-214",
        "--runtime-mode",
        "4capas",
        "--delivery-authority",
        "manager",
        "--go-fila",
        "GO-17",
        "--mensaje-id",
        "MSG-213A",
        "--comando",
        "python -c \"print('ok')\"",
    )
    assert state["identidad"] == {"rol": "builder", "hilo": "IM-214"}
    assert state["autoridad"] == {
        "runtimeMode": "4capas",
        "delivery_authority": "manager",
    }
    assert state["recibo"] == {"go_fila": "GO-17", "mensaje_id": "MSG-213A"}
    assert state["comando_verificacion"] == "python -c \"print('ok')\""
    assert state["sha_datos"] == _git(repo, "rev-parse", "HEAD")


def test_emit_non_git_cwd_fails(tmp_path: Path) -> None:
    """Before: use a temporary directory without Git metadata.

    During: request bare emission into a not-yet-existing output path.

    After: require failure and absence of the output artifact.
    """
    assert SCRIPT.is_file(), "script no existe todavia"
    out = tmp_path / "must-not-exist.json"
    result = _run_script("--emit", "--out", str(out), cwd=tmp_path)
    assert result.returncode != 0
    assert not out.exists()


def test_verify_intact_exit_zero(tmp_path: Path) -> None:
    """Before: emit one intact state in a real temporary repository.

    During: verify the state through the CLI.

    After: require successful validation without changing the file.
    """
    repo = _git_repo(tmp_path)
    out = repo / "state.json"
    _emit(repo, out)
    result = _run_script("--verify", str(out), cwd=repo)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing-file", 10),
        ("malformed-json", 10),
        ("missing-nested-field", 11),
        ("invalid-date", 12),
        ("bad-sha-datos", 13),
        ("mutated-field", 14),
        ("failed-verification-command", 15),
        ("intact", 0),
    ],
)
def test_verify_exact_exit_codes(tmp_path: Path, case: str, expected: int) -> None:
    """Before: create one hermetic state-validation fixture per taxonomy row.

    During: apply exactly the selected defect, rehash only when the contract
    requires it, and verify through the real CLI subprocess.

    After: require the precise documented exit code for every validation class.
    """
    repo = _git_repo(tmp_path)
    candidate = repo / f"{case}.json"
    if case == "missing-file":
        pass
    elif case == "malformed-json":
        candidate.write_text("{esto no es json", encoding="utf-8")
    else:
        source = repo / "state.json"
        state = _emit(repo, source)
        if case == "missing-nested-field":
            del state["identidad"]["hilo"]
        elif case == "invalid-date":
            state["fecha_utc"] = "not-a-date-at-all"
        elif case == "bad-sha-datos":
            state["sha_datos"] = "a" * 39
            state["sha_estado"] = _digest(state)
        elif case == "mutated-field":
            state["identidad"]["rol"] = "auditor"
        elif case == "failed-verification-command":
            state["comando_verificacion"] = (
                "python scripts/flight/no_existe_zzz_213a.py"
            )
            state["sha_estado"] = _digest(state)
        _write_state(candidate, state)

    result = _run_script("--verify", str(candidate), cwd=repo)
    assert result.returncode == expected, result.stderr or result.stdout


@pytest.mark.parametrize(
    ("field_path", "replacement"),
    [
        (("identidad", "rol"), "auditor"),
        (("autoridad", "runtimeMode"), "tradicional"),
        (("fecha_utc",), "2026-11-21T10:10:10Z"),
        (("recibo", "go_fila"), "STOP"),
        (("comando_verificacion",), "python -c \"print('mutated')\""),
    ],
)
def test_verify_mutated_each_campo_nonzero(
    tmp_path: Path, field_path: tuple[str, ...], replacement: str
) -> None:
    """Before: emit a valid state and copy it for one-field mutation.

    During: mutate exactly one contract field without helping the digest.

    After: require verification to reject every independently changed field.
    """
    repo = _git_repo(tmp_path)
    out = repo / "state.json"
    _emit(repo, out)
    state = _load(out)
    target: dict[str, object] = state
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = replacement
    mutated = repo / "mutated.json"
    _write_state(mutated, state)
    result = _run_script("--verify", str(mutated), cwd=repo)
    assert result.returncode != 0


@pytest.mark.parametrize(
    "bad_sha", ["a" * 39, "a" * 41, "A" * 40, "0x" + "a" * 38, "z" * 40]
)
def test_verify_bad_sha_datos_format_nonzero(tmp_path: Path, bad_sha: str) -> None:
    """Before: emit a valid state and replace only sha_datos.

    During: recompute sha_estado independently so format validation is isolated.

    After: require rejection of every invalid SHA representation.
    """
    repo = _git_repo(tmp_path)
    out = repo / "state.json"
    state = _emit(repo, out)
    state["sha_datos"] = bad_sha
    state["sha_estado"] = _digest(state)
    mutated = repo / "bad-sha.json"
    _write_state(mutated, state)
    result = _run_script("--verify", str(mutated), cwd=repo)
    assert result.returncode != 0


def test_verify_tampered_digest_nonzero(tmp_path: Path) -> None:
    """Before: emit a valid state and preserve all contract fields.

    During: replace sha_estado with a different well-formed digest.

    After: require the verifier to detect the tampered digest.
    """
    repo = _git_repo(tmp_path)
    out = repo / "state.json"
    state = _emit(repo, out)
    state["sha_estado"] = "0" * 64
    mutated = repo / "tampered.json"
    _write_state(mutated, state)
    result = _run_script("--verify", str(mutated), cwd=repo)
    assert result.returncode != 0


@pytest.mark.parametrize("case", ["missing-nested", "missing-digest", "empty-command"])
def test_verify_schema_missing_pieces_nonzero(tmp_path: Path, case: str) -> None:
    """Before: emit a valid state and select one schema defect.

    During: remove or empty a required piece without recomputing the digest.

    After: require schema rejection before any digest assistance is applied.
    """
    repo = _git_repo(tmp_path)
    out = repo / "state.json"
    state = _emit(repo, out)
    if case == "missing-nested":
        del state["identidad"]["hilo"]
    elif case == "missing-digest":
        del state["sha_estado"]
    else:
        state["comando_verificacion"] = ""
    mutated = repo / f"schema-{case}.json"
    _write_state(mutated, state)
    result = _run_script("--verify", str(mutated), cwd=repo)
    assert result.returncode != 0


def test_verify_head_advance_still_zero(tmp_path: Path) -> None:
    """Before: emit state tied to the first real repository commit.

    During: advance HEAD with an empty commit and verify twice without re-reading
    the current HEAD from the state validator.

    After: require both verifications to remain successful and prove HEAD moved.
    """
    repo = _git_repo(tmp_path)
    out = repo / "state.json"
    state = _emit(repo, out)
    original_head = state["sha_datos"]
    _git(
        repo,
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "user.name=Test User",
        "commit",
        "--quiet",
        "--allow-empty",
        "-m",
        "advance",
    )
    assert _git(repo, "rev-parse", "HEAD") != original_head
    for _ in range(2):
        result = _run_script("--verify", str(out), cwd=repo)
        assert result.returncode == 0, result.stderr


def test_comando_selfcheck_executable(tmp_path: Path) -> None:
    """Before: emit a state whose verification command is supplied by production.

    During: execute that command with shell semantics from the script repository.

    After: require a successful command and a single-line representation.
    """
    repo = _git_repo(tmp_path)
    out = repo / "state.json"
    state = _emit(repo, out)
    command = state["comando_verificacion"]
    assert "\n" not in command
    result = subprocess.run(  # noqa: S602 - contract explicitly requires shell=True
        command,
        shell=True,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_handoff_plantilla_exists_no_head_points_estado() -> None:
    """Before: locate the future handoff template.

    During: inspect its literal placeholders and state-reference contract.

    After: reject templates that point at HEAD instead of the vigente state.
    """
    assert TEMPLATE.is_file(), "NO EXISTE = conteo de partida no existe"
    content = TEMPLATE.read_text(encoding="utf-8")
    assert content.count("HEAD") == 0
    assert "diseno/ESTADO_RELEVO_VIGENTE.json" in content
    assert "{{" in content


def test_select_vigente_deterministic(tmp_path: Path) -> None:
    """Before: create valid, invalid, reversed-mtime, and tied-date candidates.

    During: select repeatedly and compare bytes against the deterministic winner.

    After: require date precedence, invalid exclusion, lexical tie-break, and
    untouched output when no candidate validates.
    """
    repo = _git_repo(tmp_path / "repo")
    candidates = repo / "candidates"
    candidates.mkdir()
    source = repo / "source.json"
    base = _emit(repo, source)
    for name, date in (
        ("aaa_state.json", "2026-11-19T10:00:00Z"),
        ("zzz_state.json", "2026-11-20T21:00:00Z"),
        ("mmm_state.json", "2026-11-21T09:00:00Z"),
    ):
        candidate = dict(base)
        candidate["fecha_utc"] = date
        candidate["sha_estado"] = _digest(candidate)
        _write_state(candidates / name, candidate)
    broken = _load(candidates / "mmm_state.json")
    broken["identidad"]["rol"] = "broken"
    _write_state(candidates / "mmm_state.json", broken)
    aaa = candidates / "aaa_state.json"
    zzz = candidates / "zzz_state.json"
    os.utime(aaa, (2_000_000_000, 2_000_000_000))
    os.utime(zzz, (1_000_000_000, 1_000_000_000))
    out = repo / "selected.json"
    result = _run_script(
        "--select-vigente",
        "--candidates",
        str(candidates),
        "--out",
        str(out),
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == zzz.read_bytes()

    tie_a = dict(base)
    tie_a["fecha_utc"] = "2026-11-22T09:00:00Z"
    tie_a["sha_estado"] = _digest(tie_a)
    tie_z = dict(tie_a)
    tie_z["identidad"] = dict(tie_z["identidad"])
    tie_z["identidad"]["rol"] = "lexically-later"
    tie_z["sha_estado"] = _digest(tie_z)
    _write_state(candidates / "bbb_state.json", tie_a)
    _write_state(candidates / "ccc_state.json", tie_z)
    result = _run_script(
        "--select-vigente",
        "--candidates",
        str(candidates),
        "--out",
        str(out),
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == (candidates / "bbb_state.json").read_bytes()

    only_broken = repo / "only-broken"
    only_broken.mkdir()
    _write_state(only_broken / "broken.json", broken)
    sentinel = b"keep this byte-for-byte\n"
    out.write_bytes(sentinel)
    result = _run_script(
        "--select-vigente",
        "--candidates",
        str(only_broken),
        "--out",
        str(out),
        cwd=repo,
    )
    assert result.returncode != 0
    assert out.read_bytes() == sentinel


def test_selfcheck_ok(tmp_path: Path) -> None:
    """Before: provide an isolated working directory for the CLI.

    During: run the internal selfcheck mode without additional arguments.

    After: require its documented success marker and zero exit status.
    """
    result = _run_script("--selfcheck", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "selfcheck ok" in result.stdout
