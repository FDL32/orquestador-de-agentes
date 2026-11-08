"""Derive the next flight heartbeat from a predecessor and a reduced roster.

Before: ``predecessor`` must be a UTF-8 heartbeat file with the documented
anchors, ``roster`` must contain exactly the three consumed roster objects, and
``go_index`` must be the successor's positive Go number.

During: the renderer validates the closed rule counts, preserves the cascade
and postcompaction tails byte-for-byte, derives own/supervisor identities
outside protected judgement and insertion spans, updates the step-9 Go
references, forces the status line, and replaces the three judgement spans.  It can also calculate the
predecessor path's SHA-256 prefix with :func:`predecessor_sha12` for a
judgement supplied by a caller.

After: ``render_latido`` returns ``(0, text)`` for a complete derivation,
``(2, text)`` for a rule mismatch, foreign id, or unconsumed roster field, and
``(3, text)`` when a judgement is not supplied.  Every non-zero result carries
one ``DIFERENCIAS:`` line per problem.  The command-line interface writes the
same plain text to stdout and exits with that return code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


_CASCADE_START = "la cascada es "
_CASCADE_END = " LATIDO DE PROGRESO"


def predecessor_sha12(predecessor: str | Path) -> str:
    """Return the first 12 hexadecimal SHA-256 characters of a predecessor.

    Before: ``predecessor`` must identify a readable file.
    During: the file is read as bytes and hashed without normalizing it.
    After: the exact path bytes produce a deterministic 12-character prefix;
    filesystem errors are allowed to propagate to the CLI error handler.
    """

    return hashlib.sha256(Path(predecessor).read_bytes()).hexdigest()[:12]


def _read_predecessor(predecessor: str | Path) -> str:
    return Path(predecessor).read_text(encoding="utf-8")


def _judgement_spans(text: str) -> dict[str, tuple[int, int]]:
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        raise ValueError("el predecesor no tiene linea de cabecera JUICIO")
    header_end = len(lines[0]) + len(lines[1])
    note_start = text.find("[", len(lines[0]))
    note_end = text.find("\n", note_start)
    note_end = text.rfind("]", note_start, note_end) + 1
    if note_start < 0 or note_end <= note_start:
        raise ValueError("no se encontro ancla de JUICIO nota_derivacion")
    objective = re.search(
        r"\(ARRANQUE_[A-Z]+-\d+_20261108\.md s\.2: .*?\)",
        text[header_end:],
        re.DOTALL,
    )
    if objective is None:
        raise ValueError("no se encontro ancla de JUICIO objetivo_en_curso")
    objective_start = header_end + objective.start()
    objective_end = header_end + objective.end()
    return {
        "nota_derivacion": (note_start, note_end),
        "objetivo_en_curso": (objective_start, objective_end),
    }


def _derive_predecessor(
    text: str, cascade_start: int, cascade_end: int
) -> dict[str, Any]:
    own_match = re.search(
        r"Eres (CO-\d+), sesion coordinadora ACTIVA.*?tu hilo es (mcp:[0-9a-f-]+),",
        text,
        re.DOTALL,
    )
    supervisor_match = re.search(r"Tu supervisora es (CO-\d+) \((mcp:[0-9a-f-]+)", text)
    step9_match = re.search(r"(?m)^9\. Contexto propio:.*$", text)
    if own_match is None or supervisor_match is None or step9_match is None:
        raise ValueError("identidades o paso 9 no derivables del predecesor")
    go_match = re.search(
        r"fila b(\d+) de diseno/GO_RELEVO_24H_REGISTRO\.md", step9_match.group(0)
    )
    if go_match is None:
        raise ValueError("go_index_predecesor no derivable del paso 9")
    cascade_match = re.match(
        r"(CO-\d+) \((mcp:[0-9a-f-]+)\)", text[cascade_start:cascade_end]
    )
    if cascade_match is None:
        raise ValueError("primer elemento de cascada no derivable")
    own_anchor = f"ARRANQUE_{own_match.group(1)} s.1"
    own_anchor_end = text.find(own_anchor)
    if own_anchor_end < 0:
        raise ValueError("ancla R2b de ARRANQUE no encontrada")
    post_start = own_anchor_end + len(own_anchor)
    if text[post_start : post_start + 3] == " y ":
        post_start += 1
    if text[post_start : post_start + 2] != "y ":
        raise ValueError("ancla R2b 'y ' no encontrada")
    post_end = text.find(" (procedimiento de ticket", post_start)
    if post_end < 0:
        raise ValueError("ancla final R2b no encontrada")
    return {
        "own_code": own_match.group(1),
        "own_id": own_match.group(2),
        "supervisor_code": supervisor_match.group(1),
        "supervisor_id": supervisor_match.group(2),
        "go_index": int(go_match.group(1)),
        "cascade_code": cascade_match.group(1),
        "cascade_id": cascade_match.group(2),
        "post_span": (post_start, post_end),
    }


def _roster_values(
    roster: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str], list[str]]:
    errors: list[str] = []
    locations = (
        ("active_roles.orquestador", roster.get("active_roles", {}).get("orquestador")),
        ("active_roles.supervisor", roster.get("active_roles", {}).get("supervisor")),
        ("cadena_contexto[0]", (roster.get("cadena_contexto") or [None])[0]),
    )
    values: list[dict[str, str]] = []
    for location, value in locations:
        if not isinstance(value, dict):
            errors.append(f"campo de roster no consumido: objeto ausente en {location}")
            values.append({})
            continue
        extra = sorted(set(value) - {"threadId", "session_code"})
        missing = sorted({"threadId", "session_code"} - set(value))
        errors.extend(
            f"campo de roster no consumido: {key} en {location}" for key in extra
        )
        errors.extend(
            f"campo de roster ausente: {key} en {location}" for key in missing
        )
        values.append(value)
    return values[0], values[1], values[2], errors


def _replace_outside(
    text: str, spans: list[tuple[int, int]], old: str, new: str
) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        pieces.append(text[cursor:start].replace(old, new))
        pieces.append(text[start:end])
        cursor = end
    pieces.append(text[cursor:].replace(old, new))
    return "".join(pieces)


def render_latido(  # noqa: C901
    predecessor: str | Path,
    roster: dict[str, Any],
    go_index: int,
    juicios: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Render the successor heartbeat according to the closed derivation rules.

    Before: see the module contract; the input mapping is not modified.
    During: validates roster shape and ids, measures R2/R3 anchors, applies
    R1-R4 outside protected spans, and fills or marks both JUICIO spans.
    After: returns the rendered UTF-8 text and rc 0, 2, or 3 as documented;
    malformed input is reported as a plain ``DIFERENCIAS:`` diagnostic.
    """

    problems: list[str] = []
    try:
        text = _read_predecessor(predecessor)
        own, supervisor, context, roster_errors = _roster_values(roster)
        problems.extend(roster_errors)
        if any(
            set(value) != {"threadId", "session_code"}
            for value in (own, supervisor, context)
        ):
            return 2, _failure(text, problems)

        cascade_anchor_count = text.count(_CASCADE_START)
        if cascade_anchor_count != 1:
            problems.append(f"regla R2: esperado 1, encontrado {cascade_anchor_count}")
        cascade_start = text.find(_CASCADE_START) + len(_CASCADE_START)
        cascade_end = text.find(_CASCADE_END, cascade_start)
        if cascade_start < len(_CASCADE_START) or cascade_end < 0:
            problems.append("regla R2: anclas de cascada incompletas")
            cascade_start = cascade_end = 0
        derived = _derive_predecessor(text, cascade_start, cascade_end)
        r6_anchor = f"ARRANQUE_{derived['own_code']} s.1"
        r6_count = text.count(r6_anchor)
        if r6_count != 1:
            problems.append(f"regla R6: esperado 1, encontrado {r6_count}")
        if (
            derived["supervisor_code"] != context["session_code"]
            or derived["supervisor_id"] != context["threadId"]
        ):
            problems.append(
                "roster.cadena_contexto[0] no coincide con la identidad de supervisora "
                "citada en el predecesor"
            )
        spans = [(cascade_start, cascade_end), derived["post_span"]]
        judgement_spans = _judgement_spans(text)
        spans.extend(judgement_spans.values())

        all_ids = set(re.findall(r"mcp:[0-9a-z-]+", text))
        frozen_ids = set(re.findall(r"mcp:[0-9a-z-]+", text[cascade_start:cascade_end]))
        predecessor_identity_ids = {derived["own_id"], derived["supervisor_id"]}
        roster_ids = {own["threadId"], supervisor["threadId"], context["threadId"]}
        problems.extend(
            f"id mcp ajeno al roster: {item}"
            for item in sorted(
                all_ids - roster_ids - frozen_ids - predecessor_identity_ids
            )
        )

        step9_match = re.search(r"(?m)^9\. Contexto propio:.*$", text)
        if step9_match is None:
            problems.append("regla R3: parrafo del paso 9 ausente")
        else:
            step9 = step9_match.group(0)
            r3_rules = {
                f"Go relevo 24h {derived['go_index']}": 1,
                f"fila b{derived['go_index']}": 1,
                f"Go relevo 24h {derived['go_index'] + 1}": 1,
            }
            for literal, expected in r3_rules.items():
                measured = step9.count(literal)
                if measured != expected:
                    problems.append(
                        f"regla R3 {literal}: esperado {expected}, encontrado {measured}"
                    )

        if problems:
            return 2, _failure(text, problems)

        rendered = _replace_outside(
            text, spans, derived["own_code"], own["session_code"]
        )
        rendered = _replace_outside(
            rendered, spans, derived["supervisor_code"], supervisor["session_code"]
        )
        rendered = _replace_outside(rendered, spans, derived["own_id"], own["threadId"])
        rendered = _replace_outside(
            rendered,
            spans,
            derived["supervisor_id"],
            supervisor["threadId"],
        )
        line9 = re.search(r"(?m)^9\. Contexto propio:.*$", rendered)
        if line9 is None:
            return 2, _failure(
                rendered, ["regla R3: parrafo del paso 9 ausente tras derivacion"]
            )
        step9 = line9.group(0).replace(
            f"Go relevo 24h {derived['go_index']}", "Go relevo 24h __GO_INDEX__"
        )
        step9 = step9.replace(
            f"Go relevo 24h {derived['go_index'] + 1}", "Go relevo 24h __GO_NEXT__"
        )
        step9 = step9.replace("__GO_INDEX__", str(go_index)).replace(
            "__GO_NEXT__", str(go_index + 1)
        )
        step9 = step9.replace(f"fila b{derived['go_index']}", f"fila b{go_index}")
        rendered = rendered[: line9.start()] + step9 + rendered[line9.end() :]

        rendered = "ESTADO: VIGENTE\n" + rendered.split("\n", 1)[1]
        cascade_text = text[cascade_start:cascade_end]
        replacement = (
            f"{context['session_code']} ({context['threadId']}), luego {cascade_text}"
        )
        missing: list[str] = []
        for name, (start, end) in sorted(
            judgement_spans.items(), key=lambda item: item[1][0], reverse=True
        ):
            value = (juicios or {}).get(name)
            if value is None:
                missing.append(name)
                value = f"[[JUICIO:{name}]]"
            rendered = rendered[:start] + value + rendered[end:]
        rendered = rendered.replace(
            f"cascada directa {derived['cascade_code']} ({derived['cascade_id']})",
            f"cascada directa {context['session_code']} ({context['threadId']})",
        )
        rendered = rendered.replace(
            f"o '{derived['cascade_code']}'",
            f"o '{context['session_code']}'",
        )
        rendered_cascade_start = rendered.index(_CASCADE_START) + len(_CASCADE_START)
        rendered_cascade_end = rendered.index(_CASCADE_END, rendered_cascade_start)
        rendered = (
            rendered[:rendered_cascade_start]
            + replacement
            + rendered[rendered_cascade_end:]
        )
        rendered = rendered.replace(
            f"para el salto {own['session_code']} -> {own['session_code']}",
            f"para el salto {own['session_code']} -> {_next_session_code(own['session_code'])}",
        )
        post_text = text[derived["post_span"][0] : derived["post_span"][1]]
        rendered_anchor_end = rendered.index(
            f"ARRANQUE_{own['session_code']} s.1"
        ) + len(f"ARRANQUE_{own['session_code']} s.1")
        rendered_post_start = rendered.index(post_text, rendered_anchor_end)
        rendered_post_end = rendered_post_start + len(post_text)
        section_value = (juicios or {}).get("secciones_postcompactacion_nueva")
        if section_value is None:
            missing.append("secciones_postcompactacion_nueva")
            section_value = "[[JUICIO:secciones_postcompactacion_nueva]]"
        rendered = (
            rendered[:rendered_post_end]
            + f" y PROTOCOLO_POSTCOMPACTACION_{supervisor['session_code']}.md {section_value}"
            + rendered[rendered_post_end:]
        )
        if missing:
            return 3, _failure(
                rendered, [f"hueco de JUICIO no rellenado: {name}" for name in missing]
            )
        return 0, rendered
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        return 2, _failure("", [str(exc)])


def _failure(text: str, problems: list[str]) -> str:
    return text.rstrip("\n") + "\n\nDIFERENCIAS:\n" + "\n".join(problems) + "\n"


def _next_session_code(code: str) -> str:
    match = re.fullmatch(r"(.*?)(\d+)", code)
    if match is None:
        raise ValueError(f"session_code no numerico: {code}")
    return f"{match.group(1)}{int(match.group(2)) + 1}"


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predecessor", required=True, type=Path)
    parser.add_argument("--roster", required=True, type=Path)
    parser.add_argument("--go-index", required=True, type=int)
    parser.add_argument("--juicio", action="append", default=[])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    roster = json.loads(args.roster.read_text(encoding="utf-8"))
    juicios: dict[str, str] = {}
    for item in args.juicio:
        name, separator, path = item.partition("=@")
        if not separator:
            parser.error("--juicio debe tener la forma nombre=@fichero")
        juicios[name] = Path(path).read_text(encoding="utf-8")
    rc, output = render_latido(args.predecessor, roster, args.go_index, juicios)
    if args.out is None:
        sys.stdout.write(output)
    else:
        args.out.write_text(output, encoding="utf-8", newline="")
    return rc


if __name__ == "__main__":
    raise SystemExit(_main())
