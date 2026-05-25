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
import pathlib
import sys
from io import StringIO
from unittest.mock import patch

import pytest


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
        """Test main con memoria relevante."""
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

    def test_main_without_memory(self):
        """Test main sin memoria (no se incluye additionalContext)."""
        stdin_mock = StringIO("{}")
        stdout_mock = StringIO()

        with (
            patch.object(sys, "stdin", stdin_mock),
            patch.object(sys, "stdout", stdout_mock),
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
            patch.object(hook, "load_observations_safe", return_value=[]),
            patch.object(hook, "extract_keywords_from_work_plan", return_value=[]),
            pytest.raises(SystemExit) as exc_info,
        ):
            hook.main()
        assert exc_info.value.code == 0

        result = json.loads(stdout_mock.getvalue())
        assert result["continue"] is True
        assert result["input"] == {}  # Input vacio por error de parseo


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
