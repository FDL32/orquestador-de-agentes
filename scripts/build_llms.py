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

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = "https://raw.githubusercontent.com/FDL32/orquestacion-agentes/main"

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
        "session_bootstrap.md",
        "prompts/session_bootstrap.md",
        "Philosophy & onboarding",
    ),
    (
        "refactor_bootstrap.md",
        "prompts/refactor_bootstrap.md",
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
    "prompts/session_bootstrap.md",
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
            "- `uv run pip-audit .` — supply-chain audit.",
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


def main() -> int:
    base_url = os.environ.get("LLMS_REPO_BASE", DEFAULT_BASE).rstrip("/")

    index = build_index_block(base_url)
    (PROJECT_ROOT / "llms.txt").write_text(index, encoding="utf-8")

    full = build_full_block(base_url, index)
    (PROJECT_ROOT / "llms-full.txt").write_text(full, encoding="utf-8")

    print(
        f"[OK] llms.txt ({len(index)} bytes) + llms-full.txt ({len(full)} bytes) generated."
    )
    print(f"     Base URL: {base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
