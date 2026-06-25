#!/usr/bin/env python3
"""
Smart upgrade system for z_scripts agent system.

Public, documented entrypoint for the agent-system upgrade flow.

WOT-2026-013t: this module is the canonical PUBLIC entrypoint, but it no longer
owns a second editable ``UpgradeManager``. The single owner of the upgrade logic
is ``scripts.upgrade_agent_system`` (it integrates ``ProjectPathsResolver`` and
``DoctorAgentSystem`` and is the focal unit-test surface). To keep the two forks
from diverging again, ``scripts.upgrade`` re-exports the owner's public names
(``UpgradeManager``, ``main``) and its ``shutil``/``datetime`` bindings, so:

  - ``from scripts.upgrade import UpgradeManager`` keeps working and resolves to
    the SAME class the unit tests exercise (``UpgradeManager.__module__`` ==
    ``scripts.upgrade_agent_system``);
  - ``scripts.upgrade.shutil`` IS ``scripts.upgrade_agent_system.shutil`` (and
    likewise for ``datetime``), so a test that patches ``scripts.upgrade.shutil``
    intercepts the owner's real copies -- the copy seam is unambiguous and the
    fail-without-fix barriers do not depend on a shared-``shutil`` accident;
  - there is exactly ONE editable body of upgrade logic.

Usage:
  python scripts/upgrade.py /path/to/project --dry-run
  python scripts/upgrade.py /path/to/project --confirm
  python scripts/upgrade.py /path/to/project --verify
"""

from __future__ import annotations

import sys

# WOT-2026-013t: single owner. Re-export the owner's public surface so this
# module stays the documented public entrypoint WITHOUT carrying a second
# editable UpgradeManager. `datetime` and `shutil` are re-exported so that code
# patching `scripts.upgrade.<name>` patches the SAME object the owner uses.
from scripts.upgrade_agent_system import (
    UpgradeManager,
    datetime,
    main,
    shutil,
)


__all__ = ["UpgradeManager", "datetime", "main", "shutil"]


if __name__ == "__main__":
    sys.exit(main())
