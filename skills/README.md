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
- `review_bridge` inyecta memoria curada en revisiones futuras
- `bui-implement-from-plan/references/code-rules.md` y `man-review-implementation` reflejan las reglas activas
- `_shared/anti-patterns.md` mantiene el inventario canonicamente numerado AP-01..AP-07

## 2. Tabla operativa

| Skill | Role | Stage | writes_memory | quality_gate | Descripcion |
|---|---|---|---|---|---|
| `setup-agent-system` | `user` | `setup` | `false` | `false` | Instalar y configurar el sistema de agentes con flujo oficial por etapas y compatibilidad legacy Manager+Builder en un proyecto existente |
| `man-create-work-plan` | `manager` | `plan` | `false` | `false` | Crear planes de implementacion estructurados con fases, tareas y criterios de aceptacion |
| `man-review-implementation` | `manager` | `review` | `false` | `false` | Revisar trabajo del Builder segun el plan aprobado y criterios de calidad |
| `man-resolve-escalation` | `manager` | `review` | `false` | `false` | Resolver bloqueos y escalaciones del Builder con decisiones documentadas |
| `bui-implement-from-plan` | `builder` | `implement` | `false` | `false` | Ejecutar un plan aprobado |
| `bui-write-deliverable` | `builder` | `implement` | `false` | `false` | Generar un deliverable markdown (no-codigo) desde descripcion y criterios de aceptacion |
| `bui-run-quality-gates` | `builder` | `quality` | `false` | `true` | Validar codigo con ruff y pytest segun el tipo de entregable |
| `bui-self-audit` | `builder` | `review` | `false` | `false` | Auto-auditoria obligatoria antes de reportar cualquier tarea como completada |
| `test-driven-development` | `shared` | `implement` | `false` | `false` | Metodologia Red/Green/Refactor para mantener la base de codigo libre de regresiones |
| `systematic-debugging` | `shared` | `implement` | `false` | `false` | Proceso riguroso de cuatro fases para diagnosticar y corregir errores |
| `code-audit` | `shared` | `review` | `false` | `false` | Auditoria sistematica de dead code, deuda tecnica y archivos inactivos |
| `refactor-manager` | `shared` | `review` | `false` | `false` | Protocolo de reingenieria segura con analisis, plan, refactor, validacion e iteracion |
| `project-finalize` | `shared` | `close` | `false` | `false` | Cierre profesional con auditoria, limpieza, documentacion, versionado y verificacion final |
| `version-changelog` | `shared` | `close` | `false` | `false` | Gestion semantica de versiones y CHANGELOG.md siguiendo SemVer y Keep a Changelog |
| `session-close-observations` | `shared` | `close` | `true` | `false` | Generar observaciones curadas al final de cada sesion para memoria auto-mejorable |
| `memory-consolidate` | `shared` | `memory` | `true` | `false` | Dedupe, filter y archive de `observations.jsonl` |
| `create-agent-skill` | `shared` | `meta` | `false` | `false` | Meta-skill para crear nuevas micro-skills siguiendo el estandar Agent Skills |
| `graphify` | `shared` | `support` | `false` | `false` | Construir grafo de conocimiento persistente del codebase para exploracion eficiente |
| `local-audit` | `shared` | `support` | `false` | `false` | Generar un snapshot rapido y estructurado del estado del repositorio |
| `repo-compare` | `shared` | `support` | `false` | `false` | Comparar proyecto local con repositorio GitHub para detectar funcionalidades de valor |
| `secure-existing-project` | `shared` | `support` | `false` | `false` | Aplicar arquitectura de seguridad privada/publica a proyecto Python existente |
| `scaffold-python-project` | `shared` | `setup` | `false` | `false` | Crear estructura completa de proyecto Python nuevo con seguridad integrada |

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
- `review_bridge` inyecta memoria curada en el prompt del Manager
- `code-rules.md` del Builder recoge reglas preventivas
- `man-review-implementation` usa el inventario AP-01..AP-07 como checklist bloqueante
- `skills/_shared/anti-patterns.md` es la referencia compartida para Builder y Manager

## 4. Indice compacto

### Manager
- `man-create-work-plan` - plan
- `man-review-implementation` - review
- `man-resolve-escalation` - review

### Builder
- `bui-implement-from-plan` - implement
- `bui-write-deliverable` - implement
- `bui-run-quality-gates` - quality
- `bui-self-audit` - review

### Compartidas
- `test-driven-development` - implement
- `systematic-debugging` - implement
- `code-audit` - review
- `refactor-manager` - review
- `project-finalize` - close
- `version-changelog` - close
- `session-close-observations` - close
- `memory-consolidate` - memory
- `create-agent-skill` - meta
- `graphify` - support
- `local-audit` - support
- `repo-compare` - support
- `secure-existing-project` - support
- `scaffold-python-project` - setup

### Usuario
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

- `man-[accion]` - Skills del Manager
- `bui-[accion]` - Skills del Builder
- `[accion]` - Skills compartidas
- `_shared/` - Inventario y referencias compartidas, fuera del discovery de skills
- `SKILL.md` - frontmatter con taxonomia operativa
- `references/` - documentacion de apoyo

## Referencias

- [Sistema Multi-Agente](../EMPEZAR-AQUI.md)
- [Flujo del Manager](../.agent/workflows/manager_workflow.md)
- [Flujo del Builder](../.agent/workflows/builder_workflow.md)
