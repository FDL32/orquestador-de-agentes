"""Tests of the pre-registered O6b probe (WOT-2026-124h).

Hermetic: two synthetic archives (motor and destination) in ``tmp_path`` with
the real archive layout read by ``read_archive_observations``; the renders come
from the real ``bus.memory_loader.format_memory_index``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

from bus import memory_loader as ml  # noqa: E402
from scripts import measure_index_o6b as m  # noqa: E402


UTC = timezone.utc


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _obs(oid: str, when: datetime, signal: str = "", **extra) -> dict:
    return {
        "id": oid,
        "timestamp": _iso(when),
        "topic": extra.pop("topic", oid),
        "signal": signal or f"leccion {oid}",
        "source": "test",
        **extra,
    }


def _archive(root: Path, entries: list[dict]) -> Path:
    d = root / ".agent" / "runtime" / "memory" / "archive"
    d.mkdir(parents=True, exist_ok=True)
    (d / "observations.2026-10.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8"
    )
    return root


def _union(motor: list[dict], destino: list[dict]) -> list[dict]:
    return [{**e, "_origin": "local"} for e in destino] + [
        {**e, "_origin": "motor"} for e in motor
    ]


T0 = m.O6B_START
OLD = T0 - timedelta(days=40)


# (i) filtro de corte inicial
def test_no_cut_before_o6b_start_even_with_history():
    citer = _obs("obs-citer", T0 - timedelta(days=20), "aplica obs-target")
    target = _obs("obs-target", OLD)
    rows = m.measure(_union([citer, target], []), now=T0 + timedelta(days=29))
    assert rows == []
    rows = m.measure(_union([citer, target], []), now=T0 + timedelta(days=30))
    assert [r["t"] for r in rows] == [T0.isoformat()]
    assert rows[0]["objetivo"] == 0, "la cita es anterior a O6B_START: no es objetivo"


# (ii) ventana abierta -> INSUFICIENTE con 0 cortes
def test_open_window_is_insufficient(tmp_path, capsys):
    motor = _archive(tmp_path / "motor", [_obs("obs-a", OLD)])
    dest = _archive(tmp_path / "dest", [_obs("obs-b", OLD)])
    rc = m.main(
        [
            "--motor-root",
            str(motor),
            "--project-root",
            str(dest),
            "--now",
            "2026-11-20T00:00:00Z",
            "--json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["cortes"] == [] and out["veredicto"] == "INSUFICIENTE"


# (iii) las frescas no compiten por Importantes
def test_fresh_lesson_never_enters_important():
    fresh = _obs("obs-fresh", T0 - timedelta(days=2))
    old = _obs("obs-old", OLD)
    citers = [
        _obs(f"obs-c{i}", T0 - timedelta(days=1), "ver obs-fresh obs-old")
        for i in range(3)
    ]
    corpus = _union([fresh, old, *citers], [])
    edges = m.citation_edges(m._vigent_lessons(corpus))
    chosen = [e["id"] for e in m.select_important(corpus, edges, set(), T0)]
    assert chosen == ["obs-old"]


# (iv) autocita y refutadas no cuentan como cita
def test_self_and_stale_citations_do_not_count():
    a = _obs("obs-aa", OLD, "me cito obs-aa")
    dead = _obs("obs-dead", OLD, "cito obs-bb", status="refuted")
    b = _obs("obs-bb", OLD)
    c = _obs("obs-cc", OLD, "cito obs-dead")
    d = _obs("obs-dd", OLD, "cito obs-bb")  # control: a valid citation counts
    edges = m.citation_edges(m._vigent_lessons(_union([a, dead, b, c, d], [])))
    assert [cited for _date, cited in edges] == ["obs-bb"]


# (v) cuota por origen en Importantes
def test_origin_quota_keeps_destination_in_important():
    motor = [_obs(f"obs-m{i}", OLD + timedelta(hours=i)) for i in range(8)]
    dest = [_obs(f"obs-d{i}", OLD + timedelta(hours=i)) for i in range(2)]
    cite_all = " ".join(e["id"] for e in motor) + " " + " ".join(e["id"] for e in motor)
    citers = [_obs(f"obs-x{i}", T0 - timedelta(days=1), cite_all) for i in range(3)]
    citers.append(_obs("obs-y", T0 - timedelta(days=1), "obs-d0 obs-d1"))
    corpus = _union(motor + citers, dest)
    edges = m.citation_edges(m._vigent_lessons(corpus))
    chosen = {e["id"] for e in m.select_important(corpus, edges, set(), T0)}
    assert {"obs-d0", "obs-d1"} <= chosen
    assert len(chosen) == m.O6B_IMPORTANT


# (vi) render dentro del presupuesto, seccion Importantes y suelos restaurados
def test_render_budget_section_and_floors_restored(monkeypatch):
    many = [
        _obs(f"obs-l{i:03d}", OLD + timedelta(hours=i), "x " * 40) for i in range(120)
    ]
    important = many[:8]
    render = m.render_o6b(_union(many, []), important)
    assert len(render) <= ml.INDEX_BUDGET_CHARS
    assert m.IMPORTANT_HEADER in render
    assert {e["id"] for e in important} <= m.shown_ids(render)
    assert (ml.INDEX_FLOOR_TOTAL, ml.INDEX_FLOOR_PER_ORIGIN) == (25, 10)

    def boom(*_a, **_k):
        raise RuntimeError("render roto")

    monkeypatch.setattr(ml, "format_memory_index", boom)
    with pytest.raises(RuntimeError):
        m.render_o6b(_union(many, []), important)
    assert (ml.INDEX_FLOOR_TOTAL, ml.INDEX_FLOOR_PER_ORIGIN) == (25, 10)


# (vii) logica del veredicto, una clausula cada vez
def _row(t, obj, hoy, o6b, fh, fo):
    return {
        "t": t,
        "objetivo": obj,
        "aciertos_hoy": hoy,
        "aciertos_o6b": o6b,
        "frescas": 10,
        "frescas_hoy": fh,
        "frescas_o6b": fo,
    }


@pytest.mark.parametrize(
    ("rows", "expected", "clause"),
    [
        ([_row("1", 10, 2, 4, 10, 10), _row("2", 10, 2, 3, 10, 10)], "CUMPLE", None),
        (
            [_row("1", 10, 2, 2, 10, 10), _row("2", 10, 2, 2, 10, 10)],
            "NO CUMPLE",
            "(a)",
        ),
        (
            [_row("1", 10, 3, 6, 10, 10), _row("2", 10, 3, 2, 10, 10)],
            "NO CUMPLE",
            "(b)",
        ),
        (
            [_row("1", 10, 2, 4, 10, 7), _row("2", 10, 2, 3, 10, 10)],
            "NO CUMPLE",
            "(c) corte",
        ),
        (
            [_row("1", 10, 2, 4, 10, 8), _row("2", 10, 2, 3, 10, 9)],
            "NO CUMPLE",
            "(c) agregado",
        ),
        ([_row("1", 25, 2, 4, 10, 10)], "INSUFICIENTE", "corte(s) valido(s)"),
        (
            [_row("1", 9, 2, 4, 10, 10), _row("2", 10, 2, 3, 10, 10)],
            "INSUFICIENTE",
            "objetivo total",
        ),
        (
            [
                _row("1", 10, 2, 4, 10, 10),
                _row("2", 10, 2, 3, 10, 10),
                _row("3", 0, 0, 0, 0, 0),
            ],
            "CUMPLE",
            None,
        ),
    ],
)
def test_verdict_clauses(rows, expected, clause):
    result, reasons = m.verdict(rows)
    assert result == expected
    if clause:
        assert any(clause in r for r in reasons), reasons
    else:
        assert reasons == []


# (viii) HOY es el render real
def test_hoy_is_the_real_render():
    citer = _obs("obs-citer", T0 + timedelta(days=3), "aplica obs-target")
    target = _obs("obs-target", OLD)
    union = _union([citer, target], [_obs("obs-dest", OLD)])
    rows = m.measure(union, now=T0 + timedelta(days=30))
    corpus_t = [e for e in union if m._ts(e) < T0]
    real = ml.format_memory_index(corpus_t, local_text="", budget=ml.INDEX_BUDGET_CHARS)
    assert rows[0]["len_hoy"] == len(real)
    assert rows[0]["objetivo"] == 1 and rows[0]["aciertos_hoy"] == 1


def test_union_drops_motor_copies_of_destination_ids(tmp_path):
    motor = _archive(tmp_path / "motor", [_obs("obs-same", OLD), _obs("obs-m", OLD)])
    dest = _archive(tmp_path / "dest", [_obs("obs-same", OLD)])
    union = m.build_union(motor, dest)
    assert sorted((e["id"], e["_origin"]) for e in union) == [
        ("obs-m", "motor"),
        ("obs-same", "local"),
    ]


def test_cli_rejects_missing_project_root(monkeypatch, capsys):
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    assert m.main([]) == 2
    assert m.main(["--project-root", str(MOTOR_ROOT), "--now", "ayer"]) == 2


def test_objective_only_counts_lessons_born_before_the_cut():
    """OBJETIVO(t): a lesson born inside the window cannot be shown at t, so a
    citation to it is not part of the objective."""
    newborn = _obs("obs-newborn", T0 + timedelta(days=2))
    citer = _obs("obs-citer", T0 + timedelta(days=5), "aplica obs-newborn")
    rows = m.measure(_union([newborn, citer], []), now=T0 + timedelta(days=30))
    assert rows[0]["objetivo"] == 0


def test_shown_ids_are_only_the_leading_id_of_index_lines():
    """Mostradas = ids of ``- <id>:`` lines; an id quoted inside a signal, or a
    topic line without id, is not shown."""
    render = "\n".join(
        [
            "- obs-aa: aplica obs-bb",
            "- topic-sin-id: menciona obs-cc (--recall --query topic-sin-id)",
            "[REFUTADA] obs-dd: refutada",
        ]
    )
    assert m.shown_ids(render) == {"obs-aa"}


def test_corrupt_archive_stops_the_measurement_with_rc2(tmp_path, capsys):
    """Deliberate divergence from the boot loader (codex review of f969b620):
    a corrupt archive is NOT degraded to empty -- the probe refuses to measure."""
    motor = _archive(tmp_path / "motor", [_obs("obs-mm", OLD)])
    dest = _archive(tmp_path / "dest", [_obs("obs-dd", OLD)])
    bad = (
        dest
        / ".agent"
        / "runtime"
        / "memory"
        / "archive"
        / "observations.2026-09.jsonl"
    )
    bad.write_text("{no es json\n", encoding="utf-8")
    rc = m.main(["--motor-root", str(motor), "--project-root", str(dest), "--json"])
    assert rc == 2
    assert "archive corrupto" in capsys.readouterr().err


def test_duplicate_ids_follow_the_newest_copy_like_the_renderer():
    """Two copies of one id: the NEWEST decides (as `_dedup_newest` in the
    renderer), whatever their order in the union -- a newer refuted copy makes
    the lesson stale, a newer vigent copy carries the citation."""
    old_v = _obs("obs-dup", OLD, "cita obs-tt")
    new_refuted = _obs(
        "obs-dup", OLD + timedelta(days=1), "cita obs-tt", status="refuted"
    )
    target = _obs("obs-tt", OLD)
    for order in ([old_v, new_refuted, target], [new_refuted, old_v, target]):
        assert "obs-dup" not in m._vigent_lessons(_union(order, []))
    new_v = _obs("obs-dup", OLD + timedelta(days=2), "sin citas")
    for order in ([new_v, old_v, target], [old_v, new_v, target]):
        vigent = m._vigent_lessons(_union(order, []))
        assert vigent["obs-dup"]["signal"] == "sin citas"
        assert m.citation_edges(vigent) == []
