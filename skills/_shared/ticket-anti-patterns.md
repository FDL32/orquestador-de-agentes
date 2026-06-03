# Catalogo Canonico de Anti-Patrones de Ticket

Fuente compartida para Builder y Manager. Cada entrada debe leerse como una regla de redaccion para tickets y audits: nombre corto, por que rompe al agente, como detectarlo y un ejemplo malo/bueno. El formato de ejemplos `NO/SI` sigue el patron de `code-rules.md`: corto, directo y apto para pegar en prompts sin ambiguedad.

## TP-01 - Contradiccion secuencial

- **Descripcion:** El plan pide dos acciones incompatibles sobre el mismo recurso o en el mismo paso de la secuencia.
- **Por que rompe al Builder:** El Builder intenta cumplir ambas instrucciones literalmente y termina implementando una carrera o un comportamiento imposible.
- **Senal de deteccion:** Un paso dice "eliminar / reemplazar / salir" y otro paso posterior exige conservar o esperar el mismo estado sin mecanismo observable.

❌ Ejemplo malo:
> "El launcher elimina `supervisor_lock.txt` y luego espera a que el supervisor viejo salga solo."

✅ Ejemplo bueno:
> "El supervisor sale del bucle tras el requeue, libera el lock en el `finally` y el launcher espera a que el lock desaparezca antes de abrir Builder."

## TP-02 - Criterio no verificable

- **Descripcion:** El criterio de aceptacion describe una intencion, pero no un comando, test o asercion concreta.
- **Por que rompe al Builder:** El Builder no sabe cuando parar ni el Manager sabe cuando aprobar; la review se vuelve subjetiva.
- **Senal de deteccion:** Palabras como "observable", "correcto", "fresco" o "estable" sin una prueba literal que las verifique.

❌ Ejemplo malo:
> "El camino de reinicio es observable y falla cerrado si no puede garantizar frescura."

✅ Ejemplo bueno:
> "El test `test_launcher_resume_builder_fail_closed_on_timeout` debe fallar con exit code 1 y un mensaje concreto en stderr cuando el lock no desaparece."

## TP-03 - Deriva de ambito implicita

- **Descripcion:** El ticket menciona "otros archivos", "etc." o "los necesarios" sin enumerar exactamente los entregables.
- **Por que rompe al Builder:** El Builder amplía o reduce el alcance segun su criterio, y el review pierde fidelidad.
- **Senal de deteccion:** `Files Likely Touched` incompleto, vacio o con comodines no justificados.

❌ Ejemplo malo:
> "Cambiar launcher y otros archivos relacionados si hace falta."

✅ Ejemplo bueno:
> "Archivos Likely Touched: `scripts/launch_agent_terminals.ps1`, `bus/supervisor.py`, `tests/test_launch_agent_terminals_script.py`, `tests/test_supervisor.py`."

## TP-04 - Semantica blanda

- **Descripcion:** El plan usa expresiones como "si procede", "opcionalmente", "preferiblemente" o "stale" sin definir el criterio.
- **Por que rompe al Builder:** El Builder inventa heuristicas o decide por defecto de forma inconsistente.
- **Senal de deteccion:** Cualquier decision que dependa de una palabra blanda en lugar de una regla concreta.

❌ Ejemplo malo:
> "Si procede, limpiar el lock viejo antes de abrir Builder."

✅ Ejemplo bueno:
> "En `-ResumeBuilder`, esperar al supervisor viejo y fallar cerrado si no libera el lock dentro del timeout."

## TP-05 - Paridad PLAN/AUDIT rota

- **Descripcion:** El plan y el audit no describen exactamente la misma secuencia, los mismos archivos o los mismos criterios de aceptacion. Incluye tambien la paridad interna del propio AUDIT: sus Blockers, Evidencia esperada y TP Check deben usar los mismos verbos y condiciones que las Fases del PLAN.
- **Por que rompe al Builder:** El Builder puede satisfacer una superficie y fallar la otra; el Manager termina revisando dos contratos distintos.
- **Senal de deteccion:** Un criterio aparece en `PLAN_WP` pero no en `AUDIT_WP`, o el audit introduce una condicion extra no presente en el plan. Tambien: un Blocker del AUDIT usa un verbo distinto al de la Fase correspondiente ("anadir" cuando la Fase dice "verificar y completar").

❌ Ejemplo malo:
> El plan exige `SUPERVISOR_RESTARTED`, pero el audit solo pide "trazabilidad del reinicio" sin decir que evento o payload buscar. O: el Blocker dice "anadir tres observaciones" cuando la Fase ya fue corregida a "verificar y completar".

✅ Ejemplo bueno:
> El plan y el audit piden la misma secuencia: salida cooperativa del supervisor viejo, espera del launcher, arranque fresco y evento `SUPERVISOR_RESTARTED` con `{"round": N, "reason": "resume-builder"}`. Y el Blocker del AUDIT usa exactamente el mismo verbo que la Fase del PLAN.

**Nota sobre gates de aprobacion:** si una gate de calidad (como el TP Check) aparece como seccion suelta al final del documento en lugar de como paso explicito numerado antes del flujo de ejecucion, el agente la trata como opcional. Las gates deben preceder al flujo, no seguirlo.

## TP-06 - TP Check no canonico

- **Descripcion:** El `## TP Check` del AUDIT verifica criterios de diseno del entregable en vez de verificar que el PLAN esta libre de los anti-patrones `TP-01..TP-05`.
- **Por que rompe al Builder:** El audit deja de funcionar como gate uniforme y la deteccion automatica pierde la senal mecanica que necesita para validar el contrato.
- **Senal de deteccion:** Los items del `TP Check` hablan del dominio del ticket ("Flujo de propuesta", "Clasificacion de alcance", etc.) en lugar de usar la forma canonica `TP-01:`, `TP-02:`, `TP-03:`, `TP-04:` y `TP-05:`.

❌ Ejemplo malo:
> `## TP Check`
> - Flujo de propuesta y validacion: la skill propone learnings y pide validacion.
> - Clasificacion de alcance: local, generalizable y dudoso.

✅ Ejemplo bueno:
> `## TP Check`
> - TP-01: verificado - las 3 fases son secuenciales sin contradiccion; Fase 1 configura, Fase 2 crea, Fase 3 anade cobertura.
> - TP-02: verificado - Fase 2 cita el mecanismo explicito y los criterios nombran el comando literal y el test de cobertura.
> - TP-03: verificado - Files Likely Touched lista archivos concretos sin comodines.
> - TP-04: verificado - no aparece lenguaje blando en el flujo critico.
> - TP-05: verificado - PLAN y AUDIT describen las mismas fases, archivos y criterios de parada.

## TP-07 - Alcance condicional

- **Descripcion:** El plan usa clausulas condicionales como "si existe", "si se anade", "si aplica" o "si procede" para decidir alcance, en lugar de cerrar la decision en el ticket.
- **Por que rompe al Builder:** El Builder queda autorizado a incluir o excluir trabajo segun su interpretacion, y el plan deja de fijar el contrato de entrega.
- **Senal de deteccion:** Aparicion de "si existe", "si se anade", "si aplica", "si procede" o formulaciones equivalentes dentro de `Objetivo`, `Fases`, `Criterios` o `Decision Arquitectonica`.

? Ejemplo malo:
> "Si existe modo de reparacion, anadir un flag adicional."

✅ Ejemplo bueno:
> "El wrapper expone `--verify` como ruta por defecto y `--repair` como modo explicito separado; ambos estan definidos en la fase y en los criterios de aceptacion."

Detectado automaticamente por `validate_ticket_prose.py` como `TP-PROSE-12`.

## AP-D01 - Destructive scope cleanup

- **Descripcion:** Builder revierte, borra o resetea archivos que no estan en `Files Likely Touched` usando `git checkout`, `git reset`, `git revert` u otra operacion destructiva.
- **Por que rompe al Builder:** destruye trabajo ajeno y convierte una discrepancia de scope en una perdida de estado dificil de auditar.
- **Senal de deteccion:** el diff muestra eliminaciones o reversiones fuera del whitelist del plan, o el log menciona limpieza destructiva sobre archivos no declarados.

? Ejemplo malo:
> "Builder hace `git checkout -- skills/_shared/ticket-anti-patterns.md` porque sobraba en su scope."

✅ Ejemplo bueno:
> "Builder deja el archivo intacto, anota la discrepancia en `execution_log.md` y pide al Manager una actualizacion explicita del scope."

Detectado por el review checklist y por el Manager leyendo el `git diff` cuando la discrepancia aparece en el flujo de entrega.

## AP-D02 - Unprotected generated artifact

- **Descripcion:** Un artefacto generado o de runtime que no esta excluido de hooks mutadores se reescribe en `pre-push` y rompe la entrega.
- **Por que rompe al Builder:** el push falla por mutacion de archivos que no deberian participar en el formateo o en el fijado de finales de linea.
- **Senal de deteccion:** un hook mutador toca `.agent/context/project-map.json`, `events.jsonl` u otro artefacto generado declarado como runtime.

? Ejemplo malo:
> "`pre-push` ejecuta `end-of-file-fixer` sobre `.agent/context/project-map.json` y modifica el arbol."

✅ Ejemplo bueno:
> "Los artefactos generados quedan excluidos de hooks mutadores; el preflight solo los verifica de forma no mutadora."

Detectado automaticamente por `delivery_hygiene_check.py`.

## AP-D03 - Handoff sin ancla de recuperacion

- **Descripcion:** Builder intenta hacer handoff sin checkpoint M3 o sin protocolo de recuperacion documental.
- **Por que rompe al Builder:** si el arbol queda en estado inconsistente, no hay forma segura de volver a un punto conocido sin riesgo de perder trabajo.
- **Senal de deteccion:** `--mark-ready` falla por falta de M3; `git status` muestra archivos fuera de scope sin ancla de recuperacion; Builder usa `git checkout` destructivo en lugar de checkpoints.

? Ejemplo malo:
> "Builder ejecuta `--mark-ready` sin M3 y cuando el arbol se ensucia, usa `git checkout --hard` para limpiar, perdiendo trabajo ajeno."

✅ Ejemplo bueno:
> "Builder crea M3 explicitamente con `create_checkpoint.py --milestone M3` antes de `--mark-ready`; si el arbol se ensucia, sigue el protocolo de recuperacion con `git checkout checkpoint/review-<ticket>`."

Detectado por el guard de handoff (`pre_handoff_guard.py`) que bloquea si M3 falta. Ver `.agent/rules/builder/recovery.md`.

## Uso

- Usa estas entradas como referencia al redactar el `## TP Check` del `AUDIT_WP-XXXX.md`.
- Formato abreviado esperado en el audit:
  - `TP-01: verificado - ...`
  - `TP-02: verificado - ...`
  - `TP-03: verificado - ...`
  - `TP-04: verificado - ...`
  - `TP-05: verificado - ...`
- Si un TP aplica, el plan debe corregirse antes de aprobarse.
- Si el TP no aplica, explicalo en una sola linea verificable, no con lenguaje vago.
