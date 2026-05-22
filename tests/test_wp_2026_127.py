"""
Tests for WP-2026-127: State revision, approval timeout and skill filtering.

Tests cover:
- OCC (Optimistic Concurrency Control) in supervisor.py
- Approval system with timeout in approval.py
- Skill filtering by role in skill_resolver.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bus.approval import (
    ApprovalPolicy,
    ApprovalReason,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalStore,
)
from bus.exceptions import (
    ApprovalExpiredError,
    ApprovalTimeoutPolicyError,
    ConcurrentStateError,
    SkillAccessDeniedError,
    SkillNotFoundError,
)
from bus.skill_resolver import SkillResolver, create_resolver


# =============================================================================
# Tests for bus/exceptions.py
# =============================================================================


def test_concurrent_state_error_message():
    """Test ConcurrentStateError produces correct error message."""
    exc = ConcurrentStateError(
        artifact_path="/test/path.json",
        expected_revision=123,
        actual_revision=456,
        ticket_id="WP-2026-127",
    )
    assert "Concurrent state conflict" in str(exc)
    assert "/test/path.json" in str(exc)
    assert "123" in str(exc)
    assert "456" in str(exc)
    assert "WP-2026-127" in str(exc)


def test_concurrent_state_error_without_ticket():
    """Test ConcurrentStateError works without ticket_id."""
    exc = ConcurrentStateError(
        artifact_path="/test/path.json",
        expected_revision=None,
        actual_revision=456,
    )
    assert "Concurrent state conflict" in str(exc)
    assert "ticket" not in str(exc)


def test_approval_expired_error_message():
    """Test ApprovalExpiredError produces correct error message."""
    exc = ApprovalExpiredError(
        approval_id="approval-123",
        ticket_id="WP-2026-127",
        timeout_seconds=300,
        elapsed_seconds=350.5,
    )
    assert "expired" in str(exc)
    assert "approval-123" in str(exc)
    assert "WP-2026-127" in str(exc)
    assert "300" in str(exc)
    assert "350" in str(exc)


def test_skill_not_found_error():
    """Test SkillNotFoundError with and without role."""
    exc = SkillNotFoundError(skill_name="/unknown", role="BUILDER")
    assert "/unknown" in str(exc)
    assert "BUILDER" in str(exc)

    exc_no_role = SkillNotFoundError(skill_name="/unknown")
    assert "/unknown" in str(exc_no_role)
    assert "role" not in str(exc_no_role)


def test_skill_access_denied_error():
    """Test SkillAccessDeniedError includes allowlist."""
    exc = SkillAccessDeniedError(
        skill_name="/admin", role="BUILDER", allowlist=["/impl", "/test"]
    )
    assert "/admin" in str(exc)
    assert "BUILDER" in str(exc)
    assert "/impl" in str(exc)


def test_approval_timeout_policy_error():
    """Test ApprovalTimeoutPolicyError for misconfigured policies."""
    exc = ApprovalTimeoutPolicyError(
        policy_name="invalid_policy", reason="timeout must be positive"
    )
    assert "invalid_policy" in str(exc)
    assert "timeout must be positive" in str(exc)


# =============================================================================
# Tests for bus/approval.py - ApprovalRequest
# =============================================================================


def test_approval_request_creation():
    """Test ApprovalRequest is created with correct defaults."""
    request = ApprovalRequest(
        approval_id="test-1",
        ticket_id="WP-2026-127",
        timeout_seconds=300,
    )
    assert request.approval_id == "test-1"
    assert request.ticket_id == "WP-2026-127"
    assert request.status == ApprovalStatus.PENDING
    assert request.reason is None
    assert request.timeout_seconds == 300
    assert request.is_pending() is True
    assert request.is_resolved() is False


def test_approval_request_resolve():
    """Test ApprovalRequest resolution."""
    request = ApprovalRequest(approval_id="test-1", ticket_id="WP-2026-127")
    request.resolve(
        status=ApprovalStatus.APPROVED,
        reason=ApprovalReason.HUMAN_APPROVED,
    )
    assert request.status == ApprovalStatus.APPROVED
    assert request.reason == ApprovalReason.HUMAN_APPROVED
    assert request.resolved_at is not None
    assert request.is_resolved() is True
    assert request.is_pending() is False


def test_approval_request_cannot_resolve_twice():
    """Test that resolving twice raises ValueError."""
    request = ApprovalRequest(approval_id="test-1", ticket_id="WP-2026-127")
    request.resolve(
        status=ApprovalStatus.APPROVED,
        reason=ApprovalReason.HUMAN_APPROVED,
    )
    with pytest.raises(ValueError, match="already resolved"):
        request.resolve(
            status=ApprovalStatus.REJECTED,
            reason=ApprovalReason.HUMAN_REJECTED,
        )


def test_approval_request_is_expired():
    """Test ApprovalRequest expiration detection."""
    # Create a request that is already expired (created 10 minutes ago)
    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    request = ApprovalRequest(
        approval_id="test-1",
        ticket_id="WP-2026-127",
        created_at=past_time.isoformat(),
        timeout_seconds=300,  # 5 minutes
    )
    assert request.is_expired() is True

    # Create a fresh request (not expired)
    fresh_request = ApprovalRequest(
        approval_id="test-2",
        ticket_id="WP-2026-127",
        timeout_seconds=600,  # 10 minutes
    )
    assert fresh_request.is_expired() is False


def test_approval_request_is_expired_resolved_request():
    """Test that resolved requests are never considered expired."""
    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    request = ApprovalRequest(
        approval_id="test-1",
        ticket_id="WP-2026-127",
        created_at=past_time.isoformat(),
        timeout_seconds=300,
        status=ApprovalStatus.APPROVED,
        reason=ApprovalReason.HUMAN_APPROVED,
    )
    assert request.is_expired() is False


def test_approval_request_to_from_dict():
    """Test ApprovalRequest serialization."""
    original = ApprovalRequest(
        approval_id="test-1",
        ticket_id="WP-2026-127",
        status=ApprovalStatus.PENDING,
        timeout_seconds=300,
        metadata={"key": "value"},
    )
    data = original.to_dict()
    restored = ApprovalRequest.from_dict(data)
    assert restored.approval_id == original.approval_id
    assert restored.ticket_id == original.ticket_id
    assert restored.status == original.status
    assert restored.timeout_seconds == original.timeout_seconds
    assert restored.metadata == original.metadata


# =============================================================================
# Tests for bus/approval.py - ApprovalPolicy
# =============================================================================


def test_approval_policy_creation():
    """Test ApprovalPolicy with valid configuration."""
    policy = ApprovalPolicy(
        policy_name="default",
        timeout_seconds=300,
        auto_resolve=True,
    )
    assert policy.policy_name == "default"
    assert policy.timeout_seconds == 300
    assert policy.auto_resolve is True


def test_approval_policy_invalid_timeout():
    """Test ApprovalPolicy rejects non-positive timeout."""
    with pytest.raises(ApprovalTimeoutPolicyError, match="timeout_seconds must be positive"):
        ApprovalPolicy(timeout_seconds=0)

    with pytest.raises(ApprovalTimeoutPolicyError, match="timeout_seconds must be positive"):
        ApprovalPolicy(timeout_seconds=-100)


def test_approval_policy_create_request():
    """Test ApprovalPolicy creates requests with correct timeout."""
    policy = ApprovalPolicy(policy_name="test", timeout_seconds=600)
    request = policy.create_request(
        approval_id="req-1",
        ticket_id="WP-2026-127",
        metadata={"test": True},
    )
    assert request.approval_id == "req-1"
    assert request.timeout_seconds == 600
    assert request.metadata == {"test": True}


def test_approval_policy_check_and_expire_auto_resolve():
    """Test ApprovalPolicy auto-resolves expired requests."""
    policy = ApprovalPolicy(
        policy_name="test",
        timeout_seconds=300,
        auto_resolve=True,
        auto_resolve_status=ApprovalStatus.EXPIRED,
    )

    # Create an expired request
    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    request = ApprovalRequest(
        approval_id="test-1",
        ticket_id="WP-2026-127",
        created_at=past_time.isoformat(),
        timeout_seconds=300,
    )

    # Check and expire
    result = policy.check_and_expire(request)
    assert result.status == ApprovalStatus.EXPIRED
    assert result.reason == ApprovalReason.TIMEOUT_EXPIRED


def test_approval_policy_check_and_expire_no_auto_resolve():
    """Test ApprovalPolicy raises ApprovalExpiredError when auto_resolve=False."""
    policy = ApprovalPolicy(
        policy_name="test",
        timeout_seconds=300,
        auto_resolve=False,
    )

    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    request = ApprovalRequest(
        approval_id="test-1",
        ticket_id="WP-2026-127",
        created_at=past_time.isoformat(),
        timeout_seconds=300,
    )

    with pytest.raises(ApprovalExpiredError, match="test-1"):
        policy.check_and_expire(request)


def test_approval_policy_check_and_expire_not_expired():
    """Test ApprovalPolicy doesn't modify non-expired requests."""
    policy = ApprovalPolicy(policy_name="test", timeout_seconds=600)

    # Fresh request (not expired)
    request = ApprovalRequest(
        approval_id="test-1",
        ticket_id="WP-2026-127",
        timeout_seconds=600,
    )

    result = policy.check_and_expire(request)
    assert result.status == ApprovalStatus.PENDING
    assert result.reason is None


def test_approval_policy_check_and_expire_already_resolved():
    """Test ApprovalPolicy doesn't modify already resolved requests."""
    policy = ApprovalPolicy(policy_name="test", timeout_seconds=300)

    request = ApprovalRequest(
        approval_id="test-1",
        ticket_id="WP-2026-127",
        status=ApprovalStatus.APPROVED,
        reason=ApprovalReason.HUMAN_APPROVED,
    )

    result = policy.check_and_expire(request)
    assert result.status == ApprovalStatus.APPROVED


# =============================================================================
# Tests for bus/approval.py - ApprovalStore
# =============================================================================


def test_approval_store_save_and_load(tmp_path):
    """Test ApprovalStore persists and loads requests."""
    store_path = tmp_path / "approvals" / "store.json"
    store = ApprovalStore(store_path=store_path)

    request = ApprovalRequest(
        approval_id="test-1",
        ticket_id="WP-2026-127",
        timeout_seconds=300,
    )
    store.save(request)

    loaded = store.load("test-1")
    assert loaded is not None
    assert loaded.approval_id == "test-1"
    assert loaded.ticket_id == "WP-2026-127"


def test_approval_store_load_nonexistent():
    """Test ApprovalStore returns None for nonexistent request."""
    store = ApprovalStore(store_path=Path("/nonexistent/path/store.json"))
    assert store.load("nonexistent") is None


def test_approval_store_delete(tmp_path):
    """Test ApprovalStore delete operation."""
    store_path = tmp_path / "approvals" / "store.json"
    store = ApprovalStore(store_path=store_path)

    request = ApprovalRequest(approval_id="test-1", ticket_id="WP-2026-127")
    store.save(request)

    assert store.delete("test-1") is True
    assert store.load("test-1") is None
    assert store.delete("test-1") is False  # Already deleted


def test_approval_store_list_by_ticket(tmp_path):
    """Test ApprovalStore lists requests by ticket."""
    store_path = tmp_path / "approvals" / "store.json"
    store = ApprovalStore(store_path=store_path)

    store.save(ApprovalRequest(approval_id="req-1", ticket_id="WP-2026-127"))
    store.save(ApprovalRequest(approval_id="req-2", ticket_id="WP-2026-127"))
    store.save(ApprovalRequest(approval_id="req-3", ticket_id="WP-2026-128"))

    requests = store.list_by_ticket("WP-2026-127")
    assert len(requests) == 2
    assert all(r.ticket_id == "WP-2026-127" for r in requests)


def test_approval_store_list_pending(tmp_path):
    """Test ApprovalStore lists only pending requests."""
    store_path = tmp_path / "approvals" / "store.json"
    store = ApprovalStore(store_path=store_path)

    pending = ApprovalRequest(approval_id="req-1", ticket_id="WP-2026-127")
    approved = ApprovalRequest(
        approval_id="req-2",
        ticket_id="WP-2026-127",
        status=ApprovalStatus.APPROVED,
        reason=ApprovalReason.HUMAN_APPROVED,
    )
    store.save(pending)
    store.save(approved)

    pending_list = store.list_pending()
    assert len(pending_list) == 1
    assert pending_list[0].approval_id == "req-1"


def test_approval_store_create_request(tmp_path):
    """Test ApprovalStore.create_request persists immediately."""
    store_path = tmp_path / "approvals" / "store.json"
    store = ApprovalStore(store_path=store_path)

    request = store.create_request(
        approval_id="req-1",
        ticket_id="WP-2026-127",
        metadata={"test": True},
    )
    assert request.approval_id == "req-1"

    # Verify it was persisted
    loaded = store.load("req-1")
    assert loaded is not None
    assert loaded.metadata == {"test": True}


def test_approval_store_resolve_request(tmp_path):
    """Test ApprovalStore.resolve_request updates persisted request."""
    store_path = tmp_path / "approvals" / "store.json"
    store = ApprovalStore(store_path=store_path)

    store.create_request(approval_id="req-1", ticket_id="WP-2026-127")

    resolved = store.resolve_request(
        approval_id="req-1",
        status=ApprovalStatus.APPROVED,
        reason=ApprovalReason.HUMAN_APPROVED,
    )
    assert resolved is not None
    assert resolved.status == ApprovalStatus.APPROVED

    # Verify persistence
    loaded = store.load("req-1")
    assert loaded.status == ApprovalStatus.APPROVED


def test_approval_store_check_and_expire_all(tmp_path):
    """Test ApprovalStore.check_and_expire_all expires all pending expired requests."""
    store_path = tmp_path / "approvals" / "store.json"
    store = ApprovalStore(store_path=store_path)

    # Create an expired request
    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    expired = ApprovalRequest(
        approval_id="req-expired",
        ticket_id="WP-2026-127",
        created_at=past_time.isoformat(),
        timeout_seconds=300,
    )
    # Create a fresh request
    fresh = ApprovalRequest(
        approval_id="req-fresh",
        ticket_id="WP-2026-127",
        timeout_seconds=600,
    )
    store.save(expired)
    store.save(fresh)

    expired_list = store.check_and_expire_all()
    assert len(expired_list) == 1
    assert expired_list[0].approval_id == "req-expired"
    assert expired_list[0].status == ApprovalStatus.EXPIRED

    # Fresh request should still be pending
    loaded_fresh = store.load("req-fresh")
    assert loaded_fresh.status == ApprovalStatus.PENDING


# =============================================================================
# Tests for bus/skill_resolver.py
# =============================================================================


def test_skill_resolver_default_allowlists():
    """Test SkillResolver uses default allowlists when no config."""
    resolver = SkillResolver(project_root=Path("/tmp/nonexistent"))
    assert "BUILDER" in resolver.role_allowlists
    assert "MANAGER" in resolver.role_allowlists
    assert "SUPERVISOR" in resolver.role_allowlists


def test_skill_resolver_get_allowed_skills_empty():
    """Test SkillResolver returns empty list when no skills discovered."""
    resolver = SkillResolver(
        project_root=Path("/tmp/nonexistent"),
        role_allowlists={"BUILDER": ["/impl"]},
    )
    # No skills directory exists, so should return empty
    allowed = resolver.get_allowed_skills("BUILDER")
    assert isinstance(allowed, list)


def test_skill_resolver_validate_skill_access_no_skills():
    """Test SkillResolver denies access when no skills available."""
    resolver = SkillResolver(
        project_root=Path("/tmp/nonexistent"),
        role_allowlists={"BUILDER": ["/impl"]},
    )
    # Should raise because skill not in discovered catalog
    with pytest.raises(SkillAccessDeniedError):
        resolver.validate_skill_access("/impl", "BUILDER", raise_on_denied=True)


def test_skill_resolver_get_allowed_triggers():
    """Test SkillResolver returns trigger map for allowed skills."""
    resolver = SkillResolver(
        project_root=Path("/tmp/nonexistent"),
        role_allowlists={"BUILDER": []},
    )
    triggers = resolver.get_allowed_triggers("BUILDER")
    assert isinstance(triggers, dict)
    assert len(triggers) == 0  # No skills discovered


def test_skill_resolver_filter_skills_for_prompt_no_skills():
    """Test SkillResolver returns message when no skills available."""
    resolver = SkillResolver(
        project_root=Path("/tmp/nonexistent"),
        role_allowlists={"BUILDER": []},
    )
    result = resolver.filter_skills_for_prompt("BUILDER")
    assert "No skills available" in result


def test_create_resolver_without_config():
    """Test create_resolver works without config file."""
    resolver = create_resolver(project_root=Path("/tmp/nonexistent"))
    assert isinstance(resolver, SkillResolver)


def test_skill_resolver_with_mocked_discovery(tmp_path):
    """Test SkillResolver with mocked skill discovery."""
    # Create a fake skills directory
    skills_dir = tmp_path / "skills"
    test_skill = skills_dir / "test_skill"
    test_skill.mkdir(parents=True)
    skill_file = test_skill / "SKILL.md"
    skill_file.write_text(
        "---\nname: Test Skill\ntriggers: [/test, /testing]\ndescription: A test skill\n---\n\nTest skill content\n"
    )

    resolver = SkillResolver(
        project_root=tmp_path,
        role_allowlists={"BUILDER": ["/test"]},
    )

    # Manually set discovered skills (bypassing discover_skills.py)
    resolver._discovered_skills = {
        "Test Skill": {
            "name": "Test Skill",
            "path": str(test_skill),
            "skill_file": str(skill_file),
            "triggers": ["/test", "/testing"],
            "description": "A test skill",
        }
    }

    allowed = resolver.get_allowed_skills("BUILDER")
    assert len(allowed) == 1
    assert allowed[0]["name"] == "Test Skill"

    # Validate access
    assert resolver.validate_skill_access("/test", "BUILDER") is True
    assert resolver.validate_skill_access("/testing", "BUILDER") is True
    assert resolver.validate_skill_access("/other", "BUILDER", raise_on_denied=False) is False


def test_skill_resolver_resolve_skill_by_name(tmp_path):
    """Test SkillResolver resolves skill by name."""
    skills_dir = tmp_path / "skills"
    test_skill = skills_dir / "test_skill"
    test_skill.mkdir(parents=True)
    skill_file = test_skill / "SKILL.md"
    skill_file.write_text(
        "---\nname: Test Skill\ntriggers: [/test]\n---\n\nContent\n"
    )

    resolver = SkillResolver(project_root=tmp_path)
    resolver._discovered_skills = {
        "Test Skill": {
            "name": "Test Skill",
            "path": str(test_skill),
            "skill_file": str(skill_file),
            "triggers": ["/test"],
        }
    }

    result = resolver.resolve_skill("Test Skill")
    assert result is not None
    assert result["name"] == "Test Skill"


def test_skill_resolver_resolve_skill_by_trigger(tmp_path):
    """Test SkillResolver resolves skill by trigger."""
    skills_dir = tmp_path / "skills"
    test_skill = skills_dir / "test_skill"
    test_skill.mkdir(parents=True)
    skill_file = test_skill / "SKILL.md"
    skill_file.write_text(
        "---\nname: Test Skill\ntriggers: [/test, /testing]\n---\n\nContent\n"
    )

    resolver = SkillResolver(project_root=tmp_path)
    resolver._discovered_skills = {
        "Test Skill": {
            "name": "Test Skill",
            "path": str(test_skill),
            "skill_file": str(skill_file),
            "triggers": ["/test", "/testing"],
        }
    }

    result = resolver.resolve_skill("/test")
    assert result is not None
    assert result["name"] == "Test Skill"


def test_skill_resolver_resolve_skill_not_found():
    """Test SkillResolver raises SkillNotFoundError for unknown skill."""
    resolver = SkillResolver(project_root=Path("/tmp/nonexistent"))
    resolver._discovered_skills = {}

    with pytest.raises(SkillNotFoundError, match="unknown_skill"):
        resolver.resolve_skill("unknown_skill")


def test_skill_resolver_resolve_skill_access_denied(tmp_path):
    """Test SkillResolver raises SkillAccessDeniedError for unauthorized access."""
    skills_dir = tmp_path / "skills"
    test_skill = skills_dir / "test_skill"
    test_skill.mkdir(parents=True)
    skill_file = test_skill / "SKILL.md"
    skill_file.write_text(
        "---\nname: Admin Skill\ntriggers: [/admin]\n---\n\nContent\n"
    )

    resolver = SkillResolver(
        project_root=tmp_path,
        role_allowlists={"BUILDER": ["/impl"]},  # No /admin
    )
    resolver._discovered_skills = {
        "Admin Skill": {
            "name": "Admin Skill",
            "path": str(test_skill),
            "skill_file": str(skill_file),
            "triggers": ["/admin"],
        }
    }

    with pytest.raises(SkillAccessDeniedError, match="Admin Skill"):
        resolver.resolve_skill("/admin", role="BUILDER")


# =============================================================================
# Tests for bus/supervisor.py - OCC (Optimistic Concurrency Control)
# =============================================================================


def test_supervisor_compute_revision(tmp_path):
    """Test supervisor computes consistent revisions."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    content = "test content"
    revision1 = supervisor._compute_revision(content)
    revision2 = supervisor._compute_revision(content)
    assert revision1 == revision2

    # Different content should produce different revision
    revision3 = supervisor._compute_revision("different content")
    assert revision3 != revision1


def test_supervisor_read_artifact_with_revision(tmp_path):
    """Test supervisor reads artifact with revision."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    # Non-existent file
    content, revision = supervisor._read_artifact_with_revision(
        collaboration_dir / "nonexistent.json"
    )
    assert content == ""
    assert revision is None

    # Existing file
    test_file = collaboration_dir / "test.json"
    test_content = '{"test": true}'
    test_file.write_text(test_content, encoding="utf-8")

    content, revision = supervisor._read_artifact_with_revision(test_file)
    assert content == test_content
    assert revision is not None


def test_supervisor_write_artifact_atomic(tmp_path):
    """Test supervisor writes artifact atomically."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    test_file = collaboration_dir / "test.json"
    new_content = '{"new": "content"}'

    revision = supervisor.write_artifact_atomic(test_file, new_content)
    assert revision is not None
    assert test_file.read_text(encoding="utf-8") == new_content


def test_supervisor_write_artifact_atomic_with_expected_revision(tmp_path):
    """Test supervisor OCC with correct expected revision."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    test_file = collaboration_dir / "test.json"
    initial_content = '{"initial": true}'
    test_file.write_text(initial_content, encoding="utf-8")

    _, current_revision = supervisor._read_artifact_with_revision(test_file)

    new_content = '{"updated": true}'
    revision = supervisor.write_artifact_atomic(
        test_file, new_content, expected_revision=current_revision
    )
    assert revision is not None
    assert test_file.read_text(encoding="utf-8") == new_content


def test_supervisor_write_artifact_atomic_concurrent_conflict(tmp_path):
    """Test supervisor raises ConcurrentStateError on revision mismatch."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    test_file = collaboration_dir / "test.json"
    initial_content = '{"initial": true}'
    test_file.write_text(initial_content, encoding="utf-8")

    # Use wrong expected revision
    wrong_revision = 12345

    with pytest.raises(ConcurrentStateError, match="Concurrent state conflict"):
        supervisor.write_artifact_atomic(
            test_file,
            '{"new": "content"}',
            expected_revision=wrong_revision,
            max_retries=1,  # No retries for fast test
        )


def test_supervisor_get_approval_store(tmp_path):
    """Test supervisor creates approval store."""
    from bus.supervisor import SequentialTicketSupervisor

    collaboration_dir = tmp_path / ".agent" / "collaboration"
    runtime_dir = tmp_path / ".agent" / "runtime"
    collaboration_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    supervisor = SequentialTicketSupervisor(
        project_root=tmp_path,
        collaboration_dir=collaboration_dir,
        runtime_dir=runtime_dir,
        auto_sync=False,
    )

    store = supervisor.get_approval_store()
    assert isinstance(store, ApprovalStore)
    assert store.store_path.parent.exists()
