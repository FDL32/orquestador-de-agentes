"""Useful tests for the settings canonical drift census (WOT-2026-166a)."""

from __future__ import annotations

import ast
import json
import subprocess
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest


def _git_run(cwd: Path, *args: str) -> None:
    """Run one real git command for the mini motor fixture."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        pytest.skip(f"git no disponible: {exc}")
    if result.returncode != 0:
        pytest.fail(f"git {' '.join(args)} fallo: {result.stderr}")


@pytest.fixture()
def mini_motor(tmp_path: Path) -> Path:
    """Create a real git motor and a gate stub with two stale violations."""
    motor = tmp_path / "motor"
    (motor / "scripts").mkdir(parents=True)
    (motor / ".agent" / "hooks").mkdir(parents=True)
    gate = motor / "scripts" / "check_claude_settings_portability.py"
    gate.write_text(
        "import pathlib, sys\n"
        "text = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "if '__STALE__' in text:\n"
        "    print('gate summary: stale settings')\n"
        "    print('  - first stale violation')\n"
        "    print('  - second stale violation')\n"
        "    raise SystemExit(1)\n"
        "print('gate summary: settings current')\n",
        encoding="ascii",
    )
    (motor / ".agent" / "hooks" / "claude_guard_entry.py").write_text(
        "# fixture\n", encoding="ascii"
    )
    (motor / "README.md").write_text("base\n", encoding="ascii")

    _git_run(motor, "init")
    _git_run(motor, "config", "user.email", "tests@example.invalid")
    _git_run(motor, "config", "user.name", "test")
    _git_run(motor, "add", ".")
    _git_run(motor, "commit", "-m", "initial")
    _git_run(motor, "update-ref", "refs/remotes/origin/main", "HEAD")
    return motor


def _make_destino(root: Path, name: str, stale: bool, ci: bool = False) -> Path:
    """Create one linked destination with static settings and optional CI."""
    dest = root / name
    (dest / ".claude").mkdir(parents=True, exist_ok=True)
    (dest / ".agent" / "config").mkdir(parents=True, exist_ok=True)
    settings = {"__STALE__": True, "hooks": {}} if stale else {"hooks": {}}
    (dest / ".claude" / "settings.json").write_text(
        json.dumps(settings), encoding="ascii"
    )
    (dest / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps({"destination_root": str(dest)}), encoding="ascii"
    )
    if ci:
        (dest / ".github" / "workflows").mkdir(parents=True)
        (dest / ".github" / "workflows" / "quality.yml").write_text(
            "run: python scripts/check_claude_settings_portability.py\n",
            encoding="ascii",
        )
    return dest


def _run_main(mini_motor: Path, destino_root: Path) -> tuple[int, str]:
    """Run the production module and capture its actual stdout."""
    from scripts.check_settings_canonical_drift import main

    output = StringIO()
    with redirect_stdout(output):
        rc = main(
            [
                "--project-root",
                str(mini_motor),
                "--destino-root",
                str(destino_root),
            ]
        )
    return rc, output.getvalue()


def test_a01_empty_real_diff_warns_and_fresh_control_is_silent(
    mini_motor: Path, tmp_path: Path
) -> None:
    """A real empty diff still evaluates stale settings; fresh settings do not warn."""
    destinos = tmp_path / "destinos"
    stale = _make_destino(destinos, "stale_destino", stale=True)

    rc, output = _run_main(mini_motor, destinos)
    assert rc == 0
    assert "AVISO" in output
    assert "stale_destino" in output
    assert "2 problema(s)" in output
    assert "censo: 1 destino(s)" in output

    (stale / ".claude" / "settings.json").write_text('{"hooks": {}}', encoding="ascii")
    rc, output = _run_main(mini_motor, destinos)
    assert rc == 0
    assert "AVISO" not in output
    assert "OK" in output
    assert "censo: 1 destino(s)" in output


def test_a01_bis_ajeno_diff_does_not_disable_check(
    mini_motor: Path, tmp_path: Path
) -> None:
    """An unrelated committed file does not disable the census."""
    destinos = tmp_path / "destinos"
    _make_destino(destinos, "stale_destino", stale=True)
    (mini_motor / "README.md").write_text("unrelated change\n", encoding="ascii")
    _git_run(mini_motor, "add", "README.md")
    _git_run(mini_motor, "commit", "-m", "unrelated")

    rc, output = _run_main(mini_motor, destinos)
    assert rc == 0
    assert "stale_destino" in output
    assert "AVISO" in output


def test_b01_two_failures_name_count_ci_and_exclude_healthy(
    mini_motor: Path, tmp_path: Path
) -> None:
    """Failures include count and CI state while healthy destinations stay unnamed."""
    destinos = tmp_path / "destinos"
    _make_destino(destinos, "stale_ci", stale=True, ci=True)
    _make_destino(destinos, "stale_no_ci", stale=True, ci=False)
    _make_destino(destinos, "healthy", stale=False, ci=True)

    rc, output = _run_main(mini_motor, destinos)
    assert rc == 0
    assert "stale_ci" in output and "2 problema(s)" in output
    assert "stale_ci" in output and "CI: con gate en .github/workflows" in output
    assert "stale_no_ci" in output
    assert "stale_no_ci" in output and "CI: sin gate en .github/workflows" in output
    assert "healthy" not in output
    assert "censo: 3 destino(s)" in output


def test_b02_empty_census_is_visible_and_one_is_denominated(
    mini_motor: Path, tmp_path: Path
) -> None:
    """The census denominator is visible for both zero and one evaluable target."""
    empty = tmp_path / "empty"
    empty.mkdir()
    rc, output = _run_main(mini_motor, empty)
    assert rc == 0
    assert "censo: 0 destino(s) con .claude/settings.json evaluados" in output
    assert "censo VACIO" in output

    destinos = tmp_path / "destinos"
    _make_destino(destinos, "one", stale=False)
    rc, output = _run_main(mini_motor, destinos)
    assert rc == 0
    assert "censo: 1 destino(s) con .claude/settings.json evaluados" in output


def test_link_ilegible_is_fail_visible(mini_motor: Path, tmp_path: Path) -> None:
    """Malformed active links are reported while the command remains non-blocking."""
    root = tmp_path / "destinos"
    link = root / "broken" / ".agent" / "config"
    link.mkdir(parents=True)
    (link / "motor_destination_link.json").write_text("{broken", encoding="ascii")

    rc, output = _run_main(mini_motor, root)
    assert rc == 0
    assert "censo VACIO" in output
    assert "ilegible" in output or "invalido" in output


def test_c01_prepush_warn_is_non_blocking(
    mini_motor: Path, tmp_path: Path, monkeypatch
):
    """The real prepush adapter returns a passed, non-blocking warning result."""
    destinos = tmp_path / "destinos"
    _make_destino(destinos, "stale", stale=True)
    monkeypatch.setenv("AGENT_DESTINOS_ROOT", str(destinos))

    from scripts.prepush_check import run_settings_canonical_drift_check

    result = run_settings_canonical_drift_check(mini_motor)
    assert result.passed is True
    assert result.is_blocking is False


class TestWiringVisible:
    """The prepush import remains statically visible to the wiring guard."""

    def test_wiring_visivel(self) -> None:
        """The production import is an actual wiring edge."""
        from scripts.check_guard_wiring import collect_evidence

        motor_root = Path(__file__).resolve().parents[2]
        evidence = collect_evidence(motor_root)
        assert "check_settings_canonical_drift" in evidence.get(
            "check_settings_canonical_drift", {}
        ) or "check_settings_canonical_drift" in (
            motor_root / "scripts" / "prepush_check.py"
        ).read_text(encoding="utf-8")

    def test_run_is_blocking_false(self) -> None:
        """The adapter source keeps the explicit non-blocking contract."""
        source = (
            Path(__file__).resolve().parents[2] / "scripts" / "prepush_check.py"
        ).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
        functions = [
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        ]
        target = next(
            node
            for node in functions
            if node.name == "run_settings_canonical_drift_check"
        )
        target_text = ast.get_source_segment(source, target) or ""
        assert "is_blocking=False" in target_text
