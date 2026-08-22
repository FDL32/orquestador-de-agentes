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
    _g(["init", "--bare", "-b", "main", "-q", str(origin)], tmp_path)
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


def _archive_with(tmp_path, work, pairs):
    """A minimal DESTINO root whose archived backlog closes `pairs`.

    Needed to exercise main() (and therefore the real EXIT CODE), not just
    classify()/audit(). The exit-code decision lives in main(), so a test that
    only inspects audit()'s verdicts cannot prove the guard fails (or does not
    fail) as intended -- see test_022x_pending_does_not_trigger_the_error_exit_code.

    Also drops the MANIFEST.distribute that main() requires of the motor root.
    """
    (work / "MANIFEST.distribute").write_text("x\n", encoding="utf-8")
    dest = tmp_path / "destino"
    archive = dest / ".agent" / "collaboration" / "_archive"
    archive.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"| Alta | {tid} | t | motor/x | completed | - | s | commit:{sha} |"
        for tid, sha in pairs
    )
    (archive / "backlog_done.md").write_text(rows + "\n", encoding="utf-8")
    return dest


def _archive_raw(tmp_path, work, rows_text):
    """A minimal DESTINO root whose archived backlog is exactly `rows_text`.

    Lets a census/exit-code test lay out arbitrary rows (a code row WITHOUT a commit
    cell, a plural `commits:` cell, a `done` state) that `_archive_with` -- which always
    emits a `completed` + `commit:` shape -- cannot express. Also drops the
    MANIFEST.distribute main() requires of the motor root.
    """
    (work / "MANIFEST.distribute").write_text("x\n", encoding="utf-8")
    dest = tmp_path / "destino"
    archive = dest / ".agent" / "collaboration" / "_archive"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "backlog_done.md").write_text(rows_text, encoding="utf-8")
    return dest


def _run_main(tmp_path, work, dest):
    return gl.main(
        [
            "--motor-root",
            str(work),
            "--project-root",
            str(dest),
            "--ref",
            "origin/main",
        ]
    )


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


# --------------------------------------------------------------------------- #
# WOT-2026-023q -- a SHA that never left the machine must NOT be blessed by a
# SIBLING commit's subject. CAPA 3 is a convention about the ID; "the object is
# here and reachable from my branch" is a FACT about the SHA. The fact wins.
# --------------------------------------------------------------------------- #
def _unpushed_with_sibling_landed(tmp_path):
    """(work, unpushed_sha): the ticket ALREADY landed a commit carrying its ID in the
    subject, and a LATER commit of the same ticket is still sitting unpushed on main.

    This is the every-session shape: the grouped-push policy archives rows whose commit
    has not been pushed yet, and those tickets usually have earlier commits (a contract
    edit, a probe) already in origin/main with the ID in the subject.
    """
    _origin, work = _make_repo(tmp_path)
    _commit(work, "c.txt", "contract\n", "WOT-2026-0QQQ: contract (landed)")
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    # the fix itself: committed on main, NEVER pushed
    unpushed = _commit(work, "f.txt", "the fix\n", "WOT-2026-0QQQ: the fix (unpushed)")
    return work, unpushed


def test_unpushed_sha_is_pending_not_blessed_by_sibling_subject(tmp_path):
    """THE FALSE-GREEN. The ID landed via a SIBLING commit, but THIS sha never left the
    machine -> PENDING_GROUPED_PUSH, never OK_BY_SUBJECT.

    Mutation-to-prove: put CAPA 3 back above the PENDING check and this goes red --
    the guard reports the close as landed while the fix exists only locally.
    """
    work, unpushed = _unpushed_with_sibling_landed(tmp_path)

    # Assert the setup: CAPA 3 genuinely CAN fire here (that is the whole trap), and
    # the sha genuinely is NOT in origin/main but IS on the local branch.
    assert gl._landed_by_subject("WOT-2026-0QQQ", "origin/main", work) is True
    assert gl._is_ancestor(unpushed, "origin/main", work) is False
    assert gl._is_ancestor(unpushed, "HEAD", work) is True

    verdict, detail = _classify(work, "WOT-2026-0QQQ", unpushed)

    assert verdict == gl.PENDING_GROUPED_PUSH, (
        f"a commit that never left the machine was blessed as {verdict}"
    )
    assert "grouped push" in detail


def test_mut_pending_hoist_must_require_reachable_from_head(tmp_path):
    """MUT 'PENDING fires on any existing object' -> the SQUASH case would flip
    OK_BY_SUBJECT -> PENDING_GROUPED_PUSH.

    The `_is_ancestor(sha, HEAD)` conjunct is what keeps the hoist from swallowing
    CAPA 3's legitimate cases: a squashed original still HAS an object, but it is not
    reachable from HEAD. Isolates the branch: without this test, dropping the conjunct
    would look harmless.
    """
    work, original = _squashed(tmp_path)
    patch_ids = gl.build_patch_id_set("origin/main", work)

    assert gl._has_object(original, work) is True  # the object survives the squash
    assert gl._is_ancestor(original, "HEAD", work) is False  # but is NOT on main
    assert _classify(work, "WOT-2026-0CCC", original, patch_ids)[0] == gl.OK_BY_SUBJECT


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


# --------------------------------------------------------------------------- #
# WOT-2026-022x -- PENDING_GROUPED_PUSH vs LOST CLOSE
#
# The code-only policy (022u) is a GROUPED push at the end of the session, so a
# row archived right after its commit is legitimately NOT in origin/main yet.
# Before 022x the guard called that ERROR (LOST CLOSE), and since
# audit_pipeline_codeonly.md treats such an ERROR as blocking APROBADO, EVERY
# code-only chain was formally blocked in its pre-push window.
#
# The fix is semantic and must NOT become fail-open. The four cases below are the
# whole contract: only case 2 changes; case 3 -- an object that exists but is NOT
# reachable from the local branch (an orphan left by a reset/rebase) -- is the
# genuine lost close and MUST stay ERROR.
# --------------------------------------------------------------------------- #
def test_022x_case1_landed_in_origin_is_ok(tmp_path):
    """Case 1: pushed and in origin/main -> OK (unchanged)."""
    _origin, work = _make_repo(tmp_path)
    sha = _commit(work, "p.txt", "p\n", "WOT-2026-0PP1: landed")
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    verdict, _ = _classify(work, "WOT-2026-0PP1", sha)
    assert verdict == gl.OK


def test_022x_case2_committed_not_pushed_is_pending_not_error(tmp_path):
    """Case 2 -- THE FIX: committed, on the local branch, not pushed yet.

    LOAD-BEARING: this is the NORMAL state under the grouped-push policy, between
    a ticket's commit and the session's push. It is not a lost close.
    """
    _origin, work = _make_repo(tmp_path)
    sha = _commit(work, "q.txt", "q\n", "WOT-2026-0PP2: committed, not pushed")
    # deliberately NOT pushed
    verdict, detail = _classify(work, "WOT-2026-0PP2", sha)
    assert verdict == gl.PENDING_GROUPED_PUSH, (
        "a commit that is on the local branch but not yet pushed is PENDING, not a "
        "LOST CLOSE: the grouped-push policy (022u) makes this the expected state"
    )
    assert "grouped push" in detail


def test_022x_case3_object_unreachable_from_branch_stays_error(tmp_path):
    """Case 3 -- THE ANTI-FAIL-OPEN CASE: the object exists but is NOT reachable
    from the local branch (orphaned by a reset/rebase; survives only in the reflog).

    LOAD-BEARING: this is the genuine LOST CLOSE the guard exists to catch. If 022x
    had keyed on "has an object" instead of "reachable from the branch", this would
    have been downgraded to PENDING and the guard would be FAIL-OPEN.

    Mutation: classify on _has_object alone -> this goes RED.
    """
    _origin, work = _make_repo(tmp_path)
    _g(["checkout", "-q", "-b", "tmpwork"], work)
    orphan = _commit(work, "r.txt", "r\n", "WOT-2026-0PP3: will be orphaned")
    _g(["checkout", "-q", "main"], work)
    _g(["branch", "-qD", "tmpwork"], work)  # object survives; nothing points at it

    verdict, detail = _classify(work, "WOT-2026-0PP3", orphan)
    assert verdict == gl.ERROR, (
        "an object unreachable from the local branch is a LOST CLOSE and must stay "
        "ERROR; downgrading it to PENDING would make the guard fail-open"
    )
    assert "LOST CLOSE" in detail


def test_022x_case4_nonexistent_sha_stays_warn(tmp_path):
    """Case 4: the SHA has no git object at all -> WARN, NOT ERROR.

    PREMISE REFUTED, pinned here on purpose. The chain's start-up prompt asked for
    "nonexistent SHA -> ERROR". That is WRONG, and this test exists so nobody
    "fixes" it back: the repo went through a legitimate history-rewrite
    (filter-repo, 020u) that left archived SHAs with no object whose ticket DID
    land under a new SHA -- 7 such rows are OK_BY_SUBJECT today. Making the
    no-object case an ERROR would fail legitimately republished work.

    The discriminant that matters is NOT "does the object exist" but "is it
    reachable from the branch": a SHA with no object cannot be a lost close (there
    is nothing to lose); an ORPHANED object can -- and that one stays ERROR
    (test_022x_case3).
    """
    _origin, work = _make_repo(tmp_path)
    verdict, _ = _classify(work, "WOT-2026-0PP4", "deadbeefdeadbeefdeadbeefdeadbeef")
    assert verdict == gl.WARN, (
        "a SHA with no git object must be WARN (obsolete cite / history-rewrite), "
        "never ERROR: fail-closed here would block every pre-republication ticket"
    )


def test_022x_pending_does_not_trigger_the_error_exit_code(tmp_path):
    """PENDING_GROUPED_PUSH must NOT make the guard FAIL (exit 4).

    LOAD-BEARING, and it must assert on the REAL exit code of main(), not on
    audit()'s verdict list. A first version of this test checked only the verdicts
    returned by audit(); the mutation that counts PENDING as an ERROR (which
    reintroduces the whole 022x bug -- the guard blocking the chain verdict again)
    left it GREEN, because the error filter lives in main(), not in audit(). Testing
    the wrong layer is a substring-proxy in disguise: assert the PROPERTY (the guard
    does not fail) at the layer that owns it.

    Mutation: count PENDING among `errors` in main() -> exit 4 -> RED.
    """
    _origin, work = _make_repo(tmp_path)
    sha = _commit(work, "s.txt", "s\n", "WOT-2026-0PP5: pending")

    results = gl.audit([("WOT-2026-0PP5", sha)], "origin/main", work)
    assert [r["verdict"] for r in results] == [gl.PENDING_GROUPED_PUSH]

    archive = _archive_with(tmp_path, work, [("WOT-2026-0PP5", sha)])
    rc = gl.main(
        [
            "--motor-root",
            str(work),
            "--project-root",
            str(archive),
            "--ref",
            "origin/main",
        ]
    )
    assert rc == gl.EXIT_OK, (
        f"a PENDING (committed, not yet pushed) close must NOT fail the guard; "
        f"got exit {rc}. Blocking on it is exactly the bug 022x fixes."
    )


def test_022x_a_real_lost_close_still_fails_the_guard(tmp_path):
    """The anti-fail-open twin of the test above, at the exit-code layer: a genuine
    LOST CLOSE (object unreachable from the branch) must STILL make the guard fail.

    Without this, 'PENDING does not fail' could be satisfied by a guard that never
    fails at all.
    """
    _origin, work = _make_repo(tmp_path)
    _g(["checkout", "-q", "-b", "tmpwork"], work)
    orphan = _commit(work, "t.txt", "t\n", "WOT-2026-0PP6: orphaned")
    _g(["checkout", "-q", "main"], work)
    _g(["branch", "-qD", "tmpwork"], work)

    archive = _archive_with(tmp_path, work, [("WOT-2026-0PP6", orphan)])
    rc = gl.main(
        [
            "--motor-root",
            str(work),
            "--project-root",
            str(archive),
            "--ref",
            "origin/main",
        ]
    )
    assert rc == gl.EXIT_VERDICT_ERROR, (
        f"a lost close (unreachable object) must still fail the guard; got exit {rc}"
    )


# =========================================================================== #
# WOT-2026-024c -- the guard KNOWS and PUBLISHES its denominator.
#
# Before this ticket parse_archived_commits `continue`d over `completed` code/mixed
# rows that had no `commit:` cell with NO counter, and main() reported only
# `audited = len(results)`. ERROR=0 meant "of what I looked at, nothing failed", not
# "everything landed". These tests pin the census, the plural recognition, the
# terminal-state set, uniqueness, and the prose-is-not-evidence rule. Numbers are NOT
# asserted as thresholds (they are dated snapshots); the INVARIANTS are.
# =========================================================================== #

# A terminal code row with deliverable_type in the prose cell but NO commit cell --
# the exact silent-skip shape this ticket exposes (mirrors live 021e/021j).
_ROW_CODE_NO_COMMIT = (
    "| Media | WOT-2026-0S1S | some fix deliverable_type: code | motor/x | "
    "completed | - | session-s | some-note |"
)
# A terminal code row WITH a plural commits: cell (mirrors live 019j/016e plural rows).
_ROW_CODE_PLURAL = (
    "| Media | WOT-2026-0P1P | plural work deliverable_type: code | motor/x | "
    "completed | - | session-p | commits:aaaaaaa+bbbbbbb |"
)
# A terminal legacy row: no deliverable_type substring at all -> exempt.
_ROW_LEGACY = (
    "| Baja | WOT-2026-0L1L | legacy row no dtype | motor/x | completed | - | "
    "session-l | some-note |"
)
# A terminal legacy row WITHOUT deliverable_type but WITH a valid commit cell
# (WOT-2026-055u): the evidence exists, so the census must AUDIT it.
_ROW_LEGACY_WITH_COMMIT = (
    "| Baja | WOT-2026-0L2L | legacy row commit no dtype | motor/x | completed | "
    "origina/foo | session-l | commit:0abc123 |"
)
# A `done`-state code row without commit -- terminal but NOT "completed" (DoD-4).
_ROW_DONE_CODE_NO_COMMIT = (
    "| Alta | WOT-2026-0D1D | done code deliverable_type: code | motor/x | done | "
    "- | session-d | some-note |"
)


# --------------------------------------------------------------------------- #
# DoD-1: the census publishes required / audited / skipped_required / skipped_legacy,
# and deliverable_type is read as a SUBSTRING of the prose cell, not a column.
# --------------------------------------------------------------------------- #
def test_dod1_census_publishes_denominator_from_prose_substring():
    """DoD-1. A `completed`+code row with NO commit cell must land in skipped_required
    (it must NOT silently vanish), and a legacy row (no deliverable_type) in
    skipped_legacy. deliverable_type is a substring of the Titulo cell.

    Reachable mutation: read deliverable_type as a positional cell (equality) instead
    of a substring -> the code rows classify as `None` -> skipped_required drops to 0
    and this assertion goes RED.
    """
    content = "\n".join([_ROW_CODE_NO_COMMIT, _ROW_CODE_PLURAL, _ROW_LEGACY]) + "\n"
    census = gl.census_archived(content)
    # 2 required rows (both code), 1 audited (the plural one), 1 skipped_required, 1 legacy
    assert census["required"] == 2
    assert census["audited"] == 1
    assert census["skipped_required"] == 1
    assert census["skipped_legacy"] == 1
    assert census["skipped_required_tickets"] == ["WOT-2026-0S1S"]


def test_dod1_deliverable_type_is_substring_not_column():
    """DoD-1 surface fix, isolated: a positional/equality read of deliverable_type
    returns nothing (the token is embedded in prose), the substring read returns it.

    Reachable mutation: replace the substring search with a per-cell equality read ->
    dtype resolves to None -> required drops to 0.
    """
    cells = [c.strip() for c in _ROW_CODE_NO_COMMIT.strip().strip("|").split("|")]
    # No single cell EQUALS a bare deliverable_type value -- the equality read is blind.
    assert not any(c in gl._LANDING_REQUIRED_TYPES for c in cells)
    # The substring read over the whole row DOES find it.
    assert gl._DELIVERABLE_TYPE_RE.search(_ROW_CODE_NO_COMMIT).group(1) == "code"
    assert gl.census_archived(_ROW_CODE_NO_COMMIT + "\n")["required"] == 1


# --------------------------------------------------------------------------- #
# DoD-2: ERROR=0 exits 0 ONLY if skipped_required == 0; otherwise the guard exits
# non-zero and lists the tickets. Asserted at the EXIT-CODE layer (main owns it).
# --------------------------------------------------------------------------- #
def test_dod2_skipped_required_makes_guard_exit_nonzero(tmp_path):
    """DoD-2. A required (terminal code) row with no commit evidence makes main() exit
    non-zero EVEN WHEN there are zero ERROR verdicts (nothing to audit at all here).

    Reachable mutation: return EXIT_OK regardless of census['skipped_required'] (the
    pre-fix behaviour) -> this goes RED. This is the core bug: ERROR=0 was a false
    green while a required row was silently skipped.
    """
    _origin, work = _make_repo(tmp_path)
    dest = _archive_raw(tmp_path, work, _ROW_CODE_NO_COMMIT + "\n")
    rc = _run_main(tmp_path, work, dest)
    assert rc == gl.EXIT_SKIPPED_REQUIRED, (
        f"a required code row with no commit evidence must fail the guard even with "
        f"ERROR=0; got exit {rc}"
    )


def test_dod2_clean_denominator_exits_ok(tmp_path):
    """DoD-2 twin: with every required row carrying evidence (skipped_required == 0)
    and no ERROR verdict, the guard exits 0. Guards against a fix that always fails.
    """
    _origin, work = _make_repo(tmp_path)
    landed = _commit(work, "a.txt", "a\n", "WOT-2026-0K1K: landed")
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)
    row = (
        f"| Media | WOT-2026-0K1K | work deliverable_type: code | motor/x | "
        f"completed | - | s | commit:{landed} |\n"
    )
    dest = _archive_raw(tmp_path, work, row)
    assert _run_main(tmp_path, work, dest) == gl.EXIT_OK


# --------------------------------------------------------------------------- #
# WOT-2026-043t: a row with commit evidence but NO terminal state is invisible to
# the census -- it matches none of required/audited/skipped_required/skipped_legacy,
# so the guard exits 0 without ever having looked at it. Measured 2026-08-03 while
# archiving WOT-2026-040u: the SHA was written into the STATE cell and the row
# vanished, with the guard still printing ERROR=0.
# --------------------------------------------------------------------------- #
def test_043t_commit_evidence_without_terminal_state_is_surfaced():
    """A row whose SHA sits in the STATE cell (so it has no terminal state) must be
    reported in `malformed_evidence_tickets` instead of vanishing.

    Reachable mutation: drop the malformed-evidence branch (the pre-fix `continue`)
    -> the ticket disappears from every counter and this goes RED.
    """
    row = (
        "| Media | WOT-2026-0M1M | work deliverable_type: code | motor/x | "
        "commit:abc1234 | - | s | - |\n"
    )
    census = gl.census_archived(row)
    assert census["malformed_evidence_tickets"] == ["WOT-2026-0M1M"], (
        "a row carrying a commit cell but no terminal state must be surfaced, not "
        f"silently dropped; got {census}"
    )
    # It is genuinely invisible to the four ordinary counters -- that IS the defect.
    assert census["required"] == 0
    assert census["audited"] == 0
    assert census["skipped_required"] == 0
    assert census["skipped_legacy"] == 0


def test_043t_superseded_row_with_commit_is_not_malformed():
    """CONTROL NEGATIVO. `superseded` is a legitimate non-landing close, and the real
    archive holds such rows WITH a commit cell (WOT-2026-027b, WOT-2026-040j measured
    2026-08-03). Flagging them would make the detector cry wolf on its first real run.

    Reachable mutation: remove the `superseded` exclusion -> this goes RED.
    """
    row = (
        "| Alta | WOT-2026-0S2S | moved elsewhere deliverable_type: code | motor/x | "
        "superseded | WOT-2026-0T2T | s | commit:abc1234 |\n"
    )
    census = gl.census_archived(row)
    assert census["malformed_evidence_tickets"] == [], (
        f"a superseded row is a legitimate close, not malformed evidence; got {census}"
    )


def test_043t_malformed_evidence_makes_guard_exit_nonzero(tmp_path):
    """The census SEEING the row is not enough: the guard must FAIL on it, or the
    detector is a print statement. Asserted at the exit-code layer (main owns it).

    Reachable mutation: return EXIT_OK regardless of malformed_evidence_tickets ->
    this goes RED.
    """
    _origin, work = _make_repo(tmp_path)
    row = (
        "| Media | WOT-2026-0M2M | work deliverable_type: code | motor/x | "
        "commit:abc1234 | - | s | - |\n"
    )
    dest = _archive_raw(tmp_path, work, row)
    rc = _run_main(tmp_path, work, dest)
    assert rc == gl.EXIT_MALFORMED_EVIDENCE, (
        f"a row with unreadable commit evidence must fail the guard even with "
        f"ERROR=0; got exit {rc}"
    )


# --------------------------------------------------------------------------- #
# DoD-3: a plural `commits:sha1+sha2` row is AUDITED (each SHA), not skipped or
# counted as an offender. `"commits:x".startswith("commit:")` is False today.
# --------------------------------------------------------------------------- #
def test_dod3_plural_commits_prefix_is_audited_not_skipped():
    """DoD-3. Every SHA of a `commits:a+b` cell is emitted as a pair (audited), and the
    row counts toward `audited`, NOT `skipped_required`.

    Reachable mutation: revert recognition of the plural prefix (recognize only
    `commit:`) -> the plural row parses to zero pairs AND falls into skipped_required.
    This test asserts both halves, so that mutation goes RED.
    """
    pairs = gl.parse_archived_commits(_ROW_CODE_PLURAL)
    assert pairs == [
        ("WOT-2026-0P1P", "aaaaaaa"),
        ("WOT-2026-0P1P", "bbbbbbb"),
    ]
    census = gl.census_archived(_ROW_CODE_PLURAL + "\n")
    assert census["audited"] == 1
    assert census["skipped_required"] == 0


def test_dod3_startswith_singular_is_false_for_plural():
    """DoD-3, the exact defect pinned: the naive singular check rejects the plural
    cell, which is why the plural rows were skipped. Documents the trap the fix closes.
    """
    assert "commits:x".startswith("commit:") is False
    assert "commits:x".startswith(gl._COMMIT_CELL_PREFIXES) is True


# --------------------------------------------------------------------------- #
# DoD-4: requiredness keys on a FIXED SET of terminal states, not just "completed".
# No live `done`+code row exists, so this uses a FIXTURE (contract note).
# --------------------------------------------------------------------------- #
def test_dod4_done_state_code_row_is_required_not_fail_open():
    """DoD-4. A `done`+code row with no commit is REQUIRED (skipped_required), it does
    not escape through `!= 'completed'`.

    Reachable mutation: anchor requiredness to `== 'completed'` only -> the `done` row
    is invisible -> required and skipped_required drop to 0. This goes RED.
    """
    assert "done" in gl._TERMINAL_STATES  # the fixed set, not a state-machine
    census = gl.census_archived(_ROW_DONE_CODE_NO_COMMIT + "\n")
    assert census["required"] == 1
    assert census["skipped_required"] == 1
    assert census["skipped_required_tickets"] == ["WOT-2026-0D1D"]


def test_dod4_done_state_code_row_fails_the_guard_exit_code(tmp_path):
    """DoD-4 at the exit-code layer: a terminal-but-not-`completed` required row with
    no evidence must fail main(), proving the fail-open state is actually closed.
    """
    _origin, work = _make_repo(tmp_path)
    dest = _archive_raw(tmp_path, work, _ROW_DONE_CODE_NO_COMMIT + "\n")
    assert _run_main(tmp_path, work, dest) == gl.EXIT_SKIPPED_REQUIRED


# --------------------------------------------------------------------------- #
# DoD-5: a ticket-id appearing twice in terminal rows is detected, not silently
# double-counted (live dups: 019g/019h/019l/016e).
# --------------------------------------------------------------------------- #
def test_dod5_duplicate_ticket_ids_detected():
    """DoD-5. A ticket-id in two terminal rows is reported in duplicate_tickets.

    Reachable mutation: drop the Counter/uniqueness check (return no duplicate_tickets)
    -> this goes RED.
    """
    dup_a = (
        "| Media | WOT-2026-0DUP | first row deliverable_type: code | motor/x | "
        "completed | - | s | commit:aaaaaaa |"
    )
    dup_b = (
        "| Media | WOT-2026-0DUP | second row deliverable_type: code | motor/x | "
        "completed | - | s | commit:bbbbbbb |"
    )
    census = gl.census_archived("\n".join([dup_a, dup_b, _ROW_LEGACY]) + "\n")
    assert census["duplicate_tickets"] == {"WOT-2026-0DUP": 2}


# --------------------------------------------------------------------------- #
# DoD-6: a SHA appearing ONLY in prose (no commit:/commits: cell) is NOT evidence.
# --------------------------------------------------------------------------- #
def test_dod6_prose_sha_is_not_landing_evidence():
    """DoD-6. A row that cites a SHA only in its prose Titulo cell (no commit(s) cell)
    yields NO audit pairs and counts as skipped_required, never audited.

    Reachable mutation: accept a bare 7-40 hex token in prose as evidence -> the row
    would parse to a pair and move from skipped_required to audited. This goes RED.
    """
    prose_only = (
        "| Media | WOT-2026-0PRO | fix cites d33da49 in prose deliverable_type: code "
        "| motor/x | completed | - | s | reconciled:something |"
    )
    assert gl.parse_archived_commits(prose_only) == []
    census = gl.census_archived(prose_only + "\n")
    assert census["audited"] == 0
    assert census["skipped_required"] == 1
    assert census["skipped_required_tickets"] == ["WOT-2026-0PRO"]


# --------------------------------------------------------------------------- #
# NO-GOAL: the guard EXPOSES irrecoverable required rows, it does NOT invent
# evidence. A skipped_required row must never be reclassified as audited/OK.
# --------------------------------------------------------------------------- #
def test_no_goal_guard_exposes_but_never_fabricates_evidence():
    """The guard lists the required-without-evidence tickets and keeps them OUT of
    `audited`; it never synthesizes a commit for them.
    """
    census = gl.census_archived(_ROW_CODE_NO_COMMIT + "\n")
    assert census["audited"] == 0
    assert census["skipped_required"] == 1
    assert "WOT-2026-0S1S" in census["skipped_required_tickets"]
    # And no phantom pair is emitted for the evidence-less row.
    assert gl.parse_archived_commits(_ROW_CODE_NO_COMMIT) == []


# =========================================================================== #
# WOT-2026-026g -- EXECUTING contract test for the with/without-`commit:<sha>`
# criterion, driven over a SYNTHETIC GIT FIXTURE end to end (census_archived ->
# classify -> audit -> main exit code). This replaces prose-pinning (asserting
# a fragment is present in a .md file, which never runs the guard) with a test
# that actually EXECUTES the productive path in scripts/check_backlog_commits_
# landed.py against two sibling repos: one whose required row's sha genuinely
# landed, one whose sibling required row has no commit cell at all.
#
# EXPLICITLY OUT OF SCOPE (per WOT-2026-026g adjudication): the MANIFEST.
# distribute/workspace frontier-drift check pinned as prose in
# prompts/audit_pipeline_codeonly.md (WOT-2026-023y) has no executable
# implementation anywhere in the codebase; it is NOT touched or exercised here.
# =========================================================================== #
def test_026g_row_with_landed_commit_cell_is_audited_end_to_end(tmp_path):
    """A terminal code row WHOSE `commit:<sha>` cell really landed in
    origin/main is counted as `audited` by census_archived (no integrity
    violation for that row), AND main() exits EXIT_OK end to end.

    Reachable mutation: see test_026g_mut_dropping_commit_cell_gate_hides_the_skip
    below, which flips this same criterion's OTHER arm from RED to a false
    GREEN when the `has_commit` gate in census_archived is removed.
    """
    _origin, work = _make_repo(tmp_path)
    landed = _commit(work, "land.txt", "landed payload\n", "WOT-2026-026G1: lands")
    _g(["push", "-q", "origin", "main"], work)
    _g(["fetch", "-q", "origin"], work)

    row_with_commit = (
        f"| Media | WOT-2026-026G1 | landed work deliverable_type: code | motor/x | "
        f"completed | - | s | commit:{landed} |\n"
    )
    census = gl.census_archived(row_with_commit)
    assert census["required"] == 1
    assert census["audited"] == 1
    assert census["skipped_required"] == 0

    dest = _archive_raw(tmp_path, work, row_with_commit)
    rc = _run_main(tmp_path, work, dest)
    assert rc == gl.EXIT_OK, (
        f"a required row whose commit cell genuinely landed must exit OK; got {rc}"
    )


def test_026g_sibling_row_missing_commit_cell_is_exposed_end_to_end(tmp_path):
    """The SIBLING fixture: the same kind of required (terminal, code) row, but
    with NO `commit:<sha>` cell at all. census_archived must classify it as
    `skipped_required` (the silent-skip this guard exists to expose), and
    main() must NOT report a false EXIT_OK -- it must exit EXIT_SKIPPED_REQUIRED,
    listing the offending ticket.
    """
    _origin, work = _make_repo(tmp_path)

    row_without_commit = (
        "| Media | WOT-2026-026G2 | missing evidence deliverable_type: code | "
        "motor/x | completed | - | s | no-evidence-here |\n"
    )
    census = gl.census_archived(row_without_commit)
    assert census["required"] == 1
    assert census["audited"] == 0
    assert census["skipped_required"] == 1
    assert census["skipped_required_tickets"] == ["WOT-2026-026G2"]
    # And the parser never fabricates a pair for the evidence-less row.
    assert gl.parse_archived_commits(row_without_commit) == []

    dest = _archive_raw(tmp_path, work, row_without_commit)
    rc = _run_main(tmp_path, work, dest)
    assert rc == gl.EXIT_SKIPPED_REQUIRED, (
        f"a required row with no commit(s) cell must be EXPOSED (non-zero exit), "
        f"never silently reported as EXIT_OK; got {rc}"
    )


def test_026g_mut_dropping_commit_cell_gate_hides_the_skip():
    """MUTATION-VERIFY pair (manual, applied and reverted against production during
    this ticket's gates -- see execution_log.md / builder report for the two real
    exit codes). Documents in-repo, with teeth, exactly which branch the two tests
    above are isolating.

    MUTATION: in census_archived(), replace the `if has_commit: audited += 1 else:
    skipped_required += 1 ...` branch with an unconditional `audited += 1` (i.e.
    treat every required row as audited regardless of whether it carries a
    commit(s) cell). That single-branch mutation:
      - leaves test_026g_row_with_landed_commit_cell_is_audited_end_to_end GREEN
        (that row already has a commit cell, so the unconditional branch agrees).
      - flips test_026g_sibling_row_missing_commit_cell_is_exposed_end_to_end RED,
        because the row with NO commit cell would now also be counted as
        `audited` (skipped_required stays 0) and main() would report EXIT_OK
        instead of EXIT_SKIPPED_REQUIRED -- exactly the silent-skip false-green
        WOT-2026-024c/026g exist to prevent.

    This test itself re-asserts the un-mutated (correct) behaviour directly on
    the gate expression, so a naive `git diff` reviewer can see the isolated
    branch without re-deriving it from the two end-to-end tests above.
    """
    row_without_commit = (
        "| Media | WOT-2026-026G3 | isolates the has_commit gate "
        "deliverable_type: code | motor/x | completed | - | s | none |\n"
    )
    has_commit = gl._commit_cell(gl._row_cells(row_without_commit.strip())) is not None
    assert has_commit is False  # the exact condition the mutation would invert
    census = gl.census_archived(row_without_commit)
    assert census["skipped_required"] == 1, (
        "the has_commit gate in census_archived must route a commit-cell-less "
        "required row into skipped_required, not audited"
    )


# --------------------------------------------------------------------------- #
# WOT-2026-040s: una linea FISICA puede llevar VARIAS filas logicas fusionadas.
# El parser iteraba por linea fisica y tomaba el PRIMER ticket-ID de cada una,
# descartando el resto en silencio -> fail-open en el DENOMINADOR: el commit del
# 2o ticket nunca llegaba a audit(), luego no podia dar ERROR. Un guard que no
# mira no puede bloquear.
# --------------------------------------------------------------------------- #

_FUSED_A = (
    "| WOT-2026-111A | completed | fila A deliverable_type: code "
    "| motor/a | completed | - | s | commit:aaaaaaa |"
)
_FUSED_B = (
    "| WOT-2026-222B | completed | fila B deliverable_type: code "
    "| motor/b | completed | - | s | commit:bbbbbbb |"
)


def test_fused_physical_line_yields_every_logical_row():
    """Dos filas terminales en UNA linea fisica -> DOS pares, no uno.

    DoD-1/4a de WOT-2026-040s. Falla antes del fix (devuelve 1 par: el 2o
    ticket se pierde) y pasa despues. El control con '\n' prueba que el
    fixture es valido -- si el caso separado tambien fallara, el test estaria
    midiendo otra cosa.
    """
    separated = gl.parse_archived_commits(_FUSED_A + "\n" + _FUSED_B)
    assert separated == [("WOT-2026-111A", "aaaaaaa"), ("WOT-2026-222B", "bbbbbbb")], (
        "control: separadas por newline el parser ya funcionaba; si esto falla, "
        "el fixture no representa dos filas validas"
    )
    fused = gl.parse_archived_commits(_FUSED_A + _FUSED_B)
    assert fused == separated, (
        "una linea fisica con dos filas logicas debe emitir los MISMOS pares que "
        "las mismas dos filas separadas por newline: el 2o ticket no puede "
        "desaparecer del denominador (fail-open)"
    )


def test_fused_physical_line_does_not_shrink_the_census():
    """El DENOMINADOR declarado no puede encoger por una fusion de filas.

    DoD-4a. census_archived sangra por la MISMA causa que parse_archived_commits:
    reparar solo el parser dejaria el censo mintiendo, que es exactamente el
    fail-open que este ticket ataca. Hallazgo de la auditoria del contrato.
    """
    separated = gl.census_archived(_FUSED_A + "\n" + _FUSED_B)
    fused = gl.census_archived(_FUSED_A + _FUSED_B)
    assert fused == separated, (
        f"el censo de una linea fusionada debe igualar al de las filas "
        f"separadas; separadas={separated} fusionadas={fused}"
    )


def test_fused_row_fix_keeps_literal_pipe_in_titulo_working():
    """El fix NO puede reintroducir parsing posicional (STOP del contrato).

    La fila viva WOT-2026-021i lleva 'system|infra' en su Titulo -> 9 celdas.
    Por eso el ticket-ID se busca por REGEX y la celda de commit por PREFIJO,
    nunca por indice. Este test pinnea esa restriccion de diseño: si alguien
    arregla la fusion con cells[1], esta fila deja de parsear.
    """
    nine_cells = (
        "| WOT-2026-021I | completed | titulo con system|infra dentro "
        "deliverable_type: code | motor/x | completed | - | s | commit:ccccccc |"
    )
    assert gl.parse_archived_commits(nine_cells) == [("WOT-2026-021I", "ccccccc")], (
        "una fila con '|' literal en el Titulo debe seguir parseando: el fix de "
        "la fusion no puede volver al acceso posicional por indice"
    )


def test_empty_cell_is_not_mistaken_for_a_fused_row():
    """Un '||' que es CELDA VACIA no puede partir la fila (WOT-2026-040s).

    El '||' es ambiguo: cierre+apertura de dos filas fusionadas, o una celda
    vacia dentro de UNA fila legitima. El primer intento de fix partia por '||'
    a ciegas y devolvia [] para este caso -- cambiaba un fail-open por otro,
    perdiendo el ticket entero. Medido antes de escribir este test.

    La regla: solo se parte si el lado derecho ARRANCA una fila de verdad, o
    sea si lleva su propia celda de ticket-ID.
    """
    with_empty_cell = (
        "| WOT-2026-333C | completed | titulo || motor/x "
        "| completed | - | s | commit:ddddddd |"
    )
    assert gl.parse_archived_commits(with_empty_cell) == [
        ("WOT-2026-333C", "ddddddd")
    ], (
        "una fila con una celda vacia debe seguir parseando como UNA fila: "
        "partir por '||' a ciegas la destruye"
    )
    # y el caso fusionado de verdad sigue partiendose
    assert len(gl.parse_archived_commits(_FUSED_A + _FUSED_B)) == 2


def test_capa1_detail_names_the_ref_it_actually_checked(tmp_path):
    """El detail de CAPA 1 no puede decir 'origin/main' si comprobo OTRA ref.

    WOT-2026-040c DoD(b). ``classify`` recibe ``ref`` y lo usa en ``_is_ancestor``,
    pero el mensaje llevaba ``origin/main`` HARDCODEADO: con ``--ref HEAD`` afirmaba
    que un commit estaba en origin/main sin haberlo comprobado nunca. Un guard que
    reporta una ref que no midio da evidencia FALSA al operador -- y el operador
    cierra sobre esa evidencia.
    """
    work, *_ = _make_repo(tmp_path)
    head = _sha(work)
    # ref = HEAD: el sha ES ancestro de HEAD, luego cae en CAPA 1
    verdict, detail = gl.classify("WOT-2026-0REF", head, "HEAD", work, set())
    assert verdict == gl.OK
    assert "CAPA 1" in detail
    assert "origin/main" not in detail, (
        f"el detail nombra origin/main pero la ref comprobada fue HEAD: {detail!r}"
    )
    assert "HEAD" in detail, f"el detail debe nombrar la ref que comprobo: {detail!r}"


def test_capa2_detail_also_names_the_ref_it_actually_checked(tmp_path):
    """CAPA 2 lleva el MISMO label hardcodeado que CAPA 1 -- y su propia barrera.

    WOT-2026-040c DoD(b), hallazgo MAJOR de la manager-review: el fix toco CAPA 1 Y
    CAPA 2, pero solo CAPA 1 quedaba pinneada. Un mutante que revirtiera unicamente
    la CAPA 2 habria sobrevivido a la suite entera. Una barrera por rama tocada.
    """
    work, original, rebased = _rebased_pair(tmp_path)
    patch_ids = {gl._patch_id(rebased, work)}
    verdict, detail = gl.classify("WOT-2026-0RF2", original, "HEAD", work, patch_ids)
    assert verdict == gl.OK
    assert "CAPA 2" in detail
    assert "origin/main" not in detail, (
        f"CAPA 2 nombra origin/main pero comprobo HEAD: {detail!r}"
    )
    assert "HEAD" in detail, f"CAPA 2 debe nombrar la ref real: {detail!r}"


# --------------------------------------------------------------------------- #
# WOT-2026-055u: a legacy row (no deliverable_type) WITH a commit cell is
# auditable -> the census puts it in `audited`; a legacy row WITHOUT commit goes
# to the named counter `skipped_legacy_no_commit`, never to `skipped_legacy` and
# never to ERROR.
# --------------------------------------------------------------------------- #
def test_055u_legacy_row_with_commit_is_audited():
    """DoD (a): a terminal legacy row (no deliverable_type) with a VALID commit cell
    counts as `audited`, not `skipped_legacy_no_commit` and not `skipped_legacy`.

    Reachable mutation: revert the `if has_commit: audited += 1` branch back to the
    pre-055u `skipped_legacy += 1` -> audited drops to 0 and this goes RED.
    """
    census = gl.census_archived(_ROW_LEGACY_WITH_COMMIT + "\n")
    assert census["audited"] == 1, f"legacy evidence must be audited: {census}"
    assert census["skipped_legacy_no_commit"] == 0, f"{census}"
    assert census["skipped_legacy"] == 0, f"{census}"


def test_055u_legacy_row_without_commit_has_named_counter():
    """DoD (b): a legacy row with NO commit goes to the NAMED counter
    `skipped_legacy_no_commit` -- declared debt, not ERROR, and not skipped.

    Reachable mutation: delete the counter -> `skipped_legacy_no_commit` missing
    (KeyError) or dropped to 0 while the row vanishes -> RED.
    """
    census = gl.census_archived(_ROW_LEGACY + "\n")
    assert census["skipped_legacy_no_commit"] == 1, f"{census}"
    assert census["audited"] == 0, f"{census}"
    assert census["skipped_required"] == 0, f"{census}"


def test_055u_legacy_row_with_commit_parse_pairs():
    """A legacy-with-commit row must reach `parse_archived_commits` too: its sha still
    gets audited against origin/main (the evidence exists regardless of dtype label).
    """
    pairs = gl.parse_archived_commits(_ROW_LEGACY_WITH_COMMIT)
    assert pairs == [("WOT-2026-0L2L", "0abc123")], f"{pairs}"
