"""Tests for the explicit, fail-closed 4B-start dispatcher."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.flight.start_ticket import StartError, start_ticket


start_ticket_module = importlib.import_module("scripts.flight.start_ticket")


def _run(command: list[str], *, cwd=None, **kwargs):
    return subprocess.run(command, cwd=cwd, **kwargs)


def _git(repo: Path, *args: str) -> str:
    return _run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "--all")
    _run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@t",
            "commit",
            "-m",
            message,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return _git(repo, "rev-parse", "HEAD")


def _world(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "source repo"
    source.mkdir()
    _git(source, "init", "-q")
    (source / "file.txt").write_text("base\n", encoding="utf-8")
    base = _commit(source, "base")
    (source / "file.txt").write_text("base\ntip\n", encoding="utf-8")
    tip = _commit(source, "tip")
    project = tmp_path / "project"
    (project / ".agent" / "runtime" / "ensemble").mkdir(parents=True)
    dispatcher = tmp_path / "dispatcher.py"
    dispatcher.write_text(
        "import json, os, pathlib, sys\n"
        "p=pathlib.Path(sys.argv[sys.argv.index('--project-root')+1])\n"
        "k=sys.argv[sys.argv.index('--backend-key')+1]\n"
        "loop=sys.argv[sys.argv.index('--loop-id')+1]\n"
        "row={'event':'ronda','ticket':sys.argv[sys.argv.index('--ticket')+1],"
        "'phase':sys.argv[sys.argv.index('--phase')+1],"
        "'loop_id':sys.argv[sys.argv.index('--loop-id')+1],"
        "'backend_key':k,'commit_sha':sys.argv[sys.argv.index('--commit-sha')+1],"
        "'challenge_nonce':sys.argv[sys.argv.index('--challenge-nonce')+1],"
        "'model':'m-'+k,'model_reported':None if loop=='NO_LEGIBLE' else ('other' if loop=='DISCREPANT' else 'm-'+k),'cwd':str(pathlib.Path.cwd())}\n"
        "write = os.environ.get('FAKE_WRITE') != '0' and not (loop == 'MUTE_REVIEWER' and k == 'REVIEWER')\n"
        "if write and loop != 'NO_RECEIPT' and loop != 'FAIL_RC':\n"
        " with (p/'.agent/runtime/ensemble/scorecard.jsonl').open('a', encoding='utf-8') as f: f.write(json.dumps(row)+'\\n')\n"
        "if loop == 'FAIL_RC': sys.exit(7)\n"
        "print(pathlib.Path.cwd())\n",
        encoding="utf-8",
    )
    roster = tmp_path / "roster.json"
    roster.write_text(
        json.dumps(
            {
                "excluded_lenses": {},
                "session_types": {
                    "implantacion": {
                        "lenses": {
                            "MANAGER_REVIEW": [
                                {"backend_key": "BA03", "profile": "profile-ba03"},
                                {
                                    "backend_key": "BA254",
                                    "profile": "profile-ba254",
                                },
                            ]
                        },
                        "revisor": {
                            "backend_key": "REVIEWER",
                            "profile": "profile-reviewer",
                            "channel": "loop-round",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    agents = tmp_path / "agents.json"
    agents.write_text(
        json.dumps(
            {
                "ensemble_registry": {
                    "backend_keys": {
                        "BA03": {"family": "glm"},
                        "BA254": {"family": "codex"},
                        "REVIEWER": {"family": "review"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return {
        "source": source,
        "base": base,
        "tip": tip,
        "project": project,
        "dispatcher": dispatcher,
        "roster": roster,
        "agents": agents,
    }


def _start(world: dict[str, object], tmp_path: Path, **overrides):
    values = {
        "ticket": "WOT-2026-999x",
        "base": world["base"],
        "tip": world["tip"],
        "source_repo": world["source"],
        "clone_dir": tmp_path / "clone",
        "output_dir": tmp_path / "out",
        "roster_path": world["roster"],
        "session_type": "implantacion",
        "agents_config": world["agents"],
        "builder_family": "codex2",
        "project_root": world["project"],
        "dispatcher": world["dispatcher"],
        "python": sys.executable,
        "loop_id": "L-test",
        "phase": "MANAGER_REVIEW",
        "challenge_nonce": "n" * 32,
    }
    values.update(overrides)
    return start_ticket(**values)


def test_start_dispatches_lenses_with_clone_cwd_and_models(tmp_path: Path) -> None:
    world = _world(tmp_path)
    receipt = _start(world, tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert len(payload["lenses"]) == 3
    assert {row["role"] for row in payload["lenses"]} == {"lens", "revisor"}
    assert [row["role"] for row in payload["lenses"]] == [
        "lens",
        "lens",
        "revisor",
    ]
    assert {row["model_requested"] for row in payload["lenses"]} == {
        "m-BA03",
        "m-BA254",
        "m-REVIEWER",
    }
    scorecard = [
        json.loads(line)
        for line in (world["project"] / ".agent/runtime/ensemble/scorecard.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {row["cwd"] for row in scorecard} == {str(tmp_path / "clone")}


def test_start_reloads_roster_before_each_dispatch(tmp_path: Path) -> None:
    world = _world(tmp_path)
    calls = 0

    def change_roster_after_first_dispatch(command, **kwargs):
        nonlocal calls
        result = _run(command, **kwargs)
        if "loop-round" in command:
            calls += 1
            if calls == 1:
                roster = json.loads(Path(world["roster"]).read_text(encoding="utf-8"))
                roster["session_types"]["implantacion"]["lenses"][
                    "MANAGER_REVIEW"
                ].pop()
                Path(world["roster"]).write_text(json.dumps(roster), encoding="utf-8")
        return result

    with pytest.raises(StartError, match="roster cambio antes del despacho: BA254"):
        _start(world, tmp_path, runner=change_roster_after_first_dispatch)


@pytest.mark.parametrize("field", ["channel", "profile"])
def test_start_rejects_invalid_reviewer_contract(tmp_path: Path, field: str) -> None:
    world = _world(tmp_path)
    roster = json.loads(Path(world["roster"]).read_text(encoding="utf-8"))
    if field == "channel":
        roster["session_types"]["implantacion"]["revisor"][field] = "text"
    else:
        roster["session_types"]["implantacion"]["revisor"].pop(field)
    Path(world["roster"]).write_text(json.dumps(roster), encoding="utf-8")
    with pytest.raises(StartError, match="revisor invalido"):
        _start(world, tmp_path)


def test_start_rejects_excluded_reviewer(tmp_path: Path) -> None:
    world = _world(tmp_path)
    roster = json.loads(Path(world["roster"]).read_text(encoding="utf-8"))
    roster["excluded_lenses"] = {"REVIEWER": "test"}
    Path(world["roster"]).write_text(json.dumps(roster), encoding="utf-8")
    with pytest.raises(StartError, match="lente excluida: REVIEWER"):
        _start(world, tmp_path)


def test_start_reviewer_without_row_is_non_ok(tmp_path: Path) -> None:
    world = _world(tmp_path)
    receipt = _start(world, tmp_path, loop_id="MUTE_REVIEWER")
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    statuses = {row["backend_key"]: row["status"] for row in payload["lenses"]}
    assert statuses["REVIEWER"] == "SIN_RECIBO"
    assert all(status == "OK" for key, status in statuses.items() if key != "REVIEWER")


def test_start_reinvocation_without_new_scorecard_row_is_non_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world(tmp_path)
    _start(world, tmp_path, loop_id="REINVOCATION")
    monkeypatch.setenv("FAKE_WRITE", "0")
    receipt = _start(world, tmp_path, loop_id="REINVOCATION")
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert {row["status"] for row in payload["lenses"]} == {"SIN_RECIBO"}


def test_start_reinvocation_with_new_scorecard_rows_is_ok(tmp_path: Path) -> None:
    world = _world(tmp_path)
    _start(world, tmp_path, loop_id="REINVOCATION")
    receipt = _start(world, tmp_path, loop_id="REINVOCATION")
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert {row["status"] for row in payload["lenses"]} == {"OK"}


def _seed_scorecard_row(world: dict[str, object], values: dict[str, str]) -> None:
    path = world["project"] / ".agent/runtime/ensemble/scorecard.jsonl"
    path.write_text(json.dumps(values) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    "field",
    [
        "ticket",
        "phase",
        "loop_id",
        "backend_key",
        "commit_sha",
        "challenge_nonce",
        "event",
    ],
)
def test_start_count_filters_all_fields_before_dispatch(
    tmp_path: Path, field: str
) -> None:
    world = _world(tmp_path)
    row = {
        "event": "ronda",
        "ticket": "WOT-2026-999x",
        "phase": "MANAGER_REVIEW",
        "loop_id": "COUNT-FILTERS",
        "backend_key": "BA03",
        "commit_sha": world["tip"],
        "challenge_nonce": "n" * 32,
        "model": "old",
        "model_reported": "old",
    }
    row[field] = {
        "ticket": "other-ticket",
        "phase": "OTHER_PHASE",
        "loop_id": "OTHER_LOOP",
        "backend_key": "OTHER_BACKEND",
        "commit_sha": "0" * 40,
        "challenge_nonce": "x" * 32,
        "event": "other",
    }[field]
    _seed_scorecard_row(world, row)
    receipt = _start(world, tmp_path, loop_id="COUNT-FILTERS")
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    statuses = {item["backend_key"]: item["status"] for item in payload["lenses"]}
    assert statuses["BA03"] == "OK"


@pytest.mark.parametrize(
    "field",
    [
        "ticket",
        "phase",
        "loop_id",
        "backend_key",
        "commit_sha",
        "challenge_nonce",
        "event",
    ],
)
def test_start_count_filters_all_fields_reject_mute_after_prior_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    world = _world(tmp_path)
    row = {
        "event": "ronda",
        "ticket": "WOT-2026-999x",
        "phase": "MANAGER_REVIEW",
        "loop_id": "COUNT-FILTERS",
        "backend_key": "BA03",
        "commit_sha": world["tip"],
        "challenge_nonce": "n" * 32,
        "model": "old",
        "model_reported": "old",
    }
    row[field] = {
        "ticket": "other-ticket",
        "phase": "OTHER_PHASE",
        "loop_id": "OTHER_LOOP",
        "backend_key": "OTHER_BACKEND",
        "commit_sha": "0" * 40,
        "challenge_nonce": "x" * 32,
        "event": "other",
    }[field]
    _seed_scorecard_row(world, row)
    monkeypatch.setenv("FAKE_WRITE", "0")
    receipt = _start(world, tmp_path, loop_id="COUNT-FILTERS")
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    statuses = {item["backend_key"]: item["status"] for item in payload["lenses"]}
    assert statuses["BA03"] == "SIN_RECIBO"


@pytest.mark.parametrize(
    "field",
    [
        "ticket",
        "phase",
        "loop_id",
        "backend_key",
        "commit_sha",
        "challenge_nonce",
        "event",
    ],
)
def test_start_rejects_scorecard_row_with_wrong_filter(
    tmp_path: Path, field: str
) -> None:
    world = _world(tmp_path)
    dispatcher = Path(world["dispatcher"])
    text = dispatcher.read_text(encoding="utf-8")
    replacements = {
        "challenge_nonce": (
            "'challenge_nonce':sys.argv[sys.argv.index('--challenge-nonce')+1]",
            "'challenge_nonce':'wrong'",
        ),
        "commit_sha": (
            "'commit_sha':sys.argv[sys.argv.index('--commit-sha')+1]",
            "'commit_sha':'wrong'",
        ),
        "loop_id": (
            "'loop_id':sys.argv[sys.argv.index('--loop-id')+1]",
            "'loop_id':'wrong'",
        ),
        "event": ("'event':'ronda'", "'event':'adjudicate'"),
        "ticket": (
            "'ticket':sys.argv[sys.argv.index('--ticket')+1]",
            "'ticket':'wrong'",
        ),
        "phase": (
            "'phase':sys.argv[sys.argv.index('--phase')+1]",
            "'phase':'wrong'",
        ),
        "backend_key": ("'backend_key':k", "'backend_key':'wrong'"),
    }
    old, new = replacements[field]
    dispatcher.write_text(text.replace(old, new), encoding="utf-8")
    receipt = _start(world, tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert {row["status"] for row in payload["lenses"]} == {"SIN_RECIBO"}


def test_start_uses_latest_matching_scorecard_row(tmp_path: Path) -> None:
    world = _world(tmp_path)
    Path(world["dispatcher"]).write_text(
        "import json, pathlib, sys\n"
        "p=pathlib.Path(sys.argv[sys.argv.index('--project-root')+1])\n"
        "k=sys.argv[sys.argv.index('--backend-key')+1]\n"
        "row={'event':'ronda','ticket':sys.argv[sys.argv.index('--ticket')+1],"
        "'phase':sys.argv[sys.argv.index('--phase')+1],"
        "'loop_id':sys.argv[sys.argv.index('--loop-id')+1],"
        "'backend_key':k,'commit_sha':sys.argv[sys.argv.index('--commit-sha')+1],"
        "'challenge_nonce':sys.argv[sys.argv.index('--challenge-nonce')+1],"
        "'model':'old','model_reported':'old'}\n"
        "path=p/'.agent/runtime/ensemble/scorecard.jsonl'\n"
        "with path.open('a', encoding='utf-8') as f:\n"
        " f.write(json.dumps(row)+'\\n')\n"
        " row['model']='latest'; row['model_reported']='latest'\n"
        " f.write(json.dumps(row)+'\\n')\n",
        encoding="utf-8",
    )
    receipt = _start(world, tmp_path, loop_id="MULTI")
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert {row["model_requested"] for row in payload["lenses"]} == {"latest"}


@pytest.mark.parametrize(
    "field",
    [
        "roster_path",
        "session_type",
        "agents_config",
        "builder_family",
        "clone_dir",
        "output_dir",
        "project_root",
        "dispatcher",
        "challenge_nonce",
    ],
)
def test_start_requires_explicit_inputs(tmp_path: Path, field: str) -> None:
    world = _world(tmp_path)
    value = ""
    with pytest.raises(StartError):
        _start(world, tmp_path, **{field: value})


@pytest.mark.parametrize(
    "change",
    [
        "lenses_absent",
        "phase_absent",
        "revisor_absent",
        "excluded_lenses",
        "builder_family",
        "reviewer_duplicate",
        "duplicate_pair",
    ],
)
def test_start_rejects_roster_contract(tmp_path: Path, change: str) -> None:
    world = _world(tmp_path)
    roster = json.loads(Path(world["roster"]).read_text(encoding="utf-8"))
    session = roster["session_types"]["implantacion"]
    if change == "lenses_absent":
        session.pop("lenses")
    elif change == "phase_absent":
        session["lenses"].pop("MANAGER_REVIEW")
    elif change == "revisor_absent":
        session.pop("revisor")
    elif change == "excluded_lenses":
        roster["excluded_lenses"] = {"BA03": "test"}
    elif change == "builder_family":
        pass
    elif change == "reviewer_duplicate":
        session["revisor"]["backend_key"] = "BA03"
    else:
        session["lenses"]["MANAGER_REVIEW"][1]["backend_key"] = "BA03"
    Path(world["roster"]).write_text(json.dumps(roster), encoding="utf-8")
    if change == "builder_family":
        with pytest.raises(StartError, match="familia del Builder"):
            _start(world, tmp_path, builder_family="glm")
    else:
        with pytest.raises(StartError):
            _start(world, tmp_path)


def test_start_rejects_unreadable_effective_model(tmp_path: Path) -> None:
    world = _world(tmp_path)
    receipt = _start(world, tmp_path, loop_id="NO_LEGIBLE")
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert {row["status"] for row in payload["lenses"]} == {"NO_LEGIBLE"}


def test_start_records_missing_agent_family_as_no_legible(tmp_path: Path) -> None:
    world = _world(tmp_path)
    agents = json.loads(Path(world["agents"]).read_text(encoding="utf-8"))
    agents["ensemble_registry"]["backend_keys"].pop("BA03")
    Path(world["agents"]).write_text(json.dumps(agents), encoding="utf-8")
    receipt = _start(world, tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    statuses = {row["backend_key"]: row["status"] for row in payload["lenses"]}
    assert statuses == {
        "BA03": "NO_LEGIBLE",
        "BA254": "OK",
        "REVIEWER": "OK",
    }


def test_main_returns_one_when_receipt_has_non_ok_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = tmp_path / "start_receipt.json"
    receipt.write_text(
        json.dumps({"lenses": [{"backend_key": "BA03", "status": "SIN_RECIBO"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(start_ticket_module, "start_ticket", lambda **_: receipt)
    argv = [
        flag
        for name, value in {
            "ticket": "T",
            "base": "B",
            "tip": "T",
            "source-repo": "S",
            "clone-dir": "C",
            "output-dir": "O",
            "roster-path": "R",
            "session-type": "implantacion",
            "agents-config": "A",
            "builder-family": "codex",
            "project-root": "P",
            "dispatcher": "D",
            "python": "python",
            "loop-id": "L",
            "phase": "MANAGER_REVIEW",
            "challenge-nonce": "N",
        }.items()
        for flag in (f"--{name}", value)
    ]
    assert start_ticket_module.main(argv) == 1


@pytest.mark.parametrize(
    ("loop_id", "status"),
    [
        ("DISCREPANT", "DISCREPANTE"),
        ("NO_RECEIPT", "SIN_RECIBO"),
        ("FAIL_RC", "FALLO_RC"),
    ],
)
def test_start_records_non_ok_lens_states(
    tmp_path: Path, loop_id: str, status: str
) -> None:
    world = _world(tmp_path)
    receipt = _start(world, tmp_path, loop_id=loop_id)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert {row["status"] for row in payload["lenses"]} == {status}


def test_start_rejects_clone_head_mismatch(tmp_path: Path) -> None:
    world = _world(tmp_path)
    clone = tmp_path / "clone"
    _run(
        ["git", "clone", "--no-hardlinks", str(world["source"]), str(clone)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    _run(
        ["git", "-C", str(clone), "checkout", "--detach", world["base"]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    def leave_clone_at_base(command, **kwargs):
        if command[:2] == ["git", "-C"] and "checkout" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return _run(command, **kwargs)

    with pytest.raises(StartError, match="HEAD del clon"):
        _start(world, tmp_path, runner=leave_clone_at_base)


def test_start_rejects_invalid_tip_reference(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with pytest.raises(StartError, match="ref invalida"):
        _start(world, tmp_path, tip="0" * 40)
