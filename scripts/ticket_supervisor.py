#!/usr/bin/env python3
"""Run the sequential ticket supervisor for WP-2026-024..026.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# WOT-2026-070g (Eje 1): pre-parse --project-root BEFORE importing
# runtime.project_root, so resolve_project_root() sees the env var at
# import time (it uses lru_cache and falls back to motor root).
_pre_parser = argparse.ArgumentParser(add_help=False)
_pre_args, _ = _pre_parser.parse_known_args()
_pre_root = getattr(_pre_args, "project_root", None)
if _pre_root:
    os.environ["AGENT_PROJECT_ROOT"] = str(Path(_pre_root).resolve())


# Bootstrap: project root must be on sys.path before importing runtime.project_root.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
from runtime.project_root import resolve_project_root  # noqa: E402


_PROJECT_ROOT = resolve_project_root()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))


def _project_root() -> Path:
    """Return the resolved project root (cached for performance)."""
    return _PROJECT_ROOT


from bus.supervisor import (  # noqa: E402
    SequentialTicketSupervisor,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sequential ticket supervisor",
        add_help=True,
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Path to the destination workspace (project root). "
        "Required when running from the motor repo; without it the "
        "supervisor will fail with an actionable diagnostic instead of "
        "falling back to the motor's own .agent/ seed.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single supervision tick (default mode)",
    )
    parser.add_argument(
        "--reactive",
        action="store_true",
        help="Poll events for a limited time (acotado, safer than --loop)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Idle timeout in seconds for --reactive mode (default 300s / resets on activity)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously as a daemon (use with caution)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval used by --loop",
    )
    parser.add_argument(
        "--no-auto-sync",
        action="store_true",
        help="Do not invoke the controller automatically after ticket transitions",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # WOT-2026-070g (Eje 1): fail explicit when no project root is available.
    # Without --project-root / AGENT_PROJECT_ROOT the supervisor would fall
    # back to the motor root and write into the neutral seed.
    motor_root = Path(__file__).resolve().parent.parent
    if Path(_PROJECT_ROOT) == motor_root:
        tried_paths: list[str] = []
        # Try common workspace locations relative to cwd
        for _candidate in (
            Path(".").resolve() / "..",
            Path(".").resolve(),
        ):
            p = str(_candidate)
            if p not in tried_paths:
                tried_paths.append(p)
        raise SystemExit(
            f"[ticket-supervisor] ERROR: no project root resolved.\n"
            f"  --project-root was not provided and AGENT_PROJECT_ROOT is not set.\n"
            f"  Fallback resolved to the motor repo ({motor_root}).\n"
            f"  Tried paths: {', '.join(tried_paths)}\n"
            f"  Fix: pass --project-root <workspace> or set AGENT_PROJECT_ROOT\n"
            f"  before running this script."
        )

    supervisor = SequentialTicketSupervisor(
        project_root=_PROJECT_ROOT,
        auto_sync=not args.no_auto_sync,
    )

    if args.reactive:
        if not supervisor.bootstrap():
            print(
                "[ticket-supervisor] bootstrap rejected: another supervisor instance is active",
                file=sys.stderr,
                flush=True,
            )
            return 1
        state = supervisor.load_state()
        print(
            f"[ticket-supervisor] reactive mode start | active={state.active_ticket or 'NONE'} "
            f"| completed={len(state.completed_tickets)} | timeout={args.timeout}s",
            flush=True,
        )
        supervisor.run_reactive(timeout_seconds=args.timeout)
        return 0

    if args.loop:
        if not supervisor.bootstrap():
            print(
                "[ticket-supervisor] bootstrap rejected: another supervisor instance is active",
                file=sys.stderr,
                flush=True,
            )
            return 1
        state = supervisor.load_state()
        print(
            f"[ticket-supervisor] loop mode start | active={state.active_ticket or 'NONE'} "
            f"| completed={len(state.completed_tickets)} | poll={args.poll_interval}s",
            flush=True,
        )
        supervisor.run_loop(poll_interval=args.poll_interval)
        return 0

    # --once mode: acquire lock for single tick, then release
    if not supervisor.bootstrap():
        print(
            "[ticket-supervisor] once mode skipped: another supervisor instance is active",
            file=sys.stderr,
            flush=True,
        )
        return 1
    state = supervisor.load_state()
    print(
        f"[ticket-supervisor] once mode start | active={state.active_ticket or 'NONE'} "
        f"| completed={len(state.completed_tickets)}",
        flush=True,
    )
    try:
        changed = supervisor.run_once()
    finally:
        supervisor._release_supervisor_lock()
    if changed:
        print("[ticket-supervisor] once mode processed new events", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
