#!/usr/bin/env python3
"""Detect divergence between the portable gitleaks seed and a target config.

WOT-2026-039k. The seed ``agent_system/templates/gitleaks.config.toml`` is
provisioned to destinos by ``install_agent_system.copy_gitleaks_config`` with a
NO-CLOBBER rule: a destino that already owns a ``.gitleaks.toml`` never receives
later additions to the seed (the 027n/063c/089l allowlists, added after the
destino was provisioned, never reached it). Byte-identity between the seed and
the motor root is already checked by ``check_publication_gate.check_gitleaks_config``;
that check is WRONG for a destino, whose file legitimately carries a LOCAL
section the seed does not have.

This guard closes the gap the no-clobber opened, WITHOUT merging TOML:

Before:
    ``seed`` is the portable seed (or any file with ``[[allowlists]]`` blocks);
    ``target`` is a candidate config (motor root, or a destino's ``.gitleaks.toml``)
    that already exists, is absent, or is unparseable.
During:
    Parses the ``[[allowlists]]`` blocks of BOTH files and reduces each block to
    the set of EXACT values it suppresses (``regexes``/``paths``/``commits``/
    ``stopwords``), order-insensitive. It is pure DETECTION: it never edits the
    target. A seed block is "present" iff some target block suppresses AT LEAST
    those values (subset test), so a destino may carry a superset (local values
    added) and its local-only blocks are ignored, never a false positive.
After:
    Returns the descriptions of the seed blocks whose value set is missing,
    NAMING each absent structural section. ``tomllib.TOMLDecodeError`` is
    reported as cause ``UNPARSEABLE`` and exit 2 -- a LOAD failure is NOT a
    detection (a mutation that breaks the file must not be read as a hit); the
    reason a mutation only counts if the mutated artifact STILL LOADS.

Exit codes: 0 = every seed section present; 1 = DIVERGENT/ABSENT/SEED_MISSING
(named); 2 = load error (target unparseable), never read as detection.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


try:  # tomllib is stdlib on 3.11+; the motor supports 3.10 via the tomli dep.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib  # type: ignore[no-redef]


MOTOR_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = MOTOR_ROOT / "agent_system" / "templates" / "gitleaks.config.toml"
MOTOR_ROOT_CONFIG = MOTOR_ROOT / ".gitleaks.toml"

# The keys that carry the exact values an allowlist block suppresses. A block
# without any of them suppresses nothing and is not a structural section.
_ALLOWLIST_VALUE_KEYS = ("regexes", "paths", "commits", "stopwords")


def load_allowlist_blocks(text: str) -> list[dict[str, Any]]:
    """Parse the ``[[allowlists]]`` blocks of a gitleaks config.

    Before: ``text`` is the raw content of a TOML config.
    During: parses with ``tomllib``; a config with no ``allowlists`` key yields [].
    After: returns the list of block dicts; raises ``tomllib.TOMLDecodeError``
           when the text does not parse (the caller reports it as a load error).
    """
    data = tomllib.loads(text)
    blocks = data.get("allowlists", [])
    if not isinstance(blocks, list):
        return []
    return [b for b in blocks if isinstance(b, dict)]


def block_values(block: dict[str, Any]) -> frozenset[str]:
    """Exact allowlist values a block suppresses, order-insensitive."""
    values: set[str] = set()
    for key in _ALLOWLIST_VALUE_KEYS:
        raw = block.get(key)
        if isinstance(raw, str):
            values.add(raw)
        elif isinstance(raw, list):
            values.update(str(v) for v in raw)
    return frozenset(values)


def _label(block: dict[str, Any]) -> str:
    desc = str(block.get("description", "")).strip()
    return desc or "<allowlist block sin description>"


def missing_seed_sections(seed_text: str, target_text: str) -> list[str]:
    """Descriptions of the seed blocks whose exact values are NOT in the target.

    A seed block is present iff some target block suppresses AT LEAST its values
    (subset). Extra target blocks (the destino's LOCAL section) never match a
    seed block on their own, and are ignored -- the local section is preserved,
    only the absent seed sections are named.

    Before: both strings are TOML; raises ``tomllib.TOMLDecodeError`` otherwise.
    During: pure comparison, no writes.
    After: list of labels, in seed order; empty when the target carries them all.
    """
    target_sets = [block_values(b) for b in load_allowlist_blocks(target_text)]
    missing: list[str] = []
    for block in load_allowlist_blocks(seed_text):
        values = block_values(block)
        if not values:
            continue  # a block that suppresses nothing is not a section
        if not any(values <= target for target in target_sets):
            missing.append(_label(block))
    return missing


def check_pair(seed_path: Path, target_path: Path) -> dict[str, Any]:
    """Report for one (seed, target) pair. Never raises, never writes.

    After: ``{"ok": bool, "cause": None|"SEED_MISSING"|"ABSENT"|"UNPARSEABLE"|
           "DIVERGENT", "missing": [...], "seed": str, "target": str}``.
    """
    report: dict[str, Any] = {
        "ok": False,
        "cause": None,
        "missing": [],
        "seed": str(seed_path),
        "target": str(target_path),
    }
    if not seed_path.exists():
        report["cause"] = "SEED_MISSING"
        return report
    # An absent target is an EMPTY (parses fine) config: every seed section is
    # missing. We keep it as a distinct cause so the caller can tell "no file"
    # apart from "file present but missing sections".
    target_text = ""
    if target_path.exists():
        target_text = target_path.read_text(encoding="utf-8")
    try:
        seed_text = seed_path.read_text(encoding="utf-8")
        missing = missing_seed_sections(seed_text, target_text)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        report["cause"] = "UNPARSEABLE"
        report["detail"] = f"{exc}"
        return report
    report["missing"] = missing
    if not target_path.exists():
        report["cause"] = "ABSENT"
    elif missing:
        report["cause"] = "DIVERGENT"
    else:
        report["ok"] = True
    return report


def warn_on_seed_divergence(
    seed_path: Path, target_path: Path, *, stream: Any = None
) -> dict[str, Any]:
    """Print a WARN naming every absent seed section (used by the installer).

    Before: ``seed_path`` and ``target_path`` are paths (target may be absent).
    During: runs ``check_pair``; if not ok, prints ONE line naming the missing
            sections (never edits the target -- the local section is preserved).
    After: returns the report for the caller to act on.
    """
    out = stream or sys.stdout
    report = check_pair(seed_path, target_path)
    if report["cause"] in (None, "ABSENT", "DIVERGENT"):
        if not report["ok"]:
            print(
                "[WARN] .gitleaks.toml diverge del seed "
                f"({report['cause']}); secciones estructurales ausentes: "
                f"{report['missing']}",
                file=out,
            )
    elif report["cause"] == "UNPARSEABLE":
        print(
            "[WARN] .gitleaks.toml no es parseable (load error, NO divergencia): "
            f"{report.get('detail', '')}",
            file=out,
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument(
        "--seed", type=Path, default=SEED_PATH, help="portable gitleaks seed"
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="config to inspect (default: motor root .gitleaks.toml)",
    )
    parser.add_argument(
        "--destino",
        type=Path,
        default=None,
        help="destino root; inspects <destino>/.gitleaks.toml (seed<->destino pair)",
    )
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    args = parser.parse_args(argv)

    if args.destino is not None:
        target = Path(args.destino) / ".gitleaks.toml"
    else:
        target = args.target or MOTOR_ROOT_CONFIG

    report = check_pair(Path(args.seed), target)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif report["cause"] == "UNPARSEABLE":
        print(f"[gitleaks-seed] LOAD ERROR (no es una deteccion): {report['detail']}")
    elif report["ok"]:
        print(f"[gitleaks-seed] OK: {target} contiene todas las secciones del seed.")
    else:
        print(
            f"[gitleaks-seed] {report['cause']}: {target} diverge del seed "
            f"({report['seed']}). Secciones estructurales ausentes:"
        )
        for label in report["missing"]:
            print(f"    - {label}")
    return 0 if report["ok"] else (2 if report["cause"] == "UNPARSEABLE" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
