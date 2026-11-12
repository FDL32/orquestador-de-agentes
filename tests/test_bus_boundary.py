from __future__ import annotations

import ast
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUS_DIR = PROJECT_ROOT / "bus"
ALLOWED_SCRIPTS_IMPORTS = {
    # WOT-2026-162i/162k: bus/supervisor.py::_materialize_ticket_projection
    # (reproyector, gate g-2a) importa check_backlog_contract de forma perezosa
    # en l.953 para _ticket_has_row; ese import es load-bearing (fail-open en
    # el call-site). Sin ciclo/dependencia inversa: scripts.check_backlog_contract
    # solo importa stdlib + bus.state_machine (hoja stdlib), sin ciclo hacia bus/.
    "scripts.check_backlog_contract",
    "scripts.discover_skills",
    # WOT-2026-098b/113a: review_bridge.py invoca el gate
    # role_models.BUILDER != role_models.REVISOR justo antes de la revision de
    # la Capa 1.5 -- el propio script declara ese call-site como su sitio de
    # invocacion NATURAL (scripts/check_role_models_distinct.py docstring).
    # Sin dependencia inversa: solo importa stdlib + agents_config.
    "scripts.check_role_models_distinct",
}


def _collect_scripts_imports(path: Path) -> set[str]:
    """Collect scripts imports from a Python file via AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "scripts" or node.module.startswith("scripts.")
            ):
                imports.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "scripts" or alias.name.startswith("scripts."):
                    imports.add(alias.name)

    return imports


def _find_scripts_imports_in_bus() -> dict[Path, set[str]]:
    """Return bus files that import from scripts."""
    imports_by_file: dict[Path, set[str]] = {}

    for path in BUS_DIR.rglob("*.py"):
        imports = _collect_scripts_imports(path)
        if imports:
            imports_by_file[path] = imports

    return imports_by_file


def test_bus_only_imports_allowed_scripts_seam() -> None:
    """bus/ may import scripts.discover_skills, but nothing else from scripts."""
    imports_by_file = _find_scripts_imports_in_bus()

    unexpected = {
        str(path): sorted(imports - ALLOWED_SCRIPTS_IMPORTS)
        for path, imports in imports_by_file.items()
        if imports - ALLOWED_SCRIPTS_IMPORTS
    }

    assert not unexpected, (
        "Unexpected scripts imports found in bus/: "
        f"{unexpected}. Allowed seam: {sorted(ALLOWED_SCRIPTS_IMPORTS)}"
    )


def test_bus_has_no_dynamic_scripts_imports() -> None:
    """bus/ does not load scripts.* dynamically via importlib or __import__."""
    dynamic_patterns = [
        r"importlib\.import_module\(['\"]scripts",
        r"__import__\(['\"]scripts",
    ]

    for path in BUS_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for pattern in dynamic_patterns:
            assert not re.search(pattern, source), (
                f"Dynamic scripts import found in {path}: pattern={pattern!r}"
            )
