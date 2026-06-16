#!/usr/bin/env python3
"""encoding_post_write_hook.py - Early encoding detection after Write|Edit|MultiEdit.

Invoked by .claude/settings.json PostToolUse hook for Write|Edit|MultiEdit.
Reads PostToolUse JSON payload from stdin, extracts file paths, and runs
encoding checks in-process via scripts.encoding_guard (file_issues + has_utf8_bom).
Falls back to subprocess check_encoding_guard.py if in-process import fails.

Exit code != 0 only if an ERROR-level encoding issue is found.
Contract: WOT-2026-010e.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _extract_paths(payload: dict) -> list[str]:
    paths: list[str] = []
    tool_input = payload.get("tool_input") or {}
    result = payload.get("result") or {}
    for source in (tool_input, result):
        for key in ("file_path", "filePath"):
            val = source.get(key)
            if isinstance(val, str) and val:
                paths.append(val)
    return paths


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / ".claude").is_dir():
            return candidate
    return start


def _resolve_destino(repo_root: Path) -> Path | None:
    env_root = os.environ.get("AGENT_PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()
    link_path = repo_root / ".agent" / "config" / "motor_destination_link.json"
    if link_path.is_file():
        try:
            data = json.loads(link_path.read_text(encoding="utf-8"))
            dest_root = data.get("destination_root")
            if dest_root:
                return Path(dest_root).resolve()
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _allowed_roots(repo_root: Path) -> list[Path]:
    roots = [repo_root]
    destino = _resolve_destino(repo_root)
    if destino and destino != repo_root:
        roots.append(destino)
    return roots


def _is_under_roots(path: Path, allowed: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in allowed)


def _text_extensions_from_guard() -> frozenset[str]:
    try:
        from scripts.encoding_guard import TEXT_EXTENSIONS

        return TEXT_EXTENSIONS
    except ImportError:
        return frozenset(
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


def _relative_to_any(path: Path) -> str:
    for root in _allowed_roots(ROOT):
        try:
            return path.relative_to(root).as_posix()
        except ValueError:  # noqa: PERF203
            pass
    return path.name


def _check_in_process(file_path: Path) -> tuple[int, list[str]]:
    try:
        from scripts.encoding_guard import TEXT_EXTENSIONS, file_issues, has_utf8_bom
    except ImportError:
        return -1, []
    if file_path.suffix.lower() not in TEXT_EXTENSIONS:
        return 0, []
    try:
        mojibake, q_in_word = file_issues(file_path)
        bom = has_utf8_bom(file_path)
    except UnicodeDecodeError as exc:
        return 0, [
            f"INFO encoding_guard_skipped_decode_error: {file_path.name}: {exc}\n"
            "ACTION: NO_ACTION_REQUIRED; final gates still apply."
        ]
    rel = _relative_to_any(file_path)
    diagnostics: list[str] = []
    if bom:
        diagnostics.append(
            f"ERROR bom: {rel}\n"
            f"ACTION: rewrite as UTF-8 without BOM. Fix: re-save {rel} without the "
            "byte-order mark (EF BB BF prefix)."
        )
    if mojibake:
        diagnostics.append(
            f"ERROR mojibake: {rel}: {mojibake[:8]}\n"
            "ACTION: replace corrupted sequence and prefer Write/Edit with UTF-8 "
            f"text over shell heredoc for non-ASCII in {rel}."
        )
    if q_in_word:
        diagnostics.append(
            f"ERROR question_mark_corruption: {rel}: {q_in_word[:8]}\n"
            "ACTION: recover intended character from source/context, do not "
            f"blindly replace ? in {rel}."
        )
    has_error = bom or bool(mojibake) or bool(q_in_word)
    return 1 if has_error else 0, diagnostics


def _check_subprocess(file_paths: list[Path]) -> tuple[int, list[str]]:
    check_script = ROOT / "scripts" / "check_encoding_guard.py"
    if not check_script.is_file():
        return 0, []
    args = [sys.executable, str(check_script)] + [str(p) for p in file_paths]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(  # noqa: S603
            args,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        diags: list[str] = []
        if proc.stdout.strip():
            diags.append(proc.stdout.strip())
        if proc.stderr.strip():
            diags.append(proc.stderr.strip())
        return proc.returncode, diags
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 0, [
            f"WARN encoding_guard_fallback_failed: {exc}\nACTION: no action required."
        ]


def _process_paths(
    paths: list[str], repo_root: Path, allowed: list[Path]
) -> tuple[int, list[str], list[Path]]:
    text_paths: list[Path] = []
    all_diag: list[str] = []
    for raw_path in paths:
        fp = Path(raw_path).resolve()
        if not _is_under_roots(fp, allowed):
            all_diag.append(
                "WARN encoding_guard_skipped_outside_allowed_roots: "
                f"{fp}\nACTION: VERIFY_ROOTS_IF_UNEXPECTED; otherwise no action required."
            )
            continue
        if fp.suffix.lower() not in _text_extensions_from_guard():
            all_diag.append(
                f"INFO encoding_guard_skipped_non_text: {fp.name} ({fp.suffix})\n"
                "ACTION: NO_ACTION_REQUIRED; final gates still apply."
            )
            continue
        text_paths.append(fp)
    return 0, all_diag, text_paths


def _run_checks(text_paths: list[Path]) -> tuple[int, list[str]]:
    all_diag: list[str] = []
    for tp in text_paths:
        code, diags = _check_in_process(tp)
        if code == -1:
            code, diags = _check_subprocess(text_paths)
            all_diag.extend(diags)
            return code, all_diag
        if code != 0:
            return code, diags
        all_diag.extend(diags)
    return 0, all_diag


def main() -> int:
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        print(
            "INFO encoding_guard_skipped_no_path: empty payload\n"
            "ACTION: NO_ACTION_REQUIRED; final gates still apply.",
            file=sys.stderr,
        )
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(
            "INFO encoding_guard_skipped_no_path: invalid JSON payload\n"
            "ACTION: NO_ACTION_REQUIRED; final gates still apply.",
            file=sys.stderr,
        )
        return 0
    paths = _extract_paths(payload)
    if not paths:
        print(
            "INFO encoding_guard_skipped_no_path: no file path in payload\n"
            "ACTION: NO_ACTION_REQUIRED; final gates still apply.",
            file=sys.stderr,
        )
        return 0
    repo_root = _find_repo_root(Path.cwd().resolve())
    allowed = _allowed_roots(repo_root)
    exit_code, all_diag, text_paths = _process_paths(paths, repo_root, allowed)
    if not text_paths and not all_diag:
        print(
            "INFO encoding_guard_skipped_no_path: no resolvable text paths\n"
            "ACTION: NO_ACTION_REQUIRED; final gates still apply.",
            file=sys.stderr,
        )
        return 0
    if text_paths:
        code, diags = _run_checks(text_paths)
        if code != 0:
            exit_code = code
        all_diag.extend(diags)
    for diag in all_diag:
        print(diag, file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
