from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _staged_relative_paths() -> list[str]:
    git_executable = shutil.which("git")
    if not git_executable:
        raise RuntimeError("git executable not found in PATH")

    result = subprocess.run(  # noqa: S603
        [git_executable, "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _explicit_paths(args: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in args:
        candidate = Path(raw).resolve()
        if candidate.exists() and candidate.is_file():
            files.append(candidate)
    return files


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _allowlist_relative(path: Path) -> str | None:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return None


def main() -> int:
    from scripts.encoding_guard import (
        file_issues,
        has_utf8_bom,
        is_allowlisted,
        iter_staged_files,
    )

    explicit_files = _explicit_paths(sys.argv[1:])
    files_to_check = explicit_files or iter_staged_files(_staged_relative_paths())

    if not files_to_check:
        return 0

    errors: list[str] = []
    for file_path in files_to_check:
        rel = _display_path(file_path)
        mojibake, q_in_word = file_issues(file_path)
        rel_for_allowlist = _allowlist_relative(file_path)
        if rel_for_allowlist is not None and is_allowlisted(rel_for_allowlist):
            if not mojibake and not q_in_word:
                errors.append(
                    f"Allowlist entry is now clean and should be removed: {rel}"
                )
            continue
        if has_utf8_bom(file_path):
            errors.append(f"UTF-8 BOM detected in {rel}")
        if mojibake:
            errors.append(f"Mojibake detected in {rel}: {mojibake[:12]}")
        if q_in_word:
            errors.append(
                f"Question-mark corruption detected in {rel}: {q_in_word[:12]}"
            )

    if errors:
        print("Encoding guard blocked this commit:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
