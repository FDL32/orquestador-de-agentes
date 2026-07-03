"""Classify git repository files before first publication.

Before:
    The caller has a git repository that may contain private or internal files.
During:
    The script reads git metadata, scans the working tree and optionally history,
    and classifies files into publication buckets.
After:
    It emits JSON evidence only. It never stages, removes, ignores, or publishes.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


TEXT_EXTENSIONS = {
    ".cfg",
    ".css",
    ".csv",
    ".distribute",
    ".env.example",
    ".example",
    ".gitignore",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".lock",
    ".md",
    ".ps1",
    ".py",
    ".rst",
    ".toml",
    ".ts",
    ".txt",
    ".workspace",
    ".yaml",
    ".yml",
}
EXCLUDE_PATTERNS = [
    ".git/**",
    ".venv/**",
    "venv/**",
    "__pycache__/**",
    ".pytest_cache/**",
    ".ruff_cache/**",
    "node_modules/**",
    "orchestrator_pipeline/**",
    ".agent/runtime/**",
    ".agent/collaboration/_archive/**",
    "privada/**",
    "private/**",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.sqlite",
    "*.db",
]
ALLOW_PUBLISH_PATTERNS = [
    ".env.example",
    "*.env.example",
]
SECURITY_FIXTURE_PATHS = frozenset(
    {
        "tests/test_redact.py",
        "tests/test_persistence_redaction.py",
        "tests/test_classify_publication.py",
        "tests/test_event_bus.py",
    }
)
# D5: Files in .agent/runtime/ that are tracked by design (WOT-2026-015c KEEP).
# They remain in EXCLUDE_TRACKED but are removed from tracked_exclusions_need_human_action.
RUNTIME_KEEP_TRACKED = frozenset(
    {
        ".agent/runtime/__init__.py",
        ".agent/runtime/memory/memory_helpers.py",
        ".agent/runtime/memory/memory_architecture.md",
    }
)
# D6a: History blobs whose only paths are accepted by design (WOT-2026-015e).
# The SKILL.md had a placeholder in an old commit; tree is already clean.
HISTORY_ACCEPTED_PATHS = frozenset({"skills/adopt-existing-project/SKILL.md"})
# D6b: Meta-documentation paths that document examples and real paths by design.
# These are the motor's own operational docs; redaction_risk is suppressed for them.
META_DOC_PATHS = frozenset(
    {
        "CHANGELOG.md",
        "docs/KNOWN_FAILURE_PATTERNS.md",
        "prompts/audit_git_publication.md",
        "prompts/audit_post_change_system_health.md",
        "scripts/classify_publication.py",
        "skills/adopt-existing-project/SKILL.md",
    }
)
CRITICAL_SECRET_PATTERNS = [
    re.compile(r"PUBLICATION_AUDIT_FAKE_SECRET\s*=", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
]
# A credential-named variable bound to a code expression
# (e.g. `token = normalized.rstrip(",").strip()`) must NOT be a false positive,
# while real credential literals must still block fail-closed. The original
# single pattern matched any `token = <16+ chars>` RHS, flagging ordinary code
# such as `token = some_function(x)` because the variable name plus a long
# expression satisfied it. The refinement keeps the broad match but adds a
# negative lookahead right after the `:`/`=` operator that excludes ONLY the code
# form -- an identifier immediately followed by `.attr` or `(call)`. So
# `token = normalized.rstrip(...)` and `token = foo.bar(baz)` are exempt, but an
# opaque credential value still blocks even when terminated by `;` `,` `)` or
# trailing prose (the lookahead only fires on identifier-then-dot/paren, not on an
# opaque blob like `AKIAIOSFODNN7EXAMPLEKEY1234`).
GENERIC_SECRET_PATTERNS = [
    # Broad credential-assignment match, but exclude RHS that is a code
    # expression (an identifier immediately followed by ``.attr`` or ``(call)``).
    # Fail-closed: an opaque value -- including one terminated by ``;`` ``,`` ``)``
    # or trailing prose -- still matches; only ``token = foo.bar(...)`` style code
    # is exempted. The negative lookahead sits right after the ``:``/``=`` operator
    # so it inspects the start of the RHS before the value class consumes it.
    re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*"
        r"(?![A-Za-z_]\w*\s*[.(])"  # NOT identifier-then-dot/paren (code expression)
        r"['\"]?[A-Za-z0-9_./+=-]{16,}"
    ),
]
SECRET_PATTERNS = CRITICAL_SECRET_PATTERNS + GENERIC_SECRET_PATTERNS
REDACTION_PATTERNS = [
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+"),
    re.compile(r"/home/[^/\s]+"),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(
        r"\b(?!env\.local\b)[a-z0-9][a-z0-9.-]*\.local\b(?!\.[a-z0-9])", re.IGNORECASE
    ),
]
MAX_TEXT_BYTES = 1_000_000
MAX_REDACTION_TARGETS_PER_FILE = 50

# WOT-2026-016o (H1): REDACTION_PATTERNS matches that are legitimate
# placeholders/redaction markers must not block the history gate. The list
# mirrors the placeholder policy proven in the 2026-07 backup batch.
HISTORY_PII_PLACEHOLDER_PATTERNS = [
    re.compile(r"(?i)^[a-z]:\\users\\<user>"),
    re.compile(r"(?i)^[a-z]:\\users\\\[tu_usuario\]"),
    re.compile(r"^/home/user$"),
    re.compile(r"^<redacted-email>$"),
    re.compile(r"@example\.com$", re.IGNORECASE),
    re.compile(r"@users\.noreply\.github\.com$", re.IGNORECASE),
    re.compile(r"(?i)^(tu[-_][\w.]*|usuario|user|alias|tu_cuenta)@"),
    re.compile(r"(?i)^env\.local$"),
]
MAX_HISTORY_PII_SAMPLES = 5


def _is_pii_placeholder(match_text: str) -> bool:
    """Before: match from REDACTION_PATTERNS. During: allowlist. After: bool."""
    return any(p.search(match_text) for p in HISTORY_PII_PLACEHOLDER_PATTERNS)


def _mask_pii_sample(match_text: str) -> str:
    """Return an evidence sample without reproducing the full PII value."""
    if len(match_text) <= 8:
        return match_text[:2] + "***"
    return match_text[:6] + "***" + match_text[-3:]


def _collect_blob_pii_samples(text: str) -> list[str]:
    """Before: blob text. During: REDACTION_PATTERNS minus placeholder allowlist.
    After: up to MAX_HISTORY_PII_SAMPLES masked evidence samples."""
    samples: list[str] = []
    for pattern in REDACTION_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group(0)
            if _is_pii_placeholder(candidate):
                continue
            samples.append(_mask_pii_sample(candidate))
            if len(samples) >= MAX_HISTORY_PII_SAMPLES:
                return samples
    return samples


@dataclass(frozen=True)
class RepoFiles:
    """Before: git repo queried. During: collect paths. After: split by tracking."""

    tracked: set[str]
    untracked: set[str]


def _now_iso() -> str:
    """Before: none. During: read UTC clock. After: return ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _git_executable() -> str:
    """Before: git should exist. During: resolve executable. After: return path."""
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git executable not found in PATH")
    return git


def _run_git(
    repo_root: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Before: repo_root is a git repo. During: run git. After: return result."""
    return subprocess.run(  # noqa: S603
        [_git_executable(), *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _lines(text: str) -> list[str]:
    """Before: text may be empty. During: split. After: non-empty stripped lines."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _git_lines(repo_root: Path, *args: str) -> list[str]:
    """Before: args are read-only. During: run git. After: return stdout lines."""
    return _lines(_run_git(repo_root, *args).stdout)


def _git_status(repo_root: Path) -> list[str]:
    """Before: repo_root is git repo. During: read status. After: short lines."""
    return _git_lines(repo_root, "status", "--short")


def _git_head(repo_root: Path) -> str:
    """Before: repo_root is git repo. During: read HEAD. After: full SHA."""
    return _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()


def _is_git_repo(repo_root: Path) -> bool:
    """Before: repo_root exists. During: ask git. After: return repo status."""
    result = _run_git(repo_root, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _normalize_path(path: str) -> str:
    """Before: path from git or filesystem. During: normalize. After: posix path."""
    return path.replace("\\", "/").strip("/")


def _matches_any(path: str, patterns: list[str]) -> bool:
    """Before: path is posix. During: fnmatch. After: true when excluded."""
    return any(fnmatch(path, pattern) for pattern in patterns)


def _is_tests_path(path: str) -> bool:
    """Before: path is a repo-relative posix path. During: prefix check. After: True
    if the path is under tests/ (redaction fixtures are expected there by design).
    NOTE: this suppresses only redaction_risk; secret_risk is never suppressed.
    """
    return path.startswith("tests/")


def _is_security_fixture_path(path: str) -> bool:
    """Before: path is a posix repo-relative path. During: exact case-sensitive
    membership against the named fixtures. After: True only for the exact
    redaction/publication test files that deliberately embed fake secret markers
    to exercise the scanner. These are intentional fixtures, not leaked
    credentials.

    Uses exact set membership (NOT fnmatch): fnmatch applies os.path.normcase on
    Windows/macOS, which case-folds and would exempt path variants like
    ``Tests/Test_Redact.py``. A security allowlist must be platform-invariant, so
    only the exact posix names are exempt -- case variants are scanned normally.
    """
    return path in SECURITY_FIXTURE_PATHS


def _is_excluded(path: str) -> bool:
    """Before: path is posix. During: apply allowlist then denylist. After: bool."""
    return _matches_any(path, EXCLUDE_PATTERNS) and not _matches_any(
        path, ALLOW_PUBLISH_PATTERNS
    )


def _is_publish_allowlisted(path: str) -> bool:
    """Before: path is posix. During: allowlist match. After: safe template path."""
    return _matches_any(path, ALLOW_PUBLISH_PATTERNS)


TextCache = dict[str, str | None]


def _read_text(path: Path) -> str | None:
    """Before: path exists. During: read bounded text. After: text or None."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096] or len(data) > MAX_TEXT_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _read_text_cached(repo_root: Path, rel_path: str, cache: TextCache) -> str | None:
    """Before: rel_path is repo-relative. During: cache read. After: text/None."""
    if rel_path not in cache:
        cache[rel_path] = _read_text(repo_root / rel_path)
    return cache[rel_path]


def _secret_patterns_for_path(path: str) -> list[re.Pattern[str]]:
    """Before: path is posix. During: choose strictness. After: regex list."""
    if _is_security_fixture_path(path):
        return []  # fixtures deliberately contain fake secret markers
    return (
        CRITICAL_SECRET_PATTERNS if _is_publish_allowlisted(path) else SECRET_PATTERNS
    )


def _has_secret(text: str | None, path: str) -> bool:
    """Before: text may be None. During: scan selected patterns. After: bool."""
    return text is not None and any(
        pattern.search(text) for pattern in _secret_patterns_for_path(path)
    )


def _content_flags(text: str | None, rel_path: str) -> list[str]:
    """Before: text may be None. During: scan. After: risk flags.

    D1: redaction_risk is suppressed for paths under tests/ (fixtures by design).
        secret_risk is NEVER suppressed -- AKIA/sk- in tests/ still blocks.
    D6b: redaction_risk is suppressed for META_DOC_PATHS (motor's own op docs).
    """
    if text is None:
        return ["binary_or_large"]
    flags: list[str] = []
    if _has_secret(text, rel_path):
        flags.append("secret_risk")
    if (
        not _is_tests_path(rel_path)
        and rel_path not in META_DOC_PATHS
        and any(pattern.search(text) for pattern in REDACTION_PATTERNS)
    ):
        flags.append("redaction_risk")
    return flags


def _redaction_targets(text: str | None) -> dict[str, Any]:
    """Before: text may be None. During: locate PII-ish matches. After: targets."""
    if text is None:
        return {"targets": [], "truncated": False, "note": "non_text_file"}
    targets: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern in REDACTION_PATTERNS:
            for match in pattern.finditer(line):
                if len(targets) >= MAX_REDACTION_TARGETS_PER_FILE:
                    return {
                        "targets": targets,
                        "truncated": True,
                        "note": "TRUNCATED: Too many redactions required. Manual review mandatory.",
                    }
                targets.append(
                    {
                        "line": line_no,
                        "match": match.group(0),
                        "pattern": pattern.pattern,
                    }
                )
    return {"targets": targets, "truncated": False, "note": ""}


def _collect_repo_files(
    repo_root: Path, runtime_excludes: set[str] | None = None
) -> RepoFiles:
    """Before: repo_root is git repo. During: query git. After: tracked/untracked."""
    excludes = runtime_excludes or set()
    tracked = {
        _normalize_path(line)
        for line in _git_lines(repo_root, "ls-files")
        if _normalize_path(line) not in excludes
    }
    untracked = {
        _normalize_path(line)
        for line in _git_lines(repo_root, "ls-files", "--others", "--exclude-standard")
        if _normalize_path(line) not in excludes
    }
    return RepoFiles(tracked=tracked, untracked=untracked)


def _classify_file(
    repo_root: Path, rel_path: str, tracked: bool, text_cache: TextCache
) -> dict[str, Any]:
    """Classify one file without mutating the repository.

    Before:
        rel_path is a repo-relative POSIX path.
    During:
        Applies path, extension, size, secret, and redaction heuristics.
    After:
        Returns classification with evidence and recommendation.
    """
    excluded = _is_excluded(rel_path)
    text = None if excluded else _read_text_cached(repo_root, rel_path, text_cache)
    flags = _content_flags(text, rel_path)
    suffix = Path(rel_path).suffix.lower()
    reasons: list[str] = []

    if excluded:
        bucket = "EXCLUDE_TRACKED" if tracked else "EXCLUDE_UNTRACKED"
        reasons.append("path_matches_exclude_policy")
    elif "secret_risk" in flags:
        bucket = "DECIDE"
        reasons.append("secret_like_content")
    elif "redaction_risk" in flags:
        bucket = "PUBLISH_WITH_REDACTIONS"
        reasons.append("local_path_or_pii_like_content")
    elif text is None and suffix in TEXT_EXTENSIONS:
        bucket = "DECIDE"
        reasons.append("binary_in_text_file")
    elif "binary_or_large" in flags or (suffix and suffix not in TEXT_EXTENSIONS):
        bucket = "DECIDE"
        reasons.append("binary_large_or_unknown_type")
    else:
        bucket = "PUBLISH"
        reasons.append("text_file_no_obvious_risk")

    return {
        "path": rel_path,
        "bucket": bucket,
        "tracked": tracked,
        "flags": flags,
        "reasons": reasons,
        "redaction_targets": _redaction_targets(text)
        if bucket == "PUBLISH_WITH_REDACTIONS"
        else None,
    }


def _scan_tree_secrets(
    repo_root: Path, files: RepoFiles, text_cache: TextCache
) -> list[dict[str, Any]]:
    """Before: files discovered. During: scan current contents. After: findings."""
    findings: list[dict[str, Any]] = []
    for rel_path in sorted(files.tracked | files.untracked):
        if _is_excluded(rel_path):
            continue
        text = _read_text_cached(repo_root, rel_path, text_cache)
        if _has_secret(text, rel_path):
            findings.append(
                {"path": rel_path, "scope": "tree", "evidence": "secret_pattern"}
            )
    return findings


def _git_show_text(repo_root: Path, object_ref: str) -> str | None:
    """Before: object_ref may exist. During: git show. After: text or None."""
    result = _run_git(repo_root, "show", object_ref, check=False)
    if result.returncode != 0 or "\x00" in result.stdout[:4096]:
        return None
    return result.stdout[:MAX_TEXT_BYTES]


def _collect_history_blob_paths(repo_root: Path) -> dict[str, list[str]]:
    """Before: repo_root is a git repo. During: rev-list + ls-tree per commit.
    After: map of blob sha -> repo-relative paths (excluded paths filtered)."""
    blob_paths: dict[str, list[str]] = {}
    for commit in _git_lines(repo_root, "rev-list", "--all"):
        for line in _git_lines(repo_root, "ls-tree", "-r", commit):
            meta, _, raw_path = line.partition("\t")
            meta_parts = meta.split()
            if len(meta_parts) < 3 or not raw_path:
                continue
            if meta_parts[1] != "blob":
                continue
            rel_path = _normalize_path(raw_path)
            if _is_excluded(rel_path):
                continue
            blob_paths.setdefault(meta_parts[2], []).append(rel_path)
    return blob_paths


def _scan_history_secrets(
    repo_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Scan git history for secret-like content.

    Before:
        repo_root is a git repo.
    During:
        Iterates commits and tracked file snapshots with bounded text reads.
        WOT-2026-016o (H1): the same blob pass also applies REDACTION_PATTERNS
        (emails, local user paths) with a placeholder allowlist, so PII in old
        blobs no longer passes the gate silently.
    After:
        Returns (secret_findings, pii_findings); no repository mutation.
    """
    findings: list[dict[str, Any]] = []
    pii_findings: list[dict[str, Any]] = []
    for blob_sha, paths in _collect_history_blob_paths(repo_root).items():
        if all(_is_security_fixture_path(path) for path in paths):
            continue  # fixtures deliberately contain fake secret markers
        if all(path in HISTORY_ACCEPTED_PATHS for path in paths):
            continue  # D6a: history blob accepted by design (WOT-2026-015e)
        text = _git_show_text(repo_root, blob_sha)
        patterns = (
            CRITICAL_SECRET_PATTERNS
            if all(_is_publish_allowlisted(path) for path in paths)
            else SECRET_PATTERNS
        )
        if text is None:
            continue
        if any(pattern.search(text) for pattern in patterns):
            unique_paths = sorted(set(paths))
            findings.append(
                {
                    "path": unique_paths[0],
                    "paths": unique_paths,
                    "scope": "history",
                    "blob": blob_sha[:12],
                    "evidence": "secret_pattern",
                }
            )
        # WOT-2026-016o: PII scan on the same blob (allowlisted placeholders
        # excluded; samples masked to avoid reproducing the PII itself).
        # D1: blobs whose every path lives under tests/ are fixtures by design
        # (mirrors the tree-side redaction_risk suppression).
        if all(_is_tests_path(path) for path in paths):
            continue
        pii_samples = _collect_blob_pii_samples(text)
        if pii_samples:
            unique_paths = sorted(set(paths))
            pii_findings.append(
                {
                    "path": unique_paths[0],
                    "paths": unique_paths,
                    "scope": "history",
                    "blob": blob_sha[:12],
                    "evidence": "redaction_pattern",
                    "samples": pii_samples,
                }
            )
    return findings, pii_findings


def _build_blocked_reasons(
    secret_findings: list[dict[str, Any]],
    tree_findings: list[dict[str, Any]],
    history_findings: list[dict[str, Any]],
    history_pii_findings: list[dict[str, Any]],
    buckets: dict[str, list[dict[str, Any]]],
    scan_history: bool,
    dirty_during_scan: bool,
    head_changed_during_scan: bool,
    is_motor_root: bool,
    allow_motor_root: bool,
    status_before: list[str],
    status_after: list[str],
    head_before: str,
    head_after: str,
) -> list[dict[str, Any]]:
    """Before: scan data exists. During: classify blockers. After: reasons."""
    blocked_reasons: list[dict[str, Any]] = []
    if secret_findings:
        blocked_reasons.append(
            {
                "code": "BLOQUEADO_POR_SECRETO",
                "tree_secret_scan": bool(tree_findings),
                "history_secret_scan": bool(history_findings),
                "findings": secret_findings,
            }
        )
    # WOT-2026-016o (H1): PII in old blobs needs a human decision (history
    # rewrite or explicit acceptance); it is neither a tree redaction nor a
    # secret, so it gets its own reason and forces human intervention.
    if history_pii_findings:
        blocked_reasons.append(
            {
                "code": "HISTORY_PII_PENDING",
                "count": len(history_pii_findings),
                "paths": sorted({f["path"] for f in history_pii_findings})[:10],
            }
        )
    if buckets["DECIDE"]:
        blocked_reasons.append(
            {"code": "DECIDE_PENDING", "count": len(buckets["DECIDE"])}
        )
    # D5: RUNTIME_KEEP_TRACKED files are accepted-by-design and do not block.
    tracked_pending = [
        item["path"]
        for item in buckets["EXCLUDE_TRACKED"]
        if item["path"] not in RUNTIME_KEEP_TRACKED
    ]
    if tracked_pending:
        blocked_reasons.append(
            {
                "code": "EXCLUDE_TRACKED_PENDING",
                "count": len(tracked_pending),
            }
        )
    if not scan_history:
        blocked_reasons.append(
            {
                "code": "HISTORY_SCAN_SKIPPED",
                "impact": "quick mode cannot prove git history is publishable",
            }
        )
    if is_motor_root and not allow_motor_root:
        blocked_reasons.append(
            {
                "code": "MOTOR_ROOT_PUBLICATION_GUARD",
                "impact": "repo_motor requires explicit --allow-motor-root",
            }
        )
    if head_changed_during_scan:
        blocked_reasons.append(
            {
                "code": "HEAD_CHANGED_DURING_SCAN",
                "head_before": head_before,
                "head_after": head_after,
            }
        )
    if dirty_during_scan:
        blocked_reasons.append(
            {
                "code": "DIRTY_DURING_SCAN",
                "status_before": status_before,
                "status_after": status_after,
            }
        )
    return blocked_reasons


def _decide_verdict(
    secret_findings: list[dict[str, Any]],
    history_pii_findings: list[dict[str, Any]],
    buckets: dict[str, list[dict[str, Any]]],
    scan_history: bool,
    dirty_during_scan: bool,
    head_changed_during_scan: bool,
    is_motor_root: bool,
    allow_motor_root: bool,
) -> str:
    """Before: scan data exists. During: apply precedence. After: verdict."""
    if secret_findings:
        return "BLOQUEADO_POR_SECRETO"
    if (
        dirty_during_scan
        or head_changed_during_scan
        or not scan_history
        or (is_motor_root and not allow_motor_root)
    ):
        return "NO_ACEPTAR_TODAVIA"
    # D5: RUNTIME_KEEP_TRACKED files are accepted-by-design; exclude from verdict check.
    tracked_pending_for_verdict = [
        item
        for item in buckets["EXCLUDE_TRACKED"]
        if item["path"] not in RUNTIME_KEEP_TRACKED
    ]
    # WOT-2026-016o: PII en historia exige decision humana (rewrite/aceptar).
    if buckets["DECIDE"] or tracked_pending_for_verdict or history_pii_findings:
        return "DECIDE_PENDING"
    if buckets["PUBLISH_WITH_REDACTIONS"]:
        return "LISTO_CON_REDACTIONS"
    return "LISTO_PARA_PUBLICAR"


def _runtime_excludes(repo_root: Path, out_path: Path | None) -> set[str]:
    """Before: optional output path. During: relativize. After: exclude set."""
    if out_path is None:
        return set()
    try:
        return {_normalize_path(out_path.resolve().relative_to(repo_root).as_posix())}
    except ValueError:
        return set()


def build_manifest(
    repo_root: Path,
    scan_history: bool = True,
    out_path: Path | None = None,
    allow_motor_root: bool = False,
) -> dict[str, Any]:
    """Build publication manifest.

    Before:
        repo_root points to a git repository.
    During:
        Classifies tracked/untracked files and scans tree/history for secrets.
    After:
        Returns JSON-safe manifest; never mutates repo.
    """
    root = repo_root.resolve()
    if not _is_git_repo(root):
        raise ValueError(f"{root} is not a git repository")

    status_before = _git_status(root)
    head_before = _git_head(root)
    is_motor_root = (root / "MANIFEST.distribute").exists()
    files = _collect_repo_files(root, _runtime_excludes(root, out_path))
    text_cache: TextCache = {}
    classified = [
        _classify_file(root, rel_path, rel_path in files.tracked, text_cache)
        for rel_path in sorted(files.tracked | files.untracked)
    ]
    tree_findings = _scan_tree_secrets(root, files, text_cache)
    history_findings, history_pii_findings = (
        _scan_history_secrets(root) if scan_history else ([], [])
    )
    status_after = _git_status(root)
    head_after = _git_head(root)
    dirty_during_scan = status_before != status_after
    head_changed_during_scan = head_before != head_after
    secret_findings = tree_findings + history_findings
    buckets: dict[str, list[dict[str, Any]]] = {
        "PUBLISH": [],
        "PUBLISH_WITH_REDACTIONS": [],
        "EXCLUDE_UNTRACKED": [],
        "EXCLUDE_TRACKED": [],
        "DECIDE": [],
    }
    for item in classified:
        buckets[item["bucket"]].append(item)

    blocked_reasons = _build_blocked_reasons(
        secret_findings,
        tree_findings,
        history_findings,
        history_pii_findings,
        buckets,
        scan_history,
        dirty_during_scan,
        head_changed_during_scan,
        is_motor_root,
        allow_motor_root,
        status_before,
        status_after,
        head_before,
        head_after,
    )
    verdict = _decide_verdict(
        secret_findings,
        history_pii_findings,
        buckets,
        scan_history,
        dirty_during_scan,
        head_changed_during_scan,
        is_motor_root,
        allow_motor_root,
    )
    return {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "repo_root": str(root),
        "mode": "dry-run" if scan_history else "quick",
        "verdict": verdict,
        "blocked_reasons": blocked_reasons,
        "git_status_before": status_before,
        "git_status_after": status_after,
        "dirty_during_scan": dirty_during_scan,
        "head_before": head_before,
        "head_after": head_after,
        "head_changed_during_scan": head_changed_during_scan,
        "is_motor_root": is_motor_root,
        "allow_motor_root": allow_motor_root,
        "summary": {bucket: len(items) for bucket, items in buckets.items()},
        "tree_secret_scan": {"ok": not tree_findings, "findings": tree_findings},
        "history_secret_scan": {
            "enabled": scan_history,
            "ok": not history_findings,
            "findings": history_findings,
        },
        "history_pii_scan": {
            "enabled": scan_history,
            "ok": not history_pii_findings,
            "findings": history_pii_findings,
        },
        "redactions_required": bool(buckets["PUBLISH_WITH_REDACTIONS"]),
        "publication_manifest": buckets,
        "gitignore_proposed": sorted(
            item["path"] for item in buckets["EXCLUDE_UNTRACKED"]
        ),
        "tracked_exclusions_need_human_action": sorted(
            item["path"]
            for item in buckets["EXCLUDE_TRACKED"]
            if item["path"] not in RUNTIME_KEEP_TRACKED
        ),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Before: payload is JSON-safe. During: create parent. After: write JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    """Before: none. During: define CLI. After: parser."""
    parser = argparse.ArgumentParser(
        description="Classify git repository contents before publication (dry-run only)."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, help="Optional JSON output path.")
    parser.add_argument(
        "--allow-motor-root",
        action="store_true",
        help="Allow auditing repo_motor itself; default blocks motor publication.",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Deprecated alias for --quick.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip git history secret scan; never returns LISTO_PARA_PUBLICAR.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Before: argv optional. During: classify. After: write JSON and exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.no_history:
            print(
                "WARNING: --no-history is deprecated; use --quick",
                file=sys.stderr,
            )
        manifest = build_manifest(
            args.repo_root,
            scan_history=not (args.no_history or args.quick),
            out_path=args.out,
            allow_motor_root=args.allow_motor_root,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.out:
        _write_json(args.out, manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if manifest["verdict"] == "LISTO_PARA_PUBLICAR":
        return 0
    if manifest["verdict"] == "BLOQUEADO_POR_SECRETO":
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
