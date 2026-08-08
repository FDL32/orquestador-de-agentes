#!/usr/bin/env python3
"""Encoding guard for COMMIT MESSAGES (WOT-2026-046f).

WOT-2026-024x calls this "la barrera del alcance, no del mecanismo": a guard
that is correctly implemented and correctly wired, but does not look where the
failure happens. ``check_encoding_guard.py`` covers FILES; the commit message
was never its surface, so a message could carry corruption and every hook
stayed green. Measured on ``a3966ae`` (WOT-2026-045g), whose subject shipped
three accents with nothing to see it.

DECIDED SCOPE (the ticket's option (b), adjudicated with the operator):
BLOCK structural corruption, WARN on accents/typographic punctuation.

Rationale, measured over the repo's 1385 commits before choosing:
  - 0 messages carry mojibake  -> blocking it costs nothing and closes the
    vector that actually corrupts.
  - 34 carry accents and 31 typographic punctuation (64 unique, 4.6%) -- all
    of it legitimate, well-written Spanish ("aísla", "cosméticas"). Blocking
    those would reject correct prose and force writing without tildes.
This mirrors what the file guard already does: it chases CORRUPTION, not
STYLE. Reporting a WARN keeps the signal without turning a barrier into a
generator of false positives (the exact pathology of WOT-2026-047f).

MEASURED LIMIT, declared rather than hidden: the reusable helpers in
``encoding_guard`` (``find_text_corruption`` / ``find_mojibake``) detect 0 of
those 64 historic cases, because they target structural corruption and not
accents. So the WARN layer is a NEW check here, not a rewiring -- a hook that
merely reused those helpers would be a barrier that never bites the failure it
promises.

Before: argv[1] is the path to the commit message file git provides
    (``.git/COMMIT_EDITMSG``); it is read as UTF-8.
During: strips comment lines (git's ``#`` scissors and template) before
    inspecting, so boilerplate never triggers a finding. No writes.
After: exit 0 when the message carries no corruption (warnings still print to
    stderr); exit 1 with a diagnostic naming the offending snippet otherwise.
    Never raises on a missing/unreadable file -- it degrades to exit 0, because
    blocking every commit on a guard bug would be worse than the gap.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.encoding_guard import (  # noqa: E402
    find_c1_controls,
    find_control_chars,
    find_mojibake,
)


# Typographic punctuation: legitimate in prose, but a frequent sign that text
# was pasted from a rich-text source. WARN only -- never a block.
#
# Declared by CODEPOINT on purpose: written as literals, ruff flags them
# RUF001 ("ambiguous character"), which is a false positive here -- these
# characters ARE the object of this guard, not a slip. Escapes also make the
# detected set explicit for a reader.
TYPOGRAPHIC = frozenset(
    "“"  # LEFT DOUBLE QUOTATION MARK
    "”"  # RIGHT DOUBLE QUOTATION MARK
    "‘"  # LEFT SINGLE QUOTATION MARK  # noqa: RUF001
    "’"  # RIGHT SINGLE QUOTATION MARK  # noqa: RUF001
    "–"  # EN DASH  # noqa: RUF001
    "—"  # EM DASH
    "…"  # HORIZONTAL ELLIPSIS
)

# Spanish accents. WARN only, for the same reason.
ACCENTED = frozenset("\xe1\xe9\xed\xf3\xfa\xfc\xf1\xc1\xc9\xcd\xd3\xda\xdc\xd1")


def strip_comments(message: str) -> str:
    """Drop git's comment lines so boilerplate never triggers a finding.

    Before: `message` is the raw commit-message text.
    During: pure string filtering; no I/O.
    After: returns the message without lines starting with '#'. Never raises.
    """
    return "\n".join(
        line for line in message.splitlines() if not line.lstrip().startswith("#")
    )


def blocking_issues(message: str) -> list[str]:
    """Structural corruption that must STOP the commit.

    Reuses ``encoding_guard`` rather than reimplementing the contract: one
    definition of "corrupt text", consumed by the file guard and by this hook.

    Before: `message` is the comment-stripped commit message.
    During: pure text inspection; no I/O.
    After: returns a list of human-readable diagnostics (empty if clean).
    """
    issues: list[str] = []
    issues.extend(f"mojibake: {s!r}" for s in find_mojibake(message))
    issues.extend(
        f"caracter de control no permitido: {s!r}" for s in find_control_chars(message)
    )
    issues.extend(
        f"control C1 (U+0080-U+009F): {s!r}" for s in find_c1_controls(message)
    )
    return issues


def advisory_issues(message: str) -> list[str]:
    """Style signals worth reporting but never worth blocking."""
    issues: list[str] = []
    found_typo = sorted({c for c in message if c in TYPOGRAPHIC})
    if found_typo:
        issues.append(
            "puntuacion tipografica: "
            + " ".join(f"{c!r} (U+{ord(c):04X})" for c in found_typo)
        )
    found_acc = sorted({c for c in message if c in ACCENTED})
    if found_acc:
        issues.append("acentos: " + " ".join(found_acc))
    return issues


def _force_utf8_stderr() -> None:
    """Make stderr able to print what this guard reports.

    On Windows the console codepage is not UTF-8, so printing the very
    characters being reported (accents, curly quotes) raised
    UnicodeEncodeError -- the guard would crash while diagnosing. Caught by
    the tests, not by reading the code.

    Before: stderr may be bound to a non-UTF-8 codepage.
    During: reconfigures the stream in place when supported.
    After: returns None; degrades silently on streams without reconfigure().
    """
    with contextlib.suppress(AttributeError, OSError, ValueError):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: git passes the message file path as argv[1]."""
    _force_utf8_stderr()
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(
            "[commit-msg-encoding] sin ruta de mensaje; nada que revisar",
            file=sys.stderr,
        )
        return 0

    path = Path(args[0])
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        # Fail OPEN on a guard-side error: blocking every commit because the
        # guard itself broke would be worse than the gap it covers.
        print(
            f"[commit-msg-encoding] no se pudo leer {path}: {e} (no bloquea)",
            file=sys.stderr,
        )
        return 0

    message = strip_comments(raw)

    for issue in advisory_issues(message):
        print(f"[commit-msg-encoding] WARN {issue}", file=sys.stderr)

    blocking = blocking_issues(message)
    if blocking:
        print(
            "[commit-msg-encoding] ERROR: el mensaje de commit tiene corrupcion:",
            file=sys.stderr,
        )
        for issue in blocking:
            print(f"  - {issue}", file=sys.stderr)
        print(
            "  Remedio: reescribe el mensaje en UTF-8 limpio. Si lo generaste con\n"
            "  un here-string o heredoc, usa 'git commit -F <fichero>' en su lugar.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
