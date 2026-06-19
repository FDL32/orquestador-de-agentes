"""Build a versioned Hermes upload bundle from canonical motor documents.

Before:
    The motor root contains AGENTS.md and the canonical bootstrap/closeout prompts.
During:
    The script extracts stable sections, copies the canonical soul template,
    writes upload snapshots, and computes SHA-256 evidence for every artifact.
After:
    The output directory contains two Markdown snapshots and a JSON manifest;
    the optional soul output is synchronized from prompts/hermes_soul.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SOUL_SOURCE = Path("prompts/hermes_soul.md")
CONTEXT_SOURCES = (
    Path("AGENTS.md"),
    Path("prompts/orchestrator_destination_bootstrap.md"),
)
CLOSEOUT_SOURCE = Path("prompts/orchestrator_session_close_chat.md")


def _read_utf8(path: Path) -> str:
    """Before: path exists. During: decode strict UTF-8. After: return text."""
    return path.read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    """Before: path is readable. During: hash bytes. After: return hex digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_utf8(path: Path, text: str) -> None:
    """Before: text is final. During: create parent. After: write UTF-8 LF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.replace("\r\n", "\n").rstrip() + "\n"
    path.write_text(normalized, encoding="utf-8", newline="\n")


def _extract_section(text: str, heading: str) -> str:
    """Before: heading is exact. During: scan headings. After: section text."""
    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError as exc:
        raise ValueError(f"Required section not found: {heading}") from exc
    level = len(heading) - len(heading.lstrip("#"))
    end = len(lines)
    for index in range(start + 1, len(lines)):
        candidate = lines[index]
        if candidate.startswith("#" * level + " "):
            end = index
            break
    return "\n".join(lines[start:end]).rstrip()


def _motor_version(motor_root: Path) -> str:
    """Before: pyproject exists. During: parse version. After: return v-prefixed."""
    content = _read_utf8(motor_root / "pyproject.toml")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, flags=re.MULTILINE)
    if not match:
        raise ValueError("Project version not found in pyproject.toml")
    return f"v{match.group(1)}"


def _source_commit(motor_root: Path) -> str:
    """Before: motor is git repo. During: read HEAD. After: return full SHA."""
    result = subprocess.run(  # noqa: S603
        [shutil.which("git") or "git", "rev-parse", "HEAD"],
        cwd=motor_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    return result.stdout.strip()


def _source_status(motor_root: Path) -> list[str]:
    """Before: motor is git repo. During: read status. After: return entries."""
    result = subprocess.run(  # noqa: S603
        [shutil.which("git") or "git", "status", "--short"],
        cwd=motor_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line.rstrip() for line in result.stdout.splitlines() if line.strip()]


def _metadata_header(version: str, commit: str, generated_at: str) -> str:
    """Before: metadata resolved. During: format. After: Markdown header."""
    return (
        "> Snapshot generado desde fuentes canonicas del motor.\n"
        f"> Motor: `{version}` | Commit: `{commit}` | Generado: `{generated_at}`\n"
        "> Si estos datos no coinciden con el motor activo, trata el snapshot como obsoleto."
    )


def build_motor_context(motor_root: Path, generated_at: str) -> str:
    """Build the compact operating-context snapshot.

    Before:
        Canonical AGENTS and destination bootstrap documents exist.
    During:
        Extracts vocabulary, CEM, security, and the current bootstrap contract.
    After:
        Returns a self-contained Markdown snapshot for Hermes uploads.
    """
    agents = _read_utf8(motor_root / "AGENTS.md")
    bootstrap = _read_utf8(motor_root / CONTEXT_SOURCES[1])
    version = _motor_version(motor_root)
    commit = _source_commit(motor_root)
    sections = [
        "# Contexto operativo del motor",
        _metadata_header(version, commit, generated_at),
        _extract_section(agents, "## Vocabulario canonico"),
        _extract_section(agents, "## CEM v0 - Contrato, Evidencia y Memoria"),
        _extract_section(agents, "## Secretos y seguridad"),
        "## Bootstrap canonico de repo_destino",
        bootstrap,
    ]
    return "\n\n".join(sections)


def build_closeout_snapshot(motor_root: Path, generated_at: str) -> str:
    """Build the canonical closeout snapshot.

    Before:
        The session-close prompt exists in the motor.
    During:
        Adds immutable source metadata to the canonical prompt.
    After:
        Returns Markdown suitable for persistent Hermes uploads.
    """
    version = _motor_version(motor_root)
    commit = _source_commit(motor_root)
    closeout = _read_utf8(motor_root / CLOSEOUT_SOURCE)
    return "\n\n".join(
        [
            "# Checklist de cierre canonico",
            _metadata_header(version, commit, generated_at),
            closeout,
        ]
    )


def _file_record(path: Path, role: str, root: Path) -> dict[str, Any]:
    """Before: file exists. During: relativize/hash. After: manifest record."""
    try:
        display_path = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        display_path = str(path.resolve())
    return {"path": display_path, "role": role, "sha256": _sha256(path)}


def build_bundle(
    motor_root: Path,
    output_root: Path,
    soul_output: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Generate the Hermes bundle and its integrity manifest.

    Before:
        motor_root is a valid motor checkout and output paths are writable.
    During:
        Writes soul/context/closeout artifacts and hashes sources and outputs.
    After:
        Returns and writes a JSON manifest describing the complete snapshot.
    """
    motor = motor_root.resolve()
    output = output_root.resolve()
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    source_paths = [motor / SOUL_SOURCE, *(motor / p for p in CONTEXT_SOURCES)]
    source_paths.append(motor / CLOSEOUT_SOURCE)
    for source in source_paths:
        if not source.is_file():
            raise FileNotFoundError(f"Required canonical source not found: {source}")

    context_path = output / "01_motor_context.md"
    closeout_path = output / "30_closeout_checklist.md"
    _write_utf8(context_path, build_motor_context(motor, timestamp))
    _write_utf8(closeout_path, build_closeout_snapshot(motor, timestamp))

    generated = [
        _file_record(context_path, "motor_context", output),
        _file_record(closeout_path, "closeout_checklist", output),
    ]
    if soul_output is not None:
        _write_utf8(soul_output.resolve(), _read_utf8(motor / SOUL_SOURCE))
        generated.append(_file_record(soul_output, "soul", output.parent))

    source_status = _source_status(motor)
    manifest = {
        "schema_version": 1,
        "bundle_type": "hermes-operational-context",
        "motor_version": _motor_version(motor),
        "source_commit": _source_commit(motor),
        "source_tree_dirty": bool(source_status),
        "source_status": source_status,
        "generated_at": timestamp,
        "source_files": [
            _file_record(path, "canonical_source", motor) for path in source_paths
        ],
        "generated_files": generated,
    }
    manifest_path = output / "bundle_manifest.json"
    _write_utf8(
        manifest_path,
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True),
    )
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    """Before: none. During: define CLI. After: return parser."""
    parser = argparse.ArgumentParser(
        description="Build a versioned Hermes context bundle from the motor."
    )
    parser.add_argument("--motor-root", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--soul-output", type=Path)
    parser.add_argument("--generated-at", help="Optional deterministic ISO timestamp")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Before: CLI args valid. During: build bundle. After: print manifest JSON."""
    args = _build_parser().parse_args(argv)
    try:
        manifest = build_bundle(
            args.motor_root,
            args.output_root,
            soul_output=args.soul_output,
            generated_at=args.generated_at,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
