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

import json
import subprocess
import sys
from pathlib import Path

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
