"""Unit tests for the pre-commit ruff hook scope guard."""

from __future__ import annotations

from scripts.check_ruff_hook_scope import check_pre_commit_config


VALID_CONFIG = """
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: uv run ruff check
        language: system
        pass_filenames: true
        types: [python]

      - id: ruff-format
        name: ruff format
        entry: uv run ruff format
        language: system
        pass_filenames: true
        types: [python]
"""

DEGRADED_CONFIG_MISSING_TYPES = """
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: uv run ruff check
        language: system
        pass_filenames: true

      - id: ruff-format
        name: ruff format
        entry: uv run ruff format
        language: system
        pass_filenames: true
        types: [python]
"""

AMBIGUOUS_CONFIG_MARKDOWN = """
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: uv run ruff check
        language: system
        pass_filenames: true
        types: [python, markdown]

      - id: ruff-format
        name: ruff format
        entry: uv run ruff format
        language: system
        pass_filenames: true
        types: [python]
"""

MISSING_HOOKS_CONFIG = """
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-yaml
"""


def test_valid_config_passes():
    success, reason = check_pre_commit_config(VALID_CONFIG)
    assert success is True
    assert "Verified" in reason


def test_degraded_config_fails():
    success, reason = check_pre_commit_config(DEGRADED_CONFIG_MISSING_TYPES)
    assert success is False
    assert "not restricted to Python-only" in reason


def test_ambiguous_config_fails():
    success, reason = check_pre_commit_config(AMBIGUOUS_CONFIG_MARKDOWN)
    assert success is False
    assert "explicitly includes Markdown" in reason


def test_missing_hooks_fails():
    success, reason = check_pre_commit_config(MISSING_HOOKS_CONFIG)
    assert success is False
    assert "No ruff pre-commit hooks" in reason


def test_valid_config_multiline_types_passes():
    """Guard must detect python in multi-line YAML list form."""
    config = """
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: uv run ruff check
        language: system
        pass_filenames: true
        types:
          - python

      - id: ruff-format
        name: ruff format
        entry: uv run ruff format
        language: system
        pass_filenames: true
        types:
          - python
"""
    success, reason = check_pre_commit_config(config)
    assert success is True
    assert "Verified" in reason


def test_multiline_types_with_markdown_fails():
    """Guard must catch markdown in multi-line form too."""
    config = """
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: uv run ruff check
        language: system
        pass_filenames: true
        types:
          - python
          - markdown

      - id: ruff-format
        name: ruff format
        entry: uv run ruff format
        language: system
        pass_filenames: true
        types:
          - python
"""
    success, reason = check_pre_commit_config(config)
    assert success is False
    assert "explicitly includes Markdown" in reason
