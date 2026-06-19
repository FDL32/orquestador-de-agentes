from __future__ import annotations

from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / ".agent"

TEXT_EXTENSIONS = frozenset(
    {
        ".md",
        ".py",
        ".json",
        ".jsonl",
        ".toml",
        ".yaml",
        ".yml",
        ".sh",
        ".ps1",
        ".txt",
        ".xml",
    }
)

SUSPICIOUS_CODEPOINTS = {
    0x00C3,
    0x00C2,
    0x00E2,
    0x00F0,
    0x0102,
    0xFFFD,
}

STATIC_FILES_TO_CHECK = [
    AGENT_DIR / "agent_controller.py",
    AGENT_DIR / "completion_checker.py",
    ROOT / "scripts" / "update_project_map.py",
    AGENT_DIR / "README.md",
    AGENT_DIR / "hooks" / "stop_hook.py",
    AGENT_DIR / "completion_common.py",
    AGENT_DIR / "collaboration" / "work_plan.md",
    AGENT_DIR / "collaboration" / "execution_log.md",
    AGENT_DIR / "collaboration" / "notifications.md",
    AGENT_DIR / "collaboration" / "TURN.md",
    AGENT_DIR / "workflows" / "manager_workflow.md",
    AGENT_DIR / "workflows" / "builder_workflow.md",
    AGENT_DIR / "templates" / "LEGACY_NOTE.md",
    AGENT_DIR / "templates" / "work_plan_template.md",
    AGENT_DIR / "templates" / "findings_template.md",
    AGENT_DIR / "templates" / "PRIVATE_REGISTRY.md",
    AGENT_DIR / "templates" / "work_plan_example_v2.md",
    AGENT_DIR / "legacy" / "LEGACY_NOTE.md",
    AGENT_DIR / "legacy" / "manager_workflow.md",
    AGENT_DIR / "legacy" / "builder_workflow.md",
    AGENT_DIR / "legacy" / "MANAGER_SKILLS.md",
    AGENT_DIR / "legacy" / "BUILDER_SKILLS.md",
    AGENT_DIR / "legacy" / "MANAGER_CONTEXT.md",
    AGENT_DIR / "legacy" / "BUILDER_CONTEXT.md",
]

GLOB_PATTERNS = [
    "skills/**/*.md",
    "prompts/**/*.md",
    "scripts/**/*.py",
    ".claude/**/*.md",
    "runtime/**/*.py",
    "bus/**/*.py",
    ".agent/**/*.py",
    "*.md",
]

EXCLUDE_PATTERNS = {
    "scripts/sandbox/**",
    ".agent/backups/**",
    ".agent/runtime/uv-cache/**",
}

ALLOWLIST = {}


def relative_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def find_mojibake(text: str) -> list[str]:
    snippets: list[str] = []
    for idx, ch in enumerate(text):
        if ord(ch) not in SUSPICIOUS_CODEPOINTS:
            continue
        snippet = text[idx : idx + 4]
        if snippet not in snippets:
            snippets.append(snippet)
    return snippets


def find_q_in_word(text: str) -> list[str]:
    matches: list[str] = []
    for idx, ch in enumerate(text[1:-1], start=1):
        if ch != "?":
            continue
        prev_char = text[idx - 1]
        next_char = text[idx + 1]
        if prev_char.isalpha() and next_char.isalpha():
            snippet = text[idx - 1 : idx + 2]
            if snippet not in matches:
                matches.append(snippet)
    return matches


# ASCII control chars (<32) that are legitimate in text files: tab, line feed,
# carriage return. Everything else below 0x20 (e.g. 0x00 NUL, 0x07 BEL, 0x0B VT,
# 0x0C FF) is corruption — the class that slipped past the guard in WOT-2026-008f
# and 008j because the guard only inspected codepoints >127 (mojibake/BOM).
_ALLOWED_CONTROL_CHARS = frozenset({"\t", "\n", "\r"})


def find_control_chars(text: str) -> list[str]:
    """Return snippets around disallowed ASCII control chars (<32, not tab/LF/CR).

    Each snippet shows the control char as ``<0xNN>`` with up to 3 chars of
    following context, deduplicated, so the report is human-readable. CRLF is
    fine because both \\r and \\n are allowed.
    """
    snippets: list[str] = []
    for idx, ch in enumerate(text):
        if ord(ch) >= 32 or ch in _ALLOWED_CONTROL_CHARS:
            continue
        marker = f"<0x{ord(ch):02X}>"
        tail = text[idx + 1 : idx + 4].replace("\n", "\\n").replace("\r", "\\r")
        snippet = marker + tail
        if snippet not in snippets:
            snippets.append(snippet)
    return snippets


def is_excluded(relative: str) -> bool:
    return any(fnmatch(relative, pattern) for pattern in EXCLUDE_PATTERNS)


def is_allowlisted(relative: str) -> bool:
    return relative in ALLOWLIST


@lru_cache(maxsize=1)
def collect_files_to_check() -> tuple[Path, ...]:
    files = {path for path in STATIC_FILES_TO_CHECK}
    for pattern in GLOB_PATTERNS:
        files.update(path for path in ROOT.glob(pattern) if path.is_file())
    return tuple(sorted(path for path in files if not is_excluded(relative_path(path))))


@lru_cache(maxsize=1)
def collect_scope_set() -> frozenset[Path]:
    return frozenset(collect_files_to_check())


def is_in_scope(relative: str) -> bool:
    if is_excluded(relative):
        return False
    candidate = ROOT / relative
    return candidate in collect_scope_set()


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def has_utf8_bom(path: Path) -> bool:
    return path.read_bytes().startswith(b"\xef\xbb\xbf")


def file_issues(path: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (mojibake, question_mark, control_char) issue snippets for path.

    WOT-2026-010v: the third element is the disallowed ASCII control chars found
    in the file. Consumers (check_encoding_guard.py CLI, encoding_post_write_hook)
    unpack all three and inherit control-char detection without a parallel
    detector.
    """
    text = load_text(path)
    return find_mojibake(text), find_q_in_word(text), find_control_chars(text)


def iter_staged_files(paths: list[str]) -> list[Path]:
    staged: list[Path] = []
    for rel in paths:
        candidate = ROOT / rel
        if candidate.exists() and candidate.is_file() and is_in_scope(rel):
            staged.append(candidate)
    return staged
