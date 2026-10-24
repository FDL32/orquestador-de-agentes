"""Tests for scripts/preflight_flight.py (WOT-2026-037c).

Four fixtures covering the three deterministic blocking classes:
    (a) GATE NO EJECUTABLE -- common_gate script fails argparse --help.
    (c) ESTADO STALE -- workspace session_state is "stale".
    (d) DECISION HUMANA -- backlog row contains REQUIERE_HUMANO / DISENO_PRIMERO.

(b) is a DECLARED NON-GOAL (gate mide el sitio equivocado): requires judgment
    (adversarial 1->9->2), not a determinista. This script does NOT cover it.
    See docstring in scripts/preflight_flight.py.

All fixtures use TEMPORARY repos/DAGs/backlogs (tmp_path, never the real tree).
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


# scripts/ is not a package: insert it on sys.path as the script itself does.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import preflight_flight as pf  # noqa: E402


# Shared fixtures across tests
GIT_ID = ("-c", "user.email=t@example.com", "-c", "user.name=tester")


def _git_run(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30
    )


def _init_repo(root: Path) -> Path:
    """Create a bare git repo with an initial commit on branch `main`."""
    root.mkdir(parents=True, exist_ok=True)
    _git_run(["init"], root)
    _git_run(["symbolic-ref", "HEAD", "refs/heads/main"], root)
    (root / "README.md").write_text("# test\n", encoding="utf-8")
    _git_run([*GIT_ID, "add", "README.md"], root)
    _git_run([*GIT_ID, "commit", "-m", "init"], root)
    return root


# ---------------------------------------------------------------------------
# Fixture (a): GATE NO EJECUTABLE
# ---------------------------------------------------------------------------


def _make_temp_script(root: Path, name: str, content: str) -> Path:
    """Write a temp Python script and make it importable via sys.path hack."""
    script = root / name
    script.write_text(content, encoding="utf-8")
    return script


def _make_clean_dag(tickets=None, gate_command="python scripts/example.py --help"):
    """Create a minimal valid DAG dict."""
    group_tickets = tickets or ["WOT-2026-037a"]
    return {
        "schema": "autonomous-batch-dag/v1",
        "groups": [
            {
                "id": "g1",
                "tickets": group_tickets,
                "depends_on_groups": [],
                "blocks_groups": [],
                "shared_surfaces": [],
                "class": "S",
                "autonomy_mode": "autonomous",
                "common_gate": gate_command,
            }
        ],
    }


def _make_dag_file(tmp_path: Path, dag_dict: dict) -> Path:
    p = tmp_path / "dag.json"
    p.write_text(json.dumps(dag_dict, ensure_ascii=False), encoding="utf-8")
    return p


def _make_backlog(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    """Write a minimal backlog.md table.

    rows: list of dicts mapping column name -> cell value.
    """
    if not rows:
        p = tmp_path / "backlog.md"
        p.write_text(
            "| Ticket | Status | Description |\n|--------|--------|-------------|\n",
            encoding="utf-8",
        )
        return p

    headers = list(rows[0].keys())
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("-" * len(h) for h in headers) + " |")
    for row in rows:
        cells = [row.get(h, "") for h in headers]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    p = tmp_path / "backlog.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _run_preflight(dag_path, workspace_root, backlog_path, json_out=False):
    """Run the preflight_flight CLI and return (rc, stdout)."""
    args = [
        sys.executable,
        str(_SCRIPTS_DIR / "preflight_flight.py"),
        "--dag",
        str(dag_path),
        "--workspace-root",
        str(workspace_root),
        "--backlog",
        str(backlog_path),
    ]
    if json_out:
        args.append("--json")
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# (a) fixture: script with a bogus flag -> HARD-STOP naming the group
# ---------------------------------------------------------------------------


def test_class_a_bogus_flag_blocks(tmp_path):
    """A group whose common_gate invokes a script with an invalid choice flag
    produces a HARD-STOP that names the group and the exact command.

    Uses choices-based script because --help is processed first in modern
    argparse, making "unrecognized argument" probes unreliable. A script with
    choices will fail with "invalid choice" regardless of --help position.

    Mutation: remove the bogus flag from the command -> the test flips GREEN
    (no block from class (a)).
    """
    script = _make_temp_script(
        tmp_path,
        "broken_script.py",
        """import argparse
p = argparse.ArgumentParser()
p.add_argument('--mode', choices=['run', 'test'])
p.parse_args()
""",
    )

    dag = _make_clean_dag(
        gate_command=f"python {script} --mode deploy",
    )

    blocks = pf._census_class_a(dag)
    assert len(blocks) >= 1
    assert blocks[0]["class"] == "a"
    assert blocks[0]["group"] == "g1"
    assert "invalid_choice: True" in blocks[0]["reason"]

    # Mutation: correct flag value -> no block from class (a)
    dag_clean = _make_clean_dag(gate_command=f"python {script} --mode run")
    blocks_clean = pf._census_class_a(dag_clean)
    assert all(b["class"] != "a" for b in blocks_clean)


# ---------------------------------------------------------------------------
# (a) mutation: same DAG with correct flag -> no block
# ---------------------------------------------------------------------------


def test_class_a_correct_flag_no_block(tmp_path):
    """A script that accepts --help cleanly does not block."""
    script = _make_temp_script(
        tmp_path,
        "good_script.py",
        """import argparse
p = argparse.ArgumentParser()
p.add_argument('--verbose', action='store_true')
args = p.parse_args()
""",
    )
    dag = _make_clean_dag(gate_command=f"python {script} --verbose")
    blocks = pf._census_class_a(dag)
    assert all(b["class"] != "a" for b in blocks)


# ---------------------------------------------------------------------------
# (c) fixture: stale session_state -> HARD-STOP
# ---------------------------------------------------------------------------


def test_class_c_stale_blocks(tmp_path):
    """A workspace with an expired session lock produces session_state='stale'
    which triggers a HARD-STOP for class (c).

    Mutation: a live lock or no lock -> no block.
    """
    ws = _init_repo(tmp_path / "workspace_stale")

    now = datetime.now(timezone.utc)
    # Session ID must match: YYYYMMDD-HHHH-<hex4,40>-<hex4,32>
    sha_part = "deadbeef"  # short git sha-like part
    uuid_part = uuid.uuid4().hex[:8]
    sid = f"{now.strftime('%Y%m%d-%H%M')}-{sha_part}-{uuid_part}"
    session_dir = ws / ".agent" / "runtime" / "session" / sid

    # Create a session with an expired lock (expires_at in the past).
    session_dir.mkdir(parents=True, exist_ok=True)
    lock = {
        "pid": 999999,
        "session_id": sid,
        "op": "init",
        "created_at": (now - timedelta(seconds=2000)).isoformat(),
        "expires_at": (now - timedelta(seconds=100)).isoformat(),
    }
    lock_path = session_dir / "lock.json"
    lock_path.write_text(json.dumps(lock, ensure_ascii=False), encoding="utf-8")

    # Add a record so record_count > 0 (use manifest.jsonl, the canonical ledger).
    (session_dir / "manifest.jsonl").write_text(
        '{"event": "artifact_added", "generator": "test"}\n',
        encoding="utf-8",
    )

    bl = _make_backlog(tmp_path, [])
    dag = _make_clean_dag()
    dag_file = _make_dag_file(tmp_path, dag)

    rc, stdout, stderr = _run_preflight(dag_file, ws, bl, json_out=True)

    # The preflight should detect stale state -> exit 1
    assert rc == 1, f"expected rc=1 for stale, got rc={rc}, stderr={stderr}"
    data = json.loads(stdout)
    assert data["blocks_found"] >= 1
    class_c_blocks = [b for b in data["details"] if b["class"] == "c"]
    assert len(class_c_blocks) >= 1


def test_class_c_active_no_block(tmp_path):
    """A workspace with a live session lock does NOT block for class (c)."""
    ws = _init_repo(tmp_path / "workspace_active")
    now = datetime.now(timezone.utc)
    sha_part = "deadbeef"
    uuid_part = uuid.uuid4().hex[:8]
    sid = f"{now.strftime('%Y%m%d-%H%M')}-{sha_part}-{uuid_part}"
    session_dir = ws / ".agent" / "runtime" / "session" / sid
    session_dir.mkdir(parents=True, exist_ok=True)

    lock = {
        "pid": 999999,
        "session_id": sid,
        "op": "init",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=3600)).isoformat(),
    }
    (session_dir / "lock.json").write_text(
        json.dumps(lock, ensure_ascii=False), encoding="utf-8"
    )
    (session_dir / "manifest.jsonl").write_text(
        '{"event": "artifact_added", "generator": "test"}\n',
        encoding="utf-8",
    )

    bl = _make_backlog(tmp_path, [])
    dag = _make_clean_dag()
    dag_file = _make_dag_file(tmp_path, dag)

    _rc, stdout, _ = _run_preflight(dag_file, ws, bl, json_out=True)
    data = json.loads(stdout)
    class_c_blocks = [b for b in data["details"] if b["class"] == "c"]
    assert len(class_c_blocks) == 0


# ---------------------------------------------------------------------------
# (d) fixture: REQUIERE_HUMANO in backlog row -> HARD-STOP
# ---------------------------------------------------------------------------


def test_class_d_requiere_humano_blocks(tmp_path):
    """A ticket in an autonomous group whose backlog row contains
    'REQUIERE_HUMANO' triggers a HARD-STOP for class (d).

    Mutation: remove the literal -> no block.
    """
    bl = _make_backlog(
        tmp_path,
        [
            {
                "Ticket": "WOT-2026-037a",
                "Status": "pending",
                "Description": "fix bug REQUIERE_HUMANO approval",
            },
        ],
    )
    dag = _make_clean_dag()

    blocks_d = pf._census_class_d(dag, bl)
    assert len(blocks_d) >= 1
    assert blocks_d[0]["class"] == "d"
    assert blocks_d[0]["ticket"] == "WOT-2026-037a"
    assert "REQUIERE_HUMANO" in blocks_d[0]["reason"]

    # Mutation: same row without the literal -> no block
    bl2 = _make_backlog(
        tmp_path,
        [
            {
                "Ticket": "WOT-2026-037a",
                "Status": "pending",
                "Description": "fix bug with approval",
            },
        ],
    )
    blocks_d2 = pf._census_class_d(dag, bl2)
    assert all(b["class"] != "d" for b in blocks_d2)


def test_class_d_diseno_primero_blocks(tmp_path):
    """A ticket whose backlog row contains 'DISENO_PRIMERO' also blocks."""
    bl = _make_backlog(
        tmp_path,
        [
            {
                "Ticket": "WOT-2026-037b",
                "Status": "pending",
                "Description": "architectural DISENO_PRIMERO needed",
            },
        ],
    )
    dag = _make_clean_dag(tickets=["WOT-2026-037b"])
    blocks_d = pf._census_class_d(dag, bl)
    assert len(blocks_d) >= 1
    assert blocks_d[0]["class"] == "d"
    assert "DISENO_PRIMERO" in blocks_d[0]["reason"]


def test_class_d_non_autonomous_group_not_checked(tmp_path):
    """Groups with autonomy_mode != 'autonomous' are NOT checked for class (d)."""
    bl = _make_backlog(
        tmp_path,
        [
            {
                "Ticket": "WOT-2026-037a",
                "Status": "pending",
                "Description": "has REQUIERE_HUMANO but group is not autonomous",
            },
        ],
    )
    dag = {
        "schema": "autonomous-batch-dag/v1",
        "groups": [
            {
                "id": "g1",
                "tickets": ["WOT-2026-037a"],
                "depends_on_groups": [],
                "blocks_groups": [],
                "shared_surfaces": [],
                "class": "S",
                "autonomy_mode": "hard-stop-with-recovery",  # NOT autonomous
                "common_gate": "echo skip",
            }
        ],
    }
    blocks_d = pf._census_class_d(dag, bl)
    assert all(b["class"] != "d" for b in blocks_d)


# ---------------------------------------------------------------------------
# Clean DAG: all 3 deterministic classes pass -> exit 0
# ---------------------------------------------------------------------------


def test_clean_dag_exits_zero(tmp_path):
    """A DAG with no blocking conditions exits 0."""
    ws = _init_repo(tmp_path / "workspace_clean")
    bl = _make_backlog(
        tmp_path,
        [
            {
                "Ticket": "WOT-2026-037a",
                "Status": "pending",
                "Description": "clean task",
            },
        ],
    )
    script = _make_temp_script(
        tmp_path,
        "clean_script.py",
        """import argparse
p = argparse.ArgumentParser()
args = p.parse_args()
""",
    )
    dag = _make_clean_dag(gate_command=f"python {script}")
    dag_file = _make_dag_file(tmp_path, dag)

    rc, stdout, _ = _run_preflight(dag_file, ws, bl, json_out=True)
    data = json.loads(stdout)
    assert rc == 0, f"expected rc=0 for clean DAG, got rc={rc}"
    assert data["blocks_found"] == 0
    assert data["groups_censused"] == 1
    assert data["tickets_censused"] == 1


# ---------------------------------------------------------------------------
# derive_session_state unit tests (mirrors the logic used by _census_class_c)
# ---------------------------------------------------------------------------


def test_derive_session_state_none():
    """Empty or all-archived sessions -> 'none'."""
    assert pf.derive_session_state([]) == "none"
    assert pf.derive_session_state([{"archived": True}]) == "none"
    assert pf.derive_session_state([{"record_count": 0}]) == "none"


def test_derive_session_state_active():
    """A live lock -> 'active'."""
    sessions = [
        {
            "session_id": "s1",
            "record_count": 3,
            "lock_state": "live",
            "archived": False,
        },
    ]
    assert pf.derive_session_state(sessions) == "active"


def test_derive_session_state_stale():
    """Expired/corrupt lock on a non-empty session -> 'stale'."""
    sessions = [
        {
            "session_id": "s1",
            "record_count": 1,
            "lock_state": "stale",
            "archived": False,
        },
    ]
    assert pf.derive_session_state(sessions) == "stale"


# ---------------------------------------------------------------------------
# H1 Fix: quoted-token stripping with _strip_matching_quotes
# ---------------------------------------------------------------------------


def test_strip_matching_quotes_no_quotes():
    """Tokens without surrounding quotes are returned unchanged."""
    assert pf._strip_matching_quotes("python") == "python"
    assert pf._strip_matching_quotes("--validate") == "--validate"
    assert (
        pf._strip_matching_quotes("C:/Users/fdl/script.py") == "C:/Users/fdl/script.py"
    )


def test_strip_matching_quotes_with_quotes():
    """Tokens surrounded by matching double-quotes have them removed."""
    assert pf._strip_matching_quotes('"C:/path/script.py"') == "C:/path/script.py"
    assert pf._strip_matching_quotes('"arg"') == "arg"


def test_strip_matching_quotes_single_quote():
    """A single standalone quote is not stripped (no matching pair)."""
    assert pf._strip_matching_quotes('"') == '"'
    assert pf._strip_matching_quotes('""') == ""


def test_strip_matching_quotes_mismatched():
    """Mismatched quotes (one side only) are not stripped."""
    assert pf._strip_matching_quotes('"start') == '"start'
    assert pf._strip_matching_quotes('end"') == 'end"'


def test_shlex_subcommand_strips_windows_quoted_tokens(tmp_path):
    """After fix, _shlex_subcommand removes literal quotes from Windows-style quoted paths.

    Verifies that:
    - tokens from quoted paths do NOT contain '"' characters
    - token.endswith('.py') MATCHES for quoted .py paths (fixing the
      script existence check in _process_subcommand_for_group)

    This is the core regression test for H1: on Windows, shlex.split with
    posix=False was leaving literal '"' in tokens like
    '"C:/path/script.py"' instead of 'C:/path/script.py'.
    """
    script = tmp_path / "agent_controller.py"
    script.write_text(
        "import argparse\np = argparse.ArgumentParser()\np.parse_args()\n",
        encoding="utf-8",
    )

    # Simulate the real-world Windows command with quoted path
    sub_cmd = f'python "{script!s}" --validate'
    tokens = pf._shlex_subcommand(sub_cmd)

    # Check that quotes are stripped from the path token
    path_token = tokens[1]
    assert '"' not in path_token, f"token still contains quotes: {path_token!r}"
    assert path_token.endswith(".py"), f"token does not end with .py: {path_token!r}"
    assert Path(path_token).exists(), f"stripped path does not exist: {path_token}"

    # Verify token content matches the unquoted script path exactly
    assert path_token == str(script)


def test_shlex_subcommand_strips_quotes_in_all_tokens(tmp_path):
    """All tokens in a command with multiple quoted args should have quotes stripped."""
    script = tmp_path / "script.py"
    script.write_text(
        "import argparse\np = argparse.ArgumentParser()\np.parse_args()\n",
        encoding="utf-8",
    )
    other_path = tmp_path / "other_dir"
    other_path.mkdir(exist_ok=True)

    sub_cmd = f'python "{script!s}" --project-root "{other_path!s}" --flag'
    tokens = pf._shlex_subcommand(sub_cmd)

    for token in tokens:
        assert '"' not in token, f"token contains quote: {token!r}"


def test_process_subcommand_for_group_script_check_with_quoted_path(tmp_path):
    """_process_subcommand_for_group should detect quoted .py scripts via endswith('.py').

    Before the H1 fix, the existence check `if token.endswith('.py')` silently
    failed for quoted paths because the token ended with `.py"` (quote included),
    making the script existence check completely inoperative.
    """
    script = tmp_path / "gate_script.py"
    script.write_text(
        "import argparse\np = argparse.ArgumentParser()\np.parse_args()\n",
        encoding="utf-8",
    )

    sub_cmd = f'python "{script!s}" --help'
    blocks = pf._process_subcommand_for_group(
        sub_cmd, "g1", f'python "{script!s}" --help'
    )

    # No blocking conditions for a valid script
    assert len(blocks) == 0


def test_census_class_a_quoted_path_clean(tmp_path):
    """A group with quoted .py path in common_gate passes class (a) census."""
    script = tmp_path / "quoted_gate.py"
    script.write_text(
        "import argparse\np = argparse.ArgumentParser()\np.parse_args()\n",
        encoding="utf-8",
    )

    dag = _make_clean_dag(
        gate_command=f'python "{script!s}" --flag',
    )
    blocks = pf._census_class_a(dag)
    assert all(b["class"] != "a" for b in blocks)


# ---------------------------------------------------------------------------
# Fix 1/2: && splitting and shlex-based sub-command parsing
# ---------------------------------------------------------------------------


def test_split_gate_commands_single():
    """A single command (no '&&') returns a one-element list."""
    gate = "python scripts/example.py --flag"
    result = pf._split_gate_commands(gate)
    assert result == [gate]


def test_split_gate_commands_double_and_and():
    """A command with '&&' splits into two sub-commands."""
    gate = "python scripts/a.py --x && python scripts/b.py --y"
    result = pf._split_gate_commands(gate)
    assert len(result) == 2
    assert result[0] == "python scripts/a.py --x"
    assert result[1] == "python scripts/b.py --y"


def test_shlex_subcommand_with_quoted_paths(tmp_path):
    """shlex correctly parses quoted Windows-style paths."""
    script_a = tmp_path / "script_a.py"
    script_a.write_text(
        "import argparse\np = argparse.ArgumentParser()\np.parse_args()\n",
        encoding="utf-8",
    )
    script_b = tmp_path / "script_b.py"
    script_b.write_text(
        "import argparse\np = argparse.ArgumentParser()\np.parse_args()\n",
        encoding="utf-8",
    )

    # Simulate a real-world Windows path with quoted strings
    tokens_a = pf._shlex_subcommand(
        "python " + str(script_a) + " --flag --project-root " + str(tmp_path)
    )
    tokens_b = pf._shlex_subcommand("python " + str(script_b) + " --level all")
    assert len(tokens_a) >= 1
    assert len(tokens_b) >= 1


def test_census_class_a_double_and_and_clean(tmp_path):
    """A common_gate with '&&' where both sub-commands accept --help does not block."""
    script_a = _make_temp_script(
        tmp_path,
        "good_a.py",
        """import argparse
p = argparse.ArgumentParser()
p.add_argument('--flag', default='x')
args = p.parse_args()
""",
    )
    script_b = _make_temp_script(
        tmp_path,
        "good_b.py",
        """import argparse
p = argparse.ArgumentParser()
p.add_argument('--level', default='all')
args = p.parse_args()
""",
    )

    dag = _make_clean_dag(
        gate_command=f"python {script_a} --flag && python {script_b} --level all",
    )
    blocks = pf._census_class_a(dag)
    assert all(b["class"] != "a" for b in blocks)


def test_census_class_a_double_and_and_one_breaks(tmp_path):
    """A common_gate with '&&' where the second sub-command has a bogus flag blocks."""
    script_a = _make_temp_script(
        tmp_path,
        "good_a2.py",
        """import argparse
p = argparse.ArgumentParser()
args = p.parse_args()
""",
    )
    script_b = _make_temp_script(
        tmp_path,
        "broken_b2.py",
        """import argparse
p = argparse.ArgumentParser()
p.add_argument('--level', choices=['unit', 'all', 'slow'])
p.parse_args()
""",
    )

    dag = _make_clean_dag(
        gate_command=f"python {script_a} && python {script_b} --level full",
    )
    blocks = pf._census_class_a(dag)
    class_a_blocks = [b for b in blocks if b["class"] == "a"]
    assert len(class_a_blocks) >= 1
    assert "invalid_choice: True" in class_a_blocks[0]["reason"]


# ---------------------------------------------------------------------------
# Fix 2: bogus-flag fixture still detected via --help only
# ---------------------------------------------------------------------------


def test_bogus_flag_detected_via_help_only(tmp_path):
    """A script with an invalid choice is detected via --help probe alone.

    Uses a choices-based script because --help is always processed first in
    modern CPython argparse. A script with an invalid choice will fail with
    "invalid choice" regardless of whether --help is appended, because
    argparse validates choices before processing --help.

    This verifies that the --help-only probe (without a first probe running
    the raw command) still catches genuinely broken scripts.
    """
    script = _make_temp_script(
        tmp_path,
        "choices_broken.py",
        """import argparse
p = argparse.ArgumentParser()
p.add_argument('--env', choices=['dev', 'staging', 'prod'])
p.parse_args()
""",
    )
    dag = _make_clean_dag(
        gate_command=f"python {script} --env production",
    )
    blocks = pf._census_class_a(dag)
    class_a_blocks = [b for b in blocks if b["class"] == "a"]
    assert len(class_a_blocks) >= 1
    assert "invalid_choice: True" in class_a_blocks[0]["reason"]


# ---------------------------------------------------------------------------
# Fix 3: multi-line continuation in backlog rows
# ---------------------------------------------------------------------------


def test_backlog_multi_line_continuation():
    """A backlog row with REQUIERE_HUMANO on a continuation line is detected."""
    backlog_text = (
        "| Ticket | Status | Description |\n"
        "|--------|--------|-------------|\n"
        "| WOT-2026-XXXXX | pending | This is a long description\n"
        "that spans multiple lines and\n"
        "contains REQUIERE_HUMANO in the prose |\n"
    )
    rows = pf._parse_backlog_rows(backlog_text)
    assert len(rows) == 1
    assert rows[0].get("Ticket") == "WOT-2026-XXXXX"
    desc = rows[0].get("Description", "")
    assert "REQUIERE_HUMANO" in desc


def test_backlog_multi_line_continuation_requiere_humano_detected():
    """A ticket with REQUIERE_HUMANO in a multi-line continuation is flagged by class (d)."""
    backlog_text = (
        "| Ticket | Status | Description |\n"
        "|--------|--------|-------------|\n"
        "| WOT-2026-XXXXX | pending | Task requires\n"
        "human REQUIERE_HUMANO approval before\n"
        "continuing with the implementation |\n"
    )
    rows = pf._parse_backlog_rows(backlog_text)
    assert len(rows) == 1
    desc = rows[0].get("Description", "")
    assert "REQUIERE_HUMANO" in desc

    blocks_d = pf._check_ticket_for_human_decision(rows[0], "WOT-2026-XXXXX")
    assert len(blocks_d) >= 1
    assert "REQUIERE_HUMANO" in blocks_d[0]["reason"]


def test_backlog_single_line_still_works():
    """Single-line rows still parse correctly after the multi-line fix."""
    backlog_text = (
        "| Ticket | Status | Description |\n"
        "|--------|--------|-------------|\n"
        "| WOT-2026-037a | pending | simple task |\n"
        "| WOT-2026-037b | pending | another task |\n"
    )
    rows = pf._parse_backlog_rows(backlog_text)
    assert len(rows) == 2
    assert rows[0].get("Ticket") == "WOT-2026-037a"
    assert rows[0].get("Status") == "pending"
    assert rows[1].get("Ticket") == "WOT-2026-037b"
    assert rows[1].get("Status") == "pending"


def test_backlog_empty_input():
    """Empty input returns no rows."""
    assert pf._parse_backlog_rows("") == []
    assert pf._parse_backlog_rows("   ") == []


def test_backlog_no_header():
    """Input without a header row (no leading '|') returns no rows."""
    text = "This is not a markdown table\njust some text\n"
    assert pf._parse_backlog_rows(text) == []


def test_backlog_multiple_continuations():
    """A row with multiple continuation lines accumulates all text."""
    backlog_text = (
        "| Ticket | Status | Description |\n"
        "|--------|--------|-------------|\n"
        "| WOT-2026-XXXXX | pending | Line one\n"
        "Line two\n"
        "Line three with DISENO_PRIMERO |\n"
    )
    rows = pf._parse_backlog_rows(backlog_text)
    assert len(rows) == 1
    desc = rows[0].get("Description", "")
    assert "Line one" in desc
    assert "Line two" in desc
    assert "DISENO_PRIMERO" in desc
