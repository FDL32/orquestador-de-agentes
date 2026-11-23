from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_loop_execution as cle


def test_historic_receipt_before_integration_is_grandfathered():
    verdict = cle.validate_level_receipt({"ts": "2026-11-22T23:59:59Z"})
    assert verdict["ok"] is True


def test_new_receipt_at_cutoff_without_marker_is_rejected():
    """Desde 2026-11-24 00:00 las rondas nuevas requieren marcador."""
    verdict = cle.validate_level_receipt({"ts": "2026-11-24T00:00:00Z"})
    assert verdict["ok"] is False


def _audit_level_row(**fields):
    row = {
        "event": "ronda",
        "ts": "2099-01-01T00:00:00+00:00",
        "nivel_gate_version": cle.LEVEL_GATE_VERSION,
        "nivel_max_uso": "medio",
        "nivel_clave": "medio",
        "peticion": None,
    }
    row.update(fields)
    return row


def _productive_verdict(tmp_path, row, commit):
    row = {
        "backend_key": "BA10",
        "challenge_nonce": "N-LEVEL",
        "commit_sha": commit,
        **row,
    }
    emitted = [
        {
            "ts": "2020-12-31T23:00:00+00:00",
            "issuer_role": "orchestrator",
            "issuer_backend_key": "BA99",
            "issued_before_ts": "2020-12-31T23:00:00+00:00",
            "commit_sha": commit,
            "loop_id": "L-LEVEL",
            "challenge_nonce": "N-LEVEL",
        }
    ]
    row["loop_id"] = "L-LEVEL"
    support = {
        "event": "ronda",
        "ts": row["ts"],
        "nivel_gate_version": cle.LEVEL_GATE_VERSION,
        "nivel_max_uso": "medio",
        "nivel_clave": "medio",
        "peticion": None,
        "backend_key": "BA11",
        "challenge_nonce": "N-LEVEL",
        "commit_sha": commit,
        "loop_id": "L-LEVEL",
    }
    ensemble = tmp_path / ".agent" / "runtime" / "ensemble"
    ensemble.mkdir(parents=True)
    (ensemble / "scorecard.jsonl").write_text(
        json.dumps(row) + "\n" + json.dumps(support) + "\n", encoding="utf-8"
    )
    (ensemble / "emitted_nonces.jsonl").write_text(
        json.dumps(emitted[0]) + "\n", encoding="utf-8"
    )
    return cle.audit(tmp_path, commit_shas=[commit], min_distinct=1)[0]


def test_productive_verdict_rejects_new_row_without_level_fields(tmp_path):
    """2099 es nueva respecto al corte y no puede heredarse como grandfather."""
    verdict = _productive_verdict(
        tmp_path, {"event": "ronda", "ts": "2099-01-01T00:00:00+00:00"}, "a" * 40
    )
    assert verdict["ok"] is False
    assert verdict["level_failures"]


def test_productive_verdict_rejects_new_premium_without_request(tmp_path):
    """Una fila nueva premium sobre medio requiere una peticion verificable."""
    row = _audit_level_row(nivel_clave="premium", peticion=None)
    verdict = _productive_verdict(tmp_path, row, "b" * 40)
    assert verdict["ok"] is False
    assert len(verdict["level_failures"]) == 1
    assert verdict["level_failures"][0]["nivel_clave"] == "premium"


def test_productive_verdict_allows_grandfather_row_without_marker(tmp_path):
    """2026-11-22 es anterior al corte 2026-11-24 y conserva grandfather."""
    row = {"event": "ronda", "ts": "2026-11-22T23:59:59Z"}
    verdict = _productive_verdict(tmp_path, row, "c" * 40)
    assert verdict["ok"] is True
    assert "level_failures" not in verdict


def test_productive_verdict_allows_marked_row_within_maximum(tmp_path):
    """Una fila nueva marcada dentro del maximo no necesita peticion."""
    row = _audit_level_row()
    verdict = _productive_verdict(tmp_path, row, "d" * 40)
    assert verdict["ok"] is True
    assert "level_failures" not in verdict


def _git_repo_with_commit(tmp_path: Path) -> str:
    """Repo minimo cuyo sha real sirve a resolve_input_commit_sha (rc del CLI)."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "im221c@test.invalid"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "IM-221c"], cwd=tmp_path, check=True)
    (tmp_path / "evidence.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "evidence.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture nivel"], cwd=tmp_path, check=True
    )
    sha = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True
        )
        .stdout.decode()
        .strip()
    )
    return sha


def _write_level_fixture(tmp_path: Path, row: dict, commit: str) -> None:
    row = {
        "backend_key": "BA10",
        "challenge_nonce": "N-LEVEL",
        "commit_sha": commit,
        **row,
    }
    row["loop_id"] = "L-LEVEL"
    support = {
        "event": "ronda",
        "ts": row["ts"],
        "nivel_gate_version": cle.LEVEL_GATE_VERSION,
        "nivel_max_uso": "medio",
        "nivel_clave": "medio",
        "peticion": None,
        "backend_key": "BA11",
        "challenge_nonce": "N-LEVEL",
        "commit_sha": commit,
        "loop_id": "L-LEVEL",
    }
    ensemble = tmp_path / ".agent" / "runtime" / "ensemble"
    ensemble.mkdir(parents=True, exist_ok=True)
    (ensemble / "scorecard.jsonl").write_text(
        json.dumps(row) + "\n" + json.dumps(support) + "\n", encoding="utf-8"
    )
    (ensemble / "emitted_nonces.jsonl").write_text(
        json.dumps(
            {
                "ts": "2020-12-31T23:00:00+00:00",
                "issuer_role": "orchestrator",
                "issuer_backend_key": "BA99",
                "issued_before_ts": "2020-12-31T23:00:00+00:00",
                "commit_sha": commit,
                "loop_id": "L-LEVEL",
                "challenge_nonce": "N-LEVEL",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _cli_rc(tmp_path: Path, commit: str) -> int:
    return cle.main(
        [
            "--project-root",
            str(tmp_path),
            "--commit-sha",
            commit,
            "--min-distinct",
            "1",
        ]
    )


def test_productive_rc_same_day_before_cutoff_without_marker_passes(tmp_path):
    """CO-161 06:3x, sujeto a CO-160: ronda de 2026-11-23T21:00 sin marcador
    es grandfather -> rc 0 por el camino productivo del CLI (main mapea
    verdicts ok a rc y este corte es el PRIMER DIA COMPLETO posterior)."""
    sha = _git_repo_with_commit(tmp_path)
    _write_level_fixture(
        tmp_path, {"event": "ronda", "ts": "2026-11-23T21:00:00Z"}, sha
    )
    assert _cli_rc(tmp_path, sha) == 0


def test_productive_rc_at_cutoff_without_marker_fails(tmp_path):
    """CO-161 06:3x: una ronda sin marcador en 2026-11-24T00:00:00 da rc
    no cero por el camino productivo del CLI."""
    sha = _git_repo_with_commit(tmp_path)
    _write_level_fixture(
        tmp_path, {"event": "ronda", "ts": "2026-11-24T00:00:00Z"}, sha
    )
    assert _cli_rc(tmp_path, sha) != 0
