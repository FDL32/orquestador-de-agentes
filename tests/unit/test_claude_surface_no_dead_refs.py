"""WOT-2026-074c: la superficie .claude no cita rutas muertas y cleanup_legacy no contradice guias.

Dos contratos:
1. Los slash commands/agents/README de .claude no citan reglas legacy inexistentes
   ni rutas `.agent/**/*.md` que no existan en el arbol.
2. Ningun nombre de LegacyCleanup.OLD_SCRIPT_NAMES / OLD_CONFIG_FILES es un fichero
   que UPGRADE_CLEANUP_GUIDE.md ordena conservar (``Keep `X```).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from scripts.cleanup_legacy import LegacyCleanup


REPO_ROOT = Path(__file__).resolve().parents[2]

CLAUDE_SURFACES = [
    ".claude/commands/agent-build.md",
    ".claude/commands/agent-plan.md",
    ".claude/commands/agent-review.md",
    ".claude/agents/builder.md",
    ".claude/agents/manager.md",
]

# Reglas legacy que nunca existieron en el motor ni en el destino.
LEGACY_RULE_NAMES = re.compile(
    r"\.agent_common_rules\.md|\.builder_rules|\.manager_rules|collaboration/constitution\.md"
)
# Rutas .md citadas en backticks bajo .agent/.
AGENT_MD_CITATION = re.compile(r"`(\.agent/[^`\s]+\.md)`")
KEEP_DIRECTIVE = re.compile(r"Keep `([^`]+)`")


def find_dead_refs(root: Path, surface: Path) -> list[str]:
    """Devuelve las referencias muertas citadas por un fichero de superficie.

    Before: ``surface`` es un fichero de texto UTF-8 legible; ``root`` es la raiz
        contra la que se resuelven las rutas ``.agent/...`` citadas.
    During: lee el texto, busca nombres legacy conocidos y rutas ``.agent/**.md``
        en backticks; comprueba la existencia de estas ultimas bajo ``root``.
        Solo lectura de disco, sin efectos colaterales.
    After: lista (posiblemente vacia) de referencias muertas, sin duplicados.
        Lanza ``OSError``/``UnicodeDecodeError`` si el fichero no se puede leer.
    """
    text = surface.read_text(encoding="utf-8")
    dead: list[str] = [m.group(0) for m in LEGACY_RULE_NAMES.finditer(text)]
    dead.extend(
        cited
        for cited in AGENT_MD_CITATION.findall(text)
        if not (root / cited).exists()
    )
    return sorted(set(dead))


def find_kept_files_listed_for_removal(
    guide_text: str, removal_names: list[str]
) -> list[str]:
    """Devuelve los nombres de ``removal_names`` que la guia manda conservar.

    Before: ``guide_text`` es el texto de UPGRADE_CLEANUP_GUIDE.md (o equivalente).
    During: extrae cada ``Keep `X``` y compara por basename con ``removal_names``.
    After: lista ordenada de contradicciones; vacia si no hay ninguna.
    """
    kept = {Path(m).name for m in KEEP_DIRECTIVE.findall(guide_text)}
    return sorted({Path(n).name for n in removal_names} & kept)


@pytest.mark.parametrize("rel", CLAUDE_SURFACES)
def test_real_claude_surface_has_no_dead_refs(rel: str) -> None:
    """Before: arbol real del motor. After: la superficie no cita rutas muertas."""
    surface = REPO_ROOT / rel
    assert surface.is_file(), f"superficie ausente: {rel}"
    assert find_dead_refs(REPO_ROOT, surface) == []


def test_readme_does_not_claim_legacy_archive() -> None:
    """El README no puede afirmar que las reglas viven en .agent/legacy/ (no existe)."""
    assert not (REPO_ROOT / ".agent" / "legacy").exists()
    readme = (REPO_ROOT / ".claude" / "README.md").read_text(encoding="utf-8")
    assert ".agent/legacy" not in readme
    assert LEGACY_RULE_NAMES.search(readme) is None


def test_dead_ref_detector_bites_on_legacy_names_and_missing_paths(
    tmp_path: Path,
) -> None:
    """Caso negativo: el detector muerde ante nombres legacy y rutas inexistentes."""
    (tmp_path / ".agent" / "rules").mkdir(parents=True)
    (tmp_path / ".agent" / "rules" / "real.md").write_text("ok", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text(
        "Lee `.agent_common_rules.md`, `.builder_rules`, `.manager_rules` y "
        "`.agent/collaboration/constitution.md`, `.agent/rules/missing.md`.",
        encoding="utf-8",
    )
    good = tmp_path / "good.md"
    good.write_text("Lee `.agent/rules/real.md` y `AGENTS.md`.", encoding="utf-8")

    dead = find_dead_refs(tmp_path, bad)
    assert ".agent_common_rules.md" in dead
    assert ".builder_rules" in dead
    assert ".manager_rules" in dead
    assert "collaboration/constitution.md" in dead
    assert ".agent/rules/missing.md" in dead
    assert find_dead_refs(tmp_path, good) == []


def test_cleanup_lists_do_not_contradict_keep_directives() -> None:
    """Before: guia real. After: ningun fichero a borrar/archivar esta en un ``Keep``."""
    guide = (REPO_ROOT / "UPGRADE_CLEANUP_GUIDE.md").read_text(encoding="utf-8")
    assert "UPGRADE_GUIDE.md" in KEEP_DIRECTIVE.findall(guide), (
        "guia sin su Keep esperado"
    )
    removal = list(LegacyCleanup.OLD_SCRIPT_NAMES) + list(
        LegacyCleanup.OLD_CONFIG_FILES
    )
    assert find_kept_files_listed_for_removal(guide, removal) == []
    assert "UPGRADE_GUIDE.md" not in LegacyCleanup.OLD_CONFIG_FILES
    assert "detect_agent_system_version.py" not in LegacyCleanup.OLD_SCRIPT_NAMES


def test_keep_contradiction_detector_bites() -> None:
    """Caso negativo: una lista que incluye un fichero ``Keep`` se detecta."""
    guide = "- Keep `UPGRADE_GUIDE.md` at the root.\n- Keep `scripts/foo.py` too."
    found = find_kept_files_listed_for_removal(
        guide, ["UPGRADE_GUIDE.md", "scripts/foo.py", "other.txt"]
    )
    assert found == ["UPGRADE_GUIDE.md", "foo.py"]
    assert find_kept_files_listed_for_removal(guide, ["other.txt"]) == []
