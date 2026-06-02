"""Tests for redaction in the memory persistence pipeline.

These tests verify that each writer redacts secrets and PII *before* persisting
observations to disk. They do NOT duplicate unit coverage of redact() itself
(covered in test_redact.py).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from bus.redact import redact_payload


# ---------------------------------------------------------------------------
# Helpers: load modules that live in .agent/ (non-package dir)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module(rel_path: str, module_name: str) -> Any:
    """Load a Python module by relative path from repo root.

    Uses importlib to work around .agent/ not being a regular package.
    """
    filepath = _REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {filepath}")
    mod = importlib.util.module_from_spec(spec)
    # Ensure bus/ is importable from within the loaded module
    sys.path.insert(0, str(_REPO_ROOT))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(_REPO_ROOT))
    return mod


# ---------------------------------------------------------------------------
# memory_helpers.append_observation
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_helpers_mod() -> Any:
    """Load memory_helpers via importlib."""
    return _load_module(
        ".agent/runtime/memory/memory_helpers.py",
        "memory_helpers",
    )


@pytest.fixture
def agent_dir(tmp_path: Path) -> Path:
    """Create a temporary .agent dir and patch get_agent_dir to point there."""
    d = tmp_path / ".agent"
    d.mkdir(parents=True)
    return d


def test_append_observation_redacts_api_key(
    memory_helpers_mod: Any,
    agent_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """append_observation persists API keys as ***REDACTED***."""
    # Patch the function reference directly on the loaded module
    monkeypatch.setattr(
        memory_helpers_mod,
        "get_agent_dir",
        lambda: agent_dir,
    )

    obs: dict[str, Any] = {
        "timestamp": "2026-06-02T00:00:00Z",
        "topic": "test",
        "signal": "My API key is sk-abcdefghijklmnopqrstuvwxyz12345",
        "source": "test",
    }
    assert memory_helpers_mod.append_observation(obs)

    obs_file = agent_dir / "runtime" / "memory" / "observations.jsonl"
    assert obs_file.exists()

    persisted = json.loads(obs_file.read_text(encoding="utf-8").strip())
    assert "***REDACTED***" in persisted["signal"]
    assert "sk-abcdefghijklmnopqrstuvwxyz12345" not in persisted["signal"]


def test_append_observation_redacts_windows_path(
    memory_helpers_mod: Any,
    agent_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """append_observation redacts Windows username in paths."""
    monkeypatch.setattr(
        memory_helpers_mod,
        "get_agent_dir",
        lambda: agent_dir,
    )

    obs: dict[str, Any] = {
        "timestamp": "2026-06-02T00:00:00Z",
        "topic": "test",
        "signal": r"Project in C:\Users\fdl\Proyectos",
        "source": "test",
    }
    assert memory_helpers_mod.append_observation(obs)

    obs_file = agent_dir / "runtime" / "memory" / "observations.jsonl"
    persisted = json.loads(obs_file.read_text(encoding="utf-8").strip())
    assert r"C:\Users\***REDACTED***" in persisted["signal"]
    assert r"C:\Users\fdl" not in persisted["signal"]


def test_append_observation_clean_entries_pass_through(
    memory_helpers_mod: Any,
    agent_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean entries without secrets keep their original content."""
    monkeypatch.setattr(
        memory_helpers_mod,
        "get_agent_dir",
        lambda: agent_dir,
    )

    obs: dict[str, Any] = {
        "timestamp": "2026-06-02T00:00:00Z",
        "topic": "test",
        "signal": "All systems nominal - no secrets here.",
        "source": "test",
    }
    assert memory_helpers_mod.append_observation(obs)

    obs_file = agent_dir / "runtime" / "memory" / "observations.jsonl"
    persisted = json.loads(obs_file.read_text(encoding="utf-8").strip())
    assert persisted["signal"] == "All systems nominal - no secrets here."


# ---------------------------------------------------------------------------
# post_tool_hook.log_observation
# ---------------------------------------------------------------------------


@pytest.fixture
def post_tool_hook_mod() -> Any:
    """Load post_tool_hook via importlib."""
    return _load_module(
        ".agent/hooks/post_tool_hook.py",
        "post_tool_hook",
    )


def test_log_observation_redacts_signal(
    post_tool_hook_mod: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """post_tool_hook redacts secrets in signal and context before writing."""
    monkeypatch.setattr(
        post_tool_hook_mod,
        "OBSERVATIONS_FILE",
        tmp_path / "observations.jsonl",
    )
    # Reset global counter
    post_tool_hook_mod._tool_call_counter = 0

    post_tool_hook_mod.log_observation(
        {
            "timestamp": "2026-06-02T00:00:00Z",
            "tool_name": "test_tool",
            "context": "Bearer sk-secret-key-12345",
            "session_id": "sess-001",
        }
    )

    obs_file = tmp_path / "observations.jsonl"
    assert obs_file.exists()
    persisted = json.loads(obs_file.read_text(encoding="utf-8"))
    # Either signal or context should be redacted
    combined = persisted.get("signal", "") + persisted.get("context", "")
    assert "***REDACTED***" in combined
    assert "Bearer sk-secret-key-12345" not in combined


def test_log_observation_redacts_jwt(
    post_tool_hook_mod: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """post_tool_hook redacts JWT tokens in context."""
    monkeypatch.setattr(
        post_tool_hook_mod,
        "OBSERVATIONS_FILE",
        tmp_path / "observations.jsonl",
    )
    post_tool_hook_mod._tool_call_counter = 0

    post_tool_hook_mod.log_observation(
        {
            "timestamp": "2026-06-02T00:00:00Z",
            "tool_name": "jwt_tool",
            "context": "Using token eyJhbGciOiJIUzI1NiJ9.eyJ0ZXN0IjoxfQ.deadbeef",
            "session_id": "sess-002",
        }
    )

    persisted = json.loads(
        (tmp_path / "observations.jsonl").read_text(encoding="utf-8")
    )
    assert "***REDACTED***" in persisted["context"]
    assert "eyJhbGciOiJIUzI1NiJ9" not in persisted["context"]


# ---------------------------------------------------------------------------
# session_close_observations.append_observations
# ---------------------------------------------------------------------------


def test_session_close_observations_redacts_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """session_close_observations.append_observations redacts signal."""
    import scripts.session_close_observations as sco

    monkeypatch.setattr(sco, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(sco, "OBS_FILE", tmp_path / "observations.jsonl")

    entry: dict[str, Any] = {
        "timestamp": "2026-06-02T00:00:00Z",
        "signal": "API key leaked: sk-abcdefghijklmnopqrstuvwxyz12345",
        "topic": "security",
        "source": "test",
        "domain": "security-gates",
        "confidence": 0.9,
        "applies_to": "code",
        "source_ticket": "WT-2026-193",
        "impact": "high",
    }
    sco.append_observations([entry])

    persisted = json.loads(
        (tmp_path / "observations.jsonl").read_text(encoding="utf-8")
    )
    assert "***REDACTED***" in persisted["signal"]
    assert "sk-abcdefghijklmnopqrstuvwxyz12345" not in persisted["signal"]


def test_session_close_observations_clean_passthrough(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean entries pass through without spurious redaction."""
    import scripts.session_close_observations as sco

    monkeypatch.setattr(sco, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(sco, "OBS_FILE", tmp_path / "observations.jsonl")

    entry: dict[str, Any] = {
        "timestamp": "2026-06-02T00:00:00Z",
        "signal": "All tests passed successfully.",
        "topic": "testing",
        "source": "test",
        "domain": "testing",
        "confidence": 0.95,
        "applies_to": "code",
        "source_ticket": "WT-2026-193",
        "impact": "medium",
    }
    sco.append_observations([entry])

    persisted = json.loads(
        (tmp_path / "observations.jsonl").read_text(encoding="utf-8")
    )
    assert persisted["signal"] == "All tests passed successfully."


# ---------------------------------------------------------------------------
# memory_consolidate._redact_entry
# ---------------------------------------------------------------------------


from scripts.memory_consolidate import _redact_entry  # noqa: E402


def test_consolidate_redact_entry_api_key() -> None:
    """_redact_entry redacts API keys from observation entries."""
    original: dict[str, Any] = {
        "timestamp": "2026-06-02T00:00:00Z",
        "signal": "Key is sk-abcdefghijklmnopqrstuvwxyz12345",
        "topic": "security",
        "source": "test",
    }
    redacted = _redact_entry(original)
    assert "***REDACTED***" in redacted["signal"]
    assert "sk-abcdefghijklmnopqrstuvwxyz12345" not in redacted["signal"]


def test_consolidate_redact_entry_windows_path() -> None:
    """_redact_entry redacts Windows username in paths."""
    original: dict[str, Any] = {
        "timestamp": "2026-06-02T00:00:00Z",
        "signal": r"Located at C:\Users\fdl\code",
        "topic": "paths",
        "source": "test",
    }
    redacted = _redact_entry(original)
    assert r"C:\Users\***REDACTED***" in redacted["signal"]
    assert r"C:\Users\fdl" not in redacted["signal"]


def test_consolidate_redact_entry_clean_passthrough() -> None:
    """_redact_entry preserves clean entries unchanged."""
    original: dict[str, Any] = {
        "timestamp": "2026-06-02T00:00:00Z",
        "signal": "Normal observation without secrets.",
        "topic": "general",
        "source": "test",
    }
    redacted = _redact_entry(original)
    assert redacted["signal"] == "Normal observation without secrets."
    assert redacted["topic"] == "general"
    assert redacted["source"] == "test"


def test_consolidate_redact_entry_idempotent() -> None:
    """_redact_entry is idempotent: redact(redact(x)) == redact(x)."""
    entry: dict[str, Any] = {
        "timestamp": "2026-06-02T00:00:00Z",
        "signal": "Key: sk-abcdefghijklmnopqrstuvwxyz12345",
        "topic": "security",
        "source": "test",
    }
    once = _redact_entry(entry)
    twice = _redact_entry(once)
    assert once == twice


# ---------------------------------------------------------------------------
# No-regression: redact_payload does not mutate the original dict
# ---------------------------------------------------------------------------


def test_redact_payload_does_not_mutate_original() -> None:
    """redact_payload returns a new dict without mutating the input."""
    original: dict[str, Any] = {
        "signal": "My key is sk-abcdefghijklmnopqrstuvwxyz12345",
    }
    original_copy = dict(original)
    redacted = redact_payload(original)
    assert original == original_copy  # original unchanged
    assert redacted is not original
