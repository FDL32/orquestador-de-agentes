#!/usr/bin/env python3
# ruff: noqa: S603, S607, C901
"""
Pre-handoff guard - Verifica higiene del arbol antes de emitir READY_FOR_REVIEW.

Este script se invoca desde agent_controller.py en _handle_mark_ready() antes de
emitir STATE_CHANGED -> READY_FOR_REVIEW.

Ejecuta git status --porcelain y excluye:
- Superficies vivas del runtime (TURN.md, STATE.md, execution_log.md, events.jsonl, etc.)
- Archivos ya ignorados por .gitignore

Si el arbol esta sucio, devuelve exit 1 + JSON diagnostico.
Si falta el checkpoint M3, devuelve exit 1 + JSON diagnostico.
Si hay archivos fuera de Files Likely Touched, los reporta como scope_discrepancy
(no bloqueante, solo observacion).

Uso:
    python scripts/pre_handoff_guard.py --project-root /path --ticket-id WOT-2026-XXX
"""

import json
import subprocess
import sys
from pathlib import Path


# Superficies vivas del runtime que NO deben generar falsos positivos
# Incluye archivos individuales y directorios completos
# PROJECT.md es superficie viva tolerada (WP-2026-172): se actualiza como
# parte del ciclo operativo y no debe bloquear --mark-ready como dirty_tree
# cuando sea la unica diferencia relevante.
LIVE_SURFACES_REL = {
    ".agent/collaboration/TURN.md",
    ".agent/collaboration/STATE.md",
    ".agent/collaboration/execution_log.md",
    ".agent/collaboration/notifications.md",
    ".agent/collaboration/review_queue.md",
    ".agent/collaboration/work_plan.md",
    ".agent/collaboration/backlog.md",
    ".agent/collaboration/archive/",
    ".agent/collaboration/_archive/",
    ".agent/runtime/memory/session_close_report.md",
    ".agent/runtime/events/events.jsonl",
    ".agent/runtime/store.json",
    ".agent/runtime/builder_lock.txt",
    ".agent/runtime/circuit_breaker.json",
    ".agent/runtime/supervisor_lock.txt",
    ".agent/runtime/relaunch_capsule.md",
    ".agent/runtime/events/",
    ".agent/runtime/approvals/",
    ".agent/context/project-map.json",
    "PROJECT.md",
}

# Patrones glob de archivos excluidos del workspace (AGENTS.md: Excluidos del workspace)
# Estos archivos son historicos/transitorios y no deben bloquear el handoff.
#
# WOT-2026-010a nomenclatura:
#   canonical:     STRATEGY_WOT-, AUDIT_WOT-
#   legacy-compat: PLAN_WP-, PLAN_WT-, AUDIT_WP-, AUDIT_WT-
# Se conservan ambos: los historicos siguen excluidos del dirty-tree del handoff.
WORKSPACE_EXCLUDED_PREFIXES = {
    ".agent/collaboration/STRATEGY_WOT-",  # canonical
    ".agent/collaboration/AUDIT_WOT-",  # canonical
    ".agent/collaboration/PLAN_WP-",  # legacy-compat
    ".agent/collaboration/AUDIT_WP-",  # legacy-compat
    ".agent/collaboration/AUDIT_WT-",  # legacy-compat
    ".agent/collaboration/PLAN_WT-",  # legacy-compat
    ".agent/collaboration/manager_feedback_",
}

# Directorios completos de superficies vivas (para excluir todo el arbol)
LIVE_SURFACE_DIRS = {
    ".agent/collaboration/archive",
    ".agent/collaboration/_archive",
    ".agent/runtime/events",
    ".agent/runtime/approvals",
}


def get_project_root(args_project_root: str | None) -> Path:
    """Obtener project root desde args o desde el directorio actual."""
    if args_project_root:
        return Path(args_project_root).resolve()
    # Default: subir dos niveles desde scripts/
    return Path(__file__).resolve().parent.parent


def get_gitignore_patterns(project_root: Path) -> set[str]:
    """Leer patrones de .gitignore y devolver paths ignorados."""
    ignored = set()
    gitignore = project_root / ".gitignore"
    if not gitignore.exists():
        return ignored

    try:
        content = gitignore.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                # Patrones simples: convertir a path relativo
                if line.startswith("/"):
                    line = line[1:]
                if line.endswith("/"):
                    line = line[:-1]
                if line:
                    ignored.add(line)
    except OSError:
        pass

    return ignored


def is_ignored_by_gitignore(file_path: Path, project_root: Path) -> bool:
    """Verificar si un archivo es ignorado por .gitignore usando git check-ignore."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", str(file_path.relative_to(project_root))],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        return result.returncode == 0
    except (FileNotFoundError, ValueError):
        return False


def get_live_surfaces_absolute(project_root: Path) -> tuple[set[str], set[str]]:
    """
    Devolver paths absolutos de superficies vivas.

    Returns:
        tuple[set[str], set[str]]: (archivos individuales, directorios completos)
    """
    live_files = set()
    live_dirs = set()

    for rel_path in LIVE_SURFACES_REL:
        full_path = project_root / rel_path
        if rel_path.endswith("/"):
            # Es un directorio
            live_dirs.add(str(full_path.resolve()))
        else:
            live_files.add(str(full_path.resolve()))

    # Tambien incluir cualquier archivo en .agent/collaboration/archive/
    archive_dir = project_root / ".agent" / "collaboration" / "archive"
    if archive_dir.exists():
        for f in archive_dir.glob("*"):
            live_files.add(str(f.resolve()))

    # Incluir _archive/plan_audit/
    plan_audit_dir = (
        project_root / ".agent" / "collaboration" / "_archive" / "plan_audit"
    )
    if plan_audit_dir.exists():
        for f in plan_audit_dir.glob("*"):
            live_files.add(str(f.resolve()))

    # Añadir directorios de LIVE_SURFACE_DIRS
    for rel_dir in LIVE_SURFACE_DIRS:
        full_path = project_root / rel_dir
        live_dirs.add(str(full_path.resolve()))

    return live_files, live_dirs


def is_workspace_excluded(rel_path: str) -> bool:
    """Verificar si un path relativo coincide con patrones excluidos del workspace.

    Archivos como PLAN_WP-*.md y AUDIT_WP-*.md estan explicitamente excluidos
    del workspace segun AGENTS.md y no deben bloquear el handoff.
    """
    normalized = rel_path.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in WORKSPACE_EXCLUDED_PREFIXES)


def is_in_live_surface_dir(file_path: str, live_dirs: set[str]) -> bool:
    """Verificar si un archivo esta dentro de un directorio de superficie viva."""
    file_path_obj = Path(file_path)
    for live_dir in live_dirs:
        live_dir_obj = Path(live_dir)
        try:
            file_path_obj.relative_to(live_dir_obj)
            return True
        except ValueError:
            continue
    return False


def get_changed_files(project_root: Path) -> set[str]:
    """Obtener archivos cambiados (staged, unstaged, untracked) usando git status."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        changed = set()
        entries = result.stdout.split("\0")
        i = 0
        while i < len(entries):
            entry = entries[i]
            if not entry:
                i += 1
                continue
            if len(entry) >= 3:
                status = entry[:2]
                path = entry[3:] if entry[2] == " " else entry[2:]
                # Manejar renames
                if status[0] == "R" and i + 1 < len(entries):
                    new_path = entries[i + 1]
                    if new_path:
                        changed.add(new_path)
                    i += 2
                    continue
                else:
                    changed.add(path)
            i += 1

        # Resolver a paths absolutos
        resolved = set()
        for f in changed:
            path = (project_root / f).resolve()
            resolved.add(str(path))
        return resolved
    except FileNotFoundError:
        return set()


def check_checkpoint_alignment(project_root: Path, ticket_id: str) -> tuple[bool, bool]:
    """Check checkpoint M3 alignment.

    Verifica si el tag checkpoint/review-<ticket> existe y si apunta
    al mismo commit que HEAD.

    Returns:
        tuple[bool, bool]: (missing_checkpoint, checkpoint_misaligned)
            - (True, False): tag no existe
            - (False, True): tag existe pero apunta a otro commit
            - (False, False): tag existe y esta alineado con HEAD
    """
    tag_name = f"checkpoint/review-{ticket_id}"
    try:
        # Check if tag exists and get its commit hash
        result = subprocess.run(
            ["git", "rev-parse", f"{tag_name}^{{}}"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        if result.returncode != 0:
            return (True, False)  # missing checkpoint

        tag_commit = result.stdout.strip()

        # Get HEAD commit hash
        head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        if head_result.returncode != 0:
            return (False, True)  # cannot determine HEAD, treat as misaligned

        head_commit = head_result.stdout.strip()

        if tag_commit != head_commit:
            return (False, True)  # checkpoint misaligned

        return (False, False)  # aligned
    except FileNotFoundError:
        return (True, False)


def _import_scope_gate():
    """Import scope_gate from the motor .agent/ directory."""
    agent_dir = Path(__file__).resolve().parent.parent / ".agent"
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    import scope_gate as _sg

    return _sg


def _import_motor_checkpoint():
    """Import motor_checkpoint from the motor .agent/ directory."""
    agent_dir = Path(__file__).resolve().parent.parent / ".agent"
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    import motor_checkpoint as _mc

    return _mc


def parse_files_likely_touched(
    project_root: Path,
    motor_root: Path | None = None,
) -> set[str]:
    """Parsear Files Likely Touched desde work_plan.md.

    Delegates to scope_gate.parse_flt_namespaced (WOT-2026-009b) so there
    is a single canonical FLT parser. Returns the union of motor and destino
    paths when motor_root is provided, otherwise destino-only paths.

    Args:
        project_root: Destino root (workspace activo).
        motor_root: Motor root for ### repo_motor path resolution.
    """
    work_plan = project_root / ".agent" / "collaboration" / "work_plan.md"
    if not work_plan.exists():
        return set()

    try:
        content = work_plan.read_text(encoding="utf-8")
    except OSError:
        return set()

    try:
        sg = _import_scope_gate()
    except ImportError:
        # Fallback: flat FLT parsing against project_root (pre-009b behavior)
        return sg_fallback_parse(content, project_root)

    effective_motor_root = motor_root if motor_root is not None else project_root
    da = _read_delivery_authority_from_content(content)
    dt = _read_deliverable_type_from_content(content)
    buckets = sg.parse_flt_namespaced(
        content,
        motor_root=effective_motor_root,
        project_root=project_root,
        delivery_authority=da,
        deliverable_type=dt,
    )
    # When motor_root is explicit: return union (scope covers both repos).
    # When motor_root is absent (standalone/test context): return all resolved
    # paths so scope_discrepancy still works — flat paths landed in "motor"
    # bucket because effective_motor_root == project_root.
    return buckets["motor"] | buckets["destino"]


def _read_delivery_authority_from_content(content: str) -> str:
    """Read delivery_authority field from work_plan content."""
    import re

    if re.search(
        r"delivery_authority\s*:?\**\s*(?:repo_destino|destino)",
        content,
        re.IGNORECASE,
    ):
        return "repo_destino"
    return "repo_motor"


def resolve_delivery_root(
    *,
    project_root: Path,
    motor_root: Path | None,
    delivery_authority: str,
) -> Path:
    """Resolve the repo where the ticket deliverable actually lands.

    The close-gate barriers (canonical suite freshness and visible productive
    commit) must be evaluated against the repo that holds the deliverable, which
    is decided by ``delivery_authority``, NOT by whether ``motor_root`` was
    passed. In motor-external topology a ``repo_destino`` code ticket keeps its
    productive commit and its run_pytest_safe ``last-run.json`` in the destination
    (``project_root``); the motor only hosts the engine code.

    Before: project_root is the active workspace (destination); motor_root is the
        engine repo or None (standalone/test); delivery_authority is read from the
        active work_plan ('repo_destino' or 'repo_motor').
    During: pure path selection, no I/O.
    After: returns project_root when delivery_authority == 'repo_destino';
        otherwise motor_root if set, else project_root (standalone fallback).
    """
    if delivery_authority == "repo_destino":
        return project_root
    return motor_root if motor_root is not None else project_root


def _read_deliverable_type_from_content(content: str) -> str:
    """Read deliverable_type from work_plan content; default 'code'."""
    import re

    m = re.search(
        r"deliverable_type\s*:?\**\s*(code|documentation|research|analysis|mixed)",
        content,
        re.IGNORECASE,
    )
    return m.group(1).lower() if m else "code"


def _read_deliverable_type_from_active_plan(project_root: Path) -> str:
    """Read deliverable_type from the active work_plan.md; default 'code'.

    Fail-safe to 'code' (the stricter path) if the plan is missing/unreadable:
    a code ticket requiring the canonical suite is the conservative default.
    """
    work_plan = project_root / ".agent" / "collaboration" / "work_plan.md"
    try:
        return _read_deliverable_type_from_content(
            work_plan.read_text(encoding="utf-8")
        )
    except OSError:
        return "code"


def _read_delivery_authority_from_active_plan(project_root: Path) -> str:
    """Read delivery_authority from the active work_plan.md; default 'repo_motor'.

    Fail-safe to 'repo_motor' (the legacy assumption) if the plan is missing or
    unreadable, preserving pre-existing behavior for single-repo deliveries.
    """
    work_plan = project_root / ".agent" / "collaboration" / "work_plan.md"
    try:
        return _read_delivery_authority_from_content(
            work_plan.read_text(encoding="utf-8")
        )
    except OSError:
        return "repo_motor"


# WOT-2026-010c: deliverable types that DO require a green canonical suite.
_SUITE_REQUIRED_TYPES = {"code", "mixed"}


def assert_canonical_suite_green(
    motor_root: Path,
    deliverable_type: str,
) -> tuple[bool, dict]:
    """Require a fresh green run_pytest_safe before handoff (WOT-2026-010c).

    Reads <motor>/.agent/runtime/pytest-safe/last-run.json (the canonical
    artifact written by run_pytest_safe.py) and requires:
        status == "finished" AND exit_code == 0 AND tested_commit_sha == HEAD.

    This closes the 010a gap: a focal-green close that left the canonical suite
    RED reached READY_FOR_REVIEW because "passed" was cited without "0 failed".

    Before: motor_root is the delivery repo (resolved by delivery_authority:
            the motor for motor-delivered tickets, the destination for
            repo_destino tickets); deliverable_type is the ticket type.
    During: for documentation/research/analysis -> auditable skip. Otherwise reads
            and validates the JSON; compares tested_commit_sha to the delivery
            repo HEAD.
    After: returns (ok, diag). On block, diag carries canonical_suite_required,
           reason, remediation, canonical_suite_error and last_run_json.
    """
    last_run = motor_root / ".agent" / "runtime" / "pytest-safe" / "last-run.json"

    # Auditable skip for non-code deliverables.
    if deliverable_type not in _SUITE_REQUIRED_TYPES:
        return True, {
            "canonical_suite_required": False,
            "reason": "deliverable_type_skip",
            "deliverable_type": deliverable_type,
        }

    base_diag = {
        "canonical_suite_required": True,
        "last_run_json": str(last_run),
        "remediation": (
            "Run the canonical suite from repo_motor and commit first: "
            "python scripts/run_pytest_safe.py  "
            "(read the tail and confirm '0 failed'); then retry --mark-ready. "
            "Log: .agent/runtime/pytest-safe/last-run.log"
        ),
    }

    if not last_run.exists():
        return False, {
            **base_diag,
            "reason": "last_run_missing",
            "canonical_suite_error": (
                "No last-run.json: run_pytest_safe has not run for this commit."
            ),
        }

    try:
        data = json.loads(last_run.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, {
            **base_diag,
            "reason": "last_run_unparseable",
            "canonical_suite_error": f"last-run.json not parseable: {exc}",
        }

    status = data.get("status")
    if status != "finished":
        return False, {
            **base_diag,
            "reason": f"status_not_finished ({status!r})",
            "canonical_suite_error": (
                f"run_pytest_safe did not finish (status={status!r}); "
                "the run crashed, was a dry-run, or is still in progress."
            ),
        }

    exit_code = data.get("exit_code")
    if exit_code != 0:
        # WOT-2026-017a (D3/D5): subset-of-baseline decision replaces binary block.
        # WOT-2026-017b (reopen): fail-closed when no node-ids were enumerated,
        # whether the field is absent (old runner) OR present-but-empty (the
        # suite failed without pytest reporting any individual FAILED test:
        # a collection crash, OOM/SIGKILL, or another state-leak that forces
        # exit_code != 0). `data.get(...) or []` normalizes both shapes to [],
        # so this single check subsumes the old "field absent" discriminant:
        # an opaque failure is an opaque failure regardless of which JSON shape
        # produced it, and treating them differently would let a real state-leak
        # masquerade as "no new failures" (a_set={} is always a subset of B).
        if not (data.get("failed_test_ids") or []):
            return False, {
                **base_diag,
                "reason": "nonzero_exit_but_no_failed_ids (state-leak suspected)",
                "canonical_suite_error": (
                    f"Canonical suite exit_code={exit_code!r} but "
                    "failed_test_ids is empty: the suite failed without "
                    "enumerating any test (collection crash, OOM/SIGKILL, or a "
                    "state-leak). This is an opaque failure, not an "
                    "inherited-subset pass. Investigate the run log "
                    "(.agent/runtime/pytest-safe/last-run.log), then re-run: "
                    "python scripts/run_pytest_safe.py --level all"
                ),
            }
        # D7: the baseline is only trustworthy if it was produced with
        # level=all + default_discovery; otherwise the comparison is meaningless.
        _level_base = data.get("level")
        _args_mode_base = data.get("args_mode")
        if _level_base != "all" or _args_mode_base != "default_discovery":
            return False, {
                **base_diag,
                "reason": (
                    f"not_full_suite (level={_level_base!r},"
                    f" args_mode={_args_mode_base!r})"
                ),
                "canonical_suite_error": (
                    f"last-run level={_level_base!r} args_mode={_args_mode_base!r}: "
                    "the baseline is only valid when produced with level=all + "
                    "default_discovery. "
                    "Run: python scripts/run_pytest_safe.py --level all"
                ),
            }
        # D1/D3: compare by exact node-id identity (not count).
        a_set = set(data.get("failed_test_ids") or [])
        b_set = set(data.get("baseline_failed_test_ids") or [])
        new_failures = a_set - b_set
        if new_failures:
            return False, {
                **base_diag,
                "reason": "regression_new_failures",
                "canonical_suite_error": (
                    f"Canonical suite exit_code={exit_code!r}: "
                    f"{len(new_failures)} new failure(s) not in baseline: "
                    + ", ".join(sorted(new_failures))
                ),
                "new_failures": sorted(new_failures),
            }
        # All failures are inherited (A subset of B). Verify SHA freshness
        # before accepting (the baseline must be against the commit being delivered).
        _inh_tested_sha = data.get("tested_commit_sha")
        _inh_head_ok, _inh_head_sha = resolve_git_head_sha_local(motor_root)
        if not _inh_head_ok:
            return False, {
                **base_diag,
                "reason": "motor_head_unresolved",
                "canonical_suite_error": _inh_head_sha,
            }
        if not _inh_tested_sha or _inh_tested_sha != _inh_head_sha:
            return False, {
                **base_diag,
                "reason": "stale_run (tested_commit_sha != delivery HEAD)",
                "canonical_suite_error": (
                    f"last-run tested {_inh_tested_sha!r} but delivery repo HEAD is "
                    f"{_inh_head_sha!r}: the suite did not run against the commit "
                    "being delivered."
                ),
            }
        return True, {
            "canonical_suite_required": True,
            "reason": "inherited_failures_subset",
            "inherited_test_ids": sorted(a_set),
            "baseline_run_sha": _inh_tested_sha,
            "level": _level_base,
            "args_mode": _args_mode_base,
            "exit_code": exit_code,
        }

    tested_sha = data.get("tested_commit_sha")
    head_ok, head_sha = resolve_git_head_sha_local(motor_root)
    if not head_ok:
        return False, {
            **base_diag,
            "reason": "motor_head_unresolved",
            "canonical_suite_error": head_sha,
        }
    if not tested_sha or tested_sha != head_sha:
        return False, {
            **base_diag,
            "reason": "stale_run (tested_commit_sha != delivery HEAD)",
            "canonical_suite_error": (
                f"last-run tested {tested_sha!r} but delivery repo HEAD is "
                f"{head_sha!r}: the suite did not run against the commit being "
                "delivered."
            ),
        }

    # WOT-2026-010q: require level=="all" so a focal run never satisfies handoff.
    level = data.get("level")
    if level != "all":
        return False, {
            **base_diag,
            "reason": f"not_full_suite (level={level!r})",
            "canonical_suite_error": (
                f"last-run level={level!r}: only level='all' counts as the "
                "canonical suite. Run: python scripts/run_pytest_safe.py --level all"
            ),
        }

    # WOT-2026-010q: require args_mode=="default_discovery" so an explicit-args
    # run (e.g. targeting a single test file) does not satisfy handoff either.
    args_mode = data.get("args_mode")
    if args_mode != "default_discovery":
        return False, {
            **base_diag,
            "reason": f"not_full_suite (args_mode={args_mode!r})",
            "canonical_suite_error": (
                f"last-run args_mode={args_mode!r}: canonical suite requires "
                "default_discovery (no explicit test paths). "
                "Run: python scripts/run_pytest_safe.py --level all"
            ),
        }

    return True, {
        "canonical_suite_required": True,
        "reason": "fresh_green",
        "tested_commit_sha": tested_sha,
        "level": level,
        "args_mode": args_mode,
        "exit_code": 0,
    }


def resolve_git_head_sha_local(repo: Path) -> tuple[bool, str]:
    """Return (True, sha) for repo HEAD, or (False, error) if git fails."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, f"git rev-parse HEAD failed in {repo}: {exc}"
    sha = proc.stdout.strip()
    if proc.returncode != 0 or not sha:
        return False, f"Unable to resolve HEAD in {repo}"
    return True, sha


def _relativize_to_any_root(abs_path: str, roots: list[Path]) -> str:
    """Return abs_path relative to the first matching root, else abs_path itself."""
    p = Path(abs_path)
    for root in roots:
        if root == p or root in p.parents:
            return str(p.relative_to(root))
    return abs_path


def check_forbidden_surfaces(
    *,
    changed_files: set[str],
    project_root: Path,
    motor_root: Path | None,
) -> list[str]:
    """Return changed files that hit a Forbidden Surface (WOT-2026-010i).

    Forbidden Surfaces declared in work_plan.md are an executable handoff
    contract: a diff that touches one of them must block handoff with a
    diagnostic that names the route, not merely fail a later audit.

    Before: changed_files are absolute path strings from the active git root;
        work_plan.md exists under project_root.
    During: parses ``## Forbidden Surfaces`` via scope_gate.parse_forbidden_surfaces
        against both project_root and motor_root (when distinct), so a forbidden
        path declared relative to either repo is matched.
    After: returns a sorted list of absolute path strings present in BOTH the
        diff and the forbidden set. Empty list means no violation.
    """
    work_plan = project_root / ".agent" / "collaboration" / "work_plan.md"
    if not work_plan.exists():
        return []
    try:
        content = work_plan.read_text(encoding="utf-8")
    except OSError:
        return []

    try:
        sg = _import_scope_gate()
    except ImportError:
        return []

    forbidden: set[str] = sg.parse_forbidden_surfaces(
        content, project_root=project_root
    )
    if motor_root is not None and motor_root.resolve() != project_root.resolve():
        forbidden |= sg.parse_forbidden_surfaces(content, project_root=motor_root)

    return sorted(changed_files & forbidden)


def assert_ticket_commit_visible(
    *,
    ticket_id: str,
    deliverable_type: str,
    motor_root: Path,
    n: int = 20,
    run_fn=subprocess.run,
) -> tuple[bool, dict]:
    """Require a repo_motor commit that names the ticket (WOT-2026-010i).

    A ``code``/``mixed`` review packet without a visible productive commit of
    the ticket reached Manager in WOT-2026-010e. This barrier blocks handoff
    unless one of the last ``n`` repo_motor commit messages contains the
    ticket_id. Documentation/research/analysis tickets are exempt: they may
    close on documental artifacts without a code commit.

    Before: motor_root is the delivery repo (must be git); ticket_id is the
        active ticket; deliverable_type drives whether the barrier applies.
    During: runs ``git log -n --format=%H%x00%s`` in motor_root and scans
        subjects for ticket_id.
    After: returns (ok, diag). On block, diag carries reason, remediation and
        the ticket_id. Fail-closed: a git failure for a code/mixed ticket blocks.
    """
    if deliverable_type not in _SUITE_REQUIRED_TYPES:
        return True, {
            "commit_visible_required": False,
            "reason": "deliverable_type_exempt",
            "deliverable_type": deliverable_type,
        }

    base_diag = {
        "commit_visible_required": True,
        "ticket_id": ticket_id,
        "remediation": (
            f"Commit the productive change in repo_motor with {ticket_id} in the "
            f"message before handoff, e.g. git commit -m '{ticket_id}: <change>'. "
            "If the delivery legitimately has no code commit, the ticket type "
            "should not be code/mixed."
        ),
    }

    try:
        result = run_fn(
            ["git", "log", f"-{n}", "--format=%H%x00%s"],
            capture_output=True,
            text=True,
            cwd=motor_root,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, {
            **base_diag,
            "reason": "git_log_failed",
            "commit_visible_error": (
                f"Could not read repo_motor git log ({exc}); blocking "
                "code/mixed handoff (fail-closed)."
            ),
        }

    if result.returncode != 0:
        return False, {
            **base_diag,
            "reason": "git_log_nonzero",
            "commit_visible_error": (
                f"git log returned {result.returncode} in {motor_root}; "
                "blocking code/mixed handoff (fail-closed)."
            ),
        }

    for line in result.stdout.split("\n"):
        if not line.strip():
            continue
        # Subject is everything after the NUL separator.
        subject = line.split("\0", 1)[-1]
        if ticket_id in subject:
            return True, {
                "commit_visible_required": True,
                "reason": "commit_visible",
                "ticket_id": ticket_id,
            }

    return False, {
        **base_diag,
        "reason": "no_visible_commit",
        "commit_visible_error": (
            f"No commit in the last {n} repo_motor commits names {ticket_id}: "
            "a code/mixed packet must carry a visible productive commit."
        ),
    }


def sg_fallback_parse(content: str, project_root: Path) -> set[str]:
    """Flat FLT parser fallback when scope_gate is not importable."""
    lines = content.split("\n")
    in_section = False
    files: set[str] = set()
    for line in lines:
        line_s = line.strip()
        if "## Files Likely Touched" in line_s:
            in_section = True
            continue
        if in_section and line_s.startswith("## "):
            break
        if in_section and line_s and not line_s.startswith("---"):
            normalized = (
                line_s.lstrip("*- ")
                .replace("`", "")
                .replace('"', "")
                .replace("'", "")
                .strip()
            )
            if normalized and "." in normalized.rsplit("/", 1)[-1]:
                files.add(str((project_root / normalized).resolve()))
    return files


def get_scope_discrepancy(
    changed_files: set[str], files_likely_touched: set[str], live_surfaces: set[str]
) -> set[str]:
    """Detectar archivos fuera de Files Likely Touched (excluyendo superficies vivas)."""
    relevant_changed = changed_files - live_surfaces
    discrepancy = relevant_changed - files_likely_touched
    return discrepancy


def run_guard(
    project_root: Path,
    ticket_id: str,
    motor_root: Path | None = None,
) -> dict:
    """
    Ejecutar el guard de handoff.

    Args:
        project_root: Destino root (workspace activo).
        ticket_id: Ticket ID.
        motor_root: Motor root para resolver rutas ``### repo_motor`` en FLT
            namespaced. Si None, scope_discrepancy solo cubre rutas de destino.

    Returns:
        dict con:
            - valid: bool (True si handoff permitido)
            - dirty_tree: bool (True si arbol sucio)
            - missing_checkpoint: bool (True si falta M3)
            - checkpoint_misaligned: bool (True si M3 existe pero no apunta a HEAD)
            - dirty_files: list[str] (archivos que ensucian el arbol)
            - scope_discrepancy: list[str] (archivos fuera de scope, no bloqueante)
            - checkpoint_tag: str | None (tag del checkpoint M3 si existe)
            - cross_root_contamination: list[str] (archivos productivos en repo
              contrario; bloquea si no vacio) [WOT-2026-009c]
            - excluded_operational: list[str] (archivos operativos en repo
              contrario; excluidos, informativo) [WOT-2026-009c]
    """
    result = {
        "valid": True,
        "dirty_tree": False,
        "missing_checkpoint": False,
        "checkpoint_misaligned": False,
        "uncommitted_work_plan": False,
        "work_plan_guard_error": None,
        "canonical_suite": None,
        "dirty_files": [],
        "scope_discrepancy": [],
        "checkpoint_tag": None,
        "ticket_id": ticket_id,
        "cross_root_contamination": [],
        "excluded_operational": [],
        "forbidden_surface_violation": [],
        "commit_visible": None,
    }

    # 1. Verificar checkpoint M3 alignment
    missing_checkpoint, checkpoint_misaligned = check_checkpoint_alignment(
        project_root, ticket_id
    )
    if missing_checkpoint:
        result["valid"] = False
        result["missing_checkpoint"] = True
    elif checkpoint_misaligned:
        result["valid"] = False
        result["checkpoint_misaligned"] = True
        result["checkpoint_tag"] = f"checkpoint/review-{ticket_id}"
    else:
        result["checkpoint_tag"] = f"checkpoint/review-{ticket_id}"

    # 2. WOT-2026-009g: work_plan.md must be committed at handoff time.
    # This is a separate rule from dirty_tree: work_plan.md is exempt from
    # generic dirty-tree detection (it is a live surface), but it MUST be
    # committed as the active ticket contract before --mark-ready proceeds.
    #
    # Fail-closed: this guard IS the barrier that closes the 008b false green.
    # If the helper cannot run (import drift, API change, bug), we must BLOCK
    # the handoff with a diagnostic, never silently pass. Silencing here would
    # reopen exactly the false green this ticket exists to close.
    try:
        mc = _import_motor_checkpoint()
        wp_ok, wp_diag = mc.assert_work_plan_committed(
            project_root=project_root,
            motor_root=motor_root if motor_root is not None else project_root,
        )
        if not wp_ok:
            result["valid"] = False
            result["uncommitted_work_plan"] = True
            result["work_plan_remediation"] = wp_diag.get("remediation", "")
    except Exception as exc:
        # Fail-closed: a broken guard must not become a silent pass.
        result["valid"] = False
        result["work_plan_guard_error"] = (
            f"{type(exc).__name__}: {exc}. "
            "Pre-handoff blocked because the work_plan commit guard could not "
            "run. Fix the guard or its import before retrying --mark-ready."
        )

    # 2.b WOT-2026-010c: the canonical suite must be fresh-green before handoff.
    # Separate, additional barrier (coexists with the M3 checkpoint and the
    # work_plan-committed guard; does NOT replace _check_log_has_quality_gate_
    # evidence in the controller). Reads run_pytest_safe's last-run.json and
    # requires status==finished + exit_code==0 + tested_commit_sha==delivery HEAD.
    # The delivery repo is resolved by delivery_authority (LEA topology fix):
    # a repo_destino code ticket keeps its suite + commit in the destination.
    # Fail-closed: any error blocks with a self-service diagnostic.
    _da = _read_delivery_authority_from_active_plan(project_root)
    _delivery_root = resolve_delivery_root(
        project_root=project_root, motor_root=motor_root, delivery_authority=_da
    )
    try:
        _dt = _read_deliverable_type_from_active_plan(project_root)
        _suite_ok, _suite_diag = assert_canonical_suite_green(_delivery_root, _dt)
        result["canonical_suite"] = _suite_diag
        if not _suite_ok:
            result["valid"] = False
    except Exception as exc:
        result["valid"] = False
        result["canonical_suite"] = {
            "canonical_suite_required": True,
            "reason": "guard_error",
            "canonical_suite_error": (
                f"{type(exc).__name__}: {exc}. Canonical-suite gate could not "
                "run; blocking handoff (fail-closed)."
            ),
        }

    # 2.c WOT-2026-010i: code/mixed packets must carry a visible productive
    # commit naming the ticket in the delivery repo. Doc-types are exempt.
    # The delivery repo is resolved by delivery_authority (LEA topology fix):
    # a repo_destino code ticket carries its commit in the destination, not the
    # motor. Fail-closed.
    try:
        _dt_cv = _read_deliverable_type_from_active_plan(project_root)
        _cv_ok, _cv_diag = assert_ticket_commit_visible(
            ticket_id=ticket_id,
            deliverable_type=_dt_cv,
            motor_root=_delivery_root,
        )
        result["commit_visible"] = _cv_diag
        if not _cv_ok:
            result["valid"] = False
    except Exception as exc:
        result["valid"] = False
        result["commit_visible"] = {
            "commit_visible_required": True,
            "reason": "guard_error",
            "commit_visible_error": (
                f"{type(exc).__name__}: {exc}. Commit-visible gate could not "
                "run; blocking handoff (fail-closed)."
            ),
        }

    # 3. Obtener superficies vivas (archivos y directorios)
    live_files, live_dirs = get_live_surfaces_absolute(project_root)

    # 3. Obtener archivos cambiados
    changed_files = get_changed_files(project_root)

    # 4. Filtrar archivos ignorados por gitignore
    non_ignored_changed = set()
    for f in changed_files:
        f_path = Path(f)
        if not is_ignored_by_gitignore(f_path, project_root):
            non_ignored_changed.add(f)

    # 5. Determinar dirty_files y scope_discrepancy
    # - dirty_files: cualquier archivo no vivo y no ignorado por gitignore.
    #   Si existe, el arbol esta sucio y el handoff debe bloquear.
    # - scope_discrepancy: subconjunto informativo de dirty_files que queda fuera
    #   de Files Likely Touched.
    #
    # Regla:
    # - Todo cambio no vivo ensucia el arbol.
    # - Los cambios fuera de scope se reportan adicionalmente como observacion.

    files_likely_touched = parse_files_likely_touched(
        project_root, motor_root=motor_root
    )

    dirty_files = set()
    scope_discrepancy = set()

    for f in non_ignored_changed:
        # Es superficie viva? → ignorar
        if f in live_files or is_in_live_surface_dir(f, live_dirs):
            continue

        # Es workspace excluded (PLAN_WP-*.md, AUDIT_WP-*.md)? → ignorar
        try:
            rel = str(Path(f).relative_to(project_root))
            if is_workspace_excluded(rel):
                continue
        except ValueError:
            pass

        dirty_files.add(f)

        # Fuera de scope: reportar como scope_discrepancy (observacion)
        if files_likely_touched and f not in files_likely_touched:
            scope_discrepancy.add(f)

    if dirty_files:
        result["valid"] = False
        result["dirty_tree"] = True
        result["dirty_files"] = sorted(
            str(Path(f).relative_to(project_root)) for f in dirty_files
        )

    # Reportar scope_discrepancy (no bloqueante)
    if scope_discrepancy:
        result["scope_discrepancy"] = sorted(
            str(Path(f).relative_to(project_root)) for f in scope_discrepancy
        )

    # 5.b WOT-2026-010i: a diff that touches a declared Forbidden Surface blocks
    # handoff with a diagnostic naming the route. Executable contract, not prose.
    forbidden_hits = check_forbidden_surfaces(
        changed_files=non_ignored_changed,
        project_root=project_root,
        motor_root=motor_root,
    )
    if forbidden_hits:
        result["valid"] = False
        roots = [project_root] + ([motor_root] if motor_root is not None else [])
        result["forbidden_surface_violation"] = sorted(
            _relativize_to_any_root(f, roots) for f in forbidden_hits
        )

    # 5.c WOT-2026-010u: an uncommitted archival rename (closed STRATEGY_/AUDIT_/
    # PLAN_ moved to _archive/plan_audit/ but never committed) blocks handoff early,
    # at the point that causes it, instead of surfacing as contaminacion_productiva
    # on the NEXT ticket. _archive/plan_audit/ is excluded from the dirty_tree check
    # above, so this dedicated barrier is what catches the limbo.
    try:
        from delivery_hygiene_check import check_archive_rename_complete

        _rename_result = check_archive_rename_complete(project_root)
        if not _rename_result.passed:
            result["valid"] = False
            result["archive_rename_uncommitted"] = _rename_result.details or [
                _rename_result.message
            ]
    except Exception as exc:
        result["valid"] = False
        result["archive_rename_guard_error"] = (
            f"check_archive_rename_complete no pudo ejecutarse: {exc}. "
            "Barrera fail-closed (WOT-2026-010u)."
        )

    # 6. WOT-2026-009c: reciprocal isolation guard — inspect non-authority root.
    # Bloquea si hay archivos productivos (no-operativos) en el repo contrario.
    if motor_root is not None and motor_root.resolve() != project_root.resolve():
        work_plan_path = project_root / ".agent" / "collaboration" / "work_plan.md"
        if work_plan_path.exists():
            try:
                plan_content = work_plan_path.read_text(encoding="utf-8")
            except OSError:
                plan_content = ""
            da = _read_delivery_authority_from_content(plan_content)
            try:
                sg = _import_scope_gate()
                if da == "repo_motor":
                    other_root = project_root.resolve()
                    collab = other_root / ".agent" / "collaboration"
                    agent_d = other_root / ".agent"
                    context_d = agent_d / "context"
                    other_exclude = sg.exclude_files(
                        collab_dir=collab,
                        agent_dir=agent_d,
                        context_dir=context_d,
                    )
                else:
                    other_root = motor_root.resolve()
                    collab = other_root / ".agent" / "collaboration"
                    agent_d = other_root / ".agent"
                    context_d = agent_d / "context"
                    other_exclude = sg.exclude_files(
                        collab_dir=collab,
                        agent_dir=agent_d,
                        context_dir=context_d,
                    )
                cross = sg.check_cross_root_contamination(
                    other_root=other_root,
                    other_exclude=other_exclude,
                )
                if cross["productive"]:
                    other_name = "repo_destino" if da == "repo_motor" else "repo_motor"
                    result["valid"] = False
                    result["cross_root_contamination"] = sorted(
                        f"contaminacion_productiva ({other_name}): {f}"
                        for f in cross["productive"]
                    )
                if cross["operational"]:
                    result["excluded_operational"] = sorted(cross["operational"])
            except (ImportError, Exception):  # noqa: S110
                pass

    return result


def main() -> int:
    """Punto de entrada principal."""
    import argparse

    parser = argparse.ArgumentParser(description="Pre-handoff guard")
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Project root directory",
    )
    parser.add_argument(
        "--ticket-id",
        type=str,
        required=True,
        help="Ticket ID (e.g., WOT-2026-010a)",
    )
    parser.add_argument(
        "--motor-root",
        type=str,
        default=None,
        help="Motor root directory (for FLT namespace resolution of repo_motor paths)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )

    args = parser.parse_args()

    project_root = get_project_root(args.project_root)
    ticket_id = args.ticket_id
    motor_root = Path(args.motor_root).resolve() if args.motor_root else None

    # Verificar que estamos en un repo git
    if not (project_root / ".git").exists():
        result = {
            "valid": True,
            "dirty_tree": False,
            "missing_checkpoint": False,
            "checkpoint_misaligned": False,
            "dirty_files": [],
            "scope_discrepancy": [],
            "checkpoint_tag": None,
            "ticket_id": ticket_id,
            "warnings": ["Repository is not git-managed"],
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("[WARN] Repository is not git-managed. Skipping guard checks.")
        return 0

    result = run_guard(project_root, ticket_id, motor_root=motor_root)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["valid"]:
            print(f"[OK] Handoff guard passed for {ticket_id}")
            if result["scope_discrepancy"]:
                print(
                    f"[WARN] Scope discrepancy (non-blocking): {', '.join(result['scope_discrepancy'])}"
                )
        else:
            print(f"[ERROR] Handoff guard failed for {ticket_id}")
            if result["missing_checkpoint"]:
                print(f"  - Missing checkpoint M3: checkpoint/review-{ticket_id}")
                print(
                    f"    Fix: git commit && git tag -a checkpoint/review-{ticket_id}"
                    f' -m "Checkpoint M3 for {ticket_id}"'
                )
            if result.get("checkpoint_misaligned"):
                print(
                    f"  - Checkpoint M3 misaligned: checkpoint/review-{ticket_id}"
                    f" does not point to HEAD"
                )
                print(
                    f"    Fix: git tag -d checkpoint/review-{ticket_id}"
                    f" && git tag -a checkpoint/review-{ticket_id}"
                    f' -m "Checkpoint M3 for {ticket_id}"'
                )
            if result.get("uncommitted_work_plan"):
                print(
                    "  - work_plan.md no está commiteado. "
                    "El contrato activo debe estar commiteado antes del handoff."
                )
                print(
                    f"    Fix: {result.get('work_plan_remediation', 'git add .agent/collaboration/work_plan.md && git commit')}"
                )
            if result.get("work_plan_guard_error"):
                print(
                    f"  - work_plan commit guard error: {result['work_plan_guard_error']}"
                )
            cv = result.get("commit_visible")
            if cv and cv.get("reason") not in (
                "commit_visible",
                "deliverable_type_exempt",
                None,
            ):
                print(
                    f"  - Commit not visible for {ticket_id}: "
                    f"{cv.get('commit_visible_error', cv.get('reason'))}"
                )
                print(f"    Fix: {cv.get('remediation', '')}")
            if result.get("forbidden_surface_violation"):
                print(
                    "  - Forbidden Surface violation: "
                    f"{', '.join(result['forbidden_surface_violation'])}"
                )
                print(
                    "    Fix: revert changes to the forbidden route(s) above, or "
                    "open a ticket whose Forbidden Surfaces do not list them."
                )
            if result.get("archive_rename_uncommitted"):
                print("  - Archive rename uncommitted (WOT-2026-010u):")
                for line in result["archive_rename_uncommitted"]:
                    print(f"      {line}")
            if result.get("archive_rename_guard_error"):
                print(
                    f"  - Archive rename guard error: {result['archive_rename_guard_error']}"
                )
            if result["dirty_tree"]:
                print(f"  - Dirty tree: {', '.join(result['dirty_files'])}")
            if result["scope_discrepancy"]:
                print(
                    f"  - Scope discrepancy (non-blocking): {', '.join(result['scope_discrepancy'])}"
                )

    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
