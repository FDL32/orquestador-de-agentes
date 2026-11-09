"""Tests WOT-2026-161d: un `.py` no puede quedar fuera de check-ast ni ruff-check.

Before (Pre-condiciones):
    - Existe `.pre-commit-config.yaml` en la raiz del repo y PyYAML esta
      disponible.
    - `git` esta disponible: las rutas .py representativas se derivan del arbol
      REAL con `git ls-files '*.py'` (no son rutas sinteticas).

During (Proceso y Recursos):
    - Carga la config real con yaml.safe_load y el validador puro
      assert_python_hooks_cover() comprueba, para check-ast y ruff-check, los
      STAGES EFECTIVOS (hook.stages, o `default_stages` raiz, o todas si faltan
      ambos; una lista vacia NO cubre nada): deben cubrir pre-commit Y
      pre-push. El invariante exige que los stages efectivos cubran ambas
      etapas; NO prohibe `stages` (los hooks reales no los declaran y heredan
      todas).
    - Filtros de fichero cubiertos: raiz `files` (si existe debe casar TODAS las
      rutas .py representativas) y raiz `exclude` (no puede casar ninguna); por
      hook: `files` prohibido, `exclude` que no case rutas .py reales
      (re.search, como pre-commit), `types` ausente o con python, `types_or`
      ausente o con python, `exclude_types` sin python/file/text, y
      `pass_filenames: true` (ausente cuenta como true) en AMBOS hooks.
    - NO cubre (declarado, para no prometer de mas):
      `minimum_pre_commit_version`, `fail_fast`, `ci`,
      `default_language_version`, `default_install_hook_types`, ni claves de
      hook ajenas al filtrado (`args`, `alias`, `verbose`, `log_file`,
      `require_serial`, `always_run`, `language`, `language_version`, `entry`,
      `additional_dependencies`). `exclude` a nivel de `repos[]` no existe en
      pre-commit 4.5.1 (solo raiz y por hook).
    - CONDICIONALIDAD DECLARADA: el invariante garantiza el CABLEADO de los
      hooks a pre-commit y pre-push, NO que pre-push lea los blobs del rango
      empujado (pre-commit pasa rutas y los hooks leen el working tree: ver
      FP-015). La cobertura de pre-push es condicional al arbol de trabajo.
    - Los mutantes son tests PERMANENTES: deepcopy de la config real + una
      mutacion, esperando AssertionError del validador. Sin variables de
      entorno ni ficheros ajenos.

After (Post-condiciones y Errores):
    - Verde con la config real; cada mutante mata su caso. Una mutacion del
      propio validador que ignore `default_stages` deja 2 casos rojos
      (raiz-default-stages-pre-commit y raiz-default-stages-vacio).
    - Solo lectura: no escribe el YAML ni toca el repo.
"""

from __future__ import annotations

import copy
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml


_ROOT = Path(__file__).resolve().parent.parent.parent

_HOOK_IDS = ("check-ast", "ruff-check")
_REQUIRED_STAGES = ("pre-commit", "pre-push")
# Stages REALES de pre-commit 4.5.1 (pre_commit/clientlib.py:26-39). Ojo:
# 'commit', 'merge-commit' y 'push' son alias LEGADOS que pre-commit transforma
# a 'pre-commit', 'pre-merge-commit' y 'pre-push'. Si el hook no declara
# `stages` y la raiz no declara `default_stages`, hereda TODAS.
_ALL_STAGES = frozenset(
    {
        "commit-msg",
        "post-checkout",
        "post-commit",
        "post-merge",
        "post-rewrite",
        "pre-commit",
        "pre-merge-commit",
        "pre-push",
        "pre-rebase",
        "prepare-commit-msg",
        "manual",
    }
)
# Un .py tiene los tags file, text y python: excluir cualquiera de ellos en
# `exclude_types` lo saca de la verificacion (types es AND y exclude_types
# descarta por interseccion).
_PYTHON_TAGS = frozenset({"python", "file", "text"})


def _python_paths() -> tuple[str, ...]:
    """Rutas .py representativas del arbol REAL (una por directorio con .py).

    Before: el cwd contiene el arbol git del repo.
    During: `git ls-files '*.py'` da los .py tracked; se toma un
    `<primer-nivel>/example.py` por cada directorio de primer nivel que tenga al
    menos un .py, mas `.agent/hooks/example.py` y `.agent/runtime/example.py` si
    esos subdirectorios tienen .py.
    After: tupla ordenada no vacia; AssertionError explicita si git no esta,
    falla o devuelve lista vacia (nunca silencioso). tests/sandbox/ se excluye
    porque es el exclude legitimo de check-ast (`^tests/sandbox/`).
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except FileNotFoundError as exc:
        raise AssertionError(
            "git no esta disponible: no puedo construir las rutas .py reales"
        ) from exc
    assert result.returncode == 0, (
        f"git ls-files fallo (rc {result.returncode}): {result.stderr.strip()}"
    )
    tracked = [line for line in result.stdout.splitlines() if line.strip()]
    assert tracked, "git ls-files '*.py' devolvio una lista vacia"
    top_dirs = {Path(name).parts[0] for name in tracked if len(Path(name).parts) > 1}
    paths = {f"{directory}/example.py" for directory in top_dirs}
    for extra in (".agent/hooks", ".agent/runtime"):
        if any(name.startswith(f"{extra}/") for name in tracked):
            paths.add(f"{extra}/example.py")
    return tuple(sorted(p for p in paths if not p.startswith("tests/sandbox/")))


_PYTHON_PATHS = _python_paths()


def _load_config() -> dict:
    """Carga el `.pre-commit-config.yaml` real; falla si no es parseable."""
    path = _ROOT / ".pre-commit-config.yaml"
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict), f"{path} no parsea a un mapping YAML"
    return data


def _hook(config: dict, hook_id: str) -> dict:
    """Devuelve el hook `hook_id`; AssertionError si falta o esta duplicado."""
    matches = [
        hook
        for repo in config.get("repos") or []
        for hook in repo.get("hooks") or []
        if hook.get("id") == hook_id
    ]
    assert len(matches) == 1, (
        f"hook {hook_id!r} aparece {len(matches)} veces en "
        ".pre-commit-config.yaml (se espera exactamente 1)"
    )
    assert isinstance(matches[0], dict)
    return matches[0]


def _effective_stages(config: dict, hook: dict) -> list[str]:
    """Stages efectivos: hook.stages > default_stages raiz > todas."""
    stages = hook.get("stages")
    if stages is None:
        stages = config.get("default_stages")
    if stages is None:
        return sorted(_ALL_STAGES)
    return list(stages)


def assert_python_hooks_cover(config: dict) -> None:
    """Validador puro: check-ast y ruff-check cubren commit Y push, sin filtros.

    Before: `config` es el mapping YAML ya parseado de `.pre-commit-config.yaml`.
    During: aplica los filtros GLOBALES de raiz (`files` debe casar todas las
    rutas .py representativas; `exclude` no puede casar ninguna) y, por hook,
    calcula los stages efectivos (hook.stages, o `default_stages` raiz, o
    todas), exige pre-commit y pre-push, prohibe `files`, exige `types` y
    `types_or` ausentes o con python, prohibe `exclude_types` con python/file/
    text, comprueba con re.search que `exclude` no casa rutas .py
    representativas, y exige `pass_filenames: true` (ausente = true).
    After: retorna None si el invariante se cumple; AssertionError con el motivo
    exacto si no. No escribe nada.
    """
    root_files = config.get("files")
    if root_files is not None:
        for path in _PYTHON_PATHS:
            assert re.search(root_files, path), (
                f"raiz: files={root_files!r} no casa la ruta Python {path!r}"
            )
    root_exclude = config.get("exclude")
    if root_exclude is not None:
        for path in _PYTHON_PATHS:
            assert not re.search(root_exclude, path), (
                f"raiz: exclude={root_exclude!r} casa la ruta Python {path!r}"
            )
    for hook_id in _HOOK_IDS:
        hook = _hook(config, hook_id)
        effective = _effective_stages(config, hook)
        missing = [stage for stage in _REQUIRED_STAGES if stage not in effective]
        assert not missing, (
            f"{hook_id}: stages efectivos {effective} no cubren {missing} "
            "(git rebase no corre el stage pre-commit: retirarlo de pre-push "
            "deja un .py replayado sin red condicional)"
        )
        assert "files" not in hook, (
            f"{hook_id}: declara `files` y puede dejar fuera los .py reales"
        )
        types = hook.get("types")
        assert types is None or "python" in types, (
            f"{hook_id}: types={types} no incluye python"
        )
        types_or = hook.get("types_or")
        assert types_or is None or "python" in types_or, (
            f"{hook_id}: types_or={types_or} no incluye python "
            "(types y types_or se aplican juntos: el .py debe pasar ambos)"
        )
        exclude_types = hook.get("exclude_types")
        if exclude_types:
            forbidden = _PYTHON_TAGS.intersection(exclude_types)
            assert not forbidden, (
                f"{hook_id}: exclude_types={exclude_types} excluye "
                f"{sorted(forbidden)}: el .py sale fuera"
            )
        exclude = hook.get("exclude")
        if exclude:
            for path in _PYTHON_PATHS:
                assert not re.search(exclude, path), (
                    f"{hook_id}: exclude={exclude!r} casa la ruta Python {path!r}"
                )
        assert hook.get("pass_filenames", True) is True, (
            f"{hook_id}: pass_filenames debe ser true para ver el .py"
        )


def test_161d_config_real_cumple_el_invariante() -> None:
    """Control positivo: la config real del repo pasa el validador."""
    assert_python_hooks_cover(_load_config())


def test_161d_rutas_python_reales_no_vacias() -> None:
    """Las rutas representativas salen del arbol real y cubren varios dirs."""
    assert _PYTHON_PATHS, "la lista de rutas .py representativas esta vacia"
    assert len(_PYTHON_PATHS) >= 2, _PYTHON_PATHS


# Mutantes permanentes: cada uno parte de una copia de la config REAL y espera
# que el validador lo rechace. Sin variables de entorno ni ficheros ajenos.
def _set_root_files_docs(config: dict) -> None:
    config["files"] = "^docs/"


def _set_root_exclude_py(config: dict) -> None:
    config["exclude"] = r".*\.py$"


def _set_root_exclude_agent_system(config: dict) -> None:
    config["exclude"] = "^agent_system/"


def _set_root_default_stages_precommit(config: dict) -> None:
    config["default_stages"] = ["pre-commit"]


def _set_root_default_stages_empty(config: dict) -> None:
    config["default_stages"] = []


def _set_stages_check_ast_precommit(config: dict) -> None:
    _hook(config, "check-ast")["stages"] = ["pre-commit"]


def _set_stages_check_ast_empty(config: dict) -> None:
    _hook(config, "check-ast")["stages"] = []


def _set_stages_ruff_prepush(config: dict) -> None:
    _hook(config, "ruff-check")["stages"] = ["pre-push"]


def _set_stages_ruff_precommit(config: dict) -> None:
    _hook(config, "ruff-check")["stages"] = ["pre-commit"]


def _set_files_check_ast(config: dict) -> None:
    _hook(config, "check-ast")["files"] = "^docs/"


def _set_exclude_ruff_scripts(config: dict) -> None:
    _hook(config, "ruff-check")["exclude"] = "^scripts/"


def _set_exclude_ruff_skills(config: dict) -> None:
    _hook(config, "ruff-check")["exclude"] = "^skills/"


def _set_exclude_ruff_runtime(config: dict) -> None:
    _hook(config, "ruff-check")["exclude"] = "^runtime/"


def _set_types_check_ast_yaml(config: dict) -> None:
    _hook(config, "check-ast")["types"] = ["yaml"]


def _set_types_or_ruff_markdown(config: dict) -> None:
    _hook(config, "ruff-check")["types_or"] = ["markdown"]


def _set_exclude_types_check_ast_python(config: dict) -> None:
    _hook(config, "check-ast")["exclude_types"] = ["python"]


def _set_pass_filenames_ruff_false(config: dict) -> None:
    _hook(config, "ruff-check")["pass_filenames"] = False


def _set_pass_filenames_check_ast_false(config: dict) -> None:
    _hook(config, "check-ast")["pass_filenames"] = False


def _remove_hook(config: dict, hook_id: str) -> None:
    for repo in config.get("repos") or []:
        hooks = repo.get("hooks") or []
        for hook in list(hooks):
            if hook.get("id") == hook_id:
                hooks.remove(hook)
                return
    raise AssertionError(f"hook {hook_id!r} no estaba (mutante invalido)")


def _remove_check_ast(config: dict) -> None:
    _remove_hook(config, "check-ast")


def _remove_ruff_check(config: dict) -> None:
    _remove_hook(config, "ruff-check")


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_set_root_files_docs, id="raiz-files-docs"),
        pytest.param(_set_root_exclude_py, id="raiz-exclude-py"),
        pytest.param(_set_root_exclude_agent_system, id="raiz-exclude-agent_system"),
        pytest.param(
            _set_root_default_stages_precommit, id="raiz-default-stages-pre-commit"
        ),
        pytest.param(_set_root_default_stages_empty, id="raiz-default-stages-vacio"),
        pytest.param(_set_stages_check_ast_precommit, id="check-ast-stages-pre-commit"),
        pytest.param(_set_stages_check_ast_empty, id="check-ast-stages-vacio"),
        pytest.param(_set_stages_ruff_prepush, id="ruff-check-stages-pre-push"),
        pytest.param(_set_stages_ruff_precommit, id="ruff-check-stages-pre-commit"),
        pytest.param(_set_files_check_ast, id="check-ast-files-docs"),
        pytest.param(_set_exclude_ruff_scripts, id="ruff-check-exclude-scripts"),
        pytest.param(_set_exclude_ruff_skills, id="ruff-check-exclude-skills"),
        pytest.param(_set_exclude_ruff_runtime, id="ruff-check-exclude-runtime"),
        pytest.param(_set_types_check_ast_yaml, id="check-ast-types-yaml"),
        pytest.param(_set_types_or_ruff_markdown, id="ruff-check-types-or-markdown"),
        pytest.param(
            _set_exclude_types_check_ast_python,
            id="check-ast-exclude-types-python",
        ),
        pytest.param(
            _set_pass_filenames_ruff_false, id="ruff-check-pass-filenames-false"
        ),
        pytest.param(
            _set_pass_filenames_check_ast_false,
            id="check-ast-pass-filenames-false",
        ),
        pytest.param(_remove_check_ast, id="check-ast-ausente"),
        pytest.param(_remove_ruff_check, id="ruff-check-ausente"),
    ],
)
def test_161d_mutante_vuelve_rojo(mutate: Callable[[dict], None]) -> None:
    """Cada mutacion de la config real hace que el validador levante AssertionError."""
    config = copy.deepcopy(_load_config())
    mutate(config)
    with pytest.raises(AssertionError):
        assert_python_hooks_cover(config)
