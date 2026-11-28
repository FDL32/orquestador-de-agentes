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
import subprocess
from pathlib import Path
from typing import Any


_VIEW_FILES = {"CO": "vista_CO.md", "IM": "vista_IM.md", "TR": "vista_TR.md"}
_INDEX_FILES = ("indice_messageid.md", "indice_fuente_larga.md", "alias_ids.md")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_ACTIVITY_PREFIX = "<!-- ACTIVIDAD:"
_ACTIVITY_RE = re.compile(
    r"^<!-- ACTIVIDAD: ([^|]+) \| ([^|]+) \| ([^|]+) \| "
    r"dueno=([^|]+) \| deuda=([^|]+) -->$"
)
_ACTIVITY_UNIVERSE_PATTERNS = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONSTITUTION.md",
    "INTERACTION_MODES.md",
    ".claude/rules/**/*.md",
    ".agent/rules/common/**/*.md",
    "prompts/**/*.md",
    "skills/**/SKILL.md",
    "docs/protocol/**/*.md",
)


def _posix_relative(path: Path, root: Path) -> str:
    """Return a root-relative path with the canonical slash separator."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def _git_tracked_files(root: Path) -> tuple[str, list[str]]:
    """Return tracked paths and the enumeration mode, failing closed on git errors."""
    try:
        probe = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        raise ValueError(f"git universe probe failed: {exc}") from exc
    if probe.returncode == 0:
        git_root = Path(probe.stdout.strip()).resolve()
        if git_root != root.resolve():
            return "filesystem", [
                _posix_relative(path, root)
                for path in root.rglob("*")
                if path.is_file() and ".git" not in path.parts
            ]
        try:
            listing = subprocess.run(  # noqa: S603
                ["git", "-C", str(root), "ls-files", "-z"],  # noqa: S607
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise ValueError(f"git file enumeration failed: {exc}") from exc
        if listing.returncode != 0:
            raise ValueError("git ls-files failed")
        return "git ls-files", [
            item.decode("utf-8") for item in listing.stdout.split(b"\0") if item
        ]
    if probe.returncode != 128:
        raise ValueError("git universe probe failed")
    return "filesystem", [
        _posix_relative(path, root)
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    ]


def _in_activity_universe(relative: str) -> bool:
    """Return whether a relative path matches one of the declared patterns."""
    if relative.startswith("prompts/vuelo_pilares_views/"):
        return False
    if relative in _ACTIVITY_UNIVERSE_PATTERNS[:4]:
        return True
    if relative.startswith(".claude/rules/") and relative.endswith(".md"):
        return True
    if relative.startswith(".agent/rules/common/") and relative.endswith(".md"):
        return True
    if relative.startswith("prompts/") and relative.endswith(".md"):
        return True
    if relative.startswith("skills/") and relative.endswith("/SKILL.md"):
        return True
    return relative.startswith("docs/protocol/") and relative.endswith(".md")


def _activity_universe(root: Path) -> tuple[str, list[str], list[str]]:
    """Enumerate the declared universe and all scanned files for R6."""
    mode, all_files = _git_tracked_files(root)
    universe = sorted(path for path in all_files if _in_activity_universe(path))
    return mode, universe, sorted(all_files)


def _activity_error(
    rule: str, relative: str, line_number: int, detail: str
) -> ValueError:
    """Create a stable rule error naming the violated route and line."""
    return ValueError(f"{rule} at {relative}:{line_number}: {detail}")


def activity_anchor_index(root: Path) -> dict[str, dict[str, str]]:  # noqa: C901
    """Index and validate activity anchors in the declared document universe.

    Before: ``root`` contains the versioned canon and its procedural documents.
    During: enumerate the root, validate R1-R6 and resolve local owners to the
    line immediately following each anchor.
    After: return one stable record per ``A-NN`` or raise ``ValueError`` naming
    the rule and ``route:line``. The companion ACTIVITY_MAP stores source-file
    hashes; this function intentionally returns only the public index contract.
    """
    project_root = Path(root).resolve()
    mode, universe, scanned = _activity_universe(project_root)
    universe_set = set(universe)
    records: dict[str, dict[str, str]] = {}
    for relative in scanned:
        path = project_root / relative
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"cannot read {relative}: {exc}") from exc
        if b"\0" in raw:
            continue
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError(f"non-UTF-8 text in {relative}") from exc
        in_universe = relative in universe_set
        for line_number, line in enumerate(lines, start=1):
            if not line.lstrip().startswith(_ACTIVITY_PREFIX):
                continue
            if not in_universe:
                raise _activity_error(
                    "R6", relative, line_number, "anchor outside universe"
                )
            match = _ACTIVITY_RE.fullmatch(line.strip())
            if match is None:
                raise _activity_error(
                    "GRAMATICA", relative, line_number, "malformed activity anchor"
                )
            identifier, name, state, owner_reference, debt = match.groups()
            identifier = identifier.strip()
            name = name.strip()
            state = state.strip()
            owner_reference = owner_reference.strip()
            debt = debt.strip()
            if not re.fullmatch(r"A-\d{2}", identifier):
                raise _activity_error(
                    "R1", relative, line_number, "invalid activity id"
                )
            if identifier in records:
                raise _activity_error(
                    "R1", relative, line_number, "duplicate activity id"
                )
            if state not in {"TIPIFICADA", "PARCIAL", "NO_TIPIFICADA"}:
                raise _activity_error(
                    "R2", relative, line_number, "invalid activity state"
                )
            if debt not in {"pendiente", "ninguna"} and not re.fullmatch(
                r"WOT-\d{4}-\d{3}[a-z]", debt
            ):
                raise _activity_error("R4", relative, line_number, "invalid deuda")
            owner = owner_reference
            if owner not in {"aqui", "ninguno"} and not re.fullmatch(
                r"[^|:]+:\d+", owner
            ):
                raise _activity_error(
                    "R3", relative, line_number, "invalid remote owner"
                )
            if state == "TIPIFICADA" and debt != "ninguna":
                raise _activity_error(
                    "R4", relative, line_number, "TIPIFICADA requires deuda=ninguna"
                )
            if state != "TIPIFICADA" and debt == "ninguna":
                raise _activity_error(
                    "R4",
                    relative,
                    line_number,
                    "non-TIPIFICADA requires deuda!=ninguna",
                )
            if owner == "ninguno" and state != "NO_TIPIFICADA":
                raise _activity_error(
                    "R5", relative, line_number, "dueno=ninguno requires NO_TIPIFICADA"
                )
            if state == "NO_TIPIFICADA" and owner != "ninguno":
                raise _activity_error(
                    "R5", relative, line_number, "NO_TIPIFICADA requires dueno=ninguno"
                )
            if owner == "aqui":
                if line_number + 1 > len(lines):
                    raise _activity_error(
                        "R3",
                        relative,
                        line_number,
                        "dueno=aqui requires a following line",
                    )
                resolved_owner = f"{relative}:{line_number + 1}"
            elif owner == "ninguno":
                resolved_owner = "ninguno"
            else:
                owner_path, owner_line_text = owner_reference.rsplit(":", 1)
                owner_line = int(owner_line_text)
                if owner_path not in universe_set:
                    raise _activity_error(
                        "R3", relative, line_number, "remote owner is outside universe"
                    )
                try:
                    owner_lines = (
                        (project_root / owner_path)
                        .read_text(encoding="utf-8")
                        .splitlines()
                    )
                except (OSError, UnicodeDecodeError) as exc:
                    raise _activity_error(
                        "R3", relative, line_number, "remote owner cannot be read"
                    ) from exc
                if owner_line < 1 or owner_line > len(owner_lines):
                    raise _activity_error(
                        "R3", relative, line_number, "remote owner line does not exist"
                    )
                resolved_owner = f"{owner_path}:{owner_line}"
            records[identifier] = {
                "nombre": name.strip(),
                "estado": state,
                "dueno": resolved_owner,
                "deuda": debt,
                "fuente": f"{relative}:{line_number}",
            }
    if mode not in {"git ls-files", "filesystem"}:
        raise ValueError("unknown activity universe mode")
    return records


def _activity_records_and_sources(
    root: Path,
) -> tuple[str, list[str], dict[str, dict[str, str]], dict[str, str]]:
    """Collect activity records plus hashes for files that contain anchors."""
    mode, universe, _ = _activity_universe(root)
    records = activity_anchor_index(root)
    source_paths = sorted(
        {record["fuente"].rsplit(":", 1)[0] for record in records.values()}
    )
    hashes = {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in source_paths
    }
    return mode, universe, records, hashes


def _render_activity_map(
    mode: str,
    universe: list[str],
    records: dict[str, dict[str, str]],
    source_hashes: dict[str, str],
) -> str:
    """Render the deterministic five-cell activity projection."""
    lines = [
        "<!-- ACTIVITY_MAP_GENERATOR: scripts/flight/check_pilares_views_fresh.py -->",
        f"<!-- ACTIVITY_UNIVERSE: mode={mode}; files={len(universe)} -->",
        "<!-- ACTIVITY_SOURCE_SHA256: one hash per file containing an anchor -->",
    ]
    lines.extend(
        f"<!-- SOURCE_SHA256: {path} {digest} -->"
        for path, digest in source_hashes.items()
    )
    lines.append(
        "<!-- la etiqueta la declara el ancla; la semantica no se comprueba -->"
    )
    lines.extend(
        [
            "",
            "| id | nombre | dueno resuelto | estado | deuda |",
            "|---|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {identifier} | {record['nombre']} | {record['dueno']} | {record['estado']} | {record['deuda']} |"
        for identifier, record in sorted(records.items())
    )
    return "\n".join(lines) + "\n"


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
    """Return stripped cells from a Markdown table row.

    Pipes literales en celdas del canon son ilegales y dan rc 1 (fail-closed;
    no se soportan escapes ni pipes en campos de la tabla).
    """
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
    """Generate role views, supporting indices and the activity projection."""
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
    activity_mode, activity_universe, activity_records, source_hashes = (
        _activity_records_and_sources(root)
    )
    activity_content = _render_activity_map(
        activity_mode, activity_universe, activity_records, source_hashes
    )
    activity_path = output / "ACTIVITY_MAP.md"
    _write(activity_path, activity_content)
    generated["files"]["ACTIVITY_MAP.md"] = hashlib.sha256(  # type: ignore[index]
        activity_content.encode("utf-8")
    ).hexdigest()
    return generated


def verify_views_fresh(  # noqa: C901
    canon_path: Path | None = None,
    output_dir: Path | None = None,
    project_root: Path | None = None,
) -> bool:
    """Return whether every generated view, index and activity map is fresh."""
    try:
        root, canon, output = _defaults(canon_path, output_dir, project_root)
        rows = _load_rows(canon)
        digest = hashlib.sha256(canon.read_bytes()).hexdigest()
        expected = {*_VIEW_FILES.values(), *_INDEX_FILES, "ACTIVITY_MAP.md"}
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
        activity_mode, activity_universe, activity_records, source_hashes = (
            _activity_records_and_sources(root)
        )
        expected_activity = _render_activity_map(
            activity_mode, activity_universe, activity_records, source_hashes
        )
        if (output / "ACTIVITY_MAP.md").read_text(
            encoding="utf-8"
        ) != expected_activity:
            return False
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
