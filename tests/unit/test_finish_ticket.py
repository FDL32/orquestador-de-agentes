"""Tests for the explicit, fail-closed 4B-finish-1 reader."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import scripts.flight.finish_ticket as finish_module
from scripts.flight.finish_ticket import FinishError, finish_ticket


KILO_TEXT = (
    "# REVIEW BA03 | WOT-2026-152h | 2e05b304\n"
    "scripts/flight/start_ticket.py:42 lectura confirmada. "
    + ("A" * 190)
    + "\nDECISION: APPROVE\n"
)
KILO_JSONL = (
    json.dumps(
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "read",
                "state": {"input": {"filePath": "C:/Temp/kilo/153t_BA07/AGENTS.md"}},
            },
        }
    )
    + "\n"
    + json.dumps({"type": "text", "part": {"type": "text", "text": KILO_TEXT}})
    + "\n"
    + json.dumps({"type": "step_finish", "part": {"type": "step-finish"}})
)
CODEX_TEXT = "No hay cambios adicionales. " + ("B" * 220) + "\nDECISION: APPROVE\n"


def _world(tmp_path: Path, *, start_rows: list[dict] | None = None):
    start = tmp_path / "start_receipt.json"
    start.write_text(
        json.dumps(
            {
                "ticket": "WOT-2026-152h",
                "tip": "2e05b304" + "0" * 32,
                "lenses": start_rows
                or [
                    {"backend_key": "BA03", "role": "lens", "status": "OK"},
                    {"backend_key": "BA254", "role": "revisor", "status": "OK"},
                ],
            }
        ),
        encoding="utf-8",
    )
    artifacts = tmp_path / "artifacts.json"
    out_kilo = tmp_path / "BA03.out"
    out_codex = tmp_path / "BA254.out"
    out_kilo.write_text(KILO_JSONL, encoding="utf-8")
    out_codex.write_text(CODEX_TEXT, encoding="utf-8")
    artifacts.write_text(
        json.dumps(
            {
                "artifacts": [
                    {"backend_key": "BA03", "out_path": str(out_kilo), "rc": 0},
                    {"backend_key": "BA254", "out_path": str(out_codex), "rc": 0},
                ]
            }
        ),
        encoding="utf-8",
    )
    return start, artifacts


def _finish(tmp_path: Path, **kwargs):
    start, artifacts = _world(tmp_path)
    values = {
        "ticket": "WOT-2026-152h",
        "start_receipt": str(start),
        "artifacts": str(artifacts),
        "output_receipt": str(tmp_path / "finish_receipt.json"),
    }
    values.update(kwargs)
    return finish_ticket(**values)


def test_finish_reads_kilo_jsonl_and_codex_plain_text(tmp_path: Path) -> None:
    receipt = _finish(tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    rows = {row["backend_key"]: row for row in payload["lenses"]}
    assert rows["BA03"]["mode"] == "LECTORA"
    assert rows["BA03"]["read_evidence"] == ["scripts/flight/start_ticket.py:42"]
    assert rows["BA03"]["vote"] == "APPROVE"
    assert rows["BA254"]["mode"] == "TEXTO"
    assert rows["BA254"]["vote"] == "APPROVE"
    assert payload["round_status"] == "INCOMPLETA"


@pytest.mark.parametrize(
    "tool",
    [
        "bash",
        "background_process",
        "edit",
        "write",
        "thread_send",
        "allocate_buffer",
        "location_lookup",
    ],
)
def test_finish_real_non_read_tools_are_texto(tmp_path: Path, tool: str) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    event = {"type": "tool_use", "part": {"type": "tool", "tool": tool}}
    out.write_text(
        json.dumps(event)
        + "\n"
        + json.dumps({"type": "text", "part": {"type": "text", "text": KILO_TEXT}}),
        encoding="utf-8",
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["mode"] == "TEXTO"


@pytest.mark.parametrize(
    "event",
    [
        {"type": "read"},
        {"type": "metadata", "name": "read"},
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "bash",
                "state": {"input": {"name": "read"}},
            },
        },
    ],
)
def test_finish_read_like_data_without_read_event_is_texto(
    tmp_path: Path, event: dict
) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    out.write_text(
        json.dumps(event)
        + "\n"
        + json.dumps({"type": "text", "part": {"type": "text", "text": KILO_TEXT}}),
        encoding="utf-8",
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["mode"] == "TEXTO"


@pytest.mark.parametrize("event_type", ["tool_call", "tool_result"])
def test_finish_recognizes_read_tool_event_types(
    tmp_path: Path, event_type: str
) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    event = {"type": event_type, "name": "read"}
    out.write_text(
        json.dumps(event)
        + "\n"
        + json.dumps({"type": "text", "part": {"type": "text", "text": KILO_TEXT}}),
        encoding="utf-8",
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["mode"] == "LECTORA"
    assert row["vote"] == "APPROVE"


def test_finish_nested_read_event_outside_part_is_texto(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    event = {
        "type": "tool_use",
        "part": {
            "type": "tool",
            "tool": "bash",
            "state": {"input": {"event": {"type": "tool", "tool": "read"}}},
        },
    }
    out.write_text(
        json.dumps(event)
        + "\n"
        + json.dumps({"type": "text", "part": {"type": "text", "text": KILO_TEXT}}),
        encoding="utf-8",
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["mode"] == "TEXTO"


def test_finish_direct_read_name_without_part_is_lectora(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    out.write_text(
        json.dumps({"type": "tool_use", "name": "read"})
        + "\n"
        + json.dumps({"type": "text", "part": {"type": "text", "text": KILO_TEXT}}),
        encoding="utf-8",
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["mode"] == "LECTORA"


def test_finish_read_event_without_route_is_texto(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    event = {"type": "tool_use", "part": {"type": "tool", "tool": "read"}}
    out.write_text(
        json.dumps(event)
        + "\n"
        + json.dumps(
            {
                "type": "text",
                "part": {"type": "text", "text": "A" * 220 + "\nDECISION: APPROVE"},
            }
        ),
        encoding="utf-8",
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["mode"] == "TEXTO"


def test_finish_route_without_read_event_is_texto(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    out.write_text(
        "scripts/x.py:12 " + "A" * 220 + "\nDECISION: APPROVE", encoding="utf-8"
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["mode"] == "TEXTO"


@pytest.mark.parametrize("jsonl", [False, True])
def test_finish_done_sentinel_is_not_counted(tmp_path: Path, jsonl: bool) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    text = "A" * 183 + "\nDECISION: APPROVE\n[DONE]"
    if jsonl:
        out.write_text(
            json.dumps({"type": "text", "part": {"type": "text", "text": text}}),
            encoding="utf-8",
        )
    else:
        out.write_text(text, encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["last_text_bytes"] == len(("A" * 183 + "\nDECISION: APPROVE").encode())
    assert row["vote"] == "APPROVE"


def test_finish_plain_done_line_is_removed_before_measurement(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    out.write_text("A" * 175 + "\n[DONE]\nDECISION: APPROVE", encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["last_text_bytes"] == len(("A" * 175 + "\nDECISION: APPROVE").encode())
    assert row["vote"] == "NO-VOTO"
    assert row["reason"] == "salida menor de 200 bytes"


def test_finish_rejects_mixed_jsonl_and_plain_text(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    out.write_text(
        json.dumps({"type": "text", "part": {"type": "text", "text": "A" * 169}})
        + "\nnota final\nDECISION: APPROVE",
        encoding="utf-8",
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["mode"] == "TEXTO"
    assert row["vote"] == "NO-VOTO"
    assert row["reason"] == "formato mixto"


@pytest.mark.parametrize("raw", ["", "[DONE]"])
def test_finish_empty_and_done_only_are_no_vote(tmp_path: Path, raw: str) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    Path(data["artifacts"][0]["out_path"]).write_text(raw, encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["vote"] == "NO-VOTO"
    assert row["reason"] == "salida menor de 200 bytes"


@pytest.mark.parametrize("literal", ["null", "true", "false", "0", '"s"', "[]", "{}"])
@pytest.mark.parametrize("literal_first", [False, True])
def test_finish_valid_json_non_dict_values_are_jsonl(
    tmp_path: Path, literal: str, literal_first: bool
) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    text_record = json.dumps(
        {"type": "text", "part": {"type": "text", "text": CODEX_TEXT}}
    )
    raw = f"{literal}\n{text_record}" if literal_first else f"{text_record}\n{literal}"
    Path(data["artifacts"][0]["out_path"]).write_text(raw, encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["mode"] == "TEXTO"
    assert row["vote"] == "APPROVE"


@pytest.mark.parametrize(
    ("raw", "vote", "reason"),
    [
        (
            json.dumps(
                {
                    "type": "text",
                    "part": {"type": "text", "text": "A" * 220 + "\nDECISION: APPROVE"},
                }
            )
            + "\n"
            + json.dumps(
                {"type": "text", "part": {"type": "text", "text": "incompleto"}}
            )
            + "\n[DONE]",
            "NO-VOTO",
            "salida menor de 200 bytes",
        ),
        (
            json.dumps(
                {
                    "type": "text",
                    "part": {"type": "text", "text": "A" * 220 + "\nDECISION: APPROVE"},
                }
            )
            + "\n"
            + json.dumps(
                {"type": "text", "part": {"type": "text", "text": "incompleto"}}
            ),
            "NO-VOTO",
            "salida menor de 200 bytes",
        ),
        (
            json.dumps({"type": "text", "part": {"type": "text", "text": "incompleto"}})
            + "\n"
            + json.dumps(
                {
                    "type": "text",
                    "part": {"type": "text", "text": "A" * 220 + "\nDECISION: APPROVE"},
                }
            )
            + "\n[DONE]",
            "APPROVE",
            None,
        ),
    ],
)
def test_finish_done_line_after_jsonl_is_ignored(
    tmp_path: Path, raw: str, vote: str, reason: str | None
) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    out.write_text(raw, encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["vote"] == vote
    if reason is not None:
        assert row["reason"] == reason


@pytest.mark.parametrize("size", [199, 200])
def test_finish_byte_boundary(tmp_path: Path, size: int) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    decision = "DECISION: APPROVE"
    out.write_text("A" * (size - len(decision) - 1) + "\n" + decision, encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["last_text_bytes"] == size
    assert row["vote"] == ("APPROVE" if size == 200 else "NO-VOTO")


def test_finish_counts_utf8_bytes_not_characters(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    decision = "DECISION: APPROVE"
    text = "é" * ((200 - len(decision) - 1) // 2) + "\n" + decision
    assert len(text) < 200 and len(text.encode("utf-8")) == 200
    out.write_text(text, encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["vote"] == "APPROVE"


def test_finish_uses_last_decision(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    out.write_text(
        "A" * 190 + "\nDECISION: CHANGES\nDECISION: APPROVE", encoding="utf-8"
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["vote"] == "APPROVE"


def test_finish_rejects_boolean_rc(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    data["artifacts"][0]["rc"] = False
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["reason"] == "rc ilegible"


@pytest.mark.parametrize(
    ("expected", "readable"),
    [("LECTORA", True), ("LECTORA", False), ("TEXTO", False), ("TEXTO", True)],
)
def test_finish_expected_mode_is_coordinator_input(
    tmp_path: Path, expected: str, readable: bool
) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    data["artifacts"][0]["expected_mode"] = expected
    if not readable:
        Path(data["artifacts"][0]["out_path"]).write_text(
            "A" * 220 + "\nDECISION: APPROVE", encoding="utf-8"
        )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["expected_mode"] == expected
    assert row["vote"] == ("APPROVE" if expected == row["mode"] else "NO-VOTO")
    if expected == "LECTORA" and not readable:
        assert row["reason"] == "sin lectura"
    if expected == "TEXTO" and readable:
        assert row["mode"] == "LECTORA"
        assert row["reason"] == "modo discrepante"


def test_finish_expected_reader_preserves_mute_reason(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    data["artifacts"][0]["expected_mode"] = "LECTORA"
    data["artifacts"][0]["rc"] = 3
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["vote"] == "NO-VOTO"
    assert row["reason"] == "stream mudo: rc 3"


def test_finish_expected_reader_preserves_decision_reason(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    data["artifacts"][0]["expected_mode"] = "LECTORA"
    Path(data["artifacts"][0]["out_path"]).write_text("A" * 220, encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["vote"] == "NO-VOTO"
    assert row["reason"] == "decision ausente"


def test_finish_expected_mode_invalid_fails_closed(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    data["artifacts"][0]["expected_mode"] = "DECLARADO"
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FinishError, match="expected_mode invalido"):
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
        )


def test_finish_reports_unplanned_artifacts_without_voting(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    extra = dict(data["artifacts"][0])
    extra["backend_key"] = "ZETA_UNPLANNED"
    another = dict(data["artifacts"][0])
    another["backend_key"] = "ALPHA_UNPLANNED"
    data["artifacts"].extend([extra, another])
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["unplanned_artifacts"] == ["ALPHA_UNPLANNED", "ZETA_UNPLANNED"]
    assert all(
        row["backend_key"] not in {"ALPHA_UNPLANNED", "ZETA_UNPLANNED"}
        for row in payload["lenses"]
    )


def test_finish_rejects_duplicate_artifacts(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    data["artifacts"].append(dict(data["artifacts"][0]))
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FinishError, match="artifacts duplicado"):
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
        )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("short", "salida menor de 200 bytes"),
        ("mute", "stream mudo: rc 3"),
        ("missing", "out ausente"),
        ("bad_rc", "rc ilegible"),
        ("no_decision", "decision ausente"),
    ],
)
def test_finish_fail_closed_no_vote_reasons(
    tmp_path: Path, change: str, reason: str
) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    entry = data["artifacts"][0]
    out = Path(entry["out_path"])
    if change == "short":
        out.write_text("short\nDECISION: APPROVE\n", encoding="utf-8")
    elif change == "mute":
        entry["rc"] = 3
    elif change == "missing":
        entry["out_path"] = str(tmp_path / "missing.out")
    elif change == "bad_rc":
        entry["rc"] = "0"
    else:
        out.write_text("A" * 240, encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    rows = json.loads(receipt.read_text(encoding="utf-8"))["lenses"]
    assert rows[0]["vote"] == "NO-VOTO"
    assert rows[0]["reason"] == reason


def test_finish_unknown_plain_format_defaults_to_texto(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    out = Path(data["artifacts"][0]["out_path"])
    out.write_text(
        "plain unknown format " + "X" * 230 + "\nDECISION: APPROVE", encoding="utf-8"
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    row = json.loads(receipt.read_text(encoding="utf-8"))["lenses"][0]
    assert row["mode"] == "TEXTO"
    assert row["vote"] == "APPROVE"


def test_finish_preserves_start_states_and_missing_artifact_is_no_vote(
    tmp_path: Path,
) -> None:
    rows = [
        {"backend_key": "BA03", "role": "lens", "status": "NO_LEGIBLE"},
        {"backend_key": "BA254", "role": "revisor", "status": "SIN_RECIBO"},
    ]
    start, artifacts = _world(tmp_path, start_rows=rows)
    data = json.loads(artifacts.read_text(encoding="utf-8"))
    data["artifacts"] = []
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
    )
    result = json.loads(receipt.read_text(encoding="utf-8"))["lenses"]
    assert [row["status"] for row in result] == ["NO_LEGIBLE", "SIN_RECIBO"]
    assert all(row["vote"] == "NO-VOTO" for row in result)


def test_finish_rejects_start_ticket_mismatch(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    with pytest.raises(FinishError, match="ticket"):
        finish_ticket(
            ticket="OTHER",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
        )


def _guard_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_finish_guard_passes_explicit_arguments_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    calls: list[list[str]] = []
    tip = _guard_payload(start)["tip"]

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"loop_exec_receipt": {"commit_sha": tip, "ok": True}}),
            stderr="",
        )

    monkeypatch.setattr(finish_module.subprocess, "run", fake_run)
    project_root = str(tmp_path / "repo destino con espacios")
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
        project_root=project_root,
        loop_id="loop-152h",
        commit_sha=tip,
    )
    payload = _guard_payload(receipt)
    assert payload["round_status"] == "COMPLETA"
    assert payload["quorum"]["status"] == "OK"
    command = calls[0]
    assert command[0] == finish_module.sys.executable
    assert command[1] == str(
        Path(finish_module.__file__).resolve().parents[1] / "check_loop_execution.py"
    )
    assert command[command.index("--project-root") + 1] == project_root
    assert command[command.index("--commit-sha") + 1] == tip
    assert command[command.index("--loop-id") + 1] == "loop-152h"


@pytest.mark.parametrize(
    ("project_root", "commit_sha", "reason"),
    [
        (None, None, "sin project-root"),
        (None, "sha", "sin project-root"),
        ("repo", None, "sin commit-sha"),
    ],
)
def test_finish_missing_guard_arguments_does_not_invoke_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_root: str | None,
    commit_sha: str | None,
    reason: str,
) -> None:
    start, artifacts = _world(tmp_path)

    def fail_run(*args: object, **kwargs: object) -> SimpleNamespace:
        raise AssertionError("el guard no debe ejecutarse")

    monkeypatch.setattr(finish_module.subprocess, "run", fail_run)
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=project_root,
            commit_sha=commit_sha,
        )
    )
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"] == {"status": "NO_MEDIDO", "reason": reason}


def test_finish_guard_rejects_start_tip_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    start_data = _guard_payload(start)
    start_data["tip"] = "different-start-tip"
    start.write_text(json.dumps(start_data), encoding="utf-8")
    monkeypatch.setattr(
        finish_module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("la discrepancia debe abortar antes del guard")
        ),
    )
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            commit_sha=tip,
        )
    )
    assert payload["quorum"]["status"] == "FALLO_RC"
    assert "discrepante" in payload["quorum"]["reason"]


@pytest.mark.parametrize(
    ("returncode", "stdout", "reason"),
    [
        (0, "[loop-exec] SKIP: no --commit-sha dado (nada que verificar).", "ausente"),
        (
            1,
            json.dumps({"loop_exec_receipt": {"commit_sha": "other", "ok": False}}),
            "otro commit",
        ),
        (
            0,
            json.dumps({"loop_exec_receipt": {"commit_sha": "sha", "ok": "yes"}}),
            "tipo invalido",
        ),
        (
            -1,
            json.dumps({"loop_exec_receipt": {"commit_sha": "sha", "ok": True}}),
            "guard rc -1",
        ),
    ],
)
def test_finish_guard_fail_closed_receipt_and_rc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    reason: str,
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    if '"commit_sha": "sha"' in stdout:
        stdout = stdout.replace('"commit_sha": "sha"', f'"commit_sha": "{tip}"')
    monkeypatch.setattr(
        finish_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=returncode, stdout=stdout, stderr=""
        ),
    )
    output = tmp_path / "finish.json"
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(output),
            project_root=str(tmp_path),
            commit_sha=tip,
        )
    )
    assert output.is_file()
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"]["status"] == "FALLO_RC"
    assert reason in payload["quorum"]["reason"]


@pytest.mark.parametrize(
    "exception", [OSError("no ejecutable"), subprocess.TimeoutExpired("guard", 900)]
)
def test_finish_guard_subprocess_error_writes_local_failure_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
) -> None:
    start, artifacts = _world(tmp_path)
    monkeypatch.setattr(
        finish_module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(exception),
    )
    output = tmp_path / "finish.json"
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(output),
            project_root=str(tmp_path),
            commit_sha=_guard_payload(start)["tip"],
        )
    )
    assert output.is_file()
    assert payload["quorum"]["status"] == "FALLO_RC"


def test_finish_guard_real_subprocess_without_rounds_is_fail_closed(
    tmp_path: Path,
) -> None:
    start, artifacts = _world(tmp_path)
    repo_root = Path(__file__).resolve().parents[2]
    actual_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    start_data = _guard_payload(start)
    start_data["tip"] = actual_sha
    start.write_text(json.dumps(start_data), encoding="utf-8")
    runtime = tmp_path / ".agent" / "runtime" / "ensemble"
    runtime.mkdir(parents=True)
    (runtime / "scorecard.jsonl").write_text("", encoding="utf-8")
    (runtime / "emitted_nonces.jsonl").write_text("", encoding="utf-8")
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            loop_id="loop-real-no-rounds",
            commit_sha=actual_sha,
        )
    )
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"]["status"] == "FALLO_RC"
    assert payload["quorum"]["guard_receipt"]["ok"] is False


def _fake_guard(monkeypatch: pytest.MonkeyPatch, receipt: dict, *, rc: int = 0):
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=rc,
            stdout=json.dumps({"loop_exec_receipt": receipt}),
            stderr="",
        )

    monkeypatch.setattr(finish_module.subprocess, "run", fake_run)
    return calls


@pytest.mark.parametrize(
    "receipts",
    [
        ({"ok": True}, {"ok": False}),
        ({"ok": False}, {"ok": True}),
        ({"ok": True}, {"ok": True}),
    ],
)
def test_finish_guard_rejects_multiple_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipts: tuple[dict, dict],
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    stdout = "\n".join(
        json.dumps({"loop_exec_receipt": {"commit_sha": tip, **receipt}})
        for receipt in receipts
    )
    monkeypatch.setattr(
        finish_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            commit_sha=tip,
        )
    )
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"] == {
        "status": "FALLO_RC",
        "reason": "recibos multiples ambiguos",
    }


def test_finish_guard_accepts_one_receipt_after_multiple_receipt_hardening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    _fake_guard(monkeypatch, {"commit_sha": tip, "ok": True})
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            commit_sha=tip,
        )
    )
    assert payload["round_status"] == "COMPLETA"
    assert payload["quorum"]["status"] == "OK"


@pytest.mark.parametrize("value", ["yes", 1, "true"])
def test_finish_guard_rejects_invalid_exempt_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    _fake_guard(monkeypatch, {"commit_sha": tip, "ok": True, "exempt": value})
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            commit_sha=tip,
        )
    )
    assert payload["quorum"] == {
        "status": "FALLO_RC",
        "reason": "recibo del guard con tipo invalido",
    }


@pytest.mark.parametrize("loop_id", ["", "   "])
def test_finish_blank_loop_id_is_not_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loop_id: str
) -> None:
    start, artifacts = _world(tmp_path)
    monkeypatch.setattr(
        finish_module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no guard")),
    )
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            loop_id=loop_id,
            commit_sha=_guard_payload(start)["tip"],
        )
    )
    assert payload["quorum"] == {"status": "NO_MEDIDO", "reason": "loop-id vacio"}


def _finish_with_guard_ok(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    start: Path | None = None,
    artifacts: Path | None = None,
    start_rows: list[dict] | None = None,
) -> dict:
    if start is None or artifacts is None:
        start, artifacts = _world(tmp_path, start_rows=start_rows)
    tip = _guard_payload(start)["tip"]
    _fake_guard(monkeypatch, {"commit_sha": tip, "ok": True})
    receipt = finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
        project_root=str(tmp_path),
        commit_sha=tip,
    )
    return _guard_payload(receipt)


def test_finish_guard_ok_requires_two_distinct_approves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _finish_with_guard_ok(tmp_path, monkeypatch)
    assert payload["round_status"] == "COMPLETA"
    assert payload["quorum"]["status"] == "OK"


def test_finish_one_approve_and_one_changes_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    data = _guard_payload(artifacts)
    Path(data["artifacts"][1]["out_path"]).write_text(
        CODEX_TEXT.replace("DECISION: APPROVE", "DECISION: CHANGES"), encoding="utf-8"
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    payload = _finish_with_guard_ok(
        tmp_path, monkeypatch, start=start, artifacts=artifacts
    )
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 1"


def test_finish_two_approves_from_same_lens_are_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {"backend_key": "BA03", "role": "lens", "status": "OK"},
        {"backend_key": "BA03", "role": "lens", "status": "OK"},
    ]
    payload = _finish_with_guard_ok(tmp_path, monkeypatch, start_rows=rows)
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 1"


def test_finish_one_approve_and_one_no_vote_are_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    data = _guard_payload(artifacts)
    Path(data["artifacts"][1]["out_path"]).write_text("short", encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    payload = _finish_with_guard_ok(
        tmp_path, monkeypatch, start=start, artifacts=artifacts
    )
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 1"


def test_finish_substituted_approve_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    data = _guard_payload(artifacts)
    data["artifacts"][1]["substituted"] = True
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    payload = _finish_with_guard_ok(
        tmp_path, monkeypatch, start=start, artifacts=artifacts
    )
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 1"


def test_finish_zero_artifacts_is_incomplete_even_with_guard_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    data = _guard_payload(artifacts)
    data["artifacts"] = []
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    payload = _finish_with_guard_ok(
        tmp_path, monkeypatch, start=start, artifacts=artifacts
    )
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 0"


def test_finish_start_substitution_wins_over_manifest_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {"backend_key": "BA03", "role": "lens", "status": "OK"},
        {
            "backend_key": "BA254",
            "role": "revisor",
            "status": "OK",
            "substituted": True,
        },
    ]
    start, artifacts = _world(tmp_path, start_rows=rows)
    data = _guard_payload(artifacts)
    data["artifacts"][1]["substituted"] = False
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    payload = _finish_with_guard_ok(
        tmp_path, monkeypatch, start=start, artifacts=artifacts
    )
    result = {row["backend_key"]: row for row in payload["lenses"]}
    assert result["BA254"]["substituted"] is True
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 1"


def test_finish_start_family_wins_and_manifest_contradiction_no_votes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {"backend_key": "BA03", "role": "lens", "status": "OK", "family": "glm"},
        {
            "backend_key": "BA254",
            "role": "revisor",
            "status": "OK",
            "family": "codex",
        },
    ]
    start, artifacts = _world(tmp_path, start_rows=rows)
    data = _guard_payload(artifacts)
    data["artifacts"][1]["family"] = "qwen"
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    payload = _finish_with_guard_ok(
        tmp_path, monkeypatch, start=start, artifacts=artifacts
    )
    result = {row["backend_key"]: row for row in payload["lenses"]}
    assert result["BA254"]["family"] == "codex"
    assert result["BA254"]["vote"] == "NO-VOTO"
    assert result["BA254"]["reason"] == "manifiesto discrepante con start"
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 1"


def test_finish_start_metadata_without_manifest_contradiction_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {"backend_key": "BA03", "role": "lens", "status": "OK", "family": "glm"},
        {
            "backend_key": "BA254",
            "role": "revisor",
            "status": "OK",
            "family": "codex",
        },
    ]
    payload = _finish_with_guard_ok(tmp_path, monkeypatch, start_rows=rows)
    assert payload["round_status"] == "COMPLETA"


@pytest.mark.parametrize(
    ("field", "start_value", "artifact_value"),
    [
        ("backend_key", "BA03", "BA254"),
        ("commit_sha", "start-sha", "artifact-sha"),
        ("family", "glm", "qwen"),
        ("model_effective", "glm-5", "qwen-3"),
        ("expected_mode", "LECTORA", "TEXTO"),
        ("expected_mode", "TEXTO", "LECTORA"),
    ],
)
def test_finish_start_protected_field_contradiction_is_no_vote(
    field: str, start_value: object, artifact_value: object
) -> None:
    start = {"backend_key": "BA03", field: start_value}
    artifact = {"backend_key": "BA03", field: artifact_value, "vote": "APPROVE"}
    merged = finish_module._merge_start_and_artifact(start, artifact)
    assert merged[field] == start_value
    assert merged["vote"] == "NO-VOTO"
    assert merged["reason"] == "manifiesto discrepante con start"


def test_finish_start_protected_field_without_contradiction_is_positive() -> None:
    merged = finish_module._merge_start_and_artifact(
        {"backend_key": "BA03", "expected_mode": "LECTORA"},
        {"backend_key": "BA03", "expected_mode": "LECTORA", "vote": "APPROVE"},
    )
    assert merged["vote"] == "APPROVE"
    assert merged["expected_mode"] == "LECTORA"


@pytest.mark.parametrize(
    "field",
    ["backend_key", "commit_sha", "family", "model_effective", "expected_mode"],
)
def test_finish_start_absent_protected_field_can_come_from_artifact(field: str) -> None:
    merged = finish_module._merge_start_and_artifact(
        {},
        {field: "artifact-value", "vote": "APPROVE"},
    )
    assert merged[field] == "artifact-value"
    assert merged["vote"] == "APPROVE"


@pytest.mark.parametrize(
    ("start_value", "artifact_value"),
    [("true", False), (False, 1)],
)
def test_finish_any_non_false_substitution_value_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_value: object,
    artifact_value: object,
) -> None:
    rows = [
        {"backend_key": "BA03", "role": "lens", "status": "OK"},
        {
            "backend_key": "BA254",
            "role": "revisor",
            "status": "OK",
            "substituted": start_value,
        },
    ]
    start, artifacts = _world(tmp_path, start_rows=rows)
    data = _guard_payload(artifacts)
    data["artifacts"][1]["substituted"] = artifact_value
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    payload = _finish_with_guard_ok(
        tmp_path, monkeypatch, start=start, artifacts=artifacts
    )
    result = {row["backend_key"]: row for row in payload["lenses"]}
    assert result["BA254"]["substituted"] is True
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 1"


@pytest.mark.parametrize("debt", [5, None])
def test_finish_guard_debt_type_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, debt: object
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    _fake_guard(monkeypatch, {"commit_sha": tip, "ok": True, "debt": debt})
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            commit_sha=tip,
        )
    )
    if debt is None:
        assert payload["quorum"]["reason"] == "guard OK"
    else:
        assert payload["quorum"] == {
            "status": "FALLO_RC",
            "reason": "recibo del guard con tipo invalido",
        }


def test_finish_expected_mode_discrepancy_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    data = _guard_payload(artifacts)
    data["artifacts"][0]["expected_mode"] = "TEXTO"
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    payload = _finish_with_guard_ok(
        tmp_path, monkeypatch, start=start, artifacts=artifacts
    )
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 1"


def test_finish_same_effective_model_collides_for_quorum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {
            "backend_key": "BA03",
            "role": "lens",
            "status": "OK",
            "model_effective": "same-model",
        },
        {
            "backend_key": "BA254",
            "role": "revisor",
            "status": "OK",
            "model_effective": "same-model",
        },
    ]
    payload = _finish_with_guard_ok(tmp_path, monkeypatch, start_rows=rows)
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 1"


def test_finish_artifact_commit_sha_mismatch_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    data = _guard_payload(artifacts)
    data["artifacts"][1]["commit_sha"] = "other-commit"
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    payload = _finish_with_guard_ok(
        tmp_path, monkeypatch, start=start, artifacts=artifacts
    )
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["quorum"]["reason"] == "menos de 2 APPROVE de lentes distintas: 1"


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ({"exempt": True}, "guard OK por exencion"),
        ({"debt": "historica"}, "guard OK por deuda historica"),
        ({"exempt": True, "debt": "historica"}, "guard OK por exencion"),
        ({}, "guard OK"),
    ],
)
def test_finish_guard_exemption_and_debt_never_make_false_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra: dict,
    reason: str,
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    receipt = {"commit_sha": tip, "ok": True, **extra}
    _fake_guard(monkeypatch, receipt)
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            commit_sha=tip,
        )
    )
    assert payload["quorum"]["guard_receipt"] == receipt
    if extra:
        assert payload["round_status"] == "INCOMPLETA"
        assert payload["quorum"] == {
            "status": "NO_MEDIDO",
            "guard_receipt": receipt,
            "reason": reason,
        }
    else:
        assert payload["round_status"] == "COMPLETA"
        assert payload["quorum"]["status"] == "OK"


def test_finish_guard_non_dict_receipt_is_contract_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    monkeypatch.setattr(
        finish_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"loop_exec_receipt": "x"}),
            stderr="",
        ),
    )
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            commit_sha=tip,
        )
    )
    assert payload["quorum"]["reason"] == "recibo del guard con tipo invalido"


@pytest.mark.parametrize("value", [5, [1], None])
def test_finish_guard_ignores_valid_non_dict_json_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    receipt = {"commit_sha": tip, "ok": True}
    _fake_guard(monkeypatch, receipt)
    original = finish_module.subprocess.run

    def with_noise(command: list[str], **kwargs: object) -> SimpleNamespace:
        result = original(command, **kwargs)
        result.stdout = json.dumps(value) + "\n" + result.stdout
        return result

    monkeypatch.setattr(finish_module.subprocess, "run", with_noise)
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            commit_sha=tip,
        )
    )
    assert payload["quorum"]["status"] == "OK"


def test_finish_guard_without_loop_id_omits_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    calls = _fake_guard(monkeypatch, {"commit_sha": tip, "ok": True})
    finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
        project_root=str(tmp_path),
        commit_sha=tip,
    )
    assert "--loop-id" not in calls[0][0]


@pytest.mark.parametrize("project_root", ["", "   "])
def test_finish_blank_project_root_is_not_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_root: str
) -> None:
    start, artifacts = _world(tmp_path)
    monkeypatch.setattr(
        finish_module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no guard")),
    )
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=project_root,
            commit_sha=_guard_payload(start)["tip"],
        )
    )
    assert payload["quorum"] == {"status": "NO_MEDIDO", "reason": "sin project-root"}


@pytest.mark.parametrize("commit_sha", ["", "  "])
def test_finish_blank_commit_sha_is_not_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_sha: str
) -> None:
    start, artifacts = _world(tmp_path)
    monkeypatch.setattr(
        finish_module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no guard")),
    )
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            commit_sha=commit_sha,
        )
    )
    assert payload["quorum"] == {"status": "NO_MEDIDO", "reason": "sin commit-sha"}


def test_finish_guard_rc_zero_false_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    _fake_guard(monkeypatch, {"commit_sha": tip, "ok": False})
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
            project_root=str(tmp_path),
            commit_sha=tip,
        )
    )
    assert payload["quorum"] == {
        "status": "FALLO_RC",
        "guard_receipt": {"commit_sha": tip, "ok": False},
        "reason": "guard veredicto no OK",
    }


def test_finish_cli_forwards_guard_flags_and_defaults_to_no_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: list[dict] = []

    def fake_finish(**kwargs: object) -> Path:
        captured.append(kwargs)
        return tmp_path / "finish.json"

    monkeypatch.setattr(finish_module, "finish_ticket", fake_finish)
    base = [
        "--ticket",
        "T",
        "--start-receipt",
        "start.json",
        "--artifacts",
        "artifacts.json",
        "--output-receipt",
        "finish.json",
    ]
    assert (
        finish_module.main(
            [
                *base,
                "--project-root",
                "P",
                "--loop-id",
                "L",
                "--commit-sha",
                "C",
            ]
        )
        == 0
    )
    assert captured[-1]["project_root"] == "P"
    assert captured[-1]["loop_id"] == "L"
    assert captured[-1]["commit_sha"] == "C"
    assert finish_module.main(base) == 0
    assert captured[-1]["project_root"] is None
    capsys.readouterr()


def test_finish_guard_subprocess_has_bounded_utf8_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, artifacts = _world(tmp_path)
    tip = _guard_payload(start)["tip"]
    calls = _fake_guard(monkeypatch, {"commit_sha": tip, "ok": True})
    finish_ticket(
        ticket="WOT-2026-152h",
        start_receipt=str(start),
        artifacts=str(artifacts),
        output_receipt=str(tmp_path / "finish.json"),
        project_root=str(tmp_path),
        commit_sha=tip,
    )
    kwargs = calls[0][1]
    assert isinstance(kwargs["timeout"], (int, float)) and kwargs["timeout"] > 0
    assert kwargs["encoding"] == "utf-8"


def test_finish_contract_failure_writes_local_failure_receipt(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    output = tmp_path / "failure.json"
    with pytest.raises(FinishError, match="ticket"):
        finish_ticket(
            ticket="OTHER",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(output),
        )
    payload = _guard_payload(output)
    assert payload["round_status"] == "INCOMPLETA"
    assert payload["error"] == payload["quorum"]["reason"]


def test_finish_route_evidence_accepts_spaces_by_shape(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = _guard_payload(artifacts)
    out = Path(data["artifacts"][0]["out_path"])
    text = "C:/ruta con espacios/archivo.py:12 " + "A" * 220 + "\nDECISION: APPROVE"
    out.write_text(
        json.dumps({"type": "tool_use", "part": {"type": "tool", "tool": "read"}})
        + "\n"
        + json.dumps({"type": "text", "part": {"type": "text", "text": text}}),
        encoding="utf-8",
    )
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    payload = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
        )
    )["lenses"][0]
    assert payload["mode"] == "LECTORA"
    assert payload["read_evidence"] == ["C:/ruta con espacios/archivo.py:12"]


def test_finish_unreadable_out_is_no_vote(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = _guard_payload(artifacts)
    out = Path(data["artifacts"][0]["out_path"])
    out.write_bytes(b"\xff\xfe")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    row = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
        )
    )["lenses"][0]
    assert row["reason"] == "out ilegible: UnicodeDecodeError"


def test_finish_negative_rc_is_no_vote(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = _guard_payload(artifacts)
    data["artifacts"][0]["rc"] = -9
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    row = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
        )
    )["lenses"][0]
    assert row["reason"] == "rc negativo"


def test_finish_preserves_start_row_rc(tmp_path: Path) -> None:
    start, _artifacts = _world(tmp_path)
    start_data = _guard_payload(start)
    start_data["lenses"][0]["rc"] = 17
    start.write_text(json.dumps(start_data), encoding="utf-8")
    row = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(_artifacts),
            output_receipt=str(tmp_path / "finish.json"),
        )
    )["lenses"][0]
    assert row["rc"] == 17


def test_finish_non_string_output_path_is_finish_error(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    with pytest.raises(FinishError, match="output_receipt"):
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=None,  # type: ignore[arg-type]
        )


def test_finish_plain_first_line_then_json_is_plain_text(tmp_path: Path) -> None:
    start, artifacts = _world(tmp_path)
    data = _guard_payload(artifacts)
    out = Path(data["artifacts"][0]["out_path"])
    plain = "A" * 220 + "\nDECISION: APPROVE"
    later = json.dumps({"type": "text", "part": {"type": "text", "text": "short"}})
    out.write_text(plain + "\n" + later, encoding="utf-8")
    artifacts.write_text(json.dumps(data), encoding="utf-8")
    row = _guard_payload(
        finish_ticket(
            ticket="WOT-2026-152h",
            start_receipt=str(start),
            artifacts=str(artifacts),
            output_receipt=str(tmp_path / "finish.json"),
        )
    )["lenses"][0]
    assert row["mode"] == "TEXTO"
    assert row["vote"] == "APPROVE"
    assert row["last_text_bytes"] == len(plain.encode("utf-8"))


def test_finish_json_record_documents_private_sentinel() -> None:
    assert "_NOT_JSON" in (finish_module._json_record.__doc__ or "")
