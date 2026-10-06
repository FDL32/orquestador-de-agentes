# Catalogo de Micro-Skills

> Sistema Multi-Agente v6 - Skills portables para Manager, Builder y soporte compartido

## 1. Mapa del ciclo

```text
setup -> plan -> implement -> review -> quality -> close -> memory
   ^                                                        |
   +---------------------- meta / support -------------------+
```

Flujo minimo de mejora continua:
- el Builder implementa desde el plan aprobado
- el Manager revisa y deja observaciones o bloqueos
- `session-close-observations` convierte aprendizajes en memoria
- `manager-session-closeout` clasifica learnings de cierre y separa alcance local/generalizable
- `review_bridge` inyecta memoria curada en revisiones futuras
- `builder-implement-from-plan/references/code-rules.md` y `manager-review-implementation` reflejan las reglas activas
- `_shared/anti-patterns.md` mantiene el inventario canonicamente numerado AP-01..AP-14

## 2. Tabla operativa

> DEC-router-skills-001 D-S6: esta tabla ya no se mantiene a mano (documentaba 25/43, desactualizada).
> La proyeccion completa y generada de las skills-puntero vive en
> [`docs/registry/ROUTER.md`](../docs/registry/ROUTER.md) (columna `Skill` de cada fila de prompt,
> mas la seccion "Skills autocontenidas por fase" para las que no apuntan a un prompt). Para el
> listado tecnico crudo de las 43 (role/stage/flags), usa `python scripts/discover_skills.py --json`
> o `docs/registry/INDEX.md`.
> Regenera con `python scripts/discover_skills.py --generate-index`; `--check-index` detecta deriva.

## 3. Bucle de mejora continua

```text
bug / finding humano
  -> observations.jsonl
  -> session-close-observations
  -> review_bridge
  -> Manager review prompt
  -> nueva deteccion / nuevo aprendizaje
```

Fuentes y destinos:
- `observations.jsonl` guarda aprendizajes persistentes
- `session-close-observations` consolida aprendizajes al cerrar sesion
- `manager-session-closeout` clasifica learnings de cierre y prepara el puente hacia el motor
- `review_bridge` inyecta memoria curada en el prompt del Manager
- `code-rules.md` del Builder recoge reglas preventivas
- `manager-review-implementation` usa el inventario AP-01..AP-14 como checklist bloqueante
- `skills/_shared/anti-patterns.md` es la referencia compartida para Builder y Manager

## 4. Indice compacto

### Manager
- `manager-create-work-plan` - plan
- `manager-review-implementation` - review
- `manager-resolve-escalation` - review

### Builder
- `builder-implement-from-plan` - implement
- `builder-write-deliverable` - implement
- `builder-run-quality-gates` - quality
- `builder-self-audit` - review

### Compartidas
- `test-driven-development` - implement
- `systematic-debugging` - implement
- `code-audit` - review
- `refactor-manager` - review
- `project-finalize` - close
- `version-changelog` - close
- `session-close-observations` - close
- `manager-session-closeout` - close
- `memory-consolidate` - memory
- `create-agent-skill` - meta
- `graphify` - support
- `local-audit` - support
- `repo-compare` - support
- `secure-existing-project` - support
- `scaffold-python-project` - setup
- `deep-research` - support

### Usuario
- `grill-work-plan` - plan
- `setup-agent-system` - setup

## Validacion

```bash
python skills/validate_all.py
```

Verifica:
- frontmatter YAML valido
- campos requeridos presentes
- enums validos para `role` y `stage`
- tipos booleanos para `writes_memory` y `quality_gate`
- directorios que empiezan por `_` se tratan como infraestructura compartida y no se validan como skills
- `references/` es recomendado; si falta o solo tiene `.gitkeep`, el validador avisa pero no falla

## Convenciones

- `manager-[accion]` - Skills del Manager
- `builder-[accion]` - Skills del Builder
- `[accion]` - Skills compartidas / auditor / usuario (sin prefijo de rol)
- (el prefijo corto `man-`/`bui-` fue el diseño original pero nunca se adopto como nombre de
  carpeta; sigue vivo solo en `contract_id` historicos como `cid-man-review-v2` o
  `cid-bui-implement-v1`, que no se renombran)
- `_shared/` - Inventario y referencias compartidas, fuera del discovery de skills
- `SKILL.md` - frontmatter con taxonomia operativa
- `references/` - documentacion de apoyo

## Referencias

- [Sistema Multi-Agente](../EMPEZAR-AQUI.md)
- [Flujo del Manager](../.agent/workflows/manager_workflow.md)
- [Flujo del Builder](../.agent/workflows/builder_workflow.md)
