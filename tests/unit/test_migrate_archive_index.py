"""Contract tests for the disposable archive-index migration.

Before: a copied JSONL index contains legacy ``RETIRADO_LOCAL`` rows.
During: the migration is previewed and then applied to a separate index.
After: the source is unchanged and the target contains an idempotent,
       complete ARCHIVADO/RETIRADO history.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.flight.migrate_archive_index import migrate_index


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
