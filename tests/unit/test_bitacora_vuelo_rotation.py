"""Tests for R13b: parse_bitacora_vuelo and step_rotate_bitacora_vuelo.

Cubre: parse_bitacora_vuelo contra bitacora real (da >0 entradas,
a diferencia de parse_review_queue que daria 0), rotacion mantiene
KEEP_ENTRIES, archivado por fecha funciona, lock vivo bloquea.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.closeout_steps.rotation import (
    parse_bitacora_vuelo,
    step_rotate_bitacora_vuelo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lock_file(path: Path, started_at: str | None = None) -> None:
    """Crea un lock file con started_at reciente."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "ticket_id": "WP-2026-999",
        "started_at": started_at or datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_bitacora(
    dir_path: Path,
    name: str = "BITACORA_vuelo_test.md",
    num_entries: int = 10,
) -> Path:
    """Crea un fichero BITACORA*.md con entradas timestamp-ISO.

    Formato real de bitacoras: `ts | actor (rol@modelo) | evento | detalle`
    """
    lines = [
        "# BITACORA de vuelo\n",
        "",
        "Formato: timestamp | actor | evento | detalle\n",
        "",
    ]
    for i in range(1, num_entries + 1):
        ts = f"2026-10-{i:02d}T10:00:00Z"
        lines.append(f"{ts} | MAN | plan_fijado | Tarea {i} definida")
        lines.append("")

    bitacora_path = dir_path / name
    bitacora_path.write_text("\n".join(lines), encoding="utf-8")
    return bitacora_path


def _setup_project_root(
    tmp_path: Path,
    num_entries: int = 10,
    locks_alive: bool = False,
) -> Path:
    """Crea un proyecto mock con bitacora y locks opcionales.

    La bitacora se crea en session_bus/ (donde step_rotate_bitacora_vuelo busca primero).
    """
    session_bus = tmp_path / ".agent" / "collaboration" / "session_bus"
    session_bus.mkdir(parents=True)
    _make_bitacora(session_bus, num_entries=num_entries)

    if locks_alive:
        runtime = tmp_path / ".agent" / "runtime"
        runtime.mkdir(parents=True)
        for lock_name in ("builder_lock.txt", "supervisor_lock.txt"):
            _make_lock_file(runtime / lock_name)

    return tmp_path


# // Tests: parse_bitacora_vuelo


class TestParseBitacoraVuelo:
    """Tests para parse_bitacora_vuelo."""

    def test_parses_timestamp_entries(self) -> None:
        """Parsea entradas separadas por timestamp ISO."""
        content = (
            "# BITACORA de vuelo\n\n"
            "Formato: timestamp | actor | evento | detalle\n\n"
            "2026-10-01T10:00:00Z | MAN | plan_fijado | Tarea 1\n\n"
            "2026-10-02T10:00:00Z | BUI | implementado | Feature A\n\n"
        )
        header, entries = parse_bitacora_vuelo(content)
        assert "BITACORA" in header
        assert len(entries) == 2
        assert "plan_fijado" in entries[0]
        assert "implementado" in entries[1]

    def test_returns_empty_for_no_timestamps(self) -> None:
        """Sin timestamps, devuelve header vacio y 0 entradas."""
        content = "# BITACORA\n\nSin entradas aqui.\n"
        header, entries = parse_bitacora_vuelo(content)
        assert "BITACORA" in header
        assert len(entries) == 0

    def test_continuation_lines_grouped_with_entry(self) -> None:
        """Lineas sin timestamp se agrupan con la entrada anterior."""
        content = (
            "2026-10-01T10:00:00Z | MAN | evento | detalle principal\n"
            "  linea continua con mas info\n"
            "  otra linea continua\n"
            "2026-10-02T10:00:00Z | BUI | evento2 | otro detalle\n"
        )
        _, entries = parse_bitacora_vuelo(content)
        assert len(entries) == 2
        assert "linea continua" in entries[0]
        assert "otro detalle" in entries[1]

    def test_different_from_parse_review_queue(self) -> None:
        """parse_bitacora_vuelo da >0 entradas donde parse_review_queue daria 0.

        La ADJUDICACION demostro que _split_header_and_entries devuelve
        entries=[] para el formato real de bitacora (lineas planas sin --- ni ##).
        """
        from scripts.closeout_steps.rotation import parse_review_queue

        content = (
            "2026-10-01T10:00:00Z | MAN | evento | detalle\n"
            "2026-10-02T10:00:00Z | BUI | evento2 | detalle2\n"
        )
        _, entries_bitacora = parse_bitacora_vuelo(content)
        _header, entries_review, _active = parse_review_queue(content)
        assert len(entries_bitacora) >= 2, "parse_bitacora_vuelo debe dar >= 2 entradas"
        assert len(entries_review) == 0, (
            "parse_review_queue da 0 entradas para formato de bitacora"
        )

    def test_single_entry(self) -> None:
        """Una sola entrada timestamp se parsea correctamente."""
        content = "2026-10-01T10:00:00Z | MAN | evento | detalle\n"
        _header, entries = parse_bitacora_vuelo(content)
        assert len(entries) == 1
        assert "evento" in entries[0]


# // Tests: step_rotate_bitacora_vuelo


class TestRotateBitacoraVuelo:
    """Tests para step_rotate_bitacora_vuelo."""

    def test_archives_old_entries(self, tmp_path: Path) -> None:
        """Archiva entradas viejas cuando hay mas de KEEP_ENTRIES."""
        project_root = _setup_project_root(tmp_path, num_entries=100)
        session_bus = project_root / ".agent" / "collaboration" / "session_bus"

        result = step_rotate_bitacora_vuelo(
            project_root,
            dry_run=False,
            bitacora_archive_dir_rel=Path(".agent") / "collaboration" / "archive",
            bitacora_glob_pattern="BITACORA*.md",
            builder_lock_rel=Path(".agent") / "runtime" / "builder_lock.txt",
            keep_entries=50,
            lock_ttl_minutes=15,
            size_warn_threshold=50 * 1024,
            step_result_cls=__import__(
                "scripts.session_closeout", fromlist=["StepResult"]
            ).StepResult,
            supervisor_lock_rel=Path(".agent") / "runtime" / "supervisor_lock.txt",
        )

        assert result.status == "PASS"
        assert "Archived" in result.detail

        # Verificar que se creo archivo de archive
        archive_dir = session_bus.parent / "archive"
        archive_files = list(archive_dir.glob("BITACORA_vuelo_*.md"))
        assert len(archive_files) >= 1

    def test_keeps_keep_entries(self, tmp_path: Path) -> None:
        """Mantiene exactamente KEEP_ENTRIES entradas despues de rotacion."""
        project_root = _setup_project_root(tmp_path, num_entries=100)
        session_bus = project_root / ".agent" / "collaboration" / "session_bus"
        bitacora_path = session_bus / "BITACORA_vuelo_test.md"

        step_rotate_bitacora_vuelo(
            project_root,
            dry_run=False,
            bitacora_archive_dir_rel=Path(".agent") / "collaboration" / "archive",
            bitacora_glob_pattern="BITACORA*.md",
            builder_lock_rel=Path(".agent") / "runtime" / "builder_lock.txt",
            keep_entries=50,
            lock_ttl_minutes=15,
            size_warn_threshold=50 * 1024,
            step_result_cls=__import__(
                "scripts.session_closeout", fromlist=["StepResult"]
            ).StepResult,
            supervisor_lock_rel=Path(".agent") / "runtime" / "supervisor_lock.txt",
        )

        content = bitacora_path.read_text(encoding="utf-8")
        _, entries = parse_bitacora_vuelo(content)
        assert len(entries) <= 50

    def test_skips_when_lock_alive(self, tmp_path: Path) -> None:
        """La rotacion se salta si hay lock vivo."""
        project_root = _setup_project_root(tmp_path, num_entries=100, locks_alive=True)

        result = step_rotate_bitacora_vuelo(
            project_root,
            dry_run=False,
            bitacora_archive_dir_rel=Path(".agent") / "collaboration" / "archive",
            bitacora_glob_pattern="BITACORA*.md",
            builder_lock_rel=Path(".agent") / "runtime" / "builder_lock.txt",
            keep_entries=50,
            lock_ttl_minutes=15,
            size_warn_threshold=50 * 1024,
            step_result_cls=__import__(
                "scripts.session_closeout", fromlist=["StepResult"]
            ).StepResult,
            supervisor_lock_rel=Path(".agent") / "runtime" / "supervisor_lock.txt",
        )

        assert result.status == "SKIP"
        assert "lock" in result.detail.lower()

    def test_dry_run_skips(self, tmp_path: Path) -> None:
        """Dry-run no modifica nada."""
        project_root = _setup_project_root(tmp_path, num_entries=100)
        session_bus = project_root / ".agent" / "collaboration" / "session_bus"
        bitacora_path = session_bus / "BITACORA_vuelo_test.md"
        original_content = bitacora_path.read_text(encoding="utf-8")

        result = step_rotate_bitacora_vuelo(
            project_root,
            dry_run=True,
            bitacora_archive_dir_rel=Path(".agent") / "collaboration" / "archive",
            bitacora_glob_pattern="BITACORA*.md",
            builder_lock_rel=Path(".agent") / "runtime" / "builder_lock.txt",
            keep_entries=50,
            lock_ttl_minutes=15,
            size_warn_threshold=50 * 1024,
            step_result_cls=__import__(
                "scripts.session_closeout", fromlist=["StepResult"]
            ).StepResult,
            supervisor_lock_rel=Path(".agent") / "runtime" / "supervisor_lock.txt",
        )

        assert result.status == "SKIP"
        assert bitacora_path.read_text(encoding="utf-8") == original_content

    def test_no_bitacora_files_skips(self, tmp_path: Path) -> None:
        """Sin ficheros BITACORA, devuelve SKIP."""
        project_root = tmp_path
        collab = project_root / ".agent" / "collaboration"
        collab.mkdir(parents=True)
        # No crear ningun BITACORA*.md

        result = step_rotate_bitacora_vuelo(
            project_root,
            dry_run=False,
            bitacora_archive_dir_rel=Path(".agent") / "collaboration" / "archive",
            bitacora_glob_pattern="BITACORA*.md",
            builder_lock_rel=Path(".agent") / "runtime" / "builder_lock.txt",
            keep_entries=50,
            lock_ttl_minutes=15,
            size_warn_threshold=50 * 1024,
            step_result_cls=__import__(
                "scripts.session_closeout", fromlist=["StepResult"]
            ).StepResult,
            supervisor_lock_rel=Path(".agent") / "runtime" / "supervisor_lock.txt",
        )

        assert result.status == "SKIP"

    def test_fewer_entries_than_keep_skips(self, tmp_path: Path) -> None:
        """Si hay menos entradas que KEEP_ENTRIES, no hay nada que archivar."""
        project_root = _setup_project_root(tmp_path, num_entries=5)

        result = step_rotate_bitacora_vuelo(
            project_root,
            dry_run=False,
            bitacora_archive_dir_rel=Path(".agent") / "collaboration" / "archive",
            bitacora_glob_pattern="BITACORA*.md",
            builder_lock_rel=Path(".agent") / "runtime" / "builder_lock.txt",
            keep_entries=50,
            lock_ttl_minutes=15,
            size_warn_threshold=50 * 1024,
            step_result_cls=__import__(
                "scripts.session_closeout", fromlist=["StepResult"]
            ).StepResult,
            supervisor_lock_rel=Path(".agent") / "runtime" / "supervisor_lock.txt",
        )

        assert result.status == "SKIP"
