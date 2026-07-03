"""Per-row publication gate for backing repos up to a remote (WOT-2026-016m).

Before:
    A repo (and optionally its sibling repos) is about to get a remote/push.
    The 2026-07 backup batch proved that classify alone misses git METADATA
    (author/committer emails) and that scans go stale if motor tools run after
    them (B-TOCTOU).
During:
    Runs six offline checks per repo: folder name (never publish a "* - copia*"
    working copy), clean tree, classify_publication full-history verdict, loose
    PII pattern over every blob of every commit, metadata emails, and the same
    battery on each sibling (the original 016m UNIDAD gap: clean repo + dirty
    sibling must not pass).
After:
    Emits a JSON report plus a human checklist (private:true via API, B-TOCTOU
    ordering) and exits 0 only on LISTO. Never mutates any repo.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.classify_publication import build_manifest  # noqa: E402


COPY_FOLDER_RE = re.compile(r" - copia", re.IGNORECASE)
# Metadata emails accepted by default: GitHub noreply and fake .local identities.
DEFAULT_EMAIL_ALLOW_RE = re.compile(
    r"@users\.noreply\.github\.com$|\.local$", re.IGNORECASE
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_executable() -> str:
    """Before: git must be on PATH. During: resolve binary. After: full path."""
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git executable not found in PATH")
    return git


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [_git_executable(), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def default_pii_terms() -> list[str]:
    """Derive the default PII term at runtime (never hardcoded in the motor)."""
    home_user = Path.home().name.strip()
    return [home_user] if home_user else []


def check_name(repo: Path) -> dict[str, Any]:
    """A '* - copia*' working copy must never become a remote's source."""
    bad = bool(COPY_FOLDER_RE.search(repo.name))
    return {"check": "name", "ok": not bad, "evidence": repo.name}


def check_tree_clean(repo: Path) -> dict[str, Any]:
    """B-TOCTOU precondition: the final scan only counts on a clean tree."""
    status = _run_git(repo, "status", "--porcelain").stdout.splitlines()
    return {"check": "tree_clean", "ok": not status, "evidence": status[:5]}


def check_classify(repo: Path) -> dict[str, Any]:
    """Full-history classify verdict (inherits the 016o history PII scan)."""
    manifest = build_manifest(repo, scan_history=True)
    verdict = manifest.get("verdict")
    return {
        "check": "classify",
        "ok": verdict == "LISTO_PARA_PUBLICAR",
        "evidence": {
            "verdict": verdict,
            "blocked_reasons": [
                r.get("code") for r in manifest.get("blocked_reasons", [])
            ],
        },
    }


# Windows caps the command line at ~32K chars; ~800 revs of 40 chars overflow
# it (WinError 206, found dogfooding the gate on the motor itself). Chunk revs.
REV_CHUNK_SIZE = 100


def check_loose_pattern(repo: Path, terms: list[str]) -> dict[str, Any]:
    """Loose PII pattern over every blob of every commit.

    Catches escape/slug variants (users\\\\term, Users-term) that fixed-string
    scans missed in production; case-insensitive by construction.
    """
    hits: set[str] = set()
    revs = _run_git(repo, "rev-list", "--all").stdout.split()
    for term in terms:
        if not term:
            continue
        pattern = rf"users[^a-z0-9]{{0,4}}{re.escape(term)}"
        for start in range(0, len(revs), REV_CHUNK_SIZE):
            chunk = revs[start : start + REV_CHUNK_SIZE]
            result = _run_git(repo, "grep", "-il", "-iE", pattern, *chunk)
            hits.update(line.split(":", 1)[-1] for line in result.stdout.splitlines())
    return {"check": "loose_pattern", "ok": not hits, "evidence": sorted(hits)[:10]}


def check_metadata(repo: Path, allow_res: list[re.Pattern[str]]) -> dict[str, Any]:
    """Author/committer emails across all history (classify never sees these)."""
    emails = sorted(
        set(_run_git(repo, "log", "--all", "--format=%ae%n%ce").stdout.split())
    )
    bad = [e for e in emails if e and not any(p.search(e) for p in allow_res)]
    return {"check": "metadata", "ok": not bad, "evidence": bad[:10]}


def run_gate(
    repo: Path,
    siblings: list[Path],
    pii_terms: list[str],
    allow_emails: list[str],
) -> dict[str, Any]:
    """Run every check on the repo, then the same battery on each sibling."""
    allow_res = [DEFAULT_EMAIL_ALLOW_RE] + [
        re.compile(re.escape(e) + "$", re.IGNORECASE) for e in allow_emails
    ]
    checks = [
        check_name(repo),
        check_tree_clean(repo),
        check_classify(repo),
        check_loose_pattern(repo, pii_terms),
        check_metadata(repo, allow_res),
    ]
    sibling_reports = []
    for sib in siblings:
        sib_checks = [
            check_name(sib),
            check_tree_clean(sib),
            check_classify(sib),
            check_loose_pattern(sib, pii_terms),
            check_metadata(sib, allow_res),
        ]
        sibling_reports.append(
            {
                "sibling": sib.name,
                "ok": all(c["ok"] for c in sib_checks),
                "checks": sib_checks,
            }
        )
    ok = all(c["ok"] for c in checks) and all(s["ok"] for s in sibling_reports)
    head = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    return {
        "verdict": "LISTO" if ok else "BLOCKED",
        "repo": repo.name,
        "head": head,
        "generated_at": _now_iso(),
        "checks": checks,
        "siblings": sibling_reports,
    }


HUMAN_CHECKLIST = """\
[checklist humana - fuera del alcance offline de este gate]
 1. Crear remoto PRIVADO y verificar private:true via API ANTES del push.
 2. B-TOCTOU: NO ejecutar herramientas del motor entre este gate y el push;
    si HEAD cambia respecto al 'head' del reporte, el gate queda INVALIDADO.
 3. Push -> re-verificar private:true y sha local == remoto.
 4. gitleaks como segunda herramienta (manual) cuando este disponible.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument(
        "--sibling",
        type=Path,
        action="append",
        default=[],
        help="Sibling repo that must also pass (repeatable; UNIDAD rule).",
    )
    parser.add_argument(
        "--pii-term",
        action="append",
        default=None,
        help="PII term for the loose pattern (repeatable; default: HOME user).",
    )
    parser.add_argument(
        "--allow-email",
        action="append",
        default=[],
        help="Extra metadata email accepted besides noreply/*.local (repeatable).",
    )
    args = parser.parse_args(argv)
    try:
        terms = args.pii_term if args.pii_term is not None else default_pii_terms()
        report = run_gate(
            args.repo_root.resolve(),
            [s.resolve() for s in args.sibling],
            terms,
            args.allow_email,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"[publication-gate] ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(HUMAN_CHECKLIST, file=sys.stderr)
    return 0 if report["verdict"] == "LISTO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
