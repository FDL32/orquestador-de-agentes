"""Deterministic markdown unit measurer for AGENTS.md / CLAUDE.md.

Splits a markdown file into non-overlapping ATX-header units, computes
own/subtree byte and character metrics across the full @-import closure,
checks the partition invariant, cross-references AGENTS_SECTIONS_REGISTRY,
and reports gates against context-budget limits.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# AGENTS_SECTIONS_REGISTRY (WOT-2026-114b: reubicado desde el retirado
# scripts/hermes_build_context_bundle.py -- este modulo es ahora su UNICO
# dueno y consumidor).
#
# WOT-2026-036g: el lector original ANCLABA POR HEADER EXACTO
# (``lines.index(heading)``): un renombrado conservador del header, o incluso
# un espacio final invisible, rompian la extraccion con ValueError. El
# REGISTRY es la lista CERRADA de secciones que este medidor cruza contra
# AGENTS.md: cada entrada mapea un id estable -> patron de header tolerante a
# renombrado conservador (mayusculas/minusculas y espaciado), sin dejar de
# anclar al nivel de encabezado y al texto del titulo.
#
# WOT-2026-114a (Fase 1 Palanca A, docs/followups/palanca-a-raiz-agents-md-
# diseno.md D1): cada entrada suma un tercer campo `source` (ruta relativa al
# motor donde VIVE el cuerpo de la seccion). Hoy las tres apuntan a
# "AGENTS.md"; una fase futura que traslade el CUERPO de una seccion a un
# modulo bajo `.agent/rules/common/` solo necesita repuntar este campo.
# ---------------------------------------------------------------------------

AGENTS_SECTIONS_REGISTRY: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "vocabulario_canonico",
        re.compile(r"^##\s+Vocabulario\s+canonico\s*$", re.IGNORECASE),
        "AGENTS.md",
    ),
    (
        "cem_v0",
        re.compile(
            r"^##\s+CEM\s+v0\s*-\s*Contrato,\s*Evidencia\s+y\s+Memoria\s*$",
            re.IGNORECASE,
        ),
        "AGENTS.md",
    ),
    (
        "secretos_y_seguridad",
        re.compile(r"^##\s+Secretos\s+y\s+seguridad\s*$", re.IGNORECASE),
        "AGENTS.md",
    ),
)

_REGISTRY_BY_ID: dict[str, tuple[re.Pattern[str], str]] = {
    sid: (pattern, source) for sid, pattern, source in AGENTS_SECTIONS_REGISTRY
}


def _registered_section_source(section_id: str) -> str:
    """Before: section_id may or may not be registered. During: look up the
    `source` field. After: returns the relative path, or raises ValueError
    naming the unknown id (same message shape as the extraction lookup)."""
    try:
        _, source = _REGISTRY_BY_ID[section_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown section id: {section_id!r}; registered ids are "
            f"{sorted(_REGISTRY_BY_ID)}"
        ) from exc
    return source


def _registry_sources() -> list[str]:
    """Before: none. During: walk the registry. After: distinct `source`
    paths in registry order, deduplicated (today all three collapse to the
    single entry "AGENTS.md")."""
    seen: list[str] = []
    for _, _, source in AGENTS_SECTIONS_REGISTRY:
        if source not in seen:
            seen.append(source)
    return seen


def _extract_registered_section(text: str, section_id: str) -> str:
    """Extract a REGISTERED section by its stable id, not by literal title.

    Before: `section_id` is a key of AGENTS_SECTIONS_REGISTRY; `text` is the
        content of whatever file that id's `source` field names.
    During: match each line against the registered tolerant pattern; the
        section runs until the next header of the SAME level.
    After: returns the section text. Raises ValueError naming the id AND the
        pattern when no header matches -- a caller must be able to tell
        "renamed beyond tolerance" from "typo in my id".
    """
    try:
        pattern, _source = _REGISTRY_BY_ID[section_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown section id: {section_id!r}; registered ids are "
            f"{sorted(_REGISTRY_BY_ID)}"
        ) from exc

    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if pattern.match(line)),
        None,
    )
    if start is None:
        raise ValueError(
            f"Required section not found: id={section_id!r} pattern={pattern.pattern!r}"
        )

    heading = lines[start]
    level = len(heading) - len(heading.lstrip("#"))
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("#" * level + " "):
            end = index
            break
    return "\n".join(lines[start:end]).rstrip()


def _read_registered_section(motor_root: Path, section_id: str) -> str:
    """Before: section_id is registered. During: read its declared `source`
    file under motor_root and extract by registry pattern. After: returns
    the section text -- IDENTICAL to reading AGENTS.md directly as long as
    `source` points there (Fase 1: it always does)."""
    source = _registered_section_source(section_id)
    text = (motor_root / source).read_text(encoding="utf-8")
    return _extract_registered_section(text, section_id)


# ---------------------------------------------------------------------------
# Unit dataclass
# ---------------------------------------------------------------------------


@dataclass
class Unit:
    """A non-overlapping unit of a markdown file.

    heading -- text of the header line or ``<preambulo>``.
    level   -- header level (0 for preambulo).
    start_line -- 1-based index of the first line in the unit.
    own_bytes  -- bytes of the unit excluding all child-unit ranges.
    own_chars  -- characters of the unit excluding all child-unit ranges.
    subtree_bytes -- own_bytes plus all descendants' own_bytes.
    subtree_chars -- same for characters.
    """

    heading: str
    level: int
    start_line: int
    end_line: int  # inclusive, 1-based
    _own_bytes: int = field(default=0, init=False, repr=False)
    _own_chars: int = field(default=0, init=False, repr=False)
    subtree_bytes: int = field(default=0, init=False, repr=False)
    subtree_chars: int = field(default=0, init=False, repr=False)

    @property
    def own_bytes(self) -> int:
        return self._own_bytes

    @property
    def own_chars(self) -> int:
        return self._own_chars


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_ATX_RE = re.compile(r"^(#{1,6})\s")


def _build_code_block_mask(lines: list[str]) -> list[bool]:
    """Return a list of bools: True if the line is inside a fenced code block.

    Tracks triple-backtick (```) and triple-tilde (~~~) fenced blocks,
    including language-tagged open fences like ````python````.
    """
    mask: list[bool] = []
    in_block = False
    open_fence: str = ""  # e.g. "```" -- closing fence must match
    for line in lines:
        mask.append(in_block)
        m = re.match(r"^(\s*)(```|~~~)", line)
        if m:
            fence_chars = m.group(2)
            rest = line[len(m.group(1)) + len(fence_chars) :].strip()
            if not in_block:
                # Opening a code block (with or without language tag)
                in_block = True
                open_fence = fence_chars
            else:
                # Already in a block: closing fence must match and be
                # same or larger size with no extra content
                if fence_chars == open_fence and rest == "":
                    in_block = False
                # Otherwise: language tag inside block or mismatched fence
                # -> stay in block
    return mask


# ---------------------------------------------------------------------------
# Public API: split_units
# ---------------------------------------------------------------------------


def split_units(text: str) -> list[Unit]:  # noqa: C901 - parser de markdown: fases secuenciales con bucles anidados para encabezados y bloques cercados
    """Split markdown into non-overlapping ATX-header units.

    Before: *text* -- the full markdown content as a string.
    During: parse lines, detect fenced code blocks, find ATX headers,
        compute own/subtree byte and char metrics.
    After: list of ``Unit`` objects in file order; preambulo is omitted
        when it has 0 bytes.
    """
    raw = text.encode("utf-8")
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    # Byte offset of each line start (0-based index -> byte offset)
    line_byte_start: list[int] = [0] * total_lines
    for i in range(total_lines - 1):
        line_byte_start[i + 1] = line_byte_start[i] + len(lines[i].encode("utf-8"))

    code_mask = _build_code_block_mask(lines)

    # --- Phase 1: find header positions ---
    header_positions: list[
        tuple[int, int, str]
    ] = []  # (0-based line_idx, level, heading_text)
    for i, line in enumerate(lines):
        if code_mask[i]:
            continue
        m = _ATX_RE.match(line)
        if m:
            level = len(m.group(1))
            heading_text = line.strip()
            header_positions.append((i, level, heading_text))

    # --- Phase 2: build raw units (with full ranges, 0-based) ---
    # All ranges use 0-based line indices internally.
    # start_line (stored as 1-based) and end_line (0-based, inclusive).
    units: list[Unit] = []

    # Preambulo: lines 0 .. first_header_line-1
    if header_positions:
        first_h_line = header_positions[0][0]  # 0-based
        if first_h_line > 0:
            units.append(
                Unit(
                    heading="<preambulo>",
                    level=0,
                    start_line=1,  # 1-based display
                    end_line=first_h_line - 1,  # 0-based inclusive (last preamble line)
                )
            )
        # Header units: each covers its line up to the line BEFORE the next header
        for idx, (h_line, h_level, h_text) in enumerate(header_positions):
            next_h_line = (
                header_positions[idx + 1][0] - 1
                if idx + 1 < len(header_positions)
                else total_lines - 1
            )
            units.append(
                Unit(
                    heading=h_text,
                    level=h_level,
                    start_line=h_line + 1,  # 1-based display
                    end_line=next_h_line,  # 0-based inclusive
                )
            )
    else:
        # No headers: whole file is preambulo
        last_line_idx = total_lines - 1
        units.append(
            Unit(
                heading="<preambulo>",
                level=0,
                start_line=1,
                end_line=last_line_idx,
            )
        )

    # --- Phase 3: compute own_bytes for all units by excluding child ranges ---
    for u in units:
        if u.level == 0:
            _compute_own_bytes(u, units, line_byte_start, lines)
            continue
        # Collect all descendant ranges (transitively)
        descendant_ranges: list[tuple[int, int]] = []
        _collect_descendant_ranges(u, units, descendant_ranges)

        # Total range bytes: from start_line-1 (0-based) to end_line (0-based inclusive)
        range_start = line_byte_start[u.start_line - 1]
        range_end_idx = u.end_line + 1  # byte offset AFTER the last line
        range_end = (
            line_byte_start[range_end_idx]
            if range_end_idx < len(line_byte_start)
            else len(raw)
        )
        total_range_bytes = range_end - range_start

        # Subtract descendant ranges that fall within parent's range
        descendant_bytes = 0
        for dr in descendant_ranges:
            # Clip descendant range to parent's range
            clip_start = max(dr[0], u.start_line - 1)
            clip_end_idx = min(dr[1] + 1, u.end_line + 1)
            if clip_end_idx > clip_start:
                descendant_bytes += (
                    line_byte_start[clip_end_idx]
                    if clip_end_idx < len(line_byte_start)
                    else len(raw)
                ) - line_byte_start[clip_start]

        u._own_bytes = total_range_bytes - descendant_bytes

        # Chars the same way, clipped to parent's range
        total_range_chars = sum(
            len(lines[ln])
            for ln in range(u.start_line - 1, u.end_line + 1)
            if 0 <= ln < len(lines)
        )
        descendant_chars = 0
        for dr in descendant_ranges:
            clip_start = max(dr[0], u.start_line - 1)
            clip_end = min(dr[1] + 1, u.end_line + 1)
            for ln in range(clip_start, clip_end):
                if 0 <= ln < len(lines):
                    descendant_chars += len(lines[ln])

        u._own_chars = total_range_chars - descendant_chars

    # --- Phase 4: compute subtree_bytes as contiguous sum of own_bytes ---
    # subtree of unit i = own_bytes of i + own_bytes of consecutive
    # following units whose level is strictly greater than i.level,
    # stopping at the first unit with level <= i.level.
    for u in units:
        stop = False
        idx = units.index(u)
        subtree_bytes = u._own_bytes
        subtree_chars = u._own_chars
        for j in range(idx + 1, len(units)):
            if units[j].level <= u.level:
                stop = True
                break
            subtree_bytes += units[j]._own_bytes
            subtree_chars += units[j]._own_chars
            if stop:
                break
        u.subtree_bytes = subtree_bytes
        u.subtree_chars = subtree_chars

    # --- Phase 6: omit zero-byte preambulo ---
    if units and units[0].heading == "<preambulo>" and units[0]._own_bytes == 0:
        units.pop(0)

    return units


def _find_children(unit: Unit, units: list[Unit]) -> list[Unit]:
    """Return all descendants: units after *unit* with level > unit.level,
    stopping at the first unit with level <= unit.level."""
    children: list[Unit] = []
    past = False
    for c in units:
        if c is unit:
            past = True
            continue
        if not past:
            continue
        if c.level <= unit.level:
            break  # closed by same or shallower heading
        children.append(c)
    return children


def _collect_descendant_ranges(
    unit: Unit, units: list[Unit], result: list[tuple[int, int]]
) -> None:
    """Recursively collect all descendant ranges (0-based start, 0-based end)."""
    past = False
    for c in units:
        if c is unit:
            past = True
            continue
        if not past:
            continue
        if c.level <= unit.level:
            break
        result.append((c.start_line - 1, c.end_line))  # convert start to 0-based
        _collect_descendant_ranges(c, units, result)


def _compute_own_bytes(
    u: Unit, units: list[Unit], line_byte_start: list[int], lines: list[str]
) -> None:
    """Compute own_bytes for a unit (preambulo or leaf)."""
    start_offset = line_byte_start[u.start_line - 1]
    # Find the byte offset of the line AFTER end_line
    if u.end_line + 1 < len(line_byte_start):
        end_offset = line_byte_start[u.end_line + 1]
    else:
        end_offset = sum(len(ln.encode("utf-8")) for ln in lines)
    u._own_bytes = end_offset - start_offset
    # Chars
    chars = 0
    for ln_idx in range(u.start_line - 1, u.end_line + 1):
        if ln_idx < len(lines):
            chars += len(lines[ln_idx])
    u._own_chars = chars


# ---------------------------------------------------------------------------
# Public API: assert_partition
# ---------------------------------------------------------------------------


def assert_partition(units: list[Unit], raw: bytes) -> None:
    """Verify the partition invariant: units cover the file exactly.

    Before: *units* (from ``split_units``) and *raw* (original bytes).
    During: sum all ``own_bytes`` and ``own_chars``.
    After: raises ``ValueError`` on mismatch; otherwise a silent no-op.
    """
    total_own_bytes = sum(u.own_bytes for u in units)
    if total_own_bytes != len(raw):
        raise ValueError(
            f"Partition invariant FAILED: own_bytes sum={total_own_bytes} "
            f"!= raw length={len(raw)}"
        )

    decoded = raw.decode("utf-8")
    total_own_chars = sum(u.own_chars for u in units)
    if total_own_chars != len(decoded):
        raise ValueError(
            f"Partition invariant FAILED: own_chars sum={total_own_chars} "
            f"!= decoded length={len(decoded)}"
        )


# ---------------------------------------------------------------------------
# Public API: resolve_closure
# ---------------------------------------------------------------------------


def resolve_closure(claude_md: Path) -> list[Path]:  # noqa: C901 - fence tracking (open/close match) mas recorrido de @imports en el mismo bucle
    """Transitive closure of always-loaded files via ``@path`` lines.

    Before: *claude_md* -- path to CLAUDE.md (absolute or resolved).
    During: include *claude_md* itself as the first element, then walk
        ``@``-import lines (not inside code blocks), resolve each
        relative to its parent file, recurse, track visited.
    After: ordered list of unique ``Path``s starting with *claude_md*,
        followed by its imports; cycle-safe;
        ``FileNotFoundError`` if an import target does not exist.
    """
    resolved = claude_md.resolve()
    visited: list[Path] = [resolved]
    seen: set[Path] = {resolved}

    def _walk(file_path: Path) -> None:
        text = file_path.read_text(encoding="utf-8")
        lines_text = text.splitlines(keepends=True)
        in_block = False
        open_fence = ""
        for line in lines_text:
            fence_match = re.match(r"^(\s*)(```|~~~)", line)
            if fence_match:
                fence_chars = fence_match.group(2)
                rest = line[len(fence_match.group(1)) + len(fence_chars) :].strip()
                if not in_block:
                    in_block = True
                    open_fence = fence_chars
                elif fence_chars == open_fence and rest == "":
                    in_block = False
                continue
            if in_block:
                continue
            stripped = line.strip()
            if not stripped.startswith("@"):
                continue
            import_path = stripped[1:].strip()
            if not import_path:
                continue
            resolved = (file_path.parent / import_path).resolve()
            if resolved in seen:
                continue
            if not resolved.exists():
                raise FileNotFoundError(
                    f"Import target does not exist: {import_path} "
                    f"(resolved: {resolved}) from {file_path}"
                )
            seen.add(resolved)
            visited.append(resolved)
            _walk(resolved)

    _walk(claude_md)
    return visited


# ---------------------------------------------------------------------------
# Public API: gates
# ---------------------------------------------------------------------------

_codex_bytes_limit = 32768
_claude_chars_limit = 40000


def gates(agents_raw: bytes, closure: list[Path]) -> dict:
    """Compute context-budget gates for Codex and Claude.

    Before: *agents_raw* -- raw bytes of AGENTS.md; *closure* -- list of
        paths from ``resolve_closure``.
    During: compute byte/char metrics and ratios against fixed limits.
    After: dict with keys ``codex_bytes``, ``codex_limit``, ``codex_ratio``,
        ``codex_deficit``, ``claude_chars``, ``claude_limit``,
        ``claude_ratio``, ``claude_deficit``.
    """
    codex_bytes = len(agents_raw)
    codex_ratio = codex_bytes / _codex_bytes_limit if _codex_bytes_limit else 0.0
    codex_deficit = max(0, codex_bytes - _codex_bytes_limit)

    claude_chars_total = 0
    for p in closure:
        decoded = p.read_text(encoding="utf-8")
        claude_chars_total += len(decoded)

    claude_chars = claude_chars_total
    claude_ratio = claude_chars / _claude_chars_limit if _claude_chars_limit else 0.0
    claude_deficit = max(0, claude_chars - _claude_chars_limit)

    return {
        "codex_bytes": codex_bytes,
        "codex_limit": _codex_bytes_limit,
        "codex_ratio": round(codex_ratio, 4),
        "codex_deficit": codex_deficit,
        "claude_chars": claude_chars,
        "claude_limit": _claude_chars_limit,
        "claude_ratio": round(claude_ratio, 4),
        "claude_deficit": claude_deficit,
    }


# ---------------------------------------------------------------------------
# Public API: registry_crosscheck
# ---------------------------------------------------------------------------


def registry_crosscheck(units: list[Unit]) -> list[dict]:
    """Cross-check units against AGENTS_SECTIONS_REGISTRY.

    Before: *units* from ``split_units`` on AGENTS.md.
    During: match each ``(id, pattern)`` against level-2 unit headings,
        count matches.
    After: list of dicts with ``id``, ``matches``, ``subtree_bytes``,
        ``status`` (``"OK"`` or ``"DRIFT"``).
    """
    results: list[dict] = []
    for section_id, pattern, _source in AGENTS_SECTIONS_REGISTRY:
        matches = [u for u in units if u.level == 2 and pattern.match(u.heading)]
        match_count = len(matches)
        subtree_bytes_val = matches[0].subtree_bytes if len(matches) == 1 else None
        status = "DRIFT" if match_count != 1 else "OK"
        results.append(
            {
                "id": section_id,
                "matches": match_count,
                "subtree_bytes": subtree_bytes_val,
                "status": status,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Public API: stamp
# ---------------------------------------------------------------------------


def stamp(repo_root: Path) -> dict:
    """Git stamp for the repository.

    Before: *repo_root* -- absolute path to the repo root.
    During: run ``git rev-parse HEAD`` and ``git status --porcelain``
        inside the repo; capture UTC timestamp.
    After: dict with ``repo_root``, ``head``, ``dirty_agents_claude``,
        ``timestamp_utc``.
    """
    root = repo_root.resolve()

    # Git HEAD
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        head = result.stdout.strip() if result.returncode == 0 else "NO VERIFICABLE"
    except Exception:
        head = "NO VERIFICABLE"

    # Dirty check for AGENTS.md and CLAUDE.md
    dirty: bool | None = None
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "AGENTS.md", "CLAUDE.md"],  # noqa: S607
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout.strip()
        dirty = bool(output) if result.returncode in (0, 1) else None
    except Exception:
        dirty = None

    return {
        "repo_root": str(root),
        "head": head,
        "dirty_agents_claude": dirty,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------


def _format_table(units: list[Unit], crosscheck: list[dict]) -> str:
    """Format units as a markdown table."""
    headers = [
        "#",
        "Linea",
        "Nivel",
        "Encabezado",
        "own_B",
        "own_chars",
        "subtree_B",
        "registry",
    ]
    rows: list[list[str]] = []
    for i, u in enumerate(units, start=1):
        registry_status = ""
        if u.level == 2:
            for _sid, pat, _src in AGENTS_SECTIONS_REGISTRY:
                if pat.match(u.heading):
                    for cc in crosscheck:
                        if cc["id"] == _sid:
                            registry_status = cc["status"]
                            break
                    break
        rows.append(
            [
                str(i),
                str(u.start_line),
                str(u.level),
                u.heading,
                str(u.own_bytes),
                str(u.own_chars),
                str(u.subtree_bytes),
                registry_status,
            ]
        )

    # Build markdown table
    col_widths = [len(h) for h in headers]
    for row in rows:
        for j, cell in enumerate(row):
            col_widths[j] = max(col_widths[j], len(cell))

    def _fmt(val: str, width: int) -> str:
        return val.ljust(width)

    header_line = (
        "| " + " | ".join(_fmt(h, col_widths[i]) for i, h in enumerate(headers)) + " |"
    )
    sep_line = (
        "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    )
    data_lines = "\n".join(
        "| "
        + " | ".join(_fmt(cell, col_widths[i]) for i, cell in enumerate(row))
        + " |"
        for row in rows
    )

    return header_line + "\n" + sep_line + "\n" + data_lines


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Before: parse ``--repo-root``, ``--json``, ``--out``.
    During: read AGENTS.md / CLAUDE.md, compute units, gates, stamp,
        crosscheck; format output.
    After: print table or JSON; exit 0 on success, 2 on partition error.
    """
    parser = argparse.ArgumentParser(
        description="Measure AGENTS.md / CLAUDE.md markdown units."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: directory containing this script).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output as JSON instead of markdown table.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write output to file instead of stdout.",
    )

    args = parser.parse_args(argv)

    repo_root = args.repo_root or Path(__file__).resolve().parent.parent
    agents_path = repo_root / "AGENTS.md"
    claude_path = repo_root / "CLAUDE.md"

    # Read files as bytes
    agents_raw = agents_path.read_bytes()
    agents_text = agents_raw.decode("utf-8")

    # Resolve closure
    try:
        closure = resolve_closure(claude_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # Split into units
    units = split_units(agents_text)

    # Assert partition
    try:
        assert_partition(units, agents_raw)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # Compute gates
    gates_data = gates(agents_raw, closure)

    # Stamp
    stamp_data = stamp(repo_root)

    # Registry crosscheck
    crosscheck = registry_crosscheck(units)

    if args.json:
        units_json = [
            {
                "heading": u.heading,
                "level": u.level,
                "start_line": u.start_line,
                "end_line": u.end_line,
                "own_bytes": u.own_bytes,
                "own_chars": u.own_chars,
                "subtree_bytes": u.subtree_bytes,
                "subtree_chars": u.subtree_chars,
            }
            for u in units
        ]
        output = {
            "stamp": stamp_data,
            "gates": gates_data,
            "units": units_json,
            "registry": crosscheck,
        }
        output_str = json.dumps(output, indent=2, ensure_ascii=False)
    else:
        output_str = _format_table(units, crosscheck)
        output_str += "\n\n"
        output_str += f"**Stamp:** `{stamp_data['head'][:12]}`"
        output_str += f" | dirty={stamp_data['dirty_agents_claude']}\n"
        output_str += (
            f"**Gates:** codex={gates_data['codex_bytes']}/{gates_data['codex_limit']} "
        )
        output_str += f"(ratio={gates_data['codex_ratio']}, deficit={gates_data['codex_deficit']}) "
        output_str += (
            f"| claude={gates_data['claude_chars']}/{gates_data['claude_limit']} "
        )
        output_str += f"(ratio={gates_data['claude_ratio']}, deficit={gates_data['claude_deficit']})\n"

    if args.out:
        args.out.write_text(output_str, encoding="utf-8", newline="\n")
    else:
        print(output_str)

    return 0


if __name__ == "__main__":
    sys.exit(main())
