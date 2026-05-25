"""Unit tests for ReviewBridge prompt and strategy selection by deliverable_type."""

from __future__ import annotations

from pathlib import Path

from bus.event_bus import EventBus
from bus.review_bridge import ReviewBridge


def _write_work_plan(tmp_path: Path, dtype: str | None) -> Path:
    collab_dir = tmp_path / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True, exist_ok=True)
    work_plan = collab_dir / "work_plan.md"

    lines = [
        "# Plan de Trabajo",
        "## Metadata",
        "- **ID:** WP-2026-091",
    ]
    if dtype is not None:
        lines.append(f"- **deliverable_type:** {dtype}")

    work_plan.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return work_plan


def test_read_deliverable_type_valid(tmp_path):
    """Test reading valid deliverable_types."""
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    # 1. code
    _write_work_plan(tmp_path, "code")
    assert bridge._read_deliverable_type() == "code"

    # 2. mixed
    _write_work_plan(tmp_path, "mixed")
    assert bridge._read_deliverable_type() == "mixed"

    # 3. documentation
    _write_work_plan(tmp_path, "documentation")
    assert bridge._read_deliverable_type() == "documentation"

    # 4. research
    _write_work_plan(tmp_path, "research")
    assert bridge._read_deliverable_type() == "research"

    # 5. analysis
    _write_work_plan(tmp_path, "analysis")
    assert bridge._read_deliverable_type() == "analysis"


def test_read_deliverable_type_fallbacks(tmp_path):
    """Test fallback behaviors for missing, unknown, or compound values."""
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    # Missing
    _write_work_plan(tmp_path, None)
    assert bridge._read_deliverable_type() == "code"

    # Unknown
    _write_work_plan(tmp_path, "unknown-type")
    assert bridge._read_deliverable_type() == "code"

    # Compound treated as mixed
    _write_work_plan(tmp_path, "code+documentation")
    assert bridge._read_deliverable_type() == "mixed"


def test_opencode_review_prompts(monkeypatch, tmp_path):
    """Test that _build_review_prompt constructs the correct prompt based on deliverable_type."""
    runtime_dir = tmp_path / ".agent" / "runtime" / "events"
    event_bus = EventBus(runtime_dir=runtime_dir)
    bridge = ReviewBridge(event_bus=event_bus, project_root=tmp_path)

    monkeypatch.setattr(bridge, "_get_manager_model", lambda: "fake-model")
    monkeypatch.setattr(bridge, "_read_canonical", lambda name: "")
    monkeypatch.setattr(bridge, "_read_canonical_optional", lambda name: None)
    monkeypatch.setattr(bridge, "_extract_ticket_section", lambda tid: "")
    monkeypatch.setattr(
        bridge, "_build_diff_for_files_likely_touched", lambda *args: ""
    )
    monkeypatch.setattr(bridge, "_git_diff_stat", lambda: "")

    # 1. Test code prompt
    _write_work_plan(tmp_path, "code")
    prompt = bridge._build_review_prompt(ticket_id="WP-2026-091", dtype="code")
    assert "Review code ticket WP-2026-091" in prompt
    assert "Verify the implementation correctness" in prompt

    # 2. Test mixed prompt
    _write_work_plan(tmp_path, "mixed")
    prompt = bridge._build_review_prompt(ticket_id="WP-2026-091", dtype="mixed")
    assert "Review mixed ticket WP-2026-091" in prompt
    assert "Verify code correctness, tests" in prompt
    assert "non-code deliverables exist" in prompt

    # 3. Test documentation prompt
    _write_work_plan(tmp_path, "documentation")
    prompt = bridge._build_review_prompt(ticket_id="WP-2026-091", dtype="documentation")
    assert "Review non-code documentation ticket WP-2026-091" in prompt
    assert "Since this is a non-code deliverable" in prompt
