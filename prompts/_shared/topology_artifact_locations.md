# Topology & artifact locations (cid-topology-artifact-locations-v0)

> Fuente unica de verdad sobre DONDE vive cada artefacto operativo en la topologia
> motor<->destino. Adoptada en WOT-2026-029b (M22, flight_20260718) para corregir el
> patron "root equivocado" (auditor o Builder leyendo estado operativo en `repo_motor`
> en vez de `repo_destino`, o viceversa).

## Regla de topologia

- `repo_motor` (`<MOTOR_ROOT>`) es CODIGO SOLAMENTE. Su propio `.agent/` es una
  **semilla neutra** (molde para destinos nuevos), NO estado operativo. Nunca
  leas ni escribas estado operativo ahi.
- `repo_destino` (`<DESTINO_ROOT>`) es donde vive el estado operativo y los
  artefactos: tickets, memoria, eventos, reportes.

## Mapa de artefactos

Expresado siempre en terminos de rol (`<MOTOR_ROOT>` / `<DESTINO_ROOT>`), nunca
como ruta absoluta de una maquina concreta ni con el nombre de una instancia de
dogfooding especifica.

| Artefacto | Vive en |
|---|---|
| Backlog | `<DESTINO_ROOT>/.agent/collaboration/backlog.md` |
| Estado de colaboracion (work_plan, execution_log, STATE, TURN) | `<DESTINO_ROOT>/.agent/collaboration/` |
| Eventos del bus | `<DESTINO_ROOT>/.agent/runtime/events/events.jsonl` |
| Memoria por proyecto | `<DESTINO_ROOT>/.agent/runtime/memory/` |
| Reportes de pipeline | `<DESTINO_ROOT>/orchestrator_pipeline/reports/` |
| **Prompt de arranque de Builder** | `<DESTINO_ROOT>/.agent/planning/builder_prompt_<TICKET>.md` |
| Superficies de codigo del motor | `<MOTOR_ROOT>/scripts/`, `<MOTOR_ROOT>/prompts/`, `<MOTOR_ROOT>/bus/` |

### Por que el prompt de arranque vive en `planning/` y no en `reports/`

Decidido en WOT-2026-067w tras un fallo medido. `reports/` es **deny-por-defecto con
allowlist** (`.gitignore:74-82`) y lo que se versiona ahi es **evidencia de cierre**
(`batch_run_*`, `start_context_isolation`, recibos de mutation-verify). Un prompt de
arranque es **entrada gobernante**, no evidencia: pertenece a `planning/`, junto a los
`ARRANQUE_*` y `PROPUESTA_*` que ya viven ahi. Censo 2026-09-16: 20 prompts de Builder
repartidos en 4 ubicaciones; `planning/` es la mayoritaria (10) y la UNICA tracked.

**Barrera, no norma:** `scripts/check_launch_prompt_paths.py` emite
`R3-ubicacion-no-canonica` y falla si un prompt de arranque vive fuera. Lo reconoce por
CONTENIDO (declaracion del `contract_id` del Builder, o encabezado de rol), no por
nombre ni carpeta: el nombre fue justamente el vector del fallo. Coste de no tenerla,
medido: un prompt fuera del universo del guard cito `execution_log.md` sin ruta, el
Builder escribio en el seed neutro del motor, y se le reprocho tres rondas de review
antes de ver que la causa era el prompt.

## Mecanismo de resolucion

El root activo se resuelve via `AGENT_PROJECT_ROOT` / `--project-root`; el
enlace motor<->destino via `resolve_motor_link(project_root)`
(`from scripts.destination_context import resolve_motor_link`); y el modo via
`is_motor_code_only()` (`from runtime.project_root import is_motor_code_only`).
`is_motor_code_only()` es un **write-guard** sobre el `.agent/` del motor, no un
detector de bus en vivo: distingue "estoy en modo codigo-solo" de "hay o no
actividad operativa real".

## Contrato de ambito FS al enviar bundles (WOT-2026-038l)

Un agente con filesystem (codex, lector-Claude-FS) necesita que se le declare
DONDE buscar, no solo QUE analizar. Causa raiz medida: `codex exec` resuelve
`rg`/`git grep` contra su propio cwd de proceso; si ese agente hereda el cwd
del proceso padre (el motor) y el artefacto a auditar vive en el
`<DESTINO_ROOT>` (o viceversa), el agente REFUTA por ambito equivocado, no
porque el artefacto no exista.

**Norma:** al enviar un bundle/prompt a un agente CON filesystem, declara la
ruta absoluta del arbol (`<MOTOR_ROOT>` / `<DESTINO_ROOT>`) para cada
artefacto que deba localizar. Si el agente solo puede leer UN arbol en esa
invocacion, marca explicitamente los elementos del otro arbol como
**NO-VERIFICABLE-POR-AMBITO** en vez de dejar que el agente los busque a
ciegas y reporte un falso negativo.

**Alcance de la barrera vs la norma:**

- **Barrera cableada (code):** `scripts/run_codex_audit.py` acepta
  `repo_root` (API keyword-only) / `--repo-root` (CLI) y lo pasa como `cwd=`
  al `Popen` que lanza `codex exec`. Cubre UNICAMENTE el camino
  `run_codex_audit`. Si `repo_root` no se declara, el helper emite un
  warning a stderr y preserva el cwd heredado (comportamiento previo,
  aditivo).
- **NORMA documental (no barrera cableada):** para la ruta lector-Claude-FS
  (un agente Claude Code leyendo el arbol directamente, sin pasar por un
  `Popen` interceptable), este contrato es una norma que el humano/prompt
  debe recordar y aplicar — no hay mecanismo de codigo que la fuerce.
- **Fuera de alcance de WOT-2026-038l:** `scripts/ensemble_dispatch.py::_transport_agent`
  es OTRO Popen codex-capaz, independiente de `run_codex_audit`. No fue
  tocado por este ticket; si se decide cablear `cwd=` ahi tambien, es un
  follow-up separado.
