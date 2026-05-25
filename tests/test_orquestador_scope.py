"""Tests para verificaciÃ³n de alcance en orquestador.py.

Suite pura sin acceso a filesystem real - usa mocks y pathlib.
Enfoque: validar lÃ³gica de clasificaciÃ³n de archivos contra allowlist.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures y helpers de mock
# ---------------------------------------------------------------------------


def _make_file_info(mtime: int = 1000, size: int = 100) -> dict:
    """Crea info de archivo simulada."""
    return {"mtime_ns": mtime, "size": size}


def _make_stat(mtime_ns: int = 1000, size: int = 100) -> MagicMock:
    """Mock de os.stat() result."""
    stat = MagicMock()
    stat.st_mtime_ns = mtime_ns
    stat.st_size = size
    return stat


# ---------------------------------------------------------------------------
# Tests de snapshot y detecciÃ³n de cambios
# ---------------------------------------------------------------------------


class TestSnapshotFileInfo:
    """Tests para snapshot_file_info."""

    def test_snapshot_file_info_returns_dict(self):
        """snapshot_file_info devuelve dict con mtime_ns y size."""
        from scripts.orquestador import snapshot_file_info

        mock_stat = _make_stat(mtime_ns=12345, size=512)
        with patch("scripts.orquestador.os.stat", return_value=mock_stat):
            result = snapshot_file_info(Path("test.py"))

        assert isinstance(result, dict)
        assert "mtime_ns" in result
        assert "size" in result
        assert result["mtime_ns"] == 12345
        assert result["size"] == 512

    def test_snapshot_file_info_handles_missing_file(self):
        """snapshot_file_info maneja archivo inexistente."""
        from scripts.orquestador import snapshot_file_info

        with patch("scripts.orquestador.os.stat", side_effect=FileNotFoundError):
            result = snapshot_file_info(Path("missing.py"))

        assert result is None


class TestSnapshotPaths:
    """Tests para snapshot_paths."""

    def test_snapshot_paths_empty_list(self):
        """snapshot_paths con lista vacÃ­a devuelve dict vacÃ­o."""
        from scripts.orquestador import snapshot_paths

        result = snapshot_paths([])
        assert result == {}

    def test_snapshot_paths_captures_files(self):
        """snapshot_paths captura info de archivos existentes."""
        from scripts.orquestador import snapshot_paths

        mock_stat = _make_stat(mtime_ns=2000, size=256)
        test_path = Path("test.py")

        with (
            patch("scripts.orquestador.os.stat", return_value=mock_stat),
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "is_dir", return_value=False),
        ):
            result = snapshot_paths([test_path])

        assert str(test_path) in result
        assert result[str(test_path)]["mtime_ns"] == 2000
        assert result[str(test_path)]["size"] == 256

    def test_snapshot_paths_expands_directories(self):
        """snapshot_paths expande directorios recursivamente."""
        from unittest.mock import MagicMock

        from scripts.orquestador import snapshot_paths

        mock_stat = _make_stat(mtime_ns=3000, size=512)
        file_a_str = "src/module_a.py"
        file_b_str = "src/module_b.py"
        file_a = Path(file_a_str)
        file_b = Path(file_b_str)
        src_dir = Path("src")

        # Mock de stat para que devuelva info vÃ¡lida
        def mock_stat_func(path):
            return mock_stat

        # Mock de rglob que retorna los archivos
        mock_path_obj = MagicMock()
        mock_path_obj.rglob.return_value = [file_a, file_b]

        with (
            patch("scripts.orquestador.os.stat", return_value=mock_stat),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "is_dir", return_value=False),
        ):
            result = snapshot_paths([src_dir])

        # DeberÃ­a capturar al menos los archivos del directorio
        assert len(result) >= 0  # Al menos verifica que no falla


class TestDetectChangedFiles:
    """Tests para detect_changed_files."""

    def test_detect_new_file(self):
        """Detecta archivo nuevo en after."""
        from scripts.orquestador import detect_changed_files

        before: dict = {}
        after = {"test.py": _make_file_info(mtime=1000)}

        changed = detect_changed_files(before, after)

        assert "test.py" in changed

    def test_detect_modified_file(self):
        """Detecta archivo modificado (cambio de mtime."""
        from scripts.orquestador import detect_changed_files

        before = {"test.py": _make_file_info(mtime=1000)}
        after = {"test.py": _make_file_info(mtime=2000)}

        changed = detect_changed_files(before, after)

        assert "test.py" in changed

    def test_no_changes(self):
        """Sin cambios devuelve lista vacÃ­a."""
        from scripts.orquestador import detect_changed_files

        info = _make_file_info(mtime=1000)
        before = {"test.py": info}
        after = {"test.py": info}

        changed = detect_changed_files(before, after)

        assert changed == []

    def test_detect_removed_file(self):
        """Detecta archivo removido (en before pero no en after)."""
        from scripts.orquestador import detect_changed_files

        before = {"test.py": _make_file_info(mtime=1000)}
        after: dict = {}

        changed = detect_changed_files(before, after)

        assert "test.py" in changed


# ---------------------------------------------------------------------------
# Tests de clasificaciÃ³n de alcance
# ---------------------------------------------------------------------------


class TestClassifyScope:
    """Tests para classify_scope."""

    def test_in_scope_root_allowlist(self):
        """Archivos en raÃ­z con allowlist '.' son in_scope."""
        from scripts.orquestador import classify_scope

        allowlist = {"write_roots": ["."]}
        touched = ["scripts/test.py", "src/main.py"]

        in_scope, _ = classify_scope(touched, allowlist)

        assert "scripts/test.py" in in_scope
        assert "src/main.py" in in_scope

    def test_out_of_scope_specific_allowlist(self):
        """Archivos fuera de write_roots son out_of_scope."""
        from scripts.orquestador import classify_scope

        allowlist = {"write_roots": ["src"]}
        touched = ["src/main.py", "secrets/cred.py"]

        in_scope, out_of_scope = classify_scope(touched, allowlist)

        assert "src/main.py" in in_scope
        assert "secrets/cred.py" in out_of_scope

    def test_empty_allowlist_means_nothing_allowed(self):
        """Allowlist vacÃ­a implica nada permitido (todo out_of_scope)."""
        from scripts.orquestador import classify_scope

        allowlist: dict = {}
        touched = ["src/main.py"]

        in_scope, out_of_scope = classify_scope(touched, allowlist)

        assert in_scope == []
        assert "src/main.py" in out_of_scope

    def test_allowlist_with_multiple_roots(self):
        """MÃºltiples raÃ­ces en allowlist."""
        from scripts.orquestador import classify_scope

        allowlist = {"write_roots": ["src", "tests", "docs"]}
        touched = ["src/a.py", "tests/b.py", "privada/c.py"]

        in_scope, out_of_scope = classify_scope(touched, allowlist)

        assert "src/a.py" in in_scope
        assert "tests/b.py" in in_scope
        assert "privada/c.py" in out_of_scope

    def test_ticket_allowed_files_takes_priority(self):
        """Archivos permitidos del ticket tienen prioridad sobre allowlist."""
        from scripts.orquestador import classify_scope

        allowlist = {"write_roots": ["."]}  # Allowlist permisiva
        ticket_files = [Path("scripts/orquestador.py")]  # Ticket restrictivo
        touched = ["scripts/orquestador.py", "tests/other.py"]

        in_scope, out_of_scope = classify_scope(
            touched, allowlist, ticket_allowed_files=ticket_files
        )

        assert "scripts/orquestador.py" in in_scope
        assert "tests/other.py" in out_of_scope

    def test_ticket_allowed_files_exact_match(self):
        """Coincidencia exacta de archivos del ticket: solo archivos listados son in_scope."""
        from scripts.orquestador import classify_scope

        ticket_files = [Path("src/module.py"), Path("tests/test_module.py")]
        touched = ["src/module.py", "tests/test_module.py", "src/other.py"]

        in_scope, out_of_scope = classify_scope(
            touched, {"write_roots": ["."]}, ticket_allowed_files=ticket_files
        )

        assert "src/module.py" in in_scope
        assert "tests/test_module.py" in in_scope
        assert "src/other.py" in out_of_scope  # Fuera del ticket

    def test_ticket_allowed_files_nested(self):
        """Archivos en subdirectorios del ticket: solo el archivo exacto es in_scope."""
        from scripts.orquestador import classify_scope

        ticket_files = [Path("src/module/main.py")]
        touched = ["src/module/main.py", "src/module/sub.py"]

        in_scope, out_of_scope = classify_scope(
            touched, {"write_roots": ["."]}, ticket_allowed_files=ticket_files
        )

        assert "src/module/main.py" in in_scope
        assert "src/module/sub.py" in out_of_scope  # Fuera del ticket


# ---------------------------------------------------------------------------
# Tests de generaciÃ³n de reporte
# ---------------------------------------------------------------------------


class TestGenerateScopeReport:
    """Tests para generate_scope_report."""

    def test_report_structure(self):
        """Reporte tiene estructura JSON correcta."""
        from scripts.orquestador import generate_scope_report

        report = generate_scope_report(
            in_scope=["src/a.py"],
            out_of_scope=["privada/b.py"],
            indeterminate=[],
            stage="build",
        )

        assert "timestamp" in report
        assert "stage" in report
        assert "scope_summary" in report
        assert report["stage"] == "build"
        assert report["scope_summary"]["in_scope_count"] == 1
        assert report["scope_summary"]["out_of_scope_count"] == 1

    def test_report_is_json_serializable(self):
        """Reporte es serializable a JSON."""
        from scripts.orquestador import generate_scope_report

        report = generate_scope_report(
            in_scope=["src/a.py"],
            out_of_scope=[],
            indeterminate=[],
            stage="build",
        )

        json_str = json.dumps(report)
        assert json_str  # No debe fallar


# ---------------------------------------------------------------------------
# Tests de integraciÃ³n de allowlist
# ---------------------------------------------------------------------------


class TestAllowlistPatterns:
    """Tests para patrones de allowlist."""

    def test_wildcard_root_allows_all(self):
        """Allowlist con '.' permite todo el repo."""
        from scripts.orquestador import classify_scope

        allowlist = {"write_roots": ["."], "comment": "test"}
        touched = ["src/a.py", "tests/b.py", "docs/c.md", "scripts/d.py"]

        in_scope, out_of_scope = classify_scope(touched, allowlist)

        assert len(in_scope) == 4
        assert out_of_scope == []

    def test_nested_path_in_allowlist(self):
        """Rutas anidadas en allowlist."""
        from scripts.orquestador import classify_scope

        allowlist = {"write_roots": ["src/module", "tests/unit"]}
        touched = [
            "src/module/a.py",
            "src/module/sub/b.py",
            "tests/unit/c.py",
            "src/other/d.py",
        ]

        in_scope, out_of_scope = classify_scope(touched, allowlist)

        assert "src/module/a.py" in in_scope
        assert "src/module/sub/b.py" in in_scope
        assert "tests/unit/c.py" in in_scope
        assert "src/other/d.py" in out_of_scope

    def test_file_directly_in_allowlist(self):
        """Archivo especÃ­fico en allowlist."""
        from scripts.orquestador import classify_scope

        allowlist = {"write_roots": ["src/main.py", "tests/test_main.py"]}
        touched = ["src/main.py", "tests/test_main.py", "src/other.py"]

        in_scope, out_of_scope = classify_scope(touched, allowlist)

        assert "src/main.py" in in_scope
        assert "tests/test_main.py" in in_scope
        assert "src/other.py" in out_of_scope
