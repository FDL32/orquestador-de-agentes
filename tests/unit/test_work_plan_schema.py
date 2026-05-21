from __future__ import annotations

import importlib.util
from pathlib import Path

# Import _check_deliverable_type dynamically since agent_controller is in .agent/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location(
    "agent_controller",
    PROJECT_ROOT / ".agent" / "agent_controller.py",
)
agent_controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_controller)


def test_deliverable_type_present_valid() -> None:
    """Test that valid deliverable_type values produce no warnings."""
    content = """## Metadata
- **ID:** WP-2026-099
- **deliverable_type:** code
"""
    warnings = agent_controller._check_deliverable_type(content)
    assert warnings == []


def test_deliverable_type_missing_emits_warning() -> None:
    """Test that missing deliverable_type emits a warning."""
    content = """## Metadata
- **ID:** WP-2026-099
- **Estado:** APPROVED
"""
    warnings = agent_controller._check_deliverable_type(content)
    assert len(warnings) == 1
    assert "missing deliverable_type" in warnings[0]


def test_deliverable_type_unknown_value_emits_warning() -> None:
    """Test that unknown deliverable_type value emits a warning."""
    content = """## Metadata
- **deliverable_type:** nonsense
"""
    warnings = agent_controller._check_deliverable_type(content)
    assert len(warnings) == 1
    assert "unknown deliverable_type" in warnings[0]


def test_deliverable_type_compound_emits_info() -> None:
    """Test that compound deliverable_type (e.g., code+documentation) emits info warning."""
    content = """## Metadata
- **deliverable_type:** code+documentation
"""
    warnings = agent_controller._check_deliverable_type(content)
    assert len(warnings) == 1
    assert "compound" in warnings[0].lower() or "mixed" in warnings[0].lower()


def test_deliverable_type_all_valid_values() -> None:
    """Test all valid deliverable_type values produce no warnings."""
    valid_values = ["code", "documentation", "research", "analysis", "mixed"]
    for value in valid_values:
        content = f"""## Metadata
- **deliverable_type:** {value}
"""
        warnings = agent_controller._check_deliverable_type(content)
        assert warnings == [], f"Expected no warnings for '{value}', got {warnings}"


def test_deliverable_type_case_insensitive() -> None:
    """Test that deliverable_type validation is case-insensitive."""
    content = """## Metadata
- **deliverable_type:** CODE
"""
    warnings = agent_controller._check_deliverable_type(content)
    assert warnings == []


def test_deliverable_type_with_extra_spaces() -> None:
    """Test that deliverable_type with extra spaces is handled correctly."""
    content = """## Metadata
- **deliverable_type:**   code
"""
    warnings = agent_controller._check_deliverable_type(content)
    assert warnings == []
