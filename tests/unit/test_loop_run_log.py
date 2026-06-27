"""
Tests de barrera para scripts/loop_run_log.py.

Verifica: idempotencia de append_entry por clave (ticket, iteration_index, event),
no reescritura de entradas previas, vista truncada con n_tail, y almacenamiento
de claves distintas. Todos los tests usan tmp_path, sin mocks.
"""

import json
import sys
from pathlib import Path

import pytest


# Insertar la raiz del repo_motor en sys.path para importar scripts/loop_run_log
_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts.loop_run_log import append_entry, get_truncated_view  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

_TICKET = "WOT-2026-014u"
_BASE_ENTRY = {
    "ticket": _TICKET,
    "iteration_index": 0,
    "timestamp_utc": "2026-06-27T09:00:00Z",
    "event": "iteration_start",
    "tokens": 5000,
    "cost_source": "estimated",
    "notes": "test fixture",
}


def _make_entry(iteration_index: int, event: str, tokens: int = 100) -> dict:
    return {
        "ticket": _TICKET,
        "iteration_index": iteration_index,
        "timestamp_utc": "2026-06-27T09:00:00Z",
        "event": event,
        "tokens": tokens,
        "cost_source": "estimated",
        "notes": "test",
    }


# ---------------------------------------------------------------------------
# Tests de barrera (deben fallar si se elimina la logica de dedup)
# ---------------------------------------------------------------------------


def test_append_entry_idempotent_same_key(tmp_path: Path) -> None:
    """
    BARRERA: Llamar append_entry dos veces con la misma clave (ticket,
    iteration_index, event) debe producir exactamente 1 fila en el log.

    Falla si se elimina la condicion de early-return en append_entry.
    """
    log_path = tmp_path / "run.jsonl"
    entry = dict(_BASE_ENTRY)

    append_entry(entry, log_path)
    append_entry(entry, log_path)  # re-run misma clave: debe ser NO-OP

    lines = [
        ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    assert len(lines) == 1, (
        f"Se esperaba 1 fila tras 2 llamadas con la misma clave, se obtuvieron {len(lines)}"
    )
    parsed = json.loads(lines[0])
    assert parsed["ticket"] == _TICKET
    assert parsed["iteration_index"] == 0
    assert parsed["event"] == "iteration_start"


def test_append_entry_does_not_rewrite_previous(tmp_path: Path) -> None:
    """
    BARRERA: Con dos entradas distintas ya escritas, una llamada con la clave
    de la primera NO debe reescribir ni alterar la segunda entrada.

    Compara bytes exactos del log antes y despues del re-run.
    Falla si se elimina la condicion de early-return en append_entry.
    """
    log_path = tmp_path / "run.jsonl"
    entry1 = _make_entry(iteration_index=0, event="iter_start", tokens=100)
    entry2 = _make_entry(iteration_index=1, event="gate_passed", tokens=200)

    append_entry(entry1, log_path)
    append_entry(entry2, log_path)

    snapshot: bytes = log_path.read_bytes()

    # Re-run con la clave de entry1: debe ser NO-OP
    append_entry(entry1, log_path)

    assert log_path.read_bytes() == snapshot, (
        "El log fue modificado tras un re-run con clave duplicada; "
        "se esperaba NO-OP (bytes identicos)."
    )


def test_get_truncated_view_bounded(tmp_path: Path) -> None:
    """
    BARRERA: get_truncated_view(n_tail=N) debe retornar exactamente N entradas
    cuando el log tiene N+5 entradas distintas.

    Falla si se elimina la condicion de early-return (duplicados inflan el log
    reduciendo el numero de entradas distintas, lo que podria romper el conteo).
    """
    log_path = tmp_path / "run.jsonl"
    n_max = 5
    n_written = n_max + 5  # 10 entradas distintas

    for i in range(n_written):
        append_entry(_make_entry(iteration_index=i, event="ev", tokens=10), log_path)

    view = get_truncated_view(log_path, n_tail=n_max)
    entries = view["entries"]

    assert len(entries) == n_max, (
        f"Se esperaban {n_max} entradas en la vista truncada, se obtuvieron {len(entries)}"
    )
    # Verificar que son las ultimas n_max (por iteration_index)
    assert entries[-1]["iteration_index"] == n_written - 1
    assert entries[0]["iteration_index"] == n_written - n_max


# ---------------------------------------------------------------------------
# Test happy path: claves distintas -> ambas almacenadas
# ---------------------------------------------------------------------------


def test_append_entry_different_keys_both_stored(tmp_path: Path) -> None:
    """
    Dos entradas con claves distintas deben almacenarse ambas en el log.
    """
    log_path = tmp_path / "run.jsonl"
    entry_a = _make_entry(iteration_index=0, event="ev0", tokens=10)
    entry_b = _make_entry(iteration_index=1, event="ev1", tokens=20)

    append_entry(entry_a, log_path)
    append_entry(entry_b, log_path)

    lines = [
        ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    assert len(lines) == 2, (
        f"Se esperaban 2 filas con claves distintas, se obtuvieron {len(lines)}"
    )
    parsed_a = json.loads(lines[0])
    parsed_b = json.loads(lines[1])
    assert parsed_a["iteration_index"] == 0
    assert parsed_b["iteration_index"] == 1
    assert parsed_a["tokens"] == 10
    assert parsed_b["tokens"] == 20


def test_append_entry_missing_key_raises(tmp_path: Path) -> None:
    """
    BARRERA: append_entry debe lanzar ValueError si la entrada no tiene
    alguno de los campos de clave (ticket, iteration_index, event).

    Sin la validacion fail-loud, una entrada incompleta colisionaria con
    otras entradas incompletas en la clave (None,...) y se perderian filas
    silenciosamente. Este test blinda el fix.
    """
    log_path = tmp_path / "run.jsonl"

    # Entrada sin el campo "event"
    entry_no_event = {
        "ticket": _TICKET,
        "iteration_index": 0,
        "timestamp_utc": "2026-06-27T09:00:00Z",
        "tokens": 100,
        "cost_source": "estimated",
        "notes": "missing event field",
    }
    with pytest.raises(ValueError, match="missing dedup key field"):
        append_entry(entry_no_event, log_path)

    # Entrada sin el campo "ticket"
    entry_no_ticket = {
        "iteration_index": 0,
        "timestamp_utc": "2026-06-27T09:00:00Z",
        "event": "iteration_start",
        "tokens": 100,
        "cost_source": "estimated",
        "notes": "missing ticket field",
    }
    with pytest.raises(ValueError, match="missing dedup key field"):
        append_entry(entry_no_ticket, log_path)

    # El log NO debe haber sido creado (fail antes de tocar disco)
    assert not log_path.exists(), (
        "El log fue creado pese a que la entrada era invalida; "
        "se esperaba que el raise ocurriera antes de escribir."
    )
