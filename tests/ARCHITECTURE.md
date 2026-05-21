# Tests Architecture

This document explains how the Windows-safe test runtime works.

## Goal

The objective is to make pytest runs deterministic on Windows by avoiding the default temp handling paths that often fail with locked files, cleanup errors, or permission problems.

## Layers

### Layer 1: project-owned runtime

All test temp activity lives under:

```text
tests/
  sandbox/
    test_runtime/
    {session_id}/
      pytest/
      tempfile/
```

This keeps temp paths short, local to the project, and easy to clean.

### Layer 2: pytest fixture override

`tests/conftest.py` replaces:
- `tmp_path_factory`
- `tmp_path`

with a project-owned implementation.

It also:
- redirects `tempfile.tempdir`
- restores `cwd` after each test
- removes the session runtime during `pytest_sessionfinish`

### Layer 3: manual temp helper

`tests/_temp_runtime.py` provides `managed_test_dir(prefix)`.

Use it when a test needs a context-manager-style temp directory without relying on `TemporaryDirectory()`.

### Layer 4: runner

`scripts/run_pytest_safe.py` is only the coordinator.

It helps with:
- lock handling
- status reporting
- cleanup of known runtime folders
- stable `--basetemp`

It is not the primary fix. The primary fix is the test runtime design.

## Smoke validation

The template ships with a small smoke test that validates:
- custom `tmp_path`
- `managed_test_dir()`
- `cwd` restoration behavior

When this smoke test passes in a new project, the runtime is ready for reuse.
