"""Unit tests for scripts/migrate_observations_schema.py (WOT-2026-214a).

Tests cover:
- Detection of records missing stable 'id'.
- Assignment of deterministic 'id' matching bus.portable_memory_archive.generate_stable_id.
- Preservation of existing 'id' fields.
- Strict byte-for-byte preservation of existing records that already have 'id'.
- Strict idempotence: second run produces zero byte changes and identical sha256.
- Strict compatibility with validate_observations.py --strict.
- Runtime observations.jsonl protection (runtime is read-only).
- Dry-run mode leaving files untouched on disk.
- Multi-file directory migration via migrate_archive_dir.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from bus.portable_memory_archive import generate_stable_id  # noqa: E402
from scripts.migrate_observations_schema import (  # noqa: E402
    migrate_archive_dir,
    migrate_archive_file,
)


def _compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def sample_archive_file(tmp_path: Path) -> Path:
    archive_dir = tmp_path / ".agent" / "runtime" / "memory" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / "observations.2026-07.jsonl"

    records = [
        {
            "timestamp": "2026-07-07T16:20:00Z",
            "topic": "gate-hardening-exact-match",
            "signal": "Hardening de gates del motor: heading detection exact match",
            "source": "session-2026-07-07",
            "domain": "security-gates",
            "applies_to": "code",
            "confidence": 0.95,
            "impact": "high",
            "source_ticket": "WOT-2026-019l",
        },
        {
            "id": "obs-already-present-id",
            "timestamp": "2026-07-08T10:00:00Z",
            "topic": "bus-signal-propagation",
            "signal": "Bus signals must be propagated with deterministic ordering",
            "source": "session-2026-07-08",
            "domain": "bus-architecture",
            "applies_to": "code",
            "confidence": 0.9,
            "impact": "medium",
            "source_ticket": "WOT-2026-020a",
        },
    ]

    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def test_migrate_archive_file_assigns_id_and_preserves_existing(
    sample_archive_file: Path,
) -> None:
    pre_lines = sample_archive_file.read_text(encoding="utf-8").splitlines()
    rec1_pre = json.loads(pre_lines[0])
    rec2_pre = json.loads(pre_lines[1])
    assert "id" not in rec1_pre
    assert rec2_pre["id"] == "obs-already-present-id"

    migrated_count, unchanged_count = migrate_archive_file(
        sample_archive_file, apply=True
    )
    assert migrated_count == 1
    assert unchanged_count == 1

    post_lines = sample_archive_file.read_text(encoding="utf-8").splitlines()
    rec1_post = json.loads(post_lines[0])
    rec2_post = json.loads(post_lines[1])

    expected_id = generate_stable_id(rec1_pre)
    assert rec1_post["id"] == expected_id
    assert rec1_post["id"].startswith("obs-")
    assert rec2_post["id"] == "obs-already-present-id"
    # Exact byte match on unchanged record line
    assert post_lines[1] == pre_lines[1]


def test_migrate_archive_file_idempotency_byte_by_byte(
    sample_archive_file: Path,
) -> None:
    migrate_archive_file(sample_archive_file, apply=True)
    sha1 = _compute_sha256(sample_archive_file)

    migrated_count, unchanged_count = migrate_archive_file(
        sample_archive_file, apply=True
    )
    sha2 = _compute_sha256(sample_archive_file)

    assert migrated_count == 0
    assert unchanged_count == 2
    assert sha1 == sha2, (
        "Second migration must produce byte-by-byte identical file (sha256 match)"
    )


def test_migrate_archive_dry_run_leaves_file_untouched(
    sample_archive_file: Path,
) -> None:
    sha_before = _compute_sha256(sample_archive_file)
    migrated_count, unchanged_count = migrate_archive_file(
        sample_archive_file, apply=False
    )

    assert migrated_count == 1
    assert unchanged_count == 1
    assert _compute_sha256(sample_archive_file) == sha_before


def test_migrate_archive_passes_validate_observations_strict(
    sample_archive_file: Path,
) -> None:
    validator_script = _MOTOR_ROOT / "scripts" / "validate_observations.py"

    res_pre = subprocess.run(
        [
            sys.executable,
            str(validator_script),
            "--strict",
            "--file",
            str(sample_archive_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_pre.returncode == 0, (
        f"Validator failed before migration: {res_pre.stderr}"
    )

    migrate_archive_file(sample_archive_file, apply=True)

    res_post = subprocess.run(
        [
            sys.executable,
            str(validator_script),
            "--strict",
            "--file",
            str(sample_archive_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_post.returncode == 0, (
        f"Validator failed after migration: {res_post.stderr}"
    )


def test_migrate_refuses_runtime_observations_file(tmp_path: Path) -> None:
    runtime_file = tmp_path / ".agent" / "runtime" / "memory" / "observations.jsonl"
    runtime_file.parent.mkdir(parents=True, exist_ok=True)
    runtime_file.write_text('{"topic": "runtime-sample"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"observations\.jsonl"):
        migrate_archive_file(runtime_file, apply=True)


def test_migrate_archive_dir(tmp_path: Path) -> None:
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    f1 = archive_dir / "observations.2026-07.jsonl"
    f2 = archive_dir / "observations.2026-08.jsonl"

    rec1 = {
        "timestamp": "2026-07-07T16:20:00Z",
        "topic": "topic-1",
        "signal": "signal 1",
        "source": "session-1",
        "domain": "security-gates",
        "applies_to": "code",
        "confidence": 0.95,
        "source_ticket": "WOT-2026-001a",
    }
    rec2 = {
        "id": "obs-already",
        "timestamp": "2026-08-07T16:20:00Z",
        "topic": "topic-2",
        "signal": "signal 2",
        "source": "session-2",
        "domain": "security-gates",
        "applies_to": "code",
        "confidence": 0.95,
        "source_ticket": "WOT-2026-002a",
    }

    f1.write_text(json.dumps(rec1) + "\n", encoding="utf-8")
    f2.write_text(json.dumps(rec2) + "\n", encoding="utf-8")

    res = migrate_archive_dir(archive_dir, apply=True)
    assert res[f1.name] == (1, 0)
    assert res[f2.name] == (0, 1)

    # Re-run for idempotency
    res2 = migrate_archive_dir(archive_dir, apply=True)
    assert res2[f1.name] == (0, 1)
    assert res2[f2.name] == (0, 1)
