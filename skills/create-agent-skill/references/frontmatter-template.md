# Template de Frontmatter

## Básico (Obligatorio)

```yaml
---
name: nombre-skill
version: 1.0.0
description: Descripción clara de una línea
author: agent-system
tags: [tag1, tag2, tag3]
---
```

## Campos Opcionales

```yaml
---
name: nombre-skill
version: 1.0.0
description: Descripción
author: agent-system
tags: [tag1, tag2]
# Opcionales:
requires: [otra-skill]      # Dependencias
scope: [manager, builder]   # Quién puede usar
difficulty: beginner        # beginner/intermediate/advanced
---
```

## Ejemplos por Tipo

### Skill del Manager
```yaml
name: man-create-work-plan
version: 1.0.0
description: Crear planes de trabajo estructurados
author: agent-system
tags: [manager, planning, architecture]
```

### Skill del Builder
```yaml
name: bui-implement-feature
version: 1.0.0
description: Implementar funcionalidad según plan
author: agent-system
tags: [builder, implementation, coding]
```

### Skill Compartida
```yaml
name: run-quality-gates
version: 1.0.0
description: Ejecutar validación de código
author: agent-system
tags: [quality, testing, linting]
```

## Tags Recomendados

| Categoría | Tags |
|-----------|------|
| Rol | `manager`, `builder` |
| Acción | `planning`, `review`, `implementation`, `testing` |
| Tema | `security`, `architecture`, `quality`, `setup` |
