"""OpenCode CLI transport helpers for the Manager review cycle.

Extracted from bus/review_bridge.py (monolith decomposition). This module
owns everything related to *talking to* the OpenCode CLI process — none of
it depends on ReviewBridge state:

- Transport-result classification (did the invocation reach the model?).
- Detection of help-banner output and backend auth failures that can
  return exit code 0.
- ``--format json`` capability detection (WT-2026-242a).
- Isolated subprocess environment construction (scratch HOME + auth copy).
- NDJSON streaming text extraction (WT-2026-204).
- Model identifier normalization for the ``--model`` flag.

``ReviewBridge`` delegates to these functions through thin wrappers.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from pathlib import Path


# WT-2026-242a: Patterns that indicate --format json is not supported by the
# real manager_executable. Used by the review runner's try-first logic to
# fall back to non-JSON output when the CLI rejects the flag.
UNSUPPORTED_JSON_FLAG_PATTERNS = (
    "unknown flag",
    "invalid option",
    "opencode run [message..]",
    "show help",
    "usage:",
)

_NDJSON_SIGNATURES = ('"type":"step_finish"', '"type":"step_start"')


def _candidate_text(stdout: str, stderr: str) -> str:
    """Return the text to inspect for CLI banners/errors.

    If stdout contains real NDJSON events (step_start / step_finish) it is
    genuine model output — marker strings may appear inside source code the
    model read, not as an actual banner. Only inspect stderr in that case,
    since OpenCode writes its CLI help to stderr.
    """
    stdout_has_ndjson = any(sig in stdout for sig in _NDJSON_SIGNATURES)
    return stderr.lower() if stdout_has_ndjson else f"{stdout}\n{stderr}".lower()


def looks_like_opencode_help(stdout: str, stderr: str) -> bool:
    """Detect an OpenCode help banner instead of model output."""
    candidate = _candidate_text(stdout, stderr)
    markers = (
        "opencode run [message..]",
        "run opencode with a message",
        "show help",
    )
    return any(marker in candidate for marker in markers)


def looks_like_auth_failure(stdout: str, stderr: str) -> bool:
    """Detect backend auth failures that may still return process exit 0."""
    candidate = _candidate_text(stdout, stderr)
    markers = (
        "token_invalidated",
        "token invalidated",
        "authentication token has been invalidated",
        "authentication failed",
        "bad credentials",
        "status 401",
        'status": 401',
        'statuscode":401',
        'statuscode": 401',
        "x-openai-authorization-error",
    )
    return any(marker in candidate for marker in markers)


def classify_transport_result(
    stdout: str, stderr: str, exit_code: int
) -> tuple[bool, str]:
    """Classify whether the OpenCode invocation reached the model.

    Returns (transport_ok, error_label). ``timeout_retryable`` is reported
    as transport-ok so the caller can retry instead of failing hard.
    """
    if "TimeoutExpired" in stderr:
        return True, "timeout_retryable"
    if exit_code != 0:
        return False, f"exit_code={exit_code}"
    if looks_like_auth_failure(stdout, stderr):
        return False, "auth_failed"
    if looks_like_opencode_help(stdout, stderr):
        return False, "help_output_detected"
    return True, ""


def needs_json_fallback(stderr: str) -> bool:
    """Return True if stderr indicates --format json is not supported.

    WT-2026-242a: The fallback is governed by concrete patterns from
    the real executable's error output, not by exit code alone. Returns
    True only when stderr contains CLI-flag-rejection markers.
    """
    stderr_lower = stderr.lower()
    return any(p in stderr_lower for p in UNSUPPORTED_JSON_FLAG_PATTERNS)


def build_review_env() -> dict[str, str]:
    """Return an isolated process environment for review execution.

    Before: os.environ was inherited unchanged, which allowed OpenCode to
            reuse the host home directory and fail on Windows with EEXIST.
    During: Creates a scratch home, redirects HOME/USERPROFILE/XDG_* there,
            and copies auth.json so OpenCode can start cleanly without
            losing credentials. Keeps at most 10 scratch dirs (oldest by
            mtime are deleted).
    After: Returns the environment dict for subprocess execution.
    """
    env = os.environ.copy()
    tmp_root = Path(tempfile.gettempdir())
    scratch_home = Path(tempfile.mkdtemp(prefix="opencode-review-", dir=tmp_root))

    existing = sorted(
        tmp_root.glob("opencode-review-*"),
        key=lambda p: p.stat().st_mtime,
    )
    for old in existing[:-10]:
        shutil.rmtree(old, ignore_errors=True)

    env["HOME"] = str(scratch_home)
    env["USERPROFILE"] = str(scratch_home)
    env["XDG_CONFIG_HOME"] = str(scratch_home / ".config")
    env["XDG_DATA_HOME"] = str(scratch_home / ".local" / "share")
    env["XDG_STATE_HOME"] = str(scratch_home / ".local" / "state")

    source_home = Path(
        os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())
    )
    source_auth = source_home / ".local" / "share" / "opencode" / "auth.json"
    if source_auth.exists():
        target_auth = scratch_home / ".local" / "share" / "opencode" / "auth.json"
        target_auth.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_auth, target_auth)

    return env


def normalize_opencode_model(model: str | None) -> str | None:
    """Normalize a role model to the identifier accepted by OpenCode CLI.

    The OpenCode CLI ``--model`` flag accepts provider-qualified IDs verbatim:
    ``opencode-go/deepseek-v4-flash``, ``openai/gpt-5.4-mini``, etc.
    Both forms were verified to work against the real CLI. No stripping needed.
    """
    if model is None:
        return None
    return model.strip() or None


def extract_json_stream_text(stdout: str) -> str | None:
    """Extract concatenated text from OpenCode NDJSON streaming output.

    WT-2026-204: Before applying regex on structured sections (## SUMMARY,
    ## BLOCKERS, ## SUGGESTIONS), extract text from ``obj["part"]["text"]``
    of each NDJSON line. This prevents the parser from failing when stdout
    contains JSONL lines interleaved with raw text (the real OpenCode
    ``--format json`` output).

    Falls back to ``obj["content"]`` list blocks for the legacy format.
    Returns None if no NDJSON text could be extracted from any line.
    """
    extracted: list[str] = []
    for line in stdout.split("\n"):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        with contextlib.suppress(Exception):
            obj = json.loads(line)
            part = obj.get("part", {})
            if isinstance(part, dict) and part.get("type") == "text" and "text" in part:
                extracted.append(part["text"])
            elif "content" in obj and isinstance(obj["content"], list):
                extracted.extend(
                    block["text"]
                    for block in obj["content"]
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "text"
                        and "text" in block
                    )
                )
    if extracted:
        return "\n".join(extracted)
    return None
