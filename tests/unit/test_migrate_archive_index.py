"""Contract tests for the disposable archive-index migration.

Before: a copied JSONL index contains legacy ``RETIRADO_LOCAL`` rows.
During: the migration is previewed and then applied to a separate index.
After: the source is unchanged and the target contains an idempotent,
       complete ARCHIVADO/RETIRADO history.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from scripts.flight import migrate_archive_index, p7_common
from scripts.flight.migrate_archive_index import migrate_index, migrate_real_root


def _write_index(path: Path, rows: list[dict[str, object]]) -> None:
    """Before: ``rows`` are JSON-serializable index records.
    During: write an isolated JSONL fixture.
    After: the fixture can be consumed by the migration.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _legacy_row() -> dict[str, object]:
    """Before: a legacy clone-batch row has archive-specific metadata.
    During: provide both common and Kilo-style fields.
    After: migration must preserve every field while changing only status in
           generated rows.
    """
    return {
        "status": "RETIRADO_LOCAL",
        "family": "kilo_mut_f_t108",
        "origin": "copies/origin/kilo_mut_f_t108",
        "archive": "kilo_mut_f_t108.zip",
        "zip": "kilo_mut_f_t108.zip",
        "manifest": "kilo_mut_f_t108.manifest.json",
        "zip_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "clone_names": ["clone-a", "clone-b"],
        "expires": "2027-02-13",
        "custom_evidence": {"writer": "clone-archiver"},
    }


def _prepare_fixture(
    path: Path,
    rows: list[dict[str, object]],
    manifest_entries: list[dict[str, str]] | None = None,
) -> None:
    """Before: rows reference artifacts in an isolated fixture directory.
    During: create minimal valid zip/manifests and repair only fixture hashes.
    After: the migration can validate real archive evidence without D: access.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = manifest_entries or [{"rel": "clone-a/README.md", "sha256": "c" * 64}]
    for row in rows:
        zip_path = path.parent / str(row["zip"])
        manifest_path = path.parent / str(row["manifest"])
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"fixture-zip"
        zip_path.write_bytes(payload)
        manifest_path.write_text(json.dumps(entries), encoding="utf-8")
        row["zip_sha256"] = hashlib.sha256(payload).hexdigest()
        row["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    _write_index(path, rows)


def test_dry_run_does_not_edit_source_or_create_target(tmp_path: Path) -> None:
    """Before: source and target are disposable copies.
    During: run the default dry-run migration.
    After: neither source nor target bytes change.
    """
    source = tmp_path / "index.jsonl"
    target = tmp_path / "migrated" / "index.jsonl"
    _prepare_fixture(source, [_legacy_row()])
    before = source.read_bytes()

    result = migrate_index(source, target)

    assert result.migrated == 1
    assert result.would_write is True
    assert source.read_bytes() == before
    assert not target.exists()


def test_apply_preserves_legacy_and_emits_complete_pair(tmp_path: Path) -> None:
    """Before: one RETIRADO_LOCAL row represents an archived clone batch.
    During: apply migration to a sibling output index.
    After: source is unchanged and target has all three status rows with no
           field lost from the generated records.
    """
    source = tmp_path / "index_kilo.jsonl"
    target = tmp_path / "out" / "index_kilo.jsonl"
    legacy = _legacy_row()
    _prepare_fixture(source, [legacy])
    source_before = source.read_bytes()

    result = migrate_index(source, target, apply=True)
    rows = [
        json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
    ]

    assert result.migrated == 1
    assert source.read_bytes() == source_before
    assert [row["status"] for row in rows] == [
        "RETIRADO_LOCAL",
        "ARCHIVADO",
        "RETIRADO",
    ]
    for row in rows[1:]:
        for key, value in legacy.items():
            if key != "status":
                assert row[key] == value
    assert rows[1]["list_sha256"]
    assert rows[2]["migration"] == "WOT-2026-175d"
    assert rows[2]["removed"] == [{"path": legacy["origin"], "status": "RETIRADA"}]


def test_apply_is_idempotent_and_keeps_clone_names(tmp_path: Path) -> None:
    """Before: the target may already contain a previous migration.
    During: apply the same source twice.
    After: the second run changes no bytes and clone_names remains intact.
    """
    source = tmp_path / "index.jsonl"
    target = tmp_path / "out" / "index.jsonl"
    _prepare_fixture(source, [_legacy_row()])

    first = migrate_index(source, target, apply=True)
    first_bytes = target.read_bytes()
    second = migrate_index(source, target, apply=True)

    assert first.migrated == second.migrated == 1
    assert second.written is False
    assert target.read_bytes() == first_bytes
    rows = [
        json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[1]["clone_names"] == ["clone-a", "clone-b"]


def test_existing_archived_row_gets_only_retired_transition(tmp_path: Path) -> None:
    """Before: the source already contains one imported ARCHIVADO row.
    During: apply the migration to a new disposable target.
    After: keep that ARCHIVADO row and add exactly one RETIRADO row, rather
           than emitting a second enriched ARCHIVADO copy.
    """
    source = tmp_path / "index_kilo.jsonl"
    target = tmp_path / "out" / "index.jsonl"
    archived = _legacy_row()
    archived["status"] = "ARCHIVADO"
    _prepare_fixture(source, [archived])

    result = migrate_index(source, target, apply=True)
    rows = [
        json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
    ]

    assert result.migrated == 1
    assert result.added_rows == 1
    assert [row["status"] for row in rows] == ["ARCHIVADO", "RETIRADO"]
    assert rows[0] == archived
    assert rows[1]["migration"] == "WOT-2026-175d"


def test_clone_names_are_derived_from_manifest_entries(tmp_path: Path) -> None:
    """Before: a clone batch row has no trusted clone-name list.
    During: derive names from two manifest relative paths.
    After: both generated lifecycle rows contain the canonical names.
    """
    source = tmp_path / "index.jsonl"
    target = tmp_path / "out" / "index.jsonl"
    row = _legacy_row()
    row.pop("clone_names")
    row["family"] = "batch_family"
    entries = [
        {"rel": "clone-b/README.md", "sha256": "b" * 64},
        {"rel": "clone-a/README.md", "sha256": "a" * 64},
    ]
    _prepare_fixture(source, [row], entries)

    migrate_index(source, target, apply=True)
    rows = [
        json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
    ]

    assert rows[1]["clone_names"] == rows[2]["clone_names"] == ["clone-a", "clone-b"]


def test_rejects_in_place_source_and_target(tmp_path: Path) -> None:
    """Before: source and target resolve to the same disposable index.
    During: request an in-place migration.
    After: reject it before any write is possible.
    """
    source = tmp_path / "index.jsonl"
    _prepare_fixture(source, [_legacy_row()])

    try:
        migrate_index(source, source, apply=True)
    except ValueError as exc:
        assert "separate" in str(exc)
    else:
        raise AssertionError("in-place migration was not rejected")


def test_atomic_replace_failure_preserves_existing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: a disposable target already contains a valid prior index.
    During: force the atomic replace operation to fail.
    After: the prior target bytes survive and the temporary file is cleaned.
    """
    source = tmp_path / "source.jsonl"
    target = tmp_path / "target.jsonl"
    _prepare_fixture(source, [_legacy_row()])
    target.write_text('{"status":"ARCHIVADO"}\n', encoding="utf-8")
    before = target.read_bytes()

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("scripts.flight.migrate_archive_index.os.replace", fail_replace)
    with pytest.raises(ValueError, match="atomically write"):
        migrate_index(source, target, apply=True)

    assert target.read_bytes() == before
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_rejects_external_d_drive_before_reading(tmp_path: Path) -> None:
    """Before: a caller accidentally supplies the real external drive.
    During: validate the path before opening it.
    After: the migration fails closed without creating a target.
    """
    source = Path("D:/flight_archive/index.jsonl")
    target = tmp_path / "target.jsonl"

    with pytest.raises(ValueError, match="D:"):
        migrate_index(source, target, apply=True)
    assert not target.exists()


@pytest.mark.parametrize("index_name", ["index.jsonl", "index_kilo.jsonl"])
def test_both_machine_indexes_and_clone_batch_are_supported(
    tmp_path: Path, index_name: str
) -> None:
    """Before: either machine index names a clone batch with many clones.
    During: migrate a copied index using its original filename.
    After: one complete transition pair exists for the batch.
    """
    source = tmp_path / "copies" / index_name
    target = tmp_path / "migrated" / index_name
    row = _legacy_row()
    row["clone_names"] = [f"clone-{number}" for number in range(12)]
    _prepare_fixture(source, [row])

    result = migrate_index(source, target, apply=True)
    rows = [
        json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
    ]

    assert result.added_rows == 2
    assert [row["status"] for row in rows] == [
        "RETIRADO_LOCAL",
        "ARCHIVADO",
        "RETIRADO",
    ]
    assert rows[1]["clone_names"] == rows[2]["clone_names"] == row["clone_names"]


def test_origin_presence_controls_retired_generation(tmp_path: Path) -> None:
    """Before: one row's origin still exists on disk and another's does not.
    During: migrate both to a disposable target.
    After: only the absent-origin row gets a RETIRADO transition; the
           present-origin row keeps only its ARCHIVADO counterpart.
    """
    source = tmp_path / "index.jsonl"
    target = tmp_path / "out" / "index.jsonl"
    present = _legacy_row()
    present["family"] = "present_family"
    present["zip"] = "present_family.zip"
    present["manifest"] = "present_family.manifest.json"
    present["origin"] = "copies/origin/present_family"
    absent = _legacy_row()
    absent["family"] = "absent_family"
    absent["zip"] = "absent_family.zip"
    absent["manifest"] = "absent_family.manifest.json"
    absent["origin"] = "copies/origin/absent_family"
    _prepare_fixture(source, [present, absent])
    (source.parent / present["origin"]).mkdir(parents=True)

    result = migrate_index(source, target, apply=True)
    rows = [
        json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
    ]

    retired_families = {row["family"] for row in rows if row["status"] == "RETIRADO"}
    archived_families = {row["family"] for row in rows if row["status"] == "ARCHIVADO"}
    assert retired_families == {"absent_family"}
    assert archived_families == {"present_family", "absent_family"}
    assert result.added_rows == 3


def _prepare_real_root_fixture(index: Path, rows: list[dict[str, object]]) -> None:
    """Before: ``rows`` reference artifacts to place beside a real-root index.
    During: write verified zip/manifest evidence and the index itself.
    After: ``migrate_real_root`` can self-migrate without external access.
    """
    _prepare_fixture(index, rows)


def test_f03_1_dry_run_by_default_has_no_side_effects(tmp_path: Path) -> None:
    """Before: a real-root index has one unmigrated legacy row.
    During: call migrate_real_root without --apply.
    After: no bytes change, no lock, and no backup directory are created."""
    index = tmp_path / "root" / "index.jsonl"
    _prepare_real_root_fixture(index, [_legacy_row()])
    before = index.read_bytes()
    backup_dir = tmp_path / "backup"

    result = migrate_real_root(index, backup_dir=backup_dir)

    assert result.would_write is True
    assert result.written is False
    assert index.read_bytes() == before
    assert not backup_dir.exists()
    assert not (index.parent / ".p7.lock").exists()


def test_f03_2_apply_without_approval_is_rejected(tmp_path: Path) -> None:
    """Before: --apply is requested with no approval messageId.
    During: call migrate_real_root(apply=True) without approval_message_id.
    After: it raises before touching the index, lock, or backup."""
    index = tmp_path / "root" / "index.jsonl"
    _prepare_real_root_fixture(index, [_legacy_row()])
    before = index.read_bytes()

    with pytest.raises(ValueError, match="approval"):
        migrate_real_root(index, apply=True, backup_dir=tmp_path / "backup")

    assert index.read_bytes() == before
    assert not (index.parent / ".p7.lock").exists()
    assert not (tmp_path / "backup").exists()


def test_f03_3_apply_takes_the_shared_p7_lock(tmp_path: Path) -> None:
    """Before: the archive_root/.p7.lock is already held by this process.
    During: call migrate_real_root(apply=True) with valid approval.
    After: it fails with the same ArchiveError p7_retire would raise,
           proving it contends on that exact shared lock path."""
    index = tmp_path / "root" / "index.jsonl"
    _prepare_real_root_fixture(index, [_legacy_row()])
    lock = index.parent / ".p7.lock"
    lock.write_text(
        json.dumps({"pid": os.getpid(), "cwd": str(tmp_path), "created": 0.0}),
        encoding="utf-8",
    )

    with pytest.raises(p7_common.ArchiveError, match="retenido"):
        migrate_real_root(
            index,
            apply=True,
            approval_message_id="messageId-test",
            backup_dir=tmp_path / "backup",
        )

    lock.unlink()


def test_f03_4_backup_dir_inside_root_is_rejected(tmp_path: Path) -> None:
    """Before: --backup-dir resolves under the real root itself.
    During: call migrate_real_root(apply=True) with that backup-dir.
    After: it rejects before acquiring the lock or writing anything."""
    index = tmp_path / "root" / "index.jsonl"
    _prepare_real_root_fixture(index, [_legacy_row()])
    before = index.read_bytes()

    with pytest.raises(ValueError, match="outside"):
        migrate_real_root(
            index,
            apply=True,
            approval_message_id="messageId-test",
            backup_dir=index.parent / "backup_inside",
        )

    assert index.read_bytes() == before
    assert not (index.parent / ".p7.lock").exists()


def test_f03_4_valid_backup_copy_with_sha256_lands_outside_root(
    tmp_path: Path,
) -> None:
    """Before: a real-root index is about to be migrated with --apply.
    During: run migrate_real_root successfully.
    After: a verbatim pre-write copy and its sha256 exist in backup-dir."""
    index = tmp_path / "root" / "index.jsonl"
    _prepare_real_root_fixture(index, [_legacy_row()])
    before = index.read_bytes()
    backup_dir = tmp_path / "backup"

    result = migrate_real_root(
        index,
        apply=True,
        approval_message_id="messageId-test",
        backup_dir=backup_dir,
    )

    assert result.written is True
    digest = hashlib.sha256(before).hexdigest()
    backup_file = backup_dir / f"index.jsonl.{digest}.bak"
    sha_file = backup_dir / f"index.jsonl.{digest}.sha256"
    assert backup_file.read_bytes() == before
    assert sha_file.read_text(encoding="utf-8").strip() == digest


def test_f03_5_atomic_replace_failure_preserves_real_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: os.replace is forced to fail during the real-root write.
    During: call migrate_real_root(apply=True).
    After: the real index keeps its prior bytes and no temp file survives."""
    index = tmp_path / "root" / "index.jsonl"
    _prepare_real_root_fixture(index, [_legacy_row()])
    before = index.read_bytes()

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("scripts.flight.migrate_archive_index.os.replace", fail_replace)

    with pytest.raises(ValueError, match="atomically write"):
        migrate_real_root(
            index,
            apply=True,
            approval_message_id="messageId-test",
            backup_dir=tmp_path / "backup",
        )

    assert index.read_bytes() == before
    assert not list(index.parent.glob(f".{index.name}.*.tmp"))


def test_f03_6_aborts_without_writing_if_index_changed_under_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: the index is read once, then mutates before the lock-time read.
    During: call migrate_real_root(apply=True).
    After: it aborts without writing and without creating a backup."""
    index = tmp_path / "root" / "index.jsonl"
    _prepare_real_root_fixture(index, [_legacy_row()])
    before = index.read_bytes()
    original_read = migrate_archive_index._read_real_root_bytes
    calls = {"n": 0}

    def fake_read(path: Path) -> bytes:
        calls["n"] += 1
        if calls["n"] == 2:
            return before + b'{"status":"NOISE"}\n'
        return original_read(path)

    monkeypatch.setattr(migrate_archive_index, "_read_real_root_bytes", fake_read)
    backup_dir = tmp_path / "backup"

    with pytest.raises(ValueError, match="changed"):
        migrate_real_root(
            index,
            apply=True,
            approval_message_id="messageId-test",
            backup_dir=backup_dir,
        )

    assert index.read_bytes() == before
    assert not backup_dir.exists()
    assert not (index.parent / ".p7.lock").exists()


def test_f05_real_root_preserves_unsorted_legacy_bytes_verbatim(
    tmp_path: Path,
) -> None:
    """Before: the legacy line's keys are NOT in sort_keys=True order.
    During: migrate_real_root appends new rows with --apply.
    After: the original line's bytes are unchanged, byte for byte."""
    index = tmp_path / "root" / "index.jsonl"
    index.parent.mkdir(parents=True)
    legacy = _legacy_row()
    zip_path = index.parent / str(legacy["zip"])
    manifest_path = index.parent / str(legacy["manifest"])
    payload = b"fixture-zip"
    zip_path.write_bytes(payload)
    manifest_path.write_text(
        json.dumps([{"rel": "clone-a/README.md", "sha256": "c" * 64}]),
        encoding="utf-8",
    )
    legacy["zip_sha256"] = hashlib.sha256(payload).hexdigest()
    legacy["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    unsorted_line = json.dumps(legacy, sort_keys=False, ensure_ascii=False) + "\n"
    index.write_text(unsorted_line, encoding="utf-8")
    before = index.read_bytes()
    assert before != (json.dumps(legacy, sort_keys=True) + "\n").encode("utf-8")

    result = migrate_real_root(
        index,
        apply=True,
        approval_message_id="messageId-test",
        backup_dir=tmp_path / "backup",
    )

    after = index.read_bytes()
    assert result.written is True
    assert after[: len(before)] == before


def test_f06_real_root_second_apply_adds_nothing_and_does_not_rewrite(
    tmp_path: Path,
) -> None:
    """Before: a real-root index was already migrated once with --apply.
    During: run migrate_real_root(apply=True) a second time.
    After: 0 rows are added and the index's bytes stay identical."""
    index = tmp_path / "root" / "index.jsonl"
    _prepare_real_root_fixture(index, [_legacy_row()])
    backup_dir = tmp_path / "backup"

    first = migrate_real_root(
        index,
        apply=True,
        approval_message_id="messageId-test-1",
        backup_dir=backup_dir,
    )
    bytes_after_first = index.read_bytes()

    second = migrate_real_root(
        index,
        apply=True,
        approval_message_id="messageId-test-2",
        backup_dir=backup_dir,
    )

    assert first.added_rows == 2
    assert second.added_rows == 0
    assert second.written is False
    assert index.read_bytes() == bytes_after_first


def test_f03_artifact_path_allows_d_drive_only_when_flagged() -> None:
    """Before: a row's zip/manifest artifact lives directly under D:.
    During: resolve its path with and without the real-root bypass.
    After: only allow_d_drive=True (real-root) accepts the D: artifact path;
           the default (disposable-copy) path still rejects it closed."""
    row = {"zip": "fam/x.zip"}
    base = Path("D:/flight_archive")

    allowed = migrate_archive_index._artifact_path(row, "zip", base, allow_d_drive=True)
    assert allowed == base / "fam/x.zip"

    with pytest.raises(ValueError, match="forbidden"):
        migrate_archive_index._artifact_path(row, "zip", base, allow_d_drive=False)


def test_f03_real_root_enrichment_bypasses_d_drive_rejection() -> None:
    """Before: a real-root row's zip/manifest base is a D: path (never
       written to; only Path.is_file() is probed, which is read-only and
       returns False for a path that is not mounted or does not exist).
    During: enrich the row with allow_d_drive=True.
    After: the failure is "archive artifacts missing", never "D: archive
           paths are forbidden" -- proving real-root mode can reach real
           evidence checks on D: instead of being rejected before trying.
           Without the flag, the old D:-rejection failure mode returns."""
    row = {"family": "fam", "zip": "fam/x.zip", "manifest": "fam/x.json"}
    base = Path("D:/wot175f_nonexistent_probe_dir")

    with pytest.raises(ValueError) as excinfo:
        migrate_archive_index._enrich_row(row, base, allow_d_drive=True)
    assert "forbidden" not in str(excinfo.value)
    assert "missing" in str(excinfo.value)

    with pytest.raises(ValueError, match="forbidden"):
        migrate_archive_index._enrich_row(row, base, allow_d_drive=False)
