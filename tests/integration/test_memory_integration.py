"""
Tests de integraciÃ³n para el flujo completo de memoria persistente.

UbicaciÃ³n: tests/integration/test_memory_integration.py
PropÃ³sito: Validar el flujo end-to-end de append, lectura y regeneraciÃ³n de Ã­ndice.
"""

import pathlib
import subprocess
import sys
from unittest.mock import patch


# Importar helpers
sys.path.insert(
    0,
    str(pathlib.Path(__file__).parent.parent.parent / ".agent" / "runtime" / "memory"),
)
from memory_helpers import append_observation, create_memory_index, read_observations


class TestMemoryIntegrationFlow:
    """Tests de integraciÃ³n del flujo completo de memoria."""

    def test_full_flow_append_read_regenerate(self, tmp_path):
        """Test flujo completo: append -> read -> regenerate index."""
        # Setup temporary memory directory
        memory_dir = tmp_path / ".agent" / "runtime" / "memory"
        memory_dir.mkdir(parents=True)

        with patch("memory_helpers.get_memory_dir", return_value=memory_dir):
            # Paso 1: Append observaciones
            obs1 = {
                "timestamp": "2026-05-06T10:00:00Z",
                "topic": "arquitectura",
                "signal": "Implementada base de memoria",
                "source": "builder",
            }
            obs2 = {
                "timestamp": "2026-05-06T11:00:00Z",
                "topic": "integracion",
                "signal": "Creado script CLI",
                "source": "builder",
            }

            assert append_observation(obs1)
            assert append_observation(obs2)

            # Paso 2: Read observaciones
            observations = read_observations()
            assert len(observations) == 2
            assert observations[0]["signal"] == "Implementada base de memoria"
            assert observations[1]["signal"] == "Creado script CLI"

            # Paso 3: Regenerate index
            assert create_memory_index()

            # Verificar que MEMORY.md se actualizÃ³
            memory_file = memory_dir / "MEMORY.md"
            assert memory_file.exists()

            with open(memory_file, encoding="utf-8") as f:
                content = f.read()
                assert "Total de observaciones: 2" in content
                assert "Arquitectura (1 observaciones)" in content
                assert "Integracion (1 observaciones)" in content
                assert "Implementada base de memoria" in content
                assert "Creado script CLI" in content

    def test_cli_integration_via_subprocess(self, tmp_path):
        """Test integraciÃ³n con CLI memory_manager.py vÃ­a subprocess."""
        # Crear un proyecto temporal con estructura
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()

        # Crear .agent estructura
        agent_dir = project_dir / ".agent"
        agent_dir.mkdir()

        # Copiar memory_helpers.py
        memory_dir = agent_dir / "runtime" / "memory"
        memory_dir.mkdir(parents=True)

        original_helpers = (
            pathlib.Path(__file__).parent.parent.parent
            / ".agent"
            / "runtime"
            / "memory"
            / "memory_helpers.py"
        )
        import shutil

        shutil.copy(original_helpers, memory_dir / "memory_helpers.py")

        # Copiar memory_manager.py
        script_dir = project_dir / "tools" / "scripts"
        script_dir.mkdir(parents=True)

        original_script = (
            pathlib.Path(__file__).parent.parent.parent
            / "tools"
            / "scripts"
            / "memory_manager.py"
        )
        shutil.copy(original_script, script_dir / "memory_manager.py")

        # Ejecutar comando append vÃ­a subprocess
        cmd = [
            sys.executable,
            str(script_dir / "memory_manager.py"),
            "append",
            "--topic",
            "test",
            "--signal",
            "ObservaciÃ³n de integraciÃ³n",
            "--source",
            "test",
        ]

        result = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)
        assert result.returncode == 0
        assert "Observacion registrada exitosamente" in result.stdout

        # Ejecutar regenerate
        cmd_regen = [
            sys.executable,
            str(script_dir / "memory_manager.py"),
            "regenerate",
        ]

        result_regen = subprocess.run(
            cmd_regen, cwd=project_dir, capture_output=True, text=True
        )
        assert result_regen.returncode == 0
        assert "Indice de memoria regenerado exitosamente" in result_regen.stdout

        # Ejecutar read
        cmd_read = [sys.executable, str(script_dir / "memory_manager.py"), "read"]

        result_read = subprocess.run(
            cmd_read, cwd=project_dir, capture_output=True, text=True
        )
        assert result_read.returncode == 0
        assert "Memoria del proyecto (1 observaciones)" in result_read.stdout
        assert "ObservaciÃ³n de integraciÃ³n" in result_read.stdout

    def test_memory_separation_from_collaboration(self, tmp_path):
        """Test que la memoria no interfiere con .agent/collaboration/."""
        # Setup
        memory_dir = tmp_path / ".agent" / "runtime" / "memory"
        memory_dir.mkdir(parents=True)

        collab_dir = tmp_path / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True)

        # Crear archivos simulados de collaboration
        work_plan = collab_dir / "work_plan.md"
        work_plan.write_text("# Work Plan\n- Task 1")

        execution_log = collab_dir / "execution_log.md"
        execution_log.write_text("# Execution Log\n- Progress")

        with patch("memory_helpers.get_memory_dir", return_value=memory_dir):
            # Append memoria
            obs = {
                "timestamp": "2026-05-06T12:00:00Z",
                "topic": "separacion",
                "signal": "Memoria no interfiere con collaboration",
                "source": "test",
            }
            assert append_observation(obs)

            # Verificar que archivos de collaboration no cambiaron
            assert work_plan.read_text() == "# Work Plan\n- Task 1"
            assert execution_log.read_text() == "# Execution Log\n- Progress"

            # Verificar que memoria funciona
            observations = read_observations()
            assert len(observations) == 1
            assert (
                observations[0]["signal"] == "Memoria no interfiere con collaboration"
            )
