"""
UI State Projector - Projects event bus state to UI JSON.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from bus.event_bus import EventBus


# WP-2026-122: Deferred path resolution via runtime.project_root
try:
    from runtime.project_root import resolve_project_root
except ImportError:
    # Fallback if runtime.project_root not available
    resolve_project_root = None


def _project_root() -> Path:
    if resolve_project_root is not None:
        return resolve_project_root()
    return Path(__file__).resolve().parents[1]


class UIStateProjector:
    def __init__(
        self,
        runtime_dir: Path | None = None,
        project_root: Path | None = None,
    ):
        root = Path(project_root) if project_root is not None else _project_root()
        self.project_root = root
        self.runtime_dir = Path(runtime_dir or (root / ".agent" / "runtime"))
        if runtime_dir is not None and project_root is None:
            self.project_root = self.runtime_dir.parents[1]
        self.ui_state_path = self.runtime_dir / "ui_state.json"
        self.collaboration_dir = self.project_root / ".agent" / "collaboration"
        self.turn_path = self.collaboration_dir / "TURN.md"
        self.event_bus = EventBus(runtime_dir=self.runtime_dir / "events")

    def _get_active_ticket_id(self) -> str:
        supervisor_state = self.runtime_dir / "supervisor_state.json"
        if supervisor_state.exists():
            try:
                data = json.loads(supervisor_state.read_text(encoding="utf-8"))
                active_ticket = str(data.get("active_ticket", "")).strip()
                if active_ticket and active_ticket != "NINGUNO":
                    return active_ticket
            except json.JSONDecodeError:
                pass

        if self.turn_path.exists():
            content = self.turn_path.read_text(encoding="utf-8")
            match = re.search(
                r"\|\s*\*\*Plan ID\*\*\s*\|\s*(WP-\d{4}-[A-Za-z0-9]+|NINGUNO)\s*\|",
                content,
            )
            if match:
                ticket = match.group(1)
                if ticket != "NINGUNO":
                    return ticket

        return "NINGUNO"

    def _get_plan_info(self) -> dict[str, str]:
        plan_id = "WP-2026-027"
        status = "COMPLETED"
        objective = "supervisor terminal-driven"
        return {
            "plan_id": plan_id,
            "status": status,
            "objective": objective,
        }

    def _get_ticket_status(self) -> dict[str, str]:
        active_ticket = self._get_active_ticket_id()
        log_status = ""
        if self.collaboration_dir.exists():
            execution_log = self.collaboration_dir / "execution_log.md"
            if execution_log.exists():
                content = execution_log.read_text(encoding="utf-8")
                match = re.search(r"\*\*Estado:\*\*\s*([A-Z_]+)", content)
                if match:
                    log_status = match.group(1)
        return {
            "plan_status": "COMPLETED" if active_ticket != "NINGUNO" else "N/A",
            "log_status": log_status or "READY_FOR_REVIEW",
        }

    def _get_current_turn(self) -> dict[str, str]:
        latest = self.event_bus.latest_event(event_type="TURN_CHANGED")
        if not latest:
            return {
                "role": "UNKNOWN",
                "plan_id": "NINGUNO",
                "action": "",
                "timestamp": "",
            }
        payload = latest.payload or {}
        return {
            "role": latest.actor,
            "plan_id": latest.ticket_id,
            "action": str(payload.get("action", "")),
            "timestamp": latest.timestamp,
        }

    def _get_recent_events(self, limit: int = 5) -> list[dict]:
        events = self.event_bus.read_events()
        return [event.to_dict() for event in events[-limit:]]

    def _get_recommended_files(self) -> list[str]:
        active_ticket = self._get_active_ticket_id()
        if active_ticket == "NINGUNO":
            return []
        execution_log = self.collaboration_dir / "execution_log.md"
        if not execution_log.exists():
            return []
        content = execution_log.read_text(encoding="utf-8")
        if "READY_FOR_REVIEW" in content or "READY_TO_CLOSE" in content:
            return ["work_plan.md", "execution_log.md"]
        return []

    def project_state(self) -> dict:
        return {
            "current_turn": self._get_current_turn(),
            "active_plan": self._get_plan_info(),
            "ticket_status": self._get_ticket_status(),
            "recent_events": self._get_recent_events(),
            "recommended_files": self._get_recommended_files(),
        }

    def update_ui_state(self) -> dict:
        self.ui_state_path.parent.mkdir(parents=True, exist_ok=True)
        state = self.project_state()
        self.ui_state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return state

    def validate_projection(self) -> bool:
        if not self.ui_state_path.exists():
            return False
        try:
            data = json.loads(self.ui_state_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return (
            isinstance(data, dict) and "current_turn" in data and "active_plan" in data
        )


def main(argv: list[str] | None = None) -> int:
    projector = UIStateProjector()
    projector.update_ui_state()
    print(json.dumps(projector.project_state(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
