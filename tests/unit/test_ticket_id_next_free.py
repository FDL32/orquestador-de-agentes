"""Tests del helper de siguiente id libre (WOT-2026-040f).

Los tests usan worktrees reales en ``tmp_path`` con cola viva + archive, y
fuerzan transiciones reales: la politica de sucesor del maximo global, el
cruce de AMBAS superficies y la mutation (id cerrado solo en el archive no se
propone).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import zlib
from pathlib import Path

import pytest
from bus.ticket_id import (
    TICKET_ID_RE,
    RefScan,
    collect_surface_ticket_ids,
    next_free_ticket_id,
    scan_ref_ticket_ids,
)


def _collab(tmp_path: Path, live: str = "", archive: str = "") -> Path:
    """Monta un directorio .agent/collaboration con backlog.md y el archive."""
    collab = tmp_path / "collaboration"
    collab.mkdir(parents=True)
    archive_dir = collab / "_archive"
    archive_dir.mkdir()
    (collab / "backlog.md").write_text(live, encoding="utf-8")
    (collab / "_archive" / "backlog_done.md").write_text(archive, encoding="utf-8")
    return collab


def _git(repo: Path, *args: str) -> str:
    """Run one real git command in a test repository."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_input(repo: Path, args: tuple[str, ...], payload: bytes) -> str:
    """Run real git with a binary stdin payload and return decoded stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=payload,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8").strip()


def _read_git_object(repo: Path, sha: str) -> tuple[str, bytes]:
    """Read one loose Git object from the real temporary repository."""
    raw = zlib.decompress((repo / ".git" / "objects" / sha[:2] / sha[2:]).read_bytes())
    header, payload = raw.split(b"\0", 1)
    kind, _, size = header.decode().partition(" ")
    assert int(size) == len(payload)
    return kind, payload


def _write_git_object(repo: Path, kind: str, payload: bytes) -> str:
    """Write one valid loose Git object without bypassing Git object format."""
    raw = f"{kind} {len(payload)}\0".encode() + payload
    sha = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
    target = repo / ".git" / "objects" / sha[:2] / sha[2:]
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(zlib.compress(raw))
    return sha


def _tree_entries(repo: Path, sha: str) -> list[tuple[bytes, bytes, bytes]]:
    """Decode a real Git tree into mode, name, and raw object SHA tuples."""
    kind, payload = _read_git_object(repo, sha)
    assert kind == "tree"
    entries = []
    rest = payload
    while rest:
        mode, _, rest = rest.partition(b" ")
        name, _, rest = rest.partition(b"\0")
        entries.append((mode, name, rest[:20]))
        rest = rest[20:]
    return entries


def _write_tree_with(
    repo: Path, tree: str, name: bytes, replacement: tuple[bytes, bytes]
) -> str:
    """Write a tree replacing one entry while preserving all other entries."""
    replacement_mode, sha_hex = replacement
    entries = []
    for old_mode, entry_name, sha in _tree_entries(repo, tree):
        if entry_name == name:
            entries.append((replacement_mode, entry_name, bytes.fromhex(sha_hex)))
        else:
            entries.append((old_mode, entry_name, sha))
    return _write_git_object(
        repo,
        "tree",
        b"".join(
            mode + b" " + entry_name + b"\0" + sha for mode, entry_name, sha in entries
        ),
    )


def _git_collab(tmp_path: Path, live: str = "", archive: str = "") -> tuple[Path, Path]:
    """Create a real git repository with the two collaboration surfaces."""
    repo = tmp_path / "repo"
    collab = repo / ".agent" / "collaboration"
    (collab / "_archive").mkdir(parents=True)
    (collab / "backlog.md").write_text(live, encoding="utf-8")
    (collab / "_archive" / "backlog_done.md").write_text(archive, encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "ticket-id-tests")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    return repo, collab


def _append_row_and_commit(repo: Path, collab: Path, row: str, message: str) -> str:
    """Append one row to the live surface and return its commit SHA."""
    path = collab / "backlog.md"
    path.write_text(path.read_text(encoding="utf-8") + row, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def test_next_free_base_case_no_ids(tmp_path):
    """Sin ids del prefijo/ano en NINGUNA superficie -> <PREFIX>-<YEAR>-001a."""
    collab = _collab(tmp_path, live="| Ticket |\n|---|---|\n", archive="")
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-001a"


def test_next_free_advances_letter_after_max(tmp_path):
    """El maximo global (400, x) en la COLA VIVA -> siguiente letra 400y."""
    collab = _collab(
        tmp_path,
        live=(
            "| Prioridad | Ticket |\n|---|---|\n"
            "| Media | WOT-2026-400w | ficha live |\n"
            "| Media | WOT-2026-400x | ficha live |\n"
        ),
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-400y"


def test_next_free_skips_archived_id_mutation(tmp_path):
    """MUTATION (DoD c): un id CERRADO solo en el archive NO se propone.

    El fallo que este helper previene (WOT-2026-027t): con `400x` solo en
    `_archive/backlog_done.md` (ausente en la cola viva), un calculo que mirara
    UNA sola superficie lo propondria. El helper barre AMBAS y devuelve el
    sucesor del maximo global, no el id ocupado.
    """
    collab = _collab(
        tmp_path,
        live="| Ticket |\n|---|---|\n| WOT-2026-400w | pendiente |\n",
        archive=(
            "| Ticket | Estado | Nota |\n|---|---|---|\n"
            "| WOT-2026-400x | completed | cerrado |\n"
        ),
    )
    result = next_free_ticket_id("WOT", 2026, collab)
    assert result != "WOT-2026-400x", (
        "el id cerrado en el archive se esta proponiendo: la asignacion barre "
        f"una sola superficie; resultado real: {result}"
    )
    assert result == "WOT-2026-400y"


def test_next_free_successor_wins_over_lower_live_gap(tmp_path):
    """La politica es sucesor del maximo global, NO rellenar huecos.

    Con `400a` y `400n` en la cola viva, el maximo global por (numero, letra) es
    `400n` y hay huecos (`400b`..`400m`). El siguiente es `400o`, NO `400b`: la
    politica declarada no rellena huecos historicos sino que avanza desde el
    maximo.
    """
    collab = _collab(
        tmp_path,
        live=(
            "| Ticket |\n|---|---|\n"
            "| WOT-2026-400a | inicial |\n"
            "| WOT-2026-400n | maximo |\n"
        ),
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-400o"


def test_next_free_letter_z_advances_number(tmp_path):
    """`400z` -> el siguiente numero `401a` (no se sale del alfabeto)."""
    collab = _collab(
        tmp_path,
        live="| Ticket |\n|---|---|\n| WOT-2026-400z | maximo |\n",
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-401a"


def test_next_free_pure_numeric_legacy_advances_number(tmp_path):
    """Un id legacy `400` sin letra -> siguiente numero `401a` (WT-2026-251a)."""
    collab = _collab(
        tmp_path,
        live="| Ticket |\n|---|---|\n| WOT-2026-400 | legacy sin letra |\n",
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-401a"


def test_next_free_filters_by_prefix_and_year(tmp_path):
    """Un id de OTRO prefijo o ano no cuenta para el maximo global."""
    collab = _collab(
        tmp_path,
        live=(
            "| Ticket |\n|---|---|\n"
            "| CTL-2026-900z | otro prefijo |\n"
            "| WOT-2025-100z | otro ano |\n"
        ),
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-001a"


def test_next_free_ignores_prose_ticket_ids_in_rows(tmp_path):
    """Solo las celdas de ticket cuentan; una mencion en el titulo no."""
    collab = _collab(
        tmp_path,
        live=(
            "| Prioridad | Ticket | Titulo |\n|---|---|---|\n"
            "| Media | WOT-2026-160b | ficha que menciona WOT-2026-999z |\n"
        ),
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-160c"


def test_next_free_ignores_ticket_ids_after_ticket_cells(tmp_path):
    """Un ID en la tercera celda es prosa y no ocupa el siguiente ID."""
    collab = _collab(
        tmp_path,
        live=(
            "| Prioridad | Nota | Titulo |\n|---|---|---|\n"
            "| Media | sin ticket | WOT-2026-999z |\n"
        ),
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-001a"


def test_next_free_ignores_ticket_ids_outside_table_rows(tmp_path):
    """Una mencion fuera de una fila markdown no ocupa un ID."""
    collab = _collab(tmp_path, live="Nota: WOT-2026-999z ya fue descartado.\n")
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-001a"


def test_next_free_row_parser_respects_escaped_pipes(tmp_path):
    """Un pipe escapado permanece dentro de la celda del ticket."""
    collab = _collab(
        tmp_path,
        live=(
            "| Prioridad | Ticket | Titulo |\n|---|---|---|\n"
            r"| Media | WOT-2026-400x\| variante | ficha |" + "\n"
        ),
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-400y"


def test_next_free_row_parser_handles_escaped_pipe_before_ticket_cell(tmp_path):
    """Un pipe escapado en la primera celda no desplaza la celda de ticket."""
    collab = _collab(
        tmp_path,
        live=(
            "| Prioridad | Ticket | Titulo |\n|---|---|---|\n"
            r"| Media\| variante | WOT-2026-400x | ficha |" + "\n"
        ),
        archive="",
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-400y"


def test_next_free_include_refs_false_ignores_prose_ticket_ids(tmp_path):
    """include_refs=False conserva la regla de excluir IDs de prosa."""
    collab = _collab(
        tmp_path,
        live=(
            "| Prioridad | Ticket | Titulo |\n|---|---|---|\n"
            "| Media | WOT-2026-160b | ficha WOT-2026-999z |\n"
        ),
    )
    assert (
        next_free_ticket_id("WOT", 2026, collab, include_refs=False) == "WOT-2026-160c"
    )


def test_collect_surface_ticket_ids_crosses_both_surfaces(tmp_path):
    """El enumerador compartido lee AMBAS superficies en una sola llamada."""
    collab = _collab(
        tmp_path,
        live="| Ticket |\n|---|---|\n| WOT-2026-400a | viva |\n",
        archive=("| Ticket |\n|---|---|\n| WOT-2026-401z | archivada |\n"),
    )
    ids = collect_surface_ticket_ids(collab)
    assert ids == {"WOT-2026-400a", "WOT-2026-401z"}


def test_next_free_skips_archived_id_if_only_archive_has_higher(tmp_path):
    """Caso espejo del 027t: el id cerrado es el MAXIMO absoluto del archive."""
    collab = _collab(
        tmp_path,
        live="| Ticket |\n|---|---|\n| WOT-2026-400w | pendiente |\n",
        archive=("| Ticket | Estado |\n|---|---|\n| WOT-2026-401a | completed |\n"),
    )
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-401b"


def test_scan_ref_ticket_ids_reads_distinct_branch_ids(tmp_path):
    """Una rama con un ID mayor cambia el sucesor y publica el denominador."""
    repo, collab = _git_collab(
        tmp_path,
        live="| Ticket | Estado |\n|---|---|\n| WOT-2026-100a | pending |\n",
    )
    _git(repo, "checkout", "-qb", "rama-mayor")
    _append_row_and_commit(
        repo,
        collab,
        "| Ticket | Estado |\n|---|---|\n| WOT-2026-200a | pending |\n",
        "higher ticket",
    )
    _git(repo, "checkout", "-q", "main")

    scan = scan_ref_ticket_ids(repo / ".agent" / "collaboration")

    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-200b"
    assert (
        next_free_ticket_id("WOT", 2026, collab, include_refs=False) == "WOT-2026-100b"
    )
    assert {"WOT-2026-100a", "WOT-2026-200a"} <= scan.ids
    assert scan.refs == 2
    assert scan.tips == 2
    assert scan.ids_solo_en_refs == {"WOT-2026-200a"}
    assert scan.blobs_leidos == 3
    assert "refs remotas posiblemente caducadas (sin fetch)" in scan.avisos


def test_next_free_includes_uncommitted_working_tree_rows_with_refs(tmp_path):
    """Una fila sin commit se une a refs leídas y conserva el control HEAD."""
    _repo, collab = _git_collab(
        tmp_path,
        live="| Ticket | Estado |\n|---|---|\n| WOT-2026-100a | pending |\n",
    )
    path = collab / "backlog.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "| Ticket | Estado |\n|---|---|\n| WOT-2026-100b | pending |\n",
        encoding="utf-8",
    )

    scan = scan_ref_ticket_ids(collab)

    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-100c"
    assert (
        next_free_ticket_id("WOT", 2026, collab, include_refs=False) == "WOT-2026-100c"
    )
    assert scan.ids == {"WOT-2026-100a"}
    assert scan.ids_solo_en_refs == set()


def test_scan_ref_ticket_ids_deduplicates_same_tip_and_same_row(tmp_path):
    """Refs al mismo tip no duplican blobs ni convierten la fila en nueva."""
    repo, collab = _git_collab(
        tmp_path,
        live="| Ticket | Estado |\n|---|---|\n| WOT-2026-100a | pending |\n",
    )
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/heads/rama-misma-fila", head)
    scan = scan_ref_ticket_ids(collab)

    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-100b"
    assert scan.ids == {"WOT-2026-100a"}
    assert scan.ids_solo_en_refs == set()
    assert scan.refs == 2
    assert scan.tips == 1
    assert scan.blobs_leidos == 2


def test_scan_ref_ticket_ids_includes_detached_head_tip(tmp_path):
    """HEAD separado aporta su tip aunque no exista una ref que lo nombre."""
    repo, collab = _git_collab(
        tmp_path,
        live="| Ticket | Estado |\n|---|---|\n| WOT-2026-100a | pending |\n",
    )
    _git(repo, "checkout", "-qb", "rama-head")
    head_sha = _append_row_and_commit(
        repo,
        collab,
        "| Ticket | Estado |\n|---|---|\n| WOT-2026-100b | pending |\n",
        "detached head ticket",
    )
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "--detach", head_sha)
    _git(repo, "branch", "-D", "rama-head")
    (collab / "backlog.md").write_text(
        "| Ticket | Estado |\n|---|---|\n| WOT-2026-100a | pending |\n",
        encoding="utf-8",
    )

    scan = scan_ref_ticket_ids(collab)

    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-100c"
    assert {"WOT-2026-100a", "WOT-2026-100b"} <= scan.ids
    assert scan.tips == 2


def test_scan_ref_ticket_ids_handles_unreadable_local_surface(tmp_path):
    """Una superficie local ilegible degrada con aviso y no lanza."""
    _repo, collab = _git_collab(
        tmp_path,
        live="| Ticket | Estado |\n|---|---|\n| WOT-2026-120a | pending |\n",
    )
    (collab / "backlog.md").unlink()
    (collab / "backlog.md").mkdir()

    scan = scan_ref_ticket_ids(collab)

    assert scan.ids == {"WOT-2026-120a"}
    assert any("superficie HEAD no disponible" in aviso for aviso in scan.avisos)
    assert scan.ids_solo_en_refs == frozenset()
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-120b"


def test_scan_ref_ticket_ids_volume_does_not_block_on_cat_file_pipes(tmp_path):
    """400 distinct 300-KB blobs finish within a hard subprocess deadline."""
    repo, collab = _git_collab(
        tmp_path,
        live="| Ticket | Estado |\n|---|---|\n| WOT-2026-100a | pending |\n",
    )
    base = _git(repo, "rev-parse", "HEAD")
    root = _git(repo, "rev-parse", f"{base}^{{tree}}")
    agent = _git(repo, "rev-parse", f"{base}:.agent")
    collab_tree = _git(repo, "rev-parse", f"{base}:.agent/collaboration")
    for index in range(400):
        body = (
            "| Ticket | Estado |\n|---|---|\n"
            f"| WOT-2026-{index + 200:03d}a | pending |\n" + "x" * 300_000
        ).encode()
        blob = _write_git_object(repo, "blob", body)
        new_collab = _write_tree_with(
            repo, collab_tree, b"backlog.md", (b"100644", blob)
        )
        new_agent = _write_tree_with(
            repo, agent, b"collaboration", (b"040000", new_collab)
        )
        new_root = _write_tree_with(repo, root, b".agent", (b"040000", new_agent))
        commit_payload = (
            f"tree {new_root}\nparent {base}\n"
            "author ticket-id-tests <tests@example.invalid> 0 +0000\n"
            "committer ticket-id-tests <tests@example.invalid> 0 +0000\n\n"
            "volume surface\n"
        ).encode()
        commit = _write_git_object(repo, "commit", commit_payload)
        ref = repo / ".git" / "refs" / "heads" / f"volume-{index:03d}"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(commit + "\n", encoding="ascii")

    script = (
        "from pathlib import Path; "
        "from bus.ticket_id import scan_ref_ticket_ids; "
        "print(scan_ref_ticket_ids(Path(__import__('sys').argv[1])).blobs_leidos)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(collab)],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    output: dict[str, bytes] = {}

    def wait_for_scan() -> None:
        output["stdout"], output["stderr"] = process.communicate()

    waiter = threading.Thread(target=wait_for_scan, daemon=True)
    waiter.start()
    waiter.join(timeout=8)
    if waiter.is_alive():
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
        else:
            process.kill()
        waiter.join(timeout=3)
        pytest.fail("scan_ref_ticket_ids excedio el limite duro de 8 s")
    assert process.returncode == 0, output.get("stderr", b"").decode()
    assert output["stdout"].strip() == b"402"


def test_scan_ref_ticket_ids_deduplicates_identical_surface_blobs_across_tips(
    tmp_path,
):
    """Tips distintos con superficies idénticas leen solo dos blobs."""
    repo, collab = _git_collab(
        tmp_path,
        live="| Ticket | Estado |\n|---|---|\n| WOT-2026-100a | pending |\n",
    )
    _git(repo, "checkout", "-qb", "rama-distinta")
    (repo / "unrelated.txt").write_text("contenido ajeno\n", encoding="utf-8")
    _git(repo, "add", "unrelated.txt")
    _git(repo, "commit", "-qm", "unrelated change")
    _git(repo, "checkout", "-q", "main")

    scan = scan_ref_ticket_ids(collab)

    assert scan.tips == 2
    assert scan.blobs_leidos == 2


def test_scan_ref_ticket_ids_reads_simulated_remote_and_ignores_symbolic_ref(tmp_path):
    """Una remote simulada cuenta y su ref simbolica no cuenta como tip."""
    repo, collab = _git_collab(
        tmp_path,
        live="| Ticket | Estado |\n|---|---|\n| WOT-2026-100a | pending |\n",
    )
    _git(repo, "checkout", "-qb", "rama-remota")
    remote_sha = _append_row_and_commit(
        repo,
        collab,
        "| Ticket | Estado |\n|---|---|\n| WOT-2026-300a | pending |\n",
        "remote ticket",
    )
    _git(repo, "checkout", "-q", "main")
    _git(repo, "update-ref", "refs/remotes/origin/rama-remota", remote_sha)
    _git(
        repo,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/rama-remota",
    )
    _git(repo, "branch", "-D", "rama-remota")
    _git(repo, "branch", "sesión-é")

    scan = scan_ref_ticket_ids(collab)

    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-300b"
    assert scan.refs == 3
    assert scan.tips == 2
    assert "WOT-2026-300a" in scan.ids_solo_en_refs


def test_scan_ref_ticket_ids_tolerates_missing_surfaces(tmp_path):
    """Una superficie ausente no impide leer la otra en cada tip."""
    repo, collab = _git_collab(
        tmp_path,
        archive="| Ticket | Estado |\n|---|---|\n| WOT-2026-150a | done |\n",
    )
    (collab / "backlog.md").unlink()
    _git(repo, "add", "-u")
    _git(repo, "commit", "-qm", "remove live surface")

    scan = scan_ref_ticket_ids(collab)

    assert scan.ids == {"WOT-2026-150a"}
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-150b"


def test_scan_ref_ticket_ids_fail_open_without_git(tmp_path):
    """Sin repositorio git conserva HEAD y publica avisos deterministas."""
    collab = _collab(
        tmp_path,
        live="| Ticket | Estado |\n|---|---|\n| WOT-2026-120a | pending |\n",
    )

    scan = scan_ref_ticket_ids(collab)

    assert scan.ids == {"WOT-2026-120a"}
    assert scan.refs == 0
    assert scan.tips == 0
    assert scan.blobs_leidos == 0
    assert next_free_ticket_id("WOT", 2026, collab) == "WOT-2026-120b"
    assert any("lectura de refs no disponible" in aviso for aviso in scan.avisos)
    assert any("refs remotas posiblemente caducadas" in aviso for aviso in scan.avisos)


def test_ref_scan_is_frozen():
    """RefScan expone un denominador inmutable para el informe del barrido."""
    scan = RefScan(frozenset(), (), 0, 0, frozenset(), ())
    try:
        scan.refs = 1
    except AttributeError:
        pass
    else:
        raise AssertionError("RefScan debe ser congelada")


def test_row_parser_parity_with_backlog_admission(tmp_path):
    """La forma de fila del bus coincide con el guard en un corpus controlado."""
    from bus.ticket_id import _row_ticket_ids_from_line
    from scripts.check_backlog_admission import row_line_ids

    corpus = [
        "| Media | WOT-2026-160b | titulo WOT-2026-999z |",
        r"| Media | WOT-2026-160b\|variante | titulo |",
        "| Media | nota | WOT-2026-999z |",
        "prosa WOT-2026-999z fuera de tabla",
        "| Media | CTL-2026-001a | WOT-2026-999z |",
        "| Media | WOT-2025-001a |",
    ]

    assert all(_row_ticket_ids_from_line(line) == row_line_ids(line) for line in corpus)


def test_find_similar_uses_canonical_pattern_not_private(tmp_path, monkeypatch):
    """DoD (b): el etiquetado delega en el patron CANONICO del bus."""
    import scripts.find_similar_signals as fss

    assert not hasattr(fss, "_TICKET_RE"), (
        "el patron privado debe desaparecer: el repositorio del patron vive en "
        "bus/ticket_id.py (una sola implementacion)"
    )
    assert fss.TICKET_ID_RE is TICKET_ID_RE, (
        "debe importar el MISMO objeto del bus, no una copia"
    )
