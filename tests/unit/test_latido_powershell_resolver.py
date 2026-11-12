"""Tests for the portable PowerShell executable resolver."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "flight" / "check_latido_alert_wiring.py"
SPEC = importlib.util.spec_from_file_location(
    "check_latido_alert_wiring_resolver_t", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _stub_subprocess(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    return captured


def test_override_is_verbatim_without_systemroot(monkeypatch, tmp_path):
    """Before: the override is absent and SystemRoot is missing.

    During: monkeypatch os.name/os.environ and stub the module subprocess.run.
    After: the override reaches argv unchanged and the parser result is empty.
    """
    override = str(tmp_path / "does-not-exist" / "custom-pwsh")
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    monkeypatch.setenv("FLIGHT_POWERSHELL_EXE", override)
    captured = _stub_subprocess(monkeypatch)

    assert MODULE._powershell_parser_actions(Path("notify_user.ps1")) == {}
    assert captured["argv"][0] == override


def test_systemroot_wins_in_windows_environment(monkeypatch, tmp_path):
    """Before: Windows has SystemRoot and no executable override.

    During: monkeypatch os.name/os.environ and stub subprocess.run.
    After: the legacy System32 PowerShell path is selected.
    """
    root = tmp_path / "Windows"
    with monkeypatch.context() as patch:
        patch.setattr(
            MODULE, "os", types.SimpleNamespace(name="nt", environ=os.environ)
        )
        patch.delenv("FLIGHT_POWERSHELL_EXE", raising=False)
        patch.setenv("SYSTEMROOT", str(root))
        captured = _stub_subprocess(patch)

        MODULE._powershell_parser_actions(Path("notify_user.ps1"))

    assert captured["argv"][0] == str(
        Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )


def test_windows_without_systemroot_raises_literal(monkeypatch):
    """Before: Windows-like inputs have neither override nor SystemRoot.

    During: monkeypatch os.name/os.environ without invoking subprocess.run.
    After: the established introspection error is raised verbatim.
    """
    with monkeypatch.context() as patch:
        patch.setattr(
            MODULE, "os", types.SimpleNamespace(name="nt", environ=os.environ)
        )
        patch.delenv("FLIGHT_POWERSHELL_EXE", raising=False)
        patch.delenv("SYSTEMROOT", raising=False)

        with pytest.raises(
            RuntimeError, match=r"^SystemRoot ausente para introspeccion PowerShell$"
        ):
            MODULE._powershell_parser_actions(Path("notify_user.ps1"))


def test_posix_resolves_pwsh(monkeypatch):
    """Before: POSIX has no override and discovers pwsh through PATH.

    During: monkeypatch os.name/os.environ, shutil.which, and subprocess.run.
    After: the discovered pwsh path is passed to the parser.
    """
    with monkeypatch.context() as patch:
        patch.setattr(
            MODULE, "os", types.SimpleNamespace(name="posix", environ=os.environ)
        )
        patch.delenv("FLIGHT_POWERSHELL_EXE", raising=False)
        patch.delenv("SYSTEMROOT", raising=False)
        patch.setattr(
            MODULE.shutil,
            "which",
            lambda name: "/usr/bin/pwsh" if name == "pwsh" else None,
        )
        captured = _stub_subprocess(patch)

        MODULE._powershell_parser_actions(Path("notify_user.ps1"))

    assert captured["argv"][0] == str(Path("/usr/bin/pwsh"))


def test_posix_without_pwsh_raises_literal(monkeypatch):
    """Before: POSIX has no override, SystemRoot, or pwsh.

    During: monkeypatch the resolver inputs and fail if subprocess.run is called.
    After: the established introspection error is raised before subprocess.run.
    """
    with monkeypatch.context() as patch:
        patch.setattr(
            MODULE, "os", types.SimpleNamespace(name="posix", environ=os.environ)
        )
        patch.delenv("FLIGHT_POWERSHELL_EXE", raising=False)
        patch.delenv("SYSTEMROOT", raising=False)
        patch.setattr(MODULE.shutil, "which", lambda _name: None)

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("subprocess.run must not be called")

        patch.setattr(MODULE.subprocess, "run", fail_if_called)
        with pytest.raises(
            RuntimeError, match=r"^SystemRoot ausente para introspeccion PowerShell$"
        ):
            MODULE._powershell_parser_actions(Path("notify_user.ps1"))


def test_override_precedes_windows_systemroot(monkeypatch, tmp_path):
    """Before: Windows-like inputs provide both override and SystemRoot.

    During: monkeypatch os.name/os.environ and stub subprocess.run.
    After: the explicit override wins before the SystemRoot gate.
    """
    override = str(tmp_path / "override-pwsh.exe")
    with monkeypatch.context() as patch:
        patch.setattr(
            MODULE, "os", types.SimpleNamespace(name="nt", environ=os.environ)
        )
        patch.setenv("SYSTEMROOT", str(tmp_path / "Windows"))
        patch.setenv("FLIGHT_POWERSHELL_EXE", override)
        captured = _stub_subprocess(patch)

        MODULE._powershell_parser_actions(Path("notify_user.ps1"))

    assert captured["argv"][0] == override
