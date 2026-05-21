"""
Tests para memoria persistente del proyecto.

UbicaciÃ³n: tests/unit/test_memory.py
"""

import json
import pathlib
import pytest
from unittest.mock import patch

# Importar los helpers
import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / '.agent' / 'runtime' / 'memory'))
from memory_helpers import append_observation, read_observations, validate_observation, get_memory_dir, get_observations_file


class TestMemoryHelpers:
    """Tests para memory_helpers.py"""

    def test_validate_observation_valid(self):
        """Test validaciÃ³n de observaciÃ³n completa."""
        obs = {
            "timestamp": "2026-05-06T14:00:00Z",
            "topic": "arquitectura",
            "signal": "Test signal",
            "source": "test"
        }
        assert validate_observation(obs) is True

    def test_validate_observation_missing_field(self):
        """Test validaciÃ³n falla si falta campo requerido."""
        obs = {
            "timestamp": "2026-05-06T14:00:00Z",
            "topic": "arquitectura",
            "signal": "Test signal"
            # Falta source
        }
        assert validate_observation(obs) is False

    def test_append_and_read_observation(self, tmp_path):
        """Test append y lectura de observaciÃ³n."""
        # Mock el directorio de memoria para usar tmp_path
        memory_dir = tmp_path / ".agent" / "runtime" / "memory"
        memory_dir.mkdir(parents=True)

        with patch('memory_helpers.get_memory_dir', return_value=memory_dir):
            obs = {
                "timestamp": "2026-05-06T14:00:00Z",
                "topic": "test",
                "signal": "Test observation",
                "source": "unit_test"
            }

            # Append
            result = append_observation(obs)
            assert result is True

            # Read
            observations = read_observations()
            assert len(observations) == 1
            assert observations[0] == obs

    def test_read_empty_file(self, tmp_path):
        """Test lectura cuando archivo no existe."""
        memory_dir = tmp_path / ".agent" / "runtime" / "memory"
        memory_dir.mkdir(parents=True)

        with patch('memory_helpers.get_memory_dir', return_value=memory_dir):
            observations = read_observations()
            assert observations == []

    def test_append_creates_directory(self, tmp_path):
        """Test que append cree el directorio si no existe."""
        memory_dir = tmp_path / ".agent" / "runtime" / "memory"
        # No crear el directorio

        with patch('memory_helpers.get_memory_dir', return_value=memory_dir):
            obs = {
                "timestamp": "2026-05-06T14:00:00Z",
                "topic": "test",
                "signal": "Test observation",
                "source": "unit_test"
            }

            result = append_observation(obs)
            assert result is True
            assert memory_dir.exists()

    def test_read_skips_invalid_json(self, tmp_path):
        """Test que lectura salte lÃ­neas JSON invÃ¡lidas."""
        memory_dir = tmp_path / ".agent" / "runtime" / "memory"
        memory_dir.mkdir(parents=True)
        obs_file = memory_dir / "observations.jsonl"

        # Escribir lÃ­nea invÃ¡lida y vÃ¡lida
        with open(obs_file, 'w', encoding='utf-8') as f:
            f.write("invalid json line\n")
            f.write('{"timestamp":"2026-05-06T14:00:00Z","topic":"test","signal":"Valid","source":"test"}\n')

        with patch('memory_helpers.get_memory_dir', return_value=memory_dir):
            observations = read_observations()
            assert len(observations) == 1
            assert observations[0]["signal"] == "Valid"

    def test_append_utf8_encoding(self, tmp_path):
        """Test que append maneje UTF-8 correctamente."""
        memory_dir = tmp_path / ".agent" / "runtime" / "memory"
        memory_dir.mkdir(parents=True)

        with patch('memory_helpers.get_memory_dir', return_value=memory_dir):
            obs = {
                "timestamp": "2026-05-06T14:00:00Z",
                "topic": "test",
                "signal": "SeÃ±al con tildes: Ã¡Ã©Ã­Ã³Ãº",
                "source": "test"
            }

            result = append_observation(obs)
            assert result is True

            observations = read_observations()
            assert len(observations) == 1
            assert observations[0]["signal"] == "SeÃ±al con tildes: Ã¡Ã©Ã­Ã³Ãº"

    def test_append_observation_validation(self, tmp_path):
        """Test que append_observation rechace observaciones invÃ¡lidas."""
        memory_dir = tmp_path / ".agent" / "runtime" / "memory"
        memory_dir.mkdir(parents=True)

        with patch('memory_helpers.get_memory_dir', return_value=memory_dir):
            # ObservaciÃ³n invÃ¡lida (falta source)
            invalid_obs = {
                "timestamp": "2026-05-06T14:00:00Z",
                "topic": "test",
                "signal": "Invalid observation"
                # Falta source
            }

            result = append_observation(invalid_obs)
            assert result is False

            # Verificar que no se escribiÃ³ nada
            observations = read_observations()
            assert len(observations) == 0

            # ObservaciÃ³n vÃ¡lida
            valid_obs = {
                "timestamp": "2026-05-06T14:00:00Z",
                "topic": "test",
                "signal": "Valid observation",
                "source": "test"
            }

            result = append_observation(valid_obs)
            assert result is True

            observations = read_observations()
            assert len(observations) == 1

    def test_create_memory_index_empty(self, tmp_path):
        """Test creaciÃ³n de Ã­ndice cuando no hay observaciones."""
        memory_dir = tmp_path / ".agent" / "runtime" / "memory"
        memory_dir.mkdir(parents=True)

        with patch('memory_helpers.get_memory_dir', return_value=memory_dir):
            from memory_helpers import create_memory_index
            result = create_memory_index()
            assert result is True

            memory_file = memory_dir / "MEMORY.md"
            assert memory_file.exists()

            with open(memory_file, 'r', encoding='utf-8') as f:
                content = f.read()
                assert "No hay observaciones registradas aÃºn" in content

    def test_create_memory_index_with_observations(self, tmp_path):
        """Test creaciÃ³n de Ã­ndice con observaciones existentes."""
        memory_dir = tmp_path / ".agent" / "runtime" / "memory"
        memory_dir.mkdir(parents=True)

        with patch('memory_helpers.get_memory_dir', return_value=memory_dir):
            # Agregar algunas observaciones
            obs1 = {"timestamp": "2026-05-06T10:00:00Z", "topic": "arquitectura", "signal": "Obs 1", "source": "agent"}
            obs2 = {"timestamp": "2026-05-06T11:00:00Z", "topic": "bug", "signal": "Obs 2", "source": "usuario"}
            obs3 = {"timestamp": "2026-05-06T12:00:00Z", "topic": "arquitectura", "signal": "Obs 3", "source": "test"}

            append_observation(obs1)
            append_observation(obs2)
            append_observation(obs3)

            from memory_helpers import create_memory_index
            result = create_memory_index()
            assert result is True

            memory_file = memory_dir / "MEMORY.md"
            with open(memory_file, 'r', encoding='utf-8') as f:
                content = f.read()
                assert "Total de observaciones: 3" in content
                assert "Arquitectura (2 observaciones)" in content
                assert "Bug (1 observaciones)" in content
                assert "Obs 1" in content
                assert "Obs 2" in content
                assert "Obs 3" in content
