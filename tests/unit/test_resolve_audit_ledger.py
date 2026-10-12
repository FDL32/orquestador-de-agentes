#!/usr/bin/env python3
"""Tests for resolve_audit_ledger (WOT-2026-054c).

Tests the append-only ledger resolver for audit adjudications.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from scripts.resolve_audit_ledger import (
    _compute_bytes_sha256,
    _compute_sha256,
    _extract_event_number,
    _extract_ts_from_filename,
    _find_incoherent_condition_blocks,
    _parse_report,
    _validate_event,
    resolve_ledger,
)


# --- Helpers ---


def _make_report(ts: str, verdict: str = "APROBADO", **extra: object) -> dict:
    """Create a minimal audit report dict."""
    base = {
        "verdict": verdict,
        "predicate": {
            "schema_valido": {"cumple": True},
            "dag_aciclico": {"cumple": True},
        },
        "isolation": {"b1": "fresh-context", "b3_read_only": True},
        **extra,
    }
    return base


def _make_event(
    *,
    event_type: str = "VERDICT_SUPERSEDED",
    target_artifact: str,
    target_sha256: str,
    target_json_sha256: str | None = None,
    resulting_status: str = "INVALIDADO",
    reason: str = "Test supersession",
    emitted_by: str = "test_auditor",
    timestamp: str = "2026-08-11T00:00:00Z",
    supersedes_event: str | None = None,
    supersedes_artifact: str | None = None,
    **extra: object,
) -> dict:
    """Create a minimal event dict."""
    base = {
        "event_type": event_type,
        "target_artifact": target_artifact,
        "target_sha256": target_sha256,
        "resulting_status": resulting_status,
        "reason": reason,
        "emitted_by": emitted_by,
        "timestamp": timestamp,
    }
    if target_json_sha256:
        base["target_json_sha256"] = target_json_sha256
    if supersedes_event:
        base["supersedes_event"] = supersedes_event
    if supersedes_artifact:
        base["supersedes_artifact"] = supersedes_artifact
    base.update(extra)
    return base


def _write_json(path: Path, data: dict) -> None:
    """Write a dict as JSON to a file."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# --- Tests: helpers ---


class TestExtractTsFromFilename:
    def test_valid(self) -> None:
        assert (
            _extract_ts_from_filename("audit_autonomous_batch_20260810-2313.json")
            == "20260810-2313"
        )

    def test_invalid(self) -> None:
        assert _extract_ts_from_filename("batch_run_20260810.json") is None

    def test_event_file(self) -> None:
        assert (
            _extract_ts_from_filename(
                "audit_autonomous_batch_20260810-2313.event_1.json"
            )
            == "20260810-2313"
        )


class TestExtractEventNumber:
    def test_valid(self) -> None:
        assert (
            _extract_event_number("audit_autonomous_batch_20260810-2313.event_1.json")
            == 1
        )
        assert (
            _extract_event_number("audit_autonomous_batch_20260810-2313.event_42.json")
            == 42
        )

    def test_invalid(self) -> None:
        assert (
            _extract_event_number("audit_autonomous_batch_20260810-2313.json") is None
        )

    def test_not_json(self) -> None:
        assert (
            _extract_event_number("audit_autonomous_batch_20260810-2313.event_1.md")
            is None
        )


class TestComputeSha256:
    def test_deterministic(self) -> None:
        data = {"a": 1, "b": 2}
        h1 = _compute_sha256(data)
        h2 = _compute_sha256(data)
        assert h1 == h2

    def test_order_independent(self) -> None:
        h1 = _compute_sha256({"a": 1, "b": 2})
        h2 = _compute_sha256({"b": 2, "a": 1})
        assert h1 == h2

    def test_different_data(self) -> None:
        h1 = _compute_sha256({"a": 1})
        h2 = _compute_sha256({"a": 2})
        assert h1 != h2


class TestComputeBytesSha256:
    def test_basic(self) -> None:
        h = _compute_bytes_sha256(b"hello")
        assert len(h) == 64  # SHA-256 hex digest

    def test_deterministic(self) -> None:
        assert _compute_bytes_sha256(b"test") == _compute_bytes_sha256(b"test")


class TestParseReport:
    def test_valid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "test.json"
        _write_json(p, {"verdict": "APROBADO"})
        data, err = _parse_report(p)
        assert err is None
        assert data is not None
        assert data["verdict"] == "APROBADO"

    def test_nonexistent(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent.json"
        data, err = _parse_report(p)
        assert data is None
        assert err is not None
        assert "Cannot read" in err

    def test_invalid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        data, err = _parse_report(p)
        assert data is None
        assert err is not None
        assert "Cannot parse" in err


class TestValidateEvent:
    def test_valid_event(self) -> None:
        original_sha = "abc123"
        event = _make_event(
            target_artifact="audit_autonomous_batch_20260810-2313.json",
            target_sha256=original_sha,
            supersedes_artifact="audit_autonomous_batch_20260810-2313.json",
        )
        errors = _validate_event(
            event,
            expected_target="audit_autonomous_batch_20260810-2313.json",
            previous_bytes_sha256=original_sha,
            previous_json_sha256="def456",
        )
        assert errors == []

    def test_missing_fields(self) -> None:
        event = {"event_type": "VERDICT_SUPERSEDED"}  # missing many required
        errors = _validate_event(
            event,
            expected_target="x",
            previous_bytes_sha256="y",
            previous_json_sha256="z",
        )
        assert len(errors) > 0
        assert any("Missing required fields" in e for e in errors)

    def test_invalid_verdict(self) -> None:
        event = _make_event(
            target_artifact="x",
            target_sha256="y",
            resulting_status="NOT_A_REAL_VERDICT",
            supersedes_artifact="x",
        )
        errors = _validate_event(
            event,
            expected_target="x",
            previous_bytes_sha256="y",
            previous_json_sha256="z",
        )
        assert any("resulting_status" in e for e in errors)

    def test_wrong_target(self) -> None:
        event = _make_event(
            target_artifact="wrong_report.json",
            target_sha256="y",
            supersedes_artifact="wrong_report.json",
        )
        errors = _validate_event(
            event,
            expected_target="correct_report.json",
            previous_bytes_sha256="y",
            previous_json_sha256="z",
        )
        assert any("target_artifact" in e for e in errors)

    def test_sha256_mismatch(self) -> None:
        event = _make_event(
            target_artifact="x",
            target_sha256="wrong_hash",
            supersedes_artifact="x",
        )
        errors = _validate_event(
            event,
            expected_target="x",
            previous_bytes_sha256="correct_hash",
            previous_json_sha256="z",
        )
        assert any("target_sha256" in e for e in errors)

    def test_json_sha256_mismatch(self) -> None:
        event = _make_event(
            target_artifact="x",
            target_sha256="y",
            target_json_sha256="wrong_json_hash",
            supersedes_artifact="x",
        )
        errors = _validate_event(
            event,
            expected_target="x",
            previous_bytes_sha256="y",
            previous_json_sha256="correct_json_hash",
        )
        assert any("target_json_sha256" in e for e in errors)

    def test_no_supersedes(self) -> None:
        event = _make_event(
            target_artifact="x",
            target_sha256="y",
        )
        # Remove both supersedes fields
        event.pop("supersedes_event", None)
        event.pop("supersedes_artifact", None)
        errors = _validate_event(
            event,
            expected_target="x",
            previous_bytes_sha256="y",
            previous_json_sha256="z",
        )
        assert any("supersedes" in e for e in errors)


# --- Tests: resolve_ledger ---


class TestResolveLedger:
    def test_not_found(self, tmp_path: Path) -> None:
        result = resolve_ledger(tmp_path, "20260810-9999")
        assert result.status == "NOT_FOUND"
        assert result.errors

    def test_parse_error(self, tmp_path: Path) -> None:
        p = tmp_path / "audit_autonomous_batch_20260810-2313.json"
        p.write_text("not json at all", encoding="utf-8")
        result = resolve_ledger(tmp_path, "20260810-2313")
        assert result.status == "PARSE_ERROR"
        assert result.errors

    def test_original_no_events(self, tmp_path: Path) -> None:
        report = _make_report("20260810-2313")
        _write_json(tmp_path / "audit_autonomous_batch_20260810-2313.json", report)

        result = resolve_ledger(tmp_path, "20260810-2313")
        assert result.status == "ORIGINAL"
        assert result.chain_length == 0
        assert result.original_data is not None
        assert result.original_data["verdict"] == "APROBADO"

    def test_superseded_by_one_event(self, tmp_path: Path) -> None:
        ts = "20260810-2313"
        original_name = f"audit_autonomous_batch_{ts}.json"

        report = _make_report(ts)
        _write_json(tmp_path / original_name, report)

        original_bytes = (tmp_path / original_name).read_bytes()
        original_bytes_sha = _compute_bytes_sha256(original_bytes)
        original_json_sha = _compute_sha256(report)

        event = _make_event(
            target_artifact=original_name,
            target_sha256=original_bytes_sha,
            target_json_sha256=original_json_sha,
            supersedes_artifact=original_name,
            resulting_status="INVALIDADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_1.json", event)

        result = resolve_ledger(tmp_path, ts)
        assert result.status == "SUPERSEDED"
        assert result.chain_length == 1
        assert result.current_event_data is not None
        assert result.current_event_data["resulting_status"] == "INVALIDADO"

    def test_chained_events(self, tmp_path: Path) -> None:
        ts = "20260810-2313"
        original_name = f"audit_autonomous_batch_{ts}.json"

        report = _make_report(ts)
        _write_json(tmp_path / original_name, report)

        original_bytes = (tmp_path / original_name).read_bytes()
        original_sha = _compute_bytes_sha256(original_bytes)
        original_json_sha = _compute_sha256(report)

        # Event 1: INVALIDADO
        event1 = _make_event(
            target_artifact=original_name,
            target_sha256=original_sha,
            target_json_sha256=original_json_sha,
            supersedes_artifact=original_name,
            resulting_status="INVALIDADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_1.json", event1)

        # Event 2: re-approves
        event1_bytes = (
            tmp_path / f"audit_autonomous_batch_{ts}.event_1.json"
        ).read_bytes()
        event1_sha = _compute_bytes_sha256(event1_bytes)
        event1_json_sha = _compute_sha256(event1)

        event2 = _make_event(
            target_artifact=original_name,
            target_sha256=event1_sha,
            target_json_sha256=event1_json_sha,
            supersedes_event=f"audit_autonomous_batch_{ts}.event_1.json",
            resulting_status="APROBADO",
            reason="Re-approval after review",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_2.json", event2)

        result = resolve_ledger(tmp_path, ts)
        assert result.status == "SUPERSEDED"
        assert result.chain_length == 2
        assert result.current_event_data is not None
        assert result.current_event_data["resulting_status"] == "APROBADO"

    def test_chain_gap_returns_indeterminado(self, tmp_path: Path) -> None:
        ts = "20260810-2313"
        original_name = f"audit_autonomous_batch_{ts}.json"

        report = _make_report(ts)
        _write_json(tmp_path / original_name, report)

        original_bytes = (tmp_path / original_name).read_bytes()
        original_sha = _compute_bytes_sha256(original_bytes)
        original_json_sha = _compute_sha256(report)

        # Skip event_1, create event_2
        event2 = _make_event(
            target_artifact=original_name,
            target_sha256=original_sha,
            target_json_sha256=original_json_sha,
            supersedes_artifact=original_name,
            resulting_status="INVALIDADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_2.json", event2)

        result = resolve_ledger(tmp_path, ts)
        assert result.status == "INDETERMINADO"
        assert any("gap" in e.lower() for e in result.errors)

    def test_invalid_event_returns_indeterminado(self, tmp_path: Path) -> None:
        ts = "20260810-2313"
        original_name = f"audit_autonomous_batch_{ts}.json"

        report = _make_report(ts)
        _write_json(tmp_path / original_name, report)

        # Event with wrong hash
        event = _make_event(
            target_artifact=original_name,
            target_sha256="wrong_hash",
            supersedes_artifact=original_name,
            resulting_status="INVALIDADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_1.json", event)

        result = resolve_ledger(tmp_path, ts)
        assert result.status == "INDETERMINADO"
        assert any("target_sha256" in e for e in result.errors)

    def test_broken_chain_stops(self, tmp_path: Path) -> None:
        ts = "20260810-2313"
        original_name = f"audit_autonomous_batch_{ts}.json"

        report = _make_report(ts)
        _write_json(tmp_path / original_name, report)

        original_bytes = (tmp_path / original_name).read_bytes()
        original_sha = _compute_bytes_sha256(original_bytes)
        original_json_sha = _compute_sha256(report)

        # Event 1: valid
        event1 = _make_event(
            target_artifact=original_name,
            target_sha256=original_sha,
            target_json_sha256=original_json_sha,
            supersedes_artifact=original_name,
            resulting_status="INVALIDADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_1.json", event1)

        # Event 2: invalid (wrong hash)
        event2 = _make_event(
            target_artifact=original_name,
            target_sha256="broken_hash",
            supersedes_event=f"audit_autonomous_batch_{ts}.event_1.json",
            resulting_status="APROBADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_2.json", event2)

        result = resolve_ledger(tmp_path, ts)
        assert result.status == "INDETERMINADO"
        assert result.chain_length == 1  # stopped at event 1

    def test_subject_isolation(self, tmp_path: Path) -> None:
        """Events from different subjects don't interfere."""
        ts1 = "20260810-2313"
        ts2 = "20260810-2314"

        # Two different originals
        _write_json(
            tmp_path / f"audit_autonomous_batch_{ts1}.json",
            _make_report(ts1),
        )
        _write_json(
            tmp_path / f"audit_autonomous_batch_{ts2}.json",
            _make_report(ts2, verdict="CAMBIOS_NECESARIOS"),
        )

        result1 = resolve_ledger(tmp_path, ts1)
        result2 = resolve_ledger(tmp_path, ts2)

        assert result1.status == "ORIGINAL"
        assert result1.original_data["verdict"] == "APROBADO"
        assert result2.status == "ORIGINAL"
        assert result2.original_data["verdict"] == "CAMBIOS_NECESARIOS"


# --- Tests: DoD criteria ---


class TestDoD:
    """Verify the DoD binary criteria from WOT-2026-054c."""

    def test_c_original_never_modified(self, tmp_path: Path) -> None:
        """DoD (c): emitting event_1 leaves the original's sha256 intact."""
        ts = "20260810-2313"
        original_name = f"audit_autonomous_batch_{ts}.json"

        report = _make_report(ts)
        _write_json(tmp_path / original_name, report)

        original_bytes_before = (tmp_path / original_name).read_bytes()
        original_sha_before = _compute_bytes_sha256(original_bytes_before)

        # Emit event_1
        original_sha = _compute_bytes_sha256(original_bytes_before)
        original_json_sha = _compute_sha256(report)

        event = _make_event(
            target_artifact=original_name,
            target_sha256=original_sha,
            target_json_sha256=original_json_sha,
            supersedes_artifact=original_name,
            resulting_status="INVALIDADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_1.json", event)

        # Verify original is unchanged
        original_bytes_after = (tmp_path / original_name).read_bytes()
        original_sha_after = _compute_bytes_sha256(original_bytes_after)
        assert original_sha_before == original_sha_after

        # Verify resolver sees the chain correctly
        result = resolve_ledger(tmp_path, ts)
        assert result.status == "SUPERSEDED"
        assert result.chain_length == 1

    def test_d_resolver_returns_last_valid(self, tmp_path: Path) -> None:
        """DoD (d): chain original -> event_1 -> event_2 returns last valid."""
        ts = "20260810-2313"
        original_name = f"audit_autonomous_batch_{ts}.json"

        report = _make_report(ts)
        _write_json(tmp_path / original_name, report)

        original_bytes = (tmp_path / original_name).read_bytes()
        original_sha = _compute_bytes_sha256(original_bytes)
        original_json_sha = _compute_sha256(report)

        event1 = _make_event(
            target_artifact=original_name,
            target_sha256=original_sha,
            target_json_sha256=original_json_sha,
            supersedes_artifact=original_name,
            resulting_status="INVALIDADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_1.json", event1)

        event1_bytes = (
            tmp_path / f"audit_autonomous_batch_{ts}.event_1.json"
        ).read_bytes()
        event1_sha = _compute_bytes_sha256(event1_bytes)
        event1_json_sha = _compute_sha256(event1)

        event2 = _make_event(
            target_artifact=original_name,
            target_sha256=event1_sha,
            target_json_sha256=event1_json_sha,
            supersedes_event=f"audit_autonomous_batch_{ts}.event_1.json",
            resulting_status="APROBADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_2.json", event2)

        result = resolve_ledger(tmp_path, ts)
        assert result.status == "SUPERSEDED"
        assert result.current_event_data["resulting_status"] == "APROBADO"
        assert result.chain_length == 2

    def test_d_double_mutation_independent(self, tmp_path: Path) -> None:
        """DoD (e): TWO independent mutations."""
        ts = "20260810-2313"
        original_name = f"audit_autonomous_batch_{ts}.json"

        report = _make_report(ts)
        _write_json(tmp_path / original_name, report)

        original_bytes = (tmp_path / original_name).read_bytes()
        original_sha = _compute_bytes_sha256(original_bytes)
        original_json_sha = _compute_sha256(report)

        # Mutation 1: add event_1
        event1 = _make_event(
            target_artifact=original_name,
            target_sha256=original_sha,
            target_json_sha256=original_json_sha,
            supersedes_artifact=original_name,
            resulting_status="INVALIDADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_1.json", event1)

        result1 = resolve_ledger(tmp_path, ts)
        assert result1.status == "SUPERSEDED"
        assert result1.chain_length == 1
        assert result1.current_event_data["resulting_status"] == "INVALIDADO"

        # Mutation 2: add event_2
        event1_bytes = (
            tmp_path / f"audit_autonomous_batch_{ts}.event_1.json"
        ).read_bytes()
        event1_sha = _compute_bytes_sha256(event1_bytes)
        event1_json_sha = _compute_sha256(event1)

        event2 = _make_event(
            target_artifact=original_name,
            target_sha256=event1_sha,
            target_json_sha256=event1_json_sha,
            supersedes_event=f"audit_autonomous_batch_{ts}.event_1.json",
            resulting_status="APROBADO",
        )
        _write_json(tmp_path / f"audit_autonomous_batch_{ts}.event_2.json", event2)

        result2 = resolve_ledger(tmp_path, ts)
        assert result2.status == "SUPERSEDED"
        assert result2.chain_length == 2
        assert result2.current_event_data["resulting_status"] == "APROBADO"


# --- Tests: ORIGINAL_INCOHERENTE (WOT-2026-054l) ---


_SUBJECT_TS = "20260810-2313"
_SUBJECT_NAME = f"audit_autonomous_batch_{_SUBJECT_TS}.json"


def _resolve_workspace_reports_dir() -> Path | None:
    """Locate the WOT-2026-054l workspace reports dir holding the live fixture.

    Before: The motor is portable; the destination reports dir is external to
            it, so the real fixture is not guaranteed to exist.
    During: Prefers AGENT_PROJECT_ROOT when set, then the sibling directory
            literally named per the ticket. Read-only; no mutation.
    After: Returns the reports dir when it holds the fixture, else None so the
           caller can skip rather than assert against a missing artifact.
    """
    candidates: list[Path] = []
    env_root = os.environ.get("AGENT_PROJECT_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(
        Path(__file__).resolve().parents[2].parent / "orquestador_de_agentes_workspace"
    )
    for root in candidates:
        reports = root / "orchestrator_pipeline" / "reports"
        if (reports / _SUBJECT_NAME).exists():
            return reports
    return None


class TestIncoherenceHelper:
    def test_detects_false_green_in_nested_block(self) -> None:
        predicate = {"suite_final_verde": {"sha_match": False, "cumple": True}}
        hits = _find_incoherent_condition_blocks(predicate)
        assert len(hits) == 1
        assert hits[0]["sha_match"] is False

    def test_concordant_block_not_flagged(self) -> None:
        predicate = {"suite_final_verde": {"sha_match": True, "cumple": True}}
        assert _find_incoherent_condition_blocks(predicate) == []

    def test_absent_fields_not_flagged(self) -> None:
        predicate = {"schema_valido": {"cumple": True, "command": "x"}}
        assert _find_incoherent_condition_blocks(predicate) == []


class TestOriginalIncoherente:
    def test_original_without_events_is_incoherente_not_original(
        self, tmp_path: Path
    ) -> None:
        """MUTATION (DoD c): the LIVE fixture, no events -> ORIGINAL_INCOHERENTE."""
        reports = _resolve_workspace_reports_dir()
        if reports is None:
            pytest.skip("workspace fixture not present in this checkout")

        shutil.copy(reports / _SUBJECT_NAME, tmp_path / _SUBJECT_NAME)

        result = resolve_ledger(tmp_path, _SUBJECT_TS)
        assert result.status == "ORIGINAL_INCOHERENTE"
        assert result.status != "ORIGINAL"
        assert result.chain_length == 0
        assert result.errors

    def test_original_with_event_is_superseded_control(self, tmp_path: Path) -> None:
        """CONTROL: LIVE fixture + live event_1 -> SUPERSEDED; check does not fire."""
        reports = _resolve_workspace_reports_dir()
        if reports is None:
            pytest.skip("workspace fixture not present in this checkout")

        shutil.copy(reports / _SUBJECT_NAME, tmp_path / _SUBJECT_NAME)
        event_name = f"audit_autonomous_batch_{_SUBJECT_TS}.event_1.json"
        shutil.copy(reports / event_name, tmp_path / event_name)

        result = resolve_ledger(tmp_path, _SUBJECT_TS)
        assert result.status == "SUPERSEDED"
        assert result.chain_length == 1
        assert result.current_event_data["resulting_status"] == "CAMBIOS_NECESARIOS"

    def test_synthetic_concordant_sha_match_true_stays_original(
        self, tmp_path: Path
    ) -> None:
        """CONTROL NEGATIVO: sha_match=true + cumple=true -> ORIGINAL (no false positive)."""
        report = _make_report(_SUBJECT_TS)
        report["predicate"]["suite_final_verde"] = {"sha_match": True, "cumple": True}
        _write_json(tmp_path / _SUBJECT_NAME, report)

        result = resolve_ledger(tmp_path, _SUBJECT_TS)
        assert result.status == "ORIGINAL"

    def test_synthetic_without_sha_match_field_stays_original(
        self, tmp_path: Path
    ) -> None:
        """CONTROL NEGATIVO 2: no sha_match/cumple block at all -> ORIGINAL."""
        report = _make_report(_SUBJECT_TS)
        _write_json(tmp_path / _SUBJECT_NAME, report)

        result = resolve_ledger(tmp_path, _SUBJECT_TS)
        assert result.status == "ORIGINAL"
