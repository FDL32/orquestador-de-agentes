"""
Approval System - Configurable timeout and resolution for human approvals.

WP-2026-127: Implements approval requests with timeout policy, expiration
tracking, and canonical resolution with reason codes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .exceptions import ApprovalExpiredError, ApprovalTimeoutPolicyError


class ApprovalStatus(str, Enum):
    """Status of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalReason(str, Enum):
    """Reason codes for approval resolution."""

    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"
    TIMEOUT_EXPIRED = "timeout_expired"
    AUTO_APPROVED = "auto_approved"
    AUTO_REJECTED = "auto_rejected"
    CANCELLED_BY_USER = "cancelled_by_user"
    CANCELLED_BY_SYSTEM = "cancelled_by_system"


@dataclass(slots=True)
class ApprovalRequest:
    """Represents a human approval request with timeout policy.

    Before: Approvals had no timeout or expiration tracking.
    During: Each request has created_at, timeout_seconds, and status tracking.
    After: Expired approvals are resolved with EXPIRED status and TIMEOUT_EXPIRED reason.

    Attributes:
        approval_id: Unique identifier for this approval request.
        ticket_id: Ticket ID associated with this approval.
        status: Current status of the approval request.
        reason: Reason code for the resolution (if resolved).
        created_at: ISO timestamp when the request was created.
        timeout_seconds: Timeout in seconds for this approval.
        resolved_at: ISO timestamp when the request was resolved (if resolved).
        metadata: Additional metadata for the approval request.
    """

    approval_id: str
    ticket_id: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    reason: ApprovalReason | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    timeout_seconds: int = 300
    resolved_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_pending(self) -> bool:
        """Check if the approval is still pending."""
        return self.status == ApprovalStatus.PENDING

    def is_resolved(self) -> bool:
        """Check if the approval has been resolved."""
        return self.status in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.CANCELLED,
        }

    def is_expired(self, current_time: datetime | None = None) -> bool:
        """Check if the approval has expired based on timeout policy.

        Args:
            current_time: Optional current time for testing. Defaults to now.

        Returns:
            True if the approval has expired, False otherwise.
        """
        if self.is_resolved():
            return False
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        created = datetime.fromisoformat(self.created_at)
        elapsed = (current_time - created).total_seconds()
        return elapsed >= self.timeout_seconds

    def resolve(
        self,
        status: ApprovalStatus,
        reason: ApprovalReason,
        resolved_at: str | None = None,
    ) -> None:
        """Resolve the approval request with a status and reason.

        Args:
            status: Final status of the approval.
            reason: Reason code for the resolution.
            resolved_at: Optional ISO timestamp. Defaults to now.

        Raises:
            ValueError: If attempting to resolve an already resolved request.
        """
        if self.is_resolved():
            raise ValueError(
                f"Approval {self.approval_id} is already resolved with "
                f"status={self.status.value}, reason={self.reason}"
            )
        self.status = status
        self.reason = reason
        self.resolved_at = resolved_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        # Convert enums to their string values for JSON serialization
        result["status"] = self.status.value
        if self.reason:
            result["reason"] = self.reason.value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRequest:
        """Create from dictionary."""
        return cls(
            approval_id=str(data.get("approval_id", "")),
            ticket_id=str(data.get("ticket_id", "")),
            status=ApprovalStatus(str(data.get("status", "pending"))),
            reason=ApprovalReason(data["reason"]) if data.get("reason") else None,
            created_at=str(
                data.get("created_at", datetime.now(timezone.utc).isoformat())
            ),
            timeout_seconds=int(data.get("timeout_seconds", 300)),
            resolved_at=data.get("resolved_at"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class ApprovalPolicy:
    """Configurable timeout policy for approvals.

    Before: Single hardcoded timeout for all approvals.
    During: Policies can be defined per escalation type with different timeouts.
    After: Each approval request uses the appropriate policy based on type.

    Attributes:
        policy_name: Name of the policy (e.g., "default", "human_gate", "urgent").
        timeout_seconds: Timeout in seconds for this policy.
        auto_resolve: Whether to auto-resolve expired approvals.
        auto_resolve_status: Status to apply on auto-resolve (default: EXPIRED).
    """

    policy_name: str = "default"
    timeout_seconds: int = 300
    auto_resolve: bool = True
    auto_resolve_status: ApprovalStatus = ApprovalStatus.EXPIRED

    def __post_init__(self) -> None:
        """Validate the policy configuration."""
        if self.timeout_seconds <= 0:
            raise ApprovalTimeoutPolicyError(
                self.policy_name,
                f"timeout_seconds must be positive, got {self.timeout_seconds}",
            )
        if self.auto_resolve and self.auto_resolve_status not in {
            ApprovalStatus.EXPIRED,
        }:
            raise ApprovalTimeoutPolicyError(
                self.policy_name,
                f"Invalid auto_resolve_status: {self.auto_resolve_status.value}",
            )

    def create_request(
        self,
        approval_id: str,
        ticket_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Create a new approval request with this policy's timeout.

        Args:
            approval_id: Unique ID for the new request.
            ticket_id: Ticket ID associated with the request.
            metadata: Optional metadata for the request.

        Returns:
            New ApprovalRequest with this policy's configuration.
        """
        return ApprovalRequest(
            approval_id=approval_id,
            ticket_id=ticket_id,
            timeout_seconds=self.timeout_seconds,
            metadata=metadata or {},
        )

    def check_and_expire(
        self, request: ApprovalRequest, current_time: datetime | None = None
    ) -> ApprovalRequest:
        """Check if a request has expired and auto-resolve if configured.

        Args:
            request: ApprovalRequest to check.
            current_time: Optional current time for testing.

        Returns:
            The same request, potentially modified if auto-resolved.

        Raises:
            ApprovalExpiredError: If the request expired and auto_resolve is False.
        """
        if not request.is_pending():
            return request

        if not request.is_expired(current_time):
            return request

        # Request has expired
        if self.auto_resolve:
            request.resolve(
                status=self.auto_resolve_status,
                reason=ApprovalReason.TIMEOUT_EXPIRED,
            )
        else:
            raise ApprovalExpiredError(
                approval_id=request.approval_id,
                ticket_id=request.ticket_id,
                timeout_seconds=self.timeout_seconds,
                elapsed_seconds=(
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(request.created_at)
                ).total_seconds(),
            )

        return request


class ApprovalStore:
    """Persistent store for approval requests.

    Before: Approval state was ephemeral or scattered across files.
    During: All approvals are persisted to a JSON store with atomic writes.
    After: Approvals survive restarts and can be queried by ticket or status.

    Attributes:
        store_path: Path to the JSON store file.
        policy: Default approval policy for new requests.
    """

    def __init__(
        self,
        store_path: Path,
        policy: ApprovalPolicy | None = None,
    ):
        self.store_path = Path(store_path)
        self.policy = policy or ApprovalPolicy()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_store(self) -> dict[str, dict[str, Any]]:
        """Read the approval store from disk."""
        if not self.store_path.exists():
            return {}
        try:
            content = self.store_path.read_text(encoding="utf-8")
            return json.loads(content)
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_store(self, data: dict[str, dict[str, Any]]) -> None:
        """Write the approval store atomically."""
        import os
        import tempfile

        fd, temp_path = tempfile.mkstemp(
            dir=str(self.store_path.parent),
            prefix="approvals_",
            suffix=".json.tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, str(self.store_path))
        except Exception:
            import contextlib

            with contextlib.suppress(OSError):
                os.unlink(temp_path)
            raise

    def save(self, request: ApprovalRequest) -> None:
        """Save an approval request to the store."""
        store = self._read_store()
        store[request.approval_id] = request.to_dict()
        self._write_store(store)

    def load(self, approval_id: str) -> ApprovalRequest | None:
        """Load an approval request by ID."""
        store = self._read_store()
        data = store.get(approval_id)
        return ApprovalRequest.from_dict(data) if data else None

    def delete(self, approval_id: str) -> bool:
        """Delete an approval request by ID."""
        store = self._read_store()
        if approval_id not in store:
            return False
        del store[approval_id]
        self._write_store(store)
        return True

    def list_by_ticket(self, ticket_id: str) -> list[ApprovalRequest]:
        """List all approval requests for a ticket."""
        store = self._read_store()
        return [
            ApprovalRequest.from_dict(data)
            for data in store.values()
            if data.get("ticket_id") == ticket_id
        ]

    def list_pending(self) -> list[ApprovalRequest]:
        """List all pending approval requests."""
        store = self._read_store()
        requests = []
        for data in store.values():
            request = ApprovalRequest.from_dict(data)
            if request.is_pending():
                requests.append(request)
        return requests

    def check_and_expire_all(self) -> list[ApprovalRequest]:
        """Check all pending requests and expire those past timeout.

        Returns:
            List of requests that were expired in this call.
        """
        expired_requests = []
        store = self._read_store()
        modified = False

        for approval_id, data in store.items():
            request = ApprovalRequest.from_dict(data)
            if request.is_pending() and request.is_expired():
                self.policy.check_and_expire(request)
                store[approval_id] = request.to_dict()
                expired_requests.append(request)
                modified = True

        if modified:
            self._write_store(store)

        return expired_requests

    def create_request(
        self,
        approval_id: str,
        ticket_id: str,
        metadata: dict[str, Any] | None = None,
        policy: ApprovalPolicy | None = None,
    ) -> ApprovalRequest:
        """Create and persist a new approval request.

        Args:
            approval_id: Unique ID for the new request.
            ticket_id: Ticket ID associated with the request.
            metadata: Optional metadata for the request.
            policy: Optional policy override for this request.

        Returns:
            The newly created ApprovalRequest, already persisted.
        """
        effective_policy = policy or self.policy
        request = effective_policy.create_request(
            approval_id=approval_id,
            ticket_id=ticket_id,
            metadata=metadata,
        )
        self.save(request)
        return request

    def resolve_request(
        self,
        approval_id: str,
        status: ApprovalStatus,
        reason: ApprovalReason,
    ) -> ApprovalRequest | None:
        """Resolve an existing approval request.

        Args:
            approval_id: ID of the request to resolve.
            status: Final status to apply.
            reason: Reason code for the resolution.

        Returns:
            The resolved request, or None if not found.
        """
        request = self.load(approval_id)
        if request is None:
            return None

        request.resolve(status=status, reason=reason)
        self.save(request)
        return request
