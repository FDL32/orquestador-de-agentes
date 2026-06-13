"""Detect unintended writes to repo_motor during destination pipelines.

Before:
    The caller has a repo_motor path and optionally a previous snapshot JSON.
During:
    The script reads git HEAD, status, and diff stats. It can also record a
    denied write attempt reported by an agent or harness.
After:
    It writes JSON evidence and never restores or mutates repo contents.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


def _now_iso() -> str:
    """Before: none. During: read clock. After: return UTC ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _git_executable() -> str:
    """Before: git must be on PATH. During: resolve binary. After: return path."""
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git executable not found in PATH")
    return git


def _run_git(
    motor_root: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Before: motor_root is a git repo. During: run git. After: return result."""
    return subprocess.run(  # noqa: S603
        [_git_executable(), *args],
        cwd=motor_root,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _lines(text: str) -> list[str]:
    """Before: text may be empty. During: split. After: non-empty stripped lines."""
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def _git_lines(motor_root: Path, *args: str) -> list[str]:
    """Before: git args are read-only. During: execute git. After: return lines."""
    return _lines(_run_git(motor_root, *args).stdout)


def capture_state(motor_root: Path) -> dict[str, Any]:
    """Capture immutable git evidence for repo_motor.

    Before:
        motor_root points to the portable motor repository.
    During:
        Reads HEAD, status, worktree diff stat, and cached diff stat.
    After:
        Returns a JSON-serializable snapshot. It never writes to the repo.
    """
    root = motor_root.resolve()
    head = _run_git(root, "rev-parse", "HEAD").stdout.strip()
    head_short = _run_git(root, "rev-parse", "--short=7", "HEAD").stdout.strip()
    status_short = _git_lines(root, "status", "--short")
    diff_stat = _git_lines(root, "diff", "--stat")
    cached_diff_stat = _git_lines(root, "diff", "--cached", "--stat")
    return {
        "motor_root": str(root),
        "head": head,
        "head_short": head_short,
        "status_short": status_short,
        "diff_stat": diff_stat,
        "cached_diff_stat": cached_diff_stat,
        "dirty": bool(status_short),
        "captured_at": _now_iso(),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Before: payload is JSON-safe. During: create parent. After: write UTF-8."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _read_json(path: Path) -> dict[str, Any]:
    """Before: path exists. During: parse JSON. After: return object dict."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def build_snapshot(motor_root: Path) -> dict[str, Any]:
    """Before: motor_root exists. During: capture. After: snapshot payload."""
    state = capture_state(motor_root)
    return {
        "event": "MOTOR_PRISTINE_SNAPSHOT",
        "motor_head_before": state["head"],
        "motor_head_before_short": state["head_short"],
        "motor_dirty_before": state["dirty"],
        "motor_status_before": state["status_short"],
        "motor_diff_stat_before": state["diff_stat"],
        "motor_cached_diff_stat_before": state["cached_diff_stat"],
        "motor_root": state["motor_root"],
        "captured_at": state["captured_at"],
    }


def build_check(motor_root: Path, before: dict[str, Any]) -> dict[str, Any]:
    """Before: before is a prior snapshot. During: capture after. After: report."""
    after = capture_state(motor_root)
    before_head = str(before.get("motor_head_before") or before.get("head") or "")
    before_short = str(
        before.get("motor_head_before_short")
        or before.get("head_short")
        or before_head[:7]
    )
    before_status = (
        before.get("motor_status_before") or before.get("status_short") or []
    )
    if not isinstance(before_status, list):
        before_status = []
    before_status_set = {str(item) for item in before_status}
    after_status_set = {str(item) for item in after["status_short"]}
    new_status_entries = sorted(after_status_set - before_status_set)
    resolved_status_entries = sorted(before_status_set - after_status_set)
    head_changed = bool(before_head and before_head != after["head"])
    dirty_detected = bool(new_status_entries or head_changed)
    event = "MOTOR_DIRTY_DETECTED" if dirty_detected else "MOTOR_PRISTINE_OK"
    return {
        "event": event,
        "motor_root": after["motor_root"],
        "motor_head_before": before_head,
        "motor_head_before_short": before_short,
        "motor_head_after": after["head"],
        "motor_head_after_short": after["head_short"],
        "motor_head_changed": head_changed,
        "pre_existing_dirty": sorted(before_status_set),
        "motor_status_new": new_status_entries,
        "motor_status_resolved": resolved_status_entries,
        "motor_dirty_after": after["dirty"],
        "motor_status_after": after["status_short"],
        "motor_diff_stat_after": after["diff_stat"],
        "motor_cached_diff_stat_after": after["cached_diff_stat"],
        "checked_at": after["captured_at"],
    }


def build_denied_attempt(
    motor_root: Path,
    report_path: Path,
    operation: str,
    path: str,
    reason: str,
    ticket: str | None,
) -> dict[str, Any]:
    """Before: an agent observed permission denial. During: append. After: report."""
    existing: dict[str, Any] = {}
    if report_path.exists():
        existing = _read_json(report_path)

    attempts = existing.get("denied_attempts", [])
    if not isinstance(attempts, list):
        attempts = []

    state = capture_state(motor_root)
    attempts.append(
        {
            "event": "MOTOR_WRITE_DENIED",
            "ticket": ticket,
            "operation": operation,
            "path": path,
            "reason": reason,
            "motor_head": state["head"],
            "motor_head_short": state["head_short"],
            "recorded_at": _now_iso(),
        }
    )

    payload = {
        **existing,
        "event": "MOTOR_WRITE_DENIED",
        "motor_root": state["motor_root"],
        "motor_head": state["head"],
        "motor_head_short": state["head_short"],
        "denied_attempts": attempts,
        "updated_at": _now_iso(),
    }
    return payload


def _print_payload(payload: dict[str, Any]) -> None:
    """Before: payload is JSON-safe. During: serialize. After: stdout JSON."""
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for motor pristine evidence.

    Before:
        Caller chooses exactly one mode: snapshot, check, or record-denied.
    During:
        Reads git evidence and optionally writes JSON report files.
    After:
        Returns 0 unless strict mode detects motor changes or a command fails.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motor-root", type=Path, default=ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--record-denied", action="store_true")
    parser.add_argument("--out", type=Path, help="Write snapshot JSON here")
    parser.add_argument("--snapshot-file", type=Path, help="Snapshot JSON for --check")
    parser.add_argument("--report", type=Path, help="Write check/denied JSON here")
    parser.add_argument(
        "--strict", action="store_true", help="Return non-zero on dirty motor"
    )
    parser.add_argument("--operation", default="write", help="Denied operation")
    parser.add_argument("--path", default="", help="Denied path")
    parser.add_argument("--reason", default="", help="Denied reason")
    parser.add_argument(
        "--ticket", default=None, help="Ticket associated with denied attempt"
    )
    args = parser.parse_args(argv)

    try:
        motor_root = args.motor_root.resolve()
        if args.snapshot:
            if not args.out:
                parser.error("--snapshot requires --out")
            payload = build_snapshot(motor_root)
            _write_json(args.out, payload)
            _print_payload(payload)
            return 0

        if args.check:
            if not args.snapshot_file or not args.report:
                parser.error("--check requires --snapshot-file and --report")
            payload = build_check(motor_root, _read_json(args.snapshot_file))
            _write_json(args.report, payload)
            _print_payload(payload)
            if args.strict and payload["event"] == "MOTOR_DIRTY_DETECTED":
                return 1
            return 0

        if args.record_denied:
            if not args.report or not args.path or not args.reason:
                parser.error("--record-denied requires --report, --path and --reason")
            payload = build_denied_attempt(
                motor_root=motor_root,
                report_path=args.report,
                operation=args.operation,
                path=args.path,
                reason=args.reason,
                ticket=args.ticket,
            )
            _write_json(args.report, payload)
            _print_payload(payload)
            return 0

    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"[check_motor_pristine] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
