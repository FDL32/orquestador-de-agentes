"""Unit tests for memory_loader.py Wing-aware parsing (WP-2026-179).

Covers:
- TP-02: get_review_context no-regression with H2 Wing / H3 Domain structure
- TP-05: retrocompatibility when memory_rules.md has no Wing headers
"""

from __future__ import annotations

import textwrap
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers to patch memory paths
# ---------------------------------------------------------------------------


def _write_rules(agent_dir: Path, content: str) -> None:
    rules_path = agent_dir / "runtime" / "memory" / "memory_rules.md"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# TP-02: get_review_context with new Wing → Domain structure
# ---------------------------------------------------------------------------


def test_get_review_context_extracts_domain_under_wing(tmp_path, monkeypatch):
    """get_review_context returns the correct domain section even nested under a Wing."""
    from bus import memory_loader

    content = textwrap.dedent("""\
        ## Wing: engine
        ### Domain: python-hygiene
        - Use pathlib for all I/O.

        ## Wing: meta
        ### Domain: delivery-hygiene
        - Always update execution_log.md before handoff.

        ## Wing: project
        ### Domain: local-rules
        - Keep secrets out of observations.jsonl.
    """)

    rules_file = tmp_path / "runtime" / "memory" / "memory_rules.md"
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    rules_file.write_text(content, encoding="utf-8")

    monkeypatch.setattr(memory_loader, "_get_rules_file", lambda: rules_file)

    result = memory_loader.get_review_context(domain="delivery-hygiene")
    assert "execution_log" in result
    # Other domains must NOT bleed in
    assert "python-hygiene" not in result
    assert "local-rules" not in result


def test_get_review_context_no_domain_returns_all(tmp_path, monkeypatch):
    """get_review_context with domain=None returns full rules file."""
    from bus import memory_loader

    content = textwrap.dedent("""\
        ## Wing: engine
        ### Domain: arch
        - Rule A

        ## Wing: project
        ### Domain: local
        - Rule B
    """)

    rules_file = tmp_path / "runtime" / "memory" / "memory_rules.md"
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    rules_file.write_text(content, encoding="utf-8")

    monkeypatch.setattr(memory_loader, "_get_rules_file", lambda: rules_file)

    result = memory_loader.get_review_context(domain=None)
    assert "Rule A" in result
    assert "Rule B" in result


def test_get_review_context_unknown_domain_falls_back_to_full(tmp_path, monkeypatch):
    """Unknown domain falls back to full rules rather than returning empty."""
    from bus import memory_loader

    content = textwrap.dedent("""\
        ## Wing: engine
        ### Domain: arch
        - Rule A
    """)

    rules_file = tmp_path / "runtime" / "memory" / "memory_rules.md"
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    rules_file.write_text(content, encoding="utf-8")

    monkeypatch.setattr(memory_loader, "_get_rules_file", lambda: rules_file)

    result = memory_loader.get_review_context(domain="nonexistent-domain")
    assert "Rule A" in result


# ---------------------------------------------------------------------------
# TP-05: Retrocompatibility — legacy rules without Wing headers
# ---------------------------------------------------------------------------


def test_get_review_context_legacy_no_wings(tmp_path, monkeypatch):
    """Legacy memory_rules.md without Wing headers still works correctly."""
    from bus import memory_loader

    content = textwrap.dedent("""\
        ## Domain: python-hygiene
        - Use pathlib.

        ## Domain: delivery-hygiene
        - Commit before handoff.
    """)

    rules_file = tmp_path / "runtime" / "memory" / "memory_rules.md"
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    rules_file.write_text(content, encoding="utf-8")

    monkeypatch.setattr(memory_loader, "_get_rules_file", lambda: rules_file)

    # Domain filter still works on legacy format
    result = memory_loader.get_review_context(domain="delivery-hygiene")
    assert "Commit before handoff" in result
    assert "python-hygiene" not in result


def test_get_review_context_empty_rules_falls_back_to_l1(tmp_path, monkeypatch):
    """Empty rules file falls back to L1 observations without crashing."""
    from bus import memory_loader

    rules_file = tmp_path / "runtime" / "memory" / "memory_rules.md"
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    rules_file.write_text("", encoding="utf-8")

    obs_file = tmp_path / "runtime" / "memory" / "observations.jsonl"
    obs_file.write_text(
        '{"signal": "important obs", "topic": "test", "source": "unit-test", "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(memory_loader, "_get_rules_file", lambda: rules_file)
    monkeypatch.setattr(memory_loader, "_get_observations_file", lambda: obs_file)

    result = memory_loader.get_review_context()
    assert "important obs" in result
