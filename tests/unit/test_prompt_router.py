"""Hermetic tests for the phase router of prompts (DEC-router-prompts-001, Plan B).

The router is a GENERATED projection (DEC-008B-001): each prompt declares its
routing metadata in frontmatter (`role`, `cycle_phase`, `route_kind`) plus the
WOT-2026-022o `PROMPT-SUMMARY` block; `discover_skills.py --generate-index`
renders `docs/registry/ROUTER.md` and `--check-index` fails when it drifts.

Every check here goes through the SAME functions production uses
(`read_prompt_parts`, `validate_route_metadata`, `module_citations`,
`build_router`): a mutation only counts if it crosses the production parser.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from scripts.discover_skills import (
    CYCLE_PHASES,
    EXTERNAL_ALLOWLIST,
    PHASE_LOOP_PARAMS,
    ROUTER_REL_PATH,
    ROUTE_KINDS,
    build_catalog,
    build_router,
    check_naming,
    check_router_stale,
    generate_router,
    module_citations,
    parse_frontmatter,
    prompt_summary,
    read_prompt_parts,
    router_metadata_errors,
    validate_route_metadata,
)


SUMMARY = "<!-- PROMPT-SUMMARY\nwhat: {what}\nwhen: {when}\nnot: {not_}\n-->\n"


def _prompt(
    fm: dict[str, str] | None, title: str, body: str = "", *, what: str = "w"
) -> str:
    """Build a prompt text with optional frontmatter, H1 and PROMPT-SUMMARY."""
    head = ""
    if fm is not None:
        head = "---\n" + "".join(f"{k}: {v}\n" for k, v in fm.items()) + "---\n"
    summary = SUMMARY.format(what=what, when="cuando", not_="no es X")
    return f"{head}# {title}\n{summary}\n{body}"


def _seed(root: Path, files: dict[str, str], agents: str = "") -> Path:
    """Create a minimal motor tree with prompts/, prompts/_shared/ and AGENTS.md."""
    (root / "prompts" / "_shared").mkdir(parents=True)
    (root / "skills").mkdir()
    for rel, text in files.items():
        path = root / "prompts" / rel
        path.write_text(text, encoding="utf-8")
    (root / "AGENTS.md").write_text(agents, encoding="utf-8")
    return root


class TestReadPromptParts:
    """`read_prompt_parts` is the single frontmatter cut shared by parser and test (T5)."""

    def test_offset_counts_the_frontmatter_lines(self, tmp_path):
        p = tmp_path / "x.md"
        p.write_text(
            "---\nrole: manager\nroute_kind: entry\n---\n# T\nbody\n", encoding="utf-8"
        )
        fm, error, body, offset = read_prompt_parts(p)
        assert error is None
        assert fm == {"role": "manager", "route_kind": "entry"}
        assert offset == 4
        assert body.splitlines()[0] == "# T"

    def test_no_frontmatter_has_zero_offset_and_full_body(self, tmp_path):
        p = tmp_path / "x.md"
        p.write_text("# T\n---\nrole: x\n---\n", encoding="utf-8")
        fm, error, body, offset = read_prompt_parts(p)
        assert error == "NO_FRONTMATTER"
        assert fm == {}
        assert offset == 0
        assert body.startswith("# T")

    def test_parse_frontmatter_is_unchanged_by_the_delegation(self, tmp_path):
        p = tmp_path / "x.md"
        p.write_text("---\nlegacy_aliases: [a, b]\n---\n# T\n", encoding="utf-8")
        assert parse_frontmatter(p) == ({"legacy_aliases": ["a", "b"]}, None)
        q = tmp_path / "y.md"
        q.write_text("# T\n", encoding="utf-8")
        assert parse_frontmatter(q) == ({}, "NO_FRONTMATTER")


class TestPromptSummaryWindow:
    """T5: the block must close within 12 lines AFTER the frontmatter (boundary)."""

    @staticmethod
    def _body_with_block_ending_at(line_no: int) -> str:
        # H1 + filler so that the closing "-->" lands on body line `line_no` (1-based).
        filler = ["filler"] * (line_no - 6)
        lines = [
            "# T",
            *filler,
            "<!-- PROMPT-SUMMARY",
            "what: w",
            "when: c",
            "not: n",
            "-->",
        ]
        return "\n".join(lines) + "\n"

    def test_block_closing_on_relative_line_12_is_found(self):
        assert prompt_summary(self._body_with_block_ending_at(12)) == {
            "what": "w",
            "when": "c",
            "not": "n",
        }

    def test_block_closing_on_relative_line_13_is_rejected(self):
        assert prompt_summary(self._body_with_block_ending_at(13)) == {}

    def test_window_is_relative_to_the_frontmatter_end(self, tmp_path):
        p = tmp_path / "x.md"
        fm = "---\n" + "".join(f"k{i}: v\n" for i in range(6)) + "---\n"
        p.write_text(fm + self._body_with_block_ending_at(12), encoding="utf-8")
        _, _, body, offset = read_prompt_parts(p)
        assert offset == 8
        assert prompt_summary(body)["what"] == "w"


class TestValidateRouteMetadata:
    """T2-T4 and T6, all through `validate_route_metadata`."""

    GOOD_ENTRY: ClassVar[dict[str, Any]] = {
        "role": "manager",
        "cycle_phase": ["F6-revision"],
        "route_kind": "entry",
    }

    def test_valid_entry_has_no_errors(self):
        assert validate_route_metadata("x.md", dict(self.GOOD_ENTRY)) == []

    def test_unknown_route_kind_is_rejected(self):
        fm = dict(self.GOOD_ENTRY, route_kind="entrada")
        assert any("route_kind" in e for e in validate_route_metadata("x.md", fm))

    def test_missing_route_kind_is_rejected(self):
        fm = {"role": "manager", "cycle_phase": ["F6-revision"]}
        assert any("route_kind" in e for e in validate_route_metadata("x.md", fm))

    def test_role_as_list_is_rejected(self):
        fm = dict(self.GOOD_ENTRY, role=["manager"])
        assert any("role" in e for e in validate_route_metadata("x.md", fm))

    def test_backend_as_role_is_rejected(self):
        fm = dict(self.GOOD_ENTRY, role="codex")
        assert any("role" in e for e in validate_route_metadata("x.md", fm))

    def test_unknown_cycle_phase_is_rejected(self):
        fm = dict(self.GOOD_ENTRY, cycle_phase=["F9-x"])
        assert any("cycle_phase" in e for e in validate_route_metadata("x.md", fm))

    def test_entry_without_cycle_phase_is_rejected(self):
        fm = {"role": "manager", "route_kind": "entry"}
        assert any("cycle_phase" in e for e in validate_route_metadata("x.md", fm))

    def test_entry_without_role_is_rejected(self):
        fm = {"cycle_phase": ["F6-revision"], "route_kind": "entry"}
        assert any("role" in e for e in validate_route_metadata("x.md", fm))

    def test_modulo_with_cycle_phase_is_rejected(self):
        fm = {"route_kind": "modulo", "cycle_phase": ["F6-revision"]}
        assert any("cycle_phase" in e for e in validate_route_metadata("m.md", fm))

    def test_modulo_without_role_is_valid(self):
        assert validate_route_metadata("m.md", {"route_kind": "modulo"}) == []

    def test_mantenimiento_with_cycle_phase_is_rejected(self):
        fm = {
            "role": "orchestrator",
            "route_kind": "mantenimiento",
            "cycle_phase": ["F1-backlog"],
        }
        assert any("cycle_phase" in e for e in validate_route_metadata("x.md", fm))

    def test_externo_outside_the_allowlist_is_rejected(self):
        errors = validate_route_metadata("other.md", {"route_kind": "externo"})
        assert any("externo" in e for e in errors)

    def test_externo_allowlist_is_exactly_hermes_soul(self):
        assert frozenset({"hermes_soul.md"}) == EXTERNAL_ALLOWLIST


class TestModuleCitations:
    """T9 boundary cases of the executable definition of a citation (DEC D4)."""

    def test_path_counts_bare_word_does_not_and_self_does_not(self, tmp_path):
        root = _seed(
            tmp_path,
            {
                "a.md": "lee `prompts/_shared/m.md` entero\n",
                "b.md": "el gate m es importante, y tambien xm.md\n",
                "_shared/m.md": "# m\nme cito: `_shared/m.md`\n",
            },
            agents="ver `_shared/m.md`\n",
        )
        cited = module_citations(root / "prompts" / "_shared" / "m.md", root)
        assert cited == ["AGENTS.md", "a.md"]

    def test_bare_filename_token_counts(self, tmp_path):
        root = _seed(
            tmp_path,
            {"a.md": "ver `m.md` y skills/_shared/m.md\n", "_shared/m.md": "# m\n"},
        )
        assert module_citations(root / "prompts" / "_shared" / "m.md", root) == ["a.md"]

    def test_skills_shared_path_does_not_count(self, tmp_path):
        root = _seed(
            tmp_path, {"a.md": "skills/_shared/m.md\n", "_shared/m.md": "# m\n"}
        )
        assert module_citations(root / "prompts" / "_shared" / "m.md", root) == []

    def test_mention_inside_a_prompt_summary_block_does_not_count(self, tmp_path):
        # A `not:` line says "this is NOT m": routing metadata, not a citation.
        root = _seed(
            tmp_path,
            {
                "a.md": _prompt(None, "A").replace(
                    "not: no es X", "not: NO es `_shared/m.md`"
                ),
                "_shared/m.md": "# m\n",
            },
        )
        assert module_citations(root / "prompts" / "_shared" / "m.md", root) == []

    def test_top_level_module_with_motor_prefix_counts(self, tmp_path):
        root = _seed(
            tmp_path, {"a.md": "<MOTOR>/prompts/mod.md\n", "mod.md": "# mod\n"}
        )
        assert module_citations(root / "prompts" / "mod.md", root) == ["a.md"]

    @pytest.mark.parametrize(
        "text",
        ["ver foo.m.md\n", "ver m.md.bak\n", "ver m.mdx\n"],
        ids=["inside-another-name", "longer-extension", "longer-suffix"],
    )
    def test_other_files_that_contain_the_name_do_not_count(self, tmp_path, text):
        # Review round (Codex BA05 / groq BA31): the token needs both boundaries.
        root = _seed(tmp_path, {"a.md": text, "_shared/m.md": "# m\n"})
        assert module_citations(root / "prompts" / "_shared" / "m.md", root) == []

    def test_end_of_sentence_dot_still_counts(self, tmp_path):
        root = _seed(tmp_path, {"a.md": "ver m.md.\n", "_shared/m.md": "# m\n"})
        assert module_citations(root / "prompts" / "_shared" / "m.md", root) == ["a.md"]

    def test_windows_separators_follow_the_same_rules(self, tmp_path):
        back = chr(92)
        root = _seed(
            tmp_path,
            {
                "a.md": f"ver prompts{back}_shared{back}m.md\n",
                "b.md": f"ver skills{back}_shared{back}m.md\n",
                "_shared/m.md": "# m\n",
            },
        )
        assert module_citations(root / "prompts" / "_shared" / "m.md", root) == ["a.md"]

    def test_unclosed_summary_block_does_not_hide_a_real_citation(self, tmp_path):
        # Review round: a block without "-->" in its window strips nothing.
        text = (
            "<!-- PROMPT-SUMMARY\nwhat: w\n\nlee `_shared/m.md` entero\n<!-- otro -->\n"
        )
        root = _seed(tmp_path, {"a.md": text, "_shared/m.md": "# m\n"})
        assert module_citations(root / "prompts" / "_shared" / "m.md", root) == ["a.md"]


class TestEmptyCyclePhaseList:
    """`cycle_phase: []` parses as [""]: it must mean "absent", not an odd value."""

    def test_empty_list_on_an_entry_reports_the_obligation(self):
        errors = validate_route_metadata(
            "e.md", {"role": "manager", "route_kind": "entry", "cycle_phase": [""]}
        )
        assert errors == ["e.md: cycle_phase obligatoria para route_kind entry"]

    def test_empty_list_on_a_modulo_is_absent(self):
        assert (
            validate_route_metadata(
                "m.md", {"route_kind": "modulo", "cycle_phase": [""]}
            )
            == []
        )


class TestRouterMetadataGate:
    """Review round (Codex BA05): invalid metadata must not reach ROUTER.md silently."""

    def test_invalid_metadata_of_any_routed_file_is_reported(self, tmp_path):
        root = _seed(
            tmp_path,
            {
                "a.md": _prompt({"role": "codex", "route_kind": "entry"}, "A"),
                "b.md": "# no adoptado\n",
            },
        )
        errors = router_metadata_errors(root)
        assert any("a.md" in e and "role" in e for e in errors)
        assert any("a.md" in e and "cycle_phase" in e for e in errors)
        assert not any("b.md" in e for e in errors)

    def test_valid_tree_has_no_metadata_errors(self, tmp_path):
        root = _seed(
            tmp_path,
            {
                "a.md": _prompt(
                    {
                        "role": "manager",
                        "cycle_phase": "[F6-revision]",
                        "route_kind": "entry",
                    },
                    "A",
                )
            },
        )
        assert router_metadata_errors(root) == []

    def test_a_modulo_without_citations_is_reported(self, tmp_path):
        root = _seed(tmp_path, {"_shared/m.md": _prompt({"route_kind": "modulo"}, "M")})
        assert any(
            "_shared/m.md" in e and "cita" in e for e in router_metadata_errors(root)
        )


class TestPhaseLoopParams:
    """T7: loop defaults validated against the dispatcher's own vocabularies."""

    def test_task_types_and_governance_phases_exist_in_the_dispatcher(self):
        from scripts.ensemble_dispatch import GOVERNMENT_PHASES, TASK_TYPES

        governance = {p.lower().replace("-", "_") for p in GOVERNMENT_PHASES}
        for phase, (
            dispatcher_phase,
            is_governance,
            task_type,
            _note,
        ) in PHASE_LOOP_PARAMS.items():
            assert phase in CYCLE_PHASES
            assert task_type in TASK_TYPES
            normalized = dispatcher_phase.lower().replace("-", "_")
            assert (normalized in governance) == is_governance, dispatcher_phase

    def test_f6_note_declares_prose_for_documentary_deliverables(self):
        assert "prose" in PHASE_LOOP_PARAMS["F6-revision"][3]


class TestRouterRendering:
    """ROUTER.md is a deterministic projection of the adopted prompts."""

    def _tree(self, root: Path) -> Path:
        return _seed(
            root,
            {
                "audit_x.md": _prompt(
                    {
                        "role": "auditor",
                        "cycle_phase": "[F3-auditoria-contrato]",
                        "route_kind": "entry",
                    },
                    "Audit X",
                    "ordena leer `prompts/_shared/gate.md`\n",
                    what="audita el contrato",
                ),
                "pipe.md": _prompt(
                    {
                        "role": "orchestrator",
                        "cycle_phase": "[F4-lanzamiento, F6-revision]",
                        "route_kind": "modo",
                    },
                    "Pipe",
                ),
                "opt.md": _prompt(
                    {"role": "orchestrator", "route_kind": "mantenimiento"}, "Opt"
                ),
                "_shared/gate.md": _prompt(
                    {"route_kind": "modulo"}, "Gate", what="gate de goal"
                ),
                "hermes_soul.md": "# Soul\n",
                "pending.md": "# Pending\n",
            },
        )

    def test_router_sections_and_rows(self, tmp_path):
        text = build_router(self._tree(tmp_path))
        assert "`prompts/audit_x.md`" in text
        assert "F3-auditoria-contrato" in text
        assert "CONTRACT_AUDIT / contract-audit" in text
        assert "F5-implementacion" in text and "no abras" in text.lower()
        assert "`prompts/pipe.md`" in text and "F4-lanzamiento, F6-revision" in text
        assert "`prompts/opt.md`" in text
        assert "`prompts/_shared/gate.md`" in text and "audit_x.md" in text
        assert (
            "hermes_soul.md" in text
        )  # declared as exempt in the header, never routed
        assert "`prompts/hermes_soul.md`" not in text
        assert "`prompts/pending.md`" not in text
        assert "Adoptados: 4 de 5" in text

    def test_router_is_deterministic(self, tmp_path):
        root = self._tree(tmp_path)
        assert build_router(root) == build_router(root)

    def test_more_than_five_citers_collapse_to_transversal(self, tmp_path):
        files = {f"c{i}.md": "ver `prompts/_shared/gate.md`\n" for i in range(6)}
        files["_shared/gate.md"] = _prompt({"route_kind": "modulo"}, "Gate")
        root = _seed(tmp_path, files)
        assert "transversal (6)" in build_router(root)


class TestRouterGate:
    """The new gate: a stale or missing ROUTER.md is detected (mutation -> red)."""

    def test_generated_router_is_fresh_then_mutation_makes_it_stale(self, tmp_path):
        root = _seed(
            tmp_path,
            {
                "a.md": _prompt(
                    {
                        "role": "manager",
                        "cycle_phase": "[F6-revision]",
                        "route_kind": "entry",
                    },
                    "A",
                )
            },
        )
        path = generate_router(root)
        assert path == root / ROUTER_REL_PATH
        assert check_router_stale(root) == (False, "")
        path.write_text(
            path.read_text(encoding="utf-8") + "edicion a mano\n", encoding="utf-8"
        )
        stale, diag = check_router_stale(root)
        assert stale and "ROUTER.md" in diag

    def test_missing_router_is_stale(self, tmp_path):
        root = _seed(tmp_path, {"a.md": "# A\n"})
        stale, diag = check_router_stale(root)
        assert stale and "does not exist" in diag


class TestCatalogAndNaming:
    """Wiring: prompt `role` reaches the catalog; naming covers prompts/_shared."""

    def test_prompt_role_from_frontmatter_reaches_the_catalog(self, tmp_path):
        root = _seed(
            tmp_path,
            {"a.md": _prompt({"role": "auditor", "route_kind": "mantenimiento"}, "A")},
        )
        entries = {e["path"]: e for e in build_catalog(root)["entries"]}
        assert entries["prompts/a.md"]["role"] == "auditor"

    def test_naming_gate_covers_prompts_shared(self, tmp_path):
        root = _seed(
            tmp_path, {"_shared/LoopX.md": "# x\n", "_shared/ok_name.md": "# y\n"}
        )
        violations = check_naming(root)
        assert len(violations) == 1 and "LoopX" in violations[0]


def test_route_kinds_enum_is_exactly_the_dec_d2_enum():
    # Set equality: adding or dropping a kind without a DEC change turns this red.
    assert set(ROUTE_KINDS) == {"entry", "modo", "modulo", "mantenimiento", "externo"}
    assert len(ROUTE_KINDS) == 5
