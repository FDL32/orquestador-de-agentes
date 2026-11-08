"""Derive the next flight heartbeat from a predecessor and a reduced roster.

Before: ``predecessor`` must be a UTF-8 heartbeat file with the documented
anchors, ``roster`` must contain exactly the three consumed roster objects, and
``go_index`` must be the successor's positive Go number.

During: the renderer validates the closed rule counts, preserves the cascade
and postcompaction tails byte-for-byte, derives own/supervisor identities
outside protected judgement and insertion spans, updates the step-9 Go
references, forces the status line, and replaces the three judgement values.  It can also calculate the
predecessor path's SHA-256 prefix with :func:`predecessor_sha12` for a
judgement supplied by a caller.

The input ``roster`` is the reduced three-object form: ``active_roles.orquestador``,
``active_roles.supervisor``, and ``cadena_contexto[0]`` with ``threadId`` and
``session_code``.  A real ``flight_roster.json`` (with ``since``, ``set_by``,
``estado``, ``version``, and other fields) must be reduced before calling this
function; passing it as-is returns rc 2.  The trigger is declared for the
saliente coordinator in its paquete de relevo; the lifecycle of scheduled tasks
(creating its own and deleting the predecessor's) is not part of this
specification.

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
    with Path(predecessor).open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _judgement_spans(text: str) -> dict[str, tuple[int, int]]:
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        raise ValueError("el predecesor no tiene linea de cabecera JUICIO")
    header_end = len(lines[0]) + len(lines[1])
    note_start = len(lines[0])
    note_end = text.find("\n", note_start)
    note_end = text.rfind("]", note_start, note_end) + 1
    if note_start < 0 or note_end <= note_start:
        raise ValueError("no se encontro ancla de JUICIO nota_derivacion")
    objective = re.search(
        r"\(ARRANQUE_[A-Z]+-\d+_\d{8}\.md s\.2: .*?\)",
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
        r"Eres (CO-\d+), sesion coordinadora ACTIVA.*?tu hilo es (mcp:[0-9A-Za-z-]+),",
        text,
        re.DOTALL,
    )
    supervisor_match = re.search(
        r"Tu supervisora es (CO-\d+) \((mcp:[0-9A-Za-z-]+)", text
    )
    step9_match = re.search(r"(?m)^9\. Contexto propio:.*$", text)
    if own_match is None or supervisor_match is None or step9_match is None:
        raise ValueError("identidades o paso 9 no derivables del predecesor")
    go_match = re.search(
        r"fila b(\d+) de diseno/GO_RELEVO_24H_REGISTRO\.md", step9_match.group(0)
    )
    if go_match is None:
        raise ValueError("go_index_predecesor no derivable del paso 9")
    cascade_match = re.match(
        r"(CO-\d+) \((mcp:[0-9A-Za-z-]+)\)", text[cascade_start:cascade_end]
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
    if not isinstance(roster, dict):
        return {}, {}, {}, ["campo de roster no consumido: roster debe ser dict"]
    if set(roster) != {"active_roles", "cadena_contexto"}:
        errors.append(
            "campo de roster no consumido: raiz debe contener exactamente "
            "active_roles y cadena_contexto"
        )
    active_roles = roster.get("active_roles")
    if not isinstance(active_roles, dict):
        errors.append("campo de roster no consumido: active_roles debe ser dict")
        active_roles = {}
    elif set(active_roles) != {"orquestador", "supervisor"}:
        errors.append(
            "campo de roster no consumido: active_roles debe contener exactamente "
            "orquestador y supervisor"
        )
    cadena_contexto = roster.get("cadena_contexto")
    if not isinstance(cadena_contexto, list):
        errors.append("campo de roster no consumido: cadena_contexto debe ser list")
        cadena_contexto = []
    elif len(cadena_contexto) != 1:
        errors.append(
            "campo de roster no consumido: cadena_contexto debe tener longitud 1"
        )
    locations = (
        ("active_roles.orquestador", active_roles.get("orquestador")),
        ("active_roles.supervisor", active_roles.get("supervisor")),
        ("cadena_contexto[0]", cadena_contexto[0] if cadena_contexto else None),
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
        errors.extend(
            f"campo de roster no consumido: {key} en {location} debe ser str no vacío"
            for key in ("threadId", "session_code")
            if key in value
            and (not isinstance(value[key], str) or not value[key].strip())
        )
        values.append(value)
    return values[0], values[1], values[2], errors


def reduce_roster(real: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Reduce a real flight roster to the three identities consumed here.

    Before: ``real`` must be a JSON-like mapping containing ``active_roles`` and
    ``cadena_contexto``.
    During: root and location metadata are checked against the closed lists of
    known non-consumed fields; the first context entry is projected to identity.
    After: returns the exact reduced roster and no errors, or ``None`` and plain
    diagnostics for missing or unknown schema fields.  The input is not mutated.
    """

    errors: list[str] = []
    if not isinstance(real, dict):
        return None, ["campo de roster no consumido: roster debe ser dict"]
    known_root = {
        "schema_version",
        "flight_id",
        "updated_at",
        "updated_by",
        "rules",
        "session_types",
        "sessions",
        "capacity",
        "excluded_lenses",
        "quota",
        "quarantine",
        "roster_fixes",
        "cadena_contexto",
        "active_roles",
    }
    errors.extend(
        f"campo de roster no consumido: {key} en raiz"
        for key in sorted(set(real) - known_root)
    )
    active_roles = real.get("active_roles")
    if not isinstance(active_roles, dict):
        errors.append("campo de roster no consumido: active_roles debe ser dict")
        active_roles = {}
    errors.extend(
        f"campo de roster no consumido: {key} en active_roles"
        for key in sorted(
            set(active_roles) - {"orquestador", "supervisor", "_schema_note"}
        )
    )
    known_role_metadata = {
        "since",
        "set_by",
        "predecessor_threadId",
        "version",
        "status",
        "approved_by",
        "nota",
        "estado",
    }
    reduced_roles: dict[str, dict[str, Any]] = {}
    for name in ("orquestador", "supervisor"):
        value = active_roles.get(name)
        location = f"active_roles.{name}"
        if not isinstance(value, dict):
            errors.append(f"campo de roster no consumido: objeto ausente en {location}")
            continue
        errors.extend(
            f"campo de roster no consumido: {key} en {location}"
            for key in sorted(
                set(value) - {"threadId", "session_code"} - known_role_metadata
            )
        )
        reduced_roles[name] = {
            key: value[key] for key in ("threadId", "session_code") if key in value
        }
    context = real.get("cadena_contexto")
    if not isinstance(context, list) or not context:
        errors.append(
            "campo de roster no consumido: cadena_contexto debe tener al menos un elemento"
        )
        context_value: Any = None
    else:
        context_value = context[0]
    if not isinstance(context_value, dict):
        errors.append(
            "campo de roster no consumido: objeto ausente en cadena_contexto[0]"
        )
        reduced_context: dict[str, Any] = {}
    else:
        known_context_metadata = {"hasta", "cerrado_por"}
        errors.extend(
            f"campo de roster no consumido: {key} en cadena_contexto[0]"
            for key in sorted(
                set(context_value)
                - {"threadId", "session_code"}
                - known_context_metadata
            )
        )
        reduced_context = {
            key: context_value[key]
            for key in ("threadId", "session_code")
            if key in context_value
        }
    reduced = {
        "active_roles": reduced_roles,
        "cadena_contexto": [reduced_context],
    }
    if errors:
        return None, errors
    return reduced, []


def _replace_identity_tokens(
    text: str,
    protected: list[tuple[int, int, str]],
    replacements: dict[str, str],
) -> str:
    """Replace identity tokens in original-text gaps and emit protected values."""
    alternatives = "|".join(
        re.escape(old) for old in sorted(replacements, key=len, reverse=True)
    )
    token_pattern = re.compile(rf"(?<![A-Za-z0-9-])({alternatives})(?![A-Za-z0-9-])")

    def replace_match(match: re.Match[str]) -> str:
        return replacements[match.group(1)]

    pieces: list[str] = []
    cursor = 0
    for start, end, value in sorted(protected):
        pieces.append(token_pattern.sub(replace_match, text[cursor:start]))
        pieces.append(value)
        cursor = end
    pieces.append(token_pattern.sub(replace_match, text[cursor:]))
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
    R1-R4 outside protected spans, and fills or marks the three judgement values.
    After: returns the rendered UTF-8 text and rc 0, 2, or 3 as documented;
    malformed input is reported as a plain ``DIFERENCIAS:`` diagnostic.
    """

    problems: list[str] = []
    try:
        if not isinstance(go_index, int) or isinstance(go_index, bool) or go_index < 1:
            return 2, _failure(
                "",
                [f"go_index debe ser entero >= 1, recibido: {go_index}"],
            )
        text = _read_predecessor(predecessor)
        own, supervisor, context, roster_errors = _roster_values(roster)
        problems.extend(roster_errors)
        if problems:
            return 2, _failure(text, problems)

        cascade_anchor_count = text.count(_CASCADE_START)
        if cascade_anchor_count != 1:
            problems.append(f"regla R2: esperado 1, encontrado {cascade_anchor_count}")
        cascade_end_count = text.count(_CASCADE_END)
        if cascade_end_count != 1:
            problems.append(
                f"regla R2b-fin: esperado 1, encontrado {cascade_end_count}"
            )
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
        judgement_spans = _judgement_spans(text)

        all_ids = set(re.findall(r"mcp:[0-9A-Za-z-]+", text))
        frozen_ids = set(
            re.findall(r"mcp:[0-9A-Za-z-]+", text[cascade_start:cascade_end])
        )
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

        missing: list[str] = []
        judgement_values: dict[str, str] = {}
        for name in ("nota_derivacion", "objetivo_en_curso"):
            value = (juicios or {}).get(name)
            if value is None or value.strip() == "" or "[[JUICIO:" in value:
                missing.append(name)
                value = f"[[JUICIO:{name}]]"
            judgement_values[name] = value
        section_value = (juicios or {}).get("secciones_postcompactacion_nueva")
        if (
            section_value is None
            or section_value.strip() == ""
            or "[[JUICIO:" in section_value
        ):
            missing.append("secciones_postcompactacion_nueva")
            section_value = "[[JUICIO:secciones_postcompactacion_nueva]]"

        cascade_text = text[cascade_start:cascade_end]
        cascade_value = (
            f"{context['session_code']} ({context['threadId']}), luego {cascade_text}"
        )
        post_text = text[derived["post_span"][0] : derived["post_span"][1]]
        post_value = (
            f"{post_text} y PROTOCOLO_POSTCOMPACTACION_{supervisor['session_code']}.md "
            f"{section_value}"
        )
        protected = [
            (cascade_start, cascade_end, cascade_value),
            (derived["post_span"][0], derived["post_span"][1], post_value),
            (
                judgement_spans["nota_derivacion"][0],
                judgement_spans["nota_derivacion"][1],
                judgement_values["nota_derivacion"],
            ),
            (
                judgement_spans["objetivo_en_curso"][0],
                judgement_spans["objetivo_en_curso"][1],
                judgement_values["objetivo_en_curso"],
            ),
        ]
        replacements = {
            derived["own_code"]: own["session_code"],
            derived["supervisor_code"]: supervisor["session_code"],
            derived["own_id"]: own["threadId"],
            derived["supervisor_id"]: supervisor["threadId"],
            derived["cascade_code"]: context["session_code"],
            derived["cascade_id"]: context["threadId"],
        }
        rendered = _replace_identity_tokens(text, protected, replacements)
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

        line_ending = "\r\n" if "\r\n" in rendered else "\n"
        rendered = "ESTADO: VIGENTE" + line_ending + rendered.split("\n", 1)[1]
        rendered = rendered.replace(
            f"para el salto {own['session_code']} -> {own['session_code']}",
            f"para el salto {own['session_code']} -> {_next_session_code(own['session_code'])}",
        )
        if missing:
            return 3, _failure(
                rendered, [f"hueco de JUICIO no rellenado: {name}" for name in missing]
            )
        foreign_rendered_ids = sorted(
            set(re.findall(r"mcp:[0-9A-Za-z-]+", rendered)) - roster_ids - frozen_ids
        )
        if foreign_rendered_ids:
            return 2, _failure(
                rendered,
                [
                    f"id mcp ajeno al roster introducido por JUICIO: {item}"
                    for item in foreign_rendered_ids
                ],
            )
        return 0, rendered
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        return 2, _failure("", [*problems, str(exc)])


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
    try:
        roster = json.loads(args.roster.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        sys.stdout.write(_failure("", [f"no se pudo leer --roster: {exc}"]))
        return 2
    roster, reduce_errors = reduce_roster(roster)
    if reduce_errors:
        sys.stdout.write(_failure("", reduce_errors))
        return 2
    juicios: dict[str, str] = {}
    for item in args.juicio:
        name, separator, path = item.partition("=@")
        if not separator:
            parser.error("--juicio debe tener la forma nombre=@fichero")
        try:
            juicios[name] = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            sys.stdout.write(_failure("", [f"no se pudo leer --juicio: {exc}"]))
            return 2
    rc, output = render_latido(args.predecessor, roster, args.go_index, juicios)
    if args.out is None:
        sys.stdout.write(output)
    else:
        try:
            args.out.write_text(output, encoding="utf-8", newline="")
        except (OSError, UnicodeError) as exc:
            sys.stdout.write(_failure("", [f"no se pudo escribir --out: {exc}"]))
            return 2
    return rc


if __name__ == "__main__":
    raise SystemExit(_main())
