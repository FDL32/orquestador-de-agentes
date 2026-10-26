# Plan de Trabajo: `create_worktree_pair.py --base-ref` + gating de verificacion

## Metadata
- **ID:** WOT-2026-129b
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-10-26
- **Prioridad:** MEDIA
- **Asignado a:** Builder

## Objetivo
`create_worktree_pair.py` crea las ramas del par desde el HEAD del checkout
principal (puede ir cientos de commits atrasado) y su sumario dice
"worktree pair creado" aunque la verificacion falle. Anadir `--base-ref`
(default `origin/main`, aplicado a motor y destino cada uno contra su
propio remoto) y gatear el mensaje de exito por el resultado real de
`collect_session_state.py`.

## Contexto
Medido en vivo (HEAD def13f4a): `git_worktree_add` no toma punto de
partida; `run_verify` es solo-recolector y su rc se ignora en el sumario.
Interino del vuelo: la orquestadora crea el par a mano con `--base-ref`
literal. Decision de diseno completa (incluyendo por que NO se toca
`write_link()`, y como quedan los 8 tests existentes verdes con el nuevo
default) en `STRATEGY_WOT-2026-129b.md` -- leerla ENTERA antes de tocar el
fichero.

## Decision Arquitectonica
Cambio local en 2 funciones (`git_worktree_add`, el bloque final de
`main()`) + 1 funcion nueva (`resolve_start_point`). No altera `write_link`
ni ninguna interfaz publica consumida fuera de este script. Detalle en
STRATEGY.

## Non-goals
- `write_link()` / schema del link (`ticket_prefix`/`destination_id`):
  WOT-2026-126d, no se toca.
- Comportamiento de `uv_sync_failed`: fuera de alcance, no cambia.

## Plan de Implementacion

### Fase 1: `--base-ref`
#### 1.1: `resolve_start_point()` + cableado en `main()` y `git_worktree_add()`
- **Tipo:** TAREA AGENTE
- **Accion:** Modificar `scripts/create_worktree_pair.py`
- **Descripcion:** Ver STRATEGY "Decision de diseno 1" (con la correccion
  CONTRACT_AUDIT de BA07: `resolve_start_point` SOLO dentro de la rama
  `state == "absent"`, nunca justo tras `is_git_repo`, para no romper el
  diagnostico de pares `complete`/`partial` sin `origin` configurado).
  Fetch best-effort con `GIT_TERMINAL_PROMPT=0` + `timeout=30` + WARN si
  resuelve en stale (fetch fallo pero el ref local si existe) +
  verificacion de solo lectura (ambos modos) + error claro + propagar
  `start_point` a `git worktree add`.
- **Riesgo:** 🟡 Medio (toca el flujo de creacion real del par; sin
  consumidores automatizados hoy fuera de la orquestadora a mano).
- **Criterio de Aceptacion:** tests 1 y 2 de STRATEGY en verde.

### Fase 2: Gating de verificacion
#### 2.1: Gatear step 8/9 de `main()` por `verify_rc`
- **Tipo:** TAREA AGENTE
- **Accion:** Modificar `scripts/create_worktree_pair.py`
- **Descripcion:** Ver STRATEGY "Decision de diseno 2". El texto exacto
  "worktree pair creado" solo en exito real no-dry-run.
- **Riesgo:** 🟡 Medio
- **Criterio de Aceptacion:** tests 3 y 4 de STRATEGY en verde.

### Fase 3: Fixture + tests
#### 3.1: Reforzar `_git_init_main` con origin bare hermetico
- **Tipo:** TAREA AGENTE
- **Accion:** Modificar `tests/unit/test_create_worktree_pair.py`
- **Descripcion:** Ver STRATEGY "Fixture de tests". Los 8 tests existentes
  deben seguir verdes SIN modificar sus asserts.
- **Riesgo:** 🔴 Alto (toca un helper compartido por 8 tests; verificar
  cada uno tras el cambio, no solo los nuevos).
- **Criterio de Aceptacion:** `pytest tests/unit/test_create_worktree_pair.py -q`
  = 12 passed, 0 failed.

#### 3.2: 4 tests nuevos
- **Tipo:** TAREA AGENTE
- **Accion:** Modificar `tests/unit/test_create_worktree_pair.py`
- **Descripcion:** Los 4 casos de STRATEGY seccion "Tests nuevos".
- **Riesgo:** 🟡 Medio
- **Criterio de Aceptacion:** los 4 en verde, cada uno verificado por
  mensaje/estado real, no solo por ausencia de excepcion.

### Fase 4: CHANGELOG
#### 4.1: Entrada WOT-2026-129b
- **Tipo:** TAREA AGENTE
- **Accion:** Modificar `CHANGELOG.md`
- **Riesgo:** 🟢 Bajo
- **Criterio de Aceptacion:** entrada presente.

## Files Likely Touched
`scripts/create_worktree_pair.py`
`tests/unit/test_create_worktree_pair.py`
`CHANGELOG.md`

### Read/inspect only
`scripts/collect_session_state.py`

## Forbidden
No tocar `write_link()` ni el schema del link (WOT-2026-126d). No tocar
`uv_sync_failed`/step 7. No crear remotos de red reales en tests (todo
hermetico, bare local).

## 🧪 Criterios de Aceptacion Global
- [ ] 12 tests en `test_create_worktree_pair.py` verdes (8 existentes + 4
      nuevos).
- [ ] `ruff check . && ruff format --check .` verdes.
- [ ] `check_guard_wiring.py` sin diffs de wiring nuevos.
- [ ] CHANGELOG.md tiene entrada WOT-2026-129b.
