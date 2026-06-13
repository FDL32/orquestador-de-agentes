# Audit Checklist (meta-auditoria del pipeline)

Checklist binario para la meta-auditoria read-only. Acompana a
`prompts/audit_pipeline.md`; no lo sustituye.

## Fase 0 - Vision global

- [ ] `AGENT_PROJECT_ROOT`, `MOTOR_ROOT` y `repo_destino` declarados.
- [ ] `check_motor_pristine.py` ejecutado como self-integrity check.
- [ ] Si las rutas no apuntan al destino/motor esperados, veredicto distinto de `APROBADO`.
- [ ] `backlog.md` leido completo.
- [ ] `pipeline_closeout_*.md` mas reciente seleccionado de forma deterministica.
- [ ] Si no hay `pipeline_closeout_*.md`, veredicto distinto de `APROBADO`.
- [ ] Todos los `closeout_*.md` listados.
- [ ] Multiples closeouts por ticket resueltos por timestamp; descartados registrados.
- [ ] Matriz objetivo -> ticket -> evidencia -> estado construida.
- [ ] Cada objetivo clasificado: CUBIERTO / PARCIAL / HUERFANO / NO_VERIFICABLE.
- [ ] Closeout obligatorio ausente registrado como `EVIDENCIA_AUSENTE`.

## Fase 1 - Por ticket (doble pasada)

Pasada A (verificacion):

- [ ] `deliverable_type` leido del plan.
- [ ] Commit con el ticket existe (`git log --oneline`).
- [ ] Diff toca solo lo declarado o justificado (`git show --stat`).
- [ ] Para `code` / `mixed`: gates focales re-ejecutados con exit code real.
- [ ] Para `documentation` / `research` / `analysis`: artefactos declarados existen y tienen contenido suficiente.
- [ ] No se exigio `ruff`/`pytest` a ticket no-code salvo que tocara codigo.
- [ ] Si el ticket afirma corregir bug/regresion, buscada evidencia de fallo previo.
- [ ] Si no hay fallo previo, la barrera queda como `INFERENCIA RAZONABLE` o no demostrada.
- [ ] Para tests `code`/`mixed` con mocks/patches, firmas/rutas contrastadas contra codigo real.
- [ ] `audit_scope_patterns` derivadas de `Files Likely Touched` si el cierre global no las declara.
- [ ] Closeout con etiquetas de evidencia y artefacto concreto.
- [ ] Encoding del closeout limpio.
- [ ] Criterios de aceptacion del plan satisfechos por evidencia.

Pasada B (refutacion):

- [ ] Buscado falso verde (test pasa con y sin fix; gate solo en arbol limpio).
- [ ] Buscado scope creep entre tickets usando diff vivo o commits asociados.
- [ ] Buscado claim `VERIFICADO` cuyo artefacto no resuelve.
- [ ] Buscado uso indebido de `git diff` vacio como evidencia de ausencia de cambios.
- [ ] Buscado fixture irreal / mock drift.
- [ ] Buscado estado canonico incoherente (BUILDER_EXIT sin terminal, etc.).

## Fase 2 - Transversal

- [ ] Dependencias entre tickets coherentes en el tiempo.
- [ ] Objetivos huerfanos y parciales listados.
- [ ] Deuda residual declarada y nunca retomada identificada.
- [ ] Contradicciones entre closeouts detectadas.
- [ ] Cada hallazgo transversal declara Clase CEM.
- [ ] Drift de motor agregado de los `motor_after_*.json`.
- [ ] `INTEGRITY_VIOLATION_DETECTED` usado para cambios reales de motor.
- [ ] `MOTOR_WRITE_DENIED` usado para intentos bloqueados sin asumir motor sucio.
- [ ] `motor_integrity.per_ticket` rellenado.

## Cierre

- [ ] Veredicto global emitido (1 de 4).
- [ ] `audit_scope.included_tickets` no esta vacio si el veredicto es `APROBADO`.
- [ ] Informe `.md` y artifact `.json` escritos en el mismo turno.
- [ ] Informe Markdown incluye alcance auditado.
- [ ] JSON incluye `audit_scope`, `audit_scope_patterns`, `audit_scope_description`.
- [ ] JSON incluye `runtime_topology`.
- [ ] JSON incluye `source_snapshot` con `path`, `exists`, `size_bytes` y `sha256` opcional/recomendado.
- [ ] JSON incluye `source_reports` con `path`, `exists`, `role`.
- [ ] JSON incluye `missing_evidence`, `integrity_events`, `motor_integrity.per_ticket`.
- [ ] JSON incluye `improvements[].severity`.
- [ ] `check_encoding_guard.py` sobre el informe `.md`: limpio.
- [ ] Si el `.json` contiene texto libre, `check_encoding_guard.py` tambien sobre `.json`.
- [ ] Cero escrituras a backlog, codigo, estado o motor (read-only verificado).
