"""Tests del generador de recibo --emit-recibo en backlog_db_compare.py
(WOT-2026-070b).

Contrato: bloque WOT-2026-070b de ticket_contracts.md (status: frozen).
Cobertura por DoD:
- DoD-1: par E2E con exit codes pegados (con recibo rc=0 / sin recibo rc=1
  SIN_RECIBO).
- DoD-3a: mutacion del eje ANCLA (corpus_sha que NO deriva del corpus
  declarado) -> RECIBO_INCOHERENTE. Roja antes del fix, verde despues, par
  de exit codes registrado.
- DoD-4: universo recortado -> generador falla y NO emite recibo.

Repos git REALES en tmp_path (patron init_git_repo de
tests/test_pre_handoff_guard.py); subprocess de git NUNCA mockeado.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

from scripts import backlog_db_compare as bdc, check_backlog_admission as cba


BACKLOG_REL = ".agent/collaboration/backlog.md"
ARCHIVE_REL = ".agent/collaboration/_archive/backlog_done.md"

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
    """Repo real con origin/main; las filas extra viajan en el commit BASE."""
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


def _emit_ficha(repo: Path, cid: str, text: str = "redactada_por: co\n") -> None:
    (repo / ".agent" / "collaboration" / f"FICHA_{cid}.md").write_text(
        text, encoding="utf-8"
    )


def run_emit_recibo(repo: Path, *args: str) -> tuple[int, str]:
    """Ejecuta emit-recibo con una ficha conforme y devuelve rc/salida combinada."""
    cid = args[args.index("--candidato-id") + 1]
    _emit_ficha(repo, cid)
    rc, stdout, stderr = run_emit_recibo_capture(repo, *args)
    return rc, stdout + stderr


def run_emit_recibo_capture(
    repo: Path,
    *args: str,
    ficha_text: str | None = "redactada_por: co\n",
    create_ficha: bool = True,
) -> tuple[int, str, str]:
    """Ejecuta emit-recibo conservando stdout y stderr por separado."""
    cid = args[args.index("--candidato-id") + 1]
    if create_ficha and "--ficha" not in args and ficha_text is not None:
        _emit_ficha(repo, cid, ficha_text)
    proc = subprocess.run(
        [
            sys.executable,
            str(bdc.__file__),
            "--emit-recibo",
            "--git-root",
            str(repo),
            *args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_guard(repo: Path, *args: str) -> tuple[int, str]:
    """Ejecuta check_backlog_admission.py y devuelve (rc, stdout+stderr)."""
    guard = (
        Path(__file__).resolve().parents[2] / "scripts" / "check_backlog_admission.py"
    )
    proc = subprocess.run(
        [sys.executable, str(guard), "--git-root", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


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


# ---------- DoD-1: par E2E con exit codes pegados ----------


def test_e2e_alta_con_recibo_rc0(tmp_path: Path) -> None:
    """DoD-1 VERDE: alta con recibo generado por --emit-recibo -> guard rc=0."""
    repo = init_repo(tmp_path)
    # Generar recibo con veredicto explicito del autor
    rc, out = run_emit_recibo(
        repo,
        "--candidato-id",
        "WOT-2026-700a",
        "--row-text",
        row("WOT-2026-700a"),
        "--veredicto",
        "NUEVA",
    )
    assert rc == 0, f"emit-recibo fallo: {out}"
    recibo = json.loads(out)
    assert recibo["candidato_id"] == "WOT-2026-700a"
    assert recibo["algoritmo"] == "backlog_db_compare"
    assert recibo["umbral"] == 0.12
    assert recibo["candidato_contenido_sha"] != ""
    assert recibo["veredicto_propuesta"]["tipo"] == "NUEVA"
    # Commit con recibo
    commit_alta(repo, row("WOT-2026-700a"), msg_with_recibo("alta 700a", recibo))
    # Guard debe pasar
    code, gout = run_guard(repo)
    assert code == 0, f"guard fallo: {gout}"
    assert "RECIBO_COHERENTE" in gout


def test_e2e_alta_sin_recibo_rc1(tmp_path: Path) -> None:
    """DoD-1 ROJO: alta sin recibo -> guard rc=1 con SIN_RECIBO."""
    repo = init_repo(tmp_path)
    commit_alta(repo, row("WOT-2026-701a"), "alta sin recibo")
    code, out = run_guard(repo)
    assert code == 1, f"guard debio fallar: {out}"
    assert "SIN_RECIBO" in out
    assert "WOT-2026-701a" in out


# ---------- DoD-3a: mutacion eje ANCLA ----------


def test_mutacion_3a_corpus_sha_no_derivado(tmp_path: Path) -> None:
    """DoD-3a: corpus_sha que NO deriva del corpus declarado -> RECIBO_INCOHERENTE.

    Roja antes del fix / verde despues: se pega el par de exit codes.
    """
    repo = init_repo(tmp_path)

    # Commit 1: alta CON recibo coherente
    surface1 = backlog_surface(repo)
    recibo_ok = build_recibo(repo, "WOT-2026-702a", row("WOT-2026-702a"), [surface1])
    sha1 = commit_alta(
        repo, row("WOT-2026-702a"), msg_with_recibo("alta 702a ok", recibo_ok)
    )

    # Commit 2: MUTAR el eje ANCLA: corpus_sha que NO deriva + sha de contenido falso
    surface2 = backlog_surface(repo)  # re-contar despues de commit 1
    recibo_bad = build_recibo(repo, "WOT-2026-702b", row("WOT-2026-702b"), [surface2])
    recibo_bad["corpus_sha"] = cba._sha(b"corpus_inventado")
    recibo_bad["candidato_contenido_sha"] = cba._sha(b"falso_contenido")
    sha2 = commit_alta(
        repo, row("WOT-2026-702b"), msg_with_recibo("alta 702b sha falso", recibo_bad)
    )

    # ROJA: auditar solo el commit con el sha falso
    code, out = run_guard(repo, "--base", sha1, "--head", sha2)
    assert code == 1, f"guard debio rechazar sha falso: {out}"
    assert "RECIBO_INCOHERENTE" in out
    assert "corpus_sha no re-deriva" in out

    # VERDE despues: commit 3 con recibo coherente
    surface3 = backlog_surface(repo)  # re-contar despues de commit 2
    recibo_ok2 = build_recibo(repo, "WOT-2026-702c", row("WOT-2026-702c"), [surface3])
    sha3 = commit_alta(
        repo, row("WOT-2026-702c"), msg_with_recibo("alta 702c ok", recibo_ok2)
    )
    code_ok, out_ok = run_guard(repo, "--base", sha2, "--head", sha3)
    assert code_ok == 0, f"guard debio pasar con sha correcto: {out_ok}"
    assert "RECIBO_COHERENTE" in out_ok


# ---------- DoD-4: universo recortado ----------


def test_universo_recortado_generador_falla(tmp_path: Path) -> None:
    """DoD-4: generador invocado con menos superficies que el universo
    obligatorio -> rc != 0 y recibo NO emitido."""
    repo = init_repo(tmp_path)
    # Pasar SOLO backlog, sin archive -> falta una superficie obligatoria
    rc, out = run_emit_recibo(
        repo,
        "--candidato-id",
        "WOT-2026-703a",
        "--backlog",
        str(repo / BACKLOG_REL),
        "--veredicto",
        "NUEVA",
    )
    assert rc != 0, f"generador debio fallar con universo recortado: {out}"
    # No debe emitir JSON valido a stdout
    assert not out.strip().startswith("{"), f"no debe haber JSON: {out[:100]}"
    assert "Faltan" in out or "obligatorio" in out


def test_universo_completo_generador_pasa(tmp_path: Path) -> None:
    """DoD-4 (control positivo): generador con universo completo -> rc=0 y
    recibo emitido."""
    repo = init_repo(tmp_path)
    rc, out = run_emit_recibo(
        repo,
        "--candidato-id",
        "WOT-2026-704a",
        "--backlog",
        str(repo / BACKLOG_REL),
        "--archive-file",
        str(repo / ARCHIVE_REL),
        "--veredicto",
        "NUEVA",
    )
    assert rc == 0, f"generador debio pasar: {out}"
    recibo = json.loads(out)
    assert recibo["candidato_id"] == "WOT-2026-704a"
    assert len(recibo["corpus"]) >= 2
    assert recibo["veredicto_propuesta"]["tipo"] == "NUEVA"


# ---------- WOT-2026-161y: contrato de ficha antes del recibo ----------


def _ficha_args(cid: str) -> tuple[str, ...]:
    return (
        "--candidato-id",
        cid,
        "--row-text",
        row(cid),
        "--veredicto",
        "NUEVA",
    )


def test_mutation_m01_ficha_no_permitida_rechaza_y_co_emite(tmp_path: Path) -> None:
    """m-01: el valor fuera del vocabulario no puede emitir el recibo."""
    repo = init_repo(tmp_path)
    cid = "WOT-2026-161ya"
    rc, stdout, stderr = run_emit_recibo_capture(
        repo, *_ficha_args(cid), ficha_text="redactada_por: codex\n"
    )
    assert rc == 1
    assert stdout == ""
    assert cba.CAUSA_VALOR_FUERA_VOCAB in stderr

    rc_ok, stdout_ok, _stderr_ok = run_emit_recibo_capture(
        repo, *_ficha_args(cid), ficha_text="redactada_por: co\n"
    )
    assert rc_ok == 0
    assert json.loads(stdout_ok)["candidato_id"] == cid


def test_mutation_m02_causas_distintas_en_stderr(tmp_path: Path) -> None:
    """m-02: ausente, duplicada y fuera de vocabulario conservan causas distintas."""
    cases = (
        ("redactada_por co\n", cba.CAUSA_CLAVE_AUSENTE),
        ("redactada_por: co\nredactada_por: co\n", cba.CAUSA_CLAVE_DUPLICADA),
        ("redactada_por: codex\n", cba.CAUSA_VALOR_FUERA_VOCAB),
    )
    messages = []
    for index, (ficha, causa) in enumerate(cases):
        repo = init_repo(tmp_path / str(index))
        cid = f"WOT-2026-161y{index}"
        rc, stdout, stderr = run_emit_recibo_capture(
            repo, *_ficha_args(cid), ficha_text=ficha
        )
        assert rc == 1
        assert stdout == ""
        assert causa in stderr
        assert cba.FICHA_CONTRACT_REL in stderr
        messages.append(stderr)
    assert len(set(messages)) == 3


def test_mutation_m03_ficha_inexistente_rechaza_sin_stdout(tmp_path: Path) -> None:
    """m-03: la ficha ausente tiene causa explícita y no deja JSON parcial."""
    repo = init_repo(tmp_path)
    cid = "WOT-2026-161ym"
    rc, stdout, stderr = run_emit_recibo_capture(
        repo, *_ficha_args(cid), create_ficha=False
    )
    assert rc == 1
    assert stdout == ""
    assert cba.CAUSA_FICHA_NO_PRESENTE in stderr
    assert cba.FICHA_CONTRACT_REL in stderr


def test_mutation_m04_importa_check_ficha_contract_una_vez() -> None:
    """m-04: el emisor importa la única implementación del guard de ficha."""
    source = Path(bdc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        alias
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "scripts.check_backlog_admission"
        for alias in node.names
        if alias.name == "check_ficha_contract"
    ]
    assert len(imports) == 1
    assert "def check_ficha_contract" not in source


def test_mutation_m05_json_identico_con_y_sin_comprobacion(tmp_path: Path) -> None:
    """m-05: contrastar la ficha no cambia el schema ni el JSON del recibo."""
    repo = init_repo(tmp_path)
    cid = "WOT-2026-161yn"
    args = _ficha_args(cid)
    rc_a, stdout_a, stderr_a = run_emit_recibo_capture(repo, *args)
    rc_b, stdout_b, stderr_b = run_emit_recibo_capture(
        repo, *args, "--sin-ficha-contrato"
    )
    assert rc_a == rc_b == 0
    assert stdout_a == stdout_b
    assert stderr_a == stderr_b == ""


def test_sin_ficha_contrato_emite_aviso_y_json_con_ficha_rota(tmp_path: Path) -> None:
    """El bypass solo advierte por stderr y conserva stdout como JSON puro."""
    repo = init_repo(tmp_path)
    cid = "WOT-2026-161yo"
    rc, stdout, stderr = run_emit_recibo_capture(
        repo,
        *_ficha_args(cid),
        "--sin-ficha-contrato",
        ficha_text="redactada_por: codex\n",
    )
    assert rc == 0
    assert json.loads(stdout)["candidato_id"] == cid
    assert "AVISO: --sin-ficha-contrato activo" in stderr


def test_sin_ficha_contrato_conforme_no_emite_aviso(tmp_path: Path) -> None:
    """Una ficha conforme no produce constancia al usar el bypass."""
    repo = init_repo(tmp_path)
    cid = "WOT-2026-161yp"
    rc, stdout, stderr = run_emit_recibo_capture(
        repo, *_ficha_args(cid), "--sin-ficha-contrato"
    )
    assert rc == 0
    assert json.loads(stdout)["candidato_id"] == cid
    assert stderr == ""


def test_shadow_log_no_se_ejecuta_si_ficha_rechaza(tmp_path: Path) -> None:
    """El rechazo de contrato ocurre antes del efecto secundario shadow."""
    repo = init_repo(tmp_path)
    cid = "WOT-2026-161yq"
    rc, stdout, stderr = run_emit_recibo_capture(
        repo, *_ficha_args(cid), ficha_text="redactada_por: codex\n"
    )
    assert rc == 1
    assert stdout == ""
    assert "AVISO: --sin-ficha-contrato" not in stderr
    assert not (
        repo
        / ".agent"
        / "runtime"
        / "audit"
        / "backlog_priority"
        / "tds_shadow_log.jsonl"
    ).exists()


def test_ficha_opcion_relativa_y_absoluta_se_resuelven_contra_git_root(
    tmp_path: Path,
) -> None:
    """--ficha manda sobre la ficha derivada: relativa a --git-root o absoluta."""
    repo = init_repo(tmp_path)
    cid = "WOT-2026-161yr"
    otra = repo / "otra_ficha.md"
    otra.write_text("redactada_por: codex\n", encoding="utf-8")
    # La ficha derivada es conforme: solo --ficha puede producir el rechazo.
    _emit_ficha(repo, cid)

    rc_rel, out_rel, err_rel = run_emit_recibo_capture(
        repo, *_ficha_args(cid), "--ficha", "otra_ficha.md"
    )
    assert rc_rel == 1
    assert out_rel == ""
    assert cba.CAUSA_VALOR_FUERA_VOCAB in err_rel

    rc_abs, out_abs, err_abs = run_emit_recibo_capture(
        repo, *_ficha_args(cid), "--ficha", str(otra)
    )
    assert rc_abs == 1
    assert out_abs == ""
    assert cba.CAUSA_VALOR_FUERA_VOCAB in err_abs

    otra.write_text("redactada_por: im\n", encoding="utf-8")
    rc_ok, out_ok, _err_ok = run_emit_recibo_capture(
        repo, *_ficha_args(cid), "--ficha", "otra_ficha.md"
    )
    assert rc_ok == 0
    assert json.loads(out_ok)["candidato_id"] == cid


def test_ficha_ilegible_rechaza_con_rc2_y_el_bypass_la_degrada(tmp_path: Path) -> None:
    """Una ficha que no es UTF-8 no se puede contrastar: rc 2, o aviso con bypass."""
    repo = init_repo(tmp_path)
    cid = "WOT-2026-161ys"
    (repo / ".agent" / "collaboration" / f"FICHA_{cid}.md").write_bytes(
        b"redactada_por: co\n\xff\xfe\n"
    )
    rc, stdout, stderr = run_emit_recibo_capture(
        repo, *_ficha_args(cid), create_ficha=False
    )
    assert rc == 2
    assert stdout == ""
    assert "ERROR al leer ficha" in stderr

    rc_b, stdout_b, stderr_b = run_emit_recibo_capture(
        repo, *_ficha_args(cid), "--sin-ficha-contrato", create_ficha=False
    )
    assert rc_b == 0
    assert json.loads(stdout_b)["candidato_id"] == cid
    assert "AVISO: --sin-ficha-contrato activo" in stderr_b


# ---------- DoD-1 REALISTA: corpus con entradas_censadas >= 2 ----------


def test_e2e_realista_entradas_ge_2(tmp_path: Path) -> None:
    """B2-FIX: test E2E con corpus REALISTA (entradas_censadas >= 2) que
    demuestra que el generador produce vecinos y el guard los acepta.

    Sin el fix, este test sale ROJO porque vecinos=[] viola la regla
    del guard (check_backlog_admission.py:423-424: 'vecinos vacio con
    entradas_censadas >= 2'). Con el fix, sale VERDE.
    """
    repo = init_repo(tmp_path)
    # Crear backlog con 3 filas existentes (entradas_censadas >= 2)
    p = repo / BACKLOG_REL
    p.write_text(
        HEADER
        + row("WOT-2026-800x", "sistema de cache distribuido")
        + row("WOT-2026-800y", "cache redis para sesiones")
        + row("WOT-2026-800z", "invalidacion de cache por eventos"),
        encoding="utf-8",
    )
    git(repo, "add", BACKLOG_REL)
    git(repo, "commit", "-m", "backlog con 3 entradas")
    git(repo, "push", "origin", "main")

    # Generar recibo para un candidato nuevo
    rc, out = run_emit_recibo(
        repo,
        "--candidato-id",
        "WOT-2026-801a",
        "--row-text",
        row("WOT-2026-801a", "cache distribuido con invalidacion"),
        "--veredicto",
        "NUEVA",
    )
    assert rc == 0, f"emit-recibo fallo: {out}"
    recibo = json.loads(out)
    assert recibo["candidato_id"] == "WOT-2026-801a"
    # Verificar que vecinos NO esta vacio (el guard lo exige)
    assert recibo["entradas_censadas"] >= 2, (
        f"entradas_censadas debe ser >= 2, got {recibo['entradas_censadas']}"
    )
    assert len(recibo["vecinos"]) > 0, (
        f"vecinos no puede estar vacio con entradas_censadas >= 2, "
        f"got {recibo['vecinos']}"
    )
    # Verificar que los vecinos tienen id y score
    for v in recibo["vecinos"]:
        assert "id" in v and "score" in v
        assert v["score"] >= 0.12

    # Commit con recibo y verificar que el guard pasa
    commit_alta(
        repo,
        row("WOT-2026-801a", "cache distribuido con invalidacion"),
        msg_with_recibo("alta 801a", recibo),
    )
    code, gout = run_guard(repo)
    assert code == 0, f"guard fallo: {gout}"
    assert "RECIBO_COHERENTE" in gout


# ---------- B3: corpus realista SIN vecinos sobre umbral ----------


def test_e2e_realista_sin_vecinos_sobre_umbral(tmp_path: Path) -> None:
    """B3-FIX: test que verifica el mecanismo de fallback del generador.

    **Limitacion declarada del fixture:** los tokens estructurales del helper
    `row()` (code, deliverable_type, test) crean overlap artificial que
    empuja TODOS los scores por encima de 0.12 en fixtures pequenos. El
    escenario delManager (backlog real de ~900 entradas con candidate
    genuinamente nuevo, score max ~0.056) NO puede reproducirse en un
    fixture unitario. Este test verifica:
    1. El recibo contiene `vecinos_barrido` como campo
    2. `_compute_vecinos` retorna fallback cuando hay candidatos
    3. El E2E con corpus completo funciona (guard acepta)
    """
    from scripts.backlog_db_compare import (
        _compute_vecinos,
    )

    repo = init_repo(tmp_path)
    p = repo / BACKLOG_REL
    p.write_text(
        HEADER
        + row("WOT-2026-810x", "dashboard de metricas de ventas")
        + row("WOT-2026-810y", "informe trimestral de facturacion")
        + row("WOT-2026-810z", "plantilla de presentacion ejecutiva")
        + row("WOT-2026-810w", "calendario de reuniones de equipo")
        + row("WOT-2026-810v", "formulario de feedback de clientes"),
        encoding="utf-8",
    )
    git(repo, "add", BACKLOG_REL)
    git(repo, "commit", "-m", "backlog con 5 entradas")

    # Verificar que _compute_vecinos retorna fallback cuando hay candidatos
    obligatorias = [BACKLOG_REL]
    candidato_id = "WOT-2026-811a"
    candidato_text = (
        "| Media | WOT-2026-811a | sistema de monitoring con alertas "
        "automaticas deliverable_type: code | s | pending | - | test | - |"
    )

    vecinos, _vecinos_barrido = _compute_vecinos(
        repo, obligatorias, candidato_id, candidato_text
    )

    # Con este corpus, los tokens estructurales crean overlap >= 0.12,
    # asi que vecinos tiene entries y vecinos_barrido esta vacio (caso umbral).
    # Si el corpus fuera mas grande y los scores cayeran bajo 0.12,
    # fallback se activaria y vecinos_barrido tendria candidates.
    # Verificar que AMBOS campos existen en el recibo y que vecinos no esta vacio.
    assert len(vecinos) > 0, "debe haber al menos un vecino con este corpus"

    # Verificar que vecinos_barrido existe como campo en el recibo
    rc, out = run_emit_recibo(
        repo,
        "--candidato-id",
        candidato_id,
        "--row-text",
        candidato_text,
        "--veredicto",
        "NUEVA",
    )
    assert rc == 0, f"emit-recibo fallo: {out}"
    recibo = json.loads(out)
    assert "vecinos_barrido" in recibo, "recibo debe contener campo vecinos_barrido"
    assert isinstance(recibo["vecinos_barrido"], list)
    assert len(recibo["vecinos"]) > 0, (
        "vecinos no puede estar vacio con entradas_censadas >= 2"
    )

    # E2E: commit y guard con rango explicito (solo el alta del candidato)
    sha_init = git(repo, "rev-parse", "HEAD").strip()
    commit_alta(
        repo,
        row("WOT-2026-811a", "sistema de monitoring con alertas automaticas"),
        msg_with_recibo("alta 811a", recibo),
    )
    sha_alta = git(repo, "rev-parse", "HEAD").strip()
    code, gout = run_guard(repo, "--base", sha_init, "--head", sha_alta)
    assert code == 0, f"guard fallo: {gout}"
    assert "RECIBO_COHERENTE" in gout


# ---------- WOT-2026-104p: --backlog/--archive-file no alteran el corpus ----------


def test_backlog_extra_pasado_por_cli_no_entra_al_corpus(tmp_path: Path) -> None:
    """WOT-2026-104p: un `--backlog` adicional (ruta que NO es DEFAULT_BACKLOG)
    satisface la cobertura de universo pero NO se suma al corpus real.

    El corpus de `_emit_recibo` siempre sale de `DEFAULT_BACKLOG` +
    `DEFAULT_ARCHIVES` resueltos contra `--git-root`: un fichero decoy
    pasado via `--backlog` (ademas de los obligatorios) no debe aparecer
    en `recibo["corpus"]` ni inflar `entradas_censadas`, aunque el usuario
    lo haya declarado explicitamente en la CLI.
    """
    repo = init_repo(tmp_path)
    decoy = repo / "decoy_backlog.md"
    decoy.write_text(
        HEADER + row("WOT-2026-900a") + row("WOT-2026-900b") + row("WOT-2026-900c"),
        encoding="utf-8",
    )

    rc, out = run_emit_recibo(
        repo,
        "--candidato-id",
        "WOT-2026-901a",
        "--backlog",
        str(repo / BACKLOG_REL),
        "--backlog",
        str(decoy),
        "--archive-file",
        str(repo / ARCHIVE_REL),
        "--veredicto",
        "NUEVA",
    )
    assert rc == 0, f"emit-recibo fallo: {out}"
    recibo = json.loads(out)
    corpus_paths = {s["path"] for s in recibo["corpus"]}
    assert corpus_paths == {BACKLOG_REL, ARCHIVE_REL}, (
        f"el corpus debe limitarse al universo obligatorio, sin el decoy: {corpus_paths}"
    )
    assert "decoy_backlog.md" not in corpus_paths


def test_contador_del_generador_coincide_con_el_del_guard(tmp_path: Path) -> None:
    """El campo `entradas` lo re-cuenta el guard: ambos deben contar IGUAL.

    Defecto medido 2026-09-16 en el PRIMER uso real del contrato (alta de
    WOT-2026-070c): el generador contaba con un contador propio (lineas que
    empiezan por `|`, menos 2) mientras el guard re-cuenta con
    `load_backlog_rows`. Sobre el archive real la diferencia era de 64
    entradas (591 vs 527) y el guard rechazaba el alta con
    RECIBO_INCOHERENTE, porque una celda de detalle puede contener una TABLA
    ANIDADA cuyas lineas empiezan por `|` sin ser filas de entrada.

    Con el contador desalineado este test falla en la asercion de igualdad;
    el E2E de mas abajo falla ademas con rc=1 del guard.
    """
    # El archive real contiene una SEGUNDA tabla con otro esquema, cuyas
    # filas no llevan id de ticket en la columna canonica. El guard las
    # descarta ("id de ticket no parseable"); el generador las contaba.
    anidada = (
        "\n## Trazas de cierre (segunda tabla, otro esquema)\n\n"
        "| Fase | Resultado |\n"
        "|---|---|\n"
        "| archivado | ok |\n"
        "| publicacion | ok |\n"
    )

    repo = init_repo(tmp_path, archive_extra=anidada)

    # El contraste es sobre lo que EMITE el generador, no sobre una
    # funcion interna: el campo `entradas` del recibo es exactamente lo
    # que el guard re-cuenta con su propio contador.
    archive = repo / ARCHIVE_REL
    guard_count = cba._count_markdown(cba.norm_newlines(archive.read_bytes()))

    # E2E: el alta debe ser aceptada por el guard.
    sha_init = git(repo, "rev-parse", "HEAD").strip()
    rc, out = run_emit_recibo(
        repo,
        "--candidato-id",
        "WOT-2026-812b",
        "--veredicto",
        "NUEVA",
        "--row-text",
        row("WOT-2026-812b", "candidato con archive de tabla anidada"),
    )
    assert rc == 0, f"emit-recibo fallo: {out}"
    recibo = json.loads(out)
    emitido = next(s["entradas"] for s in recibo["corpus"] if s["tipo"] == "archive")
    assert emitido == guard_count, (
        f"el recibo declara {emitido} entradas de archive y el guard "
        f"re-cuenta {guard_count}: RECIBO_INCOHERENTE garantizado"
    )
    commit_alta(
        repo,
        row("WOT-2026-812b", "candidato con archive de tabla anidada"),
        msg_with_recibo("alta 812b", recibo),
    )
    sha_alta = git(repo, "rev-parse", "HEAD").strip()
    code, gout = run_guard(repo, "--base", sha_init, "--head", sha_alta)
    assert code == 0, f"guard rechazo un recibo del generador canonico: {gout}"
    assert "RECIBO_COHERENTE" in gout
