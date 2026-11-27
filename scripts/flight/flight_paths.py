"""Resolve the approved read-only directory layout for a flight."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# This script is also loaded by absolute path from isolated subprocesses.  In
# that mode Python does not necessarily put the repository root on sys.path;
# calculate it from this file before importing the shared link primitives.
_repo_root = Path(__file__).resolve()
while _repo_root != _repo_root.parent and not (_repo_root / "scripts").is_dir():
    _repo_root = _repo_root.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.prefix_resolver import (  # noqa: E402
    LINK_REL,
    _link_dirs,
    _read_link,
    find_destination_link,
)


FLIGHT_PREFIX_RE = re.compile(r"^[A-Z]{3}$")
_FLIGHT_FOLDERS = ("salidas", "clones", "sandboxes", "lentes")


@dataclass(frozen=True)
class FlightPathsResult:
    """Outcome of resolving one flight's paths.

    Before: the resolver has validated the input paths and read the selected
            destination link without changing the filesystem.
    During: ``paths`` is either the complete approved set or empty when an
            error is present; warnings are non-blocking diagnostics.
    After: ``error`` is ``None`` only for a successful result, and ``exit_code``
           exposes the CLI-compatible status without performing I/O.
    """

    paths: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None

    @property
    def exit_code(self) -> int:
        """Return the stable CLI status for this result."""
        return (
            0 if self.error is None else 2 if self.error.startswith("entrada:") else 1
        )


def _invalid_input(vuelo_id: str, repos_root: Path) -> str | None:
    """Validate the two route-shaping inputs before any route is calculated."""
    if not isinstance(vuelo_id, str) or not vuelo_id:
        return "entrada: vuelo_id debe ser un segmento no vacio"
    if "/" in vuelo_id or "\\" in vuelo_id or ".." in vuelo_id:
        return "entrada: vuelo_id no puede contener separadores ni '..'"
    if not repos_root.is_absolute():
        return "entrada: repos_root debe ser una ruta absoluta"
    return None


def _read_tree_links(
    sweep_root: Path, selected_link: Path
) -> tuple[list[tuple[Path, dict]], list[str]]:
    """Read every direct child link under ``sweep_root`` through shared helpers.

    Before: ``sweep_root`` is the directory that holds the SELECTED destination
            as one of its direct children (its sibling-destinations tree), the
            same convention ``scan_links`` uses for ``parent(motor_root)`` --
            it is derived from the resolved link path, never from
            ``repos_root`` (the output tree, normally empty or nonexistent
            during this read-only piloto and unrelated to where destinations
            actually live). ``selected_link`` is the already resolved link for
            the request.
    During: enumerates link-bearing children with ``_link_dirs`` and reads each
            JSON document with ``_read_link``; no directory or file is created.
    After: returns readable link data plus warnings for unreadable documents.
    """
    link_paths = [child / LINK_REL for child in _link_dirs(sweep_root)]
    selected_resolved = selected_link.resolve()
    if selected_link.exists() and selected_resolved not in {
        link.resolve() for link in link_paths
    }:
        link_paths.append(selected_link)

    readable: list[tuple[Path, dict]] = []
    warnings: list[str] = []
    for link_path in sorted(link_paths):
        data, reason = _read_link(link_path)
        if data is None:
            warnings.append(f"AVISO link ilegible {link_path}: {reason}")
        else:
            readable.append((link_path, data))
    return readable, warnings


def _duplicate_destination_warnings(
    links: list[tuple[Path, dict]],
) -> list[str]:
    """Return warnings for repeated non-empty destination identifiers."""
    by_id: dict[str, list[Path]] = {}
    for link_path, data in links:
        destination_id = data.get("destination_id")
        if isinstance(destination_id, str) and destination_id:
            by_id.setdefault(destination_id, []).append(link_path)
    return [
        f"AVISO destination_id duplicado '{destination_id}': "
        + ", ".join(str(path) for path in paths)
        for destination_id, paths in sorted(by_id.items())
        if len(paths) > 1
    ]


def _prefix_collision(links: list[tuple[Path, dict]]) -> str | None:
    """Return a blocking diagnostic for one prefix mapped to distinct roots."""
    by_prefix: dict[str, list[tuple[Path, str]]] = {}
    for link_path, data in links:
        prefix = data.get("ticket_prefix")
        destination_root = data.get("destination_root")
        if (
            isinstance(prefix, str)
            and FLIGHT_PREFIX_RE.fullmatch(prefix)
            and isinstance(destination_root, str)
            and destination_root
        ):
            by_prefix.setdefault(prefix, []).append((link_path, destination_root))
    for prefix, entries in sorted(by_prefix.items()):
        distinct_roots = {root for _link, root in entries}
        if len(distinct_roots) > 1:
            links_text = ", ".join(str(link) for link, _root in entries)
            return f"colision de prefijo '{prefix}' entre links: {links_text}"
    return None


def _prefix_error(link_path: Path, data: dict) -> str | None:
    """Return the fail-closed diagnostic for the selected link's prefix."""
    if "ticket_prefix" not in data:
        return f"link {link_path}: falta ticket_prefix"
    prefix = data["ticket_prefix"]
    if prefix is None:
        return f"link {link_path}: ticket_prefix es null"
    if not isinstance(prefix, str) or not FLIGHT_PREFIX_RE.fullmatch(prefix):
        return (
            f"link {link_path}: ticket_prefix invalido {prefix!r}; "
            "debe cumplir ^[A-Z]{3}$"
        )
    return None


def resolve_flight_paths(
    project_root: Path, vuelo_id: str, repos_root: Path
) -> FlightPathsResult:
    """Resolve five approved paths from a destination link, read-only.

    Before: ``project_root`` identifies a destination, ``vuelo_id`` is a safe
            single path segment, and ``repos_root`` is an absolute sibling
            repository root. No output directory needs to exist.
    During: locates the selected link with ``find_destination_link``, reads it
            via ``_read_link``, audits all SIBLING-DESTINATION links (the
            selected link's own parent directory, never ``repos_root``)
            through ``_link_dirs``, and checks the dedicated three-letter
            prefix contract.
    After: returns four flight subdirectories and ``<repos_root>/_motor`` on
           success; any validation, link, prefix, or collision failure returns
           no paths and a non-zero-compatible result. Never writes.
    """
    project_root = Path(project_root)
    repos_root = Path(repos_root)
    input_error = _invalid_input(vuelo_id, repos_root)
    if input_error is not None:
        return FlightPathsResult(error=input_error)

    link_path = find_destination_link(project_root)
    if link_path is None:
        expected = project_root / LINK_REL
        return FlightPathsResult(error=f"link no encontrado: {expected}")
    data, reason = _read_link(link_path)
    if data is None:
        return FlightPathsResult(error=f"link {link_path} ilegible: {reason}")

    prefix_error = _prefix_error(link_path, data)
    if prefix_error is not None:
        return FlightPathsResult(error=prefix_error)

    # The sweep tree is the SELECTED destination's own parent directory (its
    # siblings), derived from the resolved link path -- WOT-2026-240a measured
    # that sweeping ``repos_root`` instead finds nothing in the real tree: the
    # output root is normally absent during this read-only piloto and is not
    # where destinations live (``_link_dirs`` expects ``parent(destino_root)``,
    # the same convention ``scan_links`` documents for ``parent(motor_root)``).
    sweep_root = link_path.parents[3]
    links, warnings = _read_tree_links(sweep_root, link_path)
    warnings.extend(_duplicate_destination_warnings(links))
    collision = _prefix_collision(links)
    if collision is not None:
        return FlightPathsResult(warnings=tuple(warnings), error=collision)

    flight_root = repos_root / data["ticket_prefix"] / "vuelos" / vuelo_id
    paths = (
        *tuple(flight_root / folder for folder in _FLIGHT_FOLDERS),
        repos_root / "_motor",
    )
    return FlightPathsResult(paths=paths, warnings=tuple(warnings))


def _parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the read-only resolver."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--repos-root", required=True, type=Path)
    parser.add_argument("--vuelo-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the JSON CLI without creating any route directory.

    Before: ``argv`` contains the required project, repository-root, and flight
            arguments, or ``None`` to use the process command line.
    During: delegates to ``resolve_flight_paths`` and serializes its result.
    After: prints one JSON object and returns 0, 1, or 2 according to the
           resolver outcome; it performs no writes.
    """
    args = _parser().parse_args(argv)
    result = resolve_flight_paths(args.project_root, args.vuelo_id, args.repos_root)
    payload: dict[str, object] = {
        "paths": [str(path) for path in result.paths],
    }
    if result.warnings:
        payload["warnings"] = list(result.warnings)
    elif result.error is None:
        payload["warnings"] = []
    if result.error is not None:
        payload["error"] = result.error
    print(json.dumps(payload, ensure_ascii=False))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
