"""Focal tests for the read-only retention inventory contract."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "measure_retention_inventory.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the production CLI without touching a real project root."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def snapshot_args(tmp_path: Path, root: Path, *extra: str) -> tuple[str, ...]:
    """Build an explicit snapshot command for a temporary root."""
    return (
        "--root",
        f"sample={root}",
        "--out",
        str(tmp_path / "photo.json"),
        "--flight-id",
        "flight-test",
        *extra,
    )


def read_json(path: Path) -> dict[str, object]:
    """Read a produced photo."""
    return json.loads(path.read_text(encoding="utf-8"))


def test_family_key_is_casefolded_and_never_empty() -> None:
    """Names with punctuation, digits and case share stable non-empty keys."""
    from scripts.flight.measure_retention_inventory import family_key

    assert family_key("BA03.md") == family_key("ba03.md") == "ba"
    assert family_key("CIERRE_SESION_1.md") == "cierre"
    assert family_key("2026-11-06.md") == "(sin-letras)"
    assert family_key(".gitignore") == "(oculto)"
    assert family_key("archivo con espacios 1.md") == "archivo"


def test_snapshot_has_metadata_denominator_and_age_statistics(tmp_path: Path) -> None:
    """A complete temporary tree produces labelled per-root statistics."""
    root = tmp_path / "tree with space"
    root.mkdir()
    (root / "BA03.md").write_text("123", encoding="utf-8")
    (root / "ba04.md").write_text("12", encoding="utf-8")
    out = tmp_path / "photo.json"

    result = run_cli(
        "--root",
        f"sample={root}",
        "--out",
        str(out),
        "--flight-id",
        "flight-test",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    photo = read_json(out)
    assert photo["schema_version"] == 1
    assert photo["flight_id"] == "flight-test"
    assert isinstance(photo["captured_at"], str)
    assert "motor" in photo["commits"]
    assert photo["denominator"] == {"requested": 1, "measured": 1}
    record = photo["roots"]["sample"]
    assert record["files"] == 2
    assert record["bytes"] == 5
    assert record["truncated"] is False
    assert record["median_age_days"] is not None
    assert sum(record["histogram"].values()) == 2
    assert record["families"]["ba"]["files"] == 2


def test_missing_root_is_partial_and_other_roots_are_measured(tmp_path: Path) -> None:
    """An absent root gets rc 1 without hiding a valid root."""
    root = tmp_path / "valid"
    root.mkdir()
    (root / "x.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "photo.json"
    result = run_cli(
        "--root",
        f"missing={tmp_path / 'missing'}",
        "--root",
        f"valid={root}",
        "--out",
        str(out),
        "--flight-id",
        "flight-test",
    )

    assert result.returncode == 1
    photo = read_json(out)
    assert photo["denominator"] == {"requested": 2, "measured": 1}
    assert photo["roots"]["missing"]["absent"] is True
    assert photo["roots"]["valid"]["files"] == 1


def test_budget_marks_root_partial_and_hides_global_total(tmp_path: Path) -> None:
    """An exhausted injected budget never publishes a complete total."""
    root = tmp_path / "tree"
    root.mkdir()
    for index in range(70):
        (root / f"file{index}.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "photo.json"
    result = run_cli(
        *snapshot_args(
            tmp_path,
            root,
            "--budget-seconds",
            "0",
        )
    )

    assert result.returncode == 1
    photo = read_json(out)
    assert photo["roots"]["sample"]["truncated"] is True
    assert photo["partial"] is True
    assert "total" not in photo


@pytest.mark.skipif(os.name != "nt", reason="junction test requires Windows")
def test_junction_is_not_descended(tmp_path: Path) -> None:
    """A Windows reparse-point directory is omitted, not recursively counted."""
    root = tmp_path / "root"
    target = tmp_path / "target"
    root.mkdir()
    target.mkdir()
    (target / "hidden.txt").write_text("hidden", encoding="utf-8")
    junction = root / "junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    (root / "visible.txt").write_text("visible", encoding="utf-8")
    out = tmp_path / "photo.json"

    result = run_cli(*snapshot_args(tmp_path, root))

    assert result.returncode == 0
    record = read_json(out)["roots"]["sample"]
    assert record["files"] == 1
    assert record["omitted_links"] == 1


def test_output_inside_root_is_rejected_without_writing(tmp_path: Path) -> None:
    """The output path cannot contaminate the root being measured."""
    root = tmp_path / "root"
    root.mkdir()
    out = root / "photo.json"
    result = run_cli(
        "--root",
        f"sample={root}",
        "--out",
        str(out),
        "--flight-id",
        "flight-test",
    )

    assert result.returncode == 2
    assert not out.exists()


def test_git_states_are_distinguished(tmp_path: Path) -> None:
    """A temporary repository reports tracked, ignored and untracked files."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (root / "tracked.txt").write_text("tracked", encoding="utf-8")
    (root / "ignored.txt").write_text("ignored", encoding="utf-8")
    (root / "untracked.txt").write_text("untracked", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
    out = tmp_path / "photo.json"

    result = run_cli(*snapshot_args(tmp_path, root))

    assert result.returncode == 0
    states = {
        item["name"]: item["git"]
        for item in read_json(out)["roots"]["sample"]["files_detail"]
    }
    assert states["tracked.txt"] == "versionado"
    assert states["ignored.txt"] == "ignorado"
    assert states["untracked.txt"] == "sin_seguimiento"


def test_compare_reports_family_and_root_delta(tmp_path: Path) -> None:
    """Compare reports signed root and family changes and accepts new families."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    assert (
        run_cli(
            "--root",
            f"sample={root}",
            "--out",
            str(first),
            "--flight-id",
            "flight-test",
        ).returncode
        == 0
    )
    (root / "b.txt").write_text("bb", encoding="utf-8")
    assert (
        run_cli(
            "--root",
            f"sample={root}",
            "--out",
            str(second),
            "--flight-id",
            "flight-test",
        ).returncode
        == 0
    )
    out = tmp_path / "delta.json"
    result = run_cli("--compare", str(first), str(second), "--out", str(out))

    assert result.returncode == 0
    delta = read_json(out)
    assert delta["roots"]["sample"]["files_delta"] == 1
    assert delta["roots"]["sample"]["families"]["b"]["files_delta"] == 1


def test_invalid_photo_and_duplicate_root_are_usage_errors(tmp_path: Path) -> None:
    """Malformed input fails before creating an output artifact."""
    root = tmp_path / "root"
    root.mkdir()
    out = tmp_path / "photo.json"
    duplicate = run_cli(
        "--root",
        f"sample={root}",
        "--root",
        f"sample={root}",
        "--out",
        str(out),
        "--flight-id",
        "flight-test",
    )
    assert duplicate.returncode == 2
    assert not out.exists()

    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    result = run_cli("--compare", str(bad), str(bad), "--out", str(out))
    assert result.returncode == 2
    assert not out.exists()


def test_compare_warns_on_flight_mismatch_and_propagates_partial(
    tmp_path: Path,
) -> None:
    """Different flights warn while a partial root keeps rc 1."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    common = {
        "schema_version": 1,
        "captured_at": "2026-11-07T01:00:00Z",
        "commits": {},
        "denominator": {"requested": 1, "measured": 1},
        "roots": {
            "sample": {
                "files": 1,
                "bytes": 1,
                "partial": True,
                "truncated": True,
                "oldest_age_days": None,
                "median_age_days": None,
                "histogram": {},
                "families": {
                    "a": {
                        "files": 1,
                        "bytes": 1,
                        "oldest_age_days": None,
                        "median_age_days": None,
                    }
                },
                "files_detail": [],
                "stat_errors": 0,
                "traversal_errors": [],
                "omitted_links": 0,
                "absent": False,
                "reasons": [],
            }
        },
        "reasons": [],
        "partial": False,
    }
    first.write_text(
        json.dumps({**common, "flight_id": "one", "partial": True}), encoding="utf-8"
    )
    second.write_text(
        json.dumps({**common, "flight_id": "two", "partial": True}), encoding="utf-8"
    )
    out = tmp_path / "delta.json"

    result = run_cli("--compare", str(first), str(second), "--out", str(out))

    assert result.returncode == 1
    delta = read_json(out)
    assert delta["partial"] is True
    assert delta["roots"]["sample"]["partial"] is True
    assert delta["reasons"] == ["flight_id distinto entre fotos"]


def test_snapshot_requires_flight_id_and_never_overwrites_output(
    tmp_path: Path,
) -> None:
    """Missing identity and an existing destination are both rc 2."""
    root = tmp_path / "root"
    root.mkdir()
    no_id = tmp_path / "no-id.json"
    result = run_cli("--root", f"sample={root}", "--out", str(no_id))
    assert result.returncode == 2
    assert not no_id.exists()

    existing = tmp_path / "photo.json"
    existing.write_text("original", encoding="utf-8")
    result = run_cli(*snapshot_args(tmp_path, root))
    assert result.returncode == 2
    assert existing.read_text(encoding="utf-8") == "original"


def test_compare_rejects_wrong_schema_and_nonfinite_number(tmp_path: Path) -> None:
    """Malformed compare photos fail closed before creating the delta."""
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    out = tmp_path / "delta.json"
    result = run_cli("--compare", str(wrong), str(good), "--out", str(out))
    assert result.returncode == 2
    assert not out.exists()

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"schema_version": 1, "value": NaN}', encoding="utf-8")
    result = run_cli("--compare", str(nonfinite), str(good), "--out", str(out))
    assert result.returncode == 2
    assert not out.exists()


def test_scandir_error_marks_partial_without_global_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child traversal error is partial and the no-error control is complete."""
    from scripts.flight import measure_retention_inventory as inventory

    root = tmp_path / "root"
    bad = root / "bad-child"
    root.mkdir()
    bad.mkdir()
    (root / "visible.txt").write_text("visible", encoding="utf-8")
    calls: list[Path] = []
    original_scandir = inventory.os.scandir

    def scandir_with_failure(path: str | os.PathLike[str]) -> os.ScandirIterator[str]:
        """Raise only for the synthetic child and delegate every other call."""
        calls.append(Path(path))
        if Path(path) == bad:
            raise PermissionError("synthetic child denial")
        return original_scandir(path)

    monkeypatch.setattr(inventory.os, "scandir", scandir_with_failure)
    failed_out = tmp_path / "failed.json"
    failed_photo, failed_rc = inventory._snapshot(
        argparse.Namespace(
            root=[f"sample={root}"],
            out=str(failed_out),
            flight_id="flight-test",
            workspace_root=None,
            budget_seconds=60.0,
        )
    )

    assert bad in calls
    assert failed_rc == 1
    assert failed_photo["roots"]["sample"]["partial"] is True
    assert failed_photo["roots"]["sample"]["traversal_errors"]
    assert "total" not in failed_photo

    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    (clean_root / "visible.txt").write_text("visible", encoding="utf-8")
    clean_out = tmp_path / "clean.json"
    clean_photo, clean_rc = inventory._snapshot(
        argparse.Namespace(
            root=[f"sample={clean_root}"],
            out=str(clean_out),
            flight_id="flight-test",
            workspace_root=None,
            budget_seconds=60.0,
        )
    )
    assert clean_rc == 0
    assert clean_photo["roots"]["sample"]["partial"] is False
    assert "total" in clean_photo


def test_budget_checks_directories_without_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Many empty directories can truncate on the directory polling boundary."""
    from scripts.flight import measure_retention_inventory as inventory

    root = tmp_path / "deep"
    root.mkdir()
    current = root
    for index in range(65):
        current = current / f"directory-{index}"
        current.mkdir()

    clock = iter((0.0, 1.0))
    monkeypatch.setattr(inventory.time, "monotonic", lambda: next(clock))
    partial = inventory._scan_root(root, budget=0.5, now=0.0)

    assert partial["files"] == 0
    assert partial["truncated"] is True
    assert partial["partial"] is True

    monkeypatch.setattr(inventory.time, "monotonic", lambda: 0.0)
    complete = inventory._scan_root(root, budget=0.5, now=0.0)
    assert complete["files"] == 0
    assert complete["truncated"] is False
    assert complete["partial"] is False


def test_photo_structure_validation_rejects_malformed_compare_inputs(
    tmp_path: Path,
) -> None:
    """Missing roots, wrong containers, compare artifacts and wrong types fail closed."""
    valid = {
        "schema_version": 1,
        "captured_at": "2026-11-07T01:00:00Z",
        "flight_id": "flight-test",
        "commits": {},
        "denominator": {"requested": 1, "measured": 1},
        "partial": False,
        "roots": {},
        "reasons": [],
    }
    cases = [
        {"schema_version": 1},
        {**valid, "roots": []},
        {**valid, "mode": "compare"},
        {**valid, "roots": {"sample": {"files": "one"}}},
    ]
    for index, payload in enumerate(cases):
        first = tmp_path / f"first-{index}.json"
        second = tmp_path / f"second-{index}.json"
        out = tmp_path / f"delta-{index}.json"
        first.write_text(json.dumps(payload), encoding="utf-8")
        second.write_text(json.dumps(payload), encoding="utf-8")
        result = run_cli("--compare", str(first), str(second), "--out", str(out))
        assert result.returncode == 2, result.stdout + result.stderr
        assert "RETENTION_INVENTORY error" in result.stdout
        assert "AttributeError" not in result.stderr
        assert "TypeError" not in result.stderr
        assert not out.exists()


def test_compare_recomputes_global_partial_from_truncated_root(tmp_path: Path) -> None:
    """A structurally valid root marked truncated forces a partial comparison."""
    root_record = {
        "files": 0,
        "bytes": 0,
        "oldest_age_days": None,
        "median_age_days": None,
        "histogram": {},
        "families": {},
        "files_detail": [],
        "stat_errors": 0,
        "traversal_errors": [],
        "omitted_links": 0,
        "truncated": True,
        "partial": False,
        "absent": False,
        "reasons": [],
    }
    photo = {
        "schema_version": 1,
        "captured_at": "2026-11-07T01:00:00Z",
        "flight_id": "flight-test",
        "commits": {},
        "denominator": {"requested": 1, "measured": 1},
        "partial": False,
        "roots": {"sample": root_record},
        "reasons": [],
    }
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    out = tmp_path / "delta.json"
    first.write_text(json.dumps(photo), encoding="utf-8")
    second.write_text(json.dumps(photo), encoding="utf-8")

    result = run_cli("--compare", str(first), str(second), "--out", str(out))

    assert result.returncode == 1
    assert read_json(out)["partial"] is True


def test_budget_counts_omitted_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory of omitted entries can exhaust the entry budget."""
    from scripts.flight import measure_retention_inventory as inventory

    root = tmp_path / "links"
    root.mkdir()
    for index in range(65):
        (root / f"entry-{index}").write_text("x", encoding="utf-8")
    monkeypatch.setattr(inventory, "_is_reparse", lambda path: True)
    clock = iter((0.0, 1.0))
    monkeypatch.setattr(inventory.time, "monotonic", lambda: next(clock))

    result = inventory._scan_root(root, budget=0.5, now=0.0)

    assert result["files"] == 0
    assert result["omitted_links"] > 0
    assert result["truncated"] is True
    assert result["partial"] is True


def test_reparse_race_is_checked_when_directory_is_popped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory becoming a reparse point after enqueue is omitted safely."""
    from scripts.flight import measure_retention_inventory as inventory

    root = tmp_path / "root"
    child = root / "child"
    root.mkdir()
    child.mkdir()
    (child / "hidden.txt").write_text("hidden", encoding="utf-8")
    original = inventory._is_reparse
    calls: list[Path] = []

    def race(path: Path) -> bool:
        """Simulate a reparse transition only when the child is popped."""
        calls.append(path)
        return (path == child and len(calls) > 1) or original(path)

    monkeypatch.setattr(inventory, "_is_reparse", race)
    result = inventory._scan_root(root, budget=60.0, now=0.0)

    assert child in calls
    assert result["files"] == 0
    assert result["omitted_links"] == 1


def test_root_symlink_is_resolved_intentionally(tmp_path: Path) -> None:
    """A user-selected symlink root resolves to its target before scanning."""
    from scripts.flight import measure_retention_inventory as inventory

    target = tmp_path / "target"
    alias = tmp_path / "alias"
    target.mkdir()
    (target / "visible.txt").write_text("x", encoding="utf-8")
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("el sistema no permite crear symlinks")

    parsed = inventory._parse_roots([f"sample={alias}"])

    assert parsed == [("sample", target.resolve())]


def test_root_stat_failure_is_partial_and_has_no_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root permission failure is reported as partial rc 1."""
    from scripts.flight import measure_retention_inventory as inventory

    root = tmp_path / "root"
    root.mkdir()
    out = tmp_path / "photo.json"
    original_stat = inventory.Path.stat

    def denied(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        """Deny only the measured root and delegate all other stat calls."""
        if path == root:
            raise PermissionError("synthetic root denial")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(inventory.Path, "stat", denied)
    photo, rc = inventory._snapshot(
        argparse.Namespace(
            root=[f"sample={root}"],
            out=str(out),
            flight_id="flight-test",
            workspace_root=None,
            budget_seconds=60.0,
        )
    )

    assert rc == 1
    assert photo["roots"]["sample"]["partial"] is True
    assert "raiz ilegible" in photo["roots"]["sample"]["reasons"][0]
    assert "total" not in photo


def test_symlink_skip_can_be_controlled_on_any_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A patched symlink predicate exercises the portable skip branch."""
    from scripts.flight import measure_retention_inventory as inventory

    root = tmp_path / "root"
    fake_link = root / "fake-link"
    root.mkdir()
    fake_link.mkdir()
    original = inventory.Path.is_symlink
    monkeypatch.setattr(
        inventory.Path,
        "is_symlink",
        lambda path: path == fake_link or original(path),
    )

    result = inventory._scan_root(root, budget=60.0, now=0.0)

    assert result["omitted_links"] == 1
    assert result["files"] == 0


def test_file_stat_error_is_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disappearing/stat-denied file is counted and makes the root partial."""
    from scripts.flight import measure_retention_inventory as inventory

    root = tmp_path / "root"
    file_path = root / "file.txt"
    root.mkdir()
    file_path.write_text("x", encoding="utf-8")
    original_stat = inventory.os.stat

    def denied(
        path: os.PathLike[str] | str, *args: object, **kwargs: object
    ) -> os.stat_result:
        """Deny the synthetic file and delegate every other stat call."""
        if Path(path) == file_path:
            raise PermissionError("synthetic file denial")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(inventory.os, "stat", denied)
    result = inventory._scan_root(root, budget=60.0, now=0.0)

    assert result["stat_errors"] == 1
    assert result["partial"] is True
