"""Tests de scripts/check_hook_delivery.py (diseno v6, 2026-10-23).

El guard mide la ENTREGA del indice de memoria en el lado del CONSUMIDOR (los
transcripts de Claude Code), porque el fallo real fue ese: el hook emitia y
Claude Code descartaba (`additionalContext` en la raiz). Los transcripts aqui
son sinteticos pero con la forma MEDIDA en transcripts reales del repo:
`{"attachment": {"type": "hook_additional_context", "content": [str]}}`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import bus.memory_loader as ml
import scripts.check_hook_delivery as chd
import scripts.prepush_check as prepush


def _line(**fields) -> str:
    return json.dumps(fields) + "\n"


def _transcript(
    config: Path, root: Path, name: str, *, ran: bool, delivered: bool, cwd=None
) -> Path:
    folder = config / "projects" / "slug-que-no-importa"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [_line(type="user", cwd=str(cwd or root), sessionId=name)]
    if ran:
        lines.append(
            _line(
                attachment={
                    "type": "hook_success",
                    "hookName": "SessionStart:startup",
                    "hookEvent": "SessionStart",
                    "content": "",
                    "command": 'python -c "...session_start_hook.py..."',
                }
            )
        )
    if delivered:
        lines.append(
            _line(
                attachment={
                    "type": "hook_additional_context",
                    "content": [
                        f"{chd.MEMORY_INDEX_MARKER}\n- obs-x: y\n</memory-index>",
                        "**Contratos de invocacion (M4/M5)**: ...",
                    ],
                }
            )
        )
    path = folder / f"{name}.jsonl"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _hook(tmp_path: Path, mtime: float = 1_000.0) -> Path:
    hook = tmp_path / "hook.py"
    hook.write_text("# hook\n", encoding="utf-8")
    os.utime(hook, (mtime, mtime))
    return hook


def test_marker_matches_the_loader_constant():
    """El guard no importa `bus/`; su copia del marcador debe coincidir."""
    assert chd.MEMORY_INDEX_MARKER == ml.MEMORY_INDEX_OPEN


def test_ok_when_a_session_of_this_root_received_the_index(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    config = tmp_path / "cfg"
    _transcript(config, root, "s1", ran=True, delivered=True)

    status, message = chd.evaluate(root, config, _hook(tmp_path))
    assert status == "OK", message


def test_warn_when_the_hook_ran_and_nothing_was_delivered(tmp_path):
    """El fallo P0 exacto: hook ejecutado, cero `hook_additional_context`.

    MUTACION ALCANZABLE: devolver OK cuando `ran_count` > 0 sin entrega ->
    este test cae.
    """
    root = tmp_path / "repo"
    root.mkdir()
    config = tmp_path / "cfg"
    _transcript(config, root, "s1", ran=True, delivered=False)

    status, message = chd.evaluate(root, config, _hook(tmp_path))
    assert status == "WARN"
    assert "hookSpecificOutput" in message


def test_other_roots_and_older_sessions_are_ignored(tmp_path):
    """Casa por `cwd` registrado y por mtime posterior al hook, nunca por slug."""
    root = tmp_path / "repo"
    root.mkdir()
    config = tmp_path / "cfg"
    _transcript(
        config, root, "otro", ran=True, delivered=False, cwd=tmp_path / "repo-hermano"
    )
    old = _transcript(config, root, "viejo", ran=True, delivered=False)
    os.utime(old, (10.0, 10.0))

    status, _message = chd.evaluate(root, config, _hook(tmp_path, mtime=1_000.0))
    assert status == "SKIP"


def test_subdirectory_sessions_belong_to_the_root(tmp_path):
    root = tmp_path / "repo"
    (root / "sub").mkdir(parents=True)
    config = tmp_path / "cfg"
    _transcript(config, root, "s1", ran=True, delivered=True, cwd=root / "sub")

    status, _message = chd.evaluate(root, config, _hook(tmp_path))
    assert status == "OK"


def test_skip_without_any_transcript_directory(tmp_path):
    status, message = chd.evaluate(tmp_path, tmp_path / "no-config", _hook(tmp_path))
    assert status == "SKIP"
    assert "no hay transcripts" in message


def test_prepush_maps_warn_to_non_blocking_failure(tmp_path, monkeypatch):
    """Cableado: `prepush_check` lo invoca y un WARN nunca bloquea el push."""
    monkeypatch.setattr(chd, "evaluate", lambda root: ("WARN", "sin entrega"))
    result = prepush.run_hook_delivery_check(tmp_path)
    assert result.passed is False
    assert result.is_blocking is False
    assert "WARN" in result.output

    monkeypatch.setattr(chd, "evaluate", lambda root: ("SKIP", "nada"))
    skipped = prepush.run_hook_delivery_check(tmp_path)
    assert skipped.passed is True and skipped.skipped is True
