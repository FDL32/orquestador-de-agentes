"""WOT-2026-013s: barreras de regresion para el saneamiento estricto del
observations.jsonl del repo_motor.

Cada test cubre un fallo concreto introducido/arreglado en 013s y falla SIN el
fix correspondiente (FAIL-without) y pasa CON el (PASS-with). Las fixtures son
reducciones realistas de entradas reales del corpus del MOTOR (no mocks vacios):

- Guard keep-intact demasiado laxo: dejaba intactas entradas con domain+applies_to
  validos pero sin source_ticket, o con impact/anti_pattern_id invalidos, de modo
  que --strict seguia fallando y el migrador nunca las reparaba. Mismo patron que
  el gap de applies_to que arreglo 013o.
- Mapeo Eje B: cada dominio no-enum del MOTOR (uncovered_by_MAP) debe mapear a un
  canonico EXPLICITO via DOMAIN_MIGRATION_MAP / DOMAIN_MIGRATION_TOPIC_OVERRIDE,
  nunca caer al inferidor-por-topic-substring.
- Normalizacion de impact: prosa mal ubicada en el campo enum impact se normaliza
  a un valor valido SIN tocar el signal.
- Line endings: el migrador no debe reescribir el JSONL canonico (LF) a CRLF.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest


# Motor root importable (tests/unit -> motor root is parents[2]).
_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts.migrate_observations import (  # noqa: E402
    DOMAIN_MIGRATION_MAP,
    DOMAIN_MIGRATION_TOPIC_OVERRIDE,
    _has_valid_anti_pattern_id,
    _has_valid_impact,
    _has_valid_source_ticket,
    _is_canonical_and_valid,
    _normalize_impact,
    run_migration,
)
from scripts.validate_observations import validate_file  # noqa: E402


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _write_observations(path: Path, entries: list[dict]) -> None:
    lines = [json.dumps(e, ensure_ascii=False) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def observations_path(tmp_path: Path) -> Path:
    mdir = tmp_path / "memory"
    mdir.mkdir(parents=True, exist_ok=True)
    return mdir / "observations.jsonl"


# ═══════════════════════════════════════════════════════════════════════════
# Guard: keep-intact must require source_ticket / valid impact / valid AP id
# ═══════════════════════════════════════════════════════════════════════════


class TestKeepIntactGuardStrictness:
    """The keep-intact guard must reject entries that --strict would reject.

    Pre-013s the guard checked domain+applies_to only, so the MOTOR's entries
    with a valid domain/applies_to but a missing source_ticket (or a free-text
    impact, or a non-AP-NN anti_pattern_id) were kept intact and never repaired,
    leaving --strict red.
    """

    def _entry_missing_source_ticket(self) -> dict:
        # Valid domain + applies_to, but NO source_ticket (real MOTOR pattern).
        return {
            "timestamp": "2026-06-22T10:00:00Z",
            "topic": "missing-source-ticket-case",
            "domain": "review-quality",
            "signal": "Entry with valid domain/applies_to but no source_ticket.",
            "source": "human_audit_WOT-2026-139",
            "applies_to": "mixed",
            "confidence": 0.9,
        }

    def _entry_freetext_impact(self) -> dict:
        return {
            "timestamp": "2026-06-22T10:00:00Z",
            "topic": "freetext-impact-case",
            "domain": "delivery-hygiene",
            "signal": "Entry whose impact holds a sentence instead of low/med/high.",
            "source": "session-2026-05-25",
            "applies_to": "all",
            "confidence": 0.9,
            "impact": "prevents false closes and validator mismatch",
            "source_ticket": "WOT-2026-013m",
        }

    def _entry_bad_anti_pattern_id(self) -> dict:
        return {
            "timestamp": "2026-06-22T10:00:00Z",
            "topic": "bad-ap-id-case",
            "domain": "delivery-hygiene",
            "signal": "Entry with a non-canonical anti_pattern_id AP-D01.",
            "source": "session-2026-05-25",
            "applies_to": "all",
            "confidence": 0.9,
            "anti_pattern_id": "AP-D01",
            "source_ticket": "WOT-2026-010a",
        }

    # --- helper-level: FAIL-without ---

    def test_helper_rejects_missing_source_ticket(self):
        assert _has_valid_source_ticket(self._entry_missing_source_ticket()) is False
        assert _has_valid_source_ticket({"source_ticket": "WOT-2026-013s"}) is True

    def test_helper_rejects_freetext_impact(self):
        assert _has_valid_impact(self._entry_freetext_impact()) is False
        assert _has_valid_impact({"impact": "medium"}) is True
        # impact is optional: absence is valid.
        assert _has_valid_impact({}) is True

    def test_helper_rejects_bad_anti_pattern_id(self):
        assert _has_valid_anti_pattern_id(self._entry_bad_anti_pattern_id()) is False
        assert _has_valid_anti_pattern_id({"anti_pattern_id": "AP-09"}) is True
        # anti_pattern_id is optional: absence is valid.
        assert _has_valid_anti_pattern_id({}) is True

    def test_guard_rejects_all_three_keep_intact_traps(self):
        """FAIL-without: pre-013s _is_canonical_and_valid returned True here."""
        for entry in (
            self._entry_missing_source_ticket(),
            self._entry_freetext_impact(),
            self._entry_bad_anti_pattern_id(),
        ):
            assert _is_canonical_and_valid(entry) is False, entry["topic"]

    # --- end-to-end: PASS-with (migration repairs and --strict goes green) ---

    def test_migration_repairs_keep_intact_traps(self, observations_path: Path):
        entries = [
            self._entry_missing_source_ticket(),
            self._entry_freetext_impact(),
            self._entry_bad_anti_pattern_id(),
        ]
        _write_observations(observations_path, entries)
        assert run_migration(observations_path, apply=True) == 0
        success, errors = validate_file(observations_path, strict=True)
        assert success, f"strict validation failed: {errors}"

        by_topic = {
            json.loads(ln)["topic"]: json.loads(ln)
            for ln in observations_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        }
        # source_ticket derived from source (human_audit_WOT-2026-139 -> WOT-2026-139).
        assert by_topic["missing-source-ticket-case"]["source_ticket"] == "WOT-2026-139"
        # free-text impact coerced to a valid enum value.
        assert by_topic["freetext-impact-case"]["impact"] in ("low", "medium", "high")
        # non-canonical anti_pattern_id dropped (AP-D01 has no AP-NN form).
        assert "anti_pattern_id" not in by_topic["bad-ap-id-case"]


# ═══════════════════════════════════════════════════════════════════════════
# impact normalization preserves signal (schema-only)
# ═══════════════════════════════════════════════════════════════════════════


class TestImpactNormalization:
    def test_normalize_impact_valid_preserved(self):
        for v in ("low", "medium", "high"):
            assert _normalize_impact(v) == v

    def test_normalize_impact_freetext_to_medium(self):
        assert _normalize_impact("drift en PROJECT.md y CHANGELOG.md") == "medium"
        assert _normalize_impact("") == "medium"
        assert _normalize_impact(None) == "medium"

    def test_impact_repair_does_not_touch_signal(self, observations_path: Path):
        """Schema invariant: repairing impact must not alter the signal text."""
        original_signal = "El comando --session-close no actualiza PROJECT.md."
        _write_observations(
            observations_path,
            [
                {
                    "timestamp": "2026-06-22T10:00:00Z",
                    "topic": "impact-signal-invariant",
                    "domain": "delivery-hygiene",
                    "signal": original_signal,
                    "source": "session-2026-05-25",
                    "applies_to": "all",
                    "confidence": 0.9,
                    "impact": "drift en PROJECT.md y CHANGELOG.md",
                    "source_ticket": "WOT-2026-013m",
                }
            ],
        )
        assert run_migration(observations_path, apply=True) == 0
        row = json.loads(observations_path.read_text(encoding="utf-8").splitlines()[0])
        assert row["impact"] == "medium"
        assert row["signal"] == original_signal


# ═══════════════════════════════════════════════════════════════════════════
# Eje B: explicit domain mapping (no topic-substring inference)
# ═══════════════════════════════════════════════════════════════════════════


class TestDomainMappingEjeB:
    """Every non-enum MOTOR domain maps to a canonical one explicitly.

    The barrier proves the mapping is by EXPLICIT MAP/OVERRIDE entry, not by the
    topic-substring inferidor fallback.
    """

    # Per-entry expected targets, classified by reading each signal (see the
    # work_plan's decision table). Keyed by (domain, topic).
    EXPECTED: ClassVar[dict[tuple[str, str], str]] = {
        ("engine", "bus-recovery-rule"): "bus-architecture",
        ("review-bridge", "evidence-gate-fixture-contract"): "review-quality",
        ("session-closeout", "session-close-manual-gap"): "delivery-hygiene",
        ("security", "security-gate-fail-open"): "security-gates",
        ("supervisor-behavior", "handoff-blocked-not-crash"): "bus-architecture",
        ("supervisor-behavior", "builder-window-silent-fail"): "bus-architecture",
        ("meta", "cem-false-green"): "review-quality",
        ("meta", "ticket-lineage-rule"): "review-quality",
        # architecture splits across three targets via topic override:
        ("architecture", "bus-first-read-authority"): "bus-architecture",
        ("architecture", "review-decision-provenance-contract"): "review-quality",
        ("architecture", "repo-motor-portable-root"): "delivery-hygiene",
        # audit splits across two:
        ("audit", "system-health-audit-protocol"): "review-quality",
        ("audit", "bus-absent-is-unverifiable"): "bus-architecture",
        # engine-runtime launcher -> config-schema (root-cause classification):
        ("engine-runtime", "powershell-strictmode-dynamic-properties"): "config-schema",
    }

    def test_mapping_tables_have_013s_entries(self):
        """The 013s domains must live in the explicit tables, not the inferidor."""
        for d in (
            "engine",
            "review-bridge",
            "session-closeout",
            "security",
            "supervisor-behavior",
            "meta",
        ):
            assert d in DOMAIN_MIGRATION_MAP, f"{d} missing from DOMAIN_MIGRATION_MAP"
        for t in (
            "bus-first-read-authority",
            "review-decision-provenance-contract",
            "repo-motor-portable-root",
            "system-health-audit-protocol",
            "bus-absent-is-unverifiable",
            "powershell-strictmode-dynamic-properties",
        ):
            assert t in DOMAIN_MIGRATION_TOPIC_OVERRIDE, (
                f"{t} missing from DOMAIN_MIGRATION_TOPIC_OVERRIDE"
            )

    def test_each_non_enum_domain_maps_to_expected_canonical(
        self, observations_path: Path
    ):
        entries = [
            {
                "timestamp": "2026-06-22T10:00:00Z",
                "topic": topic,
                "domain": domain,
                "signal": f"Realistic signal for {domain}/{topic}.",
                "source": "human_audit_WOT-2026-013s",
                "applies_to": "all",
                "confidence": 0.9,
            }
            for (domain, topic) in self.EXPECTED
        ]
        _write_observations(observations_path, entries)
        assert run_migration(observations_path, apply=True) == 0
        success, errors = validate_file(observations_path, strict=True)
        assert success, f"strict validation failed: {errors}"

        by_topic = {
            json.loads(ln)["topic"]: json.loads(ln)
            for ln in observations_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        }
        for (domain, topic), expected in self.EXPECTED.items():
            assert by_topic[topic]["domain"] == expected, (
                f"{domain}/{topic} -> {by_topic[topic]['domain']}, expected {expected}"
            )

    def test_topic_override_beats_map_for_diverging_domain(
        self, observations_path: Path
    ):
        """architecture has no MAP row; its entries are split per-topic.

        FAIL-without the override: the inferidor would send
        review-decision-provenance-contract to a substring-matched domain, not
        review-quality. This proves the override drives the split.
        """
        _write_observations(
            observations_path,
            [
                {
                    "timestamp": "2026-06-22T10:00:00Z",
                    "topic": "review-decision-provenance-contract",
                    "domain": "architecture",
                    "signal": "review_bridge json_final_answer authority contract.",
                    "source": "human_audit_WOT-2026-013s",
                    "applies_to": "code",
                    "confidence": 0.9,
                },
                {
                    "timestamp": "2026-06-22T10:00:00Z",
                    "topic": "bus-first-read-authority",
                    "domain": "architecture",
                    "signal": "Derive ticket state from the bus before markdown.",
                    "source": "human_audit_WOT-2026-013s",
                    "applies_to": "code",
                    "confidence": 0.9,
                },
            ],
        )
        assert run_migration(observations_path, apply=True) == 0
        by_topic = {
            json.loads(ln)["topic"]: json.loads(ln)
            for ln in observations_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        }
        assert (
            by_topic["review-decision-provenance-contract"]["domain"]
            == "review-quality"
        )
        assert by_topic["bus-first-read-authority"]["domain"] == "bus-architecture"


# ═══════════════════════════════════════════════════════════════════════════
# Line endings: migrator preserves LF (no CRLF rewrite on Windows)
# ═══════════════════════════════════════════════════════════════════════════


class TestLineEndingPreservation:
    def test_apply_keeps_lf_only(self, observations_path: Path):
        """FAIL-without newline='\\n': write_text on Windows emits CRLF."""
        _write_observations(
            observations_path,
            [
                {
                    "timestamp": "2026-06-22T10:00:00Z",
                    "topic": "lf-preservation-case",
                    "domain": "ticket-planning",
                    "summary": "Legacy entry that the migrator will rewrite.",
                }
            ],
        )
        assert run_migration(observations_path, apply=True) == 0
        raw = observations_path.read_bytes()
        assert b"\r\n" not in raw, "migrator must not introduce CRLF"
        assert raw.endswith(b"\n")
