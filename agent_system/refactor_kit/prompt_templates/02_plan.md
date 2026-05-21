# FASE 2: Plan

**Objetivo:** Definir el cambio mÃ­nimo Ãºtil.

## Tarea

BasÃ¡ndote en el anÃ¡lisis previo, propone UN refactor pequeÃ±o.

NO ESCRIBAS CÃ“DIGO AÃšN. Solo plan detallado.

## Debes Entregar

### 1. Â¿CuÃ¡l es el cambio propuesto?
DescripciÃ³n clara y concisa (mÃ¡ximo 3 frases).

Ejemplo: "Extraer lÃ³gica de validaciÃ³n de usuario_valido() a funciÃ³n aparte para mejorar reusabilidad y testabilidad."

### 2. Â¿Por quÃ© mejora el cÃ³digo?
JustificaciÃ³n especÃ­fica:
- Reduce complejidad ciclomÃ¡tica de 8 â†’ 4?
- Mejora legibilidad de funciones grandes?
- Elimina duplicidad?
- Mejora testabilidad?

### 3. Â¿CuÃ¡les son los INVARIANTES que se deben mantener?
Repetir invariantes de FASE 1.
Confirmar que el plan los respeta.

### 4. Â¿QuÃ© NO se va a tocar?
Ser explÃ­cito sobre lÃ­mites:
- "NO modificaremos la API public de la clase"
- "NO cambiaremos structure de datos"
- "NO agregaremos dependencias"

### 5. Â¿CuÃ¡les son los riesgos?
Documentar riesgos identificados:
- Probabilidad (BAJO, MEDIO, ALTO)
- Impacto
- MitigaciÃ³n

### 6. Â¿CÃ³mo validaremos que no se rompiÃ³ nada?
Estrategia de validaciÃ³n:
- Â¿QuÃ© tests existentes deben pasar?
- Â¿QuÃ© casos de uso probar manualmente?
- Â¿QuÃ© comportamiento observable verificar?

## Alternativas Descartadas

Listar 2-3 alternativas consideradas y por quÃ© se rechazaron:

```
- [Alternativa 1] âŒ RazÃ³n (demasiado grande? toca invariantes?)
- [Alternativa 2] âŒ RazÃ³n
- [Alternativa 3] âŒ RazÃ³n
```

## Formato de Respuesta

```
[Plan de Refactor]

Cambio Propuesto:
- [descripciÃ³n clara, max 3 frases]

JustificaciÃ³n:
- [por quÃ© mejora]

Invariantes a Mantener:
- [repetir los crÃ­ticos]

QuÃ© NO se Toca:
- [lÃ­mites explÃ­citos]

Riesgos Identificados:
- Riesgo X: BAJO/MEDIO/ALTO
- Riesgo Y: BAJO/MEDIO/ALTO

Estrategia de ValidaciÃ³n:
- Tests a ejecutar: [lista]
- Casos manuales: [lista]
- Comportamiento a verificar: [lista]

Alternativas Descartadas:
- [alternativa 1] âŒ [razÃ³n]
- [alternativa 2] âŒ [razÃ³n]
```

## Reglas CrÃ­ticas

âŒ **NO:**
- Proponer cambios grandes (>50 lÃ­neas de cÃ³digo)
- Cambiar comportamiento observable
- Mezclar mÃºltiples refactorings en uno
- Ser vago ("mejorar cÃ³digo")

âœ… **SÃ:**
- Proponer UN cambio mÃ­nimo
- Ser especÃ­fico y justificado
- Documentar riesgos
- Respetar invariantes
