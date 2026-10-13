"""Barreras de `scripts/backlog_triage_writer.py` (WOT-2026-049c).

El script es el UNICO dueno de la escritura del DAG de triaje. Sus tres
propiedades duras se prueban aqui, cada una con su mutation-verify (DoD 4-6):

1. El nombre del DAG nuevo lleva timestamp de SEGUNDOS.
2. El DAG previo se PRESERVA con copia (`shutil.copy2`) antes de escribir el
   nuevo -- sin la copia (mutacion: comentar `_preserve_previous`), el previo
   se pierde cuando el timestamp colisiona y estos tests caen en ROJO.
3. La escritura es ATOMICA (write-tmp-then-rename): un fallo a mitad NO deja un
   DAG parcial en la ruta canonica ni un `.tmp` huerfano. Contra una
   implementacion ingenua (`open(path, "w")` directo) el fichero final
   apareceria vacio antes de fallar.

Se importa el modulo por ruta de paquete (`scripts.`), igual que el resto de
tests de `scripts/`.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import backlog_triage_writer as writer


TS_A = "20260101-101010"
TS_B = "20260101-111111"


def _valid_dag(note: str = "baseline") -> dict[str, Any]:
    """DAG minimo valido-ish: la forma exacta la valida validate_batch_dag."""
    return {
        "schema": "autonomous-batch-dag/v1",
        "generated_at": "2026-01-01T10:10:10Z",
        "state_at_triage": {"motor": "abc123", "workspace": "def456", "dirty": 0},
        "groups": [],
        "note": note,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tmp_files(out_dir: Path) -> list[Path]:
    return sorted(out_dir.glob("*.tmp"))


def test_write_produces_canonical_seconds_timestamp(tmp_path):
    """DoD 1: el fichero nuevo es `backlog_triage_<YYYYMMDD-HHMMSS>.json`."""
    result = writer.write_triage_dag(_valid_dag(), tmp_path, timestamp=TS_A)

    assert result["path"] == tmp_path / f"backlog_triage_{TS_A}.json"
    assert writer._canonical_match(result["path"].name) is not None
    assert result["path"].exists()
    assert json.loads(result["path"].read_text(encoding="utf-8"))["note"] == "baseline"
    # Primera corrida: no hay previo que copiar.
    assert result["previous"] is None
    assert result["backup"] is None


def test_previous_dag_preserved_on_timestamp_collision(tmp_path):
    """DoD 4/5: sin copia el previo se pierde; con copia se preserva integro.

    Se fuerza COLISION de timestamp (misma corrida de segundos) para que el
    fichero nuevo apunte al MISMO nombre que el previo. Es el escenario exacto
    que una implementacion ingenua destruiria con `open(path, "w")`.
    Mutacion: comentar la llamada a `_preserve_previous` -> `backup` no existe
    y este test cae en ROJO.
    """
    first = _valid_dag(note="previo")
    writer.write_triage_dag(first, tmp_path, timestamp=TS_A)
    prev_path = tmp_path / f"backlog_triage_{TS_A}.json"
    prev_sha = _sha(prev_path)

    second = _valid_dag(note="nuevo")
    result = writer.write_triage_dag(second, tmp_path, timestamp=TS_A)

    backup = result["backup"]
    assert backup is not None, "sin copia, el DAG previo se pierde (mutation)"
    assert backup.name == f"backlog_triage_{TS_A}_previo.json"
    assert _sha(backup) == prev_sha  # bytes identicos, verificado por hash
    assert json.loads(backup.read_text(encoding="utf-8"))["note"] == "previo"
    # El destino final porta el DAG NUEVO; el previo vive en la copia.
    assert json.loads(result["path"].read_text(encoding="utf-8"))["note"] == "nuevo"


def test_previous_dag_with_distinct_name_is_copied_and_untouched(tmp_path):
    """DoD 2: con un previo de otro timestamp, se copia y el previo no se toca."""
    writer.write_triage_dag(_valid_dag(note="previo"), tmp_path, timestamp=TS_A)
    prev_path = tmp_path / f"backlog_triage_{TS_A}.json"
    prev_sha = _sha(prev_path)

    result = writer.write_triage_dag(_valid_dag(note="nuevo"), tmp_path, timestamp=TS_B)

    assert result["previous"] == prev_path
    assert result["backup"] == tmp_path / f"backlog_triage_{TS_A}_previo.json"
    assert result["backup"].exists()
    assert _sha(result["backup"]) == prev_sha
    assert _sha(prev_path) == prev_sha  # el previo original sigue intacto


def test_previo_backups_are_not_reused_as_previous(tmp_path):
    """Un `_previo` NO es un DAG canonico: no se selecciona como previo."""
    writer.write_triage_dag(_valid_dag(note="previo"), tmp_path, timestamp=TS_A)
    # La copia del previo existe tras una segunda escritura.
    writer.write_triage_dag(_valid_dag(note="nuevo"), tmp_path, timestamp=TS_B)

    previous = writer._find_previous_dag(tmp_path)

    assert previous is not None
    assert writer._is_previo_name(previous.name) is False
    assert writer._canonical_match(previous.name) is not None
    assert previous.name == f"backlog_triage_{TS_B}.json"


def test_no_partial_final_file_on_serialization_failure(tmp_path):
    """DoD 3: si la serializacion falla, el destino canonico NO llega a existir.

    Contra `open(path, "w")` directo el fichero final quedaria creado (vacio o
    a medias) antes de que `json.dumps` fallara. Con write-tmp-then-rename, no.
    """
    final = tmp_path / f"backlog_triage_{TS_A}.json"

    with pytest.raises(TypeError):
        writer.write_triage_dag({"bad": object()}, tmp_path, timestamp=TS_A)

    assert not final.exists()
    assert _tmp_files(tmp_path) == []


def test_tmp_is_cleaned_when_rename_fails(tmp_path, monkeypatch):
    """DoD 3: si `os.replace` falla, no queda `.tmp` huerfano ni DAG parcial."""
    final = tmp_path / f"backlog_triage_{TS_A}.json"

    def _boom(*_args, **_kwargs):
        raise OSError("rename fallido")

    monkeypatch.setattr(writer.os, "replace", _boom)
    with pytest.raises(OSError):
        writer.write_triage_dag(_valid_dag(), tmp_path, timestamp=TS_A)

    assert not final.exists()
    assert _tmp_files(tmp_path) == []


def test_cli_write_from_stdin(tmp_path, monkeypatch, capsys):
    """El subcomando `write` lee el DAG de stdin y lo materializa (exit 0)."""
    payload = json.dumps(_valid_dag(note="cli"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))

    rc = writer.main(["write", "--out-dir", str(tmp_path), "--timestamp", TS_A])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["written"] is True
    assert Path(out["path"]).name == f"backlog_triage_{TS_A}.json"
    assert Path(out["path"]).exists()


def test_cli_derives_reports_dir_from_project_root(tmp_path):
    """Sin `--out-dir`, el DAG va a `<root>/orchestrator_pipeline/reports/`."""
    rc = writer.main(
        [
            "write",
            "--project-root",
            str(tmp_path),
            "--from-file",
            str(_write_payload(tmp_path)),
            "--timestamp",
            TS_A,
        ]
    )

    assert rc == 0
    expected = tmp_path / "orchestrator_pipeline" / "reports"
    assert (expected / f"backlog_triage_{TS_A}.json").exists()


def test_cli_fails_closed_without_output_dir(tmp_path, monkeypatch):
    """Sin `--out-dir` ni `--project-root`, el script NO improvisa ruta (exit 2)."""
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    payload_file = _write_payload(tmp_path)

    rc = writer.main(["write", "--from-file", str(payload_file)])

    assert rc == 2


def test_cli_rejects_invalid_json(tmp_path, capsys):
    """Un JSON invalido es error de entrada (exit 2), no de I/O."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")

    rc = writer.main(["write", "--out-dir", str(tmp_path), "--from-file", str(bad)])

    assert rc == 2


def _write_payload(directory: Path) -> Path:
    path = directory / "payload.json"
    path.write_text(json.dumps(_valid_dag(note="file")), encoding="utf-8")
    return path
