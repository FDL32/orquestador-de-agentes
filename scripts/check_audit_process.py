"""Verificacion post-auditoria: comprueba que todas las fases se completaron."""

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict


class CheckResult(TypedDict):
    phase: str
    status: str  # PASS / FAIL / SKIP
    details: str


REPORTS_DIR = Path(".agent/runtime/audit/repo_audit")


def check_fase0_scoping(ticket_dir: Path) -> CheckResult:
    """Fase 0: acotacion obligatoria."""
    scoping = ticket_dir / "_scoping.json"
    if not scoping.exists():
        return {
            "phase": "Fase 0 — Acotacion",
            "status": "FAIL",
            "details": "No existe _scoping.json",
        }
    try:
        data = json.loads(scoping.read_text())
        checks = []
        if "lanes" not in data or not data["lanes"]:
            checks.append("sin lanes")
        if "privacy" not in data:
            checks.append("sin privacidad declarada")
        if "files_censadas" not in data or data["files_censadas"] is None:
            checks.append("sin censo de archivos")
        if checks:
            return {
                "phase": "Fase 0 — Acotacion",
                "status": "FAIL",
                "details": "Faltan: " + ", ".join(checks),
            }
        return {
            "phase": "Fase 0 — Acotacion",
            "status": "PASS",
            "details": f"{len(data.get('lanes', []))} lanes censados, "
            f"{data.get('files_censadas', 0)} archivos",
        }
    except (json.JSONDecodeError, KeyError) as e:
        return {
            "phase": "Fase 0 — Acotacion",
            "status": "FAIL",
            "details": f"JSON invalido: {e}",
        }


def check_fase1_manifest(ticket_dir: Path) -> CheckResult:
    """Fase 1: recoleccion determinista — manifest."""
    manifest = ticket_dir / "_meta" / "run_manifest.json"
    if not manifest.exists():
        return {
            "phase": "Fase 1 — Manifest",
            "status": "FAIL",
            "details": "No existe run_manifest.json",
        }
    try:
        data = json.loads(manifest.read_text())
        tools = data.get("tools", {})
        executed = [k for k, v in tools.items() if v.get("status") == "executed"]
        skipped = [k for k, v in tools.items() if v.get("status") == "skipped"]
        if not executed:
            return {
                "phase": "Fase 1 — Manifest",
                "status": "FAIL",
                "details": "ninguna herramienta ejecutada",
            }
        return {
            "phase": "Fase 1 — Manifest",
            "status": "PASS",
            "details": f"{len(executed)} ejecutadas, {len(skipped)} omitidas",
        }
    except (json.JSONDecodeError, KeyError) as e:
        return {
            "phase": "Fase 1 — Manifest",
            "status": "FAIL",
            "details": f"JSON invalido: {e}",
        }


def check_fase2_triage(ticket_dir: Path) -> CheckResult:
    """Fase 2: triage por lane — hallazgos por lane."""
    hallazgos_files = list(ticket_dir.glob("HALLAZGOS_*.md"))
    if not hallazgos_files:
        hallazgos_all = ticket_dir.glob("HALLAZGOS_*.json")
        hallazgos_files = list(hallazgos_all)
    if not hallazgos_files:
        return {
            "phase": "Fase 2 — Triage",
            "status": "FAIL",
            "details": "no se encontraron HALLAZGOS_<lane>",
        }
    return {
        "phase": "Fase 2 — Triage",
        "status": "PASS",
        "details": f"{len(hallazgos_files)} archivos de hallazgos por lane",
    }


def check_fase3_dedupe(ticket_dir: Path) -> CheckResult:
    """Fase 3: deduplicacion — verificar si se ejecuto el script o se skip."""
    dedupe_log = ticket_dir / "_dedupe.json"
    manifest = ticket_dir / "_meta" / "run_manifest.json"
    if dedupe_log.exists():
        try:
            data = json.loads(dedupe_log.read_text())
            return {
                "phase": "Fase 3 — Dedupe",
                "status": "PASS",
                "details": f"{data.get('duplicates_found', 0)} duplicados encontrados, "
                f"{data.get('unique', 0)} unicos",
            }
        except json.JSONDecodeError:
            return {
                "phase": "Fase 3 — Dedupe",
                "status": "SKIP",
                "details": "dedupe.json existe pero no es JSON valido",
            }
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text())
            tools = data.get("tools", {})
            if "dedupe" in tools and tools["dedupe"].get("status") == "skipped":
                return {
                    "phase": "Fase 3 — Dedupe",
                    "status": "SKIP",
                    "details": "dedupe omitido: "
                    + tools["dedupe"].get("reason", "sin motivo"),
                }
        except json.JSONDecodeError:
            pass
    return {
        "phase": "Fase 3 — Dedupe",
        "status": "FAIL",
        "details": "dedupe no ejecutado y no registrado como omitido",
    }


def check_fase4_bundle(ticket_dir: Path) -> CheckResult:
    """Fase 4: bucle adversarial — verificar bundle protocol y veredictos."""
    veredictos = ticket_dir / "_veredictos.json"
    scorecard = ticket_dir / "_scorecard.json"
    if not veredictos.exists() and not scorecard.exists():
        return {
            "phase": "Fase 4 — Bucle adversarial",
            "status": "FAIL",
            "details": "no existe _veredictos.json ni _scorecard.json",
        }
    if veredictos.exists():
        try:
            data = json.loads(veredictos.read_text())
            lentes = len(data.get("lentes", data.get("results", [])))
            has_verdicts = any(
                v.get("veredicto_adversarial")
                for v in (data.get("lentes", data.get("results", [])))
            )
            if lentes < 2:
                return {
                    "phase": "Fase 4 — Bucle adversarial",
                    "status": "FAIL",
                    "details": f"solo {lentes} lente(s), minimo 2",
                }
            if not has_verdicts:
                return {
                    "phase": "Fase 4 — Bucle adversarial",
                    "status": "FAIL",
                    "details": "lentes sin veredicto_adversarial",
                }
            return {
                "phase": "Fase 4 — Bucle adversarial",
                "status": "PASS",
                "details": f"{lentes} lentes con veredictos",
            }
        except json.JSONDecodeError as e:
            return {
                "phase": "Fase 4 — Bucle adversarial",
                "status": "FAIL",
                "details": f"JSON invalido: {e}",
            }
    if scorecard.exists():
        try:
            data = json.loads(scorecard.read_text())
            fases = data.get("fases", [])
            fase4 = [f for f in fases if "Fase 4" in f.get("phase", "")]
            if not fase4:
                return {
                    "phase": "Fase 4 — Bucle adversarial",
                    "status": "FAIL",
                    "details": "scorecard sin Fase 4",
                }
            return {
                "phase": "Fase 4 — Buelo adversarial",
                "status": "PASS",
                "details": "Fase 4 registrada en scorecard",
            }
        except json.JSONDecodeError:
            pass
    return {
        "phase": "Fase 4 — Bucle adversarial",
        "status": "FAIL",
        "details": "scorecard existe pero no parseable",
    }


def check_fase5_reporte(ticket_dir: Path) -> CheckResult:
    """Fase 5: informe final — estructura canonica."""
    informe = ticket_dir / "_final" / "INFORME.md"
    if not informe.exists():
        return {
            "phase": "Fase 5 — Informe",
            "status": "FAIL",
            "details": "no existe _final/INFORME.md",
        }
    content = informe.read_text()
    required_sections = [
        "Resumen Ejecutivo",
        "Inventario por lane",
        "Hallazgos",
        "Follow-ups",
    ]
    missing = [s for s in required_sections if s not in content]
    if missing:
        return {
            "phase": "Fase 5 — Informe",
            "status": "FAIL",
            "details": "faltan secciones: " + ", ".join(missing),
        }
    return {
        "phase": "Fase 5 — Informe",
        "status": "PASS",
        "details": "estructura canonica completa",
    }


def check_fase6_cierre(ticket_dir: Path) -> CheckResult:
    """Fase 6: cierre — verifica que hubo rollback o validacion post-implementacion."""
    cierre_log = ticket_dir / "_cierre.json"
    scorecard = ticket_dir / "_scorecard.json"
    if cierre_log.exists():
        try:
            data = json.loads(cierre_log.read_text())
            status = data.get("status", "unknown")
            if status in ("completed", "rolled_back"):
                return {
                    "phase": "Fase 6 — Cierre",
                    "status": "PASS",
                    "details": f"status: {status}",
                }
            return {
                "phase": "Fase 6 — Cierre",
                "status": "FAIL",
                "details": f"status inesperado: {status}",
            }
        except json.JSONDecodeError:
            return {
                "phase": "Fase 6 — Cierre",
                "status": "FAIL",
                "details": "cierre.json no es JSON valido",
            }
    if scorecard.exists():
        try:
            data = json.loads(scorecard.read_text())
            fases = data.get("fases", [])
            fase6 = [f for f in fases if "Fase 6" in f.get("phase", "")]
            if fase6:
                return {
                    "phase": "Fase 6 — Cierre",
                    "status": "PASS",
                    "details": "Fase 6 registrada en scorecard",
                }
            return {
                "phase": "Fase 6 — Cierre",
                "status": "SKIP",
                "details": "no hay Fase 6 en scorecard (auditoria solo reporte)",
            }
        except json.JSONDecodeError:
            return {
                "phase": "Fase 6 — Cierre",
                "status": "FAIL",
                "details": "scorecard no es JSON valido",
            }
    return {
        "phase": "Fase 6 — Cierre",
        "status": "SKIP",
        "details": "no se encontro _cierre.json ni _scorecard.json",
    }


def check_bundle_protocol(ticket_dir: Path) -> CheckResult:
    """Verifica que los bundles de Fase 4 tengan los marcadores obligatorios."""
    bundles_dir = ticket_dir / "_bundles"
    if not bundles_dir.exists():
        # bundles pueden estar embebidos en _veredictos.json
        veredictos = ticket_dir / "_veredictos.json"
        if not veredictos.exists():
            return {
                "phase": "Bundle protocol",
                "status": "SKIP",
                "details": "no hay _bundles/ ni _veredictos.json",
            }
        return {
            "phase": "Bundle protocol",
            "status": "SKIP",
            "details": "bundles no empaquetados en directorio (veredictos.json existe)",
        }

    markers = [
        "CANAL:",
        "ROL DE LA LENTE:",
        "INVENTARIO DE EVIDENCIA",
        "PRESUPUESTO",
        "NO VERIFICABLE",
    ]
    bundle_files = list(bundles_dir.glob("*.md")) + list(bundles_dir.glob("*.txt"))
    if not bundle_files:
        return {
            "phase": "Bundle protocol",
            "status": "FAIL",
            "details": "no hay archivos .md/.txt en _bundles/",
        }

    failures = []
    for bf in bundle_files:
        content = bf.read_text()
        missing = [m for m in markers if m not in content]
        if missing:
            failures.append(f"{bf.name}: {', '.join(missing)}")

    if failures:
        return {
            "phase": "Bundle protocol",
            "status": "FAIL",
            "details": "fallan marcadores: " + "; ".join(failures),
        }
    return {
        "phase": "Bundle protocol",
        "status": "PASS",
        "details": f"{len(bundle_files)} bundle(s) con todos los marcadores",
    }


def run_checks(
    ticket_path: str | None = None,
) -> tuple[list[CheckResult], Path]:
    """Ejecuta todas las verificaciones y retorna los resultados + ticket_dir."""
    results: list[CheckResult] = []

    if ticket_path:
        ticket_dir = Path(ticket_path)
    else:
        # Buscar el ticket mas reciente
        if not REPORTS_DIR.exists():
            return (
                [
                    {
                        "phase": "ROOT",
                        "status": "FAIL",
                        "details": "no existe .agent/runtime/audit/repo_audit/",
                    }
                ],
                REPORTS_DIR,
            )
        dirs = sorted(
            REPORTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
        )
        ticket_dir = dirs[0] if dirs else REPORTS_DIR

    checks = [
        ("Fase 0", check_fase0_scoping),
        ("Fase 1", check_fase1_manifest),
        ("Fase 2", check_fase2_triage),
        ("Fase 3", check_fase3_dedupe),
        ("Fase 4", check_fase4_bundle),
        ("Fase 5", check_fase5_reporte),
        ("Fase 6", check_fase6_cierre),
        ("Bundle", check_bundle_protocol),
    ]

    outcomes: list[tuple[str, CheckResult | BaseException]] = []
    for label, check_fn in checks:
        outcomes.append((label, check_fn(ticket_dir)))

    for label, outcome in outcomes:
        if isinstance(outcome, Exception):
            results.append(
                {
                    "phase": label,
                    "status": "FAIL",
                    "details": f"excepcion: {outcome}",
                }
            )
        else:
            results.append(outcome)

    return results, ticket_dir


def print_report(results: list[CheckResult], ticket_dir: Path | None = None) -> int:
    """Imprime reporte y retorna 0 si PASS todo, 1 si hay FAIL."""
    total = len(results)
    pass_count = sum(1 for r in results if r["status"] == "PASS")
    skip_count = sum(1 for r in results if r["status"] == "SKIP")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")

    label = str(ticket_dir) if ticket_dir else "unknown"

    print(f"\n{'=' * 60}")
    print(f"  Verificacion post-auditoria — {label}")
    print(f"{'=' * 60}\n")

    for r in results:
        icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(
            r["status"], "[??]"
        )
        print(f"  {icon} {r['phase']}")
        if r["details"]:
            print(f"        {r['details']}")

    print(
        f"\n  Resumen: {pass_count}/{total} PASS, {skip_count} SKIP, {fail_count} FAIL"
    )
    print(f"{'=' * 60}\n")

    return 1 if fail_count > 0 else 0


def save_json(results: list[CheckResult]):
    """Guarda los resultados como JSON para consumo automatizado."""
    out_dir = REPORTS_DIR / "_meta"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "post_audit_check.json"
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        description="Verificar que una auditoria complet todas las fases."
    )
    parser.add_argument(
        "ticket",
        nargs="?",
        default=None,
        help="Ruta al directorio del ticket (default: mas reciente)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="save_json",
        help="Guardar resultados en JSON",
    )
    args = parser.parse_args()

    results, ticket_dir = run_checks(args.ticket)
    exit_code = print_report(results, ticket_dir)
    if args.save_json:
        save_json(results)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
