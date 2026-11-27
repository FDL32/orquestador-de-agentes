"""Pruebas del medidor de contexto acumulado del vuelo WOT-2026-161b."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "flight" / "ctx_acumulado.py"
SPEC = importlib.util.spec_from_file_location("ctx_acumulado", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("no se pudo cargar ctx_acumulado.py")
ctx_acumulado = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ctx_acumulado)


def _write_transcript(
    path: Path,
    first_user: str,
    usages: list[int],
    *,
    compact_at: int | None = None,
) -> None:
    """Before: recibe una ruta de transcript y usos simulados.

    During: escribe el primer mensaje, eventos de uso y una compactacion opcional.
    After: deja un JSONL legible por el CLI del medidor.
    """
    rows: list[dict[str, object]] = [
        {"type": "user", "message": {"content": first_user}}
    ]
    for index, input_tokens in enumerate(usages):
        if compact_at == index:
            rows.append(
                {
                    "type": "system",
                    "subtype": "compact_boundary",
                    "compactMetadata": {"preTokens": 500_000},
                }
            )
        rows.append(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "usage": {
                        "input_tokens": input_tokens,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            }
        )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _run(tmp_path: Path, capsys, *extra: str) -> tuple[int, str, str]:
    """Before: `tmp_path` contains zero or more transcripts.

    During: invokes the production CLI entry point with a required project and marker.
    After: returns rc, stdout and stderr from the in-process invocation.
    """
    rc = ctx_acumulado.main(
        [
            "--project-dir",
            str(tmp_path),
            "--marker",
            "Eres CO-9",
            *extra,
        ]
    )
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_rc0_when_current_context_is_below_prepare_threshold(
    tmp_path: Path, capsys
) -> None:
    """Before: one matching transcript has no compaction and low usage.

    During: measures the transcript with the default thresholds.
    After: returns rc 0 and reports the healthy state.
    """
    _write_transcript(tmp_path / "a.jsonl", "Eres CO-9, x", [1_000, 2_000])

    rc, stdout, _stderr = _run(tmp_path, capsys)

    assert rc == 0
    assert "ESTADO: OK" in stdout


def test_rc3_when_current_context_reaches_prepare_threshold(
    tmp_path: Path, capsys
) -> None:
    """Before: the live assistant usage is exactly the prepare threshold.

    During: runs the normal measurement path.
    After: returns rc 3 and names PREPARA.
    """
    _write_transcript(tmp_path / "a.jsonl", "Eres CO-9, x", [380_000])

    rc, stdout, _stderr = _run(tmp_path, capsys)

    assert rc == 3
    assert "ESTADO: PREPARA" in stdout


def test_rc4_when_a_compaction_is_present(tmp_path: Path, capsys) -> None:
    """Before: one transcript contains a compact_boundary event.

    During: measures the matching transcript and evaluates the hard stop.
    After: returns rc 4 and reports CERRAR_Y_SALTAR.
    """
    _write_transcript(
        tmp_path / "a.jsonl", "Eres CO-9, x", [1_000, 2_000], compact_at=1
    )

    rc, stdout, _stderr = _run(tmp_path, capsys)

    assert rc == 4
    assert "ESTADO: CERRAR_Y_SALTAR" in stdout


def test_rc4_when_accumulated_usage_reaches_default_pre(tmp_path: Path, capsys) -> None:
    """Before: two matching transcripts total at least the default pre limit.

    During: sums the current usage of every matching transcript.
    After: returns rc 4 without requiring a compact_boundary event.
    """
    _write_transcript(tmp_path / "a.jsonl", "Eres CO-9, x", [300_000])
    _write_transcript(tmp_path / "b.jsonl", "Eres CO-9, y", [250_000])

    rc, stdout, _stderr = _run(tmp_path, capsys)

    assert rc == 4
    assert "ACUMULADO" in stdout


def test_rc2_when_no_transcript_matches_marker(tmp_path: Path, capsys) -> None:
    """Before: transcripts exist but their first user message has another marker.

    During: scans only the declared project directory and markers.
    After: returns rc 2 with a named diagnostic on stderr.
    """
    _write_transcript(tmp_path / "a.jsonl", "Eres CO-8, x", [1_000])

    rc, _stdout, stderr = _run(tmp_path, capsys)

    assert rc == 2
    assert "ningun transcript" in stderr


def test_rc4_alert_uses_dynamic_module_only_in_dry_run(tmp_path: Path, capsys) -> None:
    """Before: rc 4 is caused by compaction and an isolated ops directory exists.

    During: asks the production code to load comms_alert dynamically in dry-run mode.
    After: the urgent alert is visible and the temporary directory has no ledger writes.
    """
    ops_dir = tmp_path / "ops"
    ops_dir.mkdir()
    _write_transcript(tmp_path / "a.jsonl", "Eres CO-9, x", [1_000], compact_at=0)

    rc, stdout, stderr = _run(
        tmp_path,
        capsys,
        "--alert-ops-dir",
        str(ops_dir),
        "--alert-dry-run",
    )

    assert rc == 4
    assert stderr == ""
    assert "DRY-RUN notify" in stdout
    assert "URGENTE" in stdout
    assert not (ops_dir / "comms_ledger.jsonl").exists()
