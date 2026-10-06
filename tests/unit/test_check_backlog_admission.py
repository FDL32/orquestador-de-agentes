"""Tests del Backlog Admission Guard (WOT-2026-054m).

Contrato: bloque T-054M-001 de `<destino>/.agent/planning/ticket_contracts.md`
(status: frozen). Cobertura por DoD:
- D1: CLI, exit 0/1/2, denominadores publicados, --json, --recibo-file.
- D2: trigger mecanico anclado a forma de fila y a la revision PADRE.
- D3: recibo contrastado fail-closed + LIMIT de superficies externas.
- D4: veredictos mecanicos; id-solo-en-archive y edicion que preserva el id
  NO disparan; renumeracion SI.
- D5: --revalidate mismo corpus verde / corpus cambiado rojo.
- D6: ALTA_CONCURRENTE determinista (reintroduccion con recibo propio;
  solape de superficies EXIGE corpus no re-derivado; sin solape ->
  RECIBO_INCOHERENTE).
- D7: cableado en closeout (SKIP nombrado sin origin/sin backlog) y
  PROPAGACION del rechazo a run_preflight_check(closeout_mode=True).

Repos git REALES en tmp_path (patron init_git_repo de
tests/test_pre_handoff_guard.py); subprocess de git NUNCA mockeado (D8).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import check_backlog_admission as cba
from scripts.prepush_check import run_backlog_admission_check


GUARD = Path(__file__).resolve().parents[2] / "scripts" / "check_backlog_admission.py"

BACKLOG_REL = ".agent/collaboration/backlog.md"
ARCHIVE_REL = ".agent/collaboration/_archive/backlog_done.md"
MEMORIA_REL = "mem/obs.jsonl"

HEADER = (
    "# Backlog (cola viva)\n\n## Vista rapida\n\n"
    "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def row(ticket: str, titulo: str = "ficha de prueba") -> str:
    return f"| Media | {ticket} | {titulo} deliverable_type: code | s | pending | - | test | - |\n"


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout


def init_repo(tmp_path: Path, backlog_extra: str = "", archive_extra: str = "") -> Path:
    """Repo real con origin/main; las filas `*_extra` viajan en el commit BASE
    (fuera de todo rango auditado: preexisten a la UNION)."""
    repo = tmp_path / "repo"
    (repo / ".agent" / "collaboration" / "_archive").mkdir(parents=True)
    git(tmp_path, "init", "--bare", "origin.git")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "builder@example.com")
    git(repo, "config", "user.name", "Builder Test")
    (repo / "README.md").write_text("# repo\n", encoding="utf-8")
    (repo / BACKLOG_REL).write_text(HEADER + backlog_extra, encoding="utf-8")
    (repo / ARCHIVE_REL).write_text("# Archivo\n" + archive_extra, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    git(repo, "remote", "add", "origin", str(tmp_path / "origin.git"))
    git(repo, "push", "-u", "origin", "main")
    return repo


def backlog_surface(repo: Path) -> dict:
    n = cba._recount_surface(repo, {"path": BACKLOG_REL, "tipo": "backlog"}, None, repo)
    return {"path": BACKLOG_REL, "tipo": "backlog", "repo": "alta", "entradas": n}


def build_recibo(repo: Path, cid: str, row_text: str, corpus: list[dict]) -> dict:
    corpus_sha, _sin_pin, _reconto = cba.derive_corpus_sha(repo, corpus, None, repo)
    return {
        "recibo_version": 1,
        "candidato_id": cid,
        "candidato_contenido_sha": cba._sha(row_text.rstrip("\n").encode("utf-8")),
        "corpus": corpus,
        "corpus_sha": corpus_sha,
        "entradas_censadas": sum(s["entradas"] for s in corpus),
        "algoritmo": cba.ALGORITMO_REQUERIDO,
        "umbral": cba.UMBRAL_REQUERIDO,
        "veredicto_propuesta": {"tipo": "NUEVA", "ids": []},
        "vecinos": [{"id": "WOT-2026-069f", "score": 0.09}],
    }


def msg_with_recibo(subject: str, recibo: dict) -> str:
    line = json.dumps(recibo, ensure_ascii=False, separators=(",", ":"))
    return f"{subject}\n\nBACKLOG-ADMISSION-RECIBO: {line}\n"


def commit_alta(repo: Path, row_text: str, message: str) -> str:
    p = repo / BACKLOG_REL
    p.write_text(p.read_text(encoding="utf-8") + row_text, encoding="utf-8")
    git(repo, "add", BACKLOG_REL)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def run_guard(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(GUARD), "--git-root", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# Seccion D1: CLI, exit codes, denominadores y modos directos.


def test_help_exit_0() -> None:
    """M1: la interfaz se verifica ANTES de invocar; --help -> exit 0."""
    proc = subprocess.run(
        [sys.executable, str(GUARD), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0
    assert "--git-root" in proc.stdout


def test_constants_pinned() -> None:
    """F2.3: los literales del guard coinciden con los del contrato."""
    from scripts import backlog_db_compare as bdc

    assert cba.ALGORITMO_REQUERIDO == "backlog_db_compare"
    assert cba.UMBRAL_REQUERIDO == 0.12
    assert bdc.UMBRAL_DEFAULT == 0.12


def test_zero_commits_range_passes(tmp_path: Path) -> None:
    """D1: exit 0 incluye 0 altas en rango, con denominador publicado."""
    repo = init_repo(tmp_path)
    code, out = run_guard(repo)
    assert code == 0
    assert "0 commits en el rango" in out
    assert "0 altas que contrastar" in out


def test_json_report(tmp_path: Path) -> None:
    """D1: --json publica exit/lines/findings con veredicto mecanico."""
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-910a"), "alta sin recibo")
    proc = subprocess.run(
        [sys.executable, str(GUARD), "--git-root", str(repo), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    assert report["exit"] == 1
    assert report["findings"][0]["veredicto"] == "SIN_RECIBO"
    assert report["findings"][0]["candidato_id"] == "WOT-2026-910a"


def test_recibo_file_modo_directo(tmp_path: Path) -> None:
    """D1: --recibo-file en modo directo (--base/--head) contrasta el recibo."""
    repo = init_repo(tmp_path)
    surface = backlog_surface(repo)
    recibo = build_recibo(repo, "WOT-2026-911a", row("WOT-2026-911a"), [surface])
    commit_alta(repo, row("WOT-2026-911a"), "alta sin recibo en mensaje")
    base = git(repo, "merge-base", "origin/main", "HEAD").strip()
    head = git(repo, "rev-parse", "HEAD").strip()
    recibo_file = tmp_path / "recibo.json"
    recibo_file.write_text(json.dumps(recibo), encoding="utf-8")
    code, out = run_guard(
        repo, "--base", base, "--head", head, "--recibo-file", str(recibo_file)
    )
    assert code == 0, out
    assert "RECIBO_COHERENTE" in out


# Seccion DoD d: mutacion rojo y verde.


def test_alta_sin_recibo_es_rojo(tmp_path: Path) -> None:
    """DoD (d) ROJO: fila con id nuevo y sin recibo -> SIN_RECIBO, exit 1."""
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-905a"), "alta de ficha nueva")
    code, out = run_guard(repo)
    assert code == 1, out
    assert "SIN_RECIBO" in out
    assert "WOT-2026-905a" in out
    assert "recibos encontrados: 0 en mensajes de commit" in out


def test_alta_con_recibo_coherente_es_verde(tmp_path: Path) -> None:
    """DoD (d) VERDE: la misma alta con recibo coherente pasa, y el informe
    publica el denominador de recibos."""
    repo = init_repo(tmp_path)
    surface = backlog_surface(repo)
    recibo = build_recibo(repo, "WOT-2026-906a", row("WOT-2026-906a"), [surface])
    commit_alta(repo, row("WOT-2026-906a"), msg_with_recibo("alta con recibo", recibo))
    code, out = run_guard(repo)
    assert code == 0, out
    assert "VEREDICTO GLOBAL: RECIBO_COHERENTE" in out
    assert "recibos encontrados: 1 en mensajes de commit" in out


# Seccion DoD c: contraste del recibo, nunca confianza.


def test_n_incoherente_falla(tmp_path: Path) -> None:
    """DoD (c): el guard CONTRASTA, no cree: N declarado != N contado -> ROJO."""
    repo = init_repo(tmp_path)
    surface = backlog_surface(repo)
    recibo = build_recibo(repo, "WOT-2026-907a", row("WOT-2026-907a"), [surface])
    recibo["corpus"][0]["entradas"] += 1
    recibo["entradas_censadas"] += 1
    commit_alta(repo, row("WOT-2026-907a"), msg_with_recibo("alta N mentiroso", recibo))
    code, out = run_guard(repo)
    assert code == 1, out
    assert "RECIBO_INCOHERENTE" in out
    assert "re-conteo en la revision padre" in out


def test_campo_faltante_falla(tmp_path: Path) -> None:
    """DoD (c): recibo sin campo obligatorio -> RECIBO_INCOHERENTE."""
    repo = init_repo(tmp_path)
    surface = backlog_surface(repo)
    recibo = build_recibo(repo, "WOT-2026-908a", row("WOT-2026-908a"), [surface])
    del recibo["umbral"]
    commit_alta(repo, row("WOT-2026-908a"), msg_with_recibo("alta sin umbral", recibo))
    code, out = run_guard(repo)
    assert code == 1, out
    assert "RECIBO_INCOHERENTE" in out
    assert "umbral" in out


def test_corpus_cambiado_falla(tmp_path: Path) -> None:
    """DoD (c): corpus_sha que no re-deriva en la revision padre -> ROJO."""
    repo = init_repo(tmp_path)
    surface = backlog_surface(repo)
    recibo = build_recibo(repo, "WOT-2026-909a", row("WOT-2026-909a"), [surface])
    recibo["corpus_sha"] = cba._sha(b"corpus inventado")
    commit_alta(repo, row("WOT-2026-909a"), msg_with_recibo("alta sha falso", recibo))
    code, out = run_guard(repo)
    assert code == 1, out
    assert "RECIBO_INCOHERENTE" in out
    assert "corpus_sha no re-deriva" in out


# Seccion DoD e: controles negativos.


def test_id_solo_en_archive_no_dispara(tmp_path: Path) -> None:
    """D4: un id presente SOLO en el archive padre NO es alta nueva. La fila
    archivada viaja en el BASE: preexiste a la UNION que mira el guard."""
    repo = init_repo(tmp_path, archive_extra=row("WOT-2026-920a", "archivada"))
    commit_alta(
        repo, row("WOT-2026-920a", "re-alta desde archive"), "vuelve del archive"
    )
    code, out = run_guard(repo)
    assert code == 0, out
    assert "altas detectadas: 0" in out


def test_edicion_que_preserva_id_no_dispara(tmp_path: Path) -> None:
    """DoD (e): editar una fila existente preservando el id NO dispara. La fila
    original viaja en el BASE: solo la edicion esta en el rango."""
    repo = init_repo(tmp_path, backlog_extra=row("WOT-2026-921a", "titulo original"))
    (repo / BACKLOG_REL).write_text(
        HEADER + row("WOT-2026-921a", "titulo EDITADO"), encoding="utf-8"
    )
    git(repo, "add", BACKLOG_REL)
    git(repo, "commit", "-m", "edita titulo de 921a")
    code, out = run_guard(repo)
    assert code == 0, out
    assert "altas detectadas: 0" in out


def test_mencion_de_id_en_prosa_no_dispara(tmp_path: Path) -> None:
    """WOT-2026-077a (cierre 2026-09-26): un ID ajeno mencionado en la PROSA de
    una fila (celda Titulo/Nota, nunca la celda Ticket) NO es alta nueva.

    Caso real que caza esto: ampliar la fila de un ticket existente con una
    nota tipo "se decidio NO dar de alta WOT-2026-XXXXx, se amplia esta fila
    en su lugar" -- el ID aparece en texto libre, no como ticket de la fila.
    Antes del fix, `row_line_ids`/`_row_ids_of_content` corrian el regex de
    ID sobre la FILA ENTERA (`canonical_ids(body)`), asi que ese ID mencionado
    colaba como "alta nueva sin recibo" y bloqueaba el cierre canonico de un
    ticket ajeno y limpio.
    """
    repo = init_repo(tmp_path, backlog_extra=row("WOT-2026-923a", "titulo original"))
    mentioning_row = (
        "| Media | WOT-2026-923a | titulo EDITADO [se decidio AMPLIAR esta "
        "fila en vez de dar de alta WOT-2026-923b, ver barrido de similitud] "
        "deliverable_type: code | s | pending | - | test | - |\n"
    )
    (repo / BACKLOG_REL).write_text(HEADER + mentioning_row, encoding="utf-8")
    git(repo, "add", BACKLOG_REL)
    git(repo, "commit", "-m", "amplia 923a, menciona 923b en prosa")
    code, out = run_guard(repo)
    assert code == 0, out
    assert "altas detectadas: 0" in out
    assert "WOT-2026-923b" not in out


def test_alta_commiteada_con_staging_vacio_dispara(tmp_path: Path) -> None:
    """DoD (e): el staging NO es el rango: alta YA COMMITEADA con staging vacio
    dispara igual."""
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-922a"), "alta commiteada")
    assert git(repo, "diff", "--cached", "--name-only").strip() == ""
    code, out = run_guard(repo)
    assert code == 1, out
    assert "SIN_RECIBO" in out


# Seccion D6: altas concurrentes deterministas.


def test_alta_concurrente_por_reintroduccion(tmp_path: Path) -> None:
    """D6-a: reintroducir un id ya anadido con recibo -> ALTA_CONCURRENTE,
    incluso cuando el segundo recibo es coherente."""
    repo = init_repo(tmp_path)
    surface = backlog_surface(repo)
    recibo1 = build_recibo(repo, "WOT-2026-923a", row("WOT-2026-923a"), [dict(surface)])
    commit_alta(repo, row("WOT-2026-923a"), msg_with_recibo("alta 923a", recibo1))
    (repo / BACKLOG_REL).write_text(HEADER, encoding="utf-8")
    git(repo, "add", BACKLOG_REL)
    git(repo, "commit", "-m", "retira 923a")
    recibo2 = build_recibo(repo, "WOT-2026-923a", row("WOT-2026-923a"), [surface])
    commit_alta(repo, row("WOT-2026-923a"), msg_with_recibo("re-alta 923a", recibo2))
    code, out = run_guard(repo)
    assert code == 1, out
    assert "ALTA_CONCURRENTE" in out
    assert "reintroduccion del id WOT-2026-923a" in out


def test_alta_concurrente_por_solape_de_superficies(tmp_path: Path) -> None:
    """D6-b: corpus que no re-deriva Y alta anterior que toco una superficie
    declarada -> ALTA_CONCURRENTE (solape de superficies)."""
    repo = init_repo(tmp_path)
    (repo / "mem").mkdir()
    (repo / MEMORIA_REL).write_text('{"id": "x"}\n', encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "memoria inicial")
    memoria = {
        "path": MEMORIA_REL,
        "tipo": "memoria",
        "repo": "alta",
        "entradas": 1,
    }
    recibo_b = build_recibo(
        repo, "WOT-2026-924b", row("WOT-2026-924b"), [dict(memoria)]
    )
    surface = backlog_surface(repo)
    recibo_a = build_recibo(repo, "WOT-2026-924a", row("WOT-2026-924a"), [surface])
    p = repo / BACKLOG_REL
    p.write_text(p.read_text(encoding="utf-8") + row("WOT-2026-924a"), encoding="utf-8")
    obs = repo / MEMORIA_REL
    obs.write_text(obs.read_text(encoding="utf-8") + '{"id": "y"}\n', encoding="utf-8")
    git(repo, "add", BACKLOG_REL, MEMORIA_REL)
    git(repo, "commit", "-m", msg_with_recibo("alta 924a + memoria", recibo_a))
    commit_alta(repo, row("WOT-2026-924b"), msg_with_recibo("alta 924b", recibo_b))
    code, out = run_guard(repo)
    assert code == 1, out
    assert "ALTA_CONCURRENTE" in out
    assert "toco superficies declaradas" in out
    assert MEMORIA_REL in out


def test_sin_solape_es_incoherente_no_concurrente(tmp_path: Path) -> None:
    """D6: desajuste NO atribuible a una alta anterior -> RECIBO_INCOHERENTE
    (re-barrido), nunca ALTA_CONCURRENTE."""
    repo = init_repo(tmp_path)
    (repo / "mem").mkdir()
    (repo / MEMORIA_REL).write_text('{"id": "x"}\n', encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "memoria inicial")
    memoria = {
        "path": MEMORIA_REL,
        "tipo": "memoria",
        "repo": "alta",
        "entradas": 1,
    }
    recibo_b = build_recibo(
        repo, "WOT-2026-925b", row("WOT-2026-925b"), [dict(memoria)]
    )
    surface = backlog_surface(repo)
    recibo_a = build_recibo(repo, "WOT-2026-925a", row("WOT-2026-925a"), [surface])
    commit_alta(repo, row("WOT-2026-925a"), msg_with_recibo("alta 925a", recibo_a))
    obs = repo / MEMORIA_REL
    obs.write_text(obs.read_text(encoding="utf-8") + '{"id": "y"}\n', encoding="utf-8")
    git(repo, "add", MEMORIA_REL)
    git(repo, "commit", "-m", "memoria crece sin altas")
    commit_alta(repo, row("WOT-2026-925b"), msg_with_recibo("alta 925b", recibo_b))
    code, out = run_guard(repo)
    assert code == 1, out
    assert "RECIBO_INCOHERENTE" in out
    assert "ALTA_CONCURRENTE" not in out


# Seccion D5: revalidacion en el consumidor del alta.


def test_revalidate_mismo_corpus_verde(tmp_path: Path) -> None:
    """D5: --revalidate contra el corpus ACTUAL: mismo sha -> exit 0."""
    repo = init_repo(tmp_path)
    surface = backlog_surface(repo)
    recibo = build_recibo(repo, "WOT-2026-926a", row("WOT-2026-926a"), [surface])
    recibo_file = tmp_path / "recibo.json"
    recibo_file.write_text(json.dumps(recibo), encoding="utf-8")
    code, out = run_guard(repo, "--revalidate", "--recibo", str(recibo_file))
    assert code == 0, out
    assert "RECIBO_COHERENTE (revalidate)" in out


def test_revalidate_corpus_cambiado_rojo(tmp_path: Path) -> None:
    """D5: corpus vivo distinto del recibo -> exit 1 con orden de re-barrido."""
    repo = init_repo(tmp_path)
    surface = backlog_surface(repo)
    recibo = build_recibo(repo, "WOT-2026-927a", row("WOT-2026-927a"), [surface])
    recibo_file = tmp_path / "recibo.json"
    recibo_file.write_text(json.dumps(recibo), encoding="utf-8")
    code, out = run_guard(repo, "--revalidate", "--recibo", str(recibo_file))
    assert code == 0, out
    p = repo / BACKLOG_REL
    p.write_text(p.read_text(encoding="utf-8") + row("WOT-2026-927z"), encoding="utf-8")
    code, out = run_guard(repo, "--revalidate", "--recibo", str(recibo_file))
    assert code == 1, out
    assert "RECIBO_INCOHERENTE" in out
    assert "REHACE EL BARRIDO" in out


# Seccion D3 LIMIT: superficies externas declaradas.


def test_superficie_externa_no_recontada(tmp_path: Path) -> None:
    """D3 LIMIT: superficies repo:externo cuentan en la coherencia interna, NO
    se re-cuentan y el informe las lista como NO_RECONTADA."""
    repo = init_repo(tmp_path)
    surface = backlog_surface(repo)
    externa = {
        "path": "externo/mem.jsonl",
        "tipo": "memoria",
        "repo": "externo",
        "entradas": 3,
    }
    recibo = build_recibo(
        repo, "WOT-2026-928a", row("WOT-2026-928a"), [surface, externa]
    )
    commit_alta(repo, row("WOT-2026-928a"), msg_with_recibo("alta con externa", recibo))
    code, out = run_guard(repo)
    assert code == 0, out
    assert "RECIBO_COHERENTE" in out
    assert "NO_RECONTADA" in out
    assert "externo/mem.jsonl" in out


# Secciones F2.5, F2.6 y M1: forma del recibo y medicion fallida.


def test_vecinos_requeridos_con_2_entradas(tmp_path: Path) -> None:
    """F2.6: vecinos obligatorio NO vacio cuando entradas_censadas >= 2."""
    repo = init_repo(tmp_path)
    (repo / BACKLOG_REL).write_text(
        HEADER + row("WOT-2026-930x") + row("WOT-2026-930y"), encoding="utf-8"
    )
    git(repo, "add", BACKLOG_REL)
    git(repo, "commit", "-m", "dos filas previas")
    surface = backlog_surface(repo)
    assert surface["entradas"] == 2
    recibo = build_recibo(repo, "WOT-2026-930a", row("WOT-2026-930a"), [surface])
    recibo["vecinos"] = []
    commit_alta(repo, row("WOT-2026-930a"), msg_with_recibo("alta sin vecinos", recibo))
    code, out = run_guard(repo)
    assert code == 1, out
    assert "vecinos vacio con entradas_censadas >= 2" in out


def test_propuesta_semantica_sin_ids_falla(tmp_path: Path) -> None:
    """F2.5: propuesta semantica (tipo != NUEVA) exige ids canonicos no vacios."""
    repo = init_repo(tmp_path)
    surface = backlog_surface(repo)
    recibo = build_recibo(repo, "WOT-2026-931a", row("WOT-2026-931a"), [surface])
    recibo["veredicto_propuesta"] = {"tipo": "DUPLICADO_DE", "ids": []}
    commit_alta(
        repo, row("WOT-2026-931a"), msg_with_recibo("propuesta sin ids", recibo)
    )
    code, out = run_guard(repo)
    assert code == 1, out
    assert "RECIBO_INCOHERENTE" in out
    assert "propuesta DUPLICADO_DE sin ids" in out


def test_medicion_fallida_es_rc2_no_veredicto(tmp_path: Path) -> None:
    """M1/D1: git roto -> exit 2 con marcador MEDICION_FALLIDA, nunca veredicto."""
    repo = init_repo(tmp_path)
    code, out = run_guard(repo, "--base", "deadbeef" * 5, "--head", "HEAD")
    assert code == 2, out
    assert "MEDICION_FALLIDA" in out
    assert "VEREDICTO" not in out


def test_guard_es_read_only(tmp_path: Path) -> None:
    """El guard no escribe nada: el repo queda limpio tras auditar."""
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-932a"), "alta sin recibo")
    run_guard(repo)
    assert git(repo, "status", "--porcelain").strip() == ""


# Seccion D7: cableado y propagacion al closeout.


def test_wiring_skip_nombrado_sin_origin(tmp_path: Path) -> None:
    """D7: rango no resoluble (sin origin/main) -> SKIP nombrado, nunca verde
    mudo; sin backlog -> SKIP nombrado."""
    repo = tmp_path / "sin_origin"
    (repo / ".agent" / "collaboration").mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "b@example.com")
    git(repo, "config", "user.name", "B")
    (repo / BACKLOG_REL).write_text(HEADER, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base sin origin")
    result = run_backlog_admission_check(repo)
    assert result.passed is True
    assert result.skipped is True
    assert "SKIP" in result.output

    sin_backlog = tmp_path / "sin_backlog"
    sin_backlog.mkdir()
    result = run_backlog_admission_check(sin_backlog)
    assert result.passed is True
    assert result.skipped is True
    assert "No backlog.md" in result.output


def test_wiring_propagacion_closeout(tmp_path: Path, monkeypatch) -> None:
    """D7/D8: con el gate nuevo como unico fallo, run_preflight_check
    (closeout_mode=True, sin --skip-gates) retorna 1; sin el fallo, 0; y fuera
    de closeout el gate no corre."""
    import scripts.prepush_check as pc

    ok = pc.CheckResult(name="stub", passed=True, output="", is_blocking=True)
    for fn in (
        "run_delivery_hygiene_check",
        "run_ruff_check",
        "run_ruff_format_check",
        "run_agent_controller_validate",
        "run_git_status_check",
        "run_backlog_contract_check",
        "run_ghost_ticket_ids_check",
        "run_contract_reconcile_check",
        "run_handoff_state_sha_check",
        "run_handoff_committed_check",
        "run_destination_pii_check",
        "run_closeout_reconciliation_check",
        "run_landed_evidence_shape_check",
        "run_motor_destination_integration_check",
        "run_contract_formation_check",
        "run_workspace_contract_formation_check",
        "run_batch_run_accounting_check",
        "run_seal_staleness_check",
        "run_distributable_planning_check",
        "run_guard_wiring_orphan_check",
        "run_prompt_wired_invocations_check",
        "run_loop_execution_check",
        "run_principal_freshness_check",
        "run_agent_write_enforced_check",
        "run_flight_plan_collision_check",
        "run_launch_prompt_paths_check",
        "run_arranques_index_check",
        "run_dec_receipt_check",
        "run_inbox_drainage_check",
        "run_portable_memory_archive_check",
        "run_validate_all",
    ):
        monkeypatch.setattr(pc, fn, lambda *a, **k: ok)

    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-940a"), "alta sin recibo")
    assert pc.run_preflight_check(repo, closeout_mode=True) == 1

    repo_limpio = init_repo(tmp_path / "limpio")
    assert pc.run_preflight_check(repo_limpio, closeout_mode=True) == 0

    assert pc.run_preflight_check(repo, closeout_mode=False) == 0


# Seccion WOT-2026-071a: grandfather-cutoff-sha.


def test_grandfather_cutoff_pre_cutoff_fails_without_flag(tmp_path: Path) -> None:
    """DoD b-i sin_fix: commit pre-cutoff sin recibo -> SIN_RECIBO, exit 1.

    Sin el flag, el guard se comporta igual que antes: cualquier alta sin
    recibo falla, independientemente de si el commit es ancestro de dd5570f.
    """
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-950a"), "alta historica sin recibo")
    code, out = run_guard(repo)
    assert code == 1, out
    assert "SIN_RECIBO" in out
    assert "VEREDICTO GLOBAL: FALLO" in out


def test_grandfather_cutoff_pre_cutoff_warns_with_flag(tmp_path: Path) -> None:
    """DoD b-i con_fix: commit pre-cutoff sin recibo + cutoff_sha -> WARN, exit 0.

    Con el flag --grandfather-cutoff-sha, las altas cuyo commit es ancestro
    del cutoff SHA se degradan a WARN_GRANDFATHERED y el veredicto global
    NO falla. El informe cita el censo 17/30 (57%).
    """
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-951a"), "alta historica sin recibo")
    code, out = run_guard(repo, "--grandfather-cutoff-sha", "HEAD")
    assert code == 0, out
    assert "WARN_GRANDFATHERED" in out
    assert "VEREDICTO GLOBAL: RECIBO_COHERENTE" in out
    assert "17/30 (57%)" in out
    assert "grandfathered: 1 alta(s) pre-cutoff" in out


def test_grandfather_cutoff_post_cutoff_still_fails(tmp_path: Path) -> None:
    """No-relajacion: commit post-cutoff sin recibo -> sigue FALLO.

    Un commit que NO es ancestro del cutoff SHA (es decir, post-cutoff) sin
    recibo sigue fallando como SIN_RECIBO, incluso con el flag.
    """
    repo = init_repo(tmp_path)
    # Crear un commit que NO es ancestro de HEAD (es decir, post-cutoff
    # en el contexto de la prueba, donde HEAD es el cutoff).
    commit_alta(repo, row("WOT-2026-952a"), "alta historica sin recibo")
    # Ahora creamos otro commit que es post-cutoff (no ancestro de HEAD).
    (repo / BACKLOG_REL).write_text(
        (repo / BACKLOG_REL).read_text(encoding="utf-8") + row("WOT-2026-953a"),
        encoding="utf-8",
    )
    git(repo, "add", BACKLOG_REL)
    git(repo, "commit", "-m", "post-cutoff alta sin recibo")
    head = git(repo, "rev-parse", "HEAD").strip()
    # El cutoff es el commit anterior (HEAD^), asi que HEAD es post-cutoff.
    code, out = run_guard(repo, "--grandfather-cutoff-sha", f"{head}^")
    assert code == 1, out
    assert "SIN_RECIBO" in out
    assert "WOT-2026-953a" in out
    assert "VEREDICTO GLOBAL: FALLO" in out


def test_grandfather_cutoff_default_unchanged(tmp_path: Path) -> None:
    """Default intacto: sin flag, comportamiento identico al actual.

    El guard sin --grandfather-cutoff-sha debe comportarse exactamente igual
    que antes: altas sin recibo -> FALLO, con recibo -> COHERENTE.
    """
    repo = init_repo(tmp_path)
    # Alta sin recibo -> fallo
    commit_alta(repo, row("WOT-2026-960a"), "alta sin recibo")
    code, out = run_guard(repo)
    assert code == 1, out
    assert "SIN_RECIBO" in out

    # Alta con recibo -> coherente
    repo2 = init_repo(tmp_path / "coherente")
    surface = backlog_surface(repo2)
    recibo = build_recibo(repo2, "WOT-2026-961a", row("WOT-2026-961a"), [surface])
    commit_alta(repo2, row("WOT-2026-961a"), msg_with_recibo("alta con recibo", recibo))
    code2, out2 = run_guard(repo2)
    assert code2 == 0, out2
    assert "RECIBO_COHERENTE" in out2


def test_grandfather_cutoff_mutation_verify(tmp_path: Path) -> None:
    """MUTACION: sin_fix/con_fix en el mismo repositorio.

    sin_fix: guard sin cutoff sobre el rango historico -> exit != 0 (rojo)
    con_fix: guard con cutoff sobre el mismo rango -> exit 0 (verde)
    """
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-970a"), "alta historica sin recibo")
    # sin_fix: sin flag -> rojo
    code_red, out_red = run_guard(repo)
    assert code_red == 1, out_red
    assert "SIN_RECIBO" in out_red
    # con_fix: con flag -> verde
    code_green, out_green = run_guard(repo, "--grandfather-cutoff-sha", "HEAD")
    assert code_green == 0, out_green
    assert "WARN_GRANDFATHERED" in out_green
    assert "VEREDICTO GLOBAL: RECIBO_COHERENTE" in out_green


def test_closeout_default_cutoff_grandfathers_known_debt(
    tmp_path: Path, monkeypatch
) -> None:
    """_audit_closeout(cutoff_sha=None) usa GRANDFATHER_CUTOFF_SHA_DEFAULT.

    DoD: el camino real de --session-close (prepush_check --closeout-mode ->
    _audit_closeout sin cutoff_sha explicito) NUNCA paso el flag hasta este
    fix, asi que CUALQUIER cierre de sesion posterior a la deuda historica de
    6d341ff quedaba bloqueado por 56 altas que nadie pudo revisar
    retroactivamente. El SHA real del motor no existe en este repo sintetico,
    asi que el default se monkeypatchea al commit del repo de PRUEBA -- lo
    que se ejercita es el CABLEADO (cutoff_sha=None -> usa la constante),
    no el valor concreto del SHA (eso ya lo cubren D2/mutation-verify).
    """
    repo = init_repo(tmp_path)
    cutoff = commit_alta(repo, row("WOT-2026-980a"), "alta historica sin recibo")
    # Alta POST-cutoff, sigue exigiendo recibo real (el default no amnistia
    # nada nuevo).
    commit_alta(repo, row("WOT-2026-980b"), "alta reciente sin recibo")
    monkeypatch.setattr(cba, "GRANDFATHER_CUTOFF_SHA_DEFAULT", cutoff)

    code, lines, skipped, _findings = cba._audit_closeout(repo, cutoff_sha=None)
    out = "\n".join(lines)
    assert not skipped, out
    assert code == 1, out
    assert "WOT-2026-980a" in out and "WARN_GRANDFATHERED" in out
    assert "WOT-2026-980b" in out and "SIN_RECIBO" in out


def test_closeout_cutoff_empty_string_disables_grandfather(tmp_path: Path) -> None:
    """cutoff_sha='' (string vacio explicito) desactiva el grandfather.

    Distingue None (usa el default) de '' (opt-out explicito para quien
    quiera auditar sin amnistia).
    """
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-981a"), "alta sin recibo")
    code, lines, skipped, _findings = cba._audit_closeout(repo, cutoff_sha="")
    out = "\n".join(lines)
    assert not skipped, out
    assert code == 1, out
    assert "SIN_RECIBO" in out
    assert "WARN_GRANDFATHERED" not in out


def test_closeout_extra_recibos_resolves_sin_recibo(tmp_path: Path) -> None:
    """_audit_closeout(extra_recibos=...) resuelve SIN_RECIBO (WOT-2026-089q).

    DoD: antes de este fix, el UNICO llamante real de produccion
    (`run_backlog_admission_check` en prepush_check.py) invocaba
    `_audit_closeout(project_root)` sin forma de inyectar un recibo generado
    FUERA del mensaje del commit -- asi que `--recibo-file` (ya documentado
    en el CLI) era alcanzable por invocacion manual pero INALCANZABLE desde
    `--session-close` real (medido dos veces: sesion 2026-09-26 y 2026-10-02,
    mismo hallazgo exacto). Mutation-verify: SIN `extra_recibos`, la alta
    sigue SIN_RECIBO (no hay regresion de comportamiento); CON el recibo
    correcto via `extra_recibos`, pasa a RECIBO_COHERENTE.
    """
    repo = init_repo(tmp_path)
    row_text = row("WOT-2026-982a")
    corpus = [
        backlog_surface(repo),
        {"path": ARCHIVE_REL, "tipo": "archive", "repo": "alta", "entradas": 0},
    ]
    recibo = build_recibo(repo, "WOT-2026-982a", row_text, corpus)
    sha = commit_alta(repo, row_text, "alta con recibo externo")

    # sin_fix: sin extra_recibos, sigue fallando igual que antes del cambio.
    code_sin, lines_sin, skipped_sin, _f = cba._audit_closeout(repo, extra_recibos=None)
    out_sin = "\n".join(lines_sin)
    assert not skipped_sin, out_sin
    assert code_sin == 1, out_sin
    assert "SIN_RECIBO" in out_sin

    # con_fix: con el recibo correcto inyectado, la misma alta pasa.
    code_con, lines_con, skipped_con, _f2 = cba._audit_closeout(
        repo, extra_recibos=[recibo]
    )
    out_con = "\n".join(lines_con)
    assert not skipped_con, out_con
    assert code_con == 0, out_con
    assert "RECIBO_COHERENTE" in out_con
    assert "SIN_RECIBO" not in out_con
    assert sha  # el commit auditado es el que recibio el recibo externo


def test_run_backlog_admission_check_reads_recibo_files_env(
    tmp_path: Path, monkeypatch
) -> None:
    """run_backlog_admission_check lee BACKLOG_ADMISSION_RECIBO_FILES (WOT-2026-089q).

    DoD: el call-site real de produccion (prepush_check.py) debe poder
    consumir recibos externos via variable de entorno, retrocompatible
    (variable vacia/ausente = comportamiento identico al anterior al fix).
    """
    repo = init_repo(tmp_path)
    row_text = row("WOT-2026-983a")
    corpus = [
        backlog_surface(repo),
        {"path": ARCHIVE_REL, "tipo": "archive", "repo": "alta", "entradas": 0},
    ]
    recibo = build_recibo(repo, "WOT-2026-983a", row_text, corpus)
    commit_alta(repo, row_text, "alta con recibo externo via env")

    recibo_path = tmp_path / "recibo_983a.json"
    recibo_path.write_text(json.dumps(recibo, ensure_ascii=False), encoding="utf-8")

    # sin_fix: sin la variable, sigue bloqueando (no-regresion).
    monkeypatch.delenv("BACKLOG_ADMISSION_RECIBO_FILES", raising=False)
    result_sin = run_backlog_admission_check(repo)
    assert result_sin.passed is False, result_sin.output
    assert "SIN_RECIBO" in result_sin.output

    # con_fix: con la variable apuntando al recibo externo, pasa.
    monkeypatch.setenv("BACKLOG_ADMISSION_RECIBO_FILES", str(recibo_path))
    result_con = run_backlog_admission_check(repo)
    assert result_con.passed is True, result_con.output
    assert "RECIBO_COHERENTE" in result_con.output


def test_run_backlog_admission_check_recibo_file_missing_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    """Un fichero de BACKLOG_ADMISSION_RECIBO_FILES inexistente falla CERRADO.

    DoD (hallazgo de revision por bucle adversarial, Codex/BA05): la carga de
    `_load_recibo_file` debe vivir DENTRO del `try` fail-closed de
    `run_backlog_admission_check`, nunca antes -- un fichero inexistente o
    con JSON invalido debe producir CheckResult(passed=False), no una
    excepcion sin capturar que tumbe el pipeline de cierre entero.
    """
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-984a"), "alta sin recibo")

    monkeypatch.setenv(
        "BACKLOG_ADMISSION_RECIBO_FILES", str(tmp_path / "no_existe.json")
    )
    result = run_backlog_admission_check(repo)
    assert result.passed is False, result.output
    assert "medicion fallida" in result.output or "SIN_RECIBO" in result.output


def test_run_backlog_admission_check_recibo_file_invalid_json_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    """Un fichero de recibo con JSON invalido falla CERRADO, no crashea."""
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-985a"), "alta sin recibo")

    bad_path = tmp_path / "recibo_roto.json"
    bad_path.write_text("{esto no es json valido", encoding="utf-8")
    monkeypatch.setenv("BACKLOG_ADMISSION_RECIBO_FILES", str(bad_path))

    result = run_backlog_admission_check(repo)
    assert result.passed is False, result.output
    assert "medicion fallida" in result.output


def test_audit_closeout_call_without_extra_recibos_kwarg_unchanged(
    tmp_path: Path,
) -> None:
    """Llamada POSICIONAL/sin kwarg nuevo se comporta EXACTAMENTE igual que
    antes del fix (hallazgo de revision, tokenharbor_qwen/BA90): no basta con
    probar `extra_recibos=None` explicito -- un llamante que invoque
    `_audit_closeout(repo)` o `_audit_closeout(repo, cutoff_sha)` (como ya
    hacian el resto de tests de este fichero, sin tocar el parametro nuevo
    en absoluto) debe seguir dando el MISMO resultado que antes del cambio.
    """
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-986a"), "alta sin recibo, sin extra_recibos")

    # Firma vieja exacta: solo repo, sin mencionar extra_recibos.
    _code, lines, skipped, _f = cba._audit_closeout(repo)
    out = "\n".join(lines)
    assert not skipped, out
    assert "SIN_RECIBO" in out or "WARN_GRANDFATHERED" in out

    # Firma vieja con cutoff_sha posicional, tampoco toca extra_recibos.
    code2, lines2, skipped2, _f2 = cba._audit_closeout(repo, "")
    out2 = "\n".join(lines2)
    assert not skipped2, out2
    assert code2 == 1, out2
    assert "SIN_RECIBO" in out2


def test_run_backlog_admission_check_empty_env_var_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    """BACKLOG_ADMISSION_RECIBO_FILES="" (vacia, no ausente) no cambia nada.

    Distingue "variable ausente" (delenv) de "variable presente pero vacia"
    (setenv con string vacio) -- ambas deben degradar a extra_recibos=None.
    """
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-987a"), "alta sin recibo")

    monkeypatch.setenv("BACKLOG_ADMISSION_RECIBO_FILES", "")
    result = run_backlog_admission_check(repo)
    assert result.passed is False, result.output
    assert "SIN_RECIBO" in result.output


# Seccion WOT-2026-090s: todo consumidor real expone la via del recibo externo.


def _alta_con_recibo_externo(tmp_path: Path, cid: str) -> tuple[Path, Path]:
    """Repo con una alta SIN recibo en el mensaje y su recibo coherente en disco."""
    repo = init_repo(tmp_path)
    row_text = row(cid)
    corpus = [
        backlog_surface(repo),
        {"path": ARCHIVE_REL, "tipo": "archive", "repo": "alta", "entradas": 0},
    ]
    recibo = build_recibo(repo, cid, row_text, corpus)
    commit_alta(repo, row_text, "alta con recibo externo")
    recibo_path = tmp_path / f"recibo_{cid}.json"
    recibo_path.write_text(json.dumps(recibo, ensure_ascii=False), encoding="utf-8")
    return repo, recibo_path


def _consumir_cli_modo_directo(
    repo: Path, recibo: Path | None, _mp
) -> tuple[bool, str]:
    base = git(repo, "merge-base", "origin/main", "HEAD").strip()
    head = git(repo, "rev-parse", "HEAD").strip()
    extra = ["--recibo-file", str(recibo)] if recibo else []
    code, out = run_guard(repo, "--base", base, "--head", head, *extra)
    return code == 0, out


def _consumir_cli_modo_cierre(repo: Path, recibo: Path | None, _mp) -> tuple[bool, str]:
    extra = ["--recibo-file", str(recibo)] if recibo else []
    code, out = run_guard(repo, *extra)
    return code == 0, out


def _consumir_prepush_check(repo: Path, recibo: Path | None, mp) -> tuple[bool, str]:
    if recibo:
        mp.setenv("BACKLOG_ADMISSION_RECIBO_FILES", str(recibo))
    else:
        mp.delenv("BACKLOG_ADMISSION_RECIBO_FILES", raising=False)
    result = run_backlog_admission_check(repo)
    return result.passed, result.output


# Consumidores reales del guard en el motor. El cuarto, el hook pre-push que
# instala cada destino (`scripts/check_backlog_admission_hook.py`), vive en el
# repo del destino y se prueba alli: el motor no conoce sus hooks. El quinto,
# `--session-close`, llega a `prepush_check` por un subproceso: lo cubre
# test_session_close_entrega_la_via_de_recibo_a_prepush_check. La lista se
# contrasta con los call-sites reales en
# test_todo_call_site_de_audit_closeout_pasa_extra_recibos.
CONSUMIDORES = {
    "cli_modo_directo": _consumir_cli_modo_directo,
    "cli_modo_cierre": _consumir_cli_modo_cierre,
    "prepush_check": _consumir_prepush_check,
}


@pytest.mark.parametrize("consumidor", sorted(CONSUMIDORES))
def test_consumidores_exponen_la_via_de_recibo_externo(
    tmp_path: Path, monkeypatch, consumidor: str
) -> None:
    """WOT-2026-090s (b): cada consumidor real acepta el recibo externo.

    El CLI documenta `--recibo-file`, pero en modo cierre (sin --base/--head,
    que es como lo invoca el hook pre-push del destino) lo DESCARTABA en
    silencio. Medido 2026-10-06 en el destino real: 15 recibos coherentes ->
    15 SIN_RECIBO sin rango y RECIBO_COHERENTE con rango. Cada caso exige las
    dos mitades: sin recibo el consumidor bloquea (no es un verde vacuo) y con
    recibo pasa. Mutation-verify: quitar `extra_recibos` de la rama de cierre
    de `main()` pone rojo el caso `cli_modo_cierre`.
    """
    # Hermetico: la variable exportada en el shell no debe colarse en la
    # mitad "sin recibo" de ningun consumidor.
    monkeypatch.delenv("BACKLOG_ADMISSION_RECIBO_FILES", raising=False)
    repo, recibo = _alta_con_recibo_externo(tmp_path, "WOT-2026-990a")
    consumir = CONSUMIDORES[consumidor]

    ok_sin, out_sin = consumir(repo, None, monkeypatch)
    assert not ok_sin, out_sin
    assert "SIN_RECIBO" in out_sin

    ok_con, out_con = consumir(repo, recibo, monkeypatch)
    assert ok_con, out_con
    assert "RECIBO_COHERENTE" in out_con
    assert "SIN_RECIBO" not in out_con


def test_session_close_entrega_la_via_de_recibo_a_prepush_check(
    tmp_path: Path, monkeypatch
) -> None:
    """WOT-2026-090s (b): el paso real del cierre entrega la variable.

    `--session-close` ejecuta `session_closeout._step_prepush_check`, que lanza
    prepush_check.py como SUBPROCESO (gates.step_prepush_check -> _run_script
    -> closeout_steps.support.run_script). La via del recibo externo
    (`BACKLOG_ADMISSION_RECIBO_FILES`) solo llega si esa cadena hereda el
    entorno. Con un project_root temporal sin link de motor, el runner resuelve
    `<root>/scripts/prepush_check.py`: aqui, una sonda que sale con 0 solo si
    recibe la variable. Dos mitades: sin variable el paso da FAIL; con ella,
    PASS. Mutation-verify: un `env` que no parta de `os.environ` en el runner
    pone roja la mitad PASS.
    """
    from scripts.session_closeout import _step_prepush_check

    sonda = tmp_path / "scripts" / "prepush_check.py"
    sonda.parent.mkdir(parents=True)
    sonda.write_text(
        "import os\n"
        "import sys\n"
        "valor = os.environ.get('BACKLOG_ADMISSION_RECIBO_FILES')\n"
        "sys.exit(0 if valor == 'a.json;b.json' else 1)\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("BACKLOG_ADMISSION_RECIBO_FILES", raising=False)
    sin = _step_prepush_check(tmp_path, dry_run=False)
    assert sin.status == "FAIL", sin.detail

    monkeypatch.setenv("BACKLOG_ADMISSION_RECIBO_FILES", "a.json;b.json")
    con = _step_prepush_check(tmp_path, dry_run=False)
    assert con.status == "PASS", con.detail


def test_cli_modo_cierre_no_relaja_la_coherencia(tmp_path: Path) -> None:
    """WOT-2026-090s (a): reenviar el recibo NO relaja su contraste.

    El recibo externo pasa ahora tambien por la rama de cierre del CLI; debe
    contrastarse igual que en modo directo. Un recibo con N mentiroso llega
    por --recibo-file y el guard sigue en ROJO con RECIBO_INCOHERENTE.
    """
    repo = init_repo(tmp_path)
    row_text = row("WOT-2026-991a")
    corpus = [
        backlog_surface(repo),
        {"path": ARCHIVE_REL, "tipo": "archive", "repo": "alta", "entradas": 0},
    ]
    recibo = build_recibo(repo, "WOT-2026-991a", row_text, corpus)
    recibo["corpus"][0]["entradas"] += 1
    recibo["entradas_censadas"] += 1
    commit_alta(repo, row_text, "alta con recibo externo incoherente")
    recibo_file = tmp_path / "recibo_incoherente.json"
    recibo_file.write_text(json.dumps(recibo, ensure_ascii=False), encoding="utf-8")

    code, out = run_guard(repo, "--recibo-file", str(recibo_file))

    assert code == 1, out
    assert "RECIBO_INCOHERENTE" in out
    assert "VEREDICTO GLOBAL: RECIBO_COHERENTE" not in out


def _call_sites_de_audit_closeout(scripts_dir: Path) -> list[tuple[str, bool]]:
    """(fichero:linea, pasa extra_recibos) de cada llamada real en scripts/."""
    sites: list[tuple[str, bool]] = []
    for py in sorted(scripts_dir.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", None)
            )
            if name == "_audit_closeout":
                where = f"{py.relative_to(scripts_dir.parent).as_posix()}:{node.lineno}"
                sites.append(
                    (where, any(kw.arg == "extra_recibos" for kw in node.keywords))
                )
    return sites


def test_todo_call_site_de_audit_closeout_pasa_extra_recibos() -> None:
    """WOT-2026-090s (b): enumera MECANICAMENTE los consumidores del guard.

    Familia `obs-grandfather-cutoff-flag-exists-but-consumer-never-passes-it`,
    cuarta instancia: la via existe y un consumidor no la pasa (09-24 el
    cutoff, 09-26 y 10-02 los recibos en el cierre, 10-06 la rama de cierre
    del CLI). Una lista escrita a mano no ve al consumidor nuevo; este test
    recorre con `ast` todas las llamadas a `_audit_closeout` de scripts/ y
    exige `extra_recibos=` en cada una. Sobre la revision anterior al fix
    habria nombrado `scripts/check_backlog_admission.py` (la rama de cierre de
    `main()`). El minimo de 2 llamadas evita un verde vacuo si la funcion se
    renombra.
    """
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    sites = _call_sites_de_audit_closeout(scripts_dir)

    assert len(sites) >= 2, sites
    sin_via = [where for where, pasa in sites if not pasa]
    assert not sin_via, f"llamadas a _audit_closeout sin extra_recibos: {sin_via}"
