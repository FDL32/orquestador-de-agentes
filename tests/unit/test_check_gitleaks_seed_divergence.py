"""Tests for scripts/check_gitleaks_seed_divergence.py (WOT-2026-039k).

The guard closes the cascade gap the installer's no-clobber opened: seed
additions (027n/063c/089l) never reached an already-provisioned destino. It
DETECTS and NAMES the absent seed ``[[allowlists]]`` sections by EXACT value,
preserving the destino's LOCAL section, and it discriminates a LOAD error
(mutation that breaks the file) from a real detection.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import scripts.check_gitleaks_seed_divergence as g


REPO_ROOT = Path(__file__).resolve().parents[2]

# A minimal seed: one structural paths block + one exact-value fixture block.
SEED = """\
title = "seed"
[extend]
useDefault = true

[[allowlists]]
description = "structural log paths"
paths = [
  '''(^|/)execution_log\\.md$''',
]

[[allowlists]]
description = "027n privacy_preflight fixtures"
regexes = [
  '''sk-live-abc12345''',
  '''A1b2C3d4E5f6G7h8''',
]
"""

# The same seed minus the 027n block (a whole-block removal, which KEEPS the
# file loadable -- the only mutation shape that is real evidence).
SEED_WITHOUT_027N = """\
title = "seed"
[extend]
useDefault = true

[[allowlists]]
description = "structural log paths"
paths = [
  '''(^|/)execution_log\\.md$''',
]
"""


def test_seed_against_itself_has_no_missing():
    assert g.missing_seed_sections(SEED, SEED) == []


def test_missing_block_is_named_by_description():
    missing = g.missing_seed_sections(SEED, SEED_WITHOUT_027N)
    assert missing == ["027n privacy_preflight fixtures"]


def test_local_block_is_ignored_and_does_not_hide_a_seed_block():
    """A destino's LOCAL block (different values) never satisfies a seed block."""
    target = (
        SEED_WITHOUT_027N + "\n[[allowlists]]\n"
        'description = "LOCAL: workspace placeholder + public SHA"\n'
        "regexes = [\n  '''sk_live_1234567890''',\n]\n"
    )
    assert g.missing_seed_sections(SEED, target) == ["027n privacy_preflight fixtures"]


def test_superset_block_matches_a_seed_block():
    """A block carrying the seed values PLUS extras is present (local superset)."""
    target = """\
[[allowlists]]
description = "local paths extended"
paths = [
  '''(^|/)execution_log\\.md$''',
  '''(^|/)my_local_log\\.md$''',
]
[[allowlists]]
description = "027n + extra"
regexes = [
  '''sk-live-abc12345''',
  '''A1b2C3d4E5f6G7h8''',
  '''sk_local_extra''',
]
"""
    assert g.missing_seed_sections(SEED, target) == []


def test_present_is_order_and_description_independent():
    """Match is by VALUE set, not by description or block order."""
    target = """\
[[allowlists]]
description = "reordered fixtures"
regexes = [
  '''A1b2C3d4E5f6G7h8''',
  '''sk-live-abc12345''',
]
[[allowlists]]
description = "renamed paths block"
paths = [
  '''(^|/)execution_log\\.md$''',
]
"""
    assert g.missing_seed_sections(SEED, target) == []


def test_check_pair_absent_target_names_every_section(tmp_path):
    seed = tmp_path / "seed.toml"
    seed.write_text(SEED, encoding="utf-8")
    report = g.check_pair(seed, tmp_path / "missing.toml")
    assert report["ok"] is False
    assert report["cause"] == "ABSENT"
    assert report["missing"] == [
        "structural log paths",
        "027n privacy_preflight fixtures",
    ]


def test_check_pair_missing_seed(tmp_path):
    report = g.check_pair(tmp_path / "nope.toml", tmp_path / "target.toml")
    assert report["cause"] == "SEED_MISSING"


def test_check_pair_unparseable_is_a_load_error_not_a_detection(tmp_path):
    """The 063c lesson, mechanised: a file that does not LOAD is rc 2, never a hit."""
    seed = tmp_path / "seed.toml"
    seed.write_text(SEED, encoding="utf-8")
    target = tmp_path / "broken.toml"
    target.write_text('title = "broken\n[[allowlists]\n', encoding="utf-8")
    report = g.check_pair(seed, target)
    assert report["ok"] is False
    assert report["cause"] == "UNPARSEABLE"
    assert report["missing"] == []


def test_main_exit_codes_three_way(tmp_path):
    seed = tmp_path / "seed.toml"
    seed.write_text(SEED, encoding="utf-8")
    ok = tmp_path / "ok.toml"
    ok.write_text(SEED, encoding="utf-8")
    bad = tmp_path / "bad.toml"
    bad.write_text(SEED_WITHOUT_027N, encoding="utf-8")
    broken = tmp_path / "broken.toml"
    broken.write_text('title = "broken\n', encoding="utf-8")

    assert g.main(["--seed", str(seed), "--target", str(ok)]) == 0
    assert g.main(["--seed", str(seed), "--target", str(bad)]) == 1
    assert g.main(["--seed", str(seed), "--target", str(broken)]) == 2


def test_main_destino_mode(tmp_path):
    """--destino inspects <destino>/.gitleaks.toml (the seed<->destino pair)."""
    seed = tmp_path / "seed.toml"
    seed.write_text(SEED, encoding="utf-8")
    destino = tmp_path / "destino"
    destino.mkdir()
    (destino / ".gitleaks.toml").write_text(SEED_WITHOUT_027N, encoding="utf-8")
    assert g.main(["--seed", str(seed), "--destino", str(destino)]) == 1
    (destino / ".gitleaks.toml").write_text(SEED, encoding="utf-8")
    assert g.main(["--seed", str(seed), "--destino", str(destino)]) == 0


def test_mutation_block_removal_names_the_section_with_load_control(tmp_path):
    """DoD (d): the two rc, with a LOAD control proving the mutation is real.

    rc 0 on the intact target; rc 1 naming the section after removing the WHOLE
    block. The load control (the mutated file still parses) is what separates a
    detection from a config-load crash.
    """
    tomllib = g.tomllib  # reuse the module's own tomllib/tomli fallback (3.10)

    seed = tmp_path / "seed.toml"
    seed.write_text(SEED, encoding="utf-8")
    target = tmp_path / "target.toml"
    target.write_text(SEED, encoding="utf-8")

    # CONTROL: intact -> present.
    assert g.main(["--seed", str(seed), "--target", str(target)]) == 0

    # MUTATION: remove the whole 027n block.
    before = target.read_text(encoding="utf-8")
    mutated = before.split('[[allowlists]]\ndescription = "027n')[0].rstrip() + "\n"
    target.write_text(mutated, encoding="utf-8")

    # LOAD CONTROL: the mutated config must STILL load (else rc is a load error).
    tomllib.loads(mutated)
    report = g.check_pair(seed, target)
    assert report["cause"] == "DIVERGENT", "the mutated config did not even load"
    assert g.main(["--seed", str(seed), "--target", str(target)]) == 1
    assert report["missing"] == ["027n privacy_preflight fixtures"]


def test_real_seed_is_subset_of_motor_root_config():
    """Fixture-realism: the real seed's sections are all in the motor root config."""
    seed_text = g.SEED_PATH.read_text(encoding="utf-8")
    motor_cfg = (REPO_ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    assert g.missing_seed_sections(seed_text, motor_cfg) == []


def test_cli_runs_as_script_on_real_seed():
    """The guard is runnable as a CLI against the real motor root (rc 0)."""
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "check_gitleaks_seed_divergence.py"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
