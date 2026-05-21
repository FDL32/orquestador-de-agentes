# Reglas de CÃ³digo Python

## Pathlib (SIEMPRE)

**âŒ NUNCA:** `os.path.join()` â†’ **âœ… SIEMPRE:** `Path() / "file"`

```python
from pathlib import Path
path = Path("folder") / "file.txt"
content = Path("file.txt").read_text(encoding="utf-8")
Path("folder").mkdir(parents=True, exist_ok=True)
```

## Type Hints (OBLIGATORIO)

Todas las funciones deben tener type hints:

```python
def load_config(path: Path) -> dict[str, any]:
    """Carga configuraciÃ³n desde archivo."""
    ...

def save_data(data: list[dict], output_path: Path) -> None:
    """Guarda datos en archivo."""
    ...
```

**Tipos comunes:** `str`, `int`, `list[T]`, `dict[K,V]`, `Path`, `any`

## Docstrings

Toda funciÃ³n pÃºblica debe tener docstring:

```python
def validate_email(email: str) -> bool:
    """Valida formato de email.

    Args:
        email: DirecciÃ³n a validar

    Returns:
        True si vÃ¡lido, False si no
    """
    ...
```

## Manejo de Errores

**âŒ NUNCA bare except:**
```python
try:
    process()
except:  # âŒ
    pass
```

**âœ… SIEMPRE especÃ­fico:**
```python
from loguru import logger

try:
    process()
except ValueError as e:
    logger.error(f"Error: {e}")
    raise
except FileNotFoundError:
    logger.warning("Archivo no encontrado")
    return default_value
```

## Logging (NO print)

```python
from loguru import logger
logger.info("Procesando...")
logger.debug(f"Valor: {value}")
logger.warning("Archivo no existe")
logger.error(f"Error: {e}")
```

## Constantes (NO nÃºmeros mÃ¡gicos)

```python
TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

if timeout > TIMEOUT_SECONDS:
    pass
```

## ConfiguraciÃ³n sectorial (NO hardcoding)

Si un valor depende del sector, NO lo escribas en Python:
âŒ `if sector == "religioso": lista = ["casulla", "alba"]`
âœ… `lista = sector_cfg.raw.get("interlinks", {}).get("patterns", {})`

Los YAMLs de sector son el Ãºnico lugar donde viven los datos sectoriales.

## NormalizaciÃ³n de datos â€” punto Ãºnico

Si un dato puede llegar en varios formatos (segÃºn la fuente), normaliza en el punto de SALIDA (el mÃ©todo que lo produce), no en cada punto de ENTRADA (los mÃ©todos que lo consumen):
âŒ Cada consumer hace `data.get("wrapper", {}).get("field") or data.get("field")`
âœ… El productor hace `data = unwrap(data)` antes del return; los consumers hacen `data.get("field")`
