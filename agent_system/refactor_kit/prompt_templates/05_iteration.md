# FASE 5: IteraciÃ³n

**Objetivo:** Corregir errores sin reescribir.

## Requisito: Hay Errores en FASE 4

Solo se llega a FASE 5 si validaciÃ³n fallÃ³.

## Tarea

Si algÃºn test falla o validaciÃ³n es incompleta:

### 1. Causa RaÃ­z

Responde:
- Â¿CuÃ¡l es el sÃ­ntoma? (test X falla, error Y aparece)
- Â¿CuÃ¡l es la CAUSA? (lÃ­nea Z introdujo bug)
  - NO confundir sÃ­ntoma con causa
  - Investigar a fondo
- Â¿Es culpa del refactor o pre-existente?
  - Rollback un cambio a la vez
  - AÃ­sla la lÃ­nea problemÃ¡tica

### 2. Fix MÃ­nimo

PropÃ³n fix:
- Una lÃ­nea si es posible
- MÃ¡ximo 3-5 lÃ­neas
- NUNCA reescribir funciones completas

**Si fix es > 5 lÃ­neas:**
â†’ STOP
â†’ El plan fue deficiente
â†’ Rechazar y documentar aprendizaje

### 3. Aplicar Fix y Reintentar

- Aplicar fix mÃ­nimo
- Rerun FASE 4 (tests)
- Si PASS â†’ refactor completado
- Si FAIL â†’ analizar causa raÃ­z nuevamente

**MÃ¡ximo 2 intentos de fix.**
Si 3er intento necesario â†’ RECHAZAR refactor.

## Debes Entregar

```
[Causa RaÃ­z]

SÃ­ntoma:
- Test/validaciÃ³n que falla: [descripciÃ³n]

Causa Real:
- LÃ­nea problemÃ¡tica: [nÃºmero de lÃ­nea]
- ExplicaciÃ³n: [por quÃ© falla]
- Culpa del refactor: SÃ­/No

[Fix MÃ­nimo]

Cambio aplicado:
- [1-3 lÃ­neas de cÃ³digo]

JustificaciÃ³n:
- [por quÃ© esto arregla el problema]

[RevalidaciÃ³n]

Tests nuevamente: PASS/FAIL
- Si FAIL: causa raÃ­z [nÃºmero de intento: 1/2]
- Si PASS: refactor completado

Resultado Final:
- COMPLETADO / BLOQUEADO
```

## Ejemplo

**SÃ­ntoma:** Test `test_user_validation()` falla con AssertionError

**Causa:** Refactor cambiÃ³ return type de `validate_user()` de bool â†’ dict, pero test espera bool

**Fix MÃ­nimo:**
```python
# LÃ­nea 45: mantener backward compatibility
return {
    "valid": result,
    "errors": errors
}["valid"]  # Retorna bool como antes
```

**RevalidaciÃ³n:** Tests pasan âœ“

---

## Reglas CrÃ­ticas

âŒ **NO:**
- Reescribir cÃ³digo (si necesitas, plan fue malo)
- Ignorar la causa raÃ­z
- Intentar mÃ¡s de 2 fixes

âœ… **SÃ:**
- Investigar causa raÃ­z
- Fix mÃ­nimo (1-3 lÃ­neas)
- Reintentar validaciÃ³n
- Documentar aprendizaje si se rechaza
