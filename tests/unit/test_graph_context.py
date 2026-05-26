"""
Unit tests for scripts/graph_context.py.

Tests cover:
- Graph loading and error handling
- Work plan parsing (ticket ID, files likely touched)
- Neighbor extraction from graph edges
- File categorization by type
- Context generation with line limits
- Destination project context generation
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.graph_context import (
    categorize_files,
    extract_active_ticket_id,
    extract_files_likely_touched,
    format_file_size,
    generate_context_for_destination,
    generate_project_context,
    get_immediate_neighbors,
    load_graph,
    load_graph_report,
    load_work_plan,
)


@pytest.fixture
def temp_graphify_dir(tmp_path: Path) -> Path:
    """Create a temporary graphify-out directory with test data."""
    graphify_dir = tmp_path / "graphify-out"
    graphify_dir.mkdir()

    graph_data = {
        "nodes": {
            "file1.py": {"type": "python", "size_bytes": 1024},
            "file2.py": {"type": "python", "size_bytes": 2048},
            "doc1.md": {"type": "markdown", "size_bytes": 512},
            "doc2.md": {"type": "markdown", "size_bytes": 768},
            "other.txt": {"type": "text", "size_bytes": 256},
        },
        "edges": [
            {"source": "file1.py", "target": "doc1.md", "type": "reference"},
            {"source": "file2.py", "target": "file1.py", "type": "import"},
            {"source": "doc1.md", "target": "doc2.md", "type": "link"},
        ],
    }

    graph_path = graphify_dir / "graph.json"
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f)

    report_content = "# Graphify Report\n\n- Total nodes: 5\n"
    report_path = graphify_dir / "GRAPH_REPORT.md"
    report_path.write_text(report_content, encoding="utf-8")

    return graphify_dir


@pytest.fixture
def temp_collaboration_dir(tmp_path: Path) -> Path:
    """Create a temporary collaboration directory with work_plan.md."""
    collab_dir = tmp_path / ".agent" / "collaboration"
    collab_dir.mkdir(parents=True)

    work_plan_content = """# Work Plan - WP-2026-147

## Metadata
- **ID:** WP-2026-147
- **Estado:** APPROVED
- **deliverable_type:** code

## Files Likely Touched
- file1.py
- doc1.md
"""
    work_plan_path = collab_dir / "work_plan.md"
    work_plan_path.write_text(work_plan_content, encoding="utf-8")

    return collab_dir


@pytest.fixture
def temp_project_root(
    tmp_path: Path,
    temp_graphify_dir: Path,
    temp_collaboration_dir: Path,
) -> Path:
    """Create a complete temporary project structure."""
    temp_graphify_dir.rename(tmp_path / "graphify-out")
    temp_collaboration_dir.rename(tmp_path / ".agent" / "collaboration")
    return tmp_path


class TestLoadGraph:
    """Tests for load_graph function."""

    def test_load_graph_success(self, temp_project_root: Path) -> None:
        """Test successful graph loading."""
        with patch("scripts.graph_context.get_graphify_dir") as mock_get_dir:
            mock_get_dir.return_value = temp_project_root / "graphify-out"
            graph = load_graph()
            assert "nodes" in graph
            assert "edges" in graph
            assert len(graph["nodes"]) == 5

    def test_load_graph_file_not_found(self) -> None:
        """Test FileNotFoundError when graph.json missing."""
        with patch("scripts.graph_context.get_graphify_dir") as mock_get_dir:
            mock_get_dir.return_value = Path("/nonexistent")
            with pytest.raises(FileNotFoundError, match="Graph file not found"):
                load_graph()

    def test_load_graph_invalid_json(self, tmp_path: Path) -> None:
        """Test ValueError for malformed JSON."""
        graphify_dir = tmp_path / "graphify-out"
        graphify_dir.mkdir()
        graph_path = graphify_dir / "graph.json"
        graph_path.write_text("invalid json {", encoding="utf-8")

        with patch("scripts.graph_context.get_graphify_dir") as mock_get_dir:
            mock_get_dir.return_value = graphify_dir
            with pytest.raises(ValueError, match="Invalid JSON"):
                load_graph()


class TestLoadGraphReport:
    """Tests for load_graph_report function."""

    def test_load_report_success(self, temp_project_root: Path) -> None:
        """Test successful report loading."""
        with patch("scripts.graph_context.get_graphify_dir") as mock_get_dir:
            mock_get_dir.return_value = temp_project_root / "graphify-out"
            report = load_graph_report()
            assert "# Graphify Report" in report

    def test_load_report_file_not_found(self) -> None:
        """Test FileNotFoundError when GRAPH_REPORT.md missing."""
        with patch("scripts.graph_context.get_graphify_dir") as mock_get_dir:
            mock_get_dir.return_value = Path("/nonexistent")
            with pytest.raises(FileNotFoundError, match="Graph report not found"):
                load_graph_report()


class TestLoadWorkPlan:
    """Tests for load_work_plan function."""

    def test_load_work_plan_success(self, temp_project_root: Path) -> None:
        """Test successful work plan loading."""
        with patch("scripts.graph_context.get_collaboration_dir") as mock_get_dir:
            mock_get_dir.return_value = temp_project_root / ".agent" / "collaboration"
            content = load_work_plan()
            assert "WP-2026-147" in content

    def test_load_work_plan_file_not_found(self) -> None:
        """Test FileNotFoundError when work_plan.md missing."""
        with patch("scripts.graph_context.get_collaboration_dir") as mock_get_dir:
            mock_get_dir.return_value = Path("/nonexistent")
            with pytest.raises(FileNotFoundError, match="Work plan not found"):
                load_work_plan()


class TestExtractActiveTicketId:
    """Tests for extract_active_ticket_id function."""

    def test_extract_from_metadata(self) -> None:
        """Test extraction from Metadata section."""
        content = """# Work Plan
## Metadata
- **ID:** WP-2026-147
"""
        assert extract_active_ticket_id(content) == "WP-2026-147"

    def test_extract_from_title(self) -> None:
        """Test extraction from title."""
        content = "# Work Plan - WP-2026-148\n"
        assert extract_active_ticket_id(content) == "WP-2026-148"

    def test_no_ticket_found(self) -> None:
        """Test None when no ticket ID present."""
        content = "# Work Plan\nNo ticket here\n"
        assert extract_active_ticket_id(content) is None

    def test_empty_content(self) -> None:
        """Test empty content."""
        assert extract_active_ticket_id("") is None


class TestExtractFilesLikelyTouched:
    """Tests for extract_files_likely_touched function."""

    def test_extract_files(self) -> None:
        """Test file extraction from section."""
        content = """## Files Likely Touched
- file1.py
- file2.py
- doc1.md
"""
        files = extract_files_likely_touched(content)
        assert files == {"file1.py", "file2.py", "doc1.md"}

    def test_no_section(self) -> None:
        """Test empty set when section missing."""
        content = "## Other Section\n- something\n"
        assert extract_files_likely_touched(content) == set()

    def test_stop_at_next_section(self) -> None:
        """Test extraction stops at next section."""
        content = """## Files Likely Touched
- file1.py
## Other Section
- file2.py
"""
        files = extract_files_likely_touched(content)
        assert files == {"file1.py"}

    def test_empty_section(self) -> None:
        """Test empty section."""
        content = "## Files Likely Touched\n## Next Section\n"
        assert extract_files_likely_touched(content) == set()


class TestGetImmediateNeighbors:
    """Tests for get_immediate_neighbors function."""

    def test_find_neighbors(self) -> None:
        """Test neighbor extraction from edges."""
        graph = {
            "edges": [
                {"source": "A.py", "target": "B.py", "type": "import"},
                {"source": "B.py", "target": "C.py", "type": "import"},
            ]
        }
        neighbors = get_immediate_neighbors(graph, {"B.py"})
        assert neighbors == {"A.py", "C.py"}

    def test_no_neighbors(self) -> None:
        """Test no neighbors when no edges."""
        graph = {"edges": []}
        neighbors = get_immediate_neighbors(graph, {"A.py"})
        assert neighbors == set()

    def test_isolated_nodes(self) -> None:
        """Test nodes with no connections."""
        graph = {"edges": [{"source": "X.py", "target": "Y.py", "type": "link"}]}
        neighbors = get_immediate_neighbors(graph, {"A.py"})
        assert neighbors == set()

    def test_bidirectional_edges(self) -> None:
        """Test edges work in both directions."""
        graph = {
            "edges": [
                {"source": "A.py", "target": "B.py", "type": "link"},
            ]
        }
        neighbors_from_source = get_immediate_neighbors(graph, {"A.py"})
        neighbors_from_target = get_immediate_neighbors(graph, {"B.py"})
        assert neighbors_from_source == {"B.py"}
        assert neighbors_from_target == {"A.py"}


class TestCategorizeFiles:
    """Tests for categorize_files function."""

    def test_categorize_by_type(self) -> None:
        """Test file categorization."""
        nodes = {
            "a.py": {"type": "python"},
            "b.py": {"type": "python"},
            "c.md": {"type": "markdown"},
            "d.txt": {"type": "text"},
        }
        files = {"a.py", "b.py", "c.md", "d.txt"}
        categorized = categorize_files(nodes, files)

        assert len(categorized["python"]) == 2
        assert len(categorized["markdown"]) == 1
        assert len(categorized["other"]) == 1

    def test_missing_node_info(self) -> None:
        """Test files with missing node info."""
        nodes = {"a.py": {"type": "python"}}
        files = {"a.py", "b.py"}
        categorized = categorize_files(nodes, files)

        assert len(categorized["python"]) == 1
        assert len(categorized["other"]) == 1

    def test_empty_files(self) -> None:
        """Test empty file set."""
        categorized = categorize_files({}, set())
        assert categorized == {"python": [], "markdown": [], "other": []}


class TestFormatFileSize:
    """Tests for format_file_size function."""

    def test_bytes(self) -> None:
        """Test bytes formatting."""
        assert format_file_size(512) == "512 B"

    def test_kilobytes(self) -> None:
        """Test KB formatting."""
        assert format_file_size(1536) == "1.5 KB"

    def test_megabytes(self) -> None:
        """Test MB formatting."""
        assert format_file_size(1572864) == "1.5 MB"

    def test_zero(self) -> None:
        """Test zero size."""
        assert format_file_size(0) == "0 B"


class TestGenerateProjectContext:
    """Tests for generate_project_context function."""

    def test_generate_context(self, temp_project_root: Path) -> None:
        """Test context generation."""
        with (
            patch("scripts.graph_context.get_graphify_dir") as mock_graph,
            patch("scripts.graph_context.get_collaboration_dir") as mock_collab,
        ):
            mock_graph.return_value = temp_project_root / "graphify-out"
            mock_collab.return_value = temp_project_root / ".agent" / "collaboration"

            context = generate_project_context()

            assert "## Project Context" in context
            assert "WP-2026-147" in context
            assert "file1.py" in context or "file2.py" in context
            assert "doc1.md" in context

    def test_context_line_limit(self, temp_project_root: Path) -> None:
        """Test context respects max_lines limit."""
        with (
            patch("scripts.graph_context.get_graphify_dir") as mock_graph,
            patch("scripts.graph_context.get_collaboration_dir") as mock_collab,
        ):
            mock_graph.return_value = temp_project_root / "graphify-out"
            mock_collab.return_value = temp_project_root / ".agent" / "collaboration"

            context = generate_project_context(max_lines=10)
            lines = context.split("\n")
            assert len(lines) <= 10

    def test_context_deterministic(self, temp_project_root: Path) -> None:
        """Test context generation is deterministic."""
        with (
            patch("scripts.graph_context.get_graphify_dir") as mock_graph,
            patch("scripts.graph_context.get_collaboration_dir") as mock_collab,
        ):
            mock_graph.return_value = temp_project_root / "graphify-out"
            mock_collab.return_value = temp_project_root / ".agent" / "collaboration"

            context1 = generate_project_context()
            context2 = generate_project_context()

            assert context1 == context2


class TestGenerateContextForDestination:
    """Tests for generate_context_for_destination function."""

    def test_destination_success(self, temp_project_root: Path) -> None:
        """Test context generation for destination project."""
        context = generate_context_for_destination(temp_project_root)

        assert context is not None
        assert "## Project Context" in context
        assert "WP-2026-147" in context

    def test_destination_missing_graph(self, tmp_path: Path) -> None:
        """Test None when graph missing in destination."""
        result = generate_context_for_destination(tmp_path)
        assert result is None

    def test_destination_missing_work_plan(self, tmp_path: Path) -> None:
        """Test None when work_plan missing in destination."""
        graphify_dir = tmp_path / "graphify-out"
        graphify_dir.mkdir()
        graph_path = graphify_dir / "graph.json"
        graph_path.write_text("{}", encoding="utf-8")

        result = generate_context_for_destination(tmp_path)
        assert result is None

    def test_destination_invalid_graph(self, tmp_path: Path) -> None:
        """Test None when graph.json is invalid."""
        graphify_dir = tmp_path / "graphify-out"
        graphify_dir.mkdir()
        graph_path = graphify_dir / "graph.json"
        graph_path.write_text("invalid json", encoding="utf-8")

        collab_dir = tmp_path / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True)
        (collab_dir / "work_plan.md").write_text("# Plan\n", encoding="utf-8")

        result = generate_context_for_destination(tmp_path)
        assert result is None


class TestIntegration:
    """Integration tests for the full workflow."""

    def test_full_workflow(self, temp_project_root: Path) -> None:
        """Test complete context generation workflow."""
        with (
            patch("scripts.graph_context.get_graphify_dir") as mock_graph,
            patch("scripts.graph_context.get_collaboration_dir") as mock_collab,
        ):
            mock_graph.return_value = temp_project_root / "graphify-out"
            mock_collab.return_value = temp_project_root / ".agent" / "collaboration"

            context = generate_project_context(max_lines=30)
            lines = context.split("\n")

            assert len(lines) <= 30
            assert lines[0] == "## Project Context"
            assert any("Ticket:" in line for line in lines)
            assert any("Scope:" in line for line in lines)

    def test_empty_graph(self, tmp_path: Path) -> None:
        """Test with empty graph."""
        graphify_dir = tmp_path / "graphify-out"
        graphify_dir.mkdir()
        (graphify_dir / "graph.json").write_text(
            '{"nodes": {}, "edges": []}', encoding="utf-8"
        )
        (graphify_dir / "GRAPH_REPORT.md").write_text("# Report\n", encoding="utf-8")

        collab_dir = tmp_path / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True)
        (collab_dir / "work_plan.md").write_text(
            "# WP-2026-999\n## Files Likely Touched\n- test.py\n",
            encoding="utf-8",
        )

        with (
            patch("scripts.graph_context.get_graphify_dir") as mock_graph,
            patch("scripts.graph_context.get_collaboration_dir") as mock_collab,
        ):
            mock_graph.return_value = graphify_dir
            mock_collab.return_value = collab_dir

            context = generate_project_context()
            assert "## Project Context" in context
