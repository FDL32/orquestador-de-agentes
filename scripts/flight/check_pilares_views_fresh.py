"""Generate and verify role-scoped projections of the flight-pillar canon.

Before: the canonical pillar table is available in the motor repository.
During: project its current operational rows into deterministic Markdown views
and indices, recording the canonical SHA-256 in every generated view.
After: generation and verification are fail-closed; stale, edited, incomplete,
or unsafe references are rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


_VIEW_FILES = {"CO": "vista_CO.md", "IM": "vista_IM.md", "TR": "vista_TR.md"}
_INDEX_FILES = ("indice_messageid.md", "indice_fuente_larga.md", "alias_ids.md")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _defaults(
    canon_path: Path | None, output_dir: Path | None, project_root: Path | None
) -> tuple[Path, Path, Path]:
    """Resolve paths without relying on the caller's current directory."""
    root = (
        Path(project_root)
        if project_root is not None
        else (
            Path(canon_path).parent
            if canon_path is not None
            else Path(__file__).parents[2]
        )
    )
    canon = (
        Path(canon_path)
        if canon_path is not None
        else root / ".agent/rules/common/vuelo_pilares.md"
    )
    output = (
        Path(output_dir)
        if output_dir is not None
        else root / "prompts/vuelo_pilares_views"
    )
    return root, canon, output


def _cells(line: str) -> list[str]:
    """Return stripped cells from a Markdown table row."""
    cells = [cell.strip() for cell in line.strip().split("|")]
    if cells and not cells[0]:
        cells.pop(0)
    if cells and not cells[-1]:
        cells.pop()
    return cells


def _load_rows(canon_path: Path) -> list[dict[str, str]]:
    """Load the canonical eight-column pillar rows."""
    text = canon_path.read_text(encoding="utf-8")
    if not text or not text.endswith("\n"):
        raise ValueError("canonical file must be non-empty and end with a newline")
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("| P") or line.startswith("| Pilar"):
            continue
        cells = _cells(line)
        if len(cells) != 8:
            raise ValueError("canonical pillar rows must have eight columns")
        pillar, phrase, state, message_id, source, mechanism, ask, ambito = cells
        if state == "RATIFICADA":
            if not _UUID_RE.fullmatch(message_id):
                raise ValueError(f"invalid messageId for {pillar}")
            tokens = {token.strip() for token in re.split(r"[,/]", ambito)}
            if not ambito or not tokens <= {"CO", "IM", "TR", "G"}:
                raise ValueError(f"invalid ambito for {pillar}")
        elif state == "SUPERADA" and ambito != "HISTORICO":
            raise ValueError(f"SUPERADA row {pillar} must be HISTORICO")
        rows.append(
            {
                "pillar": pillar,
                "phrase": phrase,
                "state": state,
                "message_id": message_id,
                "source": source,
                "mechanism": mechanism,
                "ask": ask,
                "ambito": ambito,
            }
        )
    if not rows:
        raise ValueError("canonical file has no pillar rows")
    return rows


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a deterministic Markdown table."""
    line = "| " + " | ".join(headers) + " |\n"
    line += "|" + "|".join("---" for _ in headers) + "|\n"
    return line + "".join("| " + " | ".join(row) + " |\n" for row in rows)


def _write(path: Path, content: str) -> None:
    """Write UTF-8 text with explicit LF endings."""
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8", newline="\n")


def _flight_runtime_folders(project_root: Path) -> list[Path]:
    """Return existing flight runtime directories across nearby workspaces."""
    folders: list[Path] = []
    parent = project_root.resolve().parent
    for search_root in (parent, parent.parent, Path.home() / "Proyectos_Python"):
        if not search_root.is_dir():
            continue
        try:
            for item in search_root.iterdir():
                flight_base = item / ".agent/runtime/flight"
                if flight_base.is_dir():
                    folders.extend(p for p in flight_base.iterdir() if p.is_dir())
        except OSError:
            continue
    return folders


def _find_source_file(primary: str, project_root: Path) -> Path | None:
    """Locate a long-form source file within the motor or flight directories."""
    norm = Path(primary)
    if norm.is_absolute() or ".." in norm.parts:
        raise ValueError(f"source path must be relative: {primary}")
    direct = project_root / primary
    if direct.is_file():
        return direct
    env_flight = os.environ.get("FLIGHT_DIR")
    if env_flight:
        fpath = Path(env_flight)
        for cand in (fpath / primary, fpath / "diseno" / primary):
            if cand.is_file():
                return cand
    for folder in _flight_runtime_folders(project_root):
        for cand in (folder / primary, folder / "diseno" / primary):
            if cand.is_file():
                return cand
    return None


def _source_index(rows: list[dict[str, str]], project_root: Path) -> dict[str, str]:
    """Validate file-form sources and return pillar-to-source mappings."""
    result: dict[str, str] = {}
    for row in rows:
        source = row["source"].strip()
        if source.lower().startswith("sin_fichero:"):
            result[row["pillar"]] = source
            continue
        # A semicolon separates a primary relative path from an explanation.
        primary = source.split(";", 1)[0].strip()
        found = _find_source_file(primary, project_root)
        if found is None:
            raise FileNotFoundError(f"source file not found: {primary}")
        result[row["pillar"]] = primary
    return result


def _read_index(path: Path) -> dict[str, Any]:
    """Read a generated JSON-in-Markdown or two-column table index."""
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    rows = [_cells(line) for line in text.splitlines() if line.startswith("|")]
    data = [row for row in rows if len(row) >= 2 and not set(row[0]) <= {"-"}]
    if len(data) < 2:
        raise ValueError(f"invalid index: {path}")
    result: dict[str, Any] = {}
    for row in data[1:]:
        result[row[0]] = json.loads(row[1]) if row[1].startswith("[") else row[1]
    return result


def resolve_alias(alias: str, alias_map: dict[str, str]) -> str:
    """Resolve an alias chain and reject missing, ambiguous, or cyclic maps."""
    folded: dict[str, list[str]] = {}
    for key in alias_map:
        folded.setdefault(key.casefold(), []).append(key)
    current = alias
    seen: set[str] = set()
    while True:
        matches = folded.get(current.casefold(), [])
        if len(matches) != 1:
            raise KeyError(f"unknown or ambiguous alias: {current}")
        key = matches[0]
        if key in seen:
            raise ValueError("circular alias")
        seen.add(key)
        target = alias_map[key]
        target_matches = folded.get(target.casefold(), [])
        if not target_matches:
            if not target or target != target.upper():
                raise KeyError(f"unknown alias target: {target}")
            return target
        current = target


def _render_view(rows: list[dict[str, str]], role: str, digest: str) -> str:
    """Render the deterministic content for a role view."""
    headers = [
        "Pilar",
        "Frase",
        "ESTADO",
        "messageId",
        "fuente larga",
        "mecanismo",
        "a quien preguntar",
        "ambito",
    ]
    selected = [
        row
        for row in rows
        if row["state"] == "RATIFICADA"
        and (
            role in row["ambito"].replace(" ", "").split(",")
            or "G" in row["ambito"].replace(" ", "").split(",")
        )
    ]
    body = _table(
        headers,
        [
            [
                row[key]
                for key in (
                    "pillar",
                    "phrase",
                    "state",
                    "message_id",
                    "source",
                    "mechanism",
                    "ask",
                    "ambito",
                )
            ]
            for row in selected
        ],
    )
    return f"<!-- CANON_SHA256: {digest} -->\n\n{body}"


def generate_views_and_indices(
    canon_path: Path | None = None,
    output_dir: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, object]:
    """Generate the three role views and their supporting indices."""
    root, canon, output = _defaults(canon_path, output_dir, project_root)
    rows = _load_rows(canon)
    digest = hashlib.sha256(canon.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    generated: dict[str, object] = {"canon_sha256": digest, "files": {}}
    for role, filename in _VIEW_FILES.items():
        content = _render_view(rows, role, digest)
        _write(output / filename, content)
        generated["files"][filename] = digest  # type: ignore[index]

    message_index: dict[str, list[str]] = {}
    for row in rows:
        if row["state"] == "RATIFICADA":
            message_index.setdefault(row["message_id"], []).append(row["pillar"])
    message_rows = [
        [key, json.dumps(value, ensure_ascii=False)]
        for key, value in sorted(message_index.items())
    ]
    _write(
        output / "indice_messageid.md", _table(["messageId", "pilares"], message_rows)
    )
    source_index = _source_index(rows, root)
    _write(
        output / "indice_fuente_larga.md",
        _table(
            ["Pilar", "fuente larga"],
            [[key, value] for key, value in sorted(source_index.items())],
        ),
    )
    aliases = {token: token for token in ("CO", "IM", "TR", "G")}
    _write(
        output / "alias_ids.md",
        _table(
            ["alias", "id canonico"], [[key, value] for key, value in aliases.items()]
        ),
    )
    generated["files"].update({name: digest for name in _INDEX_FILES})  # type: ignore[union-attr]
    return generated


def verify_views_fresh(  # noqa: C901
    canon_path: Path | None = None,
    output_dir: Path | None = None,
    project_root: Path | None = None,
) -> bool:
    """Return whether every generated view and index matches the canon."""
    try:
        root, canon, output = _defaults(canon_path, output_dir, project_root)
        rows = _load_rows(canon)
        digest = hashlib.sha256(canon.read_bytes()).hexdigest()
        expected = {*_VIEW_FILES.values(), *_INDEX_FILES}
        if {path.name for path in output.glob("*.md")} != expected:
            return False
        for role, filename in _VIEW_FILES.items():
            path = output / filename
            if not path.is_file():
                return False
            expected_content = _render_view(rows, role, digest)
            if path.read_text(encoding="utf-8") != expected_content:
                return False
        expected_messages: dict[str, list[str]] = {}
        for row in rows:
            if row["state"] == "RATIFICADA":
                expected_messages.setdefault(row["message_id"], []).append(
                    row["pillar"]
                )
        if not (output / "indice_messageid.md").is_file():
            return False
        if _read_index(output / "indice_messageid.md") != expected_messages:
            return False
        if not (output / "indice_fuente_larga.md").is_file():
            return False
        expected_sources = _source_index(rows, root)
        if _read_index(output / "indice_fuente_larga.md") != expected_sources:
            return False
        if not (output / "alias_ids.md").is_file():
            return False
        _read_index(output / "alias_ids.md")
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return False
    return True


def rollback_views(output_dir: Path, originals_dir: Path, manifest_path: Path) -> None:
    """Restore manifest-listed files and verify each restored SHA-256."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("manifest files mapping is required")
    for relative, expected_hash in files.items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("manifest path escapes output directory")
        source = originals_dir / relative_path
        target = output_dir / relative_path
        if not source.is_file():
            raise FileNotFoundError(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected_hash:
            raise ValueError(f"restored hash mismatch: {relative}")


def run_pilares_views_fresh_check(
    project_root: Path | str | None = None,
    canon_path: Path | None = None,
    output_dir: Path | None = None,
) -> tuple[int, list[str]]:
    """Run the check and return ``(exit_code, diagnostic_messages)``."""
    if verify_views_fresh(
        canon_path, output_dir, Path(project_root) if project_root else None
    ):
        return 0, ["pilares views are fresh"]
    return 1, ["pilares views are stale or invalid"]


def main() -> int:
    """Provide the ``--generate`` and ``--check`` command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--generate", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--canon-path", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.generate:
        generate_views_and_indices(args.canon_path, args.output_dir, args.project_root)
        return 0
    code, messages = run_pilares_views_fresh_check(
        args.project_root, args.canon_path, args.output_dir
    )
    for message in messages:
        print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
