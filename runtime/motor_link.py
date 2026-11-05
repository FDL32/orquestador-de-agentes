"""
Motor Link - Pure helper to resolve motor root/controller/script from motor_destination_link.json.

This module provides pure functions for resolving the external motor repository
location from the workspace's motor_destination_link.json file. It is the single
point of truth for external-motor topology resolution across all bus components.

Before: Each component (review_bridge, supervisor, scripts) had its own private
        resolution logic, leading to duplication and drift.
During: Reads .agent/config/motor_destination_link.json from project_root,
        extracts motor_root, and resolves relative paths.
After: Returns Path or None for each resolution function.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple


LINK_OK = "OK"
LINK_MISSING = "MISSING"
LINK_UNREADABLE = "UNREADABLE"


class MotorLinkRead(NamedTuple):
    """Outcome of ``read_motor_link``: ``state`` is one of the three ``LINK_*`` values.

    ``data`` is the parsed object only for ``LINK_OK``. ``reason`` is set only for
    ``LINK_UNREADABLE`` and starts with the cause: ``decode``, ``json``,
    ``not-a-dict`` or ``io``.
    """

    state: str
    data: dict | None = None
    reason: str | None = None


def read_motor_link(link_path: Path) -> MotorLinkRead:
    """Read a motor_destination_link.json once, tolerating the PowerShell BOM.

    WOT-2026-126a-1: the single reader that tells "no link" apart from "a link I
    cannot read". Callers that would otherwise treat both as "no prefix" (and write
    null over the second) must branch on ``state``.

    Before: ``link_path`` is the full path of the link file; it may not exist.
    During: one ``read_bytes`` and a ``utf-8-sig`` decode (BOM tolerated, the
            incident of 2026-10-23) and ``json.loads``. Writes nothing.
    After: ``LINK_MISSING`` when the file does not exist; ``LINK_OK`` with the dict;
           ``LINK_UNREADABLE`` with the cause for a decode error, invalid JSON, a
           JSON root that is not an object, or an OS error other than "not found"
           (a directory, a permission problem). Never raises.

    Limit: a broken symlink is intentionally reported as ``LINK_MISSING`` here.
        This reader contract is shared by the 152a/152b/152c readers; the writer
        is responsible for refusing to overwrite a broken existing link.
    """
    try:
        raw = link_path.read_bytes()
    except FileNotFoundError:
        return MotorLinkRead(LINK_MISSING)
    except OSError as exc:
        return MotorLinkRead(LINK_UNREADABLE, reason=f"io: {exc}")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return MotorLinkRead(LINK_UNREADABLE, reason=f"decode: {exc}")
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        return MotorLinkRead(LINK_UNREADABLE, reason=f"json: {exc}")
    if not isinstance(data, dict):
        return MotorLinkRead(
            LINK_UNREADABLE, reason=f"not-a-dict: {type(data).__name__}"
        )
    return MotorLinkRead(LINK_OK, data=data)


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
        # `utf-8-sig` tolera el BOM que deja PowerShell 5.1; con `utf-8`
        # estricto el link se trataba como ausente (ronda 5, 2026-10-23).
        data = json.loads(link_path.read_text(encoding="utf-8-sig"))
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
