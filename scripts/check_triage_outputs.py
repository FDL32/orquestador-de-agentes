#!/usr/bin/env python3
"""Gate de FORMA sobre el artefacto de salida del triaje (WOT-2026-071b).

El cierre de sesiones de diseno valida los PLANES de `queued/`, pero los
ARTEFACTOS de salida del triaje (`backlog_triage_*.json` + su par `.md`) no
tenian ninguna puerta. Este guard localiza el triaje mas reciente auditable,
lo pasa por `validate_batch_dag.py` y anade las claves del contrato PRODUCTOR
(`prompts/backlog_triage.md`) que el validador del consumidor no mira:
`generated_at`/`state_at_triage`/`stop_policy`/`budget`, el `evidence_label` y
`artifact` del roster, y el `surface_scan` por grupo. Falla cerrado citando
fichero y error.

Uso:
    python scripts/check_triage_outputs.py --project-root <workspace> [--require-artifact]

Salida:
- Exit 0 con `ficheros auditados: <M>` (M >= 2) nombrando el JSON auditado.
- Exit 0 con `SKIP` NOMBRADO si no hay artefacto candidato y no se pidio
  `--require-artifact` (nunca un exit 0 silencioso).
- Exit 1 ante el primer fallo de la cadena (a)-(f), citando fichero y error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# El JSON del triaje vive bajo `<workspace>/orchestrator_pipeline/reports/`.
_REPORTS_REL = Path("orchestrator_pipeline") / "reports"

# Regex ANCLADA: solo nombres canonicos del productor. Excluye por construccion
# las tumbas legacy (`backlog_triage_output.*`, solo-fecha sin hora) y cualquier
# fichero con sufijo tras el timestamp (`*_priority_score_evidence.json`,
# `*_corrected_v2.json`). Acepta la variante real `backlog_triage_batch_<ts>`.
_TRIAGE_JSON_RE = re.compile(
    r"backlog_triage_(?P<batch>batch_)?(?P<date>\d{8})[-_](?P<time>\d{4,6})\.json"
)

# Claves top-level del contrato productor (`prompts/backlog_triage.md`,
# seccion "Salida obligatoria"). Fuente: el prompt que PRODUCE el artefacto.
_REQUIRED_TOP = (
    "schema",
    "generated_at",
    "state_at_triage",
    "groups",
    "stop_policy",
    "budget",
)
_STATE_KEYS = ("motor", "workspace", "dirty")
# Mismo enum que `validate_batch_dag._VALID_EVIDENCE_LABELS`: se copia del
# contrato productor, no se reconstruye de memoria.
_VALID_EVIDENCE_LABELS = {"VERIFICADO", "INFERIDO", "REQUIERE_HUMANO"}
# Tipo de cada clave de `surface_scan` (contrato productor, Fase 2).
_SURFACE_SCAN_TYPES = {"executed": bool, "coverage": str, "method": str}

_PREFIX = "[triage-exit]"


def _stamp_key(name: str) -> tuple[str, str] | None:
    """(fecha, hora-padded) del nombre de un triaje candidato, o None.

    Before: `name` es el nombre de fichero (sin ruta).
    During: puro; `fullmatch` de la regex anclada. La hora se rellena a 6
        digitos por la derecha para comparar numericamente anchos de 4 y 6.
    After: `(YYYYMMDD, HHMMSSo)` o None si no es candidato. Nunca lanza.
    """
    match = _TRIAGE_JSON_RE.fullmatch(name)
    if match is None:
        return None
    return (match.group("date"), match.group("time").ljust(6, "0"))


def locate_latest_triage(reports_dir: Path) -> tuple[Path | None, list[str]]:
    """Triaje candidato mas reciente + ficheros no-candidata encontrados.

    Before: `reports_dir` es el directorio de reportes del workspace.
    During: puro I/O de lectura. Candidatas = ficheros cuyo nombre casa
        COMPLETAMENTE con `_TRIAGE_JSON_RE`. Orden: por (fecha, hora)
        descendente; empate exacto -> gana el NO-batch (nombre canonico del
        productor); empate residual -> lexicografico descendente.
    After: `(json_path, [no-candidata `backlog_triage_*`])`. `(None, others)`
        si el directorio no existe o no hay candidata. Nunca lanza.
    """
    if not reports_dir.is_dir():
        return None, []
    candidates: list[tuple[Path, re.Match[str]]] = []
    others: list[str] = []
    for path in sorted(reports_dir.iterdir()):
        if not path.is_file():
            continue
        match = _TRIAGE_JSON_RE.fullmatch(path.name)
        if match is not None:
            candidates.append((path, match))
        elif path.name.startswith("backlog_triage_"):
            others.append(path.name)
    if not candidates:
        return None, others

    # Sorts estables aplicados de menor a mayor precedencia.
    candidates.sort(key=lambda item: item[0].name, reverse=True)
    candidates.sort(key=lambda item: 0 if item[1].group("batch") is None else 1)
    candidates.sort(
        key=lambda item: (
            item[1].group("date"),
            item[1].group("time").ljust(6, "0"),
        ),
        reverse=True,
    )
    return candidates[0][0], others


def _parse_iso8601(value: str) -> datetime | None:
    """`datetime` de un string ISO-8601, tolerando el sufijo `Z`; o None.

    Before: `value` es el valor crudo de `generated_at`.
    During: puro; normaliza `Z` a `+00:00` y delega en `fromisoformat`.
    After: `datetime` o None si no es parseable. Nunca lanza.
    """
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _check_top_level(data: dict) -> str | None:
    """Claves top-level requeridas del contrato productor (paso (c)).

    Before: `data` es el objeto raiz ya parseado del JSON de triaje.
    During: puro; comprueba presencia y forma de las claves obligatorias.
    After: mensaje de error concreto, o None si todas estan presentes y son
        del tipo correcto.
    """
    missing = [key for key in _REQUIRED_TOP if key not in data]
    if missing:
        return f"faltan claves top-level requeridas: {missing}"
    generated = data.get("generated_at")
    if not isinstance(generated, str):
        return "'generated_at' debe ser un string ISO-8601"
    if _parse_iso8601(generated) is None:
        return f"'generated_at' no es ISO-8601 parseable: {generated!r}"
    state = data.get("state_at_triage")
    if not isinstance(state, dict):
        return "'state_at_triage' debe ser un objeto"
    missing_state = [key for key in _STATE_KEYS if key not in state]
    if missing_state:
        return f"'state_at_triage' no declara {missing_state}"
    if not isinstance(data.get("groups"), list):
        return "'groups' debe ser una lista (vacia es valida)"
    if not isinstance(data.get("stop_policy"), dict):
        return "'stop_policy' debe ser un objeto"
    if not isinstance(data.get("budget"), dict):
        return "'budget' debe ser un objeto"
    return None


def _check_roster(data: dict) -> str | None:
    """`evidence_label` y `artifact` del roster (paso (d)).

    Solo aplica si `tickets[]` es un roster (alguna entrada declara
    `classification` o `evidence_label`). Cada entrada SIN `note` (una nota es
    una exclusion auto-evidente) debe declarar un `evidence_label` valido y la
    clave `artifact` (el valor puede ser null). Misma regla de forma que
    `validate_batch_dag`, mas la clave `artifact` que el validador no mira.

    Before: `data` es el objeto raiz del JSON.
    During: puro; solo lee `tickets[]`.
    After: mensaje de error concreto, o None si el roster es conforme.
    """
    entries = data.get("tickets")
    if not isinstance(entries, list):
        return None
    is_roster = any(
        isinstance(entry, dict)
        and ("classification" in entry or "evidence_label" in entry)
        for entry in entries
    )
    if not is_roster:
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("note") or "").strip():
            continue
        ticket = entry.get("id", "<sin id>")
        if entry.get("evidence_label") not in _VALID_EVIDENCE_LABELS:
            return (
                f"ticket '{ticket}' de tickets[] declara evidence_label "
                f"{entry.get('evidence_label')!r} invalido/ausente; debe ser uno de "
                f"{sorted(_VALID_EVIDENCE_LABELS)}"
            )
        if "artifact" not in entry:
            return f"ticket '{ticket}' de tickets[] no declara la clave 'artifact'"
    return None


def _check_surface_scan(data: dict) -> str | None:
    """`surface_scan` obligatorio en CADA grupo no vacio (paso (e)).

    Strictness DELIBERADA: se exige en todos los grupos, mas estricto que
    `validate_batch_dag` (que solo lo exige en grupos raiz /v2). El exit gate
    audita el contrato del PRODUCTOR (`prompts/backlog_triage.md`), que declara
    el scan sobre el FLT y bloquea el SILENCIO, no la ausencia de dato
    (`{executed: false, ...}` es una declaracion honesta y pasa).

    Before: `data` es el objeto raiz del JSON.
    During: puro; recorre `groups[]`.
    After: mensaje de error concreto, o None si todos los grupos lo declaran
        con sus tres claves del tipo correcto.
    """
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        return None
    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("id", "<sin id>")
        raw = group.get("surface_scan")
        if raw is None:
            return (
                f"grupo '{gid}': falta 'surface_scan' -- el contrato productor "
                "(backlog_triage.md Fase 2) bloquea el SILENCIO de superficie"
            )
        if not isinstance(raw, dict):
            return (
                f"grupo '{gid}': 'surface_scan' debe ser un objeto "
                "{executed, coverage, method}"
            )
        for key, expected in _SURFACE_SCAN_TYPES.items():
            value = raw.get(key)
            if value is None:
                return (
                    f"grupo '{gid}': 'surface_scan' no declara '{key}' "
                    f"({expected.__name__})"
                )
            if not isinstance(value, expected):
                return (
                    f"grupo '{gid}': 'surface_scan.{key}' debe ser "
                    f"{expected.__name__}, no {type(value).__name__}"
                )
    return None


def _run_tool(tool: Path, args: list[str]) -> subprocess.CompletedProcess[str] | str:
    """Ejecuta un script hermano con `sys.executable`; devuelve su resultado o error.

    Before: `tool` es la ruta absoluta del script; `args` sus argumentos.
    During: un unico `subprocess.run` con captura de stdout/stderr. Sin shell.
    After: `CompletedProcess` con `returncode`, o un string con el error de
        invocacion (OSError) para que el caller lo cite. Nunca lanza.
    """
    try:
        return subprocess.run(  # noqa: S603
            [sys.executable, str(tool), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return f"no se pudo invocar {tool.name}: {exc}"


def _audit_candidate(json_path: Path, sibling_md: Path) -> str | None:
    """Cadena de validacion (b)-(f) sobre la candidata. Error concreto o None.

    Before: `json_path` y su `sibling_md` existen (el paso (a) ya corrio en
        `check_triage_outputs`).
    During: (b) valida el DAG via `validate_batch_dag.py`; parsea el JSON;
        (c) claves top-level; (d) roster; (e) `surface_scan`; (f) encoding
        guard sobre el par. Fail-closed: el primer fallo corta.
    After: None si toda la cadena pasa; un string con el error concreto si
        algo falla (el caller antepone el fichero). Nunca lanza: los
        subprocess capturan OSError y el parseo captura JSONDecodeError/OSError.
    """
    scripts_dir = Path(__file__).resolve().parent
    validator = scripts_dir / "validate_batch_dag.py"
    result = _run_tool(validator, [str(json_path)])
    if isinstance(result, str):
        return result
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return f"validate_batch_dag.py exit {result.returncode}: {detail}"

    try:
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"JSON ilegible/no parseable: {exc}"
    if not isinstance(data, dict):
        return "la raiz del JSON debe ser un objeto"

    for check in (_check_top_level, _check_roster, _check_surface_scan):
        error = check(data)
        if error:
            return error

    encoding_guard = scripts_dir / "check_encoding_guard.py"
    result = _run_tool(encoding_guard, [str(sibling_md), str(json_path)])
    if isinstance(result, str):
        return result
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return f"check_encoding_guard.py exit {result.returncode}: {detail}"
    return None


def check_triage_outputs(project_root: Path, require_artifact: bool = False) -> int:
    """Audita el triaje mas reciente del workspace. Devuelve el exit code.

    Before: `project_root` es el workspace (los reportes viven bajo
        `<project_root>/orchestrator_pipeline/reports/`).
    During: localiza la candidata mas reciente, exige el par `.md` (paso (a)) y
        delega (b)-(f) en `_audit_candidate`, fail-closed.
    After: 0 con la linea `ficheros auditados: <M>` (M >= 2) nombrando el JSON;
        0 con SKIP nombrado si no hay candidata y no se pidio `--require-artifact`;
        1 ante un fallo, o si `--require-artifact` y no hay artefacto (cita el
        directorio y lista las no-candidatas).
    """
    reports_dir = Path(project_root) / _REPORTS_REL
    json_path, others = locate_latest_triage(reports_dir)

    if json_path is None:
        listing = ", ".join(others) if others else "(ninguno)"
        if require_artifact:
            print(
                f"{_PREFIX} FAIL: no hay triaje candidato en {reports_dir}; "
                f"ficheros no-candidata: {listing}",
                file=sys.stderr,
            )
            return 1
        print(
            f"{_PREFIX} SKIP: no hay triaje candidato en {reports_dir} "
            f"({len(others)} fichero(s) no-candidata). Nada que auditar."
        )
        return 0

    sibling_md = json_path.with_suffix(".md")
    if not sibling_md.is_file():
        print(
            f"{_PREFIX} FAIL: {json_path}: par incompleto: falta el .md hermano "
            f"{sibling_md.name}",
            file=sys.stderr,
        )
        return 1

    error = _audit_candidate(json_path, sibling_md)
    if error:
        print(f"{_PREFIX} FAIL: {json_path}: {error}", file=sys.stderr)
        return 1

    print(f"{_PREFIX} OK: ficheros auditados: 2 ({json_path.name}, {sibling_md.name})")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI: `--project-root <workspace>` [--require-artifact]."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--project-root",
        required=True,
        type=Path,
        help="Workspace cuyo orchestrator_pipeline/reports/ se audita.",
    )
    parser.add_argument(
        "--require-artifact",
        action="store_true",
        help=(
            "Exigir la existencia de un triaje candidato: sin artefacto, falla "
            "citando el directorio y las no-candidatas (en vez de SKIP)."
        ),
    )
    args = parser.parse_args(argv)
    return check_triage_outputs(args.project_root, args.require_artifact)


if __name__ == "__main__":
    sys.exit(main())
