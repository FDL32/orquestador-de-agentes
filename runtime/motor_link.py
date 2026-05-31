"""
Motor Link - Pure helper to resolve motor root/controller/script from motor_destination_link.json.

This module provides pure functions for resolving the external motor repository
location from the workspace's motor_destination_link.json file. It is the single
point of truth for Model B motor resolution across all bus components.

Before: Each component (review_bridge, supervisor, scripts) had its own private
        resolution logic, leading to duplication and drift.
During: Reads .agent/config/motor_destination_link.json from project_root,
        extracts motor_root, and resolves relative paths.
After: Returns Path or None for each resolution function.
"""

from __future__ import annotations

import json
from pathlib import Path


def resolve_motor_root(project_root: Path) -> Path | None:
    """Resolve motor root from workspace's motor_destination_link.json.

    Before: motor_destination_link.json must exist at
            project_root/.agent/config/motor_destination_link.json.
    During: Reads JSON, extracts motor_root, verifies it exists on disk.
    After: Returns absolute Path to the motor root, or None if link file is
           missing, malformed, or the motor_root path does not exist.

    Args:
        project_root: Absolute path to the destination project root.

    Returns:
        Absolute Path to the motor root directory, or None.
    """
    link_path = project_root / ".agent" / "config" / "motor_destination_link.json"
    if not link_path.exists():
        return None
    try:
        data = json.loads(link_path.read_text(encoding="utf-8"))
        motor_root = data.get("motor_root")
        if motor_root and Path(motor_root).exists():
            return Path(motor_root).resolve()
    except (json.JSONDecodeError, OSError):
        pass
    return None


def resolve_motor_controller(project_root: Path) -> Path | None:
    """Resolve agent_controller.py from external motor root.

    Before: motor_root must be resolvable via resolve_motor_root().
    During: Appends .agent/agent_controller.py to the motor root.
    After: Returns absolute Path to agent_controller.py, or None if the
           motor root is not resolvable or the file does not exist.

    Args:
        project_root: Absolute path to the destination project root.

    Returns:
        Absolute Path to the motor's agent_controller.py, or None.
    """
    motor_root = resolve_motor_root(project_root)
    if motor_root is None:
        return None
    controller = motor_root / ".agent" / "agent_controller.py"
    return controller if controller.exists() else None


def resolve_motor_script(project_root: Path, script_name: str) -> Path | None:
    """Resolve a script path from the external motor root.

    Before: motor_root must be resolvable via resolve_motor_root().
    During: Appends scripts/<script_name> to the motor root.
    After: Returns absolute Path to the script, or None if the motor root
           is not resolvable or the script does not exist.

    Args:
        project_root: Absolute path to the destination project root.
        script_name: Filename of the script (e.g., 'prepush_check.py').

    Returns:
        Absolute Path to the script in the motor repository, or None.
    """
    motor_root = resolve_motor_root(project_root)
    if motor_root is None:
        return None
    script = motor_root / "scripts" / script_name
    return script if script.exists() else None
