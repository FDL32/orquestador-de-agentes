"""Tests for WOT-2026-020s: rotate_kilo_logs.py (R13a).

Cubre: compresion de log viejo+inactivo, NO compresion si lock vivo,
NO compresion/purga si vuelo activo, SI purga si vuelo abandonado,
purga de .log.gz tras 30 dias, atomicidad (original sobrevive si gzip falla).
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pytest import MonkeyPatch


_ROOT = Path(__file__).resolve().parents[2]


def _load(module_name: str):
    """Carga un modulo desde scripts/ por import dinamico."""
    spec = __import__("importlib").util.spec_from_file_location(
        module_name, _ROOT / "scripts" / f"{module_name}.py"
    )
    module = __import__("importlib").util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_rk = _load("rotate_kilo_logs")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    probe = _git(root, "rev-parse", "--show-toplevel")
    assert probe.returncode == 0, probe.stderr


def _set_mtime(path: Path, days_ago: int) -> None:
    """Establece mtime de `path` a `days_ago` dias atras."""
    old_time = datetime.now(timezone.utc) - timedelta(days=days_ago)
    ts = old_time.timestamp()
    os.utime(path, (ts, ts))


def _setup_project(
    tmp_path: Path,
    days_old: int = 0,
    with_work_plan: bool = False,
    work_plan_days_old: int | None = None,
    has_terminal: bool = False,
    locks_alive: bool = False,
) -> Path:
    """Crea un proyecto con un log y locks opcionales. NO ejecuta rotacion.

    Devuelve el project_root para que el test llame a _rk.rotate_kilo_logs().
    """
    planning = tmp_path / ".agent" / "planning"
    planning.mkdir(parents=True)
    runtime = tmp_path / ".agent" / "runtime"
    runtime.mkdir(parents=True)

    log_path = planning / "builder_kilo_r1.log"
    log_path.write_text("contenido del log\n", encoding="utf-8")

    if days_old > 0:
        _set_mtime(log_path, days_old)

    if with_work_plan:
        wp_path = planning / "work_plan.md"
        wp_path.write_text("# Work Plan\n", encoding="utf-8")
        if work_plan_days_old is not None:
            _set_mtime(wp_path, work_plan_days_old)
        if has_terminal:
            (planning / "builder_recibo_r1.md").write_text(
                "terminal\n", encoding="utf-8"
            )

    if locks_alive:
        now = datetime.now(timezone.utc).isoformat()
        for lock_name in ("builder_lock.txt", "supervisor_lock.txt"):
            lock_path = runtime / lock_name
            lock_path.write_text(
                json.dumps({"ticket_id": "WP-2026-999", "started_at": now}),
                encoding="utf-8",
            )

    return tmp_path


class TestLogCompression:
    """Pruebas de compresion de logs viejos+inactivos."""

    def test_compresses_old_inactive_log(self, tmp_path: Path) -> None:
        """Un log viejo (>7d) e inactivo se comprime a .log.gz."""
        _setup_project(tmp_path, days_old=10)
        _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=False,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )
        planning = tmp_path / ".agent" / "planning"
        assert (planning / "builder_kilo_r1.log.gz").exists()
        assert not (planning / "builder_kilo_r1.log").exists()
        with gzip.open(
            planning / "builder_kilo_r1.log.gz", "rt", encoding="utf-8"
        ) as f:
            assert "contenido del log" in f.read()

    def test_does_not_compress_recent_log(self, tmp_path: Path) -> None:
        """Un log reciente no se comprime."""
        _setup_project(tmp_path, days_old=3)
        _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=False,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )
        planning = tmp_path / ".agent" / "planning"
        assert (planning / "builder_kilo_r1.log").exists()
        assert not (planning / "builder_kilo_r1.log.gz").exists()

    def test_does_not_compress_if_lock_alive(self, tmp_path: Path) -> None:
        """Un log viejo NO se comprime si hay lock vivo."""
        _setup_project(tmp_path, days_old=10, locks_alive=True)
        _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=False,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )
        planning = tmp_path / ".agent" / "planning"
        assert (planning / "builder_kilo_r1.log").exists()
        assert not (planning / "builder_kilo_r1.log.gz").exists()


class TestFlightActivity:
    """Pruebas de excepcion de vuelo activo."""

    def test_protects_log_when_flight_active(self, tmp_path: Path) -> None:
        """Vuelo activo (work_plan reciente sin terminal) protege el log."""
        _setup_project(
            tmp_path,
            days_old=10,
            with_work_plan=True,
            work_plan_days_old=5,
            has_terminal=False,
        )
        _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=False,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )
        planning = tmp_path / ".agent" / "planning"
        assert (planning / "builder_kilo_r1.log").exists()
        assert not (planning / "builder_kilo_r1.log.gz").exists()

    def test_allows_purge_when_flight_abandoned(self, tmp_path: Path) -> None:
        """Vuelo abandonado (work_plan > 30d sin terminal) NO protege."""
        _setup_project(
            tmp_path,
            days_old=10,
            with_work_plan=True,
            work_plan_days_old=35,
            has_terminal=False,
        )
        _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=False,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )
        planning = tmp_path / ".agent" / "planning"
        assert (planning / "builder_kilo_r1.log.gz").exists()
        assert not (planning / "builder_kilo_r1.log").exists()

    def test_allows_purge_when_flight_has_terminal(self, tmp_path: Path) -> None:
        """Vuelo con veredicto terminal NO protege (vuelo cerrado)."""
        _setup_project(
            tmp_path,
            days_old=10,
            with_work_plan=True,
            work_plan_days_old=5,
            has_terminal=True,
        )
        _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=False,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )
        planning = tmp_path / ".agent" / "planning"
        assert (planning / "builder_kilo_r1.log.gz").exists()
        assert not (planning / "builder_kilo_r1.log").exists()

    def test_does_not_protect_without_work_plan(self, tmp_path: Path) -> None:
        """Sin work_plan.md, no hay excepcion — el log se comprime."""
        _setup_project(tmp_path, days_old=10, with_work_plan=False)
        _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=False,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )
        planning = tmp_path / ".agent" / "planning"
        assert (planning / "builder_kilo_r1.log.gz").exists()
        assert not (planning / "builder_kilo_r1.log").exists()


class TestLogGzPurge:
    """Pruebas de purga de .log.gz viejos."""

    def test_purges_old_log_gz(self, tmp_path: Path) -> None:
        """Un .log.gz viejo (>30d) se purga."""
        planning = tmp_path / ".agent" / "planning"
        planning.mkdir(parents=True)
        gz_path = planning / "old.log.gz"
        gz_path.write_bytes(b"compressed data")
        _set_mtime(gz_path, 35)

        _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=False,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )
        assert not gz_path.exists()

    def test_preserves_recent_log_gz(self, tmp_path: Path) -> None:
        """Un .log.gz reciente no se purga."""
        planning = tmp_path / ".agent" / "planning"
        planning.mkdir(parents=True)
        gz_path = planning / "recent.log.gz"
        gz_path.write_bytes(b"compressed data")

        _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=False,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )
        assert gz_path.exists()


class TestDryRun:
    """Pruebas de modo dry-run."""

    def test_dry_run_does_not_modify_files(self, tmp_path: Path) -> None:
        """--dry-run no modifica ningun archivo."""
        planning = tmp_path / ".agent" / "planning"
        planning.mkdir(parents=True)
        log_path = planning / "builder_kilo_r1.log"
        log_path.write_text("contenido del log\n", encoding="utf-8")
        # Set mtime to 10 days ago
        old_time = datetime.now(timezone.utc) - timedelta(days=10)
        os.utime(log_path, (old_time.timestamp(), old_time.timestamp()))

        result = _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=True,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )

        # En dry-run, el log NO debe comprimirse
        assert log_path.exists(), f"log was deleted! Files: {list(planning.iterdir())}"
        assert not (planning / "builder_kilo_r1.log.gz").exists()
        assert result.dry_run is True


class TestCliOutput:
    """Pruebas de salida CLI."""

    def test_cli_returns_zero(self, tmp_path: Path) -> None:
        """El CLI devuelve exit code 0 siempre."""
        planning = tmp_path / ".agent" / "planning"
        planning.mkdir(parents=True)
        (planning / "test.log").write_text("data\n", encoding="utf-8")

        rc = _rk.main(["--project-root", str(tmp_path)])
        assert rc == 0

    def test_cli_json_output_is_valid(self, tmp_path: Path, capsys) -> None:
        """La salida --json es JSON valido."""
        planning = tmp_path / ".agent" / "planning"
        planning.mkdir(parents=True)
        (planning / "test.log").write_text("data\n", encoding="utf-8")

        rc = _rk.main(["--project-root", str(tmp_path), "--json"])
        out = capsys.readouterr().out.strip()

        assert rc == 0
        payload = json.loads(out)
        assert "denominator" in payload


class TestSubprocessInvocation:
    """Reproduce la ruta productiva real: `run_script()` en
    scripts/closeout_steps/support.py invoca este modulo como SUBPROCESO
    standalone (`[sys.executable, <motor>/scripts/rotate_kilo_logs.py, ...]`,
    cwd=project_root), nunca como `import`. Un test que solo haga `_load()`
    o llame a `_rk.main()` in-process no ejercita ese sys.path[0]=scripts/ y
    no detecta un ModuleNotFoundError en el import diferido de
    scripts.closeout_steps (medido 2026-10-19: el modulo paso todos los
    tests existentes mientras fallaba en produccion)."""

    def test_subprocess_cli_does_not_raise_modulenotfound(self, tmp_path: Path) -> None:
        """La invocacion real via subprocess no debe fallar por import roto."""
        planning = tmp_path / ".agent" / "planning"
        planning.mkdir(parents=True)
        (planning / "test.log").write_text("data\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(_ROOT / "scripts" / "rotate_kilo_logs.py"),
                "--project-root",
                str(tmp_path),
            ],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=False,
        )

        assert "ModuleNotFoundError" not in result.stderr
        assert "No module named" not in result.stdout
        assert result.returncode == 0


class TestAtomicity:
    """Pruebas de atomicidad (rename antes de comprimir)."""

    def test_compress_failure_preserves_original(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Si gzip.open falla, el .log ORIGINAL sobrevive intacto (mutation-verify)."""
        import gzip as gzip_mod

        planning = tmp_path / ".agent" / "planning"
        planning.mkdir(parents=True)
        log_path = planning / "builder_kilo_r1.log"
        original_content = "contenido del log\n"
        log_path.write_text(original_content, encoding="utf-8")
        _set_mtime(log_path, 10)

        # Forzar gzip.open para que lance excepcion durante _compress_log
        original_gzip_open = gzip_mod.open

        def failing_gzip_open(*args, **kwargs):
            raise OSError("simulated gzip failure")

        monkeypatch.setattr(gzip_mod, "open", failing_gzip_open)

        _rk.rotate_kilo_logs(
            tmp_path,
            dry_run=False,
            compress_days=7,
            delete_days=30,
            now=datetime.now(timezone.utc),
        )

        # Restaurar gzip.open original
        monkeypatch.setattr(gzip_mod, "open", original_gzip_open)

        # El original .log debe existir (no se borro)
        assert log_path.exists(), (
            "El .log original desapareció tras el fallo de compresion"
        )
        # El contenido original debe estar intacto
        assert log_path.read_text(encoding="utf-8") == original_content
