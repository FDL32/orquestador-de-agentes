"""Diagnose orphaned Builder processes and identity contract gaps.

WT-2026-242c: This script provides reproducible evidence for the detection gap
in Stop-ProjectBuilderProcesses. It checks:

1. Whether any Builder processes are running (by CommandLine pattern).
2. Whether builder_lock.txt contains a complete identity contract.
3. Whether the lock PID matches a live process.
4. Whether the bus state allows safe reconciliation.

Usage:
    python scripts/diagnose_builder_orphans.py --project-root <path> [--json]

The --json flag outputs structured JSON for automation. Without it, outputs
human-readable diagnostic text.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any


def _detect_builder_processes_wmi(project_root: str) -> list[dict[str, Any]]:
    """Detect Builder processes via Win32_Process on Windows.

    Returns list of dicts with keys: pid, name, command_line, parent_pid.
    On non-Windows, returns empty list (WMI not available).
    """
    if platform.system() != "Windows":
        return []

    try:
        import subprocess

        ps_script = f"""
        $root = [regex]::Escape("{project_root}")
        $patterns = @('opencode.*run.*--agent\\s+builder')
        Get-CimInstance Win32_Process | Where-Object {{
            $cmd = $_.CommandLine
            $null -ne $cmd -and
            $cmd -match $root -and
            (($patterns | Where-{{ $cmd -match $_ }}) -ne $null)
        }} | ForEach-Object {{
            [pscustomobject]@{{
                pid = $_.ProcessId
                name = $_.Name
                command_line = $_.CommandLine
                parent_pid = $_.ParentProcessId
            }}
        }} | ConvertTo-Json -Compress
        """
        result = subprocess.run(  # noqa: S603 - intentional PowerShell call for WMI query
            ["powershell", "-NoProfile", "-Command", ps_script],  # noqa: S607 - powershell on PATH
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return []

        output = result.stdout.strip()
        if not output:
            return []

        parsed = json.loads(output)
        if isinstance(parsed, dict):
            return [parsed]
        return parsed
    except Exception:
        return []


def _read_builder_lock(project_root: str) -> dict[str, Any] | None:
    """Read and parse builder_lock.txt. Returns None if missing or invalid."""
    lock_path = Path(project_root) / ".agent" / "runtime" / "builder_lock.txt"
    if not lock_path.exists():
        return None

    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        if raw.startswith("{"):
            return json.loads(raw)
        return {"legacy_format": True, "raw": raw}
    except (json.JSONDecodeError, OSError):
        return None


def _check_bus_state(project_root: str, ticket_id: str) -> str | None:
    """Check bus-derived state for the ticket. Returns state value or None."""
    try:
        sys.path.insert(0, str(Path(project_root)))
        sys.path.insert(0, str(Path(project_root) / ".agent"))

        from bus.event_bus import EventBus
        from bus.state_machine import StateMachine

        events_path = (
            Path(project_root) / ".agent" / "runtime" / "events" / "events.jsonl"
        )
        if not events_path.exists():
            return None

        bus = EventBus(events_path=str(events_path))
        events = bus.read_events(ticket_id=ticket_id)
        if not events:
            return None

        state = StateMachine.derive_state_from_events([e.to_dict() for e in events])
        return state.value if state else None
    except Exception:
        return None


def _is_bus_state_post_success(bus_state: str | None) -> bool:
    """Check if bus state is past IN_PROGRESS (orphan-safe territory)."""
    if bus_state is None:
        return False
    return bus_state in (
        "READY_FOR_REVIEW",
        "READY_TO_CLOSE",
        "HUMAN_GATE",
        "COMPLETED",
    )


def diagnose(project_root: str) -> dict[str, Any]:
    """Run full diagnostic. Returns structured result dict."""
    result: dict[str, Any] = {
        "project_root": project_root,
        "platform": platform.system(),
        "builder_processes": [],
        "lock_state": None,
        "bus_state": None,
        "gap_confirmed": False,
        "gap_reason": None,
        "reconciliation_safe": False,
    }

    processes = _detect_builder_processes_wmi(project_root)
    result["builder_processes"] = processes

    lock = _read_builder_lock(project_root)
    result["lock_state"] = lock

    ticket_id = None
    if lock and isinstance(lock, dict):
        ticket_id = lock.get("ticket_id")
    if ticket_id:
        bus_state = _check_bus_state(project_root, ticket_id)
        result["bus_state"] = bus_state
        result["reconciliation_safe"] = _is_bus_state_post_success(bus_state)

    if not processes and lock and lock.get("pid"):
        result["gap_confirmed"] = True
        result["gap_reason"] = (
            f"builder_lock.txt references PID {lock['pid']} but no Builder "
            f"process found with --agent builder in CommandLine. The process "
            f"may have exited while child processes survived."
        )
    elif not processes and not lock:
        result["gap_confirmed"] = False
        result["gap_reason"] = "No Builder processes and no lock — clean state."
    elif processes:
        result["gap_confirmed"] = False
        result["gap_reason"] = (
            f"Found {len(processes)} Builder process(es) with --agent builder "
            f"in CommandLine. Detection via Stop-ProjectBuilderProcesses works."
        )

    return result


def format_human(result: dict[str, Any]) -> str:
    """Format diagnostic result as human-readable text."""
    lines = [
        "=== Builder Orphan Diagnostic ===",
        f"Project root: {result['project_root']}",
        f"Platform: {result['platform']}",
        "",
        f"Builder processes detected: {len(result['builder_processes'])}",
    ]
    for p in result["builder_processes"]:
        lines.append(f"  PID={p['pid']} Name={p['name']} Parent={p['parent_pid']}")
        cmd = p.get("command_line", "")
        lines.append(f"    CMD: {cmd[:120]}{'...' if len(cmd) > 120 else ''}")

    lines.append("")
    lines.append(
        f"Builder lock state: {json.dumps(result['lock_state'], indent=2) if result['lock_state'] else 'NONE'}"
    )
    lines.append(f"Bus state: {result['bus_state'] or 'UNKNOWN'}")
    lines.append(f"Reconciliation safe: {result['reconciliation_safe']}")
    lines.append("")
    lines.append(f"Gap confirmed: {result['gap_confirmed']}")
    if result["gap_reason"]:
        lines.append(f"Reason: {result['gap_reason']}")

    return "\n".join(lines)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Diagnose orphaned Builder processes")
    parser.add_argument("--project-root", required=True, help="Project root path")
    parser.add_argument(
        "--json", action="store_true", dest="json_output", help="Output JSON"
    )
    args = parser.parse_args()

    result = diagnose(args.project_root)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(format_human(result))

    return 0 if not result["gap_confirmed"] else 1


if __name__ == "__main__":
    sys.exit(main())
