# Anatomía de un SKILL.md

## Estructura General

```markdown
---
name: nombre-skill
version: 1.0.0
description: Descripción clara
author: agent-system
tags: [tag1, tag2]
---

# nombre-skill

## Overview
Contexto y propósito (2-3 líneas).

## Workflow
Pasos numerados claros.

## Output Format
Resultado esperado.

## References
Lista de references.

## Constraints
Reglas que NO deben romperse.
```

## Frontmatter Obligatorio

| Campo | Descripción | Ejemplo |
|-------|-------------|---------|
| name | Nombre kebab-case | `man-review-code` |
| version | Semver | `1.0.0` |
| description | Una línea clara | `Revisar código del Builder` |
| author | Creador | `agent-system` |
| tags | Categorías | `[manager, review]` |

## Body: Secciones Requeridas

1. **Overview** - Contexto y propósito
2. **Workflow** - Pasos numerados
3. **Output Format** - Qué produce
4. **References** - Links a docs
5. **Constraints** - Reglas estrictas

## Progressive Disclosure

```
Frontmatter (metadata)
    ↓
Body (instrucciones)
    ↓
References (detalles)
```

El agente carga solo lo necesario.
