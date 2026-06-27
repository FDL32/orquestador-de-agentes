"""
Modulo stdlib-only para registro idempotente de iteraciones de pipeline.

Implementa append-inmutable con clave estable (ticket, iteration_index, event).
Solo usa modulos de la libreria estandar: json, pathlib.
"""

import json
from pathlib import Path


def append_entry(entry: dict, log_path: Path) -> None:
    """
    Agrega una entrada al log JSONL de forma idempotente (append-inmutable).

    Before:
        - entry debe contener al menos los campos "ticket", "iteration_index"
          y "event" para formar la clave estable de deduplicacion.
        - log_path puede no existir (se creara en la primera llamada).
        - No se requiere ningun lock externo; el modulo hace append atomico
          por linea.

    During:
        - Valida que entry contiene los 3 campos de clave con valor no-None
          (ticket, iteration_index, event). Si falta alguno, lanza ValueError
          antes de tocar el disco (fail-loud, no perdida silenciosa).
        - Lee log_path si existe y extrae la clave (ticket, iteration_index,
          event) de cada linea JSON valida.
        - Si la clave de entry ya existe en el log: retorna sin error (no-op).
        - Si la clave es nueva: abre log_path en modo append ("a") y escribe
          json.dumps(entry) seguido de un salto de linea.
        - El log previo no se reescribe: solo se anaden nuevas lineas al final.

    After:
        - Si la clave era nueva: log_path contiene la nueva entrada al final.
        - Si la clave ya existia: log_path queda exactamente igual (idempotente).
        - Lanza ValueError si falta alguno de los campos de clave (ticket,
          iteration_index, event) o su valor es None.
        - No lanza excepcion si la entrada es duplicada (clave ya existe).
        - Lanza json.JSONDecodeError si una linea existente del log no es JSON
          valido (indicador de corrupcion, no se silencia).

    Args:
        entry: Diccionario con los campos de la entrada. Debe incluir "ticket",
               "iteration_index" y "event". Campos adicionales se preservan.
        log_path: Ruta al archivo JSONL del run-log.
    """
    required = ("ticket", "iteration_index", "event")
    missing = [k for k in required if entry.get(k) is None]
    if missing:
        raise ValueError(f"loop_run_log entry missing dedup key field(s): {missing}")

    existing_keys: set[tuple] = set()

    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            key = (
                parsed.get("ticket"),
                parsed.get("iteration_index"),
                parsed.get("event"),
            )
            existing_keys.add(key)

    entry_key = (entry.get("ticket"), entry.get("iteration_index"), entry.get("event"))
    if entry_key in existing_keys:
        return

    with log_path.open("a", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(entry) + "\n")


def get_truncated_view(log_path: Path, n_tail: int = 20) -> dict:
    """
    Retorna una vista truncada del log para uso en context-window del agente.

    Before:
        - log_path puede existir o no. Si no existe, se retorna un dict vacio.
        - n_tail debe ser un entero positivo. El default 20 es el calibrado
          para contextos operativos estandar.

    During:
        - Lee todas las entradas del log JSONL (lineas validas, no vacias).
        - Calcula el total de entradas y la suma de tokens (ignorando null).
        - Retorna las ultimas n_tail entradas y un resumen agregado.
        - No modifica el log en disco.

    After:
        - Retorna dict con dos claves:
            "entries": lista de los ultimos n_tail dicts (o todos si hay menos).
            "summary": dict con:
                "total_entries": int, total de lineas validas en el log.
                "total_tokens": int, suma de campo "tokens" (excluyendo null).
                "cost_per_accepted_change_note": str, descripcion del denominador.
        - Si log_path no existe: entries=[], total_entries=0, total_tokens=0.

    Args:
        log_path: Ruta al archivo JSONL del run-log.
        n_tail: Numero maximo de entradas a retornar en "entries". Default: 20.

    Returns:
        dict con claves "entries" y "summary".
    """
    if not log_path.exists():
        return {
            "entries": [],
            "summary": {
                "total_entries": 0,
                "total_tokens": 0,
                "cost_per_accepted_change_note": _cost_note(),
            },
        }

    all_entries = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        all_entries.append(json.loads(line))

    total_tokens = sum(
        e.get("tokens") or 0 for e in all_entries if e.get("tokens") is not None
    )

    return {
        "entries": all_entries[-n_tail:],
        "summary": {
            "total_entries": len(all_entries),
            "total_tokens": total_tokens,
            "cost_per_accepted_change_note": _cost_note(),
        },
    }


def _cost_note() -> str:
    """
    Retorna el string explicativo del denominador cost_per_accepted_change.

    El denominador N es el numero de cambios cuyo commit de cierre sigue
    presente en la historia git del repo_destino 7 dias despues de su merge,
    sin commit de revert que lo anule. Verificacion por historia git, no por
    estado de review. El calculo real requiere acceso al repo_destino post-merge.
    """
    return (
        "cost_per_accepted_change = total_tokens / N, donde N = commits de cierre "
        "presentes en historia git del repo_destino 7 dias despues del merge, sin revert. "
        "Verificacion por historia git (heuristica: detecta revert por convencion de subject 'Revert'; un revert manual sin esa palabra no se detecta)."
    )
