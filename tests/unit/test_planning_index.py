"""Tests WOT-2026-090h: indice ON-DEMAND de .agent/planning/."""

from __future__ import annotations

from pathlib import Path

from scripts import planning_index as pi


def _make_planning(root: Path, files: dict[str, str]) -> Path:
    planning = root / ".agent" / "planning"
    for name, content in files.items():
        target = planning / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return planning


def test_026o_dod_a_index_lists_all_md_with_tipo(tmp_path: Path) -> None:
    """DoD(a): TODOS los .md de planning aparecen con su tipo clasificado."""
    _make_planning(
        tmp_path,
        {
            "work_plan.md": "x",
            "AUDIT_WOT-2026-001.md": "x",
            "builder_prompt_WOT-2026-002.md": "x",
            "revisor_veredicto_WOT-2026-003.md": "x",
            "PROPUESTA_foo.md": "x",
            "diseno_bar.md": "x",
            "decision_WOT-2026-004.json": "no-md",
            "sub/coso.md": "x",
            "sin_patron.md": "x",
        },
    )
    entries = pi.build_index(tmp_path / ".agent" / "planning")
    files = {e["file"] for e in entries}
    assert files == {
        "work_plan.md",
        "AUDIT_WOT-2026-001.md",
        "builder_prompt_WOT-2026-002.md",
        "revisor_veredicto_WOT-2026-003.md",
        "PROPUESTA_foo.md",
        "diseno_bar.md",
        "sub/coso.md",
        "sin_patron.md",
    }  # decision_WOT-2026-004.json NO es .md
    tipos = {e["file"]: e["tipo"] for e in entries}
    assert tipos["work_plan.md"] == "work_plan"
    assert tipos["AUDIT_WOT-2026-001.md"] == "AUDIT"
    assert tipos["builder_prompt_WOT-2026-002.md"] == "builder_prompt"
    assert tipos["revisor_veredicto_WOT-2026-003.md"] == "revisor_veredicto"
    assert tipos["PROPUESTA_foo.md"] == "propuesta"
    assert tipos["diseno_bar.md"] == "diseno"
    assert tipos["sin_patron.md"] == "otro"
    assert tipos["sub/coso.md"] == "otro"


def test_026o_dod_b_index_reflects_added_file(tmp_path: Path) -> None:
    """DoD(b): el indice queda STALE si se anade un fichero -- on-demand, la
    regeneracion lo refleja (el indice nunca es una foto persistida)."""
    _make_planning(tmp_path, {"work_plan.md": "x"})
    first = pi.build_index(tmp_path / ".agent" / "planning")
    assert len(first) == 1
    # Se anade un fichero NUEVO: el indice anterior no lo contiene; la
    # regeneracion on-demand si.
    _make_planning(tmp_path, {"AUDIT_nuevo.md": "y"})
    stale = [e["file"] for e in first]
    assert "AUDIT_nuevo.md" not in stale
    second = pi.build_index(tmp_path / ".agent" / "planning")
    assert len(second) == 2
    assert {e["file"] for e in second} == {"work_plan.md", "AUDIT_nuevo.md"}


def test_026o_render_is_navegable_markdown(tmp_path: Path) -> None:
    _make_planning(tmp_path, {"work_plan.md": "x", "sub/AUDIT_a.md": "x"})
    entries = pi.build_index(tmp_path / ".agent" / "planning")
    md = pi.render_markdown(tmp_path / ".agent" / "planning", entries)
    assert "[work_plan.md](work_plan.md)" in md
    assert "[sub/AUDIT_a.md](sub/AUDIT_a.md)" in md
    assert "| work_plan | 1 |" in md
    assert "| AUDIT | 1 |" in md


def test_026o_cli_persists_only_with_out(tmp_path: Path, capsys) -> None:
    """STOP de la ficha: el indice NO persiste por defecto; --out es opt-in."""
    _make_planning(tmp_path, {"work_plan.md": "x"})
    out_file = tmp_path / "indice.md"
    assert pi.main(["--project-root", str(tmp_path), "--out", str(out_file)]) == 0
    assert out_file.is_file()
    assert "work_plan.md" in out_file.read_text(encoding="utf-8")

    out_file2 = tmp_path / "indice2.md"
    assert pi.main(["--project-root", str(tmp_path)]) == 0
    assert not out_file2.exists()  # sin --out, nada persistido


def test_026o_cli_missing_planning_fails_closed(tmp_path: Path, capsys) -> None:
    assert pi.main(["--project-root", str(tmp_path)]) == 2
    assert "nunca un indice vacuo" in capsys.readouterr().err


def test_090h_r2_json_out_persists_json(tmp_path: Path) -> None:
    """Ronda 2 (hallazgo Codex): --json --out persiste JSON, no Markdown."""
    import json as jsonlib

    _make_planning(tmp_path, {"work_plan.md": "x"})
    out_file = tmp_path / "indice.json"
    assert (
        pi.main(["--project-root", str(tmp_path), "--json", "--out", str(out_file)])
        == 0
    )
    data = jsonlib.loads(out_file.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data[0]["file"] == "work_plan.md"
