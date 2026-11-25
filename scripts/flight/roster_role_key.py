"""Resolve the FLT compatibility key for the active coordinator role.

Before: ``active_roles`` is the decoded roster mapping.
During: inspect only ``orquestador`` and ``coordinadora`` and reject both.
After: return the sole key, or ``None`` when neither key exists.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any


ROLE_KEYS = ("orquestador", "coordinadora")


class RosterRoleKeyError(ValueError):
    """Raised when both compatibility keys are present."""


def resolve_orchestrator_role(active_roles: Mapping[str, Any]) -> str | None:
    """Return the sole compatibility key, or fail closed on both."""
    if not isinstance(active_roles, Mapping):
        raise TypeError("active_roles debe ser un mapping")
    present = [key for key in ROLE_KEYS if key in active_roles]
    if len(present) > 1:
        raise RosterRoleKeyError(
            "active_roles contiene ambas claves de coordinacion: " + ", ".join(present)
        )
    return present[0] if present else None


def orchestrator_entry(active_roles: Mapping[str, Any]) -> Any:
    """Return the resolved entry, or ``None`` when no key is present."""
    key = resolve_orchestrator_role(active_roles)
    return active_roles[key] if key is not None else None


def set_orchestrator_entry(active_roles: MutableMapping[str, Any], entry: Any) -> str:
    """Update the present key, or create only ``orquestador`` when absent."""
    key = resolve_orchestrator_role(active_roles) or "orquestador"
    active_roles[key] = entry
    return key


resolve_role_key = resolve_orchestrator_role
set_role_entry = set_orchestrator_entry
