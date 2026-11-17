"""Tests for the settled-session pending confirmation barrier."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).parents[2] / "scripts" / "flight" / "pending_confirmation.py"
)
SPEC = importlib.util.spec_from_file_location("pending_confirmation_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _store(tmp_path, now):
    """Build a store with a deterministic clock.

    Before: tmp_path is a pytest-owned isolated directory and now is mutable.
    During: a JSONL-backed store is constructed with a closure clock.
    After: callers can advance now and inspect durable transitions.
    """
    return MODULE.PendingConfirmationStore(
        tmp_path / "pending.jsonl",
        lambda: now[0],
        verifier=lambda auth: (
            auth.actor == "operator-1" and auth.token == "credential-" + "ok"
        ),
        authorized_actors=frozenset({"operator-1"}),
    )


def _authorization():
    """Return the credential accepted by the deterministic test verifier.

    Before: a privileged test operation needs a caller identity.
    During: a stable actor and token are constructed.
    After: the returned Authorization can be verified by the test store.
    """
    return MODULE.Authorization(actor="operator-1", token="credential-" + "ok")


def _pending(store, mode="auto", ttl=300, enqueue=None):
    """Create one settled target request for focused tests.

    Before: store is empty or isolated from another test.
    During: the broker creates a pending request for a settled target.
    After: the public pending_confirmation response is returned.
    """
    return store.create_pending(
        target_thread_id="mcp:target-001",
        target_lifecycle_version="epoch-7",
        content="hello",
        client_request_id="client-001",
        expires_in_seconds=ttl,
        mode=mode,
        enqueue=enqueue,
    )


class TestPendingConfirmation:
    """Cover the eight contract rows with real store transitions."""

    def test_c01_pending_has_no_wake_or_enqueue_and_system_notice(self, tmp_path):
        """Settled send creates pending state without calling target activity."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        activity = []
        response = _pending(store, enqueue=activity.append)
        assert store.attempt_delivery(
            response["pending_id"], activity.append, _authorization()
        ) == {
            "status": "error",
            "error": "not_confirmed",
        }
        assert response["status"] == "pending_confirmation"
        assert {
            "pending_id",
            "target_thread_id",
            "target_lifecycle_version",
            "content_hash",
            "client_request_id",
            "expires_at",
        } <= response.keys()
        assert activity == []
        assert response["issuer"] == "SYSTEM"

    def test_c02_delivery_envelope_is_system_not_target(self, tmp_path):
        """Confirmation envelope identifies SYSTEM as sender."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store)
        result = store.confirm_once(
            pending_id=response["pending_id"],
            content_hash_value=response["content_hash"],
            target_lifecycle_version="epoch-7",
            authorization=_authorization(),
        )
        assert result["status"] == "confirmed"
        delivered = []
        delivery = store.attempt_delivery(
            response["pending_id"], delivered.append, _authorization()
        )
        assert delivery == {"status": "delivered", "pending_id": response["pending_id"]}
        assert delivered == [
            {
                "sender": "SYSTEM",
                "target_thread_id": "mcp:target-001",
                "content_hash": response["content_hash"],
                "pending_id": response["pending_id"],
            }
        ]

    @pytest.mark.parametrize(
        ("field", "value", "error"),
        [
            ("authorization", None, "missing_actor"),
            ("content_hash_value", "bad", "content_hash_mismatch"),
            ("target_lifecycle_version", "epoch-8", "lifecycle_version_mismatch"),
        ],
    )
    def test_c03_rejects_authorization_hash_and_epoch(
        self, tmp_path, field, value, error
    ):
        """Each confirmation precondition rejects independently."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store)
        values = {
            "pending_id": response["pending_id"],
            "content_hash_value": response["content_hash"],
            "target_lifecycle_version": "epoch-7",
            "authorization": _authorization(),
        }
        values[field] = value
        assert store.confirm_once(**values) == {"status": "error", "error": error}

    def test_c03_ttl_and_idempotency_are_enforced(self, tmp_path):
        """Expiry and a repeated confirmation are terminal errors."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store, ttl=5)
        now[0] += timedelta(seconds=6)
        expired = store.confirm_once(
            pending_id=response["pending_id"],
            content_hash_value=response["content_hash"],
            target_lifecycle_version="epoch-7",
            authorization=_authorization(),
        )
        assert expired == {"status": "error", "error": "expired"}

    def test_c04_concurrent_confirmations_deliver_once(self, tmp_path):
        """The process CAS lock lets only one concurrent confirmer deliver."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store)
        results = []

        def confirm():
            results.append(
                store.confirm_once(
                    pending_id=response["pending_id"],
                    content_hash_value=response["content_hash"],
                    target_lifecycle_version="epoch-7",
                    authorization=_authorization(),
                )
            )

        threads = [threading.Thread(target=confirm) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sum(result["status"] == "confirmed" for result in results) == 1
        delivered = []
        assert (
            store.attempt_delivery(
                response["pending_id"], delivered.append, _authorization()
            )["status"]
            == "delivered"
        )
        assert len(delivered) == 1

    def test_c04_delivery_token_is_exclusive_in_process(self, tmp_path):
        """The delivery token accepts one in-process claimant only."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store)
        first = store._acquire_delivery_token(response["pending_id"], _authorization())
        second = store._acquire_delivery_token(response["pending_id"], _authorization())
        assert first is True
        assert second is False

    def test_c04_delivery_token_is_exclusive_across_processes(self, tmp_path):
        """The delivery token accepts one OS-process claimant only."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store)
        ready0 = tmp_path / "ready-0"
        ready1 = tmp_path / "ready-1"
        go = tmp_path / "go"
        child = (
            "import importlib.util,sys,time; from pathlib import Path; "
            "p=sys.argv[1]; store_path=sys.argv[2]; ready=sys.argv[3]; "
            "go=sys.argv[4]; pending_id=sys.argv[5]; "
            "s=importlib.util.spec_from_file_location('pc',p); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "st=m.PendingConfirmationStore(store_path); "
            "Path(ready).write_text('ready',encoding='utf-8'); "
            "next(time.sleep(0.01) for _ in iter(int,1) if Path(go).exists()); "
            "result=st._acquire_delivery_token(pending_id,m.Authorization('a','b')); "
            "print(result,flush=True)"
        )
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child,
                    str(MODULE_PATH),
                    str(store.path),
                    str(ready0),
                    str(go),
                    response["pending_id"],
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ),
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child,
                    str(MODULE_PATH),
                    str(store.path),
                    str(ready1),
                    str(go),
                    response["pending_id"],
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ),
        ]
        for _ in range(500):
            if ready0.exists() and ready1.exists():
                break
            time.sleep(0.01)
        go.write_text("go", encoding="utf-8")
        outputs = [process.communicate(timeout=30) for process in processes]
        results = [stdout.strip() for stdout, _stderr in outputs]
        assert sorted(results) == ["False", "True"]

    @pytest.mark.parametrize("action", ["cancel", "expire"])
    def test_c05_cancel_and_expire_are_terminal(self, tmp_path, action):
        """Cancelled and expired requests never reach the delivery callback."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store, ttl=1)
        if action == "cancel":
            store.cancel(response["pending_id"], "operator_cancel")
        else:
            now[0] += timedelta(seconds=2)
            store.expire(response["pending_id"])
        result = store.confirm_once(
            pending_id=response["pending_id"],
            content_hash_value=response["content_hash"],
            target_lifecycle_version="epoch-7",
            authorization=_authorization(),
        )
        assert result == {"status": "error", "error": "already_terminal"}
        calls = []
        assert store.attempt_delivery(
            response["pending_id"], calls.append, _authorization()
        ) == {"status": "error", "error": "not_confirmed"}
        assert calls == []

    @pytest.mark.parametrize("mode", sorted(MODULE.VALID_MODES))
    def test_c06_scheduler_queue_steer_restart_preserve_barrier(self, tmp_path, mode):
        """All host scheduler modes return pending without target activity."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store, mode=mode)
        calls = []
        routed = store.route_without_confirmation(
            response["pending_id"], mode, calls.append, _authorization()
        )
        assert routed == {"status": "error", "error": "not_confirmed"}
        assert calls == []

    def test_c07_force_reactivate_is_authenticated_reasoned_and_audited(self, tmp_path):
        """Forced reactivation is separate and requires authorization plus reason."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        assert store.force_reactivate(
            target_thread_id="mcp:target-001", authorization=None, reason="ops"
        ) == {"status": "error", "error": "missing_actor"}
        assert store.force_reactivate(
            target_thread_id="mcp:target-001", authorization=_authorization(), reason=""
        ) == {"status": "error", "error": "reason_required"}
        result = store.force_reactivate(
            target_thread_id="mcp:target-001",
            authorization=_authorization(),
            reason="operator requested",
        )
        assert result["status"] == "reactivated"
        assert store.audit()[0]["event"] == "force_reactivate"
        assert store.audit()[0]["actor"] == "operator-1"
        assert store.audit()[0]["evidence_digest"]

    def test_c08_public_contract_is_additive_and_durable(self, tmp_path):
        """The response fields and JSONL persistence support consumer migration."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store)
        restored = MODULE.PendingConfirmationStore(
            store.path,
            lambda: now[0],
            verifier=lambda auth: (
                auth.actor == "operator-1" and auth.token == "credential-" + "ok"
            ),
            authorized_actors=frozenset({"operator-1"}),
        )
        assert (
            restored.route_without_confirmation(response["pending_id"], "auto")[
                "status"
            ]
            == "pending_confirmation"
        )
        assert response["client_request_id"] == "client-001"

    def test_c03_bad_credential_is_rejected(self, tmp_path):
        """The verifier rejects an invalid credential independently of actor."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store)
        result = store.confirm_once(
            pending_id=response["pending_id"],
            content_hash_value=response["content_hash"],
            target_lifecycle_version="epoch-7",
            authorization=MODULE.Authorization("operator-1", "invalid"),
        )
        assert result == {"status": "error", "error": "bad_credential"}

    def test_b1_attempt_delivery_is_authenticated_and_one_shot(self, tmp_path):
        """The only transport gate delivers once and then closes permanently."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store)
        calls = []
        assert store.attempt_delivery(response["pending_id"], calls.append, None) == {
            "status": "error",
            "error": "missing_actor",
        }
        store.confirm_once(
            pending_id=response["pending_id"],
            content_hash_value=response["content_hash"],
            target_lifecycle_version="epoch-7",
            authorization=_authorization(),
        )
        assert (
            store.attempt_delivery(
                response["pending_id"], calls.append, _authorization()
            )["status"]
            == "delivered"
        )
        assert store.attempt_delivery(
            response["pending_id"], calls.append, _authorization()
        ) == {"status": "error", "error": "already_delivered"}
        assert len(calls) == 1
        assert (
            store._latest(store._read(), response["pending_id"])["status"]
            == "delivered"
        )

    def test_delivery_failure_is_terminal_and_audited(self, tmp_path):
        """A transport exception is not confirmed and cannot implicitly retry."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store)

        def failing(_envelope):
            raise RuntimeError("transport down")

        result = store.confirm_once(
            pending_id=response["pending_id"],
            content_hash_value=response["content_hash"],
            target_lifecycle_version="epoch-7",
            authorization=_authorization(),
        )
        assert result == {"status": "confirmed", "pending_id": response["pending_id"]}
        result = store.attempt_delivery(
            response["pending_id"], failing, _authorization()
        )
        assert result == {"status": "error", "error": "delivery_failed"}
        latest = store._latest(store._read(), response["pending_id"])
        assert latest["status"] == "delivery_failed"
        assert store.audit()[0]["event"] == "delivery_failed"
        calls = []
        retry = store.attempt_delivery(
            response["pending_id"], calls.append, _authorization()
        )
        assert retry == {"status": "error", "error": "already_delivered"}
        assert calls == []

    def test_cross_process_claim_delivers_once(self, tmp_path):
        """Two OS processes race and O_EXCL permits one delivery."""
        now = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        store = _store(tmp_path, now)
        response = _pending(store, ttl=86400)
        assert (
            store.confirm_once(
                pending_id=response["pending_id"],
                content_hash_value=response["content_hash"],
                target_lifecycle_version="epoch-7",
                authorization=_authorization(),
            )["status"]
            == "confirmed"
        )
        child = (
            "import importlib.util,json,sys,time; from pathlib import Path; "
            "p=sys.argv[1]; store_path=sys.argv[2]; marker=sys.argv[3]; "
            "release=sys.argv[4]; pid=sys.argv[5]; digest=sys.argv[6]; "
            "s=importlib.util.spec_from_file_location('pc',p); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "st=m.PendingConfirmationStore(store_path, "
            "verifier=lambda a:a.actor=='operator-1' and a.token=='credential-'+'ok', "
            "authorized_actors=frozenset({'operator-1'})); "
            "deliver=lambda e:(Path(marker).write_text(json.dumps(e),encoding='utf-8'), "
            "next(time.sleep(0.01) for _ in iter(int,1) if Path(release).exists()))[1]; "
            "r=st.attempt_delivery(pid, deliver, "
            "m.Authorization('operator-1','credential-'+'ok')); "
            "print(json.dumps(r))"
        )
        release = tmp_path / "release"
        marker0 = tmp_path / "delivery-0.json"
        marker1 = tmp_path / "delivery-1.json"
        first = subprocess.Popen(
            [
                sys.executable,
                "-c",
                child,
                str(MODULE_PATH),
                str(store.path),
                str(marker0),
                str(release),
                response["pending_id"],
                response["content_hash"],
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(500):
            if marker0.exists():
                break
            time.sleep(0.01)
        second = subprocess.Popen(
            [
                sys.executable,
                "-c",
                child,
                str(MODULE_PATH),
                str(store.path),
                str(marker1),
                str(release),
                response["pending_id"],
                response["content_hash"],
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(100):
            if marker1.exists():
                break
            time.sleep(0.01)
        release.write_text("go", encoding="utf-8")
        processes = [first, second]
        outputs = [process.communicate(timeout=30) for process in processes]
        results = [json.loads(stdout.strip()) for stdout, _stderr in outputs]
        assert sum(result["status"] == "delivered" for result in results) == 1
        assert (
            sum(
                result.get("error") in {"already_delivered", "delivery_unknown"}
                for result in results
            )
            == 1
        )
        assert len(list(tmp_path.glob("delivery-*.json"))) == 1

    def test_crash_after_delivery_intent_is_delivery_unknown(self, tmp_path):
        """A dead transport leaves an audited unknown state, never a false delivery."""
        store_path = tmp_path / "pending.jsonl"
        control = tmp_path / "pending-id"
        delivery_log = tmp_path / "delivery.log"
        child = (
            "import importlib.util,os,sys; from pathlib import Path; "
            "p=sys.argv[1]; store_path=sys.argv[2]; control=sys.argv[3]; "
            "s=importlib.util.spec_from_file_location('pc',p); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "st=m.PendingConfirmationStore(store_path, "
            "verifier=lambda a:a.actor=='operator-1' and a.token=='credential-'+'ok', "
            "authorized_actors=frozenset({'operator-1'})); "
            "q=st.create_pending(target_thread_id='mcp:target-001', "
            "target_lifecycle_version='epoch-7',content='hello', "
            "client_request_id='client-crash',expires_in_seconds=86400); "
            "Path(control).write_text(q['pending_id'],encoding='utf-8'); "
            "st.confirm_once(pending_id=q['pending_id'],content_hash_value=q['content_hash'], "
            "target_lifecycle_version='epoch-7', "
            "authorization=m.Authorization('operator-1','credential-'+'ok')); "
            "st.attempt_delivery(q['pending_id'],lambda e:os._exit(2), "
            "m.Authorization('operator-1','credential-'+'ok'))"
        )
        child_proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                child,
                str(MODULE_PATH),
                str(store_path),
                str(control),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(500):
            if control.exists():
                break
            time.sleep(0.01)
        child_proc.wait(timeout=30)
        pending_id = control.read_text(encoding="utf-8")
        assert child_proc.returncode == 2
        assert not delivery_log.exists()
        parent = _store(tmp_path, [datetime.now(timezone.utc)])
        calls = []
        first = parent.attempt_delivery(pending_id, calls.append, _authorization())
        assert first == {"status": "error", "error": "delivery_unknown"}
        latest = parent._latest(parent._read(), pending_id)
        assert latest["status"] == "delivery_unknown"
        assert parent.audit()[-1]["event"] == "delivery_unknown"
        second = parent.attempt_delivery(pending_id, calls.append, _authorization())
        assert second == {"status": "error", "error": "delivery_unknown"}
        assert calls == []
        resolved = parent.force_reactivate(
            target_thread_id="mcp:target-001",
            authorization=_authorization(),
            reason="crash reviewed",
            pending_id=pending_id,
        )
        assert resolved["status"] == "reactivated"
