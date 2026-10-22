# Propuesta de optimizacion: que aporta `repo-audit` + estado de Hermes + siguiente palanca

> Documento de DISENO (`sesion_diseno` dentro de una sesion de desarrollo en curso). Read-only
> sobre codigo: no implementa nada. Entrada para el bucle adversarial DESIGN_REVIEW que lo sigue.

contract_id: cid-propuesta-optimizacion-hermes-repo-audit-v1

## ESTADO_FRESCO

    ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\optimizacion-arranque-frio-cont-20261022, HEAD=ca8426e48734922cb2e9e83462699cb05cd15282, dirty=0, verificado=2026-10-22T09:46Z

## 1. Pregunta del usuario: que puede aportar `skills/repo-audit` al sistema

`repo-audit` (nucleo `prompts/repo_audit_multiagent.md`, v2.4, `contract_id:
cid-repo-audit-multiagent-v2`) **ya existe en este mismo motor**, no es una herramienta externa
a evaluar: es un auditor multiagente de 7 fases (recoleccion determinista -> triage por lane ->
dedupe -> bucle adversarial de verificacion -> informe -> conexion con ejecucion ya existente),
ya paso su propio bucle adversarial de diseno (`DBL-4`, 8 lentes, veredicto unanime CAMBIOS, 0
bloqueantes) y ya tuvo una primera corrida real completa (nota v2.4).

Aporta DIRECTAMENTE a dos lineas de este vuelo:

1. **Lane `proceso` (solo si `Ambito == motor`):** censa solapamiento entre prompts/skills,
   pasos de flujo redundantes y friccion Manager<->Builder<->Revisor **documentada y citable**.
   Esto es relevante para "arranque en frio" aunque no toque el gate de `siempre-cargado`
   directamente: reduce el volumen total de `citado-obligatorio`/`router-condicional` que un
   agente frio puede necesitar atravesar, y puede destapar prompts/skills duplicados que
   compiten por la misma funcion (coste de mantenimiento, no solo de contexto).
2. **Lane dead-code + gate de sostenibilidad (5 capas) para clasificar Hermes con rigor
   mecanico**, en vez de mi verificacion manual de esta sesion (Seccion 2 abajo), que es
   evidencia parcial, no un veredicto formal.

**Recomendacion:** no lanzar el `repo-audit` COMPLETO (7 fases + bucle de Fase 4 con 5
hallazgos) como parte de ESTE ticket de arranque en frio -- es una inversion mayor (presupuesto
propio, lentes propias, gate de privacidad, Fase 0 de alcance). Proponer un **follow-up
separado** (`docs/followups/repo-audit-motor-fase0-propuesta-followup.md`, a crear SI el bucle
de abajo lo valida) con alcance acotado: `Ambito: motor`, lanes = `{proceso, dead-code}`,
dirigido especificamente a (a) confirmar/refutar el estado de Hermes y (b) censar duplicacion
prompt/skill relevante al arranque en frio. Esto respeta el Non-goal de `repo-audit` mismo
("no usar para un solo archivo ya identificado") al declarar el alcance ampliado justificado por
mas de un objetivo.

## 2. Reverificacion de Hermes (pregunta previa del usuario en esta sesion)

Verificacion manual (no formal, NO sustituye el gate de 5 capas de `repo-audit` Seccion 3.1):

| Capa (gate de sostenibilidad) | Resultado |
|---|---|
| 1. `git grep -l hermes` (texto) | 1 referencia de CODIGO real no-test, no-doc: `scripts/discover_skills.py:936` `EXTERNAL_ALLOWLIST: frozenset[str] = frozenset({"hermes_soul.md"})` |
| 2. Literal sin frontera de palabra (`importlib`/`getattr`) | Sin hallazgo adicional mas alla de la capa 1 |
| 3. Entry-points (`pyproject.toml`, Makefile, CI) | Ninguno (`grep -i hermes pyproject.toml` y `.github/` vacios) |
| 4. Excluir historico (CHANGELOG, docs de archivo) | Excluido correctamente (CHANGELOG 2026-06-20 es el unico rastro historico puro) |
| 5. `__all__` de paquete padre | No aplica (es un script, no una API importada) |

**Veredicto preliminar (NO formal):** Hermes **no es DEAD puro** -- la capa 1 encuentra una
referencia de codigo real (el allowlist de `discover_skills.py`). Por la regla del gate
("si CUALQUIER capa encuentra una referencia, el hallazgo baja a `DEAD (unverified dynamic)` --
nunca se autoborra, siempre requiere revision humana explicita"), el caso correcto es
`DEAD (unverified dynamic)`, no un borrado directo. Ademas tiene mantenimiento real reciente
(commit `60011336`, 2026-08-28, WOT-2026-036g) y su propia suite de tests viva en la suite
canonica. **No hay wiring automatico** (ni pre-commit ni CI lo invoca): es una herramienta
manual para exportar un bundle de contexto a un agente externo llamado "Hermes" (otro chat/LLM
fuera de este motor), no dead code tecnico pero si de uso incierto/manual.

**Implicacion para la decision:** no hay base solida para "retirar Hermes" como accion
mecanica de este ticket. Es una decision de PRODUCTO del usuario (?sigue usando ese flujo de
exportar bundle a un agente externo, o no?), no algo que un grep o un Builder deba decidir. La
via correcta para resolverlo con rigor es el lane dead-code de `repo-audit` (Seccion 1), que
emite `veredicto_adversarial` tras un bucle real, en vez de mi lectura manual de esta sesion.

## 3. Correccion sobre WOT-2026-114a (el ticket ya en vuelo)

El ticket que delegue antes de esta pregunta (Fase 1 de la Palanca A: registro de Hermes
re-apuntable via campo `source`, sin mover contenido todavia) **sigue siendo valido
independientemente de la decision sobre Hermes**:

- Si Hermes se CONSERVA: el registro re-apuntable es precondicion para mover
  `## Vocabulario canonico` / `## CEM v0` de `AGENTS.md` a un modulo sin que Hermes reciba menos
  contenido (PASO 3(e) de `prompts/doc_optimization.md`, escape valido via PASO 4 before/after).
- Si Hermes se RETIRA (decision de producto del usuario, no de este ticket): el registro
  re-apuntable queda sin consumidor que lo necesite, pero el trabajo no se desperdicia del
  todo -- simplemente el PASO 3(e) deja de aplicar a esas 2 secciones (24.681 B movibles
  directamente, sin la plomeria), y el commit de WOT-2026-114a pasaria a ser revertible sin
  dano (es local, no pusheado).

No hay motivo para interrumpir ese ticket mientras se decide lo de Hermes.

## 4. Nueva pasada sobre toda la informacion reunida: errores y puntos de mejora encontrados

1. **Hallazgo propio, correccion sobre Fase 0R (WOT-2026-112c):** el informe atribuye el
   bloqueo universal de PASO 3(d) a `build_llms.py`, pero de las 24 unidades nivel-2, NINGUNA
   depende SOLO de ese bloqueo -- cada una ya falla antes por PASO 2 (filas #1/#2/#3, SIEMPRE se
   queda) o PASO 3(c)/(e). La unica unidad etiquetada "solo 3(d)" (`## Comandos principales`) es
   en realidad PASO 2 fila #3 (comando operativo) tambien. **Conclusion:** arreglar
   `build_llms.py` no desbloquea ninguna unidad de `AGENTS.md`; el veredicto `SIN CANDIDATO
   MOVIBLE` de Fase 0R es mas robusto de lo que su propio informe argumenta, pero por una razon
   distinta a la que cita como causa raiz.
2. **Hallazgo nuevo (esta pasada):** el diseno de Palanca A (`docs/followups/palanca-a-raiz-
   agents-md-diseno.md`, Fase 1-2, D1/D1-bis) YA tenia la via de escape para el bloqueo PASO
   3(e) de Hermes (registro re-apuntable + baseline sha256), escrita el 2026-10-21, UN DIA antes
   de que Fase 0R (2026-10-22) concluyera "SIN CANDIDATO MOVIBLE" sin ejercer esa via. No es una
   contradiccion real (Fase 0R mide bajo las reglas del protocolo SIN el mecanismo de escape
   todavia implementado; el diseno de Palanca A plantea implementarlo), pero las dos fuentes
   convivian sin que ninguna citara explicitamente a la otra en su conclusion -- riesgo de que
   una tercera lectura tome la conclusion de Fase 0R como definitiva y abandone la via de la
   Palanca A sin saber que ya estaba disenada. Este documento cierra ese gap de lectura.
3. **Punto de mejora de proceso (no bloqueante):** no hay ningun artefacto que declare
   EXPLICITAMENTE "Hermes es DEAD/ABANDONED/en uso" con `veredicto_adversarial`. Es la primera
   vez que se cuestiona su vigencia desde que se creo (2026-06-20). Proponer el follow-up de
   Seccion 1 para generar esa evidencia formal si el usuario quiere decidir con rigor.
4. **Punto de mejora (riesgo declarado, no nuevo):** el diseno de Palanca A declara R2 ("las
   cifras de retencion son estimadas, la Fase 0 las sustituye") -- Fase 0R SI corrio esa
   medicion (24 unidades con fila PASO 2 + veredicto PASO 3), pero NO en el formato que el
   diseno de Palanca A esperaba (retencion E2 por bloque, suelo de 28540 B). Hay un desajuste de
   formato entre lo que el diseno pidio medir y lo que Fase 0R entrego -- util para quien
   retome la Fase 2 de la Palanca A, para no asumir que Fase 0R ya es la Fase 0 del diseno.

## 5. Propuesta de optimizacion consolidada

1. **Dejar correr y cerrar WOT-2026-114a** (Fase 1, registro re-apuntable) tal como esta en
   vuelo -- valido bajo cualquier decision sobre Hermes (Seccion 3).
2. **Declarar la deuda de `AGENTS.md`/`CLAUDE.md` sobre ambos gates como PASO 5 de
   `doc_optimization.md`** (deuda con dueno, ya existe el artefacto base en
   `docs/followups/agents-md-over-quota-followup.md`; anadir ahi la correccion de la Seccion 4.1
   de este documento, no abrir un fichero nuevo).
3. **Abrir el follow-up acotado de `repo-audit`** (Seccion 1) para: (a) emitir un
   `veredicto_adversarial` formal sobre Hermes (lane dead-code), y (b) censar duplicacion
   prompt/skill relevante al arranque en frio (lane `proceso`) -- EXCLUSIVAMENTE si el bucle
   adversarial de este documento lo valida como prioridad razonable frente a otras tareas del
   vuelo.
4. **No decidir unilateralmente retirar Hermes.** Es una decision de producto del usuario; este
   documento solo prepara la evidencia para que la tome con informacion completa.
5. **Si Hermes se conserva y el follow-up de `repo-audit` no encuentra bloqueos nuevos**,
   continuar la Palanca A por la Fase 2 del diseno (mover `## Vocabulario canonico` al modulo,
   usando el registro ya re-apuntable de WOT-2026-114a) como el siguiente ticket natural del
   vuelo de arranque en frio.

## 6. Bucle adversarial pedido por el usuario

Esta propuesta se somete a `ensemble_dispatch.py loop-round`, fase `DESIGN_REVIEW`
(`loop_id: EXPLORATORY-hermes-repo-audit-20261022`, sin commit/nonce por tratarse de una
propuesta sin cambios de codigo), con las lentes pedidas explicitamente por el usuario:
`challenger_codex` (agent), `challenger_opencode_glm_5_2` (agent), `challenger_nan_deepseek_flash`
(api), `challenger_nan_qwen_flash` (api), `challenger_gemini_gemini` (api),
`challenger_mistral` (api), `challenger_cohere_command` (api). Repo publico (`DEFAULT_BASE` de
`scripts/build_llms.py` apunta a `github.com/FDL32/orquestador-de-agentes`, repo real
publico) -> `data-sensitivity: public`, lentes `api` permitidas sin restriccion adicional del
gate de privacidad de Fase 0 de `repo_audit_multiagent.md` (aunque aqui no se invoca ese
prompt: es el mismo criterio de privacidad, declarado por consistencia).
