"""Script to verify that ruff pre-commit hooks remain Python-only to prevent drift."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / ".pre-commit-config.yaml"


def _accumulate_list_item(hook: dict[str, str | list[str]], key: str, val: str) -> None:
    """Helper to accumulate list items in current hook."""
    existing = hook.get(key)
    if existing is not None:
        if isinstance(existing, list):
            existing.append(val)
        else:
            hook[key] = [str(existing), val]
    else:
        hook[key] = [val]


def _parse_hooks(content: str) -> list[dict[str, str | list[str]]]:
    """Parse YAML lines to retrieve hook blocks."""
    lines = content.splitlines()
    hooks = []
    current_hook: dict[str, str | list[str]] = {}
    current_key = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check if a new hook item starts with a hyphen
        if stripped.startswith("-") and "id:" in stripped:
            if current_hook:
                hooks.append(current_hook)
            current_hook = {}
            current_key = None

            parts = stripped[1:].split(":", 1)
            k, v = parts[0].strip(), parts[1].strip()
            current_hook[k] = v
            current_key = k
            continue

        if current_hook:
            # If it's a key-value pair
            if (
                ":" in stripped
                and not stripped.startswith("[")
                and not stripped.startswith("-")
            ):
                parts = stripped.split(":", 1)
                k, v = parts[0].strip(), parts[1].strip()
                current_hook[k] = v
                current_key = k
            elif stripped.startswith("-") and current_key:
                # Multi-line list item value for current_key
                val = stripped[1:].strip()
                _accumulate_list_item(current_hook, current_key, val)

    if current_hook:
        hooks.append(current_hook)
    return hooks


def _normalize_types_val(raw: str | list[str] | None) -> str:
    """Flatten inline or multi-line 'types' values to a single comparable string."""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return " ".join(raw).lower()
    return str(raw).lower()


def check_pre_commit_config(content: str) -> tuple[bool, str]:
    """Parse .pre-commit-config.yaml and verify ruff hooks are restricted to Python.

    Returns:
        (bool, reason)
    """
    try:
        hooks = _parse_hooks(content)
    except Exception as e:
        return False, f"Could not parse hooks: {e}"

    ruff_hooks = [h for h in hooks if h.get("id") in ("ruff-check", "ruff-format")]
    if not ruff_hooks:
        return (
            False,
            "No ruff pre-commit hooks (ruff-check/ruff-format) found in .pre-commit-config.yaml",
        )

    for hook in ruff_hooks:
        hook_id = hook.get("id")

        # Normalize types and files — supports both inline and multi-line YAML list forms
        types_val = _normalize_types_val(hook.get("types"))
        files_val = str(hook.get("files", ""))

        if "markdown" in types_val or "md" in types_val:
            return (
                False,
                f"Hook '{hook_id}' explicitly includes Markdown or other non-Python: '{types_val}'",
            )

        # Verify hook scope
        has_python_type = "python" in types_val
        has_python_files = ".py" in files_val or "\\.py$" in files_val

        if not (has_python_type or has_python_files):
            return False, (
                f"Hook '{hook_id}' is not restricted to Python-only files. "
                f"Found types: '{types_val}', files: '{files_val}'"
            )

    return (
        True,
        f"Verified {len(ruff_hooks)} ruff hooks are correctly restricted to Python.",
    )


def main() -> int:
    if not CONFIG_PATH.exists():
        print(f"[scope-guard] Config file not found at {CONFIG_PATH}", file=sys.stderr)
        return 1

    try:
        content = CONFIG_PATH.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[scope-guard] Could not read {CONFIG_PATH}: {e}", file=sys.stderr)
        return 1

    success, reason = check_pre_commit_config(content)
    if not success:
        print(f"[scope-guard] GUARD FAIL: {reason}", file=sys.stderr)
        return 1

    print(f"[scope-guard] GUARD PASS: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
