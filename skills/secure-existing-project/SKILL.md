---
name: secure-existing-project
version: 1.0.0
description: Aplicar arquitectura de seguridad privada/publica a proyecto Python existente
triggers: [/secure, /security-audit, /harden]
author: agent
tags: [core, system]
---

# secure-existing-project

Migra un proyecto Python existente a la arquitectura de seguridad privada/publica.

## Overview

Convierte un proyecto con credenciales expuestas a uno seguro con separaciÃ³n privada/publica.

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
â”œâ”€â”€ privada/              # â›” NUNCA commitear
â”‚   â”œâ”€â”€ .env
â”‚   â”œâ”€â”€ config.json
â”‚   â””â”€â”€ credentials.json
â”‚
â””â”€â”€ publica/
    â””â”€â”€ repo/             # âœ… Workspace agentes
        â”œâ”€â”€ src/
        â”œâ”€â”€ tests/
        â””â”€â”€ .env.example
```

### Paso 3: Migrar Secrets (ðŸ‘¤ Usuario)

Instruir al usuario:
```markdown
## AcciÃ³n Requerida (Usuario)

Mover archivos sensibles a `privada/`:

1. Copiar `.env` â†’ `privada/.env`
2. Copiar `config.json` â†’ `privada/config.json`
3. Eliminar originales de `publica/repo/`
4. Crear versiones `.example` sin valores reales
```

### Paso 4: Implementar ConfiguraciÃ³n

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

Crear `src/settings.py` con bÃºsqueda en cascada (ver reference).

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
# Verificar que privada/ no estÃ¡ trackeada
git status | grep privada  # No debe mostrar nada

# Verificar que .env.example existe
ls -la publica/repo/.env.example
```

## Output

- Estructura `privada/` creada
- `config.py` y `settings.py` implementados
- `.gitignore` actualizado
- Archivos `.example` creados
- Instrucciones al usuario para migraciÃ³n

## References

- `references/security-checklist.md` - Checklist de auditorÃ­a
- `references/cascade-config-pattern.md` - CÃ³digo de config/settings

## Constraints

- **NO** mover archivos de `privada/` automÃ¡ticamente (usuario lo hace)
- **NO** dejar secrets en cÃ³digo despuÃ©s de la migraciÃ³n
- **SIEMPRE** crear archivos `.example`
