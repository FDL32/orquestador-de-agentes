"""
Bus Exceptions - Custom exceptions for the event bus system.

WP-2026-127: Defines exceptions for concurrent state conflicts,
approval expiration, and skill validation errors.
"""

from __future__ import annotations

from pathlib import Path


class ConcurrentStateError(Exception):
    """Raised when a state write conflicts with an expected revision.

    Before: State writes could overwrite concurrent modifications silently.
    During: Writer provides expectedRevision; bus compares with current revision.
    After: Write fails with ConcurrentStateError if revision mismatch detected.

    Attributes:
        artifact_path: Path to the artifact that had the conflict.
        expected_revision: The revision the writer expected.
        actual_revision: The actual current revision of the artifact.
        ticket_id: Ticket ID associated with the conflict.
    """

    def __init__(
        self,
        artifact_path: str,
        expected_revision: int | str | None,
        actual_revision: int | str | None,
        ticket_id: str | None = None,
    ):
        self.artifact_path = artifact_path
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        self.ticket_id = ticket_id
        message = (
            f"Concurrent state conflict for {artifact_path}: "
            f"expected revision {expected_revision!r}, "
            f"got {actual_revision!r}"
        )
        if ticket_id:
            message += f" (ticket: {ticket_id})"
        super().__init__(message)


class ApprovalExpiredError(Exception):
    """Raised when an approval request has expired per timeout policy.

    Before: Approval requests could remain pending indefinitely.
    During: ApprovalPolicy checks timeout; expired requests raise this error.
    After: Expired approvals are resolved with EXPIRED reason, not APPROVED/REJECTED.

    Attributes:
        approval_id: ID of the expired approval request.
        ticket_id: Ticket ID associated with the approval.
        timeout_seconds: The configured timeout that was exceeded.
        elapsed_seconds: How long the approval has been pending.
    """

    def __init__(
        self,
        approval_id: str,
        ticket_id: str,
        timeout_seconds: int,
        elapsed_seconds: float,
    ):
        self.approval_id = approval_id
        self.ticket_id = ticket_id
        self.timeout_seconds = timeout_seconds
        self.elapsed_seconds = elapsed_seconds
        super().__init__(
            f"Approval {approval_id} for ticket {ticket_id} expired: "
            f"timeout={timeout_seconds}s, elapsed={elapsed_seconds:.1f}s"
        )


class SkillNotFoundError(Exception):
    """Raised when a referenced skill cannot be found or validated.

    Before: Missing skills caused silent failures or runtime errors.
    During: SkillResolver validates skill references before use.
    After: Invalid skill references raise SkillNotFoundError early.

    Attributes:
        skill_name: Name or trigger of the missing skill.
        role: Role that requested the skill (optional).
    """

    def __init__(self, skill_name: str, role: str | None = None):
        self.skill_name = skill_name
        self.role = role
        message = f"Skill not found: {skill_name}"
        if role:
            message += f" (requested by role: {role})"
        super().__init__(message)


class SkillAccessDeniedError(Exception):
    """Raised when a role attempts to use a skill not in its allowlist.

    Before: Roles could access any skill in the catalog.
    During: SkillResolver filters skills by role allowlist.
    After: Unauthorized skill access raises SkillAccessDeniedError.

    Attributes:
        skill_name: Name of the skill that was denied.
        role: Role that attempted access.
        allowlist: The role's configured allowlist (for debugging).
    """

    def __init__(self, skill_name: str, role: str, allowlist: list[str] | None = None):
        self.skill_name = skill_name
        self.role = role
        self.allowlist = allowlist
        message = f"Skill access denied: {skill_name} for role {role}"
        if allowlist:
            message += f" (allowlist: {allowlist})"
        super().__init__(message)


class ApprovalTimeoutPolicyError(Exception):
    """Raised when an approval timeout policy is misconfigured.

    Before: Invalid timeout configs could cause silent failures.
    During: ApprovalPolicy validates timeout configuration on load.
    After: Invalid policies raise ApprovalTimeoutPolicyError at startup.

    Attributes:
        policy_name: Name of the misconfigured policy.
        reason: Description of the configuration error.
    """

    def __init__(self, policy_name: str, reason: str):
        self.policy_name = policy_name
        self.reason = reason
        super().__init__(f"Approval timeout policy '{policy_name}' invalid: {reason}")


class EmptySkillCatalogError(Exception):
    """Raised when the skill catalog is empty after discovery.

    Before: Empty catalogs were treated as normal, causing silent failures.
    During: create_resolver() validates that at least one skill was discovered.
    After: Empty catalogs raise EmptySkillCatalogError as infrastructure error.

    Attributes:
        project_root: Root path where skills were searched.
        skills_dir: Path to the skills directory.
    """

    def __init__(self, project_root: Path, skills_dir: Path | None = None):
        self.project_root = project_root
        self.skills_dir = skills_dir
        message = f"Empty skill catalog at {project_root}"
        if skills_dir:
            message += f" (skills_dir: {skills_dir})"
        message += (
            ". Check that skills/ directory contains valid SKILL.md files, "
            "or add knowledge docs to .agent/microagents/."
        )
        super().__init__(message)
