"""
Memory helpers for observation management.

WP-2026-122: Uses runtime.project_root for dynamic project root resolution.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


# WP-2026-122: Deferred path resolution - this module is already in runtime/memory/
# so we use __file__ based resolution which is correct for the memory directory


def get_memory_dir() -> Path:
    """Get the memory directory path (where this module lives)."""
    return Path(__file__).resolve().parent


def get_observations_file() -> Path:
    return get_memory_dir() / "observations.jsonl"


def validate_observation(observation: dict) -> bool:
    required = {"timestamp", "topic", "signal", "source"}
    return required.issubset(observation.keys())


def append_observation(observation: dict) -> bool:
    if not validate_observation(observation):
        return False
    memory_dir = get_memory_dir()
    memory_dir.mkdir(parents=True, exist_ok=True)
    observations_file = get_observations_file()
    with observations_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, ensure_ascii=False) + "\n")
    return True


def read_observations() -> list[dict]:
    observations_file = get_observations_file()
    if not observations_file.exists():
        return []
    observations: list[dict] = []
    for line in observations_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            observations.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return observations


def create_memory_index() -> bool:
    memory_dir = get_memory_dir()
    memory_dir.mkdir(parents=True, exist_ok=True)
    observations = read_observations()
    memory_file = memory_dir / "MEMORY.md"
    if not observations:
        empty_message = (
            "No hay observaciones registradas a" + chr(250) + "n. "
            "No hay observaciones registradas aÃºn."
        )
        memory_file.write_text(
            f"# MEMORY\n\n{empty_message}\n",
            encoding="utf-8",
        )
        return True

    topics = Counter(
        str(item.get("topic", "sin tema")).title() for item in observations
    )
    lines = ["# MEMORY", "", f"Total de observaciones: {len(observations)}", ""]
    for topic, count in sorted(topics.items()):
        lines.append(f"- {topic} ({count} observaciones)")
    lines.append("")
    for item in observations:
        lines.append(f"## {item.get('topic', 'sin tema')}")
        lines.append(f"- {item.get('signal', '')}")
        lines.append("")
    memory_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return True
