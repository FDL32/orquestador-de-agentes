"""Tests for project_scanner module."""

import tempfile
from pathlib import Path

import pytest
from scripts.project_scanner import (
    _is_excluded,
    _matches_pattern,
    categorize_file,
    detect_framework_hints,
    extract_imports,
    generate_report,
    rel_path,
    scan_project,
    sha256_file,
)


class TestMatchesPattern:
    """Test _matches_pattern utility."""

    def test_matches_extension_pattern(self):
        """Test matching file extension patterns."""
        path = Path("test.pyc")
        assert _matches_pattern(path, {"*.pyc"}) is True
        assert _matches_pattern(path, {"*.py"}) is False

    def test_matches_name_pattern(self):
        """Test matching exact name patterns."""
        path = Path(".DS_Store")
        assert _matches_pattern(path, {".DS_Store"}) is True
        assert _matches_pattern(path, {".gitignore"}) is False

    def test_no_match(self):
        """Test when no pattern matches."""
        path = Path("test.py")
        assert _matches_pattern(path, {"*.pyc", "*.so"}) is False


class TestIsExcluded:
    """Test _is_excluded function."""

    def test_excluded_directory(self):
        """Test that excluded directories are filtered."""
        project_root = Path("/tmp/test")
        excluded_paths = [
            project_root / ".git" / "config",
            project_root / ".venv" / "lib" / "python.py",
            project_root / "__pycache__" / "module.pyc",
            project_root / "node_modules" / "package" / "index.js",
        ]
        for path in excluded_paths:
            assert _is_excluded(path, project_root) is True, f"Failed for {path}"

    def test_excluded_file_pattern(self):
        """Test that excluded file patterns are filtered."""
        project_root = Path("/tmp/test")
        excluded_paths = [
            project_root / "module.pyc",
            project_root / "data.so",
            project_root / "debug.log",
        ]
        for path in excluded_paths:
            assert _is_excluded(path, project_root) is True, f"Failed for {path}"

    def test_included_file(self):
        """Test that valid product files are included."""
        project_root = Path("/tmp/test")
        included_paths = [
            project_root / "src" / "module.py",
            project_root / "docs" / "README.md",
            project_root / "pyproject.toml",
        ]
        for path in included_paths:
            assert _is_excluded(path, project_root) is False, f"Failed for {path}"

    def test_excluded_by_extension(self):
        """Test files with non-whitelisted extensions are excluded."""
        project_root = Path("/tmp/test")
        path = project_root / "data.bin"
        assert _is_excluded(path, project_root) is True


class TestCategorizeFile:
    """Test categorize_file function."""

    def test_python_category(self):
        """Test Python file categorization."""
        assert categorize_file(Path("test.py")) == "python"

    def test_documentation_category(self):
        """Test documentation file categorization."""
        assert categorize_file(Path("README.md")) == "documentation"
        assert categorize_file(Path("notes.txt")) == "documentation"

    def test_config_category(self):
        """Test config file categorization."""
        assert categorize_file(Path("pyproject.toml")) == "config"
        assert categorize_file(Path("config.yaml")) == "config"
        assert categorize_file(Path("settings.json")) == "config"

    def test_scripts_category(self):
        """Test script file categorization."""
        assert categorize_file(Path("run.sh")) == "scripts"
        assert categorize_file(Path("deploy.ps1")) == "scripts"

    def test_javascript_category(self):
        """Test JavaScript file categorization."""
        assert categorize_file(Path("app.js")) == "javascript"
        assert categorize_file(Path("component.jsx")) == "javascript"

    def test_typescript_category(self):
        """Test TypeScript file categorization."""
        assert categorize_file(Path("app.ts")) == "typescript"
        assert categorize_file(Path("component.tsx")) == "typescript"


class TestSha256File:
    """Test sha256_file function."""

    def test_sha256_deterministic(self):
        """Test that SHA256 is deterministic."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("test content")
            temp_path = Path(f.name)

        try:
            hash1 = sha256_file(temp_path)
            hash2 = sha256_file(temp_path)
            assert hash1 == hash2
            assert len(hash1) == 64  # SHA256 hex length
        finally:
            temp_path.unlink()

    def test_sha256_different_content(self):
        """Test that different content produces different hashes."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f1:
            f1.write("content 1")
            path1 = Path(f1.name)

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f2:
            f2.write("content 2")
            path2 = Path(f2.name)

        try:
            hash1 = sha256_file(path1)
            hash2 = sha256_file(path2)
            assert hash1 != hash2
        finally:
            path1.unlink()
            path2.unlink()

    def test_sha256_unreadable(self):
        """Test that unreadable files return UNREADABLE."""
        fake_path = Path("/nonexistent/file.txt")
        assert sha256_file(fake_path) == "UNREADABLE"


class TestRelPath:
    """Test rel_path function."""

    def test_rel_path_within_root(self):
        """Test relative path within project root."""
        project_root = Path("/tmp/project")
        file_path = project_root / "src" / "module.py"
        result = rel_path(file_path, project_root)
        assert result == "src/module.py"

    def test_rel_path_forward_slashes(self):
        """Test that result uses forward slashes."""
        project_root = Path("/tmp/project")
        file_path = project_root / "src" / "subdir" / "module.py"
        result = rel_path(file_path, project_root)
        assert "\\" not in result
        assert "/" in result


class TestExtractImports:
    """Test extract_imports function with AST-based import extraction."""

    def test_extract_stdlib_imports(self):
        """Test extraction of stdlib imports."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("import os\nimport sys\nfrom pathlib import Path\n")
            temp_path = Path(f.name)

        try:
            result = extract_imports(temp_path, Path("/tmp"))
            assert result["error"] is None
            imports = result["imports"]
            assert len(imports) == 3
            # All should be classified as stdlib
            for imp in imports:
                assert imp["type"] in ("stdlib", "local")
        finally:
            temp_path.unlink()

    def test_extract_from_import(self):
        """Test extraction of from...import statements."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("from collections import defaultdict\n")
            temp_path = Path(f.name)

        try:
            result = extract_imports(temp_path, Path("/tmp"))
            assert result["error"] is None
            assert len(result["imports"]) == 1
            assert result["imports"][0]["name"] == "collections.defaultdict"
        finally:
            temp_path.unlink()

    def test_extract_syntax_error(self):
        """Test that SyntaxError is captured in result."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("import os\nif True:\n  print('bad indent'\n")  # Syntax error
            temp_path = Path(f.name)

        try:
            result = extract_imports(temp_path, Path("/tmp"))
            assert result["error"] is not None
            assert "SyntaxError" in result["error"]
        finally:
            temp_path.unlink()

    def test_extract_local_import(self, tmp_path):
        """Test that local imports preserve full module path."""
        # Create a local module
        local_dir = tmp_path / "mypackage"
        local_dir.mkdir()
        (local_dir / "__init__.py").write_text("")
        (local_dir / "mymodule.py").write_text("def foo(): pass")

        # Create file that imports local module
        test_file = tmp_path / "main.py"
        test_file.write_text("from mypackage.mymodule import foo\nimport mypackage")

        result = extract_imports(test_file, tmp_path)
        assert result["error"] is None

        # At least one import should be local with full path preserved
        local_imports = [imp for imp in result["imports"] if imp["type"] == "local"]
        # Note: mypackage should be found as local module
        assert len(local_imports) >= 1, (
            f"Expected local imports, got: {result['imports']}"
        )
        # Local imports should have 'path' key
        for imp in local_imports:
            assert "path" in imp

    def test_extract_external_import(self):
        """Test that external imports are collapsed to top-level."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write("import requests\nfrom flask import Flask\n")
            temp_path = Path(f.name)

        try:
            result = extract_imports(temp_path, Path("/tmp"))
            assert result["error"] is None
            external_imports = [
                imp for imp in result["imports"] if imp["type"] == "external"
            ]
            assert len(external_imports) == 2
            # Top-level package should be collapsed
            packages = {imp["package"] for imp in external_imports}
            assert "requests" in packages
            assert "flask" in packages
        finally:
            temp_path.unlink()


class TestDetectFrameworkHints:
    """Test detect_framework_hints function."""

    def test_detect_pyproject(self, tmp_path):
        """Test detection of pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.poetry]\nname = 'test'\n[tool.ruff]\n"
        )

        hints = detect_framework_hints(tmp_path)
        assert hints["python"]["has_pyproject"] is True
        assert "poetry" in hints["frameworks"]
        assert "ruff" in hints["tools"]

    def test_detect_requirements(self, tmp_path):
        """Test detection of requirements.txt frameworks."""
        (tmp_path / "requirements.txt").write_text(
            "flask==2.0.0\npydantic>=1.0\nnumpy\n"
        )

        hints = detect_framework_hints(tmp_path)
        assert hints["python"]["has_requirements"] is True
        assert "flask" in hints["frameworks"]
        assert "pydantic" in hints["frameworks"]
        assert "numpy" in hints["tools"]

    def test_detect_uv_lock(self, tmp_path):
        """Test detection of uv.lock."""
        (tmp_path / "uv.lock").write_text("lock file content")

        hints = detect_framework_hints(tmp_path)
        assert hints["python"]["has_uv_lock"] is True
        assert "uv" in hints["tools"]

    def test_detect_package_json(self, tmp_path):
        """Test detection of package.json frameworks."""
        (tmp_path / "package.json").write_text(
            '{"dependencies": {"react": "^18.0"}, "devDependencies": {"typescript": "^5.0"}}'
        )

        hints = detect_framework_hints(tmp_path)
        assert hints["javascript"]["has_package_json"] is True
        assert "react" in hints["frameworks"]
        assert "typescript" in hints["tools"]

    def test_no_manifests(self, tmp_path):
        """Test when no manifests exist."""
        hints = detect_framework_hints(tmp_path)
        assert hints["python"] == {}
        assert hints["javascript"] == {}
        assert hints["frameworks"] == []
        assert hints["tools"] == []


class TestScanProject:
    """Test scan_project integration."""

    def test_scan_project_structure(self, tmp_path):
        """Test that scan_project returns expected structure."""
        # Create minimal project structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("import os\nprint('hello')")
        (tmp_path / "README.md").write_text("# Test")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")

        result = scan_project(tmp_path)

        # Check top-level keys
        assert "version" in result
        assert "generated" in result
        assert "project_root" in result
        assert "summary" in result
        assert "files" in result
        assert "importMap" in result
        assert "frameworks" in result

        # Check summary
        assert result["summary"]["total_files"] >= 3
        assert "python" in result["summary"]["categories"]
        assert "documentation" in result["summary"]["categories"]
        assert "config" in result["summary"]["categories"]

        # Check importMap has our Python file
        python_files = result["importMap"]["python_files"]
        assert any("main.py" in path for path in python_files)

    def test_scan_project_exclusions(self, tmp_path):
        """Test that excluded directories are not scanned."""
        # Create excluded directories
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git config")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "module.pyc").write_text("cache")
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("venv file")

        # Create included file
        (tmp_path / "main.py").write_text("print('hello')")

        result = scan_project(tmp_path)

        # Excluded files should not appear
        all_paths = []
        for category_files in result["files"].values():
            all_paths.extend(f["path"] for f in category_files)

        assert not any(".git" in p for p in all_paths)
        assert not any("__pycache__" in p for p in all_paths)
        assert not any(".venv" in p for p in all_paths)
        assert any("main.py" in p for p in all_paths)

    def test_scan_project_deterministic(self, tmp_path):
        """Test that scan_project is deterministic."""
        # Create project structure
        (tmp_path / "a.py").write_text("import os")
        (tmp_path / "b.py").write_text("import sys")
        (tmp_path / "README.md").write_text("# Test")

        result1 = scan_project(tmp_path)
        result2 = scan_project(tmp_path)

        # Remove timestamp for comparison
        del result1["generated"]
        del result2["generated"]

        assert result1 == result2

    def test_scan_project_fingerprints(self, tmp_path):
        """Test that files have SHA256 fingerprints."""
        (tmp_path / "test.py").write_text("print('hello')")

        result = scan_project(tmp_path)

        python_files = result["files"].get("python", [])
        assert len(python_files) == 1
        assert "sha256" in python_files[0]
        assert len(python_files[0]["sha256"]) == 64  # SHA256 hex length
        assert "size" in python_files[0]


class TestGenerateReport:
    """Test generate_report function."""

    def test_report_contains_summary(self, tmp_path):
        """Test that report contains summary information."""
        project_map = {
            "generated": "2026-01-01T00:00:00Z",
            "project_root": "/tmp/test",
            "summary": {
                "total_files": 10,
                "total_size_bytes": 1024,
                "categories": {"python": 5, "documentation": 3, "config": 2},
            },
            "frameworks": {
                "frameworks": ["flask"],
                "tools": ["pytest"],
                "python": {},
                "javascript": {},
            },
            "importMap": {"python_files": {}},
            "parse_errors": [],
        }

        report = generate_report(project_map)

        assert "# Project Scanner Report" in report
        assert "Total files: 10" in report
        assert "python: 5" in report
        assert "flask" in report
        assert "pytest" in report

    def test_report_with_parse_errors(self):
        """Test that report includes parse errors."""
        project_map = {
            "generated": "2026-01-01T00:00:00Z",
            "project_root": "/tmp/test",
            "summary": {"total_files": 1, "total_size_bytes": 100, "categories": {}},
            "frameworks": {
                "frameworks": [],
                "tools": [],
                "python": {},
                "javascript": {},
            },
            "importMap": {"python_files": {}},
            "parse_errors": [
                "file1.py: SyntaxError: invalid syntax",
                "file2.py: SyntaxError: EOF",
            ],
        }

        report = generate_report(project_map)

        assert "Parse Errors" in report
        assert "SyntaxError" in report
        assert "file1.py" in report


class TestScanProjectRealProject:
    """Integration tests scanning the actual project."""

    @pytest.mark.slow
    def test_scan_current_project(self):
        """Test scanning the current project (orquestador_de_agentes).

        Marked as slow because it scans the entire project tree.
        Run with: pytest -m slow
        """
        from runtime.project_root import resolve_project_root

        project_root = resolve_project_root()
        result = scan_project(project_root)

        # Should find many files
        assert result["summary"]["total_files"] > 100
        assert "python" in result["summary"]["categories"]
        assert result["summary"]["categories"]["python"] > 50

        # Should have importMap entries
        assert len(result["importMap"]["python_files"]) > 50

        # Should be deterministic (run twice)
        result2 = scan_project(project_root)
        del result["generated"]
        del result2["generated"]
        assert result == result2
