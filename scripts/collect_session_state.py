#!/usr/bin/env python
"""Recolector de estado para el arranque de una sesion nueva (WOT session-hop).

Que protege
-----------
Un arranque de sesion transporta DOS cosas: el METODO (que no caduca y vive
versionado en ``prompts/session_hop.md``) y el ESTADO (que caduca en horas). Cuando
el estado se COPIA en vez de RE-MEDIRSE, se convierte en premisa falsa heredada.

Medido en este repo en dos dias: un arranque declaraba el destino en ``eb721cb``
cuando era ``f34aa80``; decia "237 pending" cuando eran 240 (239 al dia siguiente);
mandaba expandir 4 slugs de memoria de los que 3 daban ``rc=1``; y un mismo censo
dio 157 -> 152 -> 154.

Este script emite ese estado MEDIDO, con el comando y el exit code de cada dato,
para que el arranque no lo invente.

CONTRATO DE AUTORIDAD (no negociable)
-------------------------------------
**Este script RECOLECTA; el AGENTE juzga.** Mismo contrato que
``backlog_reconcile.py`` (*"This script NEVER classifies"*). Su salida no contiene
NINGUN veredicto: ni ``APTO_AUTONOMO``, ni ``LIKELY_DONE``, ni ``APROBADO``, ni
``LISTO``, ni ``BLOQUEANTE``. Si un consumidor busca ahi una conclusion, no la va a
encontrar, y eso es deliberado: el juicio exige leer la evidencia, y la evidencia es
lo que este script entrega.

El test ``test_collect_session_state.py`` fija esa lista de terminos CERRADA. Una
lista abierta ("ninguna palabra de veredicto") no seria testeable, y por tanto
tampoco un contrato.

CONTRATO DE FALLO (el caso que mas importa)
-------------------------------------------
Con arbol SUCIO, suite STALE o un gate en rojo, este script **sigue saliendo 0 y
REPORTA esos hechos**. Un recolector que se cae cuando el arbol no esta sano es
inutil justo cuando hace falta.

``rc != 0`` queda reservado a fallo del PROPIO recolector: ruta irresoluble o I/O.
Nunca a un hallazgo sobre el repo.

Before / During / After
-----------------------
Before: ``--project-root`` apunta a un destino existente; ``--motor-root`` se deriva
    si se omite (el repo que contiene este script).
During: ejecuta comandos read-only (git, gates, lectura de JSON). No escribe en
    ninguna superficie operativa: ni ``backlog.md``, ni ``STATE.md``, ni el bus.
After: imprime un bloque markdown pegable (o JSON con ``--json``) donde cada dato
    lleva su ``command:`` y su ``exit_code:``. Exit 0 salvo fallo del recolector.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent

# Terminos de VEREDICTO que esta salida no puede contener. Lista CERRADA a
# proposito: es lo que hace el contrato testeable (ver el test hermano). Una lista
# abierta ("ninguna palabra de juicio") no se puede verificar de forma reproducible.
FORBIDDEN_VERDICTS = (
    "APTO_AUTONOMO",
    "REQUIERE_HUMANO",
    "DISENO_PRIMERO",
    "LIKELY_DONE",
    "LIKELY_PENDING",
    "NEEDS_HUMAN_VERIFY",
    "APROBADO",
    "CAMBIOS NECESARIOS",
    "LISTO",
    "BLOQUEANTE",
)


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> dict:
    """Ejecuta un comando read-only y devuelve su recibo.

    El ``exit_code`` sale de ``subprocess.returncode``, NUNCA de ``$?`` tras un pipe:
    ``cmd | tail`` devuelve el rc de ``tail``, que casi siempre es 0 (leccion
    recurrente de este repo).
    """
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "command": " ".join(cmd),
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        # NO se propaga: un comando que no arranca es un HECHO a reportar, no un
        # motivo para tumbar la recoleccion entera.
        return {
            "command": " ".join(cmd),
            "exit_code": None,
            "stdout": "",
            "stderr": f"no ejecutable: {exc}",
        }


def _git(root: Path, *args: str) -> dict:
    return _run(["git", "-C", str(root), *args])


def collect_repo(role: str, root: Path) -> dict:
    """Hechos de un repo: HEAD, rama, sucio (tracked vs untracked), sin publicar."""
    if not root.exists():
        return {"role": role, "path": str(root), "exists": False}

    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(root, "status", "--porcelain")
    unpushed = _git(root, "log", "--oneline", "origin/main..HEAD")

    lines = [ln for ln in status["stdout"].splitlines() if ln.strip()]
    tracked = [ln for ln in lines if not ln.startswith("??")]
    untracked = [ln for ln in lines if ln.startswith("??")]

    return {
        "role": role,
        "path": str(root),
        "exists": True,
        "head": head["stdout"][:40],
        "branch": branch["stdout"],
        # tracked vs untracked SEPARADOS: un arranque que los suma reporta "sucio"
        # cuando lo unico presente son artefactos nuevos de otra sesion.
        "dirty_tracked": len(tracked),
        "dirty_untracked": len(untracked),
        "untracked_sample": [ln[3:] for ln in untracked[:5]],
        "unpushed_count": len(
            [ln for ln in unpushed["stdout"].splitlines() if ln.strip()]
        ),
        "unpushed": [ln for ln in unpushed["stdout"].splitlines() if ln.strip()][:10],
        "receipts": [head, status, unpushed],
    }


def collect_suite(motor_root: Path) -> dict:
    """Sello de la suite canonica frente al HEAD real.

    El campo se llama ``tested_commit_sha`` (lo escribe ``run_pytest_safe.py``), y
    ``level``/``args_mode`` importan tanto como el sha: una corrida filtrada se
    registra igual con ``level: all`` pero mide un SUBCONJUNTO.
    """
    path = motor_root / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
    if not path.exists():
        return {"present": False, "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return {"present": True, "path": str(path), "unreadable": str(exc)}

    head = _git(motor_root, "rev-parse", "HEAD")["stdout"]
    tested = data.get("tested_commit_sha")
    return {
        "present": True,
        "path": str(path),
        "tested_commit_sha": tested,
        "head": head,
        "matches_head": bool(tested) and tested == head,
        "level": data.get("level"),
        "args_mode": data.get("args_mode"),
        "exit_code": data.get("exit_code"),
        "passed": data.get("passed"),
        "skipped": data.get("skipped"),
    }


def collect_gates(motor_root: Path, project_root: Path) -> list[dict]:
    """Gates read-only, cada uno con su rc REAL. Un rojo aqui NO tumba la corrida."""
    py = sys.executable
    return [
        _run(
            [
                py,
                str(motor_root / "scripts" / "check_backlog_contract.py"),
                "--project-root",
                str(project_root),
            ],
            cwd=motor_root,
        ),
        _run(
            [py, str(motor_root / "scripts" / "check_guard_wiring.py")],
            cwd=motor_root,
        ),
    ]


def collect_memory_slugs(motor_root: Path, slugs: list[str]) -> list[dict]:
    """Verifica CADA slug antes de que el arranque lo cite.

    Un arranque que ordena expandir un slug inexistente le regala al ejecutor un paso
    imposible. Solo los ``rc=0`` son citables.
    """
    py = sys.executable
    out = []
    for slug in slugs:
        rec = _run(
            [
                py,
                str(motor_root / "scripts" / "memory_context.py"),
                "--recall",
                "--id",
                slug,
            ],
            cwd=motor_root,
            timeout=60,
        )
        out.append(
            {
                "slug": slug,
                "exit_code": rec["exit_code"],
                "citable": rec["exit_code"] == 0,
            }
        )
    return out


def collect_inbox(project_root: Path) -> dict:
    inbox = project_root / ".agent" / "collaboration" / "backlog_inbox"
    fichas = (
        sorted(p.name for p in inbox.glob("*.tickets.md")) if inbox.exists() else []
    )
    fp = project_root / "orchestrator_pipeline" / "flight_plans"
    return {
        "inbox_path": str(inbox),
        "fichas_count": len(fichas),
        "fichas": fichas,
        "queued": sorted(p.name for p in (fp / "queued").glob("*.json"))
        if (fp / "queued").exists()
        else [],
        "in_flight": sorted(p.name for p in (fp / "in_flight").glob("*"))
        if (fp / "in_flight").exists()
        else [],
    }


def collect_mode(motor_root: Path) -> dict:
    """Modo de despliegue: se DETECTA, nunca se asume (un vuelo ya se equivoco)."""
    rec = _run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, '.'); "
            "from runtime.project_root import is_motor_code_only; "
            "print(is_motor_code_only())",
        ],
        cwd=motor_root,
    )
    return {
        "command": rec["command"],
        "exit_code": rec["exit_code"],
        "is_motor_code_only": rec["stdout"].strip(),
    }


def build_report(motor_root: Path, project_root: Path, slugs: list[str]) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "EVIDENCIA FECHADA, no criterio. Cada dato lleva su comando: re-mide "
            "antes de citar. Este bloque no contiene veredictos por contrato."
        ),
        "repos": [
            collect_repo("repo_motor", motor_root),
            collect_repo("repo_destino", project_root),
        ],
        "mode": collect_mode(motor_root),
        "suite": collect_suite(motor_root),
        "gates": collect_gates(motor_root, project_root),
        "memory_slugs": collect_memory_slugs(motor_root, slugs),
        "inbox": collect_inbox(project_root),
    }


def render_markdown(rep: dict) -> str:
    out: list[str] = []
    out.append(f"## ESTADO MEDIDO [snapshot {rep['generated_at']}]")
    out.append("")
    out.append(f"> {rep['note']}")
    out.append("")
    out.append("### Topologia")
    out.append("")
    out.append(
        "| Rol | Ruta | HEAD | Rama | dirty tracked | untracked | sin publicar |"
    )
    out.append("|---|---|---|---|---|---|---|")
    for r in rep["repos"]:
        if not r.get("exists"):
            out.append(f"| {r['role']} | {r['path']} | (no existe) | - | - | - | - |")
            continue
        out.append(
            f"| {r['role']} | {r['path']} | `{r['head'][:7]}` | {r['branch']} | "
            f"{r['dirty_tracked']} | {r['dirty_untracked']} | {r['unpushed_count']} |"
        )
    out.append("")
    out.append(
        f"Modo: `is_motor_code_only() = {rep['mode']['is_motor_code_only']}` "
        f"(`exit_code: {rep['mode']['exit_code']}`) -- **detectado, no asumido**."
    )
    out.append("")

    s = rep["suite"]
    out.append("### Suite canonica")
    out.append("")
    if not s.get("present"):
        out.append(f"- `last-run.json` ausente en `{s['path']}`.")
    elif s.get("unreadable"):
        out.append(f"- `last-run.json` ilegible: {s['unreadable']}")
    else:
        out.append(
            f"- `tested_commit_sha`: `{str(s['tested_commit_sha'])[:7]}` | "
            f"HEAD: `{str(s['head'])[:7]}` | coincide: **{s['matches_head']}**"
        )
        out.append(
            f"- `level={s['level']}` `args_mode={s['args_mode']}` "
            f"`exit_code={s['exit_code']}` passed={s['passed']} skipped={s['skipped']}"
        )
    out.append("")

    out.append("### Gates (rc real, sin pipe)")
    out.append("")
    out.extend(
        f"- `{g['command']}` -> `exit_code: {g['exit_code']}`" for g in rep["gates"]
    )
    out.append("")

    out.append("### Slugs de memoria")
    out.append("")
    citable = [m["slug"] for m in rep["memory_slugs"] if m["citable"]]
    no_cit = [m["slug"] for m in rep["memory_slugs"] if not m["citable"]]
    out.append(
        f"- Citables (`rc=0`): {', '.join(f'`{s}`' for s in citable) or '(ninguno)'}"
    )
    if no_cit:
        out.append(
            f"- **NO citables (`rc!=0`)**: {', '.join(f'`{s}`' for s in no_cit)} "
            "-- no los ordenes expandir."
        )
    out.append("")

    i = rep["inbox"]
    out.append("### Buzon y planes")
    out.append("")
    out.append(f"- fichas en `backlog_inbox/`: **{i['fichas_count']}**")
    out.append(f"- `flight_plans/queued/`: {len(i['queued'])}")
    out.append(f"- `flight_plans/in_flight/`: {len(i['in_flight'])}")
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Recolecta el estado medido para el arranque de una sesion nueva. "
            "RECOLECTA, no juzga: su salida no contiene veredictos."
        )
    )
    ap.add_argument("--project-root", required=True, help="raiz del repo_destino")
    ap.add_argument(
        "--motor-root",
        default=None,
        help="raiz del motor (por defecto: el de este script)",
    )
    ap.add_argument(
        "--slug",
        action="append",
        default=None,
        help="slug de memoria a verificar (repetible)",
    )
    ap.add_argument(
        "--json", action="store_true", help="salida JSON en vez de markdown"
    )
    args = ap.parse_args()

    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        # rc != 0 SOLO por fallo del recolector, nunca por un hallazgo del repo.
        print(
            f"[session-hop] ERROR: --project-root no existe: {project_root}",
            file=sys.stderr,
        )
        return 2

    motor_root = Path(args.motor_root).resolve() if args.motor_root else MOTOR_ROOT
    slugs = args.slug or [
        "obs-guard-green-only-counts-if-your-row-entered-its-denominator",
        "obs-dod-invariant-not-measurement",
    ]

    rep = build_report(motor_root, project_root, slugs)
    print(
        json.dumps(rep, ensure_ascii=False, indent=2)
        if args.json
        else render_markdown(rep)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
