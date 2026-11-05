from __future__ import annotations

import json
import secrets
import subprocess
import sys
from pathlib import Path

from scripts.flight import verify_delivery


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _fixture_repo(tmp_path: Path, *, with_test: bool = True) -> tuple[Path, str]:
    repo = tmp_path / "repo con espacio"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "src.py").write_text("value = 1\n", encoding="utf-8")
    if with_test:
        test_path = repo / "tests" / "unit"
        test_path.mkdir(parents=True)
        (test_path / "test_sample.py").write_text(
            "def test_sample():\n    assert True\n", encoding="utf-8"
        )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "src.py").write_text("value = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "-qm",
        "WOT-2026-157a: verify delivery\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
        "--author=Claude <noreply@anthropic.com>",
    )
    return repo, base


def _runner_without_real_pytest(command, **kwargs):
    if any("run_pytest_safe.py" in str(part) for part in command):
        return subprocess.CompletedProcess(command, 0, "focal ok\n", "")
    return subprocess.run(command, **kwargs)


def test_verify_delivery_happy_path_emits_green_receipt(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    rc, receipt = verify_delivery.measure_delivery(
        repo,
        base,
        flt=["src.py"],
        command_runner=_runner_without_real_pytest,
    )

    assert rc == 0
    assert receipt["verdict"] == "GREEN"
    assert receipt["steps"]["flt"]["status"] == "OK"
    assert receipt["steps"]["focal_tests"]["status"] == "NA"
    assert receipt["head_sha_start"] == receipt["head_sha_end"]
    assert receipt["steps"]["tree"]["command_rc"] == 0
    assert receipt["steps"]["commits-count"]["command_rc"] == 0
    assert receipt["steps"]["trailer"]["command_rc"] == 0
    assert receipt["steps"]["scope"]["command_rc"] == 0
    assert receipt["steps"]["ruff"]["command_rcs"] == {"check": 0, "format": 0}
    assert receipt["steps"]["encoding"]["command_rc"] == 0
    assert receipt["steps"]["entropy"]["command_rc"] == 0
    assert receipt["steps"]["sha_stability"]["command_rcs"] == {
        "start": 0,
        "base": 0,
        "end": 0,
    }


def test_verify_delivery_without_flt_is_no_medido_with_exact_cause(
    tmp_path: Path,
) -> None:
    repo, base = _fixture_repo(tmp_path)

    rc, receipt = verify_delivery.measure_delivery(repo, base, flt=[])

    assert rc == 1
    assert receipt["steps"]["flt"]["status"] == "NO_MEDIDO"
    assert receipt["steps"]["flt"]["cause"] == "flt: no source provided"


def test_verify_delivery_rejects_receipt_inside_measured_worktree(
    tmp_path: Path,
) -> None:
    repo, base = _fixture_repo(tmp_path)
    receipt_path = repo / "receipt.json"

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], receipt=receipt_path
    )

    assert rc == 2
    assert receipt["steps"]["receipt"]["cause"] == (
        "receipt: path is inside measured worktree"
    )
    assert not receipt_path.exists()


def test_verify_delivery_detects_entropy_only_in_added_diff_lines(
    tmp_path: Path,
) -> None:
    repo, base = _fixture_repo(tmp_path)
    token = secrets.token_hex(32)
    (repo / "src.py").write_text(f"api_key = {token}\n", encoding="utf-8")
    _git(repo, "add", "src.py")
    _git(repo, "commit", "-qm", "secret")
    base = _git(repo, "rev-parse", "HEAD~1")

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=_runner_without_real_pytest
    )

    assert rc == 1
    assert receipt["steps"]["entropy"]["status"] == "FAIL"
    assert receipt["steps"]["entropy"]["cause"].startswith("entropy:")


def test_entropy_import_failure_is_no_medido_and_global_red(
    tmp_path: Path, monkeypatch
) -> None:
    repo, base = _fixture_repo(tmp_path)
    original_import = __import__

    def blocked_import(name, *args, **kwargs):
        if name == "scripts.ensemble_dispatch":
            raise ImportError("synthetic unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    rc, receipt = verify_delivery.measure_delivery(repo, base, flt=["src.py"])

    assert rc == 1
    assert receipt["steps"]["entropy"]["status"] == "NO_MEDIDO"
    assert receipt["steps"]["entropy"]["rc"] == 1
    assert receipt["verdict"] == "RED"


def test_verify_delivery_cli_rejects_invalid_base_with_rc_two(tmp_path: Path) -> None:
    repo, _ = _fixture_repo(tmp_path)

    rc, receipt = verify_delivery.measure_delivery(repo, "not-a-commit", flt=["src.py"])

    assert rc == 2
    assert receipt["steps"]["input"]["cause"] == "input: base is not a valid commit"


def test_verify_delivery_rejects_base_that_is_not_an_ancestor(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)

    def non_ancestor_runner(command, **kwargs):
        if command[:3] == ["git", "merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(command, 1, b"", b"not ancestor")
        return subprocess.run(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=non_ancestor_runner
    )

    assert rc == 2
    assert receipt["steps"]["input"]["cause"] == (
        "input: base is not an ancestor of HEAD"
    )


def test_commits_count_rejects_zero_commits_with_exact_cause(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)

    rc, receipt = verify_delivery.measure_delivery(repo, "HEAD", flt=["src.py"])

    assert base != _git(repo, "rev-parse", "HEAD")
    assert rc == 1
    assert receipt["steps"]["commits-count"]["cause"] == (
        "commits-count: expected exactly 1 commit, got 0"
    )


def test_verify_delivery_cli_bootstraps_imports_as_real_subprocess(
    tmp_path: Path,
) -> None:
    repo, base = _fixture_repo(tmp_path, with_test=False)
    cli = Path(__file__).parents[2] / "scripts" / "flight" / "verify_delivery.py"

    result = subprocess.run(
        [
            sys.executable,
            str(cli),
            str(repo),
            base,
            "--flt",
            "src.py",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "verdict=GREEN rc=0" in result.stdout
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["verdict"] == "GREEN"
    assert payload["steps"]["entropy"]["rc"] == 0


def test_verify_delivery_cli_receipt_write_failure_publishes_only_red(
    tmp_path: Path,
) -> None:
    repo, base = _fixture_repo(tmp_path, with_test=False)
    cli = Path(__file__).parents[2] / "scripts" / "flight" / "verify_delivery.py"
    receipt = tmp_path / "missing-parent" / "receipt.json"

    result = subprocess.run(
        [
            sys.executable,
            str(cli),
            str(repo),
            base,
            "--flt",
            "src.py",
            "--receipt",
            str(receipt),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "GREEN" not in result.stdout
    assert result.stdout.count('"verdict"') == 1
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["verdict"] == "RED"
    assert payload["rc"] == 1
    assert payload["steps"]["receipt"]["status"] == "FAIL"
    assert payload["steps"]["receipt"]["command_rc"] == 1
    assert "receipt: cannot write receipt" in payload["steps"]["receipt"]["cause"]
    assert not receipt.exists()


def test_resolve_flt_from_backlog_delegates_to_scope_gate(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog.md"
    backlog.write_text(
        "| Media | WOT-2026-157a | Files Likely Touched: `src.py` |\n",
        encoding="utf-8",
    )

    paths, error = verify_delivery.resolve_flt(
        tmp_path, [], ticket="WOT-2026-157a", backlog=backlog
    )

    assert error is None
    assert paths == {"src.py"}


def test_verify_delivery_rejects_diff_path_outside_flt(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    (repo / "outside.txt").write_text("outside\n", encoding="utf-8")
    _git(repo, "add", "outside.txt")
    _git(repo, "commit", "-qm", "outside")
    base = _git(repo, "rev-parse", "HEAD~1")

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=_runner_without_real_pytest
    )

    assert rc == 1
    assert receipt["steps"]["scope"]["cause"].startswith(
        "scope: diff path outside FLT:"
    )


def test_diff_path_failure_marks_dependent_steps_no_medido(
    tmp_path: Path,
) -> None:
    repo, base = _fixture_repo(tmp_path)

    def broken_diff_paths(command, **kwargs):
        if command[:3] == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(command, 128, b"", b"diff failed")
        return _runner_without_real_pytest(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo,
        base,
        flt=["src.py"],
        command_runner=broken_diff_paths,
    )

    assert rc == 1
    assert receipt["steps"]["scope"]["status"] == "NO_MEDIDO"
    for step_name in ("ruff", "encoding", "focal_tests"):
        step = receipt["steps"][step_name]
        assert step["status"] == "NO_MEDIDO"
        assert step["rc"] == 1
        assert step["command_rc"] == 128
        assert step["cause"] == "depends on diff paths (rc=128)"
    assert receipt["verdict"] == "RED"


def test_verify_delivery_marks_focal_runner_failure_fail(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    test_path = repo / "tests" / "unit" / "test_sample.py"
    test_path.write_text("def test_sample():\n    assert 1 == 2\n", encoding="utf-8")
    _git(repo, "add", str(test_path))
    _git(repo, "commit", "-qm", "broken focal")
    base = _git(repo, "rev-parse", "HEAD~1")

    def failed_runner(command, **kwargs):
        if any("run_pytest_safe.py" in str(part) for part in command):
            return subprocess.CompletedProcess(command, 1, "", "focal failed")
        return subprocess.run(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo,
        base,
        flt=["src.py", "tests/unit/test_sample.py"],
        command_runner=failed_runner,
    )

    assert rc == 1
    assert receipt["steps"]["focal_tests"]["status"] == "FAIL"
    assert receipt["steps"]["focal_tests"]["cause"] == ("focal_tests: test file failed")


def test_commits_count_rejects_an_extra_commit_with_exact_cause(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    (repo / "src.py").write_text("value = 3\n", encoding="utf-8")
    _git(repo, "add", "src.py")
    _git(repo, "commit", "-qm", "extra")

    rc, receipt = verify_delivery.measure_delivery(repo, base, flt=["src.py"])

    assert rc == 1
    assert receipt["steps"]["commits-count"]["status"] == "FAIL"
    assert receipt["steps"]["commits-count"]["rc"] == 1
    assert receipt["steps"]["commits-count"]["cause"] == (
        "commits-count: expected exactly 1 commit, got 2"
    )


def test_tree_dirty_reports_tracked_and_untracked_paths(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    (repo / "src.py").write_text("value = 99\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    rc, receipt = verify_delivery.measure_delivery(repo, base, flt=["src.py"])

    assert rc == 1
    assert receipt["steps"]["tree"]["status"] == "FAIL"
    assert "src.py" in receipt["steps"]["tree"]["cause"]
    assert "untracked.txt" in receipt["steps"]["tree"]["cause"]


def test_encoding_rejects_mojibake_and_names_the_file(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    mojibake = bytes.fromhex("636166c383c2a9").decode("utf-8")
    (repo / "docs.md").write_text(f"# Title\n\n{mojibake}\n", encoding="utf-8")
    _git(repo, "add", "docs.md")
    _git(
        repo,
        "commit",
        "-qm",
        "mojibake\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
    )
    base = _git(repo, "rev-parse", "HEAD~1")

    rc, receipt = verify_delivery.measure_delivery(
        repo,
        base,
        flt=["src.py", "docs.md"],
        command_runner=_runner_without_real_pytest,
    )

    assert rc == 1
    assert receipt["steps"]["encoding"]["status"] == "FAIL"
    assert "encoding: docs.md" in receipt["steps"]["encoding"]["cause"]


def test_encoding_clean_markdown_is_measured_and_passes(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    (repo / "docs.md").write_text("# Clean\n\nText.\n", encoding="utf-8")
    _git(repo, "add", "docs.md")
    _git(
        repo, "commit", "-qm", "docs\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    )
    base = _git(repo, "rev-parse", "HEAD~1")

    rc, receipt = verify_delivery.measure_delivery(
        repo,
        base,
        flt=["src.py", "docs.md"],
        command_runner=_runner_without_real_pytest,
    )

    assert rc == 0
    assert receipt["steps"]["encoding"]["status"] == "OK"
    assert receipt["steps"]["encoding"]["command_rc"] == 0


def test_focal_runner_failure_is_no_medido_when_process_cannot_start(
    tmp_path: Path,
) -> None:
    repo, base = _fixture_repo(tmp_path)
    test_path = repo / "tests" / "unit" / "test_sample.py"
    test_path.write_text("def test_sample():\n    assert 2 == 2\n", encoding="utf-8")
    _git(repo, "add", str(test_path))
    _git(
        repo, "commit", "-qm", "focal\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    )
    base = _git(repo, "rev-parse", "HEAD~1")

    def dead_runner(command, **kwargs):
        if any("run_pytest_safe.py" in str(part) for part in command):
            raise FileNotFoundError("runner unavailable")
        return subprocess.run(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo,
        base,
        flt=["src.py", "tests/unit/test_sample.py"],
        command_runner=dead_runner,
    )

    assert rc == 1
    assert receipt["steps"]["focal_tests"]["status"] == "NO_MEDIDO"
    assert receipt["steps"]["focal_tests"]["cause"] == (
        "focal_tests: runner could not start"
    )


def test_sha_change_between_measurements_is_fail_closed(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    calls = 0

    def unstable_runner(command, **kwargs):
        nonlocal calls
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            calls += 1
            if calls >= 3:
                return subprocess.CompletedProcess(command, 0, b"f" * 40 + b"\n", b"")
        return subprocess.run(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=unstable_runner
    )

    assert head != "f" * 40
    assert rc == 1
    assert receipt["steps"]["sha_stability"]["cause"] == (
        "sha-unstable: HEAD changed during measurement"
    )


def test_sha_start_rev_parse_failure_is_no_medido(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    calls = 0

    def broken_start(command, **kwargs):
        nonlocal calls
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            calls += 1
            if calls == 2:
                return subprocess.CompletedProcess(command, 128, b"", b"start failed")
        return subprocess.run(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=broken_start
    )

    assert rc == 1
    assert receipt["steps"]["sha_stability"]["cause"] == (
        "sha-stability: start rev-parse failed (rc=128)"
    )
    assert receipt["steps"]["sha_stability"]["command_rcs"] == {
        "start": 128,
        "base": 0,
        "end": 0,
    }


def test_sha_malformed_start_is_no_medido(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    calls = 0

    def malformed_start(command, **kwargs):
        nonlocal calls
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            calls += 1
            if calls == 2:
                return subprocess.CompletedProcess(command, 0, b"not-a-sha\n", b"")
        return subprocess.run(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=malformed_start
    )

    assert rc == 1
    assert receipt["steps"]["sha_stability"]["status"] == "NO_MEDIDO"
    assert receipt["steps"]["sha_stability"]["cause"] == (
        "sha-stability: start rev-parse returned invalid SHA (rc=0)"
    )
    assert receipt["steps"]["sha_stability"]["command_rcs"] == {
        "start": 0,
        "base": 0,
        "end": 0,
    }


def test_sha_base_rev_parse_failure_is_no_medido(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)

    def broken_base(command, **kwargs):
        if command == ["git", "rev-parse", base]:
            return subprocess.CompletedProcess(command, 128, b"", b"base failed")
        return subprocess.run(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=broken_base
    )

    assert rc == 1
    assert receipt["steps"]["sha_stability"]["cause"] == (
        "sha-stability: base rev-parse failed (rc=128)"
    )


def test_sha_end_rev_parse_failure_is_no_medido(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)
    calls = 0

    def broken_end(command, **kwargs):
        nonlocal calls
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            calls += 1
            if calls == 3:
                return subprocess.CompletedProcess(command, 128, b"", b"end failed")
        return subprocess.run(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=broken_end
    )

    assert rc == 1
    assert receipt["steps"]["sha_stability"]["cause"] == (
        "sha-stability: end rev-parse failed (rc=128)"
    )


def test_focal_argv_is_explicit_and_has_no_forbidden_suite_flags(
    tmp_path: Path,
) -> None:
    repo, base = _fixture_repo(tmp_path)
    test_path = repo / "tests" / "unit" / "test_sample.py"
    test_path.write_text("def test_sample():\n    assert 3 == 3\n", encoding="utf-8")
    _git(repo, "add", str(test_path))
    _git(
        repo, "commit", "-qm", "focal\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    )
    base = _git(repo, "rev-parse", "HEAD~1")
    commands = []

    def capture_runner(command, **kwargs):
        commands.append(list(command))
        return _runner_without_real_pytest(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo,
        base,
        flt=["src.py", "tests/unit/test_sample.py"],
        command_runner=capture_runner,
    )
    focal = next(
        command
        for command in commands
        if any(str(part).endswith("run_pytest_safe.py") for part in command)
    )

    assert rc == 0
    assert receipt["steps"]["commits-count"]["cause"].startswith("commits-count:")
    assert receipt["steps"]["focal_tests"]["status"] == "OK"
    assert receipt["steps"]["focal_tests"]["command_rcs"] == [0]
    assert "--wait-lock" in focal and "900" in focal
    assert "--" in focal and "tests/unit/test_sample.py" in focal
    assert not {"--level", "--select-from-diff", "--force-parallel"} & set(focal)


def test_ruff_absent_is_no_medido_and_global_verdict_is_red(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)

    def no_ruff(command, **kwargs):
        if command and command[0] == "ruff":
            raise FileNotFoundError("ruff unavailable")
        return _runner_without_real_pytest(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=no_ruff
    )

    assert rc == 1
    assert receipt["steps"]["ruff"]["status"] == "NO_MEDIDO"
    assert receipt["verdict"] == "RED"


def test_tree_status_command_rc_is_preserved(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)

    def broken_status(command, **kwargs):
        if command[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(command, 128, b"", b"status failed")
        return _runner_without_real_pytest(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=broken_status
    )

    assert rc == 1
    assert receipt["steps"]["tree"]["status"] == "NO_MEDIDO"
    assert receipt["steps"]["tree"]["command_rc"] == 128


def test_trailer_absent_has_exact_cause(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)

    def absent_trailer(command, **kwargs):
        if command[:3] == ["git", "log", "-1"]:
            return subprocess.CompletedProcess(command, 0, b"plain commit\n", b"")
        return _runner_without_real_pytest(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=absent_trailer
    )

    assert rc == 1
    assert receipt["steps"]["trailer"]["cause"] == (
        "trailer: required provider trailer missing"
    )


def test_trailer_model_version_has_exact_cause(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)

    def versioned_trailer(command, **kwargs):
        if command[:3] == ["git", "log", "-1"]:
            message = b"Co-Authored-By: Claude 5.5 <noreply@anthropic.com>\n"
            return subprocess.CompletedProcess(command, 0, message, b"")
        return _runner_without_real_pytest(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=versioned_trailer
    )

    assert rc == 1
    assert receipt["steps"]["trailer"]["status"] == "FAIL"
    assert (
        "trailer: model identity crystallization detected:"
        in receipt["steps"]["trailer"]["cause"]
    )


def test_trailer_crystallization_unavailable_is_no_medido(
    tmp_path: Path, monkeypatch
) -> None:
    repo, base = _fixture_repo(tmp_path)

    def unavailable(_message):
        raise ImportError("synthetic crystallization unavailable")

    monkeypatch.setattr(
        "scripts.check_model_id_crystallization.crystallization_issues", unavailable
    )
    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=_runner_without_real_pytest
    )

    assert rc == 1
    assert receipt["steps"]["trailer"]["status"] == "NO_MEDIDO"
    assert receipt["steps"]["trailer"]["command_rc"] == 0
    assert receipt["steps"]["trailer"]["cause"] == (
        "trailer: crystallization_issues unavailable or signature changed"
    )


def test_ruff_check_failure_preserves_command_rc(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)

    def bad_check(command, **kwargs):
        if command[:2] == ["ruff", "check"]:
            return subprocess.CompletedProcess(command, 7, b"", b"ruff check failed")
        return _runner_without_real_pytest(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=bad_check
    )

    assert rc == 1
    assert receipt["steps"]["ruff"]["status"] == "FAIL"
    assert receipt["steps"]["ruff"]["command_rcs"] == {"check": 7, "format": 0}


def test_ruff_format_failure_preserves_command_rc(tmp_path: Path) -> None:
    repo, base = _fixture_repo(tmp_path)

    def bad_format(command, **kwargs):
        if command[:3] == ["ruff", "format", "--check"]:
            return subprocess.CompletedProcess(command, 8, b"", b"ruff format failed")
        return _runner_without_real_pytest(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=bad_format
    )

    assert rc == 1
    assert receipt["steps"]["ruff"]["status"] == "FAIL"
    assert receipt["steps"]["ruff"]["command_rcs"] == {"check": 0, "format": 8}


def test_ruff_format_unavailable_preserves_check_rc_and_cause(
    tmp_path: Path,
) -> None:
    repo, base = _fixture_repo(tmp_path)

    def format_unavailable(command, **kwargs):
        if command[:2] == ["ruff", "check"]:
            return subprocess.CompletedProcess(command, 7, b"", b"ruff check failed")
        if command[:3] == ["ruff", "format", "--check"]:
            raise FileNotFoundError("ruff format unavailable")
        return _runner_without_real_pytest(command, **kwargs)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=["src.py"], command_runner=format_unavailable
    )

    assert rc == 1
    assert receipt["steps"]["ruff"]["status"] == "NO_MEDIDO"
    assert receipt["steps"]["ruff"]["command_rcs"] == {"check": 7}
    assert receipt["steps"]["ruff"]["cause"] == (
        "ruff: format unavailable after check rc=7"
    )


def test_absolute_flt_outside_worktree_returns_receipt_not_traceback(
    tmp_path: Path,
) -> None:
    repo, base = _fixture_repo(tmp_path)

    rc, receipt = verify_delivery.measure_delivery(
        repo, base, flt=[str(tmp_path / "outside.py")]
    )

    assert rc == 1
    assert receipt["steps"]["scope"]["status"] == "NO_MEDIDO"
    assert "scope: FLT path outside worktree" in receipt["steps"]["scope"]["cause"]
