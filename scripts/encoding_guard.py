from __future__ import annotations

import re
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
    # WOT-2026-011f: bring real PowerShell sources under the repo-wide guard so
    # BOM/mojibake in .ps1 is caught (the launcher carried both pre-011f).
    "scripts/**/*.ps1",
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


# WOT-2026-013q: the broken-backtick fragment is the same heredoc/PowerShell
# escape-literalization that produced `r (from \r) in CTL-2026-007a; the very
# same mechanism emits `n (from \n) and `t (from \t) at the end of a path
# bullet. Match the [rnt] family, EOL-anchored and path-shaped, so legitimate
# inline-code bullets (e.g. ``- use `ruff` ``) never false-positive.
_BROKEN_PATH_BULLET_RE = re.compile(r"^[./A-Za-z0-9_-]+(?:/[./A-Za-z0-9_-]+)*/`[rnt]$")


def find_path_bullet_mangling(text: str) -> list[str]:
    """Return narrow signatures of markdown path-bullet corruption.

    This catches the signatures from the CTL-2026-007a incident:

    - a literal tab immediately after the bullet marker (`- <TAB>path`)
    - a broken backtick fragment at the end of a path bullet from heredoc
      escape literalization: ``- src/pipeline/`r`` and its same-mechanism
      siblings ``/`n`` and ``/`t``.

    The detector is intentionally narrow so legitimate tabs elsewhere in the
    file (for example, markdown tables) and inline-code bullets remain allowed.
    """
    snippets: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        if not stripped.startswith("- "):
            continue

        body = stripped[2:]
        if body.startswith("\t"):
            snippet = "<bullet-tab>" + body[:12].replace("\t", "<TAB>")
            if snippet not in snippets:
                snippets.append(snippet)

        if _BROKEN_PATH_BULLET_RE.fullmatch(body):
            snippet = body[-16:]
            if snippet not in snippets:
                snippets.append(snippet)
    return snippets


def find_c1_controls(text: str) -> list[str]:
    """Return snippets around C1 control codepoints (U+0080-U+009F) in decoded text.

    WOT-2026-014d: C1 control characters are a distinct class from ASCII controls
    (<32) and mojibake.  They are valid UTF-8 multibyte sequences so
    ``content.decode('utf-8', errors='strict')`` does NOT flag them, yet they
    indicate encoding corruption (typically CP1252-mismapped markers that were
    stored as raw C1 bytes and re-read as UTF-8).  A separate check is required.

    Each snippet shows the codepoint as ``<U+NNNN>`` with up to 3 chars of
    following context, deduplicated for human readability.
    """
    snippets: list[str] = []
    for idx, ch in enumerate(text):
        if not (0x0080 <= ord(ch) <= 0x009F):
            continue
        marker = f"<U+{ord(ch):04X}>"
        tail = text[idx + 1 : idx + 4].replace("\n", "\\n").replace("\r", "\\r")
        snippet = marker + tail
        if snippet not in snippets:
            snippets.append(snippet)
    return snippets


def check_utf8_strict(path: Path) -> list[str]:
    """Return a single-element list if the file has invalid UTF-8 byte sequences.

    WOT-2026-014d: complementary layer for the C1 check.  ``find_c1_controls``
    catches valid-UTF-8-but-wrong-class codepoints; this function catches a
    different class: raw byte sequences that are NOT valid UTF-8 at all (e.g.
    lone continuation bytes, overlong sequences).

    Returns an empty list on clean files so the caller can use a uniform
    ``if snippets`` test.
    """
    raw = path.read_bytes()
    try:
        raw.decode("utf-8", errors="strict")
        return []
    except UnicodeDecodeError as exc:
        return [f"<invalid-utf8:{exc.start:#04x}:{exc.reason}>"]


def find_text_corruption(text: str) -> list[str]:
    """Return non-mojibake structural corruption snippets for a text file."""
    findings: list[str] = []
    for snippet in [
        *find_control_chars(text),
        *find_path_bullet_mangling(text),
        *find_c1_controls(text),
    ]:
        if snippet not in findings:
            findings.append(snippet)
    return findings


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
    """Return (mojibake, question_mark, text_corruption) issue snippets for path.

    The third element intentionally keeps the existing 3-tuple contract used by
    the CLI guard and the post-write hook.  It now covers:
    - disallowed ASCII control chars (<32, not tab/LF/CR)
    - narrow path-bullet mangling signatures (CTL-2026-007a)
    - C1 control codepoints (U+0080-U+009F) in decoded text (WOT-2026-014d)
    - invalid UTF-8 byte sequences via strict-decode (WOT-2026-014d)

    Note: ``check_utf8_strict`` operates on raw bytes before ``load_text``
    (which uses errors='replace' semantics via UTF-8 read).  For files that are
    already valid UTF-8 the strict check is a no-op.  For files with invalid
    bytes it returns a diagnostic snippet appended to the third element so the
    existing caller contract (3-tuple, third element is a list[str]) is preserved.
    """
    strict_issues = check_utf8_strict(path)
    if strict_issues:
        # File has invalid UTF-8 bytes: load_text would raise UnicodeDecodeError.
        # Return early with only the strict-decode diagnostic so callers receive
        # a well-formed 3-tuple without an exception propagating.
        return [], [], list(strict_issues)
    text = load_text(path)
    text_corruption = find_text_corruption(text)
    return find_mojibake(text), find_q_in_word(text), text_corruption


def iter_staged_files(paths: list[str]) -> list[Path]:
    staged: list[Path] = []
    for rel in paths:
        candidate = ROOT / rel
        if candidate.exists() and candidate.is_file() and is_in_scope(rel):
            staged.append(candidate)
    return staged
