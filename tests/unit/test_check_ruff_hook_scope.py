"""Unit tests for the pre-commit ruff hook scope guard."""

from __future__ import annotations

import re
import subprocess
import sys
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
# retiro dos "noqa: S603" del arbol. Ese es el mecanismo que reaparecio DOS
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


def _effective_ruff_fix(
    probe: Path, *, no_fix: bool = False, cwd: Path | None = None
) -> bool:
    command = [sys.executable, "-m", "ruff", "check", "--show-settings"]
    if no_fix:
        command.append("--no-fix")
    command.append(str(probe))
    result = subprocess.run(
        command,
        cwd=cwd or probe.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "ruff no pudo mostrar la configuración efectiva "
        f"(rc={result.returncode}): {result.stderr.strip()}"
    )
    fix_lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("fix")
    ]
    assert fix_lines, "ruff --show-settings no devolvió una línea `fix`"
    match = re.match(r"fix\s*=\s*(true|false)\s*$", fix_lines[0], re.IGNORECASE)
    assert match, f"formato inesperado para la configuración `fix`: {fix_lines[0]!r}"
    return match.group(1).lower() == "true"


def test_real_ruff_config_is_not_autofix() -> None:
    """The repository's effective config must keep gates read-only by default."""
    repo_root = Path(__file__).resolve().parents[2]
    probe = repo_root / "scripts" / "check_guard_wiring.py"
    assert _effective_ruff_fix(probe, cwd=repo_root) is False, (
        "reintroducir `fix = true` en pyproject haría que dispatcher y workflow "
        "(que no llevan `--no-fix`) reescriban ficheros"
    )


def test_effective_ruff_fix_is_false_and_no_floor(tmp_path: Path) -> None:
    """El control mide Ruff efectivo y prueba el pin contra una config mutada."""
    repo_root = Path(__file__).resolve().parents[2]
    source = repo_root / "pyproject.toml"
    pyproject = source.read_text(encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text("x = 1\n", encoding="utf-8")

    lines = pyproject.splitlines()
    copied_lines: list[str] = []
    in_ruff_section = False
    replaced_fix = False
    for line in lines:
        if line.startswith("["):
            in_ruff_section = line == "[tool.ruff]"
        if in_ruff_section and re.match(r"^\s*fix\s*=", line):
            copied_lines.append("fix = true")
            replaced_fix = True
        else:
            copied_lines.append(line)
    if not replaced_fix:
        section_index = copied_lines.index("[tool.ruff]")
        copied_lines.insert(section_index + 1, "fix = true")
    copied = "\n".join(copied_lines) + "\n"
    assert copied != pyproject
    active_fix_lines = [
        line for line in copied.splitlines() if re.match(r"^\s*fix\s*=", line)
    ]
    assert active_fix_lines == ["fix = true"]
    (tmp_path / "pyproject.toml").write_text(copied, encoding="utf-8")

    assert _effective_ruff_fix(probe) is True, (
        "sin el pin la config mutada debe activar fix"
    )
    assert _effective_ruff_fix(probe, no_fix=True) is False, (
        "con --no-fix la config efectiva debe quedar en fix = false"
    )
