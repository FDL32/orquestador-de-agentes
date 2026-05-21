---
name: create-agent-skill
version: 1.0.0
description: Meta-skill para crear nuevas micro-skills siguiendo el estÃ¡ndar Agent Skills
triggers: [/create-skill, skill-create, /new]
author: agent
tags: [core, system]
---

# create-agent-skill

Crea nuevas micro-skills portables siguiendo el estÃ¡ndar establecido.

## Overview

Cuando necesitas una nueva skill para una acciÃ³n especÃ­fica, usa esta skill para crearla correctamente.

## Workflow

### Paso 1: Definir PropÃ³sito

Determinar:
- **Â¿QuÃ© acciÃ³n realiza?** (una sola, concreta)
- **Â¿QuiÃ©n la usa?** (Manager / Builder / Ambos)
- **Â¿QuÃ© necesita saber el agente?** (contexto mÃ­nimo)

### Paso 2: Identificar Fuentes

Buscar en el sistema actual:
- Workflows relevantes
- Reglas del agente
- Protocolos existentes
- CÃ³digo de referencia

**Principio:** Condensar, no copiar.

### Paso 3: Crear Estructura

```bash
# Nombre en kebab-case
mkdir -p skills/[nombre-skill]/references
```

**ConvenciÃ³n de nombres:**
- `man-[accion]` - Skills del Manager
- `bui-[accion]` - Skills del Builder
- `[accion]` - Skills compartidas (sin prefijo)

### Paso 4: Escribir SKILL.md

Estructura obligatoria:
```markdown
---
name: nombre-skill
version: 1.0.0
description: DescripciÃ³n clara de una lÃ­nea
author: agent-system
tags: [tag1, tag2, tag3]
---

# nombre-skill

DescripciÃ³n breve (1-2 lÃ­neas).

## Overview

CuÃ¡ndo y para quÃ© usar esta skill.

## Workflow

### Paso 1: [Nombre del paso]
Instrucciones claras...

### Paso 2: [Nombre del paso]
...

## Output Format

QuÃ© produce esta skill.

## References

- `references/ref1.md` - DescripciÃ³n

## Constraints

- **NO** hacer X
- **SIEMPRE** hacer Y
```

**LÃ­mites:**
- SKILL.md: mÃ¡ximo 250 lÃ­neas
- References: mÃ¡ximo 80 lÃ­neas cada una

### Paso 5: Crear References

Extraer y condensar de las fuentes:
- Checklists
- Templates
- Ejemplos de cÃ³digo
- Formatos

### Paso 6: Validar

```bash
python skills/validate_all.py
```

Verificar:
- [ ] Frontmatter YAML vÃ¡lido
- [ ] Campos requeridos: name, version, description, author, tags
- [ ] Cuerpo no supera 250 lÃ­neas
- [ ] References no superan 80 lÃ­neas
- [ ] Carpeta `references/` existe

### Paso 7: Documentar

AÃ±adir a `skills/README.md`:
```markdown
| nombre-skill | DescripciÃ³n | Manager/Builder | tags |
```

## Progressive Disclosure

Estructura de informaciÃ³n:
1. **Frontmatter** - Metadatos esenciales
2. **Body** - Instrucciones paso a paso
3. **References** - Detalles de apoyo

## Output

Nueva skill en:
```
skills/[nombre-skill]/
â”œâ”€â”€ SKILL.md           # Instrucciones principales
â””â”€â”€ references/        # DocumentaciÃ³n de apoyo
    â”œâ”€â”€ ref1.md
    â””â”€â”€ ref2.md
```

## References

- `references/skill-anatomy.md` - AnatomÃ­a de un SKILL.md
- `references/frontmatter-template.md` - Template de frontmatter

## Constraints

- **UNA** acciÃ³n por skill
- **MÃXIMO** 250 lÃ­neas en SKILL.md
- **MÃXIMO** 80 lÃ­neas por reference
- **SIEMPRE** validar con `validate_all.py`
- **USAR** prefijos man-/bui- segÃºn corresponda
