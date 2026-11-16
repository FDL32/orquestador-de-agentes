"""Compute which backlog rows are eligible for implementation.

Before: ``backlog_path`` and ``registry_path`` identify readable Markdown and
JSON inputs; optional ``fichas_dir`` contains ficha files used only for FLT.
During: read the inputs, load the canonical active-state predicate by sibling
path, and evaluate each backlog row in source order without writing state.
After: return one exact-field decision dictionary per backlog row, or raise a
standard I/O or JSON exception when an input cannot be read.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path


DEPENDENCY_RE = re.compile(r"(?<![A-Za-z-])(?:WOT|WT)-\d{4}-\d+[a-z]?")
FLT_HEADER_RE = re.compile(r"^#+\s*(?:\d+\s+)?Files Likely Touched\b", re.IGNORECASE)
ACTIVE_CHECKER_NAME = "check_cell_conformance"


def _load_cell_checker():
    """Load the canonical sibling checker with the measured route-loader pattern.

    Before: the sibling ``check_cell_conformance.py`` is next to this module.
    During: use ``spec_from_file_location``, ``sys.modules`` and its cache.
    After: return the cached checker module with its canonical ``is_activa``.
    """
    cached = sys.modules.get(ACTIVE_CHECKER_NAME)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().with_name("check_cell_conformance.py")
    spec = importlib.util.spec_from_file_location(ACTIVE_CHECKER_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _split_row(line):
    """Split one Markdown table line into trimmed cells."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells):
    """Identify a Markdown table separator row."""
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _backlog_rows(path):
    """Read Markdown backlog rows and preserve their file order.

    Before: ``path`` points to a pipe table with the documented eight columns.
    During: identify the live header and skip separator or non-ticket lines.
    After: return dictionaries containing only the source cells needed here.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    header = None
    rows = []
    for line in lines:
        if "|" not in line:
            continue
        cells = _split_row(line)
        if _is_separator(cells):
            continue
        normalized = [cell.casefold() for cell in cells]
        if "ticket" in normalized and ("state" in normalized or "estado" in normalized):
            header = {name: index for index, name in enumerate(normalized)}
            continue
        if header is None or len(cells) <= max(header.values()):
            continue
        ticket = cells[header["ticket"]]
        if not ticket:
            continue
        rows.append(
            {
                "ticket": ticket,
                "title": cells[header.get("title", header.get("titulo", 2))],
                "scope": cells[header.get("scope", 3)],
                "state": cells[
                    header["state"] if "state" in header else header["estado"]
                ],
                "depends": cells[header.get("depends on", header.get("depende de", 5))],
                "reactivation": cells[
                    header.get("reactivation", header.get("reactivacion", 7))
                ],
            }
        )
    return rows


def _read_registry(path):
    """Read the registry session list without mutating the registry."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    sessions = value.get("sessions") if isinstance(value, dict) else None
    if not isinstance(sessions, list):
        raise ValueError("registry must contain a sessions list")
    return [session for session in sessions if isinstance(session, dict)]


def _starts_with_marker(value, *markers):
    """Return whether a cell starts with any case-insensitive marker."""
    text = str(value or "").casefold()
    return any(text.startswith(marker.casefold()) for marker in markers)


def _flt(path):
    """Read route bullets from the first Files Likely Touched section.

    Before: ``path`` is a ficha path or does not exist.
    During: scan only the named heading section and its plain route bullets.
    After: return a route set, or ``None`` when the section is unknown.
    """
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    in_section = False
    routes = set()
    for line in lines:
        if in_section and re.match(r"^#+\s+", line):
            break
        if FLT_HEADER_RE.match(line.strip()):
            in_section = True
            continue
        if in_section:
            match = re.match(r"^\s*-\s+(\S.*?)\s*$", line)
            if match:
                routes.add(match.group(1))
    if not in_section or not routes:
        return None
    return routes


def _short_ticket(ticket):
    """Return the slot suffix used by registry and ficha names."""
    return ticket.rsplit("-", 1)[-1]


def _session_name(session):
    """Return the stable registry identifier used in ``im_vivos``."""
    return str(session.get("code") or session.get("slot") or "")


def _flt_reasons(ficha_flt, flt_known, live_info):
    """Return FLT exclusion reasons for one candidate."""
    reasons = []
    if live_info["unknown"]:
        reasons.append("flt_im_desconocido")
    if live_info["missing"]:
        reasons.append("ficha_im_no_encontrada")
    if (
        flt_known
        and not live_info["unknown"]
        and not live_info["missing"]
        and any(ficha_flt & live_flt for live_flt in live_info["flts"])
    ):
        reasons.append("flt_conflicto")
    return reasons


def _decision(row, sessions, open_tickets, fichas_dir, live_info):
    """Evaluate one backlog row against shared read-only facts."""
    ticket = row["ticket"]
    state = row["state"]
    dependencies = DEPENDENCY_RE.findall(row["depends"])
    open_dependencies = [item for item in dependencies if item in open_tickets]
    retained = (
        state.casefold() == "deferred"
        or _starts_with_marker(row["title"], "[RETENIDA", "RETENIDA")
        or _starts_with_marker(row["reactivation"], "[RETENIDA", "RETENIDA")
    )
    no_tomar = _starts_with_marker(
        row["title"], "[NO TOMAR", "NO TOMAR"
    ) or _starts_with_marker(row["scope"], "[NO TOMAR", "NO TOMAR")
    diseno_primero = _starts_with_marker(
        row["title"], "[DISENO_PRIMERO", "DISENO_PRIMERO"
    )
    ficha_flt = _flt(fichas_dir / f"FICHA_WOT-2026-{_short_ticket(ticket)}.md")
    flt_known = ficha_flt is not None
    reasons = []
    notices = []
    if not flt_known:
        notices.append("flt_desconocido")
    if retained:
        reasons.append("retenida")
    if no_tomar:
        reasons.append("no_tomar")
    if diseno_primero:
        reasons.append("diseno_primero")
    if open_dependencies:
        reasons.append("dependencia_abierta")
    reasons.extend(_flt_reasons(ficha_flt, flt_known, live_info))
    if state.casefold() != "pending":
        reasons.append("estado_no_elegible")
    brief = any(
        session.get("slot") == _short_ticket(ticket) and bool(session.get("brief"))
        for session in sessions
    )
    result = {
        "ticket": ticket,
        "estado": state,
        "retenida": retained,
        "no_tomar": no_tomar,
        "diseno_primero": diseno_primero,
        "dependencias": dependencies,
        "dependencias_abiertas": open_dependencies,
        "flt_conflicto": "flt_conflicto" in reasons
        or "flt_im_desconocido" in reasons
        or "ficha_im_no_encontrada" in reasons,
        "im_vivos": live_info["names"],
        "tiene_brief": brief,
        "apta": not reasons,
        "motivos_no_apta": reasons,
        "flt_conocido": flt_known,
        "avisos": notices,
    }
    return result


def cola_apta(backlog_path, registry_path, fichas_dir=None):
    """Return deterministic eligibility decisions for backlog rows.

    Before: paths identify the backlog, registry, and optional ficha directory.
    During: read backlog and registry once, derive live IM FLTs, then evaluate
        every row in source order; no clock, network, global mutable state, or
        write operation is used.
    After: return one dictionary with exactly the contract fields per row.
    """
    backlog = Path(backlog_path)
    registry = Path(registry_path)
    fichas = Path(fichas_dir) if fichas_dir is not None else backlog.parent
    rows = _backlog_rows(backlog)
    sessions = _read_registry(registry)
    checker = _load_cell_checker()
    live = [
        session
        for session in sessions
        if session.get("role") == "implantacion"
        and checker.is_activa(session.get("status"))
    ]
    live_info = {
        "names": [_session_name(session) for session in live],
        "flts": [],
        "missing": False,
        "unknown": False,
    }
    for session in live:
        ficha = fichas / f"FICHA_WOT-2026-{session.get('slot', '')}.md"
        if not ficha.is_file():
            live_info["missing"] = True
            continue
        current_flt = _flt(ficha)
        if current_flt is None:
            live_info["unknown"] = True
        else:
            live_info["flts"].append(current_flt)
    open_tickets = {row["ticket"] for row in rows}
    return [_decision(row, sessions, open_tickets, fichas, live_info) for row in rows]
