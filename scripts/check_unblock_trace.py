#!/usr/bin/env python3
# ruff: noqa: S603, S607
"""Check git commit messages for closeout-unblock evidence.

Before: ``motor_root`` is a Git repository and the audited range is resolvable.
The verifier has no dependency on the ignored session ledger.
During: derive declarative and corrected non-declarative candidates from
``git log`` and compare their commit-message markers with the closed baseline.
After: print every finding and return 0 only when no required trace or
classification is missing.

LIMITE DECLARADO: this protects the session-close evidence path for commits
that touch the declared guard surfaces and gate machinery. It does not detect
an unblock that touches neither surface, and it does not prevent local commits.
The source of guard surfaces is the versioned ``GUARD_SURFACE_PREFIXES``
constant below; the gate-machinery list is ``GATE_SURFACES``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent
# Measured from the repo_destino, not from the motor. Keep this explicit so a
# future maintainer cannot silently replace it with motor HEAD^.
CUTOFF_SHA = "ac56dcc77d80dbe350a73b7deaf9286e7f74d5c1"
GUARD_SURFACE_PREFIXES = (
    "scripts/check_",
    "scripts/validate_",
    "scripts/guard_",
    "scripts/prepush_check.py",
    ".agent/hooks/",
)
GATE_SURFACES = frozenset(
    {
        "scripts/prepush_check.py",
        "scripts/guard_denominator_policy.yaml",
        "scripts/check_guard_wiring.py",
        ".pre-commit-config.yaml",
    }
)
GRANDFATHERED_SHAS = (
    # Closed four-SHA baseline re-measured against origin/main.  The first
    # entry is the pre-existing L6 gate commit in this flight range; the
    # remaining entries preserve the historical hotfix/unblock control set.
    # Grandfathering is applied to both channels because these commits predate
    # this verifier and cannot be retrofitted with a message marker.
    "8c939150fdfdb86917986281ff1bc64829d7a9bf",
    "5939847e999004805b19a371a534a6bcc9d3b46b",
    "dab5b66274bbd4ef76a9f7a49e4b240f48f71ad5",
    "c344854e975c5932d5c75813796ce96f4c359c4e",
)
GRANDFATHERED_COUNT = 4
DECLARATIVE_SUBJECT = re.compile(r"\b(?:hotfix|desbloqueo|unblock)\b", re.I)
TRACE_MARKER = re.compile(
    r"^\s*(?:PREEXISTING_GATE_UNBLOCK|NOT_PREEXISTING_UNBLOCK)\s*:", re.I | re.M
)


def _git(root: Path, *args: str) -> tuple[int, str]:
    """Run one read-only Git command and preserve its real return code."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        return 127, str(exc)
    return result.returncode, (result.stdout or result.stderr).strip()


def _commits(root: Path, revision_range: str) -> tuple[int, list[str], str]:
    """Return commit ids in the requested range, or a fail-closed error."""
    rc, output = _git(root, "rev-list", revision_range)
    if rc != 0:
        return rc, [], f"git rev-list {revision_range!r}: {output}"
    return 0, [line for line in output.splitlines() if line], ""


def _commit_data(root: Path, sha: str) -> tuple[int, str, list[str], str]:
    """Read one commit message and its changed paths from Git."""
    rc, message = _git(root, "show", "-s", "--format=%B", sha)
    if rc != 0:
        return rc, "", [], f"git show message {sha}: {message}"
    rc, paths = _git(
        root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha
    )
    if rc != 0:
        return rc, "", [], f"git diff-tree {sha}: {paths}"
    return 0, message, paths.splitlines(), ""


def _is_guard_surface(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in GUARD_SURFACE_PREFIXES)


def _is_grandfathered(sha: str) -> bool:
    return any(sha.startswith(prefix) for prefix in GRANDFATHERED_SHAS)


def _findings_for_commit(
    sha: str, message: str, paths: list[str]
) -> tuple[bool, bool, bool, list[str]]:
    """Classify one commit and return counters plus any blocking findings."""
    subject = message.splitlines()[0] if message.splitlines() else ""
    has_trace = bool(TRACE_MARKER.search(message))
    is_grandfathered = _is_grandfathered(sha)
    is_declarative = bool(DECLARATIVE_SUBJECT.search(subject))
    findings: list[str] = []
    if is_declarative and not has_trace and not is_grandfathered:
        findings.append(f"{sha}: declarative unblock without trace")

    is_candidate = any(_is_guard_surface(path) for path in paths) and any(
        path in GATE_SURFACES for path in paths
    )
    classified = is_candidate and has_trace
    if is_candidate and not has_trace and not is_grandfathered:
        findings.append(f"{sha}: unclassified corrected non-declarative candidate")
    return is_declarative, is_candidate, classified, findings


def run_check(root: Path, revision_range: str) -> int:
    """Audit Git-derived traces and return a process-style verdict."""
    if len(GRANDFATHERED_SHAS) != GRANDFATHERED_COUNT:
        print(
            "FAIL: grandfather allowlist changed; update the closed baseline "
            "with a new measurement before running this guard."
        )
        return 1

    rc, shas, error = _commits(root, revision_range)
    if rc:
        print(f"FAIL: {error}")
        return 1

    findings: list[str] = []
    declarative = 0
    corrected_candidates = 0
    classified = 0
    for sha in shas:
        rc, message, paths, error = _commit_data(root, sha)
        if rc:
            print(f"FAIL: {error}")
            return 1
        is_declarative, is_candidate, classified_commit, commit_findings = (
            _findings_for_commit(sha, message, paths)
        )
        declarative += is_declarative
        if is_candidate:
            corrected_candidates += 1
            if classified_commit:
                classified += 1
        findings.extend(commit_findings)

    print(
        f"[unblock-trace] commits={len(shas)} declarative={declarative} "
        f"corrected_candidates={corrected_candidates} classified={classified} "
        f"cutoff_destination={CUTOFF_SHA}"
    )
    for finding in findings:
        print(f"FAIL: {finding}")
    return 1 if findings else 0


def main(argv: list[str] | None = None) -> int:
    """Parse the standalone guard CLI and return its real verdict."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--motor-root", default=str(MOTOR_ROOT))
    parser.add_argument(
        "--range",
        dest="revision_range",
        default="origin/main..HEAD",
        help="Git revision range to audit; the trigger is always derived from git log.",
    )
    args = parser.parse_args(argv)
    return run_check(Path(args.motor_root).resolve(), args.revision_range)


if __name__ == "__main__":
    raise SystemExit(main())
