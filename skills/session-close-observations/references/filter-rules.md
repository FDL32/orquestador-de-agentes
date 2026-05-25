# Reglas de Filtrado - Session Close Observations

## Tres Reglas de Curacion

Toda observacion candidata debe pasar estas tres reglas:

### 1. Es un hecho

La observacion debe ser:
- **Objetiva**: Verificable por terceros
- **Concreta**: Describe algo que ocurrio o se decidio
- **Atemporal**: No depende del estado emocional del autor

**Ejemplos que PASAN**:
- "Session-close observations skill creada con schema de 6 campos"
- "Filtros de curacion: hecho, persistencia, utilidad repetida"
- "WP-2026-132 conecta skill en project-finalize paso 9c-9d"

**Ejemplos que FALLAN**:
- "Me parece que la memoria deberia ser mas eficiente" (opinion)
- "Tool edit called" (trace de herramienta)
- "Sesion productiva" (subjetivo)

### 2. Sobrevive a otra sesion

La observacion debe ser util dentro de 1+ semanas:

**Preguntas de validacion**:
- ¿Esta observacion ayudara en el proximo WP?
- ¿Documenta algo que de otra forma se olvidaria?
- ¿Es referencia para decisiones futuras?

**Ejemplos que PASAN**:
- Decisiones arquitectonicas
- Convenciones de codigo establecidas
- Patrones de implementacion reutilizables
- Bugs fijos con causa raiz documentada

**Ejemplos que FALLAN**:
- "Reunion a las 3pm hoy" (temporal)
- "Archivo X modificado" (sin contexto)
- "Error temporal en build" (si ya se resolvio sin aprendizaje)

### 3. Evita trabajo repetido

La observacion no debe duplicar conocimiento existente:

**Check de duplicados**:
- Comparar signal contra observaciones previas
- Detectar equivalencia semantica, no solo exacta
- Ventana de 24h para duplicados temporales

**Ejemplos que PASAN**:
- Nueva convencion no documentada antes
- Decision que cambia un patron anterior
- Hecho tecnico sin registro previo

**Ejemplos que FALLAN**:
- Duplicado exacto de observacion existente
- Mismo hecho con redaccion ligeramente distinta
- Re-iteracion de decision ya consolidada

## Filtros Automaticos

### Por longitud
- **Regla**: signal < 30 caracteres → descartar
- **Razon**: Entradas muy cortas suelen ser ruido

### Por patron
- **Regla**: signal empieza con "Tool " y termina con " called" → descartar
- **Razon**: Son traces de herramientas, no observaciones

### Por categoria
- **Regla**: category no esta en [`convention`, `decision`, `fact`, `pattern`] → descartar
- **Razon**: Categoria invalida indica schema incorrecto

### Por campos requeridos
- **Regla**: Falta timestamp, signal, category, source_ticket, topic o source → descartar
- **Razon**: Schema incompleto rompe trazabilidad

## Criterios de Promocion

Una observacion es promovida a `observations.jsonl` cuando:

1. ✅ Schema valido (6 campos, tipos correctos)
2. ✅ Pasa los 3 filtros de curacion
3. ✅ No es duplicado de observacion existente
4. ✅ Signal >= 30 caracteres
5. ✅ Categoria valida

## Implementacion

Ver `scripts/session_close_observations.py` para la implementacion de filtros.
