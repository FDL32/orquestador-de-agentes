"""Unit tests for the pre-commit ruff hook scope guard."""

from __future__ import annotations

from pathlib import Path

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


# ---------------------------------------------------------------------------
# El hook de VERIFICACION no puede MUTAR (WOT-2026-047w, incidente 2026-08-05).
#
# `pyproject.toml` declara `fix = true`, asi que `ruff check` reescribe ficheros
# POR CONFIGURACION aunque nadie pase `--fix`. Medido en el repo real: correr
# `ruff check <fichero> --select RUF100` -- una consulta, no una correccion --
# retiro 2 `# noqa: S603` del arbol. Ese es el mecanismo que reaparecio DOS
# veces en dos checkouts sin commit ni autor: no fue un acto humano, fue un
# probe de conteo con efecto de escritura.
#
# Sin `--no-fix`, el hook de pre-commit hereda ese comportamiento: un gate que
# corrige en silencio deja de ser un gate.
# ---------------------------------------------------------------------------

RUFF_HOOK_MUST_BE_READONLY = "--no-fix"


def test_ruff_check_hook_is_pinned_readonly() -> None:
    """El hook `ruff-check` del repo REAL declara `--no-fix`.

    Mutacion: quitar `--no-fix` del entry -> este test cae.
    """
    config_path = Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"
    assert config_path.is_file(), f"config de pre-commit ausente: {config_path}"
    text = config_path.read_text(encoding="utf-8")

    entry = next(
        (ln for ln in text.splitlines() if "entry:" in ln and "ruff check" in ln),
        None,
    )
    assert entry is not None, "no se encontro el entry del hook ruff-check"
    assert RUFF_HOOK_MUST_BE_READONLY in entry, (
        "el hook `ruff-check` NO lleva --no-fix y pyproject declara `fix = true`: "
        "el hook REESCRIBE ficheros por configuracion. Medido 2026-08-05: "
        "`ruff check <f> --select RUF100` retiro 2 noqa del arbol sin pedirlo. "
        f"entry actual: {entry.strip()!r}"
    )


def test_pyproject_still_declares_fix_true_so_the_pin_is_needed() -> None:
    """Control: si `fix = true` desapareciera, este pin dejaria de ser necesario.

    No falla el pin -- documenta POR QUE existe. Si alguien pone `fix = false`,
    este test avisa de que la premisa del pin cambio y hay que re-decidir.
    """
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "fix = true" in text, (
        "pyproject ya NO declara `fix = true`: la premisa del pin `--no-fix` "
        "cambio. Re-evalua si el pin sigue haciendo falta en vez de asumirlo."
    )
