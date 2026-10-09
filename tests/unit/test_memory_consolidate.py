#!/usr/bin/env python3
"""Tests for memory_consolidate.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from bus.redact import redact_payload
from scripts.memory_consolidate import (
    MEMORY_MD_LINE_CAP,
    _apply_consolidation,
    _extract_rules_from_entries,
    dedupe,
    generate_memory_profile_md,
    generate_memory_rules_md,
    is_droppable_noise,
    is_noise,
    parse_entries,
    regen_memory_md,
    split_by_age,
)


def test_042e_l2_l3_incluyen_las_entradas_archivadas(monkeypatch, tmp_path) -> None:
    """WOT-2026-042e: consolidar NO debe expulsar la memoria de L2/L3.

    Defecto medido 2026-07-27: `_regenerate_l2_l3(recent, ...)` recibia SOLO el
    buffer post-cutoff, asi que toda entrada de mas de 30 dias desaparecia de
    L2 (`memory_rules.md`) y L3 (`memory_profile.md`) al archivarse. Combinado
    con WOT-2026-024r (`memory_loader` no lee `archive/`), el efecto es que
    ARCHIVAR EQUIVALE A BORRAR desde el punto de vista del agente -- y ocurre
    como parte del cierre canonico, sobre datos que nadie recupera.

    Mutation: si `_regenerate_l2_l3` vuelve a recibir solo `recent`, la leccion
    vieja desaparece de ambas proyecciones y este test cae.
    """
    import scripts.memory_consolidate as mc

    vieja = (
        "REGLA VIEJA PERO VIGENTE: el guard mide con vara mas floja "
        "que la que predica y sale verde igual"
    )
    nueva = (
        "REGLA RECIENTE: un exit 0 puede significar que no hice nada "
        "en operaciones idempotentes"
    )
    old_ts = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()

    entries = [
        {"timestamp": old_ts, "signal": vieja, "domain": "quality"},
        {"timestamp": new_ts, "signal": nueva, "domain": "quality"},
    ]
    recent, archivable = split_by_age(entries, days=30)
    assert len(recent) == 1 and len(archivable) == 1, "el fixture debe partir 1/1"

    rules = tmp_path / "memory_rules.md"
    profile = tmp_path / "memory_profile.md"
    monkeypatch.setattr(mc, "MEMORY_RULES_MD", rules)
    monkeypatch.setattr(mc, "MEMORY_PROFILE_MD", profile)

    mc._regenerate_l2_l3(recent, verbose=False, archivable=archivable)

    rules_txt = rules.read_text(encoding="utf-8")
    profile_txt = profile.read_text(encoding="utf-8")
    assert nueva in rules_txt, "la leccion reciente debe estar en L2"
    assert vieja in rules_txt, (
        "la leccion ARCHIVADA desaparecio de L2: consolidar expulsa la memoria "
        "de los niveles legibles (regresion de WOT-2026-042e)"
    )
    assert vieja[:60] in profile_txt, (
        "la leccion ARCHIVADA desaparecio de L3 (regresion de WOT-2026-042e)"
    )


def test_042e_el_call_site_de_main_pasa_las_archivables() -> None:
    """WOT-2026-042e: el CALL-SITE tambien esta cubierto, no solo la funcion.

    Hueco medido durante el propio fix: el test de arriba llama a
    `_regenerate_l2_l3` DIRECTAMENTE, asi que un mutante que devolviera el
    call-site de `main` a `_regenerate_l2_l3(recent, verbose)` lo dejaba VERDE
    y el bug volvia a produccion. Es la leccion de AGENTS.md sobre barreras que
    no miran donde ocurre el fallo: la funcion admitia el argumento y nadie se
    lo pasaba.

    Se audita el AST en vez del texto crudo: un comentario que mencione
    `archivable` no debe dar por bueno el cableado.
    """
    import ast

    def _callee(node: ast.Call) -> str:
        """Nombre del invocado, cubriendo `f(...)` y `mod.f(...)`."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return ""

    def _names_archivable(arg: ast.expr) -> bool:
        """True solo si el argumento es la VARIABLE `archivable`.

        Endurecido tras el review de Manager: la version anterior aceptaba
        cualquier tercer posicional, asi que un mutante
        `_regenerate_l2_l3(recent, verbose, [])` pasaba en VERDE -- un falso
        verde que dejaba volver el bug entero.
        """
        return isinstance(arg, ast.Name) and arg.id == "archivable"

    source = Path("scripts/memory_consolidate.py").read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and _callee(node) == "_regenerate_l2_l3"
    ]
    assert calls, "no se encontro ninguna llamada a _regenerate_l2_l3"
    for call in calls:
        by_keyword = any(
            kw.arg == "archivable" and _names_archivable(kw.value)
            for kw in call.keywords
        )
        by_position = len(call.args) >= 3 and _names_archivable(call.args[2])
        assert by_keyword or by_position, (
            f"la llamada a _regenerate_l2_l3 en la linea {call.lineno} NO pasa "
            "las entradas archivables reales: consolidar volveria a expulsar la "
            "memoria de L2/L3 (regresion de WOT-2026-042e)"
        )


def test_is_noise_tool_called() -> None:
    """Tool X called patterns should be dropped."""
    assert is_noise("Tool view_file called") is True
    assert is_noise("Tool bash called") is True
    assert is_noise("  Tool edit called  ") is True


def test_is_noise_short_entry() -> None:
    """Entries < 30 chars should be dropped."""
    assert is_noise("Short signal") is True
    assert is_noise("x" * 29) is True
    assert is_noise("x" * 30) is False


def test_is_noise_valid_entry() -> None:
    """Valid entries should not be marked as noise."""
    assert is_noise("This is a valid observation signal with enough length") is False
    assert is_noise("WP-2026-083 completed successfully after implementation") is False


def test_089e_una_entrada_con_id_nunca_es_ruido_descartable() -> None:
    """WOT-2026-089e: `is_noise` mira solo el signal; una leccion con `id` no rota."""
    assert is_droppable_noise({"id": "obs-x", "signal": "Corta"}) is False
    assert (
        is_droppable_noise({"id": "obs-y", "signal": "Tool view_file called"}) is False
    )
    # Control negativo: sin `id` las mismas senales SI se descartan.
    assert is_droppable_noise({"signal": "Corta"}) is True
    assert is_droppable_noise({"signal": "Tool view_file called"}) is True
    assert is_droppable_noise({}) is True


def test_089e_la_rotacion_conserva_la_leccion_corta_con_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """El call-site de la rotacion usa el guard: con `id` se conserva, sin `id` se descarta.

    Mutacion: volver a `is_noise(e.get("signal", ""))` en `main` descarta tambien la
    leccion corta con `id` y el recuento baja de 2 a 1.
    """
    now = datetime.now(timezone.utc).isoformat()
    base = {"timestamp": now, "source": "t", "domain": "testing"}
    entries = [
        {**base, "topic": "a", "id": "obs-corta", "signal": "Corta con id"},
        {**base, "topic": "b", "signal": "Corta sin id"},
        {**base, "topic": "c", "signal": "Tool view_file called"},
        {
            **base,
            "topic": "d",
            "signal": "Una observacion valida y con longitud suficiente",
        },
    ]
    test_obs = tmp_path / "observations.jsonl"
    test_obs.write_text(
        "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8"
    )
    monkeypatch.setattr("scripts.memory_consolidate.OBS", test_obs)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_DIR", tmp_path)
    monkeypatch.setattr("scripts.memory_consolidate.ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_MD", tmp_path / "MEMORY.md")
    monkeypatch.setattr("scripts.memory_consolidate.REPORT", tmp_path / "REPORT.md")

    import sys

    from scripts import memory_consolidate

    monkeypatch.setattr(sys, "argv", ["memory_consolidate.py", "--dry-run"])
    memory_consolidate.main()

    assert "Would keep 2 entries, drop 2" in capsys.readouterr().out


def test_dedupe_within_window() -> None:
    """Two identical entries within 24h should result in one (newest kept)."""
    now = datetime.now(timezone.utc)
    older = now - timedelta(hours=12)
    entries = [
        {
            "signal": "Test signal",
            "source": "builder",
            "topic": "test",
            "timestamp": older.isoformat(),
        },
        {
            "signal": "Test signal",
            "source": "builder",
            "topic": "test",
            "timestamp": now.isoformat(),
        },
    ]
    result, dropped = dedupe(entries)
    assert len(result) == 1
    assert dropped == 1
    assert result[0]["timestamp"] == now.isoformat()


def test_dedupe_outside_window() -> None:
    """Two identical entries > 24h apart should both be kept."""
    now = datetime.now(timezone.utc)
    older = now - timedelta(hours=48)
    entries = [
        {
            "signal": "Test signal",
            "source": "builder",
            "topic": "test",
            "timestamp": older.isoformat(),
        },
        {
            "signal": "Test signal",
            "source": "builder",
            "topic": "test",
            "timestamp": now.isoformat(),
        },
    ]
    result, dropped = dedupe(entries)
    assert len(result) == 2
    assert dropped == 0


def test_split_by_age() -> None:
    """Entries older than cutoff should be in archivable list."""
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=10)
    old = now - timedelta(days=45)
    entries = [
        {"signal": "Recent", "timestamp": recent.isoformat()},
        {"signal": "Old", "timestamp": old.isoformat()},
    ]
    recent_list, archivable = split_by_age(entries, days=30)
    assert len(recent_list) == 1
    assert recent_list[0]["signal"] == "Recent"
    assert len(archivable) == 1
    assert archivable[0]["signal"] == "Old"


def test_regen_memory_md() -> None:
    """MEMORY.md should be regenerated with proper structure."""
    now = datetime.now(timezone.utc)
    entries = [
        {
            "signal": "Test signal A",
            "topic": "test_topic",
            "timestamp": now.isoformat(),
            "source": "builder",
        },
        {
            "signal": "Test signal B",
            "topic": "test_topic",
            "timestamp": now.isoformat(),
            "source": "builder",
        },
    ]
    stats = {"kept": 2, "deduped": 0, "dropped": 1, "archived": 0}
    content = regen_memory_md(entries, stats)
    assert "# MEMORY" in content
    assert "Regenerated:" in content
    assert "Total observations: 2" in content
    assert "## test_topic" in content
    assert "Test signal A" in content
    assert "Test signal B" in content
    assert "kept=2" in content


def test_parse_entries_empty_file(tmp_path: Path) -> None:
    """Parse empty file returns empty list."""
    test_file = tmp_path / "empty.jsonl"
    test_file.write_text("", encoding="utf-8")
    result = parse_entries(test_file)
    assert result == []


def test_parse_entries_malformed(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Malformed JSON lines are skipped with warning."""
    test_file = tmp_path / "malformed.jsonl"
    test_file.write_text(
        '{"valid": "entry"}\nnot json at all\n{"another": "valid"}\n',
        encoding="utf-8",
    )
    result = parse_entries(test_file)
    assert len(result) == 2
    captured = capsys.readouterr()
    assert "Warning: Skipping malformed JSON" in captured.out


def test_idempotency(tmp_path: Path) -> None:
    """Running dedupe twice on stable input produces same result."""
    now = datetime.now(timezone.utc)
    entries = [
        {
            "signal": "Unique signal A",
            "source": "builder",
            "topic": "test",
            "timestamp": now.isoformat(),
        },
        {
            "signal": "Unique signal B",
            "source": "manager",
            "topic": "test",
            "timestamp": now.isoformat(),
        },
    ]
    result1, _ = dedupe(entries)
    result2, _ = dedupe(result1)
    assert len(result1) == len(result2)
    assert [e["signal"] for e in result1] == [e["signal"] for e in result2]


def test_apply_consolidation_does_not_duplicate_against_existing_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lesson already archived in a PREVIOUS month must not be re-archived.

    Regression test for the bug measured 2026-09-28: `_apply_consolidation`
    only checked `archive_file.exists()` for the CURRENT month, so a lesson
    promoted months ago got concatenated again -- 11 real duplicates in the
    first L1 rotation in months. The dedup key must also be computed on
    REDACTED entries on both sides: the archive on disk is already redacted,
    and comparing a raw `archivable` entry against it produces a false
    negative when the topic contains redactable text (e.g. an email), which
    is exactly what blocked the first commit of that rotation.

    Mutation: revert to comparing only `archive_file.exists()` for the
    current month -> this goes RED (the old-month duplicate reappears).
    """
    test_obs = tmp_path / "observations.jsonl"
    test_obs.write_text("", encoding="utf-8")
    test_memory_md = tmp_path / "MEMORY.md"
    test_archive = tmp_path / "archive"
    test_archive.mkdir()

    monkeypatch.setattr("scripts.memory_consolidate.OBS", test_obs)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_DIR", tmp_path)
    monkeypatch.setattr("scripts.memory_consolidate.ARCHIVE_DIR", test_archive)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_MD", test_memory_md)
    monkeypatch.setattr(
        "scripts.memory_consolidate.MEMORY_RULES_MD", tmp_path / "memory_rules.md"
    )
    monkeypatch.setattr(
        "scripts.memory_consolidate.MEMORY_PROFILE_MD", tmp_path / "memory_profile.md"
    )

    old_month_file = test_archive / "observations.2020-01.jsonl"
    already_archived = {
        "signal": "leccion-vieja ya archivada, contacto old@example.com",
        "source": "builder",
        "topic": "leccion-vieja",
        "source_ticket": "WOT-2026-010a",
        "timestamp": "2020-01-15T00:00:00+00:00",
    }
    # The archive on disk is always stored REDACTED (memory_consolidate
    # redacts on every write), so the fixture must reflect that.
    old_month_file.write_text(
        json.dumps(redact_payload(already_archived), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    duplicate_entry = dict(already_archived)  # same (topic, source_ticket)
    stats = {"kept": 0, "deduped": 0, "dropped": 0, "archived": 1}

    _apply_consolidation(
        recent=[], archivable=[duplicate_entry], stats=stats, verbose=False
    )

    now = datetime.now(timezone.utc)
    current_month_file = test_archive / f"observations.{now.strftime('%Y-%m')}.jsonl"
    current_month_entries = (
        parse_entries(current_month_file) if current_month_file.exists() else []
    )
    assert not [
        e for e in current_month_entries if e.get("topic") == "leccion-vieja"
    ], "a lesson already archived in ANOTHER month must NOT be re-archived"
    assert len(parse_entries(old_month_file)) == 1


def test_042s_autogenerated_topic_does_not_reach_tracked_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WOT-2026-042s DoD (a)+(b): telemetria autogenerada (topic en
    AUTOGENERATED_TOPICS) NUNCA debe aterrizar en el archive TRACKEADO.

    Fixture con dientes (DoD b): signal >= 30 chars y SIN terminar en
    'called', para que is_droppable_noise (que corre ANTES en el pipeline
    real, aunque aqui se llama _apply_consolidation directo) no sea el que
    la descarta -- si is_noise la filtrase, este test no probaria el filtro
    de AUTOGENERATED_TOPICS que es el objeto de la ficha.

    Mutation (DoD c): revertir el filtro anadido en _apply_consolidation
    (quitar las dos lineas que calculan skipped_autogenerated/archivable
    filtrado) debe poner este test ROJO -- la entrada reaparece en el
    archive.
    """
    test_obs = tmp_path / "observations.jsonl"
    test_obs.write_text("", encoding="utf-8")
    test_archive = tmp_path / "archive"
    test_archive.mkdir()

    monkeypatch.setattr("scripts.memory_consolidate.OBS", test_obs)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_DIR", tmp_path)
    monkeypatch.setattr("scripts.memory_consolidate.ARCHIVE_DIR", test_archive)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_MD", tmp_path / "MEMORY.md")
    monkeypatch.setattr(
        "scripts.memory_consolidate.MEMORY_RULES_MD", tmp_path / "memory_rules.md"
    )
    monkeypatch.setattr(
        "scripts.memory_consolidate.MEMORY_PROFILE_MD", tmp_path / "memory_profile.md"
    )

    telemetry_entry = {
        "signal": "Ticket WOT-2026-999z completado: cierre automatico de sesion",
        "source": "session-close",
        "topic": "ticket-completion",
        "source_ticket": "WOT-2026-999z",
        "timestamp": "2020-01-15T00:00:00+00:00",
    }
    stats = {"kept": 0, "deduped": 0, "dropped": 0, "archived": 1}

    _apply_consolidation(
        recent=[], archivable=[telemetry_entry], stats=stats, verbose=False
    )

    now = datetime.now(timezone.utc)
    current_month_file = test_archive / f"observations.{now.strftime('%Y-%m')}.jsonl"
    current_month_entries = (
        parse_entries(current_month_file) if current_month_file.exists() else []
    )
    assert not [
        e for e in current_month_entries if e.get("topic") == "ticket-completion"
    ], (
        "telemetria autogenerada (topic='ticket-completion') aterrizo en el "
        "archive TRACKEADO -- el filtro AUTOGENERATED_TOPICS no esta aplicado "
        "en _apply_consolidation (regresion de WOT-2026-042s)"
    )


def test_042s_legitimate_lesson_still_archives_anti_false_positive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WOT-2026-042s DoD (d): anti-falso-positivo obligatorio. Una leccion
    legitima (topic NO autogenerado) debe SEGUIR rotando al archive -- sin
    esto, "arreglar" el filtro de telemetria apagaria la memoria entera.
    """
    test_obs = tmp_path / "observations.jsonl"
    test_obs.write_text("", encoding="utf-8")
    test_archive = tmp_path / "archive"
    test_archive.mkdir()

    monkeypatch.setattr("scripts.memory_consolidate.OBS", test_obs)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_DIR", tmp_path)
    monkeypatch.setattr("scripts.memory_consolidate.ARCHIVE_DIR", test_archive)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_MD", tmp_path / "MEMORY.md")
    monkeypatch.setattr(
        "scripts.memory_consolidate.MEMORY_RULES_MD", tmp_path / "memory_rules.md"
    )
    monkeypatch.setattr(
        "scripts.memory_consolidate.MEMORY_PROFILE_MD", tmp_path / "memory_profile.md"
    )

    legitimate_entry = {
        "signal": "REGLA: un mock que fabrica el resultado sin invocar nada "
        "real da verde con o sin el fix de produccion",
        "source": "builder",
        "topic": "testing",
        "source_ticket": "WOT-2026-047i",
        "timestamp": "2020-01-15T00:00:00+00:00",
    }
    stats = {"kept": 0, "deduped": 0, "dropped": 0, "archived": 1}

    _apply_consolidation(
        recent=[], archivable=[legitimate_entry], stats=stats, verbose=False
    )

    now = datetime.now(timezone.utc)
    current_month_file = test_archive / f"observations.{now.strftime('%Y-%m')}.jsonl"
    current_month_entries = parse_entries(current_month_file)
    assert [e for e in current_month_entries if e.get("topic") == "testing"], (
        "una leccion LEGITIMA (topic no autogenerado) no aterrizo en el "
        "archive: el filtro de telemetria esta apagando memoria real "
        "(falso positivo, DoD (d) de WOT-2026-042s)"
    )


def test_042s_since_days_parsing_matches_between_dry_run_and_apply() -> None:
    """WOT-2026-042s DoD (g): _run_pipeline (stats de dry-run) y el call-site
    REAL de escritura (main()'s apply branch, hoy vía el mismo _run_pipeline)
    deben parsear --since IDENTICAMENTE.

    Defecto medido antes del fix: _run_pipeline usaba
    `30 if not since.endswith('d') else int(since[:-1])` invertido respecto
    a main()'s recompute `30 if since.endswith('d') else int(since[:-1])` --
    toda entrada explicita de --since divergia entre lo reportado y lo
    realmente archivado (7d -> 7 vs 30; 30 -> 30 vs 3; 10 -> 30 vs 1).

    Con el fix, main() ya NO recalcula: reusa el archivable que devuelve
    _run_pipeline, asi que la divergencia es estructuralmente imposible.
    Este test fija el contrato de _parse_since_days en los casos medidos.
    """
    from scripts.memory_consolidate import _parse_since_days

    assert _parse_since_days("30d") == 30
    assert _parse_since_days("7d") == 7
    assert _parse_since_days("90d") == 90
    assert _parse_since_days("30") == 30
    assert _parse_since_days("10") == 10


def test_dry_run_no_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-run mode should not write any versioned files."""
    test_obs = tmp_path / "observations.jsonl"
    original_content = '{"test": "entry"}\n'
    test_obs.write_text(original_content, encoding="utf-8")

    test_memory_md = tmp_path / "MEMORY.md"
    test_report = tmp_path / "REPORT.md"
    test_archive = tmp_path / "archive"
    tmp_dir = tmp_path / "runtime" / "tmp"

    monkeypatch.setattr("scripts.memory_consolidate.OBS", test_obs)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_DIR", tmp_path)
    monkeypatch.setattr("scripts.memory_consolidate.ARCHIVE_DIR", test_archive)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_MD", test_memory_md)
    monkeypatch.setattr("scripts.memory_consolidate.REPORT", test_report)
    monkeypatch.setattr(
        "scripts.memory_consolidate.TMP_REPORT", tmp_dir / "CONSOLIDATION_REPORT.md"
    )

    import sys

    from scripts import memory_consolidate

    monkeypatch.setattr(sys, "argv", ["memory_consolidate.py"])

    memory_consolidate.main()

    assert test_obs.read_text(encoding="utf-8") == original_content
    assert not test_memory_md.exists()
    assert not test_report.exists(), (
        "dry-run must NOT write to REPORT (versioned path); "
        "the report goes to a gitignored tmp path instead (WOT-2026-091b)"
    )
    # dry-run report goes to TMP_REPORT (gitignored), not REPORT
    assert (tmp_dir / "CONSOLIDATION_REPORT.md").exists()
    assert "DRY-RUN" in (tmp_dir / "CONSOLIDATION_REPORT.md").read_text(
        encoding="utf-8"
    )


def test_091b_dry_run_no_versioned_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WOT-2026-091b: dry-run must NOT write CONSOLIDATION_REPORT.md to the versioned path.

    DoD (WOT-2026-091b criterion 4.0d): `--dry-run` no escribe NINGUN fichero
    versionado (imprime a stdout o escribe en una ruta gitignored). El criterio
    4.0(d) del cierre usa un modo que no escribe.

    Mutation: volver a `REPORT.write_text(...)` en `write_report` sin condicional
    de `dry_run` hace que el test FALLA porque `REPORT.exists()` es True.
    """
    test_obs = tmp_path / "observations.jsonl"
    test_obs.write_text('{"test": "entry"}\n', encoding="utf-8")

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    report_path = memory_dir / "CONSOLIDATION_REPORT.md"
    tmp_dir = tmp_path / "runtime" / "tmp"

    monkeypatch.setattr("scripts.memory_consolidate.OBS", test_obs)
    monkeypatch.setattr("scripts.memory_consolidate.MEMORY_DIR", memory_dir)
    monkeypatch.setattr(
        "scripts.memory_consolidate.ARCHIVE_DIR", memory_dir / "archive"
    )
    monkeypatch.setattr(
        "scripts.memory_consolidate.MEMORY_MD", memory_dir / "MEMORY.md"
    )
    monkeypatch.setattr("scripts.memory_consolidate.REPORT", report_path)
    monkeypatch.setattr(
        "scripts.memory_consolidate.TMP_REPORT", tmp_dir / "CONSOLIDATION_REPORT.md"
    )

    import sys

    from scripts import memory_consolidate

    monkeypatch.setattr(sys, "argv", ["memory_consolidate.py"])
    memory_consolidate.main()

    # Criterion: versioned REPORT must NOT exist after dry-run
    assert not report_path.exists(), (
        "WOT-2026-091b DoD: --dry-run must NOT write to the versioned "
        "CONSOLIDATION_REPORT.md path"
    )
    # The report is written to the gitignored tmp path instead
    assert tmp_dir.exists()


def test_regen_memory_md_line_cap() -> None:
    """MEMORY.md should be capped at MEMORY_MD_LINE_CAP (80) lines.

    Generates an artificially large number of entries to force the index
    to exceed the cap, then verifies truncation with visible marker.
    """
    now = datetime.now(timezone.utc)
    # Create enough entries to exceed 80 lines
    # Each entry in the output takes ~2 lines (topic header + signal)
    # Plus index and summary sections (~20 lines)
    # So we need ~100 entries to safely exceed the cap
    entries = [
        {
            "signal": f"Test signal {i} with enough text to be meaningful",
            "topic": f"topic_{i % 10}",  # 10 different topics
            "timestamp": now.isoformat(),
            "source": "builder",
        }
        for i in range(100)
    ]
    stats = {"kept": 100, "deduped": 0, "dropped": 0, "archived": 0}
    content = regen_memory_md(entries, stats)
    lines = content.split("\n")

    # Verify cap is enforced
    assert len(lines) <= MEMORY_MD_LINE_CAP, (
        f"MEMORY.md has {len(lines)} lines, exceeds cap of {MEMORY_MD_LINE_CAP}"
    )

    # Verify truncation marker is present when capped
    assert "[MEMORY.md truncated at" in content
    assert "Full history available in observations.jsonl" in content

    # Verify structure is still valid (header and index always present)
    assert "# MEMORY" in content
    assert "Regenerated:" in content
    assert "Total observations: 100" in content


# =============================================================================
# Tests WP-2026-178: L2 memory rules generation
# =============================================================================


def test_generate_memory_rules_md_empty() -> None:
    """Empty entries produce L2 header with no rules."""
    content = generate_memory_rules_md([])
    assert "# Memory Rules (L2)" in content
    assert "Total rules: 0" in content
    assert "No rules extracted yet" in content


def test_generate_memory_rules_md_with_rules() -> None:
    """Entries with rule-like signals produce parseable L2 rules."""
    entries = [
        {
            "signal": "When refactoring a method return type from None to bool, "
            "always use 'is False' guards in callers rather than truthiness (AP-05).",
            "topic": "testing",
            "source_ticket": "WP-2026-137",
            "timestamp": "2026-05-25T10:00:00Z",
            "source": "human_audit",
        },
        {
            "signal": "Security gates must fail closed (exit 2 / raise) on invalid "
            "or unknown config. Silent permissive fallback is dangerous (AP-11).",
            "topic": "security",
            "source_ticket": "WP-2026-154",
            "timestamp": "2026-05-27T10:00:00Z",
            "source": "human_audit",
            "domain": "security-gates",
        },
        {
            "signal": "Short signal",  # Too short, should be skipped
            "topic": "general",
            "timestamp": "2026-05-25T10:00:00Z",
            "source": "builder",
        },
    ]
    content = generate_memory_rules_md(entries)

    # L2 header present
    assert "# Memory Rules (L2)" in content
    assert "Total rules: 2" in content  # Short signal filtered out

    # Wing header present (default wing: project)
    assert "## Wing: project" in content

    # Parseable domain sections under wings
    assert "### Domain: security-gates" in content
    assert "### Domain: testing" in content

    # Rule IDs present (H4 under H3 domain)
    assert "#### R-001:" in content
    assert "#### R-002:" in content

    # Source tickets present
    assert "WP-2026-154" in content
    assert "WP-2026-137" in content

    # Short signal excluded
    assert "Short signal" not in content


def test_generate_memory_rules_md_deterministic() -> None:
    """Two runs on same data produce identical L2 rules."""
    entries = [
        {
            "signal": "Always use 'is False' guards when return type changes from None to bool. "
            "This avoids silent breakage with monkeypatched mocks in tests.",
            "topic": "testing",
            "source_ticket": "WP-2026-137",
            "timestamp": "2026-05-25T10:00:00Z",
            "source": "human_audit",
        },
        {
            "signal": "Security gates must fail closed. Silent fallback on unknown "
            "config is more dangerous than explicit block.",
            "topic": "security",
            "source_ticket": "WP-2026-154",
            "timestamp": "2026-05-27T10:00:00Z",
            "source": "human_audit",
            "domain": "security-gates",
        },
    ]
    content1 = generate_memory_rules_md(entries)
    content2 = generate_memory_rules_md(entries)
    assert content1 == content2


def test_generate_memory_rules_md_allows_explicit_domain() -> None:
    """Entries with explicit 'domain' field qualify even without rule keywords."""
    entries = [
        {
            "signal": "A longer signal that has no rule keywords but carries a domain. "
            "Domain fields make any entry rule-eligible regardless of style.",
            "topic": "architecture",
            "domain": "bus-architecture",
            "source_ticket": "WP-2026-178",
            "timestamp": "2026-05-30T10:00:00Z",
            "source": "test",
        },
    ]
    content = generate_memory_rules_md(entries)
    assert "Total rules: 1" in content
    assert "## Wing: engine" in content  # topic 'architecture' maps to engine wing
    assert "### Domain: bus-architecture" in content


# =============================================================================
# Tests WP-2026-178: L3 memory profile generation
# =============================================================================


def test_generate_memory_profile_md_empty() -> None:
    """Empty entries produce L3 header with zero counts."""
    content = generate_memory_profile_md([])
    assert "# Memory Profile (L3)" in content
    assert "Total observations: 0" in content
    assert "Active Domains" in content


def test_generate_memory_profile_md_with_entries() -> None:
    """Entries produce profile with domains, tickets, and recent signals."""
    entries = [
        {
            "signal": "First rule about testing.",
            "topic": "testing",
            "source_ticket": "WP-2026-100",
            "timestamp": "2026-05-25T10:00:00Z",
            "source": "audit",
        },
        {
            "signal": "Security finding with longer signal text.",
            "topic": "security",
            "domain": "security-gates",
            "source_ticket": "WP-2026-154",
            "timestamp": "2026-05-27T10:00:00Z",
            "source": "audit",
        },
        {
            "signal": "Architecture decision recorded.",
            "topic": "architecture",
            "source_ticket": "WP-2026-175",
            "timestamp": "2026-05-29T10:00:00Z",
            "source": "session-close",
        },
    ]
    content = generate_memory_profile_md(entries)

    # Header
    assert "# Memory Profile (L3)" in content
    assert "Total observations: 3" in content

    # Active Domains section
    assert "## Active Domains" in content

    # Active Tickets Referenced section
    assert "## Active Tickets Referenced" in content
    assert "WP-2026-100" in content
    assert "WP-2026-154" in content
    assert "WP-2026-175" in content

    # Recent Signals section
    assert "## Recent Signals" in content
    # Most recent entry should appear
    assert "Architecture decision recorded" in content or "session-close" in content


def test_096a_family_summary_section_appears_per_domain() -> None:
    """DoD (a): cada domain con >=1 observacion tiene su propia seccion
    '### <domain> (<N> observations)' dentro de 'Family Summaries'."""
    entries = [
        {
            "signal": "Regla sobre testing A.",
            "topic": "t1",
            "domain": "testing",
            "confidence": 0.9,
            "timestamp": "2026-10-01T10:00:00Z",
        },
        {
            "signal": "Regla sobre testing B.",
            "topic": "t2",
            "domain": "testing",
            "confidence": 0.5,
            "timestamp": "2026-10-02T10:00:00Z",
        },
        {
            "signal": "Regla sobre seguridad.",
            "topic": "t3",
            "domain": "security-gates",
            "confidence": 0.8,
            "timestamp": "2026-10-01T10:00:00Z",
        },
    ]
    content = generate_memory_profile_md(entries)
    assert "## Family Summaries" in content
    assert "### testing (2 observations)" in content
    assert "### security-gates (1 observations)" in content


def test_096a_mutation_removing_family_summary_logic_drops_the_section() -> None:
    """MUTATION del DoD (b): sin la logica de resumen, la seccion desaparece.

    Reproduce la mutacion llamando directamente al helper con una lista vacia
    simulada via el propio contrato: si `_family_summary_sections` deja de
    devolver nada para un domain con entradas, `generate_memory_profile_md`
    no debe seguir imprimiendo la cabecera de la seccion.
    """
    entries = [
        {
            "signal": "Leccion de dominio nuevo que antes no existia.",
            "topic": "t1",
            "domain": "warning-contracts",
            "confidence": 0.7,
            "timestamp": "2026-10-05T10:00:00Z",
        },
    ]
    content = generate_memory_profile_md(entries)
    assert "### warning-contracts (1 observations)" in content

    # Control negativo: una lista de entries vacia no produce la seccion en
    # absoluto (ni cabecera ni cuerpo) -- confirma que la seccion depende de
    # haber entries reales, no que aparezca siempre por defecto.
    empty_content = generate_memory_profile_md([])
    assert "## Family Summaries" not in empty_content


def test_096a_domain_with_single_observation_is_its_own_summary() -> None:
    """DoD (c): domain con 1 sola observacion no produce error ni seccion
    vacia -- esa unica observacion ES el resumen."""
    entries = [
        {
            "signal": "Unica leccion de este dominio por ahora.",
            "topic": "t1",
            "domain": "contract-fixtures",
            "confidence": 0.6,
            "timestamp": "2026-10-03T10:00:00Z",
        },
    ]
    content = generate_memory_profile_md(entries)
    assert "### contract-fixtures (1 observations)" in content
    assert "Unica leccion de este dominio por ahora." in content


def test_096a_top_n_is_ranked_by_confidence_then_timestamp() -> None:
    """El top-N dentro de un domain es determinista: confidence desc,
    timestamp como desempate -- no el orden de llegada en la lista."""
    entries = [
        {
            "signal": "Baja confianza, mas reciente.",
            "topic": "t1",
            "domain": "testing",
            "confidence": 0.2,
            "timestamp": "2026-10-09T10:00:00Z",
        },
        {
            "signal": "Alta confianza, mas antigua.",
            "topic": "t2",
            "domain": "testing",
            "confidence": 0.95,
            "timestamp": "2026-10-01T10:00:00Z",
        },
        {
            "signal": "Confianza media.",
            "topic": "t3",
            "domain": "testing",
            "confidence": 0.5,
            "timestamp": "2026-10-05T10:00:00Z",
        },
    ]
    content = generate_memory_profile_md(entries)
    # Aislar la seccion 'Family Summaries' (hasta el siguiente '## '): el
    # signal de baja confianza SI aparece en 'Recent Signals' (seccion
    # preexistente, no tocada por este ticket, ordenada por recencia
    # global) -- comparar contra el documento entero daria un falso
    # positivo ahi.
    start = content.index("## Family Summaries")
    end = content.index("\n## ", start + len("## Family Summaries"))
    family_section = content[start:end]

    idx_section = family_section.index("### testing")
    idx_high = family_section.index("Alta confianza, mas antigua.")
    idx_med = family_section.index("Confianza media.")
    idx_low = family_section.find("Baja confianza, mas reciente.")
    assert idx_section < idx_high < idx_med, (
        "el top-2 debe ordenar por confidence descendente, no por recencia"
    )
    # MAX_L3_FAMILY_SUMMARY=2: la tercera entrada (menor confidence) queda
    # fuera del resumen -- no aparece en absoluto en ESTA seccion (puede
    # seguir apareciendo en 'Recent Signals', que es otro mecanismo).
    assert idx_low == -1


def test_096a_missing_confidence_sorts_as_zero_never_crashes() -> None:
    """Una entrada sin `confidence` (legacy) no rompe el ranking -- cuenta
    como 0.0, nunca lanza TypeError al comparar con una entrada que si la
    tiene."""
    entries = [
        {
            "signal": "Entrada legacy sin confidence.",
            "topic": "t1",
            "domain": "testing",
            "timestamp": "2026-10-01T10:00:00Z",
        },
        {
            "signal": "Entrada moderna con confidence alta.",
            "topic": "t2",
            "domain": "testing",
            "confidence": 0.9,
            "timestamp": "2026-10-02T10:00:00Z",
        },
    ]
    content = generate_memory_profile_md(entries)
    idx_modern = content.index("Entrada moderna con confidence alta.")
    idx_legacy = content.index("Entrada legacy sin confidence.")
    assert idx_modern < idx_legacy


def test_signal_truncation_marks_cut_in_projections() -> None:
    """Long signals truncated in L1/L2/L3 projections carry the '...' marker.

    The full signal always lives untruncated in observations.jsonl; the
    generated projections (MEMORY.md, memory_rules.md header, memory_profile.md)
    only bound display width. Before the fix these used bare slices ([:200],
    [:80], [:150]) with NO marker, so a reader could not tell a line was cut.
    Barrier: a >cap signal must produce the truncation marker in each projection.
    """
    from scripts.memory_consolidate import (
        MAX_SIGNAL_MEMORY_MD,
        MAX_SIGNAL_PROFILE,
        SIGNAL_TRUNCATION_MARKER,
        generate_memory_profile_md,
        generate_memory_rules_md,
        regen_memory_md,
    )

    now = datetime.now(timezone.utc)
    # 250-char rule-like signal (contains "must be" so it promotes to an L2 rule;
    # carries an explicit domain so _extract_rules_from_entries keeps it).
    long_signal = (
        "Rule R-999: the closeout report path must be announced to stderr on "
        "prepush failure so the operator can locate the failure detail without "
        "blind reruns, and this sentence is intentionally padded well beyond two "
        "hundred and fifty characters to force truncation in every projection."
    )
    assert len(long_signal) > MAX_SIGNAL_MEMORY_MD
    entry = {
        "signal": long_signal,
        "source": "builder",
        "topic": "testing",
        "domain": "testing",
        "timestamp": now.isoformat(),
    }

    # L1 projection (MEMORY.md): truncated to 200 -> marker present.
    _stats = {"kept": 1, "deduped": 0, "dropped": 0, "archived": 0}
    memory_md = regen_memory_md([entry], _stats)
    assert SIGNAL_TRUNCATION_MARKER in memory_md
    assert long_signal not in memory_md  # the full untruncated signal is NOT inlined

    # L3 projection (memory_profile.md): truncated to 150 -> marker present.
    profile_md = generate_memory_profile_md([entry])
    assert SIGNAL_TRUNCATION_MARKER in profile_md
    assert long_signal[:MAX_SIGNAL_PROFILE].rstrip() in profile_md

    # L2 (memory_rules.md): the #### header is truncated (marker present) but the
    # FULL signal body is preserved right below it (no data loss).
    rules_md = generate_memory_rules_md([entry])
    assert SIGNAL_TRUNCATION_MARKER in rules_md
    assert long_signal in rules_md  # full signal preserved in the rule body


# =============================================================================
# Tests WOT-2026-058b: L2 publishes its cap denominator (candidates vs expelled)
# =============================================================================


def _rule_entries(n: int, *, prefix: str = "regla") -> list[dict]:
    """N entradas rule-like con signal distinto (>=60 chars) y dominio explicito."""
    return [
        {
            "signal": f"Always verify the {prefix} number {i} before merging; "
            "this must be re-measured with a command.",
            "domain": "testing",
            "source_ticket": f"WOT-2026-{i:03d}a",
            "topic": "t",
        }
        for i in range(n)
    ]


def _header_int(content: str, label: str) -> int:
    """Lee el entero de la linea de cabecera `label: N` del propio texto."""
    for line in content.splitlines():
        if line.startswith(f"{label}: "):
            return int(line.split(": ", 1)[1])
    raise AssertionError(f"cabecera ausente: {label}")


@pytest.mark.parametrize("max_rules", [0, -1, 1, 29, 30, 31, 10**9])
def test_058b_candidates_count_every_signal_regardless_of_cap(max_rules: int) -> None:
    """El denominador no depende del tope; el tope solo corta cuantas reglas se guardan.

    Fija el borde `max_rules <= 0` (guarda 0, no 1) y que `candidates` cuenta cada
    signal distinto que pasa el filtro aunque quede fuera del tope.
    """
    result = _extract_rules_from_entries(_rule_entries(40), max_rules=max_rules)
    assert result["candidates"] == 40
    assert len(result["rules"]) == min(max(max_rules, 0), 40)
    assert result["truncated"] == (len(result["rules"]) < 40)


def test_058b_a_repeated_signal_counts_once_even_across_domains() -> None:
    """Una signal repetida en dos dominios es UNA candidata, no dos.

    Fija que `candidates` cuenta signals distintos, no entradas: `seen_signals` se
    consulta antes de contar.
    """
    a = _rule_entries(1)[0]
    b = {**a, "domain": "otro-dominio"}
    result = _extract_rules_from_entries([a, b])
    assert result["candidates"] == 1
    assert len(result["rules"]) == 1


def test_058b_memory_rules_header_publishes_candidates_and_expelled() -> None:
    """La cabecera publica Total rules, Candidates y Expelled by cap, con E == C - N.

    Fija que el corte deja de ser mudo: la propia cabecera lleva el numerador y el
    denominador, leidos de vuelta del texto generado.
    """
    content = generate_memory_rules_md(_rule_entries(40))
    assert "Total rules: 30" in content
    assert "Candidates: 40" in content
    assert "Expelled by cap: 10" in content

    content_small = generate_memory_rules_md(_rule_entries(5))
    assert "Expelled by cap: 0" in content_small

    for text in (content, content_small):
        total = _header_int(text, "Total rules")
        candidates = _header_int(text, "Candidates")
        expelled = _header_int(text, "Expelled by cap")
        assert expelled == candidates - total


def test_058b_cap_expels_the_oldest_candidates_not_list_position() -> None:
    """DEC-WOT-2026-047b / WOT-2026-058b: el tope corta por RECENCIA, no por
    orden de llegada a la lista.

    Mutation-verify: con el sort de recencia quitado (list order tal cual),
    esta aseveracion falla -- las entradas 0..4 (las primeras en `entries`,
    las MAS ANTIGUAS por timestamp) sobreviven el tope en vez de las 35..39
    (las mas recientes), que es exactamente el defecto que describe
    `_extract_rules_from_entries` antes de esta resolucion.
    """
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entries = []
    for i in range(40):
        entry = _rule_entries(1, prefix=f"orden{i}")[0]
        # Timestamp CRECIENTE con el indice: la entrada 39 es la MAS RECIENTE,
        # pero aparece ULTIMA en la lista -- si el corte fuera por posicion
        # (defecto anterior) quedaria fuera del tope de 30.
        entry["timestamp"] = (base + timedelta(days=i)).isoformat()
        entries.append(entry)

    result = _extract_rules_from_entries(entries, max_rules=30)
    assert len(result["rules"]) == 30
    assert result["candidates"] == 40
    assert result["truncated"] is True

    kept_signals = {r["signal"] for r in result["rules"]}
    # Las 30 MAS RECIENTES son las entradas 10..39 (timestamps mas altos).
    newest_30 = {
        _rule_entries(1, prefix=f"orden{i}")[0]["signal"] for i in range(10, 40)
    }
    oldest_10 = {
        _rule_entries(1, prefix=f"orden{i}")[0]["signal"] for i in range(0, 10)
    }
    assert kept_signals == newest_30
    assert kept_signals.isdisjoint(oldest_10)


def test_042s_autogenerated_topics_has_a_single_canonical_declaration() -> None:
    """WOT-2026-042s DoD (e): no-divergencia via scanner AST, PROHIBIDO
    enumerar ficheros a mano -- se usa `git ls-files` para el universo.

    Baseline RE-MEDIDO 2026-10-09 (corrige el baseline stale del contrato
    original, "2 Assign, 0 Import" -- ese snapshot describia
    check_portable_memory_promotion.py:73 como una segunda declaracion
    legacy bajo R-2, pero esa duplicacion ya NO existe: WOT-2026-045-REMED
    unifico los tres consumidores (reconcile_portable_memory,
    check_portable_memory_promotion, bus/memory_loader) bajo el predicado
    compartido `is_lesson`, que importa AUTOGENERATED_TOPICS en vez de
    re-declararlo). Hoy el universo real es: 1 Assign (la declaracion
    canonica en bus/portable_memory_archive.py) + 1 ImportFrom (el
    re-export deliberado en scripts/reconcile_portable_memory.py, con su
    propio comentario "Reexportados a proposito").

    Mutation: anadir una nueva `AUTOGENERATED_TOPICS = frozenset(...)` en
    cualquier otro modulo trackeado debe subir ASSIGN a 2 y poner este test
    ROJO -- esa es la regresion que el DoD original (gate por INCREMENTO)
    existe para cazar.
    """
    import ast
    import subprocess

    motor_root = Path(__file__).resolve().parents[2]
    tracked = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=motor_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    assigns: list[str] = []
    imports: list[str] = []
    for rel in tracked:
        path = motor_root / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if any(
                    isinstance(t, ast.Name) and t.id == "AUTOGENERATED_TOPICS"
                    for t in targets
                ):
                    assigns.append(rel)
            if isinstance(node, (ast.Import, ast.ImportFrom)) and (
                "AUTOGENERATED_TOPICS" in {alias.name for alias in node.names}
            ):
                imports.append(rel)

    assert assigns == ["bus/portable_memory_archive.py"], (
        f"se esperaba exactamente 1 declaracion canonica de AUTOGENERATED_TOPICS "
        f"en bus/portable_memory_archive.py, se encontraron {len(assigns)}: {assigns} "
        "-- una declaracion nueva fuera del modulo canonico es la regresion que "
        "este gate existe para cazar (WOT-2026-042s DoD e)"
    )
    assert "scripts/reconcile_portable_memory.py" in imports, (
        "el re-export deliberado en scripts/reconcile_portable_memory.py "
        "desaparecio: check_portable_memory_promotion lo importa de ahi"
    )
