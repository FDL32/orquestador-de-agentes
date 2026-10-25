#!/usr/bin/env python3
"""Tests for WOT-2026-127f: expelled list and --list-expelled flag."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _rule_entries(n: int, *, prefix: str = "regla") -> list[dict]:
    """N entradas rule-like con signal distinto (>=60 chars) y dominio explicito."""
    return [
        {
            "signal": f"Always verify the {prefix} number {i} before merging; "
            "this must be re-measured with a command.",
            "domain": "testing",
            "source_ticket": f"WOT-2026-{i:03d}a",
            "topic": f"t_{prefix}_{i}",
        }
        for i in range(n)
    ]


# =============================================================================
# Test (1): generate_memory_rules_md produces IDENTICAL bytes before/after change
# =============================================================================


def test_127f_generate_memory_rules_md_bytes_unchanged() -> None:
    """BEFORE/DURING/AFTER: Verifica que generate_memory_rules_md produce los
    mismos bytes que la version ANTES del cambio (1ea8c50c).

    El cambio de _extract_rules_from_entries es ADITIVO: solo anadimos la clave
    'expelled' al dict de retorno. La funcion generate_memory_rules_md lee
    extraction['rules'] y construye el markdown del mismo modo -- la clave
    'expelled' vive solo en el dict, no en el output de markdown.

    Metodo: generamos el output contra un corpus fijo y lo comparamos contra un
    string LITERAL que contiene el output medido de la version pre-change
    (1ea8c50c) sobre el MISMO corpus.

    Mutation: si introduce un cambio no esperado en el flujo de
    generate_memory_rules_md, el assert fallara.
    """
    from scripts.memory_consolidate import generate_memory_rules_md

    corpus = [
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
            "signal": "Always check the auth gateway timeout before deploying; "
            "a silent timeout bypasses the rate limiter (AP-22).",
            "topic": "security",
            "source_ticket": "WP-2026-160",
            "timestamp": "2026-05-28T10:00:00Z",
            "source": "human_audit",
            "domain": "security-gateway",
        },
    ]

    actual = generate_memory_rules_md(corpus)

    # Expected bytes measured from 1ea8c50c (pre-change version) on the same corpus.
    # Generated with: python -c "import mod; print(repr(mod.generate_memory_rules_md(corpus)))"
    _expected = (
        "# Memory Rules (L2)\n"
        "\n"
        "Total rules: 3\n"
        "Candidates: 3\n"
        "Expelled by cap: 0\n"
        "\n"
        "Rules derived deterministically from observations.jsonl. "
        "Each rule carries an ID (R-XXX), domain, wing, source ticket, and signal text.\n"
        "\n"
        "## Wing: project\n"
        "\n"
        "### Domain: security-gates\n"
        "\n"
        "#### R-001: Security gates must fail closed (exit 2 / raise) on invalid "
        "or unknown config. S...[truncated]\n"
        "\n"
        "Security gates must fail closed (exit 2 / raise) on invalid "
        "or unknown config. Silent permissive fallback is dangerous (AP-11).\n"
        "\n"
        "*Source: WP-2026-154*\n"
        "\n"
        "\n"
        "### Domain: security-gateway\n"
        "\n"
        "#### R-002: Always check the auth gateway timeout before deploying; "
        "a silent timeout bypasse...[truncated]\n"
        "\n"
        "Always check the auth gateway timeout before deploying; "
        "a silent timeout bypasses the rate limiter (AP-22).\n"
        "\n"
        "*Source: WP-2026-160*\n"
        "\n"
        "\n"
        "### Domain: testing\n"
        "\n"
        "#### R-003: When refactoring a method return type from None to bool, "
        "always use 'is False' g...[truncated]\n"
        "\n"
        "When refactoring a method return type from None to bool, "
        "always use 'is False' guards in callers rather than truthiness (AP-05).\n"
        "\n"
        "*Source: WP-2026-137*\n"
        "\n"
    )

    assert actual == _expected, (
        f"generate_memory_rules_md produced different bytes than pre-change (1ea8c50c). "
        f"diff actual vs expected: {len(actual)} vs {len(_expected)} chars"
    )


# =============================================================================
# Test (2): corpus de 35 candidatas -> expelled tiene 5, en orden de recencia
# =============================================================================


def test_127f_35_candidates_expelled_5_in_recency_order() -> None:
    """35 candidatas distintas -> expelled tiene 5, en orden de recencia, y son
    exactamente las que no estan en rules.

    El tope MAX_L2_RULES es 30. Con 35 candidatas distintas (signals únicos,
    >=60 chars, son lecciones), se guardan 30 y se expulsan 5. Las 5 expulsadas
    son las MENOS recientes (las que entran DESPUES de llenar los 30 slots con
    las 30 mas recientes).
    """
    from scripts.memory_consolidate import (
        MAX_L2_RULES,
        _extract_rules_from_entries,
    )

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entries: list[dict] = []
    for i in range(35):
        entry = {
            "signal": f"Always verify the corpus rule number {i} before merging; "
            "this must be re-measured with a command.",
            "domain": "testing",
            "source_ticket": f"WOT-2026-{i:03d}a",
            "topic": f"t_{i}",
            "timestamp": (base + timedelta(days=i)).isoformat(),
        }
        entries.append(entry)

    # La entrada i=0 es la MAS ANTIGUA, i=34 la MAS RECIENTE.
    # Con cap=30 y orden descendente por timestamp: las entradas 0..4 (menos
    # recientes) son expulsadas; las 5..34 (30 mas recientes) se guardan.

    result = _extract_rules_from_entries(entries, max_rules=MAX_L2_RULES)

    assert result["candidates"] == 35
    assert len(result["rules"]) == 30
    assert result["truncated"] is True
    assert len(result["expelled"]) == 5

    # Verificar que las 5 expulsadas son las MENOS recientes (i=0..4).
    expelled_sources = {e["source_ticket"] for e in result["expelled"]}
    expected_expelled = {f"WOT-2026-{i:03d}a" for i in range(5)}
    assert expelled_sources == expected_expelled

    # Verificar orden de recencia: la primera expulsada es la MAS RECIENTE
    # de las expulsadas (i=4), la ultima es la MENOS reciente (i=0).
    expelled_ts = [e["timestamp"] for e in result["expelled"]]
    assert expelled_ts == sorted(expelled_ts, reverse=True), (
        "expelled debe estar en orden de recencia descendente"
    )

    # Verificar que las 5 expulsadas NO estan en rules.
    kept_signals = {r["signal"] for r in result["rules"]}
    expelled_signals = {e["signal"] for e in result["expelled"]}
    assert kept_signals.isdisjoint(expelled_signals)


# =============================================================================
# Test (3): equivalencia entre --list-expelled y --apply en copia
# =============================================================================


def test_127f_list_expelled_equiv_with_apply(  # noqa: C901
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """--list-expelled --json == --apply: igualdad de conjuntos, anti-vacuidad, recent no vacio.

    Before: corpus de 40 entradas en ``tmp_path`` (i=0..28 con timestamps
        1-29d (recientes), i=29..34 con 30-35d (antiguas), i=35..39 con
        40-44d (antiguas)); 2 pares duplicados (i=1/2, i=10/11); archive con
        duplicados locales (i=0..4) y 5 unicos antiguos (i=100..104).
    During: ejecuta ``--list-expelled --json`` (sonda) y ``--apply`` (copia),
        verifica (a) header match (Candidates/Expelled by cap),
        (b) parsed rules == Total rules > 0 (anti-vacuidad),
        (c) written_signals == expected_signals (igualdad de conjuntos),
        (d) len(upcoming["expelled"]) > 0 (al menos una expulsada),
        (e) mtimes sin cambios tras --list-expelled.
    After: el test falla si hay divergencia entre las entradas de la sonda y
        las de ``--apply`` (p.ej. recortar ``recent`` en ``_compute_inputs``
        altera la sonda, que usa esa funcion entera, pero no ``--apply``, que
        toma ``recent`` de ``_run_pipeline``), o si ``recent`` llega vacio (la
        igualdad de conjuntos se vuelve trivialmente cierta).
    """
    import shutil

    import scripts.memory_consolidate as mc

    now = datetime.now(timezone.utc)

    # Crear 40 entradas distintas para tener >= 35 candidatas tras filtrado.
    # i=0..28: 1-29d (recientes), i=29..34: 30-35d (antiguas, i=29 en la frontera cae en archivable); i=35..39: 40-44d (antiguas).
    # Algunas duplicadas entre si (i=1 y i=2 comparten signal, i=10 y i=11).
    entries: list[dict] = []
    signals_used: list[str] = []
    for i in range(40):
        # Las duplicadas comparten signal
        if i == 1 or i == 2:
            sig = "Always verify the dedup group first signal before merging; this must be re-measured with a command."
        elif i == 10 or i == 11:
            sig = "Always verify the dedup group second signal before merging; this must be re-measured with a command."
        else:
            sig = (
                f"Always verify the unique signal number {i} before merging; "
                "this must be re-measured with a command."
            )
        signals_used.append(sig)
        # i=0..34: timestamps 1-35d (i=0..28 recientes, i=29..34 archivables: split_by_age usa ts < now-30d con un now posterior)
        # i=35..39: 40-44d, siempre antiguos
        if i < 35:
            ts = (now - timedelta(days=1 + i)).isoformat()
        else:
            ts = (now - timedelta(days=5 + i)).isoformat()
        entries.append(
            {
                "signal": sig,
                "domain": "testing",
                "source_ticket": f"WOT-2026-{i:03d}a",
                "topic": f"t_{i}",
                "timestamp": ts,
            }
        )

    # OBS: todas las entradas (recent + archivable)
    test_obs = tmp_path / "observations.jsonl"
    test_obs.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
        encoding="utf-8",
    )

    # Archive: duplicados locales + entradas UNICAS del archive (solo archivo).
    # Las unicas tienen topics f_100..f_104 que no coinciden con ningun local,
    # asi que _project_l2_input las admite y mutation (i) las perderia.
    test_archive = tmp_path / "archive"
    test_archive.mkdir()
    archive_file = test_archive / "observations.2020-01.jsonl"
    archive_entries = entries[:5]  # i=0..4 duplicadas en archive
    for i in range(100, 105):
        archive_entries.append(
            {
                "signal": f"Archive-only rule number {i} that is not in local entries; "
                "this must be re-measured with a command.",
                "domain": "testing",
                "source_ticket": f"WOT-2026-{i:03d}a",
                "topic": f"f_{i}",
                "timestamp": (now - timedelta(days=365)).isoformat(),
            }
        )
    archive_file.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in archive_entries),
        encoding="utf-8",
    )

    # memory_rules.md: cabecera publicada existente
    test_memory_rules = tmp_path / "memory_rules.md"
    test_memory_rules.write_text(
        "# Memory Rules (L2)\n\nTotal rules: 20\nCandidates: 35\nExpelled by cap: 15\n\n",
        encoding="utf-8",
    )

    # MEMORY.md
    test_memory_md = tmp_path / "MEMORY.md"
    test_memory_md.write_text("# MEMORY\n\n", encoding="utf-8")

    # Monkeypatch paths
    monkeypatch.setattr(mc, "OBS", test_obs)
    monkeypatch.setattr(mc, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(mc, "ARCHIVE_DIR", test_archive)
    monkeypatch.setattr(mc, "MEMORY_MD", test_memory_md)
    monkeypatch.setattr(mc, "MEMORY_RULES_MD", test_memory_rules)
    monkeypatch.setattr(mc, "MEMORY_PROFILE_MD", tmp_path / "memory_profile.md")
    monkeypatch.setattr(mc, "REPORT", tmp_path / "CONSOLIDATION_REPORT.md")
    monkeypatch.setattr(
        mc, "TMP_REPORT", tmp_path / "runtime" / "tmp" / "CONSOLIDATION_REPORT.md"
    )

    # (b) Capturar listing + mtimes ANTES de --list-expelled
    def _list_all(path: Path) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for p in sorted(path.rglob("*")):
            if p.is_file():
                st = p.stat()
                result[str(p)] = {"mtime": st.st_mtime, "size": st.st_size}
        return result

    before = _list_all(tmp_path)

    # Assert: recent no vacio en la entrada de la sonda (_compute_inputs).
    recent, _, _ = mc._compute_inputs(test_obs, 30)
    assert len(recent) > 0, (
        "El carril 'recent' esta vacio; el test asume al menos una entrada "
        "reciente en el fixture para que la igualdad de conjuntos no sea trivial."
    )

    # Ejecutar --list-expelled --json
    import sys

    monkeypatch.setattr(
        sys, "argv", ["memory_consolidate.py", "--list-expelled", "--json"]
    )
    mc.main()

    captured = capsys.readouterr()
    probe_result = json.loads(captured.out)

    # Verificar mtimes identicos
    after = _list_all(tmp_path)
    assert before == after, "--list-expelled modifico ficheros"

    # Verificar bloques en output
    assert "publicado" in probe_result
    assert "proxima_consolidacion" in probe_result
    upcoming = probe_result["proxima_consolidacion"]

    # Ahora copiar a segunda ruta y correr --apply (c)
    dest_path = tmp_path / "copy"
    shutil.copytree(tmp_path, dest_path)

    dest_obs = dest_path / "observations.jsonl"
    dest_archive = dest_path / "archive"
    dest_memory_md = dest_path / "MEMORY.md"
    dest_memory_rules = dest_path / "memory_rules.md"
    dest_memory_profile = dest_path / "memory_profile.md"
    dest_memory_dir = dest_path

    # Re-apuntar constantes del modulo
    monkeypatch.setattr(mc, "OBS", dest_obs)
    monkeypatch.setattr(mc, "MEMORY_DIR", dest_memory_dir)
    monkeypatch.setattr(mc, "ARCHIVE_DIR", dest_archive)
    monkeypatch.setattr(mc, "MEMORY_MD", dest_memory_md)
    monkeypatch.setattr(mc, "MEMORY_RULES_MD", dest_memory_rules)
    monkeypatch.setattr(mc, "MEMORY_PROFILE_MD", dest_memory_profile)
    monkeypatch.setattr(mc, "REPORT", dest_path / "CONSOLIDATION_REPORT.md")
    monkeypatch.setattr(
        mc, "TMP_REPORT", dest_path / "runtime" / "tmp" / "CONSOLIDATION_REPORT.md"
    )

    # Correr --apply
    monkeypatch.setattr(sys, "argv", ["memory_consolidate.py", "--apply"])
    mc.main()

    # (d) Leer memory_rules.md escrito y verificar
    rules_content = dest_memory_rules.read_text(encoding="utf-8")

    # Parsear cabecera del memory_rules.md escrito
    header_values: dict[str, int] = {}
    for line in rules_content.splitlines():
        for label in ("Total rules", "Candidates", "Expelled by cap"):
            if line.startswith(f"{label}: "):
                header_values[label] = int(line.split(": ", 1)[1])
                break

    # Candidates y Expelled by cap del rules.md == los de la sonda
    assert header_values.get("Candidates") == upcoming["candidates"], (
        f"Candidates no coincide: rules={header_values.get('Candidates')} "
        f"probe={upcoming['candidates']}"
    )
    assert header_values.get("Expelled by cap") == upcoming["expelled_by_cap"], (
        f"Expelled by cap no coincide: rules={header_values.get('Expelled by cap')} "
        f"probe={upcoming['expelled_by_cap']}"
    )

    # Anti-vacuidad: el numero de reglas parseadas del archivo == Total rules > 0.
    # Se parsea con el formato REAL que escribe generate_memory_rules_md:
    # encabezado de dominio, luego "#### R-XXX: <truncado>", luego cuerpo completo,
    # luego opcionales *Source: ...*.
    parsed_rule_signals: dict[str, str] = {}  # rule_id -> signal completo
    current_domain = ""
    waiting_for_signal: bool = False
    for line in rules_content.splitlines():
        if line.startswith("### Domain: "):
            current_domain = line[len("### Domain: ") :]
            waiting_for_signal = False
        elif line.startswith("#### R-"):
            parts = line.split(":", 2)
            if len(parts) >= 2:
                rule_id = parts[1].strip()
                parsed_rule_signals[rule_id] = ""
                waiting_for_signal = True
        elif waiting_for_signal and current_domain:
            if line == "":
                continue
            if not line.startswith("*Source:"):
                parsed_rule_signals[list(parsed_rule_signals.keys())[-1]] = line
            waiting_for_signal = False
        elif line == "":
            waiting_for_signal = False

    # Contar reglas con signal no vacia (solo las con signal real).
    rules_with_signal = {k: v for k, v in parsed_rule_signals.items() if v}
    assert len(rules_with_signal) == header_values.get("Total rules", 0), (
        f"Se parsearon {len(rules_with_signal)} reglas con signal, "
        f"se esperaba {header_values.get('Total rules', 0)}. "
        f"Anti-vacuidad fallida: parsed={len(rules_with_signal)} == Total rules."
    )

    # Total rules > 0 explicito.
    assert header_values.get("Total rules", 0) > 0, "Total rules debe ser > 0."

    # (d) Igualdad de conjuntos: las señales escritas == las que la sonda deja
    # dentro del tope por la ruta de produccion.
    # Se recalcula con las MISMAS constantes re-apuntadas y ANTES de --apply
    # (el re-punto ya se hizo al copiar la copia y re-apuntar).
    expected_extracted = mc._extract_rules_from_entries(
        mc._project_l2_input(*mc._compute_inputs(dest_obs, 30))
    )["rules"]
    expected_signals = {r["signal"] for r in expected_extracted}
    written_signals = set(rules_with_signal.values())

    assert written_signals == expected_signals, (
        f"Conjuntos no iguales. Solo en escritas: {written_signals - expected_signals}. "
        f"Solo en sonda: {expected_signals - written_signals}."
    )

    # Debe haber al menos una expulsada (el fixture tiene >35 candidatas con cap=30).
    assert len(upcoming["expelled"]) > 0, (
        "Se esperaba al menos una regla expulsada en el fixture."
    )


# =============================================================================
# Test (4): --list-expelled + --apply -> SystemExit != 0
# =============================================================================


def test_127f_list_expelled_apply_mutually_exclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """--list-expelled + --apply juntos -> SystemExit.code == 2, stderr contiene mutually exclusive."""
    import sys

    import scripts.memory_consolidate as mc

    test_obs = tmp_path / "observations.jsonl"
    test_obs.write_text("", encoding="utf-8")
    test_memory_rules = tmp_path / "memory_rules.md"
    test_memory_rules.write_text("# Memory Rules (L2)\n\n", encoding="utf-8")

    monkeypatch.setattr(mc, "OBS", test_obs)
    monkeypatch.setattr(mc, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(mc, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(mc, "MEMORY_MD", tmp_path / "MEMORY.md")
    monkeypatch.setattr(mc, "MEMORY_RULES_MD", test_memory_rules)
    monkeypatch.setattr(mc, "MEMORY_PROFILE_MD", tmp_path / "memory_profile.md")
    monkeypatch.setattr(mc, "REPORT", tmp_path / "CONSOLIDATION_REPORT.md")
    monkeypatch.setattr(
        mc, "TMP_REPORT", tmp_path / "runtime" / "tmp" / "CONSOLIDATION_REPORT.md"
    )

    monkeypatch.setattr(
        sys, "argv", ["memory_consolidate.py", "--list-expelled", "--apply"]
    )

    with pytest.raises(SystemExit) as exc:
        mc.main()

    assert exc.value.code == 2

    captured = capsys.readouterr()
    assert "mutually exclusive" in captured.err


# =============================================================================
# Test R3-3: archivable NO debe deduplicarse por stable id en _compute_inputs
# =============================================================================


def test_127f_r3_archivable_no_dedup_by_stable_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3-3: archivable en _compute_inputs vuelve a la semantica de 1ea8c50c.

    Corpos con DOS entradas de >30 dias que comparten la misma clave de
    dedup (misma signal/topic/source, timestamps distintos dentro de la
    ventana de dedupe, 24h) mas otras entradas.

    El numero de lineas anadidas al archive por --apply debe ser igual a
    ``len(_compute_inputs(OBS, 30)[1])`` (archivable sin dedup por stable id)
    y al numero que archivaba el codigo de 1ea8c50c sobre ese mismo corpus
    (expresion literal pre-change: ``split_by_age(filtered, since_days)[1]``).

    Mutation-verify: si _compute_inputs deduplica archivable por stable id,
    este test FALLA (node-id + linea final de pytest).
    """
    import sys

    import scripts.memory_consolidate as mc

    now = datetime.now(timezone.utc)
    old_ts_1 = (now - timedelta(days=40)).isoformat()
    old_ts_2 = (now - timedelta(days=39, hours=12)).isoformat()
    old_ts_3 = (now - timedelta(days=35)).isoformat()
    new_ts = now.isoformat()

    # Dos antiguas con la MISMA clave de dedup (misma signal/source/topic,
    # timestamps dentro de 24h ventana -- en este caso, 12h de diferencia).
    # La dedupe() las fusiona en UNA sola, pero archivable NO pasa por dedupe
    # y debe conservar las DOS.
    dedup_pair_1 = {
        "signal": "Always verify the dedup pair first entry before merging; "
        "this must be re-measured with a command.",
        "topic": "dedup_test",
        "source": "test",
        "domain": "testing",
        "timestamp": old_ts_1,
    }
    dedup_pair_2 = {
        "signal": "Always verify the dedup pair first entry before merging; "
        "this must be re-measured with a command.",
        "topic": "dedup_test",
        "source": "test",
        "domain": "testing",
        "timestamp": old_ts_2,
    }

    # Tercera antigua unica (fuera de la ventana de dedup, no colisiona).
    old_unique = {
        "signal": "Always verify the old unique signal before merging; "
        "this must be re-measured with a command.",
        "topic": "old_unique",
        "source": "test",
        "domain": "testing",
        "timestamp": old_ts_3,
    }

    # Entrada reciente (no archivable).
    recent_entry = {
        "signal": "Always verify the recent signal before merging; "
        "this must be re-measured with a command.",
        "topic": "recent",
        "source": "test",
        "domain": "testing",
        "timestamp": new_ts,
    }

    entries = [dedup_pair_1, dedup_pair_2, old_unique, recent_entry]

    # OBS
    test_obs = tmp_path / "observations.jsonl"
    test_obs.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
        encoding="utf-8",
    )

    test_archive = tmp_path / "archive"
    test_archive.mkdir()
    test_memory_md = tmp_path / "MEMORY.md"
    test_memory_md.write_text("# MEMORY\n\n", encoding="utf-8")

    # Re-apuntar constantes del modulo
    monkeypatch.setattr(mc, "OBS", test_obs)
    monkeypatch.setattr(mc, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(mc, "ARCHIVE_DIR", test_archive)
    monkeypatch.setattr(mc, "MEMORY_MD", test_memory_md)
    monkeypatch.setattr(mc, "MEMORY_RULES_MD", tmp_path / "memory_rules.md")
    monkeypatch.setattr(mc, "MEMORY_PROFILE_MD", tmp_path / "memory_profile.md")
    monkeypatch.setattr(mc, "REPORT", tmp_path / "CONSOLIDATION_REPORT.md")
    monkeypatch.setattr(
        mc, "TMP_REPORT", tmp_path / "runtime" / "tmp" / "CONSOLIDATION_REPORT.md"
    )

    # (a) Calcular archivable pre-change (expresion literal 1ea8c50c):
    #     split_by_age([e for e in parse_entries(obs_path) if not is_droppable_noise(e)],
    #                  since_days)[1]
    pre_entries = mc.parse_entries(test_obs)
    pre_filtered = [e for e in pre_entries if not mc.is_droppable_noise(e)]
    pre_change_archivable_count = len(mc.split_by_age(pre_filtered, 30)[1])

    # (b) Calcular archivable actual via _compute_inputs
    _, archivable, _ = mc._compute_inputs(test_obs, 30)
    actual_archivable_count = len(archivable)

    # (c) Ambas deben coincidir: archivable no deduplicada por stable id
    assert actual_archivable_count == pre_change_archivable_count, (
        f"_compute_inputs archivable tiene {actual_archivable_count} entradas, "
        f"se esperaba {pre_change_archivable_count} (expresion pre-change 1ea8c50c: "
        f"split_by_age(filtered, 30)[1] sin dedup). "
        f"Mutation: si deducas archivable por stable id, este assert FALLA."
    )

    # (d) Correr --apply y verificar que las lines anadidas al archive ==
    #     actual_archivable_count
    monkeypatch.setattr(sys, "argv", ["memory_consolidate.py", "--apply"])
    mc.main()

    # Leer el archivo de archive creado
    current_month = now.strftime("%Y-%m")
    archive_file = test_archive / f"observations.{current_month}.jsonl"
    assert archive_file.exists(), "El archivo de archive no se creo"

    archived_entries = mc.parse_entries(archive_file)
    assert len(archived_entries) == actual_archivable_count, (
        f"Se anadieron {len(archived_entries)} lineas al archive, "
        f"se esperaba {actual_archivable_count} (== len(_compute_inputs(OBS, 30)[1])). "
        f"Mutation: deduplicar archivable en _compute_inputs hace caer este assert."
    )

    # Verificacion adicional: las DOS entradas de la pareja dedup deben estar
    # en el archive (si deduplicas por stable id, una desaparece).
    archived_signals = [e.get("signal", "") for e in archived_entries]
    pair_signal = dedup_pair_1["signal"]
    # Contar cuantas veces aparece el signal de la pareja en el archive
    pair_count_in_archive = sum(1 for s in archived_signals if s == pair_signal)
    assert pair_count_in_archive == 2, (
        f"Se esperaba 2 copias de la pareja dedup en el archive (timestamps "
        f"diferentes, misma clave dedup), se encontraron {pair_count_in_archive}. "
        f"Esta es la linea final del mutation-verify: deduplicar archivable en "
        f"_compute_inputs -> ROJO aqui (pair_count_in_archive != 2)."
    )


# =============================================================================
# Test R5-4: --since invalido -> SystemExit.code == 2, sin escritura
# =============================================================================


def test_127f_r5_since_invalid_parser_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """--since abc -> SystemExit.code == 2, sin traceback, sin escritura."""
    import sys

    import scripts.memory_consolidate as mc

    test_obs = tmp_path / "observations.jsonl"
    test_obs.write_text("", encoding="utf-8")

    monkeypatch.setattr(mc, "OBS", test_obs)
    monkeypatch.setattr(mc, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(mc, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(mc, "MEMORY_MD", tmp_path / "MEMORY.md")
    monkeypatch.setattr(mc, "MEMORY_RULES_MD", tmp_path / "memory_rules.md")
    monkeypatch.setattr(mc, "MEMORY_PROFILE_MD", tmp_path / "memory_profile.md")
    monkeypatch.setattr(mc, "REPORT", tmp_path / "CONSOLIDATION_REPORT.md")
    monkeypatch.setattr(
        mc, "TMP_REPORT", tmp_path / "runtime" / "tmp" / "CONSOLIDATION_REPORT.md"
    )

    monkeypatch.setattr(sys, "argv", ["memory_consolidate.py", "--since", "abc"])

    with pytest.raises(SystemExit) as exc:
        mc.main()

    assert exc.value.code == 2

    captured = capsys.readouterr()
    assert "Invalid --since value" in captured.err

    # Sin escritura: el archivo de reporte no debe haberse creado.
    assert not mc.TMP_REPORT.exists()
    assert not mc.REPORT.exists()


# =============================================================================
# Test R5-3: total = len(projected) > candidates
# =============================================================================


def test_127f_r5_total_gt_candidates() -> None:
    """R5-3: total (len(projected)) > candidates (distinct signals passing lesson filter).

    Proyectamos entradas que incluyen una no-leccion (signal corto, <=60 chars).
    Esa entrada cuenta en projected pero NO en candidates.
    """
    from scripts.memory_consolidate import _compute_upcoming

    # Entrada proyectada que NO es candidata: signal corto (no es leccion).
    non_lesson = {
        "signal": "Short sig",  # <= 60 chars, no pasa el filtro
        "domain": "testing",
        "topic": "short_sig",
        "timestamp": "2026-01-01T00:00:00Z",
    }

    # Entrada candidata: signal largo (>=60 chars), es leccion.
    lesson = {
        "signal": "Always verify the lesson signal before merging; "
        "this must be re-measured with a command.",
        "domain": "testing",
        "topic": "lesson",
        "timestamp": "2026-01-02T00:00:00Z",
    }

    upcoming = _compute_upcoming([non_lesson, lesson], [], [])

    assert upcoming["total"] > 0, "total debe ser > 0"
    assert upcoming["candidates"] > 0, "candidates debe ser > 0"
    assert upcoming["total"] > upcoming["candidates"], (
        f"total={upcoming['total']} debe ser > candidates={upcoming['candidates']} "
        f"(la entrada no-leccion cuenta en projected pero no en candidates)."
    )
