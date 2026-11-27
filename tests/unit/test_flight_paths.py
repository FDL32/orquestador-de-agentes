"""Tests for the read-only flight path resolver (WOT-2026-240a)."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.flight import flight_paths


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "flight_paths.py"
LINK_REL = Path(".agent") / "config" / "motor_destination_link.json"


def _write_link(
    destination: Path,
    *,
    prefix: object = "ABC",
    destination_id: object = "destination",
    destination_root: Path | None = None,
    repos_root: Path | None = None,
) -> Path:
    """Write one synthetic destination link and return its path."""
    link = destination / LINK_REL
    link.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "destination_id": destination_id,
        "destination_root": str(destination_root or destination),
        "motor_root": str(destination.parent / "motor"),
        "ticket_prefix": prefix,
    }
    if repos_root is not None:
        payload["repos_root"] = str(repos_root)
    link.write_text(json.dumps(payload), encoding="utf-8")
    return link


def _run_cli(
    project_root: Path,
    repos_root: Path,
    vuelo_id: str = "vuelo-20261026b",
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the resolver CLI against an isolated fixture."""
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--project-root",
            str(project_root),
            "--repos-root",
            str(repos_root),
            "--vuelo-id",
            vuelo_id,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _payload(proc: subprocess.CompletedProcess[str]) -> dict[str, object]:
    """Parse the resolver's JSON response."""
    return json.loads(proc.stdout)


def test_r01_returns_exactly_the_five_approved_paths(tmp_path: Path) -> None:
    repos_root = tmp_path / "repos"
    destination = repos_root / "ABC"
    _write_link(destination, repos_root=repos_root)

    proc = _run_cli(destination, repos_root)

    assert proc.returncode == 0
    direct = flight_paths.resolve_flight_paths(
        destination, "vuelo-20261026b", repos_root
    )
    assert direct.paths == tuple(Path(path) for path in _payload(proc)["paths"])
    assert _payload(proc) == {
        "paths": [
            str(repos_root / "ABC" / "vuelos" / "vuelo-20261026b" / "salidas"),
            str(repos_root / "ABC" / "vuelos" / "vuelo-20261026b" / "clones"),
            str(repos_root / "ABC" / "vuelos" / "vuelo-20261026b" / "sandboxes"),
            str(repos_root / "ABC" / "vuelos" / "vuelo-20261026b" / "lentes"),
            str(repos_root / "_motor"),
        ],
        "warnings": [],
    }


@pytest.mark.parametrize(
    ("prefix", "cause"),
    [("__missing__", "falta"), (None, "null"), ("AR", "^[A-Z]{3}$")],
)
def test_r02_missing_null_or_invalid_prefix_fails_closed(
    tmp_path: Path, prefix: object, cause: str
) -> None:
    repos_root = tmp_path / "repos"
    destination = repos_root / "ABC"
    link = destination / LINK_REL
    if prefix == "__missing__":
        _write_link(destination, repos_root=repos_root)
        data = json.loads(link.read_text(encoding="utf-8"))
        del data["ticket_prefix"]
        link.write_text(json.dumps(data), encoding="utf-8")
    else:
        _write_link(destination, prefix=prefix, repos_root=repos_root)

    proc = _run_cli(destination, repos_root)
    payload = _payload(proc)

    assert proc.returncode == 1
    assert payload["paths"] == []
    assert str(link) in str(payload["error"])
    assert cause in str(payload["error"])


def test_r03_duplicate_prefix_with_distinct_destinations_fails(tmp_path: Path) -> None:
    repos_root = tmp_path / "repos"
    first = repos_root / "first"
    second = repos_root / "second"
    first_link = _write_link(first, destination_root=first, repos_root=repos_root)
    second_link = _write_link(second, destination_root=second, repos_root=repos_root)

    proc = _run_cli(first, repos_root)
    payload = _payload(proc)

    assert proc.returncode == 1
    assert payload["paths"] == []
    assert str(first_link) in str(payload["error"])
    assert str(second_link) in str(payload["error"])


def test_r04_duplicate_destination_id_is_only_a_warning(tmp_path: Path) -> None:
    repos_root = tmp_path / "repos"
    selected = repos_root / "selected"
    other = repos_root / "other"
    _write_link(selected, destination_id="same", repos_root=repos_root)
    other_link = _write_link(
        other, prefix=None, destination_id="same", repos_root=repos_root
    )

    proc = _run_cli(selected, repos_root)
    payload = _payload(proc)

    assert proc.returncode == 0
    assert len(payload["paths"]) == 5
    assert any(
        "AVISO" in warning and "same" in warning and str(other_link) in warning
        for warning in payload["warnings"]
    )


def test_r05_cli_is_strictly_read_only(tmp_path: Path) -> None:
    repos_root = tmp_path / "repos"
    destination = repos_root / "ABC"
    _write_link(destination, repos_root=repos_root)
    before = {
        path: path.stat().st_mtime_ns for path in tmp_path.rglob("*") if path.is_file()
    }
    missing_repos_root = tmp_path / "must-not-be-created"

    proc = _run_cli(destination, missing_repos_root)

    assert proc.returncode == 0
    assert not missing_repos_root.exists()
    after = {
        path: path.stat().st_mtime_ns for path in tmp_path.rglob("*") if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    ("vuelo_id", "repos_root", "expected_error"),
    [
        ("vuelo/uno", "{repos}", "vuelo_id"),
        ("vuelo\\uno", "{repos}", "vuelo_id"),
        ("vuelo..uno", "{repos}", "vuelo_id"),
        ("vuelo-1", "relative-repos", "repos_root"),
    ],
)
def test_r06_invalid_inputs_return_rc2_without_paths(
    tmp_path: Path,
    vuelo_id: str,
    repos_root: str,
    expected_error: str,
) -> None:
    real_repos_root = repos_root.format(repos=tmp_path / "repos")
    destination = tmp_path / "destination"
    _write_link(destination, repos_root=Path(real_repos_root))

    proc = _run_cli(destination, Path(real_repos_root), vuelo_id)
    if repos_root == "relative-repos":
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--project-root",
                str(destination),
                "--repos-root",
                repos_root,
                "--vuelo-id",
                vuelo_id,
            ],
            capture_output=True,
            text=True,
        )

    payload = _payload(proc)
    assert proc.returncode == 2
    assert payload["paths"] == []
    assert expected_error in str(payload["error"])


def test_r03_r04_sweep_uses_destination_siblings_not_repos_root(
    tmp_path: Path,
) -> None:
    """The collision/duplicate sweep must ignore ``repos_root`` entirely.

    Measured defect (IM, WOT-2026-240a, e-01 against the real vuelo
    workspace): sweeping ``repos_root`` (the normally-absent output tree)
    instead of the selected destination's own siblings silently hid the real
    ``destination_id`` duplicate this ticket exists to surface. ``repos_root``
    here is a disjoint tree from where the destinations live, exactly like
    the real ``C:/repos`` vs. ``Proyectos_Python`` layout.
    """
    repos_root = tmp_path / "repos"  # disjoint from both destination trees below

    dup_tree = tmp_path / "proyectos_dup"
    selected = dup_tree / "workspace"
    duplicate_sibling = dup_tree / "motor_checkout"
    _write_link(selected, destination_id="same", repos_root=repos_root)
    duplicate_link = _write_link(
        duplicate_sibling, prefix=None, destination_id="same", repos_root=repos_root
    )

    proc = _run_cli(selected, repos_root)
    payload = _payload(proc)
    assert proc.returncode == 0
    assert len(payload["paths"]) == 5
    assert any(
        "AVISO" in warning and "same" in warning and str(duplicate_link) in warning
        for warning in payload["warnings"]
    )

    collision_tree = tmp_path / "proyectos_collision"
    collision_a = collision_tree / "collision_a"
    collision_b = collision_tree / "collision_b"
    first_link = _write_link(
        collision_a, destination_root=collision_a, repos_root=repos_root
    )
    second_link = _write_link(
        collision_b, destination_root=collision_b, repos_root=repos_root
    )
    collision_proc = _run_cli(collision_a, repos_root)
    collision_payload = _payload(collision_proc)
    assert collision_proc.returncode == 1
    assert collision_payload["paths"] == []
    assert str(first_link) in str(collision_payload["error"])
    assert str(second_link) in str(collision_payload["error"])


def test_r07_imports_reader_primitives_without_defining_a_reader() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "scripts.prefix_resolver"
    ]
    assert len(imports) == 1
    assert {alias.name for alias in imports[0].names} >= {
        "_link_dirs",
        "_read_link",
        "find_destination_link",
    }
    own_reader_defs = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"_read_link", "read_link", "load_link", "_load_link"}
    }
    assert own_reader_defs == set()


def test_extra_cli_works_under_python_i_from_external_cwd(tmp_path: Path) -> None:
    """The path bootstrap protects route-loaded scripts from ``from scripts...``.

    This reproduces the measured failure where a route-loaded module had no repo
    root in ``sys.path``; both cases use a real isolated Python subprocess.
    """
    repos_root = tmp_path / "repos"
    destination = repos_root / "ABC"
    _write_link(destination, repos_root=repos_root)
    external_cwd = tmp_path / "outside"
    external_cwd.mkdir()

    cli = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPT),
            "--project-root",
            str(destination),
            "--repos-root",
            str(repos_root),
            "--vuelo-id",
            "vuelo-20261026b",
        ],
        cwd=external_cwd,
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 0
    assert "Traceback" not in cli.stderr

    import_script = (
        "import importlib.util, sys\n"
        f"path = {str(SCRIPT)!r}\n"
        "spec = importlib.util.spec_from_file_location('flight_paths_isolated', path)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules['flight_paths_isolated'] = mod\n"
        "spec.loader.exec_module(mod)\n"
    )
    loaded = subprocess.run(
        [sys.executable, "-I", "-c", import_script],
        cwd=external_cwd,
        capture_output=True,
        text=True,
    )
    assert loaded.returncode == 0
    assert "Traceback" not in loaded.stderr
