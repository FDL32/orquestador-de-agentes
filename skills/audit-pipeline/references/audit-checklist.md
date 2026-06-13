# Audit Checklist (meta-auditoria del pipeline)

Checklist binario para la meta-auditoria read-only. Acompaña a
`prompts/audit_pipeline.md`; no lo sustituye.

## Fase 0 — Vision global

- [ ] `backlog.md` leido completo.
- [ ] `pipeline_closeout_*.md` mas reciente leido.
- [ ] Todos los `closeout_*.md` listados.
- [ ] Matriz objetivo -> ticket -> evidencia -> estado construida.
- [ ] Cada objetivo clasificado: CUBIERTO / PARCIAL / HUERFANO / NO_VERIFICABLE.

## Fase 1 — Por ticket (doble pasada)

Pasada A (verificacion):

- [ ] Commit con el ticket existe (`git log --oneline`).
- [ ] Diff toca solo lo declarado o justificado (`git show --stat`).
- [ ] Gates focales re-ejecutados (ruff + tests del ticket) con exit code real.
- [ ] Closeout con etiquetas de evidencia y artefacto concreto.
- [ ] Encoding del closeout limpio.
- [ ] Criterios de aceptacion del plan satisfechos por evidencia.

Pasada B (refutacion):

- [ ] Buscado falso verde (test pasa con y sin fix; gate solo en arbol limpio).
- [ ] Buscado scope creep entre tickets.
- [ ] Buscado claim `VERIFICADO` cuyo artefacto no resuelve.
- [ ] Buscado fixture irreal / mock drift.
- [ ] Buscado estado canonico incoherente (BUILDER_EXIT sin terminal, etc.).

## Fase 2 — Transversal

- [ ] Dependencias entre tickets coherentes en el tiempo.
- [ ] Objetivos huerfanos y parciales listados.
- [ ] Deuda residual declarada y nunca retomada identificada.
- [ ] Contradicciones entre closeouts detectadas.
- [ ] Drift de motor agregado de los `motor_after_*.json`.

## Cierre

- [ ] Veredicto global emitido (1 de 4).
- [ ] Informe `.md` y artifact `.json` escritos en el mismo turno.
- [ ] `check_encoding_guard.py` sobre el informe: limpio.
- [ ] Cero escrituras a backlog, codigo, estado o motor (read-only verificado).
