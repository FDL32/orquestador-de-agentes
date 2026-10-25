"""Tests for scripts/check_memory_health.py (WOT-2026-089e, P0).

The trigger of the optimization prompt used to be prose measured by hand on whatever
root the agent had. These tests pin the mechanical measurement: explicit roots, the
compound noise criterion, the published denominator and the schema validator.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_memory_health import (
    _REGENERATED_RE,
    main,
    measure_root,
)


def _lesson(i: int) -> dict:
    return {
        "id": f"obs-{i}",
        "topic": f"topic-{i}",
        "signal": f"Una leccion valida con longitud suficiente numero {i}",
        "source": "session-2026-10-01",
    }


def _noise() -> dict:
    return {
        "topic": "tool_usage",
        "signal": "Tool view_file called",
        "source": "post_tool_hook",
    }


def _root(
    tmp_path: Path, name: str, *, noise: int = 0, lessons: int = 0, rules: int = 0
):
    mem = tmp_path / name / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    entries = [_noise() for _ in range(noise)] + [_lesson(i) for i in range(lessons)]
    (mem / "observations.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8"
    )
    if rules:
        (mem / "memory_rules.md").write_text(
            "".join(f"#### R-{i:03d}\ntexto\n\n" for i in range(rules)),
            encoding="utf-8",
        )
    return tmp_path / name


def _fired(measure: dict) -> set[str]:
    return {t["id"] for t in measure["triggers"] if t["fired"]}


def test_a_noisy_l1_fires_criterion_d_and_publishes_the_denominator(tmp_path) -> None:
    root = _root(tmp_path, "motor", noise=510, lessons=5)
    measure = measure_root(root, run_validate=False)
    assert "d" in _fired(measure)
    assert measure["l1"]["parsed"] == 515
    assert measure["l1"]["noise"] == 510
    assert measure["l1"]["with_id"] == 5


def test_a_healthy_l1_does_not_fire(tmp_path) -> None:
    root = _root(tmp_path, "destino", noise=3, lessons=5)
    assert _fired(measure_root(root, run_validate=False)) == set()


def test_criterion_d_is_compound_size_alone_or_ratio_alone_do_not_fire(
    tmp_path,
) -> None:
    big_but_clean = _root(tmp_path, "big", lessons=600)
    small_but_noisy = _root(tmp_path, "small", noise=100, lessons=1)
    assert "d" not in _fired(measure_root(big_but_clean, run_validate=False))
    assert "d" not in _fired(measure_root(small_but_noisy, run_validate=False))


def test_criterion_d_boundary_is_strictly_more_than_500_entries(tmp_path) -> None:
    at_limit = _root(tmp_path, "at", noise=500)
    over = _root(tmp_path, "over", noise=501)
    assert "d" not in _fired(measure_root(at_limit, run_validate=False))
    assert "d" in _fired(measure_root(over, run_validate=False))


def test_criterion_a_fires_at_90_percent_of_max_l2_rules(tmp_path) -> None:
    below = _root(tmp_path, "below", rules=26)
    at = _root(tmp_path, "at", rules=27)
    assert "a" not in _fired(measure_root(below, run_validate=False))
    assert "a" in _fired(measure_root(at, run_validate=False))


def test_an_entry_with_id_is_never_counted_as_noise(tmp_path) -> None:
    mem = tmp_path / "r" / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    (mem / "observations.jsonl").write_text(
        json.dumps({"id": "obs-corta", "signal": "corta"}) + "\n", encoding="utf-8"
    )
    measure = measure_root(tmp_path / "r", run_validate=False)
    assert measure["l1"]["noise"] == 0
    assert measure["l1"]["with_id"] == 1


def test_malformed_lines_are_counted_not_swallowed(tmp_path) -> None:
    root = _root(tmp_path, "r", lessons=2)
    obs = root / ".agent" / "runtime" / "memory" / "observations.jsonl"
    obs.write_text(
        obs.read_text(encoding="utf-8") + "esto no es json\n", encoding="utf-8"
    )
    measure = measure_root(root, run_validate=False)
    assert measure["l1"]["malformed"] == 1
    assert measure["l1"]["parsed"] == 2


def test_an_absent_root_is_measured_as_absent_fires_only_b_and_does_not_raise(
    tmp_path,
) -> None:
    measure = measure_root(tmp_path / "no-existe", run_validate=True)
    assert measure["l1"]["present"] is False
    assert measure["validate_rc"] is None
    # R4-2: absent non-motor root fires trigger (b) by absence of MEMORY.md.
    assert _fired(measure) == {"b"}


def test_two_roots_in_one_process_are_measured_independently(tmp_path, capsys) -> None:
    """The reason for a pure `measure_root(root)`: importing the memory module binds
    ONE root at import time. Mutation: measuring the wrong root makes both equal."""
    noisy = _root(tmp_path, "motor", noise=600, lessons=5)
    clean = _root(tmp_path, "destino", lessons=5)
    code = main(
        [
            "--motor-root",
            str(noisy),
            "--project-root",
            str(clean),
            "--json",
            "--skip-validate",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert set(out) == {"motor", "destino"}
    assert "d" in _fired(out["motor"])
    assert "d" not in _fired(out["destino"])
    assert out["motor"]["root"] != out["destino"]["root"]


def test_the_same_root_for_motor_and_destination_is_measured_once(
    tmp_path, capsys
) -> None:
    root = _root(tmp_path, "solo", lessons=1)
    main(
        [
            "--motor-root",
            str(root),
            "--project-root",
            str(root),
            "--json",
            "--skip-validate",
        ]
    )
    assert set(json.loads(capsys.readouterr().out)) == {"destino"}


def test_text_output_publishes_the_denominator(tmp_path, capsys) -> None:
    root = _root(tmp_path, "motor", noise=510, lessons=5)
    main(["--project-root", str(root), "--skip-validate"])
    out = capsys.readouterr().out
    assert "parseadas=515" in out
    assert "ruido=510" in out
    assert "(d) DISPARA" in out
    assert "memory_optimization.md" in out


def test_criterion_c_uses_the_real_validator_with_positive_and_negative_control(
    tmp_path,
) -> None:
    valid = {
        "timestamp": "2026-10-01T00:00:00Z",
        "topic": "algo-valido",
        "signal": "Una observacion valida con longitud suficiente para el contrato",
        "source": "session-2026-10-01",
        "domain": "testing",
        "applies_to": "code",
        "confidence": 0.9,
        "source_ticket": "WOT-2026-001a",
    }
    drifted = {**valid, "topic": "algo-roto", "applies_to": "documentation"}
    ok_root = tmp_path / "ok" / ".agent" / "runtime" / "memory"
    bad_root = tmp_path / "bad" / ".agent" / "runtime" / "memory"
    for mem, entry in ((ok_root, valid), (bad_root, drifted)):
        mem.mkdir(parents=True)
        (mem / "observations.jsonl").write_text(
            json.dumps(entry) + "\n", encoding="utf-8"
        )
    ok = measure_root(tmp_path / "ok", run_validate=True)
    bad = measure_root(tmp_path / "bad", run_validate=True)
    assert ok["validate_rc"] == 0
    assert "c" not in _fired(ok)
    assert bad["validate_rc"] != 0
    assert "c" in _fired(bad)


def test_the_script_thresholds_match_the_close_prompt_block_4_0() -> None:
    """The prompt governs and the script implements: a number changed in only one of
    the two is a silent divergence (the 4.0 declares them as knobs, not as measured).

    Mutation: changing any knob of the script without the prompt turns this red.
    """
    from scripts.check_memory_health import (
        L1_MIN_ENTRIES,
        L1_NOISE_RATIO,
        L2_TRIGGER_FRACTION,
        MEMORY_STALE_DAYS,
    )

    root = Path(__file__).resolve().parents[2]
    prompt = (root / "prompts" / "orchestrator_session_close_full_audit.md").read_text(
        encoding="utf-8"
    )
    block = prompt[
        prompt.index("4.0 OPTIMIZACION DEL SISTEMA DE MEMORIA") : prompt.index(
            "7. `prompts/memory_upload.md`"
        )
    ]
    # Each number must sit in ITS OWN criterion, not anywhere in the block.
    import re

    segments = re.split(r"\n\s+\(([abcd])\) ", block)
    criteria = dict(zip(segments[1::2], segments[2::2], strict=True))
    assert set(criteria) == {"a", "b", "c", "d"}, criteria.keys()
    assert f"{round(L2_TRIGGER_FRACTION * 100)}%" in criteria["a"]
    assert f"{MEMORY_STALE_DAYS} dias" in criteria["b"]
    # (c) must name the root's L1: without --file the validator checks the MOTOR.
    command_c = " ".join(criteria["c"].split())
    assert "validate_observations.py --strict --file <raiz>/" in command_c
    assert f"{L1_MIN_ENTRIES} entradas" in criteria["d"]
    assert f"{round(L1_NOISE_RATIO * 100)}%" in criteria["d"]
    assert "check_memory_health.py --motor-root <repo_motor>" in block


def test_058b_l2_header_publishes_expelled_and_fires_criterion_a(tmp_path) -> None:
    """Con el tope lleno, (a) muestra cuantas candidatas expulso el cap.

    Fija el acoplamiento que hace visible el corte: 30 reglas disparan (a) y su
    detail publica `expulsadas E de C candidatas` leido de la cabecera de L2.
    """
    root = _root(tmp_path, "r4", lessons=1)
    mem = root / ".agent" / "runtime" / "memory"
    (mem / "memory_rules.md").write_text(
        "Total rules: 30\n"
        "Candidates: 40\n"
        "Expelled by cap: 10\n"
        + "".join(f"#### R-{i:03d}\ntexto\n\n" for i in range(30)),
        encoding="utf-8",
    )
    measure = measure_root(root, run_validate=False)
    assert measure["l2"]["rules"] == 30
    assert measure["l2"]["candidates"] == 40
    assert measure["l2"]["expelled"] == 10
    detail_a = next(t["detail"] for t in measure["triggers"] if t["id"] == "a")
    assert "expulsadas 10 de 40" in detail_a
    assert "a" in _fired(measure)


def test_058b_old_l2_format_reads_as_na_and_does_not_raise(tmp_path) -> None:
    """Un L2 de formato anterior degrada a n/d sin lanzar.

    Fija que la ausencia de las dos lineas de cabecera no rompe la medicion: solo
    deja candidates y expelled en None y el detail de (a) en `candidatas n/d`.
    """
    root = _root(tmp_path, "r5", rules=30)
    measure = measure_root(root, run_validate=False)
    assert measure["l2"]["candidates"] is None
    assert measure["l2"]["expelled"] is None
    detail_a = next(t["detail"] for t in measure["triggers"] if t["id"] == "a")
    assert "n/d" in detail_a


def test_058b_a_single_header_line_degrades_field_by_field(tmp_path) -> None:
    """Con UNA sola de las dos lineas, cada campo se lee por separado.

    Fija que `Candidates` y `Expelled by cap` se leen de forma independiente: con
    solo `Candidates`, este se lee (40) y `expelled` queda None, y el detail dice n/d.
    """
    root = _root(tmp_path, "r6", lessons=1)
    mem = root / ".agent" / "runtime" / "memory"
    (mem / "memory_rules.md").write_text(
        "Total rules: 30\n"
        "Candidates: 40\n" + "".join(f"#### R-{i:03d}\ntexto\n\n" for i in range(30)),
        encoding="utf-8",
    )
    measure = measure_root(root, run_validate=False)
    assert measure["l2"]["candidates"] == 40
    assert measure["l2"]["expelled"] is None
    detail_a = next(t["detail"] for t in measure["triggers"] if t["id"] == "a")
    assert "n/d" in detail_a


# --- Avisos de capa (EXPLORATORY-aviso-memoria, 2026-10-21) ------------------------


def _layers(root: Path, *, l2: bool = False, l3: bool = False, archives: int = 0):
    """Anade L2/L3/archive a una raiz de `_root` (L1 ya creada por `_root`)."""
    mem = root / ".agent" / "runtime" / "memory"
    if l2:
        (mem / "memory_rules.md").write_text("#### R-001\ntexto\n", encoding="utf-8")
    if l3:
        (mem / "memory_profile.md").write_text("# Perfil\n", encoding="utf-8")
    if archives:
        (mem / "archive").mkdir()
        for i in range(archives):
            (mem / "archive" / f"observations.2026-0{i + 1}.jsonl").write_text(
                json.dumps(_lesson(i)) + "\n", encoding="utf-8"
            )
    return root


def test_layer_warning_fires_when_l2_l3_missing_and_l1_exists(tmp_path) -> None:
    root = _root(tmp_path, "r", lessons=2)
    measure = measure_root(root, run_validate=False)
    assert measure["layers"] == {"l1": True, "l2": False, "l3": False, "archives": 0}
    (warning,) = measure["warnings"]
    assert "L2/L3" in warning
    assert "decision manual del usuario" in warning


def test_layer_warning_never_recommends_a_command_or_the_optimization(tmp_path) -> None:
    """`--apply` regenera L2 desde L1 viva y puede perder reglas (memory_hierarchy.md).

    Las 3 lentes del bucle lo senalaron: el aviso informa, no prescribe. Se barren los
    tres textos posibles (L1 si/no, archive si/no).
    """
    cases = [
        _root(tmp_path, "con_l1", lessons=1),
        _layers(_root(tmp_path, "sin_l1_archive", lessons=0), archives=2),
        _root(tmp_path, "sin_nada", lessons=0),
    ]
    seen = set()
    for root in cases:
        if root.name != "con_l1":
            (root / ".agent" / "runtime" / "memory" / "observations.jsonl").unlink()
        (warning,) = measure_root(root, run_validate=False)["warnings"]
        seen.add(warning)
        assert "--apply" not in warning
        assert "memory_optimization" not in warning
        assert ";" not in warning  # el hook une las raices con ";"
    assert len(seen) == 3


def test_layer_warning_without_l1_reports_the_archive_count(tmp_path) -> None:
    root = _layers(_root(tmp_path, "r", lessons=0), archives=3)
    (root / ".agent" / "runtime" / "memory" / "observations.jsonl").unlink()
    (warning,) = measure_root(root, run_validate=False)["warnings"]
    assert "archive versionado (3 ficheros)" in warning


def test_layer_warning_without_l1_nor_archive_says_there_is_no_memory(tmp_path) -> None:
    root = _root(tmp_path, "r", lessons=0)
    (root / ".agent" / "runtime" / "memory" / "observations.jsonl").unlink()
    (warning,) = measure_root(root, run_validate=False)["warnings"]
    assert "no tiene memoria persistente" in warning


def test_layer_warning_is_silent_when_l2_and_l3_exist(tmp_path) -> None:
    root = _layers(_root(tmp_path, "r", lessons=2), l2=True, l3=True)
    measure = measure_root(root, run_validate=False)
    assert measure["warnings"] == []
    assert measure["layers"]["l2"] and measure["layers"]["l3"]


def test_layer_warning_names_only_the_missing_layer(tmp_path) -> None:
    only_l2 = _layers(_root(tmp_path, "a", lessons=1), l2=True)
    (warning,) = measure_root(only_l2, run_validate=False)["warnings"]
    assert "L3" in warning and "L2" not in warning
    only_l3 = _layers(_root(tmp_path, "b", lessons=1), l3=True)
    (warning,) = measure_root(only_l3, run_validate=False)["warnings"]
    assert "L2" in warning and "L3" not in warning


def test_layer_warning_never_says_no_memory_while_a_distilled_layer_exists(
    tmp_path,
) -> None:
    """Hallazgo de la lente DeepSeek: con L2 presente, sin L1 ni archive, el texto
    "no tiene memoria persistente" seria falso (L2 ES persistente)."""
    root = _layers(_root(tmp_path, "r", lessons=0), l2=True)
    (root / ".agent" / "runtime" / "memory" / "observations.jsonl").unlink()
    (warning,) = measure_root(root, run_validate=False)["warnings"]
    assert "L3 ausente" in warning
    assert "no tiene memoria persistente" not in warning


def test_layer_warning_agrees_in_number_with_the_missing_layers(tmp_path) -> None:
    one = measure_root(_layers(_root(tmp_path, "uno", lessons=1), l2=True))
    (warning,) = one["warnings"]
    assert "L3 ausente" in warning and "ausentes" not in warning
    assert "regenerarla" in warning
    both = measure_root(_root(tmp_path, "dos", lessons=1))
    (warning,) = both["warnings"]
    assert "L2/L3 ausentes" in warning and "regenerarlas" in warning


def test_archive_count_ignores_directories_that_match_the_pattern(tmp_path) -> None:
    root = _layers(_root(tmp_path, "r", lessons=0), archives=1)
    archive = root / ".agent" / "runtime" / "memory" / "archive"
    (archive / "observations.falso.jsonl").mkdir()
    assert measure_root(root, run_validate=False)["layers"]["archives"] == 1


def test_layer_warning_on_an_absent_root_does_not_raise(tmp_path) -> None:
    measure = measure_root(tmp_path / "no_existe", run_validate=False)
    assert measure["layers"] == {"l1": False, "l2": False, "l3": False, "archives": 0}
    assert len(measure["warnings"]) == 1


def test_layer_warning_is_not_a_trigger(tmp_path) -> None:
    """Un trigger disparado dice "aplica memory_optimization.md": accion equivocada."""
    measure = measure_root(_root(tmp_path, "r", lessons=2), run_validate=False)
    assert measure["warnings"]
    assert _fired(measure) == set()
    assert {t["id"] for t in measure["triggers"]} == {"a", "b", "c", "d"}


def test_text_output_prints_the_aviso_only_when_a_layer_is_missing(
    tmp_path, capsys
) -> None:
    sin = _root(tmp_path, "sin", lessons=1)
    con = _layers(_root(tmp_path, "con", lessons=1), l2=True, l3=True)
    assert main(["--project-root", str(sin), "--skip-validate"]) == 0
    assert "AVISO:" in capsys.readouterr().out
    assert main(["--project-root", str(con), "--skip-validate"]) == 0
    assert "AVISO" not in capsys.readouterr().out


# --- WOT-2026-127e: _memory_md_staleness por contenido, motor label, growth ---


def test_memory_md_absent_returns_present_false_and_stale_none(tmp_path) -> None:
    """MEMORY.md ausente: present False, stale_days None (no 0.0), trigger (b) no dispara.

    Fija que un motor code-only sin MEMORY.md no produce un verde silencioso
    de stale_days=0.0: la ausencia se marca explicitamente y (b) no dispara.
    """
    root = _root(tmp_path, "no_md", lessons=1)
    mem = root / ".agent" / "runtime" / "memory"
    # Hacer que root sea detectable como motor (con bus/memory_loader.py)
    (root / "bus").mkdir()
    (root / "bus" / "memory_loader.py").write_text("# motor", encoding="utf-8")
    # Eliminar el MEMORY.md creado por _root para simular ausencia
    (mem / "MEMORY.md").unlink()
    assert not (mem / "MEMORY.md").is_file()
    measure = measure_root(root, run_validate=False)
    assert measure["memory_md"]["present"] is False
    assert measure["memory_md"]["stale_days"] is None
    assert "b" not in _fired(measure)


def test_memory_md_staleness_content_method_with_old_regenerated(tmp_path) -> None:
    """Sello Regenerated antiguo con entradas 10 dias posteriores: stale_days ~= 10, metodo "contenido".

    Fija que el sello se lee en cualquier linea (no solo la primera) y se compara
    con el timestamp maximo de las ENTRADAS del archive, no con el mtime de los
    ficheros (que un checkout reinicia). Fixture REALISTA: MEMORY.md con exactamente
    esos bytes (CRLF), escrito con write_bytes para conservar los finales de linea.
    El sello esta en la linea 3 (despues de "# MEMORY" y una linea en blanco).
    """
    from datetime import datetime, timedelta, timezone

    root = _root(tmp_path, "content_md", lessons=1)
    mem = root / ".agent" / "runtime" / "memory"
    archive_dir = mem / "archive"
    archive_dir.mkdir()

    # Sello antiguo: 20 dias atras
    old_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    # Entrada del archive con timestamp 10 dias posterior al sello
    entry_ts = (
        (datetime.now(timezone.utc) - timedelta(days=10))
        .isoformat()
        .replace("+00:00", "Z")
    )

    # Crear archive con timestamp en la entrada (no solo mtime)
    archive_file = archive_dir / "observations.2026-10.jsonl"
    archive_file.write_bytes(
        json.dumps(
            {"id": "obs-1", "timestamp": entry_ts, "signal": "s", "source": "t"}
        ).encode("utf-8")
        + b"\r\n"
    )

    # MEMORY.md con CRLF, sello en LINEA 3 (no primera linea)
    memory_bytes = (
        f"# MEMORY\r\n\r\nRegenerated: {old_date}\r\n\r\nTotal observations: 1\r\n"
    ).encode()
    mem.joinpath("MEMORY.md").write_bytes(memory_bytes)

    measure = measure_root(root, run_validate=False)
    assert measure["memory_md"]["present"] is True
    assert measure["memory_md"]["stale_days"] is not None
    # El sello es 20 dias atras, la entrada es 10 dias atras -> desfase = 10 dias
    assert 9.0 < measure["memory_md"]["stale_days"] <= 11.0
    assert measure["memory_md"]["metodo"] == "contenido"


def test_memory_md_staleness_content_regenerated_newer_than_entries(tmp_path) -> None:
    """Sello Regenerated posterior a todas las entradas: stale_days 0.0, metodo "contenido".

    Fija que cuando el sello es MAS RECENTE que cualquier entrada del archive,
    stale_days es 0.0 (contenido fresco).
    """
    from datetime import datetime, timedelta, timezone

    root = _root(tmp_path, "content_newer", lessons=1)
    mem = root / ".agent" / "runtime" / "memory"
    archive_dir = mem / "archive"
    archive_dir.mkdir()

    # Entrada del archive: 20 dias atras
    entry_ts = (
        (datetime.now(timezone.utc) - timedelta(days=20))
        .isoformat()
        .replace("+00:00", "Z")
    )
    # Sello Regenerated: 5 dias atras (mas reciente que la entrada)
    reg_date = (
        (datetime.now(timezone.utc) - timedelta(days=5))
        .isoformat()
        .replace("+00:00", "Z")
    )

    archive_file = archive_dir / "observations.2026-10.jsonl"
    archive_file.write_bytes(
        json.dumps(
            {"id": "obs-1", "timestamp": entry_ts, "signal": "s", "source": "t"}
        ).encode("utf-8")
        + b"\r\n"
    )

    memory_bytes = (
        f"# MEMORY\r\n\r\nRegenerated: {reg_date}\r\n\r\nTotal observations: 1\r\n"
    ).encode()
    mem.joinpath("MEMORY.md").write_bytes(memory_bytes)

    measure = measure_root(root, run_validate=False)
    assert measure["memory_md"]["present"] is True
    assert measure["memory_md"]["stale_days"] == 0.0
    assert measure["memory_md"]["metodo"] == "contenido"


def test_memory_md_staleness_multiline_requires_re_multiline_flag(tmp_path) -> None:
    """Mutation-verify: sin re.MULTILINE el sello en linea 3 no se caza -> ROJO.

    Fija que _REGENERATED_RE necesita re.MULTILINE para casar el sello cuando
    no esta en la primera linea del archivo. Mutation: compilar el patron de
    produccion sin el flag hace que el regex no caze el sello en linea 3 -> el
    test de mutation cae (no pasa de forma false-verde).
    """
    import re
    from datetime import datetime, timedelta, timezone

    root = _root(tmp_path, "multiline", lessons=1)
    mem = root / ".agent" / "runtime" / "memory"
    archive_dir = mem / "archive"
    archive_dir.mkdir()

    entry_ts = (
        (datetime.now(timezone.utc) - timedelta(days=5))
        .isoformat()
        .replace("+00:00", "Z")
    )

    archive_file = archive_dir / "observations.2026-10.jsonl"
    archive_file.write_bytes(
        json.dumps(
            {"id": "obs-1", "timestamp": entry_ts, "signal": "s", "source": "t"}
        ).encode("utf-8")
        + b"\r\n"
    )

    # Sello en linea 3, NO primera linea
    reg_date = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    memory_bytes = (
        f"# MEMORY\r\n\r\nRegenerated: {reg_date}\r\n\r\nTotal observations: 0\r\n"
    ).encode()
    mem.joinpath("MEMORY.md").write_bytes(memory_bytes)

    # Con el flag MULTILINE -> casa el sello en linea 3 -> metodo "contenido"
    measure = measure_root(root, run_validate=False)
    assert measure["memory_md"]["metodo"] == "contenido"

    # Mutation-verify: derivar la copia del patron de produccion y compilar
    # sin MULTILINE para verificar que no caza el sello en linea 3.
    no_multiline_re = re.compile(_REGENERATED_RE.pattern)
    text = memory_bytes.decode("utf-8")
    assert no_multiline_re.search(text) is None, (
        "Sin MULTILINE el regex de produccion no caza el sello en linea 3 -> "
        "fixture valida la barrera"
    )


def test_memory_md_staleness_no_regenerated_says_mtime_method(tmp_path) -> None:
    """Sin sello Regenerated: fallback a mtime, metodo "mtime".

    Fija que la ausencia de sello produce stale_days medido por mtime con
    el metodo correcto ("mtime") y no por contenido.
    """
    root = _root(tmp_path, "no_sello", lessons=1)
    mem = root / ".agent" / "runtime" / "memory"
    archive_dir = mem / "archive"
    archive_dir.mkdir()

    archive_file = archive_dir / "observations.2026-10.jsonl"
    archive_file.write_text(
        json.dumps({"id": "obs-1", "signal": "signal", "source": "test"}) + "\n",
        encoding="utf-8",
    )

    # MEMORY.md sin sello Regenerated
    mem.joinpath("MEMORY.md").write_text(
        "# MEMORY\n\nTotal observations: 0\n\n", encoding="utf-8"
    )

    measure = measure_root(root, run_validate=False)
    assert measure["memory_md"]["present"] is True
    assert measure["memory_md"]["stale_days"] is not None
    assert measure["memory_md"]["metodo"] == "mtime"


def test_is_motor_detects_bus_memory_loader(tmp_path) -> None:
    """Raiz con bus/memory_loader.py es detectada como motor."""
    root = tmp_path / "motor_like"
    root.mkdir()
    (root / "bus").mkdir()
    (root / "bus" / "memory_loader.py").write_text("# placeholder", encoding="utf-8")
    (root / ".agent" / "runtime" / "memory").mkdir(parents=True)
    measure = measure_root(root, run_validate=False)
    assert measure["is_motor"] is True


def test_is_not_motor_when_no_memory_loader(tmp_path) -> None:
    """Raiz sin bus/memory_loader.py no es motor."""
    root = _root(tmp_path, "not_motor", lessons=1)
    measure = measure_root(root, run_validate=False)
    assert measure["is_motor"] is False


def test_growth_includes_archive_stats(tmp_path) -> None:
    """Growth con denominadores correctos: rows, bytes, dup_groups, recall_log.

    Fija que growth se llena con datos reales del archive cuando hay
    ficheros, y que un grupo de duplicado exacto se cuenta correctamente.
    """
    root = _root(tmp_path, "growth", lessons=1)
    mem = root / ".agent" / "runtime" / "memory"
    archive_dir = mem / "archive"
    archive_dir.mkdir()

    # Crear archive con un duplicado exacto
    entry = json.dumps(
        {"id": "obs-dup", "topic": "dup", "signal": "dup-signal", "source": "test"},
        sort_keys=True,
        ensure_ascii=False,
    )
    (archive_dir / "observations.2026-10.jsonl").write_text(
        entry + "\n" + entry + "\n", encoding="utf-8"
    )

    # recall_log.jsonl existente
    (mem / "recall_log.jsonl").write_text("line1\nline2\n", encoding="utf-8")

    measure = measure_root(root, run_validate=False)
    growth = measure["growth"]
    assert growth["archive_rows"] == 2  # 2 lineas no vacias
    assert growth["archive_bytes"] > 0
    assert growth["archive_exact_dup_groups"] == 1  # 1 grupo duplicado
    assert growth["recall_log_lines"] == 2  # 2 lineas no vacias


def test_growth_empty_when_no_archives(tmp_path) -> None:
    """Sin archive: growth vacio."""
    root = _root(tmp_path, "no_archive", lessons=1)
    measure = measure_root(root, run_validate=False)
    assert measure["growth"] == {}


def test_format_prints_growth_and_motor_label(tmp_path, capsys) -> None:
    """El formato de texto imprime crecimiento y etiqueta 'motor'."""
    motor = tmp_path / "motor"
    motor.mkdir()
    (motor / "bus").mkdir()
    (motor / "bus" / "memory_loader.py").write_text("# x", encoding="utf-8")
    mem = motor / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    mem.joinpath("observations.jsonl").write_text(
        json.dumps({"topic": "t", "signal": "s", "source": "src"}) + "\n",
        encoding="utf-8",
    )
    archive_dir = mem / "archive"
    archive_dir.mkdir()
    (archive_dir / "observations.2026-10.jsonl").write_text(
        json.dumps({"topic": "t"}) + "\n", encoding="utf-8"
    )
    measure_root(motor, run_validate=False)
    main(["--project-root", str(motor), "--skip-validate"])
    out = capsys.readouterr().out
    assert "motor:" in out
    assert "archive_rows=" in out
    assert "archive_bytes=" in out


def test_main_motor_vs_destino_labels_in_json(tmp_path, capsys) -> None:
    """main con --project-root=destino --motor-root=real_motor: labels correctos."""
    dest = _root(tmp_path, "dest", lessons=1)
    motor = tmp_path / "real_motor"
    motor.mkdir()
    (motor / "bus").mkdir()
    (motor / "bus" / "memory_loader.py").write_text("# x", encoding="utf-8")
    mem = motor / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    (mem / "observations.jsonl").write_text(
        json.dumps({"topic": "t", "signal": "s", "source": "src"}) + "\n",
        encoding="utf-8",
    )

    code = main(
        [
            "--project-root",
            str(dest),
            "--motor-root",
            str(motor),
            "--json",
            "--skip-validate",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert set(out) == {"motor", "destino"}
    assert out["motor"]["is_motor"] is True
    assert out["destino"]["is_motor"] is False


def test_motor_root_is_the_first_key_in_json_output(tmp_path, capsys) -> None:
    """motor PRIMERO, destino SEGUNDO: el orden de raices es CONTRATO de salida.

    WOT-2026-127e R3-2. El hook SessionStart une las raices con "; " en el orden
    del JSON, asi que la primera clave debe ser "motor" y la segunda "destino".
    Mutation-verify: volver a roots["motor"] = motor (motor al final) -> ROJO;
    restaurar orden motor -> VERDE.
    """
    dest = _root(tmp_path, "dest_r3", lessons=1)
    motor = tmp_path / "motor_r3"
    motor.mkdir()
    (motor / "bus").mkdir()
    (motor / "bus" / "memory_loader.py").write_text("# x", encoding="utf-8")
    mem = motor / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    (mem / "observations.jsonl").write_text(
        json.dumps({"topic": "t", "signal": "s", "source": "src"}) + "\n",
        encoding="utf-8",
    )

    code = main(
        [
            "--project-root",
            str(dest),
            "--motor-root",
            str(motor),
            "--json",
            "--skip-validate",
        ]
    )
    out_raw = capsys.readouterr().out
    assert code == 0
    out = json.loads(out_raw)
    keys = list(out.keys())
    assert keys[0] == "motor", f"Primera clave debe ser 'motor', es '{keys[0]}': {keys}"
    assert keys[1] == "destino", (
        f"Segunda clave debe ser 'destino', es '{keys[1]}': {keys}"
    )


# --- WOT-2026-127e R4: motor key when project_root is motor, (b) absence fire ---


def test_project_root_is_motor_returns_motor_key_only(tmp_path, capsys) -> None:
    """R4-1: cuando project_root == motor, la clave JSON es 'motor', no 'destino'.

    Fija que _is_motor(project_root) hace que main() use la etiqueta "motor"
    en el JSON para project_root, incluso sin --motor-root o con --motor-root
    apuntando al mismo directorio. Mutation-verify: quitar la rama _is_motor
    -> la clave vuelve a ser "destino" (test ROJO).
    """
    motor = tmp_path / "motor_fixture"
    motor.mkdir()
    (motor / "bus").mkdir()
    (motor / "bus" / "memory_loader.py").write_text("# x", encoding="utf-8")
    mem = motor / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    (mem / "observations.jsonl").write_text(
        json.dumps({"topic": "t", "signal": "s", "source": "src"}) + "\n",
        encoding="utf-8",
    )

    code = main(
        [
            "--project-root",
            str(motor),
            "--motor-root",
            str(motor),
            "--json",
            "--skip-validate",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert set(out) == {"motor"}, (
        f"Con project_root=motor, clave debe ser solo 'motor', es {list(out.keys())}"
    )
    assert out["motor"]["is_motor"] is True


def test_project_root_is_motor_no_motor_root_arg(tmp_path, capsys) -> None:
    """R4-1: sin --motor-root y project_root es motor, clave es 'motor'."""
    motor = tmp_path / "motor_noroot"
    motor.mkdir()
    (motor / "bus").mkdir()
    (motor / "bus" / "memory_loader.py").write_text("# x", encoding="utf-8")
    mem = motor / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    (mem / "observations.jsonl").write_text(
        json.dumps({"topic": "t", "signal": "s", "source": "src"}) + "\n",
        encoding="utf-8",
    )

    code = main(["--project-root", str(motor), "--json", "--skip-validate"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert set(out) == {"motor"}, (
        f"Sin --motor-root y project_root=motor, clave debe ser 'motor', "
        f"es {list(out.keys())}"
    )


def test_b_fires_on_memory_md_absent_in_destino(tmp_path) -> None:
    """R4-2: destino sin MEMORY.md -> (b) fired True, detalle 'ausente'.

    Fija que un destino real (sin bus/memory_loader.py) sin MEMORY.md
    dispara (b) con detail que contiene "ausente". Mutation: quitar la rama
    `stale_days is None and not is_motor` -> (b) no dispara (test ROJO).
    """
    dest = tmp_path / "dest_no_md"
    dest.mkdir()
    mem = dest / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    archive = mem / "archive"
    archive.mkdir()
    (archive / "observations.2026-07.jsonl").write_text(
        json.dumps(
            {
                "id": "obs-x",
                "timestamp": "2026-07-28T00:00:00Z",
                "topic": "t",
                "signal": "s",
                "source": "test",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (mem / "observations.jsonl").write_text(
        json.dumps(
            {
                "id": "obs-x",
                "topic": "t",
                "signal": "s",
                "source": "test",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    measure = measure_root(dest, run_validate=False)
    assert measure["memory_md"]["present"] is False
    assert measure["memory_md"]["metodo"] == "ausente"
    trig_b = next(t for t in measure["triggers"] if t["id"] == "b")
    assert trig_b["fired"] is True
    assert "ausente" in trig_b["detail"]


def test_b_no_fire_on_memory_md_absent_in_motor(tmp_path) -> None:
    """R4-2: motor sin MEMORY.md -> (b) fired False (ausencia es normal en motor).

    Fija que un motor (con bus/memory_loader.py) sin MEMORY.md NO dispara (b),
    incluso estando presente. Mutation: devolver True para ambos -> test ROJO.
    """
    motor = tmp_path / "motor_no_md"
    motor.mkdir()
    (motor / "bus").mkdir()
    (motor / "bus" / "memory_loader.py").write_text("# x", encoding="utf-8")
    mem = motor / ".agent" / "runtime" / "memory"
    mem.mkdir(parents=True)
    archive = mem / "archive"
    archive.mkdir()
    (archive / "observations.2026-07.jsonl").write_text(
        json.dumps(
            {
                "id": "obs-x",
                "timestamp": "2026-07-28T00:00:00Z",
                "topic": "t",
                "signal": "s",
                "source": "test",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (mem / "observations.jsonl").write_text(
        json.dumps(
            {
                "id": "obs-x",
                "topic": "t",
                "signal": "s",
                "source": "test",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    measure = measure_root(motor, run_validate=False)
    assert measure["memory_md"]["present"] is False
    assert measure["memory_md"]["metodo"] == "ausente"
    trig_b = next(t for t in measure["triggers"] if t["id"] == "b")
    assert trig_b["fired"] is False


def test_max_archive_entry_timestamp_skips_non_string_timestamp(tmp_path) -> None:
    """R4-3: una entrada con timestamp=int no crashea, usa la valida.

    Fija que una linea con `"timestamp": 12345` (int) se ignora y la funcion
    sigue trabajando con entradas validas. Mutation: no saltar non-str ->
    AttributeError (test ROJO).
    """
    from scripts.check_memory_health import _max_archive_entry_timestamp

    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    (archive_dir / "observations.2026-07.jsonl").write_text(
        json.dumps({"id": "bad", "timestamp": 12345, "signal": "s"}) + "\n",
        encoding="utf-8",
    )
    (archive_dir / "observations.2026-08.jsonl").write_text(
        json.dumps(
            {
                "id": "good",
                "timestamp": "2026-08-15T12:00:00Z",
                "signal": "s",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _max_archive_entry_timestamp(archive_dir)
    assert result is not None
    assert result.year == 2026
    assert result.month == 8
    assert result.day == 15


# --- WOT-2026-127e R5-2: no descartar una raiz motor distinta ------------------------


def test_r5_2_two_distinct_motors_yield_motor_and_motor_proyecto_keys(
    tmp_path, capsys
) -> None:
    """R5-2: dos motores sinteticos distintos -> claves == ["motor", "motor-proyecto"].

    Fija que cuando --motor-root apunta a un motor y --project-root a OTRO motor,
    el JSON incluye ambas raices como "motor" y "motor-proyecto", nunca descartando.
    Mutation: volver a la rama que descarta (else vacio) -> ROJO (node-id y rc).
    """
    motor_a = tmp_path / "motor_a"
    motor_b = tmp_path / "motor_b"
    for m in (motor_a, motor_b):
        m.mkdir()
        (m / "bus").mkdir()
        (m / "bus" / "memory_loader.py").write_text("# motor", encoding="utf-8")
        mem = m / ".agent" / "runtime" / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
        (mem / "observations.jsonl").write_text(
            json.dumps(
                {"topic": "t", "signal": "s", "source": "src", "id": f"obs-{m.name}"}
            )
            + "\n",
            encoding="utf-8",
        )

    code = main(
        [
            "--project-root",
            str(motor_b),
            "--motor-root",
            str(motor_a),
            "--json",
            "--skip-validate",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    keys = list(out.keys())
    assert keys == ["motor", "motor-proyecto"], (
        f"Claves deben ser ['motor', 'motor-proyecto'], es {keys}"
    )
    assert out["motor"]["is_motor"] is True
    assert out["motor-proyecto"]["is_motor"] is True
    assert out["motor"]["root"] != out["motor-proyecto"]["root"]


def test_format_prints_motor_proyecto_label_instead_of_motor(tmp_path) -> None:
    """R6-4 (N-7): _format imprime "motor-proyecto:" para la clave motor-proyecto.

    Fija que el formato de texto muestra la etiqueta exacta del JSON
    ("motor-proyecto") en lugar de substituir todo lo is_motor por "motor".
    """
    from scripts.check_memory_health import _format

    measure = {
        "root": str(tmp_path / "motor_b"),
        "l1": {
            "present": True,
            "parsed": 1,
            "malformed": 0,
            "noise": 0,
            "with_id": 0,
            "noise_ratio": 0.0,
        },
        "l2": {
            "present": True,
            "rules": 0,
            "candidates": None,
            "expelled": None,
            "max_rules": 30,
        },
        "memory_md": {
            "present": True,
            "archives": 0,
            "stale_days": 0.0,
            "metodo": "mtime",
        },
        "validate_rc": 0,
        "triggers": [],
        "layers": {"l1": True, "l2": False, "l3": False, "archives": 0},
        "warnings": [],
        "growth": {},
        "is_motor": True,
    }
    text = _format(measure, "motor-proyecto")
    assert "motor-proyecto:" in text, (
        f"expected 'motor-proyecto:' in output, got: {text}"
    )
    assert text.startswith("[memory-health] motor-proyecto:"), (
        f"_format must start with 'motor-proyecto:', got: {text}"
    )
