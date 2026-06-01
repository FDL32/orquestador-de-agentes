"""Stable blocker fingerprinting for adaptive Manager review.

WT-2026-196: Firma resistente a drift de lineas y ruido markdown.
La firma canonica usa `file + function/symbol + summary` como eje principal;
`line` es solo hint secundario.

Before: Requiere texto markdown de feedback del Manager (seccion ## BLOCKERS).
During: Parsea blockers individuales, normaliza ruido Markdown y genera firma.
After: Devuelve listas de dicts con 'raw', 'summary', 'signature' y metadatos.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# constantes
# ---------------------------------------------------------------------------
_BLOCKER_MARKERS = ("BLOCKER", "P0", "P1")
_SUGGESTION_MARKERS = ("SUGGESTION", "NIT")
_BLOCKING_LANGUAGE = (
    "falla",
    "regresion",
    "incorrecto",
    "must",
    "required",
    "bloquea",
    "critical",
    "necesario",
    "obligatorio",
)

_SECTION_HEADER_RE = re.compile(
    r"^##\s*(BLOCKERS|SUMMARY|SUGGESTIONS)\s*$", re.IGNORECASE | re.MULTILINE
)
_FILE_LINE_RE = re.compile(r"(?P<file>[\w./\\-]+\.\w+)(?::(?P<line>\d+))?")
_BULLET_LEADER_RE = re.compile(r"^[\s]*[-*+]\s+")
_MARKER_PREFIX_RE = re.compile(
    r"^(BLOCKER|P0|P1|SUGGESTION|NIT)[:\s]\s*", re.IGNORECASE
)
_MD_FORMATTING_RE = re.compile(r"[*`#~]{1,3}|__+")
_WHITESPACE_COLLAPSE_RE = re.compile(r"\s+")
_EXTRA_PUNCTUATION_RE = re.compile(r"[.!,;:]+$")


# ---------------------------------------------------------------------------
# helpers de normalizacion
# ---------------------------------------------------------------------------


def _strip_markdown_noise(text: str) -> str:
    """Remove markdown formatting, bullets, and collapse whitespace."""
    text = _BULLET_LEADER_RE.sub("", text)
    text = _MARKER_PREFIX_RE.sub("", text)
    text = _MD_FORMATTING_RE.sub("", text)
    text = text.replace("\\n", " ").replace("\n", " ").replace("\r", " ")
    text = _WHITESPACE_COLLAPSE_RE.sub(" ", text)
    text = text.strip()
    text = _EXTRA_PUNCTUATION_RE.sub("", text)
    return text.strip()


def _normalize_summary(text: str) -> str:
    """Fully normalize a blocker summary for signature computation.

    - Uppercase
    - Strip markdown
    - Collapse whitespace to single space
    - Strip leading/trailing punctuation
    """
    clean = _strip_markdown_noise(text)
    clean = clean.upper().strip()
    clean = _WHITESPACE_COLLAPSE_RE.sub(" ", clean)
    return clean


def _extract_file_and_function(
    line_content: str,
) -> tuple[str | None, str | None, int | None]:
    """Extract (file, function_symbol, line_number) from a blocker line.

    Parses patterns like:
      - `bus/review_bridge.py:123` -> file, line 123
      - `bus/review_bridge.py::some_function` -> file, function
      - `manager_review_bridge.py:456:_save_state` -> file, line, function

    Returns:
        (file_path, function_symbol, line_number) — each may be None.
    """
    file = None
    function = None
    line = None

    # Try to extract file:line or file:line:symbol or file::symbol
    match = _FILE_LINE_RE.search(line_content)
    if match:
        file = match.group("file")
        line_str = match.group("line")
        if line_str:
            line = int(line_str)

    # Try to extract function/symbol after :: or before (
    func_match = re.search(r"::(\w+)", line_content)
    if func_match:
        function = func_match.group(1)
    else:
        func_match = re.search(r"`(\w+)\(\)`", line_content)
        if func_match:
            function = func_match.group(1)
        else:
            func_match = re.search(r"'(\w+)\(\)'", line_content)
            if func_match:
                function = func_match.group(1)

    return file, function, line


def _is_likely_blocker(text: str) -> bool:
    """Determine if text reads like a blocker (vs a suggestion).

    Uses marker prefixes and blocking language keywords.
    """
    upper = text.upper().strip()
    for marker in _BLOCKER_MARKERS:
        if upper.startswith(marker) or f"[{marker}]" in upper:
            return True
    for marker in _SUGGESTION_MARKERS:
        if upper.startswith(marker) or f"[{marker}]" in upper:
            return False
    # No explicit marker: check blocking language
    for keyword in _BLOCKING_LANGUAGE:
        if keyword in upper:
            return True
    # If no markers and no blocking language, treat as blocker by default
    # if it references a file:line pattern (structural finding)
    return bool(_FILE_LINE_RE.search(text))


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------


def parse_blockers(feedback_text: str) -> list[dict[str, Any]]:
    """Extract individual blocker entries from Manager feedback markdown.

    Before: Requires raw markdown text with a ``## BLOCKERS`` section.
    During: Parses the BLOCKERS section, splits into individual bullet/line
            entries, normalizes each.
    After: Returns a list of dicts with keys:
           'raw', 'summary', 'file', 'function', 'line', 'is_blocker'.

    Args:
        feedback_text: Raw Manager feedback (stdout or normalized feedback).

    Returns:
        List of parsed blocker dicts. Only entries classified as blockers
        (``is_blocker=True``) are included. Non-blocker items like suggestions
        or meta-text are excluded.
    """
    entries: list[dict[str, Any]] = []

    # Locate the BLOCKERS section
    sections = list(_SECTION_HEADER_RE.finditer(feedback_text))
    blockers_section: str | None = None
    for i, match in enumerate(sections):
        if match.group(1).upper() == "BLOCKERS":
            start = match.end()
            end = (
                sections[i + 1].start() if i + 1 < len(sections) else len(feedback_text)
            )
            raw_section = feedback_text[start:end]
            # Truncate at DECISION: line (not a section header but terminates content)
            decision_stop = re.search(
                r"\bDECISION:\s*(APPROVE|CHANGES|INSPECT)", raw_section
            )
            if decision_stop:
                raw_section = raw_section[: decision_stop.start()]
            blockers_section = raw_section.strip()
            break

    if not blockers_section:
        return entries

    # Split into individual lines / bullets
    for raw_line in blockers_section.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        # Each blocker is typically a bullet (-, *)
        if raw_line.startswith("-") or raw_line.startswith("*"):
            content = _BULLET_LEADER_RE.sub("", raw_line).strip()
        else:
            content = raw_line
        if not content:
            continue

        file, function, line = _extract_file_and_function(content)
        is_blocker = _is_likely_blocker(content)
        summary = _strip_markdown_noise(content)
        # Strip file:line prefix from summary so signature is line-number-independent
        if file:
            # Remove patterns like "file.py:123:" or "file.py: " or "file.py "
            file_prefix = re.escape(file)
            summary = re.sub(
                rf"^{file_prefix}(:\d+)?[:\s]*",
                "",
                summary,
                flags=re.IGNORECASE,
            ).strip()

        entries.append(
            {
                "raw": raw_line,
                "summary": summary,
                "file": file,
                "function": function,
                "line": line,
                "is_blocker": is_blocker,
            }
        )

    return [e for e in entries if e["is_blocker"]]


def compute_signature(blocker: dict[str, Any]) -> str:
    """Compute a stable fingerprint for a blocker dict.

    Firma canonica (resistente a drift de lineas):
      1. Si hay `file + function`, usar ``file::function::summary``.
      2. Si solo hay `file`, usar ``file:::summary``.
      3. Si no hay file, usar ``|summary``.

    Summary se normaliza a mayusculas + sin ruido markdown.
    Line solo es hint secundario — la firma NO incluye el numero de linea.

    Args:
        blocker: Dict with keys 'file', 'function', 'summary'.

    Returns:
        Normalized signature string.
    """
    summary = _normalize_summary(blocker.get("summary", ""))
    file = blocker.get("file")
    function = blocker.get("function")

    if file and function:
        return f"{file}::{function}::{summary}"
    elif file:
        return f"{file}:::{summary}"
    else:
        return f"|{summary}"


def compute_blocker_overlap(
    previous_signatures: set[str],
    current_signatures: set[str],
) -> float:
    """Compute overlap ratio between two sets of blocker signatures.

    Args:
        previous_signatures: Set of signatures from previous review.
        current_signatures: Set of signatures from current review.

    Returns:
        Overlap ratio 0.0-1.0. Returns 0.0 if either set is empty.
    """
    if not previous_signatures or not current_signatures:
        return 0.0
    intersection = previous_signatures & current_signatures
    # Use max cardinality as denominator to be conservative
    denominator = max(len(previous_signatures), len(current_signatures))
    if denominator == 0:
        return 0.0
    return len(intersection) / denominator


def extract_signatures_from_feedback(feedback_text: str) -> set[str]:
    """Convenience: parse blockers and return set of signatures.

    Args:
        feedback_text: Raw Manager feedback.

    Returns:
        Set of signature strings.
    """
    blockers = parse_blockers(feedback_text)
    return {compute_signature(b) for b in blockers}


def blocker_lines_from_signature(signature: str) -> list[str]:
    """Reconstruct human-readable lines from repeated blockers for HUMAN_GATE.

    Args:
        signatures: Canonical blocker signature string.

    Returns:
        List of reconstructed lines for display in reports.
    """
    lines: list[str] = []
    if signature.startswith("|"):
        lines.append(f"- {signature[1:]}")
    elif ":::" in signature:
        parts = signature.split(":::", 1)
        lines.append(f"- `{parts[0]}` — {parts[1]}")
    elif "::" in signature:
        parts = signature.split("::", 2)
        if len(parts) == 3:
            lines.append(f"- `{parts[0]}::{parts[1]}` — {parts[2]}")
        else:
            lines.append(f"- {signature}")
    else:
        lines.append(f"- {signature}")
    return lines
