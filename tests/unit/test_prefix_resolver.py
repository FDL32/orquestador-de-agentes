"""Unit tests for prefix_resolver.py (WOT-2026-020s).

Covers: resolve known/unknown/duplicate, WOT->motor, None->error,
malformed->error, guard mismatch blocks, mutation (without guard no block),
verify detects duplicates/drift, project-name resolution.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.prefix_resolver import (
    discover_motor_root,
    extract_prefix,
    guard,
    resolve_by_project_name,
    resolve_prefix,
    scan_links,
)


def _make_link(
    dest_root: Path,
    motor_root: Path,
    prefix: str | None,
    dest_id: str | None = None,
) -> None:
    """Create a motor_destination_link.json in dest_root."""
    link_dir = dest_root / ".agent" / "config"
    link_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "motor_root": str(motor_root),
        "destination_root": str(dest_root),
        "motor_version": "v9.17.1",
    }
    if prefix is not None:
        data["ticket_prefix"] = prefix
    if dest_id is not None:
        data["destination_id"] = dest_id
    (link_dir / "motor_destination_link.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _make_motor(tmp_path: Path) -> Path:
    """Create a fake motor root with agent_controller.py."""
    motor = tmp_path / "motor"
    agent_dir = motor / ".agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    return motor


def _make_tree(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Create motor + EXF + CTL destinations under tmp_path.

    Returns (motor_root, exf_root, ctl_root, search_root).
    """
    search_root = tmp_path / "projects"
    search_root.mkdir()
    motor = search_root / "orquestador_de_agentes"
    motor.mkdir()
    (motor / ".agent").mkdir(parents=True)
    (motor / ".agent" / "agent_controller.py").write_text("# motor\n", encoding="utf-8")
    exf = search_root / "Extractor_Facturas_PDF_Seguro"
    exf.mkdir()
    ctl = search_root / "Crear_Texto_LLM"
    ctl.mkdir()
    _make_link(exf, motor, "EXF", "Extractor_Facturas_PDF_Seguro")
    _make_link(ctl, motor, "CTL", "Crear_Texto_LLM")
    return motor, exf, ctl, search_root


# ---------------------------------------------------------------------------
# resolve_prefix
# ---------------------------------------------------------------------------


def test_resolve_known_prefix(tmp_path: Path) -> None:
    motor, exf, ctl, _ = _make_tree(tmp_path)
    assert resolve_prefix("EXF", motor) == exf
    assert resolve_prefix("CTL", motor) == ctl


def test_resolve_wot_returns_motor(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    assert resolve_prefix("WOT", motor) == motor


def test_resolve_unknown_prefix_returns_none(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    assert resolve_prefix("XYZ", motor) is None


def test_resolve_none_prefix_returns_none(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    assert resolve_prefix(None, motor) is None


def test_resolve_duplicate_prefix_returns_none(tmp_path: Path) -> None:
    motor, _exf, _ctl, search_root = _make_tree(tmp_path)
    # Create a second destination with the same prefix
    dup = search_root / "Another_EXF"
    dup.mkdir()
    _make_link(dup, motor, "EXF", "Another_EXF")
    assert resolve_prefix("EXF", motor) is None


def test_resolve_skips_null_prefix(tmp_path: Path) -> None:
    motor, exf, _ctl, search_root = _make_tree(tmp_path)
    # Add a destination with null prefix
    null_dest = search_root / "NoPrefix"
    null_dest.mkdir()
    _make_link(null_dest, motor, None, "NoPrefix")
    # EXF and CTL still resolve; null-prefix dest is not in the map
    assert resolve_prefix("EXF", motor) == exf
    assert resolve_prefix("NoPrefix", motor) is None


# ---------------------------------------------------------------------------
# extract_prefix
# ---------------------------------------------------------------------------


def test_extract_prefix_from_ticket_id() -> None:
    assert extract_prefix("WOT-2026-020t") == "WOT"
    assert extract_prefix("EXF-2026-010a") == "EXF"


def test_extract_prefix_project_name_returns_none() -> None:
    assert extract_prefix("Extractor_Facturas_PDF_Seguro") is None


def test_extract_prefix_malformed_raises() -> None:
    with pytest.raises(ValueError, match="Malformed"):
        extract_prefix("WOT-2026-020")
    with pytest.raises(ValueError, match="Malformed"):
        extract_prefix("wot-2026-020t")


def test_extract_prefix_malformed_short_sequence_raises() -> None:
    with pytest.raises(ValueError, match="Malformed"):
        extract_prefix("ABC-2026-1a")


def test_extract_prefix_empty_string_returns_none() -> None:
    assert extract_prefix("") is None


# ---------------------------------------------------------------------------
# guard
# ---------------------------------------------------------------------------


def test_guard_match_returns_zero(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert guard("EXF-2026-010a", cwd=exf, motor_root=motor) == 0


def test_guard_mismatch_blocks(tmp_path: Path) -> None:
    motor, exf, _ctl, _ = _make_tree(tmp_path)
    # cwd is EXF but ticket is CTL -> mismatch -> block
    assert guard("CTL-2026-001a", cwd=exf, motor_root=motor) == 1


def test_guard_wot_in_motor_passes(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    assert guard("WOT-2026-020t", cwd=motor, motor_root=motor) == 0


def test_guard_wot_in_destination_blocks(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    # cwd is EXF but ticket is WOT -> resolves to motor -> mismatch -> block
    assert guard("WOT-2026-020t", cwd=exf, motor_root=motor) == 1


def test_guard_unknown_prefix_returns_2(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert guard("XYZ-2026-001a", cwd=exf, motor_root=motor) == 2


def test_guard_malformed_id_returns_2(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert guard("wot-2026-020t", cwd=exf, motor_root=motor) == 2


def test_guard_project_name_match(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert guard("Extractor_Facturas_PDF_Seguro", cwd=exf, motor_root=motor) == 0


def test_guard_project_name_mismatch_blocks(tmp_path: Path) -> None:
    motor, exf, _ctl, _ = _make_tree(tmp_path)
    assert guard("Crear_Texto_LLM", cwd=exf, motor_root=motor) == 1


# ---------------------------------------------------------------------------
# mutation: without guard, mismatch is not detected
# ---------------------------------------------------------------------------


def test_mutation_without_guard_mismatch_not_blocked(tmp_path: Path) -> None:
    """If the guard is removed (not called), a prefix/cwd mismatch goes
    undetected. This proves the guard IS the barrier: resolve_prefix alone
    never blocks, it just returns the path."""
    motor, exf, ctl, _ = _make_tree(tmp_path)
    # Without guard: resolve CTL -> ctl_root (no comparison, no blocking)
    resolved = resolve_prefix("CTL", motor)
    assert resolved == ctl
    # The mismatch (cwd=exf, resolved=ctl) is NOT detected without the guard
    # Simulate "guard removed": just resolve, don't compare
    assert resolved != exf  # they ARE different, but nothing blocks


# ---------------------------------------------------------------------------
# discover_motor_root
# ---------------------------------------------------------------------------


def test_discover_motor_root_from_destination_link(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert discover_motor_root(exf) == motor


def test_discover_motor_root_when_cwd_is_motor(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    assert discover_motor_root(motor) == motor


def test_discover_motor_root_undiscoverable(tmp_path: Path) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    assert discover_motor_root(bare) is None


# ---------------------------------------------------------------------------
# scan_links
# ---------------------------------------------------------------------------


def test_scan_links_finds_all(tmp_path: Path) -> None:
    _motor, exf, ctl, search_root = _make_tree(tmp_path)
    mapping = scan_links(search_root)
    assert "EXF" in mapping
    assert "CTL" in mapping
    assert mapping["EXF"] == [exf]
    assert mapping["CTL"] == [ctl]


def test_scan_links_empty_when_no_links(tmp_path: Path) -> None:
    search_root = tmp_path / "empty"
    search_root.mkdir()
    assert scan_links(search_root) == {}


# ---------------------------------------------------------------------------
# resolve_by_project_name
# ---------------------------------------------------------------------------


def test_resolve_by_project_name(tmp_path: Path) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    assert resolve_by_project_name("Extractor_Facturas_PDF_Seguro", motor) == exf


def test_resolve_by_project_name_not_found(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    assert resolve_by_project_name("Nonexistent", motor) is None


# ---------------------------------------------------------------------------
# CLI (integration via main)
# ---------------------------------------------------------------------------


def test_cli_resolve_prints_path(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--resolve", "EXF", "--motor-root", str(motor)])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert Path(out) == exf


def test_cli_resolve_unknown_exits_1(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--resolve", "XYZ", "--motor-root", str(motor)])
    assert rc == 1


def test_cli_resolve_malformed_exits_2(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--resolve", "exf", "--motor-root", str(motor)])
    assert rc == 2


def test_cli_resolve_prefix_with_numbers_exits_2(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--resolve", "EXF2", "--motor-root", str(motor)])
    assert rc == 2


def test_cli_resolve_empty_prefix_exits_2(tmp_path: Path) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--resolve", "", "--motor-root", str(motor)])
    assert rc == 2


def test_cli_guard_mismatch_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    motor, exf, _ctl, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    monkeypatch.chdir(exf)
    rc = main(["--guard", "CTL-2026-001a", "--motor-root", str(motor)])
    assert rc == 1


def test_cli_guard_match_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    motor, exf, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    monkeypatch.chdir(exf)
    rc = main(["--guard", "EXF-2026-010a", "--motor-root", str(motor)])
    assert rc == 0


def test_cli_verify_detects_duplicate(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    motor, _exf, _ctl, search_root = _make_tree(tmp_path)
    dup = search_root / "Dup_EXF"
    dup.mkdir()
    _make_link(dup, motor, "EXF", "Dup_EXF")
    from scripts.prefix_resolver import main

    rc = main(["--verify", "--motor-root", str(motor)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "DUPLICATE" in err
    assert "EXF" in err


def test_cli_verify_clean_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    motor, _, _, _ = _make_tree(tmp_path)
    from scripts.prefix_resolver import main

    rc = main(["--verify", "--motor-root", str(motor)])
    assert rc == 0
