# Formato de execution_log.md

## Estructura

```markdown
# Registro de EjecuciÃ³n

## Metadata
- **Plan ID:** WP-XXX
- **Ejecutado por:** Builder
- **Inicio:** YYYY-MM-DD HH:MM
- **Estado:** ðŸ”µ IN_PROGRESS / ðŸŸ  BLOCKED / ðŸŸ£ READY_FOR_REVIEW

## ðŸ“¦ SesiÃ³n N: YYYY-MM-DD HH:MM

### ðŸ”„ Inicio de Fase X
- **Fase:** [Nombre]
- **Tareas pendientes:** N

### âœ… [FECHA] - [Tarea Completada]
- **Archivo:** `src/archivo.py`
- **Cambios:** [DescripciÃ³n]

**CÃ³digo:**
```python
def nueva_funcion(param: str) -> dict:
    """DescripciÃ³n."""
    return {"result": param}
```

**Tests:**
```bash
$ python scripts/run_pytest_safe.py -- tests/ -v
[archivo].py::test_nueva PASSED
```

### âš ï¸ Issue Encontrado
**ID:** ISS-001
**DescripciÃ³n:** [Problema]
**Intentos:** 1. [Intento] 2. [Intento]
**Tiempo:** ~XX min
**DecisiÃ³n:** [Escalar/Continuar]

## ðŸ“Š Resumen de Fase

**Tareas:** N/M completadas
**Tests:** X/Y pasando
**PrÃ³xima sesiÃ³n:** [Tareas pendientes]
```

## Estados

| Estado | Emoji | Significado |
|--------|-------|-------------|
| IN_PROGRESS | ðŸ”µ | Implementando |
| BLOCKED | ðŸŸ  | Esperando Manager |
| READY_FOR_REVIEW | ðŸŸ£ | Listo para revisiÃ³n |
