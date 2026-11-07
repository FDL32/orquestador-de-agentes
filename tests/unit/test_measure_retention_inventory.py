"""Focal tests for the read-only retention inventory contract."""

from __future__ import annotations

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
                "families": {"a": {"files": 1, "bytes": 1}},
            }
        },
        "reasons": [],
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
