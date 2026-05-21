# Catalogo de Micro-Skills

> **Sistema Multi-Agente v5** - Skills portables para Manager y Builder

## Resumen

| # | Skill | Descripcion | Usuario | Tags |
|---|-------|-------------|---------|------|
| 1 | `man-review-implementation` | Revisar trabajo del Builder | Manager | `manager`, `review`, `quality` |
| 2 | `man-create-work-plan` | Crear planes de trabajo | Manager | `manager`, `planning`, `architecture` |
| 3 | `man-resolve-escalation` | Resolver bloqueos del Builder | Manager | `manager`, `escalation`, `decision` |
| 4 | `bui-implement-from-plan` | Ejecutar un plan aprobado | Builder | `builder`, `implementation`, `coding` |
| 5 | `bui-run-quality-gates` | Validar codigo con ruff y pytest | Builder | `builder`, `testing`, `quality` |
| 6 | `bui-self-audit` | Auto-auditoria obligatoria antes de review | Builder | `builder`, `audit`, `quality` |
| 7 | `graphify` | Construir un grafo persistente del codebase | Builder | `graphify`, `tokens`, `knowledge-graph` |
| 8 | `project-finalize` | Cierre profesional: auditoria, limpieza y docs | Ambos | `closeout`, `cleanup`, `documentation` |
| 9 | `version-changelog` | Gestion semantica de versiones y changelog | Ambos | `versioning`, `semver`, `changelog` |
| 10 | `secure-existing-project` | Aplicar seguridad a proyecto existente | Ambos | `security`, `architecture`, `migration` |
| 11 | `scaffold-python-project` | Crear estructura de proyecto Python nuevo | Ambos | `python`, `project`, `scaffold` |
| 12 | `setup-agent-system` | Instalar el sistema multi-agente | Usuario | `setup`, `multi-agent`, `configuration` |
| 13 | `create-agent-skill` | Crear nuevas micro-skills | Ambos | `meta`, `skill-creation`, `template` |
| 14 | `code-audit` | AuditorÃ­a sistemÃ¡tica: dead code, deuda tÃ©cnica, abandono | Builder | `audit`, `quality`, `python`, `builder` |

## Uso por Rol

### Manager
- `man-review-implementation` - Revisar codigo
- `man-create-work-plan` - Planificar
- `man-resolve-escalation` - Resolver bloqueos

### Builder
- `bui-implement-from-plan` - Implementar
- `bui-run-quality-gates` - Validar calidad
- `bui-self-audit` - Auto-auditar antes de review
- `code-audit` - Auditar dead code, deuda tÃ©cnica, archivos inactivos
- `graphify` - Explorar corpus grandes con menos tokens

### Compartidas
- `project-finalize` - Cierre profesional
- `version-changelog` - Versionado y changelog
- `secure-existing-project` - Seguridad
- `scaffold-python-project` - Crear proyectos
- `create-agent-skill` - Crear skills

### Usuario / Setup
- `setup-agent-system` - Instalacion inicial

## Estructura

Cada skill contiene:
```
skill-name/
|-- SKILL.md              # Instrucciones principales
`-- references/           # Documentacion de apoyo
    |-- ref1.md
    `-- ref2.md
```

## Validacion

```bash
python skills/validate_all.py
```

Verifica:
- Frontmatter YAML valido
- Campos requeridos presentes
- Estructura correcta

## Convenciones

**Nombres:**
- `man-[accion]` - Skills del Manager
- `bui-[accion]` - Skills del Builder
- `[accion]` - Skills compartidas

**Limites:**
- SKILL.md: maximo 250 lineas
- References: maximo 80 lineas cada una

## Referencias

- [Sistema Multi-Agente](../EMPEZAR-AQUI.md)
- [Flujo del Manager](../.agent/workflows/manager_workflow.md)
- [Flujo del Builder](../.agent/workflows/builder_workflow.md)
