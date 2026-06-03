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


def main() -> int:
    from scripts.encoding_guard import (
        file_issues,
        is_allowlisted,
        iter_staged_files,
        relative_path,
    )

    staged_files = iter_staged_files(_staged_relative_paths())
    if not staged_files:
        return 0

    errors: list[str] = []
    for file_path in staged_files:
        rel = relative_path(file_path)
        mojibake, q_in_word = file_issues(file_path)
        if is_allowlisted(rel):
            if not mojibake and not q_in_word:
                errors.append(
                    f"Allowlist entry is now clean and should be removed: {rel}"
                )
            continue
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
