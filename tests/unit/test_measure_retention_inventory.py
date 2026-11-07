"""Focal tests for the read-only retention inventory contract."""

from __future__ import annotations

import argparse
import copy
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


def emit_valid_photo(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    """Produce a valid photo through the production CLI for negative tests."""
    root = tmp_path / "valid-root"
    root.mkdir()
    (root / "valid.txt").write_text("valid", encoding="utf-8")
    photo_path = tmp_path / "valid-photo.json"
    result = run_cli(
        "--root",
        f"sample={root}",
        "--out",
        str(photo_path),
        "--flight-id",
        "flight-test",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return photo_path, read_json(photo_path)


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
        "partial": True,
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
    _, valid = emit_valid_photo(tmp_path)
    good = tmp_path / "good.json"
    good.write_text(json.dumps(valid), encoding="utf-8")
    wrong = tmp_path / "wrong.json"
    wrong_payload = copy.deepcopy(valid)
    wrong_payload["schema_version"] = 99
    wrong.write_text(json.dumps(wrong_payload), encoding="utf-8")
    out = tmp_path / "delta.json"
    result = run_cli("--compare", str(wrong), str(good), "--out", str(out))
    assert result.returncode == 2
    assert not out.exists()

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite_payload = copy.deepcopy(valid)
    nonfinite_payload["roots"]["sample"]["extra"] = 0
    nonfinite_text = json.dumps(nonfinite_payload).replace(
        '"extra": 0', '"extra": 1e999'
    )
    nonfinite.write_text(nonfinite_text, encoding="utf-8")
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
    _, valid = emit_valid_photo(tmp_path)
    cases: list[tuple[dict[str, object], str]] = []
    missing_roots = copy.deepcopy(valid)
    del missing_roots["roots"]
    cases.append((missing_roots, "campos ausentes"))
    roots_list = copy.deepcopy(valid)
    roots_list["roots"] = []
    cases.append((roots_list, "roots invalido"))
    compare_artifact = copy.deepcopy(valid)
    compare_artifact["mode"] = "compare"
    cases.append((compare_artifact, "artefacto compare"))
    wrong_files = copy.deepcopy(valid)
    wrong_files["roots"]["sample"]["files"] = "one"
    cases.append((wrong_files, "sample.files invalido"))
    good = tmp_path / "good.json"
    good.write_text(json.dumps(valid), encoding="utf-8")
    for index, (payload, expected_message) in enumerate(cases):
        first = tmp_path / f"first-{index}.json"
        out = tmp_path / f"delta-{index}.json"
        first.write_text(json.dumps(payload), encoding="utf-8")
        result = run_cli("--compare", str(first), str(good), "--out", str(out))
        assert result.returncode == 2, result.stdout + result.stderr
        assert "RETENTION_INVENTORY error" in result.stdout
        assert expected_message in result.stdout
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
        "partial": True,
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


def test_scandir_is_consumed_incrementally_and_closes_on_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow oversized directory stops before its iterator is exhausted."""
    from scripts.flight import measure_retention_inventory as inventory

    root = tmp_path / "large"
    root.mkdir()
    for index in range(128):
        (root / f"entry-{index}.txt").write_text("x", encoding="utf-8")
    original_scandir = inventory.os.scandir
    yielded: list[os.DirEntry[str]] = []
    state = {"closed": False}

    class SlowScanner:
        """Context-managed iterator that records early closure."""

        def __enter__(self) -> SlowScanner:
            self.iterator = original_scandir(root)
            return self

        def __iter__(self) -> SlowScanner:
            return self

        def __next__(self) -> os.DirEntry[str]:
            entry = next(self.iterator)
            yielded.append(entry)
            return entry

        def __exit__(self, *_args: object) -> None:
            self.iterator.close()
            state["closed"] = True

    def slow_scandir(path: Path) -> SlowScanner | os.ScandirIterator[str]:
        """Return the slow instrumented iterator only for the target root."""
        if Path(path) == root:
            return SlowScanner()
        return original_scandir(path)

    monkeypatch.setattr(inventory.os, "scandir", slow_scandir)
    clock = iter((0.0, 1.0))
    monkeypatch.setattr(inventory.time, "monotonic", lambda: next(clock))
    output = tmp_path / "photo.json"
    photo, rc = inventory._snapshot(
        argparse.Namespace(
            root=[f"sample={root}"],
            out=str(output),
            flight_id="flight-test",
            workspace_root=None,
            budget_seconds=0.5,
        )
    )

    assert rc == 1
    assert photo["partial"] is True
    assert "total" not in photo
    assert len(yielded) < 128
    assert state["closed"] is True


def test_photo_rejects_absent_or_truncated_root_without_partial(
    tmp_path: Path,
) -> None:
    """Snapshot invariants reject root states that contradict their partial flag."""
    _, valid = emit_valid_photo(tmp_path)
    for field in ("absent", "truncated"):
        payload = copy.deepcopy(valid)
        payload["roots"]["sample"][field] = True
        payload["roots"]["sample"]["partial"] = False
        first = tmp_path / f"invalid-{field}.json"
        second = tmp_path / f"valid-{field}.json"
        out = tmp_path / f"delta-{field}.json"
        first.write_text(json.dumps(payload), encoding="utf-8")
        second.write_text(json.dumps(valid), encoding="utf-8")

        result = run_cli("--compare", str(first), str(second), "--out", str(out))

        assert result.returncode == 2
        assert "partial" in result.stdout
        assert not out.exists()


def test_deep_extra_field_returns_rc2_without_traceback(tmp_path: Path) -> None:
    """A valid photo with a deeply nested extra field fails as a usage error."""
    _, valid = emit_valid_photo(tmp_path)
    good = tmp_path / "good-deep.json"
    good.write_text(json.dumps(valid), encoding="utf-8")
    deep = "[" * 2000 + "0" + "]" * 2000
    nested = tmp_path / "nested.json"
    nested_text = json.dumps(valid)[:-1] + f', "extra": {deep}}}'
    nested.write_text(nested_text, encoding="utf-8")
    out = tmp_path / "nested-delta.json"

    result = run_cli("--compare", str(nested), str(good), "--out", str(out))

    assert result.returncode == 2
    assert "RETENTION_INVENTORY error" in result.stdout
    assert "Traceback" not in result.stderr
    assert not out.exists()


def test_finite_recursion_error_is_usage_error_after_json_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parser-accepted deep field is rejected when finite() exhausts the stack."""
    from scripts.flight import measure_retention_inventory as inventory

    _, valid = emit_valid_photo(tmp_path)
    parse_limit = 1000
    finite_limit = 100
    deep = copy.deepcopy(valid)
    deep["extra"] = [0]
    for _ in range(200):
        deep["extra"] = [deep["extra"]]
    candidate = tmp_path / "finite-deep.json"
    candidate.write_text(json.dumps(deep), encoding="utf-8")
    shallow = copy.deepcopy(valid)
    shallow["extra"] = [0]
    shallow_candidate = tmp_path / "finite-shallow.json"
    shallow_candidate.write_text(json.dumps(shallow), encoding="utf-8")

    original_load = inventory.json.load
    parsed = False

    def load_then_lower_limit(handle: object, **kwargs: object) -> object:
        """Let json.load finish before lowering the limit for finite()."""
        nonlocal parsed
        photo = original_load(handle, **kwargs)
        parsed = True
        sys.setrecursionlimit(finite_limit)
        return photo

    monkeypatch.setattr(inventory.json, "load", load_then_lower_limit)

    previous_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(parse_limit)
        with pytest.raises(inventory.UsageError, match="demasiado anidada"):
            inventory._load_photo(candidate)
        assert parsed is True
        sys.setrecursionlimit(parse_limit)
        assert inventory._load_photo(shallow_candidate)["schema_version"] == 1
    finally:
        sys.setrecursionlimit(previous_limit)


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
