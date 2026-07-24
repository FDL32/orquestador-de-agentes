"""Tests for agent configuration loader."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# Add project root FIRST, then .agent directory to path for imports.
# This ensures runtime.* modules (from root) are importable before
# .agent modules that depend on them.
_project_root = Path(__file__).parent.parent.parent
_agent_dir = _project_root / ".agent"
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_agent_dir) not in sys.path:
    sys.path.insert(0, str(_agent_dir))


from agents_config import (  # noqa: E402
    MIGRATIONS,
    AgentsConfigError,
    _migrate_1_0_to_1_1,
    _migrate_1_3_to_1_4,
    get_backend_args,
    get_backend_config,
    get_backend_for_role,
    get_discovery_method,
    get_model_for_role,
    load_agents_config,
    migrate_agents_config,
    resolve_executable,
)


# WOT-2026-019o (leccion 024t): las expectativas de la cadena de migraciones se
# DERIVAN del registro, nunca se pinean como snapshot -- un numero/lista fijada
# caduca sola con cada migracion nueva sin que el invariante haya cambiado.
ALL_MIGRATION_IDS = [m.id for m in MIGRATIONS]
LATEST_SCHEMA = MIGRATIONS[-1].to_version


VALID_CONFIG = {
    "schema_version": "1.0",
    "backends": {
        "kilo": {
            "executable": "kilo.exe",
            "args": ["run", "--auto"],
            "discovery": {
                "method": "vscode_extension",
                "extension_glob": "kilocode.kilo-code-*",
                "binary_name": "kilo.exe",
                "path_fallback": True,
            },
        },
        "opencode": {
            "executable": "opencode",
            "args": ["run"],
            "discovery": {"method": "path_only"},
        },
    },
    "role_assignments": {"BUILDER": "opencode", "MANAGER": "kilo"},
}

VALID_CONFIG_WITH_MODELS = {
    "schema_version": "1.1",
    "backends": {
        "kilo": {
            "executable": "kilo.exe",
            "args": ["run", "--auto"],
            "discovery": {
                "method": "vscode_extension",
                "extension_glob": "kilocode.kilo-code-*",
                "binary_name": "kilo.exe",
                "path_fallback": True,
            },
        },
        "opencode": {
            "executable": "opencode",
            "args": ["run"],
            "discovery": {"method": "path_only"},
        },
    },
    "role_assignments": {"BUILDER": "opencode", "MANAGER": "kilo"},
    "role_models": {
        "BUILDER": "opencode-go/deepseek-v4-flash",
        "MANAGER": "opencode-go/deepseek-v4-flash",
    },
}


def _create_test_config(tmp_path: Path, config: dict) -> Path:
    """Create a test config file in tmp_path/.agent/config/agents.json."""
    agent_dir = tmp_path / ".agent"
    config_dir = agent_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "agents.json"
    config_file.write_text(json.dumps(config))
    return tmp_path


class TestLoadAgentsConfig:
    """Test configuration loading and validation."""

    def test_load_valid_config(self, tmp_path):
        """Test loading a valid configuration."""
        project_root = _create_test_config(tmp_path, VALID_CONFIG)

        config = load_agents_config(project_root)
        assert config["schema_version"] == "1.0"
        assert "kilo" in config["backends"]
        assert "opencode" in config["backends"]

    def test_load_missing_file(self, tmp_path):
        """Test error when config file is missing."""
        with pytest.raises(AgentsConfigError, match="not found"):
            load_agents_config(tmp_path)

    def test_load_invalid_json(self, tmp_path):
        """Test error when JSON is invalid."""
        project_root = _create_test_config(tmp_path, {})
        config_file = project_root / ".agent" / "config" / "agents.json"
        config_file.write_text("not valid json")

        with pytest.raises(AgentsConfigError, match="Invalid JSON"):
            load_agents_config(project_root)

    def test_validate_missing_schema_version(self, tmp_path):
        """Test validation fails without schema_version."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        del bad_config["schema_version"]
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="schema_version"):
            load_agents_config(project_root)

    def test_validate_missing_backends(self, tmp_path):
        """Test validation fails without backends."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        del bad_config["backends"]
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="backends"):
            load_agents_config(project_root)

    def test_validate_empty_backends(self, tmp_path):
        """Test validation fails with empty backends."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["backends"] = {}
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="cannot be empty"):
            load_agents_config(project_root)

    def test_validate_missing_role_assignments(self, tmp_path):
        """Test validation fails without role_assignments."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        del bad_config["role_assignments"]
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="role_assignments"):
            load_agents_config(project_root)

    def test_validate_unknown_role(self, tmp_path):
        """Test validation fails with unknown role."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["role_assignments"] = {"UNKNOWN_ROLE": "kilo"}
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="Unknown role"):
            load_agents_config(project_root)

    def test_validate_role_references_unknown_backend(self, tmp_path):
        """Test validation fails when role references unknown backend."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["role_assignments"] = {"BUILDER": "unknown_backend"}
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="unknown backend"):
            load_agents_config(project_root)

    def test_validate_backend_missing_required_key(self, tmp_path):
        """Test validation fails when backend missing required key."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["backends"]["kilo"] = {
            "executable": "kilo.exe"
        }  # missing args and discovery
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="missing required key"):
            load_agents_config(project_root)

    def test_validate_backend_args_not_list(self, tmp_path):
        """Test validation fails when args is not a list."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["backends"]["kilo"]["args"] = "run --auto"  # should be list
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match=r"args.*must be a list"):
            load_agents_config(project_root)

    def test_validate_unknown_discovery_method(self, tmp_path):
        """Test validation fails with unknown discovery method."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["backends"]["kilo"]["discovery"]["method"] = "unknown_method"
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="unknown discovery method"):
            load_agents_config(project_root)


class TestGetBackendForRole:
    """Test role to backend lookup."""

    # WOT-2026-026j: get_backend_for_role ahora lee role_mapping (canonico), no
    # role_assignments (legacy basura no-referenciada). El legacy MAYUS se
    # normaliza por transicion. Estos tests se migraron del contrato viejo.
    @patch("agents_config.load_agents_config")
    def test_get_builder_backend(self, mock_load):
        """builder (o BUILDER legacy) resuelve por role_mapping."""
        mock_load.return_value = _config_with_role_mapping(
            {"builder": {"backend": "claude"}}
        )
        assert get_backend_for_role("builder") == "claude"
        assert get_backend_for_role("BUILDER") == "claude"  # legacy normalizado

    @patch("agents_config.load_agents_config")
    def test_get_manager_backend(self, mock_load):
        """manager (o MANAGER legacy) resuelve por role_mapping."""
        mock_load.return_value = _config_with_role_mapping(
            {"manager": {"backend": "nan"}}
        )
        assert get_backend_for_role("manager") == "nan"
        assert get_backend_for_role("MANAGER") == "nan"

    @patch("agents_config.load_agents_config")
    def test_get_unassigned_role(self, mock_load):
        """SUPERVISOR es actor_runtime: get_backend_for_role lo RECHAZA (D4)."""
        mock_load.return_value = _config_with_role_mapping(
            {"manager": {"backend": "claude"}}
        )
        with pytest.raises(AgentsConfigError, match="actor_runtime"):
            get_backend_for_role("SUPERVISOR")


class TestGetBackendConfig:
    """Test backend configuration retrieval."""

    @patch("agents_config.load_agents_config")
    def test_get_kilo_config(self, mock_load):
        """Test getting kilo backend config."""
        mock_load.return_value = VALID_CONFIG
        config = get_backend_config("kilo")
        assert config["executable"] == "kilo.exe"
        assert config["args"] == ["run", "--auto"]

    @patch("agents_config.load_agents_config")
    def test_get_opencode_config(self, mock_load):
        """Test getting opencode backend config."""
        mock_load.return_value = VALID_CONFIG
        config = get_backend_config("opencode")
        assert config["executable"] == "opencode"
        assert config["args"] == ["run"]

    @patch("agents_config.load_agents_config")
    def test_get_unknown_backend(self, mock_load):
        """Test error when backend is unknown."""
        mock_load.return_value = VALID_CONFIG
        with pytest.raises(AgentsConfigError, match="Unknown backend"):
            get_backend_config("unknown")


class TestResolveExecutable:
    """Test executable resolution."""

    @patch("agents_config.load_agents_config")
    def test_resolve_kilo_executable(self, mock_load):
        """Test resolving kilo executable."""
        mock_load.return_value = VALID_CONFIG
        exe = resolve_executable("kilo")
        assert exe == "kilo.exe"

    @patch("agents_config.load_agents_config")
    def test_resolve_opencode_executable(self, mock_load):
        """Test resolving opencode executable."""
        mock_load.return_value = VALID_CONFIG
        exe = resolve_executable("opencode")
        assert exe == "opencode"


class TestGetBackendArgs:
    """Test backend arguments retrieval."""

    @patch("agents_config.load_agents_config")
    def test_get_kilo_args(self, mock_load):
        """Test getting kilo args."""
        mock_load.return_value = VALID_CONFIG
        args = get_backend_args("kilo")
        assert args == ["run", "--auto"]

    @patch("agents_config.load_agents_config")
    def test_get_opencode_args(self, mock_load):
        """Test getting opencode args."""
        mock_load.return_value = VALID_CONFIG
        args = get_backend_args("opencode")
        assert args == ["run"]


class TestGetDiscoveryMethod:
    """Test discovery method retrieval."""

    @patch("agents_config.load_agents_config")
    def test_get_vscode_extension_discovery(self, mock_load):
        """Test getting vscode_extension discovery method."""
        mock_load.return_value = VALID_CONFIG
        method = get_discovery_method("kilo")
        assert method == "vscode_extension"

    @patch("agents_config.load_agents_config")
    def test_get_path_only_discovery(self, mock_load):
        """Test getting path_only discovery method."""
        mock_load.return_value = VALID_CONFIG
        method = get_discovery_method("opencode")
        assert method == "path_only"


class TestGetModelForRole:
    """Test model override retrieval from role_models."""

    # WOT-2026-026j: get_model_for_role ahora lee role_mapping[rol]['model'].
    @patch("agents_config.load_agents_config")
    def test_get_model_with_override(self, mock_load):
        """El modelo del rol viene de role_mapping['manager']['model']."""
        mock_load.return_value = _config_with_role_mapping(
            {"manager": {"backend": "claude", "model": "claude-x"}}
        )
        assert get_model_for_role("MANAGER") == "claude-x"

    @patch("agents_config.load_agents_config")
    def test_get_builder_model_with_override(self, mock_load):
        """El modelo de builder viene de role_mapping['builder']['model']."""
        mock_load.return_value = _config_with_role_mapping(
            {"builder": {"backend": "claude", "model": "builder-m"}}
        )
        assert get_model_for_role("BUILDER") == "builder-m"

    @patch("agents_config.load_agents_config")
    def test_get_model_without_override(self, mock_load):
        """Test getting model returns None when role_models is absent."""
        mock_load.return_value = VALID_CONFIG  # No role_models
        model = get_model_for_role("MANAGER")
        assert model is None

    @patch("agents_config.load_agents_config")
    def test_get_model_partial_override(self, mock_load):
        """Test getting model returns None for role without override."""
        config_partial = copy.deepcopy(VALID_CONFIG_WITH_MODELS)
        config_partial["role_models"] = {"BUILDER": "opencode-go/deepseek-v4-flash"}
        # MANAGER not in role_models
        mock_load.return_value = config_partial
        model = get_model_for_role("MANAGER")
        assert model is None

    @patch("agents_config.load_agents_config")
    def test_get_model_actor_runtime_rechazado(self, mock_load):
        """D4: pedir el modelo de un actor_runtime (SUPERVISOR) -> raise claro."""
        mock_load.return_value = _config_with_role_mapping(
            {"manager": {"backend": "claude"}}
        )
        with pytest.raises(AgentsConfigError, match="actor_runtime"):
            get_model_for_role("SUPERVISOR")

    @patch("agents_config.load_agents_config")
    def test_get_model_role_no_en_mapping_es_none(self, mock_load):
        """Un rol sin entrada en role_mapping -> None (usa default del backend)."""
        mock_load.return_value = _config_with_role_mapping(
            {"manager": {"backend": "claude"}}
        )
        assert get_model_for_role("auditor") is None

    def test_validate_role_models_unknown_role(self, tmp_path):
        """Test validation fails when role_models has unknown role."""
        bad_config = copy.deepcopy(VALID_CONFIG_WITH_MODELS)
        bad_config["role_models"]["UNKNOWN_ROLE"] = "some-model"
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="Unknown role"):
            load_agents_config(project_root)

    def test_validate_role_models_not_object(self, tmp_path):
        """Test validation fails when role_models is not an object."""
        bad_config = copy.deepcopy(VALID_CONFIG_WITH_MODELS)
        bad_config["role_models"] = "invalid"
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match=r"role_models.*must be an object"):
            load_agents_config(project_root)


class TestMigrationFramework:
    """Tests for the config migration framework (WP-2026-085)."""

    def test_migrate_idempotent(self, tmp_path):
        """
        Test #1: ejecutar migrate dos veces seguidas → segunda es no-op.

        Before: Config en schema 1.0 sin _migrations.
        During: Primera migración aplica (1.0→1.1→1.2), segunda encuentra _migrations poblado.
        After: Segunda invocación retorna applied=[], skipped=[...], backups=[].
        """
        cfg = tmp_path / "agents.json"
        cfg.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "backends": {
                        "opencode": {
                            "executable": "opencode",
                            "args": ["run"],
                            "discovery": {"method": "path_only"},
                        }
                    },
                    "role_assignments": {"BUILDER": "opencode"},
                }
            )
        )
        report1 = migrate_agents_config(cfg)
        report2 = migrate_agents_config(cfg)
        assert report1.applied == ALL_MIGRATION_IDS
        assert report2.applied == []
        assert report2.skipped == ALL_MIGRATION_IDS
        assert report2.backups == []

    def test_migrate_creates_timestamped_backup(self, tmp_path):
        """
        Test #2: pre-migracion existe, post-migracion existe agents.json.bak.<ts>.

        Before: Config en schema 1.0 sin backup.
        During: migrate_agents_config crea backup antes de cada migracion (dos migraciones).
        After: backups existen.
        """
        cfg = tmp_path / "agents.json"
        cfg.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "backends": {
                        "opencode": {
                            "executable": "opencode",
                            "args": ["run"],
                            "discovery": {"method": "path_only"},
                        }
                    },
                    "role_assignments": {"BUILDER": "opencode"},
                }
            )
        )
        report = migrate_agents_config(cfg)
        # un backup por migracion aplicada, derivado del registro (024t)
        assert len(report.backups) == len(ALL_MIGRATION_IDS)
        assert all(b.exists() for b in report.backups)

    def test_migrate_updates_migrations_list(self, tmp_path):
        """
        Test #3: tras aplicar, _migrations contiene los ids de las migraciones.

        Before: Config sin _migrations field.
        During: migrate_agents_config aplica migraciones y actualiza _migrations.
        After: agents.json tiene _migrations: ["1.0_to_1.1", "1.1_to_1.2"] y schema_version: "1.2".
        """
        cfg = tmp_path / "agents.json"
        cfg.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "backends": {
                        "opencode": {
                            "executable": "opencode",
                            "args": ["run"],
                            "discovery": {"method": "path_only"},
                        }
                    },
                    "role_assignments": {"BUILDER": "opencode"},
                }
            )
        )
        migrate_agents_config(cfg)
        result = json.loads(cfg.read_text())
        assert result["_migrations"] == ALL_MIGRATION_IDS
        assert result["schema_version"] == LATEST_SCHEMA

    def test_legacy_config_without_migrations_field(self, tmp_path):
        """
        Test #4: config ya en la ULTIMA version del registro pero sin _migrations.

        Before: Config en LATEST_SCHEMA (derivada del registro, 024t) sin
                _migrations field.
        During: migrate_agents_config detecta legacy y hace backfill retroactivo.
        After: _migrations poblado con TODOS los ids del registro sin
               re-ejecutar ningun handler.
        """
        cfg = tmp_path / "agents.json"
        # Config ya en la ultima version pero sin _migrations
        cfg.write_text(
            json.dumps(
                {
                    "schema_version": LATEST_SCHEMA,
                    "backends": {
                        "opencode": {
                            "executable": "opencode",
                            "args": ["run"],
                            "discovery": {"method": "path_only"},
                        }
                    },
                    "role_assignments": {"BUILDER": "opencode"},
                    "role_models": {"BUILDER": "x"},
                }
            )
        )
        report = migrate_agents_config(cfg)
        result = json.loads(cfg.read_text())
        assert result["_migrations"] == ALL_MIGRATION_IDS
        assert result["role_models"]["BUILDER"] == "x"  # no overwrite
        assert report.applied == []  # no handler ejecutado
        assert set(ALL_MIGRATION_IDS).issubset(set(report.skipped))

    def test_dry_run_no_writes(self, tmp_path):
        """
        Test #5: --dry-run no toca disco (mtime invariante).

        Before: Config en schema 1.0, mtime registrado.
        During: migrate_agents_config(dry_run=True) simula sin escribir.
        After: mtime invariante, no backup creado, report muestra lo que pasaría.
        """
        cfg = tmp_path / "agents.json"
        cfg.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "backends": {
                        "opencode": {
                            "executable": "opencode",
                            "args": ["run"],
                            "discovery": {"method": "path_only"},
                        }
                    },
                    "role_assignments": {"BUILDER": "opencode"},
                }
            )
        )
        mtime_before = cfg.stat().st_mtime
        report = migrate_agents_config(cfg, dry_run=True)
        mtime_after = cfg.stat().st_mtime
        assert mtime_before == mtime_after
        # report si muestra lo que pasaria (derivado del registro, 024t)
        assert report.applied == ALL_MIGRATION_IDS
        assert report.backups == []

    def test_migration_handler_pure(self):
        """
        Test #6: _migrate_1_0_to_1_1 no muta el dict input.

        Before: dict config original.
        During: handler crea nuevo dict, no muta input.
        After: input inalterado, output es dict diferente con schema 1.1.
        """
        config = {
            "schema_version": "1.0",
            "backends": {
                "opencode": {
                    "executable": "opencode",
                    "args": ["run"],
                    "discovery": {"method": "path_only"},
                }
            },
            "role_assignments": {"BUILDER": "opencode"},
        }
        config_snapshot = dict(config)
        result = _migrate_1_0_to_1_1(config)
        assert config == config_snapshot  # input no mutado
        assert result is not config
        assert result["schema_version"] == "1.1"

    def test_migrate_from_1_0(self, tmp_path):
        """
        Test #7: migración full 1.0 → LATEST backfill strictness_profile, profiles y role_mapping.

        WOT-2026-026j D3: la cadena ya NO inyecta role_models legacy (ese era el
        defecto 024t). role_models legacy queda como basura no-referenciada; el
        contrato canonico vive en role_mapping (sembrado por 1.3->1.4).

        Before: Config legacy schema 1.0 sin role_models, strictness_profile ni profiles.
        During: migrate_agents_config aplica handlers que backfills todo salvo el legacy.
        After: schema_version LATEST, strictness_profile=standard, profiles con
               minimal/standard/strict, role_mapping canonico, _migrations poblado.
        """
        cfg = tmp_path / "agents.json"
        cfg.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "backends": {
                        "opencode": {
                            "executable": "opencode",
                            "args": ["run"],
                            "discovery": {"method": "path_only"},
                        }
                    },
                    "role_assignments": {"BUILDER": "opencode"},
                }
            )
        )
        migrate_agents_config(cfg)
        result = json.loads(cfg.read_text())
        assert result["schema_version"] == LATEST_SCHEMA
        assert result["strictness_profile"] == "standard"
        assert "profiles" in result
        assert "minimal" in result["profiles"]
        assert "standard" in result["profiles"]
        assert "strict" in result["profiles"]
        # 1.2 -> 1.3 (WOT-2026-019o): claves ensemble_* backfilled vacias
        assert result["ensemble_profiles"] == {}
        assert result["ensemble_pipelines"] == {}
        assert result["ensemble_private_roots"] == []
        # 1.3 -> 1.4 (WOT-2026-026j): role_mapping canonico sembrado
        assert "role_mapping" in result


class TestSkillAllowlists:
    """Tests for WP-2026-128: skill allowlists validation."""

    def test_load_config_with_skill_allowlists(self, tmp_path):
        """Test loading config with skill_allowlists defined."""
        config_with_allowlists = copy.deepcopy(VALID_CONFIG)
        config_with_allowlists["skill_allowlists"] = {
            "BUILDER": ["/impl", "/tdd"],
            "MANAGER": ["/review"],
        }
        project_root = _create_test_config(tmp_path, config_with_allowlists)
        config = load_agents_config(project_root)
        assert "skill_allowlists" in config
        assert config["skill_allowlists"]["BUILDER"] == ["/impl", "/tdd"]

    def test_validate_skill_allowlists_unknown_role(self, tmp_path):
        """Test validation fails when skill_allowlists has unknown role."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["skill_allowlists"] = {"UNKNOWN_ROLE": ["/impl"]}
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="Unknown role"):
            load_agents_config(project_root)

    def test_validate_skill_allowlists_not_list(self, tmp_path):
        """Test validation fails when allowlist is not a list."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["skill_allowlists"] = {"BUILDER": "not_a_list"}
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="must be a list"):
            load_agents_config(project_root)

    def test_validate_skill_allowlists_not_object(self, tmp_path):
        """Test validation fails when skill_allowlists is not an object."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["skill_allowlists"] = "invalid"
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="must be an object"):
            load_agents_config(project_root)

    def test_load_config_without_skill_allowlists_retrocompatible(self, tmp_path):
        """Test config without skill_allowlists loads fine (retrocompatible)."""
        project_root = _create_test_config(tmp_path, VALID_CONFIG)
        config = load_agents_config(project_root)
        assert "skill_allowlists" not in config  # Not required


class TestStrictnessProfiles:
    """Tests for WP-2026-154: strictness profiles and schema 1.2."""

    def test_migrate_1_1_to_1_2_handler(self):
        """Test _migrate_1_1_to_1_2 backfills strictness_profile and profiles."""
        from agents_config import _migrate_1_1_to_1_2

        config = {
            "schema_version": "1.1",
            "backends": {
                "opencode": {
                    "executable": "opencode",
                    "args": ["run"],
                    "discovery": {"method": "path_only"},
                }
            },
            "role_assignments": {"BUILDER": "opencode"},
        }
        result = _migrate_1_1_to_1_2(config)
        assert result["schema_version"] == "1.2"
        assert result["strictness_profile"] == "standard"
        assert "profiles" in result
        assert "minimal" in result["profiles"]
        assert "standard" in result["profiles"]
        assert "strict" in result["profiles"]
        assert config["schema_version"] == "1.1"  # input not mutated

    def test_load_config_with_strictness_profile(self, tmp_path):
        """Test loading config with strictness_profile defined."""
        config_with_profile = copy.deepcopy(VALID_CONFIG)
        config_with_profile["schema_version"] = "1.2"
        config_with_profile["strictness_profile"] = "strict"
        config_with_profile["profiles"] = {
            "minimal": {"description": "minimal"},
            "standard": {"description": "standard"},
            "strict": {"description": "strict"},
        }
        project_root = _create_test_config(tmp_path, config_with_profile)
        config = load_agents_config(project_root)
        assert config["strictness_profile"] == "strict"

    def test_validate_strictness_profile_invalid(self, tmp_path):
        """Test validation fails when strictness_profile is invalid."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["schema_version"] = "1.2"
        bad_config["strictness_profile"] = "invalid_profile"
        bad_config["profiles"] = {
            "minimal": {},
            "standard": {},
            "strict": {},
        }
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="Invalid 'strictness_profile'"):
            load_agents_config(project_root)

    def test_validate_profiles_missing_required(self, tmp_path):
        """Test validation fails when profiles missing required profile."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["schema_version"] = "1.2"
        bad_config["strictness_profile"] = "standard"
        bad_config["profiles"] = {
            "minimal": {},
            # missing standard and strict
        }
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="Missing required profile"):
            load_agents_config(project_root)

    def test_validate_profiles_not_object(self, tmp_path):
        """Test validation fails when profiles is not an object."""
        bad_config = copy.deepcopy(VALID_CONFIG)
        bad_config["schema_version"] = "1.2"
        bad_config["strictness_profile"] = "standard"
        bad_config["profiles"] = "invalid"
        project_root = _create_test_config(tmp_path, bad_config)

        with pytest.raises(AgentsConfigError, match="Invalid 'profiles'"):
            load_agents_config(project_root)

    def test_get_strictness_profile_default(self, tmp_path, monkeypatch):
        """Test get_strictness_profile returns 'standard' as default."""
        from agents_config import get_strictness_profile

        config = {
            "schema_version": "1.2",
            "backends": {
                "opencode": {
                    "executable": "opencode",
                    "args": ["run"],
                    "discovery": {"method": "path_only"},
                }
            },
            "role_assignments": {"BUILDER": "opencode"},
        }
        # No strictness_profile defined → default to standard
        assert get_strictness_profile(config) == "standard"

    def test_get_strictness_profile_explicit(self, tmp_path):
        """Test get_strictness_profile returns configured value."""
        from agents_config import get_strictness_profile

        config = {
            "schema_version": "1.2",
            "backends": {
                "opencode": {
                    "executable": "opencode",
                    "args": ["run"],
                    "discovery": {"method": "path_only"},
                }
            },
            "role_assignments": {"BUILDER": "opencode"},
            "strictness_profile": "strict",
            "profiles": {
                "minimal": {},
                "standard": {},
                "strict": {},
            },
        }
        assert get_strictness_profile(config) == "strict"

    def test_get_profile_config(self, tmp_path):
        """Test get_profile_config returns profile configuration."""
        from agents_config import get_profile_config

        config = {
            "schema_version": "1.2",
            "backends": {
                "opencode": {
                    "executable": "opencode",
                    "args": ["run"],
                    "discovery": {"method": "path_only"},
                }
            },
            "role_assignments": {"BUILDER": "opencode"},
            "strictness_profile": "minimal",
            "profiles": {
                "minimal": {"write_roots": ["src"], "blocked_command_patterns": []},
                "standard": {"write_roots": [], "blocked_command_patterns": []},
                "strict": {"write_roots": [], "blocked_command_patterns": ["rm -rf"]},
            },
        }
        # Explicit profile name
        minimal_config = get_profile_config("minimal", config)
        assert minimal_config["write_roots"] == ["src"]

        # Default to configured profile
        default_config = get_profile_config(config=config)
        assert default_config == minimal_config

    def test_get_profile_config_unknown_profile(self, tmp_path):
        """Test get_profile_config raises on unknown profile."""
        from agents_config import get_profile_config

        config = {
            "schema_version": "1.2",
            "backends": {
                "opencode": {
                    "executable": "opencode",
                    "args": ["run"],
                    "discovery": {"method": "path_only"},
                }
            },
            "role_assignments": {"BUILDER": "opencode"},
            "profiles": {
                "minimal": {},
                "standard": {},
                "strict": {},
            },
        }
        with pytest.raises(AgentsConfigError, match="Unknown strictness profile"):
            get_profile_config("nonexistent", config)


# --------------------------------------------------------------------------- #
# WOT-2026-026j: rediseno de taxonomia de roles. role_mapping canonico (roles en
# MINUSCULA), cascada local->versionado->default, migracion que corta el legacy
# en origen, SUPERVISOR como actor_runtime aparte, barrera = SCHEMA FAIL-CLOSED.
# Cada test fija una barrera del DoD; el nombre dice que mutation cubre.
# --------------------------------------------------------------------------- #


def _config_with_role_mapping(role_mapping: dict, extra: dict | None = None) -> dict:
    """Config valido minimo que declara role_mapping (schema 1.4)."""
    cfg = {
        "schema_version": "1.4",
        "backends": {
            "claude": {
                "executable": "claude",
                "args": ["run"],
                "discovery": {"method": "path_only"},
            },
            "codex": {
                "executable": "codex.cmd",
                "args": ["exec"],
                "discovery": {"method": "path_only"},
            },
            "nan": {
                "executable": "nan",
                "args": ["run"],
                "discovery": {"method": "path_only"},
            },
        },
        "role_assignments": {"BUILDER": "claude"},
        "role_mapping": role_mapping,
    }
    if extra:
        cfg.update(extra)
    return cfg


class TestRoleMappingSchemaFailClosed:
    """D1/D4: el schema RECHAZA claves de role_mapping fuera del enum canonico."""

    def test_canonical_roles_accepted(self, tmp_path):
        """H4: los 5 roles canonicos validan Y resuelven al backend esperado.

        Antes era floor assertion (`assert path.exists()`, satisfecha aunque el
        role_mapping se ignorara). Ahora aserta las 5 claves canonicas efectivas
        y que 'manager' resuelve a su backend -- muerde si la cascada se rompe.
        """
        cfg = _config_with_role_mapping(
            {
                "orchestrator": {"backend": "claude"},
                "manager": {"backend": "codex"},
                "builder": {"backend": "claude"},
                "auditor": {"backend": "codex"},
                "challenger": {"backend": "nan"},
            }
        )
        _create_test_config(tmp_path, cfg)
        config = load_agents_config(tmp_path)
        assert set(config["role_mapping"].keys()) == {
            "orchestrator",
            "manager",
            "builder",
            "auditor",
            "challenger",
        }
        assert get_backend_for_role("manager", config) == "codex"

    def test_role_mapping_rejects_supervisor(self, tmp_path):
        """M-schema: SUPERVISOR dentro de role_mapping -> FALLA (es actor_runtime)."""
        cfg = _config_with_role_mapping(
            {"manager": {"backend": "claude"}, "SUPERVISOR": {"backend": "claude"}}
        )
        _create_test_config(tmp_path, cfg)
        with pytest.raises(AgentsConfigError, match="role_mapping"):
            load_agents_config(tmp_path)

    def test_role_mapping_rejects_unknown_key(self, tmp_path):
        """M-schema: una clave arbitraria fuera del enum -> FALLA fail-closed."""
        cfg = _config_with_role_mapping(
            {"manager": {"backend": "claude"}, "foo": {"backend": "claude"}}
        )
        _create_test_config(tmp_path, cfg)
        with pytest.raises(AgentsConfigError, match="role_mapping"):
            load_agents_config(tmp_path)

    def test_role_mapping_rejects_uppercase_legacy(self, tmp_path):
        """M-schema: los roles MAYUS legacy NO valen en role_mapping (solo minuscula)."""
        cfg = _config_with_role_mapping({"MANAGER": {"backend": "claude"}})
        _create_test_config(tmp_path, cfg)
        with pytest.raises(AgentsConfigError, match="role_mapping"):
            load_agents_config(tmp_path)


class TestRoleMappingCascade:
    """D2: get_*_for_role resuelven local -> versionado -> default REAL."""

    def test_versionado_gana_sin_local(self, tmp_path):
        """Nivel 2: sin agents.local.json, se lee el role_mapping versionado."""
        cfg = _config_with_role_mapping(
            {"manager": {"backend": "claude", "model": "claude-x"}}
        )
        _create_test_config(tmp_path, cfg)
        config = load_agents_config(tmp_path)
        assert get_model_for_role("manager", config) == "claude-x"
        assert get_backend_for_role("manager", config) == "claude"

    def test_local_gana_sobre_versionado(self, tmp_path):
        """M-cascada-local: agents.local.json sobrescribe el modelo/backend versionado."""
        cfg = _config_with_role_mapping(
            {"manager": {"backend": "claude", "model": "versionado-Y"}}
        )
        _create_test_config(tmp_path, cfg)
        # agents.local.json junto al agents.json versionado
        local = tmp_path / ".agent" / "config" / "agents.local.json"
        local.write_text(
            json.dumps(
                {"role_mapping": {"manager": {"backend": "nan", "model": "local-X"}}}
            ),
            encoding="utf-8",
        )
        config = load_agents_config(tmp_path)
        assert get_model_for_role("manager", config) == "local-X"
        assert get_backend_for_role("manager", config) == "nan"

    def test_model_default_es_none_sin_override(self, tmp_path):
        """Nivel 3 modelo: rol sin entrada -> None (backend usa su default)."""
        cfg = _config_with_role_mapping({"manager": {"backend": "claude"}})
        _create_test_config(tmp_path, cfg)
        config = load_agents_config(tmp_path)
        assert get_model_for_role("auditor", config) is None

    def test_backend_default_devuelve_el_backend_centinela(self, tmp_path):
        """M-cascada-default: rol ausente CON backend 'default' -> 'default'.

        Con dientes: backends declara el centinela 'default'; auditor no esta en
        role_mapping -> get_backend_for_role DEBE devolver 'default' (nivel 3).
        Si se desactiva el fallback de nivel 3, lanza -> el test cae.
        """
        cfg = _config_with_role_mapping({"manager": {"backend": "claude"}})
        cfg["backends"]["default"] = {
            "executable": "default-be",
            "args": [],
            "discovery": {"method": "path_only"},
        }
        _create_test_config(tmp_path, cfg)
        config = load_agents_config(tmp_path)
        assert get_backend_for_role("auditor", config) == "default"

    def test_backend_sin_default_lanza_claro(self, tmp_path):
        """Nivel 3 sin default: no inventar backend -> AgentsConfigError claro."""
        cfg = _config_with_role_mapping({"manager": {"backend": "claude"}})
        _create_test_config(tmp_path, cfg)
        config = load_agents_config(tmp_path)
        with pytest.raises(AgentsConfigError, match="auditor"):
            get_backend_for_role("auditor", config)


class TestRoleRejectionH2H3:
    """H2/H3: get_*_for_role rechaza roles no-canonicos y normaliza case."""

    def test_typo_role_rechazado_no_degrada_a_default(self, tmp_path):
        """H2 [BLOQUEANTE]: un typo ('BUILDERR') NO cae al centinela 'default'.

        Con dientes: backends declara 'default'; sin la barrera H2 el typo
        degrada silencioso a 'default'. La barrera exige raise que cite el rol.
        """
        cfg = _config_with_role_mapping({"manager": {"backend": "claude"}})
        cfg["backends"]["default"] = {
            "executable": "default-be",
            "args": [],
            "discovery": {"method": "path_only"},
        }
        _create_test_config(tmp_path, cfg)
        config = load_agents_config(tmp_path)
        with pytest.raises(AgentsConfigError, match="BUILDERR"):
            get_backend_for_role("BUILDERR", config)

    def test_typo_role_rechazado_en_get_model(self, tmp_path):
        """H2: get_model_for_role tambien rechaza el rol invalido (no None mudo)."""
        cfg = _config_with_role_mapping({"manager": {"backend": "claude"}})
        _create_test_config(tmp_path, cfg)
        config = load_agents_config(tmp_path)
        with pytest.raises(AgentsConfigError, match="notarole"):
            get_model_for_role("notarole", config)

    def test_actor_runtime_case_insensitive(self, tmp_path):
        """H3: 'supervisor' minuscula tambien se rechaza como actor_runtime."""
        cfg = _config_with_role_mapping({"manager": {"backend": "claude"}})
        _create_test_config(tmp_path, cfg)
        config = load_agents_config(tmp_path)
        with pytest.raises(AgentsConfigError, match="actor_runtime"):
            get_backend_for_role("supervisor", config)
        with pytest.raises(AgentsConfigError, match="actor_runtime"):
            get_model_for_role("supervisor", config)

    def test_legacy_uppercase_manager_sigue_resolviendo(self, tmp_path):
        """H2 no rompe la transicion: 'MANAGER' legacy sigue normalizando a canonico."""
        cfg = _config_with_role_mapping(
            {"manager": {"backend": "codex", "model": "m-x"}}
        )
        _create_test_config(tmp_path, cfg)
        config = load_agents_config(tmp_path)
        assert get_backend_for_role("MANAGER", config) == "codex"
        assert get_model_for_role("MANAGER", config) == "m-x"


class TestMigrationCutsLegacyD3:
    """D3: la migracion corta el legacy en ORIGEN y siembra role_mapping."""

    def test_1_0_to_1_1_no_inyecta_legacy_model(self):
        """M-migracion (unidad): _migrate_1_0_to_1_1 NO siembra role_models legacy.

        Con dientes: restaurar la inyeccion de 'opencode-go/deepseek-v4-flash'
        en el handler hace caer este assert.
        """
        result = _migrate_1_0_to_1_1({"schema_version": "1.0"})
        assert result["schema_version"] == "1.1"
        assert "role_models" not in result

    def test_1_3_to_1_4_siembra_role_mapping_canonico(self):
        """D3: _migrate_1_3_to_1_4 siembra role_mapping con claves canonicas."""
        result = _migrate_1_3_to_1_4({"schema_version": "1.3"})
        assert result["schema_version"] == "1.4"
        assert "role_mapping" in result
        assert set(result["role_mapping"].keys()) <= {
            "orchestrator",
            "manager",
            "builder",
            "auditor",
            "challenger",
        }

    def test_invariante_024t_install_fresco_sin_legacy(self, tmp_path):
        """INVARIANTE 024t: install fresco 1.0->1.4 -> 0 apariciones del legacy.

        Criterio INVARIANTE (no 'hoy N hits'): el string legacy no debe aparecer
        en NINGUNA parte del config migrado, ni en role_mapping ni en role_models.
        Con dientes: si el handler 1.0->1.1 vuelve a inyectarlo, el conteo sube.
        """
        cfg = tmp_path / "agents.json"
        cfg.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "backends": {
                        "opencode": {
                            "executable": "opencode",
                            "args": ["run"],
                            "discovery": {"method": "path_only"},
                        }
                    },
                    "role_assignments": {"BUILDER": "opencode"},
                }
            )
        )
        migrate_agents_config(cfg)
        migrated_text = cfg.read_text()
        assert migrated_text.count("opencode-go/deepseek-v4-flash") == 0


class TestRealAgentsJsonContract:
    """H1/D4/M-challenger: el agents.json REAL cumple el contrato canonico."""

    @staticmethod
    def _real_config() -> dict:
        real_path = _project_root / ".agent" / "config" / "agents.json"
        return load_agents_config(real_path.parent.parent.parent)

    def test_real_config_declara_role_mapping_manager(self):
        """H1: role_mapping['manager'] existe en el config real (no cae a default)."""
        config = self._real_config()
        assert "role_mapping" in config
        assert "manager" in config["role_mapping"]
        # get_backend_for_role('manager') resuelve al backend real, no al centinela
        assert get_backend_for_role("manager", config) != "default"

    def test_real_config_declara_actor_runtime_supervisor(self):
        """D4: el config real declara actor_runtime con SUPERVISOR."""
        config = self._real_config()
        assert "actor_runtime" in config
        assert "SUPERVISOR" in config["actor_runtime"]

    def test_challenger_referencia_ensemble_profiles_no_copia_inline(self):
        """M-challenger: challenger REFERENCIA ensemble_profiles, no copia los 4 nan.

        Con dientes: si alguien inserta una copia inline de un perfil nan
        (api_base_url / api_key_env / backend_key) dentro de role_mapping,
        el assert cae. El dueno de los perfiles sigue siendo ensemble_profiles.
        """
        config = self._real_config()
        challenger = config["role_mapping"]["challenger"]
        inline_profile_markers = {"api_base_url", "api_key_env", "backend_key"}
        assert not (inline_profile_markers & set(challenger.keys())), (
            "challenger no debe copiar inline los perfiles nan; debe REFERENCIAR "
            "ensemble_profiles"
        )
        # La referencia apunta a ensemble_profiles reales
        ref = challenger.get("ensemble_profiles_ref", [])
        assert ref, "challenger debe declarar ensemble_profiles_ref"
        for profile_name in ref:
            assert profile_name in config["ensemble_profiles"], (
                f"challenger referencia perfil inexistente '{profile_name}'"
            )
