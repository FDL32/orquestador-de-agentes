"""Tests for agent configuration loader."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# Add the agent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".agent"))

from agents_config import (
    AgentsConfigError,
    _migrate_1_0_to_1_1,
    get_backend_args,
    get_backend_config,
    get_backend_for_role,
    get_discovery_method,
    get_model_for_role,
    load_agents_config,
    migrate_agents_config,
    resolve_executable,
)


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
        "BUILDER": "opencode-go/qwen3.5-plus",
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

    @patch("agents_config.load_agents_config")
    def test_get_builder_backend(self, mock_load):
        """Test getting backend for BUILDER role."""
        mock_load.return_value = VALID_CONFIG
        backend = get_backend_for_role("BUILDER")
        assert backend == "opencode"

    @patch("agents_config.load_agents_config")
    def test_get_manager_backend(self, mock_load):
        """Test getting backend for MANAGER role."""
        mock_load.return_value = VALID_CONFIG
        backend = get_backend_for_role("MANAGER")
        assert backend == "kilo"

    @patch("agents_config.load_agents_config")
    def test_get_unassigned_role(self, mock_load):
        """Test error when role has no backend assigned."""
        mock_load.return_value = VALID_CONFIG
        with pytest.raises(AgentsConfigError, match="No backend assigned"):
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

    @patch("agents_config.load_agents_config")
    def test_get_model_with_override(self, mock_load):
        """Test getting model when role_models is present."""
        mock_load.return_value = VALID_CONFIG_WITH_MODELS
        model = get_model_for_role("MANAGER")
        assert model == "opencode-go/deepseek-v4-flash"

    @patch("agents_config.load_agents_config")
    def test_get_builder_model_with_override(self, mock_load):
        """Test getting BUILDER model when role_models is present."""
        mock_load.return_value = VALID_CONFIG_WITH_MODELS
        model = get_model_for_role("BUILDER")
        assert model == "opencode-go/qwen3.5-plus"

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
        config_partial["role_models"] = {"BUILDER": "opencode-go/qwen3.5-plus"}
        # MANAGER not in role_models
        mock_load.return_value = config_partial
        model = get_model_for_role("MANAGER")
        assert model is None

    @patch("agents_config.load_agents_config")
    def test_get_model_unknown_role(self, mock_load):
        """Test error when role is unknown."""
        mock_load.return_value = VALID_CONFIG
        with pytest.raises(AgentsConfigError, match="Unknown role"):
            get_model_for_role("UNKNOWN_ROLE")

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
        During: Primera migración aplica, segunda encuentra _migrations poblado.
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
        assert report1.applied == ["1.0_to_1.1"]
        assert report2.applied == []
        assert report2.skipped == ["1.0_to_1.1"]
        assert report2.backups == []

    def test_migrate_creates_timestamped_backup(self, tmp_path):
        """
        Test #2: pre-migración existe, post-migración existe agents.json.bak.<ts>.

        Before: Config en schema 1.0 sin backup.
        During: migrate_agents_config crea backup antes de aplicar.
        After: backup existe y contiene el contenido original (schema_version 1.0).
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
        assert len(report.backups) == 1
        assert report.backups[0].exists()
        # backup tiene contenido original
        original = json.loads(report.backups[0].read_text())
        assert original["schema_version"] == "1.0"

    def test_migrate_updates_migrations_list(self, tmp_path):
        """
        Test #3: tras aplicar, _migrations contiene el id de la migración.

        Before: Config sin _migrations field.
        During: migrate_agents_config aplica migración y actualiza _migrations.
        After: agents.json tiene _migrations: ["1.0_to_1.1"] y schema_version: "1.1".
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
        assert result["_migrations"] == ["1.0_to_1.1"]
        assert result["schema_version"] == "1.1"

    def test_legacy_config_without_migrations_field(self, tmp_path):
        """
        Test #4: config con schema_version: "1.1" pero sin _migrations.

        Before: Config ya en 1.1 pero sin _migrations field.
        During: migrate_agents_config detecta legacy y hace backfill retroactivo.
        After: _migrations: ["1.0_to_1.1"] poblado sin re-ejecutar handler.
        """
        cfg = tmp_path / "agents.json"
        # Config ya en 1.1 pero sin _migrations
        cfg.write_text(
            json.dumps(
                {
                    "schema_version": "1.1",
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
        assert result["_migrations"] == ["1.0_to_1.1"]
        assert result["role_models"]["BUILDER"] == "x"  # no overwrite
        assert report.applied == []  # no handler ejecutado
        assert "1.0_to_1.1" in report.skipped

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
        assert report.applied == ["1.0_to_1.1"]  # report sí muestra lo que pasaría
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
        Test #7: migración 1.0 → 1.1 backfill role_models.

        Before: Config legacy schema 1.0 sin role_models.
        During: migrate_agents_config aplica handler que backfills role_models.
        After: schema_version 1.1, role_models con defaults WP-072, _migrations poblado.
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
        assert result["schema_version"] == "1.1"
        assert "role_models" in result
        assert result["role_models"]["BUILDER"] == "opencode-go/qwen3.5-plus"
        assert result["role_models"]["MANAGER"] == "openai/gpt-5.4-mini"


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
