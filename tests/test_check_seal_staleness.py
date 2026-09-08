#!/usr/bin/env python3
"""Tests for scripts/check_seal_staleness.py (WOT-2026-055c).

Covers the three-layer contract of the start-context-isolation receipt guard:
(1) integrity triple-via (prompt_sha256 + prompt_bytes + prompt_lines),
(2) temporal order (approved_at after prompt mtime), (3) semantic freshness
(WARN heuristic). Plus the hard anchors of audit sec 4.bis: flight, scope,
project_root_resolved, approved_by external, status RESOLVED.

Fixtures are hermetic: real receipts + real prompt files in tmp_path, no
filesystem mocking. Temporal control uses os.utime. The single mocked call is
_measured_validate_counts (a subprocess boundary), used only to exercise the
WARN heuristic deterministically.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from scripts.check_seal_staleness import check_seal_staleness, main


def _write_prompt(root: Path, content: str = "# Arranque de vuelo test\n") -> Path:
    prompt = root / "arrranque_test.md"
    prompt.write_text(content, encoding="utf-8", newline="\n")
    # mtime deterministico en el pasado: approved_at (12:00, aware) queda
    # POSTERIOR, asi el orden temporal es hermetico e independiente de la hora
    # en que corra la suite.
    os.utime(prompt, (1784800000, 1784800000))  # 2026-07-24-ish (UTC epoch)
    return prompt


def _write_receipt(
    root: Path,
    *,
    prompt: Path,
    status: str = "RESOLVED",
    flight: str = "FP-TEST-0001",
    approved_by: str = "human-operator",
    approved_at: str = "2026-08-22T12:00:00+02:00",
    scope: list[str] | None = None,
    payload: dict | None = None,
) -> Path:
    data = payload if payload is not None else {}
    data.setdefault("status", status)
    data.setdefault("flight", flight)
    data.setdefault("prompt_path", str(prompt))
    data.setdefault("prompt_sha256", hashlib.sha256(prompt.read_bytes()).hexdigest())
    data.setdefault("prompt_bytes", prompt.stat().st_size)
    data.setdefault("prompt_lines", len(prompt.read_bytes().splitlines()))
    data.setdefault("project_root_resolved", str(root))
    data.setdefault("approved_by", approved_by)
    data.setdefault("approved_at", approved_at)
    # scope conforme por defecto; un payload con "scope": None (o ausente via
    # payload) produce el caso que el guard debe cazar.
    if "scope" not in data:
        data["scope"] = ["WOT-2026-055c"]
    receipt = root / "start_context_isolation.json"
    receipt.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return receipt


def _write_executed_prompt(
    root: Path,
    content: str = "# Arranque REALMENTE ejecutado B\nlinea dos\n",
    utime: int = 1784800000,
) -> Path:
    """El prompt B que la sesion REALMENTE ejecuto (WOT-2026-066z). Fichero
    aparte del sellado A, con bytes distintos y mtime controlado como
    _write_prompt para que el orden temporal sea hermetico."""
    prompt = root / "arranque_ejecutado_B.md"
    prompt.write_text(content, encoding="utf-8", newline="\n")
    os.utime(prompt, (utime, utime))
    return prompt


class TestIntegrityTripleVia:
    def test_conforming_receipt_has_no_findings(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        receipt = _write_receipt(tmp_path, prompt=prompt)
        assert (
            check_seal_staleness(receipt, prompt_path=prompt, flight_id="FP-TEST-0001")
            == []
        )

    def test_sha_mismatch_is_hard(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        payload = {
            "prompt_sha256": "0" * 64,
        }
        receipt = _write_receipt(tmp_path, prompt=prompt, payload=payload)
        findings = check_seal_staleness(receipt, prompt_path=prompt)
        assert any("prompt_sha256" in f for f in findings)
        assert all(not f.startswith("[WARN]") for f in findings)

    def test_bytes_mismatch_is_hard(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        payload = {"prompt_bytes": -1}
        receipt = _write_receipt(tmp_path, prompt=prompt, payload=payload)
        findings = check_seal_staleness(receipt, prompt_path=prompt)
        assert any("prompt_bytes" in f for f in findings)

    def test_lines_mismatch_is_hard(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        payload = {"prompt_lines": 9999}
        receipt = _write_receipt(tmp_path, prompt=prompt, payload=payload)
        findings = check_seal_staleness(receipt, prompt_path=prompt)
        assert any("prompt_lines" in f for f in findings)


class TestExecutedPromptAnchor:
    """WOT-2026-066z / DEC-066Z-001: nivel 2 de la cascada del prompt REALLY
    consumido. El recibo declara en `prompt_executed_path` el arranque que la
    sesion REALMENTE ejecuto (lo escribe el RESOLVER del recibo, no el
    ejecutor); el guard lo contrasta contra el sello midiendo BYTES, no
    afirmaciones. El nivel 3 (receipt.prompt_path) queda CONSERVADO como
    fallback legacy por decision (DEC-066Z-001 sec 4)."""

    def test_declared_executed_prompt_distinct_from_sealed_is_hard(
        self, tmp_path: Path
    ) -> None:
        prompt_a = _write_prompt(tmp_path)
        prompt_b = _write_executed_prompt(tmp_path)
        receipt = _write_receipt(
            tmp_path, prompt=prompt_a, payload={"prompt_executed_path": str(prompt_b)}
        )
        findings = check_seal_staleness(receipt)
        sha_findings = [f for f in findings if "prompt_sha256" in f]
        assert sha_findings, findings
        # la discrepancia NOMBRA a A y a B, no solo los shas:
        assert prompt_b.name in sha_findings[0]
        assert prompt_a.name in sha_findings[0]
        assert all(not f.startswith("[WARN]") for f in findings)

    def test_declared_executed_prompt_equal_to_sealed_is_clean(
        self, tmp_path: Path
    ) -> None:
        # Control de simetria (DoD 1): misma via, caso feliz -> sin hallazgos.
        prompt_a = _write_prompt(tmp_path)
        receipt = _write_receipt(
            tmp_path, prompt=prompt_a, payload={"prompt_executed_path": str(prompt_a)}
        )
        assert check_seal_staleness(receipt) == []

    def test_arg_still_wins_over_declared_executed_prompt(self, tmp_path: Path) -> None:
        # Nivel 1 > nivel 2: el arg del CLI/humano sigue mandando sobre el campo.
        prompt_a = _write_prompt(tmp_path)
        prompt_b = _write_executed_prompt(tmp_path)
        receipt = _write_receipt(
            tmp_path, prompt=prompt_a, payload={"prompt_executed_path": str(prompt_b)}
        )
        assert check_seal_staleness(receipt, prompt_path=prompt_a) == []

    def test_declared_executed_prompt_relative_resolves_against_receipt_dir(
        self, tmp_path: Path
    ) -> None:
        prompt_a = _write_prompt(tmp_path)
        subdir = tmp_path / "sesion"
        subdir.mkdir()
        prompt_b = _write_executed_prompt(subdir)
        receipt = _write_receipt(
            tmp_path,
            prompt=prompt_a,
            payload={"prompt_executed_path": "sesion/arranque_ejecutado_B.md"},
        )
        findings = check_seal_staleness(receipt)
        assert any("prompt_sha256" in f and prompt_b.name in f for f in findings)

    def test_declared_executed_prompt_missing_is_hard(self, tmp_path: Path) -> None:
        # Ancla DECLARADA que no resuelve -> hard (fail-closed), nombrando el campo.
        prompt_a = _write_prompt(tmp_path)
        receipt = _write_receipt(
            tmp_path,
            prompt=prompt_a,
            payload={"prompt_executed_path": str(tmp_path / "desaparecido.md")},
        )
        findings = check_seal_staleness(receipt)
        assert any(
            "cannot resolve" in f and "prompt_executed_path" in f for f in findings
        )

    def test_receipt_without_executed_field_keeps_legacy_fallback(
        self, tmp_path: Path
    ) -> None:
        # La AUSENCIA del campo no es hallazgo: un recibo legacy conforme cae al
        # nivel 3 y sale limpio (DEC-066Z-001 sec 4).
        prompt_a = _write_prompt(tmp_path)
        receipt = _write_receipt(tmp_path, prompt=prompt_a)
        assert check_seal_staleness(receipt) == []


class TestTemporalOrder:
    def test_approved_at_predating_prompt_mtime_is_hard(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        past = "2020-01-01T00:00:00+02:00"
        receipt = _write_receipt(tmp_path, prompt=prompt, approved_at=past)
        findings = check_seal_staleness(receipt, prompt_path=prompt)
        assert any("approved_at" in f and "EARLIER" in f for f in findings)

    def test_naive_approved_at_does_not_crash(self, tmp_path: Path) -> None:
        # approved_at sin offset no debe lanzar TypeError al comparar con mtime aware.
        prompt = _write_prompt(tmp_path)
        receipt = _write_receipt(
            tmp_path, prompt=prompt, approved_at="2026-08-22T20:00:00"
        )
        assert check_seal_staleness(receipt, prompt_path=prompt) == []


class TestHardAnchors:
    def test_status_pending_is_hard(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        receipt = _write_receipt(tmp_path, prompt=prompt, status="PENDING")
        findings = check_seal_staleness(receipt, prompt_path=prompt)
        assert any("status" in f for f in findings)

    def test_missing_scope_is_hard(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        receipt = _write_receipt(tmp_path, prompt=prompt, payload={"scope": None})
        findings = check_seal_staleness(receipt, prompt_path=prompt)
        assert any("scope" in f for f in findings)

    def test_flight_mismatch_is_hard(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        receipt = _write_receipt(tmp_path, prompt=prompt, flight="FP-OTHER-9000")
        findings = check_seal_staleness(
            receipt, prompt_path=prompt, flight_id="FP-TEST-0001"
        )
        assert any("flight" in f for f in findings)

    def test_project_root_mismatch_is_hard(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        receipt = _write_receipt(tmp_path, prompt=prompt)
        findings = check_seal_staleness(
            receipt, prompt_path=prompt, project_root=tmp_path.parent
        )
        assert any("project_root_resolved" in f for f in findings)

    def test_self_approval_is_hard(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        receipt = _write_receipt(tmp_path, prompt=prompt, approved_by="builder")
        findings = check_seal_staleness(receipt, prompt_path=prompt, executor="builder")
        assert any("self-approval" in f for f in findings)


class TestSemanticFreshnessWarn:
    def test_warning_claim_mismatch_is_warn_not_hard(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        prompt = _write_prompt(
            tmp_path, content="# Arranque\nEstado actual: 0 warnings\n"
        )
        receipt = _write_receipt(tmp_path, prompt=prompt)
        monkeypatch.setattr(
            "scripts.check_seal_staleness._measured_validate_counts",
            lambda root: (0, 2),
        )
        findings = check_seal_staleness(
            receipt, prompt_path=prompt, project_root=tmp_path
        )
        warns = [f for f in findings if f.startswith("[WARN]")]
        assert warns, findings
        hard = [f for f in findings if not f.startswith("[WARN]")]
        assert hard == []


class TestCli:
    def test_cli_exit_2_on_usage_error(self) -> None:
        assert main([]) == 2

    def test_cli_exit_1_on_hard_finding(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        receipt = _write_receipt(tmp_path, prompt=prompt, status="PENDING")
        rc = main([str(receipt), "--prompt", str(prompt)])
        assert rc == 1

    def test_cli_exit_0_on_conforming(self, tmp_path: Path) -> None:
        prompt = _write_prompt(tmp_path)
        receipt = _write_receipt(tmp_path, prompt=prompt)
        rc = main([str(receipt), "--prompt", str(prompt)])
        assert rc == 0


class TestPrepushWiring:
    """WOT-2026-055c cableado en prepush: WARN no bloqueante que ve el recibo."""

    def test_wiring_detects_bad_receipt_as_warn(self, tmp_path: Path) -> None:
        from scripts.prepush_check import run_seal_staleness_check

        prompt = _write_prompt(tmp_path)
        reports = tmp_path / "orchestrator_pipeline" / "reports"
        reports.mkdir(parents=True)
        receipt = _write_receipt(
            reports,
            prompt=prompt,
            status="PENDING",
            payload={"project_root_resolved": str(tmp_path)},
        )
        result = run_seal_staleness_check(tmp_path)
        assert result.passed is False
        assert result.is_blocking is False
        assert receipt.name in result.output

    def test_wiring_passes_clean(self, tmp_path: Path) -> None:
        from scripts.prepush_check import run_seal_staleness_check

        prompt = _write_prompt(tmp_path)
        reports = tmp_path / "orchestrator_pipeline" / "reports"
        reports.mkdir(parents=True)
        _write_receipt(
            reports, prompt=prompt, payload={"project_root_resolved": str(tmp_path)}
        )
        result = run_seal_staleness_check(tmp_path)
        assert result.passed is True

    def test_wiring_anchors_the_receipt_against_its_own_batch_run(
        self, tmp_path: Path
    ) -> None:
        """WOT-2026-058s: el cableado debe pasar el ANCLA de pertenencia.

        Medido 2026-08-23 por DOS auditorias independientes: `prepush_check`
        invocaba `check_seal_staleness(receipt, project_root=...)` sin
        `batch_run_path`, asi que la capa de PERTENENCIA quedaba inerte EN
        PRODUCCION -- un recibo de OTRO vuelo pasaba SIN HALLAZGOS. El guard
        mordia en sus tests y no miraba donde ocurre el fallo ("barrera del
        alcance"), justo lo que §4.bis punto 4 declara falso_verde.

        El ancla correcta es el `batch_run` DEL PROPIO recibo (derivable por
        `flight`), nunca un flight ajeno: comparar contra el ancla equivocada es
        el falso positivo que ese mismo punto documenta.
        """
        from scripts.prepush_check import run_seal_staleness_check

        prompt = _write_prompt(tmp_path)
        reports = tmp_path / "orchestrator_pipeline" / "reports"
        reports.mkdir(parents=True)
        receipt = _write_receipt(
            reports,
            prompt=prompt,
            payload={
                "project_root_resolved": str(tmp_path),
                "flight": "FP-EL-MIO",
            },
        )
        # el UNICO batch_run del directorio declara OTRO flight -> recibo ajeno.
        # Su nombre es deliberadamente el del OTRO vuelo: el ancla sale del disco,
        # no del `flight` del recibo (si no, un recibo que miente se auto-exime).
        (reports / "batch_run_FP-OTRO-VUELO.json").write_text(
            json.dumps({"flight": "FP-OTRO-VUELO", "PREDICATE": {}}),
            encoding="utf-8",
        )

        result = run_seal_staleness_check(tmp_path)

        assert result.passed is False, "un recibo ajeno debe dar hallazgo"
        assert receipt.name in result.output
        assert "batch_run" in result.output

    def test_wiring_clean_receipt_with_matching_batch_run_passes(
        self, tmp_path: Path
    ) -> None:
        """Control negativo: mismo montaje, `flight` COINCIDENTE -> sin hallazgo.

        Sin este par, el test de arriba pasaria con un guard que marcase
        cualquier recibo que tenga un `batch_run` al lado.
        """
        from scripts.prepush_check import run_seal_staleness_check

        prompt = _write_prompt(tmp_path)
        reports = tmp_path / "orchestrator_pipeline" / "reports"
        reports.mkdir(parents=True)
        _write_receipt(
            reports,
            prompt=prompt,
            payload={
                "project_root_resolved": str(tmp_path),
                "flight": "FP-EL-MIO",
            },
        )
        (reports / "batch_run_FP-EL-MIO.json").write_text(
            json.dumps({"flight": "FP-EL-MIO", "PREDICATE": {}}),
            encoding="utf-8",
        )

        result = run_seal_staleness_check(tmp_path)
        assert result.passed is True, result.output

    def test_wiring_skips_without_reports_dir(self, tmp_path: Path) -> None:
        from scripts.prepush_check import run_seal_staleness_check

        result = run_seal_staleness_check(tmp_path)
        assert result.passed is True
        assert "(skip)" in result.output

    def test_wiring_detects_executed_prompt_distinct_from_sealed(
        self, tmp_path: Path
    ) -> None:
        """WOT-2026-066z (DoD 1 + DoD 3): el camino automatico emite el
        veredicto de R1.

        Espejo hermetico del par R1/R2 del escalado (ficha F-A2, salida literal
        preservada en arranques/INCIDENT_20260908-ficha-inbox-borrada-con-rm.md):
        recibo que sella A y declara en `prompt_executed_path` el arranque B que
        la sesion REALMENTE ejecuto (bytes distintos, mtime posterior a
        approved_at). R1 (con --prompt) daba 4 hard findings y R2 (sin ella)
        daba `seal fresh`; con el nivel 2 de DEC-066Z-001 el camino AUTOMATICO
        -- que NO pasa prompt_path -- debe emitir el mismo veredicto que R1:
        las 4 clases de hallazgo, sin bloquear (el regimen sigue siendo WARN).
        """
        from scripts.prepush_check import run_seal_staleness_check

        prompt_a = _write_prompt(tmp_path)
        prompt_b = _write_executed_prompt(tmp_path, utime=1800000000)
        reports = tmp_path / "orchestrator_pipeline" / "reports"
        reports.mkdir(parents=True)
        receipt = _write_receipt(
            reports,
            prompt=prompt_a,
            payload={
                "project_root_resolved": str(tmp_path),
                "prompt_executed_path": str(prompt_b),
            },
        )
        result = run_seal_staleness_check(tmp_path)
        assert result.passed is False, result.output
        assert result.is_blocking is False
        assert receipt.name in result.output
        # las 4 clases de hallazgo que R1 emitio con la ancla:
        assert "prompt_sha256" in result.output
        assert prompt_b.name in result.output
        assert prompt_a.name in result.output
        assert "prompt_bytes" in result.output
        assert "prompt_lines" in result.output
        assert "EARLIER" in result.output

    def test_wiring_executed_prompt_equal_to_sealed_passes(
        self, tmp_path: Path
    ) -> None:
        """Control de simetria del DoD 1: A y B = el MISMO fichero -> sin hard."""
        from scripts.prepush_check import run_seal_staleness_check

        prompt = _write_prompt(tmp_path)
        reports = tmp_path / "orchestrator_pipeline" / "reports"
        reports.mkdir(parents=True)
        _write_receipt(
            reports,
            prompt=prompt,
            payload={
                "project_root_resolved": str(tmp_path),
                "prompt_executed_path": str(prompt),
            },
        )
        result = run_seal_staleness_check(tmp_path)
        assert result.passed is True, result.output

    def test_vuelo_sin_batch_run_y_ausencia_de_ancla_no_es_rojo_garantizado(
        self, tmp_path: Path
    ) -> None:
        """WOT-2026-066z (DoD 4): control negativo del camino automatico.

        Un recibo conforme SIN `batch_run` en disco y SIN ancla derivable de
        prompt (ni arg, ni `prompt_executed_path`) NO se convierte en rojo
        garantizado: cae al nivel 3 legacy y esta capa calla. Sin este control,
        el fix cambiaria un falso verde por un falso rojo sistematico.
        """
        from scripts.prepush_check import run_seal_staleness_check

        prompt = _write_prompt(tmp_path)
        reports = tmp_path / "orchestrator_pipeline" / "reports"
        reports.mkdir(parents=True)
        receipt = _write_receipt(
            reports, prompt=prompt, payload={"project_root_resolved": str(tmp_path)}
        )
        assert not list(reports.glob("batch_run_*.json"))
        result = run_seal_staleness_check(tmp_path)
        assert result.passed is True, result.output
        assert "hard" not in result.output
        assert receipt.name not in result.output
