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

# WT-2026-251a: canonical ticket ID pattern (accepts WP, WT, 3-letter prefixes)
from bus.ticket_id import TICKET_ID_PATTERN

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
from runtime.project_root import get_agent_dir, resolve_project_root


_PROJECT_ROOT = resolve_project_root()
_AGENT_DIR = get_agent_dir()
# WT-2026-251a: derived from TICKET_ID_PATTERN to accept 3-letter prefixes.
_PLAN_ID_PATTERN = re.compile(
    r"^-\s+\*\*ID:\*\*\s*(" + TICKET_ID_PATTERN + r"|none|NINGUNO)\s*$",
    re.MULTILINE,
)
_STATUS_PATTERN = re.compile(r"\*\*Estado:\*\*\s*([A-Z_]+)")
_TITLE_PATTERN = re.compile(
    r"^-\s+\*\*(?:Title|Titulo):\*\*\s*(.+?)\s*$",
    re.MULTILINE,
)
_OBJECTIVE_PATTERN = re.compile(
    r"^##\s+Objetivo\s*$\n(.+?)(?=\n##|\Z)",
    re.DOTALL | re.MULTILINE,
)


def _project_root() -> Path:
    """Return the resolved project root (cached for performance)."""
    return _PROJECT_ROOT


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

    def _read_collaboration_file(self, name: str) -> str:
        path = self.collaboration_dir / name
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

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

        plan_info = self._get_plan_info()
        if plan_info["plan_id"] != "NINGUNO":
            return plan_info["plan_id"]

        if self.turn_path.exists():
            content = self.turn_path.read_text(encoding="utf-8")
            # WT-2026-251a: derived from TICKET_ID_PATTERN to accept 3-letter prefixes.
            match = re.search(
                r"\|\s*\*\*(?:Plan|Ticket)\s*ID\*\*\s*\|\s*("
                + TICKET_ID_PATTERN
                + r"|NINGUNO)\s*\|",
                content,
            )
            if match:
                ticket = match.group(1)
                if ticket != "NINGUNO":
                    return ticket

        return "NINGUNO"

    def _get_plan_info(self) -> dict[str, str]:
        content = self._read_collaboration_file("work_plan.md")
        if not content:
            return {
                "plan_id": "NINGUNO",
                "status": "N/A",
                "objective": "",
            }

        plan_match = _PLAN_ID_PATTERN.search(content)
        status_match = _STATUS_PATTERN.search(content)
        title_match = _TITLE_PATTERN.search(content)
        objective_match = _OBJECTIVE_PATTERN.search(content)

        plan_id = plan_match.group(1) if plan_match else "NINGUNO"
        if plan_id.lower() == "none":
            plan_id = "NINGUNO"
        status = status_match.group(1) if status_match else "N/A"
        objective = ""
        if objective_match:
            objective = objective_match.group(1).strip().splitlines()[0].strip()
        elif title_match:
            objective = title_match.group(1).strip()

        return {
            "plan_id": plan_id,
            "status": status,
            "objective": objective,
        }

    def _get_ticket_status(self) -> dict[str, str]:
        plan_info = self._get_plan_info()
        execution_log = self._read_collaboration_file("execution_log.md")
        match = _STATUS_PATTERN.search(execution_log)
        log_status = match.group(1) if match else "N/A"
        return {
            "plan_status": plan_info["status"],
            "log_status": log_status,
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
        execution_log = self._read_collaboration_file("execution_log.md")
        if not execution_log:
            return []
        if "READY_FOR_REVIEW" in execution_log or "READY_TO_CLOSE" in execution_log:
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
