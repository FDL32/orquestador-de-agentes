# AUDIT - WOT-2026-016o

**Ticket:** WOT-2026-016o - classify_publication: aplicar REDACTION_PATTERNS tambien a la historia (H1 history-blind a PII)
**Estado del plan:** APPROVED

## TP Check

- TP-01: verificado - fases secuenciales: Fase 0 confirma el gap en codigo (lineas citadas),
  Fase 1 integra el scan PII en el MISMO recorrido de blobs (cero iteracion extra), Fase 2
  testea con mutation. Sin contradicciones.
- TP-02: verificado - criterios con comandos/salidas literales: pytest focal 4 passed + suite
  classify 70 passed, mutation via monkeypatch REDACTION_PATTERNS=[], muestras enmascaradas
  (assert '***' presente y PII entera ausente), ruff 0, encoding 0, suite canonica sha==HEAD.
- TP-03: verificado - enumera el codigo nuevo (HISTORY_PII_PLACEHOLDER_PATTERNS,
  _is_pii_placeholder, _mask_pii_sample, _collect_blob_pii_samples,
  _collect_history_blob_paths, HISTORY_PII_PENDING, history_pii_scan) y Non-goals explicitos
  (SECRET_PATTERNS intactos, tree-side intacto, sin rewrite automatico, 016m aparte).
- TP-04: verificado - decision cerrada: PII-en-historia = DECIDE_PENDING (exit 3, decision
  humana), NO BLOQUEADO_POR_SECRETO (exit 1); razon registrada en work_plan.
- TP-05: verificado - plan/audit/log describen el mismo diff; el hallazgo D1 (fixtures tests/
  exentas, heredado del tree-side) quedo documentado como decision de paridad, no scope creep.

## Blockers

- Ninguno. Hallazgo gestionado: el test D1 existente exigia paridad de la exencion tests/
  en historia -> anadida (espejo del tree-side; secret_risk NUNCA se suprime, igual que antes).
  C901 resuelto factorizando helpers puros (sin cambio de comportamiento; 70/70 verdes).

## Evidencia esperada al cierre

- pytest tests/test_classify_history_pii.py (4) + tests/test_classify_publication.py (66) verdes.
- MUTATION: REDACTION_PATTERNS=[] -> history_pii_scan.ok=True (falso verde reproducido).
- Suite canonica --level all exit 0 sha==HEAD; validate 0/0; commit con ID 016o.
