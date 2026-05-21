# Tests Usage Guide

This folder contains the Windows-safe test runtime used by the project.

## Quick policy

Use:
- `tmp_path` and `tmp_path_factory` from `tests/conftest.py`
- `tests._temp_runtime.managed_test_dir()` for manual temp dirs
- `python scripts/run_pytest_safe.py` as the official and recommended entry point on Windows
- `tests/sandbox/test_runtime/` as the runtime root for test temps

Avoid:
- `TemporaryDirectory()` as the default pattern on Windows
- native pytest temp handling outside the project override
- `tests/tmp/` as a convention
- temp directories scattered in the repo root
- direct `pytest` runs as the normal path when the safe runner is available

## When to use each helper

- Use `tmp_path` when the test only needs one isolated temp directory.
- Use `managed_test_dir()` when the test needs a context-managed probe directory or nested workspaces.

## Commands

```powershell
python scripts/run_pytest_safe.py
python scripts/run_pytest_safe.py --status
python scripts/run_pytest_safe.py --cleanup-only
python -m pytest tests -q -p no:cacheprovider
```

Prefer `scripts/run_pytest_safe.py` for regular runs. Use raw `pytest` only for targeted diagnostics when you already know the environment is safe.
