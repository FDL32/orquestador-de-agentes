#!/usr/bin/env python3
"""Collect deterministic system-health evidence (collector, NOT auditor).

Before:
    - A valid repo_motor path (must contain MANIFEST.distribute).
    - Optionally a repo_destino path with a .agent/ workspace.
    - Mode: full (requires both), motor-only, or auto (degrade with notice).

During:
    - Runs read-only deterministic checks (ruff, pytest-safe last-run, validate,
      encoding guard, motor-pristine snapshot, git inventories, manifest-vs-tracked
      diff). Captures raw stdout/exit per check under <out>/raw/. Builds a
      normalized findings.json with RELATIVIZED paths. Writes skeleton .md files
      with the fixed header block for the agent to fill (Pass B / judgment).
    - Never mutates the working tree. Never archives or deletes. Never emits a
      verdict: the agent is the auditor.

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
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "ok": True,
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


def _read_pytest_last_run(motor_root: Path) -> dict:
    """Read the canonical runner's last-run.json exit_code (real exit, not pipe)."""
    p = motor_root / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
    if not p.exists():
        return {"present": False, "exit_code": None}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return {
            "present": True,
            "exit_code": d.get("exit_code"),
            "finished_at": d.get("finished_at"),
        }
    except (OSError, json.JSONDecodeError) as exc:
        return {"present": False, "exit_code": None, "error": str(exc)}


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
> rellenar los hallazgos aplicando prompts/system_health_audit.md.
"""

SKELETON_FILES = {
    "00_scope.md": ("00 - Scope y topologia", "topologia y baseline del sistema"),
    "01_motor_audit.md": ("01 - Auditoria del repo_motor", "salud del motor"),
    "02_workspace_audit.md": ("02 - Auditoria del repo_destino", "salud del destino"),
    "03_integration_audit.md": ("03 - Auditoria de integracion", "motor+destino"),
    "04_quality_gates.md": ("04 - Quality gates", "ruff/pytest-safe/encoding/validate"),
    "05_archive_plan.md": ("05 - Archive plan", "KEEP/ARCHIVE/DELETE por ruta"),
    "06_tickets.md": ("06 - Tickets propuestos", "un ticket por familia"),
    "07_adversarial_review.md": (
        "07 - Pasada adversarial",
        "claims VERIFICADO/INFERIDO/NO VERIFICADO",
    ),
    "auditoria_general_resumen.md": ("Resumen general", "veredicto humano/agente"),
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
    # NOTE: --apply-fixes is intentionally NOT implemented in v0. The collector is
    # strictly read-only. A future v1 may add it for small doc/CLI drift fixes only.
    args = parser.parse_args(argv)

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
    checks["ruff_motor"] = _run(["ruff", "check", "."], motor_root)
    checks["validate_motor"] = _run(
        [
            sys.executable,
            ".agent/agent_controller.py",
            "--validate",
            "--json",
            "--force",
        ],
        motor_root,
    )
    checks["discover_skills_contract"] = _run(
        [sys.executable, "scripts/discover_skills.py", "--check-contract"], motor_root
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
    pytest_last = _read_pytest_last_run(motor_root)

    if dest_ok:
        checks["ruff_destino"] = _run(["ruff", "check", "."], dest_root)
        checks["validate_destino"] = _run(
            [
                sys.executable,
                str(motor_root / ".agent" / "agent_controller.py"),
                "--validate",
                "--json",
                "--force",
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
    if pytest_last.get("present") and pytest_last.get("exit_code") not in (0, None):
        criticals.append("pytest_safe_last_run_nonzero")
    if pytest_last.get("present") is False:
        criticals.append("pytest_safe_last_run_missing")  # cannot confirm green
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
        "pytest_safe_last_run": pytest_last,
        "inventory": {
            "motor_tracked_count": len(motor_tracked),
            "destino_tracked_count": len(dest_tracked),
        },
        "automatic_criticals": criticals,
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

    # ---- INDEX.md (append-only register) ----
    if dest_ok or args.out:
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
    print(f"[collect] mode={mode} degraded={degraded} automatic_criticals={criticals}")
    return 1 if criticals else 0


if __name__ == "__main__":
    sys.exit(main())
