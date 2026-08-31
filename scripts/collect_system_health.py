#!/usr/bin/env python3
"""Collect deterministic system-health evidence (collector, NOT auditor).

Before:
    - A valid repo_motor path (must contain MANIFEST.distribute).
    - Optionally a repo_destino path with a .agent/ workspace.
    - Mode: full (requires both), motor-only, or auto (degrade with notice).

During:
    - Runs read-only deterministic checks (ruff on motor and destino, validate on
      both, discover-skills contract, motor-pristine snapshot, pytest-safe
      last-run inventory, git inventories). Captures raw stdout/exit per check
      under <out>/raw/. Builds a normalized findings.json with RELATIVIZED paths.
      Writes skeleton .md files with the fixed header block for the agent to fill
      (Pass B / judgment).
    - WOT-2026-024m: this list enumerates ONLY the checks the collector actually
      runs (see the ``checks[...]`` block below). Two checks that earlier
      versions of this docstring advertised are NOT run: there is no doc-encoding
      verification here, and MANIFEST.distribute is only checked for EXISTENCE as
      a motor-root precondition (line ~260), never compared against the tracked
      tree.
    - By default writes ONLY inside the output dir (self-contained evidence);
      it does not touch any tracked file. The append-only INDEX.md register is
      opt-in via --publish-index (OFF by default): a pure collector never
      mutates a tracked file (WOT-2026-023x). Never archives or deletes. Never
      emits a verdict: the agent is the auditor.
    - Residual (out of scope for 023x, tracked by WOT-2026-021f): in the
      dogfooding workspace, .agent/audits/system_health/ is NOT gitignored, so
      the output dir itself appears as untracked. That is a policy decision
      (version the audits or not) reserved to the user, NOT a collector defect.

After:
    - Output dir is immutable (refuses to overwrite; appends _NN if needed).
    - Exit codes:
        0 = collection OK, no automatic criticals.
        1 = collection OK, automatic criticals (red suite, secret, DECIDE pending).
        2 = execution/collection error.
        3 = incomplete/degraded topology when --mode full was required.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "system-health-collector/v0"


def _run(cmd: list[str], cwd: Path, timeout: int = 600) -> dict:
    """Run a command read-only, capturing stdout/stderr/exit. Never raises."""
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "ok": proc.returncode == 0,
        }
    except FileNotFoundError as exc:
        return {
            "cmd": cmd,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "ok": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "exit_code": None,
            "stdout": "",
            "stderr": f"timeout: {exc}",
            "ok": False,
        }
    except OSError as exc:
        return {
            "cmd": cmd,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "ok": False,
        }


def _git_head(repo: Path) -> str | None:
    res = _run(["git", "rev-parse", "HEAD"], repo)
    if res["exit_code"] == 0:
        return res["stdout"].strip()
    return None


def _git_tracked(repo: Path) -> list[str]:
    res = _run(["git", "ls-files"], repo)
    if res["exit_code"] == 0:
        return [ln for ln in res["stdout"].splitlines() if ln]
    return []


def _relativize(text: str, roots: dict[str, Path]) -> str:
    """Replace absolute personal roots with stable placeholders."""
    if not text:
        return text
    out = text
    for label, root in roots.items():
        if root is None:
            continue
        root_text = str(root)
        for variant in {
            root_text,
            root_text.replace("\\", "/"),
            root_text.replace("/", "\\"),
        }:
            out = out.replace(variant, f"<{label}>")
    return out


def _unique_out_dir(base: Path) -> Path:
    """Return an immutable output dir; never overwrite an existing one."""
    if not base.exists():
        return base
    for n in range(1, 100):
        cand = base.parent / f"{base.name}_{n:02d}"
        if not cand.exists():
            return cand
    raise RuntimeError(f"too many existing audit dirs for {base}")


def _read_delivery_authority(root: Path) -> str:
    """Read delivery_authority from a repo's active work_plan (repo_motor default).

    WOT-2026-021n: mirror of pre_handoff_guard._read_delivery_authority_from_content
    (same regex) so the HEAD we compare tested_commit_sha against uses the SAME axis
    that run_pytest_safe used to STAMP it. Returns "repo_destino" only when the field
    says so; "repo_motor" otherwise (missing/unreadable work_plan -> default).
    """
    wp = root / ".agent" / "collaboration" / "work_plan.md"
    try:
        content = wp.read_text(encoding="utf-8")
    except OSError:
        return "repo_motor"
    if re.search(
        r"delivery_authority\s*:?\**\s*(?:repo_destino|destino)",
        content,
        re.IGNORECASE,
    ):
        return "repo_destino"
    return "repo_motor"


def _read_pytest_last_run(motor_root: Path) -> dict:
    """Read the canonical runner's last-run.json (real exit, not pipe).

    WOT-2026-021m: also surfaces failed_test_ids/error_test_ids/state_leak so the
    caller can tell a REAL test failure from an exit-1 caused ONLY by the state-leak
    of gitignored projections (AUDIT_*/STRATEGY_*). The producer (run_pytest_safe.py)
    writes state_leak ONLY when non-empty, so it is either a non-empty list or ABSENT
    -- never []. failed/error_test_ids may be absent on started/dry-run records, hence
    the .get(..., []) defaults.
    """
    p = motor_root / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
    if not p.exists():
        return {"present": False, "exit_code": None}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return {
            "present": True,
            "exit_code": d.get("exit_code"),
            "finished_at": d.get("finished_at"),
            "failed_test_ids": d.get("failed_test_ids", []),
            "error_test_ids": d.get("error_test_ids", []),
            "state_leak": d.get("state_leak"),
            # WOT-2026-021n: surface the commit the last run tested so the caller can
            # flag a STALE witness (last-run of an old HEAD). May be absent on
            # started/dry-run records or old fixtures -> None (no spurious stale).
            "tested_commit_sha": d.get("tested_commit_sha"),
        }
    except (OSError, json.JSONDecodeError) as exc:
        return {"present": False, "exit_code": None, "error": str(exc)}


def _last_run_is_caducated(lr: dict, session_start: datetime) -> bool:
    """WOT-2026-022l: True if this last-run FINISHED BEFORE the session started.

    A last-run whose ``finished_at`` predates ``session_start`` is pre-session
    evidence: it describes a state from before this audit/close, so an
    unexplained nonzero exit from it is caducated, not a fresh red suite.

    Fail-safe to NOT caducated (returns False) when finished_at is absent or
    unparseable: without a timestamp we cannot prove the evidence is old, so we
    keep the stricter verdict (never silence a red we cannot date).
    """
    finished_at_raw = lr.get("finished_at")
    if not finished_at_raw:
        return False
    try:
        finished_at = datetime.fromisoformat(str(finished_at_raw))
    except (ValueError, TypeError):
        return False
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    return finished_at < session_start


HEADER_TEMPLATE = """# {title}

## Bloque de cabecera

- **Scope:** {scope}
- **Repo motor (HEAD):** {motor_root} @ {motor_head}
- **Repo destino (HEAD):** {dest_root} @ {dest_head}
- **Fecha:** {date}
- **Modo:** {mode}
- **Comandos ejecutados:** ver findings.json y raw/
- **Cobertura declarada:** {coverage}
- **Limitaciones:** recoleccion determinista (Pasada A). El juicio adversarial
  (Pasada B) lo completa el agente. Este archivo es un esqueleto.

---

> Esqueleto generado por collect_system_health.py ({schema}). El agente debe
> rellenar los hallazgos aplicando prompts/audit_post_change_system_health.md.
"""

SKELETON_FILES = {
    "00_scope.md": ("00 - Scope y topologia", "topologia y baseline del sistema"),
    "01_motor_audit.md": ("01 - Auditoria del repo_motor", "salud del motor"),
    "02_workspace_audit.md": ("02 - Auditoria del repo_destino", "salud del destino"),
    "03_integration_audit.md": ("03 - Auditoria de integracion", "motor+destino"),
    "04_quality_gates.md": ("04 - Quality gates", "ruff/pytest-safe last-run/validate"),
    "05_archive_plan.md": ("05 - Archive plan", "KEEP/ARCHIVE/DELETE por ruta"),
    "06_tickets.md": ("06 - Tickets propuestos", "un ticket por familia"),
    "07_adversarial_review.md": (
        "07 - Pasada adversarial",
        "claims VERIFICADO/INFERIDO/NO VERIFICADO",
    ),
    "auditoria_general_resumen.md": ("Resumen general", "veredicto humano/agente"),
}


def _parse_guard_wiring(run_result: dict) -> dict:
    """Parse check_guard_wiring output into a debt inventory + a fail-closed verdict.

    WOT-2026-024v. Before: ``run_result`` is a ``_run`` dict from invoking
    ``scripts/check_guard_wiring.py`` WITHOUT ``--strict`` (--strict overloads rc=1,
    conflating EXPECTED declared debt with a real regression -> false-green).
    During: parse the ``    <guard>  -> <owner>`` owner block and classify by OUTPUT
    CONTENT, not exit-code band. After: returns ``{status, entries, exit_code, count}``
    with ``status`` one of:
        - ``ok``: rc==0 AND an owner block parsed (baseline holds; the declared debt
          is INVENTORIED, not alarmed);
        - ``fail_regression``: rc==1 (a guard de-wired/undeclared/stale -- the
          structural regression this collector must surface);
        - ``fail_unparseable``: rc==0 but no owner block (unexpected output);
        - ``fail_error``: rc is None (spawn/timeout via _run) or any other code
          (e.g. 2 = argparse / can't-open-file -> guard missing). Fail-closed:
          a broken/missing guard is NEVER silently swallowed.
    """
    rc = run_result.get("exit_code")
    stdout = run_result.get("stdout") or ""
    entries: list[dict] = []
    for line in stdout.splitlines():
        match = re.match(r"^\s+(\S+)\s+->\s+(.+)$", line)
        if match:
            entries.append({"guard": match.group(1), "owner": match.group(2).strip()})
    if rc == 0 and entries:
        status = "ok"
    elif rc == 0:
        status = "fail_unparseable"
    elif rc == 1:
        status = "fail_regression"
    else:
        status = "fail_error"
    return {
        "status": status,
        "entries": entries,
        "exit_code": rc,
        "count": len(entries),
    }


def main(argv: list[str] | None = None) -> int:  # noqa: C901 - CLI orchestration of read-only checks
    parser = argparse.ArgumentParser(
        description="Collect system-health evidence (collector, not auditor)."
    )
    parser.add_argument(
        "--motor-root",
        required=True,
        help="repo_motor path (must contain MANIFEST.distribute)",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="repo_destino path (workspace with .agent/)",
    )
    parser.add_argument(
        "--mode", choices=["full", "motor-only", "auto"], default="auto"
    )
    parser.add_argument(
        "--out", default=None, help="explicit output dir (overrides destino default)"
    )
    parser.add_argument(
        "--publish-index",
        action="store_true",
        help=(
            "append a row to the shared INDEX.md register next to the output dir. "
            "OFF by default: a pure collector never mutates a tracked file "
            "(WOT-2026-023x). The INDEX.md lives at <out_dir>.parent/INDEX.md, "
            "which is a TRACKED file in the dogfooding workspace."
        ),
    )
    parser.add_argument(
        "--session-start",
        default=None,
        help=(
            "WOT-2026-020i/022l: ISO-8601 timestamp of the session/close start. A "
            "destino last-run whose finished_at PREDATES this is EVIDENCE STALE: a "
            "nonzero exit from it degrades to WARN (caducated evidence), never a "
            "critical. Default: the collector's own start time."
        ),
    )
    # NOTE: --apply-fixes is intentionally NOT implemented in v0. The collector is
    # strictly read-only. A future v1 may add it for small doc/CLI drift fixes only.
    args = parser.parse_args(argv)

    # WOT-2026-022l: resolve the session-start cutoff. A last-run finished BEFORE
    # this instant is pre-session evidence: its nonzero exit is caducated, not a
    # fresh red suite. Default to now() so a run without the flag treats every
    # last-run finished before the collector started as stale evidence.
    _collector_started = datetime.now(timezone.utc)
    session_start: datetime | None = None
    if args.session_start:
        try:
            session_start = datetime.fromisoformat(args.session_start)
            if session_start.tzinfo is None:
                session_start = session_start.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            print(
                f"[collect] WARNING: --session-start not ISO-8601, ignoring: "
                f"{args.session_start}",
                file=sys.stderr,
            )
            session_start = None
    if session_start is None:
        session_start = _collector_started

    motor_root = Path(args.motor_root).resolve()
    if not (motor_root / "MANIFEST.distribute").exists():
        print(
            f"[collect] ERROR: motor-root has no MANIFEST.distribute: {motor_root}",
            file=sys.stderr,
        )
        return 2

    dest_root = Path(args.project_root).resolve() if args.project_root else None
    dest_ok = bool(dest_root and (dest_root / ".agent").exists())

    # Resolve effective mode / degradation.
    mode = args.mode
    degraded = False
    if mode == "full" and not dest_ok:
        print(
            "[collect] ERROR: --mode full requires a valid repo_destino with .agent/",
            file=sys.stderr,
        )
        return 3
    if mode == "auto" and not dest_ok:
        degraded = True
        mode = "motor-only"
        print(
            "[collect] NOTICE: no valid repo_destino; degrading to motor-only.",
            file=sys.stderr,
        )

    roots = {"MOTOR_ROOT": motor_root, "DESTINO_ROOT": dest_root}

    # Resolve output dir (motor executes; destino conserves).
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    if args.out:
        base_out = Path(args.out).resolve()
    elif dest_ok:
        base_out = (
            dest_root / ".agent" / "audits" / "system_health" / f"general_audit_{stamp}"
        )
    else:
        base_out = (
            motor_root / ".agent" / "runtime" / "audit" / f"general_audit_{stamp}"
        )
    try:
        out_dir = _unique_out_dir(base_out)
        (out_dir / "raw").mkdir(parents=True, exist_ok=False)
        # raw/ may leak personal paths/PII; keep it out of git by default
        # (v1 will sanitize it; until then it must not be versioned).
        (out_dir / ".gitignore").write_text("raw/\n", encoding="utf-8")
    except (OSError, RuntimeError) as exc:
        print(f"[collect] ERROR: cannot create output dir: {exc}", file=sys.stderr)
        return 2

    motor_head = _git_head(motor_root)
    dest_head = _git_head(dest_root) if dest_ok else None

    # ---- Deterministic checks (read-only) ----
    checks: dict[str, dict] = {}
    checks["ruff_motor"] = _run(["ruff", "check", "--no-fix", "."], motor_root)
    checks["validate_motor"] = _run(
        [
            sys.executable,
            ".agent/agent_controller.py",
            "--validate",
            "--json",
            "--force",
            # WOT-2026-024a: this collector is READ-ONLY (AGENTS.md); --no-heal
            # stops --validate from healing bus drift into the tracked STATE.md.
            "--no-heal",
        ],
        motor_root,
    )
    checks["discover_skills_contract"] = _run(
        [sys.executable, "scripts/discover_skills.py", "--check-contract"], motor_root
    )
    # WOT-2026-024v: inventory guard-wiring debt (read-only). NO --strict: --strict
    # OVERLOADS rc=1, conflating EXPECTED declared debt with a real regression, which
    # would let a de-wired guard slip through as "expected" (false-green). Without
    # --strict, rc==0=baseline-ok (+ owner block) and rc==1=structural regression.
    checks["guard_wiring"] = _run(
        [
            sys.executable,
            "scripts/check_guard_wiring.py",
            "--motor-root",
            str(motor_root),
        ],
        motor_root,
    )
    pristine_snap = out_dir / "raw" / "motor_snapshot.json"
    checks["motor_pristine_snapshot"] = _run(
        [
            sys.executable,
            "scripts/check_motor_pristine.py",
            "--snapshot",
            "--motor-root",
            ".",
            "--out",
            str(pristine_snap),
        ],
        motor_root,
    )
    # WOT-2026-022v: READ BOTH last-runs. The collector audits TWO repos, and every
    # version until now read ONE and discarded the other in silence:
    #
    #   - the original keyed the file on `dest_ok`, so whenever a destino was passed the
    #     MOTOR's last-run was never consulted: a RED motor was invisible;
    #   - keying it on `delivery_authority` (the first attempt at this ticket) inverted
    #     the blindness: 12 of the 13 real destinos do not DECLARE the field, so they
    #     defaulted to repo_motor and their OWN last-run was discarded -- a destino with
    #     a genuinely red suite reported rc=0, criticals=[]. Strictly worse: a false-RED
    #     is noisy, a false-GREEN is silent. An adversarial audit killed it before push.
    #
    # The invariant, from the module's own philosophy ("the collector collects, the agent
    # is the auditor"): DELIVERY_AUTHORITY DECIDES SEVERITY, NOT VISIBILITY.
    #
    #   delivery repo   red -> CRITICAL   missing -> CRITICAL (cannot confirm the delivery)
    #   the other repo  red -> WARNING    missing -> WARNING   (visible; never silent)
    #
    # So a destino's red suite is ALWAYS surfaced, the dogfooding workspace's fossil
    # last-run stops false-REDding a motor close, and 021c is preserved (a repo_destino
    # ticket still gets its critical from the DESTINO's own suite).
    delivery_authority = (
        _read_delivery_authority(dest_root) if dest_ok else "repo_motor"
    )
    delivery_is_dest = dest_ok and delivery_authority == "repo_destino"

    motor_last = _read_pytest_last_run(motor_root)
    motor_last["source"] = "motor"
    dest_last = _read_pytest_last_run(dest_root) if dest_ok else None
    if dest_last is not None:
        dest_last["source"] = "destino"

    # The record of the repo the ticket is DELIVERED from. Kept under the original key so
    # existing consumers of findings.json keep working.
    pytest_last = dest_last if delivery_is_dest else motor_last

    # WOT-2026-021n: flag a STALE last-run (tested a different commit than the current
    # delivery HEAD). The HEAD to compare against is resolved by delivery_authority, NOT
    # by the last-run file location. run_pytest_safe stamps tested_commit_sha with the
    # HEAD of _delivery_repo_root(), which is the destino only when delivery_authority ==
    # repo_destino, else the motor -- so BOTH records are stamped against the same HEAD
    # and both compare against it. `stale` is orthogonal to the verdict: it never
    # silences a red and never downgrades one. It only says "this witness is not fresh".
    delivery_head = dest_head if delivery_is_dest else motor_head
    for _lr in (motor_last, dest_last):
        if _lr is None:
            continue
        _tested = _lr.get("tested_commit_sha")
        # Truthiness (never `is not None`): None/"" tested_sha or head collapse to
        # not-stale. bool() forces a genuine bool (a falsy term would otherwise leak
        # through the `and`).
        _lr["stale"] = bool(
            _lr.get("present")
            and _tested
            and delivery_head
            and _tested != delivery_head
        )

    if dest_ok:
        checks["ruff_destino"] = _run(["ruff", "check", "--no-fix", "."], dest_root)
        checks["validate_destino"] = _run(
            [
                sys.executable,
                str(motor_root / ".agent" / "agent_controller.py"),
                "--validate",
                "--json",
                "--force",
                # WOT-2026-024a: read-only collector -> never heal the destino's
                # tracked STATE.md.
                "--no-heal",
                "--project-root",
                str(dest_root),
            ],
            motor_root,
        )

    # ---- Inventories ----
    motor_tracked = _git_tracked(motor_root)
    dest_tracked = _git_tracked(dest_root) if dest_ok else []

    # ---- Automatic critical detection (no judgment, only flags) ----
    criticals: list[str] = []
    warnings: list[str] = []

    def _flag_last_run(lr: dict, *, is_delivery: bool) -> dict:
        """Classify ONE repo's last-run and return its STRUCTURED verdict.

        Severity comes from delivery_authority; VISIBILITY never does -- the
        non-delivery repo is warned about, never silenced.

        The findings are ALSO returned as a block rather than only appended to the flat
        lists. A warning appended to `automatic_warnings` is easy to bury in a list that
        already holds stale/lint noise; the caller publishes these blocks as
        `authoritative_health` / `non_authoritative_health` so a red non-delivery repo is
        a first-class fact with its own `verdict`, not a string someone has to grep for.

        The delivery repo keeps the original finding names, so existing consumers of
        findings.json are untouched; the other repo gets the same names suffixed with
        its repo, which is new information rather than changed information.
        """
        sev = criticals if is_delivery else warnings
        tag = "" if is_delivery else f"_{lr['source']}"
        mine: list[str] = []

        def _emit(target: list[str], name: str) -> None:
            target.append(f"{name}{tag}")
            mine.append(f"{name}{tag}")

        verdict = "green"

        if lr.get("present") is False:
            # Cannot confirm green. For the delivery repo that is a blocker; for the
            # other one it is a fact the auditor should see, not a gate.
            _emit(sev, "pytest_safe_last_run_missing")
            verdict = "unknown"
        else:
            if lr.get("exit_code") not in (0, None):
                # WOT-2026-021m: classify a nonzero exit by its CAUSE. Branch order
                # matters: a real test failure (failed/error ids) wins over a state-leak,
                # and an unexplained nonzero exit stays at the repo's severity (fail-safe,
                # never silenced). Truthiness (never `!= []`): state_leak is a non-empty
                # list or absent/None.
                if lr.get("failed_test_ids") or lr.get("error_test_ids"):
                    _emit(sev, "pytest_safe_last_run_nonzero")
                    verdict = "red"
                elif lr.get("state_leak"):
                    # exit-1 caused ONLY by the state-leak of gitignored projections
                    # (AUDIT_*/STRATEGY_* that the suite legitimately mutates) -> WARN,
                    # not a real red suite. The leak is surfaced, just not a critical.
                    _emit(warnings, "pytest_safe_last_run_stateleak_only")
                    verdict = "stateleak"
                elif _last_run_is_caducated(lr, session_start):
                    # WOT-2026-022l, decision (b): an UNEXPLAINED nonzero from a
                    # last-run that FINISHED BEFORE the session started is caducated
                    # evidence, not a fresh red suite. In a code-only close the
                    # dogfooding workspace keeps an old exit-5 (no-tests-collected)
                    # last-run that would false-critical EVERY close. Degrade to
                    # WARN with the CAUSE spelled out: WARN por evidencia caducada,
                    # NO por suite verde. A recent unexplained nonzero stays a
                    # critical (never option (a): that would silence a real red).
                    _emit(warnings, "pytest_safe_last_run_stale_nonzero")
                    verdict = "stale"
                else:
                    # nonzero, no failed/error ids, no state_leak, RECENT -> unexplained.
                    _emit(sev, "pytest_safe_last_run_nonzero")
                    verdict = "red"

            # WOT-2026-021n: stale is ALWAYS a warning, for either repo. It never
            # silences a red and never downgrades one -- a stale red stays red AND stale.
            if lr.get("stale"):
                _emit(warnings, "pytest_safe_last_run_stale")

        return {
            "repo": lr["source"],
            "is_delivery": is_delivery,
            "verdict": verdict,  # green | red | stateleak | unknown
            "blocking": is_delivery and verdict in ("red", "unknown"),
            "stale": bool(lr.get("stale")),
            "exit_code": lr.get("exit_code"),
            "findings": mine,
            "last_run": lr,
        }

    motor_health = _flag_last_run(motor_last, is_delivery=not delivery_is_dest)
    dest_health = (
        _flag_last_run(dest_last, is_delivery=delivery_is_dest)
        if dest_last is not None
        else None
    )
    authoritative = motor_health if not delivery_is_dest else dest_health
    non_authoritative = dest_health if not delivery_is_dest else motor_health

    if checks.get("validate_motor", {}).get("exit_code") not in (0, None):
        criticals.append("validate_motor_nonzero")

    # ---- Write raw evidence ----
    for name, res in checks.items():
        raw = (
            f"$ {' '.join(res['cmd'])}\n"
            f"exit_code={res['exit_code']} ok={res['ok']}\n"
            f"--- stdout ---\n{res['stdout']}\n--- stderr ---\n{res['stderr']}\n"
        )
        (out_dir / "raw" / f"{name}.txt").write_text(
            _relativize(raw, roots), encoding="utf-8"
        )
    (out_dir / "raw" / "tracked_files_motor.txt").write_text(
        "\n".join(motor_tracked), encoding="utf-8"
    )
    if dest_ok:
        (out_dir / "raw" / "tracked_files_destino.txt").write_text(
            "\n".join(dest_tracked), encoding="utf-8"
        )

    # WOT-2026-024v: inventory the declared guard-wiring debt (read-only) and
    # fail-closed if the guard is missing/broken or reports a structural regression.
    # The auditor (Bloque 1) JUDGES this section; the collector only collects.
    guard_wiring = _parse_guard_wiring(checks.get("guard_wiring", {}))
    if guard_wiring["status"] != "ok":
        criticals.append(f"guard_wiring_{guard_wiring['status']}")

    # ---- findings.json (normalized, relativized) ----
    findings = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "degraded": degraded,
        "topology": {
            "motor_root": "<MOTOR_ROOT>",
            "destino_root": "<DESTINO_ROOT>" if dest_ok else None,
            "motor_head": motor_head,
            "destino_head": dest_head,
            "destino_present": dest_ok,
        },
        "checks": {
            k: {"exit_code": v["exit_code"], "ok": v["ok"]} for k, v in checks.items()
        },
        # The DELIVERY repo's record, under the original key (consumers unchanged).
        "pytest_safe_last_run": pytest_last,
        # WOT-2026-022v: both repos are reported as STRUCTURED blocks, so the one that is
        # not delivering cannot be buried in a flat warnings list. `non_authoritative_health`
        # carries its own `verdict` (green/red/stateleak/unknown): a red destino during a
        # motor ticket is a first-class fact that does not block, not a string to grep for.
        # `delivery_authority` is surfaced because it decides severity and used to be invisible.
        "authoritative_health": authoritative,
        "non_authoritative_health": non_authoritative,
        "delivery_authority": delivery_authority,
        "inventory": {
            "motor_tracked_count": len(motor_tracked),
            "destino_tracked_count": len(dest_tracked),
        },
        "guard_wiring_debt": guard_wiring,
        "automatic_criticals": criticals,
        "automatic_warnings": warnings,
        "note": "Collector output is [RELATO]; the agent produces the verdict (Pass B).",
    }
    (out_dir / "findings.json").write_text(
        _relativize(json.dumps(findings, indent=2, ensure_ascii=False), roots),
        encoding="utf-8",
    )

    # ---- Skeleton markdown files ----
    coverage = (
        "Pasada A determinista. pytest-safe via last-run.json (exit real, no pipe). "
        "Si la suite es allowlist parcial, NO es verde global."
    )
    for fname, (title, scope) in SKELETON_FILES.items():
        body = HEADER_TEMPLATE.format(
            title=title,
            scope=scope,
            motor_root="<MOTOR_ROOT>",
            motor_head=motor_head,
            dest_root="<DESTINO_ROOT>" if dest_ok else "n/a",
            dest_head=dest_head or "n/a",
            date=stamp,
            mode=mode,
            coverage=coverage,
            schema=SCHEMA_VERSION,
        )
        (out_dir / fname).write_text(body, encoding="utf-8")

    # ---- INDEX.md (append-only register) -- opt-in only (WOT-2026-023x) ----
    # The register lives at out_dir.parent/INDEX.md, a TRACKED file in the
    # dogfooding workspace. Writing it by default made this "read-only collector"
    # mutate the working tree on every run (AGENTS.md calls it a "read-only
    # collector"; the sibling batch audit hit this B3 violation live). It is now
    # gated behind --publish-index so the default invocation touches no tracked file.
    if args.publish_index:
        index = out_dir.parent / "INDEX.md"
        if not index.exists():
            index.write_text(
                "# System Health Audits - INDEX\n\n"
                "| Fecha | Motor HEAD | Destino HEAD | Criticos auto | Ruta |\n"
                "|-------|-----------|--------------|---------------|------|\n",
                encoding="utf-8",
            )
        row = (
            f"| {stamp} | {(motor_head or 'n/a')[:7]} | {(dest_head or 'n/a')[:7]} "
            f"| {len(criticals)} | {out_dir.name} |\n"
        )
        with index.open("a", encoding="utf-8") as fh:
            fh.write(row)

    print(f"[collect] OK -> {out_dir}")
    print(
        f"[collect] mode={mode} degraded={degraded} "
        f"automatic_criticals={criticals} automatic_warnings={warnings}"
    )
    # WOT-2026-022v: say the non-delivery repo's verdict OUT LOUD. It does not block, and
    # that is exactly why it needs a line of its own -- a non-blocking fact buried in a
    # warnings list is how a red destino stays invisible in practice.
    if non_authoritative and non_authoritative["verdict"] != "green":
        print(
            f"[collect] OJO: el repo que NO entrega ({non_authoritative['repo']}) esta en "
            f"'{non_authoritative['verdict']}' (exit_code={non_authoritative['exit_code']}, "
            f"stale={non_authoritative['stale']}). No bloquea este ticket, pero NO esta verde."
        )
    return 1 if criticals else 0


if __name__ == "__main__":
    sys.exit(main())
