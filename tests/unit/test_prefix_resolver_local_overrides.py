"""Regression guard: local prefix overrides are SCOPED to their own motor_root.

Measured defect (2026-10-16): ``load_overrides()`` resolved the file as
``Path(__file__).resolve().parent / "prefix_resolver.local.json"`` -- an absolute
path tied to the SCRIPT, so it applied to every ``--motor-root``. A real local
override in the principal motor therefore leaked into fixture motors created
under ``tmp_path``. Control (same work, same command, one variable):

* with the override file present: ``5 failed, 71 passed``
* with it removed:               ``76 passed``

Those 5 failures were tests asserting ``resolve_prefix("WOT") is None`` or a
clean ``--verify``. The file is gitignored, so a clean clone never has it: the
pre-existing suite CANNOT pin this fix, and this module does.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prefix_resolver import load_overrides, resolve_prefix


def _make_motor(root: Path, name: str) -> Path:
    """Create ``<root>/<name>/scripts`` so the motor has an override slot."""
    motor = root / name
    (motor / "scripts").mkdir(parents=True, exist_ok=True)
    return motor


def test_override_is_visible_to_its_own_motor_only(tmp_path: Path) -> None:
    """An override written inside motor A is invisible to motor B.

    Before: motor A must ship its own ``prefix_resolver.local.json`` and motor B
        (a sibling fixture with none) must resolve nothing.
    During: writes the file only under ``motor_a/scripts`` and reads both roots.
    After: motor A sees exactly its entry; motor B sees none. Fails under the old
        absolute-path loader (motor B would see motor A's file, and motor A
        would see nothing of its own unless it happened to be the script's dir).
    """
    motor_a = _make_motor(tmp_path, "motor_a")
    motor_b = _make_motor(tmp_path, "motor_b")
    destino = tmp_path / "destino_wot"
    (motor_a / "scripts" / "prefix_resolver.local.json").write_text(
        json.dumps({"overrides": {"WOT": str(destino)}}), encoding="utf-8"
    )

    assert dict(load_overrides(motor_a)) == {"WOT": destino}
    assert load_overrides(motor_b) == {}


def test_resolve_prefix_honours_its_own_motor_override(tmp_path: Path) -> None:
    """``resolve_prefix`` uses the override of the motor it was asked about.

    Before: two sibling motors; only one declares an override for ``WOT``.
    During: resolves the same prefix against each root.
    After: the owning motor returns its path (rc path is exact), the sibling
        still returns None (no links, no override) -> the ambiguity work-around
        does not become a global default.
    """
    motor_a = _make_motor(tmp_path, "motor_a")
    motor_b = _make_motor(tmp_path, "motor_b")
    destino = tmp_path / "destino_wot"
    (motor_a / "scripts" / "prefix_resolver.local.json").write_text(
        json.dumps({"overrides": {"WOT": str(destino)}}), encoding="utf-8"
    )

    assert resolve_prefix("WOT", motor_a) == destino
    assert resolve_prefix("WOT", motor_b) is None


def test_missing_override_file_is_not_an_error(tmp_path: Path) -> None:
    """A motor without the optional file yields an empty dict (never raises).

    Before: fresh motor root with an empty ``scripts/`` dir.
    During: call with the root, and with ``None`` (legacy signature).
    After: both return a dict; no exception escapes.
    """
    motor = _make_motor(tmp_path, "bare")

    assert load_overrides(motor) == {}
    assert isinstance(load_overrides(None), dict)


def test_structurally_malformed_override_never_raises(tmp_path: Path) -> None:
    """WOT-2026-103f: JSON-valid but structurally malformed overrides
    (non-dict `overrides`, or non-string values) must not raise.

    Before: this reproduces exactly the 3 cases a governance review found
        escaping the narrower except clause: AttributeError/TypeError.
    During: writes each malformed variant, then calls load_overrides.
    After: all 3 return a dict (empty or partial), never an exception --
        FAILS under the pre-fix code with AttributeError/TypeError.
    """
    motor = _make_motor(tmp_path, "motor_malformed")
    override_path = motor / "scripts" / "prefix_resolver.local.json"

    override_path.write_text(json.dumps({"overrides": None}), encoding="utf-8")
    assert load_overrides(motor) == {}

    override_path.write_text(json.dumps({"overrides": ["WOT"]}), encoding="utf-8")
    assert load_overrides(motor) == {}

    override_path.write_text(json.dumps({"overrides": {"WOT": 123}}), encoding="utf-8")
    assert load_overrides(motor) == {}


def test_malformed_override_mixed_with_valid_entry_keeps_the_valid_one(
    tmp_path: Path,
) -> None:
    """A non-string value is skipped; a sibling valid entry still resolves.

    This is the discriminating case: a function that caught the exception
    by returning `{}` for the whole file (rather than validating per-value)
    would also pass ``== {}`` tests above but would LOSE the valid entry
    here -- this test pins the per-value validation, not just non-crashing.
    """
    motor = _make_motor(tmp_path, "motor_mixed")
    destino = tmp_path / "destino_ctl"
    override_path = motor / "scripts" / "prefix_resolver.local.json"
    override_path.write_text(
        json.dumps({"overrides": {"WOT": 123, "CTL": str(destino)}}),
        encoding="utf-8",
    )

    assert dict(load_overrides(motor)) == {"CTL": destino}
