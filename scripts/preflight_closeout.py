#!/usr/bin/env python3
"""Pre-flight de cierre agregado (WOT-2026-016a).

Agrega de UNA VEZ los checks de handoff que hoy se descubren SECUENCIALMENTE
en reintentos de ``--mark-ready``, mas el check NUEVO que la sesion de
publication-readiness expuso: el checkpoint M3 debe crearse en el repo correcto
(el ``delivery_root`` resuelto por ``delivery_authority``), no en el destino
cuando ``delivery_authority == repo_motor``.

Decision de diseno (AP-D04 aplicado al propio motor): este script NO
reimplementa la logica de los checks. Importa y orquesta las funciones ya
existentes en ``scripts/pre_handoff_guard.py`` (``run_guard``,
``assert_canonical_suite_green``, ``resolve_delivery_root`` y los lectores del
plan activo). Duplicar la logica crearia dos fuentes de verdad que divergen --
exactamente el bug que AP-D04 describe en el dominio de los gates de seguridad.

Before (pre-condiciones): existe un work_plan.md activo en
``<project_root>/.agent/collaboration/`` con ``delivery_authority`` y
``deliverable_type``; ``motor_root`` apunta al repo_motor (delivery repo para
tickets motor); git esta disponible.

During (proceso y recursos): resuelve ``delivery_root`` por authority, llama a
``run_guard`` y ``assert_canonical_suite_green`` contra ese repo, y agrega sus
veredictos en tres checks (dirty_tree, checkpoint_m3, canonical_suite). I/O:
lectura del plan activo, invocaciones git read-only via las funciones
importadas. No muta estado.

After (post-condiciones y errores): imprime un diagnostico agregado (humano o
JSON con ``--json``) con un check por linea, el comando de fix exacto por check,
una advertencia CI/local no-bloqueante (AP-D05) y un veredicto global. Exit 0 si
los tres checks PASS; exit 1 si alguno FALLA o si el plan/git no se pueden leer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Importar (no reimplementar) la logica canonica de pre-handoff. Mismo patron
# que el resto del repo: scripts/ no es un paquete, asi que se inserta su dir en
# sys.path y se importa el modulo hermano.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pre_handoff_guard


CI_LOCAL_WARNING = (
    "green local NO sustituye CI clon-limpio si hay runtime desindexado "
    "(AP-D05): un test que lee un artefacto del repo puede pasar local y fallar "
    "en clon limpio. Verifica hermeticidad o skip-si-ausente."
)


def _checkpoint_fix(ticket_id: str, delivery_root: Path) -> str:
    """Comando exacto para crear M3 en el repo correcto (el delivery_root)."""
    return (
        "python scripts/create_checkpoint.py --milestone M3 "
        f"--ticket-id {ticket_id} --project-root {delivery_root}"
    )


def run_preflight(
    project_root: Path,
    ticket_id: str,
    motor_root: Path | None,
) -> dict:
    """Agregar los checks de cierre y devolver un diagnostico unico.

    Before: project_root es el workspace activo (destino); ticket_id es el
        ticket en curso; motor_root es el repo_motor o None (standalone/test).
    During: resuelve delivery_root por delivery_authority del plan activo, llama
        run_guard y assert_canonical_suite_green contra ese delivery_root y
        agrega sus resultados. No muta estado.
    After: devuelve un dict con ticket_id, delivery_authority, delivery_root,
        tres checks (cada uno {"pass", "detail", "fix"}), ci_local_warning y
        all_pass.
    """
    authority = pre_handoff_guard._read_delivery_authority_from_active_plan(
        project_root
    )
    deliverable_type = pre_handoff_guard._read_deliverable_type_from_active_plan(
        project_root
    )
    delivery_root = pre_handoff_guard.resolve_delivery_root(
        project_root=project_root,
        motor_root=motor_root,
        delivery_authority=authority,
    )

    # Orquestar el guard contra el delivery_root correcto. run_guard ya cubre el
    # checkpoint M3 (check_checkpoint_alignment) y el dirty_tree; lo invocamos
    # con project_root=delivery_root para que el tag y el arbol se busquen donde
    # vive el commit productivo (el gap real de la sesion).
    guard = pre_handoff_guard.run_guard(delivery_root, ticket_id, motor_root=motor_root)

    # La suite canonica se evalua contra el delivery_root (donde vive
    # last-run.json del run que probo el commit entregado).
    suite_ok, suite_diag = pre_handoff_guard.assert_canonical_suite_green(
        delivery_root, deliverable_type
    )

    # --- Agregacion: un check por concepto, con fix exacto ---
    dirty_pass = not guard.get("dirty_tree", False)
    dirty_files = guard.get("dirty_files", []) or []
    dirty_check = {
        "pass": dirty_pass,
        "detail": (
            "arbol limpio"
            if dirty_pass
            else f"arbol sucio: {len(dirty_files)} archivo(s) sin commitear "
            f"en {delivery_root}: {dirty_files}"
        ),
        "fix": (
            ""
            if dirty_pass
            else "commitea o limpia los archivos no declarados en el "
            f"delivery_root ({delivery_root}) antes de cerrar"
        ),
    }

    missing_ckpt = guard.get("missing_checkpoint", False)
    misaligned_ckpt = guard.get("checkpoint_misaligned", False)
    ckpt_pass = not missing_ckpt and not misaligned_ckpt
    if ckpt_pass:
        ckpt_detail = (
            f"checkpoint/review-{ticket_id} presente y alineado con HEAD "
            f"en {delivery_root}"
        )
    elif missing_ckpt:
        ckpt_detail = (
            f"falta checkpoint/review-{ticket_id} en el delivery_root "
            f"({delivery_root}); authority={authority}"
        )
    else:
        ckpt_detail = (
            f"checkpoint/review-{ticket_id} existe pero no apunta a HEAD "
            f"en {delivery_root}"
        )
    checkpoint_check = {
        "pass": ckpt_pass,
        "detail": ckpt_detail,
        # El fix SIEMPRE cita el delivery_root correcto: ese es el check nuevo.
        "fix": "" if ckpt_pass else _checkpoint_fix(ticket_id, delivery_root),
    }

    suite_reason = suite_diag.get("reason", "unknown")
    suite_check = {
        "pass": suite_ok,
        "detail": (
            f"suite canonica fresh-green ({suite_reason})"
            if suite_ok
            else f"suite canonica NO valida: {suite_reason} -- "
            f"{suite_diag.get('canonical_suite_error', '')}"
        ),
        "fix": (
            ""
            if suite_ok
            else suite_diag.get(
                "remediation",
                "python scripts/run_pytest_safe.py --level all",
            )
        ),
    }

    checks = {
        "dirty_tree": dirty_check,
        "checkpoint_m3": checkpoint_check,
        "canonical_suite": suite_check,
    }
    all_pass = all(c["pass"] for c in checks.values())

    return {
        "ticket_id": ticket_id,
        "delivery_authority": authority,
        "delivery_root": str(delivery_root),
        "deliverable_type": deliverable_type,
        "checks": checks,
        "ci_local_warning": CI_LOCAL_WARNING,
        "all_pass": all_pass,
    }


def _render_human(report: dict) -> str:
    """Render legible del reporte agregado, con un check por linea."""
    lines: list[str] = []
    verdict = "PASS" if report["all_pass"] else "FAIL"
    lines.append(f"PREFLIGHT CLOSEOUT [{verdict}] -- ticket {report['ticket_id']}")
    lines.append(
        f"  delivery_authority={report['delivery_authority']} "
        f"delivery_root={report['delivery_root']} "
        f"deliverable_type={report['deliverable_type']}"
    )
    for name, check in report["checks"].items():
        mark = "PASS" if check["pass"] else "FAIL"
        lines.append(f"  [{mark}] {name}: {check['detail']}")
        if not check["pass"] and check["fix"]:
            lines.append(f"         fix: {check['fix']}")
    lines.append(f"  WARNING (CI/local): {report['ci_local_warning']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-flight agregado de cierre: reporta de una vez dirty_tree, "
            "checkpoint M3 (en el delivery_root correcto) y suite canonica."
        )
    )
    parser.add_argument(
        "--project-root",
        required=True,
        type=Path,
        help="Workspace activo (destino) con .agent/collaboration/work_plan.md.",
    )
    parser.add_argument(
        "--ticket-id",
        required=True,
        help="ID del ticket en curso (ej. WOT-2026-016a).",
    )
    parser.add_argument(
        "--motor-root",
        type=Path,
        default=None,
        help="Repo motor (delivery repo para tickets repo_motor).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emitir el reporte agregado como JSON unico.",
    )
    args = parser.parse_args(argv)

    try:
        report = run_preflight(
            project_root=args.project_root.resolve(),
            ticket_id=args.ticket_id,
            motor_root=args.motor_root.resolve() if args.motor_root else None,
        )
    except Exception as exc:  # fail-closed: cualquier error => exit 1
        diag = {
            "ticket_id": args.ticket_id,
            "all_pass": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        if args.json:
            print(json.dumps(diag, indent=2))
        else:
            print(
                f"PREFLIGHT CLOSEOUT [FAIL] -- ticket {args.ticket_id}\n"
                f"  error: {diag['error']}"
            )
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_render_human(report))

    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
