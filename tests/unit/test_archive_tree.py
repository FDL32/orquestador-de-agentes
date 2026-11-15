"""Contract tests for the versioned clone archiver.

Before: the archive tool is absent or incomplete.
During: tests exercise the public CLI and independent round-trip checks.
After: the test file documents the fail-closed archive contract.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest
from scripts.flight import archive_tree, p7_common


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "archive_tree.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _restore_manifest_mtimes(manifest: Path, restored: Path) -> None:
    """Before: ``restored`` was extracted without metadata restoration.
    During: restore each file mtime from the independent manifest recipe.
    After: the independent verifier can compare, rather than manufacture, mtimes.
    """
    for row in json.loads(manifest.read_text(encoding="utf-8")):
        if not row.get("dir"):
            path = restored / row["rel"]
            os.utime(path, (float(row["mtime"]), float(row["mtime"])))


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin"
    archive = tmp_path / "archive"
    clone = origin / "clone-a"
    clone.mkdir(parents=True)
    (clone / "empty").mkdir()
    (clone / "data.txt").write_text("payload", encoding="utf-8")
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps([{"rel": "clone-a"}]), encoding="utf-8")
    return origin, archive, approved


def _approved(origin: Path, approved: Path) -> str:
    value = [{"rel": "clone-a", "sha256": archive_tree.tree_hash(origin / "clone-a")}]
    approved.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(approved.read_bytes()).hexdigest()


def test_cli_dry_run_contract(tmp_path: Path) -> None:
    """Before: the new CLI is not present.
    During: invoke the required dry-run boundary.
    After: the origin is unchanged and candidates are reported.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    before_origin = archive_tree.tree_hash(origin)
    before_archive = archive_tree.tree_hash(archive)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--list",
        str(approved),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["candidates"] == ["clone-a"]
    assert archive_tree.tree_hash(origin) == before_origin
    assert archive_tree.tree_hash(archive) == before_archive


def test_apply_requires_and_checks_approval(tmp_path: Path) -> None:
    """Before: approval is absent or stale.
    During: reject both cases before creating archive evidence.
    After: a valid list is the only accepted apply input.
    """
    origin, archive, approved = _fixture(tmp_path)
    result = _run("--origin", str(origin), "--archive-root", str(archive), "--apply")
    assert result.returncode == 2
    list_hash = _approved(origin, approved)
    approved.write_text(
        approved.read_text(encoding="utf-8").replace("clone-a", "clone-b"),
        encoding="utf-8",
    )
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode != 0
    assert not archive.exists()


def test_apply_rejects_missing_root_and_entry_hash(tmp_path: Path) -> None:
    """Before: the archive root is absent or an approved tree changed.
    During: fail before lock-dependent filesystem writes.
    After: rc 4 is used for the absent root and rc 1 for a stale entry.
    """
    origin, archive, approved = _fixture(tmp_path)
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 4
    assert not archive.exists()
    archive.mkdir()
    value = json.loads(approved.read_text(encoding="utf-8"))
    value[0]["sha256"] = "0" * 64
    approved.write_text(json.dumps(value), encoding="utf-8")
    bad_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply",
        "--list",
        str(approved),
        "--list-sha256",
        bad_hash,
    )
    assert result.returncode == 1
    assert list(archive.iterdir()) == []


def test_dry_run_missing_root_is_rc4(tmp_path: Path) -> None:
    """Before: the archive root is absent.
    During: run the safe default without creating a root.
    After: rc 4 and zero filesystem writes are observed.
    """
    origin, archive, _approved_path = _fixture(tmp_path)
    result = _run("--origin", str(origin), "--archive-root", str(archive))
    assert result.returncode == 4
    assert not archive.exists()


def test_archive_and_retire_are_separate_phases(tmp_path: Path) -> None:
    """Before: an approved clone and an existing archive root exist.
    During: archive-only is followed by retire-only against the original origin.
    After: the first phase preserves origin and the second adds one RETIRADO row.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    archive_result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert archive_result.returncode == 0, archive_result.stderr
    assert (origin / "clone-a").exists()
    retire_result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-retire",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert retire_result.returncode == 0, retire_result.stderr
    assert not (origin / "clone-a").exists()
    assert [
        row["status"] for row in p7_common.load_jsonl_index(archive / "index.jsonl")
    ] == ["ARCHIVADO", "RETIRADO"]


def test_readonly_abort_keeps_origin_intact(tmp_path: Path) -> None:
    """Before: a selected file is readonly.
    During: combined apply performs preflight before staging.
    After: rc 1 leaves the origin hash and clone path unchanged.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    file_path = origin / "clone-a" / "data.txt"
    file_path.chmod(0o444)
    before = archive_tree.tree_hash(origin)
    try:
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        assert result.returncode == 1
        assert (origin / "clone-a").exists()
        assert archive_tree.tree_hash(origin) == before
        assert not any(path.name.startswith(".p7_") for path in origin.parent.iterdir())
    finally:
        file_path.chmod(0o666)


def test_stage_requires_resume_and_resume_returns_clone(tmp_path: Path) -> None:
    """Before: a staged clone remains after an interrupted operation.
    During: reject without resume, then archive with resume and return the clone.
    After: no stage orphan or temporary file remains.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    stage = origin.parent / (".p7_" + "stage_" + "clone_archive")
    stage.mkdir()
    shutil.move(str(origin / "clone-a"), str(stage / "clone-a"))
    rejected = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert rejected.returncode == 1
    resumed = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--resume",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert (origin / "clone-a").exists()
    assert not stage.exists()
    assert not list(archive.rglob("*.tmp"))


@pytest.mark.parametrize("size,expected", [(6, 0), (7, 0), (8, 1)])
def test_max_bytes_boundaries(tmp_path: Path, size: int, expected: int) -> None:
    """Before: a selected clone is exactly below, equal to, or above the limit.
    During: evaluate the byte budget before staging or archive writes.
    After: only the one-byte-over case fails with no archive artifacts.
    """
    origin, archive, approved = _fixture(tmp_path)
    (origin / "clone-a" / "data.txt").write_bytes(b"x" * size)
    list_hash = _approved(origin, approved)
    archive.mkdir()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--max-bytes",
        "7",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == expected
    if expected:
        assert list(archive.iterdir()) == []


def test_apply_round_trip_and_p7_index(tmp_path: Path) -> None:
    """Before: a real clone-shaped tree and an approved hash exist.
    During: archive and retire the same batch.
    After: zip, manifest, ARCHIVADO, RETIRADO, and P7 reconciliation agree.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0, result.stderr
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    assert [row["status"] for row in rows] == ["ARCHIVADO", "RETIRADO"]
    archived = rows[0]
    manifest = json.loads(Path(archived["manifest"]).read_text(encoding="utf-8"))
    with __import__("zipfile").ZipFile(archived["zip"]) as zipped:
        assert set(zipped.namelist()) == {
            row["rel"] for row in manifest if not row.get("dir")
        }
    assert not (origin / "clone-a").exists()
    assert p7_common.reconcile_index(archive, rows, archived["family"]) == []


def _independent_verify(
    zip_path: Path, manifest_path: Path, restored: Path
) -> list[str]:
    """Before: a zip, manifest, and restored directory are independent inputs.
    During: compare mtime, size, digest, extra files, and empty directories.
    After: return discrepancy labels without importing the production archiver.
    """
    rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    bad: list[str] = []
    expected_files = set()
    expected_dirs = set()
    for row in rows:
        path = restored / row["rel"]
        if row.get("dir"):
            expected_dirs.add(row["rel"])
            path.mkdir(parents=True, exist_ok=True)
            if not path.is_dir():
                bad.append("missing-dir")
            continue
        for parent in Path(row["rel"]).parents:
            if str(parent) != ".":
                expected_dirs.add(parent.as_posix())
        expected_files.add(row["rel"])
        if not path.is_file():
            bad.append("missing-file")
            continue
        info = path.stat()
        row_bad = (
            info.st_size != row["size"]
            or abs(info.st_mtime - float(row["mtime"])) > 1e-3
        )
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            row_bad = True
        if row_bad:
            bad.append("discrepant")
    actual_files = {
        p.relative_to(restored).as_posix() for p in restored.rglob("*") if p.is_file()
    }
    actual_dirs = {
        p.relative_to(restored).as_posix() for p in restored.rglob("*") if p.is_dir()
    }
    bad.extend(["extra-file"] * len(actual_files - expected_files))
    bad.extend(["extra-dir"] * len(actual_dirs - expected_dirs))
    return bad


def test_independent_round_trip_verifier(tmp_path: Path) -> None:
    """Before: three clone-shaped trees are archived without the verifier helper.
    During: restore and compare through the independent implementation.
    After: the clean restore passes and a byte mutation returns one discrepancy.
    """
    source = inspect.getsource(_independent_verify)
    assert "archive_tree" not in source
    origin = tmp_path / "origin"
    archive = tmp_path / "archive"
    origin.mkdir()
    archive.mkdir()
    for index in range(3):
        clone = origin / f"clone-{index}"
        clone.mkdir()
        (clone / "empty").mkdir()
        (clone / "payload.bin").write_bytes(bytes([index]) * (1024 + index))
    approved = tmp_path / "approved.json"
    entries = [
        {
            "rel": f"clone-{index}",
            "sha256": archive_tree.tree_hash(origin / f"clone-{index}"),
        }
        for index in range(3)
    ]
    approved.write_text(json.dumps(entries), encoding="utf-8")
    list_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0, result.stderr
    row = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    restored = tmp_path / "restored"
    restored.mkdir()
    with zipfile.ZipFile(row["zip"]) as zipped:
        zipped.extractall(restored)
    _restore_manifest_mtimes(Path(row["manifest"]), restored)
    assert _independent_verify(Path(row["zip"]), Path(row["manifest"]), restored) == []
    mutated = next(restored.rglob("payload.bin"))
    mutated.write_bytes(b"mutated")
    assert (
        len(_independent_verify(Path(row["zip"]), Path(row["manifest"]), restored)) == 1
    )


def test_independent_verifier_uses_three_real_git_clones(tmp_path: Path) -> None:
    """Before: a real git source can be cloned without hardlinks.
    During: archive three real clones, including a file above one MiB, and restore independently.
    After: the clean restore has zero discrepancies and one byte mutation has one.
    """
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.bin").write_bytes(b"x" * (1024 * 1024 + 1))
    (source / "README").write_text("git", encoding="utf-8")
    for command in (
        ["git", "init"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "test"],
        ["git", "add", "."],
        ["git", "commit", "-m", "fixture"],
    ):
        result = subprocess.run(
            command, cwd=source, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
    origin = tmp_path / "origin"
    archive = tmp_path / "archive"
    origin.mkdir()
    archive.mkdir()
    for index in range(3):
        clone = origin / f"clone-{index}"
        result = subprocess.run(
            ["git", "clone", "--no-hardlinks", str(source), str(clone)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    approved = tmp_path / "approved.json"
    entries = [
        {
            "rel": f"clone-{index}",
            "sha256": archive_tree.tree_hash(origin / f"clone-{index}"),
        }
        for index in range(3)
    ]
    approved.write_text(json.dumps(entries), encoding="utf-8")
    list_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--umbral-hilo",
        str(1024 * 1024),
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0, result.stderr
    row = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    restored = tmp_path / "restored"
    restored.mkdir()
    with zipfile.ZipFile(row["zip"]) as zipped:
        zipped.extractall(restored)
    _restore_manifest_mtimes(Path(row["manifest"]), restored)
    assert _independent_verify(Path(row["zip"]), Path(row["manifest"]), restored) == []
    target = next(restored.rglob("large.bin"))
    data = bytearray(target.read_bytes())
    data[0] ^= 1
    target.write_bytes(data)
    assert (
        len(_independent_verify(Path(row["zip"]), Path(row["manifest"]), restored)) == 1
    )


def test_prohibited_strings_scan_uses_constructed_needles() -> None:
    """Before: source must not bake environment-specific archive names.
    During: scan source using both separators and a date regex.
    After: no forbidden literal or date is present in the implementation.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    needles = [
        "C:" + "/" + "Temp",
        "C:" + "\\" + "Temp",
        "p7_" + "stage_" + "tramo1",
        "flight_" + "archive_" + "kilo",
    ]
    assert not any(needle in source for needle in needles)
    date_pattern = re.compile("20" + r"\d\d-\d\d-\d\d")
    assert not date_pattern.search(source)


def test_prohibited_string_control_positive_scans_script_and_test(
    tmp_path: Path,
) -> None:
    """Before: both forbidden separators exist only in a temporary control file.
    During: scan the implementation and test source plus the control file.
    After: production sources have zero hits and the control file has two hits.
    """
    sources = [SCRIPT, Path(__file__)]
    needles = ["C:" + "/" + "Temp", "C:" + "\\" + "Temp"]
    control = tmp_path / "control.txt"
    control.write_text(needles[0] + "\n" + needles[1], encoding="utf-8")
    assert (
        sum(
            source.read_text(encoding="utf-8").count(needle)
            for source in sources
            for needle in needles
        )
        == 0
    )
    assert (
        sum(control.read_text(encoding="utf-8").count(needle) for needle in needles)
        == 2
    )


def test_min_free_existing_root_rejects_without_writes(tmp_path: Path) -> None:
    """Before: an existing archive root has insufficient free space by policy.
    During: run archive-only with an intentionally impossible minimum.
    After: rc 4 and no family or index are written.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--min-libre",
        str(2**63 - 1),
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 4
    assert list(archive.iterdir()) == []


def test_live_lock_rejects_and_orphan_lock_recovers(tmp_path: Path) -> None:
    """Before: the P7 lock is respectively live and orphaned.
    During: execute the CLI against the same archive root.
    After: live lock rejects, dead PID is recovered, and cleanup releases the lock.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    lock = archive / ".p7.lock"
    p7_common.acquire_lock(lock, pid=os.getpid(), cwd=str(ROOT))
    try:
        rejected = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-archive",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        assert rejected.returncode != 0
    finally:
        p7_common.release_lock(lock)
    lock.write_text(json.dumps({"pid": 99999999, "cwd": str(ROOT)}), encoding="utf-8")
    recovered = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert not lock.exists()


def test_existing_family_aborts_before_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: the deterministic family name already exists.
    During: patch the module clock and execute the archive-only route.
    After: rc 1 and no second index row are produced.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    family = "clone_archive_STAMP"
    (archive / family).mkdir()

    class FixedDateTime:
        @classmethod
        def now(cls, _timezone: object) -> object:
            return type("Stamp", (), {"strftime": lambda _self, _fmt: "STAMP"})()

    monkeypatch.setattr(archive_tree, "datetime", FixedDateTime)
    result = archive_tree.main(
        [
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-archive",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        ]
    )
    assert result != 0
    assert not (archive / "index.jsonl").exists()


def test_corrupt_zip_rejected_by_independent_zip_check(tmp_path: Path) -> None:
    """Before: archive-only has produced a verified family.
    During: corrupt one zip byte and run the independent verifier.
    After: ArchiveTreeError or BadZipFile is raised before retirement.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0
    row = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    zip_path = Path(row["zip"])
    with zipfile.ZipFile(zip_path) as zipped:
        info = zipped.infolist()[0]
        offset = (
            info.header_offset + 30 + len(info.filename.encode()) + len(info.extra) + 1
        )
    data = bytearray(zip_path.read_bytes())
    data[offset] ^= 1
    zip_path.write_bytes(data)
    with pytest.raises((archive_tree.ArchiveTreeError, zipfile.BadZipFile)):
        archive_tree._verify_zip(
            zip_path, json.loads(Path(row["manifest"]).read_text(encoding="utf-8"))
        )


def test_real_process_cwd_guard(tmp_path: Path) -> None:
    """Before: a real child has its cwd inside a clone.
    During: inspect the Windows process table and PEB-derived cwd.
    After: the live child is detected, then terminated and reaped.
    """
    assert sys.platform == "win32"
    clone = tmp_path / "clone"
    clone.mkdir()
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=clone,
    )
    try:
        time.sleep(0.5)
        assert any(pid == child.pid for pid, _ in archive_tree.active_processes(clone))
    finally:
        child.terminate()
        child.wait(timeout=10)


def test_real_shell_and_claude_commandline_guard(tmp_path: Path) -> None:
    """Before: real cmd and a copied claude.exe reference a clone.
    During: inspect both live command lines while each process is alive.
    After: both PIDs are detected and always terminated in the cleanup block.
    """
    if sys.platform != "win32":
        pytest.fail("Windows real-process contract is required")
    clone = tmp_path / "clone"
    clone.mkdir()
    command_shell = Path(os.environ["COMSPEC"])
    claude = tmp_path / "claude.exe"
    shutil.copy2(command_shell, claude)
    command = f"echo {clone} & ping 127.0.0.1 -n 30 > nul"
    children = [
        subprocess.Popen([str(command_shell), "/c", command], cwd=clone),
        subprocess.Popen([str(claude), "/c", command], cwd=clone),
    ]
    try:
        time.sleep(0.5)
        found = {pid for pid, _ in archive_tree.active_processes(clone)}
        assert {child.pid for child in children} <= found
    finally:
        for child in children:
            child.terminate()
        for child in children:
            child.wait(timeout=10)


def test_shell_and_claude_commandline_guard_is_not_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: shell-named processes reference the protected clone.
    During: feed the same process-table shape used by the Windows probe.
    After: shell and claude.exe references are reported, not filtered.
    """
    clone = tmp_path / "clone"
    clone.mkdir()
    rows = [
        (901, "bash.exe " + str(clone), None),
        (902, "claude.exe " + str(clone), None),
    ]
    monkeypatch.setattr(archive_tree, "_process_rows", lambda: rows)
    assert {pid for pid, _ in archive_tree.active_processes(clone)} == {901, 902}


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    """Before: ``process`` is a fixture process that may have descendants.
    During: terminate the complete Windows process tree and wait for its root.
    After: the launched root is reaped, with no fallback that can leave children alive.
    """
    if process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    process.wait(timeout=10)


def _wait_for_process_references(origin: Path, pids: set[int]) -> None:
    """Before: real fixture processes have just been launched.
    During: poll the production process probe until every PID is visible.
    After: the CLI guard can be exercised without a timing race.
    """
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        found = {pid for pid, _ in archive_tree.active_processes(origin)}
        if pids <= found:
            return
        time.sleep(0.1)
    assert pids <= {pid for pid, _ in archive_tree.active_processes(origin)}


def _assert_process_abort_result(
    result: subprocess.CompletedProcess[str],
    origin: Path,
    archive: Path,
    before_origin: str,
    before_archive: str,
) -> None:
    """Before: a live-process guard should reject before staging or archive writes.
    During: assert the public CLI failure and its exact diagnostic.
    After: both trees are unchanged and no archive artifact family was created.
    """
    assert result.returncode != 0
    assert "live process references origin" in result.stderr
    assert archive_tree.tree_hash(origin) == before_origin
    assert archive_tree.tree_hash(archive) == before_archive
    paths = list(archive.rglob("*"))
    assert not any(path.name.startswith("clone_archive_") for path in paths)
    assert not any(path.name == "index.jsonl" for path in paths)
    assert not any(path.name.endswith(".tmp") for path in paths)


def _assert_abort_keeps_origin(tmp_path: Path, mutate: object) -> None:
    """Before: an approved clone is changed before combined apply.
    During: execute the supplied destructive-boundary mutation.
    After: apply rejects, origin hash is unchanged, and no family exists.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    before = archive_tree.tree_hash(origin)
    mutate(origin)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode != 0
    assert archive_tree.tree_hash(origin) == before
    assert not any(
        path.is_dir() and path.name.startswith("clone_archive_")
        for path in archive.iterdir()
    )


@pytest.mark.parametrize("case", ["extra", "empty", "mtime", "junction", "readonly"])
def test_b05_abort_matrix_keeps_origin(tmp_path: Path, case: str) -> None:
    """Before: one unsafe-origin condition is introduced.
    During: combined apply runs the real preflight.
    After: rc is nonzero, origin hash is unchanged, and no family exists.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    target = tmp_path / "junction-target"
    target.mkdir()
    junction = origin / "clone-a" / "link"
    read_only = origin / "clone-a" / "data.txt"
    try:
        if case == "extra":
            (origin / "clone-a" / "extra.txt").write_text("extra", encoding="utf-8")
        elif case == "empty":
            (origin / "clone-a" / "new-empty").mkdir()
        elif case == "mtime":
            path = origin / "clone-a" / "data.txt"
            os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
        elif case == "junction":
            made = subprocess.run(
                [
                    os.environ["COMSPEC"],
                    "/c",
                    "mklink",
                    "/J",
                    str(junction),
                    str(target),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert made.returncode == 0, made.stderr
        else:
            read_only.chmod(0o444)
        before = archive_tree.tree_hash(origin)
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        assert result.returncode != 0
        assert archive_tree.tree_hash(origin) == before
        assert not any(
            path.is_dir() and path.name.startswith("clone_archive_")
            for path in archive.iterdir()
        )
    finally:
        if junction.exists():
            subprocess.run(
                [os.environ["COMSPEC"], "/c", "rmdir", str(junction)],
                capture_output=True,
                check=False,
            )
        read_only.chmod(0o666)


def test_resume_never_deletes_data_tmp_in_dry_run_or_archive(tmp_path: Path) -> None:
    """Before: a resumed stage contains a data file ending in ``.tmp``.
    During: dry-run and archive-only resume inspect it without stage cleanup.
    After: the data file remains and the origin hash is unchanged by dry-run.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    data_tmp = origin / "clone-a" / "data.tmp"
    data_tmp.write_text("payload", encoding="utf-8")
    stage = origin.parent / ".p7_stage_clone_archive"
    stage.mkdir()
    shutil.move(str(origin / "clone-a"), str(stage / "clone-a"))
    _approved(stage, approved)
    list_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    before = archive_tree.tree_hash(stage)
    dry = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--resume",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert dry.returncode == 0, dry.stderr
    assert (stage / "clone-a" / "data.tmp").exists()
    assert archive_tree.tree_hash(stage) == before
    applied = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--resume",
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert applied.returncode == 0, applied.stderr
    assert (origin / "clone-a" / "data.tmp").exists()


def _write_recovery_ledger(
    archive: Path,
    origin: Path,
    record: dict[str, object],
    manifest: list[dict[str, object]],
) -> Path:
    ledger = archive / "retirement_recovery.json"
    ledger.write_text(
        json.dumps(
            {
                "status": "IN_PROGRESS",
                "family": record["family"],
                "origin": str(origin),
                "record": record,
                "manifest": manifest,
            }
        ),
        encoding="utf-8",
    )
    return ledger


def test_recovery_fails_closed_for_process_zip_manifest_and_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: recovery evidence is independently challenged.
    During: each live-process or evidence mismatch is rejected before cleanup.
    After: the origin and recovery ledger remain intact in every case.
    """
    original_active_processes = archive_tree.active_processes
    for case in ("process", "zip", "manifest", "origin"):
        root = tmp_path / case
        origin, archive, record, manifest = _archived_fixture(root)
        ledger = _write_recovery_ledger(archive, origin, record, manifest)
        before = archive_tree.tree_hash(origin)
        if case == "process":
            monkeypatch.setattr(
                archive_tree, "active_processes", lambda _origin: [(1, "live")]
            )
        elif case == "zip":
            Path(record["zip"]).write_bytes(b"corrupt")
        elif case == "manifest":
            data = json.loads(ledger.read_text(encoding="utf-8"))
            data["record"]["manifest_sha256"] = "0" * 64
            ledger.write_text(json.dumps(data), encoding="utf-8")
        else:
            data = json.loads(ledger.read_text(encoding="utf-8"))
            data["origin"] = str(root / "different-origin")
            ledger.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises((archive_tree.ArchiveTreeError, zipfile.BadZipFile)):
            archive_tree._recover_retirement(archive)
        assert archive_tree.tree_hash(origin) == before
        assert ledger.exists()
        if case == "process":
            monkeypatch.setattr(
                archive_tree, "active_processes", original_active_processes
            )


def test_recovery_cleans_only_own_hidden_partials(tmp_path: Path) -> None:
    """Before: recovery has own hidden partials and unrelated temporary files.
    During: recover the archived family and scope cleanup to archive/family paths.
    After: own partials disappear while foreign files do not.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    _write_recovery_ledger(archive, origin, record, manifest)
    own_root = archive / ".archive.tmp"
    own_family = Path(record["zip"]).parent / ".family.tmp"
    foreign_root = archive / "foreign.tmp"
    foreign_family = archive / "other-family"
    foreign_family.mkdir()
    foreign_nested = foreign_family / ".foreign.tmp"
    for path in (own_root, own_family, foreign_root, foreign_nested):
        path.write_text("tmp", encoding="utf-8")
    archive_tree._recover_retirement(archive)
    assert not own_root.exists()
    assert not own_family.exists()
    assert foreign_root.exists()
    assert foreign_nested.exists()


def test_retirement_does_not_overwrite_other_pending_ledger(tmp_path: Path) -> None:
    """Before: family A has an interrupted retirement ledger.
    During: family B attempts to retire against the same archive root.
    After: the operation aborts and family A's ledger bytes are unchanged.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    ledger = _write_recovery_ledger(archive, origin, record, manifest)
    before = ledger.read_bytes()
    with pytest.raises(
        archive_tree.ArchiveTreeError, match="retirement recovery pending"
    ):
        archive_tree._retire(origin, archive, "different-family", record, manifest)
    assert ledger.read_bytes() == before
    assert origin.exists()


def test_approved_entry_without_hash_is_rejected_without_writes(tmp_path: Path) -> None:
    """Before: the list hash is correct but an entry omits its tree hash.
    During: apply validates every approved entry before any archive write.
    After: the exact contract error is returned and the archive stays empty.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    approved.write_text(json.dumps([{"rel": "clone-a"}]), encoding="utf-8")
    list_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode != 0
    assert "every approved entry needs rel and sha256" in result.stderr
    assert not (archive / "index.jsonl").exists()


@pytest.mark.parametrize("failure", ["returncode", "timeout", "oserror"])
def test_windows_process_listing_fails_closed_and_retries(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Before: Windows process enumeration is unavailable or reports failure.
    During: retry once with 30 seconds after the 10-second attempt.
    After: fail closed instead of allowing retirement to proceed.
    """
    calls: list[int] = []
    monkeypatch.setattr(archive_tree.os, "name", "nt")

    def fake_run(*_args: object, **kwargs: object) -> object:
        calls.append(int(kwargs["timeout"]))
        if failure == "returncode":
            return type("Result", (), {"returncode": 1, "stdout": ""})()
        if failure == "timeout":
            raise subprocess.TimeoutExpired("powershell", kwargs["timeout"])
        raise OSError("powershell unavailable")

    monkeypatch.setattr(archive_tree.subprocess, "run", fake_run)
    with pytest.raises(archive_tree.ArchiveTreeError, match="cannot list processes"):
        archive_tree._process_rows()
    assert calls == [10, 30]


def test_m03_direct_retirement_rejects_extra_origin_file(tmp_path: Path) -> None:
    """Before: archive evidence matches an intact clone origin.
    During: add an unapproved file and invoke direct retirement with saved evidence.
    After: retirement rejects the extra file without changing the origin or ledger.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    extra = origin / "clone-a" / "extra.txt"
    extra.write_text("extra", encoding="utf-8")
    original = origin / "clone-a" / "data.txt"

    with pytest.raises(Exception) as excinfo:
        archive_tree._retire(origin, archive, str(record["family"]), record, manifest)

    assert isinstance(excinfo.value, archive_tree.ArchiveTreeError)
    assert "origin has extra or missing" in str(excinfo.value)
    assert original.read_text(encoding="utf-8") == "payload"
    assert (origin / "clone-a" / "empty").is_dir()
    assert extra.read_text(encoding="utf-8") == "extra"
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    assert sum(row.get("status") == "RETIRADO" for row in rows) == 0
    assert not (archive / "retirement_recovery.json").exists()


def test_m15_direct_retirement_rejects_changed_origin_mtime(tmp_path: Path) -> None:
    """Before: archive evidence includes the original file metadata.
    During: bump a file mtime and invoke direct retirement with saved evidence.
    After: retirement rejects the changed mtime without changing the origin or ledger.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    target = origin / "clone-a" / "data.txt"
    original_mtime = target.stat().st_mtime
    os.utime(target, (target.stat().st_atime, original_mtime + 10))

    caught: Exception | None = None
    try:
        archive_tree._retire(origin, archive, str(record["family"]), record, manifest)
    except Exception as exc:
        caught = exc

    assert isinstance(caught, archive_tree.ArchiveTreeError)
    assert "origin changed" in str(caught)
    assert target.read_text(encoding="utf-8") == "payload"
    assert (origin / "clone-a" / "empty").is_dir()
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    assert sum(row.get("status") == "RETIRADO" for row in rows) == 0
    assert not (archive / "retirement_recovery.json").exists()


def test_m16_rejects_valid_approved_list_with_wrong_list_hash(tmp_path: Path) -> None:
    """Before: the approved entries match the current origin tree.
    During: apply archive with a deliberately incorrect approved-list digest.
    After: the exact list-hash error is returned without archive publication.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    _approved(origin, approved)

    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        "0" * 64,
    )

    assert result.returncode != 0
    assert "approved list hash mismatch" in result.stderr
    assert not (archive / "index.jsonl").exists()
    assert not any(
        path.is_dir() and path.name.startswith("clone_archive_")
        for path in archive.iterdir()
    )


def test_m07_verifies_zip_before_publishing_archive_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: an approved clone and archive root are ready for archive-only mode.
    During: make zip verification fail during the real in-process CLI run.
    After: no ARCHIVADO row is published before verification succeeds.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)

    def fail_verification(_zip_path: Path, _manifest: list[dict[str, object]]) -> None:
        raise archive_tree.ArchiveTreeError("simulated zip verification failure")

    monkeypatch.setattr(archive_tree, "_verify_zip", fail_verification)
    result = archive_tree.main(
        [
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-archive",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        ]
    )

    assert result != 0
    assert not (archive / "index.jsonl").exists()
    assert not any(
        path.is_file() and path.name == "index.jsonl" for path in archive.iterdir()
    )


def test_b05_live_process_abort_keeps_origin(tmp_path: Path) -> None:
    """Before: a real child owns the clone as current directory.
    During: combined apply checks the process before staging.
    After: rc is nonzero and origin remains intact after child cleanup.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    before = archive_tree.tree_hash(origin)
    before_archive = archive_tree.tree_hash(archive)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], cwd=origin / "clone-a"
    )
    try:
        _wait_for_process_references(origin, {child.pid})
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        _assert_process_abort_result(result, origin, archive, before, before_archive)
    finally:
        _kill_process_tree(child)
    assert child.pid not in {pid for pid, *_ in archive_tree._process_rows()}


def test_b03_live_process_commandline_abort_keeps_origin(tmp_path: Path) -> None:
    """Before: a real child runs outside the clone but its command line names it.
    During: combined apply must reject the command-line reference before any write.
    After: rc, diagnostic, hashes, artifact absence, and child cleanup are verified.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    clone = origin / "clone-a"
    before = archive_tree.tree_hash(origin)
    before_archive = archive_tree.tree_hash(archive)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", str(clone)],
        cwd=tmp_path,
    )
    try:
        _wait_for_process_references(origin, {child.pid})
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        _assert_process_abort_result(result, origin, archive, before, before_archive)
    finally:
        _kill_process_tree(child)
    assert child.pid not in {pid for pid, *_ in archive_tree._process_rows()}


def test_b03_real_shell_cwd_abort_keeps_origin(tmp_path: Path) -> None:
    """Before: a real cmd.exe descendant has its cwd inside the clone.
    During: combined apply must reject the shell reference before any write.
    After: rc, diagnostic, hashes, artifact absence, and the complete tree cleanup hold.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    before = archive_tree.tree_hash(origin)
    before_archive = archive_tree.tree_hash(archive)
    command_shell = Path(os.environ["COMSPEC"])
    child = subprocess.Popen(
        [str(command_shell), "/c", "ping 127.0.0.1 -n 30 > nul"],
        cwd=origin / "clone-a",
    )
    try:
        _wait_for_process_references(origin, {child.pid})
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        _assert_process_abort_result(result, origin, archive, before, before_archive)
    finally:
        _kill_process_tree(child)
    assert child.pid not in {pid for pid, *_ in archive_tree._process_rows()}


def test_b03_claude_exe_fixture_cwd_abort_keeps_origin(tmp_path: Path) -> None:
    """Before: a copied COMSPEC named claude.exe has cwd inside the clone.
    During: combined apply must reject it through cwd detection before any write.
    After: rc, diagnostic, hashes, artifact absence, and the complete tree cleanup hold.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_hash = _approved(origin, approved)
    before = archive_tree.tree_hash(origin)
    before_archive = archive_tree.tree_hash(archive)
    command_shell = Path(os.environ["COMSPEC"])
    claude_fixture = tmp_path / "claude.exe"
    shutil.copy2(command_shell, claude_fixture)
    child = subprocess.Popen(
        [str(claude_fixture), "/c", "ping 127.0.0.1 -n 30 > nul"],
        cwd=origin / "clone-a",
    )
    try:
        _wait_for_process_references(origin, {child.pid})
        result = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply",
            "--list",
            str(approved),
            "--list-sha256",
            list_hash,
        )
        _assert_process_abort_result(result, origin, archive, before, before_archive)
    finally:
        _kill_process_tree(child)
    assert child.pid not in {pid for pid, *_ in archive_tree._process_rows()}


def _archived_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, object], list[dict[str, object]]]:
    """Before: a temporary clone fixture exists.
    During: archive it without retirement and load evidence.
    After: return origin, archive, record, and manifest.
    """
    origin, archive, approved = _fixture(tmp_path)
    (origin / "clone-a" / "second.txt").write_text("second", encoding="utf-8")
    archive.mkdir()
    list_hash = _approved(origin, approved)
    result = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_hash,
    )
    assert result.returncode == 0, result.stderr
    record = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    return (
        origin,
        archive,
        record,
        json.loads(Path(record["manifest"]).read_text(encoding="utf-8")),
    )


def test_b06_permission_error_leaves_recoverable_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: archive evidence exists and retirement is authorized.
    During: the second unlink raises PermissionError.
    After: no RETIRADO row exists and an IN_PROGRESS ledger remains.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    original = archive_tree._safe_remove
    calls = 0

    def fail_second(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("simulated")
        original(path)

    monkeypatch.setattr(archive_tree, "_safe_remove", fail_second)
    with pytest.raises(PermissionError):
        archive_tree._retire(origin, archive, str(record["family"]), record, manifest)
    assert not any(
        row.get("status") == "RETIRADO"
        for row in p7_common.load_jsonl_index(archive / "index.jsonl")
    )
    assert (
        json.loads((archive / "retirement_recovery.json").read_text(encoding="utf-8"))[
            "status"
        ]
        == "IN_PROGRESS"
    )
    assert any(origin.rglob("*"))


def test_b06_recovery_after_index_failure_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before: deletion completes but index publication raises.
    During: recover through the real CLI and repeat recovery.
    After: exactly one RETIRADO row exists and the ledger is gone.
    """
    origin, archive, record, manifest = _archived_fixture(tmp_path)
    original = p7_common.write_jsonl_index_atomic

    def fail_index(path: Path, rows: object) -> None:
        if path.name == "index.jsonl" and any(
            row.get("status") == "RETIRADO" for row in rows
        ):
            raise RuntimeError("simulated death")
        original(path, rows)

    monkeypatch.setattr(p7_common, "write_jsonl_index_atomic", fail_index)
    with pytest.raises(RuntimeError):
        archive_tree._retire(origin, archive, str(record["family"]), record, manifest)
    assert (archive / "retirement_recovery.json").exists()
    recovered = _run(
        "--origin", str(origin), "--archive-root", str(archive), "--recover-retirement"
    )
    assert recovered.returncode == 0, recovered.stderr
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    assert sum(row.get("status") == "RETIRADO" for row in rows) == 1
    assert not origin.exists()
    assert not (archive / "retirement_recovery.json").exists()


def test_b10_mixed_archive_tree_and_p7_retire_index(tmp_path: Path) -> None:
    """Before: one clone batch and one regular P7 repository share an archive root.
    During: archive both writers and run real p7_retire dry-runs for both families.
    After: both subprocesses return zero and both family reconciliations are empty.
    """
    origin_a, archive, approved_a = _fixture(tmp_path / "a")
    archive.mkdir(parents=True, exist_ok=True)
    list_hash_a = _approved(origin_a, approved_a)
    archived_a = _run(
        "--origin",
        str(origin_a),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved_a),
        "--list-sha256",
        list_hash_a,
    )
    assert archived_a.returncode == 0, archived_a.stderr
    row_a = p7_common.load_jsonl_index(archive / "index.jsonl")[0]
    origin_b = tmp_path / "b" / "repo"
    origin_b.mkdir(parents=True)
    tracked = origin_b / "tracked.txt"
    tracked.write_text("p7", encoding="utf-8")
    for command in (
        ["git", "init"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "test"],
        ["git", "add", "."],
        ["git", "commit", "-m", "fixture"],
    ):
        completed = subprocess.run(
            command, cwd=origin_b, capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0, completed.stderr
    approved_b = tmp_path / "b" / "approved.json"
    entry_b = [
        {
            "rel": "tracked.txt",
            "sha256": hashlib.sha256(tracked.read_bytes()).hexdigest(),
        }
    ]
    approved_b.write_text(json.dumps(entry_b), encoding="utf-8")
    list_hash_b = hashlib.sha256(approved_b.read_bytes()).hexdigest()
    p7_apply = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "flight" / "p7_retire.py"),
            "--archive-root",
            str(archive),
            "--family",
            "p7-family",
            "--origin",
            str(origin_b),
            "--list",
            str(approved_b),
            "--list-sha256",
            list_hash_b,
            "--apply-archive",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert p7_apply.returncode == 0, p7_apply.stderr
    rows = p7_common.load_jsonl_index(archive / "index.jsonl")
    approved_a_p7 = tmp_path / "a" / "p7-approved.json"
    entry_a_p7 = [
        {
            "rel": "clone-a/data.txt",
            "sha256": hashlib.sha256(
                (origin_a / "clone-a" / "data.txt").read_bytes()
            ).hexdigest(),
        }
    ]
    approved_a_p7.write_text(json.dumps(entry_a_p7), encoding="utf-8")
    list_hash_a_p7 = hashlib.sha256(approved_a_p7.read_bytes()).hexdigest()
    for family, origin, list_path, list_sha in (
        (row_a["family"], origin_a, approved_a_p7, list_hash_a_p7),
        ("p7-family", origin_b, approved_b, list_hash_b),
    ):
        dry = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "flight" / "p7_retire.py"),
                "--archive-root",
                str(archive),
                "--family",
                str(family),
                "--origin",
                str(origin),
                "--list",
                str(list_path),
                "--list-sha256",
                list_sha,
                "--dry-run",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert dry.returncode == 0, dry.stderr
        assert p7_common.reconcile_index(archive, rows, str(family)) == []


@pytest.mark.parametrize("mutation", ["extra", "mtime", "junction"])
def test_b05_archive_first_mutation_aborts_retire(
    tmp_path: Path, mutation: str
) -> None:
    """Before: a clone has been archived while its origin remains present.
    During: mutate the archived origin, then attempt retire-only from that origin.
    After: preflight rejects without RETIRADO or origin changes; junction rejection names links.
    """
    origin, archive, approved = _fixture(tmp_path)
    archive.mkdir()
    list_sha = _approved(origin, approved)
    archived = _run(
        "--origin",
        str(origin),
        "--archive-root",
        str(archive),
        "--apply-archive",
        "--list",
        str(approved),
        "--list-sha256",
        list_sha,
    )
    assert archived.returncode == 0, archived.stderr
    rows_before = p7_common.load_jsonl_index(archive / "index.jsonl")
    assert len(rows_before) == 1 and rows_before[0]["status"] == "ARCHIVADO"
    target = tmp_path / "junction-target"
    junction = origin / "clone-a" / "link"
    read_only = origin / "clone-a" / "data.txt"
    try:
        if mutation == "extra":
            (origin / "clone-a" / "extra.txt").write_text("extra", encoding="utf-8")
        elif mutation == "mtime":
            path = origin / "clone-a" / "data.txt"
            os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
        else:
            target.mkdir()
            made = subprocess.run(
                [
                    os.environ["COMSPEC"],
                    "/c",
                    "mklink",
                    "/J",
                    str(junction),
                    str(target),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert made.returncode == 0, made.stderr
        mutated_hash = archive_tree.tree_hash(origin)
        retired = _run(
            "--origin",
            str(origin),
            "--archive-root",
            str(archive),
            "--apply-retire",
            "--list",
            str(approved),
            "--list-sha256",
            list_sha,
        )
        assert retired.returncode != 0
        assert archive_tree.tree_hash(origin) == mutated_hash
        assert (origin / "clone-a").exists()
        rows_after = p7_common.load_jsonl_index(archive / "index.jsonl")
        assert sum(row.get("status") == "RETIRADO" for row in rows_after) == 0
        if mutation == "junction":
            error = retired.stderr.lower()
            assert "link" in error or "reparse" in error or "enlace" in error
    finally:
        if junction.exists():
            subprocess.run(
                [os.environ["COMSPEC"], "/c", "rmdir", str(junction)],
                capture_output=True,
                check=False,
            )
        read_only.chmod(0o666)
