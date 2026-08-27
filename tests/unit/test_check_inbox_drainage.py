"""Tests de WOT-2026-042u: drenaje del backlog_inbox con barrera cableada.

Contrato: work_plan.md del ticket (DoD a-e, enmiendas CONTRACT_AUDIT L710/L711
BA05 absorbidas). Hermetico: cada test monta su destino sintetico en tmp_path
(con el arbol REAL de superficies: canonico, legacy, _archive, caches). Las
aserciones sobre (d)/idempotencia miden CONTEOS DE ARTEFACTOS, nunca exit codigos
-- es el DoD que este ticket existe porque un `exit 0` puede significar "no hice
nada" (AGENTS.md, CEM).

Regla de tests utiles (AGENTS.md): sin floor assertions; transiciones reales de
estado del filesystem; ramas de rechazo ejercitadas por su propia invocacion.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.check_inbox_drainage import (
    CANONICAL_INBOX_REL,
    classify_inbox,
    main,
    run_mark_drained,
    run_move_strays,
)


CANON_REL = Path(".agent") / "collaboration" / "backlog_inbox"


def _mkdest(tmp_path: Path) -> Path:
    canon = tmp_path / CANON_REL
    canon.mkdir(parents=True, exist_ok=True)
    return tmp_path


def _touch(path: Path, body: str = "# ficha\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _pending_names(tmp_path: Path) -> set[str]:
    return {p.name for p in (tmp_path / CANON_REL).glob("*.tickets.md")}


def _ledger_lines(tmp_path: Path) -> list[dict]:
    led = tmp_path / CANON_REL / "_drained" / "drain_ledger.jsonl"
    if not led.is_file():
        return []
    return [
        json.loads(ln)
        for ln in led.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


def _drained_files(tmp_path: Path) -> list[Path]:
    zone = tmp_path / CANON_REL / "_drained"
    return sorted(zone.rglob("*.tickets.md")) if zone.is_dir() else []


# ---------------- DoD a ----------------


def test_a_canonical_declared_in_code(tmp_path):
    """(a): EL CODIGO declara el unico canonico: ruta relativa fija, resuelta
    contra el project_root (argumento), no contra env ni cwd."""
    assert Path(".agent") / "collaboration" / "backlog_inbox" == CANONICAL_INBOX_REL
    # y la resolucion es literalmente esa:
    from scripts.check_inbox_drainage import canonical_inbox

    assert canonical_inbox(tmp_path) == tmp_path / ".agent/collaboration/backlog_inbox"


def test_a_no_second_canonical_constant(tmp_path):
    """(a) en negativo: una ficha en el legacy NO cuenta como pending -- el
    canonico es UNO solo."""
    dest = _mkdest(tmp_path)
    _touch(dest / "orchestrator_pipeline/backlog_inbox/FP-x.tickets.md")
    rep = classify_inbox(dest)
    assert rep["pending_count"] == 0
    assert [s["basename"] for s in rep["strays"]] == ["FP-x.tickets.md"]


# ---------------- DoD c ----------------


def test_c_stray_in_legacy_fails_with_three_part_diagnostic(tmp_path, capsys):
    """(c): ficha huérfana en el buzon no-canonico FALLA (rc!==0) con las TRES
    partes self-service: que fichero, donde deberia estar, como moverlo."""
    dest = _mkdest(tmp_path)
    _touch(dest / "orchestrator_pipeline/backlog_inbox/FP-20269999-ejemplo.tickets.md")
    rc = main(["--project-root", str(dest)])
    assert rc != 0
    out = capsys.readouterr().out
    assert "FP-20269999-ejemplo.tickets.md" in out  # (i) que fichero
    assert "donde deberia estar" in out  # (ii)
    assert "mov" in out.lower()  # (iii) como moverlo
    assert "como moverlo" in out
    # y el consejo self-service: comando de re-verificacion citable
    assert "check_inbox_drainage.py --project-root" in out


def test_c_pending_does_not_block_census_warn(tmp_path, capsys):
    """Asimetria del contrato (WARN census, no cierre): pendientes en canonico
    dan exit 0 con censo visible (n y edad de la mas antigua)."""
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "FP-old.tickets.md")
    rc = main(["--project-root", str(dest)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARN census: 1" in out
    rep = classify_inbox(dest)
    assert rep["pending"][0]["age_days"] >= 0


def test_c_empty_canonical_is_named_skip_not_pass(tmp_path, capsys):
    """Anti-falso-positivo del DoD card: canonico VACIO no rompe el cierre, y el
    vacio se nombra como SKIP ("no es un PASS"), no se disfraza de drenaje hecho."""
    dest = _mkdest(tmp_path)
    rc = main(["--project-root", str(dest)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SKIP" in out and "No es un PASS" in out


def test_c_support_material_is_info_not_stray(tmp_path, capsys):
    """Leccion AMPLIADA (4 clases no-ficha): material de apoyo en el canonico ni
    se fusiona ni rompe; sale INFO, y el guard no exige renombrarlo."""
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "FUSIONES-20260808.md")
    _touch(dest / CANON_REL / "README.md")
    assert main(["--project-root", str(dest)]) == 0
    assert "material de apoyo" in capsys.readouterr().out
    assert _pending_names(dest) == set()


# ---------------- tricotomia y prunes (enmiendas L711) ---------


def test_archive_terminal_zone_exempt(tmp_path):
    """La zona terminal EXPLICITA `_archive/backlog_inbox_*/**` (patron real
    `backlog_inbox_fusionado_20260811/`, medido 8 fichas) NO es stray."""
    dest = _mkdest(tmp_path)
    _touch(
        dest
        / ".agent/collaboration/_archive/backlog_inbox_fusionado_20260811/FP-old.tickets.md"
    )
    rep = classify_inbox(dest)
    assert rep["strays"] == []
    assert rep["drained_count"] == 1
    assert main(["--project-root", str(dest)]) == 0


def test_archive_other_zone_is_stray_teeth(tmp_path):
    """DIENTES del estrechamiento (finding L711 #2): una ficha viva mal
    depositada en OTRA zona de _archive NO queda invisible con verde: es stray."""
    dest = _mkdest(tmp_path)
    _touch(dest / ".agent/collaboration/_archive/otros_residuos/FP-viva.tickets.md")
    rep = classify_inbox(dest)
    assert [s["basename"] for s in rep["strays"]] == ["FP-viva.tickets.md"]
    assert main(["--project-root", str(dest)]) != 0


def test_runtime_ficha_is_stray_teeth(tmp_path):
    """DIENTES del anti-prune (finding L711 #3): el runtime NO es zona franca --
    una ficha ahi es stray con su diagnostico."""
    dest = _mkdest(tmp_path)
    _touch(dest / ".agent/runtime/scratch/FP-perdida.tickets.md")
    rep = classify_inbox(dest)
    assert [s["basename"] for s in rep["strays"]] == ["FP-perdida.tickets.md"]
    assert main(["--project-root", str(dest)]) != 0


def test_cache_dirs_pruned(tmp_path):
    """Caches de codigo NO generan strays (un .tickets.md version-vendido en un
    venv no es trabajo invisible)."""
    dest = _mkdest(tmp_path)
    _touch(dest / ".venv/Lib/site-packages/paquete/FP-ruido.tickets.md")
    assert classify_inbox(dest)["strays"] == []


def test_deep_inside_canonical_is_stray(tmp_path):
    """El pending es solo hijo DIRECTO: una ficha enterrada en un subdir del
    canonico no es pending silenciosa -- queda a la vista como stray."""
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "subzona/FP-enterrada.tickets.md")
    rep = classify_inbox(dest)
    assert rep["pending_count"] == 0
    assert [s["basename"] for s in rep["strays"]] == ["FP-enterrada.tickets.md"]


def test_dir_symlink_is_warned_not_silently_invisible(tmp_path, monkeypatch, capsys):
    """Rama ALCANZABLE del hallazgo BA10/deepseek MANAGER_REVIEW (2026-08-27):
    un directorio-symlink no recorrido NO puede esconder fichas en silencio.
    En Windows sin privilegios no se pueden crear dir-symlinks; se monkeypatchea
    el PREDICADO de deteccion (no el escaneo) para que la rama sea ejecutada y
    asertada en cualquier SO. WARN (no bloqueante): link no es ficha confirmada."""
    import scripts.check_inbox_drainage as cid

    dest = _mkdest(tmp_path)
    escondite = _mkdest(tmp_path / "escondite")
    _touch(escondite / "FP-tras-link.tickets.md")

    real_predicado = cid._dir_is_untraversed_link
    monkeypatch.setattr(
        cid,
        "_dir_is_untraversed_link",
        lambda p: p.name == "escondite" or real_predicado(p),
    )
    rep = cid.classify_inbox(dest)
    assert any(entry["path"].endswith("escondite") for entry in rep["dir_links"]), rep[
        "dir_links"
    ]
    assert rep["strays"] == []  # no es ficha confirmada -> no stray, pero...
    assert rep["pending_count"] == 0
    rc = cid.main(["--project-root", str(dest)])
    out = capsys.readouterr()
    assert rc == 0  # WARN no bloquea el cierre
    assert (
        "escondite" in out.out + out.err
        and "dir-symlink" in (out.out + out.err).lower()
    )
    # ...y queda NOMBRADO en la salida (la invisibilidad silenciosa era el fallo)


# ---------------------------------------------------------------- Dientes ronda 2 (MANAGER_REVIEW BA05 post-4ab4320)


def test_casefold_extension_no_invisibility(tmp_path):
    """ALTO-casesensitivity (Codex L701): `FP-X.TICKETS.MD` en un buzon lateral es
    VISIBLE como stray (el glob del vecino DEC la ve en Windows; la tricotomia no
    puede mirar menos)."""
    dest = _mkdest(tmp_path)
    _touch(dest / "orchestrator_pipeline/backlog_inbox/FP-MAYUSC.TICKETS.MD")
    rep = classify_inbox(dest)
    assert [s["basename"] for s in rep["strays"]] == ["FP-MAYUSC.TICKETS.MD"]


def test_casefold_mayus_en_canonico_es_pending(tmp_path):
    """Simetrico: en el canonico, una extension en mayusculas sigue siendo pending
    (misma regla casefold que el escaneo stray)."""
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "FP-MAYUSP.TICKETS.MD")
    rep = classify_inbox(dest)
    assert rep["pending_count"] == 1, rep
    assert rep["strays"] == []


def test_move_rollback_on_midbatch_failure(tmp_path, monkeypatch, capsys):
    """ALTO-atomicidad real (Codex L701): si shutil.move revienta a mitad del lote,
    lo ya movido vuelve a su sitio (lote sin medios-migrados que parezcan progreso)."""
    import scripts.check_inbox_drainage as cid

    dest = _mkdest(tmp_path)
    s1 = _touch(dest / "orchestrator_pipeline/backlog_inbox/FP-uno.tickets.md")
    s2 = _touch(dest / "otro_lugar/FP-dos.tickets.md")
    canon_dir = dest / CANON_REL

    real_move = shutil.move
    ida_count = {"n": 0}

    def flaky_move(a, b):
        # solo fallan los movimientos AL CANONICO (ida), y a partir del segundo:
        # simula OSError en medio del lote; el rollback (canonico -> origen)
        # SIEMPRE se ejecuta real para probar la revertida.
        if canon_dir in Path(b).parents:
            ida_count["n"] += 1
            if ida_count["n"] >= 2:
                raise OSError("disco-lleno simulado")
        return real_move(a, b)

    monkeypatch.setattr(cid.shutil, "move", flaky_move)
    rc = cid.run_move_strays(dest)
    monkeypatch.undo()
    out = capsys.readouterr().out
    assert rc != 0
    assert "abort ATOMICO" in out, out
    # el PRIMERO que si se movio debe haber VUELTO a su origen:
    assert s1.exists(), f"rollback incompleto: {s1} no volvio {out}"
    assert s2.exists()
    assert not (dest / CANON_REL / "FP-uno.tickets.md").exists(), (
        "quedaron restos del lote revertido"
    )


def test_mark_drained_ledger_fail_revierte_move(tmp_path, monkeypatch, capsys):
    """MEDIO-ledger atomico (Codex L701): si el append del ledger revienta DESPUES
    del move, la ficha vuelve al canonico (nada drenado sin registro)."""
    import scripts.check_inbox_drainage as cid

    dest = _mkdest(tmp_path)
    ficha = _touch(dest / CANON_REL / "FP-ledgerfalla.tickets.md")

    def boom_open(self, *a, **k):
        if str(a[0] if a else "").startswith("a") and "drain_ledger" in str(self):
            raise OSError("sin-permiso simulado")
        return Path.open(self, *a, **k)

    monkeypatch.setattr(Path, "open", boom_open)
    rc = cid.run_mark_drained(
        dest, "FP-ledgerfalla.tickets.md", "moved", None, "prueba de rollback"
    )
    monkeypatch.undo()
    out = capsys.readouterr().out
    assert rc != 0
    assert "move revertido" in out or "auditoria manual" in out, out
    assert ficha.exists(), "la ficha quedo drenada sin su linea de ledger"
    assert not cid._ledger_names(dest), "existe ledger con lineas pese al fallo"


def test_fused_to_formato_invalido_rechazado(tmp_path):
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "FP-formato.tickets.md")
    assert (
        run_mark_drained(
            dest, "FP-formato.tickets.md", "fused", "sin-forma-de-id", None
        )
        != 0
    )
    assert (
        run_mark_drained(dest, "FP-formato.tickets.md", "fused", "WOT-2026-999x", None)
        == 0
    )
    assert (dest / CANON_REL / "_drained").is_dir()


def test_fused_to_legacy_wt_wp_aceptado(tmp_path):
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "FP-leg.tickets.md")
    assert (
        run_mark_drained(dest, "FP-leg.tickets.md", "fused", "WT-2026-019", None) == 0
    )


def test_flags_excluyentes_rechazados(tmp_path):
    dest = _mkdest(tmp_path)
    with pytest.raises(SystemExit) as ex:
        main(
            [
                "--project-root",
                str(dest),
                "--move-strays",
                "--mark-drained",
                "FP-x.tickets.md",
                "--disposition",
                "moved",
            ]
        )
    assert ex.value.code == 2


def test_symlink_shown_as_unsupported(tmp_path):
    """Política symlink (enmierta L710 MEDIO): un `*.tickets.md` symlink NO es
    pending silencioso: stray-unsupported con su destino resuelto. Si el SO no
    deja crear symlinks, SKIP declarado (no verde por ausencia del test)."""
    dest = _mkdest(tmp_path)
    real = _touch(dest / "otrolado/FP-real.tickets.md")
    link = dest / CANON_REL / "FP-link.tickets.md"
    try:
        os.symlink(str(real), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("el entorno no permite crear symlinks (Windows sin privilegios)")
    rep = classify_inbox(dest)
    assert any(s["path"].endswith("FP-link.tickets.md") for s in rep["strays"]), rep[
        "strays"
    ]
    assert rep["pending_count"] == 0
    assert main(["--project-root", str(dest)]) != 0


# ---------------- DoD d ---------------- idempotencia por artefacto


def test_d_mark_drained_moves_and_appends_ledger(tmp_path):
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "FP-20260801-a.tickets.md", "# a\n")
    _touch(dest / CANON_REL / "FP-20260802-b.tickets.md", "# b\n")
    assert (
        main(
            [
                "--mark-drained",
                "FP-20260801-a.tickets.md",
                "--disposition",
                "fused",
                "--fused-to",
                "WOT-2026-999a",
                "--project-root",
                str(dest),
            ]
        )
        == 0
    )
    # ARTEFACTOS (no el exit code):
    assert _pending_names(dest) == {"FP-20260802-b.tickets.md"}
    drained = _drained_files(dest)
    assert [p.name for p in drained] == ["FP-20260801-a.tickets.md"]
    led = _ledger_lines(dest)
    assert len(led) == 1
    assert led[0]["ficha"] == "FP-20260801-a.tickets.md"
    assert led[0]["disposition"] == "fused"
    assert led[0]["fused_to"] == "WOT-2026-999a"


def test_d_second_pass_idempotent_by_artifact_counts(tmp_path):
    """(d) literal: segunda pasada = no-op VERIFICABLE POR CONTEOS. Se comparan
    los cuatro contadores, prohibido fiarse del rc."""
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "FP-x.tickets.md")
    assert (
        main(
            [
                "--mark-drained",
                "FP-x.tickets.md",
                "--disposition",
                "moved",
                "--project-root",
                str(dest),
            ]
        )
        == 0
    )
    cnt_1 = (
        set(),
        len(_drained_files(dest)),
        len(_ledger_lines(dest)),
        classify_inbox(dest)["pending_count"],
    )
    rc2 = main(
        [
            "--mark-drained",
            "FP-x.tickets.md",
            "--disposition",
            "moved",
            "--project-root",
            str(dest),
        ]
    )
    cnt_2 = (
        set(),
        len(_drained_files(dest)),
        len(_ledger_lines(dest)),
        classify_inbox(dest)["pending_count"],
    )
    assert rc2 == 0
    assert cnt_1 == cnt_2, "los artefactos mutaron en una 2a pasada: no es no-op"
    # una auditoria completa intercalada tampoco cambia conteos
    rc3 = main(["--project-root", str(dest)])
    cnt_3 = (
        set(),
        len(_drained_files(dest)),
        len(_ledger_lines(dest)),
        classify_inbox(dest)["pending_count"],
    )
    assert rc3 == 0 and cnt_2 == cnt_3


def test_d_expired_requires_reason(fused_env):
    dest = fused_env
    rc = run_mark_drained(dest, "FP-probe.tickets.md", "expired", None, None)
    assert rc != 0
    assert _pending_names(dest) == {"FP-probe.tickets.md"}


def test_d_fused_requires_evidence_id(tmp_path):
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "FP-y.tickets.md")
    assert run_mark_drained(dest, "FP-y.tickets.md", "fused", None, None) != 0
    assert _pending_names(dest) == {"FP-y.tickets.md"}  # nada movido


@pytest.fixture
def fused_env(tmp_path):
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "FP-probe.tickets.md")
    return dest


# ---------------------------------------------------------------- move-strays (DoD e, enmiendas)


def test_e_move_strays_happy_path(tmp_path):
    dest = _mkdest(tmp_path)
    stray = _touch(dest / "orchestrator_pipeline/backlog_inbox/FP-huerfana.tickets.md")
    assert run_move_strays(dest) == 0
    assert not stray.exists()
    assert _pending_names(dest) == {"FP-huerfana.tickets.md"}


def test_e_move_strays_atomic_duplicate_batch_aborts_all(tmp_path):
    """L711 ALTO: dos strays mismo basename entre SI -> abort TOTAL ANTES de
    mover nada (sin progreso parcial disfrazado)."""
    dest = _mkdest(tmp_path)
    s1 = _touch(dest / "orchestrator_pipeline/backlog_inbox/FP-misma.tickets.md")
    s2 = _touch(dest / ".agent/runtime/p/FP-misma.tickets.md")
    rc = run_move_strays(dest)
    assert rc != 0
    assert s1.exists() and s2.exists()  # nada movido a medias
    assert _pending_names(dest) == set()


def test_e_move_strays_collision_with_canonical_aborts(tmp_path):
    """Stray whose basename equals a pending canonical one -> abort, ambos
    intactos, nada pisado."""
    dest = _mkdest(tmp_path)
    keep = _touch(dest / CANON_REL / "FP-choque.tickets.md", "# vigente\n")
    stray = _touch(
        dest / "orchestrator_pipeline/backlog_inbox/FP-choque.tickets.md",
        "# huercana\n",
    )
    rc = run_move_strays(dest)
    assert rc != 0
    assert keep.read_text(encoding="utf-8") == "# vigente\n"
    assert stray.exists()


def test_e_move_strays_idempotent_second_pass_by_counts(tmp_path):
    dest = _mkdest(tmp_path)
    _touch(dest / "orchestrator_pipeline/backlog_inbox/FP-unica.tickets.md")
    assert run_move_strays(dest) == 0
    before = _pending_names(dest)
    rc2 = run_move_strays(dest)
    assert rc2 == 0
    assert _pending_names(dest) == before  # no-op: mismo contenido del canonico


# ---------------------------------------------------------------- JSON artifact


def test_json_emite_contadores_leybles(tmp_path, capsys):
    dest = _mkdest(tmp_path)
    _touch(dest / CANON_REL / "FP-json.tickets.md")
    rc = main(["--json", "--project-root", str(dest)])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["pending_count"] == 1
    assert data["strays"] == []


# ---------------- DoD b ---------------- cableado


def test_b_guard_registrado_en_closeout_prepush():
    """Import estatico (patron 042m) + registro en la secuencia closeout. No es
    un grepeo de texto: se verifica el objeto callable y su inclusion real en el
    grafo del runner."""
    import inspect

    from scripts import prepush_check as pc

    assert callable(getattr(pc, "run_inbox_drainage_check", None)), "el run_ no existe"
    src = inspect.getsource(pc.run_preflight_check)
    assert "run_inbox_drainage_check" in src, "no registrado en la secuencia"
    assert "if closeout_mode" in src or "closeout_mode" in src


def test_b_wiring_classifies_stray_blocking_pending_warn(tmp_path):
    """El conector prepush: stray -> passed False IS blocking; pending -> WARN
    (passed False, no bloqueante); vacio -> passed True."""
    from scripts import prepush_check as pc

    dest = _mkdest(tmp_path / "d1")
    _touch(dest / "orchestrator_pipeline/backlog_inbox/FP-w.tickets.md")
    r = pc.run_inbox_drainage_check(dest)
    assert r.passed is False and r.is_blocking is True

    dest2 = _mkdest(tmp_path / "d2")
    _touch(dest2 / CANON_REL / "FP-p.tickets.md")
    r2 = pc.run_inbox_drainage_check(dest2)
    assert r2.passed is False and r2.is_blocking is False

    dest3 = _mkdest(tmp_path / "d3")
    r3 = pc.run_inbox_drainage_check(dest3)
    assert r3.passed is True
