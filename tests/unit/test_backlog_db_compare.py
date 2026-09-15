"""Tests for scripts/backlog_db_compare.py (F1, WOT-2026-069f).

Cobertura (contrato T-069F-001, tras la enmienda IDF): D1 CLI/parseo, D2
denominador fail-closed, D3 metrica+no-transitividad, D4 FLT, D5 informes
md+json con head-sha, D6 no-escritura (hashes + colision fail-closed), D7
fixture sintetico del patron 045c/049h/058u (SEPARADO de la evidencia
historica), D8 cadena A~B~C sin A~C, D9 negativo disjunto, D11 frontera de
sensibilidad del umbral con fixtures PINEADOS (los scores de los fixtures son
constantes independientes del umbral elegido: el test de meseta NO se
auto-confirma).

Los fixtures son SINTETICOS: los tokens `kx/ky/kz/...` se generan para
controlar el score IDF de cada par dentro de la banda medida del patron real
(0.14-0.24) y del ruido de cola (~0.10). Los valores se PINEAN aqui como
constantes: si el algoritmo los desplaza, este fichero falla y obliga a
rejustificar la banda.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def _find_module() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "scripts" / "backlog_db_compare.py",  # motor: tests/unit/..
        here.parents[1] / "backlog_db_compare.py",  # scratch dev: <dir>/tests/..
        here.parents[2] / "backlog_db_compare.py",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise AssertionError("no se encontro backlog_db_compare.py en candidatos")


_SPEC = importlib.util.spec_from_file_location("backlog_db_compare", _find_module())
bdc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bdc)


HEADER = (
    "# Backlog (cola viva)\n\n## Vista rapida\n\n"
    "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
    "|-----------|--------|--------|-------|--------|------------|--------|--------------|\n"
)


def _tok(prefix: str, n: int) -> list[str]:
    return [f"{prefix}{i:03d}" for i in range(n)]


def _row(label: str, tokens: list[str]) -> str:
    return f"| Media | {label} | {' '.join(tokens)} | fx/{label.lower()} | pending | - | s | - |\n"


def _write_backlog(tmp_path: Path, rows: list[str], name: str = "backlog.md") -> Path:
    p = tmp_path / name
    p.write_text(HEADER + "".join(rows), encoding="utf-8", newline="\n")
    return p


# --- Fixture PATRON (045c/049h/058u), banda IDF medida 0.14-0.30 -------------
# Conjuntos (df = en cuantas de las 3 entradas aparece cada token): A lleva
# X20(df2) mas Y10(df2) mas oA8(df1); B lleva X20 mas Z12(df3) mas oB14(df1);
# C lleva Y10 mas Z12 mas oC12(df1).
# Scores IDF MEDIDOS (constantes pineadas abajo): A-B 0.2713; B-C 0.1519;
# A-C 0.1407. Los tres >= 0.12 (default); los DOS DEBILES < 0.17 (=default+0.05).
_PAT_A = _tok("kx", 20) + _tok("ky", 10) + _tok("ka", 8)
_PAT_B = _tok("kx", 20) + _tok("kz", 12) + _tok("kb", 14)
_PAT_C = _tok("ky", 10) + _tok("kz", 12) + _tok("kc", 12)
PAT_A, PAT_B, PAT_C = "WOT-2026-900a", "WOT-2026-900b", "WOT-2026-900c"

# --- Fixture RUIDO DE COLA: par ~0.107 (banda (default-0.05, default)) -------
_N1 = _tok("kn", 7) + _tok("kna", 22)
_N2 = _tok("kn", 7) + _tok("knb", 22)
NOI_A, NOI_B = "WOT-2026-901a", "WOT-2026-901b"

# --- Fixture CADENA (no-transitividad): A-B ~0.361, B-C ~0.272, A-C = 0 ----
_CH_A = _tok("tx", 30) + _tok("ta", 22)
_CH_B = _tok("tx", 30) + _tok("tz", 24)
_CH_C = _tok("tz", 24) + _tok("tc", 26)
CHA, CHB, CHC = "WOT-2026-902a", "WOT-2026-902b", "WOT-2026-902c"


def _run(args: list[str]) -> int:
    return bdc.main(args)


def _json_of(
    tmp_path: Path, backlog: Path, extra: list[str] | None = None, out: str = "r.json"
) -> dict:
    out_path = tmp_path / out
    args = ["--backlog", str(backlog), "--out-json", str(out_path)] + (extra or [])
    rc = _run(args)
    assert rc == 0, f"rc inesperado {rc}"
    return json.loads(out_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# D1 / D5: CLI + informes
# ---------------------------------------------------------------------------


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        _run(["--help"])
    assert exc.value.code == 0


def test_reports_md_and_json_with_head_sha(tmp_path):
    backlog = _write_backlog(tmp_path, [_row(PAT_A, _PAT_A), _row(PAT_B, _PAT_B)])
    out_md = tmp_path / "out.md"
    out_json = tmp_path / "out.json"
    rc = _run(
        [
            "--backlog",
            str(backlog),
            "--head-sha",
            "a" * 40,
            "--out",
            str(out_md),
            "--out-json",
            str(out_json),
        ]
    )
    assert rc == 0
    md = out_md.read_text(encoding="utf-8")
    assert "LOTES DE REVISION" in md
    assert "idf" in md
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["schema"] == "backlog-db-compare/v1"
    assert data["head_sha"] == "a" * 40
    assert data["head_sha_origin"] == "explicit"
    assert data["criteria"]["metric"] == "idf"
    assert data["criteria"]["idf_corpus_n"] == 2


def test_json_stdout_is_parseable(tmp_path, capsys):
    backlog = _write_backlog(tmp_path, [_row(PAT_A, _PAT_A)])
    rc = _run(["--backlog", str(backlog), "--json", "--head-sha", "b" * 40])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["entries_total"] == 1


# ---------------------------------------------------------------------------
# D7: patron 045c/049h/058u -> UN lote con pares listados + scores pineados
# ---------------------------------------------------------------------------


def test_pattern_fixture_emits_one_lote_with_pairs(tmp_path):
    backlog = _write_backlog(
        tmp_path,
        [_row(PAT_A, _PAT_A), _row(PAT_B, _PAT_B), _row(PAT_C, _PAT_C)],
    )
    data = _json_of(tmp_path, backlog)
    assert data["lots_count"] == 1, data["lots"]
    lot = data["lots"][0]
    assert sorted(lot["members"]) == sorted([PAT_A, PAT_B, PAT_C])
    assert len(lot["edges"]) == 3  # los 3 pares superan el umbral 0.12
    for e in lot["edges"]:
        assert e["score"] >= bdc.UMBRAL_DEFAULT
    # el par mas fuerte (A-B, ~0.295) esta listado y ordenado el primero
    assert lot["edges"][0]["a"] == PAT_A and lot["edges"][0]["b"] == PAT_B


def test_pattern_fixture_scores_pinned_non_circular(tmp_path):
    """Los scores de los fixtures son CONSTANTES pineadas (bandas), no derivadas
    del umbral: el test de sensibilidad D11 los mide, no los fabrica."""
    backlog = _write_backlog(
        tmp_path,
        [_row(PAT_A, _PAT_A), _row(PAT_B, _PAT_B), _row(PAT_C, _PAT_C)],
    )
    data = _json_of(tmp_path, backlog, extra=["--threshold", "0.05"], out="pins.json")
    scores = {
        (e["a"], e["b"]): e["score"] for lot in data["lots"] for e in lot["edges"]
    }
    ab = scores[(PAT_A, PAT_B)]
    ac = scores[(PAT_A, PAT_C)]
    bc = scores[(PAT_B, PAT_C)]
    assert 0.25 <= ab <= 0.35, ab
    assert 0.12 <= ac < 0.17, ac  # debil: dentro de la banda (default, default+0.05)
    assert 0.12 <= bc < 0.17, bc
    assert ab > bc and ab > ac


# ---------------------------------------------------------------------------
# D8: cadena A~B~C sin A~C -> 1 lote, 2 aristas, el par A-C NO se lista
# ---------------------------------------------------------------------------


def test_chain_lote_is_component_not_clique(tmp_path):
    backlog = _write_backlog(
        tmp_path, [_row(CHA, _CH_A), _row(CHB, _CH_B), _row(CHC, _CH_C)]
    )
    data = _json_of(tmp_path, backlog)
    assert data["lots_count"] == 1
    lot = data["lots"][0]
    assert sorted(lot["members"]) == sorted([CHA, CHB, CHC])
    assert len(lot["edges"]) == 2
    pairs = {(e["a"], e["b"]) for e in lot["edges"]}
    assert pairs == {(CHA, CHB), (CHB, CHC)}
    assert (CHA, CHC) not in pairs  # no-transitividad: A-C no es arista


# ---------------------------------------------------------------------------
# D9: sin solape -> sin lotes / sin aristas
# ---------------------------------------------------------------------------


def test_disjoint_rows_no_lotes(tmp_path):
    backlog = _write_backlog(
        tmp_path,
        [_row("WOT-2026-903a", _tok("dd", 30)), _row("WOT-2026-903b", _tok("ee", 30))],
    )
    data = _json_of(tmp_path, backlog)
    assert data["edges_count"] == 0
    assert data["lots_count"] == 0


# ---------------------------------------------------------------------------
# D11: frontera de sensibilidad (fixtures pineados; banda +-0.05 del default)
# ---------------------------------------------------------------------------


def test_raised_threshold_breaks_full_pattern_lote(tmp_path):
    backlog = _write_backlog(
        tmp_path,
        [_row(PAT_A, _PAT_A), _row(PAT_B, _PAT_B), _row(PAT_C, _PAT_C)],
    )
    # default+0.05 = 0.17: los dos pares debiles (< 0.17) caen; solo A-B queda.
    data = _json_of(tmp_path, backlog, extra=["--threshold", "0.17"])
    for lot in data["lots"]:
        assert PAT_C not in lot["members"]


def test_lowered_threshold_admits_noise_band_pair(tmp_path):
    backlog = _write_backlog(tmp_path, [_row(NOI_A, _N1), _row(NOI_B, _N2)])
    at_default = _json_of(tmp_path, backlog, out="r1.json")
    assert at_default["lots_count"] == 0  # ~0.107 < 0.12
    at_low = _json_of(tmp_path, backlog, extra=["--threshold", "0.10"], out="r2.json")
    assert at_low["lots_count"] == 1  # ~0.107 >= 0.10: la banda de cola entra


# ---------------------------------------------------------------------------
# D6: NO-ESCRITURA (hash de entradas intacto) + colision fail-closed
# ---------------------------------------------------------------------------


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_no_write_hashes_and_collision_abort(tmp_path):
    backlog = _write_backlog(tmp_path, [_row(PAT_A, _PAT_A), _row(PAT_B, _PAT_B)])
    before = _sha(backlog)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    rc = _run(
        [
            "--backlog",
            str(backlog),
            "--head-sha",
            "c" * 40,
            "--out",
            str(out_dir / "r.md"),
            "--out-json",
            str(out_dir / "r.json"),
        ]
    )
    assert rc == 0
    assert _sha(backlog) == before  # el recolector no toco su entrada

    # colision declarada: --out apuntando a la propia DB -> rc=2 ANTES de escribir
    rc2 = _run(
        [
            "--backlog",
            str(backlog),
            "--head-sha",
            "c" * 40,
            "--out",
            str(backlog),
        ]
    )
    assert rc2 == 2
    assert _sha(backlog) == before


# ---------------------------------------------------------------------------
# Determinismo
# ---------------------------------------------------------------------------


def test_output_is_deterministic(tmp_path):
    backlog = _write_backlog(
        tmp_path,
        [_row(PAT_A, _PAT_A), _row(PAT_B, _PAT_B), _row(PAT_C, _PAT_C)],
    )
    rc = _run(
        [
            "--backlog",
            str(backlog),
            "--head-sha",
            "d" * 40,
            "--out-json",
            str(tmp_path / "a.json"),
        ]
    )
    assert rc == 0
    rc = _run(
        [
            "--backlog",
            str(backlog),
            "--head-sha",
            "d" * 40,
            "--out-json",
            str(tmp_path / "b.json"),
        ]
    )
    assert rc == 0
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


# ---------------------------------------------------------------------------
# Metrica: raw disponible como comparacion declarada, nunca default
# ---------------------------------------------------------------------------


def test_metric_raw_available_and_declared(tmp_path):
    backlog = _write_backlog(
        tmp_path,
        [_row(PAT_A, _PAT_A), _row(PAT_B, _PAT_B), _row(PAT_C, _PAT_C)],
    )
    data = _json_of(tmp_path, backlog, extra=["--metric", "raw", "--threshold", "0.15"])
    assert data["criteria"]["metric"] == "raw"
    assert data["criteria"]["idf_corpus_n"] is None
    assert data["lots_count"] == 1  # raw: A-B 0.31, B-C 0.21, A-C 0.16 >= 0.15


# ---------------------------------------------------------------------------
# D2: denominador fail-closed + conteo de saltados
# ---------------------------------------------------------------------------


def test_universe_with_content_but_zero_inspected_fails_closed(tmp_path):
    # filas de tabla SIN cabecera: el parser no puede etiquetarlas -> rc=2
    p = tmp_path / "sin_cabecera.md"
    p.write_text(
        "| Media | WOT-2026-904a | algo | scope | pending | - | s | - |\n",
        encoding="utf-8",
        newline="\n",
    )
    rc = _run(["--backlog", str(p)])
    assert rc == 2


def test_universe_counters_and_skipped_lists(tmp_path):
    # backlog valido + inbox con ficha (formato `## Ticket:`) y otra (formato H1
    # `# FP-... -- titulo`, medido en el buzon real) + queued con plan y un json
    backlog = _write_backlog(tmp_path, [_row(PAT_A, _PAT_A)])
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "FP-20260915-demo.tickets.md").write_text(
        "## Ticket: FP-20260915-demo-1\n- titulo demo\n", encoding="utf-8", newline="\n"
    )
    (inbox / "FP-20260914-h1-demo.tickets.md").write_text(
        "# FP-20260914 -- demo en formato H1\n\ncuerpo de la ficha\n",
        encoding="utf-8",
        newline="\n",
    )
    (inbox / "README.md").write_text("no es ficha\n", encoding="utf-8", newline="\n")
    queued = tmp_path / "queued"
    queued.mkdir()
    (queued / "FP-20260915-plan.md").write_text(
        "# Plan demo\n", encoding="utf-8", newline="\n"
    )
    (queued / "meta.json").write_text("{}\n", encoding="utf-8", newline="\n")

    out = tmp_path / "counters.json"
    rc = _run(
        [
            "--backlog",
            str(backlog),
            "--inbox",
            str(inbox),
            "--queued",
            str(queued),
            "--head-sha",
            "e" * 40,
            "--out-json",
            str(out),
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    by_surface = {u["surface"]: u for u in data["universes"]}
    assert by_surface["backlog"]["inspected"] == 1
    assert by_surface["inbox"]["inspected"] == 2  # ambos formatos en el mismo buzon
    assert any(s["where"] == "README.md" for s in by_surface["inbox"]["skipped"])
    assert by_surface["plans"]["inspected"] == 1
    assert any(s["where"] == "meta.json" for s in by_surface["plans"]["skipped"])


# ---------------------------------------------------------------------------
# D4: contratos -> mapa T-* <-> WOT-* + FLT + cobertura declarada
# ---------------------------------------------------------------------------

_CONTRACTS = """# Ticket contracts

## T-090A-001 -- WOT-2026-900a: demo con FLT

- **ticket_id:** WOT-2026-900a
- **Files Likely Touched (una unica ruta parseable por bullet):**
  - `scripts/backlog_db_compare.py`
  - `tests/unit/test_backlog_db_compare.py`
- **Forbidden Surfaces:**
  - `privada/`

## T-090B-001 -- WOT-2026-900b: demo sin ticket_id

- **Objective-Link:** demo
"""


def test_contracts_map_and_coverage(tmp_path):
    backlog = _write_backlog(
        tmp_path,
        [_row(PAT_A, _PAT_A), _row(PAT_B, _PAT_B), _row(PAT_C, _PAT_C)],
    )
    contracts = tmp_path / "ticket_contracts.md"
    contracts.write_text(_CONTRACTS, encoding="utf-8", newline="\n")
    out = tmp_path / "r.json"
    rc = _run(
        [
            "--backlog",
            str(backlog),
            "--contracts",
            str(contracts),
            "--head-sha",
            "f" * 40,
            "--out-json",
            str(out),
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    c = data["contracts"]
    assert c["blocks_total"] == 2
    assert c["blocks_resolved"] == 1
    assert any("090B" in s["where"] for s in c["skipped"])
    flt = c["flt_entries"]["WOT-2026-900a"]
    assert "scripts/backlog_db_compare.py" in flt
    assert "tests/unit/test_backlog_db_compare.py" in flt
