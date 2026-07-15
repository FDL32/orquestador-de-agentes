# Repo Charter — Motor de orquestacion multi-agente

> Charter del PROPIO MOTOR (no de un repo_destino). Vive en la RAIZ del motor, **no** en
> `.agent/planning/`, porque el motor no es un destino. **No viaja**: no figura en
> `MANIFEST.distribute` (allowlist literal de 52 entradas; verificado por pertenencia, no por
> glob). Declara la intencion y los limites del motor como herramienta portable.
> El usuario aprueba via `DEC-*`; este archivo no se edita en operacion normal.
> Aprobado por el usuario (respuestas de charter, 2026-07-15). Ver `DEC-motor-charter`.

## Product Intent
El motor es una herramienta portable para incorporar orquestacion asistida a proyectos Python,
con contratos, evidencia, memoria y gates reproducibles. Debe funcionar tanto **clonado** en un
proyecto nuevo como **enlazado** desde una instalacion central que gobierna una flota de
`repo_destino`. El dogfooding del propio motor es un caso de uso, **no el producto**.

## Architecture Constraints
- El motor vive UNA vez en el repo fuente. Los destinos lo **referencian externamente** (via
  `motor_destination_link.json`); **no heredan su estado interno**.
- Dos modos de despliegue, ambos soportados sin mezclar estado: **clon autonomo** por proyecto y
  **flota** con motor central enlazado (`is_motor_code_only()` discrimina el modo).
- Lo que viaja a un destino sale EXCLUSIVAMENTE de `MANIFEST.distribute` (allowlist explicita).

## Non-Goals

### NG-RAIZ — el motor NO decide politica por heuristica
Cuando falta un contrato (`repo_charter`, `destination_root`, `ticket_prefix`, una `DEC-*`
necesaria), el motor **falla explicito o pide `DEC`**. No inventa destino, ni superficie
distribuible, ni reglas de adopcion. Es la raiz de la que salen los demas Non-Goals, y el
antipatron que mas ha costado: inventar una premisa en vez de medirla o pedir la decision.

### NG-1 — NO distribuye su dogfooding
El motor NUNCA deposita en un destino sus propios contratos/tickets/planning vivos. Alcance
preciso: aplica a `MANIFEST.distribute` y a `--install` fresco. Un **seed NEUTRO** (plantilla sin
WOT reales) SI puede viajar; el planning vivo NO. *(Cierra la politica de `WOT-2026-024h`.)*

### NG-2 — NO versiona estado operativo en la superficie que viaja
Runtime, proyecciones, colaboracion y outputs de auditorias no son superficie distribuible.
Matiz: contratos y charters SI pueden versionarse (son intencion, no estado); lo prohibido es el
**estado operativo** (runtime/collaboration/proyecciones/outputs).

### NG-3 — NO nombra esta maquina ni este dogfooding en superficie distribuida
Nada que viaja puede citar rutas de usuario, el nombre del workspace ni el sufijo `_dev`. Los
ejemplos LOCALES no distribuibles pueden existir. *(Ya cableado: `check_distribution_agnostic`.)*

### NG-4 — NO sobrescribe destinos ya adoptados sin no-clobber
Ninguna operacion del motor pisa ficheros propiedad del destino (planning, collaboration,
runtime). `--install` fresco SI puede depositar un seed neutro. *(Ya cerrado por
`WOT-2026-024d`; el charter lo eleva a invariante.)*

## Quality Bar (criterios medibles)
- **Todo guard nuevo cableado, o deuda declarada.** Un guard que nadie invoca es una norma, no una
  barrera (`WOT-2026-024u`): guard nuevo sin cablear = FAIL; deuda existente = WARN con su ticket.
- **Todo probe publica su denominador:** `denominador / inspeccionados / hits / saltados` + LISTA
  de saltados. `inspeccionados == 0` -> ROJO, nunca verde. *(La regla que 8 falso-verdes enseñaron.)*
- **DoD invariante, jamas una medicion.** Un criterio que fija un NUMERO se pudre y empuja a romper
  una herramienta que funciona (`WOT-2026-024t`). Los numeros son evidencia fechada (SNAPSHOT).
- **Suite verde POST-commit + CI.** `tested_sha == HEAD` sobre el commit que se sube; CI es la
  autoridad final.
- **Ruta productiva, o evidencia degradada.** Todo probe de cierre declara launcher, shell, cwd,
  env relevante y **por que reproduce produccion**. Si no reproduce la ruta productiva, es
  evidencia EXPLORATORIA (orienta, no cierra).

## Security Constraints
- Sin secretos, PII, tokens, rutas personales ni telemetria remota en superficie distribuible.
- El write-guard (`PreToolUse`) debe **fail-closed** (exit 2; un exit 1 NO bloquea) y leer el
  payload productivo (`tool_input` anidado).

## FRASE CLAVE (invariante rector)
> **El motor portable no contiene ni distribuye estado, historico operativo, dogfooding, rutas
> locales ni datos de ningun `repo_destino`. Los destinos referencian el motor; no heredan su
> vida interna.**

## Objetivos

### OBJ-001 — El motor es agnostico en la superficie que viaja
- description: nada de lo que sale por `MANIFEST.distribute` nombra esta maquina, este workspace
  ni el dogfooding.
- success_criteria: `check_distribution_agnostic` exit 0 con su denominador publicado; 0 agujas
  vivas sin eximir.
- failure_modes:
  - un hardcode vive en una entrada que viaja y el guard sale verde porque salto ese fichero.
  - el guard mide UNA aguja y declara agnostico el conjunto (denominador incompleto).
- related_plans: [PLAN-001]

### OBJ-002 — La flota es medible y no se degrada en silencio
- description: el instrumento que audita la proteccion de la flota conoce su denominador y falla
  honestamente cuando no puede enumerar.
- success_criteria: `--fleet` publica `links / incluidos / dedupe / saltados / errores` + lista;
  `inspeccionados == 0` -> no-cero.
- failure_modes:
  - un destino se salta en silencio y el censo sale verde (el bug que el propio `024f` mata).
  - el instrumento marca en rojo los destinos CORRECTOS por confundir la forma canonica del hook.
- related_plans: [PLAN-002]

### OBJ-003 — El despliegue no daña al destino
- description: instalar o sincronizar el motor en un destino nunca pisa lo que el destino posee ni
  le inyecta el dogfooding del motor.
- success_criteria: no-clobber sobre `DESTINATION_OWNED_DIRS`; `--install` fresco deposita, como
  mucho, un seed NEUTRO.
- failure_modes:
  - `--install` fresco deposita 46KB de contratos de dogfooding (NG-1).
  - `copy_tree` degrada a copy-all sin no-clobber si falta el MANIFEST (fail-open silencioso).
- related_plans: [PLAN-003]

## Negative Audit Checklist
Antipatrones verificables que **invalidan la aceptacion** si aparecen:
- [ ] el motor decide una politica por heuristica en vez de fallar/pedir DEC (viola NG-RAIZ)
- [ ] una entrada que viaja nombra esta maquina, el workspace o el sufijo `_dev`
- [ ] estado operativo (runtime/collaboration/proyecciones/outputs) en superficie distribuible
- [ ] una operacion del motor pisa un directorio propiedad del destino
- [ ] un probe declara un resultado sin publicar su denominador
- [ ] un DoD fija un numero de la flota como criterio de aceptacion
- [ ] un guard nuevo sin cablear ni declarar su deuda
- [ ] evidencia de cierre medida fuera de la ruta productiva presentada como concluyente

## Decisiones pendientes
- `DEC-motor-charter` (esta): raiz del motor, no distribuible, define portabilidad y Non-Goals.
  Aprobada por el usuario 2026-07-15.
- `WOT-2026-024h`: implementar NG-1 (seed neutro vs no-viaja). Politica decidida; falta ejecutar.
