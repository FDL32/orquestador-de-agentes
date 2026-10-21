# Follow-up: hook SessionStart emite bytes no-UTF-8 con cwd=destino y la memoria depende del cwd

- **Slug:** `sessionstart-hook-utf8-y-memoria-por-cwd-followup`
- **Fecha:** 2026-10-21
- **Dueno:** decision de usuario para abrir WP
- **Estado:** abierto (hallazgo verificado, sin fix)
- **Origen:** hallazgo de la sesion `fdl32-nan-qwen-backlog-20261020-3d`, REPRODUCIDO de forma
  independiente por la sesion `fdl32-agents-md-sessionstart-palanca-a-2-c2` en la ruta productiva.
- **Referencia:** `.agent/hooks/session_start_hook.py` (`_print_context_safely`),
  `.claude/settings.json` (comando de `SessionStart`).

## Hallazgo 1: salida no UTF-8 con cwd=destino

Reproduccion (comando EXACTO de `.claude/settings.json`, ejecutado con `bash -c`, stdin
`{"hook_event_name":"SessionStart","source":"startup"}`, `python` = Python312 del PATH):

| cwd | bytes totales | bytes no-ASCII | `bytes.decode("utf-8")` estricto |
|---|---|---|---|
| worktree del destino (`orquestador_de_agentes_workspace`) | 38191 | 3 | INVALIDO: byte `0x97` en el offset 1557, contexto `task_id \x97 nunca un subagente` |
| worktree del motor | 33629 | 0 | VALIDO |

`0x97` es la raya (em dash) en cp1252. Causa probable (no demostrada con instrumentacion):
`_print_context_safely` hace `print(payload)` con `ensure_ascii=False`, y solo cae al camino
`backslashreplace` ante `UnicodeEncodeError`; un caracter codificable en la pagina de codigos del
sistema (cp1252) sale en cp1252, no en UTF-8. La memoria del destino contiene ese caracter; la del
motor no.

**NO verificado:** como decodifica Claude Code el stdout del hook. Puede ser solo cosmetico (un
caracter de reemplazo) o puede descartar el contexto entero. Medir esto es el primer paso.

Direccion de fix a evaluar (no aplicada): escribir siempre bytes UTF-8 explicitos en
`sys.stdout.buffer` (`payload.encode("utf-8", errors="backslashreplace")`) en vez de depender de la
codificacion de la consola, o emitir `ensure_ascii=True` (JSON ASCII puro, independiente de la
codificacion). Hay tests de `_print_context_safely` que habria que adaptar.

## Hallazgo 2: la memoria inyectada depende del cwd

Medido por `nan-qwen` (no re-medido aqui): con cwd=motor sin `AGENT_PROJECT_ROOT` el hook inyecta
478 lecciones (solo el archive del motor); con cwd=destino, 684 (478 del motor + 206 del destino,
`wc -l` sobre `archive/observations.*.jsonl`). La cabecera "N lesson(s) travel with this repo" no
nombra las superficies, asi que un agente frio en el motor tiene media memoria sin senal de ello.

Dirección a evaluar: que la cabecera nombre las superficies leidas y su recuento por origen.

## Criterio de salida

- Un test que ejecute el comando de `SessionStart` con cwd=destino y exija `decode("utf-8")`
  estricto sobre la salida real (no un fixture), con una mutacion que lo haga caer.
- La cabecera del indice declara que superficies de memoria se unieron.

## Estado_FRESCO (2026-10-21)

    ESTADO_FRESCO: raiz=<worktree del motor de la sesion sessionstart-palanca-a>, HEAD=99737636, verificado=2026-10-21
