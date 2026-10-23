from __future__ import annotations

from pathlib import Path

from scripts.check_child_closeout_report import (
    CP_IDS,
    HIJO_TERMINADO_LINE,
    main,
    validate_report,
)


CONTRACT_PATH = Path("prompts/builder_invocation_contract.md")

VALID_REPORT = """# CIERRE_PARCIAL_WOT-2026-999z

## CP-1

SHA abc123, `git diff --stat` adjunto.

## CP-2

N/A: sin guard/test nuevo

## CP-3

(a) `ruff check .` exit_code=0

(c) HIJO TERMINADO: sin procesos propios en background ni mutaciones sin restaurar

```
nothing to commit
```

## CP-4

NO PUSH

## CP-5

NINGUNO
"""


class TestSyncWithContract:
    """WOT-2026-104s: los literales hardcodeados aqui deben seguir existiendo,
    con la MISMA forma, en la fuente normativa. Alcance NARROW (no es un
    detector de drift semantico general, ver test_hijo_terminado_literal_
    matches_contract): solo caza el caso en que alguien edita uno de los dos
    lados (contrato o guard) y olvida el otro, sin tocar el contenido exigido
    de cada CP-n (X-09)."""

    def test_contract_file_exists(self) -> None:
        assert CONTRACT_PATH.is_file()

    def test_all_cp_ids_cited_in_contract(self) -> None:
        text = CONTRACT_PATH.read_text(encoding="utf-8")
        for cp in CP_IDS:
            assert f"`{cp}`" in text, f"{cp} ya no aparece citado en el contrato"

    def test_hijo_terminado_literal_matches_contract(self) -> None:
        """Guarda SOLO contra el caso concreto de WOT-2026-104j (el literal se
        edita en un lado y no en el otro). NO es un detector de drift semantico
        general: el contrato podria cambiar el CONTENIDO exigido de cualquier
        CP-n sin tocar estos literales y este test seguiria verde -- el guard
        valida FORMATO, no contenido (ver docstring del script)."""
        text = CONTRACT_PATH.read_text(encoding="utf-8")
        assert HIJO_TERMINADO_LINE in text, (
            "el literal HIJO_TERMINADO_LINE del guard diverge del texto real "
            "del contrato (Section 3.5, CP-3 (c))"
        )


class TestValidateReportHappyPath:
    def test_valid_report_has_no_violations(self) -> None:
        assert validate_report(VALID_REPORT) == []


class TestValidateReportViolations:
    def test_missing_file_entirely_blank(self) -> None:
        violations = validate_report("")
        assert violations
        assert "Faltan encabezados" in violations[0]

    def test_missing_one_cp_section(self) -> None:
        mutated = VALID_REPORT.replace("## CP-5\n\nNINGUNO\n", "")
        violations = validate_report(mutated)
        assert any("CP-5" in v for v in violations)

    def test_empty_cp_section(self) -> None:
        mutated = VALID_REPORT.replace("## CP-4\n\nNO PUSH\n", "## CP-4\n\n## CP-5")
        violations = validate_report(mutated)
        assert any("CP-4" in v and "vacio" in v for v in violations)

    def test_cp3_missing_hijo_terminado_line(self) -> None:
        mutated = VALID_REPORT.replace(
            "(c) HIJO TERMINADO: sin procesos propios en background ni mutaciones sin restaurar\n\n",
            "",
        )
        violations = validate_report(mutated)
        assert any("HIJO TERMINADO" in v and "no contiene" in v for v in violations)

    def test_cp3_nothing_after_hijo_terminado_line(self) -> None:
        mutated = VALID_REPORT.replace("```\nnothing to commit\n```\n\n", "")
        violations = validate_report(mutated)
        assert any("falta contenido posterior" in v for v in violations)

    def test_out_of_order_sections_flagged(self) -> None:
        mutated = (
            VALID_REPORT.replace("## CP-1", "## CP-X-PLACEHOLDER-1")
            .replace("## CP-2", "## CP-1")
            .replace("## CP-X-PLACEHOLDER-1", "## CP-2")
        )
        violations = validate_report(mutated)
        assert any("orden" in v for v in violations)


class TestMainCli:
    def test_main_returns_0_for_valid_report(self, tmp_path: Path, capsys) -> None:
        report = tmp_path / "CIERRE_PARCIAL_WOT-2026-999z.md"
        report.write_text(VALID_REPORT, encoding="utf-8")
        rc = main(["--report", str(report)])
        assert rc == 0
        assert "formato OK" in capsys.readouterr().out

    def test_main_returns_1_for_missing_file(self, tmp_path: Path, capsys) -> None:
        rc = main(["--report", str(tmp_path / "no_existe.md")])
        assert rc == 1
        assert "ausente" in capsys.readouterr().out

    def test_main_returns_1_for_malformed_report(self, tmp_path: Path, capsys) -> None:
        report = tmp_path / "CIERRE_PARCIAL_WOT-2026-999z.md"
        report.write_text("# nada util aqui\n", encoding="utf-8")
        rc = main(["--report", str(report)])
        assert rc == 1
        assert "NO VERIFICABLE" in capsys.readouterr().out
