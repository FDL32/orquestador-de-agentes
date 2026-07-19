"""Tests for scripts/check_bundle_receipts.py (mejora-continua v0, HUECO-1).

The receipt-guard fails a governance bundle whose PROBE sections make executable
claims without a real receipt (command + exit_code + resolvable paths). Mutation
with teeth: a bundle citing a NON-EXISTENT path, or omitting exit_code, must FAIL;
a well-formed bundle must PASS; an explicitly exempted section is allowed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_bundle_receipts", _ROOT / "scripts" / "check_bundle_receipts.py"
)
guard = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = guard
_SPEC.loader.exec_module(guard)


_GOOD = """# Bundle
## PROBE 1 -- denominator
```receipt
command: python -c "print(1)"
exit_code: 0
path: scripts/check_bundle_receipts.py
```
## QUESTIONS
Q1. ...
"""

_MISSING_RECEIPT = """# Bundle
## PROBE 1 -- claims something with no receipt
The script already covers reports.
## QUESTIONS
"""

_BAD_PATH = """# Bundle
## PROBE 1 -- cites a ghost file
```receipt
command: grep x scripts/does_not_exist_zzz.py
exit_code: 0
path: scripts/does_not_exist_zzz.py
```
"""

_NO_EXIT = """# Bundle
## PROBE 1 -- no exit code
```receipt
command: python foo.py
```
"""

_EXEMPT = """# Bundle
## PROBE 1 -- context only
<!-- no-receipt: narrative context, makes no executable claim -->
Some prose.
"""


def _run(text: str, tmp_path: Path, root: Path | None = None) -> int:
    b = tmp_path / "bundle.md"
    b.write_bytes(text.encode("utf-8"))
    return guard.run(["--bundle", str(b), "--root", str(root or _ROOT)])


def test_wellformed_bundle_passes(tmp_path: Path):
    assert _run(_GOOD, tmp_path) == 0


def test_probe_without_receipt_fails(tmp_path: Path):
    """The core HUECO-1 case: a claim ('already covers reports') with no receipt."""
    assert _run(_MISSING_RECEIPT, tmp_path) == 1


def test_receipt_citing_nonexistent_path_fails(tmp_path: Path):
    """Mutation teeth: a false receipt (cited path does not resolve) must FAIL --
    a guard that only checked 'a receipt block exists' would pass this."""
    assert _run(_BAD_PATH, tmp_path) == 1


def test_receipt_without_exit_code_fails(tmp_path: Path):
    assert _run(_NO_EXIT, tmp_path) == 1


def test_explicit_exemption_passes(tmp_path: Path):
    assert _run(_EXEMPT, tmp_path) == 0


def test_no_probe_sections_fails_closed(tmp_path: Path):
    """A bundle with zero PROBE sections is a usage error, never a silent green."""
    assert _run("# Bundle\n## QUESTIONS\nQ1.\n", tmp_path) == 1


def test_missing_bundle_file_fails(tmp_path: Path):
    assert guard.run(["--bundle", str(tmp_path / "nope.md"), "--root", str(_ROOT)]) == 1


def test_unit_validate_receipt_reports_each_problem(tmp_path: Path):
    """Unit: validate_receipt names BOTH a missing exit_code AND a bad path."""
    body = "## PROBE x\n```receipt\ncommand: foo\npath: scripts/ghost_zzz.py\n```\n"
    ok, problems = guard.validate_receipt(body, _ROOT)
    assert not ok
    assert any("exit_code" in p for p in problems)
    assert any("does not resolve" in p for p in problems)
