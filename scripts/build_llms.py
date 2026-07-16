#!/usr/bin/env python3
"""Generate llms.txt + llms-full.txt as machine-readable doc map.

Inspired by garrytan/gbrain (TS) pattern but adapted for our Python repo.
Both files live at repo root and point to canonical agent-facing docs.

llms.txt: ~80-line index with URLs.
llms-full.txt: same index with core docs inlined for single-fetch ingestion.

Default URL base is configurable via LLMS_REPO_BASE env var; forks override
without editing source.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
# WOT-2026-024g: default points to the REAL public repo. The old default
# (FDL32/orquestacion-agentes) is a 404; the canonical repo is
# FDL32/orquestador-de-agentes (verified public, HTTP 200, 2026-07-16).
DEFAULT_BASE = "https://raw.githubusercontent.com/FDL32/orquestador-de-agentes/main"

# Entries listed in the order an agent should read them.
# Each: (label, relative_path, section_heading).
ENTRIES: list[tuple[str, str, str]] = [
    (
        "AGENTS.md",
        "AGENTS.md",
        "Core entry points",
    ),
    (
        "CLAUDE.md",
        "CLAUDE.md",
        "Core entry points",
    ),
    (
        "QUICKSTART.md",
        "QUICKSTART.md",
        "Core entry points",
    ),
    (
        "PROJECT.md",
        "PROJECT.md",
        "Core entry points",
    ),
    (
        "CHANGELOG.md",
        "CHANGELOG.md",
        "Core entry points",
    ),
    (
        "INTERACTION_MODES.md",
        "INTERACTION_MODES.md",
        "Configuration",
    ),
    (
        "agents.json",
        ".agent/config/agents.json",
        "Configuration",
    ),
    (
        "pyproject.toml",
        "pyproject.toml",
        "Configuration",
    ),
    (
        "local_audit.py",
        "scripts/local_audit.py",
        "Debugging & introspection",
    ),
    (
        "agent_controller.py",
        ".agent/agent_controller.py",
        "Debugging & introspection",
    ),
    (
        "test_manager_smoke.ps1",
        "scripts/test_manager_smoke.ps1",
        "Debugging & introspection",
    ),
    (
        "orchestrator_session_bootstrap.md",
        "prompts/orchestrator_session_bootstrap.md",
        "Philosophy & onboarding",
    ),
    (
        "orchestrator_refactor_bootstrap.md",
        "prompts/orchestrator_refactor_bootstrap.md",
        "Philosophy & onboarding",
    ),
    (
        "skills/local-audit",
        "skills/local-audit/SKILL.md",
        "Skills (read RESOLVER first)",
    ),
    (
        "skills/repo-compare",
        "skills/repo-compare/SKILL.md",
        "Skills (read RESOLVER first)",
    ),
    (
        "skills/refactor-manager",
        "skills/refactor-manager/SKILL.md",
        "Skills (read RESOLVER first)",
    ),
    (
        "skills/project-finalize",
        "skills/project-finalize/SKILL.md",
        "Skills (read RESOLVER first)",
    ),
    (
        "skills/version-changelog",
        "skills/version-changelog/SKILL.md",
        "Skills (read RESOLVER first)",
    ),
]

# Files to inline in llms-full.txt (kept small; large files stay reference-only).
INLINE_IN_FULL: list[str] = [
    "AGENTS.md",
    "CLAUDE.md",
    "prompts/orchestrator_session_bootstrap.md",
    "skills/local-audit/SKILL.md",
    "skills/repo-compare/SKILL.md",
]


def build_index_block(base_url: str) -> str:
    lines = [
        "# orquestador_de_agentes",
        "",
        "> Multi-agent orchestration template (Manager/Builder/Supervisor). "
        "Python 3.10+ runtime, OpenCode backend, terminal-driven flow, canonical "
        "state in `.agent/`, skills under `skills/`, hard scope gate, anti-fabrication "
        "verification protocol. Local audit + repo compare + refactor manager are "
        "first-class skills.",
        "",
        f"Repo: {base_url}",
        "",
    ]

    grouped: dict[str, list[tuple[str, str]]] = {}
    section_order: list[str] = []
    for label, rel_path, section in ENTRIES:
        if section not in grouped:
            grouped[section] = []
            section_order.append(section)
        grouped[section].append((label, rel_path))

    for section in section_order:
        lines.append(f"## {section}")
        lines.append("")
        for label, rel_path in grouped[section]:
            url = f"{base_url}/{rel_path}"
            lines.append(f"- [{label}]({url})")
        lines.append("")

    lines.extend(
        [
            "## Operational tips",
            "",
            "- `python scripts/local_audit.py [--quick]` — 40-line snapshot (version, active plan, git, skills, recent WPs, memory).",
            "- `python .agent/agent_controller.py --validate --json --force` — drift detection.",
            "- `python scripts/run_pytest_safe.py` — test suite for current scope.",
            "- `ruff check . && ruff format .` — lint + format.",
            "- `python scripts/pip_audit_project.py` — supply-chain audit from uv.lock.",
            "- `python scripts/build_llms.py` — regenerate this file + llms-full.txt.",
            "",
        ]
    )

    lines.append("## Forks")
    lines.append("")
    lines.append(
        "If you fork, override the URL base before regenerating: "
        "`LLMS_REPO_BASE=https://raw.githubusercontent.com/your-org/your-fork/main "
        "python scripts/build_llms.py`."
    )
    lines.append("")
    return "\n".join(lines)


def build_full_block(base_url: str, index: str) -> str:
    chunks = [index, "", "---", "", "# Inlined core docs", ""]
    for rel_path in INLINE_IN_FULL:
        path = PROJECT_ROOT / rel_path
        if not path.exists():
            chunks.append(f"## {rel_path}\n\n_(not found at generation time)_\n")
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            body = path.read_text(encoding="utf-8-sig", errors="replace")
        chunks.append(f"## {rel_path}")
        chunks.append("")
        chunks.append("```markdown")
        chunks.append(body)
        chunks.append("```")
        chunks.append("")
    return "\n".join(chunks)


def _resolve_base(cli_base: str | None) -> str:
    """Resolve the URL base. Precedence: --base > LLMS_REPO_BASE env > DEFAULT_BASE.

    Forks keep overriding via the env var without editing source; the CLI flag
    wins when both are present so a one-off regeneration can target any repo.
    """
    if cli_base:
        return cli_base.rstrip("/")
    return os.environ.get("LLMS_REPO_BASE", DEFAULT_BASE).rstrip("/")


def render(base_url: str) -> tuple[str, str]:
    """Render llms.txt + llms-full.txt content IN MEMORY (no disk writes)."""
    index = build_index_block(base_url)
    full = build_full_block(base_url, index)
    return index, full


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate (or --check) llms.txt + llms-full.txt doc map."
    )
    parser.add_argument(
        "--base",
        default=None,
        help=(
            "URL base for the repo (default: real public repo, or LLMS_REPO_BASE "
            "env). Forks may override here or via the env var."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Regenerate in memory and compare against the files on disk. "
            "Exit 0 if identical, exit 1 (drift) if not. Writes nothing."
        ),
    )
    args = parser.parse_args(argv)

    base_url = _resolve_base(args.base)
    index, full = render(base_url)

    index_path = PROJECT_ROOT / "llms.txt"
    full_path = PROJECT_ROOT / "llms-full.txt"

    if args.check:
        drift: list[str] = []
        for path, expected in ((index_path, index), (full_path, full)):
            on_disk = path.read_text(encoding="utf-8") if path.exists() else None
            if on_disk != expected:
                drift.append(path.name)
        if drift:
            print(
                f"[DRIFT] {', '.join(drift)} out of sync with generator. "
                f"Run `python scripts/build_llms.py` to regenerate."
            )
            return 1
        print(f"[OK] llms.txt + llms-full.txt in sync (base {base_url}).")
        return 0

    index_path.write_text(index, encoding="utf-8")
    full_path.write_text(full, encoding="utf-8")

    print(
        f"[OK] llms.txt ({len(index)} bytes) + llms-full.txt ({len(full)} bytes) generated."
    )
    print(f"     Base URL: {base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
