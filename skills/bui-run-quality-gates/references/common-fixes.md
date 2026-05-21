# Fixes Comunes

## F401: Import no usado

**SoluciÃ³n:** Eliminar o usar `# noqa: F401`

## F841: Variable no usada

**SoluciÃ³n:** Eliminar o renombrar a `_`
```python
_ = calculate()  # Ignorar valor
```

## E501: LÃ­nea muy larga

**SoluciÃ³n:** Dividir string o parÃ¡metros
```python
long_line = (
    "texto largo "
    "mÃ¡s texto"
)

def funcion(
    param1: str,
    param2: int
) -> None:
    pass
```

## I001: Imports desordenados

**SoluciÃ³n:**
```bash
ruff check . --exclude .agent --fix
```

Orden: `__future__` â†’ stdlib â†’ third-party â†’ local

## E722: Bare except

**SoluciÃ³n:**
```python
try:
    process()
except ValueError as e:  # âœ… EspecÃ­fico
    logger.error(e)
```

## Comando Ãºtil

```bash
ruff check . --exclude .agent --fix
```
