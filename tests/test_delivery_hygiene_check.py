#!/usr/bin/env python3
"""Tests for delivery_hygiene_check.py.

Tests que validan:
1. Flujo limpio de entrega (arbol limpio, config correcta).
2. Flujo con hook mutador en pre-push que obliga a corregir antes del push.
3. Flujo con artefactos generados no excluidos.
4. Flujo con arbol sucio.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.delivery_hygiene_check import (
    GENERATED_ARTIFACT_PATHS,
    MUTATING_HOOKS,
    HygieneResult,
    check_generated_artifacts_excluded,
    check_git_tree_clean,
    check_mutating_hooks_in_pre_push,
    load_pre_commit_config,
    run_delivery_hygiene_check,
)


VALID_CONFIG_CLEAN = """
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-yaml
      - id: check-json
      # Hooks mutadores SOLO en pre-commit
      - id: end-of-file-fixer
        stages: [pre-commit]
        exclude: '^(\\.agent/runtime/|\\.agent/collaboration/|\\.agent/context/|\\.agent/runtime/events/|\\.agent/context/project-map\\.json$|\\.agent/context/project_map\\.md$|tests/sandbox/)'
      - id: trailing-whitespace
        stages: [pre-commit]
        exclude: '^(\\.agent/runtime/|\\.agent/collaboration/|\\.agent/context/|\\.agent/runtime/events/|\\.agent/context/project-map\\.json$|\\.agent/context/project_map\\.md$|tests/sandbox/)'
      - id: mixed-line-ending
        stages: [pre-commit]
        exclude: '^(\\.agent/runtime/|\\.agent/collaboration/|\\.agent/context/|\\.agent/runtime/events/|\\.agent/context/project-map\\.json$|\\.agent/context/project_map\\.md$)'

  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: uv run ruff check
        language: system
        types: [python]

      - id: ruff-format
        name: ruff format
        entry: uv run ruff format
        language: system
        stages: [pre-commit]
        types: [python]
        exclude: '^(\\.agent/runtime/|\\.agent/collaboration/|\\.agent/context/|\\.agent/runtime/events/|\\.agent/context/project-map\\.json$|\\.agent/context/project_map\\.md$)'

      - id: pip-audit
        name: pip-audit
        entry: uv run pip-audit
        language: system
        stages: [pre-push, manual]
"""

CONFIG_WITH_MUTATOR_IN_PRE_PUSH = """
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      # ERROR: mutador en pre-push
      - id: end-of-file-fixer
        stages: [pre-push]
      - id: trailing-whitespace
        stages: [pre-commit, pre-push]

  - repo: local
    hooks:
      - id: ruff-format
        stages: [pre-push]
"""

CONFIG_WITHOUT_STAGES_MUTATOR = """
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      # ERROR: sin stages = aplica a todos (incluyendo pre-push)
      - id: end-of-file-fixer
      - id: trailing-whitespace

  - repo: local
    hooks:
      - id: ruff-format
"""

CONFIG_WITH_GENERATED_ARTIFACTS_NOT_EXCLUDED = """
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: end-of-file-fixer
        stages: [pre-commit]
        # ERROR: no excluye .agent/context/ ni .agent/runtime/events/
        exclude: '^tests/sandbox/'
      - id: trailing-whitespace
        stages: [pre-commit]
        exclude: '^tests/'
"""

CONFIG_WITH_GENERATED_ARTIFACTS_EXCLUDED = """
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: end-of-file-fixer
        stages: [pre-commit]
        exclude: '^(\\.agent/runtime/|\\.agent/collaboration/|\\.agent/context/|\\.agent/runtime/events/|\\.agent/context/project-map\\.json$|\\.agent/context/project_map\\.md$|tests/sandbox/)'
      - id: trailing-whitespace
        stages: [pre-commit]
        exclude: '^(\\.agent/runtime/|\\.agent/collaboration/|\\.agent/context/|\\.agent/runtime/events/|\\.agent/context/project-map\\.json$|\\.agent/context/project_map\\.md$|tests/sandbox/)'
      - id: mixed-line-ending
        stages: [pre-commit]
        exclude: '^(\\.agent/runtime/|\\.agent/collaboration/|\\.agent/context/|\\.agent/runtime/events/|\\.agent/context/project-map\\.json$|\\.agent/context/project_map\\.md$)'
"""


def test_load_pre_commit_config_valid(tmp_path: Path) -> None:
    """Test parsing de config valido."""
    config_file = tmp_path / ".pre-commit-config.yaml"
    config_file.write_text(VALID_CONFIG_CLEAN, encoding="utf-8")

    config = load_pre_commit_config(tmp_path)

    assert config is not None
    assert "repos" in config
    assert len(config["repos"]) == 2


def test_load_pre_commit_config_missing_file(tmp_path: Path) -> None:
    """Test que retorna None si no existe el archivo."""
    config = load_pre_commit_config(tmp_path)
    assert config is None


def test_load_pre_commit_config_uses_motor_link(tmp_path: Path) -> None:
    """A destination without local config reads the canonical motor config."""
    motor_root = tmp_path / "motor"
    motor_root.mkdir()
    (motor_root / ".pre-commit-config.yaml").write_text(
        VALID_CONFIG_CLEAN,
        encoding="utf-8",
    )

    project_root = tmp_path / "destination"
    config_dir = project_root / ".agent" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "motor_destination_link.json").write_text(
        f'{{"motor_root": "{motor_root.as_posix()}"}}',
        encoding="utf-8",
    )

    config = load_pre_commit_config(project_root)

    assert config is not None
    assert len(config["repos"]) == 2


def test_check_mutating_hooks_clean_config() -> None:
    """Test que config limpia pasa la verificacion."""
    config = {
        "repos": [
            {
                "repo": "local",
                "hooks": [
                    {"id": "check-yaml"},
                    {"id": "end-of-file-fixer", "stages": ["pre-commit"]},
                    {"id": "ruff-format", "stages": ["pre-commit"]},
                ],
            }
        ]
    }

    result = check_mutating_hooks_in_pre_push(config)

    assert result.passed is True
    assert "mutadores" in result.message.lower() or "no hay" in result.message.lower()


def test_check_mutating_hooks_explicit_pre_push() -> None:
    """Test que detecta mutador explicitamente en pre-push."""
    config = {
        "repos": [
            {
                "repo": "local",
                "hooks": [
                    {"id": "end-of-file-fixer", "stages": ["pre-push"]},
                ],
            }
        ]
    }

    result = check_mutating_hooks_in_pre_push(config)

    assert result.passed is False
    assert result.details is not None
    assert any("end-of-file-fixer" in d for d in result.details)
    assert any("pre-push" in d for d in result.details)


def test_check_mutating_hooks_implicit_pre_push() -> None:
    """Test que detecta mutador sin stages (implicito en pre-push)."""
    config = {
        "repos": [
            {
                "repo": "local",
                "hooks": [
                    {"id": "trailing-whitespace"},  # Sin stages = todos
                ],
            }
        ]
    }

    result = check_mutating_hooks_in_pre_push(config)

    assert result.passed is False
    assert result.details is not None
    assert any("trailing-whitespace" in d for d in result.details)
    assert any("sin stages" in d.lower() for d in result.details)


def test_check_mutating_hooks_mixed_stages() -> None:
    """Test que detecta mutador con stages=[pre-commit, pre-push]."""
    config = {
        "repos": [
            {
                "repo": "local",
                "hooks": [
                    {"id": "ruff-format", "stages": ["pre-commit", "pre-push"]},
                ],
            }
        ]
    }

    result = check_mutating_hooks_in_pre_push(config)

    assert result.passed is False
    assert result.details is not None
    assert any("ruff-format" in d for d in result.details)


def test_check_generated_artifacts_excluded() -> None:
    """Test que artefactos generados correctamente excluidos pasan."""
    config = {
        "repos": [
            {
                "repo": "local",
                "hooks": [
                    {
                        "id": "end-of-file-fixer",
                        "exclude": r"^\.agent/context/",
                    },
                    {
                        "id": "trailing-whitespace",
                        "exclude": r"^\.agent/runtime/events/",
                    },
                ],
            }
        ]
    }

    result = check_generated_artifacts_excluded(config)

    # Debe pasar porque al menos una ruta generada esta cubierta por hook
    # (el check verifica que CADA hook de formato excluya TODAS las rutas)
    # En este caso, cada hook excluye solo una ruta, entonces fallara
    # Este test verifica el comportamiento estricto
    assert result.passed is False
    assert result.details is not None
    # Debe haber detalles indicando que rutas faltan
    assert len(result.details) > 0


def test_check_generated_artifacts_all_excluded() -> None:
    """Test que todas las rutas generadas excluidas pasan."""
    # Config que excluye TODAS las rutas generadas en CADA hook
    all_patterns = "|".join(GENERATED_ARTIFACT_PATHS)
    config = {
        "repos": [
            {
                "repo": "local",
                "hooks": [
                    {
                        "id": "end-of-file-fixer",
                        "exclude": all_patterns,
                    },
                    {
                        "id": "trailing-whitespace",
                        "exclude": all_patterns,
                    },
                    {
                        "id": "mixed-line-ending",
                        "exclude": all_patterns,
                    },
                ],
            }
        ]
    }

    result = check_generated_artifacts_excluded(config)

    assert result.passed is True
    assert "excluidos" in result.message.lower()


def test_check_generated_artifacts_missing_exclusion() -> None:
    """Test que detecta exclusion faltante de artefactos generados."""
    config = {
        "repos": [
            {
                "repo": "local",
                "hooks": [
                    {
                        "id": "end-of-file-fixer",
                        "exclude": "^tests/sandbox/",  # No excluye .agent/
                    },
                ],
            }
        ]
    }

    result = check_generated_artifacts_excluded(config)

    assert result.passed is False
    assert result.details is not None
    assert any(".agent/context/" in d for d in result.details)


def test_check_git_tree_clean_with_git(tmp_path: Path) -> None:
    """Test verificacion de arbol limpio con git disponible."""
    # Inicializar repo git limpio
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )

    result = check_git_tree_clean(tmp_path)

    # Arbol debe estar limpio (sin commits aun, pero sin cambios)
    assert result.passed is True


def test_check_git_tree_clean_with_changes(tmp_path: Path) -> None:
    """Test que detecta cambios en el arbol."""
    # Inicializar repo git
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )

    # Crear archivo no trackeado
    test_file = tmp_path / "test.txt"
    test_file.write_text("contenido", encoding="utf-8")

    result = check_git_tree_clean(tmp_path)

    # Debe detectar archivo sin trackear
    assert result.passed is False
    assert result.details is not None
    assert any("test.txt" in d for d in result.details)


def test_check_git_tree_clean_no_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test que maneja ausencia de git."""

    # Simular git no disponible
    def mock_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr("subprocess.run", mock_run)

    result = check_git_tree_clean(tmp_path)

    assert result.passed is False
    assert "GIT NO DISPONIBLE" in result.message


def test_run_delivery_hygiene_check_clean(tmp_path: Path) -> None:
    """Test flujo completo limpio."""
    config_file = tmp_path / ".pre-commit-config.yaml"
    config_file.write_text(VALID_CONFIG_CLEAN, encoding="utf-8")

    # Inicializar git limpio
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )

    # Crear commit inicial para que el arbol quede limpio
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )

    exit_code = run_delivery_hygiene_check(tmp_path, check_tree=True)

    assert exit_code == 0


def test_run_delivery_hygiene_check_mutator_in_pre_push(tmp_path: Path) -> None:
    """Test flujo con mutador en pre-push falla."""
    config_file = tmp_path / ".pre-commit-config.yaml"
    config_file.write_text(CONFIG_WITH_MUTATOR_IN_PRE_PUSH, encoding="utf-8")

    exit_code = run_delivery_hygiene_check(tmp_path, check_tree=False)

    assert exit_code == 1


def test_run_delivery_hygiene_check_no_stages(tmp_path: Path) -> None:
    """Test flujo con mutador sin stages falla."""
    config_file = tmp_path / ".pre-commit-config.yaml"
    config_file.write_text(CONFIG_WITHOUT_STAGES_MUTATOR, encoding="utf-8")

    exit_code = run_delivery_hygiene_check(tmp_path, check_tree=False)

    assert exit_code == 1


def test_run_delivery_hygiene_check_artifacts_not_excluded(tmp_path: Path) -> None:
    """Test flujo con artefactos no excluidos falla."""
    config_file = tmp_path / ".pre-commit-config.yaml"
    config_file.write_text(
        CONFIG_WITH_GENERATED_ARTIFACTS_NOT_EXCLUDED, encoding="utf-8"
    )

    exit_code = run_delivery_hygiene_check(tmp_path, check_tree=False)

    assert exit_code == 1


def test_run_delivery_hygiene_check_artifacts_excluded(tmp_path: Path) -> None:
    """Test flujo con artefactos correctamente excluidos pasa."""
    config_file = tmp_path / ".pre-commit-config.yaml"
    config_file.write_text(CONFIG_WITH_GENERATED_ARTIFACTS_EXCLUDED, encoding="utf-8")

    exit_code = run_delivery_hygiene_check(tmp_path, check_tree=False)

    assert exit_code == 0


def test_mutation_hooks_constant_contains_expected_hooks() -> None:
    """Test que MUTATING_HOOKS contiene los hooks esperados."""
    assert "end-of-file-fixer" in MUTATING_HOOKS
    assert "mixed-line-ending" in MUTATING_HOOKS
    assert "trailing-whitespace" in MUTATING_HOOKS
    assert "ruff-format" in MUTATING_HOOKS
    assert "black" in MUTATING_HOOKS
    assert "isort" in MUTATING_HOOKS


def test_generated_artifact_paths_constant() -> None:
    """Test que GENERATED_ARTIFACT_PATHS contiene rutas de directorio esperadas."""
    assert any("context" in p for p in GENERATED_ARTIFACT_PATHS)
    assert any("events" in p for p in GENERATED_ARTIFACT_PATHS)


def test_hygiene_result_namedtuple() -> None:
    """Test que HygieneResult tiene la estructura esperada."""
    result = HygieneResult(passed=True, message="OK", details=["detalle1", "detalle2"])

    assert result.passed is True
    assert result.message == "OK"
    assert result.details == ["detalle1", "detalle2"]

    # Test sin detalles
    result2 = HygieneResult(passed=False, message="FAIL")
    assert result2.details is None
