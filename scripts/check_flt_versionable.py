#!/usr/bin/env python3
"""WOT-2026-069a: gate de versionabilidad del FLT del plan activo.

El `Files Likely Touched` (FLT) del work_plan activo admitia una ruta que el
repo que resuelve `delivery_authority` tiene GITIGNORED, y ningun gate lo
detectaba hasta que el Builder intentaba commitear (medido en WOT-2026-068z).
Este modulo implementa el gate P2: dada la prosa del work_plan, resuelve cada
ruta del FLT contra el repo de entrega (reutilizando la resolucion de
``scripts/check_deliverables_exist.py``, NO la reimplementa) y la mide con
``git -C <repo> check-ignore -v`` corriendo EN ese repo. ``git check-ignore``
es la MEDIDA, no una heuristica de nombres ni de extensiones.

Severidad (decisiones de producto del contrato T-069A-001, ya tomadas):
- FAIL: plan activo NO terminal con alguna ruta FLT ignorada en el repo
  medido, NOMBRANDO la regla (``.gitignore:<linea>:<patron>``) y el repo.
- SKIP nombrado (no verde mudo): plan ausente/vacio, plan seed-neutral
  (``ID: none``), plan TERMINAL, plan sin seccion FLT, o FLT cuyas rutas
  resultan todas saltadas con motivo declarado.
- ROJO (FAIL): plan no terminal con seccion FLT presente pero
  ``inspeccionadas == 0`` sin motivo declarado (0 rutas resolubles).
- ROJO (FAIL): fallo de medicion git (rc>=2, timeout, git ausente) --
  fail-closed, nunca un verde silencioso por no poder medir.

SIN baseline y SIN allowlist: el universo del gate es el UNICO contrato
activo, asi que no hay nada que eximir. Salida pura (dict); sin I/O de
escritura; la unica ejecucion externa es ``git check-ignore`` (lectura).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path


_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP))

# Terminales irreversibles del plan, replicados INLINE de la autoridad unica
# bus/state_machine.py IRREVERSIBLE_TERMINAL_STATES. Mismo patron que
# scripts/check_worktree_topology.py:_check_contract_coherence: NO importar
# bus/ desde un modulo cuyo sys.path apunta a .agent/ (bus/ cuelga de
# motor_root y el import daria ImportError). Normalizacion del campo
# **Estado:**: upper + primer token, tolerando decoracion.
_TERMINAL_PLAN_STATES = frozenset({"COMPLETED", "SUPERSEDED", "BLOCKED_FINAL"})
_GIT_TIMEOUT_SECONDS = 10

# check-ignore(repo_root, rel_routes) -> CompletedProcess-like
CheckIgnoreRunner = Callable[[Path, list[str]], subprocess.CompletedProcess]


def _import_state_validation():
    """Import state_validation desde el .agent/ del motor."""
    agent_dir = _BOOTSTRAP / ".agent"
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    import state_validation

    return state_validation


def _import_check_deliverables_exist():
    """Import check_deliverables_exist como paquete scripts (bootstrap listo)."""
    from scripts import check_deliverables_exist

    return check_deliverables_exist


def _resolve_flt_routes(
    plan_content: str, motor_root: Path, project_root: Path
) -> list[Path]:
    """Resolver las rutas del FLT reutilizando check_deliverables_exist.

    Before:
        - ``plan_content`` es la prosa cruda del work_plan.md.
        - ``motor_root``/``project_root`` son las raices de entrega ya
          resueltas (absolutas).

    During:
        - Reusa ``scripts.check_deliverables_exist._extract_flt_paths``, la
          UNICA implementacion de resolucion FLT (namespacing por subheading
          ``### repo_motor``/``### repo_destino`` + fallback a
          ``delivery_authority`` via ``scope_gate.read_delivery_authority``).
          Este gate NO la reimplementa.
        - Ese resolvedor lee los atributos de modulo ``PROJECT_ROOT`` y
          ``resolve_motor_root``; para inyectar raices custom (tests) se
          parchean temporalmente y se restauran en ``finally`` (validate es
          single-threaded; restauracion garantizada).

    After:
        - Retorna la lista ORDENADA de rutas absolutas resueltas (set ->
          sorted para determinismo). No requiere que las rutas existan en
          disco: el gate corre en preflight, ANTES de escribir el artefacto.
    """
    cde = _import_check_deliverables_exist()
    original_project_root = cde.PROJECT_ROOT
    original_resolver = cde.resolve_motor_root
    try:
        cde.PROJECT_ROOT = project_root
        cde.resolve_motor_root = lambda: motor_root
        routes = cde._extract_flt_paths(plan_content)
    finally:
        cde.PROJECT_ROOT = original_project_root
        cde.resolve_motor_root = original_resolver
    return sorted(routes)


def _attribute_repo(
    route: Path, motor_root: Path, project_root: Path
) -> tuple[Path, str, Path] | None:
    """Atribuir una ruta resuelta al repo de entrega que la contiene.

    Before:
        - ``route`` es una ruta absoluta resuelta por el extractor FLT.

    During:
        - Prueba ``relative_to`` contra ambas raices. Gana la raiz MAS
          ESPECIFICA (mas partes en la ruta relativa); en empate (standalone,
          ambas raices iguales) gana ``repo_motor``, el default de autoridad
          para tickets WOT. Asi el repo reportado es el repo en que el
          extractor resolvio la ruta.

    After:
        - Retorna ``(repo_root, repo_role, ruta_relativa)`` o ``None`` si la
          ruta no pertenece a ninguno de los dos repos (se declara SALTADA).
    """
    candidates: list[tuple[int, str, Path, Path]] = []
    for root, role in ((motor_root, "repo_motor"), (project_root, "repo_destino")):
        try:
            rel = route.relative_to(root)
        except ValueError:
            continue
        candidates.append((len(rel.parts), role, root, rel))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c[0], c[1]))
    _parts, role, root, rel = candidates[0]
    return root, role, rel


def _run_check_ignore(
    repo_root: Path, rel_routes: list[str]
) -> subprocess.CompletedProcess:
    """Medir rutas con ``git check-ignore -v -z --stdin`` dentro de repo_root.

    Before:
        - ``repo_root`` deberia ser un repo git; si no lo es, git responde
          fatal (rc>=2) y el gate declara fallo de medicion (fail-closed).
        - ``rel_routes`` son rutas relativas al repo, no vacias.

    During:
        - UN subprocess por repo. Entrada NUL-separada (``--stdin -z``) para
          que ``core.quotePath`` no manglee rutas no-ASCII en la salida.

    After:
        - Retorna el CompletedProcess. rc 0 = al menos una ruta ignorada
          (stdout trae registros ``source\\0line\\0pattern\\0pathname``);
          rc 1 = ninguna ignorada; rc >= 2 = fallo de medicion.
    """
    return subprocess.run(  # noqa: S603 - git, args fijos, sin shell
        [  # noqa: S607 - git resuelto por PATH, args fijos
            "git",
            "-C",
            str(repo_root),
            "check-ignore",
            "-v",
            "-z",
            "--stdin",
        ],
        input="\0".join(rel_routes) + "\0",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_GIT_TIMEOUT_SECONDS,
    )


def _parse_check_ignore_vz(stdout: str) -> dict[str, str]:
    """Parsear registros ``check-ignore -v -z`` a {pathname: regla}.

    Before:
        - ``stdout`` es la salida NUL-separada de ``check-ignore -v -z``.

    During:
        - Cada registro es ``source\\0line\\0pattern\\0pathname``. La regla se
          renderiza como ``<source>:<line>:<pattern>`` -- la forma EXACTA
          ``.gitignore:<linea>:<patron>`` que el contrato exige nombrar.
        - Registros truncados/incompletos se ignoran.

    After:
        - Retorna el dict pathname -> regla solo de las rutas ignoradas.
    """
    records = [r for r in stdout.split("\0") if r != ""]
    rules: dict[str, str] = {}
    for i in range(0, len(records) - 3, 4):
        source, line, pattern, pathname = records[i : i + 4]
        rules[pathname] = f"{source}:{line}:{pattern}"
    return rules


def _has_flt_section(plan_content: str) -> bool:
    """True si el plan declara seccion ``## Files Likely Touched``.

    Misma ancla que el extractor (linea cuyo strip empieza por el literal):
    un plan sin seccion declara implicitamente 0 rutas -> motivo declarado.
    """
    return any(
        line.strip().startswith("## Files Likely Touched")
        for line in plan_content.splitlines()
    )


def _measure_repo_batches(
    result: dict,
    per_repo: dict[Path, list[tuple[str, str]]],
    runner: CheckIgnoreRunner,
) -> None:
    """Medir cada batch de rutas por repo y mutar el denominador del result.

    Before:
        - ``per_repo`` mapea repo_root -> [(ruta_relativa_posix, rol)].
        - ``runner`` es la medida (``git check-ignore`` por defecto).

    During:
        - Un batch por repo. rc 0/1 son resultados validos (0 = hay
          ignoradas; 1 = ninguna); rc >= 2 o excepcion del runner son
          fallos de medicion y se acumulan para el fail-closed del caller.
        - Las rutas ignoradas incrementan ``ignoradas`` y anaden la
          violacion con la regla nombrada y el repo medido.

    After:
        - Muta ``result`` in place: ``inspeccionadas``, ``ignoradas`` y
          ``violaciones``; ademas escribe ``measurement_failures``. Nunca
          lanza: los fallos del runner se capturan y se reportan.
    """
    measurement_failures: list[str] = []
    for repo_root in sorted(per_repo):
        entries = per_repo[repo_root]
        rel_routes = [rel for rel, _role in entries]
        try:
            proc = runner(repo_root, rel_routes)
        except Exception as exc:
            measurement_failures.append(f"{repo_root}: {type(exc).__name__}: {exc}")
            continue
        if proc.returncode not in (0, 1):
            stderr = (proc.stderr or "").strip()
            measurement_failures.append(
                f"{repo_root}: git check-ignore rc={proc.returncode} {stderr}"
            )
            continue
        ignored = _parse_check_ignore_vz(proc.stdout or "")
        for rel, role in entries:
            result["inspeccionadas"] += 1
            rule = ignored.get(rel)
            if rule is not None:
                result["ignoradas"] += 1
                result["violaciones"].append(
                    {
                        "ruta": rel,
                        "repo": str(repo_root),
                        "repo_role": role,
                        "regla": rule,
                    }
                )
    result["measurement_failures"] = measurement_failures


def _early_skip_reason(plan_content: str, cde, result: dict) -> str | None:
    """Resolver los SKIP nombrados previos a la medicion (D3).

    Before:
        - ``plan_content`` es la prosa cruda (posiblemente vacia).
        - ``result`` ya inicializado con el denominador a cero.

    During:
        - Evalua en orden: plan vacio, seed-neutral (``ID: none``), plan
          terminal, plan sin seccion FLT. Solo lectura; publica
          ``delivery_authority`` en result al leerla.

    After:
        - Retorna el motivo del SKIP, o ``None`` si el plan entra en el
          universo del gate y debe medirse. Nunca lanza por estados
          esperados del plan.
    """
    if not plan_content.strip():
        return "sin plan activo (work_plan vacio o ausente)"
    sv = _import_state_validation()
    result["delivery_authority"] = cde._import_scope_gate().read_delivery_authority(
        plan_content
    )
    if sv.get_plan_id(plan_content).strip().lower() == "none":
        return "plan seed-neutral (ID: none): sin ticket activo"
    raw_status = sv.get_status(plan_content, "**Estado:**")
    normalized_status = (
        raw_status.strip().upper().split()[0] if raw_status.strip() else ""
    )
    if normalized_status in _TERMINAL_PLAN_STATES:
        return f"plan terminal ({normalized_status}): fuera del universo del gate"
    if not _has_flt_section(plan_content):
        return (
            "plan no terminal sin seccion Files Likely Touched: "
            "0 rutas declaradas (motivo declarado por el propio plan)"
        )
    return None


def flt_paths_not_versionable(
    plan_content: str,
    *,
    motor_root: Path | None = None,
    project_root: Path | None = None,
    check_ignore: CheckIgnoreRunner | None = None,
) -> dict:
    """Medir la versionabilidad del FLT del plan activo en su repo de entrega.

    Before:
        - ``plan_content`` es la prosa cruda del work_plan.md (puede venir
          vacia si no hay plan activo).
        - ``motor_root``/``project_root`` por defecto se resuelven como
          ``check_deliverables_exist`` los resuelve (motor_link /
          ``AGENT_PROJECT_ROOT`` / vars TEST_*).
        - ``check_ignore`` inyectable para tests; por defecto es
          ``git check-ignore -v -z --stdin`` real.

    During:
        - Pura sobre el texto del plan: sin escrituras; la unica ejecucion
          externa es git check-ignore (lectura). Corre en preflight, ANTES
          de que el Builder escriba el artefacto.
        - SKIP nombrado para plan vacio, seed-neutral (ID: none), terminal,
          sin seccion FLT, o todas las rutas saltadas con motivo declarado.
        - ROJO para plan no terminal con seccion FLT y 0 rutas resolubles
          (sin motivo declarado), y para fallo de medicion git (rc>=2,
          timeout, git ausente): fail-closed, nunca verde silencioso.
        - Mide por repo (un batch check-ignore por repo distinto) y NOMBRA
          el repo medido por ruta: un mismo path puede tener contratos de
          tracking opuestos en motor y destino, y ambos ser correctos.
        - Publica el DENOMINADOR (rutas/inspeccionadas/ignoradas/saltadas),
          la LISTA de saltadas con motivo y las violaciones con la regla.

    After:
        - Retorna un dict con ``status`` OK/SKIP/FAIL, ``reason`` (SKIP y
          FAIL), ``delivery_authority``, las raices nombradas, el
          denominador, ``violaciones`` (ruta/repo/repo_role/regla) y
          ``saltadas_detalle``. No lanza por resultados git esperados; los
          errores de import inesperados propagan al llamador.
    """
    cde = _import_check_deliverables_exist()
    motor = (
        Path(motor_root).resolve()
        if motor_root
        else Path(cde.resolve_motor_root()).resolve()
    )
    destino = (
        Path(project_root).resolve()
        if project_root
        else Path(cde.PROJECT_ROOT).resolve()
    )
    runner = check_ignore or _run_check_ignore

    result: dict = {
        "gate": "flt_versionable",
        "ticket": "WOT-2026-069a",
        "status": "OK",
        "reason": None,
        "delivery_authority": None,
        "repo_motor": str(motor),
        "repo_destino": str(destino),
        "rutas": 0,
        "inspeccionadas": 0,
        "ignoradas": 0,
        "saltadas": 0,
        "violaciones": [],
        "saltadas_detalle": [],
    }

    content = plan_content or ""
    skip_reason = _early_skip_reason(content, cde, result)
    if skip_reason is not None:
        result["status"] = "SKIP"
        result["reason"] = skip_reason
        return result

    routes = _resolve_flt_routes(content, motor, destino)
    result["rutas"] = len(routes)
    if not routes:
        result["status"] = "FAIL"
        result["reason"] = (
            "ROJO: inspeccionadas == 0 sin motivo declarado "
            "(seccion FLT presente pero 0 rutas resolubles en plan no terminal)"
        )
        return result

    per_repo: dict[Path, list[tuple[str, str]]] = {}
    for route in routes:
        attributed = _attribute_repo(route, motor, destino)
        if attributed is None:
            result["saltadas"] += 1
            result["saltadas_detalle"].append(
                {
                    "ruta": str(route),
                    "motivo": "fuera de los dos repos de entrega (motor y destino)",
                }
            )
            continue
        repo_root, role, rel = attributed
        per_repo.setdefault(repo_root, []).append((rel.as_posix(), role))

    if not per_repo:
        result["status"] = "SKIP"
        result["reason"] = "0 rutas inspeccionadas: todas saltadas con motivo declarado"
        return result

    _measure_repo_batches(result, per_repo, runner)
    measurement_failures = result.pop("measurement_failures")

    if measurement_failures:
        result["status"] = "FAIL"
        result["reason"] = (
            "ROJO: no se pudo medir con git check-ignore (fail-closed): "
            + "; ".join(measurement_failures)
        )
    elif result["ignoradas"]:
        result["status"] = "FAIL"
        result["reason"] = (
            f"{result['ignoradas']} ruta(s) del FLT NO versionable(s) "
            "en el repo de entrega"
        )
    return result


def gate_errors(result: dict) -> list[str]:
    """Renderizar un resultado FAIL del gate como errores de ``--validate``.

    Before:
        - ``result`` es el dict retornado por ``flt_paths_not_versionable``.

    During:
        - Un error por violacion, NOMBRANDO la regla (``.gitignore:<linea>:
          <patron>``) y el repo medido (con su rol), tal como exige D3.
        - Sin violaciones pero FAIL (ROJO por 0 inspeccionadas o fallo de
          medicion): un error con el reason del gate.

    After:
        - Retorna [] para resultados OK/SKIP. Nunca lanza.
    """
    if result.get("status") != "FAIL":
        return []
    errors = [
        f"FLT '{violation['ruta']}' NO versionable en repo "
        f"{violation['repo']} ({violation['repo_role']}): ignorada por "
        f"{violation['regla']} (WOT-2026-069a)"
        for violation in result.get("violaciones", [])
    ]
    if not errors:
        reason = result.get("reason") or "gate FAIL sin detalle"
        errors.append(f"flt_versionable: {reason} (WOT-2026-069a)")
    return errors


def format_summary(result: dict) -> str:
    """Resumen humano de una linea (o bloque) con el denominador publicado."""
    denominador = (
        f"rutas={result['rutas']} inspeccionadas={result['inspeccionadas']} "
        f"ignoradas={result['ignoradas']} saltadas={result['saltadas']}"
    )
    head = f"flt_versionable [{result['status']}] {denominador}"
    if result["status"] == "SKIP":
        return f"[SKIP] {head} motivo: {result['reason']}"
    if result["status"] == "FAIL":
        lines = [f"[FAIL] {head}"]
        lines.extend(
            f"  {violation['ruta']} -> {violation['regla']} (repo {violation['repo']})"
            for violation in result["violaciones"]
        )
        if result["reason"]:
            lines.append(f"  motivo: {result['reason']}")
        return "\n".join(lines)
    return f"[OK] {head} repo_motor={result['repo_motor']}"


def main(argv: list[str] | None = None) -> int:
    """Sonda manual del gate sobre el work_plan activo del proyecto.

    Before:
        - Sin args (o --json). Resuelve PROJECT_ROOT igual que
          check_deliverables_exist (AGENT_PROJECT_ROOT / motor_destination_link).

    During:
        - Lee el work_plan activo y corre el gate completo (solo lectura).

    After:
        - Imprime el resultado (JSON con denominador, o resumen humano) y
          retorna 0 para OK/SKIP y 1 para FAIL. Nunca escribe.
    """
    parser = argparse.ArgumentParser(
        description="WOT-2026-069a: gate de versionabilidad del FLT del plan activo"
    )
    parser.add_argument(
        "--json", action="store_true", help="publica el resultado completo como JSON"
    )
    args = parser.parse_args(argv)
    cde = _import_check_deliverables_exist()
    content = ""
    if cde.WORK_PLAN.exists():
        content = cde.WORK_PLAN.read_text(encoding="utf-8")
    result = flt_paths_not_versionable(content)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_summary(result))
    return 0 if result["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
