# Loop Run-Log Template (schema + politicas)

> Template canonico del registro de iteraciones por pipeline.
> Cada entrada es una linea JSON (JSONL). El log es APPEND-INMUTABLE:
> las entradas pasadas NO se reescriben ni editan.
> Fuente: WOT-2026-014u. Origen externo: cobusgreyling/loop-engineering.

---

## Schema de entrada (7 campos)

Cada linea del archivo JSONL tiene la siguiente estructura:

```json
{
  "ticket": "<str>",
  "iteration_index": <int>,
  "timestamp_utc": "<ISO 8601>",
  "event": "<str>",
  "tokens": <int | null>,
  "cost_source": "measured | estimated",
  "notes": "<str>"
}
```

### Descripcion de campos

| Campo | Tipo | Descripcion |
|-------|------|-------------|
| ticket | str | ID del ticket activo. Ejemplo: WOT-2026-014u |
| iteration_index | int | Entero incremental por pipeline (0, 1, 2...). NO es timestamp. |
| timestamp_utc | str | Momento en ISO 8601 UTC. Ejemplo: 2026-06-27T10:00:00Z |
| event | str | Descripcion del evento. Ejemplos: iteration_start, gate_passed, review_submitted, changes_requested, iteration_end |
| tokens | int o null | Tokens estimados o medidos. Null si no se mide. |
| cost_source | str | measured o estimated. Ver politica de cost_source. |
| notes | str | Notas adicionales. Si cost_source=estimated, incluir metodo de estimacion. |

---

## Politica de cost_source

- measured: el valor de tokens proviene de un dato real del harness o API de la plataforma LLM.
- estimated: el valor de tokens es una aproximacion calculada por el agente o heuristica.
  El campo notes DEBE incluir el metodo de estimacion.
- PROHIBIDO mezclar entradas measured y estimated sin etiqueta explicita en notes.

---

## Denominador: cost_per_accepted_change (supervivencia git 7 dias)

El denominador de eficiencia de un pipeline es:

  cost_per_accepted_change = total_tokens_pipeline / N

Donde N = numero de cambios cuyo commit de cierre sigue presente en la historia
git del repo_destino 7 dias despues de su merge, sin commit de revert que lo
anule. Verificacion por historia git (heuristica: detecta revert por convencion de subject 'Revert'; un revert manual sin esa palabra no se detecta):

```bash
# 1. Obtener commits de cierre del pipeline:
git log --oneline --since="7 days ago"

# 2. Para cada SHA, verificar que no hay revert posterior:
git log --oneline --all | grep Revert

# 3. N = commits de cierre sin revert verificado
```

La verificacion es por historia git, NO por estado de review ni por campo del
run-log. Un review aprobado que luego es revertido NO cuenta como cambio aceptado.

Este calculo NO se realiza en runtime. El modulo scripts/loop_run_log.py expone
cost_per_accepted_change_note como string explicativo del denominador; el calculo
real requiere acceso al repo_destino 7 dias despues del merge.

---

## Regla append-inmutable

El log en disco es APPEND-ONLY. Las entradas pasadas NO se reescriben ni editan.
Si una iteracion se re-ejecuta, se agrega una nueva entrada SOLO si la clave
(ticket, iteration_index, event) no existe ya en el log.

Nunca borrar entradas del log. Si un pipeline se aborta, registrar un evento
pipeline_aborted en el log en vez de borrar entradas anteriores.

---

## Idempotencia por clave estable

La clave estable de cada entrada es la tupla (ticket, iteration_index, event).

Si se llama al appender con una entrada cuya clave ya existe en el log:
  - La entrada NO se agrega (no-op silencioso).
  - No se lanza error.
  - El log queda exactamente igual.

Esta garantia permite re-ejecutar pasos de un pipeline sin duplicar el log.
El modulo scripts/loop_run_log.py implementa esta garantia en append_entry().

---

## Rotacion de vista (context-window)

El log en disco es completo e inmutable. La vista cargada en el context-window
del agente usa get_truncated_view(n_tail=N) para evitar que el contexto crezca
sin cota.

El default calibrado es N=20 (ultimas 20 entradas + resumen agregado).
Para pipelines de muchas iteraciones, aumentar N con criterio explicito en
el campo notes del loop_budget.md.

El resumen agregado del get_truncated_view incluye:
  - total_entries: total de lineas en el log
  - total_tokens: suma de todos los campos tokens (excluyendo null)
  - cost_per_accepted_change_note: string explicativo del denominador

---

## Ejemplo trabajado con re-run

### Pipeline inicial (iteraciones 0 y 1)

Estado inicial del archivo JSONL tras el pipeline:

```
{"ticket": "WOT-2026-014u", "iteration_index": 0, "timestamp_utc": "2026-06-27T09:00:00Z", "event": "iteration_start", "tokens": 5000, "cost_source": "estimated", "notes": "conteo por tiktoken"}
{"ticket": "WOT-2026-014u", "iteration_index": 0, "timestamp_utc": "2026-06-27T09:15:00Z", "event": "gate_passed", "tokens": 1200, "cost_source": "estimated", "notes": "ruff+pytest verdes"}
{"ticket": "WOT-2026-014u", "iteration_index": 1, "timestamp_utc": "2026-06-27T10:00:00Z", "event": "review_submitted", "tokens": 2000, "cost_source": "estimated", "notes": "manager review"}
{"ticket": "WOT-2026-014u", "iteration_index": 1, "timestamp_utc": "2026-06-27T10:30:00Z", "event": "changes_requested", "tokens": 800, "cost_source": "estimated", "notes": "2 cambios solicitados"}
```

### Re-run de la iteracion 0 (idempotencia)

Si el Builder re-ejecuta la iteracion 0, la llamada a append_entry con la misma
clave (WOT-2026-014u, 0, iteration_start) produce un NO-OP: la entrada ya existe.
El log queda exactamente igual, sin segunda fila. Las 4 entradas originales
permanecen inalteradas (append-inmutable + idempotencia).

### Vista truncada del log

```python
view = get_truncated_view(log_path, n_tail=3)
# view["entries"] contiene las ultimas 3 entradas
# view["summary"]["total_entries"] == 4
# view["summary"]["total_tokens"] == 9000  (5000+1200+2000+800)
# view["summary"]["cost_per_accepted_change_note"] == "<string explicativo denominador git 7 dias>"
```

---

## Uso del modulo scripts/loop_run_log.py

```python
from pathlib import Path
from scripts.loop_run_log import append_entry, get_truncated_view

log_path = Path(".agent/runtime/loop_run_log.jsonl")

# Registrar evento (idempotente):
entry = {
    "ticket": "WOT-2026-014u",
    "iteration_index": 2,
    "timestamp_utc": "2026-06-27T11:00:00Z",
    "event": "iteration_start",
    "tokens": 3000,
    "cost_source": "estimated",
    "notes": "estimacion por promedio de iteraciones previas",
}
append_entry(entry, log_path)

# Obtener vista truncada para el context-window:
view = get_truncated_view(log_path, n_tail=20)
print(view["summary"])
```

La ruta del log es configurable; el modulo no asume una ruta fija.
Recomendado: .agent/runtime/loop_run_log.jsonl (gitignored como runtime artifact).
