"""Tests de `check_ghost_ticket_ids` (WOT-2026-053i).

El guard nace de una fuga REAL y REPETIDA: `WOT-2026-053f` se cito en un commit
publicado con CI verde y no tenia fila en ninguna superficie -- la misma fuga que
se habia corregido horas antes para `053e`. El censo posterior encontro 9
fantasmas, no 1.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "cgti", _ROOT / "scripts" / "check_ghost_ticket_ids.py"
)
assert _SPEC and _SPEC.loader
cgti = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cgti)


def _make_repo(tmp_path: Path, subjects: list[str]) -> Path:
    """Repo git REAL con un commit por asunto. Hermetico: `.git` propio.

    Un fixture sin `.git` propio dejaria que el walk-up de git alcanzase el repo
    REAL y el probe contestaria sobre el arbol de la maquina, no sobre el
    fixture (vector documentado en AGENTS.md).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    for i, subject in enumerate(subjects):
        (repo / f"f{i}.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=None)
        subprocess.run(["git", "commit", "-q", "-m", subject], cwd=repo, check=True)
    return repo


def _make_dest(tmp_path: Path, live: str = "", archive: str = "") -> Path:
    dest = tmp_path / "dest"
    collab = dest / ".agent" / "collaboration" / "_archive"
    collab.mkdir(parents=True)
    (dest / ".agent" / "collaboration" / "backlog.md").write_text(
        live, encoding="utf-8"
    )
    (collab / "backlog_done.md").write_text(archive, encoding="utf-8")
    return dest


def test_ghost_is_detected_when_cited_but_unrowed(tmp_path):
    """El caso REAL: id en un commit, sin fila -> se reporta.

    Mutation-to-prove: si `collect_cited_ids` devolviera {} o el filtro de filas
    invirtiese el sentido, este id no aparece y la asercion cae.
    """
    repo = _make_repo(tmp_path, ["WOT-2026-099z: algo publicado"])
    dest = _make_dest(tmp_path)
    cited = cgti.collect_cited_ids(repo, 50)
    rows = cgti.collect_row_ids(dest / ".agent" / "collaboration")
    assert cited is not None and "WOT-2026-099z" in cited
    assert "WOT-2026-099z" not in rows, "no hay filas: debe ser fantasma"


def test_row_in_either_surface_clears_the_ghost(tmp_path):
    """Una fila en CUALQUIERA de las dos superficies basta para no ser fantasma.

    Cubre las DOS formas de fila del archive (id en celda 1 y en celda 2): un
    regex que solo mirase la primera daria FALSOS fantasmas sobre filas reales.
    """
    live = "| Media | WOT-2026-011a | titulo | scope | pending | - | o | - |\n"
    archive = "| WOT-2026-022b | completed | cerrado |\n"
    dest = _make_dest(tmp_path, live=live, archive=archive)
    rows = cgti.collect_row_ids(dest / ".agent" / "collaboration")
    assert "WOT-2026-011a" in rows, "fila con id en celda 2 (cola viva)"
    assert "WOT-2026-022b" in rows, "fila con id en celda 1 (seccion del archive)"


def test_git_unavailable_skips_instead_of_inventing_a_verdict(tmp_path):
    """Sin git legible -> None, para que el llamador haga SKIP.

    Devolver un set vacio seria un VERDE POR AUSENCIA DE MEDICION: parece "no hay
    fantasmas" cuando en realidad no se pudo mirar. Mutation-to-prove: cambiar el
    `return None` por `return {}` hace fallar esta asercion.
    """
    not_a_repo = tmp_path / "nope"
    not_a_repo.mkdir()
    assert cgti.collect_cited_ids(not_a_repo, 10) is None


def test_baseline_exempts_known_debt_but_not_new_leaks(tmp_path):
    """La baseline perdona la deuda censada, nunca una fuga nueva.

    El criterio es "cero fantasmas NUEVOS"; el censo de 9 es evidencia fechada,
    no criterio de aceptacion (regla de AGENTS.md sobre invariante vs medicion).
    """
    assert "WOT-2026-047r" in cgti.GHOST_BASELINE, "deuda censada 2026-08-09"
    assert "WOT-2026-053f" not in cgti.GHOST_BASELINE, (
        "053f se registro en el mismo acto: NO es deuda perdonada"
    )
