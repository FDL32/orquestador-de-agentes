from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

import pytest
from scripts.flight import p7_common, p7_retire


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def _fixture(
    tmp_path: Path, *, commit: bool = False
) -> tuple[Path, Path, dict[str, object], str, Path]:
    origin = tmp_path / "origin"
    origin.mkdir(parents=True)
    source = origin / "old.md"
    source.write_text("old bytes", encoding="utf-8")
    _git(origin, "init", "-q")
    _git(origin, "config", "user.email", "test@example.com")
    _git(origin, "config", "user.name", "test")
    if commit:
        _git(origin, "add", "old.md")
        _git(origin, "commit", "-q", "-m", "fixture")
    entry = {
        "rel": "old.md",
        "size": source.stat().st_size,
        "mtime": source.stat().st_mtime,
        "sha256": p7_common.sha256_file(source),
    }
    approved = tmp_path / "approved.jsonl"
    approved.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(approved.read_bytes()).hexdigest()
    return origin, tmp_path / "archive", entry, digest, approved


def _args(
    origin: Path, archive: Path, digest: str, approved: Path, *extra: str
) -> list[str]:
    return [
        "--archive-root",
        str(archive),
        "--family",
        "arranques",
        "--origin",
        str(origin),
        "--list",
        str(approved),
        "--list-sha256",
        digest,
        *extra,
    ]


def _args_family(
    origin: Path,
    archive: Path,
    digest: str,
    approved: Path,
    family: str,
    *extra: str,
) -> list[str]:
    args = _args(origin, archive, digest, approved, *extra)
    args[args.index("arranques")] = family
    return args


def test_lista_aprobada(tmp_path: Path) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path)
    archive.mkdir()
    assert p7_retire.main(_args(origin, archive, "0" * 64, approved)) == 1
    assert not (archive / "index.jsonl").exists()
    original = approved.read_bytes()
    approved.write_bytes(original + b"\n")
    assert p7_retire.main(_args(origin, archive, digest, approved)) == 1
    entry = json.loads(original.decode("utf-8"))
    entry["sha256"] = "0" * 64
    approved.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    altered_digest = hashlib.sha256(approved.read_bytes()).hexdigest()
    assert p7_retire.main(_args(origin, archive, altered_digest, approved)) == 1
    approved.write_bytes(original)
    assert p7_retire.main(_args(origin, archive, digest, approved)) == 0
    assert origin.joinpath("old.md").exists()


def test_recomprobacion_entrada(tmp_path: Path) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path)
    archive.mkdir()
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) == 0
    )
    source = origin / "old.md"
    stamp = source.stat().st_mtime + 30
    os.utime(source, (stamp, stamp))
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-retire")) == 1
    )
    assert source.exists()


def test_aborto_discrepancia(tmp_path: Path) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path)
    archive.mkdir()
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) == 0
    )
    source = origin / "old.md"
    source.write_text("changed", encoding="utf-8")
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-retire")) == 1
    )
    assert source.exists()


def test_registro_externo(tmp_path: Path) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path)
    archive.mkdir()
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) == 0
    )
    assert (archive / "index.jsonl").is_file()
    assert not (origin / "index.jsonl").exists()


def test_dry_run_por_defecto(tmp_path: Path) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path)
    archive.mkdir()
    assert p7_retire.main(_args(origin, archive, digest, approved)) == 0
    assert list(archive.rglob("*.zip")) == []
    assert not (archive / "index.jsonl").exists()
    assert not list(archive.rglob("*.manifest.json"))


def test_aplicacion_solo_via_p7(tmp_path: Path) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path)
    archive.mkdir()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise p7_common.ArchiveError("sentinel P7")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(p7_common, "verify_list_entries", boom)
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) == 1
    )
    assert list(archive.rglob("*.zip")) == []
    monkeypatch.undo()
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) == 0
    )
    assert origin.joinpath("old.md").exists()
    assert len(list(archive.rglob("*.zip"))) == 1


def test_fallo_disco_D(tmp_path: Path) -> None:  # noqa: N802
    origin, _, _, digest, approved = _fixture(tmp_path)
    archive = tmp_path / "absent" / "flight_archive"
    assert p7_retire.main(_args(origin, archive, digest, approved)) == 4
    assert not archive.exists()


def test_no_junctions(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("junction requiere Windows")
    origin, archive, _, _digest, approved = _fixture(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "inside.md").write_text("inside", encoding="utf-8")
    junction = origin / "link.md"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        pytest.fail(result.stderr or result.stdout)
    try:
        normal = origin / "normal.md"
        normal.write_text("normal", encoding="utf-8")
        approved_entry = {
            "rel": "normal.md",
            "size": normal.stat().st_size,
            "mtime": normal.stat().st_mtime,
            "sha256": p7_common.sha256_file(normal),
        }
        approved.write_text(json.dumps(approved_entry) + "\n", encoding="utf-8")
        good_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
        walked_manifest = p7_common.manifest_of_tree(origin)
        assert all("inside.md" not in row["rel"] for row in walked_manifest)
        archive.mkdir()
        assert (
            p7_retire.main(
                _args(origin, archive, good_hash, approved, "--apply-archive")
            )
            == 0
        )
        manifest = json.loads(
            next(archive.rglob("*.manifest.json")).read_text(encoding="utf-8")
        )
        assert all(not row["rel"].startswith("link.md/") for row in manifest)
        inside = target / "inside.md"
        nested_entry = {
            "rel": "link.md/inside.md",
            "size": inside.stat().st_size,
            "mtime": inside.stat().st_mtime,
            "sha256": p7_common.sha256_file(inside),
        }
        approved.write_text(json.dumps(nested_entry) + "\n", encoding="utf-8")
        nested_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
        nested_archive = tmp_path / "archive_nested"
        nested_archive.mkdir()
        assert (
            p7_retire.main(
                _args(
                    origin,
                    nested_archive,
                    nested_hash,
                    approved,
                    "--apply-archive",
                )
            )
            == 1
        )
        assert not list(nested_archive.rglob("*.zip"))
    finally:
        subprocess.run(
            ["cmd", "/c", "rmdir", str(junction)],
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )


def test_no_toca_versionados(tmp_path: Path) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path, commit=True)
    archive.mkdir()
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) == 0
    )
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-retire")) == 0
    )
    assert (origin / "old.md").exists()
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    assert rows[-1]["removed"][0]["status"] == "SALTADA_VERSIONADA"


def test_cuadre_bidireccional(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path)
    archive.mkdir()
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) == 0
    )
    index = archive / "index.jsonl"
    saved = p7_common.load_jsonl_index(index)
    p7_common.write_jsonl_index_atomic(index, [])
    assert p7_retire.main(_args(origin, archive, digest, approved)) == 1
    assert "fichero_sin_fila" in capsys.readouterr().err
    missing = dict(saved[0])
    missing["zip"] = str(archive / "arranques" / "missing.zip")
    missing["manifest"] = str(archive / "arranques" / "missing.manifest.json")
    p7_common.write_jsonl_index_atomic(index, [missing])
    assert p7_retire.main(_args(origin, archive, digest, approved)) == 1
    assert "fila_sin_fichero" in capsys.readouterr().err


def test_ttl_solo_genera_candidatas(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, archive, entry, digest, approved = _fixture(tmp_path)
    archive.mkdir()
    old = time.time() - 30 * 86400
    os.utime(origin / "old.md", (old, old))
    entry["mtime"] = old
    approved.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(approved.read_bytes()).hexdigest()
    before = origin.joinpath("old.md").read_bytes()
    result = p7_retire.main(
        _args(origin, archive, digest, approved, "--ttl-dias", "7", "--json")
    )
    output = capsys.readouterr().out
    assert result == 0
    assert '"rel": "old.md"' in output
    assert origin.joinpath("old.md").read_bytes() == before
    assert not list(archive.rglob("*.zip"))
    assert not (archive / "index.jsonl").exists()
    assert p7_common.classify_candidates(
        [entry], now=entry["mtime"] + 86401, ttl_dias=1, min_age_segundos=0
    ) == [entry]


def test_apply_archive_zip_manifest_and_rehash(tmp_path: Path) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path)
    archive.mkdir()
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) == 0
    )
    zip_path = next(archive.rglob("*.zip"))
    assert zipfile.ZipFile(zip_path).testzip() is None
    manifest_path = next(archive.rglob("*.manifest.json"))
    assert (
        p7_common.sha256_file(zip_path)
        == p7_common.load_jsonl_index(archive / "index.jsonl")[0]["zip_sha256"]
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert all(set(row) == {"rel", "size", "mtime", "sha256"} for row in manifest)
    assert all(
        row["sha256"] == p7_common.sha256_file(origin / row["rel"]) for row in manifest
    )


def test_apply_retire_solo_despues_de_archivado(tmp_path: Path) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path)
    archive.mkdir()
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-retire")) == 1
    )
    assert (origin / "old.md").exists()
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) == 0
    )
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-retire")) == 0
    )
    assert not (origin / "old.md").exists()


def test_reconciliacion_compartida_por_familia_y_precondicion(tmp_path: Path) -> None:
    origin_a, archive, _, digest_a, approved_a = _fixture(tmp_path / "a")
    origin_b, _, _, digest_b, approved_b = _fixture(tmp_path / "b")
    archive.mkdir()
    assert (
        p7_retire.main(
            _args_family(
                origin_a, archive, digest_a, approved_a, "a", "--apply-archive"
            )
        )
        == 0
    )
    assert (
        p7_retire.main(
            _args_family(
                origin_b, archive, digest_b, approved_b, "b", "--apply-archive"
            )
        )
        == 0
    )
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    assert {row["family"] for row in rows} == {"a", "b"}
    assert (
        p7_retire.main(_args_family(origin_a, archive, digest_a, approved_a, "a")) == 0
    )
    assert (
        p7_retire.main(_args_family(origin_b, archive, digest_b, approved_b, "b")) == 0
    )

    broken = dict(rows[0])
    broken["family"] = "b"
    broken["zip"] = str(archive / "b" / "missing.zip")
    broken["manifest"] = str(archive / "b" / "missing.manifest.json")
    p7_common.write_jsonl_index_atomic(archive / "index.jsonl", [*rows, broken])
    before_zips = sorted((archive / "a").glob("*.zip"))
    assert (
        p7_retire.main(
            _args_family(
                origin_a, archive, digest_a, approved_a, "a", "--apply-archive"
            )
        )
        != 0
    )
    assert sorted((archive / "a").glob("*.zip")) == before_zips


@pytest.mark.parametrize("layout", ["archive_inside", "origin_inside", "equal"])
def test_archive_root_y_origin_no_se_superponen(
    tmp_path: Path, layout: str, capsys: pytest.CaptureFixture[str]
) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path / "fixture")
    if layout == "archive_inside":
        archive = origin / "archive"
        archive.mkdir()
    elif layout == "origin_inside":
        archive = tmp_path / "outer"
        archive.mkdir()
        origin = archive / "origin"
        origin.mkdir()
        source = origin / "old.md"
        source.write_text("old bytes", encoding="utf-8")
    else:
        archive = origin
    result = p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive"))
    assert result == 2
    assert "archive-root" in capsys.readouterr().err
    assert not (archive / ".p7.lock").exists()
    assert not (archive / "index.jsonl").exists()
    assert list(archive.rglob("*.zip")) == []


def test_main_respeta_lock_vivo_y_corrupto(tmp_path: Path) -> None:
    origin, archive, _, digest, approved = _fixture(tmp_path / "live")
    archive.mkdir()
    lock = archive / ".p7.lock"
    lock.write_text(
        json.dumps({"pid": os.getpid(), "cwd": str(tmp_path)}), encoding="utf-8"
    )
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) != 0
    )
    assert lock.read_text(encoding="utf-8")
    assert not list(archive.rglob("*.zip"))
    assert not (archive / "index.jsonl").exists()

    origin, archive, _, digest, approved = _fixture(tmp_path / "corrupt")
    archive.mkdir()
    lock = archive / ".p7.lock"
    lock.write_bytes(b"not json")
    assert (
        p7_retire.main(_args(origin, archive, digest, approved, "--apply-archive")) != 0
    )
    assert lock.read_bytes() == b"not json"
    assert not list(archive.rglob("*.zip"))
    assert not (archive / "index.jsonl").exists()
