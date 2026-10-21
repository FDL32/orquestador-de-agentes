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
    _celdas,
    dedupe,
    extraer_filas,
    fence_sin_cerrar,
    normaliza_categoria,
    parse_tablas,
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
        # El UNICO ERROR es el calificador embebido en la categoria (formato legacy
        # de HALLAZGOS_A): igualdad, no subconjunto, para que borrar una
        # comprobacion no deje este test en verde. El caso sin ningun ERROR vive en
        # TestControlPositivoEstricto.
        assert {h.code for h in errores} == {"CAT-CALIFICADOR"}, errores

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


HALLAZGOS_A_LIMPIO = HALLAZGOS_A.replace("SMELL (falso-positivo deadcode)", "SMELL")


def seccion(titulo: str, *ids: str, categoria: str | None = None) -> str:
    """Seccion extra del informe: tabla con el formato real (sin `categoria`)."""
    col = " categoria |" if categoria else ""
    sep = "---|" if categoria else ""
    filas = "\n".join(
        f"| {i} | {(categoria + ' | ') if categoria else ''}`x.py` | e | **confirmado** |"
        for i in ids
    )
    return (
        f"### {titulo}\n\n| id |{col} archivo | evidencia | veredicto_adversarial |\n"
        f"|----|{sep}---------|-----------|------------------------|\n{filas}\n"
    )


class TestControlPositivoEstricto:
    """El control positivo de verdad: un informe limpio sale con exit 0 en --strict."""

    def test_clean_report_has_zero_errors_in_memory(self):
        res = audit(hall_a=HALLAZGOS_A_LIMPIO)
        assert codigos(res, "ERROR") == []

    def test_clean_report_exits_0_in_strict_mode(self, tmp_path):
        (tmp_path / "HALLAZGOS_a.md").write_text(HALLAZGOS_A_LIMPIO, encoding="utf-8")
        (tmp_path / "HALLAZGOS_b.md").write_text(HALLAZGOS_B, encoding="utf-8")
        (tmp_path / "INFORME.md").write_text(informe(), encoding="utf-8")
        r = subprocess.run(
            [
                sys.executable,
                str(CHECK),
                str(tmp_path / "HALLAZGOS_a.md"),
                str(tmp_path / "HALLAZGOS_b.md"),
                "--informe",
                str(tmp_path / "INFORME.md"),
                "--strict",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r.returncode == 0, r.stdout + r.stderr


class TestTallyMalformado:
    """BA07/BA06: JSON valido pero mal tipado reventaba con un traceback (exit != 0/1/2)."""

    @pytest.mark.parametrize(
        "mal",
        [
            {**TALLY_OK, "veredictos": None},
            {**TALLY_OK, "veredictos": [1]},
            {**TALLY_OK, "por_categoria": None},
            {**TALLY_OK, "por_categoria": "x"},
            {**TALLY_OK, "total": "5"},
            {**TALLY_OK, "total": True},
            {**TALLY_OK, "veredictos": {**TALLY_OK["veredictos"], "otros": 1}},
            {**TALLY_OK, "veredictos": {**TALLY_OK["veredictos"], "confirmado": 1.5}},
        ],
    )
    def test_wrong_shape_is_an_error_not_a_traceback(self, mal):
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(tally=mal))
        assert "TALLY-DESCUADRE" in codigos(res, "ERROR")

    def test_two_tally_blocks_are_ambiguous(self):
        extra = f"<!-- TALLY: {json.dumps(TALLY_OK)} -->"
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra=extra))
        assert "TALLY-MULTIPLE" in codigos(res, "ERROR")

    def test_a_single_block_is_not_multiple(self):
        res = audit(hall_a=HALLAZGOS_A_LIMPIO)
        assert "TALLY-MULTIPLE" not in codigos(res)


class TestSufijosDeId:
    @pytest.mark.parametrize(
        "cita",
        ["H-01bis", "H-01bc", "H-01-2", "H-01_legacy", "H-01.v2", "H-01(ctx)", "H-01b"],
    )
    def test_any_suffix_variant_of_an_existing_id_is_caught(self, cita):
        res = audit(
            hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra=f"Ver {cita} en el texto.")
        )
        assert "ID-SUFIJO" in codigos(res, "ERROR"), cita

    @pytest.mark.parametrize(
        "cita",
        ["H-01.", "H-01, H-02", "(H-01)", "H-01-H-02", "H-01/H-02", "H-01:"],
    )
    def test_plain_citations_are_not_suffixes(self, cita):
        res = audit(
            hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra=f"Ver {cita} en el texto.")
        )
        assert "ID-SUFIJO" not in codigos(res), cita

    def test_same_suffix_is_only_forgiven_inside_a_code_span(self):
        dentro = audit(inf=informe(extra="El borrador decia `H-01_legacy` antes."))
        fuera = audit(inf=informe(extra="El borrador decia H-01_legacy antes."))
        assert "ID-SUFIJO" not in codigos(dentro)
        assert "ID-SUFIJO" in codigos(fuera)


class TestIdsEnMinusculas:
    def test_lowercase_id_in_prose_is_not_canonical(self):
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra="Ver h-05 abajo."))
        assert "ID-NO-CANONICO" in codigos(res, "ERROR")

    def test_lowercase_id_inside_a_code_span_is_a_literal_quote(self):
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra="Decia `h-05`."))
        assert "ID-NO-CANONICO" not in codigos(res)

    def test_lowercase_id_in_findings_table_is_reported(self):
        mal = HALLAZGOS_B + "| h-06 | SMELL | `src/d.py:1` | x | bajo | y |\n"
        assert "ID-NO-CANONICO" in codigos(audit(hall_b=mal), "ERROR")


class TestCensoCompleto:
    def test_row_with_unparseable_id_is_reported_not_dropped_silently(self):
        mal = HALLAZGOS_B + "| X-07 | SMELL | `src/d.py:1` | x | bajo | y |\n"
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, hall_b=mal)
        assert "ID-NO-CANONICO" in codigos(res, "ERROR")
        assert res.tally["total"] == 5  # la fila X-07 no entra en el censo

    def test_empty_id_cell_is_reported(self):
        mal = HALLAZGOS_B + "|  | SMELL | `src/d.py:1` | x | bajo | y |\n"
        assert "ID-NO-CANONICO" in codigos(audit(hall_b=mal), "ERROR")

    def test_unrecognised_table_that_cites_ids_is_an_error(self):
        # cabecera sin `categoria`: antes el fichero entero valia 0 filas en silencio
        sin_cat = "| id | archivo |\n|----|---------|\n| H-01 | `a.py:1` |\n"
        res = audit(hall_b=sin_cat)
        assert "HALLAZGOS-SIN-FILAS" in codigos(res, "ERROR")

    def test_file_without_any_id_is_only_a_warning(self):
        res = audit(hall_b="# HALLAZGOS - lane b\n\nSin hallazgos en este lane.\n")
        assert "HALLAZGOS-SIN-FILAS" in codigos(res, "WARN")
        assert "HALLAZGOS-SIN-FILAS" not in codigos(res, "ERROR")

    def test_wide_row_is_a_warning(self):
        ancha = HALLAZGOS_B + "| H-06 | SMELL | `a.py:1` | x | bajo | y | sobrante |\n"
        res = audit(hall_b=ancha)
        assert "FILA-ANCHO" in codigos(res, "WARN")

    def test_escaped_pipe_does_not_split_the_cell(self):
        # `git grep "a\|b"` es la evidencia REAL de la corrida de Redes_Sociales
        fila = '| H-06 | SMELL | `a.py:1` | `git grep "a\\|b"` | bajo | y |\n'
        res = audit(hall_b=HALLAZGOS_B + fila)
        assert "FILA-ANCHO" not in codigos(res)
        assert res.tally["total"] == 6

    def test_unescaped_pipe_is_flagged_instead_of_shifting_columns_silently(self):
        fila = '| H-06 | SMELL | `a.py:1` | `git grep "a|b"` | bajo | y |\n'
        assert "FILA-ANCHO" in codigos(audit(hall_b=HALLAZGOS_B + fila), "WARN")


class TestParserRobusto:
    def test_bom_on_first_table_line_keeps_the_rows(self):
        # El BOM va pegado a la PRIMERA linea de tabla (sin encabezado `#` delante),
        # que es el caso que antes descartaba la tabla entera: total 0 en silencio.
        bom = chr(0xFEFF)
        tabla = "| id | categoria |\n|----|-----------|\n| H-01 | SMELL |\n"
        assert build_tally({"a.md": bom + tabla})["total"] == 1

    def test_accented_header_is_the_same_column(self):
        acento = HALLAZGOS_B.replace("| categoria |", "| categoría |")
        assert audit(hall_b=acento).tally["total"] == 5

    def test_single_dash_gfm_separator_is_a_separator(self):
        t = "| id | categoria |\n|:-:|:-:|\n| H-01 | SMELL |\n"
        assert build_tally({"a.md": t})["total"] == 1

    # La fila de ejemplo pone H-05 (SMELL) bajo `### DEAD`: solo es un CAT-DIVERGE si
    # la tabla se parsea. (El texto crudo sigue contando para ID-HUERFANO a proposito:
    # una cita de id es una cita aunque este en un bloque.)
    _TABLA_EJEMPLO = (
        "| id | archivo | evidencia | veredicto_adversarial |\n"
        "|----|---------|-----------|------------------------|\n"
        "| H-05 | `x.py` | e | **confirmado** |\n"
    )

    def test_table_inside_a_code_fence_is_a_quoted_example(self):
        extra = "### DEAD\n\n```\n" + self._TABLA_EJEMPLO + "```\n"
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra=extra))
        assert "CAT-DIVERGE" not in codigos(res)

    def test_same_table_outside_the_fence_is_parsed(self):
        extra = "### DEAD\n\n" + self._TABLA_EJEMPLO
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra=extra))
        assert "CAT-DIVERGE" in codigos(res)

    def test_cli_reads_a_file_with_a_utf8_bom(self, tmp_path):
        ruta = tmp_path / "HALLAZGOS_a.md"
        ruta.write_bytes(b"\xef\xbb\xbf" + HALLAZGOS_A_LIMPIO.encode("utf-8"))
        r = subprocess.run(
            [sys.executable, str(CHECK), str(ruta), "--emit-tally"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        assert '"total": 3' in r.stdout

    def test_two_files_with_the_same_basename_are_both_counted(self, tmp_path):
        for lane, texto in (("uno", HALLAZGOS_A_LIMPIO), ("dos", HALLAZGOS_B)):
            (tmp_path / lane).mkdir()
            (tmp_path / lane / "HALLAZGOS.md").write_text(texto, encoding="utf-8")
        r = subprocess.run(
            [
                sys.executable,
                str(CHECK),
                str(tmp_path / "uno" / "HALLAZGOS.md"),
                str(tmp_path / "dos" / "HALLAZGOS.md"),
                "--emit-tally",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        assert '"total": 5' in r.stdout


class TestPipesEscapadosGFM:
    """`\\|` es un pipe literal; una barra escapada seguida de `|` SI delimita."""

    BS = chr(92)

    def test_escaped_pipe_stays_inside_the_cell(self):
        celdas = _celdas(f"| H-01 | git grep a{self.BS}|b | SMELL |")
        assert celdas == ["H-01", "git grep a|b", "SMELL"]

    def test_escaped_backslash_before_a_pipe_still_delimits(self):
        # `C:{BS}dir{BS}{BS}|` = ruta que acaba en barra + delimitador de celda
        celdas = _celdas(f"| H-01 | C:{self.BS}dir{self.BS}{self.BS}| SMELL |")
        assert celdas == ["H-01", f"C:{self.BS}dir{self.BS}{self.BS}", "SMELL"]

    def test_odd_run_of_backslashes_escapes_the_pipe(self):
        # 3 barras = `\\` (barra literal) + `\|` (pipe escapado): una sola celda
        tres = self.BS * 3
        assert _celdas(f"| a{tres}|b | c |") == [f"a{self.BS}{self.BS}|b", "c"]

    def test_trailing_escaped_pipe_is_not_the_closing_delimiter(self):
        assert _celdas(f"| a | b{self.BS}|") == ["a", "b|"]

    def test_empty_last_cell_is_kept_but_the_closing_pipe_is_dropped(self):
        assert _celdas("| a | |") == ["a", ""]
        assert _celdas("| a | b |") == ["a", "b"]
        assert _celdas("| a | b") == ["a", "b"]

    def test_lone_trailing_backslash_does_not_crash(self):
        assert _celdas(f"| a | b{self.BS}") == ["a", f"b{self.BS}"]

    def test_row_with_escaped_backslash_then_pipe_is_not_misaligned(self):
        # la barra escapada pega al delimitador: con el lookbehind antiguo se fusionaban
        # las celdas `archivo` y `evidencia` y la fila salia con una columna de menos
        dos = self.BS * 2
        fila = f"| H-06 | SMELL | C:{self.BS}dir{dos}| x | bajo | y |\n"
        res = audit(hall_b=HALLAZGOS_B + fila)
        assert "FILA-ANCHO" not in codigos(res)
        assert res.tally["total"] == 6


class TestCensoPerdidoRonda2:
    """BA07 ronda 2: formas de perder filas con exit 0 que la ronda 1 no cerro."""

    _VALIDA = "| id | categoria |\n|----|-----------|\n| H-01 | SMELL |\n"
    _MALA = "| id | categ | archivo |\n|---|---|---|\n| H-77 | SMELL | `b.py:2` |\n"

    def test_malformed_table_next_to_a_valid_one_is_an_error(self):
        # el fichero YA tiene filas, asi que HALLAZGOS-SIN-FILAS no salta: este es el hueco
        res = audit_report({"a.md": self._VALIDA + "\n" + self._MALA})
        assert "TABLA-SIN-CATEGORIA" in codigos(res, "ERROR")
        assert res.tally["total"] == 1  # H-77 no entra en el censo

    def test_a_table_with_categoria_is_not_flagged(self):
        res = audit_report({"a.md": self._VALIDA})
        assert "TABLA-SIN-CATEGORIA" not in codigos(res)

    def test_an_id_table_without_hallazgo_ids_is_not_flagged(self):
        # tabla auxiliar (p.ej. lanes) con columna `id` pero sin ids H-<n>
        aux = "| id | lane |\n|----|------|\n| 1 | tools |\n"
        res = audit_report({"a.md": self._VALIDA + "\n" + aux})
        assert "TABLA-SIN-CATEGORIA" not in codigos(res)

    def test_three_files_with_the_same_basename_and_parent_all_count(self, tmp_path):
        rutas = []
        for k in (1, 2, 3):
            carpeta = tmp_path / f"r{k}" / "lane"
            carpeta.mkdir(parents=True)
            fichero = carpeta / "HALLAZGOS.md"
            fichero.write_text(
                self._VALIDA.replace("H-01", f"H-0{k}"), encoding="utf-8"
            )
            rutas.append(str(fichero))
        r = subprocess.run(
            [sys.executable, str(CHECK), *rutas, "--emit-tally"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        assert '"total": 3' in r.stdout

    def test_the_same_path_passed_twice_does_not_crash_or_overwrite(self, tmp_path):
        fichero = tmp_path / "HALLAZGOS.md"
        fichero.write_text(self._VALIDA, encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(CHECK), str(fichero), str(fichero), str(fichero)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        # cada repeticion se ve (2 duplicados de 3 ficheros), ninguna se pisa en silencio
        assert r.stdout.count("ID-DUPLICADO") == 2


class TestAnclasYCerosRonda2:
    """BA06: un ancla de enlace no es una cita, y H-30 / H-030 son el mismo hallazgo."""

    def test_link_anchor_with_a_lowercase_id_is_not_a_citation(self):
        extra = "[Ver H-01](#h-01) y la ruta docs/h-01.md citan el mismo ancla.\n"
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra=extra))
        assert "ID-NO-CANONICO" not in codigos(res)

    def test_lowercase_id_in_plain_prose_is_still_caught(self):
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra="Ver h-01 abajo.\n"))
        assert "ID-NO-CANONICO" in codigos(res, "ERROR")

    def test_leading_zeros_do_not_disguise_a_duplicate(self):
        uno = "| id | categoria |\n|----|-----------|\n| H-30 | SMELL |\n"
        otro = "| id | categoria |\n|----|-----------|\n| H-030 | SMELL |\n"
        res = audit_report({"a.md": uno, "b.md": otro})
        assert "ID-DUPLICADO" in codigos(res, "ERROR")
        assert res.tally["total"] == 1  # el segundo no entra en el censo

    def test_distinct_numbers_with_zeros_are_not_duplicates(self):
        uno = "| id | categoria |\n|----|-----------|\n| H-30 | SMELL |\n"
        otro = "| id | categoria |\n|----|-----------|\n| H-031 | SMELL |\n"
        res = audit_report({"a.md": uno, "b.md": otro})
        assert "ID-DUPLICADO" not in codigos(res)
        assert res.tally["total"] == 2


class TestEncabezadosYEjemplosRonda2:
    def test_group_heading_levels_are_case_insensitive_and_exact(self):
        con_baja = HALLAZGOS_B + "| H-06 | SECURITY-baja | `d.py:1` | x | bajo | y |\n"
        ok = audit(
            hall_b=con_baja,
            inf=informe(extra=seccion("SECURITY-alta / MEDIA", "H-01")),
        )
        mal = audit(
            hall_b=con_baja,
            inf=informe(extra=seccion("SECURITY-alta / MEDIA", "H-06")),
        )
        assert "CAT-DIVERGE" not in codigos(ok)  # alta cabe en "alta / MEDIA"
        assert "CAT-DIVERGE" in codigos(mal)  # baja NO cabe en "alta / MEDIA"

    def test_a_level_listed_in_uppercase_after_the_slash_is_accepted(self):
        # `MEDIA` en mayusculas debe contar como `SECURITY-media`, no ignorarse
        con_media = (
            HALLAZGOS_B + "| H-06 | SECURITY-media | `d.py:1` | x | bajo | y |\n"
        )
        res = audit(
            hall_b=con_media,
            inf=informe(extra=seccion("SECURITY-alta / MEDIA", "H-06")),
        )
        assert "CAT-DIVERGE" not in codigos(res)

    def test_an_uppercase_level_in_the_heading_still_compares_exactly(self):
        # `### SECURITY-ALTA` es el nivel alta: una fila baja bajo el NO cabe, y una alta SI
        con_baja = HALLAZGOS_B + "| H-06 | SECURITY-baja | `d.py:1` | x | bajo | y |\n"
        mal = audit(
            hall_b=con_baja, inf=informe(extra=seccion("SECURITY-ALTA", "H-06"))
        )
        bien = audit(
            hall_b=con_baja, inf=informe(extra=seccion("SECURITY-ALTA", "H-01"))
        )
        assert "CAT-DIVERGE" in codigos(mal)
        assert "CAT-DIVERGE" not in codigos(bien)

    def test_id_cited_inside_a_code_fence_is_a_quoted_example(self):
        ejemplo = "```\n| H-99 | ejemplo |\n```\n"
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra=ejemplo))
        assert "ID-HUERFANO" not in codigos(res)

    def test_same_id_outside_the_fence_is_still_an_orphan(self):
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra="Ver H-99 abajo.\n"))
        assert "ID-HUERFANO" in codigos(res, "ERROR")

    def test_example_tally_block_inside_a_fence_is_not_a_second_block(self):
        ejemplo = f"```\n<!-- TALLY: {json.dumps(TALLY_OK)} -->\n```\n"
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra=ejemplo))
        assert "TALLY-MULTIPLE" not in codigos(res)

    def test_a_real_tally_only_inside_a_fence_counts_as_absent(self):
        envuelto = f"```\n<!-- TALLY: {json.dumps(TALLY_OK)} -->\n```\n"
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(tally=None, extra=envuelto))
        assert "TALLY-AUSENTE" in codigos(res, "ERROR")


class TestFencesSangria:
    """El cierre solo vale con <= 3 espacios MAS de sangrado que la apertura."""

    _TABLA = "| id | categoria |\n|---|---|\n| H-99 | SMELL |\n"

    def test_over_indented_closing_fence_does_not_close_the_block(self):
        texto = "```text\n    ```\n" + self._TABLA
        assert fence_sin_cerrar(texto) == 1  # ruidoso, no una fila fantasma
        assert parse_tablas(texto, "x") == []

    def test_closing_fence_with_up_to_three_extra_spaces_closes(self):
        texto = "```text\n   ```\n" + self._TABLA
        assert fence_sin_cerrar(texto) is None
        assert [f["cols"]["id"] for f in parse_tablas(texto, "x")] == ["H-99"]

    def test_nested_fence_in_a_list_item_closes_with_its_own_indent(self):
        texto = "- item\n\n    ```text\n    codigo\n    ```\n\n" + self._TABLA
        assert fence_sin_cerrar(texto) is None
        assert [f["cols"]["id"] for f in parse_tablas(texto, "x")] == ["H-99"]


class TestFencesCommonMark:
    """Un bloque de codigo mal cerrado no puede tragarse filas en silencio."""

    _TABLA = "| id | categoria |\n|----|-----------|\n| H-0{n} | SMELL |\n"

    def _dos_tablas(self, entre: str) -> str:
        return self._TABLA.format(n=1) + entre + "\n" + self._TABLA.format(n=2)

    def test_unclosed_fence_between_tables_is_an_error_not_silent_row_loss(self):
        texto = self._dos_tablas("```\nejemplo sin cerrar\n")
        res = audit_report({"a.md": texto})
        assert "FENCE-SIN-CERRAR" in codigos(res, "ERROR")
        assert res.tally["total"] == 1  # la fila H-02 queda dentro del fence

    def test_unclosed_fence_in_the_report_is_an_error(self):
        res = audit(hall_a=HALLAZGOS_A_LIMPIO, inf=informe(extra="```\nabierto\n"))
        assert "FENCE-SIN-CERRAR" in codigos(res, "ERROR")

    def test_properly_closed_fence_is_not_an_error(self):
        texto = self._dos_tablas("```python\nx = 1\n```\n")
        res = audit_report({"a.md": texto})
        assert "FENCE-SIN-CERRAR" not in codigos(res)
        assert res.tally["total"] == 2

    def test_inline_triple_backticks_do_not_open_a_fence(self):
        texto = self._dos_tablas("```x``` es codigo en linea\n")
        res = audit_report({"a.md": texto})
        assert "FENCE-SIN-CERRAR" not in codigos(res)
        assert res.tally["total"] == 2

    def test_tilde_fence_is_not_closed_by_backticks(self):
        texto = self._dos_tablas("~~~\ncodigo\n```\n")
        res = audit_report({"a.md": texto})
        assert "FENCE-SIN-CERRAR" in codigos(res, "ERROR")

    def test_closing_fence_must_be_at_least_as_long_as_the_opening(self):
        corto = self._dos_tablas("````\ncodigo\n```\n")  # 3 no cierra 4
        largo = self._dos_tablas("```\ncodigo\n````\n")  # 4 si cierra 3
        assert "FENCE-SIN-CERRAR" in codigos(audit_report({"a.md": corto}), "ERROR")
        res_largo = audit_report({"a.md": largo})
        assert "FENCE-SIN-CERRAR" not in codigos(res_largo)
        assert res_largo.tally["total"] == 2  # el cierre largo SI cerro: H-02 cuenta

    def test_closing_fence_cannot_carry_text(self):
        texto = self._dos_tablas("```\ncodigo\n``` texto\n")
        assert "FENCE-SIN-CERRAR" in codigos(audit_report({"a.md": texto}), "ERROR")

    def test_unclosed_fence_line_number_points_at_the_opening(self):
        texto = "# L\n\n```\nabierto\n"
        assert fence_sin_cerrar(texto) == 3
        assert fence_sin_cerrar("# L\n\n```\ncodigo\n```\n") is None


class TestCategoriaExacta:
    """Severidad de SECURITY y encabezados: antes solo se comparaba la FAMILIA."""

    def test_security_level_mismatch_is_caught(self):
        # H-01 es SECURITY-alta en su fila y el informe lo lista bajo -baja
        res = audit(inf=informe(extra=seccion("SECURITY-baja", "H-01")))
        assert "CAT-DIVERGE" in codigos(res, "ERROR")

    def test_same_security_level_is_fine(self):
        res = audit(inf=informe(extra=seccion("SECURITY-alta", "H-01")))
        assert "CAT-DIVERGE" not in codigos(res)

    def test_grouped_heading_accepts_exactly_the_levels_it_names(self):
        con_baja = HALLAZGOS_B + "| H-06 | SECURITY-baja | `d.py:1` | x | bajo | y |\n"
        ok = audit(
            hall_b=con_baja,
            inf=informe(extra=seccion("SECURITY-media / baja (deps)", "H-06")),
        )
        mal = audit(
            hall_b=con_baja,
            inf=informe(extra=seccion("SECURITY-media / baja (deps)", "H-01")),
        )
        assert "CAT-DIVERGE" not in codigos(ok)  # baja cabe en "media / baja"
        assert "CAT-DIVERGE" in codigos(mal)  # alta NO cabe en "media / baja"

    def test_grouped_family_heading_accepts_any_of_its_members(self):
        res = audit(inf=informe(extra=seccion("DEAD / ABANDONED", "H-04")))
        assert "CAT-DIVERGE" not in codigos(res)

    def test_dead_unverified_dynamic_is_not_plain_dead(self):
        # H-02 es `DEAD (unverified dynamic)` (implicacion de gobierno distinta)
        res = audit(inf=informe(extra=seccion("DEAD", "H-02")))
        assert "CAT-DIVERGE" in codigos(res, "ERROR")

    def test_plain_dead_is_not_dead_unverified_dynamic(self):
        # El sentido inverso: una fila `DEAD` plana bajo el encabezado del nivel
        # dinamico tampoco cabe; bajo `### DEAD` si.
        fila = "| H-06 | DEAD | `src/d.py:1` | x | bajo | y |\n"
        mal = audit(
            hall_b=HALLAZGOS_B + fila,
            inf=informe(extra=seccion("DEAD (unverified dynamic)", "H-06")),
        )
        bien = audit(
            hall_b=HALLAZGOS_B + fila, inf=informe(extra=seccion("DEAD", "H-06"))
        )
        assert "CAT-DIVERGE" in codigos(mal, "ERROR")
        assert "CAT-DIVERGE" not in codigos(bien)

    @pytest.mark.parametrize(
        "titulo",
        ["Deadline de entrega", "DEADLINE de entrega", "Proceso de verificacion"],
    )
    def test_heading_prose_is_not_a_category(self, titulo):
        res = audit(inf=informe(extra=seccion(titulo, "H-05")))
        assert "CAT-DIVERGE" not in codigos(res)

    def test_category_column_in_the_report_table_is_compared_exactly(self):
        mal = audit(
            inf=informe(extra=seccion("Otros", "H-01", categoria="SECURITY-baja"))
        )
        bien = audit(
            inf=informe(extra=seccion("Otros", "H-01", categoria="SECURITY-alta"))
        )
        assert "CAT-DIVERGE" in codigos(mal)
        assert "CAT-DIVERGE" not in codigos(bien)

    def test_category_column_outside_the_enum_in_the_report_is_caught(self):
        res = audit(inf=informe(extra=seccion("Otros", "H-05", categoria="INVENTADA")))
        assert "CAT-FUERA-ENUM" in codigos(res, "ERROR")


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
