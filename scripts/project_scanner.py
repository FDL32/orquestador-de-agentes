"""
Project Scanner - Deterministic project scanner with import map.

Builds a compact, token-efficient project-map.json with:
- File inventory with fingerprints (SHA256)
- Category buckets (python, markdown, config, etc.)
- Real Python importMap via ast.parse()
- Framework hints from manifests
- Exclusion filters for non-product noise

Usage:
    python scripts/project_scanner.py              # scan and emit project-map.json
    python scripts/project_scanner.py --dry-run    # print output without writing
    python scripts/project_scanner.py --report     # print human-readable report

Output:
    .agent/context/project-map.json
"""

import ast
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Fix encoding issues on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, UnicodeEncodeError):
        # Reconfigure may fail when stdout is redirected or not a text stream
        pass


# =============================================================================
# Path Resolution
# =============================================================================
try:
    from runtime.project_root import get_context_dir, resolve_project_root
except ImportError:
    resolve_project_root = None
    get_context_dir = None


def _project_root() -> Path:
    if resolve_project_root is not None:
        return resolve_project_root()
    return Path(__file__).resolve().parents[1]


def _context_dir() -> Path:
    if get_context_dir is not None:
        return get_context_dir()
    return _project_root() / ".agent" / "context"


class _LazyPath:
    def __init__(self, resolver):
        self._resolver = resolver

    def resolve(self) -> Path:
        return self._resolver()

    def __getattr__(self, name: str):
        return getattr(self.resolve(), name)

    def __truediv__(self, other):
        return self.resolve() / other

    def __fspath__(self) -> str:
        return str(self.resolve())

    def __str__(self) -> str:
        return str(self.resolve())

    def __repr__(self) -> str:
        return f"_LazyPath({self.resolve()!r})"


PROJECT_ROOT = _LazyPath(_project_root)
CONTEXT_DIR = _LazyPath(_context_dir)
OUTPUT_FILE = _LazyPath(lambda: _context_dir() / "project-map.json")

# =============================================================================
# Exclusion Filters
# =============================================================================

# Directories to exclude (noise, non-product, runtime artifacts)
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    ".eggs",
    "node_modules",
    "build",
    "dist",
    "*.egg-info",
    ".cache",
    ".uv-cache",
    "uv-cache",
    "graphify-out",
    "reviews",
    "review_packets",
}

# File patterns to exclude
EXCLUDE_FILE_PATTERNS = {
    "*.pyc",
    "*.pyo",
    "*.so",
    "*.dll",
    "*.exe",
    "*.whl",
    "*.tar.gz",
    "*.zip",
    "*.log",
    "*.lock",
    ".DS_Store",
    ".gitignore",
    ".gitattributes",
    "*.orig",
    "*.bak",
    "*.swp",
    "*.swo",
    "*~",
}

# Extensions to include (focus on product code and docs)
INCLUDE_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".sh",
    ".ps1",
    ".bat",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
}


def _matches_pattern(path: Path, patterns: set[str]) -> bool:
    """Check if path matches any glob pattern."""
    name = path.name
    for pattern in patterns:
        if pattern.startswith("*."):
            if name.endswith(pattern[1:]):
                return True
        elif pattern.endswith("*"):
            if name.startswith(pattern[:-1]):
                return True
        elif name == pattern:
            return True
    return False


def _is_excluded(path: Path, project_root: Path) -> bool:
    """Check if path should be excluded from scan."""
    # Check directory exclusions
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return True
        # Handle patterns like *.egg-info
        if part.endswith(".egg-info"):
            return True

    # Check specific path-based exclusions (relative to project root)
    try:
        rel_str = str(path.relative_to(project_root))
        # Exclude .agent runtime subdirectories (but not .agent/config or .agent/collaboration surfaces)
        if rel_str.startswith(".agent/runtime/tmp") or rel_str.startswith(
            ".agent\\runtime\\tmp"
        ):
            return True
        if "collaboration/archive" in rel_str or "collaboration\\archive" in rel_str:
            return True
        if "collaboration/_archive" in rel_str or "collaboration\\_archive" in rel_str:
            return True
        # Exclude external agent_system project
        if rel_str.startswith("agent_system") or rel_str.startswith("agent_system\\"):
            return True
    except ValueError:
        # Path not relative to project_root - skip relative checks
        pass

    # Check file pattern exclusions
    if _matches_pattern(path, EXCLUDE_FILE_PATTERNS):
        return True

    # Check extension whitelist
    return bool(path.suffix and path.suffix not in INCLUDE_EXTENSIONS)


def sha256_file(path: Path) -> str:
    """Compute SHA256 hash of file content."""
    h = hashlib.sha256()
    try:
        h.update(path.read_bytes())
        return h.hexdigest()
    except OSError:
        return "UNREADABLE"


def rel_path(path: Path, project_root: Path) -> str:
    """Get relative path as forward-slash string."""
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


# =============================================================================
# Category Buckets
# =============================================================================

CATEGORY_RULES = [
    # Source code
    (".py", "python"),
    (".js", "javascript"),
    (".ts", "typescript"),
    (".tsx", "typescript"),
    (".jsx", "javascript"),
    (".html", "markup"),
    (".css", "styles"),
    # Documentation
    (".md", "documentation"),
    (".txt", "documentation"),
    (".rst", "documentation"),
    # Configuration
    (".toml", "config"),
    (".yaml", "config"),
    (".yml", "config"),
    (".json", "config"),
    (".ini", "config"),
    (".cfg", "config"),
    # Scripts
    (".sh", "scripts"),
    (".ps1", "scripts"),
    (".bat", "scripts"),
]


def categorize_file(path: Path) -> str:
    """Categorize file by extension."""
    suffix = path.suffix.lower()
    for ext, category in CATEGORY_RULES:
        if suffix == ext:
            return category
    return "other"


# =============================================================================
# AST-based Import Extraction
# =============================================================================


def extract_imports(
    path: Path,
    project_root: Path,
    local_modules: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Extract Python imports via AST parsing.

    Before: Requires valid Python file path and project root.
    During: Parses file with ast.parse(), walks Import/ImportFrom nodes,
            resolves local modules to full paths, collapses stdlib/external.
    After: Returns dict with importMap entries and any parse errors.

    Args:
        local_modules: pre-computed map from _collect_local_modules(); computed
                       lazily if not provided (avoid passing None in hot loops).

    Returns:
        Dict with keys:
        - 'imports': list of import entries
        - 'error': SyntaxError message if parse failed, else None
    """
    result: dict[str, Any] = {"imports": [], "error": None}

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        result["error"] = f"SyntaxError: {e.msg} at line {e.lineno}"
        return result
    except (OSError, UnicodeDecodeError) as e:
        result["error"] = f"ReadError: {type(e).__name__}: {e}"
        return result

    if local_modules is None:
        local_modules = _collect_local_modules(project_root)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_entry = _classify_import(alias.name, local_modules, project_root)
                result["imports"].append(import_entry)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                full_name = f"{module}.{alias.name}" if module else alias.name
                import_entry = _classify_import(full_name, local_modules, project_root)
                result["imports"].append(import_entry)

    return result


def _collect_local_modules(project_root: Path) -> dict[str, str]:
    """
    Build a map of importable module names to their file paths.

    Before: Requires project root directory.
    During: Scans for .py files, computes module names from paths.
    After: Returns dict mapping module name (dotted) to relative file path.
    """
    local_modules: dict[str, str] = {}

    for py_file in project_root.rglob("*.py"):
        if _is_excluded(py_file, project_root):
            continue

        rel = rel_path(py_file, project_root)

        # Compute module name from path
        # e.g., "foo/bar/baz.py" -> "foo.bar.baz"
        # e.g., "foo/__init__.py" -> "foo"
        parts = list(py_file.relative_to(project_root).parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
            if not parts:
                continue
        else:
            parts[-1] = parts[-1][:-3]  # remove .py

        module_name = ".".join(parts)
        local_modules[module_name] = rel

    return local_modules


def _classify_import(
    import_name: str, local_modules: dict[str, str], project_root: Path
) -> dict[str, str]:
    """
    Classify an import as local, stdlib, or external.

    Before: Requires import name, local_modules map, and project root.
    During: Checks if import resolves to local file, stdlib, or external package.
    After: Returns import entry with type and path/top-level name.

    Strategy:
    - For local imports: preserve full module path
    - For stdlib/external: collapse to top-level package name
    """
    # Try to resolve as local module
    # Check progressively longer prefixes
    parts = import_name.split(".")

    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in local_modules:
            return {
                "name": import_name,
                "type": "local",
                "path": local_modules[candidate],
            }

    # Not local - check if stdlib or external
    top_level = parts[0]

    # Use sys.stdlib_module_names (Python 3.10+) for authoritative stdlib detection
    if top_level in sys.stdlib_module_names:
        return {"name": import_name, "type": "stdlib", "package": top_level}

    # External package
    return {"name": import_name, "type": "external", "package": top_level}


# =============================================================================
# Framework Hints Detection
# =============================================================================


def _detect_pyproject_hints(project_root: Path) -> tuple[dict, list, list]:
    """Detect hints from pyproject.toml."""
    python_hints = {}
    frameworks = []
    tools = []

    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return python_hints, frameworks, tools

    python_hints["has_pyproject"] = True
    content = pyproject.read_text(encoding="utf-8")

    if "poetry" in content:
        frameworks.append("poetry")
    if "setuptools" in content or "[build-system]" in content:
        tools.append("setuptools")
    if "pytest" in content:
        tools.append("pytest")
    if "ruff" in content:
        tools.append("ruff")
    if "mypy" in content:
        tools.append("mypy")
    if "uv" in content:
        tools.append("uv")

    return python_hints, frameworks, tools


def _detect_requirements_hints(project_root: Path) -> tuple[dict, list, list]:
    """Detect hints from requirements.txt."""
    python_hints = {}
    frameworks = []
    tools = []

    requirements = project_root / "requirements.txt"
    if not requirements.exists():
        return python_hints, frameworks, tools

    python_hints["has_requirements"] = True
    content = requirements.read_text(encoding="utf-8").lower()

    if "flask" in content:
        frameworks.append("flask")
    if "django" in content:
        frameworks.append("django")
    if "fastapi" in content:
        frameworks.append("fastapi")
    if "pydantic" in content:
        frameworks.append("pydantic")
    if "numpy" in content:
        tools.append("numpy")
    if "pandas" in content:
        tools.append("pandas")

    return python_hints, frameworks, tools


def _detect_package_json_hints(project_root: Path) -> tuple[dict, list, list]:
    """Detect hints from package.json."""
    js_hints = {}
    frameworks = []
    tools = []

    package_json = project_root / "package.json"
    if not package_json.exists():
        return js_hints, frameworks, tools

    try:
        js_hints["has_package_json"] = True
        pkg_data = json.loads(package_json.read_text(encoding="utf-8"))
        deps = pkg_data.get("dependencies", {})
        dev_deps = pkg_data.get("devDependencies", {})

        if "react" in deps:
            frameworks.append("react")
        if "vue" in deps:
            frameworks.append("vue")
        if "typescript" in deps or "typescript" in dev_deps:
            tools.append("typescript")
        if "webpack" in dev_deps:
            tools.append("webpack")
        if "vite" in dev_deps:
            tools.append("vite")
    except (json.JSONDecodeError, OSError):
        pass

    return js_hints, frameworks, tools


def detect_framework_hints(project_root: Path) -> dict[str, Any]:
    """
    Detect framework hints from common manifests.

    Before: Requires project root directory.
    During: Reads pyproject.toml, requirements.txt, package.json, etc.
    After: Returns dict with detected frameworks and metadata.
    """
    frameworks = []
    tools = []

    # Check pyproject.toml
    py_python, py_fw, py_tools = _detect_pyproject_hints(project_root)
    frameworks.extend(py_fw)
    tools.extend(py_tools)

    # Check requirements.txt
    req_python, req_fw, req_tools = _detect_requirements_hints(project_root)
    frameworks.extend(req_fw)
    tools.extend(req_tools)

    # Check uv.lock
    uv_lock = project_root / "uv.lock"
    python_hints = {**py_python, **req_python}
    if uv_lock.exists():
        python_hints["has_uv_lock"] = True
        tools.append("uv")

    # Check package.json
    pkg_js, pkg_fw, pkg_tools = _detect_package_json_hints(project_root)
    frameworks.extend(pkg_fw)
    tools.extend(pkg_tools)

    # Check for Makefile
    if (project_root / "Makefile").exists():
        tools.append("make")

    # Check for Dockerfile
    if (project_root / "Dockerfile").exists():
        tools.append("docker")

    # Remove duplicates
    frameworks = list(set(frameworks))
    tools = list(set(tools))

    return {
        "python": python_hints,
        "javascript": pkg_js,
        "frameworks": frameworks,
        "tools": tools,
    }


# =============================================================================
# Scanner Main Function
# =============================================================================


def scan_project(project_root: Path | None = None) -> dict[str, Any]:
    """
    Scan project and build project-map.json.

    Before: Requires project root (defaults to current project).
    During: Collects files, computes fingerprints, extracts imports,
            detects frameworks, builds categorized inventory.
    After: Returns structured project map dict.

    Output structure:
    {
        "version": "1.0",
        "generated": "ISO timestamp",
        "project_root": "absolute path",
        "summary": {
            "total_files": int,
            "total_size_bytes": int,
            "categories": {category: count, ...}
        },
        "files": {
            "category": [
                {"path": str, "size": int, "sha256": str},
                ...
            ],
            ...
        },
        "importMap": {
            "python_files": {
                "relative/path.py": {
                    "imports": [...],
                    "error": str | null
                },
                ...
            }
        },
        "frameworks": {
            "frameworks": [...],
            "tools": [...],
            "python": {...},
            "javascript": {...}
        }
    }
    """
    if project_root is None:
        project_root = _project_root()

    project_root = project_root.resolve()

    # Collect files
    files_by_category: dict[str, list[dict[str, Any]]] = {}
    import_map: dict[str, dict[str, Any]] = {}
    total_size = 0
    parse_errors: list[str] = []

    # Pre-compute local modules once (O(n) instead of O(n²))
    local_modules = _collect_local_modules(project_root)

    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        if _is_excluded(path, project_root):
            continue

        rel = rel_path(path, project_root)
        size = path.stat().st_size
        sha = sha256_file(path)
        category = categorize_file(path)

        total_size += size

        # Add to category bucket
        if category not in files_by_category:
            files_by_category[category] = []
        files_by_category[category].append({"path": rel, "size": size, "sha256": sha})

        # Extract imports for Python files
        if path.suffix == ".py":
            import_result = extract_imports(path, project_root, local_modules)
            if import_result["imports"] or import_result["error"]:
                import_map[rel] = {
                    "imports": import_result["imports"],
                    "error": import_result["error"],
                }
                if import_result["error"]:
                    parse_errors.append(f"{rel}: {import_result['error']}")

    # Detect framework hints
    framework_hints = detect_framework_hints(project_root)

    # Build summary
    summary = {
        "total_files": sum(len(files) for files in files_by_category.values()),
        "total_size_bytes": total_size,
        "categories": {cat: len(files) for cat, files in files_by_category.items()},
    }

    # Build project map
    project_map = {
        "version": "1.0",
        "generated": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "summary": summary,
        "files": files_by_category,
        "importMap": {"python_files": import_map},
        "frameworks": framework_hints,
        "parse_errors": parse_errors,
    }

    return project_map


def generate_report(project_map: dict[str, Any]) -> str:
    """Generate human-readable report from project map."""
    summary = project_map["summary"]
    frameworks = project_map["frameworks"]
    parse_errors = project_map.get("parse_errors", [])

    lines = [
        "# Project Scanner Report",
        f"Generated: {project_map['generated']}",
        f"Project Root: {project_map['project_root']}",
        "",
        "## Summary",
        f"- Total files: {summary['total_files']}",
        f"- Total size: {summary['total_size_bytes'] / 1024:.1f} KB",
        "",
        "## Files by Category",
    ]

    for category, count in sorted(summary["categories"].items()):
        lines.append(f"- {category}: {count}")

    lines.extend(
        [
            "",
            "## Frameworks Detected",
            f"- Frameworks: {', '.join(frameworks['frameworks']) or 'None'}",
            f"- Tools: {', '.join(frameworks['tools']) or 'None'}",
        ]
    )

    if parse_errors:
        lines.extend(
            [
                "",
                "## Parse Errors",
                f"- {len(parse_errors)} files with SyntaxError:",
            ]
        )
        # Parse errors section
        if parse_errors:
            lines.extend([f"  - {err}" for err in parse_errors[:10]])
            if len(parse_errors) > 10:
                lines.append(f"  ... and {len(parse_errors) - 10} more")

    return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================


def main() -> int:
    args = sys.argv[1:]

    dry_run = "--dry-run" in args
    report_only = "--report" in args

    project_root = _project_root()
    context_dir = _context_dir()

    # Ensure context directory exists
    context_dir.mkdir(parents=True, exist_ok=True)

    # Scan project
    print(f"Scanning project: {project_root}")
    project_map = scan_project(project_root)

    if report_only:
        print(generate_report(project_map))
        return 0

    # Serialize output
    output_json = json.dumps(project_map, indent=2, ensure_ascii=False)

    if dry_run:
        print(output_json)
        return 0

    # Write output
    output_path = context_dir / "project-map.json"
    output_path.write_text(output_json, encoding="utf-8")

    print(f"[OK] Project map written to: {output_path}")
    print(f"     Total files: {project_map['summary']['total_files']}")
    print(
        f"     Python files with imports: {len(project_map['importMap']['python_files'])}"
    )
    print(f"     Frameworks detected: {len(project_map['frameworks']['frameworks'])}")

    if project_map.get("parse_errors"):
        print(f"     Parse errors: {len(project_map['parse_errors'])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
