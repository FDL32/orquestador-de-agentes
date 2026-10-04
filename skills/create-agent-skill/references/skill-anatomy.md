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

> Fuente de verdad: `REQUIRED_FIELDS` en `skills/validate_all.py`. Si ese set cambia, actualiza
> esta tabla en el mismo commit.

| Campo | Descripción | Ejemplo |
|-------|-------------|---------|
| name | Nombre kebab-case (`manager-`/`builder-` para esos roles, sin prefijo corto) | `manager-review-implementation` |
| version | Semver | `1.0.0` |
| description | Una línea clara | `Revisar código del Builder` |
| author | Creador | `agent` |
| tags | Categorías | `[manager, review]` |
| role | `user \| shared \| manager \| builder \| auditor` | `manager` |
| stage | `setup \| plan \| implement \| quality \| review \| close \| memory \| support \| meta` | `review` |
| writes_memory | boolean | `false` |
| quality_gate | boolean | `false` |

**Recomendado (no exigido por el validador):** `triggers` — lista de comandos/alias que activan
la skill. Su ausencia no falla `validate_all.py`, pero impide el discovery por trigger.

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
