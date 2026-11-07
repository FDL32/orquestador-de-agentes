#!/usr/bin/env python3
"""
Tests para pre_compact_hook.py.

Cubre:
- Memoria vacia
- Archivo ausente
- JSONL corrupto
- Matching por keywords
- Ranking por recencia
- Presencia de additionalContext
"""

import json
import os
import pathlib
import shutil
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from tests.unit.test_session_start_hook import (
    RAYA,
    _destino_with_em_dash_archive,
    _run_settings_hook,
)


# Importar el hook
HOOK_PATH = pathlib.Path(__file__).parent.parent.parent / ".agent" / "hooks"
sys.path.insert(0, str(HOOK_PATH))
import pre_compact_hook as hook  # noqa: E402


class TestLoadObservationsSafe:
    """Tests para load_observations_safe()."""

    def test_file_not_exists(self, tmp_path):
        """Test cuando observations.jsonl no existe."""
        with patch.object(hook, "OBSERVATIONS_FILE", tmp_path / "nonexistent.jsonl"):
            obs = hook.load_observations_safe()
            assert obs == []

    def test_empty_file(self, tmp_path):
        """Test cuando el archivo existe pero esta vacio."""
        obs_file = tmp_path / "observations.jsonl"
        obs_file.write_text("", encoding="utf-8")
        with patch.object(hook, "OBSERVATIONS_FILE", obs_file):
            obs = hook.load_observations_safe()
            assert obs == []

    def test_valid_jsonl(self, tmp_path):
        """Test con archivo JSONL valido."""
        obs_file = tmp_path / "observations.jsonl"
        obs_file.write_text(
            '{"timestamp": "2026-05-24T21:45:59Z", "topic": "test", "signal": "signal1", "source": "builder"}\n'
            '{"timestamp": "2026-05-25T10:00:00Z", "topic": "arch", "signal": "signal2", "source": "manager"}\n',
            encoding="utf-8",
        )
        with patch.object(hook, "OBSERVATIONS_FILE", obs_file):
            obs = hook.load_observations_safe()
            assert len(obs) == 2
            assert obs[0]["topic"] == "test"
            assert obs[1]["topic"] == "arch"

    def test_corrupted_jsonl(self, tmp_path):
        """Test con lineas JSONL corruptas (se saltan)."""
        obs_file = tmp_path / "observations.jsonl"
        obs_file.write_text(
            '{"timestamp": "2026-05-24T21:45:59Z", "topic": "test", "signal": "signal1", "source": "builder"}\n'
            "not valid json\n"
            '{"timestamp": "2026-05-25T10:00:00Z", "topic": "arch", "signal": "signal2", "source": "manager"}\n'
            "another bad line\n",
            encoding="utf-8",
        )
        with patch.object(hook, "OBSERVATIONS_FILE", obs_file):
            obs = hook.load_observations_safe()
            assert len(obs) == 2  # Solo las lineas validas

    def test_io_error(self, tmp_path):
        """Test cuando hay error de I/O al leer (OSError desde built-in open)."""
        obs_file = tmp_path / "obs.jsonl"
        obs_file.touch()  # file exists so the guard passes
        with (
            patch.object(hook, "OBSERVATIONS_FILE", obs_file),
            patch("builtins.open", side_effect=OSError("Permission denied")),
        ):
            obs = hook.load_observations_safe()
        assert obs == []

    def test_explicit_path_overrides_module_default(self, tmp_path):
        obs_file = tmp_path / "explicit.jsonl"
        obs_file.write_text(
            '{"topic": "explicit", "signal": "path", "source": "test"}\n',
            encoding="utf-8",
        )

        obs = hook.load_observations_safe(obs_file)

        assert obs == [{"topic": "explicit", "signal": "path", "source": "test"}]

    def test_permission_error_on_path_exists_returns_empty(self, tmp_path):
        with patch.object(hook.Path, "exists", side_effect=PermissionError("denied")):
            assert hook.load_observations_safe(tmp_path / "observations.jsonl") == []


class TestExtractKeywordsFromWorkPlan:
    """Tests para extract_keywords_from_work_plan()."""

    def test_file_not_exists(self, tmp_path):
        """Test cuando work_plan.md no existe."""
        with patch.object(hook, "WORK_PLAN_FILE", tmp_path / "nonexistent.md"):
            keywords = hook.extract_keywords_from_work_plan()
            assert keywords == []

    def test_extract_keywords_basic(self, tmp_path):
        """Test extraccion basica de keywords."""
        wp_file = tmp_path / "work_plan.md"
        wp_file.write_text(
            "# Work Plan - WP-2026-135\n"
            "## Objetivo\n"
            "Hacer que el hook de pre-compactacion recupere contexto util.\n"
            "## Files Likely Touched\n"
            "- pre_compact_hook.py\n"
            "- test_pre_compact_hook.py\n",
            encoding="utf-8",
        )
        with patch.object(hook, "WORK_PLAN_FILE", wp_file):
            keywords = hook.extract_keywords_from_work_plan()
            # Debe contener palabras significativas (no stop words)
            assert (
                "pre-compactacion" in keywords
                or "pre" in keywords
                or "compactacion" in keywords
            )
            assert "contexto" in keywords
            assert "hook" not in keywords  # es stop word
            assert "test" not in keywords  # es stop word

    def test_io_error(self, tmp_path):
        """Test cuando hay error de lectura."""
        with (
            patch.object(hook, "WORK_PLAN_FILE", tmp_path / "nonexistent.md"),
            patch.object(pathlib.Path, "exists", return_value=True),
            patch.object(pathlib.Path, "read_text", side_effect=OSError("Error")),
        ):
            keywords = hook.extract_keywords_from_work_plan()
            assert keywords == []

    def test_explicit_path_overrides_module_default(self, tmp_path):
        plan_file = tmp_path / "explicit.md"
        plan_file.write_text("# ExplicitRoot\n", encoding="utf-8")

        keywords = hook.extract_keywords_from_work_plan(plan_file)

        assert "explicitroot" in keywords

    def test_permission_error_on_path_exists_returns_empty(self, tmp_path):
        with patch.object(hook.Path, "exists", side_effect=PermissionError("denied")):
            assert hook.extract_keywords_from_work_plan(tmp_path / "work_plan.md") == []


class TestScoreObservation:
    """Tests para score_observation()."""

    def test_empty_obs(self):
        """Test con observacion vacia."""
        score = hook.score_observation({}, ["keyword"])
        assert score == 0

    def test_no_keywords_match(self):
        """Test cuando no hay matching de keywords."""
        obs = {
            "timestamp": "2026-05-24T21:45:59Z",
            "topic": "unrelated",
            "signal": "nothing matches",
            "source": "builder",
        }
        score = hook.score_observation(obs, ["python", "context", "hook"])
        # Solo debe tener score de recencia, no de keywords
        assert score > 0  # recencia da puntos
        # El score de recencia es ~20260524, sin keywords no llega a 20260574
        assert score < 20260574  # sin keywords no suma 50+

    def test_keywords_match(self):
        """Test que keyword matching incrementa el score sobre el baseline de recencia."""
        obs = {
            "timestamp": "2026-05-24T21:45:59Z",
            "topic": "context",
            "signal": "python recovery",
            "source": "builder",
        }
        score_no_kw = hook.score_observation(obs, [])
        score_with_kw = hook.score_observation(obs, ["python", "context", "recovery"])
        # 3 keywords x 50 bonus each - delta must exceed base recency score
        assert score_with_kw >= score_no_kw + 3 * 50

    def test_partial_match(self):
        """Test matching parcial de keywords."""
        obs = {
            "timestamp": "2026-05-24T21:45:59Z",
            "topic": "context",
            "signal": "something else",
            "source": "builder",
        }
        score = hook.score_observation(obs, ["python", "context", "hook"])
        # Debe matchear solo "context"
        assert score >= 50  # al menos una keyword


class TestRankObservations:
    """Tests para rank_observations()."""

    def test_empty_observations(self):
        """Test con lista vacia de observaciones."""
        ranked = hook.rank_observations([], ["keyword"])
        assert ranked == []

    def test_cap_at_max(self):
        """Test que el ranking respeta el MAX_OBSERVATIONS cap."""
        observations = [
            {
                "timestamp": f"2026-05-{24 - i:02d}T10:00:00Z",
                "topic": f"topic{i}",
                "signal": f"signal{i}",
                "source": "builder",
            }
            for i in range(10)
        ]
        ranked = hook.rank_observations(observations, [])
        assert len(ranked) == hook.MAX_OBSERVATIONS

    def test_ranking_by_recency_and_keywords(self):
        """Test que el ranking combina recencia y keywords."""
        observations = [
            # Vieja pero con keywords
            {
                "timestamp": "2026-05-01T10:00:00Z",
                "topic": "context",
                "signal": "python hook",
                "source": "builder",
            },
            # Reciente sin keywords
            {
                "timestamp": "2026-05-25T10:00:00Z",
                "topic": "other",
                "signal": "nothing",
                "source": "builder",
            },
        ]
        ranked = hook.rank_observations(observations, ["python", "context", "hook"])
        # La primera debe estar arriba por keywords aunque sea mas vieja
        assert ranked[0]["topic"] == "context"


class TestFormatMemorySection:
    """Tests para format_memory_section()."""

    def test_empty_observations(self):
        """Test con lista vacia."""
        section = hook.format_memory_section([])
        assert section == ""

    def test_format_single_observation(self):
        """Test formateo de una observacion."""
        observations = [
            {
                "timestamp": "2026-05-24T21:45:59Z",
                "topic": "test",
                "signal": "test signal",
                "source": "builder",
            }
        ]
        section = hook.format_memory_section(observations)
        assert "**Memoria relevante**:" in section
        assert "test signal" in section
        assert "2026-05-24" in section

    def test_truncate_long_signal(self):
        """Test que señales largas se truncan."""
        long_signal = "a" * 200
        observations = [
            {
                "timestamp": "2026-05-24T21:45:59Z",
                "topic": "test",
                "signal": long_signal,
                "source": "builder",
            }
        ]
        section = hook.format_memory_section(observations)
        # El signal debe estar truncado a 100 chars
        assert (
            len(long_signal[:100])
            in [len(line) for line in section.split("\n") if "test" in line]
            or long_signal[:100] in section
        )


class TestMainHook:
    """Tests para main() del hook."""

    def test_main_with_empty_input(self):
        """Test main con stdin vacio."""
        stdin_mock = StringIO("")
        stdout_mock = StringIO()

        with (
            patch.object(sys, "stdin", stdin_mock),
            patch.object(sys, "stdout", stdout_mock),
            patch.object(hook, "get_compact_context", return_value=""),
            patch.object(hook, "load_observations_safe", return_value=[]),
            patch.object(hook, "extract_keywords_from_work_plan", return_value=[]),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()
        assert exc_info.value.code == 0

        result = json.loads(stdout_mock.getvalue())
        assert result["continue"] is True
        assert "input" in result

    def test_main_with_memory(self):
        """Test main con memoria relevante (fallback L1 path)."""
        stdin_mock = StringIO("{}")
        stdout_mock = StringIO()

        observations = [
            {
                "timestamp": "2026-05-24T21:45:59Z",
                "topic": "context",
                "signal": "relevant signal",
                "source": "builder",
            }
        ]

        with (
            patch.object(sys, "stdin", stdin_mock),
            patch.object(sys, "stdout", stdout_mock),
            patch.object(hook, "get_compact_context", return_value=""),
            patch.object(hook, "load_observations_safe", return_value=observations),
            patch.object(
                hook, "extract_keywords_from_work_plan", return_value=["context"]
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()
        assert exc_info.value.code == 0

        result = json.loads(stdout_mock.getvalue())
        assert result["continue"] is True
        assert "additionalContext" in result
        assert "**Memoria relevante**:" in result["additionalContext"]

    def test_main_with_loader_context(self):
        """Test main usa loader context cuando get_compact_context() no es vacio."""
        stdin_mock = StringIO("{}")
        stdout_mock = StringIO()

        with (
            patch.object(sys, "stdin", stdin_mock),
            patch.object(sys, "stdout", stdout_mock),
            patch.object(
                hook,
                "get_compact_context",
                return_value="# L3 Profile\nActive: testing",
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()
        assert exc_info.value.code == 0

        result = json.loads(stdout_mock.getvalue())
        assert result["continue"] is True
        assert "additionalContext" in result
        assert "**Memoria del proyecto (L2+L3)**" in result["additionalContext"]
        assert "L3 Profile" in result["additionalContext"]

    def test_main_without_memory(self):
        """Test main sin memoria (no se incluye additionalContext)."""
        stdin_mock = StringIO("{}")
        stdout_mock = StringIO()

        with (
            patch.object(sys, "stdin", stdin_mock),
            patch.object(sys, "stdout", stdout_mock),
            patch.object(hook, "get_compact_context", return_value=""),
            patch.object(hook, "load_observations_safe", return_value=[]),
            patch.object(hook, "extract_keywords_from_work_plan", return_value=[]),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()
        assert exc_info.value.code == 0

        result = json.loads(stdout_mock.getvalue())
        assert result["continue"] is True
        assert "additionalContext" not in result  # No se incluye si esta vacio

    def test_main_with_corrupted_input(self):
        """Test main con stdin corrupto (no falla)."""
        stdin_mock = StringIO("not valid json")
        stdout_mock = StringIO()

        with (
            patch.object(sys, "stdin", stdin_mock),
            patch.object(sys, "stdout", stdout_mock),
            patch.object(hook, "get_compact_context", return_value=""),
            patch.object(hook, "load_observations_safe", return_value=[]),
            patch.object(hook, "extract_keywords_from_work_plan", return_value=[]),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()
        assert exc_info.value.code == 0

        result = json.loads(stdout_mock.getvalue())
        assert result["continue"] is True
        assert result["input"] == {}  # Input vacio por error de parseo

    @pytest.mark.parametrize(
        "env_value",
        ["", "   ", "relative-root", "missing-root", "C:\\mangled\\root"],
    )
    def test_invalid_project_root_degrades_to_cwd_root(
        self, monkeypatch, tmp_path, env_value
    ):
        cwd_root = tmp_path / "cwd-root"
        (cwd_root / ".claude").mkdir(parents=True)
        monkeypatch.chdir(cwd_root)
        monkeypatch.setenv("AGENT_PROJECT_ROOT", env_value)

        assert hook._resolve_data_root() == cwd_root.resolve()

    def test_project_root_file_degrades_to_cwd_root(self, monkeypatch, tmp_path):
        cwd_root = tmp_path / "cwd-root"
        (cwd_root / ".claude").mkdir(parents=True)
        invalid = tmp_path / "not-a-directory"
        invalid.write_text("x", encoding="utf-8")
        monkeypatch.chdir(cwd_root)
        monkeypatch.setenv("AGENT_PROJECT_ROOT", str(invalid))

        assert hook._resolve_data_root() == cwd_root.resolve()

    def test_existing_relative_project_root_is_not_accepted(
        self, monkeypatch, tmp_path
    ):
        cwd_root = tmp_path / "cwd-root"
        relative_root = cwd_root / "relative-root"
        (cwd_root / ".claude").mkdir(parents=True)
        relative_root.mkdir()
        monkeypatch.chdir(cwd_root)
        monkeypatch.setenv("AGENT_PROJECT_ROOT", "relative-root")

        assert hook._resolve_data_root() == cwd_root.resolve()

        monkeypatch.setenv("AGENT_PROJECT_ROOT", str(relative_root))
        assert hook._resolve_data_root() == relative_root.resolve()

    def test_existing_mangled_project_root_degrades(self, monkeypatch, tmp_path):
        cwd_root = tmp_path / "cwd-root"
        mangled_root = tmp_path / "mangled-root"
        (cwd_root / ".claude").mkdir(parents=True)
        mangled_root.mkdir()
        monkeypatch.chdir(cwd_root)
        monkeypatch.setenv("AGENT_PROJECT_ROOT", str(mangled_root))

        with patch.object(hook, "_is_mangled_root", return_value=True) as detector:
            assert hook._resolve_data_root() == cwd_root.resolve()

        detector.assert_called_once_with(str(mangled_root), mangled_root.resolve())

    def test_project_root_uses_first_claude_ancestor(self, monkeypatch, tmp_path):
        root = tmp_path / "root"
        nested = root / "a" / "b"
        (root / ".claude").mkdir(parents=True)
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)

        assert hook._resolve_data_root() == root.resolve()

    def test_valid_inherited_project_root_wins_over_cwd(self, monkeypatch, tmp_path):
        cwd_root = tmp_path / "cwd-root"
        inherited_root = tmp_path / "inherited-root"
        (cwd_root / ".claude").mkdir(parents=True)
        inherited_root.mkdir()
        monkeypatch.chdir(cwd_root)
        monkeypatch.setenv("AGENT_PROJECT_ROOT", str(inherited_root))

        assert hook._resolve_data_root() == inherited_root.resolve()

    def test_main_passes_resolved_paths_and_restores_environment(
        self, monkeypatch, tmp_path, capsys
    ):
        root = tmp_path / "project"
        (root / ".claude").mkdir(parents=True)
        monkeypatch.chdir(root)
        monkeypatch.setenv("AGENT_PROJECT_ROOT", "stale-value")
        observations_paths = []
        work_plan_paths = []

        def load(path=None):
            observations_paths.append(path)
            return []

        def keywords(path=None):
            work_plan_paths.append(path)
            return []

        with (
            patch.object(sys, "stdin", StringIO("{}")),
            patch.object(hook, "get_compact_context", return_value=""),
            patch.object(hook, "load_observations_safe", side_effect=load),
            patch.object(hook, "extract_keywords_from_work_plan", side_effect=keywords),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()

        assert exc_info.value.code == 0
        assert observations_paths == [
            root / ".agent" / "runtime" / "memory" / "observations.jsonl"
        ]
        assert work_plan_paths == [root / ".agent" / "collaboration" / "work_plan.md"]
        assert os.environ["AGENT_PROJECT_ROOT"] == "stale-value"
        json.loads(capsys.readouterr().out)

    def test_main_restores_absent_environment(self, monkeypatch, tmp_path, capsys):
        root = tmp_path / "project"
        (root / ".claude").mkdir(parents=True)
        monkeypatch.chdir(root)
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)

        with (
            patch.object(sys, "stdin", StringIO("{}")),
            patch.object(sys, "stdout", StringIO()),
            patch.object(hook, "get_compact_context", return_value=""),
            patch.object(hook, "load_observations_safe", return_value=[]),
            patch.object(hook, "extract_keywords_from_work_plan", return_value=[]),
            pytest.raises(SystemExit),
        ):
            hook.main()

        assert "AGENT_PROJECT_ROOT" not in os.environ

    def test_main_continues_without_memory_when_cwd_is_unavailable(self, monkeypatch):
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        stdout = StringIO()

        with (
            patch.object(
                hook.Path, "cwd", side_effect=OSError("cwd unavailable")
            ) as cwd,
            patch.object(sys, "stdin", StringIO("{}")),
            patch.object(sys, "stdout", stdout),
            patch.object(
                hook, "get_compact_context", side_effect=AssertionError("memory read")
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()

        assert exc_info.value.code == 0
        cwd.assert_called_once_with()
        result = json.loads(stdout.getvalue())
        assert result["continue"] is True
        assert "additionalContext" not in result
        assert "AGENT_PROJECT_ROOT" not in os.environ

    def test_main_uses_valid_environment_when_cwd_is_unavailable(
        self, monkeypatch, tmp_path
    ):
        valid_root = tmp_path / "valid-root"
        valid_root.mkdir()
        monkeypatch.setenv("AGENT_PROJECT_ROOT", str(valid_root))
        stdout = StringIO()

        with (
            patch.object(
                hook.Path, "cwd", side_effect=OSError("cwd unavailable")
            ) as cwd,
            patch.object(sys, "stdin", StringIO("{}")),
            patch.object(sys, "stdout", stdout),
            patch.object(hook, "get_compact_context", return_value="VALID-ROOT"),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()

        assert exc_info.value.code == 0
        cwd.assert_not_called()
        result = json.loads(stdout.getvalue())
        assert result["continue"] is True
        assert "VALID-ROOT" in result["additionalContext"]
        assert os.environ["AGENT_PROJECT_ROOT"] == str(valid_root)

    def test_main_skips_permission_errors_while_scanning_ancestors(
        self, monkeypatch, tmp_path
    ):
        root = tmp_path / "root"
        middle = root / "middle"
        cwd_root = middle / "leaf"
        (root / ".claude").mkdir(parents=True)
        cwd_root.mkdir(parents=True)
        monkeypatch.chdir(cwd_root)
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        denied = {cwd_root / ".claude", middle / ".claude"}
        calls = []

        def is_dir(path):
            calls.append(path)
            if path in denied:
                raise PermissionError("permission denied")
            return path == root / ".claude"

        monkeypatch.setattr(hook.Path, "is_dir", is_dir)
        stdout = StringIO()

        with (
            patch.object(sys, "stdin", StringIO("{}")),
            patch.object(sys, "stdout", stdout),
            patch.object(hook, "get_compact_context", return_value=""),
            patch.object(hook, "load_observations_safe", return_value=[]),
            patch.object(hook, "extract_keywords_from_work_plan", return_value=[]),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()

        assert exc_info.value.code == 0
        assert cwd_root / ".claude" in calls
        assert middle / ".claude" in calls
        result = json.loads(stdout.getvalue())
        assert result["continue"] is True
        assert "additionalContext" not in result
        assert "AGENT_PROJECT_ROOT" not in os.environ

    def test_ancestor_scan_without_permission_error_is_control(
        self, monkeypatch, tmp_path
    ):
        root = tmp_path / "root"
        nested = root / "middle" / "leaf"
        (root / ".claude").mkdir(parents=True)
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)

        assert hook._resolve_data_root() == root.resolve()

    def test_main_degrades_when_l1_paths_are_inaccessible(self, monkeypatch, tmp_path):
        root = tmp_path / "project"
        (root / ".claude").mkdir(parents=True)
        monkeypatch.chdir(root)
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        stdout = StringIO()

        with (
            patch.object(
                hook.Path, "exists", side_effect=PermissionError("denied")
            ) as exists,
            patch.object(sys, "stdin", StringIO("{}")),
            patch.object(sys, "stdout", stdout),
            patch.object(hook, "get_compact_context", return_value=""),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()

        assert exc_info.value.code == 0
        assert exists.call_count >= 2
        result = json.loads(stdout.getvalue())
        assert result["continue"] is True
        assert "additionalContext" not in result
        assert "AGENT_PROJECT_ROOT" not in os.environ

    def test_main_degrades_when_compact_loader_raises(self, monkeypatch, tmp_path):
        root = tmp_path / "project"
        (root / ".claude").mkdir(parents=True)
        monkeypatch.chdir(root)
        monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
        stdout = StringIO()

        with (
            patch.object(sys, "stdin", StringIO("{}")),
            patch.object(sys, "stdout", stdout),
            patch.object(
                hook, "get_compact_context", side_effect=RuntimeError("loader failed")
            ),
            patch.object(
                hook, "load_observations_safe", side_effect=AssertionError("L1 read")
            ),
            patch.object(
                hook,
                "extract_keywords_from_work_plan",
                side_effect=AssertionError("plan read"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()

        assert exc_info.value.code == 0
        result = json.loads(stdout.getvalue())
        assert result["continue"] is True
        assert "additionalContext" not in result
        assert "AGENT_PROJECT_ROOT" not in os.environ


def _synthetic_precompact_fixture(tmp_path):
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    (motor / ".agent" / "hooks").mkdir(parents=True)
    (motor / ".agent" / "runtime" / "memory").mkdir(parents=True)
    shutil.copy2(
        HOOK_PATH / "pre_compact_hook.py",
        motor / ".agent" / "hooks" / "pre_compact_hook.py",
    )
    shutil.copytree(HOOK_PATH.parent.parent / "bus", motor / "bus")
    shutil.copytree(HOOK_PATH.parent.parent / "runtime", motor / "runtime")
    (destino / ".claude").mkdir(parents=True)
    (destino / ".agent" / "config").mkdir(parents=True)
    (destino / ".agent" / "runtime" / "memory").mkdir(parents=True)
    (destino / ".agent" / "collaboration").mkdir(parents=True)
    settings = pathlib.Path(__file__).parents[2] / ".claude" / "settings.json"
    shutil.copy2(settings, destino / ".claude" / "settings.json")
    (destino / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(motor)}), encoding="utf-8"
    )
    return motor, destino


def test_real_launcher_without_local_hook_anchors_loader_to_cwd(tmp_path):
    motor, destino = _synthetic_precompact_fixture(tmp_path)
    (motor / ".agent" / "runtime" / "memory" / "memory_profile.md").write_text(
        "MOTORMARK", encoding="utf-8"
    )
    (destino / ".agent" / "runtime" / "memory" / "memory_profile.md").write_text(
        "DESTMARK", encoding="utf-8"
    )

    result = _run_settings_hook("PreCompact", b"{}", destino, {})

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    output = result.stdout.decode("utf-8")
    assert "DESTMARK" in output
    assert "MOTORMARK" not in output


def test_real_launcher_l1_fallback_uses_destination_paths(tmp_path):
    motor, destino = _synthetic_precompact_fixture(tmp_path)
    (motor / ".agent" / "runtime" / "memory" / "observations.jsonl").write_text(
        '{"timestamp":"2026-11-07T00:00:00Z","topic":"motor","signal":"MOTORMARK","source":"test"}\n',
        encoding="utf-8",
    )
    (destino / ".agent" / "runtime" / "memory" / "observations.jsonl").write_text(
        '{"timestamp":"2026-11-07T00:00:00Z","topic":"destino","signal":"DESTMARK","source":"test"}\n',
        encoding="utf-8",
    )
    (destino / ".agent" / "collaboration" / "work_plan.md").write_text(
        "# DESTMARK", encoding="utf-8"
    )

    result = _run_settings_hook("PreCompact", b"{}", destino, {})

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    output = result.stdout.decode("utf-8")
    assert "DESTMARK" in output
    assert "MOTORMARK" not in output


def test_valid_stale_environment_override_is_measured(tmp_path):
    motor, destino = _synthetic_precompact_fixture(tmp_path)
    (motor / ".agent" / "runtime" / "memory" / "memory_profile.md").write_text(
        "MOTORMARK", encoding="utf-8"
    )
    (destino / ".agent" / "runtime" / "memory" / "memory_profile.md").write_text(
        "DESTMARK", encoding="utf-8"
    )

    result = _run_settings_hook(
        "PreCompact", b"{}", destino, {"AGENT_PROJECT_ROOT": str(motor)}
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    output = result.stdout.decode("utf-8")
    assert "MOTORMARK" in output
    assert "DESTMARK" not in output


class TestRobustness:
    """Tests para entradas malformadas no cubiertas por el schema basico."""

    def test_load_observations_invalid_utf8(self, tmp_path):
        """JSONL con bytes invalidos en UTF-8 no rompe el loader."""
        obs_file = tmp_path / "obs.jsonl"
        # Escribir bytes invalidos mezclados con JSON valido
        obs_file.write_bytes(
            b'{"timestamp": "2026-05-24T00:00:00Z", "topic": "ok", "signal": "s1", "source": "b"}\n'
            b"\xff\xfe invalid utf8 line\n"
            b'{"timestamp": "2026-05-25T00:00:00Z", "topic": "ok2", "signal": "s2", "source": "b"}\n'
        )
        with patch.object(hook, "OBSERVATIONS_FILE", obs_file):
            obs = hook.load_observations_safe()
        # La linea con bytes invalidos se saltea; las dos validas se cargan
        assert len(obs) == 2
        assert obs[0]["topic"] == "ok"
        assert obs[1]["topic"] == "ok2"

    def test_score_observation_non_string_fields(self):
        """score_observation no falla con topic/signal/source no-string."""
        obs = {
            "timestamp": "2026-05-24T00:00:00Z",
            "topic": 42,
            "signal": None,
            "source": True,
        }
        score = hook.score_observation(obs, ["42"])
        assert isinstance(score, int)
        assert score >= 0

    def test_format_memory_section_non_string_fields(self):
        """format_memory_section no lanza TypeError con campos no-string."""
        observations = [
            {"timestamp": None, "topic": 99, "signal": False, "source": 3.14}
        ]
        section = hook.format_memory_section(observations)
        assert "**Memoria relevante**:" in section
        # Los valores se convierten a str sin TypeError
        assert "99" in section or "False" in section


# WOT-2026-110a: mismo DoD que SessionStart sobre el comando REAL de PreCompact.
# `AGENT_PROJECT_ROOT` se apunta al destino porque este hook no lo fija solo
# (a diferencia de `session_start_hook._load_context`): es el canal canonico
# para que la memoria que se serializa sea la del destino sintetico.


def test_real_pre_compact_command_emits_ascii_with_cp1252_forced(tmp_path):
    """DoD WOT-2026-110a: el comando REAL de PreCompact emite SOLO ASCII.

    Medido 2026-10-21 antes del fix: con cwd=destino, `PYTHONUTF8` retirado y
    `PYTHONIOENCODING=cp1252`, la raya (U+2014) de la leccion salia como el
    byte 0x97 y `stdout.decode("utf-8")` fallaba.

    MUTACION ALCANZABLE: `ensure_ascii=False` en `main()` -> reaparece el byte
    0x97 y caen las tres aserciones.
    """
    destino = _destino_with_em_dash_archive(tmp_path)

    result = _run_settings_hook(
        "PreCompact",
        b"{}",
        destino,
        {"AGENT_PROJECT_ROOT": str(destino)},
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[:400]
    raw = result.stdout
    assert all(byte < 0x80 for byte in raw), (
        "el hook emitio bytes no-ASCII: con ensure_ascii=False el JSON sale en "
        f"la codepage del pipe; sospechosos={[b for b in raw if b >= 0x80][:5]}"
    )
    payload = json.loads(raw.decode("utf-8"))  # estricto
    assert payload["continue"] is True
    ctx = payload["additionalContext"]
    assert "em-dash-wot-110a" in ctx, "la leccion con U+2014 no llego al contexto"
    assert RAYA in ctx, (
        "json.loads debe recuperar el caracter ORIGINAL (U+2014), no un "
        "sustituto: el escape \\uXXXX de ensure_ascii=True es reversible"
    )
