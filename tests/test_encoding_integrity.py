"""Tests to ensure no encoding corruption exists in operational files."""

import pytest
from scripts.encoding_guard import (
    ALLOWLIST,
    ROOT,
    collect_files_to_check,
    file_issues,
    relative_path,
)


FILES_TO_CHECK = collect_files_to_check()


@pytest.mark.parametrize(
    "file_path",
    FILES_TO_CHECK,
    ids=lambda path: path.relative_to(ROOT).as_posix(),
)
def test_no_encoding_corruption_in_file(file_path):
    if not file_path.exists():
        pytest.skip(f"File {file_path} does not exist")

    rel = relative_path(file_path)
    if rel in ALLOWLIST:
        pytest.skip(f"Known dirty file pending cleanup: {rel}")

    mojibake, q_in_word = file_issues(file_path)
    assert not mojibake, f"Mojibake detected in {rel}: {mojibake[:12]}"
    assert not q_in_word, (
        f"Question-mark corruption detected in {rel}: {q_in_word[:12]}"
    )


@pytest.mark.parametrize("relative", sorted(ALLOWLIST))
def test_known_dirty_files_still_need_cleanup(relative):
    file_path = ROOT / relative
    assert file_path.exists(), f"Allowlist entry missing: {relative}"

    mojibake, q_in_word = file_issues(file_path)
    assert mojibake or q_in_word, (
        f"Allowlist entry is now clean and should be removed: {relative}"
    )
