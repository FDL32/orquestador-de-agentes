from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class StatusBarIndicator:
    """Status bar indicator for UI state projection."""

    def __init__(self, runtime_dir: Path):
        """Initialize status bar indicator."""
        self.runtime_dir = runtime_dir
        self.ui_state_path = runtime_dir / "ui_state.json"
        self.status_bar_path = runtime_dir / "status_bar.json"

    def _read_ui_state(self) -> dict[str, Any] | None:
        """Read ui_state.json file."""
        if not self.ui_state_path.exists():
            return None
        try:
            return json.loads(self.ui_state_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _extract_status_info(self, ui_state: dict[str, Any]) -> dict[str, Any]:
        """Extract status information from ui_state."""
        current_turn = ui_state.get("current_turn", {})
        active_plan = ui_state.get("active_plan", {})

        return {
            "role": current_turn.get("role", "UNKNOWN"),
            "plan_id": current_turn.get(
                "plan_id", active_plan.get("plan_id", "NINGUNO")
            ),
            "action": current_turn.get("action", "NINGUNA"),
            "plan_status": active_plan.get("status", "DESCONOCIDO"),
            "timestamp": current_turn.get("timestamp", ""),
        }

    def update_status_bar(self) -> None:
        """Update status_bar.json with current state."""
        ui_state = self._read_ui_state()
        if ui_state:
            status_info = self._extract_status_info(ui_state)
        else:
            status_info = {
                "role": "UNKNOWN",
                "plan_id": "NINGUNO",
                "action": "NINGUNA",
                "plan_status": "DESCONOCIDO",
                "timestamp": "",
            }

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        with self.status_bar_path.open("w", encoding="utf-8") as f:
            json.dump(status_info, f, indent=2, ensure_ascii=False)

    def validate_status_bar(self) -> bool:
        """Validate that status bar file exists and has required fields."""
        if not self.status_bar_path.exists():
            return False

        try:
            data = json.loads(self.status_bar_path.read_text(encoding="utf-8"))
            required_fields = ["role", "plan_id", "action", "plan_status"]
            return all(field in data for field in required_fields)
        except Exception:
            return False
