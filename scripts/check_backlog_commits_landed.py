#!/usr/bin/env python3
"""Guard: every commit the backlog gives as CLOSED actually landed in origin/main.

WOT-2026-021o. Motivated by CTL-2026-012i (2026-07-10): commit 6cee757 was marked
published in the backlog but lived only in a detached HEAD, never pushed -- it was
almost lost when the primary checkout was synced. This guard audits, for every
``commit:<sha>`` the backlog records in the ``completed`` rows of
``_archive/backlog_done.md``, whether that work reached ``origin/main`` -- by THREE
detection layers, exact to lax:

    CAPA 1  <sha> is an ancestor of origin/main            -> OK (direct).
    CAPA 2  git patch-id --stable of <sha> is among the    -> OK (catches REBASE:
            patch-ids reachable from origin/main               a rebase changes the
                                                               SHA, keeps the patch).
    CAPA 3  the ticket-ID appears in the subject of a      -> OK_BY_SUBJECT (the
            commit reachable from origin/main (anchored,       weakest -- landing by
            EXACT ID match, Revert excluded)                   CONVENTION, catches
                                                               SQUASH / cherry-pick).

Verdict if NO layer hits:
    - <sha> has NO git object at all               -> WARN (obsolete cite / typo, or
                                                       a history-rewrite that dropped
                                                       the ID convention). Never ERROR
                                                       -- fail-closed would block
                                                       every pre-republication ticket.
    - <sha> HAS an object, is REACHABLE from the   -> PENDING_GROUPED_PUSH (WOT-2026-022x)
      current local branch, but is not in                the close is committed and on the
      origin/main                                        branch; it simply has not been
                                                         pushed YET. The code-only policy
                                                         is a GROUPED push at the end of
                                                         the session, so this is the NORMAL
                                                         state between commit and push --
                                                         not a lost close. Not an ERROR.
    - <sha> HAS an object but is NOT reachable     -> ERROR fail-closed (lost close): the
      from the local branch either                       object survives only in the reflog
                                                         / an orphan (a reset or rebase
                                                         dropped it). THIS is the case the
                                                         guard exists to catch, and the one
                                                         distinction that must never be
                                                         relaxed into a WARN.

WOT-2026-022x: before this distinction, ANY object that had not landed was ERROR, so
every row archived between its commit and the grouped push reported a false LOST CLOSE
(audit_pipeline_codeonly.md treats that ERROR as blocking APROBADO -> every code-only
chain was formally blocked in its pre-push window). Fixing it by pushing early to make
the guard green would have inverted the very policy WOT-2026-022u installed. The fix is
SEMANTIC, and it must NOT become fail-open: an object unreachable from the branch is
still ERROR.

Why the anchoring/exclusion matters (each VERIFIED against live git 2026-07-10):
    - CAPA 3 is anchored to origin/main, NEVER ``--all``: ``--all`` would count a
      commit that lives only on a local branch (e.g. ctl-012i-wip) as landed = false
      OK. The whole point is to catch exactly that.
    - EXACT ID match (``\\bID\\b``, not substring): a longer id (021c2, 021ci) must
      not satisfy a 021c audit (the WOT-2026-021l lesson).
    - Revert excluded: a ``Revert "...<ID>..."`` mentions the ID but UNDOES the work.
    - CAPA 2 never admits an empty patch-id into the set: a blank/absent patch-id
      would false-OK any commit whose own patch-id is empty. (``git log -p`` already
      emits no diff -- hence no patch-id line -- for a merge, so ``--no-merges`` is a
      clarity/perf trim, not the empty-guard; the empty-guard is the parse filter.)

Topology (mirrors backlog_reconcile.py): the guard lives in ``<motor>/scripts`` but
audits the backlog of the DESTINO/workspace, resolved via ``--project-root`` verbatim
or the workspace's ``motor_destination_link.json``. The git against which origin/main
is resolved is ``--git-repo`` (default: the motor root); it is NOT assumed to be any
particular worktree.

Exit codes:
    0 = all audited SHAs OK / OK_BY_SUBJECT / WARN (no lost close).
    1 = collector self-failure (backlog unparseable, git missing, etc.).
    2 = argument / topology error (bad --motor-root / --git-repo).
    3 = degraded topology (backlog link unresolved).
    4 = VERDICT: at least one SHA is ERROR (a recorded close did not land).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


SCHEMA_VERSION = "backlog-commits-landed-guard/v1"

# Exit codes (0/1/2/3 mirror backlog_reconcile.py; 4 is the dedicated verdict-ERROR).
EXIT_OK = 0
EXIT_SELF_FAIL = 1
EXIT_ARG = 2
EXIT_DEGRADED = 3
EXIT_VERDICT_ERROR = 4

# Verdicts (per-SHA).
OK = "OK"
OK_BY_SUBJECT = "OK_BY_SUBJECT"
# Committed and on the local branch, but not yet pushed (grouped-push policy, 022u).
# Non-blocking: it is the expected state between a ticket's commit and the session's
# grouped push. NOT a lost close.
PENDING_GROUPED_PUSH = "PENDING_GROUPED_PUSH"
ERROR = "ERROR"
WARN = "WARN"

# Only these archive-table rows are audited: closed rows carrying a commit token.
_COMPLETED_STATE = "completed"
_COMMIT_PREFIX = "commit:"
# Ticket-ID shape: WOT-2026-021o / WT-2026-250c / WP-2026-... (prefix-YYYY-suffix).
_TICKET_ID_RE = re.compile(r"^(?:WOT|WP|WT|CTL)-\d{4}-[0-9a-z]+$", re.IGNORECASE)
# Revert subjects to exclude from CAPA 3 (git's `Revert "..."` and manual revert:).
_REVERT_RE = re.compile(r"^\s*revert\b", re.IGNORECASE)


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> dict:
    """Run a command read-only, capturing stdout/stderr/exit. Never raises."""
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "ok": proc.returncode == 0,
        }
    except FileNotFoundError as exc:
        return {
            "cmd": cmd,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "ok": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "exit_code": None,
            "stdout": "",
            "stderr": f"timeout: {exc}",
            "ok": False,
        }
    except OSError as exc:
        return {
            "cmd": cmd,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "ok": False,
        }


def _relativize(text: str, roots: dict[str, Path]) -> str:
    """Replace absolute personal roots with stable placeholders (PII scrub)."""
    if not text:
        return text
    out = text
    for label, root in roots.items():
        if root is None:
            continue
        root_text = str(root)
        for variant in {
            root_text,
            root_text.replace("\\", "/"),
            root_text.replace("/", "\\"),
        }:
            out = out.replace(variant, f"<{label}>")
    return out


def _resolve_destino_root(
    project_root: str | None, workspace_root: str | None
) -> tuple[Path | None, str | None]:
    """Resolve the repo_destino/workspace whose backlog is audited.

    Precedence: (1) --project-root verbatim; else (2) the workspace's
    ``motor_destination_link.json`` ``destination_root``. The link is
    machine-specific/gitignored, so resolve it at runtime; absence returns
    (None, reason) so the caller degrades (exit 3), never crashes. Mirror of
    backlog_reconcile._resolve_destino_root.
    """
    if project_root:
        return Path(project_root).resolve(), None
    if not workspace_root:
        return None, "no --project-root and no --workspace-root to resolve the link"
    link = (
        Path(workspace_root).resolve()
        / ".agent"
        / "config"
        / "motor_destination_link.json"
    )
    try:
        data = json.loads(link.read_text(encoding="utf-8"))
    except OSError:
        return None, f"motor_destination_link.json not found under {workspace_root}"
    except json.JSONDecodeError as exc:
        return None, f"motor_destination_link.json unreadable: {exc}"
    dest = data.get("destination_root")
    if not dest:
        return None, "motor_destination_link.json has no destination_root"
    return Path(dest).resolve(), None


def parse_archived_commits(content: str) -> list[tuple[str, str]]:
    """Extract (ticket_id, sha) pairs from ``completed`` rows carrying a commit token.

    Robust to a literal ``|`` inside the Titulo cell (e.g. the live WOT-2026-021i row
    embeds ``system|infra`` -> 9 cells, not 8): the ticket-ID is the first cell whose
    text matches _TICKET_ID_RE, and the commit token is the cell that starts with
    ``commit:``. The token groups several SHAs with a LITERAL ``+``
    (``commit:sha1+sha2+sha3``); EVERY SHA is emitted as its own pair so each is
    audited (never collapse a group to its first member). A row is audited only if it
    has both a ``completed`` cell and a ``commit:`` cell.
    """
    pairs: list[tuple[str, str]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if _COMPLETED_STATE not in cells:
            continue
        ticket_id = next((c for c in cells if _TICKET_ID_RE.match(c)), None)
        commit_cell = next((c for c in cells if c.startswith(_COMMIT_PREFIX)), None)
        if not ticket_id or not commit_cell:
            continue
        token = commit_cell[len(_COMMIT_PREFIX) :].strip()
        for sha in token.split("+"):
            sha = sha.strip()
            if sha:
                pairs.append((ticket_id, sha))
    return pairs


def _has_object(sha: str, repo: Path) -> bool:
    """True if <sha> resolves to a commit object in this repo."""
    return _run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], repo)["exit_code"] == 0


def _is_ancestor(sha: str, ref: str, repo: Path) -> bool:
    """CAPA 1: <sha> is an ancestor of ref (exit 0 = yes, 1 = no)."""
    return (
        _run(["git", "merge-base", "--is-ancestor", sha, ref], repo)["exit_code"] == 0
    )


def _patch_id(sha: str, repo: Path) -> str:
    """Stable patch-id of a single commit, or '' if none (merge / empty / missing)."""
    show = _run(["git", "show", sha], repo)
    if show["exit_code"] != 0 or not show["stdout"]:
        return ""
    try:
        proc = subprocess.run(
            ["git", "patch-id", "--stable"],  # noqa: S607
            cwd=str(repo),
            input=show["stdout"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    out = proc.stdout.strip()
    return out.split()[0] if out else ""


def _parse_patch_id_lines(stdout: str) -> set[str]:
    """Collect the patch-id column (first token) of each ``git patch-id`` line.

    Blank / whitespace-only / malformed lines contribute NOTHING: an empty patch-id
    must never enter the set, or a commit whose own patch-id is empty (merge / empty
    diff) would false-OK against it. This is the load-bearing empty-guard for CAPA 2.
    """
    ids: set[str] = set()
    for line in stdout.splitlines():
        parts = line.split()
        if parts and parts[0]:
            ids.add(parts[0])
    return ids


def build_patch_id_set(ref: str, repo: Path) -> set[str]:
    """CAPA 2 support: patch-ids of every commit reachable from ref.

    Built ONCE per run (O(history); ~8s for ~940 commits) then reused as an O(1)
    membership test. ``--no-merges`` trims merge commits for clarity/perf (``git log
    -p`` emits no diff for a merge anyway, so they carry no patch-id); the actual
    empty-patch-id guard lives in _parse_patch_id_lines.
    """
    res = _run(["git", "log", "--no-merges", "-p", "--format=%H", ref], repo)
    if res["exit_code"] != 0 or not res["stdout"]:
        return set()
    try:
        proc = subprocess.run(
            ["git", "patch-id", "--stable"],  # noqa: S607
            cwd=str(repo),
            input=res["stdout"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return _parse_patch_id_lines(proc.stdout)


def _landed_by_subject(ticket_id: str, ref: str, repo: Path) -> bool:
    """CAPA 3: an EXACT-ID, non-Revert commit subject reachable from ref mentions ID.

    ``git log <ref> --grep`` is a substring pre-filter (anchored to ref, NEVER
    ``--all``); the exact ``\\bID\\b`` word-boundary match and the Revert exclusion are
    applied in Python so a longer id (021c2) or a revert can't false-OK.
    """
    res = _run(
        ["git", "log", ref, f"--grep={ticket_id}", "--fixed-strings", "--format=%s"],
        repo,
    )
    if res["exit_code"] != 0 or not res["stdout"]:
        return False
    exact = re.compile(rf"(?<![\w-]){re.escape(ticket_id)}(?![\w-])", re.IGNORECASE)
    for subject in res["stdout"].splitlines():
        if _REVERT_RE.match(subject):
            continue
        if exact.search(subject):
            return True
    return False


def classify(
    ticket_id: str, sha: str, ref: str, repo: Path, patch_ids: set[str]
) -> tuple[str, str]:
    """Return (verdict, detail) for one (ticket_id, sha), layers exact -> lax.

    Precedence is load-bearing: CAPA 3 (by-subject) runs BEFORE the no-object WARN,
    so a SHA rewritten by history (no object) whose ID still lands by convention is
    OK_BY_SUBJECT, not a false WARN (the 016e/016h case: the recorded SHAs have no
    object but the tickets landed under new SHAs).
    """
    if _is_ancestor(sha, ref, repo):
        return OK, "ancestor of origin/main (CAPA 1)"
    pid = _patch_id(sha, repo)
    if pid and pid in patch_ids:
        return OK, "patch-id present in origin/main (CAPA 2, rebase)"
    if _landed_by_subject(ticket_id, ref, repo):
        return (
            OK_BY_SUBJECT,
            "ticket-ID in an origin/main subject (CAPA 3, squash/cherry-pick)",
        )
    if _has_object(sha, repo):
        # WOT-2026-022x. The object exists and no layer says it landed. Two VERY
        # different situations, and collapsing them is what made the guard block
        # every code-only chain in its pre-push window:
        #   reachable from the local branch -> committed, simply not pushed YET
        #                                      (grouped-push policy, 022u): PENDING.
        #   NOT reachable                    -> the close is LOST (orphan / dropped by
        #                                      a reset or rebase): ERROR, fail-closed.
        # This must never become fail-open: the unreachable case stays ERROR.
        if _is_ancestor(sha, "HEAD", repo):
            return (
                PENDING_GROUPED_PUSH,
                "committed and reachable from the local branch, but not in "
                f"{ref} -- pending the session's grouped push (not a lost close)",
            )
        return ERROR, "object exists but landed by no layer -- LOST CLOSE (fail-closed)"
    return (
        WARN,
        "no git object and no ID in origin/main subjects -- obsolete cite / typo or "
        "a history-rewrite that dropped the ID convention; verify manually",
    )


def audit(pairs: list[tuple[str, str]], ref: str, repo: Path) -> list[dict]:
    """Classify every (ticket_id, sha) pair. Builds the CAPA-2 set once."""
    patch_ids = build_patch_id_set(ref, repo)
    results: list[dict] = []
    for ticket_id, sha in pairs:
        verdict, detail = classify(ticket_id, sha, ref, repo, patch_ids)
        results.append(
            {"ticket_id": ticket_id, "sha": sha, "verdict": verdict, "detail": detail}
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit that backlog-closed commits landed in origin/main (3 layers)."
    )
    parser.add_argument(
        "--motor-root", required=True, help="repo_motor path (MANIFEST.distribute)"
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="repo_destino/workspace (backlog owner), verbatim",
    )
    parser.add_argument(
        "--workspace-root",
        default=None,
        help="workspace holding motor_destination_link.json",
    )
    parser.add_argument(
        "--git-repo",
        default=None,
        help="repo whose origin/main the SHAs are audited against (default: --motor-root)",
    )
    parser.add_argument(
        "--ref", default="origin/main", help="reference to check landing against"
    )
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args(argv)

    motor_root = Path(args.motor_root).resolve()
    if not (motor_root / "MANIFEST.distribute").exists():
        print(
            f"[landed] ERROR: motor-root has no MANIFEST.distribute: {motor_root}",
            file=sys.stderr,
        )
        return EXIT_ARG

    git_repo = Path(args.git_repo).resolve() if args.git_repo else motor_root
    # Pin the ref repo explicitly: the ref must resolve here, else topology is wrong.
    if (
        _run(["git", "rev-parse", "--verify", "--quiet", args.ref], git_repo)[
            "exit_code"
        ]
        != 0
    ):
        print(
            f"[landed] ERROR: ref '{args.ref}' does not resolve in {git_repo} "
            "(wrong --git-repo, or run `git fetch` first)",
            file=sys.stderr,
        )
        return EXIT_ARG

    dest_root, dest_err = _resolve_destino_root(args.project_root, args.workspace_root)
    if dest_root is None:
        print(
            f"[landed] NOTICE: backlog root unresolved ({dest_err}); degraded.",
            file=sys.stderr,
        )
        return EXIT_DEGRADED

    archive = dest_root / ".agent" / "collaboration" / "_archive" / "backlog_done.md"
    try:
        content = archive.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(f"[landed] ERROR: cannot read archive {archive}: {exc}", file=sys.stderr)
        return EXIT_SELF_FAIL

    pairs = parse_archived_commits(content)
    results = audit(pairs, args.ref, git_repo)

    roots = {"MOTOR_ROOT": motor_root, "DESTINO_ROOT": dest_root, "GIT_REPO": git_repo}
    counts = {
        v: sum(1 for r in results if r["verdict"] == v)
        for v in (OK, OK_BY_SUBJECT, PENDING_GROUPED_PUSH, ERROR, WARN)
    }
    # Only ERROR blocks. PENDING_GROUPED_PUSH is the expected pre-push state (022x).
    errors = [r for r in results if r["verdict"] == ERROR]

    if args.json:
        payload = {
            "schema": SCHEMA_VERSION,
            "ref": args.ref,
            "audited": len(results),
            "counts": counts,
            "results": results,
        }
        print(_relativize(json.dumps(payload, indent=2, ensure_ascii=False), roots))
    else:
        print(f"[landed] audited {len(results)} commit(s) against {args.ref}")
        print(
            f"[landed] OK={counts[OK]} OK_BY_SUBJECT={counts[OK_BY_SUBJECT]} "
            f"PENDING_GROUPED_PUSH={counts[PENDING_GROUPED_PUSH]} "
            f"WARN={counts[WARN]} ERROR={counts[ERROR]}"
        )
        for r in results:
            if r["verdict"] in (ERROR, WARN, PENDING_GROUPED_PUSH):
                print(
                    f"[landed]   {r['verdict']}: {r['ticket_id']} {r['sha']} -- {r['detail']}"
                )

    if errors:
        print(
            f"[landed] FAIL: {len(errors)} recorded close(s) did NOT land in {args.ref}",
            file=sys.stderr,
        )
        return EXIT_VERDICT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
