# FASE 4: ValidaciÃ³n

**Objetivo:** Demostrar que no se rompiÃ³ nada.

## Tareas de ValidaciÃ³n

### 1. ValidaciÃ³n SintÃ¡ctica
```bash
python -m py_compile [archivo]
python -c "import [mÃ³dulo]"
```

### 2. Linting
```bash
ruff check [archivo]
```

Debe pasar sin errores.

### 3. Tests Existentes
```bash
# Ejecutar tests que usan este cÃ³digo
python -m pytest tests/ -v
```

- Â¿Todos los tests pasan?
- Si falla uno â†’ FASE 5

### 4. RegresiÃ³n Manual

**Casos a verificar:**
- Happy path: el caso de uso normal, Â¿funciona igual?
- Edge cases: casos lÃ­mite, Â¿se comportan igual?
- Error handling: si hay errores, Â¿se reportan igual?
- Comportamiento observable: salidas, side effects, Â¿idÃ©nticos?

### 5. RegresiÃ³n de Comportamiento

Verificar:
- Return values: Â¿iguales?
- Exceptions: Â¿mismas condiciones?
- Side effects: Â¿idÃ©nticos? (files, logs, state)
- Performance: Â¿comparable o mejor?

## Debes Entregar

```
[ValidaciÃ³n Completa]

Syntax Check: PASS/FAIL
- Errores: [lista si hay]

Imports Check: PASS/FAIL
- Errores: [lista si hay]

Ruff Linting: PASS/FAIL
- Issues: [lista si hay]

Tests Existentes: PASS/FAIL (X/Y)
- Tests que fallan: [lista si hay]
- Coverage: [X%]

RegresiÃ³n Manual:
- Happy path: PASS/FAIL [evidencia]
- Edge cases: PASS/FAIL [evidencia]
- Error handling: PASS/FAIL [evidencia]
- Observable behavior: PASS/FAIL [evidencia]

ConclusiÃ³n:
- SAFE TO MERGE / NEEDS FIX / BLOCKED
- Riesgos abiertos: [si hay]
```

## Si Hay Fallos

- Documenta exactamente quÃ© falla
- Causa probable: [hipÃ³tesis]
- RecomendaciÃ³n: ir a FASE 5 (iteraciÃ³n)

## Reglas CrÃ­ticas

âŒ **NO:**
- Ignorar resultados de tests
- Asumir que "deberÃ­a funcionar"
- Saltarse un caso de validaciÃ³n

âœ… **SÃ:**
- Validar exhaustivamente
- Documentar hallazgos
- Ser honesto sobre fallos
