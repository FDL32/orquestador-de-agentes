"""Tests for deliverable_type-aware scope gate (WOT-2026-009a).

Verifica que parse_files_likely_touched y check_scope_gate reconocen la
seccion ## Builder como alternativa a ## Files Likely Touched para tickets
de tipo analysis/documentation/research, y que tickets code/mixed NO
parsean ## Builder como whitelist.
"""

from __future__ import annotations

import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_AGENT_DIR = _PROJECT_ROOT / ".agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import scope_gate  # noqa: E402


_ROOT = Path("/fake/root")

_ANALYSIS_NO_SURFACES = (
    "# Work Plan\n\n"
    "## Metadata\n\n"
    "- **deliverable_type:** analysis\n\n"
    "## Objetivo\n\nHacer algo.\n"
)

_ANALYSIS_WITH_BUILDER = (
    "# Work Plan\n\n"
    "## Metadata\n\n"
    "- **deliverable_type:** analysis\n\n"
    "## Builder\n\n"
    "- `.agent/docs/foo.md`\n"
    "- `.agent/docs/bar.md`\n\n"
    "## Read/inspect only\n\n"
    "- `prompts/x.md`\n"
)

_ANALYSIS_BUILDER_ONE = (
    "# Work Plan\n\n"
    "## Metadata\n\n"
    "- **deliverable_type:** analysis\n\n"
    "## Builder\n\n"
    "- `.agent/docs/foo.md`\n"
)

_DOCUMENTATION_WITH_BUILDER = (
    "# Work Plan\n\n"
    "## Metadata\n\n"
    "- **deliverable_type:** documentation\n\n"
    "## Builder\n\n"
    "- `prompts/new_prompt.md`\n"
)

_RESEARCH_WITH_BUILDER = (
    "# Work Plan\n\n"
    "## Metadata\n\n"
    "- **deliverable_type:** research\n\n"
    "## Builder\n\n"
    "- `.agent/docs/report.md`\n"
)

_CODE_BUILDER_ONLY = (
    "# Work Plan\n\n"
    "## Metadata\n\n"
    "- **deliverable_type:** code\n\n"
    "## Builder\n\n"
    "- `bus/foo.py`\n"
)

_MIXED_BUILDER_ONLY = (
    "# Work Plan\n\n"
    "## Metadata\n\n"
    "- **deliverable_type:** mixed\n\n"
    "## Builder\n\n"
    "- `bus/foo.py`\n"
)

_ANALYSIS_FLT_AND_BUILDER = (
    "# Work Plan\n\n"
    "## Metadata\n\n"
    "- **deliverable_type:** analysis\n\n"
    "## Files Likely Touched\n\n"
    "- `.agent/docs/foo.md`\n\n"
    "## Builder\n\n"
    "- `.agent/docs/OTHER.md`\n"
)


def _parse(plan: str, deliverable_type: str = "code") -> set[str]:
    return scope_gate.parse_files_likely_touched(
        plan, project_root=_ROOT, deliverable_type=deliverable_type
    )


def _gate(plan: str, changed: set[str], deliverable_type: str = "code") -> dict:
    return scope_gate.check_scope_gate(
        plan,
        changed,
        set(),
        parse_files_likely_touched_fn=lambda content, **kw: (
            scope_gate.parse_files_likely_touched(
                content, project_root=_ROOT, deliverable_type=deliverable_type
            )
        ),
        deliverable_type=deliverable_type,
    )


# Negativo A: analysis sin FLT ni Builder -> warning backward-compat


def test_analysis_no_surfaces_emits_warning() -> None:
    result = _gate(
        _ANALYSIS_NO_SURFACES,
        changed={str(_ROOT / ".agent/docs/foo.md")},
        deliverable_type="analysis",
    )
    assert result["valid"] is True
    assert any("No Files Likely Touched" in w for w in result["warnings"])


# Positivo A: analysis con ## Builder -> whitelist real


def test_analysis_builder_section_parsed_as_whitelist() -> None:
    files = _parse(_ANALYSIS_WITH_BUILDER, deliverable_type="analysis")
    assert str((_ROOT / ".agent/docs/foo.md").resolve()) in files
    assert str((_ROOT / ".agent/docs/bar.md").resolve()) in files
    assert str((_ROOT / "prompts/x.md").resolve()) not in files


def test_analysis_builder_section_no_warning_when_covered() -> None:
    changed = {str((_ROOT / ".agent/docs/foo.md").resolve())}
    result = _gate(_ANALYSIS_BUILDER_ONE, changed=changed, deliverable_type="analysis")
    assert result["valid"] is True
    assert result["warnings"] == []


def test_documentation_builder_section_parsed() -> None:
    files = _parse(_DOCUMENTATION_WITH_BUILDER, deliverable_type="documentation")
    assert str((_ROOT / "prompts/new_prompt.md").resolve()) in files


def test_research_builder_section_parsed() -> None:
    files = _parse(_RESEARCH_WITH_BUILDER, deliverable_type="research")
    assert str((_ROOT / ".agent/docs/report.md").resolve()) in files


# Positivo B: code/mixed con ## Builder -> NO parsea Builder


def test_code_does_not_parse_builder_section() -> None:
    assert _parse(_CODE_BUILDER_ONLY, deliverable_type="code") == set()


def test_code_gate_emits_warning_without_flt() -> None:
    result = _gate(
        _CODE_BUILDER_ONLY,
        changed={str(_ROOT / "bus/foo.py")},
        deliverable_type="code",
    )
    assert result["valid"] is True
    assert any("No Files Likely Touched" in w for w in result["warnings"])


def test_mixed_does_not_parse_builder_section() -> None:
    assert _parse(_MIXED_BUILDER_ONLY, deliverable_type="mixed") == set()


# Positivo C: analysis con ## Files Likely Touched -> FLT tiene prioridad


def test_analysis_with_flt_uses_flt_not_builder() -> None:
    files = _parse(_ANALYSIS_FLT_AND_BUILDER, deliverable_type="analysis")
    assert str((_ROOT / ".agent/docs/foo.md").resolve()) in files
    assert str((_ROOT / ".agent/docs/OTHER.md").resolve()) not in files
