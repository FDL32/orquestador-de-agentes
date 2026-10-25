---
role: orchestrator
route_kind: mantenimiento
---
# Prompt: Curacion de memoria -- mecanismo Builder+Revisor de doble pasada

<!-- PROMPT-SUMMARY
what: Mecanismo de doble pasada Builder+Revisor sobre memoria curada en disco. El Builder propone candidatos a redundancia citando la prosa posterior donde la conclusion ya aparece literal; el Revisor objeta; el script aplica invariantes deterministas conservadores.
when: Cuando el usuario invoca explicitamente el mecanismo via python scripts/curate_memory.py --help. Disparador manual, nunca programado.
not: NO es el ciclo de compactacion de Claude Code (pre_compact_hook.py). NO integra additionalContext de pre_compact_hook.py (bloqueado por WOT-2026-041y).
-->

> **Modo:** recolector y aplicador de invariantes (script `scripts/curate_memory.py`)
> que consume ficheros de juicio producidos externamente por dos backends DISTINTOS
> (Builder y Revisor, ver `prompts/persona_system.md` Seccion 2). El script NUNCA
> invoca un LLM ni escribe sobre el fichero fuente.

contract_id: cid-memory-curation-v1
Script canonico: scripts/curate_memory.py (3 subcomandos).
Contrato de artefactos: bundle.json, candidates.json, objections.json.
Hermano de `prompts/doc_optimization.md` y `prompts/memory_optimization.md`
(estructura frontmatter + PROMPT-SUMMARY).

## Disparador

EXCLUSIVAMENTE manual: `python scripts/curate_memory.py --help`.
NUNCA cron, NUNCA parte del ciclo de compactacion de Claude Code.

## Sintaxis de los 3 subcomandos

### 1. export-bundle

```
python scripts/curate_memory.py export-bundle \
  --source PATH_OBSERVATIONS.JSONL \
  [--text-field signal] \
  --out RUTA_BUNDLE.json
```

Lee el JSONL linea a linea, parsea cada linea como JSON (lineas no parseables se saltan con aviso por stderr), extrae el campo `--text-field` (default `signal`) y emite un JSON con clave `entries`, lista de objetos `{index, text, timestamp}`, indexados 0-based.

### 2. apply

```
python scripts/curate_memory.py apply \
  --source PATH_OBSERVATIONS.JSONL \
  --proposal CANDIDATOS.json \
  --objections OBJECIONES.json \
  --output CURADA.jsonl \
  --report INFORME.md \
  [--last-n 20] \
  [--text-field signal]
```

- `CANDIDATOS.json`: objeto con clave `candidates`, lista de `{index, citation_index, reason}` (producido por el Builder de memoria).
- `OBJECIONES.json`: objeto con clave `objections`, lista de `{index, reason}` (producido por el Revisor de memoria).
- Un candidato i se descarta SOLO SI se cumplen las 4 condiciones a la vez:
  1. **Sin objecion del Revisor**: i no aparece en ningun `objections` index.
  2. **Fuera de last-n**: i < total_entradas - last_n.
  3. **Cita literal valida**: el texto de citation_index contiene (via `in` de Python tras normalizar con `lower()` y `strip()`) el texto normalizado de i.
  4. **No protegido**: el texto de i no matchea ningun patron de `is_protected()`.
- Si CUALQUIERA falla, el candidato se CONSERVA verbatim byte-a-byte.
- Escribe `CURADA.jsonl` (lineas RAW originales, sin re-serializar JSON) y `INFORME.md` con conteos antes/despues, tabla de descartados y tabla de sobrevivientes con motivo.

### 3. --help

```
python scripts/curate_memory.py --help
```

Describe los 3 subcomandos y sus flags. Exit code 0.

## Contrato de artefactos

### bundle.json

```json
{
  "entries": [
    {"index": 0, "text": "...", "timestamp": "2026-10-25T..."},
    ...
  ]
}
```

Producido por `export-bundle`. Lectura solo.

### candidates.json

```json
{
  "candidates": [
    {"index": 3, "citation_index": 7, "reason": "redundante"},
    ...
  ]
}
```

Producido por el **Builder de memoria** (Backend A). Referencia a `prompts/persona_system.md` Seccion 2 para el rol.

### objections.json

```json
{
  "objections": [
    {"index": 3, "reason": "conservar por X"},
    ...
  ]
}
```

Producido por el **Revisor de memoria** (Backend B, DISTINTO del Builder). Referencia a `prompts/persona_system.md` Seccion 2 para el rol.

## Invariantes cableados en codigo

Los 4 invariantes se verifican en `scripts/curate_memory.py::is_protected` y la logica de `apply`:

1. **Cita literal verificable**: el operador `in` de Python tras normalizar `lower()`/`strip()`. Si la cita es invalida (indice no existe) o la subcadena no aparece, se conserva.
2. **Ventana last-n**: los ultimos N indices del source se protegen siempre.
3. **Objecion del Revisor**: si el Revisor objeto un indice, el script lo conserva (el script nunca ignora objeciones).
4. **Patrones protegidos** (`is_protected`):
   - (i) `exit_code` / `exit code` (case-insensitive).
   - (ii) Hex token 7-40 chars como palabra completa (SHA candidato).
   - (iii) Conteo de tests: numero + tests/test/passed/failed.
   - (iv) Path de fichero: separador + nombre con extension.

Cualquiera de los 4 -> se CONSERVA. Solo si los 4 pasan -> se descarta.

## Artefacto de salida

- `CURADA.jsonl`: linea RAW verbatim de las entradas que no se descartaron.
- `INFORME.md`: markdown con conteos antes/despues, tabla de descartados, tabla de sobrevivientes.

## Non-goals

- **Integracion con additionalContext de `pre_compact_hook.py`**: FUERA de este mecanismo.
  Bloqueado por `WOT-2026-041y` (dos disenos motor/destino sin converger, sin decidir cual es canonico).
  La integracion con la seccion Memoria de `additionalContext` que proyecta `pre_compact_hook.py`
  queda FUERA de este mecanismo hasta que `WOT-2026-041y` resuelva cual diseno (motor o destino)
  es el canonico.
- No invoca LLMs desde dentro del script.
- No promueve `CURADA.jsonl` como sustituto de `observations.jsonl` en produccion.
- No implementa disparador programado/cron.
