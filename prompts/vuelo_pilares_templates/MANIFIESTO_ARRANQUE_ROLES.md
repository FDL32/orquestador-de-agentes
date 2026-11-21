# Manifiesto de arranque por rol

## A) Propósito

Plantilla versionada en el motor para el arranque frío de los roles CO, TR e IM.
La instancia por vuelo se genera desde esta plantilla y localiza los artefactos
obligatorios y la expansión de memoria de cada paquete.

## B) Contrato de expansión de placeholders

- `<motor>` = `C:/Users/fdl/.t3/worktrees/orquestador_de_agentes/orquestadora-3-vuelo-20261026b`
- `<flight>` = `C:/Users/fdl/Proyectos_Python/orquestador_de_agentes_workspace/.agent/runtime/flight/vuelo-20261026b`
- `<fecha>` = `YYYYMMDD` del día de generación, obtenido con `Get-Date -Format yyyyMMdd` en el momento de generar; no es el nombre del vuelo ni del ticket.
- Ejemplo de instancia: `<flight>/diseno/MANIFIESTO_ARRANQUE_ROLES_<fecha>.md`

Todas las rutas citadas llevan prefijo `<motor>/` o `<flight>/` y son absolutas
tras expandir el placeholder.

## C) Precedencia

1. El estado firmado vigente manda sobre cualquier estado citado en plantillas o instancias.
2. Este manifiesto fija rutas y recall y no fija HEAD.
3. Los marcadores de HEAD histórico de las plantillas son evidencia fechada, jamás autoridad.
4. Los `ARRANQUE_CO-*` y `HANDOFF_CO-*` instanciados son registro histórico.

Si manifiesto y ARRANQUE discrepan en estado, manda el estado firmado; en rutas,
manda el manifiesto.

## D) estado firmado vigente

- Ruta: `<flight>/diseno/ESTADO_RELEVO_VIGENTE.json` - DECLARADO COMO: **NO EXISTE** (medido 2026-11-21, `Test-Path False`); es la RUTA ESTABLE que crea el primer `python scripts/flight/sign_relevo_state.py --emit --out <ruta>` y que renueva `--select-vigente`; la valida `python scripts/flight/sign_relevo_state.py --verify <ruta>`. NUNCA citarla como válida hasta entonces.
- Comando de verificación real: `python scripts/flight/sign_relevo_state.py --verify <ruta>`
- Comando de emisión: `python scripts/flight/sign_relevo_state.py --emit --out <ruta>`
- Campos consumidos, exactamente: `identidad`, `autoridad`, `fecha_utc`, `recibo`, `comando_verificacion`.

## E) Resumen de roles

| rol | recall obligatorio |
|---|---|
| CO | `python scripts/memory_context.py --recall --query "supervision de vuelo y relevo"` |
| TR | `python scripts/memory_context.py --recall --query "triaje y admision de backlog"` |
| IM | `python scripts/memory_context.py --recall --query "implantacion y contrato del Builder"` |

## F) Paquetes por rol

### CO

bootstrap es indice, no corpus completo. Expande el recall obligatorio antes de
operar y usa esta tabla como inventario mínimo del paquete CO.

| artefacto | ruta | nota |
|---|---|---|
| autoridad de órdenes | `<motor>/docs/protocol/flight_supervision.md` | Existe; autoridad de órdenes. |
| pilares y precedencia | `<motor>/.agent/rules/common/vuelo_pilares.md` | Existe; pilares y precedencia. |
| estado de relevo | `<flight>/diseno/ESTADO_RELEVO_VIGENTE.json` | **NO EXISTE**; medido 2026-11-21, se genera en cada relevo. |
| operación en curso | `<flight>/diseno/OPERACION_EN_CURSO_<CO>.md` | Existe; registro operativo, patrón medido. |
| arranque CO | `<flight>/diseno/ARRANQUE_<CO>_<fecha>.md` | Existe; ejemplo `ARRANQUE_CO-141_20261120.md`. |
| handoff entre CO | `<flight>/diseno/HANDOFF_CO-<n>_a_CO-<n+1>_<fecha>.md` | Existe; ejemplo `HANDOFF_CO-140_a_CO-141_20261120.md`. |
| plantilla de handoff | `<motor>/prompts/vuelo_pilares_templates/HANDOFF_PLANTILLA.md` | Existe. |
| registro de relevo | `<flight>/diseno/GO_RELEVO_24H_REGISTRO.md` | Existe. |

### TR

bootstrap es indice, no corpus completo. Expande el recall obligatorio antes de
triage y usa esta tabla como inventario mínimo del paquete TR.

| artefacto | ruta | nota |
|---|---|---|
| brief TR | `<flight>/diseno/BRIEF_TR_<detalle>_<fecha>.md` | Existe; ejemplos `BRIEF_TR_MEMORIA_20261120.md` y `BRIEF_triaje_TR25_TR26_pasada2_20261109.md`. |
| backlog vivo | `<flight>/../../../collaboration/backlog.md` | Existe; resuelve al backlog del workspace. |
| prompt de triaje | `<motor>/prompts/backlog_triage.md` | Existe. |
| prompt de admisión | `<motor>/prompts/backlog_admit.md` | Existe. |
| protocolo de findings | `<motor>/prompts/_shared/finding_triage_protocol.md` | Existe; ruta real. |
| recibos de alta | `<flight>/backlog_admission_recibos_fixed/` | Existe; recibos de alta. |

### IM

bootstrap es indice, no corpus completo. Expande el recall obligatorio antes de
implantar y usa esta tabla como inventario mínimo del paquete IM.

| artefacto | ruta | nota |
|---|---|---|
| brief IM | `<flight>/diseno/BRIEF_IM_<TICKET>_<fecha>.md` | Existe; ejemplo `BRIEF_IM_212a_20261121.md`. |
| contrato de lanzamiento Builder | `<motor>/prompts/orchestrator_launch_builder.md` | Existe; contrato de invocación y entrega del Builder. |
| relevo de sesión | `<motor>/prompts/t3_role_session_relief.md` | Existe; alivio y relevo de sesión. |
| jerarquía de memoria | `<motor>/.agent/rules/common/memory_hierarchy.md` | Existe; arquitectura de memoria para expansión. |
| instancia del manifiesto | `<flight>/diseno/MANIFIESTO_ARRANQUE_ROLES_<fecha>.md` | **NO EXISTE** hasta que se genere. |
