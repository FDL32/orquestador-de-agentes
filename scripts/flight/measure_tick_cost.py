"""Before: provide a read-only CLI for measuring Claude transcript pulses.

During: parse only user, assistant, and system records, calculate pulse costs,
inventory the supplied heartbeat text, or compare two measurement artifacts.
Inventory historical blocks start at each ``[HISTORICO]`` marker and end at the
next marker; the last one ends at its line end. References and protocol names
are classified only outside those spans. ``resto`` is the byte complement of
the three classified unions.

After: write exactly one new JSON artifact requested by ``--out`` and return
zero, or fail closed with return code two.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any


PULSE_RE = re.compile(r"^\s*LATIDO (?:SUPERVISION )?CO-(\d+)\b")
DEFAULT_CACHE_READ_WEIGHT = 0.1
DEFAULT_FRESH_WEIGHT = 1.0
DEFAULT_CACHE_COLD_THRESHOLD = 100_000
METRICS = (
    "llamadas",
    "vueltas",
    "salida",
    "ctx0",
    "ctx1",
    "crecimiento",
    "fresco",
    "cache_read",
)


def _json_lines(path: Path) -> list[dict[str, Any]]:
    """Before: receive one JSONL transcript path.

    During: read and validate every line as a JSON object.

    After: return the ordered record list or raise a value error.
    """
    try:
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{number}: registro no es objeto")
                records.append(value)
        return records
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"no se puede leer {path}: {exc}") from exc


def _content_text(content: Any) -> str:
    """Before: receive tool-result content in any supported JSON shape.

    During: concatenate textual list blocks or serialize non-text blocks.

    After: return the exact text whose UTF-8 bytes are measured.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                pieces.append(str(block["text"]))
            elif isinstance(block, str):
                pieces.append(block)
            else:
                pieces.append(
                    json.dumps(block, ensure_ascii=False, separators=(",", ":"))
                )
        return "".join(pieces)
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _tool_result_sizes(value: Any) -> tuple[int, int]:
    """Before: receive a tool-result content value.

    During: encode its complete text and its first line as UTF-8.

    After: return total and first-line byte counts.
    """
    raw = _content_text(value).encode("utf-8")
    return len(raw), len(raw.split(b"\n", 1)[0])


def _timestamp(value: Any) -> dt.datetime:
    """Before: receive an ISO timestamp.

    During: normalize a trailing Z and parse it.

    After: return an aware datetime or raise a value error.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp ISO ausente")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"timestamp ISO invalido: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _label(folder: Path) -> str:
    """Before: receive a project directory.

    During: derive a stable label from its final useful path component.

    After: return the folder label without inventing a business account.
    """
    return folder.name or folder.parent.name


def _state_windows(path: Path | None) -> list[tuple[dt.datetime, dt.datetime, str]]:
    """Before: receive an optional state-window file.

    During: validate JSON shape, states, and strict ISO ordering.

    After: return validated half-open windows, or an empty list when omitted.
    """
    if path is None:
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"estados invalido: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("ventanas"), list):
        raise ValueError("estados requiere ventanas")
    windows: list[tuple[dt.datetime, dt.datetime, str]] = []
    for item in value["ventanas"]:
        if not isinstance(item, dict) or item.get("estado") not in {"activo", "reposo"}:
            raise ValueError("estado invalido")
        start = _timestamp(item.get("desde"))
        end = _timestamp(item.get("hasta"))
        if start >= end:
            raise ValueError("ventana desde>=hasta")
        windows.append((start, end, item["estado"]))
    return windows


def _pulse_state(
    stamp: dt.datetime, windows: list[tuple[dt.datetime, dt.datetime, str]]
) -> str:
    """Before: receive a pulse timestamp and validated state windows.

    During: find the window containing the timestamp.

    After: return active, resting, or unknown without inference.
    """
    for start, end, state in windows:
        if start <= stamp < end:
            return state
    return "desconocido"


def _usage(record: dict[str, Any]) -> tuple[str, dict[str, int]] | None:
    """Before: receive an assistant record.

    During: ignore synthetic/no-usage assistants and validate required usage.

    After: return model and integer usage components, or None when excluded.
    """
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    model = message.get("model")
    usage = message.get("usage")
    if model == "<synthetic>" or not isinstance(usage, dict):
        return None
    if "input_tokens" not in usage:
        raise ValueError("usage sin input_tokens")
    keys = (
        "input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "output_tokens",
    )
    values: dict[str, int] = {}
    for key in keys:
        value = usage.get(key, 0)
        if not isinstance(value, int):
            raise ValueError(f"usage invalido: {key}")
        values[key] = value
    return str(model or "desconocido"), values


def _deduplicate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Before: receive bounded transcript records.

    During: retain the first record for every non-empty ``message.id`` while
    preserving records without an id because they cannot be proven duplicates.

    After: return records in transcript order without repeated messages.
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        message = record.get("message")
        message_id = message.get("id") if isinstance(message, dict) else None
        if message_id is not None:
            key = str(message_id)
            if key in seen:
                continue
            seen.add(key)
        unique.append(record)
    return unique


def _pulse(  # noqa: C901
    records: list[dict[str, Any]],
    folder: Path,
    windows: list[tuple[dt.datetime, dt.datetime, str]],
    cache_read_weight: float = DEFAULT_CACHE_READ_WEIGHT,
    fresh_weight: float = DEFAULT_FRESH_WEIGHT,
) -> dict[str, Any]:
    """Before: receive one pulse's bounded records.

    During: calculate usage, tool sizes, model, timestamps, and compact state.

    After: return one complete pulse mapping, including nulls for absent data.
    """
    records = _deduplicate_records(records)
    opening = records[0]
    message = opening.get("message", {})
    stamp = _timestamp(opening.get("timestamp"))
    match = PULSE_RE.match(message.get("content", ""))
    if match is None:
        raise ValueError("pulso sin CO")
    co = int(match.group(1))
    usages: list[tuple[str, dict[str, int]]] = []
    tools: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    compact = any(
        record.get("type") == "system" and record.get("subtype") == "compact_boundary"
        for record in records
    )
    for record in records:
        if record.get("type") == "assistant":
            used = _usage(record)
            if used is not None:
                usages.append(used)
            content = record.get("message", {}).get("content", [])
            if isinstance(content, list):
                tools.extend(
                    block
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "tool_use"
                )
        if record.get("type") == "user":
            content = record.get("message", {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and "tool_use_id" in block
                        and "content" in block
                    ):
                        results[str(block["tool_use_id"])] = block["content"]
    model = usages[0][0] if usages else "desconocido"
    input_values = [
        item[1]["input_tokens"]
        + item[1]["cache_read_input_tokens"]
        + item[1]["cache_creation_input_tokens"]
        for item in usages
    ]
    orders: list[dict[str, Any]] = []
    for tool in tools:
        sizes = (
            _tool_result_sizes(results[tool["id"]])
            if str(tool.get("id")) in results
            else (None, None)
        )
        orders.append(
            {
                "tool": str(tool.get("name", tool.get("tool", "desconocido"))),
                "bytes_totales": sizes[0],
                "bytes_primera_linea": sizes[1],
            }
        )
    pulse: dict[str, Any] = {
        "co": co,
        "cuenta": _label(folder),
        "modelo": model,
        "llamadas": len(tools),
        "vueltas": len(usages),
        "salida": sum(item[1]["output_tokens"] for item in usages),
        "ctx0": input_values[0] if input_values else None,
        "ctx1": input_values[-1] if input_values else None,
        "crecimiento": None
        if compact or not input_values
        else input_values[-1] - input_values[0],
        "fresco": sum(
            item[1]["input_tokens"] + item[1]["cache_creation_input_tokens"]
            for item in usages
        ),
        "cache_read": sum(item[1]["cache_read_input_tokens"] for item in usages),
        "coste_ponderado": sum(
            item[1]["input_tokens"] + item[1]["cache_creation_input_tokens"]
            for item in usages
        )
        * fresh_weight
        + sum(item[1]["cache_read_input_tokens"] for item in usages)
        * cache_read_weight,
        "timestamp": opening.get("timestamp"),
        "estado": _pulse_state(stamp, windows),
        "compact_boundary": compact,
        "estado_tick": "despierta"
        if not usages
        else "quieto"
        if len(tools) <= 1
        else "activo",
        "ordenes": orders,
    }
    return pulse


def _fingerprint(folder: Path) -> tuple[tuple[str, int], ...]:
    """Before: receive a transcript directory.

    During: collect relative names and byte sizes without reading contents.

    After: return a comparable deterministic content-shape fingerprint.
    """
    return tuple(
        sorted(
            (str(path.relative_to(folder)), path.stat().st_size)
            for path in folder.rglob("*")
            if path.is_file()
        )
    )


def _read_measurement(  # noqa: C901
    folders: list[Path],
    co_from: int | None,
    co_to: int | None,
    windows: list[tuple[dt.datetime, dt.datetime, str]],
    cache_read_weight: float = DEFAULT_CACHE_READ_WEIGHT,
    fresh_weight: float = DEFAULT_FRESH_WEIGHT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], bool, int, int]:
    """Before: receive validated folders and filters.

    During: deduplicate real paths, read JSONL sessions, and bound pulses by user openings.

    After: return pulses, session accounting, notices, identical-content status,
    and pulse/no-response denominators.
    """
    pulses: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    notices: list[str] = []
    total_candidates = 0
    no_response = 0
    seen: dict[str, str] = {}
    actual: list[Path] = []
    for folder in folders:
        real = os.path.realpath(folder)
        if real in seen:
            notices.append(f"{folder}: duplicada de {seen[real]}: no leida")
        else:
            seen[real] = str(folder)
            actual.append(folder)
    fingerprints = [_fingerprint(folder) for folder in actual]
    identical = len(fingerprints) > 1 and len(set(fingerprints)) == 1
    if identical:
        notices.append("carpetas con identico contenido: no sumar")
    for folder in actual:
        for path in sorted(folder.rglob("*.jsonl")):
            records = _deduplicate_records(_json_lines(path))
            boundaries = [
                index
                for index, record in enumerate(records)
                if record.get("type") == "user"
                and not (
                    isinstance(record.get("message", {}).get("content"), list)
                    and any(
                        isinstance(block, dict) and block.get("type") == "tool_result"
                        for block in record["message"]["content"]
                    )
                )
            ]
            starts = [
                index
                for index in boundaries
                if isinstance(records[index].get("message", {}).get("content"), str)
                and PULSE_RE.match(records[index]["message"]["content"])
            ]
            session_total = 0
            session_pulse = 0
            usage_pulses = 0
            previous_stamp: dt.datetime | None = None
            compactation_before = False
            for record in records:
                if record.get("type") != "assistant":
                    continue
                used = _usage(record)
                if used is not None:
                    session_total += used[1]["cache_read_input_tokens"]
            for start in starts:
                end = next(
                    (boundary for boundary in boundaries if boundary > start),
                    len(records),
                )
                pulse_records = records[start:end]
                opening_content = records[start]["message"]["content"]
                opening_match = PULSE_RE.match(opening_content)
                if opening_match is None:
                    raise ValueError("pulso sin CO")
                co = int(opening_match.group(1))
                if (co_from is not None and co < co_from) or (
                    co_to is not None and co > co_to
                ):
                    continue
                pulse_usages = [
                    used
                    for record in _deduplicate_records(pulse_records)
                    if record.get("type") == "assistant"
                    for used in [_usage(record)]
                    if used is not None
                ]
                session_pulse += sum(
                    used[1]["cache_read_input_tokens"] for used in pulse_usages
                )
                usage_pulses += bool(pulse_usages)
                total_candidates += 1
                if not pulse_usages:
                    no_response += 1
                pulse = _pulse(
                    pulse_records,
                    folder,
                    windows,
                    cache_read_weight,
                    fresh_weight,
                )
                stamp = _timestamp(pulse["timestamp"])
                pulse["segundos_desde_pulso_anterior"] = (
                    None
                    if previous_stamp is None
                    else int((stamp - previous_stamp).total_seconds())
                )
                pulse["compactacion_previa"] = compactation_before
                previous_stamp = stamp
                compactation_before = compactation_before or pulse["compact_boundary"]
                pulses.append(pulse)
            sessions.append(
                {
                    "fichero": str(path),
                    "cache_read_total": session_total,
                    "cache_read_pulsos": session_pulse,
                    "fraccion": session_pulse / session_total
                    if session_total
                    else None,
                    "pulsos": usage_pulses,
                }
            )
    return pulses, sessions, notices, identical, total_candidates, no_response


def _percentile(values: list[int], minimum: int = 5) -> int | None:
    """Before: receive numeric observations.

    During: apply the ticket's minimum sample and indexed p90 rule.

    After: return null below five observations or the ordered p90 value.
    """
    if len(values) < minimum:
        return None
    return sorted(values)[int(0.9 * (len(values) - 1))]


def _aggregate(pulses: list[dict[str, Any]]) -> dict[str, Any]:
    """Before: receive a pulse group.

    During: calculate n, median, and p90 for every measured numeric field.

    After: return a self-describing aggregate mapping.
    """
    result: dict[str, Any] = {
        "n": len(pulses),
        "alcance": {
            "carpetas": sorted({p["cuenta"] for p in pulses}),
            "co": sorted({p["co"] for p in pulses}),
            "modelos": sorted({p["modelo"] for p in pulses}),
        },
    }
    responsive = [pulse for pulse in pulses if pulse.get("vueltas", 0) > 0]
    result["n"] = len(responsive)
    for metric in METRICS:
        values = [
            pulse[metric] for pulse in responsive if isinstance(pulse.get(metric), int)
        ]
        result[metric] = {
            "n": len(values),
            "mediana": statistics.median(values) if values else None,
            "p90": _percentile(values),
        }
    return result


def _group_aggregates(pulses: list[dict[str, Any]]) -> dict[str, Any]:
    """Before: receive all measured pulses.

    During: partition by the required global, CO, account, model, and account-model keys.

    After: return all aggregate groups with stable string keys.
    """
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        "global": {"global": pulses},
        "por_co": {},
        "por_cuenta": {},
        "por_modelo": {},
        "por_cuenta_modelo": {},
    }
    for pulse in pulses:
        for name, key in (
            ("por_co", str(pulse["co"])),
            ("por_cuenta", pulse["cuenta"]),
            ("por_modelo", pulse["modelo"]),
            ("por_cuenta_modelo", f"{pulse['cuenta']}|{pulse['modelo']}"),
        ):
            groups[name].setdefault(key, []).append(pulse)
    return {
        name: (
            {key: _aggregate(value) for key, value in group.items()}
            if name != "global"
            else _aggregate(pulses)
        )
        for name, group in groups.items()
    }


def _inventory(path: Path) -> dict[str, Any]:
    """Before: receive a heartbeat markdown file.

    During: classify UTF-8 byte spans for historical blocks, references, and protocol names.

    After: return class bytes, counts, unique references, and the byte complement.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"no se puede leer inventario: {exc}") from exc
    encoded = text.encode("utf-8")
    historical: list[tuple[int, int]] = []
    marks = list(re.finditer(r"\[HISTORICO\]", text))
    for index, mark in enumerate(marks):
        end = (
            marks[index + 1].start()
            if index + 1 < len(marks)
            else text.find("\n", mark.end())
        )
        if end < 0:
            end = len(text)
        historical.append(
            (len(text[: mark.start()].encode()), len(text[:end].encode()))
        )
    occupied = [False] * len(encoded)
    for start, end in historical:
        for index in range(start, end):
            occupied[index] = True
    refs = list(re.finditer(r"CO-\d+ \(mcp:[0-9a-fA-F-]+\)", text))
    protocols = list(re.finditer(r"PROTOCOLO_POSTCOMPACTACION_CO-\d+\.md", text))
    ref_spans: list[tuple[int, int]] = []
    protocol_spans: list[tuple[int, int]] = []
    for match, target in [(match, ref_spans) for match in refs] + [
        (match, protocol_spans) for match in protocols
    ]:
        start = len(text[: match.start()].encode())
        end = len(text[: match.end()].encode())
        if not any(occupied[start:end]):
            target.append((start, end))
            for index in range(start, end):
                occupied[index] = True
    hist_bytes = sum(end - start for start, end in historical)
    ref_bytes = sum(end - start for start, end in ref_spans)
    protocol_bytes = sum(end - start for start, end in protocol_spans)
    return {
        "total_bytes": len(encoded),
        "por_clase": {
            "historico": {"bytes": hist_bytes, "ocurrencias": len(historical)},
            "referencias": {"bytes": ref_bytes, "ocurrencias": len(ref_spans)},
            "protocolo": {"bytes": protocol_bytes, "ocurrencias": len(protocol_spans)},
        },
        "referencias": {
            "total": len(refs),
            "unicas": len(set(match.group(0) for match in refs)),
        },
        "n_bloques_historico": len(historical),
        "resto_bytes": len(encoded) - hist_bytes - ref_bytes - protocol_bytes,
    }


def _comparison(current: Path, candidate: Path) -> dict[str, Any]:
    """Before: receive two measurement artifacts.

    During: pair pulse groups by state, account, model, and context tranche.

    After: return per-state threshold verdicts and global comparability.
    """
    try:
        left = json.loads(current.read_text(encoding="utf-8"))["pulsos"]
        right = json.loads(candidate.read_text(encoding="utf-8"))["pulsos"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"comparacion invalida: {exc}") from exc
    states: dict[str, Any] = {}
    for state in ("activo", "reposo"):
        groups: dict[
            tuple[Any, ...], tuple[list[dict[str, Any]], list[dict[str, Any]]]
        ] = {}
        for side, pulses in enumerate((left, right)):
            for pulse in pulses:
                if pulse.get("estado") != state:
                    continue
                key = (
                    pulse.get("cuenta"),
                    pulse.get("modelo"),
                    (pulse.get("ctx0") or 0) // 100000,
                )
                if key not in groups:
                    groups[key] = ([], [])
                groups[key][side].append(pulse)
        paired: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for left_group, right_group in groups.values():
            paired.extend(zip(left_group, right_group, strict=False))
        if len(paired) < 30:
            states[state] = {"veredicto": "INSUFICIENTE"}
            continue
        left_turns = [pair[0]["vueltas"] for pair in paired]
        right_turns = [pair[1]["vueltas"] for pair in paired]
        left_cache = [pair[0]["cache_read"] for pair in paired]
        right_cache = [pair[1]["cache_read"] for pair in paired]
        lv = statistics.median(left_turns)
        rv = statistics.median(right_turns)
        lc = statistics.median(left_cache)
        rc = statistics.median(right_cache)
        states[state] = {
            "pares": len(paired),
            "mediana_vigente_vueltas": lv,
            "mediana_candidato_vueltas": rv,
            "diff_vueltas": rv - lv,
            "mediana_vigente_cache_read": lc,
            "mediana_candidato_cache_read": rc,
            "diff_cache_read": rc - lc,
            "veredicto": "COMPARABLE",
        }
    return {
        **states,
        "veredicto": "COMPARABLE"
        if all(
            states[state]["veredicto"] == "COMPARABLE" for state in ("activo", "reposo")
        )
        else "INSUFICIENTE",
    }


def _parser() -> argparse.ArgumentParser:
    """Before: no arguments have been parsed.

    During: define mutually exclusive measurement, inventory, and comparison modes.

    After: return the configured argparse parser.
    """
    parser = argparse.ArgumentParser(prog="measure_tick_cost")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--project-dir", action="append")
    modes.add_argument("--inventario")
    modes.add_argument("--comparar", nargs=2, metavar=("VIGENTE", "CANDIDATO"))
    parser.add_argument("--co-from", type=int)
    parser.add_argument("--co-to", type=int)
    parser.add_argument("--estados")
    parser.add_argument(
        "--peso-cache-read", type=float, default=DEFAULT_CACHE_READ_WEIGHT
    )
    parser.add_argument("--peso-fresco", type=float, default=DEFAULT_FRESH_WEIGHT)
    parser.add_argument(
        "--cache-fria-umbral", type=int, default=DEFAULT_CACHE_COLD_THRESHOLD
    )
    parser.add_argument("--out")
    return parser


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    """Before: receive CLI arguments for one measurement operation.

    During: validate the selected mode, create exactly one output, and dispatch it.

    After: return zero on success and two for all usage, I/O, or data errors.
    """
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if not args.out or Path(args.out).exists():
            raise ValueError("--out obligatorio y de creacion exclusiva")
        modes = sum(
            value is not None
            for value in (args.project_dir, args.inventario, args.comparar)
        )
        if modes != 1:
            raise ValueError("exactamente un modo")
        if args.inventario and (
            args.co_from is not None or args.co_to is not None or args.estados
        ):
            raise ValueError("opciones de medida fuera de modo medida")
        if args.comparar and (
            args.co_from is not None or args.co_to is not None or args.estados
        ):
            raise ValueError("opciones de medida fuera de modo comparador")
        if (
            args.co_from is not None
            and args.co_to is not None
            and args.co_from > args.co_to
        ):
            raise ValueError("rango CO invalido")
        out = Path(args.out)
        if args.inventario:
            artifact = {"inventario": _inventory(Path(args.inventario))}
        elif args.comparar:
            artifact = {
                "comparacion": _comparison(
                    Path(args.comparar[0]), Path(args.comparar[1])
                )
            }
        else:
            folders = [Path(folder) for folder in args.project_dir]
            if not all(folder.is_dir() for folder in folders):
                raise ValueError("carpeta inexistente")
            windows = _state_windows(Path(args.estados) if args.estados else None)
            pulses, sessions, notices, identical, total_candidates, no_response = (
                _read_measurement(
                    folders,
                    args.co_from,
                    args.co_to,
                    windows,
                    args.peso_cache_read,
                    args.peso_fresco,
                )
            )
            compacted = sum(1 for pulse in pulses if pulse["compact_boundary"])
            accounts = [folder for folder in folders]
            real_accounts = {os.path.realpath(folder) for folder in accounts}
            non_separable = len(accounts) > 1 and (
                identical or len(real_accounts) < len(accounts)
            )
            account = (
                "n/a"
                if non_separable
                else ("separable" if len(accounts) > 1 else _label(accounts[0]))
            )
            meta = {
                "carpetas_leidas": [str(folder) for folder in folders] + notices,
                "rango_co": {
                    "min": min((pulse["co"] for pulse in pulses), default=None),
                    "max": max((pulse["co"] for pulse in pulses), default=None),
                },
                "modelos": sorted({pulse["modelo"] for pulse in pulses}),
                "n": total_candidates,
                "n_sin_respuesta": no_response,
                "n_compactados": compacted,
                "cuenta": account,
                "sesiones": sessions,
                "pesos_coste": {
                    "cache_read": args.peso_cache_read,
                    "fresco": args.peso_fresco,
                },
            }
            if non_separable:
                meta["cuenta_motivo"] = "cuenta no separable"
            artifact = {
                "meta": meta,
                "pulsos": pulses,
                "agregados": _group_aggregates(pulses),
                "cache_fria": {
                    "umbral_fresco_tokens": args.cache_fria_umbral,
                    "pulsos": [
                        {
                            "co": pulse["co"],
                            "timestamp": pulse["timestamp"],
                            "fresco": pulse["fresco"],
                            "coste_ponderado": pulse["coste_ponderado"],
                            "segundos_desde_pulso_anterior": pulse[
                                "segundos_desde_pulso_anterior"
                            ],
                            "compactacion_previa": pulse["compactacion_previa"],
                        }
                        for pulse in pulses
                        if pulse["fresco"] >= args.cache_fria_umbral
                    ],
                },
            }
            qualifying = [
                session["fraccion"]
                for session in sessions
                if session["pulsos"] >= 3 and session["fraccion"] is not None
            ]
            artifact["agregados"]["m11"] = {
                "n": len(qualifying),
                "mediana": statistics.median(qualifying)
                if len(qualifying) >= 5
                else None,
            }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"n={artifact.get('meta', {}).get('n', 'n/a')} alcance={artifact.get('meta', {}).get('carpetas_leidas', 'n/a')}"
        )
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
