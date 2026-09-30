# DEC-086P10-001: Suplente del refuter, y arreglo de seguridad de BA06

**Ticket:** WOT-2026-086i (draft, depende de esta decision) + ticket nuevo por fichar para el arreglo
de BA06 (no es de WOT-2026-086: es un mecanismo ya declarado que hoy no se cumple).
**Fecha:** 2026-09-30
**Estado:** **DECIDED**
**Decidido por:** Usuario, 2026-09-30 (respuestas via AskUserQuestion sobre
`PROPUESTA_D1_D2_D3_D5_P10_ratificacion_20260930.md`, workspace).
**Autor de la investigacion:** agente independiente de solo lectura (P10), mas verificacion directa del
orquestador.

---

## DECISION 1: politica cuando falta el refuter (codex) en gobierno

Se adopta el default de DEC-086I-001 (margen `UNI-5`) mas la politica de espera cuando aun asi el
minimo no se alcanza: si codex esta en cuarentena, el bucle se ejecuta sin refuter y el informe lo
declara `refuter: ausente (<causa>, reset <hora>)`; en `CLOSE`/`MANAGER_REVIEW` de tickets `code`/`mixed`
el paso refuter queda PENDIENTE y se relanza tras el reset. **No se llama `INSUFICIENTE`** a este estado:
esa etiqueta ya significa "menos lentes que el minimo" (P5) y mezclar las dos causas las confunde.

**No se invierte en un segundo agente con filesystem de pago.** El usuario senalo correctamente que ya
existe un agente con acceso a filesystem (opencode/BA06); el hueco no es de inventario de proveedores,
es de que ese agente hoy no corre en solo lectura real (ver Decision 2).

## DECISION 2: arreglo de seguridad de BA06 (PRERREQUISITO, no depende de si se usa como suplente)

**Hallazgo confirmado por reproduccion directa (no solo por el informe del investigador):** el perfil
`challenger_opencode_glm_5_2` (BA06) declara `write: false` + `readonly_agent: "auditor"`, pero el
agente `auditor.md` (con `bash: deny`) SOLO existe en `<motor>/.opencode/agents/auditor.md`. Con
`repo_scope: destino`, `opencode agent list` en el destino da `build, compaction, explore, general,
plan, summary, title, manager` -- **sin `auditor`** --, y `opencode run --agent auditor` cae al agente
por defecto (`build`, con permisos de edicion y bash). Verificado por el orquestador:

    cwd=<destino>: build, compaction, explore, general, plan, summary, title, manager
    cwd=<motor>:   build, compaction, explore, general, plan, summary, title, auditor, builder, manager

**Se decide:** copiar `auditor.md` al destino (`<destino>/.opencode/agents/auditor.md`), **permitiendo
que ese agente lea el motor** (relajar `external_directory` SOLO para ese agente, SOLO lectura, SOLO
hacia el arbol del motor).

### Motivo

El propio contrato `ensemble_loop.md` vive en el motor, y los bundles pasados a lentes `repo_scope:
destino` citan rutas del motor por diseno (WOT-2026-042v, "VEN LOS DOS ARBOLES"). Si el agente de solo
lectura del destino no puede leer el motor, BA06 quedaria ciego a la mitad del contrato que se supone
que audita -- perderia justo la capacidad que lo hace util como sustituto de codex. La alternativa
(lanzar esas lentes con `cwd=<motor>`) cambiaria sin necesidad el contrato de ambito vigente desde
WOT-2026-042v.

### Alcance del arreglo (superficie acotada)

- `<destino>/.opencode/agents/auditor.md`: copia de `<motor>/.opencode/agents/auditor.md` con
  `external_directory` ampliado para permitir lectura (nunca escritura) hacia `<motor>`.
- `scripts/check_agent_write_enforced.py`: anadir una comprobacion DINAMICA (ejecutar `opencode agent
  list` con el cwd real de cada perfil `repo_scope: destino` y verificar que el `readonly_agent`
  declarado aparece en el listado), no solo la comprobacion estatica actual (que solo mira si el backend
  DECLARA `readonly_agent`, sin comprobar que exista desde el cwd real).
- Este arreglo se hace **independientemente de si BA06 se usa despues como suplente del refuter**: hoy
  BA06 ya esta en el fan-out de gobierno (L720, L800) y corre con el fallo de seguridad activo en cada
  ronda sobre el destino.

### Ticket

Se ficha aparte de la familia WOT-2026-086 (no es una decision de diseno del bucle: es un mecanismo ya
declarado -- `write: false` -- que hoy no se cumple). Ver `<destino>/.agent/planning/
HALLAZGO_BA06_no_readonly_en_destino_20260930.md` para el alta con recibo.

## DECISION 3: suplente del refuter, a prueba, tras el arreglo de BA06

Una vez arreglado BA06, se prueba como suplente degradado con el UMBRAL de DEC-086I-001 (>=80% util en
>=5 rondas del tamano de bundle relevante, contando como muda una respuesta de solo preambulo sin
veredicto -- el 62-66% historico de glm-5.2 esta inflado por rondas asi, medido: el 38% del modelo
actual glm-5.3-flash cae a 3/11 con bundles >15 KB). Candidatos, en orden: `opencode-go/glm-5.3` (sin
flash, 2/2 medido), `deepseek-v4-pro`, `kimi-k3`. Se descarta `kilo` (mismo origen que opencode, sin
datos, peor perfil de seguridad: `run --auto` sin agente de solo lectura).

## Condiciones de reapertura declaradas

- Si el reset de codex pasa a ser de dias (limite semanal) en vez de horas: la espera bloquea demasiado,
  hace falta reconsiderar un suplente real o una dispensa humana explicita.
- Si la cuota de `opencode-go` resulta ser por cuenta (no medido) y el Builder/Manager la agotan: usar
  BA06 como suplente le quitaria capacidad a la implantacion (contra D15 de la propuesta original).
- Si otros modelos de opencode muestran el mismo patron de "solo preambulo sin veredicto": el problema
  seria del transporte `opencode run`, no del modelo, y probar otro modelo no arreglaria nada.
