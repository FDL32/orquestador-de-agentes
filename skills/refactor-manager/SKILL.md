---
name: refactor-manager
version: 2.0.0
description: Protocolo de reingenierÃ­a segura con 5 fases (anÃ¡lisis â†’ plan â†’ refactor â†’ validaciÃ³n â†’ iteraciÃ³n)
triggers: [/refactor, refactor-manager, refactor]
author: agent
role: shared
stage: review
writes_memory: false
quality_gate: false
tags: [core, system]
---

# refactor-manager

Skill para que Manager dirija refactorizaciÃ³n segura de cÃ³digo Python, reduciendo riesgo y manteniendo invariantes.

Basado en protocolo de Principal Engineer: separaciÃ³n estricta entre anÃ¡lisis, plan y ejecuciÃ³n.

## Overview

El Manager usa esta skill para refactorizar cÃ³digo de forma controlada:

1. **Fase 1 (AnÃ¡lisis):** Goose lee cÃ³digo, identifica problemas, documenta hallazgos (sin modificar)
2. **Fase 2 (Plan):** Manager revisa hallazgos y aprueba cambio mÃ­nimo propuesto
3. **Fase 3 (Refactor):** Goose ejecuta SOLO cambios aprobados
4. **Fase 4 (ValidaciÃ³n):** Tests + ruff + regresiÃ³n verifican cero impacto
5. **Fase 5 (IteraciÃ³n):** Si fallos, Goose propone fix mÃ­nimo (no reescribir)

**Invariante:** Nunca cambiar comportamiento observable sin aprobaciÃ³n explÃ­cita.

## Workflow

### Prerequisitos
- Archivo target identificado (path absoluto o relativo)
- Manager disponible para revisar plan (fase 2)
- Proyecto con tests + ruff configurado

### Paso 1: Verificar Turno
```bash
python .agent/agent_controller.py
```
Si rol es BUILDER, informar al usuario: "Este skill es para Manager".

### Paso 2: Cargar Contexto
Leer en orden:
1. `.agent/rules/manager/refactoring-protocol.md` - reglas y protocolo
2. Archivo target - entender cÃ³digo actual
3. Casos de uso existentes - identificar invariantes

### Paso 3: Ejecutar FASE 1 â€” AnÃ¡lisis

**Objetivo:** Entender antes de tocar.

Tarea para Goose:
```
Analiza este archivo: [path]

NO MODIFIQUES NADA. Solo documenta:
1. Â¿QuÃ© hace el cÃ³digo?
2. Â¿CuÃ¡les son las responsabilidades?
3. Detecta:
   - Acoplamiento innecesario
   - Complejidad sin justificaciÃ³n
   - Duplicidad de cÃ³digo
   - Code smells (nombres confusos, funciones grandes, etc)
4. Â¿CuÃ¡les son los invariantes? (comportamiento que no puede cambiar)
5. Â¿Hay incertidumbres? MÃ¡rcalas como HIPÃ“TESIS

Salida:
[AnÃ¡lisis]
- Â¿QuÃ© hace?
- Responsabilidades
- Problemas detectados
- Invariantes
- HipÃ³tesis/incertidumbres
```

Goose entrega reporte de anÃ¡lisis (NO cÃ³digo modificado).

**REGLA CRÃTICA:** Si hay dudas en fase 1 â†’ DETENERSE y preguntar.

### Paso 4: Manager Revisa AnÃ¡lisis

Manager lee reporte y decide:
- **CONTINUAR:** Acepta anÃ¡lisis, propone refactor mÃ­nimo
- **PROFUNDIZAR:** Pide anÃ¡lisis mÃ¡s detallado de ciertos aspectos
- **RECHAZAR:** El alcance es demasiado amplio o riesgoso

Si continuar, pasar a FASE 2.

### Paso 5: Ejecutar FASE 2 â€” Plan

**Objetivo:** Definir el cambio mÃ­nimo Ãºtil.

Tarea para Goose:
```
BasÃ¡ndote en el anÃ¡lisis previo, propone UN refactor pequeÃ±o:

1. Â¿CuÃ¡l es el cambio propuesto?
2. Â¿Por quÃ© mejora el cÃ³digo?
3. Â¿QuÃ© NO se va a tocar?
4. Â¿CuÃ¡les son los riesgos?
5. Â¿CÃ³mo validaremos que no se rompiÃ³ nada?

Alternativas descartadas (y por quÃ©):
- [alternativa 1] âŒ RazÃ³n
- [alternativa 2] âŒ RazÃ³n

Salida:
[Plan]
- Cambio propuesto
- JustificaciÃ³n
- QuÃ© no se toca
- Riesgos
- Estrategia de validaciÃ³n
```

Goose entrega propuesta de plan (sin cÃ³digo).

### Paso 6: Manager Aprueba Plan

Manager lee plan y decide:
- **APROBADO:** Procede a FASE 3
- **AJUSTES:** Pide cambios al plan (scope, riesgos, etc)
- **RECHAZADO:** Plan no cumple criterios

Si no aprobado, iterar Fase 2 o abandonar.

### Paso 7: Ejecutar FASE 3 â€” Refactor

**Objetivo:** Aplicar SOLO el cambio definido.

Tarea para Goose:
```
Implementa el plan aprobado:

1. Lee el cÃ³digo original
2. Aplica SOLO los cambios del plan (sin extras)
3. MantÃ©n invariantes intactos
4. CÃ³digo debe ser:
   - Completo (no fragmentos rotos)
   - Consistente con el proyecto
   - Legible

Salida: CÃ³digo modificado listo para validaciÃ³n
```

Goose entrega cÃ³digo refactorizado.

**REGLA:** Si tentaciÃ³n de hacer "un cambio mÃ¡s" â†’ DETENER y documentar para prÃ³xima iteraciÃ³n.

### Paso 8: Ejecutar FASE 4 â€” ValidaciÃ³n

**Objetivo:** Demostrar que no se rompiÃ³ nada.

Tarea para Goose + sistemas automÃ¡ticos:
```
Valida que el refactor no rompe nada:

1. Syntax check: python -m py_compile [archivo]
2. Imports: python -c "import [mÃ³dulo]"
3. Linting: ruff check [archivo]
4. Tests:
   - Â¿QuÃ© tests existentes usan este cÃ³digo?
   - Â¿Todos los tests pasan?
   - Â¿Coverage se mantiene?
5. RegresiÃ³n manual:
   - Casos felices (happy path)
   - Edge cases
   - Error handling
6. Comportamiento observable:
   - Â¿El cÃ³digo hace exactamente lo mismo que antes (desde afuera)?

Salida:
[ValidaciÃ³n]
- Casos a testear
- Tests sugeridos (si hay gaps)
- Resultado: PASS / FAIL / PARCIAL
- Riesgos abiertos (si hay)
```

Si FAIL â†’ pasar a FASE 5. Si PASS â†’ refactor completado exitosamente.

### Paso 9: Ejecutar FASE 5 â€” IteraciÃ³n (si hay errores)

**Objetivo:** Corregir sin reescribir.

Si tests fallan:
```
1. Analiza causa raÃ­z:
   - Â¿QuÃ© test falla exactamente?
   - Â¿Por quÃ©? (sÃ­ntomas vs causa real)
   - Â¿Es el refactor o era pre-existente?

2. Propone fix MÃNIMO:
   - Una lÃ­nea si posible
   - MÃ¡ximo 3-5 lÃ­neas
   - NUNCA reescribir funciones completas

3. Aplica fix y reintentar validaciÃ³n

4. Si sigue fallando despuÃ©s de 2 intentos:
   â†’ Reportar y abandonar el refactor
   â†’ Documentar bloqueador
```

**REGLA:** Si necesitas reescribir > 20% del cÃ³digo del plan â†’ DETENER. El plan fue deficiente.

### Paso 10: Manager Aprueba o Rechaza

Manager revisa:
1. CÃ³digo refactorizado (lectura directa, no confÃ­es en logs)
2. Reporte de validaciÃ³n
3. Hallazgos de cada fase

DecisiÃ³n final:
- **APROBADO:** Refactor listo para merge/commit
- **RECHAZADO CON FEEDBACK:** Documento quÃ© cambiar, reintentar
- **CANCELADO:** Aprendizajes documentados para futuro

## Invariantes NO Negociables

âŒ **PROHIBIDO:**
1. Cambiar comportamiento observable sin autorizaciÃ³n explÃ­cita
2. Modificar APIs pÃºblicas o contratos externos
3. Introducir dependencias nuevas sin justificaciÃ³n
4. Mezclar refactor con rediseÃ±o o migraciÃ³n
5. Reescribir en lugar de refactor mÃ­nimo
6. Ignorar resultados de tests
7. Asumir comportamiento (siempre validar)

âœ… **OBLIGATORIO:**
1. AnÃ¡lisis antes de cualquier cambio
2. Plan aprobado antes de ejecuciÃ³n
3. SeparaciÃ³n estricta: anÃ¡lisis â‰  ejecuciÃ³n
4. ValidaciÃ³n exhaustiva despuÃ©s
5. Documentar decisiones y bloqueadores
6. Si hay duda â†’ preguntar, no asumir

## Roles y Responsabilidades

### Manager (TÃº)
- AprobaciÃ³n de Fase 1 (anÃ¡lisis comprensible?)
- AprobaciÃ³n de Fase 2 (plan aceptable?)
- ValidaciÃ³n final (cÃ³digo respetuoso con invariantes?)
- DecisiÃ³n final: aprobado/rechazado/ajustes

### Goose (IA)
- Fase 1: AnÃ¡lisis (no escribir cÃ³digo)
- Fase 2: Propuesta de plan (no escribir cÃ³digo)
- Fase 3: Refactor controlado
- Fase 4: ValidaciÃ³n automatizada
- Fase 5: Fix mÃ­nimo iterativo

### Sistema (Tests + Ruff)
- ValidaciÃ³n sintÃ¡ctica
- Linting
- RegresiÃ³n automatizada
- Behavioural tests

## Ejemplo: Refactorizar run_pytest_safe.py

```bash
# Manager inicia
python scripts/orquestador.py --skill /refactor \
  --query "Refactoriza scripts/run_pytest_safe.py

Target: scripts/run_pytest_safe.py
Scope: Mejorar error handling (no cambiar comportamiento)
Constraint: Debe seguir 5 fases del protocolo
Manager rol: yo revisarÃ© cada fase
"

# Goose ejecuta:
# FASE 1: Analiza run_pytest_safe.py
#   â†’ Identifica: exception handling inconsistente, nombres confusos, etc
#   â†’ Documenta invariantes: exit codes (0=ok, 1=fail, 2=error)
#   â†’ Propone cambios: mejorar try/except, clarificar nombres
#
# FASE 2: Manager aprueba plan
#   â†’ Goose propone: agregar type hints, mejorar docstrings
#   â†’ Manager: "Aprobado, pero SOLO error handling, no type hints aÃºn"
#   â†’ Plan ajustado: mÃ­nimo cambio
#
# FASE 3: Refactor
#   â†’ Goose aplica cambios aprobados
#
# FASE 4: ValidaciÃ³n
#   â†’ Tests pasan? âœ“
#   â†’ Ruff clean? âœ“
#   â†’ Comportamiento igual? âœ“
#
# FASE 5: IteraciÃ³n
#   â†’ Refactor exitoso, fin
```

## Troubleshooting

**P: Â¿QuÃ© si Goose propone un cambio demasiado grande en FASE 2?**
R: Rechazar y pedir subdivisiÃ³n. El plan debe ser mÃ­nimo.

**P: Â¿QuÃ© si tests fallan en FASE 4?**
R: Fase 5: analizar causa raÃ­z, fix mÃ­nimo. Si 2+ intentos fallan, abandonar.

**P: Â¿Puedo hacer dos refactors en uno?**
R: No. Un refactor = una responsabilidad. Si necesitas dos, crear dos tickets.

**P: Â¿Debo seguir TODAS las 5 fases?**
R: SÃ­. Cada fase previene errores diferentes. Saltarse una es riesgoso.

## Prompts asociados

Esta skill define el **protocolo** (5 fases). Los prompts operativos viven en archivos hermanos:

- `PROMPT_TEMPLATE.md` â€” Meta-prompt largo: rol, invariantes, clasificacion A/B/C/D, preflight, criterios de aceptacion, plan de rollback. Pasalo como contexto base al agente ejecutor.
- `EXECUTION_PROMPT.md` â€” Prompts cortos del dia a dia: analisis + plan, aplicar sub-fase, foco en zona concreta, auditoria "no hace falta refactor", tests de caracterizacion.
- `../../prompts/refactor_bootstrap.md` â€” Paste-ready para arrancar una sesion nueva de refactor con cualquier backend.

## Referencias

- `.agent/rules/manager/refactoring-protocol.md` â€” Protocolo completo
- `CLAUDE.md` secciÃ³n 3l â€” IntegraciÃ³n TICKET #010
- `WP-2026-010` â€” Plan de implementaciÃ³n
