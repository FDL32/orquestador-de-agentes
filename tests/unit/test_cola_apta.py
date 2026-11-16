"""Tests for the route-loaded backlog queue checker.

Before: temporary backlog, registry, and ficha files provide all input data.
During: tests load the implementation by path and exercise each contract branch.
After: queue decisions, loader caching, FLT rules, and read-only behavior are
verified without touching live flight files.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "flight" / "cola_apta.py"
)


def _load_cola():
    """Load the checker by path and cache its module in sys.modules.

    Before: the source path points to the new checker.
    During: reuse the canonical module name and cache entry.
    After: return the same module object on repeated loads.
    """
    name = "cola_apta"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _row(
    ticket,
    title="Clean",
    scope="scope",
    state="pending",
    depends="-",
    reactivation="-",
):
    """Build one row of the eight-column backlog table."""
    return (
        f"| High | {ticket} | {title} | {scope} | {state} | {depends} | test | "
        f"{reactivation} |"
    )


def _files_section(paths):
    """Build the exact FLT section understood by the contract."""
    return "## Files Likely Touched\n" + "\n".join(f"- {path}" for path in paths)


def _fixture(tmp_path, rows=None, sessions=None, ficha_paths=None, ficha_text=None):
    """Create isolated input files, returning their paths and ficha directory."""
    rows = rows or [_row("WOT-2026-100a")]
    sessions = sessions or []
    backlog = tmp_path / "backlog.md"
    backlog.write_text(
        "| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    registry = tmp_path / "session_registry.json"
    registry.write_text(json.dumps({"sessions": sessions}), encoding="utf-8")
    fichas = tmp_path / "fichas"
    fichas.mkdir()
    if ficha_paths is not None:
        for ticket, paths in ficha_paths.items():
            (fichas / f"FICHA_WOT-2026-{ticket}.md").write_text(
                _files_section(paths), encoding="ascii"
            )
    if ficha_text is not None:
        (fichas / "FICHA_WOT-2026-100a.md").write_text(ficha_text, encoding="ascii")
    return backlog, registry, fichas


def test_determinismo_and_row_order(tmp_path):
    """Before: rows are ordered differently from their ticket names.

    During: call the checker twice with identical paths.
    After: both lists match and retain source row order.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(
        tmp_path,
        rows=[_row("WOT-2026-100b"), _row("WOT-2026-100a")],
    )
    first = module.cola_apta(backlog, registry, fichas)
    second = module.cola_apta(backlog, registry, fichas)
    assert first == second
    assert [item["ticket"] for item in first] == ["WOT-2026-100b", "WOT-2026-100a"]


def test_exclusion_retenida(tmp_path):
    """Before: the state is deferred.

    During: evaluate one candidate.
    After: retained is the exclusion reason.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(
        tmp_path, rows=[_row("WOT-2026-100a", "[RETENIDA] old")]
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert (
        item["retenida"]
        and not item["apta"]
        and item["motivos_no_apta"] == ["retenida"]
    )


def test_exclusion_no_tomar(tmp_path):
    """Before: title starts with the no-take marker.

    During: evaluate the marker at the start of the cell.
    After: no_tomar excludes the row.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(
        tmp_path, rows=[_row("WOT-2026-100a", "[NO TOMAR] old")]
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["no_tomar"] and item["motivos_no_apta"] == ["no_tomar"]


def test_exclusion_deferred_state_is_retenida(tmp_path):
    """Before: the row state is deferred and its cells have no marker.

    During: evaluate the state branch of D-1.
    After: deferred is retained and excluded for that reason.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(
        tmp_path, rows=[_row("WOT-2026-100a", state="deferred")]
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["retenida"] and "retenida" in item["motivos_no_apta"]


def test_exclusion_reactivation_marker(tmp_path):
    """Before: Reactivation starts with the retained marker.

    During: evaluate the Reactivation disjunct of D-1.
    After: the row is retained and excluded.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(
        tmp_path, rows=[_row("WOT-2026-100a", reactivation="RETENIDA until later")]
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["retenida"] and item["motivos_no_apta"] == ["retenida"]


def test_exclusion_no_tomar_scope(tmp_path):
    """Before: Scope starts with the no-take marker.

    During: evaluate the Scope disjunct of D-2.
    After: no_tomar excludes the row.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(
        tmp_path, rows=[_row("WOT-2026-100a", scope="NO TOMAR this row")]
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["no_tomar"] and item["motivos_no_apta"] == ["no_tomar"]


def test_markers_in_middle_do_not_exclude(tmp_path):
    """Before: retained and no-take words occur only inside cells.

    During: evaluate the marker predicates at their cell starts.
    After: neither marker excludes the pending row.
    """
    module = _load_cola()
    row = _row(
        "WOT-2026-100a",
        title="A RETENIDA note",
        scope="A NO TOMAR note",
        reactivation="A RETENIDA note",
    )
    backlog, registry, fichas = _fixture(tmp_path, rows=[row])
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert not item["retenida"] and not item["no_tomar"] and item["apta"]


def test_exclusion_diseno_primero(tmp_path):
    """Before: both supported design-first spellings are present.

    During: evaluate each row independently.
    After: both rows carry only the design-first exclusion.
    """
    module = _load_cola()
    rows = [
        _row("WOT-2026-100a", "[DISENO_PRIMERO] a"),
        _row("WOT-2026-100b", "DISENO_PRIMERO b"),
    ]
    backlog, registry, fichas = _fixture(tmp_path, rows=rows)
    items = module.cola_apta(backlog, registry, fichas)
    assert all(item["motivos_no_apta"] == ["diseno_primero"] for item in items)


def test_exclusion_dependencia_abierta(tmp_path):
    """Before: a dependency has a live backlog row.

    During: parse the dependency and resolve it against the table.
    After: the dependency is reported open and excludes the candidate.
    """
    module = _load_cola()
    rows = [_row("WOT-2026-100a", depends="WOT-2026-100b"), _row("WOT-2026-100b")]
    backlog, registry, fichas = _fixture(tmp_path, rows=rows)
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["dependencias_abiertas"] == ["WOT-2026-100b"]
    assert "dependencia_abierta" in item["motivos_no_apta"]


def test_dependency_with_dec_prefix_is_ignored(tmp_path):
    """Before: Depends on contains a decision-prefixed WOT identifier.

    During: apply the dependency regex boundary rule.
    After: the decision reference is not parsed and does not block the row.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(
        tmp_path, rows=[_row("WOT-2026-100a", depends="DEC-WOT-2026-047b")]
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["dependencias"] == []
    assert item["dependencias_abiertas"] == [] and item["apta"]


def test_dependency_without_live_backlog_row_is_not_open(tmp_path):
    """Before: Depends on names an identifier absent from the live backlog.

    During: resolve parsed dependencies against current backlog ticket rows.
    After: the absent dependency is not open and the row remains apta.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(
        tmp_path, rows=[_row("WOT-2026-100a", depends="WOT-2026-999z")]
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["dependencias"] == ["WOT-2026-999z"]
    assert item["dependencias_abiertas"] == [] and item["apta"]


def test_exclusion_flt_conflicto_and_parameter(tmp_path):
    """Before: only the explicit fichas_dir has an overlapping live IM FLT.

    During: pass that directory instead of the backlog parent.
    After: the candidate conflicts, proving the argument is not ignored.
    """
    module = _load_cola()
    session = {
        "code": "IM-1",
        "role": "implantacion",
        "slot": "200a",
        "status": "ACTIVA",
    }
    backlog, registry, fichas = _fixture(
        tmp_path,
        sessions=[session],
        ficha_paths={"200a": ["scripts/flight/cola_apta.py"]},
    )
    (tmp_path / "FICHA_WOT-2026-100a.md").write_text(
        _files_section(["other/module.py"]), encoding="ascii"
    )
    (fichas / "FICHA_WOT-2026-100a.md").write_text(
        _files_section(["scripts/flight/cola_apta.py"]), encoding="ascii"
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["flt_conflicto"] and "flt_conflicto" in item["motivos_no_apta"]


def test_flt_triaje_does_not_count_as_live_im(tmp_path):
    """Before: a triaje session is ACTIVA and its ficha overlaps the candidate.

    During: evaluate the role filter before reading live IM FLTs.
    After: the triaje is absent from im_vivos and the candidate remains apta.
    """
    module = _load_cola()
    session = {"code": "TR-1", "role": "triaje", "slot": "200a", "status": "ACTIVA"}
    paths = {
        "100a": ["scripts/flight/cola_apta.py"],
        "200a": ["scripts/flight/cola_apta.py"],
    }
    backlog, registry, fichas = _fixture(
        tmp_path, sessions=[session], ficha_paths=paths
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["im_vivos"] == []
    assert not item["flt_conflicto"] and item["apta"]


def test_flt_live_im_disjoint_keeps_candidate_apta(tmp_path):
    """Before: a live IM has a known FLT disjoint from the candidate.

    During: compare the candidate and live-IM route sets.
    After: the candidate remains apta with a known, non-conflicting FLT.
    """
    module = _load_cola()
    session = {
        "code": "IM-1",
        "role": "implantacion",
        "slot": "200a",
        "status": "ACTIVA",
    }
    paths = {"100a": ["candidate.py"], "200a": ["other.py"]}
    backlog, registry, fichas = _fixture(
        tmp_path, sessions=[session], ficha_paths=paths
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["flt_conocido"] and not item["flt_conflicto"] and item["apta"]


def test_flt_header_suffix_still_reads_routes(tmp_path):
    """Before: the candidate FLT heading has a parenthetical suffix.

    During: parse the heading by its normative prefix.
    After: its routes are known and an overlapping live IM conflicts.
    """
    module = _load_cola()
    session = {
        "code": "IM-1",
        "role": "implantacion",
        "slot": "200a",
        "status": "ACTIVA",
    }
    backlog, registry, fichas = _fixture(tmp_path, sessions=[session])
    suffix = "## 6 Files Likely Touched (T-A = WOT-2026-100a; owner)\n- shared.py\n"
    (fichas / "FICHA_WOT-2026-100a.md").write_text(suffix, encoding="ascii")
    (fichas / "FICHA_WOT-2026-200a.md").write_text(
        _files_section(["shared.py"]), encoding="ascii"
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["flt_conocido"] and item["flt_conflicto"]


def test_exclusion_estado_no_elegible(tmp_path):
    """Before: the candidate is blocked.

    During: apply the pending-only eligibility rule.
    After: state_no_elegible excludes the row.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(
        tmp_path, rows=[_row("WOT-2026-100a", state="blocked")]
    )
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert item["motivos_no_apta"] == ["estado_no_elegible"]


def test_brief_and_sin_brief_are_informative(tmp_path):
    """Before: one slot has a brief and another slot has none.

    During: evaluate both pending rows.
    After: brief status never changes apta.
    """
    module = _load_cola()
    rows = [_row("WOT-2026-100a"), _row("WOT-2026-100b")]
    sessions = [
        {
            "slot": "100a",
            "brief": "brief.md",
            "role": "implantacion",
            "status": "ASENTADA",
        }
    ]
    backlog, registry, fichas = _fixture(tmp_path, rows=rows, sessions=sessions)
    items = module.cola_apta(backlog, registry, fichas)
    assert items[0]["tiene_brief"] and items[0]["apta"]
    assert not items[1]["tiene_brief"] and items[1]["apta"]


def test_loader_uses_same_cached_module(tmp_path):
    """Before: the route loader has no cached module.

    During: load twice using the measured import pattern.
    After: both loads return the same module object.
    """
    sys.modules.pop("cola_apta", None)
    first = _load_cola()
    second = _load_cola()
    assert first is second
    assert callable(first.cola_apta)


def test_flt_unknown_is_visible_but_not_excluding(tmp_path):
    """Before: the candidate has no ficha FLT.

    During: evaluate the fail-open candidate rule.
    After: flt_desconocido is an aviso, not a blocking reason.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(tmp_path)
    item = module.cola_apta(backlog, registry, fichas)[0]
    assert not item["flt_conocido"]
    assert item["apta"] and item["avisos"] == ["flt_desconocido"]


def test_flt_im_missing_or_unknown_fails_closed(tmp_path):
    """Before: a live IM has either no ficha or an empty FLT section.

    During: evaluate both fail-closed cases.
    After: each case excludes with its precise diagnostic.
    """
    module = _load_cola()
    session = {
        "code": "IM-1",
        "role": "implantacion",
        "slot": "200a",
        "status": "ACTIVA",
    }
    backlog, registry, fichas = _fixture(tmp_path, sessions=[session])
    missing = module.cola_apta(backlog, registry, fichas)[0]
    assert "ficha_im_no_encontrada" in missing["motivos_no_apta"]
    (fichas / "FICHA_WOT-2026-200a.md").write_text("# No FLT\n", encoding="ascii")
    unknown = module.cola_apta(backlog, registry, fichas)[0]
    assert "flt_im_desconocido" in unknown["motivos_no_apta"]


def test_fuente_unica_ignores_non_flt_ficha_text(tmp_path):
    """Before: a ficha exists but only its non-FLT text changes.

    During: compare decisions before and after that edit.
    After: all output fields remain identical.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(
        tmp_path, ficha_text="# state pending brief fake\n"
    )
    before = module.cola_apta(backlog, registry, fichas)
    (fichas / "FICHA_WOT-2026-100a.md").write_text(
        "# state blocked brief changed\n", encoding="ascii"
    )
    after = module.cola_apta(backlog, registry, fichas)
    assert before == after


def test_hash_input_files_unchanged(tmp_path):
    """Before: input files have recorded hashes.

    During: invoke the checker repeatedly.
    After: both input hashes are unchanged.
    """
    module = _load_cola()
    backlog, registry, fichas = _fixture(tmp_path)

    def digest(path):
        return hashlib.sha256(path.read_bytes()).digest()

    before = (digest(backlog), digest(registry))
    module.cola_apta(backlog, registry, fichas)
    module.cola_apta(backlog, registry, fichas)
    assert before == (digest(backlog), digest(registry))


def test_noncanonical_ticket_rows_are_preserved(tmp_path):
    """Before: data rows include noncanonical ticket identifiers.

    During: parse every data row without a ticket regex filter.
    After: all rows appear in their original order.
    """
    module = _load_cola()
    rows = [
        _row("DEC-WOT-2026-047b"),
        _row("WOT-2026-STATE-RECON-A"),
        _row("WOT-2026-STATE-RECON-B"),
    ]
    backlog, registry, fichas = _fixture(tmp_path, rows=rows)
    items = module.cola_apta(backlog, registry, fichas)
    assert [item["ticket"] for item in items] == [
        row.split("|")[2].strip() for row in rows
    ]


def test_separator_row_is_not_a_backlog_entry(tmp_path):
    """Before: the fixture contains the real Markdown separator row.

    During: parse the table with one separator and two data rows.
    After: only data rows are returned, in their original order.
    """
    module = _load_cola()
    rows = [_row("WOT-2026-100b"), _row("WOT-2026-100a")]
    backlog, registry, fichas = _fixture(tmp_path, rows=rows)
    items = module.cola_apta(backlog, registry, fichas)
    assert len(items) == len(rows)
    assert [item["ticket"] for item in items] == [
        "WOT-2026-100b",
        "WOT-2026-100a",
    ]
