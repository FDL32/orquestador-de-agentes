# Prompt: Auditoria Adversarial de Cierre de Sesion

contract_id: cid-session-close-full-audit-v0
Skill canonica: skills/session-close-full-audit/SKILL.md

## Que es y que NO es

Pasada de auditoria adversarial que precede al cierre canonico de una sesion.
Encadena las tres auditorias estructurales de salud del sistema, anade una
pasada adversarial sobre el CODIGO GENERADO en la sesion (el paso que el flujo
de cierre anterior omitia), y solo entonces deja proceder al cierre operativo y
a la promocion de memoria.

NO reimplementa la logica de las skills que orquesta. Es un wrapper contextual:
- la salud del sistema la posee `skills/system-health-audit/SKILL.md`;
- el cierre operativo lo posee `skills/manager-session-closeout/SKILL.md` +
  `prompts/orchestrator_session_close_chat.md` (comando canonico
  `agent_controller.py --session-close`);
- la promocion de memoria la gobierna `prompts/memory_upload.md`.

El contrato del auditor lo gobierna integramente `prompts/audit_agent_output.md`
(CEM v0, evidencia antes que relato, doble pasada, frontera del auditor); este
prompt NO lo reproduce, solo lo aplica al cierre de sesion. MODO read-only por
defecto: audita y propone el cambio minimo; no parchea salvo instruccion explicita.

Distincion con skills hermanas:
- `system-health-audit` = salud de las 3 capas (es el Bloque 1 de esta pasada).
- `audit-pipeline` = meta-auditoria post-pipeline de UN ticket cerrado.
- `audit_agent_output` = auditoria esceptica generica de output (es la
  herramienta del Bloque 2; aqui se aplica a los diffs de la sesion).
- esta pasada = orquesta las anteriores + cierre + memoria en un cierre de sesion.

---

## Prompt

```text
Auditas el cierre de esta sesion como AUDITOR adversarial, no como narrador.

CONTRATO: rige `prompts/audit_agent_output.md` (CEM v0) en su totalidad; no se reproduce aqui. En una frase operativa: evidencia antes que relato (ningun auto-reporte cuenta; solo diff/exit-code/test/bus/SHA/bytes/git), etiqueta cada hallazgo VERIFICADO/INFERIDO/NO VERIFICADO, y responde con conclusiones + evidencia citada, no con volcados de archivos. Para los detalles del contrato (frontera del auditor, verificacion topologica, checklist esceptico, clasificacion CEM) lee el prompt fuente; no los repitas en tu reporte.

REGLA DE PARADA (especifica de esta pasada de cierre): si cualquier gate sale en rojo, o si un hallazgo contradice una afirmacion previa del Builder/Manager, DETENTE. No avances a la promocion de memoria. Surfacea la contradiccion explicitamente (claim original vs evidencia real) en vez de taparla. La memoria solo se promociona sobre una sesion verde y reconciliada.

Ejecuta en este orden y reporta por bloque:

== BLOQUE 1: AUDITORIA DE SALUD DEL SISTEMA (3 auditorias estructurales) ==
1. `prompts/audit_post_change_system_health.md` (contract_id cid-system-health-audit-v0). Recolector determinista primero: `python scripts/collect_system_health.py --motor-root <repo_motor> --project-root <repo_destino> --mode auto`. El script RECOLECTA (testigo read-only); TU AUDITAS (aplicas juicio). Su Fase 8 (pasada adversarial) invoca `prompts/audit_agent_output.md` sobre la salida del recolector: hazla explicita, no implicita.
2. `prompts/audit_complete_motor_destination.md`. Analisis estrategico read-only de arquitectura/portabilidad/loop Builder-Manager. NO muta el arbol; produce blueprint de tickets para DESPUES, no acciones ahora.
3. `prompts/audit_portability_legacy_surface.md`. Inventario read-only de stubs legacy y candidatos a extraer/retirar; propone follow-ups pequenos.

== BLOQUE 2: PASADA ADVERSARIAL SOBRE EL CODIGO GENERADO ESTA SESION (el paso que faltaba) ==
Esta es la barrera critica que el flujo anterior omitia: la salida del Builder nunca se validaba con escepticismo antes de cristalizar aprendizajes.

4. Aplica `prompts/audit_agent_output.md` (su checklist esceptico y clasificacion CEM completos) SOBRE LOS DIFFS DE ESTA SESION, no sobre codigo generico. MODO: solo lectura e inspeccion, NO implementacion. Encuadre especifico para el cierre (el resto lo da el prompt fuente):
   - Encuadre: los "diffs" son los commits productivos de ESTA sesion. Enumeralos con `git log` / `git diff --stat` (cwd=repo_motor). Cita SHAs y rutas reales.
   - Mira especialmente: false-green, root equivocado, fixture drift, scope creep, mock drift, floor assertion (todos definidos en el prompt fuente).
   - Barrera mutation-verified: para cada guard/test nuevo que afirme bloquear un fallo, demuestra que FALLA sin el fix. Un guard que no se demuestra que bloquea no cuenta como barrera.
5. Herramientas de EVIDENCIA de esta pasada (no son las 3 auditorias estructurales). El auditor PROPONE hallazgos; estas skills son consumidoras que IMPLEMENTAN solo si procede y con tu OK:
   - `skills/builder-self-audit/SKILL.md`: las 3 barreras secuenciales del Builder (sintaxis por tipo via py_compile/yaml.safe_load/json.load, completitud multi-archivo, frescura documental PROJECT.md/QUICKSTART.md/TURN.md/STATE.md) deben tener evidencia de salida real, no exit code de un pipe.
   - `skills/builder-run-quality-gates/SKILL.md`: confirma que los gates corrieron via `scripts/run_gates_dispatch.py` (dispatch por deliverable_type), NO invocando ruff/pytest directo (eso evade el audit trail).
   - `skills/code-audit/SKILL.md`: si procede, vulture/deadcode/ruff son generadores de senal, no veredictos; toda categoria DEAD/ABANDONED/LEGACY/SMELL exige triangulacion manual contra git history.
   - `skills/systematic-debugging/SKILL.md`: si la sesion agoto intentos de debug, revisa `execution_log.md` por marcadores de escalado (tope de 3 intentos); un cierre sobre premisa no resuelta es bandera.
   - `prompts/manager_review.md`: confirma que la verificacion mecanica del Manager dispatcho por deliverable_type (ruff/pytest si code|mixed; validate+encoding si docs|research|analysis). Aplicar el gate equivocado invalida la review.

PUNTO DE CONTROL antes del Bloque 3: la sesion debe estar VERDE y RECONCILIADA. Si el Bloque 2 destapa un false-green o una contradiccion, vuelve al Builder; NO continues.

== BLOQUE 3: CIERRE CANONICO ==
6. `prompts/orchestrator_session_close_chat.md` es el WRAPPER orquestador. NO reimplementes sus pasos en este prompt: las skills son la fuente canonica. Invoca el comando canonico unico, que ya orquesta todo el pipeline automaticamente:
   - `python .agent/agent_controller.py --session-close --dry-run --project-root <repo_destino>` (previsualiza, no muta), revisa el reporte.
   - `python .agent/agent_controller.py --session-close --project-root <repo_destino>` (ejecuta). Si `STATE.md` ya esta COMPLETED, anade `--force`.
   - El pipeline orquesta en orden: prepush_check (bloqueante), local_audit, validacion de prosa, observaciones por ticket (`session-close-observations`), consolidacion de memoria (`memory-consolidate`), limpieza de sesion, archivado de collaboration/bus/execution_log, manifest check, git clean. NO repitas estos pasos a mano; los scripts sueltos (`local_audit.py`, `session_close_observations.py`, `memory_consolidate.py --dry-run`) son solo para diagnostico puntual.
   - Learnings y changelog (decisiones humanas, fuera del pipeline automatico): `manager-session-closeout` (`skills/manager-session-closeout/SKILL.md`) clasifica learnings local/generalizable/dudoso y escribe `closeout_lessons.md`; `version-changelog` (`skills/version-changelog/SKILL.md`) propone bump SemVer (tags solo con tu OK explicito).
   - VALIDACION post-cierre obligatoria: `python .agent/agent_controller.py --validate --json --project-root <repo_destino>` debe dar `0 errors / 0 warnings`. Si aparece `bus_drift` post-archive, reconcilia con `scripts/reconcile_ticket.py --ticket <ID> --reason "post-session-close bus drift"` y revalida. NO fabriques eventos de bus a mano.

== BLOQUE 4: PROMOCION DE MEMORIA (decision, no escritura ciega) ==
7. `prompts/memory_upload.md` es GATE de pre-escritura (propose-before-write), NO un volcado al final. Para CADA aprendizaje:
   - Declara el destino ANTES de escribir: Claude privada / portable motor (repo_motor) / portable destino (repo_destino) / varios.
   - Distingue OBSERVACION (hecho objetivo, lo posee session-close-observations) de LEARNING (regla generalizable con evidencia, lo posee manager-session-closeout). No los mezcles en el mismo tier.
   - Sin evidencia verificable (diff/commit/test/exit-code/evento-bus) no hay entrada portable: degrada a dudoso o descarta.
   - Gate de schema-drift: si `observations.jsonl` esta en drift, NO se admiten entradas portables nuevas. Valida contra `skills/_shared/ap-schema.md` y el consumidor real `bus/memory_loader.py`.
   - Promocion a repo_motor (engine/meta) exige confirmacion humana explicita. Las alas portables no se escriben sin aprobacion.
   - Si el Manager detecto un false-positive o fixture drift en el Bloque 2, ese "aprendizaje" NO se cristaliza como hecho: el loop de feedback lo bloquea.

PROPIEDAD DE ARTEFACTOS (quien escribe que, para evitar triple-write ciego):
- `observations.jsonl`: lo posee session-close-observations (observaciones) + manager-session-closeout (learnings locales). memory-consolidate solo dedupe/archiva; nunca lo reescribe a mano.
- `UPSTREAM_LEARNINGS.md`: lo posee manager-session-closeout (generalizables/dudosos con TTL).
- `closeout_lessons.md`: puente para el siguiente manager-create-work-plan; lo posee manager-session-closeout.
- `CHANGELOG.md` + ficheros de version: los posee version-changelog.
- `MEMORY.md`: lo regenera memory-consolidate; no se edita a mano.

VALIDACION FINAL: `python .agent/agent_controller.py --validate --json --project-root <repo_destino>` -> exige `0 errors / 0 warnings`. Reporta exit code real.

Recordatorio: responde con conclusiones etiquetadas (VERIFICADO/INFERIDO/NO VERIFICADO) y evidencia citada (SHA, ruta, exit code), no con volcados de archivos. Si algo sale en rojo, DETENTE en el punto de control correspondiente y surfacea la contradiccion antes de tocar memoria.
```

---

## Cuando usarlo

- Al cerrar una sesion que toco codigo del motor o del destino, ANTES del cierre
  canonico, para auditar adversarialmente los diffs de la sesion.
- Como fase previa recomendada de `orchestrator_session_close_chat.md`.

## Cuando NO usarlo

- Durante un ticket aun en `IN_PROGRESS` (usa el cierre normal del ticket).
- Para arrancar una sesion nueva (usa `orchestrator_session_bootstrap.md`).
- Como sustituto del cierre operativo: esta pasada audita y precede; el cierre
  real lo ejecuta `agent_controller.py --session-close`.
