"""Before: define executable grammar contracts for session titles.

During: generate paired valid and invalid cases from the same field rules.

After: exercise rendering, checking, linting, input handling, and one grammar.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from scripts.flight import session_title


ROOT = Path(__file__).resolve().parents[2]
SEPARATOR = "\u00b7"
ROLES = ("CO", "IM", "TR")
FIELDS_BY_ROLE = {
    "CO": ("codigo", "mandato", "parentesis"),
    "IM": ("codigo", "ticket", "tema", "coordinadora", "parentesis"),
    "TR": ("codigo", "tema", "coordinadora", "parentesis"),
}
POSITIONS = ("inicial", "interior", "final", "antes_sep", "despues_sep")


def _title(
    role: str,
    *,
    mandato: str = "Consolidar reglas",
    tema: str = "Replica corta",
    ticket: str = "152s-2b",
    coordinadora: str = "CO-112",
    parentesis: str = "",
) -> str:
    fields = {
        "CO": f"CO-111 {SEPARATOR} {mandato}",
        "IM": f"IM-186 {SEPARATOR} {ticket} {tema} {SEPARATOR} {coordinadora}",
        "TR": f"TR-70 {SEPARATOR} {tema} {SEPARATOR} {coordinadora}",
    }
    return fields[role] + (f" {parentesis}" if parentesis else "")


def _expected(field: str, value: str, role: str) -> int:
    if field == "ticket":
        return 0 if re.fullmatch(r"\d{2,4}[a-z]?(?:-[0-9a-z]{1,3})*", value) else 1
    if field in {"codigo", "coordinadora"}:
        candidate = (
            value
            if value.startswith(("CO-", "IM-", "TR-"))
            else f"{role}-{value}"
            if field == "codigo"
            else value
        )
        pattern = r"CO-\d{1,4}" if field == "coordinadora" else r"(?:CO|IM|TR)-\d{1,4}"
        return 0 if re.fullmatch(pattern, candidate) else 1
    if field == "parentesis":
        return (
            0
            if re.fullmatch(
                r"\((desde|releva|relevo|IDLE|Codex)( [^)]{1,60})?\)", value
            )
            else 1
        )
    words = len(value.split())
    return 0 if 1 <= words <= 6 else 1


def _generated_pairs():  # noqa: C901
    values = {
        "codigo": ("9", "12345"),
        "ticket": ("152s-2b", "WOT-2025-12"),
        "mandato": ("Consolidar reglas", "uno dos tres cuatro cinco seis siete"),
        "tema": ("Replica corta", "uno dos tres cuatro cinco seis siete"),
        "coordinadora": ("CO-112", "IM-112"),
        "parentesis": ("(desde nota)", "(desde )"),
    }
    pairs = []
    combinations = set()
    for role in ROLES:
        for field in FIELDS_BY_ROLE[role]:
            combinations.add((field, role))
            for value in values[field if field in values else "tema"]:
                if field == "codigo":
                    base = _title(role).replace(
                        {"CO": "CO-111", "IM": "IM-186", "TR": "TR-70"}[role],
                        f"{role}-{value}",
                    )
                elif field == "mandato":
                    base = _title(role, mandato=value)
                elif field == "tema":
                    base = _title(role, tema=value)
                elif field == "ticket":
                    base = _title(role, ticket=value)
                elif field == "coordinadora":
                    base = _title(role, coordinadora=value)
                else:
                    base = _title(role, parentesis=value)
                pairs.append((base, _expected(field, value, role)))
    positional_combinations = set()
    for role in ROLES:
        for field in FIELDS_BY_ROLE[role]:
            base_value = {
                "codigo": {"CO": "CO-111", "IM": "IM-186", "TR": "TR-70"}[role],
                "mandato": "Consolidar reglas",
                "ticket": "152s-2b",
                "tema": "Replica corta",
                "coordinadora": "CO-112",
                "parentesis": "(desde nota)",
            }[field]
            for position in POSITIONS:
                positional_combinations.add((field, role, position))
                valid_title = _title_with_field(role, field, base_value)
                pairs.append((valid_title, _expected(field, base_value, role)))
                if position in {"antes_sep", "despues_sep"}:
                    separator = f" {SEPARATOR} "
                    replacement = (
                        f"  {SEPARATOR} "
                        if position == "antes_sep"
                        else f" {SEPARATOR}  "
                    )
                    pairs.append((valid_title.replace(separator, replacement), 1))
                else:
                    perturbation = "\t"
                    if position == "inicial":
                        changed = perturbation + base_value
                    elif position == "interior":
                        split_at = max(1, len(base_value) // 2)
                        changed = (
                            base_value[:split_at] + perturbation + base_value[split_at:]
                        )
                    else:
                        changed = base_value + perturbation
                    pairs.append((_title_with_field(role, field, changed), 1))
    return pairs, combinations, positional_combinations


def _title_with_field(role: str, field: str, value: str) -> str:
    """Before: receive one applicable role, field, and value.

    During: place the value in the canonical title field without changing other fields.

    After: return the title used by the paired generator.
    """
    if field == "codigo":
        return _title(role).replace(
            {"CO": "CO-111", "IM": "IM-186", "TR": "TR-70"}[role], value
        )
    if field == "mandato":
        return _title(role, mandato=value)
    if field == "ticket":
        return _title(role, ticket=value)
    if field == "tema":
        return _title(role, tema=value)
    if field == "coordinadora":
        return _title(role, coordinadora=value)
    return _title(role, parentesis=value)


def test_session_title_generado(capsys):
    """Before: derive paired cases across roles and applicable fields.

    During: check each generated title against its rule-derived result.

    After: report the generated count and every declared role/field pairing.
    """
    pairs, combinations, positional_combinations = _generated_pairs()
    assert pairs
    assert combinations == {
        (field, role) for role in ROLES for field in FIELDS_BY_ROLE[role]
    }
    assert positional_combinations == {
        (field, role, position)
        for role in ROLES
        for field in FIELDS_BY_ROLE[role]
        for position in POSITIONS
    }
    for title, expected in pairs:
        assert session_title.check(title) == expected, title
    assert session_title.check(_title("CO", mandato="")) == 1
    assert (
        session_title.check(_title("CO", mandato="uno dos tres cuatro cinco seis")) == 0
    )
    assert (
        session_title.check(
            _title("CO", mandato="uno dos tres cuatro cinco seis siete")
        )
        == 1
    )
    exact_100 = "a" * (100 - len("CO-111 " + SEPARATOR + " "))
    assert len(_title("CO", mandato=exact_100)) == 100
    assert session_title.check(_title("CO", mandato=exact_100)) == 0
    assert session_title.check(_title("CO", mandato=exact_100 + "a")) == 1
    exact_60 = "(desde " + "a" * 52 + ")"
    assert len(exact_60) == 60
    assert session_title.check(_title("CO", parentesis=exact_60)) == 0
    assert session_title.check(_title("CO", parentesis=exact_60 + "a")) == 1
    for codepoint in session_title.CONTROL_CHARS:
        assert session_title.check(_title("CO", mandato="uno" + chr(codepoint))) == 1
    assert (
        session_title.check(
            f"IM-186 {SEPARATOR} 152s-2b replica corta {SEPARATOR} CO-112"
        )
        == 0
    )
    assert session_title.check("CO-111 - Consolidar reglas") == 1
    assert session_title.check(_title("CO", mandato="uno  dos")) == 0
    for forbidden in ("coordinadora", "implantador", "triaje", "vuelo-", "releva a"):
        assert session_title.check(_title("CO", mandato=forbidden)) == 1
    for allowed in ("vuelo", "vuela", "vuelos", "vuela-s"):
        assert session_title.check(_title("CO", mandato=allowed)) == 0
    assert all(
        decision.startswith("DA-") for decision in session_title.DECISIONES_ABIERTAS
    )
    assert {decision[:5] for decision in session_title.DECISIONES_ABIERTAS} == {
        "DA-1:",
        "DA-2:",
        "DA-3:",
        "DA-4:",
    }
    print(
        f"generated_pairs={len(pairs)} positional_combinations={len(positional_combinations)}"
    )
    print(
        "combinations="
        + ",".join(f"{role}:{field}" for field, role in sorted(combinations))
    )


def test_session_title_render_check():
    """Before: provide canonical render inputs and boundary values.

    During: render abbreviated tickets and validate the resulting literals.

    After: valid renders check as zero and invalid year prefixes check as one.
    """
    assert session_title.render("CO", "CO-111", mandato="Consolidar reglas") == _title(
        "CO"
    )
    rendered = session_title.render(
        "IM",
        "IM-186",
        ticket="WOT-2026-152s-2b",
        tema="Replica corta",
        coordinadora="CO-112",
    )
    assert rendered == _title("IM")
    assert session_title.check(rendered) == 0
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/flight/session_title.py"),
            "render",
            "--rol",
            "CO",
            "--codigo",
            "CO-111",
            "--mandato",
            "Consolidar reglas",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == _title("CO")
    assert session_title.check(_title("IM", ticket="WOT-2025-12")) == 1
    assert session_title.check(_title("IM", ticket="152s-2b")) == 0


def test_session_title_lint_relevo():
    """Before: prepare valid, duplicate, invalid, and missing-list inputs.

    During: invoke the read-only lint operation and its command interface.

    After: return codes distinguish success, invalid/duplicate, and unreadable input.
    """
    title = _title("CO")
    assert session_title.lint_relevo(title, [title]) == 0
    assert session_title.lint_relevo(title, [title, title]) == 1
    assert session_title.lint_relevo("not a title", [title]) == 1
    assert session_title.lint_relevo(title, None) == 2
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/flight/session_title.py"),
            "lint-relevo",
            "--titulo",
            title,
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2


def test_session_title_entradas():
    """Before: select empty, whitespace, non-string, and control inputs.

    During: pass each input to the public checker.

    After: invalid strings return one while unreadable types return two.
    """
    assert session_title.check("") == 1
    assert session_title.check("   ") == 1
    assert session_title.check(" " + _title("CO")) == 1
    assert session_title.check(None) == 2
    assert session_title.check(42) == 2
    assert session_title.check(_title("CO", mandato="uno\ttwo")) == 1
    assert session_title.check(_title("CO") + "\n") == 1


def test_session_title_una_sola_gramatica():
    """Before: inspect the module's shared grammar declarations.

    During: verify master patterns, literals, and the five canonical test nodes.

    After: all public paths point to one set of exact grammar constants.
    """
    assert session_title.TICKET_PATTERN.pattern == r"^\d{2,4}[a-z]?(?:-[0-9a-z]{1,3})*$"
    assert (
        session_title.PAREN_PATTERN.pattern
        == r"^\((desde|releva|relevo|IDLE|Codex)( [^)]{1,60})?\)$"
    )
    source = (ROOT / "scripts/flight/session_title.py").read_text(encoding="ascii")
    master_declarations = (
        "SEPARATOR =",
        "LONGITUD_MAX =",
        "FORBIDDEN_WORDS =",
        "FORBIDDEN_PHRASES =",
        "PAREN_TOKENS =",
        "TICKET_PATTERN =",
        "PAREN_PATTERN =",
        "CODE_PATTERN =",
        "COORDINATOR_PATTERN =",
        "CONTROL_CHARS =",
    )
    assert all(source.count(declaration) == 1 for declaration in master_declarations)
    assert source.count('"releva a"') == 1
    assert source.count('"vuelo-"') == 1
    assert source.count('"^\\d{2,4}[a-z]?(?:-[0-9a-z]{1,3})*$"') == 1
    assert source.count("DECISIONES_ABIERTAS =") == 1
    assert session_title.PAREN_TOKENS == ("desde", "releva", "relevo", "IDLE", "Codex")
    assert session_title.LONGITUD_MAX == 100
    assert frozenset({"releva a"}) == session_title.FORBIDDEN_PHRASES
    assert session_title.SEPARATOR == SEPARATOR
