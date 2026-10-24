"""Tests de scripts/check_prompt_load_bearing_refs.py (WOT-2026-090p)."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_prompt_load_bearing_refs as chk  # noqa: E402


def _md(tmp_path: Path, text: str, name: str = "p.md") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def test_mutation_load_bearing_planning_ref_is_hit(tmp_path):
    p = _md(
        tmp_path,
        "> `x_design.md` (workspace planning) is load-bearing for this prompt\n",
    )
    hits = chk.find_violations([p])
    assert len(hits) == 1
    assert hits[0][1] == 1


def test_negative_control_provenance_marker_no_hit(tmp_path):
    p = _md(
        tmp_path,
        "> `x_design.md` (workspace planning) is load-bearing for this prompt. "
        "Procedencia no normativa.\n",
    )
    assert chk.find_violations([p]) == []


def test_doc_optimization_literal_paragraph_no_hit(tmp_path):
    para = (
        "Expediente de evidencia (mediciones, bucle de 3 rondas, contraejemplos "
        "completos):\n"
        "`<DESTINO>/.agent/planning/PROPUESTA_doc_optimization.md` -- ruta generica "
        "por destino, no\nnecesariamente existente en cada uno. **No hace falta "
        "leer ninguno de los dos para ejecutar este\nprotocolo.** La norma es "
        "normativa en el motor.\n"
    )
    assert chk.find_violations([_md(tmp_path, para)]) == []


def test_destino_prefixed_list_with_obligatorio_no_hit(tmp_path):
    p = _md(
        tmp_path, "- `DESTINO_ROOT/.agent/planning/repo_charter.md` (obligatorio)\n"
    )
    assert chk.find_violations([p]) == []


def test_workspace_artifacts_with_obligatorio_no_hit(tmp_path):
    p = _md(
        tmp_path,
        "Actualiza `STATE.md` y `work_plan.md`: paso obligatorio antes del cierre.\n",
    )
    assert chk.find_violations([p]) == []


def test_obligatorio_alone_is_not_a_normative_marker(tmp_path):
    p = _md(tmp_path, "Ver `.agent/planning/x.md`, es obligatorio leerlo.\n")
    assert chk.find_violations([p]) == []


def test_paragraph_boundary_blank_line_isolates(tmp_path):
    p = _md(tmp_path, "see .agent/planning/x.md\n\nthis is load-bearing\n")
    assert chk.find_violations([p]) == []


def test_unreadable_file_reported_not_skipped(tmp_path):
    hits = chk.find_violations([tmp_path / "missing.md"])
    assert hits and hits[0][1] == 0


def test_known_debt_hit_warns_and_exits_zero(tmp_path, monkeypatch):
    hits = [("a.md", 3, "x"), ("b.md", 1, "y")]
    blocking, warned, settled = chk.apply_known_debt(hits, {"a.md": "WOT-2026-124a"})
    assert blocking == [("b.md", 1, "y")]
    assert warned == [("a.md", 3, "x")]
    assert settled == []

    only_debt = [("a.md", 3, "x")]
    monkeypatch.setattr(chk, "build_denominator", lambda root: (1, ["a.md"], None))
    monkeypatch.setattr(chk, "find_violations", lambda paths, root=None: only_debt)
    code, out = chk.audit(tmp_path, {"a.md": "WOT-2026-124a"})
    assert code == 0
    assert any("WARN" in ln and "WOT-2026-124a" in ln for ln in out)


def test_known_debt_without_hits_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(chk, "build_denominator", lambda root: (1, ["a.md"], None))
    monkeypatch.setattr(chk, "find_violations", lambda paths, root=None: [])
    code, out = chk.audit(tmp_path, {"a.md": "WOT-2026-124a"})
    assert code == 1
    assert any("deuda saldada" in ln for ln in out)


def test_non_debt_hit_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(chk, "build_denominator", lambda root: (1, ["z.md"], None))
    monkeypatch.setattr(
        chk, "find_violations", lambda paths, root=None: [("z.md", 2, "t")]
    )
    code, _out = chk.audit(tmp_path, {})
    assert code == 1


def test_known_debt_is_closed_declared_list():
    assert set(chk.KNOWN_DEBT.values()) == {"WOT-2026-124a"}
    assert len(chk.KNOWN_DEBT) == 2


def test_extra_scope_in_real_denominator():
    n, files, err = chk.build_denominator(ROOT)
    assert err is None and n > 0
    for extra in chk.EXTRA_SCOPE:
        assert extra in files


def test_empty_denominator_exit_1(tmp_path):
    # tmp_path sin MANIFEST.distribute -> denominador vacio -> fail-closed
    code, out = chk.audit(tmp_path)
    assert code == 1
    assert any("FAIL-CLOSED" in ln for ln in out)


def test_git_failure_is_fail_closed(tmp_path, monkeypatch):
    (tmp_path / "MANIFEST.distribute").write_text("prompts/\n", encoding="utf-8")
    monkeypatch.setattr(chk, "_git", lambda root, *a: (1, []))
    code, _out = chk.audit(tmp_path)
    assert code == 1


def test_real_tree_exit_zero():
    code, out = chk.audit(ROOT)
    assert code == 0, "\n".join(out)


def test_main_returns_audit_code(capsys):
    assert chk.main(["--motor-root", str(ROOT)]) == 0
    assert "entradas ->" in capsys.readouterr().out
