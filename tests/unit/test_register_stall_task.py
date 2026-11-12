"""Focused tests for the scheduled-task XML producer and its fail-closed guard."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree

import pytest


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason=(
        "WindowsIdentity::GetCurrent in register_stall_task.ps1 l.71 and the "
        "python.exe leaf in l.199-201 require Windows Task Scheduler semantics"
    ),
)


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "register_stall_task.ps1"
PS = shutil.which("powershell") or shutil.which("pwsh")
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def _run_ps(
    args: list[str], *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run the producer in a non-interactive PowerShell process."""
    assert PS, "PowerShell is required by this Windows-task fixture"
    result = subprocess.run(
        [PS, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def task_box(tmp_path: Path) -> dict[str, Path]:
    """Create an isolated tracked motor, with spaces and a non-ASCII data path."""
    motor = tmp_path / "motor root with spaces"
    task = motor / "scripts" / "flight" / "flight_stall_check.py"
    task.parent.mkdir(parents=True)
    task.write_bytes(
        (ROOT / "scripts" / "flight" / "flight_stall_check.py").read_bytes()
    )
    python = motor / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"test interpreter placeholder")
    cmd = motor / "cmd.exe"
    cmd.write_bytes(b"test cmd placeholder")
    other = motor / "other.exe"
    other.write_bytes(b"test other placeholder")
    ops = tmp_path / "ops space - cafe-\u00e9"
    flight = tmp_path / "flight space - cafe-\u00e9"
    ops.mkdir()
    flight.mkdir()
    _git(motor, "init", "-q")
    _git(motor, "config", "user.email", "test@example.invalid")
    _git(motor, "config", "user.name", "Test")
    _git(motor, "add", "scripts/flight/flight_stall_check.py")
    _git(motor, "commit", "-qm", "fixture")
    return {
        "motor": motor,
        "task": task,
        "python": python,
        "cmd": cmd,
        "other": other,
        "ops": ops,
        "flight": flight,
    }


def _base_args(box: dict[str, Path]) -> list[str]:
    return [
        "-MotorRoot",
        str(box["motor"]),
        "-PythonExe",
        str(box["python"]),
        "-OpsDir",
        str(box["ops"]),
        "-FlightDir",
        str(box["flight"]),
    ]


def _sid() -> str:
    result = subprocess.run(
        [
            PS or "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _account_name() -> str:
    result = subprocess.run(
        [
            PS or "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Security.Principal.WindowsIdentity]::GetCurrent().Name",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _expected_xml(box: dict[str, Path], **changes: str) -> str:  # noqa: C901
    sid = changes.get("sid", _sid())
    if changes.get("name_user"):
        sid = _account_name()
    command = changes.get("command", str(box["python"]))
    if changes.get("cmd_path"):
        command = str(box["cmd"])
    if changes.get("other_path"):
        command = str(box["other"])
    working = changes.get("working", str(box["motor"]))
    arguments = changes.get(
        "arguments",
        f'"{box["task"]}" --heartbeat-check --ops-dir "{box["ops"]}" '
        f'--flight-dir "{box["flight"]}"',
    )
    task = ElementTree.Element(f"{{{NS}}}Task", {"version": "1.4"})
    principals = ElementTree.SubElement(task, f"{{{NS}}}Principals")
    principal = ElementTree.SubElement(
        principals, f"{{{NS}}}Principal", {"id": "Author"}
    )
    for name, value in (
        ("UserId", sid),
        ("LogonType", changes.get("logon", "InteractiveToken")),
        ("RunLevel", changes.get("run_level", "LeastPrivilege")),
    ):
        ElementTree.SubElement(principal, f"{{{NS}}}{name}").text = value
    settings = ElementTree.SubElement(task, f"{{{NS}}}Settings")
    ElementTree.SubElement(
        settings, f"{{{NS}}}MultipleInstancesPolicy"
    ).text = changes.get("instances", "IgnoreNew")
    if not changes.get("no_trigger"):
        triggers = ElementTree.SubElement(task, f"{{{NS}}}Triggers")
        trigger = ElementTree.SubElement(triggers, f"{{{NS}}}TimeTrigger")
        ElementTree.SubElement(trigger, f"{{{NS}}}StartBoundary").text = changes.get(
            "start_boundary", "2026-11-05T00:00:00Z"
        )
        ElementTree.SubElement(trigger, f"{{{NS}}}Enabled").text = changes.get(
            "enabled", "true"
        )
        repetition = ElementTree.SubElement(trigger, f"{{{NS}}}Repetition")
        ElementTree.SubElement(repetition, f"{{{NS}}}Interval").text = changes.get(
            "interval", "PT10M"
        )
        ElementTree.SubElement(repetition, f"{{{NS}}}StopAtDurationEnd").text = "false"
        if changes.get("extra_trigger"):
            ElementTree.SubElement(triggers, f"{{{NS}}}TimeTrigger")
    actions = ElementTree.SubElement(task, f"{{{NS}}}Actions", {"Context": "Author"})
    execute = ElementTree.SubElement(actions, f"{{{NS}}}Exec")
    for name, value in (
        ("Command", command),
        ("Arguments", arguments),
        ("WorkingDirectory", working),
    ):
        ElementTree.SubElement(execute, f"{{{NS}}}{name}").text = value
    if changes.get("second_exec"):
        ElementTree.SubElement(actions, f"{{{NS}}}Exec")
    if changes.get("unknown_action"):
        ElementTree.SubElement(actions, f"{{{NS}}}Mystery")
    if changes.get("second_principal"):
        ElementTree.SubElement(principals, f"{{{NS}}}Principal")
    if changes.get("unknown_principal"):
        ElementTree.SubElement(principal, f"{{{NS}}}Mystery")
    if changes.get("unknown_trigger") and not changes.get("no_trigger"):
        ElementTree.SubElement(triggers[0], f"{{{NS}}}Mystery")
    return ElementTree.tostring(task, encoding="unicode")


def _write_xml(box: dict[str, Path], content: str, name: str = "hostile.xml") -> Path:
    path = box["ops"] / name
    path.write_text(content, encoding="utf-8")
    return path


def _check_hostile(box: dict[str, Path], **changes: str) -> str:
    xml = _write_xml(box, _expected_xml(box, **changes), "hostile.xml")
    result = _run_ps([*_base_args(box), "-XmlPath", str(xml), "-WhatIf"])
    assert result.returncode == 2, result.stdout + result.stderr
    return result.stdout + result.stderr


def test_generated_xml_is_guarded_and_whatif_is_default(
    task_box: dict[str, Path],
) -> None:
    result = _run_ps(_base_args(task_box))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REGISTER_STALL_WHATIF" in result.stdout
    assert "--heartbeat-check" in result.stdout
    generated = ElementTree.fromstring(  # noqa: S314 - producer output is local test data
        result.stdout.splitlines()[1]
    )
    triggers = generated.findall(f"{{{NS}}}Triggers/{{{NS}}}TimeTrigger")
    assert len(triggers) == 1
    assert triggers[0].find(f"{{{NS}}}Repetition/{{{NS}}}Interval").text == "PT10M"
    assert not (task_box["ops"] / "task_registered.json").exists()


@pytest.mark.parametrize(
    ("label", "changes"),
    [
        ("system", {"sid": "S-1-5-18"}),
        ("name-user", {"name_user": "true"}),
        ("logon", {"logon": "Password"}),
        ("runlevel", {"run_level": "HighestAvailable"}),
        ("instances", {"instances": "Parallel"}),
        ("cmd", {"command": "cmd.exe"}),
        ("redirect", {"arguments": "x > output.txt"}),
        ("command", {"arguments": "x -Command whoami"}),
        ("encoded", {"arguments": "x -EncodedCommand Zg=="}),
        ("python-c", {"arguments": "x -c whoami"}),
        ("bypass", {"arguments": "x -ExecutionPolicy Bypass"}),
        (
            "extra",
            {"arguments": "x --heartbeat-check --ops-dir x --flight-dir y --extra"},
        ),
        ("missing-heartbeat", {"arguments": "x --ops-dir x --flight-dir y"}),
        ("working-directory", {"working": "C:\\other"}),
        ("relative-python", {"command": "python.exe"}),
        ("python-leaf-cmd", {"cmd_path": "true"}),
        ("python-leaf-other", {"other_path": "true"}),
        ("enabled-false", {"enabled": "false"}),
        ("enabled-case", {"enabled": "TRUE"}),
        ("enabled-space", {"enabled": " true "}),
        ("startboundary-garbage", {"start_boundary": "nonsense"}),
        ("startboundary-empty", {"start_boundary": ""}),
        ("startboundary-non-iso", {"start_boundary": "05/11/2026 00:00"}),
        ("missing-trigger", {"no_trigger": "true"}),
        ("extra-trigger", {"extra_trigger": "true"}),
        ("wrong-interval", {"interval": "PT15M"}),
        ("second-exec", {"second_exec": "true"}),
        ("second-principal", {"second_principal": "true"}),
        ("unknown-action", {"unknown_action": "true"}),
        ("unknown-principal", {"unknown_principal": "true"}),
        ("unknown-trigger", {"unknown_trigger": "true"}),
    ],
)
def test_each_xml_rejection_is_fail_closed(
    task_box: dict[str, Path], label: str, changes: dict[str, str]
) -> None:
    output = _check_hostile(task_box, **changes)
    expected = {
        "redirect": "forbidden command or redirection",
        "command": "forbidden command or redirection",
        "encoded": "forbidden command or redirection",
        "python-c": "forbidden command or redirection",
        "bypass": "forbidden command or redirection",
        "extra": "extra flag in Arguments",
        "missing-heartbeat": "Arguments must include --heartbeat-check",
        "relative-python": "Python command must be absolute",
        "name-user": "UserId must be a literal SID",
        "python-leaf-cmd": "PythonExe leaf must be python.exe",
        "python-leaf-other": "PythonExe leaf must be python.exe",
        "enabled-false": "trigger Enabled must equal true",
        "enabled-case": "trigger Enabled must equal true",
        "enabled-space": "trigger Enabled must equal true",
        "startboundary-garbage": "StartBoundary must be valid ISO 8601",
        "startboundary-empty": "StartBoundary must be valid ISO 8601",
        "startboundary-non-iso": "StartBoundary must be valid ISO 8601",
    }.get(label)
    assert "REGISTER_STALL_REJECTED" in output, label
    if expected:
        assert expected in output, output


@pytest.mark.parametrize(
    "start_boundary", ["2026-11-05T00:00:00Z", "2026-11-05T01:00:00+01:00"]
)
def test_valid_iso_startboundary_is_accepted(
    task_box: dict[str, Path], start_boundary: str
) -> None:
    xml = _write_xml(
        task_box,
        _expected_xml(task_box, start_boundary=start_boundary),
        "valid-boundary.xml",
    )
    result = _run_ps([*_base_args(task_box), "-XmlPath", str(xml), "-WhatIf"])
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("leaf", ["cmd", "other"])
def test_producer_rejects_non_python_executable(
    task_box: dict[str, Path], leaf: str
) -> None:
    result = _run_ps(
        [
            "-MotorRoot",
            str(task_box["motor"]),
            "-PythonExe",
            str(task_box[leaf]),
            "-OpsDir",
            str(task_box["ops"]),
            "-FlightDir",
            str(task_box["flight"]),
        ]
    )
    assert result.returncode == 2
    assert "PythonExe leaf must be python.exe (input)" in result.stdout + result.stderr


def test_guard_rejects_different_python_with_same_leaf(
    task_box: dict[str, Path],
) -> None:
    alternate = task_box["motor"] / "alternate" / "python.exe"
    alternate.parent.mkdir()
    alternate.write_bytes(b"alternate interpreter placeholder")
    xml = _write_xml(
        task_box,
        _expected_xml(task_box, command=str(alternate)),
        "different-python.xml",
    )
    result = _run_ps([*_base_args(task_box), "-XmlPath", str(xml), "-WhatIf"])
    assert result.returncode == 2
    assert "PythonExe differs from the fixed interpreter" in (
        result.stdout + result.stderr
    )


def test_untracked_task_script_is_rejected(task_box: dict[str, Path]) -> None:
    _git(task_box["motor"], "rm", "-q", "scripts/flight/flight_stall_check.py")
    task_box["task"].parent.mkdir(parents=True, exist_ok=True)
    task_box["task"].write_bytes(b"untracked")
    output = _run_ps(_base_args(task_box))
    assert output.returncode == 2
    assert (
        "git failed" in output.stdout + output.stderr
        or "tracked" in output.stdout + output.stderr
    )


def test_task_script_different_from_head_is_rejected(task_box: dict[str, Path]) -> None:
    task_box["task"].write_bytes(task_box["task"].read_bytes() + b"\nmutation")
    output = _run_ps(_base_args(task_box))
    assert output.returncode == 2
    assert "differs from HEAD" in output.stdout + output.stderr
