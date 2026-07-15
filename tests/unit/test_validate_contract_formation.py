#!/usr/bin/env python
"""
Tests for scripts/validate_contract_formation.py.

Before: Requires scripts/validate_contract_formation.py and fixture files
        in tests/fixtures/contract_formation/{valid,invalid}/.
During: Runs each validation function against known-good and known-bad fixtures.
After: Reports pass/fail per test case.
"""

from pathlib import Path

from scripts.validate_contract_formation import (
    VResult,
    _detect,
    validate_contract_gap,
    validate_plan_graph,
    validate_repo_charter,
    validate_ticket_contracts,
)


FIXTURES = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "contract_formation"
)
VALID = FIXTURES / "valid"
INVALID = FIXTURES / "invalid"


# ===========================================================================
# _detect helper
# ===========================================================================


class TestDetect:
    def test_charter_by_filename(self):
        assert _detect(str(VALID / "repo_charter.md")) == "charter"

    def test_plan_graph_by_filename(self):
        assert _detect(str(VALID / "plan_graph.md")) == "plan_graph"

    def test_ticket_contracts_by_filename(self):
        assert _detect(str(VALID / "ticket_contracts.md")) == "ticket_contracts"

    def test_unknown_filename(self) -> None:
        """Files without a recognised name or content fall back to unknown."""
        t = FIXTURES / "valid"
        # The content-heuristic fallback matches `repo_charter.md` because
        # it contains "Product Intent" and "OBJ-", so create a synthetic
        # path that has neither hint in its name.
        p = t / "readme.md"
        if not p.exists():
            p.write_text("Not a contract artifact.")
        assert _detect(str(p)) == "unknown"
        p.unlink()


# ===========================================================================
# repo_charter
# ===========================================================================


class TestValidateRepoCharter:
    def test_valid_charter_passes(self):
        res = VResult()
        validate_repo_charter(str(VALID / "repo_charter.md"), res)
        assert res.ok, f"Valid charter should pass, got {len(res.errors)} errors"

    def test_invalid_charter_fails(self):
        res = VResult()
        validate_repo_charter(
            str(INVALID / "repo_charter_missing_failure_modes.md"), res
        )
        assert not res.ok, "Invalid charter should fail"
        errors_by_field = {e.field_: e.reason for e in res.errors}
        assert any("failure_modes" in k for k in errors_by_field), (
            "Should report missing failure_modes"
        )

    def test_invalid_reports_both_failure_modes_and_checklist(self):
        res = VResult()
        validate_repo_charter(
            str(INVALID / "repo_charter_missing_failure_modes.md"), res
        )
        fields = [e.field_ for e in res.errors]
        assert any("OBJ-001" in f for f in fields), "Should mention OBJ-001"
        assert any("Non-Goals" in f for f in fields), "Should mention Non-Goals"
        assert any("Negative Audit Checklist" in f for f in fields), (
            "Should mention Negative Audit Checklist"
        )

    def test_error_format_includes_file_and_revalidate(self):
        res = VResult()
        validate_repo_charter(
            str(INVALID / "repo_charter_missing_failure_modes.md"), res
        )
        for err in res.errors:
            rendered = err.render()
            assert "ERROR | file=" in rendered
            assert (
                "revalidate: python scripts/validate_contract_formation.py" in rendered
            )


# ===========================================================================
# plan_graph
# ===========================================================================


class TestValidatePlanGraph:
    def test_valid_plan_graph_passes(self):
        res = VResult()
        validate_plan_graph(str(VALID / "plan_graph.md"), res)
        assert res.ok, f"Valid plan_graph should pass, got {len(res.errors)} errors"

    def test_missing_impact_simulation_fails(self):
        res = VResult()
        content = (
            "## PLAN-001 -- Example\n\nNo impact simulation here.\n"
            "--shared_dependencies: none\n"
        )
        f = FIXTURES / "invalid" / "tmp_no_impact.md"
        f.write_text(content)
        validate_plan_graph(str(f), res)
        assert not res.ok
        fields = [e.field_ for e in res.errors]
        assert any("Impact Simulation" in ff for ff in fields)
        f.unlink()

    def test_missing_plan_blocks_fails(self):
        res = VResult()
        content = "# Not a plan graph\n\nNo PLAN- blocks at all.\n"
        f = FIXTURES / "invalid" / "tmp_no_plan_blocks.md"
        f.write_text(content)
        validate_plan_graph(str(f), res)
        assert not res.ok
        fields = [e.field_ for e in res.errors]
        assert any("PLAN-*" in ff for ff in fields)
        f.unlink()

    def test_error_mentions_shared_dependencies(self):
        res = VResult()
        f = FIXTURES / "invalid" / "tmp_no_shared.md"
        f.write_text("## PLAN-001 -- Solo\n\nNo common dependencies clause.\n")
        validate_plan_graph(str(f), res)
        assert not res.ok
        fields = [e.field_ for e in res.errors]
        assert any("shared_dependencies" in ff for ff in fields)
        f.unlink()

    # ---- WOT-2026-007g: paralelizable strict validation ----

    def test_invalid_paralelizable_free_text_fails(self, tmp_path):
        """'no -- unico plan' concatenated to the value is rejected."""
        content = (
            "## PLAN-001 -- Example\n\n"
            "## Impact Simulation\n\n"
            "| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable |\n"
            "|------|-------------|------------|--------------------|-------------|---------------|\n"
            "| PLAN-001 | a.py | none | ninguno | serializar | no -- unico plan |\n"
            "\n"
            "## Merge Regression Audit\n\nN/A\n"
        )
        f = tmp_path / "paralelizable_free_text.md"
        f.write_text(content, encoding="utf-8")
        res = VResult()
        validate_plan_graph(str(f), res)
        assert not res.ok
        fields = [(e.field_, e.reason) for e in res.errors]
        assert any("paralelizable" in fld for fld, _ in fields), (
            "Should report invalid paralelizable value"
        )
        reasons = [r for _, r in fields if "paralelizable" in _]
        assert any("no -- unico plan" in r for r in reasons), (
            "Error must mention the invalid value"
        )

    def test_valid_paralelizable_yes_passes(self, tmp_path):
        content = (
            "## PLAN-001 -- Example\n\n"
            "## Impact Simulation\n\n"
            "| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable |\n"
            "|------|-------------|------------|--------------------|-------------|---------------|\n"
            "| PLAN-001 | a.py | none | ninguno | serializar | yes |\n"
            "\n"
            "## Merge Regression Audit\n\nN/A\n"
        )
        f = tmp_path / "paralelizable_yes.md"
        f.write_text(content, encoding="utf-8")
        res = VResult()
        validate_plan_graph(str(f), res)
        paralelizable_errors = [e for e in res.errors if "paralelizable" in e.field_]
        assert len(paralelizable_errors) == 0, (
            f"yes should be valid, got: {paralelizable_errors}"
        )

    def test_valid_paralelizable_no_passes(self, tmp_path):
        content = (
            "## PLAN-001 -- Example\n\n"
            "## Impact Simulation\n\n"
            "| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable |\n"
            "|------|-------------|------------|--------------------|-------------|---------------|\n"
            "| PLAN-001 | a.py | none | ninguno | serializar | no |\n"
            "\n"
            "## Merge Regression Audit\n\nN/A\n"
        )
        f = tmp_path / "paralelizable_no.md"
        f.write_text(content, encoding="utf-8")
        res = VResult()
        validate_plan_graph(str(f), res)
        paralelizable_errors = [e for e in res.errors if "paralelizable" in e.field_]
        assert len(paralelizable_errors) == 0

    def test_valid_paralelizable_after_plan_passes(self, tmp_path):
        content = (
            "## PLAN-001 -- Example\n\n"
            "## PLAN-002 -- Dep\n\n"
            "## Impact Simulation\n\n"
            "| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable |\n"
            "|------|-------------|------------|--------------------|-------------|---------------|\n"
            "| PLAN-001 | a.py | none | ninguno | serializar | yes |\n"
            "| PLAN-002 | b.py | none | lock conflict | wait | after PLAN-001 |\n"
            "\n"
            "## Merge Regression Audit\n\nN/A\n"
        )
        f = tmp_path / "paralelizable_after_plan.md"
        f.write_text(content, encoding="utf-8")
        res = VResult()
        validate_plan_graph(str(f), res)
        paralelizable_errors = [e for e in res.errors if "paralelizable" in e.field_]
        assert len(paralelizable_errors) == 0, (
            f"after PLAN-001 should be valid, got: {paralelizable_errors}"
        )

    def test_valid_paralelizable_after_plan_002_passes(self, tmp_path):
        content = (
            "## PLAN-001 -- First\n\n"
            "## PLAN-002 -- Second\n\n"
            "## Impact Simulation\n\n"
            "| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable |\n"
            "|------|-------------|------------|--------------------|-------------|---------------|\n"
            "| PLAN-001 | a.py | none | ninguno | serializar | yes |\n"
            "| PLAN-002 | b.py | none | lock conflict | wait | after PLAN-002 |\n"
            "\n"
            "## Merge Regression Audit\n\nN/A\n"
        )
        f = tmp_path / "paralelizable_after_plan_002.md"
        f.write_text(content, encoding="utf-8")
        res = VResult()
        validate_plan_graph(str(f), res)
        paralelizable_errors = [e for e in res.errors if "paralelizable" in e.field_]
        assert len(paralelizable_errors) == 0

    def test_paralelizable_with_parallelism_notes_column_passes(self, tmp_path):
        """parallelism_notes as a separate column must not interfere with
        Paralelizable validation (WOT-2026-007g review, MEDIUM blocker)."""
        content = (
            "## PLAN-001 -- First\n\n"
            "## PLAN-002 -- Second\n\n"
            "## Impact Simulation\n\n"
            "| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable | parallelism_notes |\n"
            "|------|-------------|------------|--------------------|-------------|---------------|-------------------|\n"
            "| PLAN-001 | a.py | none | ninguno | serializar | yes | unico plan |\n"
            "| PLAN-002 | b.py | none | lock conflict | wait | after PLAN-001 | depende de PLAN-001 |\n"
            "\n"
            "## Merge Regression Audit\n\nN/A\n"
        )
        f = tmp_path / "parallelism_notes_col.md"
        f.write_text(content, encoding="utf-8")
        res = VResult()
        validate_plan_graph(str(f), res)
        paralelizable_errors = [e for e in res.errors if "paralelizable" in e.field_]
        assert len(paralelizable_errors) == 0, (
            f"parallelism_notes column must not cause false positives, "
            f"got: {paralelizable_errors}"
        )

    # ---- WOT-2026-007g: Merge Regression Audit ----

    def test_missing_merge_regression_audit_fails(self, tmp_path):
        content = (
            "## PLAN-001 -- Example\n\n"
            "## Impact Simulation\n\n"
            "| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable |\n"
            "|------|-------------|------------|--------------------|-------------|---------------|\n"
            "| PLAN-001 | a.py | none | ninguno | serializar | no |\n"
            "\n"
            "## Forbidden Surfaces\n\nN/A\n"
        )
        f = tmp_path / "no_merge_audit.md"
        f.write_text(content, encoding="utf-8")
        res = VResult()
        validate_plan_graph(str(f), res)
        assert not res.ok
        fields = [e.field_ for e in res.errors]
        assert any("Merge Regression Audit" in ff for ff in fields), (
            "Should report missing Merge Regression Audit section"
        )


# ===========================================================================
# ticket_contracts
# ===========================================================================


class TestValidateTicketContracts:
    def test_valid_ticket_contracts_passes(self):
        res = VResult()
        validate_ticket_contracts(str(VALID / "ticket_contracts.md"), res)
        assert res.ok, (
            f"Valid ticket_contracts should pass, got {len(res.errors)} errors"
        )

    def test_invalid_ticket_contracts_fails(self):
        res = VResult()
        validate_ticket_contracts(
            str(INVALID / "ticket_contracts_missing_fields.md"), res
        )
        assert not res.ok, "Invalid ticket_contracts should fail"

    def test_error_mentions_missing_status(self):
        res = VResult()
        validate_ticket_contracts(
            str(INVALID / "ticket_contracts_missing_fields.md"), res
        )
        fields = [e.field_ for e in res.errors]
        assert any("status" in f for f in fields), "Should report missing status"

    def test_error_mentions_forbidden_surfaces(self):
        res = VResult()
        validate_ticket_contracts(
            str(INVALID / "ticket_contracts_missing_fields.md"), res
        )
        fields = [e.field_ for e in res.errors]
        assert any("Forbidden Surfaces" in f for f in fields)

    def test_error_mentions_stop_conditions(self):
        res = VResult()
        validate_ticket_contracts(
            str(INVALID / "ticket_contracts_missing_fields.md"), res
        )
        fields = [e.field_ for e in res.errors]
        assert any("STOP conditions" in f for f in fields)

    def test_error_mentions_contract_gap_behavior(self):
        res = VResult()
        validate_ticket_contracts(
            str(INVALID / "ticket_contracts_missing_fields.md"), res
        )
        fields = [e.field_ for e in res.errors]
        assert any("CONTRACT_GAP" in f for f in fields)


# ===========================================================================
# contract_gap
# ===========================================================================


class TestValidateContractGap:
    def test_valid_gap_passes(self):
        res = VResult()
        content = (
            "- **ticket_id:** T-001\n"
            "- **gap_type:** premise_false\n"
            "- **description:** something\n"
            "- **evidence:** log output\n"
            "- **requested_resolution:** reopen\n"
        )
        f = FIXTURES / "invalid" / "tmp_gap_valid.md"
        f.write_text(content)
        validate_contract_gap(str(f), res)
        assert res.ok, f"Valid gap should pass, got {len(res.errors)} errors"
        f.unlink()

    def test_invalid_gap_fails(self):
        res = VResult()
        content = "# CG-001\n\nMissing all required fields.\n"
        f = FIXTURES / "invalid" / "tmp_gap_invalid.md"
        f.write_text(content)
        validate_contract_gap(str(f), res)
        assert not res.ok
        f.unlink()

    def test_gap_errors_include_field_name(self):
        res = VResult()
        content = "# CG-001\n\nMissing all fields.\n"
        f = FIXTURES / "invalid" / "tmp_gap_errors.md"
        f.write_text(content)
        validate_contract_gap(str(f), res)
        field_names = {e.field_ for e in res.errors}
        assert "ticket_id" in field_names
        assert "gap_type" in field_names
        f.unlink()


# ===========================================================================
# main() CLI
# ===========================================================================


class TestMainCLI:
    def test_cli_valid_files_exit_zero(self):
        from scripts.validate_contract_formation import main

        rc = main(
            [
                "--charter",
                str(VALID / "repo_charter.md"),
                "--plan",
                str(VALID / "plan_graph.md"),
                "--tickets",
                str(VALID / "ticket_contracts.md"),
            ]
        )
        assert rc == 0, "CLI with valid files should exit 0"

    def test_cli_invalid_files_exit_one(self):
        from scripts.validate_contract_formation import main

        rc = main(
            [
                "--charter",
                str(INVALID / "repo_charter_missing_failure_modes.md"),
                "--tickets",
                str(INVALID / "ticket_contracts_missing_fields.md"),
            ]
        )
        assert rc == 1, "CLI with invalid files should exit 1"

    def test_cli_no_args_prints_help(self):
        from scripts.validate_contract_formation import main

        rc = main([])
        assert rc == 0, "No args should print help and exit 0"

    def test_cli_missing_file_reports_error(self):
        from scripts.validate_contract_formation import main

        rc = main(["--charter", "/nonexistent/path.md"])
        assert rc == 1, "Missing file should exit 1"

    def test_cli_auto_detect_from_file_args(self):
        from scripts.validate_contract_formation import main

        rc = main(
            [
                str(VALID / "repo_charter.md"),
                str(VALID / "plan_graph.md"),
                str(VALID / "ticket_contracts.md"),
            ]
        )
        assert rc == 0, "Auto-detect should work for valid files"

    def test_cli_gap_good(self):
        from scripts.validate_contract_formation import main

        content = "- **ticket_id:** T-001\n- **gap_type:** premise_false\n- **description:** x\n- **evidence:** y\n- **requested_resolution:** z\n"
        f = FIXTURES / "invalid" / "tmp_gap_cli.md"
        f.write_text(content)
        rc = main(["--gap", str(f)])
        assert rc == 0
        f.unlink()

    def test_cli_gap_bad(self):
        from scripts.validate_contract_formation import main

        f = FIXTURES / "invalid" / "tmp_gap_cli_bad.md"
        f.write_text("# only\n")
        rc = main(["--gap", str(f)])
        assert rc == 1
        f.unlink()

    def test_revalidate_command_in_error_output(self, capsys):
        """Every error includes the revalidate command for self-service gates."""
        from scripts.validate_contract_formation import main

        main(
            [
                "--tickets",
                str(INVALID / "ticket_contracts_missing_fields.md"),
            ]
        )
        captured = capsys.readouterr()
        assert (
            "revalidate: python scripts/validate_contract_formation.py" in captured.out
        )


# ===========================================================================
# Canonical template regression + new required fields
# (WOT-2026-007c independent review follow-up)
# ===========================================================================

TEMPLATES = (
    Path(__file__).resolve().parents[2] / "docs" / "contract_formation" / "templates"
)

_COMPLETE_TICKET_LINES = [
    "## T-OK-001 -- complete contract",
    "- **status:** frozen",
    "- **Objective-Link:** OBJ-001",
    "- **Plan-Link:** PLAN-001",
    "- **Premise:** the repo is in a known state",
    "- **Premise Re-check (read-only):** run a read-only command",
    "- **Context Baseline Evidence:** git_head, validate_result, generated_at",
    "- **Forbidden Surfaces:** no extra surfaces",
    "- **DoD:** ruff passes and tests are green",
    "- **STOP conditions:** stop and escalate if blocked",
    "- **CONTRACT_GAP behavior:** emit CG file and block",
    "- **Builder clarification budget:** 0",
]
_COMPLETE_TICKET = chr(10).join(_COMPLETE_TICKET_LINES) + chr(10)


class TestCanonicalTemplates:
    """The validator must not reject the canonical templates the motor publishes.

    This is the regression barrier requested in the WOT-2026-007c review: if a
    template field is renamed (e.g. requested_resolution -> action) or the
    validator drifts away from the published contract, these tests break.
    """

    def test_charter_template_passes(self):
        res = VResult()
        validate_repo_charter(str(TEMPLATES / "repo_charter.md"), res)
        assert res.ok, (
            f"charter template must pass, got {[e.field_ for e in res.errors]}"
        )

    def test_gap_template_passes(self):
        res = VResult()
        validate_contract_gap(str(TEMPLATES / "contract_gap.md"), res)
        assert res.ok, f"gap template must pass, got {[e.field_ for e in res.errors]}"

    def test_ticket_template_passes(self):
        res = VResult()
        validate_ticket_contracts(str(TEMPLATES / "ticket_contract.md"), res)
        assert res.ok, (
            f"ticket template must pass, got {[e.field_ for e in res.errors]}"
        )

    def test_gap_template_uses_requested_resolution(self):
        text = (TEMPLATES / "contract_gap.md").read_text(encoding="utf-8")
        assert "requested_resolution" in text, (
            "canonical gap template field drifted; validator GAP_REQUIRED must follow"
        )

    def test_plan_graph_template_passes(self):
        """The canonical plan_graph template must pass the updated validator
        (WOT-2026-007g: paralelizable strict values + Merge Regression Audit)."""
        res = VResult()
        validate_plan_graph(str(TEMPLATES / "plan_graph.md"), res)
        assert res.ok, (
            f"plan_graph template must pass, got {[e.field_ for e in res.errors]}"
        )


class TestNewRequiredTicketFields:
    """Premise Re-check and Context Baseline are DoD-required per WOT-2026-007c.

    A barrier test: an otherwise-complete contract that drops one of these fields
    must fail. Without the field in TICKET_REQUIRED, these tests would not fail.
    """

    def _write(self, tmp_path, content):
        f = tmp_path / "ticket.md"
        f.write_text(content, encoding="utf-8")
        return f

    def test_complete_ticket_passes(self, tmp_path):
        res = VResult()
        f = self._write(tmp_path, _COMPLETE_TICKET)
        validate_ticket_contracts(str(f), res)
        assert res.ok, (
            f"complete ticket must pass, got {[e.field_ for e in res.errors]}"
        )

    def test_missing_premise_recheck_fails(self, tmp_path):
        content = _COMPLETE_TICKET.replace(
            "- **Premise Re-check (read-only):** run a read-only command", ""
        )
        res = VResult()
        f = self._write(tmp_path, content)
        validate_ticket_contracts(str(f), res)
        assert any("Premise Re-check" in e.field_ for e in res.errors), (
            "must report missing Premise Re-check"
        )

    def test_missing_context_baseline_fails(self, tmp_path):
        content = _COMPLETE_TICKET.replace(
            "- **Context Baseline Evidence:** git_head, validate_result, generated_at",
            "",
        )
        res = VResult()
        f = self._write(tmp_path, content)
        validate_ticket_contracts(str(f), res)
        assert any("Context Baseline" in e.field_ for e in res.errors), (
            "must report missing Context Baseline"
        )


# ===========================================================================
# Vocabulario de estados terminales (WOT: cierre de sesion 2026-07-15)
# El validador NO mantiene su propia lista de terminales: la deriva de la UNICA
# autoridad bus/state_machine.py. Un contrato terminal se exime del checklist de
# campos-vivos pero exige traza de cierre.
# ===========================================================================


class TestTerminalStatusVocabulary:
    def _block(self, tid: str, status: str, *, extra: str = "") -> str:
        # bloque MINIMO: solo ticket_id + status (+ extra). Sin campos-vivos.
        return f"## {tid}\n\n- **ticket_id:** {tid}\n- **status:** {status}\n{extra}"

    def _run(self, block: str):
        from scripts.validate_contract_formation import _chk_ticket

        res = VResult()
        _chk_ticket(block, "T-X-001", "f.md", res)
        return [e.field_ for e in res.errors]

    def test_terminal_vocab_comes_from_authority(self):
        # El conjunto terminal del validador == la autoridad, no una lista propia.
        from bus.state_machine import terminal_state_strings
        from scripts.validate_contract_formation import STATUS_TERMINAL

        for s in terminal_state_strings(include_legacy=True):
            assert s.lower() in STATUS_TERMINAL, f"{s} deberia ser terminal"
        # los tres honestos y el legacy
        assert {"completed", "superseded", "blocked_final", "closed"} <= STATUS_TERMINAL

    def test_terminal_with_evidence_is_exempt_from_live_fields(self):
        # completed + Evidence -> NO exige Premise/DoD/etc (contrato cerrado).
        block = self._block(
            "T-X-001", "completed", extra="- **Evidence:** commit:abc1234"
        )
        assert self._run(block) == [], (
            "un terminal con traza no debe exigir campos-vivos"
        )

    def test_terminal_without_trace_fails(self):
        # completed SIN closed:/Evidence: -> closure_trace (no dejar huerfanos).
        block = self._block("T-X-001", "completed")
        fields = self._run(block)
        assert any("closure_trace" in f for f in fields), fields

    def test_superseded_and_blocked_final_accepted(self):
        for st in ("superseded", "blocked-final", "blocked_final"):
            block = self._block("T-X-001", st, extra="- **closed:** 2026-06-21")
            assert self._run(block) == [], (
                f"{st} deberia ser un terminal valido con traza"
            )

    def test_live_status_still_requires_full_checklist(self):
        # frozen (vivo) sin campos -> exige el checklist completo (regresion guard).
        block = self._block("T-X-001", "frozen")
        fields = self._run(block)
        assert any("Premise" in f for f in fields)
        assert any("DoD" in f for f in fields)

    def test_missing_status_still_requires_checklist(self):
        # sin status NO es un cierre legitimo -> sigue exigiendo campos (el bug que
        # el refactor introdujo y este test bloquea).
        block = "## T-X-001\n\n- **ticket_id:** T-X-001\n- **Objective-Link:** OBJ-1\n"
        fields = self._run(block)
        assert any("status" in f for f in fields)
        assert any("DoD" in f for f in fields), "sin status debe seguir pidiendo DoD"

    def test_unknown_status_rejected(self):
        block = self._block("T-X-001", "absorbed", extra="- **Evidence:** x")
        fields = self._run(block)
        assert any("status" in f for f in fields), (
            "un estado fuera de vocabulario falla"
        )
