"""Channel identity form-check hook (WOT-2026-089x, Correccion E).

Detects a FORM collision in a manual cross-session channel file (the
``## T<N> | ... | origen=<editor>:<nombre-sesion> | ...`` block format used by
``CANAL_cursor_vscode_sin_sendmessage.md`` and any sibling file that follows
the same header convention) BEFORE the write lands, when the new turn's
``origen=`` session name has a prefix relation (in EITHER direction) with an
``origen=`` already present in the file (from any other ``(editor, name)``
pair -- the real incident this guards against was SAME-editor,
``claude-code:...-90`` vs ``claude-code:...-90b``), and the new turn does not
declare ``confirmado-por-ListAgents: <nombre>``.

This is a DETECCION DE FORMA, not an identity check: the hook can verify that
the new turn's text contains the escape line, never that the session which
wrote it actually ran ``ListAgents``. The value is a forced, auditable
declaration left in versioned text -- never real-time prevention of a false
claim (see ``PROPUESTA_mejoras_protocolo_mensajeria_20261009.md``, Seccion
5.quater). Framing the message as identity verification would overpromise
what hooks can mechanically check; the blocking message below says so
explicitly.

Before: a PreToolUse payload (Claude tool_use JSON) for ``Edit``/``Write``/
``MultiEdit`` arrives on stdin -- same contract as ``guard_paths.py``.
During: extracts the new ``origen=`` session name(s) from the edit's added
text and the existing ``origen=`` session names already in the file (current
content on disk for ``Edit``, or none for a brand-new ``Write``), then checks
the bidirectional-prefix collision rule.
After: exits 0 (no collision, or escape line present) or 2 with a
"deteccion de forma" diagnostic on stderr -- never a silent false green, and
never blocks on any file that is not already a channel-format file.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


#: Header block this hook understands -- NOT hardcoded to one filename; any
#: file whose content already contains this header shape is in scope.
_ORIGEN_RE = re.compile(r"origen=([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+)")
_ESCAPE_RE = re.compile(r"confirmado-por-ListAgents:\s*(\S+)")

_BLOCK_MSG_TEMPLATE = (
    "guard_channel_identity: deteccion de forma -- el nombre de sesion "
    "'{new_name}' (editor={new_editor}) coincide o tiene relacion de prefijo "
    "(en cualquier direccion) con 'origen={other_editor}:{other_name}' ya "
    "usado por otro turno en este fichero. Ejecuta ListAgents primero y "
    "confirma tu nombre real, o anade la linea "
    "'confirmado-por-ListAgents: <nombre>' a tu bloque. Esta barrera NO "
    "verifica tu identidad real -- solo fuerza una declaracion explicita y "
    "auditable."
)


def _is_prefix_either_direction(a: str, b: str) -> bool:
    """True if ``a`` is a prefix of ``b`` or ``b`` is a prefix of ``a``."""
    return a != b and (a.startswith(b) or b.startswith(a))


def _origen_pairs(text: str) -> list[tuple[str, str]]:
    """Extract all ``(editor, session_name)`` pairs from ``origen=`` fields."""
    return [(editor, name) for editor, name in _ORIGEN_RE.findall(text)]


def _has_escape(text: str) -> bool:
    """True if ``text`` declares ``confirmado-por-ListAgents: <algo>``."""
    return bool(_ESCAPE_RE.search(text))


def _new_text_blocks_from_payload(tool_input: dict[str, object]) -> list[str]:
    """The text block(s) being ADDED by this edit, kept SEPARATE per block.

    ``Edit``/``Write`` yield a single block (``new_string``/``content``).
    ``MultiEdit`` yields one block per entry in ``edits`` -- kept separate so
    a ``confirmado-por-ListAgents:`` escape declared in ONE block never
    exempts the ``origen=`` pairs of a DIFFERENT block in the same payload
    (Codex DESIGN_REVIEW finding, 2026-10-09: a global join let one escape
    line cover every block).
    """
    for key in ("new_string", "content"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return [value]
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        return [
            edit["new_string"]
            for edit in edits
            if isinstance(edit, dict) and isinstance(edit.get("new_string"), str)
        ]
    return []


def _existing_text(tool_input: dict[str, object]) -> str:
    """Current on-disk content of the target file, read fresh (never cached)."""
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return ""
    path = Path(file_path)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def evaluate_channel_identity(data: dict[str, object]) -> tuple[int, str | None]:
    """Evaluate a PreToolUse payload in-process. Returns (exit_code, message)."""
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0, None

    new_blocks = _new_text_blocks_from_payload(tool_input)
    if not any(_origen_pairs(block) for block in new_blocks):
        # Not a channel-format turn being added -- out of scope, never block.
        return 0, None

    existing_text = _existing_text(tool_input)
    existing_set = set(_origen_pairs(existing_text))

    for block in new_blocks:
        block_has_escape = _has_escape(block)
        for new_editor, new_name in _origen_pairs(block):
            if block_has_escape:
                continue
            for other_editor, other_name in existing_set:
                if other_editor == new_editor and other_name == new_name:
                    # Exact same (editor, name) pair as an existing turn --
                    # not a collision, it is the same session re-appearing.
                    continue
                if _is_prefix_either_direction(new_name, other_name):
                    return 2, _BLOCK_MSG_TEMPLATE.format(
                        new_name=new_name,
                        new_editor=new_editor,
                        other_editor=other_editor,
                        other_name=other_name,
                    )

    return 0, None


if __name__ == "__main__":
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        payload = {}

    exit_code, reason = evaluate_channel_identity(payload)
    if exit_code != 0 and reason:
        print(reason, file=sys.stderr)
    sys.exit(exit_code)
