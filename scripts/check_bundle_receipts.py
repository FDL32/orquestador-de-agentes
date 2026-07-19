#!/usr/bin/env python3
"""Deterministic receipt-guard for governance-loop bundles (mejora-continua v0).

Attacks HUECO-1 (confirmed live 2026-07-19): the phase-`1` collector that builds
the bundle consumed by the nan fan-out has NO safety net -- a single agent writes
it, and the nan models have no filesystem, so a probe stated WITHOUT a real
receipt propagates a false premise to all 9 lenses. In the 025h MANAGER_REVIEW the
8 nan returned SHIP unanimously and only the Codex-with-filesystem refuter caught a
real bug; this guard is the CHEAP, DETERMINISTIC first line before that.

This is the NON-PROMPT part of the "bundle-guard in the 3 governments" the user
approved (2026-07-19). It does NOT touch the governance prompt .md files
(anti-recursion 026b): it validates a bundle FILE for receipt completeness. The
LLM pass (Codex) and the prompt wiring are deferred to the formal PDCA ticket.

Receipt convention (v0): a bundle is markdown with `## PROBE ...` sections. Every
PROBE section that makes an executable claim MUST carry a fenced receipt block:

    ## PROBE 3 -- grep 'report' in the script
    ```receipt
    command: grep -n report scripts/prune_runtime_retention.py
    exit_code: 0
    path: scripts/prune_runtime_retention.py
    output: |
      255:    return report
    ```

Rules enforced (fail-closed):
  - every `## PROBE` section has a ```receipt fenced block;
  - each receipt declares `command:` and `exit_code:` (a claim without a receipt
    is exploratory evidence, never a closing probe -- CEM);
  - every `path:` in a receipt is RELATIVE, stays INSIDE --root, and RESOLVES on
    disk (an absolute path or a `..`-escape would .exists() outside the repo -> a
    wrong-root false green; a non-existent file is a false receipt);
  - `exit_code:` is an integer.
A PROBE section explicitly marked `<!-- no-receipt: <reason> -->` is exempt (for
narrative/context sections that make no executable claim); the reason is required.

Before:
  - --bundle points at an existing markdown bundle; --root is the repo the probe
    paths are relative to (default: cwd).
During:
  - Parse `## PROBE` sections, extract receipt blocks, validate each rule; read-only.
After:
  - Prints a per-probe report. Exit 0 iff every probe has a valid receipt (or an
    explicit exemption). Exit 1 on any violation or usage error. Never writes.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


_PROBE_HEADER_RE = re.compile(r"^##\s+PROBE\b.*$", re.MULTILINE)
_RECEIPT_FENCE_RE = re.compile(r"```receipt\s*\n(.*?)```", re.DOTALL)
_EXEMPT_RE = re.compile(r"<!--\s*no-receipt:\s*(.+?)\s*-->")
_COMMAND_RE = re.compile(r"^command:\s*(.+)$", re.MULTILINE)
_EXIT_RE = re.compile(r"^exit_code:\s*(.+)$", re.MULTILINE)
_PATH_RE = re.compile(r"^path:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class ProbeResult:
    header: str
    ok: bool
    problems: tuple[str, ...]
    exempt_reason: str | None


def _split_probe_sections(text: str) -> list[tuple[str, str]]:
    """Return [(header_line, section_body)] for each `## PROBE` section (body runs
    up to the next `## ` header of any kind)."""
    sections: list[tuple[str, str]] = []
    for m in _PROBE_HEADER_RE.finditer(text):
        start = m.start()
        # Body ends at the next top-level `## ` header (probe or not).
        next_h = re.search(r"^##\s+", text[m.end() :], re.MULTILINE)
        end = m.end() + next_h.start() if next_h else len(text)
        sections.append((m.group(0).strip(), text[start:end]))
    return sections


def validate_receipt(body: str, root: Path) -> tuple[bool, list[str]]:
    """Validate ONE probe body's receipt. Returns (ok, problems)."""
    problems: list[str] = []
    fence = _RECEIPT_FENCE_RE.search(body)
    if not fence:
        return False, ["no ```receipt block (a claim without a receipt is not a probe)"]
    receipt = fence.group(1)
    if not _COMMAND_RE.search(receipt):
        problems.append("receipt missing `command:`")
    exit_m = _EXIT_RE.search(receipt)
    if not exit_m:
        problems.append("receipt missing `exit_code:`")
    else:
        raw = exit_m.group(1).strip()
        try:
            int(raw)
        except ValueError:
            problems.append(f"exit_code is not an integer: {raw!r}")
    for path_m in _PATH_RE.finditer(receipt):
        rel = path_m.group(1).strip()
        # A receipt path must be INSIDE --root and resolve. An absolute path (or a
        # `..` escape) would let `root / rel` land OUTSIDE the repo and still
        # .exists() -> a wrong-root false green (Codex closing audit 2026-07-19).
        # Reject anything that is absolute or resolves outside root FIRST.
        cand = Path(rel)
        if cand.is_absolute():
            problems.append(
                f"cited path is absolute (must be relative to --root): {rel}"
            )
            continue
        try:
            resolved = (root / cand).resolve()
            root_r = root.resolve()
            inside = resolved == root_r or root_r in resolved.parents
        except (OSError, ValueError):
            inside = False
        if not inside:
            problems.append(f"cited path escapes --root: {rel}")
        elif not resolved.exists():
            problems.append(f"cited path does not resolve: {rel}")
    return (not problems), problems


def check_bundle(bundle_text: str, root: Path) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    for header, body in _split_probe_sections(bundle_text):
        exempt = _EXEMPT_RE.search(body)
        if exempt:
            results.append(ProbeResult(header, True, (), exempt.group(1)))
            continue
        ok, problems = validate_receipt(body, root)
        results.append(ProbeResult(header, ok, tuple(problems), None))
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic receipt-guard for governance-loop bundles: every PROBE "
            "section must carry a ```receipt with command/exit_code and resolvable "
            "paths (mejora-continua v0, HUECO-1)."
        )
    )
    parser.add_argument("--bundle", type=Path, required=True, help="Bundle .md path.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repo root the probe paths are relative to (default: cwd).",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    bundle: Path = args.bundle
    if not bundle.is_file():
        print(f"Error: bundle not found: {bundle}", file=sys.stderr)
        return 1
    text = bundle.read_bytes().decode("utf-8", errors="replace")
    results = check_bundle(text, args.root)
    if not results:
        print(f"Error: no `## PROBE` sections found in {bundle}", file=sys.stderr)
        return 1

    failed = [r for r in results if not r.ok]
    for r in results:
        if r.exempt_reason is not None:
            print(f"  EXEMPT  {r.header}  ({r.exempt_reason})")
        elif r.ok:
            print(f"  OK      {r.header}")
        else:
            print(f"  MISSING {r.header}")
            for p in r.problems:
                print(f"            - {p}")
    print(
        f"[bundle-receipts] {len(results)} probe(s), "
        f"{len(results) - len(failed)} ok, {len(failed)} without a valid receipt"
    )
    return 1 if failed else 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
