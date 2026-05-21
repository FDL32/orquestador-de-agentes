#!/usr/bin/env python3
"""Run the sequential ticket supervisor for WP-2026-024..026."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = PROJECT_ROOT / ".agent"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from bus.supervisor import (  # noqa: E402
    SequentialTicketSupervisor,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sequential ticket supervisor")
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
    supervisor = SequentialTicketSupervisor(
        project_root=PROJECT_ROOT,
        auto_sync=not args.no_auto_sync,
    )

    if args.reactive:
        supervisor.bootstrap()
        state = supervisor.load_state()
        print(
            f"[ticket-supervisor] reactive mode start | active={state.active_ticket or 'NONE'} "
            f"| completed={len(state.completed_tickets)} | timeout={args.timeout}s",
            flush=True,
        )
        supervisor.run_reactive(timeout_seconds=args.timeout)
        return 0

    if args.loop:
        supervisor.bootstrap()
        state = supervisor.load_state()
        print(
            f"[ticket-supervisor] loop mode start | active={state.active_ticket or 'NONE'} "
            f"| completed={len(state.completed_tickets)} | poll={args.poll_interval}s",
            flush=True,
        )
        supervisor.run_loop(poll_interval=args.poll_interval)
        return 0

    supervisor.bootstrap()
    state = supervisor.load_state()
    print(
        f"[ticket-supervisor] once mode start | active={state.active_ticket or 'NONE'} "
        f"| completed={len(state.completed_tickets)}",
        flush=True,
    )
    changed = supervisor.run_once()
    if changed:
        print("[ticket-supervisor] once mode processed new events", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
