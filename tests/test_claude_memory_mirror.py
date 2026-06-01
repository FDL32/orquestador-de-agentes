"""Tests for claude_memory_mirror.py — local opt-in Claude memory sync.

Test inventory (from work plan WT-2026-192):
  - test_claude_memory_mirror_missing_path_warns_without_crashing
  - test_claude_memory_mirror_permission_denied_reports_local_warning
  - test_claude_memory_mirror_dry_run_does_not_write
  - test_claude_memory_mirror_apply_writes_to_mirror_path
  - test_claude_memory_mirror_export_reads_workspace_memory_only
  - test_claude_memory_mirror_import_preserves_source_and_dedupes
  - test_validate_succeeds_when_claude_memory_path_is_missing
  - test_session_close_does_not_call_claude_memory_mirror
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# Add scripts to path
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from claude_memory_mirror import (  # noqa: E402
    _generate_obs_id,
    _md_to_observation,
    _observation_to_md,
    _parse_frontmatter,
    _read_observations,
    _write_observations,
    build_parser,
    derive_project_slug,
    do_check_freshness,
    do_export,
    do_import,
    main,
)


# Use the motor repo's own memory dir for path resolution fallback in tests.
_MOTOR_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    """Create an isolated memory directory for testing."""
    mdir = tmp_path / "memory"
    mdir.mkdir(parents=True, exist_ok=True)
    return mdir


@pytest.fixture
def claude_dir(tmp_path: Path) -> Path:
    """Create a fake Claude memory mirror directory."""
    cdir = tmp_path / "claude_memory"
    cdir.mkdir(parents=True, exist_ok=True)
    return cdir


@pytest.fixture
def observations_path(memory_dir: Path) -> Path:
    """Path to observations.jsonl within the isolated memory dir."""
    return memory_dir / "observations.jsonl"


@pytest.fixture
def sample_observations() -> list[dict]:
    """Return a list of sample observation dicts."""
    return [
        {
            "id": "obs-commit-hygiene",
            "timestamp": "2026-05-31T20:10:31.147070+00:00",
            "topic": "commit-hygiene",
            "signal": "El cierre canonico no valida el ultimo commit.",
            "source": "migrated:WT-2026-191",
            "domain": "delivery-hygiene",
            "confidence": 0.9,
            "applies_to": "code",
            "source_ticket": "WT-2026-191",
        },
        {
            "id": "obs-memory-tiers",
            "timestamp": "2026-05-31T20:10:31.147070+00:00",
            "topic": "memory-tiers",
            "signal": "Memory loader soporta L3/L2/L1 con fallthrough.",
            "source": "migrated:WT-2026-191",
            "domain": "bus-architecture",
            "confidence": 0.85,
            "applies_to": "code",
            "source_ticket": "WT-2026-191",
        },
    ]


# --- Tests: derive_project_slug ---


class TestDeriveProjectSlug:
    """Deterministic slug derivation per WT-2026-192 algorithm."""

    def test_windows_path(self):
        """Windows paths produce expected slug."""
        root = Path("C:/Users/fdl/Proyectos_Python/z_scripts")
        slug = derive_project_slug(root)
        assert slug == "c--Users-fdl-Proyectos-Python-z-scripts"

    def test_unix_path_passthrough(self):
        """Unix paths without drive letters get C: prefix on Windows."""
        root = Path("/home/user/project")
        slug = derive_project_slug(root)
        # On Windows, resolve() prepends C:\ -> slug starts with c--
        assert isinstance(slug, str)
        assert "--" in slug
        assert "home" in slug
        assert "user" in slug
        assert "project" in slug
        assert "_" not in slug

    def test_underscores_replaced(self):
        """Underscores are replaced with hyphens."""
        root = Path("C:/my_project/sub_module")
        slug = derive_project_slug(root)
        assert "_" not in slug


# --- Tests: _generate_obs_id ---


class TestGenerateObsId:
    """Stable observation ID generation."""

    def test_uses_existing_id(self):
        """Returns existing id field when present."""
        obs = {"id": "my-custom-id", "topic": "test", "signal": "hello"}
        assert _generate_obs_id(obs) == "my-custom-id"

    def test_generates_from_topic_and_signal(self):
        """Generates topic-hash when no id field."""
        obs = {"topic": "memory-tiers", "signal": "some signal content"}
        result = _generate_obs_id(obs)
        assert result.startswith("memory-tiers-")
        assert len(result) > len("memory-tiers-")

    def test_deterministic(self):
        """Same inputs produce same output."""
        obs = {"topic": "test", "signal": "content"}
        assert _generate_obs_id(obs) == _generate_obs_id(obs)


# ---------------------------------------------------------------------------
# Tests: _parse_frontmatter / _observation_to_md round-trip
# ---------------------------------------------------------------------------


class TestFrontmatterRoundTrip:
    """Export and import are reversible."""

    def test_round_trip_preserves_all_fields(self):
        """Export then import recovers original observation fields."""
        obs = {
            "id": "test-round-trip",
            "signal": "Some signal text for round-trip testing.",
            "domain": "testing",
            "confidence": 0.75,
            "source": "test-suite",
            "timestamp": "2026-06-01T12:00:00+00:00",
        }
        md = _observation_to_md(obs)
        frontmatter, body = _parse_frontmatter(md)
        recovered = _md_to_observation(frontmatter, body)

        # Check id preserved
        assert recovered["id"] == "test-round-trip"
        # Check signal preserved
        assert "Some signal text for round-trip testing." in recovered["signal"]
        # Check metadata fields preserved
        assert recovered["domain"] == "testing"
        assert recovered["confidence"] == 0.75
        assert recovered["source"] == "test-suite"
        assert recovered["timestamp"] == "2026-06-01T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Tests: missing / permission-denied paths
# ---------------------------------------------------------------------------


class TestMissingPathHandling:
    """~/.claude/ missing must not crash the script."""

    def test_import_missing_claude_dir_returns_info(self, observations_path):
        """Import with nonexistent claude dir returns info message, not crash."""
        nonexistent = Path("/nonexistent/claude/memory")
        exit_code, messages = do_import(observations_path, nonexistent, apply=False)
        assert exit_code == 0
        assert any("not found" in msg for msg in messages)

    def test_export_missing_observations_returns_info(self, claude_dir):
        """Export with no observations returns info, not crash."""
        nonexistent = Path("/tmp/nonexistent_obs.jsonl")
        exit_code, messages = do_export(nonexistent, claude_dir, apply=False)
        assert exit_code == 0
        assert any("No observations" in msg for msg in messages)


class TestPermissionDeniedHandling:
    """Permission errors should degrade to local warning."""

    def test_export_oserror_reported_as_warning(self, observations_path, claude_dir):
        """When write fails with OSError, it's reported as warning, not crash."""
        # Create one observation
        obs = [{"id": "test-obs", "signal": "test body", "topic": "test"}]
        _write_observations(observations_path, obs)

        # Patch the write_text to raise OSError
        with patch.object(
            Path, "write_text", side_effect=OSError(13, "Permission denied")
        ):
            exit_code, messages = do_export(observations_path, claude_dir, apply=True)

        assert exit_code == 0  # Non-fatal
        assert any("WARNING" in msg for msg in messages)


# ---------------------------------------------------------------------------
# Tests: dry-run vs apply
# ---------------------------------------------------------------------------


class TestDryRunBehavior:
    """--dry-run must not write any files."""

    def test_export_dry_run_does_not_write(self, observations_path, claude_dir):
        """Export in dry-run mode creates no files in claude_dir."""
        obs = [{"id": "test-dry", "signal": "body", "topic": "test"}]
        _write_observations(observations_path, obs)

        exit_code, messages = do_export(observations_path, claude_dir, apply=False)
        assert exit_code == 0
        assert any("DRY-RUN" in msg for msg in messages)
        assert len(list(claude_dir.glob("*.md"))) == 0

    def test_import_dry_run_does_not_modify_observations(
        self, observations_path, claude_dir
    ):
        """Import in dry-run mode does not append to observations.jsonl."""
        # Write one existing observation
        existing = [{"id": "existing-obs", "signal": "existing", "topic": "test"}]
        _write_observations(observations_path, existing)

        # Write a claude markdown file
        obs_to_import = {
            "id": "new-obs",
            "signal": "new observation",
            "topic": "test",
            "domain": "testing",
            "confidence": 0.5,
            "source": "test",
            "timestamp": "2026-06-01T00:00:00+00:00",
        }
        md_content = _observation_to_md(obs_to_import)
        (claude_dir / "new-obs.md").write_text(md_content, encoding="utf-8")

        exit_code, messages = do_import(observations_path, claude_dir, apply=False)
        assert exit_code == 0
        assert any("DRY-RUN" in msg for msg in messages)

        # Verify observations.jsonl only has the original
        final_obs = _read_observations(observations_path)
        assert len(final_obs) == 1
        assert final_obs[0]["id"] == "existing-obs"


class TestApplyBehavior:
    """--apply must actually write files."""

    def test_export_apply_writes_to_mirror_path(self, observations_path, claude_dir):
        """Export with --apply creates .md files in claude_dir."""
        obs = [
            {
                "id": "apply-test-1",
                "signal": "First test observation.",
                "topic": "test",
            },
            {
                "id": "apply-test-2",
                "signal": "Second test observation.",
                "topic": "test",
            },
        ]
        _write_observations(observations_path, obs)

        exit_code, _messages = do_export(observations_path, claude_dir, apply=True)
        assert exit_code == 0

        md_files = list(claude_dir.glob("*.md"))
        assert len(md_files) == 2
        assert (claude_dir / "apply-test-1.md").exists()
        assert (claude_dir / "apply-test-2.md").exists()


# ---------------------------------------------------------------------------
# Tests: export reads workspace memory only
# ---------------------------------------------------------------------------


class TestExportScope:
    """Export must only read from canonical workspace memory."""

    def test_export_reads_workspace_memory_only(self, observations_path, claude_dir):
        """Export uses only the provided observations_path, not other sources."""
        obs = [{"id": "scope-test", "signal": "only this one", "topic": "test"}]
        _write_observations(observations_path, obs)

        exit_code, _messages = do_export(observations_path, claude_dir, apply=True)
        assert exit_code == 0

        md_files = list(claude_dir.glob("*.md"))
        assert len(md_files) == 1
        content = (claude_dir / "scope-test.md").read_text(encoding="utf-8")
        assert "only this one" in content


# ---------------------------------------------------------------------------
# Tests: import preserves source and dedupes
# ---------------------------------------------------------------------------


class TestImportPreservesSourceAndDedupes:
    """Import must preserve source provenance and avoid duplicates."""

    def test_import_preserves_source_and_dedupes(self, observations_path, claude_dir):
        """Import keeps source from metadata and dedupes by id."""
        # Existing observation (will cause dedupe)
        existing_obs = {
            "id": "dedupe-me",
            "signal": "This observation already exists.",
            "topic": "test",
            "domain": "testing",
            "confidence": 0.5,
            "source": "original-source",
            "timestamp": "2026-06-01T00:00:00+00:00",
        }
        _write_observations(observations_path, [existing_obs])

        # Same id exported to claude dir (simulating updated version)
        claude_obs = {
            "id": "dedupe-me",
            "signal": "Updated signal that should NOT be imported (deduped).",
            "topic": "test",
            "domain": "testing",
            "confidence": 0.8,
            "source": "claude-update",
            "timestamp": "2026-06-01T12:00:00+00:00",
        }
        md_content = _observation_to_md(claude_obs)
        (claude_dir / "dedupe-me.md").write_text(md_content, encoding="utf-8")

        # New observation to import
        new_obs = {
            "id": "brand-new-obs",
            "signal": "Brand new observation from Claude.",
            "topic": "test",
            "domain": "testing",
            "confidence": 0.9,
            "source": "claude-source",
            "timestamp": "2026-06-01T12:00:00+00:00",
        }
        md_content = _observation_to_md(new_obs)
        (claude_dir / "brand-new-obs.md").write_text(md_content, encoding="utf-8")

        exit_code, _messages = do_import(observations_path, claude_dir, apply=True)
        assert exit_code == 0

        final_obs = _read_observations(observations_path)
        assert len(final_obs) == 2  # Original + new (not 3)

        # Verify original preserved (not overwritten)
        original = [o for o in final_obs if o["id"] == "dedupe-me"]
        assert len(original) == 1
        assert original[0]["source"] == "original-source"  # Preserved
        assert "already exists" in original[0]["signal"]  # Not overwritten

        # Verify new observation imported with source preserved
        imported = [o for o in final_obs if o["id"] == "brand-new-obs"]
        assert len(imported) == 1
        assert imported[0]["source"] == "claude-source"

    def test_import_adds_source_when_missing(self, observations_path, claude_dir):
        """Import adds 'claude-memory-mirror' source when metadata has no source."""
        obs = {
            "id": "no-source-obs",
            "signal": "Observation without source in metadata.",
            "topic": "test",
            "domain": "testing",
            "confidence": 0.5,
            "timestamp": "2026-06-01T00:00:00+00:00",
        }
        md_content = _observation_to_md(obs)
        (claude_dir / "no-source-obs.md").write_text(md_content, encoding="utf-8")

        exit_code, _messages = do_import(observations_path, claude_dir, apply=True)
        assert exit_code == 0

        final_obs = _read_observations(observations_path)
        assert len(final_obs) == 1
        assert final_obs[0]["source"] == "claude-memory-mirror"


# --- Tests: check-freshness ---


class TestCheckFreshness:
    """--check-freshness reports relative ages without crashing."""

    def test_check_freshness_no_observations(self, claude_dir):
        """Freshness check with missing observations returns info."""
        obs_path = Path("/nonexistent/observations.jsonl")
        exit_code, messages = do_check_freshness(obs_path, claude_dir, apply=False)
        assert exit_code == 1
        assert any("does not exist" in msg for msg in messages)

    def test_check_freshness_no_claude_dir(self, observations_path):
        """Freshness check with missing claude dir returns info."""
        (observations_path.parent).mkdir(parents=True, exist_ok=True)
        observations_path.write_text("{}\n", encoding="utf-8")
        nonexistent = Path("/nonexistent/claude/dir")
        exit_code, messages = do_check_freshness(
            observations_path, nonexistent, apply=False
        )
        assert exit_code == 1
        assert any("does not exist" in msg for msg in messages)


# ---------------------------------------------------------------------------
# Tests: agent_controller --validate does not depend on Claude
# ---------------------------------------------------------------------------


class TestValidateIndependentOfClaude:
    """--validate must work without Claude installed."""

    def test_validate_state_files_does_not_reference_claude(self):
        """validate_state_files method has no Claude dependency in its logic."""
        # Verify agent_controller has no import of claude_memory_mirror
        controller_path = (
            Path(__file__).parent.parent / ".agent" / "agent_controller.py"
        )
        content = controller_path.read_text(encoding="utf-8")
        assert "claude_memory_mirror" not in content

    def test_validate_command_not_crashing_without_claude(self):
        """agent_controller --validate does not need ~/.claude/ to exist."""
        # Set up sys.path to import agent_controller
        agent_dir = Path(__file__).parent.parent / ".agent"
        _restore_path = str(agent_dir) not in sys.path
        if _restore_path:
            sys.path.insert(0, str(agent_dir))

        try:
            from agent_controller import validate_state_files

            errors = validate_state_files()
            assert isinstance(errors, dict)
            # The validate result doesn't involve Claude at all
            assert "work_plan.md" in errors
            assert "execution_log.md" in errors
        finally:
            if _restore_path:
                sys.path.pop(0)


# ---------------------------------------------------------------------------
# Tests: session-close does not call Claude mirror
# ---------------------------------------------------------------------------


class TestSessionCloseIndependent:
    """--session-close must not call claude_memory_mirror."""

    def test_session_closeout_does_not_import_mirror(self):
        """session_closeout.py has no reference to claude_memory_mirror."""
        closeout_path = _SCRIPTS_DIR / "session_closeout.py"
        content = closeout_path.read_text(encoding="utf-8")
        assert "claude_memory_mirror" not in content
        assert "Claude" not in content or "Claude" in content == content.count("Claude")

    def test_main_functions_return_expected_types(self):
        """Public functions return expected (int, list) tuples."""
        # Create tmp paths
        import tempfile

        from claude_memory_mirror import do_check_freshness, do_export, do_import

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            obs_path = base / "obs.jsonl"
            cdir = base / "claude"
            cdir.mkdir()

            ec, msgs = do_export(obs_path, cdir, apply=False)
            assert isinstance(ec, int)
            assert isinstance(msgs, list)

            ec, msgs = do_import(obs_path, cdir, apply=False)
            assert isinstance(ec, int)
            assert isinstance(msgs, list)

            ec, msgs = do_check_freshness(obs_path, cdir, apply=False)
            assert isinstance(ec, int)
            assert isinstance(msgs, list)


# ---------------------------------------------------------------------------
# Tests: CLI argument parsing
# ---------------------------------------------------------------------------


class TestCliParsing:
    """CLI argument parsing."""

    def test_requires_at_least_one_action(self):
        """main() returns non-zero when no action specified."""
        with patch("sys.argv", ["claude_memory_mirror.py"]):
            ec = main()
        assert ec == 1  # Returns error code, not sys.exit

    def test_accepts_export(self):
        """Parser accepts --export flag."""
        parser = build_parser()
        args = parser.parse_args(["--export"])
        assert args.export
        assert not args.import_
        assert not args.check_freshness

    def test_accepts_import(self):
        """Parser accepts --import flag."""
        parser = build_parser()
        args = parser.parse_args(["--import"])
        assert args.import_

    def test_accepts_apply_flag(self):
        """Parser accepts --apply flag."""
        parser = build_parser()
        args = parser.parse_args(["--export", "--apply"])
        assert args.apply

    def test_main_export_dry_run_returns_zero(self):
        """main() with --export returns 0 without crashing."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            test_obs_path = base / "obs.jsonl"
            test_obs_path.parent.mkdir(parents=True, exist_ok=True)
            test_obs = [{"id": "cli-test", "signal": "body", "topic": "test"}]
            _write_observations(test_obs_path, test_obs)

            with (
                patch("sys.argv", ["claude_memory_mirror.py", "--export"]),
                patch(
                    "claude_memory_mirror.get_observations_path",
                    return_value=test_obs_path,
                ),
                patch(
                    "claude_memory_mirror.get_claude_memory_dir",
                    return_value=base / "mirror",
                ),
            ):
                ec = main()
                assert ec == 0


# ---------------------------------------------------------------------------
# Tests: derived project slug matches real environment
# ---------------------------------------------------------------------------


class TestRealPathSlug:
    """Verify slug derivation works for the real project path."""

    def test_motor_repo_slug(self):
        """Motor repo path produces a deterministic slug."""
        slug = derive_project_slug(_MOTOR_PROJECT_ROOT)
        assert isinstance(slug, str)
        assert len(slug) > 10
        assert "--" in slug or "-" in slug

    def test_workspace_slug(self):
        """Workspace path produces expected slug pattern."""
        workspace = Path("C:/Users/fdl/Proyectos_Python/z_scripts")
        slug = derive_project_slug(workspace)
        assert slug == "c--Users-fdl-Proyectos-Python-z-scripts"
