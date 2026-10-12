"""Tests for scripts/check_archive_hygiene.py (WOT-2026-094c).

DoD (e): con duplicacion nueva el script retorna exit 1; con entradas
limpias retorna exit 0. Los tests ejercitan el CLI REAL por subprocess
(nada de surrogates) sobre raices tmp_path, y pinean la baseline fechada
MEM_CM_G7 (2026-10-07) como documentacion, no como criterio de aceptacion.

Las mutaciones usan `--baseline` con ceros para que UNA sola anomalia
supere la baseline: la baseline embebida del motor (78/77/87) es tan
grande que un fixture diminuto nunca la superaria y el test no morderia.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.check_archive_hygiene import BASELINES


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_archive_hygiene.py"


def _write_archive(root: Path, month: str, entries: list[dict[str, Any]]) -> Path:
    """Create `<root>/.agent/runtime/memory/archive/observations.<month>.jsonl`."""
    archive_dir = root / ".agent" / "runtime" / "memory" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_file = archive_dir / f"observations.{month}.jsonl"
    lines = [json.dumps(entry, ensure_ascii=True) for entry in entries]
    archive_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return archive_file


def _zero_baseline(tmp_path: Path) -> Path:
    """Baseline con ceros: cualquier anomalia del fixture la supera."""
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(
        json.dumps(
            {
                "missing_id": 0,
                "duplicate_ids": 0,
                "duplicate_pairs": 0,
                "parse_errors": 0,
            }
        ),
        encoding="utf-8",
    )
    return baseline_file


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _entry(
    entry_id: str, topic: str = "some-topic", ticket: str = "WOT-2026-094c"
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "timestamp": "2026-10-12T00:00:00Z",
        "topic": topic,
        "signal": "senal de prueba",
        "source": "test",
        "source_ticket": ticket,
    }


class TestCheckArchiveHygieneExitCodes:
    """DoD (e): exit 0 limpio / exit 1 ante duplicacion nueva."""

    def test_clean_archive_exits_zero_with_default_baseline(
        self, tmp_path: Path
    ) -> None:
        """Entradas limpias (ids unicos, pares unicos) -> exit 0 con la
        baseline DEFAULT (perfil motor): el camino canonico del DoD."""
        _write_archive(
            tmp_path,
            "2026-10",
            [_entry("obs-a"), _entry("obs-b"), _entry("obs-c")],
        )
        result = _run_cli(["--root", str(tmp_path)])
        assert result.returncode == 0, result.stderr
        assert "[OK] Sin duplicacion nueva" in result.stdout
        # DoD (a): el reporte lista POR ARCHIVE.
        assert "-- observations.2026-10.jsonl: 3 entradas" in result.stdout

    def test_new_duplicate_id_exits_one(self, tmp_path: Path) -> None:
        _write_archive(
            tmp_path,
            "2026-10",
            [_entry("obs-a"), _entry("obs-a")],
        )
        result = _run_cli(
            ["--root", str(tmp_path), "--baseline", str(_zero_baseline(tmp_path))]
        )
        assert result.returncode == 1, result.stdout
        assert "duplicate_ids" in result.stderr

    def test_new_duplicate_pair_exits_one(self, tmp_path: Path) -> None:
        """Mismo (topic, source_ticket) con ids DISTINTOS: par nuevo repetido."""
        _write_archive(
            tmp_path,
            "2026-10",
            [
                _entry("obs-a", topic="same-topic", ticket="WT-1"),
                _entry("obs-b", topic="same-topic", ticket="WT-1"),
            ],
        )
        result = _run_cli(
            [
                "--root",
                str(tmp_path),
                "--baseline",
                str(_zero_baseline(tmp_path)),
            ]
        )
        assert result.returncode == 1, result.stdout
        assert "duplicate_pairs" in result.stderr

    def test_entry_without_id_exits_one(self, tmp_path: Path) -> None:
        entry = _entry("obs-a")
        del entry["id"]
        _write_archive(tmp_path, "2026-10", [_entry("obs-b"), entry])
        result = _run_cli(
            ["--root", str(tmp_path), "--baseline", str(_zero_baseline(tmp_path))]
        )
        assert result.returncode == 1, result.stdout
        assert "missing_id" in result.stderr

    def test_cross_month_duplicate_id_exits_one(self, tmp_path: Path) -> None:
        """El mismo id, UNA vez en cada mes: duplicacion ENTRE meses.

        Mutation que cazaria una implementacion que solo mirara duplicados
        dentro de cada fichero: el conteo raiz SUMA a traves de archivos.
        """
        _write_archive(tmp_path, "2026-09", [_entry("obs-shared", ticket="WT-1")])
        _write_archive(tmp_path, "2026-10", [_entry("obs-shared", ticket="WT-1")])
        result = _run_cli(
            ["--root", str(tmp_path), "--baseline", str(_zero_baseline(tmp_path))]
        )
        assert result.returncode == 1, result.stdout
        assert "duplicate_ids" in result.stderr
        # Y el listado raiz nombra el valor duplicado entre meses.
        assert "obs-shared x2" in result.stdout

    def test_unparseable_line_exits_one(self, tmp_path: Path) -> None:
        archive_file = _write_archive(tmp_path, "2026-10", [_entry("obs-a")])
        archive_file.write_text(
            archive_file.read_text(encoding="utf-8") + "{not json}\n",
            encoding="utf-8",
        )
        result = _run_cli(
            ["--root", str(tmp_path), "--baseline", str(_zero_baseline(tmp_path))]
        )
        assert result.returncode == 1, result.stdout
        assert "parse_errors" in result.stderr

    def test_missing_archive_dir_exits_zero(self, tmp_path: Path) -> None:
        result = _run_cli(["--root", str(tmp_path)])
        assert result.returncode == 0, result.stderr
        assert "Sin archives" in result.stdout


class TestEmbeddedBaselineDocumentation:
    """DoD (b): la baseline MEM_CM_G7 (2026-10-07) vive documentada y
    fechada en el script como referencia, no como criterio de aceptacion
    (el total de entradas y de archivos crecen legitimamente y NO deciden)."""

    def test_motor_baseline_matches_dated_reference(self) -> None:
        assert BASELINES["motor"] == {
            "archives": 4,
            "entries": 455,
            "missing_id": 78,
            "duplicate_ids": 77,
            "duplicate_pairs": 87,
            "parse_errors": 0,
        }

    def test_destino_baseline_matches_dated_reference(self) -> None:
        assert BASELINES["destino"] == {
            "archives": 0,  # no medido como archivos separados en MEM_CM_G7
            "entries": 170,
            "missing_id": 154,
            "duplicate_ids": 1,
            "duplicate_pairs": 16,
            "parse_errors": 0,
        }

    def test_growth_is_not_a_deciding_metric(self, tmp_path: Path) -> None:
        """Mas entradas con ids unicos NO es duplicacion nueva: exit 0 con
        una baseline que ya registra crecimiento previo."""
        baseline_file = tmp_path / "baseline.json"
        baseline_file.write_text(
            json.dumps(
                {
                    "missing_id": 0,
                    "duplicate_ids": 0,
                    "duplicate_pairs": 0,
                    "parse_errors": 0,
                    "entries": 2,
                    "archives": 1,
                }
            ),
            encoding="utf-8",
        )
        _write_archive(
            tmp_path,
            "2026-10",
            [_entry(f"obs-{i}", ticket=f"WT-{i}") for i in range(5)],
        )
        result = _run_cli(["--root", str(tmp_path), "--baseline", str(baseline_file)])
        assert result.returncode == 0, result.stderr
