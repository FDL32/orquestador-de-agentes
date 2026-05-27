"""
Extractor determinista de grafo de conocimiento para orquestador_de_agentes.

Construye graphify-out/graph.json sin usar LLM:
  - Archivos .py: extracciÃ³n AST (imports, clases, funciones)
  - Archivos .md: extracciÃ³n de links Markdown [text](path)

Uso:
    python scripts/update_project_map.py            # construir/actualizar
    python scripts/update_project_map.py --report   # solo mostrar reporte
    python scripts/update_project_map.py --update   # solo procesar archivos modificados
"""

import ast
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


sys.stdout.reconfigure(encoding="utf-8")


# Bootstrap: project root must be on sys.path before importing runtime.project_root.
_PROJECT_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_BOOTSTRAP))

# WP-2026-122 / WP-2026-155: Centralized path resolution via runtime.project_root
from runtime.project_root import resolve_project_root  # noqa: E402


_PROJECT_ROOT = resolve_project_root()


def _project_root() -> Path:
    """Return the resolved project root (cached for performance)."""
    return _PROJECT_ROOT


def _out_dir(project_root: Path) -> Path:
    return project_root / "graphify-out"


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
OUT_DIR = _LazyPath(lambda: _out_dir(_project_root()))
GRAPH_FILE = _LazyPath(lambda: _out_dir(_project_root()) / "graph.json")
CACHE_FILE = _LazyPath(lambda: _out_dir(_project_root()) / "cache" / "sha256.json")
REPORT_FILE = _LazyPath(lambda: _out_dir(_project_root()) / "GRAPH_REPORT.md")

# Extensiones a procesar
EXTENSIONS = {".py", ".md"}

# Directorios a ignorar
IGNORE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".venv",
    "venv",
    "graphify-out",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".tmp",
    "tmp_pytest_*",
    "agent_system",  # proyecto externo -- no mezclar
    "uv-cache",  # env dependencies -- not product code
    "_archive",  # plan/audit history -- internal state
    "review_packets",  # review packets -- internal state
    "reviews",  # review outputs -- internal state
    "sandbox",  # one-shot debug scripts -- not portable product
    "test_runtime",  # generated test session state -- not portable product
}

# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Utilidades
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: S110
            pass
    return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def collect_files(root: Path) -> list[Path]:
    result = []
    for p in root.rglob("*"):
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        if p.suffix in EXTENSIONS and p.is_file():
            result.append(p)
    return sorted(result)


def rel(path: Path) -> str:
    """Ruta relativa desde PROJECT_ROOT como string con forward slashes."""
    project_root = _project_root()
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# ExtracciÃ³n Python (AST)
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€


def extract_py_links(path: Path) -> list[str]:
    """Extrae imports y referencias de un archivo .py."""
    links = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                links.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                links.append(node.module.split(".")[0])
    except Exception:  # noqa: S110
        pass
    return links


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# ExtracciÃ³n Markdown (links)
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

MD_LINK_RE = re.compile(r"\[.*?\]\((?!https?://)([^)]+)\)")


def extract_md_links(path: Path) -> list[str]:
    """Extrae enlaces Markdown relativos (excluye URLs externas)."""
    links = []
    try:
        text = path.read_text(encoding="utf-8")
        for m in MD_LINK_RE.finditer(text):
            target = m.group(1)
            # Ignorar enlaces vacÃ­os o con solo fragmento
            if target and not target.startswith("#"):
                links.append(target)
    except Exception:  # noqa: S110
        pass
    return links


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# ConstrucciÃ³n del grafo
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€


def build_graph() -> tuple[dict, dict]:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    project_root = _project_root()
    files = collect_files(project_root)
    current_hashes: dict[str, str] = {}

    for f in files:
        r = rel(f)
        h = sha256(f)
        current_hashes[r] = h

        node_type = "file"
        if f.suffix == ".py":
            node_type = "python"
        elif f.suffix == ".md":
            node_type = "markdown"

        nodes[r] = {
            "type": node_type,
            "size_bytes": f.stat().st_size,
            "sha256": h,
        }

        # Extraer referencias
        if f.suffix == ".py":
            refs = extract_py_links(f)
        elif f.suffix == ".md":
            refs = extract_md_links(f)
        else:
            refs = []

        # Convertir referencias a rutas relativas si es posible
        for ref in refs:
            # Si el target estÃ¡ dentro del proyecto, normalizar
            target_path = project_root / ref
            try:
                if target_path.exists() and target_path.is_file():
                    target_rel = rel(target_path)
                    edges.append(
                        {"source": r, "target": target_rel, "type": "reference"}
                    )
            except Exception:  # noqa: S110
                # Fuera del project_root -- omitir
                pass

    return {"nodes": nodes, "edges": edges}, current_hashes


def generate_report(graph: dict) -> str:
    """Genera GRAPH_REPORT.md legible."""
    nodes = graph["nodes"]
    edges = graph["edges"]

    stats = {
        "total_nodes": len(nodes),
        "py_files": sum(1 for n in nodes.values() if n["type"] == "python"),
        "md_files": sum(1 for n in nodes.values() if n["type"] == "markdown"),
        "total_edges": len(edges),
    }

    # Construir lista de archivos
    file_lines = []
    for path, meta in sorted(nodes.items()):
        size_kb = meta["size_bytes"] / 1024
        file_lines.append(f"  - `{path}` ({meta['type']}, {size_kb:.1f} KB)")

    # Construir enlaces
    edge_lines = []
    edge_counts = defaultdict(int)
    for e in edges:
        edge_counts[f"{e['source']} -> {e['target']}"] += 1

    top_edges = sorted(edge_counts.items(), key=lambda kv: -kv[1])[:50]
    for pair, count in top_edges:
        edge_lines.append(f"  - `{pair}` ({count}x)")

    report = f"""# Graphify Report â€" {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

**Corpus:** orquestador_de_agentes

## EstadÃ­sticas

- Nodos totales: {stats["total_nodes"]}
  - Python: {stats["py_files"]}
  - Markdown: {stats["md_files"]}
- Enlaces (referencias): {stats["total_edges"]}

## Archivos del Proyecto

{chr(10).join(file_lines[:200])}

## Top 50 Enlaces (mÃ¡s referenciados)

{chr(10).join(edge_lines[:50])}

## Uso

Graphify se ejecuta **manualmente** antes de:
  - Releases / tags
  - AuditorÃ­as de seguridad
  - Copias de la plantilla a nuevos proyectos
  - Revisiones de arquitectura importante

No es parte del Quality Gate diario. Ejecutar:

    python scripts/update_project_map.py
"""
    return report


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# CLI
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€


def main() -> int:
    args = sys.argv[1:]

    # Modo solo reporte
    if "--report" in args:
        if not REPORT_FILE.exists():
            print(
                "ERROR: graphify-out/GRAPH_REPORT.md no existe. Ejecuta sin --report primero."
            )
            return 1
        print(REPORT_FILE.read_text(encoding="utf-8"))
        return 0

    # Modo solo actualizaciÃ³n incremental
    only_update = "--update" in args

    # Cargar cache anterior
    old_hashes = load_json(CACHE_FILE)

    # Construir grafo completo
    graph, current_hashes = build_graph()

    # Detectar cambios si es incremental
    if only_update and old_hashes:
        changed = [rel for rel, h in current_hashes.items() if old_hashes.get(rel) != h]
        if not changed:
            print(
                "Ningun archivo modificado desde ultima generacion. Graphify actualizado."
            )
            return 0
        print(f"Archivos modificados: {len(changed)}. Regenerando grafo completo...")

    # Guardar grafo
    save_json(GRAPH_FILE, graph)
    save_json(CACHE_FILE, current_hashes)

    # Generar reporte
    report = generate_report(graph)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report, encoding="utf-8")

    print(f"[OK] graphify-out actualizado: {GRAPH_FILE.relative_to(PROJECT_ROOT)}")
    print(f"[OK] Reporte generado: {REPORT_FILE.relative_to(PROJECT_ROOT)}")
    print(f"[OK] Cache de hashes: {CACHE_FILE.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
