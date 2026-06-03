"""Tests to ensure no encoding corruption exists in operational files."""

import pytest
from scripts.encoding_guard import (
    ALLOWLIST,
    ROOT,
    collect_files_to_check,
    file_issues,
    is_in_scope,
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


CORE_SCOPE_REGRESSION = [
    ".agent/agent_controller.py",
    ".agent/completion_checker.py",
    "scripts/update_project_map.py",
    "scripts/orquestador.py",
    "runtime/ui_state_projector.py",
    "bus/event_bus.py",
    "scripts/check_encoding_guard.py",
]


@pytest.mark.parametrize("relative", CORE_SCOPE_REGRESSION)
def test_hook_scope_matches_test_scope_for_core_files(relative):
    file_path = ROOT / relative
    assert file_path in FILES_TO_CHECK, (
        f"Regression fixture missing from test scope: {relative}"
    )
    assert is_in_scope(relative), f"Hook scope should include: {relative}"
