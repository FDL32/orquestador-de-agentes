"""
Canonical ticket ID pattern for the motor.

WT-2026-245c: Single source of truth for the ticket ID regex pattern
``(?:WP|WT|[A-Z]{3})-\\d{4}-[A-Za-z0-9]+``.

All Python consumers (review_bridge, supervisor, etc.) MUST import from this
module instead of repeating the pattern inline. PowerShell consumers maintain
their own local copy via ``$script:TicketIdPattern``.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


# ── Canonical ticket ID pattern ──────────────────────────────────────────────
# Matches WP-XXXX-XXX, WT-XXXX-XXX, and three-letter-prefix tickets like
# CTL-XXXX-XXX. The prefix is exactly 2 or 3 uppercase letters.
# The year is exactly 4 digits. The suffix is alphanumeric (letters and digits).
TICKET_ID_PATTERN = r"(?:WP|WT|[A-Z]{3})-\d{4}-[A-Za-z0-9]+"

# ── Compiled regex for direct use ────────────────────────────────────────────
TICKET_ID_RE = re.compile(TICKET_ID_PATTERN)

# ── Pattern for matching **ID:** fields in markdown ──────────────────────────
WORKPLAN_ID_PATTERN = re.compile(r"\*\*ID:\*\*\s*(" + TICKET_ID_PATTERN + r")")

# ── Pattern for matching markdown table rows with ticket IDs ─────────────────
# Compiled with IGNORECASE because callers match against user-authored markdown
# where header casing may vary (e.g. "Plan ID" vs "plan id").
TURN_TABLE_PATTERN = re.compile(
    r"\|\s*\*\*(?:Ticket Activo|Plan ID|Ticket|Plan activo)\*\*\s*\|\s*"
    r"(" + TICKET_ID_PATTERN + r")\s*\|",
    re.IGNORECASE,
)

# ── Pattern for matching **Plan activo:** or **ID:** fields ──────────────────
# Compiled with IGNORECASE because callers match against user-authored markdown
# where field casing may vary.
WORKPLAN_FIELD_PATTERN = re.compile(
    r"\*\*(?:Plan activo|ID):\*\*\s*(" + TICKET_ID_PATTERN + r")",
    re.IGNORECASE,
)

# ── Pattern for matching markdown headings with ticket IDs ───────────────────
WORKPLAN_HEADING_PATTERN = re.compile(
    r"^\s*##\s+(" + TICKET_ID_PATTERN + r")\b",
    re.MULTILINE,
)

# ── Loose match pattern (finds ticket ID anywhere in text) ───────────────────
LOOSE_PATTERN = re.compile(r"(" + TICKET_ID_PATTERN + r")")

# ── Section delimiter for execution_log.md extraction ────────────────────────
SECTION_DELIMITER_PATTERN = re.compile(r"(?=\n### " + TICKET_ID_PATTERN + r")")

# ── Numeric-only patterns (feed int()) ──────────────────────────────────────
# WT-2026-251a: Extended from WP|WT to include 3-letter prefixes (e.g. WOT).
# The captured group is always the numeric suffix (\d+) so callers can safely
# call int() on it. Alphanumeric suffixes like "042a" do NOT match these
# patterns — only the pure-numeric portion prefix triggers a match,
# ensuring int() safety downstream (bus/supervisor.py:468,624).
NUMERIC_SUFFIX_PATTERN = re.compile(r"(?:WP|WT|[A-Z]{3})-\d{4}-(\d+)")
NEXT_TICKET_PATTERN = re.compile(r"(?:WP|WT|[A-Z]{3})-(\d{4})-(\d+)")

# ── Sort key pattern (accepts all prefixes, extracts year + suffix) ──────────
TICKET_SORT_KEY_PATTERN = re.compile(r"(?:WP|WT|[A-Z]{3})-(\d{4})-([A-Za-z0-9]+)")


_REF_REMOTE_WARNING = "refs remotas posiblemente caducadas (sin fetch)"


@dataclass(frozen=True)
class RefScan:
    """Immutable denominator and IDs produced by a local ref sweep.

    Before: the caller provides no mutable state; the scan owns all counts and
        sets returned by the ref reader.
    During: the reader fills the values while traversing local and remote refs
        without network access.
    After: instances expose frozen collections and counters for reporting; a
        failed sweep is represented by avisos rather than an exception.
    """

    ids: frozenset[str]
    refs: int
    tips: int
    blobs_leidos: int
    ids_solo_en_refs: frozenset[str]
    avisos: tuple[str, ...]


def is_valid_ticket_id(ticket_id: str) -> bool:
    """Return True if the string is a valid ticket ID.

    Before: Requires a string.
    During: Matches against the canonical TICKET_ID_PATTERN.
    After: Returns True for valid IDs like WP-2026-001, WT-2026-042a,
           CTL-2026-001a. Returns False for invalid strings.
    """
    return bool(TICKET_ID_RE.fullmatch(ticket_id))


def extract_ticket_id(text: str) -> str | None:
    """Extract the first ticket ID found in text, or None.

    Before: Requires a string.
    During: Searches for the canonical ticket ID pattern.
    After: Returns the first match or None.
    """
    m = LOOSE_PATTERN.search(text)
    return m.group(1) if m else None


def extract_all_ticket_ids(text: str) -> list[str]:
    """Extract all ticket IDs found in text.

    Before: Requires a string.
    During: Finds all matches of the canonical ticket ID pattern.
    After: Returns a list of matched ticket IDs (may be empty).
    """
    return LOOSE_PATTERN.findall(text)


# ── Next-free-ID allocation helpers (WOT-2026-040f) ──────────────────────────
# Pattern for the canonical assignment form <PREFIX>-<YEAR>-NNNx used by
# `orchestrator_pipeline.md:0.d`: three-digit number + OPTIONAL single trailing
# letter. Pure-numeric suffixes (WT-2026-251a legacy) also match, feeding int()
# safely on the number group. The letter group is optional so `-040` and `-040f`
# both parse: max is (number, letter-ord).
_CANONICAL_ID_RE = re.compile(r"([A-Z]{2,4})-(\d{4})-(\d{3,})([a-z]?)")


def collect_surface_ticket_ids(collab_dir: Path) -> set[str]:
    """Return the ticket IDs present in BOTH live-backlog and archive surfaces.

    Before: ``collab_dir`` resolves to a ``.agent/collaboration`` directory
        containing ``backlog.md`` (live queue) and ``_archive/backlog_done.md``
        (terminal archive). Missing files are tolerated (empty contribution).
    During: reads both files, extracts every canonical ticket ID from each via
        ``extract_all_ticket_ids``, unions the two sets. No mutation.
    After: returns the set of IDs found across BOTH surfaces. This is the
        single shared implementation of "which IDs exist" used by the
        assignment helper and by the memory-dedupe sweep
        (``scripts/find_similar_signals.py``).
    """
    found: set[str] = set()
    for rel in ("backlog.md", "_archive/backlog_done.md"):
        path = collab_dir / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found.update(extract_all_ticket_ids(text))
    return found


def _split_row_cells(line: str) -> list[str]:
    """Split a markdown row into cells while preserving escaped pipes.

    Before: ``line`` is one markdown table row, possibly using ``\\|`` for a
        literal pipe inside a cell.
    During: walks the line once, treating only unescaped pipes as delimiters,
        then trims the optional outer cells and surrounding whitespace.
    After: returns the ordered cell contents without the outer markdown
        delimiters; it does not perform I/O or mutate the input.
    """
    cells: list[str] = []
    buffer: list[str] = []
    escaped = False
    for char in line:
        if char == "|" and not escaped:
            cells.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
        escaped = char == "\\" and not escaped
    cells.append("".join(buffer))
    if cells and not cells[0].strip():
        cells = cells[1:]
    if cells and not cells[-1].strip():
        cells = cells[:-1]
    return [cell.strip() for cell in cells]


def _collect_row_ticket_ids(collab_dir: Path) -> set[str]:
    """Collect ticket IDs from the first two cells of both HEAD surfaces.

    Before: ``collab_dir`` points to a collaboration directory containing zero
        or more of ``backlog.md`` and ``_archive/backlog_done.md``.
    During: reads existing files as UTF-8 with replacement, normalizes line
        endings, and extracts canonical IDs only from the first two cells of
        lines beginning with ``|``. Missing files contribute no IDs.
    After: returns the union of row-cell IDs from both HEAD surfaces, without
        mutation; prose-only mentions and cells after the first two are absent.
    """
    found: set[str] = set()
    for rel in ("backlog.md", "_archive/backlog_done.md"):
        path = collab_dir / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
            if not line.lstrip().startswith("|"):
                continue
            cells = _split_row_cells(line)
            found.update(TICKET_ID_RE.findall(" ".join(cells[:2])))
    return found


def _row_ticket_ids_from_line(line: str) -> set[str]:
    """Extract ticket IDs from one markdown row using the two-cell contract.

    Before: ``line`` is one decoded line from a backlog surface.
    During: ignores non-row text, splits escaped pipes, and searches only the
        first two cells with the canonical ticket regex.
    After: returns the IDs in the ticket-cell window, or an empty set; it does
        not access files, invoke git, or mutate state.
    """
    if not line.lstrip().startswith("|"):
        return set()
    cells = _split_row_cells(line)
    return set(TICKET_ID_RE.findall(" ".join(cells[:2])))


def _row_ticket_ids_from_text(text: str) -> set[str]:
    """Extract ticket-cell IDs from normalized markdown text.

    Before: ``text`` is decoded backlog content and may contain CRLF or CR
        line endings.
    During: normalizes line endings and unions ``_row_ticket_ids_from_line``
        for each line without importing the admission guard.
    After: returns the union of IDs from the first two cells of row lines only;
        no filesystem or git state is changed.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    found: set[str] = set()
    for line in normalized.splitlines():
        found.update(_row_ticket_ids_from_line(line))
    return found


def _git_text(repo: Path, *args: str) -> str:
    """Run a read-only git command and decode its stdout.

    Before: ``repo`` is a candidate repository path and ``args`` are git
        arguments that do not mutate refs or working-tree files.
    During: invokes git through an argument list without a shell and decodes
        UTF-8 output with replacement for unusual branch names.
    After: returns stdout or propagates the specific subprocess/I/O failure to
        the fail-open scan boundary.
    """
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def _read_blob_ids(repo: Path, blob_shas: list[str]) -> set[str]:
    """Read unique blobs through git batch and release each payload in turn.

    Before: ``blob_shas`` contains object IDs reported as blobs by batch-check.
    During: sends the IDs to one ``cat-file --batch`` process, reads each
        header and exact payload length, extracts row IDs, then discards that
        payload before reading the next blob.
    After: returns the union of row IDs; subprocess failures raise for the
        caller's fail-open boundary and no repository state is modified.
    """
    if not blob_shas:
        return set()
    process = subprocess.Popen(  # noqa: S603
        ["git", "-C", str(repo), "cat-file", "--batch"],  # noqa: S607
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdin is None or process.stdout is None:
        process.kill()
        process.wait()
        raise RuntimeError("git cat-file --batch no expuso sus pipes")
    stdin = process.stdin
    stdout = process.stdout
    try:
        stdin.write(("\n".join(blob_shas) + "\n").encode("ascii"))
        stdin.close()
        found: set[str] = set()
        for _ in blob_shas:
            header = stdout.readline()
            if not header:
                raise RuntimeError("git cat-file --batch termino antes de tiempo")
            parts = header.rstrip(b"\n").split()
            if len(parts) != 3 or parts[1] != b"blob":
                raise RuntimeError("git cat-file --batch devolvio un objeto no blob")
            size = int(parts[2])
            payload = stdout.read(size)
            if len(payload) != size:
                raise RuntimeError("git cat-file --batch devolvio un blob truncado")
            if stdout.read(1) != b"\n":
                raise RuntimeError("git cat-file --batch no termino el blob")
            found.update(_row_ticket_ids_from_text(payload.decode("utf-8", "replace")))
        if process.wait() != 0:
            raise RuntimeError("git cat-file --batch fallo")
        return found
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def scan_ref_ticket_ids(collab_dir: Path) -> RefScan:
    """Scan HEAD surfaces and all readable local/remote refs without network.

    Before: ``collab_dir`` is the collaboration directory of a candidate git
        repository; its two surfaces may be absent, and git may be unavailable.
    During: enumerates non-symbolic heads/remotes, deduplicates tip and blob
        objects, reads unique surface blobs with batch-check and batch, and
        extracts only the first two row cells. Remote refs are never fetched.
    After: returns a ``RefScan`` denominator whose ``ids`` are the row IDs
        extracted from refs actually read; ``ids_solo_en_refs`` is that set
        minus IDs currently present in the working-tree HEAD surfaces. Git
        absence, unreadable refs, or unreadable blobs yield working-tree IDs
        plus avisos, including the fixed stale-remote warning; no exception
        escapes.
    """
    fallback_ids = frozenset(_collect_row_ticket_ids(collab_dir))
    avisos: list[str] = [_REF_REMOTE_WARNING]
    try:
        repo = collab_dir.parent.parent
        discovered_root = Path(
            _git_text(repo, "rev-parse", "--show-toplevel").strip()
        ).resolve()
        if discovered_root != repo.resolve():
            raise RuntimeError(
                f"la colaboracion no es la raiz git esperada ({discovered_root})"
            )
        if not _git_text(repo, "rev-parse", "HEAD").strip():
            raise RuntimeError("HEAD vacio")
        raw_refs = _git_text(
            repo,
            "for-each-ref",
            "--format=%(refname)%00%(objectname)%00%(symref)",
            "refs/heads",
            "refs/remotes",
        )
        refs: list[tuple[str, str]] = []
        for line in raw_refs.splitlines():
            name, sep, rest = line.partition("\0")
            if not sep:
                continue
            sha, sep, symref = rest.partition("\0")
            if not sep or symref:
                continue
            refs.append((name, sha))
        tips = sorted({sha for _, sha in refs})
        specs = "".join(
            f"{tip}:{surface}\n"
            for tip in tips
            for surface in (
                ".agent/collaboration/backlog.md",
                ".agent/collaboration/_archive/backlog_done.md",
            )
        )
        check = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), "cat-file", "--batch-check"],  # noqa: S607
            input=specs.encode("utf-8"),
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8", "replace")
        blob_shas: list[str] = []
        seen_blobs: set[str] = set()
        for line in check.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "blob" and parts[0] not in seen_blobs:
                seen_blobs.add(parts[0])
                blob_shas.append(parts[0])
        ids = _read_blob_ids(repo, blob_shas)
        head_ids = _collect_row_ticket_ids(collab_dir)
        return RefScan(
            frozenset(ids),
            len(refs),
            len(tips),
            len(blob_shas),
            frozenset(ids - head_ids),
            tuple(avisos),
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        avisos.append(f"lectura de refs no disponible ({exc})")
        return RefScan(fallback_ids, 0, 0, 0, frozenset(), tuple(avisos))


def next_free_ticket_id(
    prefix: str,
    year: int,
    collab_dir: Path,
    *,
    include_refs: bool = True,
) -> str:
    """Return the next free ticket ID for a prefix/year scanning both surfaces.

    Before: ``collab_dir`` is a live ``.agent/collaboration`` directory with
        ``backlog.md`` and ``_archive/backlog_done.md``; ``prefix`` is the
        canon ticket prefix (e.g. ``WOT``); ``year`` the operative year.
    During: collects the canonical IDs in the first two cells of BOTH HEAD
        surfaces and, by default, unions IDs from refs read by
        ``scan_ref_ticket_ids``; parses each matching
        ``<PREFIX>-<YEAR>-NNNx`` into ``(number, letter)``, and takes the
        global maximum. Allocation policy (WOT-2026-040f, declared): NO
        gap-filling -- always the successor of the global max (number, letter)
        across live + archive. Successor rules: same number with next letter
        (``400x`` -> ``400y``); ``z`` or pure-numeric suffix advances the
        number with letter ``a`` (``400z`` -> ``401a``). No prior IDs of the
        prefix/year -> ``<PREFIX>-<YEAR>-001a``.
    After: returns the successor as ``<PREFIX>-<YEAR>-NNNx`` (3-digit number).
        With ``include_refs=True`` it excludes IDs in HEAD plus refs actually
        read; it cannot cover refs from other machines or refs skipped after a
        declared read failure. With ``include_refs=False`` it uses HEAD only.
    """
    head_ids = _collect_row_ticket_ids(collab_dir)
    existing = (
        head_ids | set(scan_ref_ticket_ids(collab_dir).ids)
        if include_refs
        else head_ids
    )
    max_key: tuple[int, int] | None = None
    for tid in existing:
        m = _CANONICAL_ID_RE.fullmatch(tid)
        if not m:
            continue
        pfx, yr, num, letter = m.groups()
        if pfx != prefix or int(yr) != year:
            continue
        key = (int(num), ord(letter) if letter else 0)
        if max_key is None or key > max_key:
            max_key = key
    if max_key is None:
        return f"{prefix}-{year:04d}-001a"
    num, letter_ord = max_key
    if letter_ord == 0 or letter_ord == ord("z"):
        return f"{prefix}-{year:04d}-{num + 1:03d}a"
    return f"{prefix}-{year:04d}-{num:03d}{chr(letter_ord + 1)}"
