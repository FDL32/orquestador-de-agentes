#!/usr/bin/env python3
"""Measure hit@5 quality of ``--recall --headlines`` on lessons promoted to norm (G).

WOT-2026-124b (Etapa 1, B.2b), ronda 6 (WOT-2026-124e).  Unit = non-excluded
citation (DoD c): each (filename, id, line) surviving exclusion and pool
intersection.  Each citation has ONE surface query (file stem) and FASE queries
(section vocabulary or all 8 terms if no section).  Recall is cached by query
text.

Usage:
    python scripts/measure_recall_quality.py \\
        --motor-root <ruta> --destino-root <ruta> --out <ruta.md> \\
        [--limit 5]

The script is deterministic: given the same corpus it produces byte-identical
``--out`` except for the date line.

Before: ``motor_root`` and ``destino_root`` exist and are valid repos/roots.
During: extracts citations, derives queries, runs recall (cached), measures hits.
After: writes ``--out`` markdown with primary table, secondary table, detail,
    and failures list; exits rc 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path


# Bootstrap sys.path to resolve motor packages.
_MOTOR_ROOT_RESOLVED = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT_RESOLVED) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT_RESOLVED))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Git grep paths (same regex as sim.py line 93, without -h to keep filename).
_GIT_GREP_PATHS = [
    "prompts",
    "AGENTS.md",
    "CLAUDE.md",
    ".agent/rules",
    "skills",
    "docs",
    "CONSTITUTION.md",
    "scripts",
    "tests",
]

# Stems that do NOT produce a useful query surface.
_USELESS_STEMS = frozenset(
    [
        "AGENTS",
        "CLAUDE",
        "CONSTITUTION",
        "README",
        "SKILL",
        "ROUTER",
        "__init__",
        "conftest",
    ]
)

# FASE vocabulary (closed list).
_FASE_VOCAB = [
    "commit",
    "suite",
    "push",
    "cierre",
    "encoding",
    "backlog",
    "bus",
    "memoria",
]

#: Pattern to extract obs-IDs from text (portable from sim.py).
_CITE_PATTERN = re.compile(r"obs-[a-z0-9-]*")

#: Excluded script filename (absolute path stem) from citations.
_EXCLUDED_SCRIPT_STEM = "measure_recall_quality"


# ---------------------------------------------------------------------------
# Pure logic: extract citations, derive queries, decide hit
# ---------------------------------------------------------------------------


def _git_grep_cites(
    motor_root: Path,
) -> list[tuple[str, str, int]]:
    """Run ``git -C <motor> grep -o -n '<pattern>'`` for all cite paths.

    Returns a list of ``(filename, obs_id, line_number)`` for every citation
    found.  Each file is searched separately so we keep the filename context.

    Before: ``motor_root`` is a valid git repository.
    During: runs git grep for each path; collects all obs- matches.
    After: returns flat list of (file, id, line) tuples; raises on git grep
        failure (rc >= 2 or OS/subprocess error).
    """
    results: list[tuple[str, str, int]] = []
    pattern = _CITE_PATTERN.pattern
    for path in _GIT_GREP_PATHS:
        try:
            out = subprocess.run(  # noqa: S603
                ["git", "-C", str(motor_root), "grep", "-o", "-n", pattern, "--", path],  # noqa: S607
                capture_output=True,
                text=True,
                check=False,
            )
            if out.returncode == 1:
                # rc 1: no matches in this path -> normal, skip it.
                continue
            if out.returncode != 0:
                # rc >= 2: actual git failure -> abort.
                raise RuntimeError(
                    f"git grep failed for path '{path}' with returncode {out.returncode}"
                )
            for raw_line in out.stdout.splitlines():
                # Format: <path>:<line>:match
                # git grep -o -n -- <path> produces: <path>:<linenum>:obs-xxx
                colon_parts = raw_line.split(":")
                if len(colon_parts) < 3:
                    continue
                # Reconstruct: filename might contain colons, so join all but last 2
                filename = ":".join(colon_parts[:-2])
                line_num_str = colon_parts[-2]
                match_part = ":".join(colon_parts[-1:])
                try:
                    line_num = int(line_num_str)
                except ValueError:
                    continue
                # Extract obs-IDs from match_part (may contain multiple)
                results.extend(
                    (filename, m.group(), line_num)
                    for m in _CITE_PATTERN.finditer(match_part)
                )
        except (OSError, subprocess.SubprocessError) as e:
            raise RuntimeError(f"git grep failed for path '{path}': {e}") from e
    return results


def _dedup_key_id(entry: dict) -> str:
    """Return the dedup_key for a lesson entry (fuente comun del motor)."""
    from bus.portable_memory_archive import dedup_key

    return dedup_key(entry)


def _is_lesson(entry: dict) -> bool:
    """Check if an entry is a lesson (not template/telemetry).

    Sin fallback: si el import falla, la medicion debe romper en voz alta en
    vez de tratar cualquier entrada como leccion (fail-closed).
    """
    from bus.portable_memory_archive import is_lesson

    return is_lesson(entry)


def _load_archive_ids(root: Path) -> list[dict]:
    """Load lesson entries from archive JSONL files in <root>/.agent/runtime/memory/archive/.

    Returns deduplicated entries (by dedup_key, keeping latest), only lessons,
    without superseded/refuted status.

    Before: ``root`` is a valid project root with an archive directory.
    During: reads all *.jsonl files in the archive directory.
    After: returns list of lesson dicts.
    """
    archive_dir = root / ".agent" / "runtime" / "memory" / "archive"
    if not archive_dir.is_dir():
        return []

    entries: list[dict] = []
    for jsonl_file in sorted(archive_dir.glob("*.jsonl")):
        try:
            for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                # Skip non-lessons
                if not _is_lesson(entry):
                    continue
                # Skip superseded/refuted
                status = entry.get("status", "")
                if status in ("superseded", "refuted"):
                    continue
                entries.append(entry)
        except (OSError, UnicodeDecodeError):
            continue
    return entries


def _dedup_entries(entries: list[dict]) -> list[dict]:
    """Deduplicate entries by dedup_key, keeping the latest.

    Before: list of lesson entries (may have duplicates by dedup_key).
    During: computes dedup_key for each entry, keeps latest by timestamp.
    After: returns deduplicated list; entries without id get a stable fallback.
    """
    seen: dict[str, dict] = {}
    for entry in entries:
        dk = _dedup_key_id(entry)
        if dk:
            if dk not in seen:
                seen[dk] = entry
            else:
                # Keep the latest by timestamp
                existing_ts = seen[dk].get("timestamp", "")
                new_ts = entry.get("timestamp", "")
                if new_ts > existing_ts:
                    seen[dk] = entry
    return list(seen.values())


def _filter_excluded_citations(
    citations: list[tuple[str, str, int]],
    script_stem: str,
) -> tuple[list[tuple[str, str, int]], int]:
    """Filter out citations from the measuring script itself and useless stems at root.

    Before: list of (filename, obs_id, line_number) citations.
    During: checks if citation filename matches the excluded script stem
        or if the stem is in USELESS_STEMS with no valid parent.
    After: returns (filtered_citations, excluded_count).
    """
    filtered: list[tuple[str, str, int]] = []
    excluded_count = 0
    for fn, oid, ln in citations:
        # Exclude self-citations
        if Path(fn).stem == script_stem:
            excluded_count += 1
            continue
        # Exclude useless stems at root level
        stem = Path(fn).stem
        if stem in _USELESS_STEMS:
            parent = Path(fn).parent.name
            if not parent or parent in _USELESS_STEMS:
                excluded_count += 1
                continue
        filtered.append((fn, oid, ln))
    return filtered, excluded_count


def _intersect_with_pool(
    citations: list[tuple[str, str, int]],
    pool: list[dict],
) -> list[tuple[str, str, int]]:
    """Keep only citations whose obs-ID is in the deduplicated pool.

    Before: citations from git grep; pool of lesson entries.
    During: builds set of pool IDs, filters citations.
    After: returns citations where obs-ID is in pool.
    """
    pool_ids = {e.get("id") for e in pool if e.get("id")}
    return [(fn, oid, ln) for fn, oid, ln in citations if oid in pool_ids]


def _derive_surface_query(filename: str) -> str | None:
    """Derive a query from the SUPERFICIE (file stem) of a citing file.

    Applies the fixed rule:
    - If stem is in USELESS_STEMS, use parent directory name.
    - If parent is repo root or also in USELESS_STEMS, return None (exclude).

    Before: ``filename`` is the path of the citing file.
    During: extracts stem, checks against useless list, resolves parent.
    After: returns a query string or None if excluded.
    """
    stem = Path(filename).stem
    if stem in _USELESS_STEMS:
        parent = Path(filename).parent.name
        if parent in _USELESS_STEMS or not parent:
            return None
        return parent
    return stem


def _extract_markdown_section(filepath: str, line_number: int, motor_root: Path) -> str:
    """Extract the nearest markdown heading above the given line.

    "Seccion" = the markdown header closest above the citation line.
    Only .md files are considered markdown; non-markdown files return empty
    string (no section).

    Recognizes headers of any level (``#`` through ``######``) matching
    ``^#{1,6}\\s+\\S``.  Lines inside fenced code blocks (triple backticks)
    are ignored for header matching.

    Before: ``filepath`` relative to motor root, ``line_number`` is 1-based.
    During: checks extension is .md, reads file, scans lines from the top
        downward tracking code fences, finds the nearest header above
        line_number (outside any code block).
    After: returns the heading text (without # markers and trailing spaces)
        or empty string.
    """
    full_path = Path(motor_root) / filepath
    if full_path.suffix != ".md":
        return ""
    try:
        lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    heading_re = re.compile(r"^(#{1,6})\s+(\S.*)$")
    in_code_block = False
    current = ""
    for raw_line in lines[: line_number - 1]:
        if raw_line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        m = heading_re.match(raw_line)
        if m:
            current = m.group(2).strip()
    return current


def _derive_fase_queries(section: str) -> list[str]:
    """Derive FASE queries from the markdown section heading.

    Uses the closed vocabulary.  If no vocabulary word appears in the heading,
    returns the full vocabulary list (measures against all 8).

    Before: ``section`` is the markdown heading text (or empty).
    During: case-insensitive match against FASE_VOCAB.
    After: returns list of vocabulary terms found (or all if none found).
    """
    if not section:
        return list(_FASE_VOCAB)
    section_lower = section.lower()
    found = [v for v in _FASE_VOCAB if v in section_lower]
    return found if found else list(_FASE_VOCAB)


def _recall_run(
    motor_root: Path,
    query: str,
    destino_root: Path,
    limit: int,
) -> tuple[int, str, str]:
    """Run ``memory_context.py --recall --headlines --limit N --query Q``.

    Default implementation uses subprocess.  Can be overridden for testing.

    Before: all paths valid; ``query`` is a non-empty string.
    During: spawns python process with AGENT_PROJECT_ROOT set.
    After: returns (returncode, stdout, stderr).
    """
    env = os.environ.copy()
    env["AGENT_PROJECT_ROOT"] = str(destino_root)
    cmd = [
        sys.executable,
        str(motor_root / "scripts" / "memory_context.py"),
        "--recall",
        "--headlines",
        "--limit",
        str(limit),
        "--query",
        query,
        "--caller",
        "measure_recall_quality",
    ]
    try:
        out = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(motor_root),
            timeout=60,
        )
        return out.returncode, out.stdout, out.stderr
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)


def _is_hit(
    rc: int,
    stdout: str,
    lesson_id: str,
    lesson_topic: str,
    lesson_signal: str,
) -> bool:
    """Decide if a recall result is a HIT for the given lesson.

    Hit = the lesson's ``id`` appears at the start of some line as ``- <id>:``.
    For lessons without id: line ``- <topic>: <titular>`` with matching topic
    and titular (expected 0 cases).  Any rc != 0 returns False here; the
    caller (``_measure_hits``) classifies it BEFORE calling: rc 1 with
    ``No observations found`` in stderr = MISS, any other rc != 0 = FALLO.

    Before: ``rc`` is the recall return code; ``stdout`` is its output.
    During: checks each line for pattern match.
    After: returns True if hit, False otherwise.
    """
    if rc != 0:
        return False  # no hit; the caller already classified this rc as MISS or FALLO

    for line in stdout.splitlines():
        stripped = line.strip()
        # Pattern: "- <id>:" at start of line
        if stripped.startswith(f"- {lesson_id}:"):
            return True
        # No-id lesson: "- <topic>: <titular>"
        if (
            not lesson_id
            and lesson_topic
            and lesson_signal
            and stripped.startswith(f"- {lesson_topic}:")
        ):
            # Extract titular from line (after "- topic: ")
            line_after_topic = stripped[len(f"- {lesson_topic}:") :].strip()
            # Titular match: line's titular starts with lesson's signal
            if lesson_signal.lower() in line_after_topic.lower():
                return True
    return False


# ---------------------------------------------------------------------------
# Main logic (pure)
# ---------------------------------------------------------------------------


def _build_queries_for_citations(
    citations: list[tuple[str, str, int]],
    pool_by_id: dict[str, dict],
    motor_root: Path,
) -> list[tuple[int, str, str, str]]:
    """Build all (citation_idx, query_type, query_value, section) tuples.

    For each citation, derives a SUPERFICIE query and FASE queries.
    Returns queries indexed by citation position so results map back.
    Citations with no valid surface query (useless stem at root) are excluded entirely.

    Before: citations are filtered and intersected with pool.
    During: applies surface and fase rules.
    After: returns list of (citation_index, query_type, query, section) tuples.
    """
    queries: list[tuple[int, str, str, str]] = []

    for idx, (filename, obs_id, line_num) in enumerate(citations):
        lesson = pool_by_id.get(obs_id)
        if not lesson:
            continue

        # SUPERFICIE query
        surface_query = _derive_surface_query(filename)
        if surface_query is None:
            # Useless stem at root -> exclude citation entirely
            continue

        section = _extract_markdown_section(filename, line_num, motor_root)
        queries.append((idx, "superficie", surface_query, section))

        # FASE queries
        fase_terms = _derive_fase_queries(section)
        queries.extend((idx, "fase", term, section) for term in fase_terms)

    return queries


def _measure_hits(  # noqa: C901
    queries: list[tuple[int, str, str, str]],
    citations: list[tuple[str, str, int]],
    pool_by_id: dict[str, dict],
    motor_root: Path,
    destino_root: Path,
    limit: int,
    recall_fn: Callable,
) -> tuple[dict, dict, dict, list[str], dict[int, dict]]:
    """Run recall for each query and measure hit@5 (unit: non-excluded citation).

    Returns (hit_by_type, denominators, lesson_results, failures, citation_summary).

    Unit = non-excluded citation: each (filename, id, line) surviving exclusion
    and pool intersection.  Each citation has ONE surface query (its file stem)
    and FASE queries (from its section heading, or all 8 vocab terms if no
    section).

    Recall is cached by query text: ``recall_fn`` is called ONCE per distinct
    query string and the result is reused across citations that share the same
    query (e.g. two citations in the same file share the surface query).

    Query classification per citation:
    - rc == 0  -> evaluate ``_is_hit`` with the citation's obs-id.
    - rc == 1  with ``"No observations found"`` in stderr  -> MISS (not failure).
    - rc == 1  with anything else in stderr  -> FAIL.
    - rc != 0 and rc != 1  -> FAIL.

    Denominator rules (DoD c, WOT-2026-124e ronda 6):
    - superficie: every citation that has a surface query, EXCEPT those whose
      surface query is a FAIL.  Failed surface queries appear in "Fallos".
    - fase: every citation, EXCEPT those whose ALL phase queries are FAIL.
      If at least one phase query is HIT, the citation counts as HIT and stays
      in the denominator even if other phase queries failed.
    - union: every citation except those whose surface type was excluded AND
      whose phase type was excluded (i.e. no valid queries at all).

    Before: queries list from ``_build_queries_for_citations``; ``citations``
        is the full list; ``pool_by_id`` maps lesson IDs to entry dicts.
    During: runs recall with cache, evaluates hit per citation.
    After: returns hit counts, denominators, per-lesson aggregates, failure
        list (every superficie or fase query with rc != 0 that is not a
        "No observations found" miss), and per-citation summary dict.
    """
    # Per-citation tracking (indexed by position in citations list).
    citation_data: dict[int, dict] = {}
    failures: list[str] = []

    # Cache: query_text -> (rc, stdout, stderr)
    recall_cache: dict[str, tuple[int, str, str]] = {}

    for idx, query_type, query, section in queries:
        # Initialise citation entry if not seen yet.
        if idx not in citation_data:
            citation_data[idx] = {
                "filename": citations[idx][0],
                "obs_id": citations[idx][1],
                "line": citations[idx][2],
                "section": section,
                "superficie_hit": False,
                "fase_hit": False,
                "surface_failure": False,
                "surface_failure_details": [],
                "phase_failures": [],
                "has_superficie_query": query_type == "superficie",
            }
        elif query_type == "superficie":
            citation_data[idx]["has_superficie_query"] = True

        # Use cached recall result if available, otherwise call and cache.
        if query not in recall_cache:
            recall_cache[query] = recall_fn(motor_root, query, destino_root, limit)
        rc, stdout, stderr = recall_cache[query]

        if rc == 1 and "No observations found" in stderr:
            # rc 1 with "No observations found" in stderr = MISS, not a failure
            continue

        if rc != 0:
            # FAIL
            citation_data[idx]["phase_failures"].append(
                f"{query_type}:{query} -> rc={rc}"
            )
            if query_type == "superficie":
                citation_data[idx]["surface_failure"] = True
                citation_data[idx]["surface_failure_details"].append(query)
            failures.append(f"{citations[idx][1]}:{query_type}:{query}:rc={rc}")
            continue

        # rc == 0 -> evaluate hit
        citation = citations[idx]
        obs_id = citation[1]
        lesson_entry = pool_by_id.get(obs_id, {})
        hit = _is_hit(
            rc,
            stdout,
            obs_id,
            lesson_entry.get("topic", ""),
            lesson_entry.get("signal", ""),
        )

        if hit:
            if query_type == "superficie":
                citation_data[idx]["superficie_hit"] = True
            else:
                citation_data[idx]["fase_hit"] = True

    # Count hits and denominators per citation.
    hit_by_type: dict[str, int] = {
        "superficie": 0,
        "fase": 0,
        "union": 0,
    }
    denominators: dict[str, int] = {
        "superficie": 0,
        "fase": 0,
        "union": 0,
    }

    for idx, res in citation_data.items():
        has_surface = res.get("has_superficie_query", False)
        surface_failed = res.get("surface_failure", False)

        # Phase queries for this citation
        phase_queries_for_cit = [q for q in queries if q[0] == idx and q[1] == "fase"]
        # All phase queries failed = EVERY phase query of this citation is a FALLO
        # (one "fase:" failure entry per failed phase query). A mix of MISS and
        # FALLO keeps the citation in the denominator.
        phase_failure_count = sum(
            1 for detail in res["phase_failures"] if detail.startswith("fase:")
        )
        all_phase_failed = len(
            phase_queries_for_cit
        ) > 0 and phase_failure_count == len(phase_queries_for_cit)
        surface_excluded = (not has_surface) or surface_failed
        phase_excluded = all_phase_failed

        # Union denominator: exclude only when both types excluded.
        if not (surface_excluded and phase_excluded):
            denominators["union"] += 1

        # Superficie denominator: exclude if no surface query or surface failed.
        if has_surface and not surface_failed:
            denominators["superficie"] += 1

        # Fase denominator: exclude only if all phase queries failed.
        if len(phase_queries_for_cit) > 0 and not all_phase_failed:
            denominators["fase"] += 1

        surf_hit = res["superficie_hit"]
        fase_hit = res["fase_hit"]
        if surf_hit:
            hit_by_type["superficie"] += 1
        if fase_hit:
            hit_by_type["fase"] += 1
        if surf_hit or fase_hit:
            hit_by_type["union"] += 1

    # Build per-lesson aggregate (informational, not the DoD criterion).
    # Map: for each unique lesson_id, aggregate its citations' results.
    lesson_results: dict[str, dict] = {}
    # Collect unique obs_ids first
    unique_obs_ids: list[str] = []
    for res in citation_data.values():
        oid = res["obs_id"]
        if oid not in unique_obs_ids:
            unique_obs_ids.append(oid)
    # Aggregate per unique lesson_id
    for obs_id in unique_obs_ids:
        # Collect all citation indices for this lesson.
        cit_indices = [i for i, r in citation_data.items() if r["obs_id"] == obs_id]
        any_surface_hit = any(citation_data[i]["superficie_hit"] for i in cit_indices)
        any_fase_hit = any(citation_data[i]["fase_hit"] for i in cit_indices)
        has_surface = any(
            citation_data[i].get("has_superficie_query", False) for i in cit_indices
        )
        section = citation_data[cit_indices[0]]["section"] if cit_indices else ""
        lesson_results[obs_id] = {
            "superficie_hit": any_surface_hit,
            "fase_hit": any_fase_hit,
            "section": section,
            "has_superficie_query": has_surface,
            "cit_indices": cit_indices,
        }

    # Build per-citation summary for report.
    citation_summary: dict[int, dict] = {}
    for idx, res in citation_data.items():
        surface_hit = res["superficie_hit"]
        fase_hit = res["fase_hit"]
        citation_summary[idx] = {
            "filename": res["filename"],
            "obs_id": res["obs_id"],
            "line": res["line"],
            "section": res["section"],
            "surface_hit": surface_hit,
            "fase_hit": fase_hit,
            "union_hit": surface_hit or fase_hit,
        }

    return hit_by_type, denominators, lesson_results, failures, citation_summary


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _generate_report(
    hit_by_type: dict[str, int],
    denominators: dict[str, int],
    lesson_results: dict[str, dict],
    citation_summary: dict[int, dict],
    citations: list[tuple[str, str, int]],
    pool: list[dict],
    excluded_count: int,
    failures: list[str],
    motor_sha: str,
    output_path: Path,
) -> None:
    """Generate the markdown report and write it to ``output_path``.

    Before: all measurement results are computed.
    During: formats primary table (hit@5 by type, unit: citation), secondary
        table (per-lesson aggregate, informational), per-citation detail, and
        failures list.
    After: writes markdown file; does NOT raise.
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total_lessons_in_pool = len(pool)

    lines: list[str] = []
    lines.append(f"# Hit@5 recall quality report -- {now_utc}")
    lines.append("")
    lines.append(f"- **Motor SHA:** `{motor_sha}`")
    lines.append(f"- **Date:** {now_utc}")
    distinct_lessons = len({oid for _fn, oid, _ln in citations})
    lines.append(
        f"- **Citas de G (citadas y en el pool):** {len(citations) + excluded_count}"
    )
    lines.append(f"- **Citas de G excluidas:** {excluded_count}")
    lines.append(f"- **Citas no excluidas (unidad):** {len(citations)}")
    lines.append(
        f"- **Lecciones distintas en las citas no excluidas:** {distinct_lessons}"
    )
    lines.append(f"- **Total lecciones en pool:** {total_lessons_in_pool}")
    lines.append("")

    # ---- Primary table: Hit@5 por tipo (unidad: cita no excluida) ----
    lines.append("## Hit@5 por tipo (unidad: cita no excluida)")
    lines.append("")
    lines.append(
        "Denominador = citas no excluidas (DoD c), menos las citas cuyas queries "
        "de ese tipo fallaron (listadas en Fallos)."
    )
    lines.append("")
    lines.append("| Tipo | Hits | Denominador | Hit rate |")
    lines.append("|------|------|-------------|----------|")

    for qtype in ("superficie", "fase", "union"):
        hits = hit_by_type.get(qtype, 0)
        denom = denominators.get(qtype, 0)
        rate = f"{hits / denom:.1%}" if denom > 0 else "N/A"
        lines.append(f"| {qtype} | {hits} | {denom} | {rate} |")

    lines.append("")

    # ---- Secondary table: Agregado por leccion (informativo) ----
    lines.append("## Agregado por leccion (informativo, no es el criterio del DoD)")
    lines.append("")
    lines.append("Una leccion es HIT de un tipo si ALGUNA de sus citas es HIT.")
    lines.append("")
    lines.append("| Leccion | Seccion | Superficie | Fase |")
    lines.append("|---------|---------|------------|------|")

    for lid in sorted(lesson_results.keys()):
        res = lesson_results[lid]
        section = res.get("section", "")
        surf = "HIT" if res["superficie_hit"] else "MISS"
        fase = "HIT" if res["fase_hit"] else "MISS"
        lines.append(f"| {lid} | {section or '-'} | {surf} | {fase} |")

    lines.append("")

    # ---- Per-citation detail ----
    lines.append("## Detalle por cita")
    lines.append("")
    lines.append("| Fichero:Linea | ID | Seccion | Superficie | Fase | Union |")
    lines.append("|---------------|----|---------|------------|------|-------|")

    # Sort by (filename, line) for deterministic output.
    sorted_indices = sorted(
        citation_summary.keys(),
        key=lambda i: (citation_summary[i]["filename"], citation_summary[i]["line"]),
    )
    for idx in sorted_indices:
        s = citation_summary[idx]
        surface = "HIT" if s["surface_hit"] else "MISS"
        fase = "HIT" if s["fase_hit"] else "MISS"
        union = "HIT" if s["union_hit"] else "MISS"
        section = s["section"] or "-"
        lines.append(
            f"| {s['filename']}:{s['line']} | {s['obs_id']} | {section} | {surface} | {fase} | {union} |"
        )

    lines.append("")

    # ---- Fallos: toda query con rc != 0 que no sea "sin resultados" ----
    if failures:
        lines.append("## Fallos (queries de superficie o fase con rc != 0)")
        lines.append("")
        lines.append(
            "Formato: `<id>:<tipo>:<query>:rc=<n>`. Una cita sale del denominador "
            "de superficie si su query de superficie falla, y del de fase solo si "
            "fallan TODAS sus queries de fase; sale de la union solo si sale de "
            "ambos."
        )
        lines.append("")
        lines.extend([f"- {f}" for f in sorted(failures)])
        lines.append("")

    # ---- Excluded citations ----
    lines.append(f"Citas de G excluidas: {excluded_count}")
    lines.append("")

    # Sin seccion group (informational)
    sin_seccion = [lid for lid, res in lesson_results.items() if not res.get("section")]
    if sin_seccion:
        lines.append(f"Grupo 'sin seccion': {len(sin_seccion)} lecciones")
        lines.extend([f"- {lid}" for lid in sorted(sin_seccion)])
        lines.append("")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI and main
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point for the CLI.

    Before: CLI arguments parsed.
    During: orchestrates extraction, derivation, measurement, and reporting.
    After: writes --out or exits with error.
    """
    parser = argparse.ArgumentParser(
        description="Measure hit@5 of --recall --headlines on G lessons."
    )
    parser.add_argument(
        "--motor-root",
        required=True,
        help="Path to the motor repository root.",
    )
    parser.add_argument(
        "--destino-root",
        required=True,
        help="Path to the destino (project) root.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output markdown file path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Limit for --recall --headlines (default: 5).",
    )
    args = parser.parse_args()

    motor_root = Path(args.motor_root).resolve()
    destino_root = Path(args.destino_root).resolve()
    output_path = Path(args.out).resolve()

    # Step 1: git grep citations from motor repo
    try:
        raw_citations = _git_grep_cites(motor_root)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if not raw_citations:
        print(
            "ERROR: git grep found no citations. Aborting (fail-closed).",
            file=sys.stderr,
        )
        return 1

    # Step 2: load and deduplicate pool from both archives
    motor_entries = _load_archive_ids(motor_root)
    destino_entries = _load_archive_ids(destino_root)
    all_entries = motor_entries + destino_entries
    pool = _dedup_entries(all_entries)

    if not pool:
        print(
            "ERROR: no lessons in pool. Aborting (fail-closed).",
            file=sys.stderr,
        )
        return 1

    pool_by_id = {e.get("id"): e for e in pool if e.get("id")}

    # Step 3: intersect citations with pool -> universe G, BEFORE excluding,
    # so the excluded count refers to G citations (DoD b: "excluida y contada").
    g_citations = _intersect_with_pool(raw_citations, pool)
    if not g_citations:
        print(
            "ERROR: no citations intersect with pool. Aborting (fail-closed).",
            file=sys.stderr,
        )
        return 1

    # Filter out self-citations and useless stems at root
    citations, excluded_count = _filter_excluded_citations(
        g_citations, _EXCLUDED_SCRIPT_STEM
    )
    if not citations:
        print(
            "ERROR: all citations were excluded. Aborting (fail-closed).",
            file=sys.stderr,
        )
        return 1

    # Step 4: derive queries (indexed by citation position)
    queries = _build_queries_for_citations(citations, pool_by_id, motor_root)
    if not queries:
        print(
            "ERROR: no valid queries derived. Aborting (fail-closed).",
            file=sys.stderr,
        )
        return 1

    # Step 5: measure hit@5
    hit_by_type, denominators, lesson_results, failures, citation_summary = (
        _measure_hits(
            queries,
            citations,
            pool_by_id,
            motor_root,
            destino_root,
            args.limit,
            _recall_run,
        )
    )

    # Step 6: get motor SHA
    try:
        sha_out = subprocess.run(  # noqa: S603
            ["git", "-C", str(motor_root), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )
        motor_sha = sha_out.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        motor_sha = "unknown"

    # Step 7: generate report
    _generate_report(
        hit_by_type,
        denominators,
        lesson_results,
        citation_summary,
        citations,
        pool,
        excluded_count,
        failures,
        motor_sha,
        output_path,
    )

    print(f"Report written to {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
