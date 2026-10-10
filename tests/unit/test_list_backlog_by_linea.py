"""Tests de WOT-2026-095b: listado read-only de fichas por [LINEA: <nombre>].

Dientes del DoD (d): las lineas del fixture usan un par con INCLUSION de
substring (X="governance" es substring de Y="backlog-governance"), de modo
que sustituir el match EXACTO por substring (`X in valor`) sobre-matchea la
ficha Y y el assert "exactamente 2" cae. (La pareja de ejemplo del contrato,
ensemble-backends vs ensemble-governance, NO se contiene entre si -- medido
2026-10-10 sobre el censo real de 18 valores; el propio contrato ordena
re-elegir el par para que la mutacion muerda, condicion STOP 2.)

El fixture cubre AMBOS layouts (lecciones
`a-wired-check-can-be-blind-to-the-layout-where-the-failure-lives` y
`asertar-en-la-capa-que-decide-el-resultado`): una ficha X vive en la cola
viva Prioridad-led, la otra en el bloque compacto `| Ticket | Estado | Nota |`
del archive; la ficha Y en una fila Prioridad-led del archive; la ficha sin
campo en la viva.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = _MOTOR_ROOT / "scripts" / "list_backlog_by_linea.py"

_SPEC = importlib.util.spec_from_file_location("list_backlog_by_linea", SCRIPT)
lbl = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lbl)

X = "governance"
Y = "backlog-governance"  # contiene a X como substring: trampa de mutacion

LIVE_TABLE = """# Backlog de prueba

## Vista rapida

| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |
|---|---|---|---|---|---|---|---|
| Alta | WOT-2026-001a | FICHA A con [LINEA: governance] en el titulo | s | pending | - | test | - |
| Media | WOT-2026-001d | FICHA D sin ningun campo de linea | s | blocked | - | test | condition: x |
"""

ARCHIVE_TABLE = """# Backlog cerrado de prueba

| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Commit |
|---|---|---|---|---|---|---|---|
| Media | WOT-2026-001b | FICHA B con [LINEA: backlog-governance] | s | completed | - | test | commit:1234567 |

## Cierre log

| Ticket | Estado | Nota |
|---|---|---|
| WOT-2026-001c | completed | cierre con [LINEA: governance] en la nota |
| WOT-2026-001e | superseded | duplicado historico, sin campo |
"""


@pytest.fixture()
def destino(tmp_path: Path) -> Path:
    colab = tmp_path / ".agent" / "collaboration"
    (colab / "_archive").mkdir(parents=True)
    (colab / "backlog.md").write_text(LIVE_TABLE, encoding="utf-8")
    (colab / "_archive" / "backlog_done.md").write_text(ARCHIVE_TABLE, encoding="utf-8")
    return tmp_path


def _run_with_env(
    args: list[str], root: Path | None, env_root: bool = False
) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env.pop("AGENT_PROJECT_ROOT", None)
    if env_root and root is not None:
        env["AGENT_PROJECT_ROOT"] = str(root)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )


def test_linea_exact_devuelve_exactamente_las_dos_fichas_x(destino: Path) -> None:
    """DoD (d) nuclear: `--linea governance` = EXACTAMENTE A y C, no B (Y)."""
    res = _run_with_env(["--project-root", str(destino), "--linea", X], destino)
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "WOT-2026-001a" in out  # layout viva Prioridad-led
    assert "WOT-2026-001c" in out  # layout compacto del archive (no ceguera)
    assert "WOT-2026-001b" not in out  # Y contiene X: SOLO exacto vale
    assert "WOT-2026-001d" not in out  # sin campo: nunca en listado por linea
    assert "fichas: 2 (viva: 1, archive: 1)" in out


def test_censo_lista_valores_crudos_y_separa_origenes(destino: Path) -> None:
    """DoD (b): censo por valor crudo, con conteo viva/archive por valor."""
    res = _run_with_env(["--project-root", str(destino), "--list-lineas"], destino)
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert f"{X}  fichas=2  viva=1  archive=1" in out
    assert f"{Y}  fichas=1  viva=0  archive=1" in out
    # el censo NO normaliza: ambos valores conviven como vocabulario crudo.
    assert Y in out and X in out


def test_censo_declara_fichas_sin_campo_y_jamas_linea_vacia(destino: Path) -> None:
    """DoD (c): contador explicito de fichas sin campo; nunca 'linea vacia'."""
    res = _run_with_env(["--project-root", str(destino), "--list-lineas"], destino)
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "fichas SIN campo [LINEA: 2 (viva: 1, archive: 1)" in out
    assert "linea vacia" not in out.lower()
    # ninguna consulta devuelve las fichas sin campo
    for query in (X, Y):
        r = _run_with_env(["--project-root", str(destino), "--linea", query], destino)
        assert r.returncode == 0
        assert "WOT-2026-001d" not in r.stdout
        assert "WOT-2026-001e" not in r.stdout


def test_cero_coincidencias_exit_cero_con_mensaje_claro(destino: Path) -> None:
    """Exit codes: listado con 0 fichas es 0 con mensaje explicito."""
    res = _run_with_env(
        ["--project-root", str(destino), "--linea", "no-existe-ninguna-linea"],
        destino,
    )
    assert res.returncode == 0, res.stderr
    assert "0 fichas" in res.stdout


def test_sin_root_falla_cerrado_sin_fallback_a_cwd(tmp_path: Path) -> None:
    """Fail-closed SIN --project-root ni AGENT_PROJECT_ROOT (exit != 0)."""
    res = _run_with_env(["--list-lineas"], None)
    assert res.returncode != 0
    assert "fail-closed" in res.stderr.lower() or "project-root" in res.stderr.lower()


def test_agent_project_root_es_respetado(destino: Path) -> None:
    """La raiz puede fijarse por AGENT_PROJECT_ROOT sin flag CLI."""
    res = _run_with_env(["--list-lineas"], destino, env_root=True)
    assert res.returncode == 0, res.stderr
    assert X in res.stdout


def test_backlog_md_ausente_es_fail_closed(destino: Path) -> None:
    """Sin backlog.md no hay universo posible: exit != 0, nunca 0 silencioso."""
    (destino / ".agent" / "collaboration" / "backlog.md").unlink()
    res = _run_with_env(["--project-root", str(destino), "--list-lineas"], destino)
    assert res.returncode != 0
    assert "backlog.md" in res.stderr


def test_archive_ausente_avisado_por_stderr_y_sigue_viva(destino: Path) -> None:
    """Destino fresco sin archive: aviso explicito, nunca silencio (M3)."""
    import shutil

    shutil.rmtree(destino / ".agent" / "collaboration" / "_archive")
    res = _run_with_env(["--project-root", str(destino), "--list-lineas"], destino)
    assert res.returncode == 0, res.stderr
    assert "archive ausente" in res.stderr
    assert "fichas=1  viva=1  archive=0" in res.stdout
    listing = _run_with_env(["--project-root", str(destino), "--linea", X], destino)
    assert listing.returncode == 0, listing.stderr
    assert "WOT-2026-001a" in listing.stdout
    assert "WOT-2026-001c" not in listing.stdout


def test_read_prio_fichas_empareja_parser_y_estado(destino: Path) -> None:
    """Unidad in-process: predicado compartido -> emparejamiento 1:1 con el parser."""
    live = destino / ".agent" / "collaboration" / "backlog.md"
    fichas = lbl.read_prio_fichas(live, lbl.ORIGEN_VIVA)
    assert [(f.ticket, f.estado, f.valores) for f in fichas] == [
        ("WOT-2026-001a", "pending", [X]),
        ("WOT-2026-001d", "blocked", []),
    ]


def test_desajuste_parser_estado_aborta_runtime_error(destino: Path) -> None:
    """El guard anti-zip silencioso: si parser y scan divergen, NO adivina."""
    live = destino / ".agent" / "collaboration" / "backlog.md"
    real_cells = lbl._estado_cells

    def _corto(path: Path) -> list[str]:
        return real_cells(path)[:1]

    monkey = pytest.MonkeyPatch()
    monkey.setattr(lbl, "_estado_cells", _corto)
    try:
        with pytest.raises(RuntimeError, match="desajuste"):
            lbl.read_prio_fichas(live, lbl.ORIGEN_VIVA)
    finally:
        monkey.undo()
