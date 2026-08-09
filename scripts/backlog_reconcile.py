#!/usr/bin/env python3
"""Collect read-only git signals for backlog reconciliation (collector, NOT judge).

WOT-2026-021i: automates "Fase 0 (Reconciliacion)" of /backlog-triage
(prompts/backlog_triage.md). For each LIVE backlog ticket it gathers raw git
signals with evidence and emits them as [RELATO]; the AGENT judges
LIKELY_DONE / LIKELY_PENDING / NEEDS_HUMAN_VERIFY. This script NEVER classifies.

Before:
    - A valid repo_motor path (must contain MANIFEST.distribute).
    - A repo_destino / workspace whose backlog is reconciled, resolved either via
      --project-root or via the workspace's motor_destination_link.json.

During:
    - Parses the "## Vista rapida" table of the backlog (reusing the same
      extraction contract as scripts/check_backlog_contract.py). For each row whose
      Estado is pending/deferred/completed-partial, emits three raw signal families
      run against the repo chosen BY SCOPE (motor/* -> motor; destinos/* -> destino;
      system|infra/* -> n/a, no forced grep):
        1. git log --all --fixed-strings --grep <TICKET_ID>  (closing commits)
        2. git ls-files <path> + git status --short <path>   (scope-file presence)
        3. git grep -n -i <term>                              (DoD-term hits; -i!)
    - Emits ONE repo-level last-run block per repo (motor + destino), NOT per ticket:
      last-run.json is per-repo (no ticket field), so a per-ticket copy would be
      misleading. `stale` compares tested_commit_sha against THAT repo's HEAD only.
    - Never mutates anything. Never emits a verdict/classification/evidence_label.

After:
    - Output dir is immutable (refuses to overwrite; appends _NN if needed).
    - Exit codes:
        0 = collection OK.
        1 = collector self-failure (backlog unparseable, etc.) -- NEVER ticket-level.
        2 = argument/topology error (bad --motor-root).
        3 = degraded topology (backlog link unresolved) when a full run was required.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "backlog-reconcile-collector/v0"

# Live-queue statuses that enter reconciliation (mirror backlog_triage.md l.65 and
# check_backlog_contract LIVE_STATES; terminal states never appear in the table).
RECONCILE_STATES = ("pending", "deferred", "completed-partial")

_VISTA_RAPIDA_HEADER = "## Vista rapida"
# 0-based cell indices after splitting a row on '|' (parity with
# check_backlog_contract._TABLE_HEADER_COLS / validate_backlog l.176,180).
_COL_TICKET = 1
_COL_TITULO = 2
_COL_SCOPE = 3
_COL_STATUS = 4
_COL_DEPENDS = 5
_EXPECTED_COLS = 8

# Harvest file paths / file:line cites and backticked identifiers from opaque text.
# Anchored, no nested unbounded quantifier -> no catastrophic backtracking.
_PATH_RE = re.compile(r"[\w./-]+\.py(?::\d+(?:-\d+)?)?")
_IDENT_RE = re.compile(r"`([^`]{2,60})`")

# WOT-2026-041f cross (e): an "accepted" marker inside a DEC line. Kept broad on
# purpose -- a MISSED signal is worse than a noisy one, because the agent reviews
# every signal but never sees the ones we filtered away.
_DEC_ACCEPTED_RE = re.compile(r"\baccept(?:ed|ada|ado)\b", re.IGNORECASE)
# WOT-2026-041f cross (f): ticket-IDs inside a free-text "Depende de" cell, which
# may hold several ("WOT-2026-027c, WOT-2026-026j") or a literal "-".
_TICKET_ID_IN_CELL_RE = re.compile(
    r"\b(?:WOT|WP|WT|CTL)-\d{4}-[0-9a-z]+\b", re.IGNORECASE
)
# Live statuses that carry a blocker worth cross-checking (cross (f)). Distinct
# from RECONCILE_STATES: 'blocked' rows do NOT enter reconciliation, but their
# blocker is still checked against the live queue.
_BLOCKED_STATE = "blocked"

# Cap of grep lines kept per term in the gitignored raw/ dump (the full count still
# goes to findings; a broad term can otherwise match thousands of lines).
_RAW_LINES_PER_TERM = 50


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> dict:
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


def _git_head(repo: Path) -> str | None:
    res = _run(["git", "rev-parse", "HEAD"], repo)
    if res["exit_code"] == 0:
        return res["stdout"].strip()
    return None


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


def _unique_out_dir(base: Path) -> Path:
    """Return an immutable output dir; never overwrite an existing one."""
    if not base.exists():
        return base
    for n in range(1, 100):
        cand = base.parent / f"{base.name}_{n:02d}"
        if not cand.exists():
            return cand
    raise RuntimeError(f"too many existing reconcile dirs for {base}")


def _resolve_destino_root(
    project_root: str | None, workspace_root: str | None
) -> tuple[Path | None, str | None]:
    """Resolve the repo_destino whose backlog is reconciled.

    Precedence: (1) --project-root used verbatim (the destino/backlog owner); else
    (2) resolve the workspace's motor_destination_link.json ``destination_root``
    (--workspace-root points at where the link lives). The link is
    machine-specific/gitignored, so resolve it at runtime; absence/unresolvability
    returns (None, reason) so the caller can degrade (exit 3), never crash.
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


def _read_last_run(repo: Path) -> dict:
    """Read a repo's canonical last-run.json and flag staleness vs THAT repo's HEAD.

    Repo-level (last-run.json has no ticket field). `stale` uses truthiness so a
    missing tested_commit_sha or HEAD collapses to not-stale (indeterminate != stale).
    Never cross-repo (the 021c/021n axis lesson).
    """
    p = repo / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
    if not p.exists():
        return {"present": False}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"present": False, "error": str(exc)}
    tested_sha = d.get("tested_commit_sha")
    head = _git_head(repo)
    return {
        "present": True,
        "exit_code": d.get("exit_code"),
        "finished_at": d.get("finished_at"),
        "tested_commit_sha": tested_sha,
        "head": head,
        "stale": bool(tested_sha and head and tested_sha != head),
        "failed_test_ids": d.get("failed_test_ids", []),
        "error_test_ids": d.get("error_test_ids", []),
    }


def _extract_vista_rapida_rows(content: str) -> tuple[list[list[str]], str | None]:
    """Return the 8-cell data rows under '## Vista rapida' (parity with the contract).

    Reads ONLY that table; stops at the next blank line or '## ' header; the '>'
    blockquote after the table terminates the loop (only '|' lines are rows).
    """
    lines = content.splitlines()
    try:
        start = next(
            i for i, ln in enumerate(lines) if ln.strip() == _VISTA_RAPIDA_HEADER
        )
    except StopIteration:
        return [], f"missing '{_VISTA_RAPIDA_HEADER}' section"
    header_idx = None
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("| Prioridad"):
            header_idx = i
            break
    if header_idx is None:
        return [], "no table header found under 'Vista rapida'"
    rows: list[list[str]] = []
    for i in range(header_idx + 2, len(lines)):  # +2 skips the |---| separator
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("## "):
            break
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            rows.append(cells)
    return rows, None


def _scope_repo(
    scope_slug: str, motor_root: Path, dest_root: Path | None
) -> tuple[str, Path | None]:
    """Route a ticket's git signals to the repo that OWNS its code, by scope prefix.

    motor/* -> motor; destinos/* (or a bare destino) -> the destino; system|infra/*
    -> n/a (no forced grep; the agent judges without a repo signal). Returns
    (label, repo_path_or_None).
    """
    prefix = scope_slug.split("/", 1)[0].strip().lower() if scope_slug else ""
    if prefix == "motor":
        return "motor", motor_root
    if prefix in ("destinos", "destino"):
        return "destino", dest_root
    return "n/a", None


def _harvest_terms(
    ticket_id: str, scope_slug: str, titulo: str, ficha_body: str
) -> list[str]:
    """Derive DoD/scope search terms from the row + ficha (opaque text, split-safe).

    The scope PREFIX (before the first '/', e.g. 'motor'/'destinos'/'system') is
    dropped -- it is the routing axis, generic to every ticket in that area, and a
    `git grep` for it is huge and useless. Of the remaining slug tokens, those
    shorter than 5 chars (e.g. 'skip', 'gate', 'not') are dropped too. File paths
    and backticked identifiers harvested from the titulo/ficha are specific and kept
    regardless of length.
    """
    terms: set[str] = set()
    slug_tail = scope_slug.split("/", 1)[1] if "/" in scope_slug else ""
    for token in re.split(r"[-_]", slug_tail):
        token = token.strip()
        if len(token) >= 5:
            terms.add(token)
    for text in (titulo, ficha_body):
        for m in _PATH_RE.findall(text):
            terms.add(m)
        for m in _IDENT_RE.findall(text):
            terms.add(m.strip())
    terms.discard(ticket_id)  # the ID is Signal 1 (git log --grep), not a grep term
    return sorted(t for t in terms if t)


def _harvest_paths(titulo: str, ficha_body: str) -> list[str]:
    """Scope-file candidates: file paths (strip any :line suffix) from row + ficha."""
    paths: set[str] = set()
    for text in (titulo, ficha_body):
        for m in _PATH_RE.findall(text):
            paths.add(m.split(":", 1)[0])
    return sorted(paths)


def _ficha_body_for(content: str, ticket_id: str) -> str:
    """Return the '### <ticket_id> ...' ficha body (up to the next '### '), or ''."""
    lines = content.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("### ") and ticket_id in ln:
            start = i + 1
            break
    if start is None:
        return ""
    body: list[str] = []
    for ln in lines[start:]:
        if ln.startswith("### "):
            break
        body.append(ln)
    return "\n".join(body)


def _signal_commits(ticket_id: str, repo: Path) -> list[dict]:
    """git log --all --fixed-strings --grep <ID>: commits mentioning the ticket."""
    res = _run(
        [
            "git",
            "log",
            "--all",
            "--fixed-strings",
            f"--grep={ticket_id}",
            "--pretty=%H%x1f%s%x1f%ad",
            "--date=short",
        ],
        repo,
    )
    out: list[dict] = []
    if res["exit_code"] == 0 and res["stdout"].strip():
        for line in res["stdout"].splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3:
                out.append(
                    {"sha": parts[0][:12], "subject": parts[1], "date": parts[2]}
                )
    return out


def _signal_paths(paths: list[str], repo: Path) -> list[dict]:
    """git ls-files + git status --short per scope path (AS WRITTEN; 020s lesson)."""
    out: list[dict] = []
    for path in paths:
        ls = _run(["git", "ls-files", path], repo)
        tracked = bool(ls["exit_code"] == 0 and ls["stdout"].strip())
        st = _run(["git", "status", "--short", path], repo)
        status = st["stdout"].strip() if st["exit_code"] == 0 else None
        out.append(
            {
                "path": path,
                "tracked": tracked,
                "present": (repo / path).exists(),
                "status": status or "",
            }
        )
    return out


def _signal_grep(terms: list[str], repo: Path, raw_sink: list[str]) -> list[dict]:
    """git grep -n -i <term>: case-INSENSITIVE (021d lesson).

    Emits only the HIT COUNT into the versioned findings -- the matched lines are
    third-party file contents that routinely embed absolute paths / other repos'
    text, so dumping them into the (versioned) findings.json would leak PII and add
    noise. The full lines go to the gitignored ``raw/`` sink instead.
    """
    out: list[dict] = []
    for term in terms:
        res = _run(["git", "grep", "-n", "-i", "--", term], repo)
        lines = res["stdout"].splitlines() if res["exit_code"] == 0 else []
        if lines:
            # The findings carry the FULL hit count; the raw dump keeps only a
            # sample (a broad term can match thousands of lines -- unbounded dumps
            # bloat raw/ for no added signal, since the agent reads the count).
            sample = lines[:_RAW_LINES_PER_TERM]
            omitted = len(lines) - len(sample)
            header = f"# git grep -i '{term}' ({len(lines)} hits"
            header += f", showing first {len(sample)})" if omitted else ")"
            raw_sink.append(header + "\n" + "\n".join(sample))
        out.append({"term": term, "hits": len(lines)})
    return out


def _signal_dec_accepted(ticket_id: str, dest_root: Path) -> list[dict]:
    """WOT-2026-041f cross (e): DEC records that mention this ticket as accepted.

    A ticket still sitting in a LIVE state while a DEC declares its decision
    accepted is a DIVERGENCE worth surfacing -- but it is NOT a verdict. Several
    innocent readings exist (the DEC accepted a design, not the implementation;
    the row covers work beyond the DEC). The agent decides; this only reports
    WHERE to look.

    Before: ``dest_root`` may or may not hold a ``decisions`` tree; a missing
    tree is a silent empty signal, never an error.
    During: reads ``*.md`` under the DEC dir, matching the ticket-ID and an
    accepted marker in the SAME file. Read-only.
    After: a list of ``{path, line, text}`` evidence records (possibly empty).
    Never raises: unreadable files are skipped.
    """
    signals: list[dict] = []
    dec_dir = dest_root / "orchestrator_pipeline" / "decisions"
    if not dec_dir.is_dir():
        return signals
    try:
        candidates = sorted(dec_dir.rglob("*.md"))
    except OSError:
        return signals
    for dec in candidates:
        try:
            text = dec.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        if ticket_id not in text:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if ticket_id in line and _DEC_ACCEPTED_RE.search(line):
                signals.append(
                    {"path": dec.name, "line": idx, "text": line.strip()[:200]}
                )
    return signals


def _signal_blocker_offqueue(depends_cell: str, live_ids: frozenset[str]) -> list[dict]:
    """WOT-2026-041f cross (f): blockers that are NOT in the live queue.

    A ``blocked`` row whose blocker is absent from the live table is a
    divergence: the blocker may have been archived (so the row is unblocked and
    nobody noticed) or it may be a typo / a ticket that never existed. Those
    readings are OPPOSITE in consequence, so this emits the raw fact and lets
    the agent resolve it -- it never says "unblock this".

    Before: ``depends_cell`` is the raw "Depende de" cell; ``live_ids`` are the
    ticket-IDs present in the live table.
    During: pure string work, no I/O.
    After: one record per blocker-ID not found among ``live_ids``. ``-`` and
    empty cells yield nothing (no blocker declared is not a divergence).
    """
    return [
        {"blocker": blocker, "present_in_live_queue": False}
        for blocker in _TICKET_ID_IN_CELL_RE.findall(depends_cell or "")
        if blocker not in live_ids
    ]


def _collect_all(
    rows: list[list[str]], content: str, motor_root: Path, dest_root: Path
) -> tuple[list[dict], list[str], list[str], list[dict]]:
    """Build per-ticket signal records for every row in the reconcile set.

    Returns (tickets, warnings, raw_sink, divergences). Each ticket's signals run
    against the repo chosen by scope (_scope_repo); scope with no repo
    (system/infra) yields a warning and empty file/grep signals (the agent judges
    without a repo signal).

    WOT-2026-041f adds ``divergences``: cross-checks that surface a CONTRADICTION
    between two sources (a DEC vs the row's state; a blocker vs the live queue).
    They remain [RELATO] like every other signal -- each carries its evidence and
    an explicit note that opposite readings exist. This script NEVER classifies.
    """
    tickets: list[dict] = []
    warnings: list[str] = []
    raw_sink: list[str] = []
    divergences: list[dict] = []
    # Cross (f) needs the WHOLE live table as its reference set, so it is built
    # before the per-ticket loop: a blocker is "off-queue" relative to every live
    # row, not just the reconciled subset.
    live_ids = frozenset(
        cells[_COL_TICKET] for cells in rows if len(cells) == _EXPECTED_COLS
    )
    for cells in rows:
        if len(cells) != _EXPECTED_COLS:
            continue  # the contract gate owns shape validation; skip malformed rows
        status = cells[_COL_STATUS]
        depends_cell = cells[_COL_DEPENDS]
        # Cross (f): check for off-queue blockers on:
        # 1. 'blocked' rows (original logic -- never enter reconciliation)
        # 2. 'pending'/'completed-partial' rows with a non-empty dependency cell
        #    (WOT-2026-046g: these may be silently unblocked)
        has_dependency = depends_cell and depends_cell.strip() not in ("", "-")
        if status == _BLOCKED_STATE or (status in RECONCILE_STATES and has_dependency):
            offqueue = _signal_blocker_offqueue(depends_cell, live_ids)
            if offqueue:
                # WOT-2026-046g: use different kind for pending/CP rows vs blocked rows
                kind = (
                    "blocked_with_offqueue_blocker"
                    if status == _BLOCKED_STATE
                    else "pending_with_offqueue_blocker"
                )
                note = (
                    (
                        "SIGNAL, not verdict: the blocker may be archived "
                        "(row silently unblocked) or a typo. Opposite "
                        "consequences -- the agent resolves it."
                    )
                    if status == _BLOCKED_STATE
                    else (
                        "SIGNAL, not verdict: a pending/CP row declares a blocker "
                        "that is not in the live queue. The blocker may be archived "
                        "(dependency satisfied) or a typo. The agent resolves it."
                    )
                )
                divergences.append(
                    {
                        "kind": kind,
                        "ticket_id": cells[_COL_TICKET],
                        "status": status,
                        "blockers": offqueue,
                        "note": note,
                    }
                )
        if status not in RECONCILE_STATES:
            continue
        ticket_id = cells[_COL_TICKET]
        scope_slug = cells[_COL_SCOPE]
        titulo = cells[_COL_TITULO]
        ficha_body = _ficha_body_for(content, ticket_id)
        repo_label, repo = _scope_repo(scope_slug, motor_root, dest_root)
        record = {
            "ticket_id": ticket_id,
            "status": status,
            "scope_slug": scope_slug,
            "repo": repo_label,
            "grep_commits": [],
            "scope_paths": [],
            "dod_terms": [],
            "dec_accepted_hits": [],
        }
        # Cross (e): a LIVE row whose DEC says "accepted". Runs regardless of
        # scope repo -- DECs live in the destino, not in the scoped repo.
        dec_hits = _signal_dec_accepted(ticket_id, dest_root)
        if dec_hits:
            record["dec_accepted_hits"] = dec_hits
            divergences.append(
                {
                    "kind": "dec_accepted_but_ticket_live",
                    "ticket_id": ticket_id,
                    "status": status,
                    "evidence": dec_hits,
                    "note": (
                        "SIGNAL, not verdict: the DEC may have accepted a DESIGN "
                        "while implementation stays pending. The agent judges."
                    ),
                }
            )
        if repo is None:
            warnings.append(
                f"{ticket_id}: scope '{scope_slug}' -> no git repo (n/a); "
                "file/grep signals omitted"
            )
        else:
            paths = _harvest_paths(titulo, ficha_body)
            terms = _harvest_terms(ticket_id, scope_slug, titulo, ficha_body)
            ticket_sink: list[str] = []
            record["grep_commits"] = _signal_commits(ticket_id, repo)
            record["scope_paths"] = _signal_paths(paths, repo)
            record["dod_terms"] = _signal_grep(terms, repo, ticket_sink)
            if ticket_sink:
                raw_sink.append(
                    f"===== {ticket_id} ({repo_label}) =====\n" + "\n".join(ticket_sink)
                )
        tickets.append(record)
    return tickets, warnings, raw_sink, divergences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect backlog-reconciliation git signals (collector, not judge)."
    )
    parser.add_argument(
        "--motor-root", required=True, help="repo_motor path (MANIFEST.distribute)"
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="repo_destino (backlog owner), used verbatim",
    )
    parser.add_argument(
        "--workspace-root",
        default=None,
        help="active workspace (holds motor_destination_link.json)",
    )
    parser.add_argument("--out", default=None, help="explicit output dir (immutable)")
    # NOTE: no --apply-fixes. The collector is strictly read-only, always.
    args = parser.parse_args(argv)

    motor_root = Path(args.motor_root).resolve()
    if not (motor_root / "MANIFEST.distribute").exists():
        print(
            f"[reconcile] ERROR: motor-root has no MANIFEST.distribute: {motor_root}",
            file=sys.stderr,
        )
        return 2

    # Resolve the backlog owner: --project-root verbatim, else via the workspace link.
    dest_root, dest_err = _resolve_destino_root(args.project_root, args.workspace_root)
    if dest_root is None:
        print(
            f"[reconcile] NOTICE: backlog root unresolved ({dest_err}); degraded.",
            file=sys.stderr,
        )
        return 3

    backlog = dest_root / ".agent" / "collaboration" / "backlog.md"
    try:
        content = backlog.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(
            f"[reconcile] ERROR: cannot read backlog {backlog}: {exc}", file=sys.stderr
        )
        return 1

    rows, table_err = _extract_vista_rapida_rows(content)
    if table_err:
        print(f"[reconcile] ERROR: {table_err}", file=sys.stderr)
        return 1

    roots = {"MOTOR_ROOT": motor_root, "DESTINO_ROOT": dest_root}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    base_out = (
        Path(args.out).resolve()
        if args.out
        else (
            dest_root
            / ".agent"
            / "runtime"
            / "reconcile"
            / f"backlog_reconcile_{stamp}"
        )
    )
    try:
        out_dir = _unique_out_dir(base_out)
        (out_dir / "raw").mkdir(parents=True, exist_ok=False)
        (out_dir / ".gitignore").write_text("raw/\n", encoding="utf-8")
    except (OSError, RuntimeError) as exc:
        print(f"[reconcile] ERROR: cannot create output dir: {exc}", file=sys.stderr)
        return 2

    tickets, warnings, raw_sink, divergences = _collect_all(
        rows, content, motor_root, dest_root
    )

    # WOT-2026-046i: explicit coverage block so "zero divergences" is
    # distinguishable from "zero coverage".
    all_statuses = [
        cells[_COL_STATUS] for cells in rows if len(cells) == _EXPECTED_COLS
    ]
    reconcile_count = sum(1 for s in all_statuses if s in RECONCILE_STATES)
    blocked_count = sum(1 for s in all_statuses if s == _BLOCKED_STATE)
    other_count = len(all_statuses) - reconcile_count - blocked_count
    coverage = {
        "states_checked": sorted(set(all_statuses)),
        "total_rows": len(all_statuses),
        "reconcile_rows": reconcile_count,
        "blocked_rows": blocked_count,
        "other_rows": other_count,
        "divergence_kinds": sorted({d["kind"] for d in divergences}),
        "limitation": (
            "Short-form blocker IDs (e.g. '028a' instead of 'WOT-2026-028a') "
            "are not detected (backlog_reconcile.py:126-128)."
        ),
    }

    repos_last_run = {
        "motor": _read_last_run(motor_root),
        "destino": _read_last_run(dest_root),
    }

    findings = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topology": {
            "motor_root": "<MOTOR_ROOT>",
            "destino_root": "<DESTINO_ROOT>",
            "backlog": str(backlog.name),
        },
        "coverage": coverage,
        "tickets": tickets,
        "repos_last_run": repos_last_run,
        "automatic_warnings": warnings,
        "automatic_criticals": [],
        "divergences": divergences,
        "note": "Collector output is [RELATO]; the agent produces the verdict (Fase 0).",
    }
    (out_dir / "findings.json").write_text(
        _relativize(json.dumps(findings, indent=2, ensure_ascii=False), roots),
        encoding="utf-8",
    )
    # Raw grep dumps carry third-party file contents (absolute paths / other repos'
    # text) -> kept ONLY under the gitignored raw/ dir, never in the versioned JSON.
    if raw_sink:
        (out_dir / "raw" / "grep_hits.txt").write_text(
            _relativize("\n\n".join(raw_sink), roots), encoding="utf-8"
        )

    print(f"[reconcile] OK -> {out_dir}")
    print(
        f"[reconcile] tickets={len(tickets)} warnings={len(warnings)} "
        f"divergences={len(divergences)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
