"""Before: inspect Claude transcript JSONL files without changing them.

During: aggregate long calls, background windows, raw payload states, and shell counts.
After: emit only deterministic counts, durations, flags, and effective-root declarations.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


LONG_CALL_THRESHOLD_MS = 300_000
CLASS_FOREGROUND = "foreground"
CLASS_BACKGROUND = "fondo"
CLASS_APPROVAL = "aprobacion"
CLASS_UNCLASSIFIED = "NO_CLASIFICADA"
CLASS_ORDER = (CLASS_FOREGROUND, CLASS_BACKGROUND, CLASS_APPROVAL, CLASS_UNCLASSIFIED)
RAW_KEYS = ("session_crons", "background_tasks")
SHELL_TOOLS = ("Bash", "PowerShell")
KEY_PRESENT = "present"
KEY_EMPTY = "empty"
KEY_ABSENT = "absent"
DEFAULT_LIMIT = 200


@dataclass(frozen=True)
class ToolCall:
    """Before: hold one qualifying tool call.

    During: retain its tool, class, and duration values.
    After: provide immutable data for report aggregation.
    """

    tool: str
    class_name: str
    duration_ms: int


@dataclass(frozen=True)
class BackgroundWindow:
    """Before: hold one contiguous background-task run.

    During: retain elapsed milliseconds and the following-user-message flag.
    After: provide immutable data for report aggregation.
    """

    duration_ms: int
    push_after: bool


def resolve_roots(roots: Iterable[Path | str]) -> list[Path]:
    """Before: receive declared transcript roots.

    During: resolve each root and deduplicate by normalized resolved path.
    After: return effective roots in declaration order.
    """
    resolved = []
    seen = set()
    for root in roots:
        path = Path(root).resolve()
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            resolved.append(path)
    return resolved


def iter_transcripts(roots: Iterable[Path | str]) -> list[Path]:
    """Before: receive declared transcript roots.

    During: enumerate sorted JSONL files under deduplicated resolved roots.
    After: return each resolved transcript path once in deterministic order.
    """
    found = []
    seen = set()
    for root in resolve_roots(roots):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            resolved = path.resolve()
            key = os.path.normcase(str(resolved))
            if key not in seen:
                seen.add(key)
                found.append(resolved)
    return sorted(found, key=lambda path: str(path))


def load_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Before: receive one transcript path.

    During: read non-empty JSON lines and skip malformed lines.
    After: return decoded records and the count of discarded invalid JSON lines.
    """
    records = []
    corrupt_lines = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                corrupt_lines += 1
                continue
            if isinstance(value, dict):
                records.append(value)
    return records, corrupt_lines


def classify_tool_call(
    input_payload: dict[str, Any], result_payload: dict[str, Any]
) -> str:
    """Before: receive tool input and result metadata.

    During: apply the contract's background, approval, foreground, and fallback precedence.
    After: return exactly one canonical class name.
    """
    if (
        input_payload.get("run_in_background") is True
        or result_payload.get("isBackground") is True
    ):
        return CLASS_BACKGROUND
    if result_payload.get("permissionDecision") in {"ask", "deny", "denied"}:
        return CLASS_APPROVAL
    if result_payload.get("permissionDecision") in {"allow", "approved", "bypass"}:
        return CLASS_FOREGROUND
    if input_payload.get("run_in_background") is False:
        return CLASS_FOREGROUND
    return CLASS_UNCLASSIFIED


def collect_long_calls(records: list[dict[str, Any]]) -> list[ToolCall]:
    """Before: receive decoded transcript records.

    During: map assistant tool uses to tool results and filter strictly by durationMs.
    After: return qualifying calls, excluding hook attachments without toolUseResult.
    """
    tools = {}
    for record in records:
        if record.get("type") != "assistant":
            continue
        uuid = record.get("uuid")
        message = record.get("message") or {}
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and uuid:
                tools[uuid] = (block.get("name", "unknown"), block.get("input") or {})
    calls = []
    for record in records:
        result = record.get("toolUseResult")
        if not isinstance(result, dict):
            continue
        duration = result.get("durationMs")
        if not isinstance(duration, (int, float)) or duration <= LONG_CALL_THRESHOLD_MS:
            continue
        name, input_payload = tools.get(
            record.get("sourceToolAssistantUUID"), ("unknown", {})
        )
        result_payload = dict(result)
        result_payload.update(
            {key: value for key, value in record.items() if key != "toolUseResult"}
        )
        calls.append(
            ToolCall(
                name, classify_tool_call(input_payload, result_payload), int(duration)
            )
        )
    return calls


def _contains_nonempty_key(value: Any, wanted: str) -> tuple[bool, bool]:
    """Before: receive arbitrary decoded JSON and one target key.

    During: recurse through dictionaries and classify whether the key is empty or non-empty.
    After: return (found, non_empty) without interpreting payload contents.
    """
    found = False
    non_empty = False
    if isinstance(value, dict):
        for key, child in value.items():
            if key == wanted:
                found = True
                if child not in (None, "", [], {}):
                    non_empty = True
            child_found, child_non_empty = _contains_nonempty_key(child, wanted)
            found = found or child_found
            non_empty = non_empty or child_non_empty
    elif isinstance(value, list):
        for child in value:
            child_found, child_non_empty = _contains_nonempty_key(child, wanted)
            found = found or child_found
            non_empty = non_empty or child_non_empty
    return found, non_empty


def session_key(record: dict[str, Any], path: Path) -> str:
    """Before: receive one record and its transcript path.

    During: prefer the record session identifier and fall back to the filename stem.
    After: return a stable printable session key.
    """
    return str(record.get("sessionId") or record.get("session_id") or path.stem)


def merge_raw_state(
    state: dict[str, dict[str, tuple[bool, bool]]],
    session: str,
    key: str,
    found: bool,
    non_empty: bool,
) -> None:
    """Before: receive one raw-key observation and its session accumulator.

    During: merge found and non-empty flags with commutative OR operations without
    retaining the source record.
    After: update the O(sessions * keys) raw state in place, independent of record order.
    """
    session_state = state.setdefault(session, {})
    old_found, old_non_empty = session_state.get(key, (False, False))
    session_state[key] = (old_found or found, old_non_empty or non_empty)


def raw_state_to_states(
    raw_state: dict[str, dict[str, tuple[bool, bool]]],
) -> dict[str, dict[str, str]]:
    """Before: receive incremental raw-key accumulators.

    During: translate each (found, non-empty) pair to its public state.
    After: return present, empty, or absent values without transcript records.
    """
    states = {}
    for session, session_state in raw_state.items():
        states[session] = {}
        for key in RAW_KEYS:
            found, non_empty = session_state.get(key, (False, False))
            states[session][key] = (
                KEY_PRESENT if non_empty else KEY_EMPTY if found else KEY_ABSENT
            )
    return states


def count_shell_calls(records: list[dict[str, Any]]) -> dict[str, int]:
    """Before: receive decoded transcript records.

    During: count assistant tool-use blocks whose names are shell tools.
    After: return counts for Bash and PowerShell, including zero values.
    """
    counts = {name: 0 for name in SHELL_TOOLS}
    for record in records:
        if record.get("type") != "assistant":
            continue
        for block in (record.get("message") or {}).get("content") or []:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") in counts
            ):
                counts[block["name"]] += 1
    return counts


def _timestamp_ms(value: Any) -> int | None:
    """Before: receive a transcript timestamp.

    During: parse ISO-8601 text into epoch milliseconds.
    After: return milliseconds or None when parsing fails.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def _is_background(record: dict[str, Any]) -> bool:
    """Before: receive one decoded record.

    During: recursively inspect background_tasks for a non-empty value.
    After: return whether the record belongs to a background window.
    """
    return _contains_nonempty_key(record, "background_tasks")[1]


def _is_human_message(record: dict[str, Any]) -> bool:
    """Before: receive one decoded record after a background window.

    During: distinguish human user text from metadata and tool results.
    After: return the push-after predicate.
    """
    if record.get("type") != "user" or record.get("isMeta") is True:
        return False
    content = (record.get("message") or {}).get("content") or []
    return not any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def _push_after_window(records: list[dict[str, Any]], end: int) -> bool:
    """Before: receive transcript records and the final index of a window.

    During: inspect the first relevant following record; a human message pushes, while
    an assistant response decides false and attachments, progress, tool results, meta,
    and system records are skipped.
    After: return the discriminating push flag for that window.
    """
    for record in records[end + 1 :]:
        if record.get("type") == "assistant":
            return False
        if _is_human_message(record):
            return True
        if record.get("type") in {"attachment", "progress", "system"}:
            continue
        content = (record.get("message") or {}).get("content") or []
        if record.get("isMeta") is True or any(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        ):
            continue
    return False


def background_windows(records: list[dict[str, Any]]) -> list[BackgroundWindow]:
    """Before: receive records in transcript order.

    During: group maximal consecutive background-task records and inspect the first
    relevant following record. A human message makes push true; an assistant response
    makes it false, while attachments, progress, tool results, isMeta, and system records
    are skipped. Later records do not change that first relevant decision.
    After: return elapsed windows and human-message push flags.
    """
    windows = []
    index = 0
    while index < len(records):
        if not _is_background(records[index]):
            index += 1
            continue
        start = index
        while index + 1 < len(records) and _is_background(records[index + 1]):
            index += 1
        first = _timestamp_ms(records[start].get("timestamp"))
        last = _timestamp_ms(records[index].get("timestamp"))
        duration = last - first if first is not None and last is not None else 0
        push = _push_after_window(records, index)
        windows.append(BackgroundWindow(duration, push))
        index += 1
    return windows


def build_report(
    roots: Iterable[Path | str],
    *,
    limit: int | None = DEFAULT_LIMIT,
    redact_roots: bool = False,
) -> str:
    """Before: receive declared roots and optional inventory controls.

    During: resolve, inventory, parse, aggregate, and format transcript observations.
    After: return only the contract's counts, durations, flags, and root declarations.
    """
    declared_roots = list(roots)
    effective = resolve_roots(declared_roots)
    limit_value = DEFAULT_LIMIT if limit is None else limit
    transcripts = iter_transcripts(effective)
    if limit_value > 0:
        transcripts = sorted(
            transcripts, key=lambda path: path.stat().st_mtime_ns, reverse=True
        )[:limit_value]
    raw_state = {}
    tool_counts = {}
    class_counts = {name: 0 for name in CLASS_ORDER}
    shells = {name: 0 for name in SHELL_TOOLS}
    window_count = 0
    window_ms_total = 0
    window_push = 0
    corrupt_total = 0
    for path in transcripts:
        records, corrupt_lines = load_records(path)
        corrupt_total += corrupt_lines
        for record in records:
            session = session_key(record, path)
            for key in RAW_KEYS:
                found, non_empty = _contains_nonempty_key(record, key)
                merge_raw_state(raw_state, session, key, found, non_empty)
        for call in collect_long_calls(records):
            class_counts[call.class_name] += 1
            tool_counts[call.tool] = tool_counts.get(call.tool, 0) + 1
        for window in background_windows(records):
            window_count += 1
            window_ms_total += window.duration_ms
            window_push += int(window.push_after)
        for name, count in count_shell_calls(records).items():
            shells[name] += count
        del records
    states = raw_state_to_states(raw_state)
    lines = [
        "espera_background_probe",
        f"roots_declaradas: {len(declared_roots)}",
        f"roots_efectivas: {len(effective)}",
    ]
    for index, root in enumerate(effective):
        lines.append(f"root[{index}]: {'root-' + str(index) if redact_roots else root}")
    lines.extend(
        [
            f"transcripts: {len(transcripts)}",
            f"sessions: {len(raw_state)}",
            f"limit: {limit_value}",
            *(["aviso: sin limite (recorrido completo)"] if limit_value == 0 else []),
            f"long_call_threshold_ms: {LONG_CALL_THRESHOLD_MS}",
            f"long_calls_total: {sum(tool_counts.values())}",
        ]
    )
    lines.extend(
        f"long_call[{name}]: {tool_counts[name]}"
        for name in sorted(tool_counts)
        if tool_counts[name] > 0
    )
    lines.extend(f"class[{name}]: {class_counts[name]}" for name in CLASS_ORDER)
    lines.extend(
        [
            f"window_count: {window_count}",
            f"window_ms_total: {window_ms_total}",
            f"window_push: {window_push}",
        ]
    )
    for key in RAW_KEYS:
        lines.extend(
            f"raw[{key}][{session}]: {states[session][key]}"
            for session in sorted(states)
        )
    lines.append(f"corrupt_lines: {corrupt_total}")
    lines.extend(f"shells[{name}]: {shells[name]}" for name in SHELL_TOOLS)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Before: receive optional CLI arguments.

    During: parse roots and print the read-only aggregate report.
    After: return zero without writing files.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--redact-roots", action="store_true")
    args = parser.parse_args(argv)
    roots = (
        args.root if args.root is not None else [Path.home() / ".claude" / "projects"]
    )
    print(build_report(roots, limit=args.limit, redact_roots=args.redact_roots), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
