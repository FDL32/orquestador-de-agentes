"""Single-source barrier for the evidence criterion (WOT-2026-044v).

The criterion "evidencia antes que relato" (what counts as evidence, the
probe-or-hypothesis rule, the VERIFICADO / INFERIDO / NO VERIFICADO labels) lives
ONCE in ``prompts/_shared/evidence_contract.md``. Every other surface must point
to it with a short phrase instead of restating it (X-09: skill/prompt point, the
contract governs).

A RE-DECLARATION is a text unit (paragraph or list item) that restates the
criterion AND does not reference ``evidence_contract`` in that same unit. Titles
and pointers ("hereda audit_agent_output.md: evidencia antes que relato, CEM v0")
never match because they do not carry the long-form criterion phrases.

DECLARED LIMIT (Review 2, same principle as ``check_document_self_contradiction``:
it only covers the predicates it declares). The detector is LEXICAL. It covers the
families in ``CRITERION_PATTERNS`` (literal "ningun auto-reporte ... evidencia;
usa", probe-or-hypothesis, "auto-reporte ... como/no es/no vale como ...
evidencia|prueba", "informe ... sustituye ... evidencia|prueba", "afirmaciones
causales ... requieren ... prueba"). It does NOT cover arbitrary paraphrases: a
restatement in words outside those families passes. Extending it is a new family
plus its mutation test, not a promise of semantic coverage.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = "prompts/_shared/evidence_contract.md"
POINTER = "evidence_contract"

#: Universe scanned (relative to the repo root). ``skills/`` includes ``references/``.
UNIVERSE_FILES = ("AGENTS.md", "CLAUDE.md")
UNIVERSE_DIRS = ("prompts", "skills", ".agent/rules")

#: Long-form criterion phrases, matched on accent-folded lowercase text.
CRITERION_PATTERNS = (
    re.compile(
        r"ningun\s+auto-?report\w*[^.;]{0,40}evidencia\s*;\s*(?:usa|solo|verifica)"
    ),
    re.compile(r"precedida\s+de\s+un\s+probe"),
    re.compile(r"marcad[ao]\s+como\s+hipotesis"),
    # Family one: a self-report framed as (not) evidence or proof.
    re.compile(
        r"auto-?report\w*[^.;]{0,60}\b(?:como|no\s+es|no\s+vale\s+como|sustituye\w*)\b"
        r"[^.;]{0,30}\b(?:evidencia|prueba)"
    ),
    # Family two: an agent report said to replace the evidence.
    re.compile(
        r"\binforme\b[^.;]{0,40}\bsustituye\w*\b[^.;]{0,30}\b(?:evidencia|prueba)"
    ),
    # Family three: causal or state claims said to require proof.
    re.compile(
        r"afirmaciones?\s+(?:causal|historic|de\s+estado)\w*[^.;]{0,40}"
        r"\b(?:requieren|exigen|necesitan)\b[^.;]{0,30}\b(?:prueba|probe|evidencia)"
    ),
)

#: The label vocabulary is USED (not restated) by many audit surfaces, so it is not
#: a re-declaration signal; the contract test only checks the contract defines it.
LABELS_PATTERN = re.compile(r"verificado\s*/\s*inferido\s*/\s*no\s+verificado")

_ITEM_START = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def _fold(text: str) -> str:
    """Return ``text`` lowercased with accents removed.

    Before: ``text`` is any str.
    During: NFKD-normalizes and drops combining marks; pure function, no I/O.
    After: accent- and case-insensitive text; never raises for str input.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def split_units(text: str) -> list[str]:
    """Split markdown into paragraphs and individual list items.

    Before: ``text`` is the file content.
    During: breaks on blank lines and on every bullet/numbered line start, so a
        pointer in one list item cannot exempt a restatement in its neighbour.
    After: non-empty units, each a joined string; pure, no I/O.
    """
    units: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if current:
                units.append(current)
                current = []
            continue
        if _ITEM_START.match(line) and current:
            units.append(current)
            current = []
        current.append(line)
    if current:
        units.append(current)
    return [" ".join(part.strip() for part in unit) for unit in units]


def is_redeclaration(unit: str) -> bool:
    """Decide whether one text unit restates the evidence criterion.

    Before: ``unit`` is a single paragraph or list item.
    During: a unit that cites ``evidence_contract`` is a pointer and passes;
        otherwise it is matched against the long-form criterion phrases.
    After: True only for a restatement without pointer; pure, no I/O.
    """
    folded = _fold(unit)
    if POINTER in folded:
        return False
    return any(p.search(folded) for p in CRITERION_PATTERNS)


def iter_universe(root: Path) -> list[Path]:
    """List the scanned ``.md`` files under ``root``, minus the contract itself.

    Before: ``root`` is a repo-like directory (it may lack some universe paths).
    During: walks ``UNIVERSE_FILES`` and ``UNIVERSE_DIRS`` (``skills/*/references``
        included); filesystem reads only.
    After: sorted unique paths; missing paths are skipped, never an error.
    """
    found: set[Path] = set()
    for name in UNIVERSE_FILES:
        path = root / name
        if path.is_file():
            found.add(path)
    for dirname in UNIVERSE_DIRS:
        base = root / dirname
        if base.is_dir():
            found.update(p for p in base.rglob("*.md") if p.is_file())
    contract = root / CONTRACT_REL
    return sorted(p for p in found if p != contract)


def find_redeclarations(root: Path) -> list[str]:
    """Scan the universe and report every re-declaration of the criterion.

    Before: ``root`` as in ``iter_universe``; files are UTF-8 text.
    During: reads each file and tests each unit with ``is_redeclaration``.
    After: ``"<relpath>: <excerpt>"`` per hit; empty list means single source.
        Undecodable files raise ``UnicodeDecodeError`` (a corrupt file must be
        visible, not skipped).
    """
    hits: list[str] = []
    for path in iter_universe(root):
        text = path.read_text(encoding="utf-8")
        for unit in split_units(text):
            if is_redeclaration(unit):
                rel = path.relative_to(root).as_posix()
                hits.append(f"{rel}: {unit[:120]}")
    return hits


def test_real_tree_has_single_source() -> None:
    """The real repo has zero re-declarations outside the contract.

    Before: the working tree contains ``prompts/_shared/evidence_contract.md``.
    During: scans the real universe.
    After: zero hits, with each offender listed in the failure message.
    """
    assert (ROOT / CONTRACT_REL).is_file(), "the single-source contract must exist"
    assert find_redeclarations(ROOT) == []


def test_contract_itself_holds_the_criterion() -> None:
    """The contract carries the criterion the other surfaces point to.

    Before: the contract file exists.
    During: matches its folded text against the criterion patterns.
    After: at least the probe rule and the labels are present, so a pointer
        never targets an empty file.
    """
    folded = _fold((ROOT / CONTRACT_REL).read_text(encoding="utf-8"))
    folded = re.sub(r"\s+", " ", folded)
    assert "ningun auto-reporte de agente es evidencia" in folded
    assert CRITERION_PATTERNS[1].search(folded), "probe rule missing"
    assert CRITERION_PATTERNS[2].search(folded), "hypothesis rule missing"
    assert LABELS_PATTERN.search(folded), "labels missing"


def test_mutation_skill_restating_criterion_is_detected(tmp_path: Path) -> None:
    """MUTATION: a SKILL.md that restates the criterion is caught.

    Before: ``tmp_path`` is an empty fixture repo.
    During: writes a skill restating the criterion with no pointer.
    After: the scan reports that skill (the barrier bites).
    """
    skill = tmp_path / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "# Demo\n\n- **Evidencia antes que relato.** Ningun auto-reporte cuenta como "
        "evidencia; solo diff, exit code, test.\n",
        encoding="utf-8",
    )
    hits = find_redeclarations(tmp_path)
    assert len(hits) == 1
    assert hits[0].startswith("skills/demo/SKILL.md")


def test_mutation_in_references_is_detected(tmp_path: Path) -> None:
    """MUTATION: references/ is inside the scanned universe.

    Before: ``tmp_path`` is an empty fixture repo.
    During: writes a references file restating the probe-or-hypothesis rule.
    After: detected, per the 2026-10-24 scope decision.
    """
    ref = tmp_path / "skills" / "demo" / "references" / "x.md"
    ref.parent.mkdir(parents=True)
    ref.write_text(
        "Toda afirmacion causal va precedida de un probe ejecutado, o marcada como hipotesis.\n",
        encoding="utf-8",
    )
    assert len(find_redeclarations(tmp_path)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "No aceptes auto-reportes como evidencia. Verifica artefactos y comandos.",
        "Las afirmaciones causales requieren pruebas ejecutadas; las conjeturas deben "
        "identificarse como tales.",
        "Ningun informe de un agente sustituye la evidencia; verifica con diff o exit code.",
        "El auto-reporte del agente no vale como prueba: usa diff, exit code o test.",
    ],
)
def test_mutation_review2_paraphrase_families_are_detected(
    tmp_path: Path, text: str
) -> None:
    """MUTATION (Review 2): paraphrases of the criterion without pointer are caught.

    Before: ``tmp_path`` is an empty fixture repo.
    During: writes one paraphrase as a prompt, with no ``evidence_contract`` pointer.
    After: exactly one hit; the same text WITH the pointer yields zero (exempt).
    """
    prompt = tmp_path / "prompts" / "p.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(text + "\n", encoding="utf-8")
    assert len(find_redeclarations(tmp_path)) == 1
    prompt.write_text(
        text + " Ver `prompts/_shared/evidence_contract.md`.\n", encoding="utf-8"
    )
    assert find_redeclarations(tmp_path) == []


@pytest.mark.parametrize(
    "text",
    [
        "Hereda `prompts/audit_agent_output.md`: evidencia antes que relato, CEM v0.",
        "- **Evidencia antes que relato:** auto-reporte no es evidencia; criterio en "
        "`prompts/_shared/evidence_contract.md`.",
        "Rige `prompts/_shared/evidence_contract.md`: ningun auto-reporte es evidencia; "
        "usa diff, exit code.",
        "El informe es evidencia DECLARADA (CEM: ningun auto-reporte es\nevidencia): "
        "el auditor re-ejecuta lo que cita.",
    ],
)
def test_negative_control_pointers_and_headlines_not_detected(
    tmp_path: Path, text: str
) -> None:
    """CONTROL NEGATIVO: headlines, pointers and plain mentions do not match.

    Before: ``tmp_path`` is an empty fixture repo.
    During: writes each non-restating text as a prompt.
    After: zero hits, proving the detector does not fire on pointers/titles.
    """
    prompt = tmp_path / "prompts" / "p.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(text + "\n", encoding="utf-8")
    assert find_redeclarations(tmp_path) == []


def test_pointer_in_neighbour_item_does_not_exempt_restatement(tmp_path: Path) -> None:
    """A pointer in a sibling list item must not hide a restatement.

    Before: ``tmp_path`` is an empty fixture repo.
    During: writes two adjacent bullets, only the first with the pointer.
    After: exactly the second bullet is reported.
    """
    prompt = tmp_path / "prompts" / "p.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(
        "- ver `prompts/_shared/evidence_contract.md`\n"
        "- toda afirmacion va precedida de un probe ejecutado\n",
        encoding="utf-8",
    )
    hits = find_redeclarations(tmp_path)
    assert len(hits) == 1
    assert "precedida" in hits[0]
