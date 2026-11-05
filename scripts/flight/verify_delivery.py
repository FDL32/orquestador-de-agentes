"""Measure an implementation delivery and emit a machine-readable receipt.

Before: the caller supplies an existing worktree, an ancestor base commit, and
an explicit FLT or a ticket/backlog pair. During: subprocesses run with argv
lists and no shell; every measurement is retained with its literal return
code. After: the CLI prints a human summary and JSON, returning 0 only for a
green delivery, 1 for FAIL/NO_MEDIDO, or 2 for invalid input.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PYTHON = sys.executable
_TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    runner=subprocess.run,
) -> subprocess.CompletedProcess:
    """Run one argv command without a shell.

    Before: command contains executable and arguments, and cwd is a directory.
    During: delegates to the injected runner with captured byte streams.
    After: returns the runner result unchanged; OS launch errors propagate to
    the caller so the corresponding step can become NO_MEDIDO.
    """
    return runner(list(command), cwd=cwd, capture_output=True, text=False, check=False)


def _step(status: str, rc: int | None, cause: str, **details: Any) -> dict[str, Any]:
    """Build one receipt step with a stable status, rc, and exact cause."""
    return {"status": status, "rc": rc, "cause": cause, **details}


def _decode(data: bytes | str) -> str:
    return data if isinstance(data, str) else data.decode("utf-8", errors="replace")


def _git_bytes(
    repo: Path, args: Sequence[str], *, runner=subprocess.run
) -> subprocess.CompletedProcess:
    return _run(["git", *args], cwd=repo, runner=runner)


def _validate_input(
    repo: Path, base: str, *, runner=subprocess.run
) -> dict[str, Any] | None:
    """Validate worktree and base before measurements.

    Before: repo and base are raw CLI values.
    During: verifies the directory, resolves the base commit, and checks that
    it is an ancestor of the current HEAD.
    After: returns None when valid, otherwise a receipt step whose cause names
    the invalid input and whose rc is 2.
    """
    if not repo.is_dir():
        return _step("FAIL", 2, "input: worktree does not exist")
    base_result = _git_bytes(
        repo, ["rev-parse", "--verify", f"{base}^{{commit}}"], runner=runner
    )
    if base_result.returncode != 0:
        return _step(
            "FAIL",
            2,
            "input: base is not a valid commit",
            stderr=_decode(base_result.stderr),
        )
    head_result = _git_bytes(repo, ["rev-parse", "HEAD"], runner=runner)
    if head_result.returncode != 0:
        return _step(
            "FAIL",
            2,
            "input: HEAD is not a valid commit",
            stderr=_decode(head_result.stderr),
        )
    ancestor = _git_bytes(
        repo, ["merge-base", "--is-ancestor", base, "HEAD"], runner=runner
    )
    if ancestor.returncode != 0:
        return _step(
            "FAIL",
            2,
            "input: base is not an ancestor of HEAD",
            stderr=_decode(ancestor.stderr),
        )
    return None


def _load_scope_gate() -> Any:
    path = ROOT / ".agent" / "scope_gate.py"
    spec = importlib.util.spec_from_file_location("verify_delivery_scope_gate", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load scope_gate from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _backlog_row(backlog: Path, ticket: str) -> str:
    """Extract one backlog row without parsing its FLT tokens locally.

    Before: backlog exists and contains the requested ticket.
    During: joins the physical lines belonging to that markdown row, then
    presents only its Files Likely Touched fragment to scope_gate.
    After: returns the synthetic work-plan text consumed by scope_gate, or
    raises ValueError when the ticket/source is absent.
    """
    try:
        lines = backlog.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"backlog: cannot read source ({exc})") from exc
    marker = re.compile(rf"^\|\s*[^|]+\|\s*{re.escape(ticket)}\s*\|")
    start = next(
        (index for index, line in enumerate(lines) if marker.search(line)), None
    )
    if start is None:
        raise ValueError("backlog: ticket row not found")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^\|\s*[^|]+\|\s*WOT-\d{4}-\d+[a-z]\s*\|", lines[index]):
            end = index
            break
    row = " ".join(line.strip() for line in lines[start:end])
    match = re.search(
        r"Files Likely Touched:\s*(.*?)(?:\s+deliverable_type:|\s+Origen-confirmado:|$)",
        row,
    )
    if not match:
        raise ValueError("backlog: Files Likely Touched section is absent")
    return "## Files Likely Touched\n" + match.group(1).replace(" - ", "\n- ")


def resolve_flt(
    repo: Path,
    flt: Sequence[str],
    *,
    ticket: str | None = None,
    backlog: Path | None = None,
) -> tuple[set[str], str | None]:
    """Resolve the explicit FLT or delegate backlog parsing to scope_gate.

    Before: explicit paths and/or ticket/backlog are supplied by the caller.
    During: normalizes explicit paths and, for backlog mode, invokes the
    canonical scope_gate parser on the extracted row text.
    After: returns normalized relative paths and an error cause, without
    silently treating an empty source as green.
    """
    explicit = {
        path.replace("\\", "/").removeprefix("./") for path in flt if path.strip()
    }
    if explicit:
        return explicit, None
    if bool(ticket) != bool(backlog):
        return set(), "flt: ticket and backlog must be supplied together"
    if ticket and backlog:
        try:
            content = _backlog_row(backlog, ticket)
            parser = _load_scope_gate()
            paths = parser.parse_flt_raw_paths(
                content,
                delivery_authority="repo_motor",
                target="authority",
                deliverable_type="code",
            )
            return set(paths), None if paths else "flt: source resolved to an empty FLT"
        except (ImportError, OSError, ValueError, AttributeError) as exc:
            return set(), f"flt: cannot resolve backlog source ({exc})"
    return set(), "flt: no source provided"


def _relative_bytes(repo: Path, paths: set[str]) -> set[bytes]:
    result: set[bytes] = set()
    for raw in paths:
        candidate = Path(raw)
        if candidate.is_absolute():
            candidate = candidate.resolve().relative_to(repo.resolve())
        result.add(os.fsencode(candidate.as_posix()))
    return result


def _nul_paths(data: bytes) -> set[bytes]:
    return {item for item in data.split(b"\0") if item}


def _sha_text(
    result: subprocess.CompletedProcess, label: str
) -> tuple[str, str | None]:
    """Validate one rev-parse result and return its SHA or an exact failure."""
    value = _decode(result.stdout).strip()
    if result.returncode != 0:
        return "", f"sha-stability: {label} rev-parse failed (rc={result.returncode})"
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        return (
            "",
            f"sha-stability: {label} rev-parse returned invalid SHA (rc={result.returncode})",
        )
    return value, None


def _added_lines(diff: bytes) -> str:
    lines = [
        _decode(line[1:])
        for line in diff.splitlines()
        if line.startswith(b"+") and not line.startswith(b"+++")
    ]
    return "\n".join(lines)


def _measure_entropy(text: str) -> tuple[str, int | None, str]:
    try:
        from scripts.ensemble_dispatch import _entropy_leak

        hit = _entropy_leak(text)
    except (ImportError, AttributeError, TypeError):
        return (
            "NO_MEDIDO",
            1,
            "entropy: _entropy_leak unavailable or signature changed",
        )
    if hit:
        return "FAIL", 1, f"entropy: {_decode(str(hit).encode('utf-8'))}"
    return "OK", 0, "entropy: no opaque secret detected"


def _measure_focal(
    repo: Path,
    test_path: str,
    *,
    runner,
    python_executable: str,
) -> subprocess.CompletedProcess | None:
    try:
        return _run(
            [
                python_executable,
                str(ROOT / "scripts" / "run_pytest_safe.py"),
                "--wait-lock",
                "900",
                "--",
                test_path,
            ],
            cwd=repo,
            runner=runner,
        )
    except OSError:
        return None


def measure_delivery(  # noqa: C901
    worktree: Path,
    base: str,
    *,
    flt: Sequence[str] = (),
    ticket: str | None = None,
    backlog: Path | None = None,
    receipt: Path | None = None,
    command_runner=subprocess.run,
    python_executable: str = DEFAULT_PYTHON,
) -> tuple[int, dict[str, Any]]:
    """Measure all delivery gates and return ``(rc, receipt)``.

    Before: worktree, base, and FLT source are available; receipt, when set,
    is outside the measured worktree.
    During: measures commits, trailer, tree, byte-exact scope, Ruff, encoding,
    added-line entropy, focal tests, and start/end SHA with fail-closed steps.
    After: returns rc 0 only when every applicable step is OK; NA focal tests
    are explicit and do not fail a diff without test files. No receipt is
    written by this function.
    """
    repo = Path(worktree).resolve()
    steps: dict[str, dict[str, Any]] = {}
    invalid = _validate_input(repo, base, runner=command_runner)
    if invalid:
        steps["input"] = invalid
        return 2, {"verdict": "RED", "steps": steps}
    if receipt is not None and Path(receipt).resolve().is_relative_to(repo):
        steps["receipt"] = _step("FAIL", 2, "receipt: path is inside measured worktree")
        return 2, {"verdict": "RED", "steps": steps}

    head_start_result = _git_bytes(repo, ["rev-parse", "HEAD"], runner=command_runner)
    base_result = _git_bytes(repo, ["rev-parse", base], runner=command_runner)
    head_start, head_start_error = _sha_text(head_start_result, "start")
    base_sha, base_error = _sha_text(base_result, "base")
    sha_errors = [error for error in (head_start_error, base_error) if error]

    flt_paths, flt_error = resolve_flt(repo, flt, ticket=ticket, backlog=backlog)
    if flt_error:
        steps["flt"] = _step("NO_MEDIDO", 1, flt_error)
    else:
        steps["flt"] = _step("OK", 0, "flt: source resolved", paths=sorted(flt_paths))

    count = _git_bytes(
        repo, ["rev-list", "--count", f"{base}..HEAD"], runner=command_runner
    )
    count_value = _decode(count.stdout).strip()
    if count.returncode != 0:
        steps["commits-count"] = _step(
            "NO_MEDIDO",
            1,
            f"commits-count: count command failed (rc={count.returncode})",
            command_rc=count.returncode,
        )
    elif count_value != "1":
        steps["commits-count"] = _step(
            "FAIL",
            1,
            f"commits-count: expected exactly 1 commit, got {count_value}",
            command_rc=count.returncode,
        )
    else:
        steps["commits-count"] = _step(
            "OK", 0, "commits-count: exactly 1 commit", command_rc=count.returncode
        )

    log = _git_bytes(repo, ["log", "-1", "--format=%B"], runner=command_runner)
    try:
        from scripts.check_model_id_crystallization import crystallization_issues

        trailer_issues = crystallization_issues(_decode(log.stdout))
    except (ImportError, AttributeError, TypeError):
        trailer_issues = None
    if log.returncode != 0:
        steps["trailer"] = _step(
            "NO_MEDIDO",
            1,
            f"trailer: git log failed (rc={log.returncode})",
            command_rc=log.returncode,
        )
    elif trailer_issues is None:
        steps["trailer"] = _step(
            "NO_MEDIDO",
            1,
            "trailer: crystallization_issues unavailable or signature changed",
            command_rc=log.returncode,
        )
    elif trailer_issues:
        steps["trailer"] = _step(
            "FAIL",
            1,
            f"trailer: model identity crystallization detected: {trailer_issues[0]}",
            command_rc=log.returncode,
        )
    elif _TRAILER not in _decode(log.stdout):
        steps["trailer"] = _step(
            "FAIL",
            1,
            "trailer: required provider trailer missing",
            command_rc=log.returncode,
        )
    else:
        steps["trailer"] = _step(
            "OK", 0, "trailer: provider trailer is valid", command_rc=log.returncode
        )

    status = _git_bytes(repo, ["status", "--porcelain=v1", "-z"], runner=command_runner)
    if status.returncode != 0:
        steps["tree"] = _step(
            "NO_MEDIDO",
            1,
            f"tree: git status failed (rc={status.returncode})",
            command_rc=status.returncode,
        )
    elif status.stdout:
        dirty = [
            _decode(item)[3:] if len(item) >= 3 else _decode(item)
            for item in status.stdout.split(b"\0")
            if item
        ]
        steps["tree"] = _step(
            "FAIL",
            1,
            f"tree: worktree is dirty: {sorted(dirty)}",
            command_rc=status.returncode,
        )
    else:
        steps["tree"] = _step(
            "OK", 0, "tree: worktree is clean", command_rc=status.returncode
        )

    changed = _git_bytes(
        repo, ["diff", "--name-only", "-z", f"{base}..HEAD"], runner=command_runner
    )
    changed_paths = _nul_paths(changed.stdout)
    if changed.returncode != 0:
        steps["scope"] = _step(
            "NO_MEDIDO",
            1,
            f"scope: diff paths could not be measured (rc={changed.returncode})",
            command_rc=changed.returncode,
        )
        paths_unmeasured_cause = f"depends on diff paths (rc={changed.returncode})"
        steps["ruff"] = _step(
            "NO_MEDIDO",
            1,
            paths_unmeasured_cause,
            command_rc=changed.returncode,
        )
        steps["encoding"] = _step(
            "NO_MEDIDO",
            1,
            paths_unmeasured_cause,
            command_rc=changed.returncode,
        )
        steps["focal_tests"] = _step(
            "NO_MEDIDO",
            1,
            paths_unmeasured_cause,
            command_rc=changed.returncode,
        )
    elif not flt_paths:
        steps["scope"] = _step("NO_MEDIDO", 1, "scope: FLT is empty")
    else:
        try:
            flt_bytes = _relative_bytes(repo, flt_paths)
        except (ValueError, OSError) as exc:
            steps["scope"] = _step(
                "NO_MEDIDO",
                1,
                f"scope: FLT path outside worktree ({exc})",
                command_rc=changed.returncode,
            )
        else:
            if changed_paths <= flt_bytes:
                steps["scope"] = _step(
                    "OK",
                    0,
                    "scope: every diff path is inside FLT",
                    command_rc=changed.returncode,
                )
            else:
                outside = sorted(_decode(item) for item in changed_paths - flt_bytes)
                steps["scope"] = _step(
                    "FAIL",
                    1,
                    f"scope: diff path outside FLT: {outside}",
                    command_rc=changed.returncode,
                )

    py_paths = sorted(_decode(path) for path in changed_paths if path.endswith(b".py"))
    if changed.returncode != 0:
        pass
    elif py_paths:
        command_rcs: dict[str, int] = {}
        try:
            check = _run(["ruff", "check", *py_paths], cwd=repo, runner=command_runner)
            command_rcs["check"] = check.returncode
        except OSError:
            steps["ruff"] = _step(
                "NO_MEDIDO", 1, "ruff: check unavailable", command_rcs=command_rcs
            )
        else:
            try:
                fmt = _run(
                    ["ruff", "format", "--check", *py_paths],
                    cwd=repo,
                    runner=command_runner,
                )
                command_rcs["format"] = fmt.returncode
            except OSError:
                steps["ruff"] = _step(
                    "NO_MEDIDO",
                    1,
                    f"ruff: format unavailable after check rc={check.returncode}",
                    command_rcs=command_rcs,
                )
            else:
                if check.returncode == 0 and fmt.returncode == 0:
                    steps["ruff"] = _step(
                        "OK",
                        0,
                        "ruff: check and format check passed",
                        command_rcs=command_rcs,
                    )
                else:
                    failed = []
                    if check.returncode != 0:
                        failed.append(f"check rc={check.returncode}")
                    if fmt.returncode != 0:
                        failed.append(f"format rc={fmt.returncode}")
                    steps["ruff"] = _step(
                        "FAIL",
                        1,
                        f"ruff: {'; '.join(failed)}",
                        command_rcs=command_rcs,
                    )
    else:
        steps["ruff"] = _step("OK", 0, "ruff: no Python files in diff")

    all_paths = sorted(_decode(path) for path in changed_paths)
    if changed.returncode != 0:
        pass
    elif all_paths:
        try:
            encoding = _run(
                [
                    python_executable,
                    str(ROOT / "scripts" / "check_encoding_guard.py"),
                    *all_paths,
                ],
                cwd=repo,
                runner=command_runner,
            )
        except OSError:
            steps["encoding"] = _step("NO_MEDIDO", 1, "encoding: guard unavailable")
        else:
            steps["encoding"] = (
                _step(
                    "OK",
                    0,
                    "encoding: explicit paths passed",
                    command_rc=encoding.returncode,
                )
                if encoding.returncode == 0
                else _step(
                    "FAIL",
                    1,
                    f"encoding: {', '.join(all_paths)} rejected explicit paths",
                    command_rc=encoding.returncode,
                )
            )
    else:
        steps["encoding"] = _step("OK", 0, "encoding: no files in diff")

    entropy_diff = _git_bytes(
        repo,
        ["diff", "--unified=0", "--no-ext-diff", "-z", f"{base}..HEAD"],
        runner=command_runner,
    )
    entropy_status, entropy_rc, entropy_cause = (
        _measure_entropy(_added_lines(entropy_diff.stdout))
        if entropy_diff.returncode == 0
        else ("NO_MEDIDO", 1, "entropy: diff could not be measured")
    )
    steps["entropy"] = _step(
        entropy_status, entropy_rc, entropy_cause, command_rc=entropy_diff.returncode
    )

    test_paths = [
        path for path in py_paths if path.replace("\\", "/").startswith("tests/")
    ]
    if changed.returncode != 0:
        pass
    elif not test_paths:
        steps["focal_tests"] = _step(
            "NA", 0, "focal_tests: N/A, diff has no test files"
        )
    else:
        focal_results = [
            _measure_focal(
                repo, path, runner=command_runner, python_executable=python_executable
            )
            for path in test_paths
        ]
        if all(
            result is not None and result.returncode == 0 for result in focal_results
        ):
            steps["focal_tests"] = _step(
                "OK",
                0,
                "focal_tests: every test file passed",
                files=test_paths,
                command_rcs=[result.returncode for result in focal_results],
            )
        elif any(result is None for result in focal_results):
            steps["focal_tests"] = _step(
                "NO_MEDIDO",
                1,
                "focal_tests: runner could not start",
                files=test_paths,
                command_rcs=[
                    None if result is None else result.returncode
                    for result in focal_results
                ],
            )
        elif any(result.returncode == 1 for result in focal_results):
            steps["focal_tests"] = _step(
                "FAIL",
                1,
                "focal_tests: test file failed",
                files=test_paths,
                rcs=[result.returncode for result in focal_results],
                command_rcs=[result.returncode for result in focal_results],
            )
        else:
            steps["focal_tests"] = _step(
                "NO_MEDIDO",
                1,
                "focal_tests: runner could not execute a test file",
                files=test_paths,
                rcs=[
                    result.returncode for result in focal_results if result is not None
                ],
                command_rcs=[
                    result.returncode for result in focal_results if result is not None
                ],
            )

    head_end_result = _git_bytes(repo, ["rev-parse", "HEAD"], runner=command_runner)
    head_end, head_end_error = _sha_text(head_end_result, "end")
    if head_end_error:
        sha_errors.append(head_end_error)
    sha_command_rcs = {
        "start": head_start_result.returncode,
        "base": base_result.returncode,
        "end": head_end_result.returncode,
    }
    if sha_errors:
        steps["sha_stability"] = _step(
            "NO_MEDIDO", 1, "; ".join(sha_errors), command_rcs=sha_command_rcs
        )
    else:
        steps["sha_stability"] = (
            _step(
                "OK",
                0,
                "sha_stability: HEAD unchanged",
                command_rcs=sha_command_rcs,
            )
            if head_start == head_end
            else _step(
                "FAIL",
                1,
                "sha-unstable: HEAD changed during measurement",
                command_rcs=sha_command_rcs,
            )
        )
    bad = [
        key for key, value in steps.items() if value["status"] in {"FAIL", "NO_MEDIDO"}
    ]
    verdict = "GREEN" if not bad else "RED"
    rc = 0 if verdict == "GREEN" else 1
    return rc, {
        "verdict": verdict,
        "rc": rc,
        "head_sha_start": head_start,
        "head_sha_end": head_end,
        "base_sha": base_sha,
        "steps": steps,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worktree", type=Path)
    parser.add_argument("base")
    parser.add_argument("--flt", action="append", default=[])
    parser.add_argument("--ticket")
    parser.add_argument("--backlog", type=Path)
    parser.add_argument("--receipt", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, print its human summary and JSON, and return its rc."""
    args = _parser().parse_args(argv)
    if bool(args.ticket) != bool(args.backlog):
        payload = {
            "verdict": "RED",
            "steps": {
                "input": _step(
                    "FAIL", 2, "input: --ticket and --backlog must be supplied together"
                )
            },
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2
    rc, payload = measure_delivery(
        args.worktree,
        args.base,
        flt=args.flt,
        ticket=args.ticket,
        backlog=args.backlog,
        receipt=args.receipt,
        python_executable=DEFAULT_PYTHON,
    )
    if args.receipt and rc != 2:
        try:
            rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            args.receipt.write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            rc = 1
            payload = {
                "verdict": "RED",
                "rc": rc,
                "steps": {
                    "receipt": _step(
                        "FAIL",
                        rc,
                        f"receipt: cannot write receipt ({exc})",
                        command_rc=rc,
                    )
                },
            }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"verdict={payload['verdict']} rc={rc}")
    print(rendered)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
