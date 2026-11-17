# Pending confirmation API

## Purpose

`scripts/flight/pending_confirmation.py` adds a confirmation barrier for a
message addressed to a settled session. It does not wake the target, enqueue a
run, retry delivery, or use the target identity as the sender.

## Public API

`PendingConfirmationStore(path, clock=None, verifier=..., authorized_actors=...)`
stores JSONL records. Confirmation claims use a durable sibling claim file
created with `os.O_CREAT | os.O_EXCL`; the claim is never removed. This is the
cross-process CAS boundary for confirmation. The JSONL transition is
atomically replaced after the claim.

`create_pending(...)` returns the additive response state
`pending_confirmation` with `pending_id`, `target_thread_id`,
`target_lifecycle_version`, `content_hash`, `client_request_id`,
`expires_at`, `issuer=SYSTEM`, and the requested host mode (`auto`, `queue`,
`steer`, or `restart`).

`Authorization(actor, token)` is the caller credential. The injected `verifier`
must validate it; an optional actor allowlist adds an identity boundary. A
missing actor returns `missing_actor`, an actor outside the allowlist returns
`unauthorized_actor`, and a missing or invalid credential returns
`bad_credential`. `confirm_once(...)` also requires the exact content hash and
current lifecycle version. Rejections are returned as `error` with one of
`unknown_pending_id`, `missing_actor`, `unauthorized_actor`,
`bad_credential`, `content_hash_mismatch`, `lifecycle_version_mismatch`,
`expired`, or `already_terminal`.

`confirm_once` never invokes transport. The exclusive confirmer marks the
request `confirmed`; the single `attempt_delivery` gate then requires the same
verified authorization and consumes a durable sibling
`<store>.<pending_id>.delivered` token created with `os.O_CREAT | os.O_EXCL`
before invoking transport. The first successful call records terminal
`delivered` and an audit entry. Later calls return `already_delivered` without
touching transport, including calls from other OS processes.

A durable `delivery_intent` transition is written after consuming the delivery
token and before invoking transport. If a later attempt finds that intent
without a `delivered` or `delivery_failed` result, it appends
`delivery_unknown` audit evidence and returns `delivery_unknown`; it never
claims a successful delivery. `force_reactivate(pending_id=...)` is the only
operation that may resolve that state, and its actor, reason, and evidence
digest are audited.

A transport exception records terminal `delivery_failed`, appends an auditable
failure record, returns `delivery_failed`, and cannot be retried implicitly.
Confirmation and delivery transitions retain the verified actor and credential
evidence digest; audit entries expose those fields for review. This is
at-most-once end-to-end delivery with explicit `confirmed`, `delivery_intent`,
`delivered`, `delivery_failed`, and `delivery_unknown` states. A process crash
after intent but before a transport result therefore remains visibly unknown,
not falsely delivered.

`cancel(pending_id)` and `expire(pending_id)` are terminal non-delivery
transitions and intentionally do not require `Authorization`: they are local
state cleanup operations. They are no-ops once a request is already
`confirmed`, `delivery_intent`, `delivered`, `delivery_failed`, or
`delivery_unknown`. `attempt_delivery(pending_id, transport, authorization)` is the
only public transport gate and refuses every state except `confirmed`; missing
or invalid authorization returns `missing_actor`, `unauthorized_actor`, or
`bad_credential`. The
`route_without_confirmation(pending_id, mode, transport, authorization)`
adapter models scheduler, queued-run, steer, restart, and retry paths and
always calls that gate with the same authorization; a pending request therefore
reaches no transport.

`force_reactivate(...)` is a separate authenticated operation. It requires a
non-empty reason, records the verified actor and a SHA-256 digest of the
credential evidence, and appends a consultable audit record returned by
`audit()`. It is never called by `confirm_once`.

## Consumer migration

Consumers should treat `pending_confirmation` as an additive send result. They
must show the SYSTEM/broker notice and retain `pending_id`, the hash, and the
lifecycle version. They should call `confirm_once` only after explicit
authorization and should handle named confirmation errors as terminal or
retryable according to the error, without waking the target implicitly.

Existing `enviado` consumers remain compatible when they continue to branch on
the existing result values; new consumers must add the `pending_confirmation`
branch before assuming delivery occurred. No scheduler or retry loop may turn
that branch into a direct enqueue.

## Store writer boundary

The durable claim and delivery tokens are safe across OS processes. The JSONL
store itself is not a general multi-writer database: simultaneous creators or
unrelated transitions may fail closed with `pending store cannot be written`
when their atomic replaces collide. Callers must retry the store operation at
the orchestration layer or serialize writers; no silent loss is claimed for
that unsupported multi-writer case.
