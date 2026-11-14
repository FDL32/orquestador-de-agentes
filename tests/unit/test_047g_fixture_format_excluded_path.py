"""Regression tests for format fixtures under Ruff-excluded paths.

Before: A fixture below ``tests/sandbox`` can be silently ignored by Ruff.
During: These helpers exercise Ruff's real configuration discovery.
After: Format tests fail loudly when their fixture is not actually inspected.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility.
    import tomli as tomllib

UNFORMATTED_FIXTURE = "x = {'a':1,   'b':2}\ndef f( a ,b ):\n  return a+b\n"


def write_unformatted_fixture(root: Path) -> Path:
    """Write a deliberately unformatted Python fixture.

    Before: A format test needs a real file that Ruff must reject.
    During: The fixture is written below the supplied temporary root.
    After: The path of the unformatted ``sample.py`` is returned.
    """
    fixture = root / "sample.py"
    fixture.write_text(UNFORMATTED_FIXTURE, encoding="utf-8")
    return fixture


def ruff_format_probe(root: Path) -> subprocess.CompletedProcess[str]:
    """Run Ruff's format check using normal configuration discovery.

    Before: The production gate discovers Ruff configuration from the fixture
    root and its parents.
    During: Ruff runs without ``--isolated`` using the gate's command shape;
    ``uv run --isolated`` does not alter Ruff's own configuration discovery.
    After: The complete subprocess result is returned for assertions.
    """
    return subprocess.run(
        ["ruff", "format", "--check", "."],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def assert_ruff_reads_fixture(root: Path) -> None:
    """Assert that Ruff sees and rejects the deliberately dirty fixture.

    Before: ``sample.py`` must be included in Ruff's discovered inputs.
    During: The real format probe is checked for a non-zero status and its
    concrete ``Would reformat`` diagnostic.
    After: A skipped fixture raises an actionable false-green assertion.
    """
    probe = ruff_format_probe(root)
    output = f"{probe.stdout}\n{probe.stderr}"
    if probe.returncode == 0 or "Would reformat" not in output:
        raise AssertionError(
            "FALSO VERDE: Ruff no inspecciono el fixture; revisa "
            "extend-exclude/tests/sandbox. "
            f"returncode={probe.returncode}, output={output!r}"
        )


def test_fixture_under_excluded_path_is_detected(tmp_path: Path) -> None:
    """Expose the excluded-path false green and verify the barrier detects it.

    Before: The temporary root is under the repository's excluded
    ``tests/sandbox`` path and has no local Ruff configuration.
    During: Ruff reports no Python files, then the positive helper is required
    to raise instead of accepting that result.
    After: The known false green is documented by a useful failing assertion.
    """
    write_unformatted_fixture(tmp_path)
    probe = ruff_format_probe(tmp_path)
    output = f"{probe.stdout}\n{probe.stderr}"

    assert probe.returncode == 0
    assert "No Python files found" in output
    try:
        assert_ruff_reads_fixture(tmp_path)
    except AssertionError:
        pass
    else:
        raise AssertionError("el detector no vio el falso verde de tests/sandbox")


def test_ruff_reads_fixture_when_shielded(tmp_path: Path) -> None:
    """Prove that a local Ruff configuration makes the positive control real.

    Before: The fixture would inherit the parent exclusion.
    During: A local ``ruff.toml`` shields it and the real probe must reject it.
    After: The shared assertion passes only when Ruff emits ``Would reformat``.
    """
    (tmp_path / "ruff.toml").write_text("line-length = 88\n", encoding="utf-8")
    write_unformatted_fixture(tmp_path)
    assert_ruff_reads_fixture(tmp_path)


def test_tests_sandbox_still_extend_excluded() -> None:
    """Keep the premise of the excluded-path regression explicit.

    Before: The repository Ruff configuration defines its exclusion boundary.
    During: The project TOML is parsed and its Ruff setting is inspected.
    After: The test remains meaningful if the exclusion is intentionally
    changed later.
    """
    config_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with config_path.open("rb") as config_file:
        config = tomllib.load(config_file)

    assert "tests/sandbox/" in config["tool"]["ruff"]["extend-exclude"], (
        "tests/sandbox/ ya no esta en [tool.ruff] extend-exclude de "
        "pyproject.toml: el falso verde de WOT-2026-047g ya no existe por "
        "esa via; si es intencionado, actualiza o elimina "
        "test_fixture_under_excluded_path_is_detected y este test."
    )
