---
name: scaffold-python-project
version: 1.0.0
description: Crear estructura completa de proyecto Python nuevo con seguridad integrada
triggers: [/scaffold, /new-project, /scaffold-python]
author: agent
tags: [core, system]
---

# scaffold-python-project

Crea un proyecto Python nuevo desde cero con estructura segura y moderna.

## Overview

Genera estructura completa: directorios, archivos de configuraciÃ³n, y setup inicial.

## Workflow

### Paso 1: Crear Estructura de Directorios

```bash
mkdir -p proyecto/{privada,publica/repo/{src,tests,data,output,logs,tools}}
```

Estructura resultante:
```
proyecto/
â”œâ”€â”€ privada/              # Credenciales (fuera del workspace)
â””â”€â”€ publica/repo/         # Workspace del agente
    â”œâ”€â”€ src/              # CÃ³digo fuente
    â”œâ”€â”€ tests/            # Tests pytest
    â”œâ”€â”€ data/             # Datos de entrada
    â”œâ”€â”€ output/           # Resultados
    â”œâ”€â”€ logs/             # Logs de ejecuciÃ³n
    â””â”€â”€ tools/            # Scripts auxiliares
```

### Paso 2: Inicializar con uv

```bash
cd publica/repo
uv init
```

Configurar `pyproject.toml` (ver reference).

### Paso 3: Crear Archivos Base

**src/config.py:**
```python
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
PRIVATE_DIR = ROOT_DIR.parent.parent / "privada"

DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
LOGS_DIR = ROOT_DIR / "logs"

for d in [OUTPUT_DIR, LOGS_DIR]:
    d.mkdir(exist_ok=True)
```

**src/settings.py:** (ver secure-existing-project)

**src/main.py:**
```python
from loguru import logger
from src.config import LOGS_DIR
from src.settings import Settings

logger.add(LOGS_DIR / "app.log", rotation="10 MB")

def main() -> None:
    logger.info("Iniciando...")
    settings = Settings()
    # TODO: Implementar

if __name__ == "__main__":
    main()
```

**src/__init__.py:**
```python
from src.config import DATA_DIR, OUTPUT_DIR
from src.settings import Settings

__all__ = ["DATA_DIR", "OUTPUT_DIR", "Settings"]
```

### Paso 4: Crear .gitignore

(ver reference)

### Paso 5: Crear Archivos .example

**.env.example:**
```env
# API
API_KEY=tu_api_key_aqui
API_SECRET=tu_secret_aqui

# Database
DATABASE_URL=postgresql://user:pass@localhost/db
```

**data/config.json.example:**
```json
{
  "setting": "valor_de_ejemplo"
}
```

### Paso 6: Instalar Dependencias

```bash
uv add loguru python-dotenv
uv add --dev pytest ruff mypy
```

### Paso 7: Pre-commit Hook (Opcional)

Crear `.git/hooks/pre-commit`:
```bash
#!/bin/sh
python tools/pre_commit_check.py
```

## Output

Proyecto listo para:
- Desarrollo seguro (privada/publica)
- GestiÃ³n con uv
- Testing con pytest
- Linting con ruff
- Logging con loguru

## References

- `references/pyproject-template.md` - Template de pyproject.toml
- `references/gitignore-template.md` - .gitignore completo

## Constraints

- **SIEMPRE** usar `uv` (no pip/requirements.txt)
- **SIEMPRE** crear archivos `.example`
- **SIEMPRE** usar `pathlib` en config.py
