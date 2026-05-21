# AnatomÃ­a de un SKILL.md

## Estructura General

```markdown
---
name: nombre-skill
version: 1.0.0
description: DescripciÃ³n clara
author: agent-system
tags: [tag1, tag2]
---

# nombre-skill

## Overview
Contexto y propÃ³sito (2-3 lÃ­neas).

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

| Campo | DescripciÃ³n | Ejemplo |
|-------|-------------|---------|
| name | Nombre kebab-case | `man-review-code` |
| version | Semver | `1.0.0` |
| description | Una lÃ­nea clara | `Revisar cÃ³digo del Builder` |
| author | Creador | `agent-system` |
| tags | CategorÃ­as | `[manager, review]` |

## Body: Secciones Requeridas

1. **Overview** - Contexto y propÃ³sito
2. **Workflow** - Pasos numerados
3. **Output Format** - QuÃ© produce
4. **References** - Links a docs
5. **Constraints** - Reglas estrictas

## Progressive Disclosure

```
Frontmatter (metadata)
    â†“
Body (instrucciones)
    â†“
References (detalles)
```

El agente carga solo lo necesario.
