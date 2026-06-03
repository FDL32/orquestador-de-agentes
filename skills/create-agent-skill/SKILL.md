---
name: create-agent-skill
version: 2.0.0
description: Meta-skill para crear nuevas micro-skills siguiendo el estándar Agent Skills
triggers: [/create-skill, skill-create, /new]
author: agent
role: shared
stage: meta
writes_memory: false
quality_gate: false
tags: [core, system]
---

# create-agent-skill

Crea nuevas micro-skills portables siguiendo el estándar establecido.

## Overview

Cuando necesitas una nueva skill para una acción específica, usa esta skill para crearla correctamente.

## Workflow

### Paso 1: Definir Propósito

Determinar:
- **¿Qué acción realiza?** (una sola, concreta)
- **¿Quién la usa?** (Manager / Builder / Ambos)
- **¿Qué necesita saber el agente?** (contexto mínimo)

### Paso 2: Identificar Fuentes

Buscar en el sistema actual:
- Workflows relevantes
- Reglas del agente
- Protocolos existentes
- Código de referencia

**Principio:** Condensar, no copiar.

### Paso 3: Crear Estructura

```bash
# Nombre en kebab-case
mkdir -p skills/[nombre-skill]/references
```

**Convención de nombres:**
- `man-[accion]` - Skills del Manager
- `bui-[accion]` - Skills del Builder
- `[accion]` - Skills compartidas (sin prefijo)

### Paso 4: Escribir SKILL.md

Estructura obligatoria:
```markdown
---
name: nombre-skill
version: 1.0.0
description: Descripción clara de una línea
author: agent-system
tags: [tag1, tag2, tag3]
---

# nombre-skill

Descripción breve (1-2 líneas).

## Overview

Cuándo y para qué usar esta skill.

## Workflow

### Paso 1: [Nombre del paso]
Instrucciones claras...

### Paso 2: [Nombre del paso]
...

## Output Format

Qué produce esta skill.

## References

- `references/ref1.md` - Descripción

## Constraints

- **NO** hacer X
- **SIEMPRE** hacer Y
```

**Límites:**
- SKILL.md: máximo 250 líneas
- References: máximo 80 líneas cada una

### Paso 5: Crear References

Extraer y condensar de las fuentes:
- Checklists
- Templates
- Ejemplos de código
- Formatos

### Paso 6: Validar

```bash
python skills/validate_all.py
```

Verificar:
- [ ] Frontmatter YAML válido
- [ ] Campos requeridos: name, version, description, author, tags
- [ ] Cuerpo no supera 250 líneas
- [ ] References no superan 80 líneas
- [ ] Carpeta `references/` existe

### Paso 7: Documentar

Añadir a `skills/README.md`:
```markdown
| nombre-skill | Descripción | Manager/Builder | tags |
```

## Progressive Disclosure

Estructura de información:
1. **Frontmatter** - Metadatos esenciales
2. **Body** - Instrucciones paso a paso
3. **References** - Detalles de apoyo

## Output

Nueva skill en:
```
skills/[nombre-skill]/
├── SKILL.md           # Instrucciones principales
└── references/        # Documentación de apoyo
    ├── ref1.md
    └── ref2.md
```

## References

- `references/skill-anatomy.md` - Anatomía de un SKILL.md
- `references/frontmatter-template.md` - Template de frontmatter

## Constraints

- **UNA** acción por skill
- **MÁXIMO** 250 líneas en SKILL.md
- **MÁXIMO** 80 líneas por reference
- **SIEMPRE** validar con `validate_all.py`
- **USAR** prefijos man-/bui- según corresponda
