"""Before: define the single grammar used by session-title operations.

During: render, check, and lint session titles without external state.

After: expose deterministic library functions and read-only command-line tools.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any


SEPARATOR = "\u00b7"
LONGITUD_MAX = 100
ROLES = frozenset({"CO", "IM", "TR"})
FORBIDDEN_WORDS = frozenset({"coordinadora", "implantador", "triaje", "vuelo-"})
FORBIDDEN_PHRASES = frozenset({"releva a"})
PAREN_TOKENS = ("desde", "releva", "relevo", "IDLE", "Codex")
TICKET_PATTERN = re.compile(r"^\d{2,4}[a-z]?(?:-[0-9a-z]{1,3})*$")
PAREN_PATTERN = re.compile(r"^\((desde|releva|relevo|IDLE|Codex)( [^)]{1,60})?\)$")
CODE_PATTERN = re.compile(r"^(?:CO|IM|TR)-\d{1,4}$")
COORDINATOR_PATTERN = re.compile(r"^CO-\d{1,4}$")
CONTROL_CHARS = frozenset(range(32)) | frozenset({127, 133, 8232, 8233})
DECISIONES_ABIERTAS = (
    "DA-1: the s.5 parenthesis pattern governs the optional lineage annotation",
    "DA-2: the complete title length limit is 100",
    "DA-3: the complete parenthesis annotation limit is 60",
    "DA-4: the F26b suffix is outside this module",
)


def _invalid_field(value: str) -> bool:
    """Before: receive one non-empty semantic field.

    During: apply word-level prohibitions and the six-word inclusive limit.

    After: return whether the field violates the shared field rules.
    """
    if not value or not value.strip() or value != value.strip():
        return True
    words = value.split()
    if not 1 <= len(words) <= 6:
        return True
    lowered = [word.lower() for word in words]
    return bool(FORBIDDEN_WORDS.intersection(lowered))


def _has_forbidden_phrase(text: str) -> bool:
    """Before: receive the complete title body.

    During: inspect word tokens and the prohibited multi-word phrase.

    After: return true only for forbidden vocabulary in the shared grammar.
    """
    words = text.lower().split()
    return any(phrase in text.lower() for phrase in FORBIDDEN_PHRASES) or bool(
        FORBIDDEN_WORDS.intersection(words)
    )


def _split_annotation(title: str) -> tuple[str, str | None] | None:
    """Before: receive a title with no outer whitespace.

    During: separate one optional final lineage annotation from the body.

    After: return body and annotation, or None for malformed parentheses.
    """
    if "(" not in title and ")" not in title:
        return title, None
    match = re.search(r" \([^)]*\)$", title)
    if not match:
        return None
    annotation = match.group(0).strip()
    body = title[: match.start()]
    if len(annotation) > 60 or not PAREN_PATTERN.fullmatch(annotation):
        return None
    if "(" in body or ")" in body:
        return None
    return body, annotation


def _check_fields(separated: list[str]) -> int:
    """Before: receive fields split by the exact separator.

    During: validate role, code, ticket, theme, mandate, and coordinator fields.

    After: return zero for a complete role-specific field sequence or one otherwise.
    """
    if not separated or len(separated) not in {2, 3}:
        return 1
    first_parts = separated[0].split()
    if len(first_parts) != 1 or not CODE_PATTERN.fullmatch(first_parts[0]):
        return 1
    role = first_parts[0].split("-", 1)[0]
    expected_fields = {"CO": 2, "IM": 3, "TR": 3}
    if role not in ROLES or len(separated) != expected_fields[role]:
        return 1
    if role == "CO":
        return 0 if not _invalid_field(separated[1]) else 1
    if role == "IM":
        ticket_and_theme = separated[1].split()
        if len(ticket_and_theme) < 2 or not TICKET_PATTERN.fullmatch(
            ticket_and_theme[0]
        ):
            return 1
        if _invalid_field(" ".join(ticket_and_theme[1:])):
            return 1
        return 0 if COORDINATOR_PATTERN.fullmatch(separated[2]) else 1
    if _invalid_field(separated[1]) or not COORDINATOR_PATTERN.fullmatch(separated[2]):
        return 1
    return 0


def _check_title(title: str) -> int:
    """Before: receive a non-empty, trimmed string.

    During: parse the role-specific fields and validate every shared rule.

    After: return zero for valid titles and one for malformed titles.
    """
    if len(title) > LONGITUD_MAX or _has_forbidden_phrase(title):
        return 1
    if f"  {SEPARATOR}" in title or f"{SEPARATOR}  " in title:
        return 1
    separated = title.split(f" {SEPARATOR} ")
    if any(SEPARATOR in field for field in separated[:-1]):
        return 1
    annotation_result = _split_annotation(title)
    if annotation_result is None:
        return 1
    body, annotation = annotation_result
    if annotation is not None:
        separated = body.split(f" {SEPARATOR} ")
    if _check_fields(separated) != 0:
        return 1
    if annotation is not None and _has_forbidden_phrase(annotation):
        return 1
    return 0


def check(title: Any) -> int:
    """Before: receive any candidate title value.

    During: classify unreadable types, whitespace, controls, and grammar errors.

    After: return zero for valid, one for invalid, and two for unreadable input.
    """
    if not isinstance(title, str):
        return 2
    if not title or not title.strip():
        return 1
    if title != title.strip() or any(ord(char) in CONTROL_CHARS for char in title):
        return 1
    return _check_title(title)


def _normalise_ticket(ticket: str) -> str:
    """Before: receive a ticket string from a render caller.

    During: remove only the supported WOT-2026- prefix.

    After: return the literal abbreviated ticket for rendering.
    """
    prefix = "WOT-2026-"
    return ticket[len(prefix) :] if ticket.startswith(prefix) else ticket


def render(
    role: str,
    code: str,
    *,
    mandato: str | None = None,
    ticket: str | None = None,
    tema: str | None = None,
    coordinadora: str | None = None,
    parentesis: str | None = None,
) -> str:
    """Before: receive role-specific fields for one session title.

    During: assemble the canonical separators and abbreviate only WOT-2026 tickets.

    After: return the exact title literal, raising ValueError for invalid fields.
    """
    if role not in ROLES:
        raise ValueError("invalid role")
    if role == "CO":
        if mandato is None:
            raise ValueError("mandato is required")
        title = f"{code} {SEPARATOR} {mandato}"
    elif role == "IM":
        if ticket is None or tema is None or coordinadora is None:
            raise ValueError("ticket, tema, and coordinadora are required")
        title = f"{code} {SEPARATOR} {_normalise_ticket(ticket)} {tema} {SEPARATOR} {coordinadora}"
    else:
        if tema is None or coordinadora is None:
            raise ValueError("tema and coordinadora are required")
        title = f"{code} {SEPARATOR} {tema} {SEPARATOR} {coordinadora}"
    if parentesis is not None:
        title += f" {parentesis}"
    if check(title) != 0:
        raise ValueError("invalid session title fields")
    return title


def lint_relevo(title: Any, titles_existing: list[str] | tuple[str, ...] | None) -> int:
    """Before: receive a measured title and an explicit existing-title list.

    During: validate the title and compare it with other session titles read-only.

    After: return zero for a valid non-duplicate, one for invalid/duplicate, or two for unreadable input.
    """
    if titles_existing is None or not isinstance(titles_existing, (list, tuple)):
        return 2
    result = check(title)
    if result != 0:
        return 1 if result == 1 else 2
    if any(not isinstance(item, str) for item in titles_existing):
        return 2
    found_measured = False
    for item in titles_existing:
        if item == title and not found_measured:
            found_measured = True
            continue
        if item == title:
            return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    """Before: prepare the command-line interface.

    During: define render and read-only lint-relevo arguments.

    After: return a parser whose errors use the documented unreadable-input code.
    """
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("--rol", "--role", dest="role", required=True)
    render_parser.add_argument("--codigo", "--code", dest="code", required=True)
    render_parser.add_argument("--mandato")
    render_parser.add_argument("--ticket")
    render_parser.add_argument("--tema", "--theme", dest="tema")
    render_parser.add_argument("--coordinadora", "--coordinator", dest="coordinadora")
    render_parser.add_argument("--parentesis", "--parentheses", dest="parentesis")
    lint_parser = subparsers.add_parser("lint-relevo")
    lint_parser.add_argument("--titulo", required=True)
    lint_parser.add_argument("--titulos-existente")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Before: receive optional command-line arguments.

    During: execute render or read-only lint-relevo and report causes on stderr.

    After: return the documented three-way status code without writing files.
    """
    args = _parser().parse_args(argv)
    try:
        if args.command == "render":
            print(
                render(
                    args.role,
                    args.code,
                    mandato=args.mandato,
                    ticket=args.ticket,
                    tema=args.tema,
                    coordinadora=args.coordinadora,
                    parentesis=args.parentesis,
                )
            )
            return 0
        if args.titulos_existente is None:
            print("--titulos-existente is required", file=sys.stderr)
            return 2
        existing = args.titulos_existente.split(",")
        result = lint_relevo(args.titulo, existing)
        if result == 1:
            print("invalid or duplicate title", file=sys.stderr)
        return result
    except (TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
