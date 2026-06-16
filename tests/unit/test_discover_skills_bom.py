"""
Tests de regresion BOM para discover_skills.py — WOT-2026-008b.

Verifica que un SKILL.md con BOM UTF-8 no queda invisible en el discovery
ni en el check-contract mientras ambos devuelven exit 0 (falso verde).

Estos tests deben FALLAR con el codigo antes del fix y PASAR con el fix.
"""

from pathlib import Path

from scripts.discover_skills import (
    _check_contract,
    discover_skills,
    parse_frontmatter,
)


BOM = b"\xef\xbb\xbf"

VALID_FRONTMATTER_WITH_BOM = (
    BOM + b"---\nname: BOM Skill\ntriggers: [/bom-test]\nrole: manager\n"
    b"source_prompt: prompts/fake.md\ncontract_id: cid-bom-test-v1\n---\n"
    b"# Body\n"
)

VALID_FRONTMATTER_NO_BOM = (
    b"---\nname: Clean Skill\ntriggers: [/clean-test]\n---\nBody\n"
)


class TestBomVisibility:
    """Un SKILL.md con BOM no puede quedar invisible en el discovery."""

    def test_bom_skill_is_discovered(self, tmp_path):
        """Regression: skill con BOM debe aparecer en discover_skills, no silenciarse."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "bom-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_bytes(VALID_FRONTMATTER_WITH_BOM)

        result = discover_skills(skills_dir)

        assert result["total_skills"] == 1, (
            f"Expected 1 skill discovered, got {result['total_skills']}. "
            "BOM is causing silent skill omission."
        )
        names = {s["name"] for s in result["skills"]}
        assert "BOM Skill" in names, (
            f"Skill 'BOM Skill' not in discovered names {names}. "
            "BOM causes NO_FRONTMATTER and skill is dropped."
        )

    def test_bom_skill_not_lost_in_multi_skill_dir(self, tmp_path):
        """Regression: con 2 skills (1 BOM, 1 clean), discovery no puede devolver solo 1."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        bom_dir = skills_dir / "bom-skill"
        bom_dir.mkdir()
        (bom_dir / "SKILL.md").write_bytes(VALID_FRONTMATTER_WITH_BOM)

        clean_dir = skills_dir / "clean-skill"
        clean_dir.mkdir()
        (clean_dir / "SKILL.md").write_bytes(VALID_FRONTMATTER_NO_BOM)

        result = discover_skills(skills_dir)

        assert result["total_skills"] == 2, (
            f"Expected 2 skills, got {result['total_skills']}. "
            "BOM skill was silently dropped."
        )

    def test_parse_frontmatter_handles_bom(self, tmp_path):
        """Regression: parse_frontmatter debe leer frontmatter aunque el archivo tenga BOM."""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_bytes(VALID_FRONTMATTER_WITH_BOM)

        data, error = parse_frontmatter(skill_file)

        assert error is None, (
            f"parse_frontmatter returned error '{error}' for BOM file. "
            "Expected successful parse (BOM should be consumed transparently)."
        )
        assert data.get("name") == "BOM Skill", (
            f"Expected name='BOM Skill', got {data}."
        )
        assert "/bom-test" in data.get("triggers", []), (
            f"Expected '/bom-test' in triggers, got {data.get('triggers')}."
        )


class TestCheckContractBom:
    """--check-contract no puede devolver exit 0 ignorando skills BOM con contrato roto."""

    def test_check_contract_detects_bom_skill_with_missing_prompt(
        self, tmp_path, monkeypatch
    ):
        """
        Regression: una skill con BOM que tiene role:manager + source_prompt + contract_id
        pero cuyo prompt no existe debe hacer fallar --check-contract.

        Con el bug actual, parse_frontmatter devuelve NO_FRONTMATTER y la skill
        se saltea silenciosamente -> exit 0 (falso verde).

        Con el fix, parse_frontmatter lee el frontmatter correctamente -> la skill
        opt-in al contract check -> el prompt no existe -> exit 1 (fallo correcto).
        """
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "bom-manager-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        # skill con BOM, role:manager, source_prompt apunta a un prompt inexistente
        content = (
            BOM + b"---\nname: BOM Manager\ntriggers: [/bom-manager]\nrole: manager\n"
            b"source_prompt: prompts/nonexistent_for_test.md\n"
            b"contract_id: cid-bom-manager-v1\n---\nBody\n"
        )
        skill_file.write_bytes(content)

        # Redirigir _get_bundle_root() a tmp_path para que el check opere sobre
        # nuestro directorio temporal en lugar del motor real.
        import scripts.discover_skills as ds

        monkeypatch.setattr(ds, "_get_bundle_root", lambda: tmp_path)

        exit_code = _check_contract()

        assert exit_code == 1, (
            f"Expected exit_code=1 (contract violation detected), got {exit_code}. "
            "BOM is silencing the skill and --check-contract returns false green."
        )

    def test_check_contract_passes_for_bom_skill_without_contract_fields(
        self, tmp_path, monkeypatch
    ):
        """
        Una skill con BOM pero sin role:manager/builder ni source_prompt/contract_id
        no debe hacer fallar --check-contract (no ha optado al contrato).
        """
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "bom-nocontract"
        skill_dir.mkdir()
        content = (
            BOM
            + b"---\nname: BOM No Contract\ntriggers: [/bom-nc]\nrole: user\n---\nBody\n"
        )
        (skill_dir / "SKILL.md").write_bytes(content)

        import scripts.discover_skills as ds

        monkeypatch.setattr(ds, "_get_bundle_root", lambda: tmp_path)

        exit_code = _check_contract()

        # Sin role:manager/builder ni source_prompt, no opt-in al contrato -> exit 0 OK
        assert exit_code == 0


class TestBomBarridoReal:
    """Verifica el estado post-fix del motor: ningun SKILL.md debe tener BOM."""

    def test_no_bom_in_skill_files(self):
        """
        Barrido post-fix: ningun SKILL.md debe tener BOM UTF-8 en el motor.
        Si este test falla, hay BOMs no eliminados; documentar con rutas exactas.
        """
        motor_root = Path(__file__).resolve().parent.parent.parent
        skills_dir = motor_root / "skills"
        bom_files = []
        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                raw = skill_file.read_bytes()
                if raw[:3] == BOM:
                    bom_files.append(str(skill_file.relative_to(motor_root)))

        assert bom_files == [], (
            f"BOM found in SKILL.md after fix: {bom_files}. "
            "All BOMs should have been removed by WOT-2026-008b."
        )

    def test_no_bom_in_prompts(self):
        """Ningun prompt/*.md debe tener BOM."""
        motor_root = Path(__file__).resolve().parent.parent.parent
        prompts_dir = motor_root / "prompts"
        bom_prompts = [
            str(f.relative_to(motor_root))
            for f in prompts_dir.glob("*.md")
            if f.read_bytes()[:3] == BOM
        ]
        assert bom_prompts == [], f"BOM found in prompts: {bom_prompts}"
