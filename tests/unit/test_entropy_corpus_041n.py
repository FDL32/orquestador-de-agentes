"""WOT-2026-041n: el corpus de entropia y sus bordes de meseta son re-derivables.

Before: tests/data/entropy_corpus_wot2026041n.jsonl versionado en el repo; el
    modulo real scripts/ensemble_dispatch.py export _shannon_bits,
    _ENTROPY_MIN_TOKEN_LEN y _ENTROPY_BITS_THRESHOLD.
During: re-deriva cada metrica del corpus con la funcion real, reconstruye la
    decision del guard (len >= min_len y bits >= thr) por celda de la malla
    citada en el informe y contrasta los bordes publicados.
After: falla si el corpus miente sobre sus propias metricas, si los bordes
    publicados ya no se reproducen, o si una entrada corrupcionada no se
    detecta (mutation del propio test).
"""

import json
import sys
from pathlib import Path


sys.path.insert(0, "scripts")
import ensemble_dispatch as ed


CORPUS = Path("tests/data/entropy_corpus_wot2026041n.jsonl")

# Bordes publicados en
# orchestrator_pipeline/reports/SWEEP_umbral_entropia_041n_20261025.md
# (evidencia fechada 2026-10-25; si cambian, el cambio es una decision, no un accidente).
BORDER_MIN_LEN = 38
BORDER_THR_LOWER = 3.9
BORDER_THR_UPPER = 4.15
BLOCKED_AT_CURRENT = 8
BLOCKED_AT_MIN_LEN_38 = 6
BLOCKED_AT_THR_LOWER = 10
BLOCKED_AT_THR_UPPER = 7


def _load_corpus() -> list[dict]:
    lines = CORPUS.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _blocked(entries: list[dict], min_len: int, thr: float) -> list[dict]:
    return [e for e in entries if e["len"] >= min_len and e["shannon_bits"] >= thr]


def _assert_entry(e: dict) -> None:
    assert e["len"] == len(e["token"]), e["token"]
    assert abs(ed._shannon_bits(e["token"]) - e["shannon_bits"]) < 5e-4, e["token"]
    assert e["kind"] in ("real_bundle", "real_response", "documented_case"), e["token"]
    assert e["sources"] and e["source_sha256"], e["token"]


def test_corpus_metricas_son_re_derivables_con_la_funcion_real() -> None:
    entries = _load_corpus()
    assert len(entries) >= 30
    for e in entries:
        _assert_entry(e)


def test_bordes_de_meseta_se_reproducen() -> None:
    entries = _load_corpus()
    cur = ed._ENTROPY_MIN_TOKEN_LEN, ed._ENTROPY_BITS_THRESHOLD
    assert len(_blocked(entries, *cur)) == BLOCKED_AT_CURRENT
    assert len(_blocked(entries, BORDER_MIN_LEN, cur[1])) == BLOCKED_AT_MIN_LEN_38
    assert len(_blocked(entries, cur[0], BORDER_THR_LOWER)) == BLOCKED_AT_THR_LOWER
    assert len(_blocked(entries, cur[0], BORDER_THR_UPPER)) == BLOCKED_AT_THR_UPPER
    # Meseta real en thr: la decision es IDENTICA dentro de [3.95, 4.1]
    # (borde inferior 3.9 y superior 4.15 segun el informe).
    for thr in (3.95, 4.05, 4.1):
        assert len(_blocked(entries, cur[0], thr)) == BLOCKED_AT_CURRENT


def test_documented_cases_059k_estan_en_el_corpus() -> None:
    tokens = {e["token"] for e in _load_corpus()}
    assert "EXPLORATORY-proceso-manager-builder-c4" in tokens
    assert any(t.startswith("PREFIJO-palabra-") for t in tokens)
    assert any(t.startswith("batch_run_FP-") for t in tokens)
    assert any(t.startswith("tested_commit_sha") for t in tokens)


def test_mutation_corrupcion_de_metrica_se_detecta() -> None:
    entries = _load_corpus()
    entries[0] = dict(entries[0])
    entries[0]["shannon_bits"] = round(entries[0]["shannon_bits"] + 1.0, 4)
    try:
        _assert_entry(entries[0])
    except AssertionError:
        pass
    else:
        raise AssertionError("la corrupcion de shannon_bits NO fue detectada")
