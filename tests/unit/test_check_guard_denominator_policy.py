from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
META = ROOT / "scripts" / "check_guard_denominator_policy.py"


def _repo(tmp_path: Path, *, include_meta: bool = True) -> tuple[Path, Path]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    if include_meta:
        shutil.copy2(META, scripts / META.name)
    (scripts / "check_synthetic.py").write_text(
        "import sys\nprint(sys.argv[1] if len(sys.argv) > 1 else 'OK')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    policy = {
        "version": 1,
        "guards": {
            "scripts/check_synthetic.py": {
                "clase": "no_denominator",
                "skip_explicito": "no",
            },
        },
    }
    if include_meta:
        policy["guards"]["scripts/check_guard_denominator_policy.py"] = {
            "clase": "no_denominator",
            "skip_explicito": "no",
        }
    path = scripts / "guard_denominator_policy.yaml"
    path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    subprocess.run(["git", "add", "scripts"], cwd=tmp_path, check=True)
    return tmp_path, path


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / META.name),
            "--motor-root",
            str(repo),
            *extra,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_entry_present_prints_denominator(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert "N check_*.py auditados=2" in result.stdout
    assert "M entradas=2" in result.stdout


def test_guard_without_entry_names_guard(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path)
    data = _load(policy)
    del data["guards"]["scripts/check_synthetic.py"]
    policy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result = _run(repo)
    assert result.returncode == 1
    assert "scripts/check_synthetic.py" in result.stderr


def test_probe_with_marker_passes(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path)
    data = _load(policy)
    data["guards"]["scripts/check_synthetic.py"]["probe"] = {
        "comando": ["{python}", "{root}/scripts/check_synthetic.py", "MARKER"],
        "cwd": "{tmpdir}",
        "preparacion": [],
        "marcador": "MARKER",
        "flujo": "stdout",
        "timeout_s": 5,
    }
    policy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert "P probes ejecutados=1" in result.stdout


def test_probe_without_marker_fails(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path)
    data = _load(policy)
    data["guards"]["scripts/check_synthetic.py"]["probe"] = {
        "comando": ["{python}", "{root}/scripts/check_synthetic.py", "OK"],
        "cwd": "{tmpdir}",
        "preparacion": [],
        "marcador": "MISSING",
        "flujo": "stdout",
        "timeout_s": 5,
    }
    policy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert _run(repo).returncode == 1


def test_probe_marker_in_wrong_flow_fails(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path)
    encoding = repo / "scripts" / "check_encoding_guard.py"
    shutil.copy2(ROOT / "scripts" / "check_encoding_guard.py", encoding)
    subprocess.run(["git", "add", str(encoding)], cwd=repo, check=True)
    data = _load(policy)
    data["guards"]["scripts/check_synthetic.py"]["probe"] = {
        "comando": ["{python}", "{root}/scripts/check_encoding_guard.py"],
        "cwd": "{tmpdir}",
        "preparacion": ["git-init"],
        "marcador": "SKIP EXPLICITO",
        "flujo": "stdout",
        "timeout_s": 10,
    }
    policy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert _run(repo).returncode == 1


def test_malicious_command_is_rejected_without_execution(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path)
    data = _load(policy)
    data["guards"]["scripts/check_synthetic.py"]["probe"] = {
        "comando": ["cmd.exe", "{root}/scripts/check_synthetic.py"],
        "cwd": "{tmpdir}",
        "preparacion": [],
        "marcador": "OK",
        "flujo": "stdout",
        "timeout_s": 5,
    }
    policy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result = _run(repo)
    assert result.returncode == 1
    assert "must be exactly {python}" in result.stderr


def test_probe_outside_scripts_is_rejected(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("print('OK')\n", encoding="utf-8")
    data = _load(policy)
    data["guards"]["scripts/check_synthetic.py"]["probe"] = {
        "comando": ["{python}", "{root}/outside.py"],
        "cwd": "{tmpdir}",
        "preparacion": [],
        "marcador": "OK",
        "flujo": "stdout",
        "timeout_s": 5,
    }
    policy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert _run(repo).returncode == 1


def test_self_entry_is_required(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path)
    data = _load(policy)
    del data["guards"]["scripts/check_guard_denominator_policy.py"]
    policy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result = _run(repo)
    assert result.returncode == 1
    assert "check_guard_denominator_policy.py" in result.stderr


def test_empty_universe_is_explicit_skip(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path, include_meta=False)
    (repo / "scripts" / "check_synthetic.py").unlink()
    shutil.copy2(META, repo / "scripts" / META.name)
    policy.write_text("version: 1\nguards: {}\n", encoding="utf-8")
    subprocess.run(
        ["git", "rm", "--cached", "-q", "scripts/check_synthetic.py"],
        cwd=repo,
        check=True,
    )
    result = _run(repo)
    assert result.returncode == 0
    assert "SKIP EXPLICITO" in result.stdout and "No es un PASS" in result.stdout


def test_empty_policy_with_universe_fails(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path)
    policy.write_text("version: 1\nguards: {}\n", encoding="utf-8")
    result = _run(repo)
    assert result.returncode == 1
    assert "check_synthetic.py" in result.stderr


def test_unreadable_or_invalid_class_fails(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path)
    policy.write_text(
        "version: 1\nguards:\n  scripts/check_synthetic.py:\n    clase: invented\n    skip_explicito: no\n",
        encoding="utf-8",
    )
    assert _run(repo).returncode == 1
    policy.write_text("not: [valid", encoding="utf-8")
    assert _run(repo).returncode == 1


def test_invalid_skip_value_names_guard(tmp_path: Path) -> None:
    repo, policy = _repo(tmp_path)
    data = _load(policy)
    data["guards"]["scripts/check_synthetic.py"]["skip_explicito"] = "quizas"
    policy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result = _run(repo)
    assert result.returncode == 1
    assert "scripts/check_synthetic.py" in result.stderr


def test_declared_guard_without_pre_commit_is_not_false_positive(
    tmp_path: Path,
) -> None:
    repo, _ = _repo(tmp_path)
    assert not (repo / ".pre-commit-config.yaml").exists()
    assert _run(repo).returncode == 0
    policy = repo / "scripts" / "guard_denominator_policy.yaml"
    data = _load(policy)
    del data["guards"]["scripts/check_synthetic.py"]
    policy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert _run(repo).returncode == 1
