# Template de Frontmatter

> Fuente de verdad de los campos requeridos: `REQUIRED_FIELDS` en `skills/validate_all.py`.
> Esta lista se copia a mano aqui por legibilidad — si `validate_all.py` cambia, actualiza
> tambien este fichero en el mismo commit (es el mismo drift que esta correccion resuelve).

## Básico (Obligatorio — exigido por `validate_all.py`)

```yaml
---
name: nombre-skill
version: 1.0.0
description: Descripción clara de una línea
author: agent-system
tags: [tag1, tag2, tag3]
role: shared              # user | shared | manager | builder | auditor
stage: support             # setup | plan | implement | quality | review | close | memory | support | meta
writes_memory: false
quality_gate: false
---
```

## Campos recomendados (no exigidos por `validate_all.py`, pero usados por practicamente todas
## las skills activas — su ausencia impide el discovery por trigger)

```yaml
---
name: nombre-skill
version: 1.0.0
description: Descripción
author: agent-system
tags: [tag1, tag2]
role: shared
stage: support
writes_memory: false
quality_gate: false
triggers: [/comando, alias1, alias2]
---
```

## Campos sin uso actual (documentados historicamente, 0 ocurrencias en las 43 skills reales
## al momento de esta revision; no los anadas salvo que tengas una razon concreta)

```yaml
# requires: [otra-skill]      # Dependencias — sin consumidor conocido
# scope: [manager, builder]   # Quien puede usar — sin consumidor conocido
# difficulty: beginner        # beginner/intermediate/advanced — sin consumidor conocido
```

## Ejemplos por Tipo (nombres reales existentes en `skills/`)

### Skill del Manager
```yaml
name: manager-create-work-plan
version: 2.0.0
description: Crear planes de trabajo estructurados
author: agent
role: manager
stage: plan
writes_memory: false
quality_gate: false
tags: [core, system]
```

### Skill del Builder
```yaml
name: builder-implement-from-plan
version: 2.0.0
description: Implementar nueva funcionalidad basado en especificacion
author: agent
role: builder
stage: implement
writes_memory: false
quality_gate: false
tags: [core, system]
```

### Skill Compartida
```yaml
name: builder-run-quality-gates
version: 2.0.0
description: Ejecutar gates apropiados según deliverable_type del WP activo
author: agent
role: builder
stage: quality
writes_memory: false
quality_gate: true
tags: [core, system]
```

## Tags Recomendados

| Categoría | Tags |
|-----------|------|
| Rol | `manager`, `builder` |
| Acción | `planning`, `review`, `implementation`, `testing` |
| Tema | `security`, `architecture`, `quality`, `setup` |
