# TERMS -- Vocabulario canonico (extraido de AGENTS.md, WOT-2026-036e)

Este documento es una extraccion de referencia (fase A aditiva) de las tablas
de vocabulario canonico ya definidas en `AGENTS.md`. La fuente canonica sigue
siendo `AGENTS.md`; este fichero no reemplaza ni reinterpreta esas tablas,
solo las hace mas facilmente localizables como referencia rapida. Ante
cualquier divergencia, prevalece `AGENTS.md`.

## Vocabulario canonico

No usar "workspace" a secas: el termino es ambiguo porque describe tanto el repo destino como el entorno multi-root del IDE.

| Termino | Descripcion |
|---------|-------------|
| `repo_motor` | `orquestador_de_agentes/` — motor portable, fuente canonica del sistema. Tiene su propio repo git. No contiene estado operativo de tickets. |
| `repo_destino` | El proyecto que usa el motor. Tiene su propio `.agent/` con estado operativo (tickets, memoria, config). Nunca comparte estado con otros destinos. |
| `workspace_activo` | Raiz operativa con `.agent/` desde la que corre el ticket actual. En la topologia actual coincide con `repo_destino`. Se configura via `AGENT_PROJECT_ROOT` o `motor_destination_link.json`. |
| `entorno_multi_root` | IDE abierto con `repo_motor` + `repo_destino` a la vez (VS Code multi-folder workspace). No es un concepto de codigo: solo describe el entorno de desarrollo. |

**Regla de repos:** toda operacion git del tooling (diff, log, commit) corre con `cwd=repo_motor`. El estado operativo (tickets, memoria, events) vive en `repo_destino`.

**Regla de `AGENT_PROJECT_ROOT`:** el motor se invoca siempre con esta variable apuntando al `workspace_activo`. Sin ella, el motor usa modo code-only y bloquea escrituras operativas.

### Glosario de nomenclatura de ticket (WOT-2026-010a)

Nomenclatura canonica de identificadores y artefactos de ticket. "Plan" se
reserva para la familia completa; el artefacto de estrategia de un ticket es
`STRATEGY_`, no `PLAN_`.

| Termino | Descripcion |
|---------|-------------|
| `WOT-YYYY-NNNx` | **Prefijo canonico de ticket** (tres letras). Ej. `WOT-2026-010a`. Es el ID que usan generadores, validadores y bus. |
| `WP-` / `WT-` | **Legacy historico.** Prefijos de tickets antiguos (161 `WP-`, 72 `WT-`). NO se migran en masa; los consumidores los aceptan como `legacy-compat`. |
| familia / plan | El plan/familia completo, ej. `WOT-2026-009` agrupa `009a..009g`. "Plan" NUNCA designa el artefacto de un ticket individual. |
| `work_plan.md` | **Contrato operativo del ticket activo.** Una unica copia viva en `.agent/collaboration/`. Lo lee el scope gate y lo ejecuta el Builder. Sin cambio de nombre. |
| `STRATEGY_WOT-<ID>.md` | **Estrategia tecnica del ticket** (opcional). Sustituye al antiguo `PLAN_WT-<ID>.md`. Libera "PLAN" para la familia. Legacy: `PLAN_WP-*`, `PLAN_WT-*`. |
| `AUDIT_WOT-<ID>.md` | **Criterios de auditoria del ticket.** Solo cambia el prefijo `WT->WOT`. Legacy: `AUDIT_WP-*`, `AUDIT_WT-*`. |
