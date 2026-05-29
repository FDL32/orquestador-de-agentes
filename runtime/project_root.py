"""
Project Root Resolution Module - Central contract for WP-2026-122.

This module provides a single source of truth for resolving the project root
path, supporting both the default motor repository and external destination
workspaces via environment variable injection.

Precedence (effective):
    1. AGENT_PROJECT_ROOT environment variable (set by entry points after parsing --project-root)
    2. Derived from Path(__file__) (defaults to motor repository)

Usage:
    from runtime.project_root import resolve_project_root, get_agent_dir, get_collab_dir

    root = resolve_project_root()  # Path to project root
    agent_dir = get_agent_dir()    # Path to .agent/ directory
    collab_dir = get_collab_dir()  # Path to .agent/collaboration/ directory

Design:
    - Import-safe: no side effects at import time
    - Cacheable: results are memoized for performance
    - Single mechanism: resolve_project_root() is the only resolution path
    - Backward compatible: defaults to motor repo when no external root is injected
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def resolve_project_root() -> Path:
    """
    Resolve the project root path with proper precedence.

    Before: Requires no state; reads os.environ["AGENT_PROJECT_ROOT"] if set.
    During: Checks environment variable first, then falls back to derivation from __file__.
    After: Returns absolute Path to project root, cached for subsequent calls.

    Precedence:
        1. AGENT_PROJECT_ROOT environment variable (if set and non-empty)
        2. Derived from this module's location (runtime/project_root.py -> parent)

    Returns:
        Absolute Path to the project root directory.

    Note:
        Entry points that accept --project-root should export the value to
        AGENT_PROJECT_ROOT environment variable immediately after parsing,
        before importing any modules that depend on the project root.
        This ensures a single channel of propagation (env var) rather than
        parallel mechanisms.
    """
    # Check environment variable first (set by entry points after CLI parsing)
    env_root = os.environ.get("AGENT_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve()

    # Fallback: derive from this module's location
    # runtime/project_root.py -> runtime/ -> project root
    return Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def get_agent_dir() -> Path:
    """
    Get the .agent/ directory path.

    Before: Requires resolve_project_root() to be available.
    During: Calls resolve_project_root() and appends ".agent".
    After: Returns absolute Path to .agent/ directory, cached.

    Returns:
        Absolute Path to the .agent/ directory.
    """
    return resolve_project_root() / ".agent"


@lru_cache(maxsize=1)
def get_collab_dir() -> Path:
    """
    Get the .agent/collaboration/ directory path.

    Before: Requires get_agent_dir() to be available.
    During: Calls get_agent_dir() and appends "collaboration".
    After: Returns absolute Path to .agent/collaboration/ directory, cached.

    Returns:
        Absolute Path to the .agent/collaboration/ directory.
    """
    return get_agent_dir() / "collaboration"


@lru_cache(maxsize=1)
def get_runtime_dir() -> Path:
    """
    Get the .agent/runtime/ directory path.

    Before: Requires get_agent_dir() to be available.
    During: Calls get_agent_dir() and appends "runtime".
    After: Returns absolute Path to .agent/runtime/ directory, cached.

    Returns:
        Absolute Path to the .agent/runtime/ directory.
    """
    return get_agent_dir() / "runtime"


@lru_cache(maxsize=1)
def get_context_dir() -> Path:
    """
    Get the .agent/context/ directory path.

    Before: Requires get_agent_dir() to be available.
    During: Calls get_agent_dir() and appends "context".
    After: Returns absolute Path to .agent/context/ directory, cached.

    Returns:
        Absolute Path to .agent/context/ directory.
    """
    return get_agent_dir() / "context"


@lru_cache(maxsize=1)
def get_scripts_dir() -> Path:
    """
    Get the scripts/ directory path.

    Before: Requires resolve_project_root() to be available.
    During: Calls resolve_project_root() and appends "scripts".
    After: Returns absolute Path to scripts/ directory, cached.

    Returns:
        Absolute Path to scripts/ directory.
    """
    return resolve_project_root() / "scripts"


def clear_cache() -> None:
    """
    Clear all cached path resolutions.

    Before: Requires no state.
    During: Clears lru_cache for all cached functions.
    After: Next call to any resolver will recompute the value.

    Use this only in testing scenarios where you need to simulate
    environment changes between calls.
    """
    resolve_project_root.cache_clear()
    get_agent_dir.cache_clear()
    get_collab_dir.cache_clear()
    get_runtime_dir.cache_clear()
    get_context_dir.cache_clear()
    get_scripts_dir.cache_clear()


def is_motor_code_only() -> bool:
    """
    Check if running in motor code-only mode (no external workspace).

    A mode is "motor code-only" when the controller is running from the motor
    repo directly without AGENT_PROJECT_ROOT / --project-root pointing to an
    external workspace.  This guard prevents accidental write operations against
    the motor's own .agent/ while it is being used as a reusable code-only engine.

    Before: No state required; reads os.environ and filesystem.
    During: Checks AGENT_PROJECT_ROOT env var; falls back to checking whether
            the resolved project root contains agent_controller.py (motor marker).
    After: Returns True if running in motor code-only mode, False otherwise.

    Returns:
        True if running without external workspace (motor code-only).
    """
    if os.environ.get("AGENT_PROJECT_ROOT", "").strip():
        return False
    # Check if the resolved root IS the motor repo by looking for the
    # motor marker (agent_controller.py in the expected .agent/ location).
    motor_marker = resolve_project_root() / ".agent" / "agent_controller.py"
    return motor_marker.exists()
