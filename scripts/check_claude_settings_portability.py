"""Portability/security gate for a tracked .claude/settings.json (WOT-2026-003c).

Invariants enforced on a *tracked* (versioned) Claude settings file:

1. No personal permission grants. ``permissions.allow`` is operator config and
   must live in the gitignored ``settings.local.json``, never in the tracked
   file (otherwise paths/domains/broad grants propagate to every clone).

2. A write guard MUST exist. There has to be a PreToolUse hook whose matcher
   covers Write, Edit AND MultiEdit. A *deleted* guard is as unsafe as a
   fail-open one, so an absent/partial hook is a violation.

3. The hook command must be the canonical entrypoint bootstrap
   (``claude_guard_entry.canonical_hook_command()``) -- nothing else. This is a
   STATIC check: the gate never executes the (potentially arbitrary) command
   string from the file it audits.

4. The canonical entrypoint itself must FAIL CLOSED. ``claude_guard_entry.py``
   (a trusted, versioned script) is executed in an isolated sandbox with no
   resolvable guard and must exit non-zero -- catching a fail-open regression
   in the entrypoint without ever running an untrusted settings command.

Before: a path to a ``.claude/settings.json`` (or a dir/repo-root with one).
During: parses JSON; static checks; one subprocess of the *trusted* entrypoint.
After: prints violations and returns exit code 0 (clean) or 1 (violations).
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENTRYPOINT = _PROJECT_ROOT / ".agent" / "hooks" / "claude_guard_entry.py"

# Import the canonical entrypoint module (single source of truth for the
# allowed hook command).
sys.path.insert(0, str(_PROJECT_ROOT / ".agent" / "hooks"))
import claude_guard_entry  # noqa: E402


_GATING_TOKENS = ("Write", "Edit", "MultiEdit")
_BENIGN_PAYLOAD = b'{"tool_name":"Write","tool_input":{"file_path":"x.txt"}}'


def check_no_personal_grants(settings: dict) -> list[str]:
    """Violations if the tracked settings hold personal permission grants."""
    violations: list[str] = []
    allow = settings.get("permissions", {}).get("allow") or []
    if allow:
        violations.append(
            "permissions.allow present in tracked settings "
            f"({len(allow)} grant(s)); move operator grants to the gitignored "
            "settings.local.json. Offending: " + ", ".join(map(str, allow[:5]))
        )
    return violations


def _gating_entries(settings: dict) -> list[dict]:
    """PreToolUse entries whose matcher references a write tool."""
    return [
        entry
        for entry in settings.get("hooks", {}).get("PreToolUse", [])
        if any(tok in entry.get("matcher", "") for tok in _GATING_TOKENS)
    ]


def check_write_guard_present(settings: dict) -> list[str]:
    """Require a PreToolUse hook covering Write, Edit AND MultiEdit.

    An absent or partial write guard is a violation: a deleted barrier is as
    dead as a fail-open one.
    """
    entries = _gating_entries(settings)
    if not entries:
        return [
            "no PreToolUse hook gates writes; a tracked settings.json must keep a "
            "Write|Edit|MultiEdit guard (a deleted guard is as unsafe as fail-open)"
        ]
    covered: set[str] = set()
    for entry in entries:
        matcher = entry.get("matcher", "")
        covered |= {tok for tok in _GATING_TOKENS if tok in matcher}
    missing = [tok for tok in _GATING_TOKENS if tok not in covered]
    if missing:
        return [f"write-guard matcher does not cover: {', '.join(missing)}"]
    return []


def check_command_is_canonical(settings: dict) -> list[str]:
    """Each write-gating hook command must equal the canonical entrypoint bootstrap.

    Static check: rejects arbitrary commands in tracked settings without ever
    executing them.
    """
    canonical = claude_guard_entry.canonical_hook_command()
    non_canonical = any(
        hook.get("type") == "command" and hook.get("command") != canonical
        for entry in _gating_entries(settings)
        for hook in entry.get("hooks", [])
    )
    if non_canonical:
        return [
            "write-gating hook command is not the canonical claude_guard_entry "
            "bootstrap; arbitrary commands in a tracked settings.json are rejected"
        ]
    return []


def check_entrypoint_fails_closed() -> list[str]:
    """The canonical entrypoint must exit non-zero with no resolvable guard."""
    if not _ENTRYPOINT.exists():
        return [f"canonical entrypoint missing: {_ENTRYPOINT}"]
    with tempfile.TemporaryDirectory(prefix="claude_guard_gate_") as sandbox:
        # Mark the sandbox itself as a repo root (a .claude with NO guard/link)
        # so the entrypoint resolves repo_root HERE and finds no guard --
        # robust regardless of where the system temp dir lives (e.g. a hermetic
        # test env whose TMP is inside a real repo).
        (Path(sandbox) / ".claude").mkdir()
        try:
            # Trusted: runs the repo's own canonical entrypoint (no shell, no
            # settings-supplied string) to verify it fails closed.
            result = subprocess.run(  # noqa: S603
                [sys.executable, str(_ENTRYPOINT), sandbox],
                input=_BENIGN_PAYLOAD,
                cwd=sandbox,
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return ["canonical entrypoint timed out; cannot confirm fail-closed"]
    if result.returncode == 0:
        return [
            "canonical entrypoint exited 0 with no resolvable guard "
            "(fail-open regression in claude_guard_entry.py)"
        ]
    return []


def check_settings_file(path: Path) -> list[str]:
    """Check one settings.json file. Returns violations (empty if clean)."""
    if not path.exists():
        return []  # nothing tracked to check
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"{path}: cannot parse settings JSON ({exc})"]
    return (
        check_no_personal_grants(settings)
        + check_write_guard_present(settings)
        + check_command_is_canonical(settings)
        + check_entrypoint_fails_closed()
    )


def _resolve_settings_path(arg: str | None) -> Path:
    """Resolve the settings.json path from an optional file/dir argument."""
    if arg is None:
        return Path(".claude/settings.json")
    p = Path(arg)
    if p.is_dir():
        return p / ".claude" / "settings.json"
    return p


@dataclass
class DiscoveryResult:
    """Census of destination links: nothing is dropped silently (DoD-1/DoD-3).

    Before: parent(motor_root) may hold sibling repos, some with a
    ``motor_destination_link.json``.
    During: every such link is resolved; each is either INCLUDED (an external,
    deduped destination) or recorded as SKIPPED with a machine-readable reason,
    EXCLUDED (motor/dogfooding of THIS motor, by identity), or DEDUPED (its
    resolved root duplicated an earlier link).
    After: ``included+skipped+excluded+deduped == links_total`` is an invariant
    the caller can assert; ``included`` is deduped-by-resolved-path THEN the
    motor and its dogfooding workspace are excluded (order is mandatory).
    """

    included: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    links_total: int = 0
    excluded: list[tuple[str, str]] = field(default_factory=list)
    # Links whose resolved destination_root duplicated an earlier link's
    # (collapsed by the dedupe that runs BEFORE exclusion). Kept so the census
    # is fully accountable: included+skipped+excluded+deduped == links_total.
    deduped: list[tuple[str, str]] = field(default_factory=list)


def _resolve_link(link: Path) -> tuple[Path | None, Path | None, str | None]:
    """Resolve one link. Returns (resolved_dest_root, resolved_motor_root, skip_reason).

    On success ``resolved_dest_root`` is a resolved directory path and
    ``skip_reason`` is None; ``resolved_motor_root`` is the resolved
    ``motor_root`` declared by the link (or None if absent/unparseable) --
    surfaced so the exclusion step can identify THIS motor's dogfooding
    workspace by IDENTITY, not by directory-name spelling.
    On failure ``resolved_dest_root`` is None and ``skip_reason`` explains why.
    """
    try:
        data = json.loads(link.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, None, f"unreadable link ({exc})"
    motor_root = data.get("motor_root")
    resolved_motor = None
    if motor_root:
        try:
            resolved_motor = Path(motor_root).resolve()
        except (OSError, ValueError):
            resolved_motor = None
    dest_root = data.get("destination_root")
    if not dest_root:
        return (
            None,
            resolved_motor,
            "no destination_root in motor_destination_link.json",
        )
    p = Path(dest_root)
    if not p.is_dir():
        return (
            None,
            resolved_motor,
            f"destination_root not a directory: {dest_root}",
        )
    return p.resolve(), resolved_motor, None


def _discover_destinations(motor_root: Path) -> DiscoveryResult:
    """Census every ``motor_destination_link.json`` sibling of the motor.

    Before: ``parent(motor_root)`` may hold sibling repos with destination links.
    During: reads each link (``_resolve_link``). A link is SKIPPED (with reason)
    when it lacks a ``destination_root``, the resolved root is not a directory,
    or the JSON is unreadable. Resolved roots are DEDUPED (two links -> one
    destination) and, ONLY AFTER dedupe, a destination is EXCLUDED from the
    external denominator BY IDENTITY iff its resolved path IS this motor
    (``_PROJECT_ROOT``) OR **any** link resolving to that path declares a
    ``motor_root`` that resolves to this motor -- i.e. it is THIS motor's own
    dogfooding workspace, identified by a resolved-topology FACT in the data,
    never by a naming convention.

    The dogfooding signal is aggregated across ALL links that resolve to the
    same path, INDEPENDENT of dedupe slot-winner order: a real workspace is
    reachable both by its own link (``motor_root`` == this motor) and by the
    principal's alias link (``motor_root`` == an upstream motor). Whichever link
    sorts first must not be able to MASK the identity carried by the other, so
    the ``motor_root``-matches-this-motor bit is OR-ed per resolved path before
    exclusion decides (P5 order preserved: dedupe collapses the alias, then the
    aggregated identity excludes the workspace).
    After: returns a ``DiscoveryResult`` where
    ``included+skipped+excluded+deduped == links_total`` and ``included`` holds
    only pure external destinations, deduped.
    """
    result = DiscoveryResult()
    parent = motor_root.parent
    if not parent.is_dir():
        return result
    this_motor = motor_root.resolve()
    # Ordered dedupe by resolved destination_root; first link wins the naming
    # slot. Per resolved path we also OR the dogfooding-identity bit across every
    # link that resolves there, so a masking alias cannot hide it.
    slot_child: dict[Path, Path] = {}
    is_dogfooding: dict[Path, bool] = {}
    for child in sorted(parent.iterdir()):
        if not child.is_dir():
            continue
        link = child / ".agent" / "config" / "motor_destination_link.json"
        if not link.exists():
            continue
        result.links_total += 1
        resolved, resolved_motor, reason = _resolve_link(link)
        if resolved is None:
            result.skipped.append((child.name, reason or "unresolved"))
            continue
        motor_root_is_this = resolved_motor is not None and resolved_motor == this_motor
        if resolved in slot_child:
            # DEDUPE (P5): collapse alias links to the same resolved root, but
            # still fold this link's dogfooding signal into the path's identity.
            result.deduped.append((child.name, str(resolved)))
            is_dogfooding[resolved] = is_dogfooding[resolved] or motor_root_is_this
            continue
        slot_child[resolved] = child
        is_dogfooding[resolved] = motor_root_is_this
    # THEN exclude motor + THIS motor's dogfooding by aggregated IDENTITY.
    for resolved, child in slot_child.items():
        is_this_motor = resolved == this_motor
        if is_this_motor or is_dogfooding[resolved]:
            result.excluded.append((child.name, str(resolved)))
            continue
        result.included.append(resolved)
    return result


# --- Real-hook classification: exactly 3 CLOSED classes (DoD-4) ---------------
CLASS_CANONICAL = "canonical"
CLASS_PYTHON_PATH = "python_path"
CLASS_UNPARSEABLE = "noncanonical_unparseable"


def _extract_python_script(command: str) -> str | None:
    """If ``command`` is ``python <path>.py [...]``, return ``<path>.py``, else None.

    A CLOSED parser, NOT a general command analyzer: it only recognises an
    invocation whose first token is a ``python`` launcher and whose next token
    is a path ending in ``.py``. The canonical command (``python -c "..."``) has
    no such ``.py`` argument token and is deliberately NOT matched here.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if len(tokens) < 2:
        return None
    launcher = Path(tokens[0]).name.lower()
    if launcher not in {"python", "python3", "py", "python.exe", "python3.exe"}:
        return None
    if tokens[1].startswith("-"):  # e.g. ``python -c "..."`` -> no script path
        return None
    if not tokens[1].lower().endswith(".py"):
        return None
    return tokens[1]


def classify_hook_command(command: str, dest_root: Path) -> tuple[str, Path | None]:
    """Classify a destination's real hook ``command`` into one of 3 classes.

    Before: ``command`` is the literal string from the destination's
    ``.claude/settings.json`` write-gating hook; the guard is NEVER executed.
    During: canonical is decided by EQUALITY to
    ``claude_guard_entry.canonical_hook_command()`` (reusing the same comparison
    as ``check_command_is_canonical``, not ``'.py' in command``); otherwise the
    command is tested for a ``python <path>.py`` form whose path is resolved
    relative to ``dest_root``; otherwise it is unparseable.
    After: returns ``(class, resolved_path_or_None)``. For CLASS_PYTHON_PATH the
    path is the resolved ``.py`` (existence is the caller's concern).
    """
    if command == claude_guard_entry.canonical_hook_command():
        return CLASS_CANONICAL, None
    script = _extract_python_script(command)
    if script is None:
        return CLASS_UNPARSEABLE, None
    script_path = Path(script)
    if not script_path.is_absolute():
        script_path = dest_root / script_path
    return CLASS_PYTHON_PATH, script_path


def check_hook_file_exists(dest_root: Path, command: str) -> list[str]:
    """Verify the REAL hook command of a destination references an existing hook.

    Before: ``command`` is the destination's actual write-gating hook string.
    During (no guard execution, DoD-4):
    - CLASS_CANONICAL: the canonical bootstrap resolves ``claude_guard_entry.py``
      locally, or via ``motor_destination_link.json`` (the remote branch is
      CORRECT only for the canonical command); a violation only if neither
      resolves.
    - CLASS_PYTHON_PATH: the referenced ``.py`` must EXIST relative to
      ``dest_root`` (Upscaler case: ``python .agent/hooks/guard_paths.py`` whose
      file is absent -> flagged missing). Canonicity is NOT its precondition,
      so ``0 missing hook files`` can no longer hide an absent referenced file.
    - CLASS_UNPARSEABLE: no ``.py`` file to check here; canonicity is enforced
      separately by ``check_command_is_canonical`` -- no missing-hook claim.
    After: returns violation messages (empty when the referenced hook exists).
    """
    cls, script_path = classify_hook_command(command, dest_root)
    if cls == CLASS_CANONICAL:
        if _canonical_entry_resolves(dest_root):
            return []
        return [
            "canonical hook command but claude_guard_entry.py not found locally "
            "nor via motor_destination_link.json; write guard will fail-closed "
            "(exit 2) but the hook file is missing"
        ]
    if cls == CLASS_PYTHON_PATH:
        if script_path is not None and script_path.exists():
            return []
        return [
            f"hook command references a python script that does not exist: "
            f"{script_path}"
        ]
    return []


def _canonical_entry_resolves(dest_root: Path) -> bool:
    """True if the canonical bootstrap can locate ``claude_guard_entry.py``.

    Local copy first, then the motor's copy via ``motor_destination_link.json``.
    This is the ORIGINAL remote-resolution branch, now scoped to the canonical
    command class only (its correct home, per the reframed contract).
    """
    local = dest_root / ".agent" / "hooks" / "claude_guard_entry.py"
    if local.exists():
        return True
    link = dest_root / ".agent" / "config" / "motor_destination_link.json"
    if link.exists():
        try:
            data = json.loads(link.read_text(encoding="utf-8"))
            motor_root = data.get("motor_root")
            if motor_root:
                motor_hook = (
                    Path(motor_root) / ".agent" / "hooks" / "claude_guard_entry.py"
                )
                if motor_hook.exists():
                    return True
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    return False


def _hook_command_of(settings_path: Path) -> str | None:
    """Return the first write-gating hook ``command`` in a settings file, or None."""
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    for entry in _gating_entries(settings):
        for hook in entry.get("hooks", []):
            if hook.get("type") == "command":
                cmd = hook.get("command")
                if isinstance(cmd, str):
                    return cmd
    return None


@dataclass
class FleetReport:
    """Census-based fleet result: knows and publishes its denominator (DoD-2)."""

    discovery: DiscoveryResult
    inspected: list[str] = field(default_factory=list)
    violations: list[tuple[str, str]] = field(default_factory=list)
    sin_settings: list[str] = field(default_factory=list)
    missing_hook: list[tuple[str, str]] = field(default_factory=list)


def fleet_check(motor_root: Path) -> FleetReport:
    """Check every external destination and publish the census (DoD-1/2/3/4).

    Before: ``motor_root`` is the motor repo; its siblings may carry destination
    links.
    During: discovers destinations (census with skips + dedupe + identity-based
    exclusion), then for each INCLUDED destination inspects its
    ``.claude/settings.json``: missing settings -> ``sin_settings``; present ->
    static portability checks plus real-hook classification of the destination's
    actual command (no guard execution).
    After: returns a ``FleetReport`` carrying the denominator (discovery),
    inspected destinations, violations, sin_settings and missing_hook. The
    caller (``_report_fleet``) turns it into an exit code.
    """
    discovery = _discover_destinations(motor_root)
    report = FleetReport(discovery=discovery)
    for dest in discovery.included:
        settings_path = dest / ".claude" / "settings.json"
        if not settings_path.exists():
            report.sin_settings.append(dest.name)
            continue
        report.inspected.append(dest.name)
        report.violations.extend(
            (dest.name, msg) for msg in check_settings_file(settings_path)
        )
        command = _hook_command_of(settings_path)
        if command is not None:
            report.missing_hook.extend(
                (dest.name, msg) for msg in check_hook_file_exists(dest, command)
            )
    return report


def _print_pairs(header: str, pairs: list[tuple[str, str]]) -> None:
    """Print ``header`` then one ``  [name] msg`` line per pair (if any)."""
    if not pairs:
        return
    print(header)
    for name, msg in pairs:
        print(f"  [{name}] {msg}")


def _report_fleet(report: FleetReport) -> int:
    """Print fleet report and return exit code (DoD-1/DoD-2 census rule).

    Prints the denominator (external destinations) / inspected / hits
    (violations) / skipped (with its list). Non-zero on violations, missing
    hooks, sin_settings, UNRESOLVED SKIPS, or an empty inspected set (RED census).
    """
    discovery = report.discovery
    denominator = len(discovery.included)
    inspected = len(report.inspected)

    _print_pairs("[FLEET] Destinations with VIOLATIONS:", report.violations)
    _print_pairs("[FLEET] Destinations with missing hook file:", report.missing_hook)
    if report.sin_settings:
        print("[FLEET] Destinations WITHOUT .claude/settings.json (no write guard):")
        for name in report.sin_settings:
            print(f"  [{name}]")
    _print_pairs(
        "[FLEET] Links SKIPPED (unresolved, not counted in denominator):",
        discovery.skipped,
    )

    # Census line: denominator / inspected / hits / skipped (DoD-2).
    print(
        f"[FLEET] Census: links_total={discovery.links_total} "
        f"denominator(external)={denominator} inspected={inspected} "
        f"hits(violations)={len(report.violations)} "
        f"skipped={len(discovery.skipped)} "
        f"sin_settings={len(report.sin_settings)} "
        f"missing_hook={len(report.missing_hook)} "
        f"excluded={len(discovery.excluded)} "
        f"deduped={len(discovery.deduped)}"
    )

    inspected_zero = inspected == 0
    if inspected_zero:
        print("[FLEET] RED: inspected == 0 (no destination could be inspected).")

    failed = bool(
        report.violations
        or report.sin_settings
        or report.missing_hook
        or discovery.skipped
        or inspected_zero
    )
    if not failed:
        print("[FLEET] All external destinations have valid .claude/settings.json")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Portability/security gate for tracked .claude/settings.json"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to settings.json or directory containing .claude/settings.json",
    )
    parser.add_argument(
        "--fleet",
        action="store_true",
        help="Check .claude/settings.json across all destination repos under parent(motor_root)",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.fleet:
        return _report_fleet(fleet_check(_PROJECT_ROOT))

    path = _resolve_settings_path(args.path)
    violations = check_settings_file(path)
    if violations:
        print(f"[check-claude-settings-portability] {path}: NOT portable/secure:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"[check-claude-settings-portability] {path}: OK (portable, fail-closed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
