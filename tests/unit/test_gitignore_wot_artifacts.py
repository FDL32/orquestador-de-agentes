"""Regression test for the motor .gitignore WOT-artifact barrier (WOT-2026-020d).

WOT-2026-019e: the noisy FAIL that ``versioned_filenames`` used to report over
per-ticket collaboration artifacts (``AUDIT_WOT-*.md``, ``PLAN_WOT-*.md``,
``STRATEGY_WOT-*.md``, ``execution_log_WOT-*.md``, ``work_plan_WOT-*.md``
under ``.agent/collaboration/``) was already resolved in production by
WOT-2026-020d (commit ``65c11f8``): it added the pattern
``.agent/collaboration/*_WOT-*.md`` to the motor's ``.gitignore``, which
untracked those artifacts. ``git ls-files`` (what ``versioned_filenames``
scans) never lists gitignored paths, so the symptom no longer reproduces.

This test does not implement the ``exclude_prefix`` mechanism proposed in the
ticket's original work_plan -- that mechanism is out of scope: the underlying
symptom is already fixed via the ``.gitignore``, and adding a code-level
exclusion on top would be speculative defense without a reproducible bug.
Instead, this is a regression barrier that protects the ``.gitignore``
mitigation itself: if that pattern is ever removed or narrowed, this test
fails immediately, before anyone has to rediscover the noisy FAIL by running
a real session close against an external destination.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]

_IS_GIT_REPO = (PROJECT_ROOT / ".git").exists()

pytestmark = pytest.mark.skipif(
    not _IS_GIT_REPO,
    reason="motor repo root has no .git (not a git checkout)",
)


def _check_ignore(relative_path: str) -> int:
    """Return the exit code of ``git check-ignore`` for ``relative_path``.

    0 means the path is ignored by some ``.gitignore`` rule; 1 means it is
    not ignored (tracked or simply not matched); any other code signals a
    usage error and should not be silently treated as either.
    """
    result = subprocess.run(
        ["git", "check-ignore", relative_path],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode


class TestGitignoreWotArtifactsBarrier:
    """Protects the WOT-2026-020d .gitignore mitigation from regressing."""

    def test_wot_collaboration_artifact_is_gitignored(self):
        """AUDIT_WOT-*.md under .agent/collaboration/ stays gitignored.

        This is the exact artifact shape that used to trigger the noisy
        ``versioned_filenames`` FAIL before WOT-2026-020d (commit
        ``65c11f8``) added ``.agent/collaboration/*_WOT-*.md`` to the
        motor's ``.gitignore``.
        """
        exit_code = _check_ignore(".agent/collaboration/AUDIT_WOT-2026-999z.md")
        assert exit_code == 0, (
            "Expected .agent/collaboration/AUDIT_WOT-2026-999z.md to be "
            "gitignored (git check-ignore exit 0); got exit "
            f"{exit_code}. The WOT-2026-020d .gitignore mitigation "
            "appears to have regressed."
        )

    def test_live_collaboration_surface_is_not_gitignored(self):
        """A live surface without the _WOT- suffix stays tracked/visible.

        Confirms the .gitignore rule is precise (matches only per-ticket
        ``*_WOT-*.md`` artifacts) and does not over-capture legitimate,
        non-suffixed collaboration surfaces such as STATE.md.
        """
        exit_code = _check_ignore(".agent/collaboration/STATE.md")
        assert exit_code == 1, (
            "Expected .agent/collaboration/STATE.md (a live surface "
            "without the _WOT- suffix) to NOT be gitignored (git "
            f"check-ignore exit 1); got exit {exit_code}. The "
            ".gitignore pattern may be over-capturing live surfaces."
        )
