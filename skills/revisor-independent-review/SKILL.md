---
name: revisor-independent-review
role: revisor
source_prompt: prompts/revisor_independent_review.md
contract_id: cid-revisor-review-v1
disable_model_invocation: true
triggers: [/revisor-review, /verify]
---

# revisor-independent-review

## Cuándo usar

Cuando se necesita una revision adversarial independiente de la implementacion del Builder.
Usar para la Capa 1.5 (Persona-2) del sistema de 4 capas: el Revisor revisa el trabajo
del Builder con su propio backend/modelo, nunca el mismo que el Builder.

## Cuándo no usar

- Para implementacion de codigo (ese es el Builder).
- Para revision de gobierno/ensemble con propuesta de cambios estructurales (proposer/challenger).
- Para validacion automatica de tests (eso corre la suite canonica, no el Revisor).

## Contrato

Este prompt se midia contra `prompts/revisor_independent_review.md`: role revisor,
route_kind entry, cycle_phase F6-revision, contract_id cid-revisor-review-v1, con
PROMPT-SUMMARY y ancla inversa. El binding es ENFORCED (opt-in revisor activo).

## Fuente normativa

Las instrucciones completas del Revisor (identidad, veredicto, alcance, remisiones,
anclaje) viven una vez en el prompt canonico: `prompts/revisor_independent_review.md`.
El prompt es source_of_truth. Esta skill solo apunta.
