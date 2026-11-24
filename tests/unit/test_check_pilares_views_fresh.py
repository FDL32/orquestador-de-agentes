"""Contract tests for role-scoped flight-pillar views.

Before: a canonical pillar index and its long-form source files are available
under a temporary directory.
During: generate the CO, IM and TR projections, their indices and the
freshness manifest, then exercise the fail-closed checks and rollback path.
After: generated artifacts preserve the canonical digest and scope rules;
hand edits, broken references, ambiguous aliases and hash divergence fail.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import scripts.flight.check_pilares_views_fresh as views_fresh
from scripts.flight.check_pilares_views_fresh import (
    generate_views_and_indices,
    resolve_alias,
    run_pilares_views_fresh_check,
    verify_views_fresh,
)


MESSAGE_CO = "11111111-1111-4111-8111-111111111111"
MESSAGE_IM = "22222222-2222-4222-8222-222222222222"
MESSAGE_TR = "33333333-3333-4333-8333-333333333333"

VIEW_FILES = {"CO": "vista_CO.md", "IM": "vista_IM.md", "TR": "vista_TR.md"}
MESSAGE_INDEX_FILE = "indice_messageid.md"
SOURCE_INDEX_FILE = "indice_fuente_larga.md"
ALIAS_INDEX_FILE = "alias_ids.md"


def _write_fixture_tree(root: Path) -> tuple[Path, Path]:
    """Create a small canonical index and its long-form sources.

    Before: ``root`` is an empty temporary directory.
    During: write distinct CO/IM/TR/G rows, one historical row and all source
    files referenced by the canonical index.
    After: return ``(canon_path, sources_dir)`` with UTF-8/LF content.
    """
    sources = root / "sources"
    sources.mkdir()
    for name in ("co.md", "im.md", "tr.md", "global.md", "old.md"):
        (sources / name).write_text(f"ESTADO: VIGENTE\n# {name}\n", encoding="utf-8")

    canon = root / "vuelo_pilares.md"
    canon.write_text(
        "# Índice de pilares\n"
        "| Pilar | Frase | ESTADO | messageId | fuente larga | mecanismo | a quien preguntar | ambito |\n"
        "|---|---|---|---|---|---|---|---|\n"
        f"| P1 | coordinación | RATIFICADA | {MESSAGE_CO} | sources/co.md | m | co | CO |\n"
        f"| P2 | implantación | RATIFICADA | {MESSAGE_IM} | sources/im.md | m | im | IM |\n"
        f"| P3 | triaje | RATIFICADA | {MESSAGE_TR} | sources/tr.md | m | tr | TR |\n"
        f"| P4 | global | RATIFICADA | {MESSAGE_CO} | sources/global.md | m | co | G |\n"
        "| P5 | antigua | SUPERADA |  | sources/old.md | m | co | HISTORICO |\n",
        encoding="utf-8",
        newline="\n",
    )
    return canon, sources


def _view_rows(path: Path) -> list[list[str]]:
    """Parse non-header Markdown rows from one generated view.

    Before: ``path`` points at a generated Markdown view.
    During: discard the digest header and Markdown separator.
    After: return stripped cells for each data row.
    """
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and cells[0] == "Pilar":
            continue
        rows.append(cells)
    return rows


def _read_markdown_index(path: Path) -> dict[str, object]:
    """Read a generated index stored as Markdown with JSON or table content.

    Before: ``path`` points at one of the generated Markdown indices.
    During: locate a JSON object, or parse a two-column Markdown table.
    After: return the index mapping independently of its Markdown encoding.
    """
    content = path.read_text(encoding="utf-8")
    candidates = [content]
    if "```" in content:
        candidates.extend(
            block.split("\n", 1)[1].rsplit("```", 1)[0]
            for block in content.split("```")
            if block.lstrip().startswith(("json\n", "JSON\n"))
        )
    for candidate in candidates:
        try:
            value = json.loads(candidate.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in content.splitlines()
        if line.strip().startswith("|")
    ]
    data = [row for row in rows if len(row) >= 2 and set(row[0]) != {"-"}]
    if len(data) < 2:
        raise ValueError(f"no index mapping found in {path}")
    return {
        row[0]: json.loads(row[1]) if row[1].startswith("[") else row[1]
        for row in data[1:]
    }


def _generate(root: Path) -> tuple[Path, Path, dict[str, object]]:
    """Generate the fixture projections and return their paths.

    Before: ``root`` is a temporary directory.
    During: invoke the production generator with the canonical fixture.
    After: return the canon path, output directory and generator result.
    """
    canon, _ = _write_fixture_tree(root)
    output = root / "views"
    result = generate_views_and_indices(canon_path=canon, output_dir=output)
    return canon, output, result


def test_m02_generates_only_co_im_tr_views(tmp_path: Path) -> None:
    """m-02: generate CO, IM and TR views, never G or SUP views."""
    _, output, _ = _generate(tmp_path)

    assert {path.name for path in output.glob("*.md")} >= set(VIEW_FILES.values())
    assert not (output / "g.md").exists()
    assert not (output / "sup.md").exists()


def test_m03_views_have_role_plus_global_rows_and_canon_sha(tmp_path: Path) -> None:
    """m-03: each view contains its scope plus G and no HISTORICO row."""
    canon, output, _ = _generate(tmp_path)
    digest = hashlib.sha256(canon.read_bytes()).hexdigest()

    for role, filename in VIEW_FILES.items():
        view = output / filename
        assert digest in "\n".join(view.read_text(encoding="utf-8").splitlines()[:3])
        rows = _view_rows(view)
        assert {row[-1] for row in rows} <= {role, "G"}
        assert all(row[-1] != "HISTORICO" for row in rows)
        assert {row[0] for row in rows} == {
            "P4",
            f"P{1 + (role == 'IM') + 2 * (role == 'TR')}",
        }


def test_m04_guard_compares_sha_and_fails_closed(tmp_path: Path) -> None:
    """m-04: a digest mismatch produces a non-zero guard result."""
    canon, output, _ = _generate(tmp_path)
    view = output / VIEW_FILES["CO"]
    view.write_text(
        view.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
        newline="\n",
    )

    assert verify_views_fresh(canon_path=canon, output_dir=output) is False
    assert run_pilares_views_fresh_check(canon_path=canon, output_dir=output) != 0


def test_m05_hand_edited_view_is_rejected(tmp_path: Path) -> None:
    """m-05: changing one generated cell is not accepted as fresh."""
    canon, output, _ = _generate(tmp_path)
    view = output / VIEW_FILES["CO"]
    view.write_text(
        view.read_text(encoding="utf-8").replace(
            "coordinación", "coordinación editada"
        ),
        encoding="utf-8",
        newline="\n",
    )

    assert verify_views_fresh(canon_path=canon, output_dir=output) is False


def test_m08_message_id_index_points_every_ratified_row_to_pillar(
    tmp_path: Path,
) -> None:
    """m-08: every RATIFICADA UUID is indexed with its pillar id."""
    _, output, result = _generate(tmp_path)
    index_path = output / MESSAGE_INDEX_FILE
    index = _read_markdown_index(index_path)
    assert index[MESSAGE_CO] == ["P1", "P4"] or index[MESSAGE_CO] == ["P4", "P1"]
    assert index[MESSAGE_IM] == ["P2"]
    assert index[MESSAGE_TR] == ["P3"]
    assert result is not None


def test_m09_source_index_requires_existing_long_sources(tmp_path: Path) -> None:
    """m-09: source index creation succeeds only for existing paths."""
    canon, output, _ = _generate(tmp_path)
    source_index = _read_markdown_index(output / SOURCE_INDEX_FILE)
    assert all((canon.parent / path).exists() for path in source_index.values())

    (canon.parent / "sources" / "im.md").unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        generate_views_and_indices(canon_path=canon, output_dir=tmp_path / "broken")


@pytest.mark.parametrize(
    "alias_map, alias",
    [
        ({"co": "CO", "coord": "CO", "CO": "CO"}, "co"),
        ({"co": "missing"}, "co"),
        ({"co": "im", "im": "co"}, "co"),
    ],
)
def test_m12_alias_resolution_fails_closed(
    alias_map: dict[str, str], alias: str, tmp_path: Path
) -> None:
    """m-12: ambiguous, absent and circular aliases are rejected."""
    _, output, _ = _generate(tmp_path)
    assert (output / ALIAS_INDEX_FILE).exists()
    with pytest.raises((KeyError, ValueError)):
        resolve_alias(alias, alias_map)


def test_m16_rollback_restores_originals_and_manifest_hashes(tmp_path: Path) -> None:
    """m-16: rollback restores bytes whose hashes match the manifest."""
    canon, output, _ = _generate(tmp_path)
    originals = tmp_path / "originals"
    originals.mkdir()
    original = originals / VIEW_FILES["CO"]
    original.write_bytes((output / VIEW_FILES["CO"]).read_bytes())
    manifest = {
        "files": {VIEW_FILES["CO"]: hashlib.sha256(original.read_bytes()).hexdigest()}
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    (output / VIEW_FILES["CO"]).write_text("mutated\n", encoding="utf-8", newline="\n")

    views_fresh.rollback_views(
        output_dir=output, originals_dir=originals, manifest_path=manifest_path
    )

    assert (
        hashlib.sha256((output / VIEW_FILES["CO"]).read_bytes()).hexdigest()
        == manifest["files"][VIEW_FILES["CO"]]
    )
    assert canon.exists()


def test_mutant_m02_creating_g_view_is_rejected(tmp_path: Path) -> None:
    """mutation m-02: a forbidden G view violates the generated surface."""
    canon, output, _ = _generate(tmp_path)
    (output / "g.md").write_text("forbidden\n", encoding="utf-8", newline="\n")
    assert run_pilares_views_fresh_check(canon_path=canon, output_dir=output) != 0


def test_mutant_m03_historico_row_is_rejected(tmp_path: Path) -> None:
    """mutant m-03: inserting HISTORICO into a view must fail freshness."""
    canon, output, _ = _generate(tmp_path)
    view = output / VIEW_FILES["CO"]
    view.write_text(
        view.read_text(encoding="utf-8")
        + "| P5 | antigua | SUPERADA |  | old.md | m | co | HISTORICO |\n",
        encoding="utf-8",
        newline="\n",
    )
    assert verify_views_fresh(canon_path=canon, output_dir=output) is False


def test_mutant_m08_dropping_message_id_index_entry_is_rejected(tmp_path: Path) -> None:
    """mutant m-08: omitting a RATIFICADA UUID breaks the index contract."""
    canon, output, _ = _generate(tmp_path)
    index_path = output / MESSAGE_INDEX_FILE
    index = _read_markdown_index(index_path)
    del index[MESSAGE_TR]
    index_path.write_text(json.dumps(index), encoding="utf-8", newline="\n")
    assert verify_views_fresh(canon_path=canon, output_dir=output) is False


def test_mutant_m09_broken_source_path_is_rejected(tmp_path: Path) -> None:
    """mutant m-09: a source index pointing outside the tree fails closed."""
    canon, output, _ = _generate(tmp_path)
    source_index_path = output / SOURCE_INDEX_FILE
    source_index = _read_markdown_index(source_index_path)
    source_index["P1"] = "sources/missing.md"
    source_index_path.write_text(
        json.dumps(source_index), encoding="utf-8", newline="\n"
    )
    assert verify_views_fresh(canon_path=canon, output_dir=output) is False


def test_mutant_m12_alias_cycle_is_rejected(tmp_path: Path) -> None:
    """mutant m-12: a two-node alias cycle cannot resolve."""
    _, output, _ = _generate(tmp_path)
    assert (output / ALIAS_INDEX_FILE).exists()
    with pytest.raises((KeyError, ValueError)):
        resolve_alias("co", {"co": "im", "im": "co"})


def test_mutant_m16_wrong_rollback_hash_is_rejected(tmp_path: Path) -> None:
    """mutant m-16: restoring bytes different from the manifest must fail."""
    _, output, _ = _generate(tmp_path)
    originals = tmp_path / "originals"
    originals.mkdir()
    (originals / VIEW_FILES["CO"]).write_text("wrong\n", encoding="utf-8", newline="\n")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"files": {VIEW_FILES["CO"]: "0" * 64}}),
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises((ValueError, RuntimeError)):
        views_fresh.rollback_views(
            output_dir=output, originals_dir=originals, manifest_path=manifest_path
        )


def test_m04_mutating_canon_byte_without_regenerating_fails_check(
    tmp_path: Path,
) -> None:
    """Mutating one byte of the canon without regenerating views makes check fail."""
    canon, output, _ = _generate(tmp_path)
    canon.write_text(
        canon.read_text(encoding="utf-8") + "\n<!-- mutant -->\n",
        encoding="utf-8",
        newline="\n",
    )
    assert verify_views_fresh(canon_path=canon, output_dir=output) is False
    rc, _ = run_pilares_views_fresh_check(canon_path=canon, output_dir=output)
    assert rc != 0


def test_m06_guard_is_wired_in_prepush_and_integrate_ticket() -> None:
    """Verify check_pilares_views_fresh is wired in prepush_check and integrate_ticket (m-06)."""
    import scripts.check_guard_wiring as cgw

    edges = cgw.wiring_edges(cgw.MOTOR_ROOT)
    guard_edges = edges.get("check_pilares_views_fresh", set())
    assert "scripts/prepush_check.py" in guard_edges
    assert "scripts/flight/integrate_ticket.py" in guard_edges


def test_mutant_m06_removing_call_in_prepush_puts_wiring_in_red() -> None:
    """Mutant m-06: removing the call in a prepush_check copy puts check_guard_wiring in red."""
    import scripts.check_guard_wiring as cgw

    prepush = (cgw.MOTOR_ROOT / "scripts" / "prepush_check.py").read_text(
        encoding="utf-8"
    )
    assert "check_pilares_views_fresh" in prepush
    mutated = prepush.replace(
        "check_pilares_views_fresh", "check_unrelated_views_fresh"
    )
    invocations = [base for base, _ln in cgw._python_invocations(mutated)]
    assert "check_pilares_views_fresh.py" not in invocations
