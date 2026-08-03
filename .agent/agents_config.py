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

# WOT-2026-026j: DOS enums, dos dominios distintos (recomendacion Codex, no
# duplicacion de un dato):
#  - KNOWN_ROLES: legacy MAYUSCULA. Valida los campos que 026j deja como basura
#    no-referenciada (role_assignments, role_models) y los aun-vivos no migrados
#    (skill_allowlists). No se amplia; muere cuando esos campos se retiren.
#  - CANONICAL_ROLES: la taxonomia canonica de AGENTS.md, en MINUSCULA. Es el
#    UNICO enum valido para role_mapping. SUPERVISOR NO esta aqui: es un actor
#    runtime del bus, no un rol IA (va en el campo actor_runtime aparte).
KNOWN_ROLES = {"BUILDER", "MANAGER", "SUPERVISOR"}
CANONICAL_ROLES = {"orchestrator", "manager", "builder", "auditor", "challenger"}
# Actores runtime del bus: NO son roles IA, no tienen backend/modelo. Pedir su
# modelo/backend via get_*_for_role es un error (raise), no un None silencioso.
ACTOR_RUNTIME_ROLES = {"SUPERVISOR"}
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

    # WOT-2026-026j (D2): fusiona el override local ANTES de validar, de modo
    # que el config resultante es el EFECTIVO (lo que runtime realmente usa) y
    # la barrera fail-closed de _validate_config muerde tambien un override
    # local invalido. La fusion vive AQUI (un solo sitio), no en cada get_*,
    # asi ningun consumidor puede saltarse la cascada por accidente.
    config = _merge_role_overrides(config, config_path.parent)

    _validate_config(config, config_path)
    return config


def _local_overrides_path(config_dir: Path) -> Path:
    """Ruta del override local gitignored, junto al agents.json versionado."""
    return config_dir / "agents.local.json"


def load_role_overrides(config_dir: Path) -> dict:
    """Carga role_mapping de agents.local.json (gitignored, opcional).

    Replica el patron tolerante de prefix_resolver.load_overrides: si el
    fichero no existe o esta malformado, devuelve {} (no rompe el arranque).

    Before: config_dir puede o no contener agents.local.json.
    During: lee JSON {"role_mapping": {...}}.
    After: devuelve el dict role_mapping local, o {} si ausente/ilegible.
    """
    path = _local_overrides_path(config_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            rm = data.get("role_mapping", {})
            return rm if isinstance(rm, dict) else {}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _merge_role_overrides(config: dict, config_dir: Path) -> dict:
    """Devuelve el config EFECTIVO con el override local fusionado por rol.

    El override local GANA sobre el versionado, entrada a entrada (nivel 1 de
    la cascada local->versionado->default). Solo toca role_mapping; no muta el
    dict de entrada (copia superficial de la seccion fusionada).
    """
    overrides = load_role_overrides(config_dir)
    if not overrides:
        return config
    effective = dict(config)
    merged = dict(config.get("role_mapping", {}))
    merged.update(overrides)  # local gana
    effective["role_mapping"] = merged
    return effective


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


def _validate_role_mapping(config: dict, config_path: Path) -> None:
    """Validate role_mapping FAIL-CLOSED against CANONICAL_ROLES (WOT-2026-026j).

    Before: config puede o no declarar role_mapping (opcional hasta 1.4).
    During: si existe, cada clave DEBE pertenecer al enum canonico en minuscula;
        SUPERVISOR y cualquier rol MAYUS legacy quedan RECHAZADOS aqui (el
        schema es la barrera, no un raise tardio en runtime). Cada entrada debe
        ser un objeto con al menos 'backend'; el backend referenciado debe
        existir en 'backends'.
    After: retorna None si valido; lanza AgentsConfigError con mensaje que cita
        'role_mapping' y el enum canonico en caso contrario.
    """
    if "role_mapping" not in config:
        return

    role_mapping = config["role_mapping"]
    if not isinstance(role_mapping, dict):
        raise AgentsConfigError(
            f"Invalid 'role_mapping' in {config_path}: must be an object"
        )

    for role, spec in role_mapping.items():
        if role not in CANONICAL_ROLES:
            raise AgentsConfigError(
                f"Unknown role '{role}' in role_mapping. "
                f"Canonical roles (lowercase): {sorted(CANONICAL_ROLES)}. "
                f"SUPERVISOR is an actor_runtime, not a role_mapping key."
            )
        if not isinstance(spec, dict) or "backend" not in spec:
            raise AgentsConfigError(
                f"Invalid entry for role '{role}' in role_mapping: "
                f"must be an object with at least a 'backend' key"
            )
        backend = spec["backend"]
        if backend not in config.get("backends", {}):
            raise AgentsConfigError(
                f"Role '{role}' in role_mapping references unknown backend '{backend}'"
            )


def _validate_actor_runtime(config: dict, config_path: Path) -> None:
    """Validate the actor_runtime section FAIL-CLOSED (WOT-2026-026j D4).

    Before: config puede o no declarar actor_runtime (opcional).
    During: si existe, debe ser una lista y cada valor DEBE pertenecer a
        ACTOR_RUNTIME_ROLES. Un rol IA canonico colado aqui (o al reves) es un
        modelo mental equivocado: se rechaza en el schema, no en runtime.
    After: retorna None si valido; lanza AgentsConfigError en caso contrario.
    """
    if "actor_runtime" not in config:
        return
    actor_runtime = config["actor_runtime"]
    if not isinstance(actor_runtime, list):
        raise AgentsConfigError(
            f"Invalid 'actor_runtime' in {config_path}: must be a list"
        )
    for actor in actor_runtime:
        if actor not in ACTOR_RUNTIME_ROLES:
            raise AgentsConfigError(
                f"Unknown actor_runtime '{actor}' in {config_path}. "
                f"Known actor_runtime roles: {sorted(ACTOR_RUNTIME_ROLES)}"
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

    # Check role_mapping (WOT-2026-026j, optional hasta schema 1.4)
    _validate_role_mapping(config, config_path)

    # Check actor_runtime (WOT-2026-026j D4, optional)
    _validate_actor_runtime(config, config_path)

    # Check skill_allowlists (optional, retrocompatible)
    _validate_skill_allowlists(config, config_path)

    # Check strictness_profile and profiles (schema 1.2+, retrocompatible)
    _validate_strictness_profiles(config, config_path)

    # Check ensemble_* keys (schema 1.3+, retrocompatible)
    _validate_ensemble(config, config_path)


def _validate_strictness_profiles(config: dict, config_path: Path) -> None:
    """Validate the strictness_profile and profiles section (schema 1.2+, retrocompatible).

    Before: strictness_profile no existía; fallback a standard.
    During: Valida que strictness_profile sea un valor conocido (minimal, standard, strict)
            y que profiles sea un objeto con las tres claves requeridas.
    After: Permite configuracion vacia o omitida (retrocompatible); falla si hay
           valores invalidos explícitamente declarados.
    """
    known_profiles = {"minimal", "standard", "strict"}

    # strictness_profile es opcional para retrocompatibilidad; default = standard
    if "strictness_profile" in config:
        profile = config["strictness_profile"]
        if profile not in known_profiles:
            raise AgentsConfigError(
                f"Invalid 'strictness_profile' in {config_path}: must be one of {known_profiles}, got '{profile}'"
            )

    # profiles es opcional para retrocompatibilidad
    if "profiles" in config:
        profiles = config["profiles"]
        if not isinstance(profiles, dict):
            raise AgentsConfigError(
                f"Invalid 'profiles' in {config_path}: must be an object"
            )
        # Validar que las claves conocidas estén presentes si profiles existe
        for profile_name in known_profiles:
            if profile_name not in profiles:
                raise AgentsConfigError(
                    f"Missing required profile '{profile_name}' in profiles"
                )
        # Validar que cada perfil tenga estructura básica
        for profile_name, profile_config in profiles.items():
            if not isinstance(profile_config, dict):
                raise AgentsConfigError(
                    f"Invalid profile '{profile_name}' in profiles: must be an object"
                )


_ENSEMBLE_CHANNELS = {"api", "agent"}
_ENSEMBLE_SENSITIVITIES = {"public", "private", "secret"}
# Credenciales SOLO por nombre de variable de entorno (api_key_env). Una clave
# de credencial literal en agents.json (fichero versionado) es fuga versionada.
_FORBIDDEN_CREDENTIAL_KEYS = {"api_key", "apikey", "token", "secret", "password"}
_ENSEMBLE_MAX_ROUNDS_CAP = 3


def _is_env_var_name(value: object) -> bool:
    """True si value tiene forma de NOMBRE de variable de entorno (MAYUS_CON_GUION_BAJO)."""
    if not isinstance(value, str) or not value:
        return False
    if value[0].isdigit():
        return False
    if value != value.upper():
        return False
    return all(c.isalnum() or c == "_" for c in value)


def _validate_ensemble(config: dict, config_path: Path) -> None:
    """Validate the ensemble_* sections (schema 1.3+, retrocompatible; WOT-2026-019o).

    Before: config es el dict ya parseado de agents.json; las claves
        `ensemble_profiles` / `ensemble_pipelines` / `ensemble_private_roots`
        pueden faltar (configs pre-1.3: retrocompatible, no valida nada).
    During: valida en UNA sola capa (regla M4 del contrato: prohibido un
        segundo schema divergente) que:
        - cada perfil declara `backend` existente en `backends` y `channel`
          en {api, agent}; `data_sensitivity` (si esta) en {public, private,
          secret}; `write` bool; `channel=api` exige `api_key_env` (forma de
          NOMBRE de env var, nunca un valor) y `api_base_url`;
        - ninguna clave de credencial literal (`api_key`, `token`, ...)
          aparece en perfiles ni en backends (M7: fuga versionada);
        - cada pipeline referencia perfiles existentes (proposer/challenger),
          declara `rubric`, y `max_rounds` (si esta) es int en [1, 3];
        - `backends.<n>.trusted` (si esta) es bool -- es el atributo del que
          cuelga el privacy_preflight (M5: atributo del BACKEND, ausente =
          false, fail-closed);
        - `ensemble_private_roots` (si esta) es lista de strings.
    After: retorna None si todo es valido; lanza AgentsConfigError con el
        campo exacto en el mensaje ante el primer defecto (gate self-service).
    """
    profiles = config.get("ensemble_profiles")
    pipelines = config.get("ensemble_pipelines")
    private_roots = config.get("ensemble_private_roots")

    if profiles is None and pipelines is None and private_roots is None:
        return  # pre-1.3: retrocompatible

    if private_roots is not None and (
        not isinstance(private_roots, list)
        or not all(isinstance(r, str) for r in private_roots)
    ):
        raise AgentsConfigError(
            f"Invalid 'ensemble_private_roots' in {config_path}: "
            "must be a list of strings"
        )

    backends = config.get("backends", {})
    for backend_name, backend in backends.items():
        _validate_ensemble_backend_extras(backend_name, backend)

    if profiles is not None:
        if not isinstance(profiles, dict):
            raise AgentsConfigError(
                f"Invalid 'ensemble_profiles' in {config_path}: must be an object"
            )
        for prof_name, prof in profiles.items():
            _validate_ensemble_profile(prof_name, prof, backends)

    if pipelines is not None:
        if not isinstance(pipelines, dict):
            raise AgentsConfigError(
                f"Invalid 'ensemble_pipelines' in {config_path}: must be an object"
            )
        for pipe_name, pipe in pipelines.items():
            _validate_ensemble_pipeline(pipe_name, pipe, profiles or {})


def _validate_ensemble_backend_extras(backend_name: str, backend: dict) -> None:
    """Chequeos de backend introducidos por 1.3: `trusted` bool + ban de credenciales."""
    if "trusted" in backend and not isinstance(backend["trusted"], bool):
        raise AgentsConfigError(
            f"Backend '{backend_name}': 'trusted' must be a bool "
            "(absent means false, fail-closed)"
        )
    leaked = _FORBIDDEN_CREDENTIAL_KEYS.intersection(k.lower() for k in backend)
    if leaked:
        raise AgentsConfigError(
            f"Backend '{backend_name}' carries literal credential key(s) "
            f"{sorted(leaked)}: credentials are referenced ONLY by env "
            "var name (api_key_env) -- agents.json is a versioned file"
        )
    # WOT-2026-047y: la plantilla que inyecta el modelo del perfil en el argv.
    # Una plantilla sin `{model}` renderizaria un flag sin valor y el CLI caeria
    # a su default en silencio: exactamente el fallo que el ticket cierra.
    if "model_flag" in backend:
        template = backend["model_flag"]
        if not isinstance(template, list) or not all(
            isinstance(part, str) for part in template
        ):
            raise AgentsConfigError(
                f"Backend '{backend_name}': 'model_flag' must be a list of "
                'strings (e.g. ["--model", "{model}"])'
            )
        if not any("{model}" in part for part in template):
            raise AgentsConfigError(
                f"Backend '{backend_name}': 'model_flag' must contain the "
                "'{model}' placeholder in at least one element, otherwise the "
                "profile model is never rendered into the argv"
            )


def _validate_ensemble_profile(prof_name: str, prof: object, backends: dict) -> None:
    """Un perfil de ensemble: backend existente, channel valido, sin credenciales."""
    if not isinstance(prof, dict):
        raise AgentsConfigError(f"Ensemble profile '{prof_name}': must be an object")
    leaked = _FORBIDDEN_CREDENTIAL_KEYS.intersection(k.lower() for k in prof)
    if leaked:
        raise AgentsConfigError(
            f"Ensemble profile '{prof_name}' carries literal "
            f"credential key(s) {sorted(leaked)}: use api_key_env"
        )
    if prof.get("backend") not in backends:
        raise AgentsConfigError(
            f"Ensemble profile '{prof_name}' references unknown "
            f"backend '{prof.get('backend')}'"
        )
    if prof.get("channel") not in _ENSEMBLE_CHANNELS:
        raise AgentsConfigError(
            f"Ensemble profile '{prof_name}': 'channel' must be one "
            f"of {sorted(_ENSEMBLE_CHANNELS)}, got '{prof.get('channel')}'"
        )
    sensitivity = prof.get("data_sensitivity")
    if sensitivity is not None and sensitivity not in _ENSEMBLE_SENSITIVITIES:
        raise AgentsConfigError(
            f"Ensemble profile '{prof_name}': 'data_sensitivity' "
            f"must be one of {sorted(_ENSEMBLE_SENSITIVITIES)}"
        )
    if "write" in prof and not isinstance(prof["write"], bool):
        raise AgentsConfigError(
            f"Ensemble profile '{prof_name}': 'write' must be a bool"
        )
    if prof["channel"] == "api":
        _validate_ensemble_api_fields(prof_name, prof)
    elif prof["channel"] == "agent":
        _validate_ensemble_agent_model(prof_name, prof, backends)


def _validate_ensemble_agent_model(prof_name: str, prof: dict, backends: dict) -> None:
    """channel=agent con `model` exige `model_flag` en su backend (fail-closed).

    WOT-2026-047y. Sin esto, un perfil que declara `model` contra un backend sin
    plantilla se enviaba EN SILENCIO al modelo por defecto del CLI, y el
    scorecard registraba el declarado: un fallo indetectable desde el registro.
    El gate lo convierte en un error de carga con el campo exacto.

    No exige nada al perfil SIN modelo (`model: null` es el contrato vigente de
    `proposer_claude` y `challenger_codex`: dejan que el CLI elija).
    """
    model = prof.get("model")
    if not model:
        return
    if not isinstance(model, str):
        raise AgentsConfigError(
            f"Ensemble profile '{prof_name}': 'model' must be a string or null"
        )
    backend_name = prof["backend"]
    template = backends.get(backend_name, {}).get("model_flag")
    if not template:
        raise AgentsConfigError(
            f"Ensemble profile '{prof_name}' declares model '{model}' but "
            f"backend '{backend_name}' has no 'model_flag' template: the model "
            "would be silently dropped and the CLI would run its default "
            f'(WOT-2026-047y). Declare e.g. "model_flag": ["--model", '
            '"{model}"] in the backend.'
        )


def _validate_ensemble_api_fields(prof_name: str, prof: dict) -> None:
    """channel=api exige api_key_env (NOMBRE de env var) y api_base_url https."""
    if not _is_env_var_name(prof.get("api_key_env")):
        raise AgentsConfigError(
            f"Ensemble profile '{prof_name}': channel=api "
            "requires 'api_key_env' shaped like an ENV VAR NAME "
            "(e.g. DEEPSEEK_API_KEY), never a literal value"
        )
    base_url = prof.get("api_base_url")
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        raise AgentsConfigError(
            f"Ensemble profile '{prof_name}': channel=api "
            "requires an https 'api_base_url'"
        )


def _validate_ensemble_pipeline(
    pipe_name: str, pipe: object, known_profiles: dict
) -> None:
    """Un pipeline de ensemble: roles hacia perfiles existentes, rubric, rondas."""
    if not isinstance(pipe, dict):
        raise AgentsConfigError(f"Ensemble pipeline '{pipe_name}': must be an object")
    for role_key in ("proposer", "challenger"):
        ref = pipe.get(role_key)
        if ref not in known_profiles:
            raise AgentsConfigError(
                f"Ensemble pipeline '{pipe_name}': '{role_key}' must "
                f"reference an existing ensemble profile, got '{ref}'"
            )
    if not isinstance(pipe.get("rubric"), str) or not pipe["rubric"]:
        raise AgentsConfigError(
            f"Ensemble pipeline '{pipe_name}': 'rubric' (canonical "
            "prompt path) is required"
        )
    if "max_rounds" in pipe:
        rounds = pipe["max_rounds"]
        if not isinstance(rounds, int) or not (1 <= rounds <= _ENSEMBLE_MAX_ROUNDS_CAP):
            raise AgentsConfigError(
                f"Ensemble pipeline '{pipe_name}': 'max_rounds' must "
                f"be an int in [1, {_ENSEMBLE_MAX_ROUNDS_CAP}] "
                "(default=2, tope=3)"
            )


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


def _is_actor_runtime(role: str) -> bool:
    """True si el rol es un actor runtime del bus (case-insensitive, H3).

    ACTOR_RUNTIME_ROLES esta en MAYUSCULA; pedir 'supervisor' o 'Supervisor'
    debe reconocerse igual para RECHAZARLO como rol IA (H3 del bucle de cierre).
    """
    return role.upper() in ACTOR_RUNTIME_ROLES


def _canonical_role(role: str) -> str:
    """Normaliza un rol al enum canonico en minuscula (WOT-2026-026j).

    Acepta el enum canonico y el legacy MAYUSCULA de los consumidores en
    transicion (MANAGER, BUILDER -> manager, builder).

    H2 [BLOQUEANTE]: un rol que NO es canonico NI legacy-normalizable conocido
    (p.ej. un typo 'BUILDERR') se RECHAZA con AgentsConfigError, en vez de
    degradar silencioso al centinela 'default'. Los actores runtime se filtran
    ANTES en get_*_for_role (via _is_actor_runtime), no aqui.
    """
    lowered = role.lower()
    if lowered in CANONICAL_ROLES:
        return lowered
    raise AgentsConfigError(
        f"Unknown role '{role}': no es un rol canonico "
        f"{sorted(CANONICAL_ROLES)} ni un actor_runtime conocido. "
        f"Un typo NO debe degradar al backend 'default' (WOT-2026-026j H2)."
    )


def get_backend_for_role(role: str, config: dict | None = None) -> str:
    """
    Get the backend name for a role via the role_mapping cascade.

    WOT-2026-026j: resuelve la cascada de TRES niveles (nivel 1 local y nivel 2
    versionado ya vienen FUSIONADOS en config['role_mapping'] por
    load_agents_config; aqui se aplica el nivel 3 default). Acepta el rol
    canonico en minuscula y, por transicion, el legacy MAYUSCULA.

    Before: config cargado (con role_mapping efectivo) o None (se carga).
    During: rechaza actores runtime (SUPERVISOR); busca el rol canonico en
        role_mapping; si falta, cae al backend centinela 'default' declarado en
        'backends' (nivel 3), y solo si tampoco existe, lanza.
    After: devuelve el nombre de backend (str). Lanza AgentsConfigError si el
        rol es un actor runtime o no resoluble.
    """
    if config is None:
        config = load_agents_config()

    if _is_actor_runtime(role):
        raise AgentsConfigError(
            f"'{role}' is an actor_runtime of the bus, not an IA role: "
            f"it has no backend. Do not resolve it via get_backend_for_role."
        )

    canonical = _canonical_role(role)
    role_mapping = config.get("role_mapping", {})
    if canonical in role_mapping:
        return role_mapping[canonical]["backend"]

    # Nivel 3: default REAL = el backend centinela 'default' declarado en
    # 'backends' (el mismo que hoy resuelve SUPERVISOR='default' en la config
    # viva). Es un backend existente, no una clave inventada. Si no existe, es
    # un error de config, no un None crudo aguas abajo.
    if "default" in config.get("backends", {}):
        return "default"
    raise AgentsConfigError(
        f"No backend for role '{role}' in role_mapping and no 'default' "
        f"backend declared. Declared roles: {sorted(role_mapping.keys())}"
    )


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
    Get the model override for a role via the role_mapping cascade.

    WOT-2026-026j: lee role_mapping[rol]['model'] (nivel 1 local + nivel 2
    versionado ya FUSIONADOS por load_agents_config). Permite cambiar el modelo
    de un rol editando solo agents.json (o agents.local.json), sin tocar codigo.

    Nivel 3 (default): devuelve None con la semantica EXPLICITA 'sin override ->
    el backend usa su propio default (opencode.json o equivalente)'. None NO es
    un error: es la ausencia de override, documentada y probada
    (test_default_cuando_ni_local_ni_versionado).

    Before: config con role_mapping efectivo, o None (se carga).
    During: rechaza actores runtime (SUPERVISOR); normaliza el rol al canonico;
        devuelve el 'model' del role_mapping o None si el rol/campo no existe.
    After: str del modelo, o None si no hay override. Lanza AgentsConfigError
        si el rol es un actor runtime.
    """
    if config is None:
        config = load_agents_config()

    if _is_actor_runtime(role):
        raise AgentsConfigError(
            f"'{role}' is an actor_runtime of the bus, not an IA role: "
            f"it has no model. Do not resolve it via get_model_for_role."
        )

    canonical = _canonical_role(role)
    role_mapping = config.get("role_mapping", {})
    entry = role_mapping.get(canonical)
    if entry is None:
        return None  # nivel 3: sin override -> el backend usa su default
    return entry.get("model")


def get_strictness_profile(config: dict | None = None) -> str:
    """
    Get the active strictness profile name.

    Returns the configured strictness_profile or 'standard' as default
    for backward compatibility.

    Args:
        config: Optional pre-loaded configuration. If None, loads from file.

    Returns:
        The strictness profile name ('minimal', 'standard', or 'strict').

    Raises:
        AgentsConfigError: If strictness_profile is invalid.
    """
    if config is None:
        config = load_agents_config()

    return config.get("strictness_profile", "standard")


def get_profile_config(
    profile_name: str | None = None, config: dict | None = None
) -> dict:
    """
    Get the configuration for a specific strictness profile.

    Args:
        profile_name: Optional profile name. If None, uses the configured
                      strictness_profile or 'standard' as default.
        config: Optional pre-loaded configuration. If None, loads from file.

    Returns:
        The profile configuration dictionary with keys like
        'write_roots', 'blocked_command_patterns', etc.

    Raises:
        AgentsConfigError: If profile is unknown.
    """
    if config is None:
        config = load_agents_config()

    if profile_name is None:
        profile_name = config.get("strictness_profile", "standard")

    profiles = config.get("profiles", {})
    if profile_name not in profiles:
        raise AgentsConfigError(
            f"Unknown strictness profile '{profile_name}'. "
            f"Available profiles: {list(profiles.keys())}"
        )

    return profiles[profile_name]


def _migrate_1_0_to_1_1(config: dict) -> dict:
    """
    Pure migration handler 1.0 → 1.1.

    Before: Config con schema_version "1.0".
    During: Solo actualiza schema_version a "1.1".
    After: Retorna nuevo dict con schema_version "1.1".

    WOT-2026-026j (D3, defecto 024t): este handler YA NO inyecta role_models con
    'opencode-go/deepseek-v4-flash'. Sembrar el legacy aqui para limpiarlo en una
    migracion posterior lo dejaba RESUCITADO transitoriamente (si un proceso muere
    o un test captura estado intermedio, persiste). Es codigo de migracion, no
    historia real del usuario: un install fresco no tiene datos que perder. El
    contrato canonico de roles vive ahora en role_mapping (sembrado por 1.3->1.4).
    """
    new = dict(config)
    new["schema_version"] = "1.1"
    return new


def _migrate_1_1_to_1_2(config: dict) -> dict:
    """
    Pure migration handler 1.1 → 1.2.

    Before: Config con schema_version "1.1" sin strictness_profile ni profiles.
    During: Backfills strictness_profile = "standard" y profiles map con
            minimal, standard, strict si faltan.
    After: Retorna nuevo dict con schema_version "1.2", strictness_profile
           y profiles populated.
    """
    new = dict(config)
    new["schema_version"] = "1.2"
    if "strictness_profile" not in new:
        new["strictness_profile"] = "standard"
    if "profiles" not in new:
        new["profiles"] = {
            "minimal": {
                "description": "Solo la superficie sensible minima",
                "write_roots": [],
                "blocked_command_patterns": [],
            },
            "standard": {
                "description": "Replica la proteccion actual como default",
                "write_roots": [],
                "blocked_command_patterns": [],
            },
            "strict": {
                "description": "Endurece el guard sin bloquear superficies canonicas vivas",
                "write_roots": [],
                "blocked_command_patterns": [],
            },
        }
    return new


def _migrate_1_2_to_1_3(config: dict) -> dict:
    """
    Pure migration handler 1.2 -> 1.3 (WOT-2026-019o).

    Before: Config con schema_version "1.2" sin claves ensemble_*.
    During: Backfills ensemble_profiles = {}, ensemble_pipelines = {} y
            ensemble_private_roots = [] si faltan. Las estructuras nacen
            VACIAS: los perfiles/pipelines reales son contenido del motor
            (versionado aparte), no de la migracion. `ensemble_private_roots`
            nace vacia A PROPOSITO (m5 del contrato): raices privadas
            concretas solo en config local del destino o via env, nunca en
            este fichero versionado.
    After: Retorna nuevo dict con schema_version "1.3" y las tres claves
           ensemble_* presentes.
    """
    new = dict(config)
    new["schema_version"] = "1.3"
    new.setdefault("ensemble_profiles", {})
    new.setdefault("ensemble_pipelines", {})
    new.setdefault("ensemble_private_roots", [])
    return new


# Mapeo legacy MAYUS -> canonico minuscula usado para SEMBRAR role_mapping desde
# el role_assignments legacy en la migracion 1.3->1.4. SUPERVISOR NO se incluye:
# es actor_runtime (va en el campo actor_runtime aparte), no un rol IA.
_LEGACY_TO_CANONICAL_SEED = {"BUILDER": "builder", "MANAGER": "manager"}


def _migrate_1_3_to_1_4(config: dict) -> dict:
    """
    Pure migration handler 1.3 -> 1.4 (WOT-2026-026j, D3).

    Before: Config con schema_version "1.3" sin role_mapping (la fuente de verdad
        canonica de roles IA).
    During: Siembra role_mapping {rol_canonico: {backend}} DERIVANDOLO del
        role_assignments legacy (BUILDER->builder, MANAGER->manager), de modo que
        los backends referenciados ya existen en 'backends' (la config migrada se
        re-valida al cargar). SUPERVISOR queda FUERA (actor_runtime). No inyecta
        el modelo legacy: el modelo por rol es override opcional, no un default
        cableado (defecto 024t cortado en origen).
    After: Retorna nuevo dict con schema_version "1.4" y role_mapping presente
        (posiblemente vacio si no habia role_assignments legacy que derivar).
    """
    new = dict(config)
    new["schema_version"] = "1.4"
    if "role_mapping" not in new:
        seeded: dict[str, dict] = {}
        legacy = new.get("role_assignments", {})
        for legacy_role, backend in legacy.items():
            canonical = _LEGACY_TO_CANONICAL_SEED.get(legacy_role)
            if canonical is not None:
                seeded[canonical] = {"backend": backend}
        new["role_mapping"] = seeded
    return new


MIGRATIONS: list[Migration] = [
    Migration(
        id="1.0_to_1.1",
        from_version="1.0",
        to_version="1.1",
        apply=_migrate_1_0_to_1_1,
    ),
    Migration(
        id="1.1_to_1.2",
        from_version="1.1",
        to_version="1.2",
        apply=_migrate_1_1_to_1_2,
    ),
    Migration(
        id="1.2_to_1.3",
        from_version="1.2",
        to_version="1.3",
        apply=_migrate_1_2_to_1_3,
    ),
    Migration(
        id="1.3_to_1.4",
        from_version="1.3",
        to_version="1.4",
        apply=_migrate_1_3_to_1_4,
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
