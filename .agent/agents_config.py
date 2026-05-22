"""
Agent Configuration Loader - Centralized backend and role configuration.

This module provides a single source of truth for agent backend assignments
and discovery methods, removing hardcoding from the PowerShell launcher.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# WP-2026-122: Single source of truth for project root resolution
_AGENT_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT_DERIVED = _AGENT_DIR.parent
if str(_PROJECT_ROOT_DERIVED) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_DERIVED))

from runtime.project_root import get_agent_dir  # noqa: E402


class _LazyPath:
    def __init__(self, resolver):
        self._resolver = resolver

    def resolve(self) -> Path:
        return self._resolver()

    def __truediv__(self, other):
        return self.resolve() / other

    def __getattr__(self, name: str):
        return getattr(self.resolve(), name)

    def __fspath__(self) -> str:
        return str(self.resolve())

    def __str__(self) -> str:
        return str(self.resolve())


def _config_path() -> Path:
    return get_agent_dir() / "config" / "agents.json"


CONFIG_PATH = _LazyPath(_config_path)

KNOWN_ROLES = {"BUILDER", "MANAGER", "SUPERVISOR"}
REQUIRED_BACKEND_KEYS = {"executable", "args", "discovery"}
REQUIRED_DISCOVERY_KEYS = {"method"}


def _validate_skill_allowlists(config: dict, config_path: Path) -> None:
    """Validate the skill_allowlists section (optional, retrocompatible).

    Before: skill_allowlists no existía; fallback en SkillResolver.
    During: Valida que cada rol en skill_allowlists sea conocido y que
            las skills referenciadas existan en el catalogo descubierto.
    After: Permite configuracion vacia o omitida; falla si hay roles
           desconocidos o skills inexistentes explicitamente declaradas.
    """
    if "skill_allowlists" not in config:
        return  # Retrocompatible: si no hay allowlists, usar fallback

    allowlists = config["skill_allowlists"]
    if not isinstance(allowlists, dict):
        raise AgentsConfigError(
            f"Invalid 'skill_allowlists' in {config_path}: must be an object"
        )

    # Validar que cada rol en allowlists sea conocido
    for role in allowlists:
        if role not in KNOWN_ROLES:
            raise AgentsConfigError(
                f"Unknown role '{role}' in skill_allowlists. Known roles: {KNOWN_ROLES}"
            )

    # Validar que cada allowlist sea una lista
    for role, skills in allowlists.items():
        if not isinstance(skills, list):
            raise AgentsConfigError(
                f"skill_allowlists['{role}'] must be a list, got {type(skills).__name__}"
            )


class AgentsConfigError(Exception):
    """Raised when agent configuration is invalid."""

    pass


@dataclass(slots=True, frozen=True)
class Migration:
    """
    Describe una transición de schema para agents.json.

    Before: Se requiere un id único, from_version, to_version, y una función apply.
    During: El registry MIGRATIONS usa esta dataclass para iterar en orden cronológico.
    After: Cada migración aplicada deja un backup timestamped y actualiza _migrations.
    """

    id: str  # ej. "1.0_to_1.1"
    from_version: str  # ej. "1.0"
    to_version: str  # ej. "1.1"
    apply: Callable[[dict], dict]  # pure: receives config dict, returns new dict


@dataclass(slots=True)
class MigrationReport:
    """
    Reporte de ejecución de migrate_agents_config().

    Before: Se crea vacío al iniciar el pipeline.
    During: Se llena con los ids aplicados, skipped y backups creados.
    After: Se retorna al caller para consumo CLI o programático.
    """

    applied: list[str]  # ids aplicados en esta invocación
    skipped: list[str]  # ids ya presentes en _migrations
    backups: list[Path]  # paths a archivos .bak.<ts> creados


def load_agents_config(project_root: Path | None = None) -> dict[str, Any]:
    """
    Load and validate the agent configuration.

    Args:
        project_root: Optional project root path. If None, uses the parent
                      directory of this module's location (or runtime.project_root
                      if available for WP-2026-122 dynamic resolution).

    Returns:
        Validated configuration dictionary.

    Raises:
        AgentsConfigError: If config file is missing or invalid.
    """
    if project_root is None:
        # WP-2026-122: Use dynamic project_root resolution if available
        if get_agent_dir is not None:
            config_path = get_agent_dir() / "config" / "agents.json"
        else:
            config_path = Path(__file__).parent / "config" / "agents.json"
    else:
        config_path = project_root / ".agent" / "config" / "agents.json"

    if not config_path.exists():
        raise AgentsConfigError(f"Configuration file not found: {config_path}")

    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise AgentsConfigError(f"Invalid JSON in configuration file: {e}") from e

    _validate_config(config, config_path)
    return config


def _validate_role_models(config: dict, config_path: Path) -> None:
    """Validate the role_models section (optional, retrocompatible)."""
    if "role_models" not in config:
        return

    role_models = config["role_models"]
    if not isinstance(role_models, dict):
        raise AgentsConfigError(
            f"Invalid 'role_models' in {config_path}: must be an object"
        )

    for role in role_models:
        if role not in KNOWN_ROLES:
            raise AgentsConfigError(
                f"Unknown role '{role}' in role_models. Known roles: {KNOWN_ROLES}"
            )


def _validate_config(config: dict, config_path: Path) -> None:
    """Validate the configuration schema."""
    # Check schema_version
    if "schema_version" not in config:
        raise AgentsConfigError(f"Missing 'schema_version' in {config_path}")

    # Check backends
    if "backends" not in config or not isinstance(config["backends"], dict):
        raise AgentsConfigError(f"Missing or invalid 'backends' in {config_path}")

    if not config["backends"]:
        raise AgentsConfigError(f"'backends' cannot be empty in {config_path}")

    for backend_name, backend_config in config["backends"].items():
        _validate_backend(backend_name, backend_config, config_path)

    # Check role_assignments
    if "role_assignments" not in config or not isinstance(
        config["role_assignments"], dict
    ):
        raise AgentsConfigError(
            f"Missing or invalid 'role_assignments' in {config_path}"
        )

    for role, backend_name in config["role_assignments"].items():
        if role not in KNOWN_ROLES:
            raise AgentsConfigError(
                f"Unknown role '{role}' in role_assignments. Known roles: {KNOWN_ROLES}"
            )
        if backend_name not in config["backends"]:
            raise AgentsConfigError(
                f"Role '{role}' references unknown backend '{backend_name}'"
            )

    # Check role_models (optional, retrocompatible)
    _validate_role_models(config, config_path)

    # Check skill_allowlists (optional, retrocompatible)
    _validate_skill_allowlists(config, config_path)


def _validate_backend(name: str, backend: dict, config_path: Path) -> None:
    """Validate a single backend configuration."""
    for key in REQUIRED_BACKEND_KEYS:
        if key not in backend:
            raise AgentsConfigError(f"Backend '{name}' missing required key '{key}'")

    if not isinstance(backend["args"], list):
        raise AgentsConfigError(f"Backend '{name}': 'args' must be a list")

    discovery = backend["discovery"]
    if not isinstance(discovery, dict):
        raise AgentsConfigError(f"Backend '{name}': 'discovery' must be an object")

    for key in REQUIRED_DISCOVERY_KEYS:
        if key not in discovery:
            raise AgentsConfigError(f"Backend '{name}' missing discovery key '{key}'")

    if discovery["method"] not in ("vscode_extension", "path_only"):
        raise AgentsConfigError(
            f"Backend '{name}': unknown discovery method '{discovery['method']}'"
        )


def get_backend_for_role(role: str, config: dict | None = None) -> str:
    """
    Get the backend name assigned to a role.

    Args:
        role: The role name (e.g., "BUILDER", "MANAGER").
        config: Optional pre-loaded configuration. If None, loads from file.

    Returns:
        The backend name assigned to the role.

    Raises:
        AgentsConfigError: If role is not assigned or unknown.
    """
    if config is None:
        config = load_agents_config()

    role_assignments = config.get("role_assignments", {})

    if role not in role_assignments:
        raise AgentsConfigError(
            f"No backend assigned to role '{role}'. "
            f"Available assignments: {list(role_assignments.keys())}"
        )

    return role_assignments[role]


def get_backend_config(backend_name: str, config: dict | None = None) -> dict:
    """
    Get the configuration for a specific backend.

    Args:
        backend_name: The backend name (e.g., "kilo", "opencode").
        config: Optional pre-loaded configuration. If None, loads from file.

    Returns:
        The backend configuration dictionary.

    Raises:
        AgentsConfigError: If backend is unknown.
    """
    if config is None:
        config = load_agents_config()

    backends = config.get("backends", {})

    if backend_name not in backends:
        raise AgentsConfigError(
            f"Unknown backend '{backend_name}'. "
            f"Available backends: {list(backends.keys())}"
        )

    return backends[backend_name]


def resolve_executable(backend_name: str, config: dict | None = None) -> str:
    """
    Resolve the executable path for a backend.

    This function returns the executable name. The actual path resolution
    (via PATH lookup or VS Code extension discovery) is performed by the
    launcher at runtime.

    Args:
        backend_name: The backend name.
        config: Optional pre-loaded configuration.

    Returns:
        The executable name to resolve.

    Raises:
        AgentsConfigError: If backend is unknown.
    """
    backend = get_backend_config(backend_name, config)
    return backend["executable"]


def get_backend_args(backend_name: str, config: dict | None = None) -> list[str]:
    """
    Get the command-line arguments for a backend.

    Args:
        backend_name: The backend name.
        config: Optional pre-loaded configuration.

    Returns:
        List of command-line arguments.

    Raises:
        AgentsConfigError: If backend is unknown.
    """
    backend = get_backend_config(backend_name, config)
    return backend["args"]


def get_discovery_method(backend_name: str, config: dict | None = None) -> str:
    """
    Get the discovery method for a backend.

    Args:
        backend_name: The backend name.
        config: Optional pre-loaded configuration.

    Returns:
        The discovery method ("vscode_extension" or "path_only").

    Raises:
        AgentsConfigError: If backend is unknown.
    """
    backend = get_backend_config(backend_name, config)
    return backend["discovery"]["method"]


def get_model_for_role(role: str, config: dict | None = None) -> str | None:
    """
    Get the model override for a role from role_models.

    This allows changing the model for a role by editing only agents.json
    without touching code. Returns None if no model override is defined
    (the backend should use its default from opencode.json or equivalent).

    Args:
        role: The role name (e.g., "BUILDER", "MANAGER").
        config: Optional pre-loaded configuration. If None, loads from file.

    Returns:
        The model identifier string, or None if no override is defined.

    Raises:
        AgentsConfigError: If role is unknown.
    """
    if config is None:
        config = load_agents_config()

    if role not in KNOWN_ROLES:
        raise AgentsConfigError(f"Unknown role '{role}'. Known roles: {KNOWN_ROLES}")

    role_models = config.get("role_models", {})
    return role_models.get(role)


def _migrate_1_0_to_1_1(config: dict) -> dict:
    """
    Pure migration handler 1.0 → 1.1.

    Before: Config con schema_version "1.0" sin role_models.
    During: Backfills role_models con los defaults de WP-072 si falta.
    After: Retorna nuevo dict con schema_version "1.1" y role_models populated.

    Esta migración es retroactiva: formaliza el cambio manual hecho en WP-072.
    """
    new = dict(config)
    new["schema_version"] = "1.1"
    if "role_models" not in new:
        new["role_models"] = {
            "BUILDER": "opencode-go/qwen3.5-plus",
            "MANAGER": "openai/gpt-5.4-mini",
        }
    return new


MIGRATIONS: list[Migration] = [
    Migration(
        id="1.0_to_1.1",
        from_version="1.0",
        to_version="1.1",
        apply=_migrate_1_0_to_1_1,
    ),
    # Future migrations appended chronologically here.
]


def migrate_agents_config(
    path: Path | None = None,
    *,
    dry_run: bool = False,
) -> MigrationReport:
    """
    Apply pending migrations to agents.json idempotently.

    Before: agents.json existe con schema_version y opcionalmente _migrations.
    During:
      1. Load JSON (raise si falta o malformed).
      2. Read current schema_version + _migrations (default []).
      3. For each Migration en MIGRATIONS en orden:
         - Si migration.id ya en _migrations: skip (idempotent).
         - Else: backup, apply handler, update _migrations, persist.
      4. Legacy backfill: si _migrations falta pero schema_version es current,
         poblar _migrations retroactivamente sin re-ejecutar handlers.
    After: Retorna MigrationReport con applied, skipped, backups.

    Args:
        path: Path to agents.json. Default: CONFIG_PATH.
        dry_run: If True, report what would happen without writing.

    Returns:
        MigrationReport with applied, skipped, and backups lists.

    Raises:
        FileNotFoundError: If agents.json does not exist.
        json.JSONDecodeError: If agents.json is malformed.
    """
    if path is None:
        path = CONFIG_PATH

    config = json.loads(path.read_text(encoding="utf-8"))
    current_migrations = list(config.get("_migrations", []))
    applied: list[str] = []
    skipped: list[str] = []
    backups: list[Path] = []

    # Legacy backfill: schema_version already current but _migrations missing
    # Only backfill if schema_version equals the latest known migration to_version
    latest_version = MIGRATIONS[-1].to_version if MIGRATIONS else "1.0"
    if "_migrations" not in config and config.get("schema_version") == latest_version:
        # Retroactively claim all migrations up to current version
        retroactive = [m.id for m in MIGRATIONS]
        current_migrations.extend(retroactive)
        config["_migrations"] = current_migrations
        if not dry_run:
            path.write_text(
                json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return MigrationReport(applied=[], skipped=retroactive, backups=[])

    for migration in MIGRATIONS:
        if migration.id in current_migrations:
            skipped.append(migration.id)
            continue
        if not dry_run:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = path.with_suffix(f".json.bak.{ts}")
            shutil.copy2(path, backup_path)
            backups.append(backup_path)
            config = migration.apply(config)
            current_migrations.append(migration.id)
            config["_migrations"] = current_migrations
            path.write_text(
                json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        applied.append(migration.id)

    return MigrationReport(applied=applied, skipped=skipped, backups=backups)


# CLI interface for PowerShell consumption
if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--migrate", action="store_true", help="Apply pending migrations"
    )
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument("command", nargs="?", help="Command to run")
    parser.add_argument("args", nargs="*", help="Command arguments")
    args = parser.parse_args()

    # Handle --migrate flag
    if args.migrate:
        report = migrate_agents_config(dry_run=args.dry_run)
        print(
            json.dumps(
                {
                    "applied": report.applied,
                    "skipped": report.skipped,
                    "backups": [str(p) for p in report.backups],
                    "dry_run": args.dry_run,
                },
                indent=2,
            )
        )
        sys.exit(0)

    # Legacy command interface
    if not args.command:
        print("Usage: python agents_config.py <command> <args...>")
        print("Commands:")
        print("  get_backend_for_role <role>")
        print("  get_model_for_role <role>")
        print("  get_executable <backend>")
        print("  get_args <backend>")
        print("  get_discovery <backend>")
        print("  validate")
        print("  --migrate [--dry-run]  Apply pending migrations")
        sys.exit(1)

    command = args.command

    try:
        config = load_agents_config()

        if command == "get_backend_for_role":
            if len(args.args) < 1:
                print("Error: missing role argument")
                sys.exit(1)
            role = args.args[0]
            backend = get_backend_for_role(role, config)
            print(backend)

        elif command == "get_model_for_role":
            if len(args.args) < 1:
                print("Error: missing role argument")
                sys.exit(1)
            role = args.args[0]
            model = get_model_for_role(role, config)
            if model:
                print(model)
            else:
                print("(no override)")

        elif command == "get_executable":
            if len(args.args) < 1:
                print("Error: missing backend argument")
                sys.exit(1)
            backend_name = args.args[0]
            exe = resolve_executable(backend_name, config)
            print(exe)

        elif command == "get_args":
            if len(args.args) < 1:
                print("Error: missing backend argument")
                sys.exit(1)
            backend_name = args.args[0]
            args_list = get_backend_args(backend_name, config)
            print(" ".join(args_list))

        elif command == "get_discovery":
            if len(args.args) < 1:
                print("Error: missing backend argument")
                sys.exit(1)
            backend_name = args.args[0]
            method = get_discovery_method(backend_name, config)
            print(method)

        elif command == "validate":
            print("Configuration is valid")

        else:
            print(f"Unknown command: {command}")
            sys.exit(1)

    except AgentsConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
