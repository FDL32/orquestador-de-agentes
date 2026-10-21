"""WOT-2026-112a (D1b): header per-origin counts, union dedup invariant, code-only warning.

Covers:
- _build_header_line produces correct format with motor/destino counts
- Header declares UNION deduplicated invariant
- Warning emitted when AGENT_PROJECT_ROOT not set and both surfaces empty
- No warning when destination surface has entries
- _read_portable_archive returns union deduplicated (not sum)
- Deduplication across motor/destino surfaces (solapamiento)
- Mutation: removing a surface still produces valid output
- _format_archive_as_text header includes per-origin breakdown
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bus.memory_loader import (  # noqa: E402
    _build_header_line,
    _format_archive_as_text,
    _read_portable_archive,
)


# =============================================================================
# Tests for _build_header_line (standalone)
# =============================================================================


class TestBuildHeaderLine:
    def test_header_without_origin_breakdown(self) -> None:
        """When no origin_breakdown is given, header is plain (backward compat)."""
        lines = _build_header_line(total=50, shown=60)
        assert "50 lesson(s) travel with this repo" in lines[0]
        assert "motor=" not in lines[0]

    def test_header_with_origin_breakdown(self) -> None:
        """Header names both surfaces with per-origin counts."""
        lines = _build_header_line(
            total=50, shown=60, origin_breakdown={"motor": 30, "destino": 20}
        )
        header = lines[0]
        assert "UNION deduplicated" in header
        assert "motor=30" in header
        assert "destino=20" in header

    def test_header_with_only_motor(self) -> None:
        """Header shows motor count when destino is absent."""
        lines = _build_header_line(
            total=30, shown=60, origin_breakdown={"motor": 30, "destino": 0}
        )
        header = lines[0]
        assert "motor=30" in header
        assert "destino=0" in header

    def test_header_with_only_destino(self) -> None:
        """Header shows destino count when motor is absent."""
        lines = _build_header_line(
            total=20, shown=60, origin_breakdown={"motor": 0, "destino": 20}
        )
        header = lines[0]
        assert "motor=0" in header
        assert "destino=20" in header

    def test_no_warning_when_destino_has_entries(self) -> None:
        """No warning when the destination surface has entries."""
        with patch.dict(os.environ, {"AGENT_PROJECT_ROOT": "/fake/root"}):
            lines = _build_header_line(
                total=50, shown=60, origin_breakdown={"motor": 30, "destino": 20}
            )
        warning_found = any("WARNING" in line for line in lines)
        assert not warning_found

    def test_warning_when_no_motor_surface_no_env(self) -> None:
        """Warning emitted when no motor-tagged entries and AGENT_PROJECT_ROOT not set."""
        # No motor entries (motor=0), destino might have entries or not
        # The key trigger is: no motor-tagged + AGENT_PROJECT_ROOT not set
        env_without = {k: v for k, v in os.environ.items() if k != "AGENT_PROJECT_ROOT"}
        with patch.dict(os.environ, env_without, clear=True):
            lines = _build_header_line(
                total=0, shown=0, origin_breakdown={"motor": 0, "destino": 0}
            )
        warning_found = any("WARNING" in line for line in lines)
        assert warning_found
        # Check warning mentions code-only mode
        warning_text = " ".join(line for line in lines if "WARNING" in line)
        assert "code-only" in warning_text.lower()

    def test_no_warning_when_both_empty_but_env_set(self) -> None:
        """No warning when AGENT_PROJECT_ROOT is set, even if both surfaces empty."""
        with patch.dict(os.environ, {"AGENT_PROJECT_ROOT": "/fake/root"}, clear=False):
            lines = _build_header_line(
                total=0, shown=0, origin_breakdown={"motor": 0, "destino": 0}
            )
        warning_found = any("WARNING" in line for line in lines)
        assert not warning_found


# =============================================================================
# Tests for _read_portable_archive: UNION deduplication
# =============================================================================


def _make_archive_month(root: Path, year: int, month: int, entries: list[dict]) -> None:
    """Create an archive observations file for a given month."""
    archive_dir = root / ".agent" / "runtime" / "memory" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    file_path = archive_dir / f"observations.{year:04d}-{month:02d}.jsonl"
    lines_data = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    file_path.write_text(lines_data + "\n", encoding="utf-8")


class TestPortabilityArchiveUnionDedup:
    def test_two_surfaces_union_deduplicated(self, tmp_path: Path) -> None:
        """The total is UNION deduplicated: overlapping entries appear once."""
        # Create a synthetic motor root archive
        motor_root = tmp_path / "motor"
        _make_archive_month(
            motor_root,
            2026,
            8,
            [
                {
                    "id": "obs-motor1",
                    "topic": "memory",
                    "source_ticket": "WOT-2026-100a",
                    "signal": "motor lesson 1",
                    "timestamp": "2026-08-01T10:00:00Z",
                    "domain": "testing",
                },
                {
                    "id": "obs-motor2",
                    "topic": "deployment",
                    "source_ticket": "WOT-2026-100b",
                    "signal": "motor lesson 2",
                    "timestamp": "2026-08-02T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )

        # Create a synthetic destination root archive with ONE overlapping entry
        destino_root = tmp_path / "destino"
        _make_archive_month(
            destino_root,
            2026,
            8,
            [
                # This entry has the same id as motor's obs-motor1 -> dedup
                {
                    "id": "obs-motor1",
                    "topic": "memory",
                    "source_ticket": "WOT-2026-050a",
                    "signal": "destino version of memory lesson",
                    "timestamp": "2026-08-01T10:00:00Z",
                    "domain": "testing",
                },
                {
                    "id": "obs-destino1",
                    "topic": "topology",
                    "source_ticket": "WOT-2026-101a",
                    "signal": "destino unique lesson",
                    "timestamp": "2026-08-03T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )

        # Patch _get_repo_root to return the destino root (active root)
        # and _resolve_motor_root to return the motor root
        with (
            patch("bus.memory_loader._get_repo_root", return_value=destino_root),
            patch("bus.memory_loader._resolve_motor_root", return_value=motor_root),
        ):
            result = _read_portable_archive()

        # Verify: 3 unique entries (obs-motor1 deduplicated, obs-motor2 + obs-destino1 unique)
        ids_data = [e.get("id") for e in result]
        assert len(result) == 3
        assert "obs-motor1" in ids_data
        assert "obs-motor2" in ids_data
        assert "obs-destino1" in ids_data
        # Verify per-origin tags
        origins = set(e.get("_origin") for e in result)
        assert "motor" in origins
        assert "local" in origins

    def test_dedup_precedence_active_root_wins(self, tmp_path: Path) -> None:
        """When same entry exists in both surfaces, the active root version is kept."""
        motor_root = tmp_path / "motor"
        _make_archive_month(
            motor_root,
            2026,
            8,
            [
                {
                    "id": "obs-shared",
                    "topic": "shared",
                    "source_ticket": "WOT-2026-001a",
                    "signal": "motor version (old)",
                    "timestamp": "2026-07-01T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )

        destino_root = tmp_path / "destino"
        _make_archive_month(
            destino_root,
            2026,
            8,
            [
                {
                    "id": "obs-shared",
                    "topic": "shared",
                    "source_ticket": "WOT-2026-001a",
                    "signal": "destino version (new, edited)",
                    "timestamp": "2026-08-01T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )

        with (
            patch("bus.memory_loader._get_repo_root", return_value=destino_root),
            patch("bus.memory_loader._resolve_motor_root", return_value=motor_root),
        ):
            result = _read_portable_archive()

        # The active root version should be present (signal contains "destino")
        assert len(result) == 1
        assert "destino version (new, edited)" in result[0]["signal"]
        # _origin tag is only present when two surfaces are merged and both
        # contribute entries. When dedup removes ALL motor entries, the early
        # return `return active` skips tagging.
        has_origin = "_origin" in result[0]
        assert has_origin is False

    def test_single_surface_no_motor(self, tmp_path: Path) -> None:
        """When only one surface exists, no motor entries appear."""
        destino_root = tmp_path / "destino"
        _make_archive_month(
            destino_root,
            2026,
            8,
            [
                {
                    "id": "obs-only",
                    "topic": "unique",
                    "source_ticket": "WOT-2026-002a",
                    "signal": "only lesson",
                    "timestamp": "2026-08-01T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )

        with (
            patch("bus.memory_loader._get_repo_root", return_value=destino_root),
            patch("bus.memory_loader._resolve_motor_root", return_value=None),
        ):
            result = _read_portable_archive()

        assert len(result) == 1
        assert result[0]["id"] == "obs-only"
        # _origin tag is only present when two surfaces are merged

    def test_motor_only_no_destino(self, tmp_path: Path) -> None:
        """When active root IS the motor, only one surface is read."""
        motor_root = tmp_path / "motor"
        _make_archive_month(
            motor_root,
            2026,
            8,
            [
                {
                    "id": "obs-motor",
                    "topic": "memory",
                    "source_ticket": "WOT-2026-003a",
                    "signal": "motor only",
                    "timestamp": "2026-08-01T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )

        # When active root is the same as motor root, _read_portable_archive
        # returns only active (no second read)
        with (
            patch("bus.memory_loader._get_repo_root", return_value=motor_root),
            patch("bus.memory_loader._resolve_motor_root", return_value=motor_root),
        ):
            result = _read_portable_archive()

        assert len(result) == 1
        assert result[0]["id"] == "obs-motor"


# =============================================================================
# Tests for _format_archive_as_text: header includes per-origin
# =============================================================================


class TestFormatArchiveHeader:
    def test_header_contains_per_origin_counts(self) -> None:
        """_format_archive_as_text produces header with motor/local counts."""
        observations = [
            {
                "id": "obs-1",
                "topic": "t1",
                "source_ticket": "W-001a",
                "signal": "s1",
                "timestamp": "2026-08-01T10:00:00Z",
                "_origin": "local",
            },
            {
                "id": "obs-2",
                "topic": "t2",
                "source_ticket": "W-002a",
                "signal": "s2",
                "timestamp": "2026-08-02T10:00:00Z",
                "_origin": "local",
            },
            {
                "id": "obs-3",
                "topic": "t3",
                "source_ticket": "W-003a",
                "signal": "s3",
                "timestamp": "2026-08-03T10:00:00Z",
                "_origin": "motor",
            },
        ]

        result = _format_archive_as_text(observations)

        # Header should mention the surfaces
        assert "motor=" in result
        assert "local=" in result or "destino=" in result

    def test_header_total_matches_actual(self) -> None:
        """The total in the header is what actually exists (not an ideal sum)."""
        observations = [
            {
                "id": f"obs-{i}",
                "topic": "t",
                "source_ticket": f"W-{i:03d}a",
                "signal": f"s{i}",
                "timestamp": f"2026-08-{i:02d}T10:00:00Z",
                "_origin": "local",
            }
            for i in range(5)
        ]

        result = _format_archive_as_text(observations)

        # Total should be 5 (the actual count)
        assert "5 lesson(s)" in result

    def test_header_with_override_total(self) -> None:
        """When total_override is given, it is used in the header."""
        observations = [
            {
                "id": "obs-1",
                "topic": "t",
                "source_ticket": "W-001a",
                "signal": "s",
                "timestamp": "2026-08-01T10:00:00Z",
                "_origin": "local",
            }
        ]

        result = _format_archive_as_text(observations, total_override=342)

        assert "342 lesson(s)" in result


# =============================================================================
# Tests: mutation removing a surface
# =============================================================================


class TestMutationRemovingSurface:
    def test_remove_motor_surface_still_valid(self, tmp_path: Path) -> None:
        """After removing the motor archive, output is still valid with one surface."""
        motor_root = tmp_path / "motor"
        _make_archive_month(
            motor_root,
            2026,
            8,
            [
                {
                    "id": "obs-motor-only",
                    "topic": "memory",
                    "source_ticket": "W-004a",
                    "signal": "motor only lesson",
                    "timestamp": "2026-08-01T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )

        # No destination archive
        destino_root = tmp_path / "destino"
        destino_root.mkdir(parents=True)

        with (
            patch("bus.memory_loader._get_repo_root", return_value=destino_root),
            patch("bus.memory_loader._resolve_motor_root", return_value=motor_root),
        ):
            result = _read_portable_archive()

        # Only motor entries
        assert len(result) == 1
        assert result[0]["id"] == "obs-motor-only"

        # Now format: should produce valid markdown with motor count
        text = _format_archive_as_text(result)
        assert "# Portable Memory (tracked archive)" in text
        # When single surface, no _origin tags, so "motor=" may not appear
        # (the header falls back to plain format without origin breakdown)
        assert "lesson(s) travel with this repo" in text

    def test_remove_destino_surface_still_valid(self, tmp_path: Path) -> None:
        """After removing the destination archive, output is still valid with motor."""
        motor_root = tmp_path / "motor"
        _make_archive_month(
            motor_root,
            2026,
            8,
            [
                {
                    "id": "obs-motor",
                    "topic": "memory",
                    "source_ticket": "W-005a",
                    "signal": "motor lesson",
                    "timestamp": "2026-08-01T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )

        # Empty destination archive dir
        destino_root = tmp_path / "destino"
        _make_archive_month(
            destino_root,
            2026,
            8,
            [],
        )

        with (
            patch("bus.memory_loader._get_repo_root", return_value=destino_root),
            patch("bus.memory_loader._resolve_motor_root", return_value=motor_root),
        ):
            result = _read_portable_archive()

        # Only motor entries
        assert len(result) == 1
        assert result[0]["id"] == "obs-motor"

    def test_both_surfaces_removed_empty_output(self, tmp_path: Path) -> None:
        """When both surfaces are empty (no archive at all), output is empty string."""
        motor_root = tmp_path / "motor"
        destino_root = tmp_path / "destino"

        with (
            patch("bus.memory_loader._get_repo_root", return_value=destino_root),
            patch("bus.memory_loader._resolve_motor_root", return_value=motor_root),
        ):
            result = _read_portable_archive()

        assert result == []

        text = _format_archive_as_text(result)
        assert text == ""
