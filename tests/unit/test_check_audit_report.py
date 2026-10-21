"""Tests for scripts/check_audit_report.py y scripts/dedupe_audit_findings.py.

Que protegen
------------
La familia de errores de higiene que `prompts/repo_audit_multiagent.md` v2.3 no
podia frenar en la primera corrida real completa (informe de `Redes_Sociales`,
2026-10-21): conteos escritos de memoria (E1, E5, E6), un id citado que nunca
tuvo fila (E2), un id reutilizado con sufijo (E7), el mismo hallazgo en dos
categorias (E8). Los fixtures de abajo reproducen la FORMA de esos casos con los
formatos de tabla REALES: las tablas de `HALLAZGOS_<lane>.md` llevan `categoria`
y las del informe NO (la categoria va en el encabezado `###`).

Before / During / After
-----------------------
Before: sin estado externo; los fixtures son literales y `tmp_path`.
During: llama a las funciones en memoria y a la CLI por subprocess (la ruta
    productiva: `python scripts/check_audit_report.py`, con su propio cwd).
After: cada test nombra el codigo de hallazgo que debe aparecer; el control
    positivo (informe coherente) no debe producir ningun ERROR.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.check_audit_report import (
    audit_report,
    build_tally,
    format_tally_block,
)
from scripts.dedupe_audit_findings import (
    dedupe,
    extraer_filas,
    normaliza_categoria,
)


REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "scripts" / "check_audit_report.py"
DEDUPE = REPO / "scripts" / "dedupe_audit_findings.py"

HALLAZGOS_A = """# HALLAZGOS - lane a

| id | categoria | archivo:linea | evidencia | confianza | impacto | recomendacion |
|----|-----------|----------------|-----------|-----------|---------|---------------|
| H-01 | SECURITY-alta | `pyproject.toml:12` | pip-audit | - | alto | actualizar |
| H-02 | DEAD (unverified dynamic) | `src/a.py:10` | grep | 3 | medio | revisar |
| H-03 | SMELL (falso-positivo deadcode) | `src/b.py:5` | vulture | - | bajo | ignorar |
"""

HALLAZGOS_B = """# HALLAZGOS - lane b

| id | categoria | archivo:linea | evidencia | impacto | recomendacion |
|----|-----------|----------------|-----------|---------|---------------|
| H-04 | ABANDONED | `src/mod.py` | git grep | medio | decidir |
| H-05 | SMELL | `src/c.py:7` | ruff | bajo | refactor |
"""

TALLY_OK = {
    "total": 5,
    "por_categoria": {
        "SECURITY-alta": 1,
        "DEAD (unverified dynamic)": 1,
        "SMELL": 2,
        "ABANDONED": 1,
    },
    "veredictos": {
        "confirmado": 2,
        "disputado": 0,
        "refutado": 0,
        "diferido_no_loop": 3,
    },
}


def informe(
    *, tally: dict | None = TALLY_OK, extra: str = "", dead_section_ids=("H-02",)
) -> str:
    """Informe con el formato REAL: tablas sin columna `categoria`."""
    bloque = f"<!-- TALLY: {json.dumps(tally)} -->\n" if tally is not None else ""
    dead = "\n".join(
        f"| {i} | `src/a.py` | grep | **confirmado** | 3/5 | medio | revisar |"
        for i in dead_section_ids
    )
    return f"""# Informe

## 1. Resumen Ejecutivo

{bloque}
## 3. Hallazgos (por severidad)

### SECURITY-alta

| id | archivo | evidencia | veredicto_adversarial | capas_verificadas | impacto | recomendacion |
|----|---------|-----------|------------------------|--------------------|---------|---------------|
| H-01 | `pyproject.toml:12` | pip-audit | **confirmado** | - | alto | actualizar |

### DEAD (unverified dynamic) - con implicacion de gobierno

| id | archivo | evidencia | veredicto_adversarial | capas_verificadas | impacto | recomendacion |
|----|---------|-----------|------------------------|--------------------|---------|---------------|
{dead}

{extra}
"""


def codigos(res, severidad=None):
    return [h.code for h in res.findings if severidad in (None, h.severity)]


def audit(hall_a=HALLAZGOS_A, hall_b=HALLAZGOS_B, inf=None):
    return audit_report(
        {"a.md": hall_a, "b.md": hall_b},
        informe_text=inf if inf is not None else informe(),
    )


class TestControlPositivo:
    def test_coherent_report_has_no_errors(self):
        res = audit()
        errores = [h for h in res.findings if h.severity == "ERROR"]
        # El unico ERROR admisible es el calificador embebido en la categoria
        # (formato legacy, ver TestFormatoCategoria); ninguno de los demas.
        assert {h.code for h in errores} <= {"CAT-CALIFICADOR"}, errores

    def test_tally_is_recomputed_from_tables_not_from_prose(self):
        tally = build_tally({"a.md": HALLAZGOS_A, "b.md": HALLAZGOS_B}, informe())
        assert tally["total"] == 5
        assert tally["por_categoria"] == TALLY_OK["por_categoria"]
        assert tally["veredictos"]["confirmado"] == 2
        assert tally["veredictos"]["diferido_no_loop"] == 3

    def test_emitted_block_round_trips_through_the_validator(self):
        tally = build_tally({"a.md": HALLAZGOS_A, "b.md": HALLAZGOS_B}, informe())
        bloque = format_tally_block(tally)
        res = audit(inf=informe(tally=None) + "\n" + bloque + "\n")
        assert "TALLY-DESCUADRE" not in codigos(res)
        assert "TALLY-AUSENTE" not in codigos(res)


class TestFamiliaConteo:
    """E1, E5, E6, E9: una cifra del informe que no coincide con las tablas."""

    def test_total_wrong_is_caught(self):
        mal = {**TALLY_OK, "total": 6}  # el "61 vs 60" de la corrida real
        res = audit(inf=informe(tally=mal))
        assert "TALLY-DESCUADRE" in codigos(res, "ERROR")

    def test_category_count_wrong_is_caught(self):
        mal = {
            **TALLY_OK,
            "por_categoria": {
                **TALLY_OK["por_categoria"],
                "DEAD (unverified dynamic)": 2,
                "SMELL": 1,
            },
        }
        res = audit(inf=informe(tally=mal))
        assert "TALLY-DESCUADRE" in codigos(res, "ERROR")

    def test_verdicts_that_do_not_sum_to_total_are_caught(self):
        # "5 confirmados + 56 diferidos" sobre un total de 60 (E5)
        mal = {
            **TALLY_OK,
            "veredictos": {
                "confirmado": 2,
                "disputado": 0,
                "refutado": 0,
                "diferido_no_loop": 4,
            },
        }
        res = audit(inf=informe(tally=mal))
        assert "TALLY-SUMA" in codigos(res, "ERROR")

    def test_missing_tally_block_is_an_error_not_silence(self):
        res = audit(inf=informe(tally=None))
        assert "TALLY-AUSENTE" in codigos(res, "ERROR")


class TestFamiliaIds:
    def test_orphan_id_cited_in_prose_is_caught(self):
        # E2: `H-14` citado en prosa, nunca asignado a fila
        res = audit(inf=informe(extra="Mismo patron que settings.py (H-14)."))
        assert "ID-HUERFANO" in codigos(res, "ERROR")

    def test_suffix_variant_of_an_existing_id_is_caught(self):
        # E7: `H-30(contexto)` reutilizado como sufijo manual
        res = audit(inf=informe(extra="| H-01(complejidad) | `main.py` | 40 | 10 |"))
        assert "ID-SUFIJO" in codigos(res, "ERROR")

    def test_suffix_quoted_inside_a_code_span_is_not_a_new_id(self):
        # Control negativo medido en la corrida real: el informe cita el defecto ya
        # corregido entre backticks ("... `H-30(run_pipeline)` en el primer borrador").
        res = audit(
            inf=informe(extra="El borrador decia `H-01(run_pipeline)` y se corrigio.")
        )
        assert "ID-SUFIJO" not in codigos(res)

    def test_non_canonical_id_in_findings_table_is_reported_not_skipped(self):
        mal = HALLAZGOS_B + "| H-06(ctx) | SMELL | `src/d.py:1` | x | bajo | y |\n"
        res = audit(hall_b=mal)
        assert "ID-NO-CANONICO" in codigos(res, "ERROR")

    def test_duplicate_id_across_files_is_caught(self):
        dup = HALLAZGOS_B + "| H-01 | SMELL | `src/e.py:1` | x | bajo | y |\n"
        res = audit(hall_b=dup)
        assert "ID-DUPLICADO" in codigos(res, "ERROR")


class TestFamiliaCategoria:
    def test_same_finding_under_two_categories_is_caught(self):
        # E8: H-05 es SMELL en su fila y el informe lo lista bajo DEAD
        res = audit(inf=informe(dead_section_ids=("H-02", "H-05")))
        assert "CAT-DIVERGE" in codigos(res, "ERROR")

    def test_free_text_category_outside_the_enum_is_caught(self):
        mal = HALLAZGOS_B.replace("| ABANDONED |", "| MODULO-OLVIDADO |")
        res = audit(hall_b=mal)
        assert "CAT-FUERA-ENUM" in codigos(res, "ERROR")

    def test_normalizer_splits_legacy_qualifier(self):
        assert normaliza_categoria("SMELL (falso-positivo deadcode)") == (
            "SMELL",
            "falso-positivo deadcode",
        )
        assert normaliza_categoria("DEAD (unverified dynamic)") == (
            "DEAD (unverified dynamic)",
            "",
        )
        assert normaliza_categoria("security-ALTA") == ("SECURITY-alta", "")
        assert normaliza_categoria("inventada") == (None, "inventada")

    def test_qualifier_embedded_in_category_is_flagged_for_migration(self):
        res = audit()
        assert "CAT-CALIFICADOR" in codigos(res)


class TestModoYSalida:
    def _write(self, tmp_path, inf):
        (tmp_path / "HALLAZGOS_a.md").write_text(HALLAZGOS_A, encoding="utf-8")
        (tmp_path / "HALLAZGOS_b.md").write_text(HALLAZGOS_B, encoding="utf-8")
        (tmp_path / "INFORME.md").write_text(inf, encoding="utf-8")

    def _cli(self, tmp_path, *extra):
        return subprocess.run(
            [
                sys.executable,
                str(CHECK),
                str(tmp_path / "HALLAZGOS_a.md"),
                str(tmp_path / "HALLAZGOS_b.md"),
                "--informe",
                str(tmp_path / "INFORME.md"),
                *extra,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        )

    def test_default_mode_reports_but_does_not_fail(self, tmp_path):
        self._write(tmp_path, informe(tally={**TALLY_OK, "total": 99}))
        r = self._cli(tmp_path)
        assert r.returncode == 0, r.stderr
        assert "TALLY-DESCUADRE" in r.stdout

    def test_strict_mode_fails_on_the_same_report(self, tmp_path):
        self._write(tmp_path, informe(tally={**TALLY_OK, "total": 99}))
        r = self._cli(tmp_path, "--strict")
        assert r.returncode == 1
        assert "TALLY-DESCUADRE" in r.stdout

    def test_emit_tally_prints_a_block_the_validator_accepts(self, tmp_path):
        self._write(tmp_path, informe(tally=None))
        r = self._cli(tmp_path, "--emit-tally")
        assert r.returncode == 0, r.stderr
        assert r.stdout.startswith("<!-- TALLY:")
        payload = json.loads(r.stdout.strip()[len("<!-- TALLY:") : -len("-->")])
        assert payload["total"] == 5

    def test_unreadable_input_exits_2(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(CHECK), str(tmp_path / "no_existe.md")],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r.returncode == 2


class TestDedupe:
    def test_legacy_table_without_alcance_keeps_line_fingerprint(self):
        filas = extraer_filas(HALLAZGOS_A, "a.md")
        h1 = next(f for f in filas if f["id"] == "H-01")
        assert h1["fingerprint"] == ("pyproject.toml", "12", "SECURITY-ALTA")

    def test_module_scope_row_gets_a_fingerprint_without_a_line(self):
        tabla = (
            "| id | categoria | archivo:linea | alcance | evidencia |\n"
            "|----|-----------|----------------|---------|-----------|\n"
            "| H-10 | ABANDONED | `src/dispatcher.py` | modulo | x |\n"
            "| H-11 | ABANDONED | `src/dispatcher.py` | modulo | x |\n"
        )
        filas = extraer_filas(tabla, "m.md")
        assert filas[0]["fingerprint"] == ("src/dispatcher.py", "*", "ABANDONED")
        duplicados, sin = dedupe(filas)
        assert len(duplicados) == 1 and not sin  # antes caia en "sin fingerprint"

    def test_row_without_alcance_and_without_line_stays_unanchored(self):
        tabla = (
            "| id | categoria | archivo:linea | evidencia |\n"
            "|----|-----------|----------------|-----------|\n"
            "| H-12 | ABANDONED | `src/dispatcher.py` | x |\n"
        )
        _, sin = dedupe(extraer_filas(tabla, "m.md"))
        assert [f["id"] for f in sin] == ["H-12"]

    def test_cli_survives_a_cp1252_console(self, tmp_path):
        # El mismo fallo de `deadcode` en Windows: print() de un caracter que
        # cp1252 no puede representar. Sin forzar UTF-8 en el script, revienta.
        tabla = (
            "| id | categoria | archivo:linea | evidencia |\n"
            "|----|-----------|----------------|-----------|\n"
            "| H-20 | SMELL | `src/✨.py` | x |\n"
            "| H-21 | SMELL | `src/✨.py` | x |\n"
        )
        f = tmp_path / "HALLAZGOS_u.md"
        f.write_text(tabla, encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(DEDUPE), str(f)],
            cwd=tmp_path,
            capture_output=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        )
        assert r.returncode == 0, r.stderr
        assert "Filas leidas: 2" in r.stdout


@pytest.mark.parametrize("script", [CHECK, DEDUPE])
def test_scripts_run_from_a_foreign_cwd(script, tmp_path):
    """Ruta productiva: el script se lanza por path, no como modulo del paquete."""
    r = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0, r.stderr
