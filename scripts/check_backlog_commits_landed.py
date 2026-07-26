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

PREMISA REFUTADA, declarada explicitamente (022x): el prompt de arranque de la cadena
pedia "SHA inexistente -> ERROR". Se implemento WARN, que es el contrato PREEXISTENTE
de 021o y el correcto. Razon, verificada contra datos vivos: el repo sufrio un
history-rewrite legitimo (filter-repo, 020u) que dejo SHAs archivados sin objeto pero
cuyo ticket SI aterrizo bajo un SHA nuevo -- hoy son 7 filas OK_BY_SUBJECT. Poner en
ERROR el caso "sin objeto" convertiria en fallo el trabajo legitimamente republicado y
bloquearia el guard entero. El discriminante que importa NO es "existe el objeto" sino
"es alcanzable desde la rama": un SHA sin objeto no puede ser un cierre perdido porque
no hay nada que perder; un objeto huerfano SI. El delta con el arranque es deliberado y
se registra aqui para que no pase en silencio (CEM: un cambio de contrato no declarado
es indistinguible de un descuido).

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
    0 = all audited SHAs OK / OK_BY_SUBJECT / WARN (no lost close) AND the denominator
        is clean (skipped_required == 0).
    1 = collector self-failure (backlog unparseable, git missing, etc.).
    2 = argument / topology error (bad --motor-root / --git-repo).
    3 = degraded topology (backlog link unresolved).
    4 = VERDICT: at least one SHA is ERROR (a recorded close did not land).
    5 = DENOMINATOR: at least one REQUIRED row (terminal + code/mixed) carries NO
        commit evidence -- skipped_required > 0 (WOT-2026-024c). ERROR=0 is only a
        legitimate exit 0 when the guard actually audited its whole denominator; a row
        it silently skipped is exposed here, never invented into evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path


SCHEMA_VERSION = "backlog-commits-landed-guard/v1"

# Exit codes (0/1/2/3 mirror backlog_reconcile.py; 4 is the dedicated verdict-ERROR).
EXIT_OK = 0
EXIT_SELF_FAIL = 1
EXIT_ARG = 2
EXIT_DEGRADED = 3
EXIT_VERDICT_ERROR = 4
# WOT-2026-024c DoD-2: a required row with no commit evidence was silently skipped.
# ERROR=0 is not enough for exit 0 -- the denominator must be clean too.
EXIT_SKIPPED_REQUIRED = 5

# Verdicts (per-SHA).
OK = "OK"
OK_BY_SUBJECT = "OK_BY_SUBJECT"
# Committed and on the local branch, but not yet pushed (grouped-push policy, 022u).
# Non-blocking: it is the expected state between a ticket's commit and the session's
# grouped push. NOT a lost close.
PENDING_GROUPED_PUSH = "PENDING_GROUPED_PUSH"
ERROR = "ERROR"
WARN = "WARN"

# Only closed rows carrying a commit token are auditED, but the DENOMINATOR (which
# rows OUGHT to carry one) keys on the full set of terminal states, not just
# "completed". WOT-2026-024c: anchoring requiredness to == "completed" alone is
# FAIL-OPEN -- a `done`/`completed-partial` row of type code/mixed without a commit
# cell would be invisible. The set is FIXED (a frozenset membership check), NOT a
# state-machine parser: the whole fix is this closed enumeration.
_COMPLETED_STATE = "completed"
_TERMINAL_STATES = frozenset(
    {"completed", "done", "completed-partial", "completed-via-010n"}
)
# Evidence cell: singular `commit:` OR plural `commits:`. WOT-2026-024c P3: a
# `commits:sha1+sha2` cell fails `.startswith("commit:")` (position 6 is 's', not
# ':'), so the plural rows -- SHAs VALID -- were silently skipped. Both prefixes are
# recognized here; the SHA-group split on `+` is unchanged.
_COMMIT_PREFIX = "commit:"
_COMMITS_PREFIX = "commits:"
_COMMIT_CELL_PREFIXES = (_COMMIT_PREFIX, _COMMITS_PREFIX)
# Ticket-ID shape: WOT-2026-021o / WT-2026-250c / WP-2026-... (prefix-YYYY-suffix).
_TICKET_ID_RE = re.compile(r"^(?:WOT|WP|WT|CTL)-\d{4}-[0-9a-z]+$", re.IGNORECASE)
# deliverable_type lives as a SUBSTRING inside the row's prose Titulo/comment cell
# (e.g. `... deliverable_type: code | ...`), NOT as a discrete column. A positional
# cell read returns 0 (wrong); the substring returns the real set. WOT-2026-024c.
_DELIVERABLE_TYPE_RE = re.compile(
    r"deliverable_type[:\s]+\**\s*(code|mixed|documentation|research|analysis)"
)
# The deliverable types whose rows REQUIRE landing evidence (a commit/commits cell).
_LANDING_REQUIRED_TYPES = frozenset({"code", "mixed"})
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


def _row_cells(line: str) -> list[str] | None:
    """Split a markdown table ROW into stripped cells, or None if it is not a row."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    return [c.strip() for c in stripped.strip("|").split("|")]


def _logical_rows(content: str) -> list[list[str]]:
    """Yield the cells of every LOGICAL row, splitting fused physical lines.

    WOT-2026-040s. A physical line can carry SEVERAL logical rows glued together
    (``...commit:aaa || WOT-2026-222B | completed |...``) -- markdown degrades that
    way when rows are edited or merged. The old readers iterated ``splitlines()``
    and took the FIRST ticket-ID per physical line, discarding the rest in silence:
    the second ticket never reached ``audit()``, so it could never raise ERROR. That
    is fail-open in the DENOMINATOR -- the worst failure class for a guard whose job
    is to block.

    The split key is the ``|`` that CLOSES a row abutting the ``|`` that OPENS the
    next one. Splitting on the cell boundary (not on a cell count) is what keeps the
    ``system|infra`` row working: a literal pipe inside a Titulo yields 9 cells, and
    this function never assumes a width. Consumers keep locating the ticket-ID by
    REGEX and the evidence cell by PREFIX -- never by index (STOP of the contract).

    Before: ``content`` is the archive text; may be empty.
    During: pure string work -- no I/O, no git.
    After: returns one cell-list per logical row, in document order. A physical line
    holding N fused rows yields N entries, so ``len()`` is a faithful denominator.
    Never raises.
    """
    rows: list[list[str]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        # A ``||`` is AMBIGUOUS: it can be row-close + row-open (a fused line), or a
        # single EMPTY CELL inside one legitimate row (``| a || b |``). Splitting on
        # it blindly destroys the empty-cell row -- trading one fail-open for another
        # (measured: the naive split returned [] for such a row, losing the ticket
        # entirely). So we split ONLY when the right-hand side actually starts a new
        # row: it must carry its own ticket-ID cell. Anything else stays as one row
        # and reaches _row_cells untouched.
        for chunk in _split_fused(stripped):
            cells = _row_cells(chunk)
            if cells:
                rows.append(cells)
    return rows


def _split_fused(stripped: str) -> list[str]:
    """Split a physical line into row-shaped chunks, conservatively (WOT-2026-040s).

    Before: ``stripped`` is a line already known to start with ``|``.
    During: scans each ``||`` boundary and cuts ONLY if the remainder parses as a row
        that owns a ticket-ID -- the signature of a genuinely fused row. A ``||`` that
        is merely an empty cell leaves the line intact.
    After: returns >=1 chunks, each starting with ``|``. Never raises. When in doubt it
        does NOT split: a missed split keeps today's behavior, while a wrong split would
        silently drop a real row.
    """
    # Collect the cut offsets in ONE forward pass, then slice. An earlier version
    # looped with a mutable ``rest`` and rebuilt it as ``"|" + rest[...]``, which
    # re-created the very ``||`` it had just consumed -> the string never shrank and
    # the loop spun forever (caught by a 124-timeout, not by review). A single pass
    # over fixed offsets cannot fail to terminate.
    cuts: list[tuple[int, int]] = []
    for m in re.finditer(r"\|\s*\|", stripped):
        candidate = "|" + stripped[m.end() - 1 :]
        cells = _row_cells(candidate)
        if cells and any(_TICKET_ID_RE.match(c) for c in cells):
            cuts.append((m.start(), m.end()))
    if not cuts:
        return [stripped]
    chunks: list[str] = []
    prev_end = 0
    for start, end in cuts:
        piece = stripped[prev_end:start] + "|"
        chunks.append(piece if piece.startswith("|") else "|" + piece)
        prev_end = end - 1
    tail = stripped[prev_end:]
    chunks.append(tail if tail.startswith("|") else "|" + tail)
    return chunks


def _commit_cell(cells: list[str]) -> str | None:
    """The evidence cell of a row: the first cell starting with ``commit:``/``commits:``.

    WOT-2026-024c P3: BOTH the singular and the plural prefix count as evidence. The
    old ``.startswith("commit:")`` silently rejected ``commits:...`` (its 7th char is
    's', not ':'), skipping valid-SHA plural rows.
    """
    return next(
        (c for c in cells if c.startswith(_COMMIT_CELL_PREFIXES)),
        None,
    )


def _shas_from_commit_cell(commit_cell: str) -> list[str]:
    """Split a ``commit:``/``commits:`` cell into its individual SHAs (grouped by ``+``).

    Strips whichever prefix is present, then splits the LITERAL ``+`` group so every
    SHA is emitted (never collapse ``sha1+sha2`` to its first member).
    """
    for prefix in _COMMIT_CELL_PREFIXES:
        if commit_cell.startswith(prefix):
            token = commit_cell[len(prefix) :].strip()
            break
    else:
        token = commit_cell.strip()
    return [sha.strip() for sha in token.split("+") if sha.strip()]


def parse_archived_commits(content: str) -> list[tuple[str, str]]:
    """Extract (ticket_id, sha) pairs from terminal rows carrying a commit token.

    Robust to a literal ``|`` inside the Titulo cell (e.g. the live WOT-2026-021i row
    embeds ``system|infra`` -> 9 cells, not 8): the ticket-ID is the first cell whose
    text matches _TICKET_ID_RE, and the commit token is the cell that starts with
    ``commit:`` OR ``commits:`` (WOT-2026-024c P3: the plural prefix is now recognized
    so its valid SHAs are audited, not skipped). The token groups several SHAs with a
    LITERAL ``+`` (``commit:sha1+sha2+sha3``); EVERY SHA is emitted as its own pair so
    each is audited (never collapse a group to its first member). A row is audited only
    if it has both a terminal-state cell and a commit(s) cell.
    """
    pairs: list[tuple[str, str]] = []
    for cells in _logical_rows(content):
        if not any(c in _TERMINAL_STATES for c in cells):
            continue
        ticket_id = next((c for c in cells if _TICKET_ID_RE.match(c)), None)
        commit_cell = _commit_cell(cells)
        if not ticket_id or not commit_cell:
            continue
        pairs.extend((ticket_id, sha) for sha in _shas_from_commit_cell(commit_cell))
    return pairs


def census_archived(content: str) -> dict:
    """Compute the guard's DENOMINATOR over the archive (WOT-2026-024c, DoD-1/5).

    Before this, the guard reported ``audited = len(results)`` and never asked how many
    rows it OUGHT to have audited: ``ERROR=0`` meant "of what I looked at, nothing
    failed", not "everything landed". This walks every markdown ROW once and classifies
    the TERMINAL rows (state in ``_TERMINAL_STATES``, DoD-4: NOT just "completed") that
    carry a ticket-ID:

      - ``required``         : deliverable_type in {code, mixed} (landing REQUIRED).
      - ``audited``          : required rows that DO carry a commit(s) cell.
      - ``skipped_required`` : required rows with NO commit(s) cell -> the silent skip
                               this ticket exists to expose (their tickets are listed).
      - ``skipped_legacy``   : terminal rows with NO deliverable_type at all (exempt).

    deliverable_type is read as a SUBSTRING of the whole row text (DoD-1 surface fix),
    never as a positional column. Duplicate ticket-ids across terminal rows are counted
    (DoD-5): a ticket appearing twice is reported, never silently double-counted.

    Returns a dict with the four counts, the sorted list of skipped-required ticket-ids
    (``skipped_required_tickets``), and the map of duplicate ticket-ids
    (``duplicate_tickets``: id -> count). Pure string parsing; touches no git and no disk.
    """
    required = audited = skipped_required = skipped_legacy = 0
    skipped_required_tickets: list[str] = []
    terminal_ids: list[str] = []
    for cells in _logical_rows(content):
        if not any(c in _TERMINAL_STATES for c in cells):
            continue
        ticket_id = next((c for c in cells if _TICKET_ID_RE.match(c)), None)
        if not ticket_id:
            continue
        terminal_ids.append(ticket_id)
        # WOT-2026-040s: search THIS logical row, not the whole physical line.
        # On a fused line the old ``search(line)`` could read the neighbour's
        # ``deliverable_type`` and classify a row by someone else's evidence.
        match = _DELIVERABLE_TYPE_RE.search(" | ".join(cells))
        dtype = match.group(1) if match else None
        has_commit = _commit_cell(cells) is not None
        if dtype in _LANDING_REQUIRED_TYPES:
            required += 1
            if has_commit:
                audited += 1
            else:
                skipped_required += 1
                skipped_required_tickets.append(ticket_id)
        elif dtype is None:
            skipped_legacy += 1
    duplicate_tickets = {tid: n for tid, n in Counter(terminal_ids).items() if n > 1}
    return {
        "required": required,
        "audited": audited,
        "skipped_required": skipped_required,
        "skipped_legacy": skipped_legacy,
        "skipped_required_tickets": sorted(skipped_required_tickets),
        "duplicate_tickets": duplicate_tickets,
    }


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

    Precedence is load-bearing, and WOT-2026-023q corrected it. A FACT about the SHA
    recorded in the row always beats a CONVENTION about the ticket's ID:

      CAPA 1/2  the SHA itself landed (ancestor / patch-id)          -> OK
      PENDING   the SHA still EXISTS and is reachable from the local
                branch -> it is committed and simply NOT PUSHED YET  -> PENDING
      CAPA 3    the SHA is GONE (or was superseded) but the ID shows
                up in an origin/main subject                          -> OK_BY_SUBJECT

    CAPA 3 used to run BEFORE the PENDING check, and that was a false-green: a commit
    that had never left the machine got blessed because a SIBLING commit of the same
    ticket (a contract edit, say) had landed and carried the ID in its subject. The
    grouped-push policy GUARANTEES such rows exist in every session, so the guard was
    reporting ERROR=0 over work that only existed locally. Reproduced deterministically
    (scripts/probe_landed_guard_unpushed.py).

    CAPA 3 still runs BEFORE the no-object WARN and before the ERROR: it exists for
    SHAs whose OBJECT IS GONE (the 016e/016h history-rewrite case) or that were
    superseded on another branch (squash-merge) -- neither is reachable from HEAD, so
    hoisting PENDING above it does not touch them.
    """
    if _is_ancestor(sha, ref, repo):
        return OK, "ancestor of origin/main (CAPA 1)"
    pid = _patch_id(sha, repo)
    if pid and pid in patch_ids:
        return OK, "patch-id present in origin/main (CAPA 2, rebase)"
    # WOT-2026-023q: this MUST precede CAPA 3. The object existing AND being reachable
    # from the local branch is a fact about THIS repo; the ID appearing in some subject
    # is a convention about SOME commit. The fact wins.
    if _has_object(sha, repo) and _is_ancestor(sha, "HEAD", repo):
        # WOT-2026-022x. Committed but not pushed YET (grouped-push policy, 022u).
        # Never fail-open: the UNREACHABLE case below stays ERROR (a lost close).
        return (
            PENDING_GROUPED_PUSH,
            "committed and reachable from the local branch, but not in "
            f"{ref} -- pending the session's grouped push (not a lost close)",
        )
    if _landed_by_subject(ticket_id, ref, repo):
        return (
            OK_BY_SUBJECT,
            "ticket-ID in an origin/main subject (CAPA 3, squash/cherry-pick)",
        )
    if _has_object(sha, repo):
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


def _print_text_report(
    results: list[dict], counts: dict, census: dict, ref: str
) -> None:
    """Human-readable report: the audit counts, the PUBLISHED denominator (DoD-1), the
    per-SHA non-OK verdicts, the required-without-evidence tickets (DoD-2), and the
    duplicate ticket-ids (DoD-5). Pure stdout; the exit decision stays in main()."""
    print(f"[landed] audited {len(results)} commit(s) against {ref}")
    # DoD-1: the denominator is now PUBLISHED, not implicit.
    print(
        f"[landed] required={census['required']} audited={census['audited']} "
        f"skipped_required={census['skipped_required']} "
        f"skipped_legacy={census['skipped_legacy']}"
    )
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
    # DoD-2: list the required tickets that carry NO landing evidence.
    for tid in census["skipped_required_tickets"]:
        print(
            f"[landed]   SKIPPED_REQUIRED: {tid} -- terminal code/mixed row with no "
            "commit(s) evidence (landing UNVERIFIED; needs human decision)"
        )
    # DoD-5: report ticket-ids that appear in more than one terminal row.
    for tid, n in sorted(census["duplicate_tickets"].items()):
        print(f"[landed]   DUPLICATE: {tid} appears in {n} terminal rows")


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

    # WOT-2026-024c: compute the DENOMINATOR before auditing. `census` answers "how
    # many rows OUGHT to carry landing evidence", so ERROR=0 can be told apart from
    # "I skipped the rows that would have failed".
    census = census_archived(content)
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
            "census": census,
            "counts": counts,
            "results": results,
        }
        print(_relativize(json.dumps(payload, indent=2, ensure_ascii=False), roots))
    else:
        _print_text_report(results, counts, census, args.ref)

    if errors:
        print(
            f"[landed] FAIL: {len(errors)} recorded close(s) did NOT land in {args.ref}",
            file=sys.stderr,
        )
        return EXIT_VERDICT_ERROR
    # DoD-2: ERROR=0 is a legitimate exit 0 ONLY if the denominator is clean. A row the
    # guard silently skipped (required, no evidence) makes exit 0 a false green.
    if census["skipped_required"] > 0:
        print(
            f"[landed] FAIL: {census['skipped_required']} required row(s) "
            f"(terminal + code/mixed) carry NO commit evidence -- the guard cannot "
            f"confirm they landed. Tickets: {', '.join(census['skipped_required_tickets'])}",
            file=sys.stderr,
        )
        return EXIT_SKIPPED_REQUIRED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
