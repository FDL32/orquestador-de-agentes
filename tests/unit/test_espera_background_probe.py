"""Before: define hermetic acceptance tests for the background probe.

During: build synthetic transcript records and pin every required aggregate.
After: prove read-only reporting, classification, raw-key probing, and root deduplication.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_probe():
    """Before: locate the new script without package side effects.

    During: import the module directly from its repository path.
    After: return the loaded probe module for the tests.
    """
    path = (
        Path(__file__).parents[2] / "scripts" / "flight" / "espera_background_probe.py"
    )
    spec = importlib.util.spec_from_file_location("espera_background_probe", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _record(session_id, timestamp, **values):
    """Before: receive synthetic transcript fields.

    During: combine the fields with stable session metadata.
    After: return one realistic transcript record.
    """
    return {"sessionId": session_id, "timestamp": timestamp, **values}


def _tool_pair(
    session_id,
    number,
    timestamp,
    name,
    duration_ms,
    permission=None,
    background=None,
    result_extra=None,
    record_extra=None,
):
    """Before: receive one synthetic tool-call specification.

    During: create its assistant tool-use record and result record.
    After: return both records in transcript order.
    """
    uuid = f"u-{session_id}-{number}"
    input_payload = {}
    if background is not None:
        input_payload["run_in_background"] = background
    assistant = _record(
        session_id,
        timestamp,
        type="assistant",
        uuid=uuid,
        message={
            "content": [{"type": "tool_use", "name": name, "input": input_payload}]
        },
    )
    tool_result = dict(result_extra or {})
    if duration_ms is not None:
        tool_result["durationMs"] = duration_ms
    result = _record(
        session_id,
        timestamp,
        type="user",
        sourceToolAssistantUUID=uuid,
        toolUseResult=tool_result,
    )
    if permission is not None:
        result["permissionDecision"] = permission
    result.update(record_extra or {})
    return [assistant, result]


def _fixture(tmp_path):
    """Before: start from an empty temporary transcript root.

    During: create three sessions covering classes, raw keys, shells, windows, and secrets.
    After: return the root and the expected synthetic transcript paths.
    """
    root = tmp_path / "projects"
    root.mkdir()
    s1 = []
    s1 += _tool_pair("s1", "a", "2026-01-01T00:00:00Z", "Bash", 301000, "allow", False)
    s1 += _tool_pair("s1", "b", "2026-01-01T00:00:01Z", "Bash", 900000, "allow", True)
    s1 += _tool_pair("s1", "c", "2026-01-01T00:00:02Z", "PowerShell", 400000, "ask")
    s1 += _tool_pair("s1", "d", "2026-01-01T00:00:03Z", "Read", 300001)
    s1 += _tool_pair("s1", "e", "2026-01-01T00:00:04Z", "Bash", 299999, "allow", False)
    s1 += _tool_pair("s1", "f", "2026-01-01T00:00:05Z", "Bash", 300000, "allow", False)
    s1 += _tool_pair("s1", "g", "2026-01-01T00:00:06Z", "PowerShell", 350000, "deny")
    s1 += _tool_pair("s1", "h", "2026-01-01T00:00:07Z", "PowerShell", 360000, "denied")
    s1 += _tool_pair(
        "s1",
        "i",
        "2026-01-01T00:00:08Z",
        "Bash",
        450000,
        result_extra={"isBackground": True},
    )
    s1 += _tool_pair(
        "s1",
        "j",
        "2026-01-01T00:00:09Z",
        "Read",
        None,
        record_extra={"durationMs": 999999},
        result_extra={},
    )
    s1 += [
        _record(
            "s1",
            "2026-01-01T00:00:10Z",
            type="attachment",
            attachment={"durationMs": 999999},
        ),
        _record(
            "s1",
            "2026-01-01T00:00:11Z",
            type="assistant",
            message={
                "content": [{"type": "text", "name": "Bash", "text": "not a tool"}]
            },
        ),
        _record(
            "s1",
            "2026-01-01T00:00:00Z",
            background_tasks=[{"id": 1}],
            session_crons=[{"secret": "TEXTO-SECRETO-FIXTURE"}],
        ),
        _record("s1", "2026-01-01T00:25:00Z", background_tasks=[{"id": 2}]),
        _record(
            "s1",
            "2026-01-01T00:25:01Z",
            type="attachment",
            attachment={"progress": 1},
        ),
        _record(
            "s1",
            "2026-01-01T00:25:02Z",
            type="user",
            message={
                "content": [
                    {"type": "text", "text": "TEXTO-SECRETO-FIXTURE human message"}
                ]
            },
        ),
        _record("s1", "2026-01-01T00:30:00Z", background_tasks=[{"id": 3}]),
        _record("s1", "2026-01-01T00:40:00Z", background_tasks=[{"id": 4}]),
        _record(
            "s1",
            "2026-01-01T00:40:01Z",
            type="user",
            isMeta=True,
            message={"content": [{"type": "text", "text": "meta"}]},
        ),
        _record(
            "s1",
            "2026-01-01T00:40:02Z",
            type="assistant",
            message={"content": [{"type": "text", "text": "progress"}]},
        ),
        _record(
            "s1",
            "2026-01-01T00:40:03Z",
            type="user",
            message={"content": [{"type": "text", "text": "later human"}]},
        ),
    ]
    s2 = [
        *_tool_pair("s2", "a", "2026-01-01T00:00:00Z", "Bash", 1000),
        _record("s2", "2026-01-01T00:00:00Z", session_crons={}, background_tasks=[]),
        _record("s2", "2026-01-01T00:00:00Z", background_tasks=[1]),
        _record("s2", "2026-01-01T00:05:00Z", background_tasks=[2]),
    ]
    s3 = [
        *_tool_pair("s3", "a", "2026-01-01T00:00:00Z", "PowerShell", 250000),
        "{no-json",
    ]
    s4 = [
        _record("s4", "2026-01-01T00:00:00Z", session_crons={}, background_tasks=[]),
        _record(
            "s4",
            "2026-01-01T00:00:01Z",
            session_crons=[{"secret": "TEXTO-SECRETO-FIXTURE"}],
            background_tasks=[{"id": 1}],
        ),
        _record("s4", "2026-01-01T00:00:02Z", session_crons={}, background_tasks=[]),
    ]
    s5 = [_record("s5", "2026-01-01T00:00:00Z", session_crons=[], background_tasks=[])]
    paths = []
    for session_id, records in (
        ("s1", s1),
        ("s2", s2),
        ("s3", s3),
        ("s4", s4),
        ("s5", s5),
    ):
        parent = root / "project-x" if session_id == "s3" else root
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / f"{session_id}.jsonl"
        path.write_text(
            "".join(
                record if isinstance(record, str) else json.dumps(record) + "\n"
                for record in records
            ),
            encoding="utf-8",
            newline="\n",
        )
        paths.append(path)
    return root, paths


def _tree_snapshot(root):
    """Before: receive a fixture root.

    During: inspect file metadata without changing the tree.
    After: return a deterministic metadata snapshot.
    """
    return sorted(
        (str(path.relative_to(root)), path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    )


def test_probe_counts_long_calls_by_tool_with_class(tmp_path):
    """Before: prepare calls over and under the strict duration threshold.

    During: build the report and inspect tool and class aggregates.
    After: confirm all four class buckets and per-tool counts are pinned.
    """
    probe = _load_probe()
    root, _ = _fixture(tmp_path)
    report = probe.build_report([root])
    lines = report.splitlines()
    assert "long_calls_total: 7" in lines
    assert "long_call[Bash]: 3" in lines
    assert "long_call[PowerShell]: 3" in lines
    assert "long_call[Read]: 1" in lines
    assert "class[foreground]: 1" in lines
    assert "class[fondo]: 2" in lines
    assert "class[aprobacion]: 3" in lines
    assert "class[NO_CLASIFICADA]: 1" in lines
    assert "window_count: 4" in lines
    assert "window_ms_total: 2400000" in lines
    assert "window_push: 1" in lines


def test_probe_counts_raw_payload_keys(tmp_path):
    """Before: prepare present, empty, and absent raw payload keys.

    During: build the report and inspect raw-key and shell aggregates.
    After: confirm key states are distinguished without interpreting values.
    """
    probe = _load_probe()
    root, _ = _fixture(tmp_path)
    lines = probe.build_report([root]).splitlines()
    expected = {
        "raw[session_crons][s1]: present",
        "raw[session_crons][s2]: empty",
        "raw[session_crons][s3]: absent",
        "raw[session_crons][s4]: present",
        "raw[session_crons][s5]: empty",
        "raw[background_tasks][s1]: present",
        "raw[background_tasks][s2]: present",
        "raw[background_tasks][s3]: absent",
        "raw[background_tasks][s4]: present",
        "raw[background_tasks][s5]: empty",
        "shells[Bash]: 6",
        "shells[PowerShell]: 4",
        "corrupt_lines: 1",
    }
    assert expected <= set(lines)


def test_probe_dedupes_roots_by_resolved_path(tmp_path):
    """Before: prepare two roots and a repeated textual alias.

    During: inventory the roots through the public report API.
    After: confirm resolved roots and transcripts are counted once.
    """
    probe = _load_probe()
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    for root, session_id in ((root_a, "one"), (root_b, "two")):
        (root / f"{session_id}.jsonl").write_text(
            json.dumps({"sessionId": session_id}) + "\n", encoding="utf-8", newline="\n"
        )
    report = probe.build_report([root_a, root_a / ".." / root_a.name, root_b])
    lines = report.splitlines()
    assert "roots_declaradas: 3" in lines
    assert "roots_efectivas: 2" in lines
    assert "transcripts: 2" in lines
    assert f"root[0]: {root_a.resolve()}" in lines
    assert f"root[1]: {root_b.resolve()}" in lines


def test_probe_report_has_only_counts_and_no_message_text(tmp_path, capsys):
    """Before: prepare transcripts containing a secret marker and human text.

    During: run the CLI twice and snapshot the fixture around both read-only calls.
    After: confirm only aggregate output is emitted and the tree is unchanged.
    """
    probe = _load_probe()
    root, _ = _fixture(tmp_path)
    before = _tree_snapshot(tmp_path)
    assert probe.main(["--root", str(root)]) == 0
    output = capsys.readouterr().out
    after = _tree_snapshot(tmp_path)
    assert before == after
    assert "TEXTO-SECRETO-FIXTURE" not in output
    assert "human message" not in output
    assert "long_calls_total: 7" in output
    assert "transcripts: 5" in output
    assert "class[foreground]: 1" in output
    assert "limit: 200" in output
    assert "aviso: sin limite" not in output
    unlimited = probe.build_report([root], limit=0)
    assert "limit: 0" in unlimited
    assert "aviso: sin limite (recorrido completo)" in unlimited
    assert probe.main(["--root", str(root), "--redact-roots"]) == 0
    redacted = capsys.readouterr().out
    assert str(root) not in redacted
    assert "roots_efectivas: 1" in redacted
