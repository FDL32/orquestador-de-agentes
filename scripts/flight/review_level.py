#!/usr/bin/env python3
"""Clasificador mecanico del nivel de revision proporcional.

Before: recibe dos referencias Git, una ficha opcional y el nivel anterior
    opcional de la ronda del mismo ticket.
During: compara arboles con ``git diff``, clasifica rutas de alto riesgo y
    cuenta lineas de produccion para decidir completo o delta.
After: imprime siempre ``NIVEL=`` y ``RAZON=``; rc 0 es una entrada valida y
    rc 2 es fail-closed por entrada, ficha o rango ilegible.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast


PRODUCTION_THRESHOLD = 50  # NO MEDIDO: umbral provisional y conservador.
LEVELS = frozenset({"completo", "delta"})
_BACKLOG_ROW_RE = re.compile(r"^\|\s*Media\s*\|\s*(?P<ticket>[A-Za-z0-9_-]+)\s*\|")
_RISK_TOKEN_RE = re.compile(r"\[RIESGO:\s*alto\]", re.IGNORECASE)
_BRIEF_RISK_RE = re.compile(r"^RISK_LEVEL:\s*high\s*$", re.IGNORECASE)


HIGH_RISK_GLOBS: dict[str, tuple[str, ...]] = {
    "consent": (
        ".agent/rules/common/consentimiento_*.md",
        "scripts/*authoriz*.py",
        "scripts/*consent*.py",
    ),
    "hooks": (".agent/hooks/**", ".agent/config/hooks_config.json", ".githooks/**"),
    "ruleset": (".agent/rules/common/flight_push_policy.md", ".github/**"),
    "backlog-flt": (
        ".agent/collaboration/backlog.md",
        ".agent/collaboration/*FLT*",
        "scripts/*backlog*",
        "scripts/check_flt_versionable.py",
    ),
    "push-sync-delete": (
        "scripts/*push*",
        "scripts/*sync*",
        "scripts/*delete*",
    ),
    "state": ("bus/**", ".agent/runtime/events/**", "scripts/*state*.py"),
    "closeout": ("scripts/*closeout*", "scripts/flight/*close*"),
    "lenses": ("scripts/ensemble_dispatch.py",),
    "integration": ("scripts/flight/integrate_ticket.py",),
    "classifier": (
        "scripts/flight/review_level.py",
        ".agent/rules/common/revision_proporcional.md",
    ),
    "guards": ("scripts/check_*.py", "scripts/flight/check_*.py"),
}


@dataclass(frozen=True)
class Classification:
    """Resultado serializable de una clasificación."""

    level: str
    reasons: tuple[str, ...]
    rc: int


@dataclass(frozen=True)
class FichaRisk:
    """Resultado del parseo de una ficha o fila de backlog."""

    high_risk: bool
    rc: int
    reason: str = ""


class ReviewLevelError(RuntimeError):
    """Error de infraestructura al leer el diff solicitado."""


def _normalise_path(path: str | Path) -> str:
    """Normaliza una ruta para comparar globs portables.

    Before: ``path`` es texto o ``Path`` relativo al repositorio.
    During: convierte separadores Windows a ``/`` y elimina el prefijo ``./``.
    After: devuelve una ruta relativa estable, sin acceder al sistema.
    """
    candidate = str(path).replace("\\", "/")
    return candidate[2:] if candidate.startswith("./") else candidate


def high_risk_family(path: str | Path) -> str | None:
    """Devuelve la familia de riesgo de una ruta o ``None``.

    Before: ``path`` es una ruta relativa del árbol Git.
    During: prueba la ruta contra la única tabla de globs declarada aquí.
    After: devuelve el primer nombre de familia coincidente, sin I/O.
    """
    candidate = _normalise_path(path)
    for family, patterns in HIGH_RISK_GLOBS.items():
        if any(fnmatch.fnmatchcase(candidate, pattern) for pattern in patterns):
            return family
    return None


def _is_production(path: str) -> bool:
    """Indica si una ruta contribuye al contador de producción.

    Before: ``path`` está normalizada y es una ruta del diff.
    During: excluye tests y docs, y acepta solo ``.py``, ``.ps1`` y ``.sh``.
    After: devuelve un booleano determinista sin leer el fichero.
    """
    candidate = _normalise_path(path)
    parts = candidate.split("/")
    return parts[0] not in {"tests", "docs"} and candidate.lower().endswith(
        (".py", ".ps1", ".sh")
    )


def _reasoned(level: str, reason: str, rc: int = 0) -> Classification:
    """Construye un resultado con una razón única y estable.

    Before: ``level`` es ``completo`` o ``delta`` y ``reason`` no está vacío.
    During: empaqueta los campos sin transformar su semántica.
    After: devuelve un ``Classification`` listo para CLI o tests.
    """
    return Classification(level, (reason,), rc)


def classify_paths(
    changed_paths: Sequence[str],
    *,
    production_lines: int,
    ficha_high_risk: bool,
    diff_empty: bool,
) -> Classification:
    """Clasifica un diff ya medido, sin ejecutar Git.

    Before: ``changed_paths`` y ``production_lines`` proceden del mismo diff;
        ``diff_empty`` debe ser verdadero cuando no hay rutas.
    During: aplica fail-closed, globs de alto riesgo, ficha y umbral inclusivo.
    After: devuelve delta solo para un cambio no sensible menor de 50 líneas;
        un rango vacío devuelve completo con rc 2.
    """
    if diff_empty or not changed_paths:
        return _reasoned("completo", "rango-vacio", 2)
    families = sorted(
        {family for path in changed_paths if (family := high_risk_family(path))}
    )
    if families:
        return _reasoned("completo", f"glob-alto-riesgo: {','.join(families)}")
    if ficha_high_risk:
        return _reasoned("completo", "ficha-riesgo-alto")
    if production_lines >= PRODUCTION_THRESHOLD:
        return _reasoned(
            "completo", f"produccion-umbral: {production_lines}>={PRODUCTION_THRESHOLD}"
        )
    return _reasoned(
        "delta",
        f"cambio-no-alto-menor-que-umbral: {production_lines}<{PRODUCTION_THRESHOLD}",
    )


def apply_previous_level(
    calculated_level: str,
    *,
    previous_level: str | None,
    lower_reason: str,
) -> Classification:
    """Aplica la regla monotónica de nivel anterior.

    Before: ``calculated_level`` procede del diff y ``previous_level`` puede
        ser ``None``, ``completo`` o ``delta``.
    During: rechaza niveles desconocidos y solo permite bajar con texto no vacío.
    After: devuelve el nivel final; un nivel anterior ilegible da completo/rc 2.
    """
    if calculated_level not in LEVELS:
        return _reasoned("completo", "nivel-calculado-ilegible", 2)
    if previous_level is None:
        return Classification(calculated_level, (), 0)
    if previous_level not in LEVELS:
        return _reasoned("completo", "prev-level-ilegible", 2)
    if previous_level == "completo" and calculated_level == "delta":
        reason = lower_reason.strip()
        if not reason:
            return _reasoned("completo", "nivel-no-baja-sin-motivo")
        return _reasoned("delta", f"bajada-con-motivo: {reason}")
    return Classification(calculated_level, (), 0)


def read_ticket_risk(backlog: Path, ticket: str) -> FichaRisk:
    """Lee exactamente una fila ``Media`` del backlog.

    Before: ``backlog`` debe ser legible y ``ticket`` no vacío.
    During: selecciona filas de una sola línea con el id en la segunda columna
        y busca el token literal ``[RIESGO: alto]``.
    After: devuelve riesgo alto/rc 0; ausencia, duplicidad o I/O dan rc 2.
    """
    try:
        lines = backlog.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return FichaRisk(False, 2, "ficha-ilegible")
    matches = [
        line
        for line in lines
        if (
            _BACKLOG_ROW_RE.match(line)
            and _BACKLOG_ROW_RE.match(line).group("ticket") == ticket
        )
    ]
    if len(matches) != 1:
        return FichaRisk(False, 2, "ticket-ausente-o-duplicado")
    return FichaRisk(bool(_RISK_TOKEN_RE.search(matches[0])), 0, "")


def read_brief_risk(brief: Path) -> FichaRisk:
    """Lee la marca opcional de riesgo alto de un brief.

    Before: ``brief`` es un fichero de texto con una línea ``RISK_LEVEL``.
    During: lee líneas completas y acepta solo ``RISK_LEVEL: high``.
    After: devuelve riesgo alto/rc 0 o ficha ilegible/rc 2.
    """
    try:
        lines = brief.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return FichaRisk(False, 2, "ficha-ilegible")
    return FichaRisk(any(_BRIEF_RISK_RE.match(line) for line in lines), 0, "")


def _run_git(repo: Path, args: Iterable[str]) -> subprocess.CompletedProcess[str]:
    """Ejecuta Git en el repositorio solicitado.

    Before: ``repo`` es un checkout y ``args`` contiene solo argumentos Git.
    During: ejecuta Git sin shell y captura stdout/stderr en UTF-8 del proceso.
    After: devuelve el proceso; el llamador traduce rc no cero a fail-closed.
    """
    try:
        return subprocess.run(  # noqa: S603 - executable and args are fixed by this CLI
            ["git", "-C", str(repo), *args],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise ReviewLevelError(f"git-no-disponible: {exc}") from exc


def diff_paths(repo: Path, left: str, right: str) -> list[str]:
    """Devuelve rutas del diff entre dos árboles, aunque sean SHAs hermanos.

    Before: ``left`` y ``right`` resuelven a commits o árboles Git.
    During: ejecuta ``git diff --name-only``; no consulta ``git log`` ni exige
        que ``left`` sea ancestro de ``right``.
    After: devuelve rutas normalizadas o eleva ``ReviewLevelError``.
    """
    completed = _run_git(
        repo, ["diff", "--name-only", "-z", "--no-renames", left, right]
    )
    if completed.returncode != 0:
        raise ReviewLevelError(f"diff-ilegible: {completed.stderr.strip()[:300]}")
    return [_normalise_path(path) for path in completed.stdout.split("\0") if path]


def production_line_count(repo: Path, left: str, right: str) -> int:
    """Cuenta añadidas más eliminadas de producción en un diff.

    Before: las referencias Git describen el mismo diff que se clasificará.
    During: parsea ``git diff --numstat`` y excluye tests/docs según
        ``_is_production``; un binario o salida ilegible falla cerrado.
    After: devuelve el total entero de líneas añadidas y eliminadas.
    """
    completed = _run_git(repo, ["diff", "--numstat", "-z", "--no-renames", left, right])
    if completed.returncode != 0:
        raise ReviewLevelError(f"stats-ilegible: {completed.stderr.strip()[:300]}")
    total = 0
    for line in completed.stdout.split("\0"):
        if not line:
            continue
        fields = line.split("\t", 2)
        if len(fields) < 3:
            raise ReviewLevelError("stats-ilegible: fila incompleta")
        additions, deletions, path = fields[0], fields[1], fields[-1]
        if additions == "-" or deletions == "-":
            raise ReviewLevelError("stats-binario")
        if _is_production(path):
            try:
                total += int(additions) + int(deletions)
            except ValueError as exc:
                raise ReviewLevelError("stats-ilegible: contador") from exc
    return total


def _fail(reason: str) -> Classification:
    """Construye el resultado fail-closed común de la CLI.

    Before: ``reason`` identifica una entrada o recurso ilegible.
    During: fija completo y rc 2 para impedir degradación silenciosa.
    After: devuelve un resultado imprimible aun cuando la entrada sea inválida.
    """
    return _reasoned("completo", reason, 2)


def _parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos sin efectos laterales.

    Before: no requiere estado externo.
    During: declara las referencias, la ficha y el nivel previo opcionales.
    After: devuelve un parser que deja la validación semántica a ``main``.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--reviewed-sha")
    parser.add_argument("--backlog", type=Path)
    parser.add_argument("--ticket")
    parser.add_argument("--brief", type=Path)
    parser.add_argument("--prev-level")
    parser.add_argument("--lower-reason", default="")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    return parser


def _print_result(result: Classification) -> None:
    """Imprime el contrato estable de salida del clasificador.

    Before: ``result`` contiene un nivel y al menos una razón.
    During: escribe una línea de nivel y una línea por razón en stdout.
    After: no modifica archivos ni ejecuta acciones externas.
    """
    print(f"NIVEL={result.level}")
    for reason in result.reasons or ("sin-escalado",):
        print(f"RAZON={reason}")


def _parse_args_or_error(
    argv: Sequence[str] | None,
) -> tuple[argparse.Namespace | None, Classification | None]:
    """Convierte errores de argparse al contrato de salida fail-closed.

    Before: ``argv`` es la secuencia opcional recibida por ``main``.
    During: ejecuta argparse y captura solo su ``SystemExit`` por error.
    After: devuelve argumentos válidos o ``argumentos-invalidos`` con rc 2;
        la petición explícita de ayuda conserva el comportamiento de argparse.
    """
    try:
        return _parser().parse_args(argv), None
    except SystemExit as exc:
        if exc.code == 0:
            raise
        return None, _fail("argumentos-invalidos")


def main(argv: Sequence[str] | None = None) -> int:  # noqa: C901 - fail-closed CLI branches
    """Ejecuta el clasificador CLI fail-closed.

    Before: argv contiene dos referencias y al menos una forma de ficha.
    During: lee la ficha, calcula el diff elegido y aplica el nivel anterior.
    After: imprime ``NIVEL``/``RAZON`` y devuelve 0 o 2; nunca lanza lentes.
    """
    args, parse_error = _parse_args_or_error(argv)
    if parse_error is not None:
        _print_result(parse_error)
        return parse_error.rc
    args = cast(argparse.Namespace, args)
    result: Classification
    try:
        if args.prev_level is not None and args.prev_level not in LEVELS:
            result = _fail("prev-level-ilegible")
        elif args.backlog is None and args.brief is None:
            result = _fail("ficha-ausente")
        elif args.backlog is not None and not args.ticket:
            result = _fail("ticket-ausente")
        else:
            risks: list[FichaRisk] = []
            if args.backlog is not None:
                risks.append(read_ticket_risk(args.backlog, args.ticket))
            if args.brief is not None:
                risks.append(read_brief_risk(args.brief))
            if any(risk.rc != 0 for risk in risks):
                result = _fail(next(risk.reason for risk in risks if risk.rc != 0))
            else:
                left = args.reviewed_sha or args.base
                paths = diff_paths(args.repo, left, args.sha)
                result = classify_paths(
                    paths,
                    production_lines=production_line_count(args.repo, left, args.sha),
                    ficha_high_risk=any(risk.high_risk for risk in risks),
                    diff_empty=not paths,
                )
                if result.rc == 0:
                    previous = apply_previous_level(
                        result.level,
                        previous_level=args.prev_level,
                        lower_reason=args.lower_reason,
                    )
                    result = Classification(
                        previous.level,
                        result.reasons + previous.reasons,
                        previous.rc,
                    )
    except ReviewLevelError as exc:
        result = _fail(str(exc))
    except Exception:
        result = _fail("error-inesperado")
    _print_result(result)
    return result.rc


if __name__ == "__main__":
    raise SystemExit(main())
