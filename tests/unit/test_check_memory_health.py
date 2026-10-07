"""Tests for scripts/check_memory_health.py (WOT-2026-089e, P0).

The trigger of the optimization prompt used to be prose measured by hand on whatever
root the agent had. These tests pin the mechanical measurement: explicit roots, the
compound noise criterion, the published denominator and the schema validator.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_memory_health import main, measure_root


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


def test_an_absent_root_is_measured_as_absent_without_firing_or_raising(
    tmp_path,
) -> None:
    measure = measure_root(tmp_path / "no-existe", run_validate=True)
    assert measure["l1"]["present"] is False
    assert measure["validate_rc"] is None
    assert _fired(measure) == set()


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
