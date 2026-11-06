"""Tests for the explicit, fail-closed 4B-finish-1 reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
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
