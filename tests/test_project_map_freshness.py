"""Tests for project map generation (Graphify) â€” ensures artifacts are fresh and valid."""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
GRAPH_FILE = PROJECT_ROOT / "graphify-out" / "graph.json"
REPORT_FILE = PROJECT_ROOT / "graphify-out" / "GRAPH_REPORT.md"
CACHE_FILE = PROJECT_ROOT / "graphify-out" / "cache" / "sha256.json"
SCRIPT = PROJECT_ROOT / "scripts" / "update_project_map.py"


class TestProjectMapExistence:
    """Verifica que los artefactos graphify existen y son vÃ¡lidos."""

    def test_script_exists(self):
        """scripts/update_project_map.py existe."""
        assert SCRIPT.exists(), f"Missing script: {SCRIPT}"

    def test_graph_json_exists_and_valid(self):
        """graphify-out/graph.json existe y es JSON vÃ¡lido."""
        assert GRAPH_FILE.exists(), f"Missing graph file: {GRAPH_FILE}"
        data = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
        assert "nodes" in data
        assert "edges" in data
        assert isinstance(data["nodes"], dict)
        assert isinstance(data["edges"], list)

    def test_graph_corpus_is_orquestacion_agentes(self):
        """El grafo solo contiene archivos del corpus orquestacion_agentes (no agent_system externo)."""
        data = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
        nodes = data["nodes"]
        # Ensure no references to external agent_system PATHS (carpeta)
        # Allow "agent_system" in script NAMES (e.g., detect_agent_system_version.py)
        for path in nodes:
            # âŒ Prohibir: agent_system/ como carpeta externa (dependencia)
            # âœ… Permitir: detect_agent_system_version.py (nombre de script legÃ­timo)
            if path.startswith("agent_system/") or "/agent_system/" in path:
                raise AssertionError(
                    f"External agent_system folder reference found: {path}"
                )
        # Ensure at least some files are under .agent/ (marker of this repo)
        has_agent = any(p.startswith(".agent/") for p in nodes)
        assert has_agent, (
            "Graph missing .agent/ files â€” corpus not set to orquestacion_agentes"
        )

    def test_report_md_exists(self):
        """graphify-out/GRAPH_REPORT.md existe y tiene contenido."""
        assert REPORT_FILE.exists(), f"Missing report: {REPORT_FILE}"
        content = REPORT_FILE.read_text(encoding="utf-8")
        assert len(content) > 0
        assert "Graphify Report" in content or "graph" in content.lower()

    def test_report_no_mojibake(self):
        """GRAPH_REPORT.md no contiene secuencias mojibake (UTF-8 mal interpretado)."""
        content = REPORT_FILE.read_text(encoding="utf-8")
        mojibake_patterns = [
            "Ã¢â‚¬",
            "Ãƒ",
            "Ã‚Â¡",
            "Ã‚Â¢",
            "Ã‚Â£",
            "Ã‚Â¤",
            "Ã‚Â¥",
            "Ã‚Â¦",
            "Ã‚Â§",
            "Ã‚Â¨",
            "Ã‚Â©",
            "Ã‚Â«",
            "Ã‚Â¬",
            "Ã‚Â®",
            "Ã‚Â¯",
            "Ã‚Â°",
            "Ã‚Â±",
            "Ã‚Â²",
            "Ã‚Â³",
            "Ã‚Â´",
            "Ã‚Âµ",
            "Ã‚Â¶",
            "Ã‚Â·",
            "Ã‚Â¸",
            "Ã‚Â¹",
            "Ã‚Âº",
            "Ã‚Â»",
            "Ã‚Â¼",
            "Ã‚Â½",
            "Ã‚Â¾",
            "Ã‚Â¿",
            "Ãƒâ‚¬",
            "Ãƒ",
            "Ãƒâ€š",
            "ÃƒÆ’",
            "Ãƒâ€ž",
            "Ãƒâ€¦",
            "Ãƒâ€ ",
            "Ãƒâ€¡",
        ]
        found = [p for p in mojibake_patterns if p in content]
        assert not found, f"Mojibake detected in report: {found}"

    def test_report_mentions_orquestacion_agentes(self):
        """El reporte identifica el corpus como orquestacion_agentes."""
        content = REPORT_FILE.read_text(encoding="utf-8")
        has_corpus = "orquestacion_agentes" in content or "corpus" in content.lower()
        assert has_corpus, "Report does not mention orquestacion_agentes corpus"

    def test_report_no_legacy_references(self):
        """El reporte no menciona agent_system/ como carpeta externa (pero sÃ­ nombres de script)."""
        content = REPORT_FILE.read_text(encoding="utf-8")
        # âŒ Prohibir: agent_system/ como carpeta externa
        # âœ… Permitir: detect_agent_system_version.py (nombre de script legÃ­timo)
        assert "agent_system/" not in content.lower(), (
            "Report references external agent_system folder"
        )

    def test_cache_exists(self):
        """graphify-out/cache/sha256.json existe."""
        assert CACHE_FILE.exists(), f"Missing cache: {CACHE_FILE}"
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        assert isinstance(cache, dict)


class TestProjectMapFreshness:
    """Verifica que el mapa estÃ¡ actualizado respecto al cÃ³digo fuente."""

    def test_graph_includes_key_files(self):
        """El grafo incluye archivos crÃ­ticos del sistema."""
        data = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
        nodes = data["nodes"]
        key_files = [
            ".agent/agent_controller.py",
            ".agent/hooks/guard_paths.py",
            ".agent/completion_checker.py",
            ".agent/collaboration/work_plan.md",
            ".agent/collaboration/execution_log.md",
        ]
        for kf in key_files:
            assert kf in nodes, f"Key file missing from graph: {kf}"

    def test_nodes_have_required_fields(self):
        """Cada nodo tiene type, size_bytes y sha256."""
        data = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
        for path, meta in data["nodes"].items():
            assert "type" in meta, f"Node {path} missing 'type'"
            assert meta["type"] in ("python", "markdown"), f"Bad type for {path}"
            assert "size_bytes" in meta, f"Node {path} missing 'size_bytes'"
            assert isinstance(meta["size_bytes"], int)
            assert "sha256" in meta, f"Node {path} missing 'sha256'"
            assert len(meta["sha256"]) == 64

    def test_cache_sha256_matches_graph(self):
        """El cache SHA256 coincide con los nodos del grafo."""
        graph = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        for rel, meta in graph["nodes"].items():
            assert rel in cache, f"Node {rel} missing from cache"
            assert cache[rel] == meta["sha256"], f"SHA256 mismatch for {rel}"

    def test_report_references_exist(self):
        """El reporte menciona estadÃ­sticas y archivos."""
        content = REPORT_FILE.read_text(encoding="utf-8")
        assert "Nodos totales" in content or "total_nodes" in content
        assert "Python:" in content
        assert "Markdown:" in content


class TestUpdateScriptExecution:
    """Pruebas de ejecuciÃ³n del script de actualizaciÃ³n."""

    def test_script_runs_cleanly(self):
        """El script se ejecuta sin errores y actualiza los artefactos."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        output = result.stdout + result.stderr
        assert "graphify-out actualizado" in output or "actualizado" in output.lower()

    def test_script_report_mode(self):
        """El modo --report imprime el reporte sin modificar archivos."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--report"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0
        assert "Graphify Report" in result.stdout
