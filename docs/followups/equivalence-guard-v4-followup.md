# Follow-up: guard de equivalencia modulo<->blob (equivalencia R1, WOT-2026-025c)

## Metadata propuesta
- **ID sugerido:** siguiente `WOT-2026-NNN` libre.
- **deliverable_type:** code (script de verificacion + cableado a pre-push).
- **delivery_authority:** repo_motor
- **Prioridad:** Media (barrera de calidad para cualquier lote de traslado de secciones de
  `AGENTS.md`).

## Objetivo

Implementar `verify_equivalence_v4.py` (o nombre equivalente) que compare el bloque
trasladado en `.agent/rules/common/memory_hierarchy.md` contra el blob original de
`AGENTS.md` en el repo, garantizando identidad byte-a-byte antes de cada push.

## Antecedentes

El contrato P6 declaro (Seccion 7, deuda 2) que `verify_equivalence_v3.py` NO EXISTE
en el arbol ni en su historia. La barrera de no-degradacion de R1 fue PROCEDURAL:
scripts de sesion nunca commiteados. La verificacion P6 se hizo con un script
temporal de una sola corrida (check 1 del PASO 4, antes del commit).

## Contrato del fix (minimo)
- Script que: (a) extrae el blob git de la seccion origen pinneada a un HEAD; (b)
  extrae el cuerpo del modulo destino desde `## <titulo>` hasta EOF del bloque;
  (c) compara `==`; (d) exit 0 si iguales, exit 1 si no.
- Cableado a pre-push (opcional, configurable en `.pre-commit-config.yaml`).
- Cada traslado futuro: ejecutar ANTES del commit y pegar el recibo.

## Non-goals
- No definir una politica de "cuantos lotes por push" (decision de producto).
- No reescribir `AGENTS.md` (ese trabajo se gestiona con `agents-md-over-quota-followup.md`).

## Criterio binario de cierre
- [ ] `verify_equivalence_v4.py` existe, pasa `ruff` y `pytest`.
- [ ] Se usa al menos una vez como recibo en la corrida P6 (o se demuestra que
      P6 no lo necesita por ser el primer traslado).
