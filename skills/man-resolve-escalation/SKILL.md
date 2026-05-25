---
name: resolve-escalation
version: 2.0.0
description: Skill para que el Manager resuelva bloqueos y escalaciones del Builder con decisiones documentadas
triggers: [/escalate, escalation, /resolve]
author: agent
role: manager
stage: review
writes_memory: false
quality_gate: false
tags: [core, system]
---

# man-resolve-escalation

Skill para resolver bloqueos tÃ©cnicos o decisiones arquitectÃ³nicas escaladas por el Builder.

## Overview

Cuando el Builder estÃ¡ `ðŸŸ  BLOCKED`, el Manager usa esta skill para:
1. Leer y entender la escalaciÃ³n
2. Clasificar tipo de bloqueo
3. Analizar opciones con trade-offs
4. Tomar decisiÃ³n documentada
5. Comunicar resoluciÃ³n

## Workflow

### Paso 0: Verificar Turno
```bash
python .agent/agent_controller.py
```
Debe indicar `ROL ACTIVO: MANAGER` y acciÃ³n `RESOLVE_BLOCK`.

### Paso 1: Leer Contexto Completo

Leer en orden:
1. `review_queue.md` - EscalaciÃ³n del Builder
2. `execution_log.md` - Contexto del problema
3. `work_plan.md` - Plan original y criterios
4. `references/escalation-levels.md` - GuÃ­a de niveles

### Paso 2: Clasificar Tipo de Bloqueo

| Tipo | DescripciÃ³n | Ejemplo |
|------|-------------|---------|
| **TÃ©cnico** | Error tÃ©cnico o bug | "No puedo hacer que funcione la conexiÃ³n" |
| **DiseÃ±o** | DecisiÃ³n arquitectÃ³nica | "Â¿Usar clase o funciones?" |
| **Dependencia** | Bloqueo externo | "Esperando API del proveedor" |
| **Permisos** | Acceso requerido | "Necesito credenciales de BD" |
| **Requisito** | AmbigÃ¼edad en requisito | "No estÃ¡ claro quÃ© debe hacer" |

### Paso 3: Analizar Opciones

Para cada opciÃ³n presentada por el Builder (o identificadas):

```markdown
| OpciÃ³n | Pros | Contras | Riesgo |
|--------|------|---------|--------|
| A | [+] | [-] | ðŸŸ¢/ðŸŸ¡/ðŸ”´ |
| B | [+] | [-] | ðŸŸ¢/ðŸŸ¡/ðŸ”´ |
```

**Criterios de decisiÃ³n:**
- Simplicidad (KISS)
- Mantenibilidad a largo plazo
- Tiempo de implementaciÃ³n
- Riesgo de introducir bugs

### Paso 4: Tomar DecisiÃ³n

**DecisiÃ³n debe ser:**
- Clara y especÃ­fica
- Accionable (el Builder sabe quÃ© hacer)
- Documentada con razonamiento

**NO dejar ambigÃ¼edades.**

### Paso 5: Documentar en review_queue.md

```markdown
### ðŸš¨ ESC-[ID]: [TÃ­tulo Corto] - RESUELTO
- **Plan ID:** WP-XXX
- **Tipo:** ESCALATION
- **Urgencia:** ðŸ”´/ðŸŸ¡/ðŸŸ¢ [Alta/Media/Baja]
- **Estado:** âœ… RESOLVED
- **Fecha resoluciÃ³n:** [YYYY-MM-DD HH:MM]

**Problema:**
[Resumen del bloqueo]

**Opciones analizadas:**
1. [OpciÃ³n A] - Pros/Contras
2. [OpciÃ³n B] - Pros/Contras

**DecisiÃ³n:** [OpciÃ³n elegida]

**Razonamiento:**
[Por quÃ© se eligiÃ³ esta opciÃ³n]

**PrÃ³ximo paso para Builder:**
[InstrucciÃ³n especÃ­fica y clara]
```

### Paso 6: Notificar al Builder

```markdown
## ðŸ“¨ [FECHA] EscalaciÃ³n Resuelta: Manager â†’ Builder
**Plan:** WP-XXX
**EscalaciÃ³n:** ESC-[ID]
**DecisiÃ³n:** [Resumen en 1 lÃ­nea]
**AcciÃ³n requerida:** Ver review_queue.md y continuar implementaciÃ³n
**Estado:** â³ PENDING
```

### Paso 7: Actualizar Estados

En `execution_log.md`:
- Cambiar estado de `ðŸŸ  BLOCKED` a `ðŸ”µ IN_PROGRESS`
- AÃ±adir nota de resoluciÃ³n

## Criterios para Escalar (GuÃ­a para Builder)

El Builder debe escalar cuando:
1. **3+ intentos fallidos** para tarea ðŸŸ¢
2. **2+ intentos fallidos** para tarea ðŸŸ¡
3. **1 intento fallido** para tarea ðŸ”´
4. **30+ minutos bloqueado** sin progreso
5. **DecisiÃ³n de arquitectura** requerida
6. **Bug en librerÃ­a externa**
7. **Incertidumbre** entre opciones equivalentes

## Anti-Patrones (NO hacer)

- **NO** dejar al Builder adivinar
- **NO** dar respuestas vagas ("intenta otra cosa")
- **NO** cambiar requisitos sin documentar
- **NO** ignorar la escalaciÃ³n

## Output Format

### ResoluciÃ³n Completa
1. Entrada en `review_queue.md` con decisiÃ³n clara
2. NotificaciÃ³n en `notifications.md`
3. ActualizaciÃ³n de `execution_log.md`

## References

- `references/escalation-levels.md` - GuÃ­a de niveles de urgencia
- `.agent/protocols/escalation_protocol.md` - Protocolo completo
- `.agent/rules/manager/` - Restricciones del rol

## Constraints

- **SIEMPRE** dar decisiÃ³n especÃ­fica, no opciones mÃºltiples
- **SIEMPRE** explicar razonamiento
- **NO** cambiar scope del plan sin documentar
- **NO** asignar nuevas tareas sin actualizar work_plan.md
