"""Tests for scripts/check_backlog_commits_landed.py (WOT-2026-021o).

The guard is git plumbing, so tests build REAL ephemeral git repos under tmp_path
(mocks would not exercise ancestor / patch-id / grep faithfully). The load-bearing
scenarios are the 6 DoD fixtures -- en-main / rebased-same-patchid / squashed-same-ID
/ Revert-of-ID / not-landed-by-any-layer / nonexistent -> OK/OK/OK_BY_SUBJECT/NO-OK/
ERROR/WARN -- plus a mutation-to-prove test per contract clause: breaking a layer,
the group split, the Revert exclusion, or the exact-ID match must flip a verdict.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "check_backlog_commits_landed",
    Path(__file__).resolve().parents[2] / "scripts" / "check_backlog_commits_landed.py",
)
gl = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gl)


def _g(args, cwd):
    """Run a git command in cwd, raising on failure (test setup must succeed)."""
    subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    )


def _sha(cwd, ref="HEAD"):
    return subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(work, fname, body, msg):
    (work / fname).write_text(body, encoding="utf-8")
    _g(["add", fname], work)
    _g(["commit", "-qm", msg], work)
    return _sha(work)


def _make_repo(tmp_path):
    """A repo with a real ``origin/main`` remote-tracking ref.

    Bare origin + a work clone; main gets one base commit pushed so origin/main
    exists. Callers add scenario commits, push (or not), and re-fetch.
    """
    origin = tmp_path / "origin.git"
    _g(["init", "--bare", "-q", str(origin)], tmp_path)
    work = tmp_path / "work"
    _g(["clone", "-q", str(origin), str(work)], tmp_path)
    _g(["config", "user.email", "t@t.com"], work)
    _g(["config", "user.name", "t"], work)
    _commit(work, "base.txt", "base\n", "base")
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    return origin, work


def _classify(work, ticket_id, sha, patch_ids=None):
    ref = "origin/main"
    if patch_ids is None:
        patch_ids = gl.build_patch_id_set(ref, work)
    return gl.classify(ticket_id, sha, ref, work, patch_ids)


# --------------------------------------------------------------------------- #
# CAPA 1 -- direct ancestor -> OK
# --------------------------------------------------------------------------- #
def test_capa1_ancestor_is_ok(tmp_path):
    _origin, work = _make_repo(tmp_path)
    landed = _commit(work, "a.txt", "a\n", "WOT-2026-0AAA: feature a")
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    verdict, _ = _classify(work, "WOT-2026-0AAA", landed)
    assert verdict == gl.OK


# --------------------------------------------------------------------------- #
# CAPA 2 -- rebase: SHA differs, patch-id is the same -> OK
# --------------------------------------------------------------------------- #
def _rebased_pair(tmp_path):
    """Return (work, original_sha, rebased_sha) where only the rebase is in main."""
    _origin, work = _make_repo(tmp_path)
    # feature branch off base, one commit -> original SHA (never pushed to main)
    _g(["checkout", "-q", "-b", "feat"], work)
    original = _commit(
        work, "feat.txt", "feature payload\n", "WOT-2026-0BBB: rebased work"
    )
    # meanwhile main advances
    _g(["checkout", "-q", "main"], work)
    _commit(work, "main2.txt", "main advances\n", "chore: main moves")
    # rebase feat onto main -> same patch, new SHA, then merge into main + push
    _g(["checkout", "-q", "feat"], work)
    _g(["rebase", "-q", "main"], work)
    rebased = _sha(work)
    _g(["checkout", "-q", "main"], work)
    _g(["merge", "-q", "--ff-only", "feat"], work)
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    return work, original, rebased


def test_capa2_rebase_same_patchid_is_ok(tmp_path):
    work, original, rebased = _rebased_pair(tmp_path)
    # sanity: original is NOT an ancestor of origin/main, rebased IS
    assert not gl._is_ancestor(original, "origin/main", work)
    assert gl._is_ancestor(rebased, "origin/main", work)
    # and they share a patch-id
    assert gl._patch_id(original, work) == gl._patch_id(rebased, work) != ""
    verdict, detail = _classify(work, "WOT-2026-0BBB", original)
    assert verdict == gl.OK
    assert "CAPA 2" in detail


# --------------------------------------------------------------------------- #
# CAPA 3 -- squash: SHA and patch-id differ, ID survives in subject -> OK_BY_SUBJECT
# --------------------------------------------------------------------------- #
def _squashed(tmp_path):
    """Return (work, original_sha) where original's ID landed only via a squash."""
    _origin, work = _make_repo(tmp_path)
    _g(["checkout", "-q", "-b", "feat"], work)
    _commit(work, "p1.txt", "part 1\n", "wip part 1")
    original = _commit(work, "p2.txt", "part 2\n", "WOT-2026-0CCC: two-part work")
    # squash-merge into main: single new commit carrying the ID (different patch-id)
    _g(["checkout", "-q", "main"], work)
    _g(["merge", "-q", "--squash", "feat"], work)
    _g(["commit", "-qm", "WOT-2026-0CCC: two-part work (squashed)"], work)
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    return work, original


def test_capa3_squash_id_in_subject_is_ok_by_subject(tmp_path):
    work, original = _squashed(tmp_path)
    assert not gl._is_ancestor(original, "origin/main", work)
    patch_ids = gl.build_patch_id_set("origin/main", work)
    assert gl._patch_id(original, work) not in patch_ids  # CAPA 2 fails for squash
    verdict, detail = _classify(work, "WOT-2026-0CCC", original, patch_ids)
    assert verdict == gl.OK_BY_SUBJECT
    assert "CAPA 3" in detail


# --------------------------------------------------------------------------- #
# Revert of the ID -> must NOT count as landed
# --------------------------------------------------------------------------- #
def _reverted(tmp_path):
    """Return (work, original_sha) where the ID appears ONLY in a Revert subject.

    A literal ``Revert "..."`` subject (git's own revert format) is created directly
    rather than via ``git revert`` -- what CAPA 3 keys off is the subject text, and
    ``git revert -q`` is rejected as a usage error by some git versions. The original
    work lives on a never-landed branch (distinct payload, distinct patch-id).
    """
    _origin, work = _make_repo(tmp_path)
    _g(["checkout", "-q", "-b", "feat"], work)
    original = _commit(
        work, "r.txt", "reverted payload\n", "WOT-2026-0DDD: work to undo"
    )
    # main gets ONLY a Revert-subject commit that mentions the ID (no landed payload).
    _g(["checkout", "-q", "main"], work)
    _commit(work, "revlog.txt", "reverted\n", 'Revert "WOT-2026-0DDD: work to undo"')
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    return work, original


def test_revert_only_mention_is_not_landed(tmp_path):
    work, original = _reverted(tmp_path)
    # The ORIGINAL (feat) SHA has an object but is not an ancestor / not patch-id-present;
    # only a Revert subject mentions the ID and CAPA 3 must exclude it -> ERROR.
    verdict, _ = _classify(work, "WOT-2026-0DDD", original)
    assert verdict == gl.ERROR
    # And CAPA 3 itself must reject the Revert-only mention outright.
    assert gl._landed_by_subject("WOT-2026-0DDD", "origin/main", work) is False


def test_revert_exclusion_is_case_insensitive_and_manual(tmp_path):
    """A lowercase `revert:` subject must also be excluded by CAPA 3."""
    _origin, work = _make_repo(tmp_path)
    _g(["checkout", "-q", "-b", "feat"], work)
    _commit(work, "m.txt", "x\n", "WOT-2026-0EEE: manual revert case")
    _g(["checkout", "-q", "main"], work)
    # manual lowercase revert mentioning the ID -- must NOT satisfy CAPA 3
    _commit(work, "note.txt", "note\n", "revert: drop WOT-2026-0EEE for now")
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    assert gl._landed_by_subject("WOT-2026-0EEE", "origin/main", work) is False


# --------------------------------------------------------------------------- #
# ERROR -- object exists, landed by NO layer (synthetic lost close)
# --------------------------------------------------------------------------- #
def test_error_object_exists_not_landed(tmp_path):
    _origin, work = _make_repo(tmp_path)
    _g(["checkout", "-q", "-b", "orphan"], work)
    orphan = _commit(work, "o.txt", "orphan work\n", "WOT-2026-0FFF: never landed")
    _g(["checkout", "-q", "main"], work)  # main never gets it, never pushed
    verdict, detail = _classify(work, "WOT-2026-0FFF", orphan)
    assert verdict == gl.ERROR
    assert "LOST CLOSE" in detail


# --------------------------------------------------------------------------- #
# WARN -- no git object at all (obsolete cite / typo)
# --------------------------------------------------------------------------- #
def test_warn_nonexistent_sha(tmp_path):
    _origin, work = _make_repo(tmp_path)
    verdict, _ = _classify(
        work, "WOT-2026-0GGG", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    )
    assert verdict == gl.WARN


# --------------------------------------------------------------------------- #
# Precedence: no-object SHA whose ID landed by subject -> OK_BY_SUBJECT, not WARN
# (the real 016e/016h case; CAPA 3 must run BEFORE the no-object WARN early-exit)
# --------------------------------------------------------------------------- #
def test_no_object_but_id_landed_is_ok_by_subject_not_warn(tmp_path):
    _origin, work = _make_repo(tmp_path)
    _commit(
        work,
        "h.txt",
        "history-rewritten landing\n",
        "WOT-2026-0HHH: landed post-rewrite",
    )
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    # audit a SHA that has NO object but whose ID is in an origin/main subject
    verdict, _ = _classify(
        work, "WOT-2026-0HHH", "cafebabecafebabecafebabecafebabecafebabe"
    )
    assert verdict == gl.OK_BY_SUBJECT


# --------------------------------------------------------------------------- #
# CAPA 3 anchored to ref, NEVER --all: a commit living ONLY on a local branch
# (the CTL-012i / ctl-012i-wip shape) must NOT count as landed. This is the
# load-bearing safety property -- a `--all` mutation would false-OK it.
# --------------------------------------------------------------------------- #
def test_capa3_local_branch_only_is_not_landed(tmp_path):
    _origin, work = _make_repo(tmp_path)
    # a commit that carries the ID but lives only on a local branch, never on main
    _g(["checkout", "-q", "-b", "wip-local"], work)
    local = _commit(work, "w.txt", "wip\n", "WOT-2026-0JJJ: only on local branch")
    _g(["checkout", "-q", "main"], work)  # main / origin/main never see it
    # anchored to origin/main -> NOT landed by subject (a --all grep WOULD find it)
    assert gl._landed_by_subject("WOT-2026-0JJJ", "origin/main", work) is False
    # and the full verdict is ERROR (object exists, no layer) -- exactly the lost close
    verdict, _ = _classify(work, "WOT-2026-0JJJ", local)
    assert verdict == gl.ERROR


# --------------------------------------------------------------------------- #
# Parser: robust to a literal '|' in the Titulo cell (the live 021i 9-cell row)
# and audits EVERY SHA of a commit:a+b+c group.
# --------------------------------------------------------------------------- #
_ROW_PIPE_IN_TITULO = (
    "| Baja | WOT-2026-021i | recolector (motor/* -> motor, system|infra -> n/a) "
    "deliverable_type: code | motor/backlog-reconcile-collector | completed | "
    "WOT-2026-021h | session-x | commit:31ce34f |"
)
_ROW_GROUP = (
    "| Media | WOT-2026-016e | fix scope-override | motor/scope-override-paths | "
    "completed | - | session-y | commit:1f667da+1ec9cae+301bab0 |"
)
_ROW_PENDING = (
    "| Alta | WOT-2026-999z | not closed | motor/x | pending | - | session-z | - |"
)


def test_parser_handles_pipe_in_titulo():
    pairs = gl.parse_archived_commits(_ROW_PIPE_IN_TITULO)
    assert pairs == [("WOT-2026-021i", "31ce34f")]


def test_parser_audits_all_shas_in_group():
    pairs = gl.parse_archived_commits(_ROW_GROUP)
    assert pairs == [
        ("WOT-2026-016e", "1f667da"),
        ("WOT-2026-016e", "1ec9cae"),
        ("WOT-2026-016e", "301bab0"),
    ]


def test_parser_skips_non_completed_rows():
    assert gl.parse_archived_commits(_ROW_PENDING) == []


# --------------------------------------------------------------------------- #
# Exact-ID match: a longer id must not satisfy a shorter-id audit (021l lesson)
# --------------------------------------------------------------------------- #
def test_capa3_exact_id_no_substring_contamination(tmp_path):
    _origin, work = _make_repo(tmp_path)
    # only a LONGER id lands; the shorter id must NOT match
    _commit(work, "c.txt", "x\n", "WOT-2026-021c2: a different, longer ticket")
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    assert gl._landed_by_subject("WOT-2026-021c", "origin/main", work) is False
    assert gl._landed_by_subject("WOT-2026-021c2", "origin/main", work) is True


# --------------------------------------------------------------------------- #
# MUTATION-TO-PROVE: each contract clause, when broken, must flip a verdict.
# These assert the CURRENT (correct) behaviour; the docstrings name the mutation
# that would make them fail (Review 2 re-runs those mutations against production).
# --------------------------------------------------------------------------- #
def _rebased_no_id_subject(tmp_path):
    """A rebase whose subject does NOT carry the ticket-ID -> ONLY CAPA 2 can save it.

    Isolates CAPA 2 from CAPA 3: the recorded ticket-ID lives in the backlog, not in
    the commit subject, so patch-id is the only layer that can land the original SHA.
    """
    _origin, work = _make_repo(tmp_path)
    _g(["checkout", "-q", "-b", "feat"], work)
    original = _commit(
        work, "feat.txt", "payload\n", "feat: work with no id in subject"
    )
    _g(["checkout", "-q", "main"], work)
    _commit(work, "main2.txt", "main advances\n", "chore: main moves")
    _g(["checkout", "-q", "feat"], work)
    _g(["rebase", "-q", "main"], work)
    _g(["checkout", "-q", "main"], work)
    _g(["merge", "-q", "--ff-only", "feat"], work)
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    return work, original


def test_mut_rebase_needs_capa2(tmp_path):
    """MUT 'compare only by literal SHA' -> rebase would flip OK->ERROR.

    Uses a rebase whose subject lacks the ticket-ID, so CAPA 3 cannot mask the
    mutation: with CAPA 2 the original is OK; with an empty patch-id set it is ERROR.
    """
    work, original = _rebased_no_id_subject(tmp_path)
    # CAPA 3 genuinely cannot fire here (no ID in subject) -- proving CAPA 2 isolation.
    assert gl._landed_by_subject("WOT-2026-0BBB", "origin/main", work) is False
    assert _classify(work, "WOT-2026-0BBB", original)[0] == gl.OK
    assert (
        gl.classify("WOT-2026-0BBB", original, "origin/main", work, set())[0]
        == gl.ERROR
    )


def test_mut_squash_needs_capa3(tmp_path):
    """MUT 'compare only by patch-id' -> squash would flip OK_BY_SUBJECT->ERROR."""
    work, original = _squashed(tmp_path)
    patch_ids = gl.build_patch_id_set("origin/main", work)
    assert _classify(work, "WOT-2026-0CCC", original, patch_ids)[0] == gl.OK_BY_SUBJECT
    # a wrong-ID audit (CAPA 3 can't fire) with the same patch-id set -> ERROR
    assert (
        gl.classify("WOT-2026-0XXX", original, "origin/main", work, patch_ids)[0]
        == gl.ERROR
    )


def test_mut_group_first_sha_only_would_miss_others():
    """MUT 'parser takes only 1st SHA of a+b+c' -> 2nd/3rd never audited."""
    pairs = gl.parse_archived_commits(_ROW_GROUP)
    assert len(pairs) == 3  # a first-only parser would yield 1 and skip 016e's 2nd/3rd


# --------------------------------------------------------------------------- #
# CAPA 2 empty-patch-id guard: the parse filter must never admit '' into the set.
# Tests _parse_patch_id_lines directly (the real guard) so the barrier has teeth:
# dropping the `if parts and parts[0]` filter makes this fail. (A merge doesn't
# produce a patch-id line at all under `git log -p`, so a repo-level test would be
# a tautology -- this exercises the filter against blank/malformed input instead.)
# --------------------------------------------------------------------------- #
def test_capa2_parse_drops_blank_and_malformed_lines():
    stdout = (
        "abc123 deadbeef\n"  # normal: patch-id <sha>
        "\n"  # blank line -> must be dropped
        "   \n"  # whitespace-only -> must be dropped
        "def456 cafef00d\n"  # normal
    )
    ids = gl._parse_patch_id_lines(stdout)
    assert ids == {"abc123", "def456"}
    assert "" not in ids


def test_capa2_set_from_real_repo_has_no_empty(tmp_path):
    """End-to-end: a real repo (incl. a merge) never yields '' in the set."""
    _origin, work = _make_repo(tmp_path)
    _g(["checkout", "-q", "-b", "side"], work)
    _commit(work, "s.txt", "side\n", "side work")
    _g(["checkout", "-q", "main"], work)
    _commit(work, "m.txt", "main\n", "main work")
    _g(["merge", "-q", "--no-ff", "-m", "merge side", "side"], work)
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    assert "" not in gl.build_patch_id_set("origin/main", work)


def test_capa2_empty_patchid_is_not_a_match(tmp_path):
    """A SHA with an empty patch-id must not match even if '' were in the set."""
    _origin, work = _make_repo(tmp_path)
    _g(["checkout", "-q", "-b", "orphan"], work)
    orphan = _commit(work, "o.txt", "x\n", "WOT-2026-0III: orphan")
    _g(["checkout", "-q", "main"], work)
    # Force a poisoned set containing '' -- classify must still NOT return OK via CAPA 2
    verdict, _ = gl.classify("WOT-2026-0III", orphan, "origin/main", work, {""})
    assert verdict == gl.ERROR  # orphan has an object, no layer hits -> ERROR, not OK
