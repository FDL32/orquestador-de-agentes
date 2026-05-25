"""Tests for validate_authority script."""

import sys
from pathlib import Path
from unittest.mock import patch

# Add scripts to path
scripts_dir = Path(__file__).parent.parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from validate_authority import (  # noqa: E402
    find_all_agent_dirs,
    extract_ticket_id,
    is_canonical_authority,
    detect_legacy_copies,
    main,
)


class TestExtractTicketId:
    def test_extracts_valid_ticket(self):
        content = "Some text\nWP-2026-052\nMore text"
        assert extract_ticket_id(content) == "WP-2026-052"

    def test_extracts_first_ticket(self):
        content = "WP-2026-051\nWP-2026-052"
        assert extract_ticket_id(content) == "WP-2026-051"

    def test_returns_unknown_when_no_ticket(self):
        content = "No ticket here"
        assert extract_ticket_id(content) == "UNKNOWN"


class TestIsCanonicalAuthority:
    def test_canonical_path_returns_true(self):
        canonical = "/path/to/orquestador_de_agentes/.agent/collaboration"
        assert is_canonical_authority(canonical, Path(canonical)) is True

    def test_non_canonical_path_returns_false(self):
        canonical = "/path/to/orquestador_de_agentes/.agent/collaboration"
        other = "/path/to/other/.agent/collaboration"
        assert is_canonical_authority(other, Path(canonical)) is False


class TestDetectLegacyCopies:
    def test_filters_out_canonical(self):
        copies = {
            "/canonical/.agent/collaboration": "WP-2026-052",
            "/legacy/.agent/collaboration": "WP-2026-051",
            "/tests/.agent/collaboration": "UNKNOWN"
        }
        canonical = "/canonical/.agent/collaboration"
        legacy = detect_legacy_copies(copies, canonical)
        assert "/legacy/.agent/collaboration" in legacy
        assert "/canonical/.agent/collaboration" not in legacy
        assert "/tests/.agent/collaboration" not in legacy

    def test_excludes_test_paths(self):
        copies = {
            "/repo/.agent/collaboration": "WP-2026-052",
            "/repo/tests/.agent/collaboration": "UNKNOWN"
        }
        canonical = "/repo/.agent/collaboration"
        legacy = detect_legacy_copies(copies, canonical)
        assert len(legacy) == 0


class TestMainFunction:
    @patch('validate_authority.find_all_agent_dirs')
    def test_main_success(self, mock_find):
        mock_root = Path(__file__).resolve().parents[1]
        mock_find.return_value = {
            str(mock_root / ".agent" / "collaboration"): "WP-2026-052"
        }
        # Mock the main function to avoid actual file operations
        with patch('builtins.print'):
            result = main()
        assert result == 0

    @patch('validate_authority.find_all_agent_dirs')
    def test_main_failure_no_canonical(self, mock_find):
        mock_find.return_value = {
            "/other/.agent/collaboration": "WP-2026-051"
        }
        with patch('builtins.print'):
            result = main()
        assert result == 1
