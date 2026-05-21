from __future__ import annotations

import re
from pathlib import Path

from .event_bus import EventBus, EventRecord


class TurnWatcher:
    def __init__(self, collaboration_dir: Path, event_bus: EventBus):
        self.collaboration_dir = Path(collaboration_dir)
        self.event_bus = event_bus
        self._last_signature: str | None = None

    def _turn_path(self) -> Path:
        return self.collaboration_dir / "TURN.md"

    def _parse_value(self, content: str, label: str) -> str:
        pattern = rf"\*\*{re.escape(label)}\*\*\s*\|\s*\*{{0,2}}([^|]+?)\*{{0,2}}\s*\|"
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()
        if label in {"work_plan.md", "execution_log.md"}:
            row = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*([^|]+?)\s*\|", content)
            if row:
                return row.group(1).strip()
        return ""

    def publish_turn_event(self) -> EventRecord | None:
        turn_path = self._turn_path()
        if not turn_path.exists():
            return None

        content = turn_path.read_text(encoding="utf-8")
        signature = content.strip()
        if not signature or signature == self._last_signature:
            return None

        plan_id = self._parse_value(content, "Plan ID")
        role = self._parse_value(content, "ROL") or "BUILDER"
        action = self._parse_value(content, "Accion") or "IMPLEMENT"
        plan_status = self._parse_value(content, "work_plan.md")
        log_status = self._parse_value(content, "execution_log.md")
        if not plan_id:
            return None

        record = self.event_bus.emit(
            "TURN_CHANGED",
            ticket_id=plan_id,
            actor=role,
            payload={
                "action": action,
                "plan_status": plan_status,
                "log_status": log_status,
                "turn_path": str(turn_path),
            },
        )
        self._last_signature = signature
        return record
