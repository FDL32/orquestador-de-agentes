"""Tests para Semantic Logger Foundation - TICKET-006.

Pruebas de integraciÃ³n para hooks modificados y observaciones persistentes.
"""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.filterwarnings("ignore")

# AÃ±adir .agent al path para imports
sys.path.insert(0, str(Path(__file__).parent.parent / ".agent"))

from hooks.native_post_tool_hook import main as native_hook_main
from hooks.post_tool_hook import (
    log_observation,
    post_tool_hook,
    reset_counter
)


class TestSemanticLogger:
    """Tests para la funcionalidad de semantic logger."""

    def setup_method(self):
        """Setup antes de cada test."""
        # Crear directorio temporal para tests
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_memory_dir = self.temp_dir / "memory"
        self.test_observations_file = self.test_memory_dir / "observations.jsonl"

    def teardown_method(self):
        """Cleanup despuÃ©s de cada test."""
        # Limpiar archivos temporales
        try:
            if hasattr(self, 'test_observations_file') and self.test_observations_file.exists():
                self.test_observations_file.unlink()
        except (AttributeError, FileNotFoundError):
            pass
        try:
            if hasattr(self, 'test_memory_dir') and self.test_memory_dir.exists():
                self.test_memory_dir.rmdir()
        except (AttributeError, OSError):
            pass
        try:
            if hasattr(self, 'temp_dir') and self.temp_dir.exists():
                self.temp_dir.rmdir()
        except (AttributeError, OSError):
            pass

    def test_hook_translation(self):
        """Test que native_post_tool_hook traduce correctamente tool names y pasa contexto."""
        # Mock stdin con datos de herramienta Read
        test_input = json.dumps({
            "tool_name": "Read",
            "result": {
                "filePath": "test.py",
                "content": "print('hello')\nprint('world')"
            }
        })

        with patch('sys.stdin.read', return_value=test_input):
            with patch('sys.stdout'):
                with patch('hooks.post_tool_hook.post_tool_hook') as mock_post_hook:
                    native_hook_main()

                    # Verificar que se llamÃ³ con contexto completo
                    mock_post_hook.assert_called_once()
                    args, kwargs = mock_post_hook.call_args
                    context = args[0]

                    assert context["tool_name"] == "view_file"
                    assert "Read file test.py" in context["context"]
                    assert "2 lines" in context["context"]
                    assert "timestamp" in context
                    assert "session_id" in context

    def test_append_only(self):
        """Test que las observaciones se escriben append-only sin sobrescribir."""
        with patch('hooks.post_tool_hook.MEMORY_DIR', self.test_memory_dir):
            with patch('hooks.post_tool_hook.OBSERVATIONS_FILE', self.test_observations_file):
                # Primera observaciÃ³n
                context1 = {
                    "tool_name": "view_file",
                    "context": "First observation",
                    "timestamp": "2026-04-30T10:00:00",
                    "session_id": "test-1"
                }
                log_observation(context1)

                # Verificar primera lÃ­nea
                assert self.test_observations_file.exists()
                with open(self.test_observations_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    assert len(lines) == 1
                    obs1 = json.loads(lines[0])
                    assert obs1["tool"] == "view_file"
                    assert obs1["context"] == "First observation"

                # Segunda observaciÃ³n
                context2 = {
                    "tool_name": "grep_search",
                    "context": "Second observation",
                    "timestamp": "2026-04-30T10:01:00",
                    "session_id": "test-1"
                }
                log_observation(context2)

                # Verificar ambas lÃ­neas
                with open(self.test_observations_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    assert len(lines) == 2
                    obs2 = json.loads(lines[1])
                    assert obs2["tool"] == "grep_search"
                    assert obs2["context"] == "Second observation"

    def test_no_op_non_reading(self):
        """Test que herramientas no de lectura no afectan el contador pero sÃ­ se registran."""
        with patch('hooks.post_tool_hook.MEMORY_DIR', self.test_memory_dir):
            with patch('hooks.post_tool_hook.OBSERVATIONS_FILE', self.test_observations_file):
                # Simular herramienta no de lectura (ej: edit_file)
                context = {
                    "tool_name": "edit_file",
                    "context": "Modified file",
                    "timestamp": "2026-04-30T10:00:00",
                    "session_id": "test-1"
                }

                # Reset counter primero
                reset_counter()

                # Ejecutar hook
                post_tool_hook(context)

                # Verificar que se registrÃ³ la observaciÃ³n
                assert self.test_observations_file.exists()
                with open(self.test_observations_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    assert len(lines) == 1
                    obs = json.loads(lines[0])
                    assert obs["tool"] == "edit_file"

                # Verificar que el counter no se incrementÃ³ (no hay reminder)
                # Si se incrementÃ³, reset_counter() habrÃ­a sido llamado y habrÃ­a otra observaciÃ³n
                with open(self.test_observations_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    assert len(lines) == 1  # Solo la observaciÃ³n original

    def test_counter_reset(self):
        """Test que reset_counter funciona correctamente y no afecta observaciones existentes."""
        with patch('hooks.post_tool_hook.MEMORY_DIR', self.test_memory_dir):
            with patch('hooks.post_tool_hook.OBSERVATIONS_FILE', self.test_observations_file):
                # Registrar algunas observaciones
                log_observation({"tool_name": "view_file", "context": "test1"})
                log_observation({"tool_name": "grep_search", "context": "test2"})

                # Verificar que existen
                with open(self.test_observations_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    assert len(lines) == 2

                # Reset counter (no deberÃ­a afectar observaciones)
                reset_counter()

                # Verificar que las observaciones siguen ahÃ­
                with open(self.test_observations_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    assert len(lines) == 2

    def test_memory_directory_creation(self):
        """Test que el directorio de memoria se crea automÃ¡ticamente."""
        with patch('hooks.post_tool_hook.MEMORY_DIR', self.test_memory_dir):
            with patch('hooks.post_tool_hook.OBSERVATIONS_FILE', self.test_observations_file):
                # Antes de log_observation, el directorio no existe
                assert not self.test_memory_dir.exists()

                # DespuÃ©s de log_observation, se crea
                log_observation({"tool_name": "test", "context": "test"})
                assert self.test_memory_dir.exists()
                assert self.test_observations_file.exists()

    def test_jsonl_format(self):
        """Test que las observaciones estÃ¡n en formato JSONL vÃ¡lido."""
        with patch('hooks.post_tool_hook.MEMORY_DIR', self.test_memory_dir):
            with patch('hooks.post_tool_hook.OBSERVATIONS_FILE', self.test_observations_file):
                context = {
                    "tool_name": "view_file",
                    "context": "Test context with unicode: Ã±Ã¡Ã©Ã­Ã³Ãº",
                    "timestamp": "2026-04-30T10:00:00.123456",
                    "session_id": "test-session-123"
                }

                log_observation(context)

                # Verificar formato JSONL
                with open(self.test_observations_file, "r", encoding="utf-8") as f:
                    line = f.readline().strip()
                    obs = json.loads(line)

                    assert obs["timestamp"] == "2026-04-30T10:00:00.123456"
                    assert obs["tool"] == "view_file"
                    assert obs["context"] == "Test context with unicode: Ã±Ã¡Ã©Ã­Ã³Ãº"
                    assert obs["session_id"] == "test-session-123"
