### Gobierno skill<->prompt: skill apunta, prompt gobierna (WOT-2026-014r / X-09)



Cuando una skill tiene prompt canonico (declara `contract_id` + `source_prompt`/`source_of_truth`), la skill es

PUNTERO operativo, no fuente normativa. PROHIBIDO re-declarar criterios normativos (gates, veredictos, estados,

barreras) en la `SKILL.md`: viven una vez en el prompt y la skill remite. Si divergen, prevalece el prompt y la

divergencia es un bug de la skill. Verificado en vivo: el SKILL de `manager-review-implementation` OMITIA

mutation-verify (E3) y el de `orchestrate-pipeline` OMITIA el reconcile post-close (E6) por re-declarar en vez de

apuntar.



**Auditoria automatica (R2):** un linter/gate puede grepear las `SKILL.md` por marcadores normativos

(`DECISION:`, `deliverable_type`, `0 errors`, `APROBADO|CHANGES|BLOCKER`, `exit code`). Un marcador en una skill

que TIENE prompt canonico es candidato a re-declaracion: el gate exige que la skill REMITA al prompt (cita

`contract_id`) en vez de definir el criterio. Si el criterio diverge del prompt -> hallazgo automatico, prevalece

el prompt. Verificado (3a pasada): 9 `SKILL.md` contienen esos marcadores -- adopt-existing-project, audit-pipeline,

builder-run-quality-gates, manager-create-work-plan, manager-review-implementation, orchestrate-pipeline,

refactor-manager, session-close-full-audit, setup-agent-system -- candidatas a re-declaracion (una parte solo

menciona el marcador). La matriz de ownership de artefactos asociada vive en `prompts/_shared/artifact_ownership.md`.



### Gobierno prompt-hijo<->prompt-nucleo: extension de X-09 un nivel arriba (2026-10-08)



El mismo principio de X-09 ("skill apunta, prompt gobierna") se aplica un nivel arriba: cuando un

prompt declara `nucleo_referenciado` (un prompt-hijo especializa un nucleo portable, como

`manager_orchestrator_loop_backlog.md` especializa a `manager_orchestrator_loop.md`), el prompt-hijo

REMITE a las secciones del nucleo que coinciden en OBJETO, no las REDECLARA en prosa paralela. Si

el objeto diverge de verdad (el hijo cubre un caso que el nucleo no contempla), el hijo puede

reescribir esa seccion COMPLETA, pero debe etiquetarla explicitamente como EXCEPCION/ESPECIALIZACION

-- nunca una copia silenciosa que se desincroniza en la siguiente correccion del nucleo.



Motivo medido (bucle de gobierno DESIGN_REVIEW, 5 lentes independientes, 2026-10-08):

`manager_orchestrator_loop_backlog.md` declaraba `source_of_truth: este prompt` pese a listar

`nucleo_referenciado`, y SU SCHEMA DE METRICAS (seccion 6) redeclaraba el `SCHEMA: adjudicacion`

del nucleo sin declarar sus diferencias reales. Corregido: la seccion 6 remite de verdad, con las

diferencias de campos y de enum declaradas explicitamente.



**Advertencia del propio caso (correccion posterior, MANAGER_REVIEW con lente

nan/deepseek-v4-flash, 2026-10-08):** 5 lentes adjudicaron mal por semejanza estructural (numero

de posicion) en vez de comparar contenido literal; detalle completo e incidente en

`docs/protocol/x09_adjudication_position_vs_content_case.md`.

