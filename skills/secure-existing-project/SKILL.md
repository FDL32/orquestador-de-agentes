---
name: secure-existing-project
version: 2.0.0
description: Aplicar arquitectura de seguridad privada/publica a proyecto Python existente
triggers: [/secure, /security-audit, /harden]
author: agent
role: shared
stage: support
writes_memory: false
quality_gate: false
tags: [core, system]
---

# secure-existing-project

Migra un proyecto Python existente a la arquitectura de seguridad privada/publica.

## Overview

Convierte un proyecto con credenciales expuestas a uno seguro con separación privada/publica.

## Workflow

### Paso 1: Auditar Proyecto Actual

Buscar secrets hardcodeados:
```bash
grep -r "API_KEY\|SECRET\|PASSWORD\|TOKEN" src/ --include="*.py"
find . -name "*.env" -o -name "config.json" -o -name "credentials*"
```

**Lista de hallazgos:**
- Archivos con credenciales en repo
- Variables hardcodeadas
- Configuraciones sensibles

### Paso 2: Crear Estructura Segura

```
proyecto/
├── privada/              # ⛔ NUNCA commitear
│   ├── .env
│   ├── config.json
│   └── credentials.json
│
└── publica/
    └── repo/             # ✅ Workspace agentes
        ├── src/
        ├── tests/
        └── .env.example
```

### Paso 3: Migrar Secrets (👤 Usuario)

Instruir al usuario:
```markdown
## Acción Requerida (Usuario)

Mover archivos sensibles a `privada/`:

1. Copiar `.env` → `privada/.env`
2. Copiar `config.json` → `privada/config.json`
3. Eliminar originales de `publica/repo/`
4. Crear versiones `.example` sin valores reales
```

### Paso 4: Implementar Configuración

Crear `src/config.py`:
```python
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
PRIVATE_DIR = ROOT_DIR.parent.parent / "privada"

DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
LOGS_DIR = ROOT_DIR / "logs"
```

Crear `src/settings.py` con búsqueda en cascada (ver reference).

### Paso 5: Actualizar .gitignore

```gitignore
# Seguridad
privada/
.env
.env.*
config.json
credentials.json
*.key
*.pem

# Python
__pycache__/
.venv/
```

### Paso 6: Verificar

```bash
# Verificar que privada/ no está trackeada
git status | grep privada  # No debe mostrar nada

# Verificar que .env.example existe
ls -la publica/repo/.env.example
```

## Output

- Estructura `privada/` creada
- `config.py` y `settings.py` implementados
- `.gitignore` actualizado
- Archivos `.example` creados
- Instrucciones al usuario para migración

## References

- `references/security-checklist.md` - Checklist de auditoría
- `references/cascade-config-pattern.md` - Código de config/settings

## Constraints

- **NO** mover archivos de `privada/` automáticamente (usuario lo hace)
- **NO** dejar secrets en código después de la migración
- **SIEMPRE** crear archivos `.example`
