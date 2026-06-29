"""Mark a destination as adopted only after verifying setup gates.

The batch manifest treats `adopted=true` as permission to move from adoption to
Contract Formation. This script is the canonical writer for that flag: it fails
closed, records evidence, and only mutates the destination link when `--apply`
is provided.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SENSITIVE_PATTERNS = (
    ".env",
    ".env.*",
    "privada/*",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.xls",
    "*.xlsx",
    "*.csv",
    "*.dat",
)


@dataclass
class Check:
    name: str
    ok: bool
    evidence: dict[str, Any]
    blocking: bool = True


@dataclass
class AdoptionReport:
    project_root: Path
    motor_root: Path
    checks: list[Check] = field(default_factory=list)
    applied: bool = False
    link_path: Path | None = None

    @property
    def ok(self) -> bool:
        return all(check.ok or not check.blocking for check in self.checks)

    @property
    def blockers(self) -> list[str]:
        return [check.name for check in self.checks if check.blocking and not check.ok]

    def to_json(self) -> dict[str, Any]:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project_root": str(self.project_root),
            "motor_root": str(self.motor_root),
            "ok": self.ok,
            "applied": self.applied,
            "link_path": None if self.link_path is None else str(self.link_path),
            "blockers": self.blockers,
            "checks": [
                {
                    "name": check.name,
                    "ok": check.ok,
                    "blocking": check.blocking,
                    "evidence": check.evidence,
                }
                for check in self.checks
            ],
        }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _run(
    command: list[str], cwd: Path, env: dict[str, str] | None = None
) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _count_items(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        return sum(_count_items(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return 1


def _ticket_prefix(project_md: Path) -> str | None:
    if not project_md.exists():
        return None
    text = project_md.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(?im)^\s*Ticket prefix:\s*([A-Z][A-Z0-9]{1,9})\s*$", text)
    if not match:
        return None
    prefix = match.group(1)
    if prefix in {"XXX", "WOT"}:
        return None
    return prefix


def _active_profile(agents_json: Path) -> str | None:
    data = _read_json(agents_json)
    if data is None:
        return None
    value = data.get("active_profile")
    return str(value) if value is not None else None


def _is_allowed_sensitive_match(path: str) -> bool:
    """Allow safe templates that match broad sensitive globs."""
    normalized = path.replace("\\", "/")
    return normalized.endswith(".env.example") or normalized.endswith("/env.example")


def _validate_clean(stdout: str) -> tuple[bool, int, int, dict[str, Any] | None]:
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return False, 0, 0, None
    if not isinstance(payload, dict):
        return False, 0, 0, None
    errors = _count_items(payload.get("errors"))
    warnings = _count_items(payload.get("warnings"))
    return errors == 0, errors, warnings, payload


def evaluate_adoption(project_root: Path, motor_root: Path) -> AdoptionReport:
    project_root = project_root.resolve()
    motor_root = motor_root.resolve()
    report = AdoptionReport(project_root=project_root, motor_root=motor_root)
    link_path = project_root / ".agent/config/motor_destination_link.json"
    report.link_path = link_path

    link_data = _read_json(link_path)
    declared_motor = (
        None
        if link_data is None
        else link_data.get("motor_root")
        or link_data.get("MOTOR_ROOT")
        or link_data.get("repo_motor")
    )
    report.checks.append(
        Check(
            "motor_destination_link",
            link_data is not None
            and declared_motor is not None
            and Path(str(declared_motor)).resolve() == motor_root,
            {
                "type": "path+json",
                "path": str(link_path),
                "exists": link_path.exists(),
                "declared_motor_root": declared_motor,
                "expected_motor_root": str(motor_root),
                "adopted_field": None
                if link_data is None
                else link_data.get("adopted"),
            },
        )
    )

    profile = _active_profile(project_root / ".agent/config/agents.json")
    report.checks.append(
        Check(
            "host_project_profile",
            profile == "host-project",
            {
                "type": "path+json",
                "path": str(project_root / ".agent/config/agents.json"),
                "active_profile": profile,
            },
        )
    )

    prefix = _ticket_prefix(project_root / "PROJECT.md")
    report.checks.append(
        Check(
            "project_ticket_prefix",
            prefix is not None,
            {
                "type": "path+content",
                "path": str(project_root / "PROJECT.md"),
                "exists": (project_root / "PROJECT.md").exists(),
                "ticket_prefix": prefix,
            },
        )
    )

    git_status = _run(["git", "status", "--porcelain=v1"], cwd=project_root)
    report.checks.append(
        Check(
            "git_status_legible",
            git_status["exit_code"] == 0,
            {"type": "command", **git_status},
        )
    )

    tracked = _run(["git", "ls-files", *SENSITIVE_PATTERNS], cwd=project_root)
    tracked_files = [
        line
        for line in tracked["stdout"].splitlines()
        if line.strip() and not _is_allowed_sensitive_match(line.strip())
    ]
    report.checks.append(
        Check(
            "no_tracked_sensitive_or_data_files",
            tracked["exit_code"] == 0 and not tracked_files,
            {"type": "command", **tracked, "tracked_files": tracked_files},
        )
    )

    env = dict(os.environ)
    env["AGENT_PROJECT_ROOT"] = str(project_root)
    validate = _run(
        [
            "python",
            str(motor_root / ".agent/agent_controller.py"),
            "--validate",
            "--json",
            "--project-root",
            str(project_root),
        ],
        cwd=project_root,
        env=env,
    )
    validate_clean, errors, warnings, _payload = _validate_clean(
        str(validate.get("stdout") or "")
    )
    validate_ok = validate["exit_code"] == 0 and validate_clean
    report.checks.append(
        Check(
            "validate_zero_errors",
            validate["exit_code"] == 0 and validate_ok,
            {
                "type": "command",
                **validate,
                "errors_count": errors,
                "warnings_count": warnings,
            },
        )
    )

    memory = _run(
        ["python", str(motor_root / "scripts/memory_context.py"), "--status"],
        cwd=project_root,
        env=env,
    )
    combined = f"{memory.get('stdout', '')}\n{memory.get('stderr', '')}"
    report.checks.append(
        Check(
            "memory_points_to_destination",
            memory["exit_code"] == 0 and str(project_root) in combined,
            {"type": "command", **memory},
        )
    )

    return report


def mark_adopted(project_root: Path, motor_root: Path, apply: bool) -> AdoptionReport:
    report = evaluate_adoption(project_root, motor_root)
    if not apply or not report.ok:
        return report
    if report.link_path is None:
        return report
    data = _read_json(report.link_path)
    if data is None:
        return report
    data["adopted"] = True
    data["adopted_at"] = datetime.now(timezone.utc).isoformat()
    data["contract_formation_required"] = True
    data["adoption_verified_by"] = "scripts/mark_destination_adopted.py"
    _write_json(report.link_path, data)
    report.applied = True
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--motor-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write adopted=true when every gate passes.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = mark_adopted(args.project_root, args.motor_root, apply=args.apply)
    payload = report.to_json()
    _write_json(args.out, payload)
    print(
        json.dumps(
            {"ok": payload["ok"], "applied": payload["applied"], "out": str(args.out)},
            indent=2,
        )
    )
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
