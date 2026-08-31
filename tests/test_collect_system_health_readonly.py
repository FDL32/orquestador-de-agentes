"""Tree-neutrality and ruff --no-fix tests for the collector (WOT-2026-047v).

DoD (2): running scripts/collect_system_health.py over a fixture that declares
`fix = true` and contains an AUTOFIXABLE finding must leave the tree BIT-IDENTICAL
and report the ruff checks RED (exit_code 1) -- never green-by-fixing. The
fixtures declare `fix = true` so ruff WOULD auto-fix without --no-fix; without
that declaration the test would go red with an intact tree and prove nothing
(a false red that passes with and without the fix). The tests run the REAL ruff
subprocess through the collector's own `_run` -- never a monkeypatched `_run`,
which would measure the mock and not the defect (mock drift).

DoD (3): scripts/check_collector_ruff_nofix.py is a static executable guard that
fails when ANY literal ruff command list lacks `--no-fix` in the SAME list (per
invocation, never by substring presence in the whole file).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent

_CSH_SPEC = importlib.util.spec_from_file_location(
    "collect_system_health",
    _REPO_ROOT / "scripts" / "collect_system_health.py",
)
csh = importlib.util.module_from_spec(_CSH_SPEC)
_CSH_SPEC.loader.exec_module(csh)

_GUARD_SPEC = importlib.util.spec_from_file_location(
    "check_collector_ruff_nofix",
    _REPO_ROOT / "scripts" / "check_collector_ruff_nofix.py",
)
check_guard = importlib.util.module_from_spec(_GUARD_SPEC)
_GUARD_SPEC.loader.exec_module(check_guard)


_AUTOFIXABLE_SOURCE = "import os\nprint(1)\n"


def _write_motor_fixture(root: Path) -> Path:
    """A motor-shaped fixture with fix=true config and an AUTOFIXABLE finding.

    MANIFEST.distribute is the collector motor-root precondition; pyproject.toml
    declares `fix = true` so a bare `ruff check` WOULD rewrite the tree. The
    fixture python file trips F401 (unused import), safely autofixable.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "MANIFEST.distribute").write_text("fixture\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[tool.ruff]\nfix = true\n", encoding="utf-8")
    target = root / "fixture_target.py"
    target.write_text(_AUTOFIXABLE_SOURCE, encoding="utf-8")
    return target


def _write_dest_fixture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".agent").mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text("[tool.ruff]\nfix = true\n", encoding="utf-8")
    target = root / "dest_target.py"
    target.write_text("import sys\nprint(1)\n", encoding="utf-8")
    return target


# ---- DoD (2): the collector does not write in the tree it audits --------------


def test_recolector_reports_rojo_y_no_muta_el_motor(tmp_path):
    motor = tmp_path / "motor"
    target = _write_motor_fixture(motor)
    before = target.read_bytes()

    out = tmp_path / "out"
    csh.main(["--motor-root", str(motor), "--mode", "motor-only", "--out", str(out)])

    assert target.read_bytes() == before, "el recolector MUTA el arbol que audita"
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    ruff_motor = findings["checks"]["ruff_motor"]
    assert ruff_motor["ok"] is False, "el check sale verde-por-arreglo"
    assert ruff_motor["exit_code"] == 1, "ruff debe reportar hallazgos sin arreglarlos"


def test_recolector_no_muta_ni_motor_ni_destino(tmp_path):
    motor = tmp_path / "motor"
    target_motor = _write_motor_fixture(motor)
    dest = tmp_path / "dest"
    target_dest = _write_dest_fixture(dest)
    before_motor = target_motor.read_bytes()
    before_dest = target_dest.read_bytes()

    out = tmp_path / "out"
    csh.main(
        [
            "--motor-root",
            str(motor),
            "--project-root",
            str(dest),
            "--mode",
            "full",
            "--out",
            str(out),
        ]
    )

    assert target_motor.read_bytes() == before_motor
    assert target_dest.read_bytes() == before_dest
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    for key in ("ruff_motor", "ruff_destino"):
        ruff = findings["checks"][key]
        assert ruff["ok"] is False, f"{key} sale verde sin haber verificado"
        assert ruff["exit_code"] == 1, f"{key} debe ser ROJO: hay hallazgo autofixable"


# ---- DoD (3): the static ruff --no-fix guard ----------------------------------


def test_guard_pasa_con_no_fix_en_la_misma_lista(tmp_path):
    target = tmp_path / "ok_target.py"
    target.write_text(
        'subprocess.run(["ruff", "check", "--no-fix", "."])\n', encoding="utf-8"
    )
    assert check_guard.main(["--target", str(target)]) == 0


def test_guard_falla_sin_no_fix_por_invocacion(tmp_path):
    target = tmp_path / "bad_target.py"
    target.write_text('subprocess.run(["ruff", "check", "."])\n', encoding="utf-8")
    assert check_guard.main(["--target", str(target)]) == 1
    assert target.exists()


def test_guard_falla_aunque_otra_invocacion_lleve_no_fix(tmp_path):
    target = tmp_path / "mixed_target.py"
    target.write_text(
        'run(["ruff", "check", "--no-fix", "."])\nrun(["ruff", "check", "."])\n',
        encoding="utf-8",
    )
    assert check_guard.main(["--target", str(target)]) == 1


def test_guard_no_falla_por_listas_sin_ruff(tmp_path):
    target = tmp_path / "no_ruff.py"
    target.write_text('run(["git", "status"])\n', encoding="utf-8")
    assert check_guard.main(["--target", str(target)]) == 0


def test_guard_pasa_sobre_el_recolector_fijado():
    assert check_guard.main([]) == 0
