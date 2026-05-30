#!/usr/bin/env python3
"""Pre-compact hook for preparation before compaction.

This hook recovers relevant context from observations.jsonl and the active
work_plan.md, projecting a compact "Memoria relevante" section into
additionalContext for Claude Code to consume before compacting.

The hook remains lightweight: no embeddings, no LLM, no heavy dependencies.
It uses two simple signals: recency and keyword matching from work_plan.
Output is capped at 5 observations maximum.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


# WP-2026-178: Ensure project root is on sys.path for memory loader import.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from bus.memory_loader import get_compact_context  # noqa: E402


# Derive AGENT_DIR from __file__ to avoid depending on cwd
AGENT_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = AGENT_DIR / "runtime" / "memory"
OBSERVATIONS_FILE = MEMORY_DIR / "observations.jsonl"
WORK_PLAN_FILE = AGENT_DIR / "collaboration" / "work_plan.md"

# Maximum observations to include in the projection
MAX_OBSERVATIONS = 5


def load_observations_safe() -> list[dict[str, Any]]:
    """Load observations from observations.jsonl safely.

    Before (Pre-conditions):
        - observations.jsonl may exist or not in MEMORY_DIR.
        - File may be empty, valid JSONL, or corrupted.

    During (Process and Resources):
        - Opens OBSERVATIONS_FILE if it exists.
        - Parses each line as JSON, skipping invalid lines.
        - Catches all I/O and JSON exceptions gracefully.

    After (Post-conditions and Errors):
        - Returns a list of valid observation dicts (may be empty).
        - Never raises; returns [] on any error.
    """
    observations: list[dict[str, Any]] = []
    if not OBSERVATIONS_FILE.exists():
        return observations

    try:
        with open(OBSERVATIONS_FILE, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    if isinstance(obs, dict):
                        observations.append(obs)
                except json.JSONDecodeError:
                    # Skip corrupted lines silently
                    pass
    except OSError:
        # File read error - return empty list
        return []

    return observations


def extract_keywords_from_work_plan() -> list[str]:
    """Extract keywords from the active work_plan.md.

    Before (Pre-conditions):
        - work_plan.md may exist or not in COLLABORATION_DIR.
        - File contains markdown text with objectives, metadata, etc.

    During (Process and Resources):
        - Reads WORK_PLAN_FILE if it exists.
        - Extracts significant words from Objetivo, Titulo, and metadata sections.
        - Filters out common stop words and markdown artifacts.

    After (Post-conditions and Errors):
        - Returns a list of lowercase keyword strings (may be empty).
        - Never raises; returns [] on any error.
    """
    if not WORK_PLAN_FILE.exists():
        return []

    try:
        content = WORK_PLAN_FILE.read_text(encoding="utf-8")
    except OSError:
        return []

    # Extract relevant sections: Objetivo, Titulo, metadata

    # Simple word extraction: alphanumeric words, lowercase
    words = re.findall(r"[a-zA-Z\u00C0-\u00FF0-9]+", content.lower())

    # Stop words to filter out (Spanish + common English)
    stop_words = {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "de",
        "del",
        "al",
        "en",
        "con",
        "sin",
        "para",
        "por",
        "que",
        "se",
        "no",
        "si",
        "es",
        "son",
        "ser",
        "esta",
        "este",
        "the",
        "a",
        "an",
        "and",
        "or",
        "in",
        "on",
        "at",
        "to",
        "for",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "wp",
        "md",
        "agent",
        "hook",
        "file",
        "test",
        "tests",
    }

    # Filter significant words: not in stop_words and length >= 3
    filtered_words = [
        word for word in words if word not in stop_words and len(word) >= 3
    ]

    # Return unique keywords, preserving order
    seen = set()
    unique_keywords = []
    for kw in filtered_words:
        if kw not in seen:
            seen.add(kw)
            unique_keywords.append(kw)

    return unique_keywords


def score_observation(obs: dict[str, Any], keywords: list[str]) -> int:
    """Score an observation based on recency and keyword matching.

    Before (Pre-conditions):
        - obs is a dict with optional 'timestamp', 'topic', 'signal', 'source'.
        - keywords is a list of lowercase keyword strings.

    During (Process and Resources):
        - Computes recency score based on timestamp (newer = higher).
        - Computes keyword match score based on topic and signal content.
        - Combines both scores with recency weighted higher.

    After (Post-conditions and Errors):
        - Returns an integer score (higher = more relevant).
        - Returns 0 if obs is empty or invalid.
    """
    if not obs:
        return 0

    score = 0

    # Recency score: parse timestamp, newer observations get higher scores
    timestamp = obs.get("timestamp", "")
    if timestamp:
        try:
            # Extract date part for simple recency scoring
            # Format: ISO 8601 like "2026-05-24T21:45:59.064645Z"
            date_part = timestamp[:10] if len(timestamp) >= 10 else ""
            if date_part:
                # Simple recency: more recent dates get higher scores
                # Use year, month, day as numeric components
                parts = date_part.split("-")
                if len(parts) == 3:
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                    # Base score from date (higher for more recent)
                    score += year * 10000 + month * 100 + day
        except (ValueError, IndexError):
            pass

    # Keyword matching score
    topic = str(obs.get("topic") or "").lower()
    signal = str(obs.get("signal") or "").lower()
    source = str(obs.get("source") or "").lower()

    text_to_match = f"{topic} {signal} {source}"

    for kw in keywords:
        if kw in text_to_match:
            score += 50  # Bonus for each keyword match

    return score


def rank_observations(
    observations: list[dict[str, Any]], keywords: list[str]
) -> list[dict[str, Any]]:
    """Rank observations by score (recency + keyword matching).

    Before (Pre-conditions):
        - observations is a list of observation dicts.
        - keywords is a list of lowercase keyword strings.

    During (Process and Resources):
        - Scores each observation using score_observation().
        - Sorts by score descending (highest first).
        - Caps the result at MAX_OBSERVATIONS.

    After (Post-conditions and Errors):
        - Returns a list of top observations (max MAX_OBSERVATIONS).
        - Returns [] if observations is empty.
    """
    if not observations:
        return []

    # Score and sort
    scored_obs = [(score_observation(obs, keywords), obs) for obs in observations]
    scored_obs.sort(key=lambda x: x[0], reverse=True)

    # Return top observations, capped at MAX_OBSERVATIONS
    top_obs = [obs for score, obs in scored_obs[:MAX_OBSERVATIONS]]
    return top_obs


def format_memory_section(observations: list[dict[str, Any]]) -> str:
    """Format observations as a compact "Memoria relevante" section.

    Before (Pre-conditions):
        - observations is a list of ranked observation dicts.

    During (Process and Resources):
        - Formats each observation as a bullet point.
        - Includes timestamp, topic, and signal summary.

    After (Post-conditions and Errors):
        - Returns a formatted markdown string.
        - Returns empty string if observations is empty.
    """
    if not observations:
        return ""

    lines = ["**Memoria relevante**:", ""]
    for obs in observations:
        timestamp = str(obs.get("timestamp") or "")[:10]  # Just date part
        topic = str(obs.get("topic") or "sin-topic")
        signal = str(obs.get("signal") or "")[:100]  # Truncate long signals
        source = str(obs.get("source") or "")

        if signal:
            lines.append(f"- [{timestamp}] **{topic}**: {signal} (fuente: {source})")
        else:
            lines.append(f"- [{timestamp}] **{topic}** (fuente: {source})")

    return "\n".join(lines)


def main() -> None:
    """Main entry point for pre-compact hook.

    Before (Pre-conditions):
        - stdin contains valid JSON input (or empty/invalid).
        - observations.jsonl may exist, be empty, or corrupted.
        - work_plan.md may exist or not.

    During (Process and Resources):
        - Reads and parses stdin JSON safely.
        - Loads observations from MEMORY_DIR safely.
        - Extracts keywords from WORK_PLAN_FILE.
        - Ranks observations by recency and keyword matching.
        - Builds additionalContext with "Memoria relevante" section.
        - Outputs JSON result with continue=true.

    After (Post-conditions and Errors):
        - Prints valid JSON to stdout with "continue" and "additionalContext".
        - Exits with code 0 (continue) or 1 (error).
        - Never crashes on missing/corrupted files.
    """
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception):
        input_data = {}

    # WP-2026-178: Prefer L2+L3 compact context from the memory loader.
    # Falls back to keyword-based L1 ranking when loader returns empty.
    compact_context = get_compact_context()

    if compact_context:
        # Loader returned structured L2/L3 content; use it directly.
        additional_context = f"**Memoria del proyecto (L2+L3)**:\n\n{compact_context}"
    else:
        # Fallback: keyword-based L1 ranking from observations.jsonl
        observations = load_observations_safe()
        keywords = extract_keywords_from_work_plan()
        ranked_obs = rank_observations(observations, keywords)
        additional_context = format_memory_section(ranked_obs)

    # Always continue - this hook is for context projection only
    continue_flag = True

    # Output result
    result: dict[str, Any] = {
        "continue": continue_flag,
        "input": input_data,
    }

    # Only include additionalContext if there's relevant memory
    if additional_context:
        result["additionalContext"] = additional_context

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if continue_flag else 1)


if __name__ == "__main__":
    main()
