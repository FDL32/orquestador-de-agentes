"""
Tests for manager-orchestrator-loop skill (WOT-2026-093d, paso 9a).

Verifica:
1. El sha256 escrito en la skill coincide con el sha256 real del nucleo.
2. Mutation-verify: sobre una copia alterada del nucleo, el hash NO coincide.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_FILE = ROOT / "skills" / "manager-orchestrator-loop" / "SKILL.md"
CORE_FILE = ROOT / "prompts" / "manager_orchestrator_loop.md"

# Hash declarado en la skill (nucleo_sha256 del frontmatter).
DECLARED_SHA = "faaa1c2bc5b84da03a02d0bc410584fa7f9e8388c34f2e237ac7e22919d92eba"


def _file_sha256(path: Path) -> str:
    """Return hex sha256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _extract_skill_sha(skill_path: Path) -> str:
    """Extract nucleo_sha256 from the skill's frontmatter."""
    content = skill_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.startswith("nucleo_sha256:"):
            return line.split(":", 1)[1].strip()
    raise ValueError(f"nucleo_sha256 not found in {skill_path}")


class TestManagerOrchestratorLoopSkill:
    """Tests for the manager-orchestrator-loop skill pointing to the core."""

    def test_skill_file_exists(self):
        """The skill SKILL.md must exist in the skills directory."""
        assert SKILL_FILE.exists(), (
            "skills/manager-orchestrator-loop/SKILL.md is missing"
        )

    def test_core_file_exists(self):
        """The core prompt must exist to have a sha256 to compare against."""
        assert CORE_FILE.exists(), "prompts/manager_orchestrator_loop.md is missing"

    def test_skill_has_contract_id(self):
        """The skill frontmatter must declare contract_id."""
        content = SKILL_FILE.read_text(encoding="utf-8")
        assert "contract_id: cid-manager-orchestrator-loop-v1" in content

    def test_skill_has_nucleo_sha256(self):
        """The skill frontmatter must declare nucleo_sha256."""
        content = SKILL_FILE.read_text(encoding="utf-8")
        assert "nucleo_sha256:" in content

    def test_skill_sha256_matches_core(self):
        """The sha256 written in the skill must equal the real core sha256."""
        core_sha = _file_sha256(CORE_FILE)
        skill_sha = _extract_skill_sha(SKILL_FILE)
        assert core_sha == DECLARED_SHA, (
            f"Core sha256 mismatch: skill declares {DECLARED_SHA}, core is {core_sha}"
        )
        assert skill_sha == core_sha, (
            f"Frontmatter nucleo_sha256 ({skill_sha}) != declared "
            f"({DECLARED_SHA}) != core ({core_sha})"
        )

    def test_declared_sha_is_64_hex(self):
        """The declared sha must be a valid 64-char hex string."""
        assert len(DECLARED_SHA) == 64, f"SHA length: {len(DECLARED_SHA)}"
        assert all(c in "0123456789abcdef" for c in DECLARED_SHA)

    def test_mutation_verify_hash_mismatches(self):
        """Mutation-verify: on an altered copy of the core, the hash must NOT match."""
        # Read the core content and alter it
        original_bytes = CORE_FILE.read_bytes()
        altered_content = original_bytes + b"\n# ALTERED FOR MUTATION TEST"

        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".md") as tmp:
            tmp.write(altered_content)
            tmp_path = Path(tmp.name)

        try:
            altered_sha = _file_sha256(tmp_path)
            assert altered_sha != DECLARED_SHA, (
                "Mutation-verify FAILED: altered core hash unexpectedly matches "
                f"declared hash {DECLARED_SHA}"
            )
            # Verify it's actually different from the real core
            real_sha = _file_sha256(CORE_FILE)
            assert altered_sha != real_sha, (
                "Mutation-verify: altered hash equals real core hash - "
                "the mutation did not change the file"
            )
        finally:
            tmp_path.unlink()

    def test_skill_points_to_correct_prompt(self):
        """The skill must reference the correct core prompt path."""
        content = SKILL_FILE.read_text(encoding="utf-8")
        assert "prompts/manager_orchestrator_loop.md" in content
        assert "contract_id: cid-manager-orchestrator-loop-v1" in content

    def test_skill_no_criteria_redeclaration(self):
        """The skill must NOT re-declare normative criteria from the core."""
        content = SKILL_FILE.read_text(encoding="utf-8")
        # These are normative criteria that should live only in the core, not here.
        # The skill should only point, not redefine.
        forbidden_criteria = [
            "DECISION: APPROVE",
            "DECISION: CHANGES",
            "BLOQUEANTE:",
            "regla de validez = [",
            "MINIMOS:",
        ]
        for criterion in forbidden_criteria:
            assert criterion not in content, (
                f"Skill re-declares normative criterion '{criterion}' - "
                "'skill apunta, prompt gobierna'"
            )

    def test_skill_does_not_summarize_core_vocabulary(
        self, skill_file: Path = SKILL_FILE
    ):
        """The skill must not enumerate the core's states or capabilities (a summary drifts).

        Before: the core defines its states and capability names in its own sections.
        During: scans the skill body for those names.
        After: fails if any appears (the first version listed the state machine and a
            stale list of schemas). Parametrizable path for mutation-verify on a copy.
        """
        content = skill_file.read_text(encoding="utf-8")
        core_terms = [
            "PROMPT_EJECUTOR",
            "LECTOR_FS",
            "LENTE_TEXTO",
            "ESTRATEGIA ->",
            "-> DIVISION",
            "ronda_ficheros",
            "ronda_texto",
            "VERIFICADOR DE HECHOS",
        ]
        found = [t for t in core_terms if t in content]
        assert not found, (
            f"Skill summarizes core vocabulary {found}: 'skill apunta, prompt gobierna'"
        )
