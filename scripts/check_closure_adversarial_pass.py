#!/usr/bin/env python3
r"""Pasada adversarial BLOQUEANTE sobre el informe de cierre y la propuesta de memoria.

Before (Pre-condiciones):
  - El fichero sidecar JSON debe existir en la ruta recibida por --sidecar.
  - El archivo debe ser JSON valido, codificado en UTF-8.
  - Debe contener al menos las claves: "ticket" (str), "lentes" (list[dict]).
  - Cada lente debe tener: "backend" (str), "verdict" (str), "hallazgos" (list[dict]).
  - Cada hallazgo debe tener: "texto" (str), "evidence" (str, opcional).

During (Proceso y Recursos):
  - Lee el sidecar JSON y valida su estructura (campos obligatorios, tipos).
  - Exige >= 2 lentes.
  - Exige que las lentes tengan backends de clase distinta (no repetidos).
  - Para cada hallazgo, valida que su campo "evidence" case un patron verificable:
    - exit code: `exit 0`, `exit 1`, `exit 2`, ... o `exit code N` o `rc=N`
    - ruta con linea: `<ruta>:<numero>` (ej. `file.py:42`) -- exige al menos un `.` (extension),
      `/` o `\` (separador) en la ruta antes de los dos puntos
    - timestamp ISO: `YYYY-MM-DD` o `YYYY-MM-DDTHH:MM` o `YYYY-MM-DDTHH:MM:SS`
  - Un hallazgo sin evidence, con evidence vacia, o que no case el patron es RECHAZADO.
  - Imprime un recuento explicito: lentes vistas, hallazgos con evidencia valida,
    hallazgos sin evidencia o invalidos.

After (Post-condiciones y Errores):
  - Exit 0 si todo es valido (>= 2 lentes, backends distintos, toda evidencia case patron).
  - Exit 1 si hay cualquier violation (fichero no existe, JSON invalido, < 2 lentes,
    backends repetidos, evidencia faltante/invalida).
  - Nunca deja excepcion sin capturar: try/except explicito, reporta por stdout/stderr.
  - El regex de evidencia es la unica barrera de formato: el auditor humano verifica
    la calidad del contenido citado.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


# Patron de evidencia verificable:
# - exit code: `exit N`, `exit code N`, `exitcode N`, o `rc=N`
# - ruta con linea: camino con `.` o `/` o `\`:`numero` (ej. `file.py:42`, `scripts/x.py:10`)
# - timestamp ISO-ish: `YYYY-MM-DD` o `YYYY-MM-DD[THH:MM[:SS]]`
EVIDENCE_PATTERN = re.compile(
    r"(exit\s+\d+|exitcode\s+\d+|exit code\s+\d+|rc=\d+|\S*[./\\]\S*:\d+|\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?)"
)


# ---------------------------------------------------------------------------
# Validacion de hallazgos individuales (Cyclomatic <= 4)
# ---------------------------------------------------------------------------


def _validate_hallazgo(hallazgo: object, prefix: str, errors: list[str]) -> bool:
    """Valida un hallazgo individual. Retorna True si es valido.

    Reglas: debe tener campo 'evidence' (str no vacio) que case EVIDENCE_PATTERN.
    """
    if not isinstance(hallazgo, dict):
        errors.append(f"{prefix}: debe ser un objeto JSON")
        return False

    if "evidence" not in hallazgo:
        errors.append(f"{prefix}: hallazgo sin campo 'evidence'")
        return False

    evidence = hallazgo["evidence"]
    if not isinstance(evidence, str):
        errors.append(
            f"{prefix}: 'evidence' debe ser string, no {type(evidence).__name__}"
        )
        return False

    if evidence == "":
        errors.append(
            f"{prefix}: 'evidence' esta vacio en: "
            f"{hallazgo.get('texto', '<sin-texto>')}"
        )
        return False

    if not EVIDENCE_PATTERN.search(evidence):
        errors.append(
            f"{prefix}: 'evidence' no case patron verificable "
            f"(exit/ruta:linea/timestamp ISO): {evidence}"
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Validacion por lente individual (Cyclomatic <= 4)
# ---------------------------------------------------------------------------


def _validate_lente(
    lente: object, idx: int, backends: list[str], errors: list[str]
) -> None:
    """Valida una lente individual y registra su backend en *backends*."""
    prefix = f"Lente[{idx}]"
    if not isinstance(lente, dict):
        errors.append(f"{prefix}: debe ser un objeto JSON")
        return

    backend_val = lente.get("backend")
    if backend_val is None:
        errors.append(f"{prefix}: falta campo 'backend'")
        backends.append("<sin-backend>")
    elif not isinstance(backend_val, str):
        errors.append(f"{prefix}: 'backend' debe ser string")
        backends.append(backend_val)
    else:
        backends.append(backend_val)

    verdict_val = lente.get("verdict")
    if verdict_val is None:
        errors.append(f"{prefix}: falta campo 'verdict'")
    elif not isinstance(verdict_val, str):
        errors.append(f"{prefix}: 'verdict' debe ser string")

    hallazgos = lente.get("hallazgos")
    if hallazgos is None:
        errors.append(f"{prefix}: falta campo 'hallazgos'")
        return
    if not isinstance(hallazgos, list):
        errors.append(f"{prefix}: 'hallazgos' debe ser una lista")
        return

    for hidx, hallazgo in enumerate(hallazgos):
        _validate_hallazgo(hallazgo, f"{prefix}.hallazgo[{hidx}]", errors)


# ---------------------------------------------------------------------------
# Validacion del sidecar completo
# ---------------------------------------------------------------------------


def validate_sidecar(data: object) -> tuple[bool, list[str]]:
    """Valida la estructura y contenido del sidecar JSON.

    Args:
        data: El objeto parsed JSON (dict con "ticket" y "lentes").

    Returns:
        Tuple (ok: bool, errors: list[str]). ok es True solo si pasa todas las validaciones.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return False, [
            "El sidecar debe ser un objeto JSON (dict), no " + type(data).__name__
        ]

    if "ticket" not in data:
        errors.append("Falta campo obligatorio: 'ticket'")
    elif not isinstance(data["ticket"], str):
        errors.append("El campo 'ticket' debe ser string")

    if "lentes" not in data:
        errors.append("Falta campo obligatorio: 'lentes'")
        return False, errors

    lentes = data["lentes"]
    if not isinstance(lentes, list):
        errors.append("El campo 'lentes' debe ser una lista")
        return False, errors

    if len(lentes) < 2:
        errors.append(f"Se requieren al menos 2 lentes, encontradas {len(lentes)}")

    backends: list[str] = []
    for idx, lente in enumerate(lentes):
        _validate_lente(lente, idx, backends, errors)

    if len(backends) != len(set(backends)):
        counts = Counter(backends)
        repeated = [k for k, v in counts.items() if v > 1]
        errors.append(
            "Las lentes deben tener backends de clase distinta. "
            f"Repetidos: {', '.join(repeated)}"
        )

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Lectura del sidecar (separa filesystem de logica de negocio)
# ---------------------------------------------------------------------------


def _read_sidecar(path_str: str) -> tuple[object | None, str | None]:
    """Lee y parsea el sidecar JSON. Retorna (data, error_msg | None)."""
    try:
        sidecar_path = Path(path_str)
        if not sidecar_path.is_file():
            return None, f"sidecar no encontrado: {path_str}"
        raw = sidecar_path.read_bytes()
        try:
            return json.loads(raw.decode("utf-8")), None
        except json.JSONDecodeError as exc:
            return None, f"JSON invalido: {exc}"
        except UnicodeDecodeError as exc:
            return None, f"sidecar no UTF-8: {exc}"
    except OSError as exc:
        return None, f"no se pudo leer {path_str}: {exc}"


# ---------------------------------------------------------------------------
# Conteo de hallazgos (separado del main para reducir cyclomatic complexity)
# ---------------------------------------------------------------------------


def _count_hallazgos(data: object) -> tuple[int, int, int]:
    """Cuenta lentes, hallazgos con evidencia valida y sin evidencia.

    Returns (lentes_count, hallazgos_validos, hallazgos_invalidos).
    """
    lentes_count = 0
    hallazgos_validos = 0
    hallazgos_invalidos = 0

    if isinstance(data, dict) and isinstance(data.get("lentes"), list):
        lentes_count = len(data["lentes"])
        for lente in data["lentes"]:
            if isinstance(lente, dict):
                hallazgos = lente.get("hallazgos", [])
                if isinstance(hallazgos, list):
                    for h in hallazgos:
                        if isinstance(h, dict):
                            ev = h.get("evidence", "")
                            if (
                                isinstance(ev, str)
                                and ev
                                and EVIDENCE_PATTERN.search(ev)
                            ):
                                hallazgos_validos += 1
                            else:
                                hallazgos_invalidos += 1

    return lentes_count, hallazgos_validos, hallazgos_invalidos


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry-point: parsea --sidecar, valida, imprime recuento, retorna exit code."""
    try:
        parser = argparse.ArgumentParser(
            description="Valida el sidecar de la pasada adversarial de cierre."
        )
        parser.add_argument(
            "--sidecar",
            required=True,
            help="Ruta al sidecar JSON con el resultado de las lentes.",
        )
        args = parser.parse_args()

        data, err = _read_sidecar(args.sidecar)
        if err is not None:
            print(f"ERROR: {err}", file=sys.stderr)
            return 1

        ok, errors = validate_sidecar(data)
        lentes_count, hallazgos_validos, hallazgos_invalidos = _count_hallazgos(data)

        print(f"lentes_vistas={lentes_count}")
        print(f"hallazgos_con_evidencia={hallazgos_validos}")
        print(f"hallazgos_sin_evidencia={hallazgos_invalidos}")

        if ok:
            print("PASADA ADVERSARIAL: OK")
            return 0
        else:
            for e in errors:
                print(f"RECHAZO: {e}", file=sys.stderr)
            print("PASADA ADVERSARIAL: RECHAZADO", file=sys.stderr)
            return 1

    except Exception as exc:
        print(f"ERROR inesperado: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
