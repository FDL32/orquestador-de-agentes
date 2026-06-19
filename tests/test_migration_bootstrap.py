"""Tests for WT-2026-191: memory migration, bootstrap CLI, and L3/L2/L1 fallback.

Test inventory:
- test_migration_produces_exact_target_schema
- test_repo_state_entry_is_excluded
- test_validate_observations_passes_after_migration
- test_migration_restores_from_backup_on_validation_failure
- test_loader_preserves_legacy_fallback_only_as_defensive_path
- test_memory_context_bootstrap_prints_l3_l2_context
- test_session_bootstrap_references_real_bootstrap_command
- test_migration_is_idempotent_on_second_run
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest


# Project root for imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bus import memory_loader as ml  # noqa: E402
from scripts.migrate_observations import (  # noqa: E402
    _is_repo_state,
    _migrate_entry,
    _normalize_applies_to,
    _normalize_timestamp,
    run_migration,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    """Create an isolated memory directory for testing."""
    mdir = tmp_path / "memory"
    mdir.mkdir(parents=True, exist_ok=True)
    return mdir


@pytest.fixture
def observations_path(memory_dir: Path) -> Path:
    """Path to observations.jsonl within the isolated memory dir."""
    return memory_dir / "observations.jsonl"


@pytest.fixture
def rules_path(memory_dir: Path) -> Path:
    """Path to memory_rules.md (L2)."""
    return memory_dir / "memory_rules.md"


@pytest.fixture
def profile_path(memory_dir: Path) -> Path:
    """Path to memory_profile.md (L3)."""
    return memory_dir / "memory_profile.md"


@pytest.fixture
def monkeypatch_memory_dir(monkeypatch: pytest.MonkeyPatch, memory_dir: Path) -> Path:
    """Monkeypatch memory_loader._get_memory_dir to use isolated temp path."""
    monkeypatch.setattr(ml, "_get_memory_dir", lambda: memory_dir)
    return memory_dir


# ─── Sample legacy entries ────────────────────────────────────────────────


@pytest.fixture
def repo_state_entry() -> dict:
    """A repo_state legacy entry that should be excluded from active memory."""
    return {
        "ts": "2026-05-31",
        "kind": "repo_state",
        "text": "Repo state snapshot at session close.",
    }


@pytest.fixture
def legacy_audit_entry() -> dict:
    """A legacy audit entry with date/ticket/summary fields."""
    return {
        "date": "2026-05-31",
        "type": "audit_closeout",
        "ticket": "WT-2026-186",
        "summary": "Closed the installer idempotency audit.",
    }


@pytest.fixture
def legacy_domain_entry() -> dict:
    """A legacy entry with bus/recovery domain."""
    return {
        "date": "2026-05-31",
        "type": "engineering_invariant",
        "domain": "bus/recovery",
        "summary": "Recovery paths must be idempotent.",
    }


@pytest.fixture
def canonical_entry() -> dict:
    """An already-canonical entry that should pass non-strict validation."""
    return {
        "timestamp": "2026-05-31T20:10:31.147070+00:00",
        "topic": "delivery-hygiene",
        "domain": "delivery-hygiene",
        "signal": "Canonical observation for testing.",
        "source": "session-test",
        "applies_to": "all",
        "confidence": 0.95,
    }


# ─── Helper ──────────────────────────────────────────────────────────────────


def _write_observations(path: Path, entries: list[dict]) -> None:
    """Write entries to observations.jsonl."""
    lines = [json.dumps(e, ensure_ascii=False) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMigration:
    """WT-2026-191 Fase 2: Migration logic tests."""

    def test_migration_produces_exact_target_schema(self, observations_path: Path):
        """TP-02: Migrated entries have all required canonical fields."""
        entries = [
            {
                "date": "2026-05-31",
                "type": "planning_rule",
                "domain": "ticket-planning",
                "summary": "Plan test path verification.",
            },
            {
                "date": "2026-05-31",
                "type": "testing_pattern",
                "domain": "validator-design",
                "summary": "Keep tests orthogonal.",
            },
        ]
        _write_observations(observations_path, entries)

        success = run_migration(observations_path, apply=True, verbose=False)
        assert success == 0

        result_text = observations_path.read_text(encoding="utf-8")
        result_lines = [ln for ln in result_text.splitlines() if ln.strip()]
        assert len(result_lines) == 2

        for line in result_lines:
            entry = json.loads(line)
            # All canonical fields must be present
            assert "timestamp" in entry, f"Missing timestamp in {entry}"
            assert "signal" in entry, f"Missing signal in {entry}"
            assert "source" in entry, f"Missing source in {entry}"
            assert "topic" in entry, f"Missing topic in {entry}"
            assert "domain" in entry, f"Missing domain in {entry}"
            assert "confidence" in entry, f"Missing confidence in {entry}"
            assert "applies_to" in entry, f"Missing applies_to in {entry}"
            assert "source_ticket" in entry, f"Missing source_ticket in {entry}"

            # Validate values
            assert isinstance(entry["timestamp"], str)
            assert isinstance(entry["signal"], str) and entry["signal"]
            assert isinstance(entry["source"], str) and entry["source"]
            assert isinstance(entry["topic"], str) and re.match(
                r"^[a-z][a-z0-9-]*$", entry["topic"]
            ), f"topic '{entry['topic']}' not kebab-case"
            assert isinstance(entry["domain"], str)
            assert isinstance(entry["confidence"], (int, float))
            assert 0.0 <= entry["confidence"] <= 1.0
            assert entry["applies_to"] in ("code", "mixed", "docs", "all")

    def test_repo_state_entry_is_excluded(self, observations_path: Path):
        """TP-03: repo_state entry excluded from active memory."""
        entries = [
            {"ts": "2026-05-31", "kind": "repo_state", "text": "Snapshot."},
            {
                "date": "2026-05-31",
                "type": "rule",
                "domain": "bus/recovery",
                "summary": "A valid rule.",
            },
        ]
        _write_observations(observations_path, entries)

        success = run_migration(observations_path, apply=True, verbose=False)
        assert success == 0

        result_text = observations_path.read_text(encoding="utf-8")
        result_lines = [ln for ln in result_text.splitlines() if ln.strip()]
        assert len(result_lines) == 1

        entry = json.loads(result_lines[0])
        assert "kind" not in entry
        assert entry.get("domain") in ("bus-architecture",), (
            "repo_state domain should not appear"
        )

    def test_validate_observations_passes_after_migration(
        self, observations_path: Path
    ):
        """TP-04: validate_observations.py --strict passes after migration."""
        entries = [
            {
                "date": "2026-05-31",
                "type": "planning_rule",
                "domain": "ticket-planning",
                "summary": "Verify test paths.",
            },
        ]
        _write_observations(observations_path, entries)

        success = run_migration(observations_path, apply=True, verbose=False)
        assert success == 0

        # Validate with --strict directly
        from scripts.validate_observations import validate_file

        valid, errors = validate_file(observations_path, strict=True)
        assert valid, f"Strict validation failed: {errors}"

    def test_migration_restores_from_backup_on_validation_failure(
        self, observations_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """TP-05: Rollback restores backup if validation fails."""
        # Create an entry that will migrate cleanly
        entries = [
            {
                "date": "2026-05-31",
                "type": "rule",
                "domain": "bus/recovery",
                "summary": "Test rule.",
            },
        ]
        _write_observations(observations_path, entries)

        # Monkeypatch the validation to fail after migration
        def _mock_validation_fails(*args, **kwargs):
            return False

        monkeypatch.setattr(
            "scripts.migrate_observations._run_strict_validation",
            _mock_validation_fails,
        )

        # Run migration (should fail and restore)
        success = run_migration(observations_path, apply=True, verbose=False)
        assert success == 1

        # Original content should be restored (backup matched original)
        result_text = observations_path.read_text(encoding="utf-8")
        result_lines = [ln for ln in result_text.splitlines() if ln.strip()]
        assert len(result_lines) == 1

        # The entry should still have original (pre-migration) fields
        entry = json.loads(result_lines[0])
        assert "date" in entry, "Original 'date' field should be restored"

    def test_migration_is_idempotent_on_second_run(self, observations_path: Path):
        """TP-06: Second migration run leaves file intact."""
        entries = [
            {
                "date": "2026-05-31",
                "type": "rule",
                "domain": "ticket-planning",
                "summary": "Test idempotency.",
            },
        ]
        _write_observations(observations_path, entries)

        # First run (apply)
        success1 = run_migration(observations_path, apply=True, verbose=False)
        assert success1 == 0
        content_after_first = observations_path.read_text(encoding="utf-8")

        # Second run (dry-run should show 0 migrations)
        success2 = run_migration(observations_path, apply=False, verbose=False)
        assert success2 == 0

        # Content should be identical
        content_after_second = observations_path.read_text(encoding="utf-8")
        assert content_after_first == content_after_second

        # Third run (apply again - should be no-op)
        success3 = run_migration(observations_path, apply=True, verbose=False)
        assert success3 == 0

        content_after_third = observations_path.read_text(encoding="utf-8")
        assert content_after_second == content_after_third

    # ─── Unit-level helpers ─────────────────────────────────────────────────

    def test_is_repo_state_detection(self, repo_state_entry: dict):
        """_is_repo_state correctly detects repo_state entries."""
        assert _is_repo_state(repo_state_entry)
        assert not _is_repo_state({"kind": "observation"})
        assert not _is_repo_state({"type": "audit"})

    def test_normalize_applies_to_array(self):
        """applies_to array is normalized to 'mixed'."""
        assert _normalize_applies_to(["code", "mixed"]) == "mixed"
        assert _normalize_applies_to(["code"]) == "mixed"

    def test_normalize_applies_to_valid_string(self):
        """Valid applies_to strings are preserved."""
        assert _normalize_applies_to("code") == "code"
        assert _normalize_applies_to("mixed") == "mixed"
        assert _normalize_applies_to("docs") == "docs"
        assert _normalize_applies_to("all") == "all"

    def test_normalize_applies_to_invalid_string(self):
        """Invalid applies_to strings are replaced with default."""
        assert _normalize_applies_to("testing") == "mixed"
        assert _normalize_applies_to("random") == "mixed"

    def test_normalize_timestamp_date_only(self):
        """Date-only strings get UTC time appended."""
        result = _normalize_timestamp("2026-05-31")
        assert result == "2026-05-31T00:00:00Z"

    def test_normalize_timestamp_iso(self):
        """Already valid ISO-8601 is preserved."""
        result = _normalize_timestamp("2026-05-31T20:10:31.147070+00:00")
        assert "T" in result
        assert result.endswith("+00:00")

    def test_migrate_entry_exclude_repo_state(self, repo_state_entry: dict):
        """_migrate_entry returns None for repo_state entries."""
        result = _migrate_entry(repo_state_entry, 0)
        assert result is None

    def test_migrate_entry_adds_defaults(self):
        """_migrate_entry adds default confidence, applies_to, source."""
        entry = {
            "date": "2026-05-31",
            "type": "audit",
            "summary": "A test observation.",
        }
        result = _migrate_entry(entry, 0)
        assert result is not None
        assert result["confidence"] == 0.9
        assert result["applies_to"] == "mixed"
        assert result["source"].startswith("migrated:")
        assert "timestamp" in result
        assert "signal" in result
        assert "id" in result


class TestBootstrap:
    """WT-2026-191 Fase 3-4: Bootstrap CLI and L3/L2/L1 fallback tests."""

    def test_memory_context_bootstrap_prints_l3_l2_context(
        self,
        monkeypatch_memory_dir: Path,
        profile_path: Path,
        rules_path: Path,
        observations_path: Path,
    ):
        """TP-08: memory_context.py --bootstrap prints L3 when available."""
        # Create L3 profile
        profile_path.write_text(
            "# Memory Profile (L3)\n\ndomain-a: 3 observations",
            encoding="utf-8",
        )
        # L2 and L1 exist but should not be used when L3 is present
        rules_path.write_text(
            "# Memory Rules (L2)\n\n## Domain: test\n\nR-001: rule",
            encoding="utf-8",
        )
        _write_observations(
            observations_path,
            [
                {
                    "timestamp": "2026-05-31T00:00:00Z",
                    "topic": "test",
                    "signal": "Raw observation",
                    "source": "test",
                }
            ],
        )

        ctx = ml.get_bootstrap_context()
        assert ctx, "Bootstrap context should not be empty"
        # L3 should be returned (L2 is not included when L3 exists)
        assert "# Memory Profile (L3)" in ctx
        # L2 should NOT be in the context when L3 is available
        assert "# Memory Rules (L2)" not in ctx

    def test_memory_context_bootstrap_l2_fallback(
        self,
        monkeypatch_memory_dir: Path,
        rules_path: Path,
        observations_path: Path,
    ):
        """Without L3, bootstrap falls back to L2 rules."""
        # Only L2 exists
        rules_path.write_text(
            "# Memory Rules (L2)\n\n## Domain: test\n\nRule content",
            encoding="utf-8",
        )
        _write_observations(
            observations_path,
            [
                {
                    "timestamp": "2026-05-31T00:00:00Z",
                    "topic": "test",
                    "signal": "Raw observation",
                    "source": "test",
                }
            ],
        )

        ctx = ml.get_bootstrap_context()
        assert "Memory Rules (L2)" in ctx
        assert "Raw observation" not in ctx  # L1 should not be shown

    def test_memory_context_bootstrap_l1_fallback(
        self,
        monkeypatch_memory_dir: Path,
        observations_path: Path,
    ):
        """Without L3/L2, bootstrap falls back to L1 raw observations."""
        _write_observations(
            observations_path,
            [
                {
                    "timestamp": "2026-05-31T00:00:00Z",
                    "topic": "fallback-test",
                    "signal": "Only raw observation available",
                    "source": "test",
                }
            ],
        )

        ctx = ml.get_bootstrap_context()
        assert "Raw Observations" in ctx
        assert "fallback-test" in ctx

    def test_memory_context_bootstrap_empty(
        self, memory_dir: Path, monkeypatch_memory_dir: Path
    ):
        """With no memory files, bootstrap returns empty string."""
        ctx = ml.get_bootstrap_context()
        assert ctx == ""

    def test_session_bootstrap_references_real_bootstrap_command(self):
        """TP-09: the canonical bootstrap prompt references the real CLI.

        WOT-2026-008h renamed session_bootstrap.md -> the orchestrator_* canonical;
        the operational content lives there now, the legacy name is a stub.
        """
        bootstrap_path = (
            Path(__file__).resolve().parents[1]
            / "prompts"
            / "orchestrator_session_bootstrap.md"
        )
        assert bootstrap_path.exists(), "orchestrator_session_bootstrap.md not found"

        content = bootstrap_path.read_text(encoding="utf-8")
        assert "memory_context.py --bootstrap" in content, (
            "canonical bootstrap should reference the real bootstrap CLI"
        )
        assert "memory_context.py --status" in content, (
            "canonical bootstrap should reference the status command"
        )

    def test_memory_context_cli_script_exists(self):
        """scripts/memory_context.py exists and is executable."""
        script_path = (
            Path(__file__).resolve().parents[1] / "scripts" / "memory_context.py"
        )
        assert script_path.exists(), "memory_context.py not found"
        content = script_path.read_text(encoding="utf-8")
        assert "--bootstrap" in content
        assert "--status" in content
        assert "get_bootstrap_context" in content


class TestLoaderFallback:
    """Memory loader L3/L2/L1 fallback hierarchy."""

    def test_loader_preserves_legacy_fallback_only_as_defensive_path(
        self,
        monkeypatch_memory_dir: Path,
        observations_path: Path,
        rules_path: Path,
        profile_path: Path,
    ):
        """TP-07: loader uses L3 -> L2 -> L1 hierarchy correctly."""
        # When L3 exists, L2 and L1 are not used
        profile_path.write_text("# L3 Only", encoding="utf-8")
        rules_path.write_text("# L2 Should Not Appear", encoding="utf-8")
        _write_observations(
            observations_path,
            [
                {
                    "timestamp": "2026-05-31T00:00:00Z",
                    "topic": "test",
                    "signal": "L1 should not appear",
                    "source": "test",
                }
            ],
        )

        ctx = ml.get_bootstrap_context()
        assert "L3 Only" in ctx
        assert "L2 Should Not Appear" not in ctx
        assert "L1 should not appear" not in ctx

        # When only L2 exists, L3 is skipped, L1 is not used
        profile_path.unlink()
        ctx = ml.get_bootstrap_context()
        assert "L2 Should Not Appear" in ctx
        assert "L1 should not appear" not in ctx

        # When only L1 exists, it is the fallback
        rules_path.unlink()
        ctx = ml.get_bootstrap_context()
        assert "L1 should not appear" in ctx

        # When nothing exists, empty string
        observations_path.unlink()
        ctx = ml.get_bootstrap_context()
        assert ctx == ""

    def test_get_memory_tier_status(
        self,
        monkeypatch_memory_dir: Path,
        profile_path: Path,
    ):
        """get_memory_tier_status reflects available tiers."""
        # Only L3 exists
        profile_path.write_text("# L3", encoding="utf-8")
        status = ml.get_memory_tier_status()
        assert status["l3"] is True
        assert status["l2"] is False
        assert status["l1"] is False

    def test_compact_context_combines_l3_and_l2(
        self,
        monkeypatch_memory_dir: Path,
        profile_path: Path,
        rules_path: Path,
    ):
        """get_compact_context() returns L3 + L2 combined."""
        profile_path.write_text("# L3 content", encoding="utf-8")
        rules_path.write_text("# L2 content", encoding="utf-8")

        ctx = ml.get_compact_context()
        assert "L3 content" in ctx
        assert "L2 content" in ctx
        # There should be a separator between them
        assert "---" in ctx


# WOT-2026-008h: orchestrator prompt rename (5 prompts -> orchestrator_*).

_ORCH_RENAMES = {
    "launch_builder": "orchestrator_launch_builder",
    "session_bootstrap": "orchestrator_session_bootstrap",
    "session_close_chat": "orchestrator_session_close_chat",
    "destination_bootstrap": "orchestrator_destination_bootstrap",
    "refactor_bootstrap": "orchestrator_refactor_bootstrap",
}
_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


# WOT-2026-011d: full legacy stub retirement (5 orchestrator + audit_plan +
# review_manager). The stubs were repointed to canonical and deleted.

_RETIRED_STUBS_011D = {
    "audit_plan": "audit_ticket_contract",
    "destination_bootstrap": "orchestrator_destination_bootstrap",
    "launch_builder": "orchestrator_launch_builder",
    "refactor_bootstrap": "orchestrator_refactor_bootstrap",
    "review_manager": "manager_review",
    "session_bootstrap": "orchestrator_session_bootstrap",
    "session_close_chat": "orchestrator_session_close_chat",
}


class TestLegacyStubRetirement011d:
    """Proof rests on: stub deleted + canonical present + no operational
    consumer (MANIFEST + live docs) still points at the legacy name."""

    def test_all_seven_stubs_deleted(self):
        for legacy in _RETIRED_STUBS_011D:
            assert not (_PROMPTS / f"{legacy}.md").exists(), (
                f"{legacy}.md must be deleted (WOT-2026-011d)"
            )

    def test_all_canonicals_present(self):
        for canon in _RETIRED_STUBS_011D.values():
            assert (_PROMPTS / f"{canon}.md").exists(), f"missing canonical {canon}"

    def test_manifest_repointed_to_canonical(self):
        root = Path(__file__).resolve().parents[1]
        manifest = (root / "MANIFEST.distribute").read_text(encoding="utf-8")
        for legacy, canon in _RETIRED_STUBS_011D.items():
            assert f"prompts/{legacy}.md" not in manifest, (
                f"MANIFEST still lists retired stub {legacy}.md"
            )
            assert f"prompts/{canon}.md" in manifest, (
                f"MANIFEST missing canonical {canon}.md"
            )

    def test_live_doc_consumers_repointed(self):
        # The operational docs that pointed at a stub must now point at canonical.
        root = Path(__file__).resolve().parents[1]
        checks = {
            ".claude/rules/00-startup.md": "session_bootstrap",
            "PROJECT.md": "session_close_chat",
            "CLOSURE_MODEL.md": "session_bootstrap",
        }
        for rel, legacy in checks.items():
            text = (root / rel).read_text(encoding="utf-8")
            assert f"prompts/{legacy}.md" not in text, (
                f"{rel} still references retired stub {legacy}.md"
            )


class TestOrchestratorRename008h:
    """Migration proof rests on canonicals + stubs + source_prompt + rg, NOT on
    --check-naming (the legacy names are lexically valid, so naming stays green
    regardless of whether the migration happened)."""

    def test_canonical_prompts_exist(self):
        for canon in _ORCH_RENAMES.values():
            assert (_PROMPTS / f"{canon}.md").exists(), f"missing canonical {canon}"

    def test_legacy_stubs_are_retired(self):
        # WOT-2026-011d: the orchestrator legacy stubs were repointed and then
        # deleted (0 non-historical consumers). The canonicals carry the body.
        for legacy in _ORCH_RENAMES:
            path = _PROMPTS / f"{legacy}.md"
            assert not path.exists(), (
                f"legacy stub {legacy}.md must be retired (WOT-2026-011d)"
            )

    def test_builder_source_prompt_points_at_canonical(self):
        skill = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "builder-implement-from-plan"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert "source_prompt: prompts/orchestrator_launch_builder.md" in skill
        assert "source_prompt: prompts/launch_builder.md" not in skill

    def test_compat_not_dependent_on_known_legacy_names(self):
        # The orchestrator legacy names must NOT live in KNOWN_LEGACY_NAMES: they
        # are lexically valid on their own, so tolerance is not via hardcode.
        from scripts.discover_skills import KNOWN_LEGACY_NAMES

        for legacy in _ORCH_RENAMES:
            assert legacy not in KNOWN_LEGACY_NAMES

    def test_no_legacy_source_prompt_in_any_skill(self):
        # Negative/regression: no live skill may still bind to a legacy prompt.
        skills_dir = Path(__file__).resolve().parents[1] / "skills"
        for skill_file in skills_dir.rglob("SKILL.md"):
            content = skill_file.read_text(encoding="utf-8")
            for legacy in _ORCH_RENAMES:
                assert f"source_prompt: prompts/{legacy}.md" not in content, (
                    f"{skill_file} still binds to legacy {legacy}.md"
                )

    def test_no_live_prose_reference_to_legacy_names(self):
        """Regression for the Manager CHANGES finding: a live prose reference
        (bare `launch_builder.md` or `prompts/launch_builder.md`) in an
        operational consumer must not survive. Stubs keep their own legacy name
        (skipped), and historical docs (DEC, CHANGELOG) are out of scope.

        This is the test that would have caught orchestrator_pipeline.md:1082.
        """
        root = Path(__file__).resolve().parents[1]
        legacy_re = re.compile(
            r"(?<![\w/])(?:" + "|".join(re.escape(n) for n in _ORCH_RENAMES) + r")\.md"
        )
        # Live operational consumers (NOT stubs, NOT historical docs).
        live_consumers = [
            root / "prompts" / f"{c}.md" for c in _ORCH_RENAMES.values()
        ] + [
            root / "prompts" / "orchestrator_pipeline.md",
            root / "prompts" / "audit_complete_motor_destination.md",
            root / "prompts" / "audit_git_publication.md",
            root / "README.md",
            root / "QUICKSTART.md",
            root / "AGENTS.md",
            root / "CLAUDE.md",
        ]
        live_consumers += list((root / "skills").rglob("SKILL.md"))

        offenders = []
        for path in live_consumers:
            if not path.exists():
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                # A stub legitimately names itself in its "# Legacy alias:" header.
                if line.lstrip().startswith("# Legacy alias:"):
                    continue
                if legacy_re.search(line):
                    offenders.append(f"{path.name}:{i}: {line.strip()}")
        assert not offenders, "live legacy prose references survive:\n" + "\n".join(
            offenders
        )
