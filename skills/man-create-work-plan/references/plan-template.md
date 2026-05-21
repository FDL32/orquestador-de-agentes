# Template de Plan de Trabajo

```markdown
# Plan de Trabajo: [TÃ­tulo]

## Metadata
- **ID:** WP-[YYYY]-[NNN]
- **Estado:** 🟡 IN_PLANNING
- **deliverable_type:** code | documentation | research | analysis | mixed
- **Creado:** [YYYY-MM-DD]
- **Prioridad:** HIGH/MEDIUM/LOW
- **Asignado a:** Builder

## ðŸŽ¯ Objetivo
[DescripciÃ³n clara en 2-3 lÃ­neas]

## ðŸ“‹ Contexto
[SituaciÃ³n actual, problema a resolver]

## ðŸ” ConfiguraciÃ³n Privada Requerida
- [ ] `.env` - Variables de entorno
- [ ] `config.json` - ConfiguraciÃ³n personal

## ðŸ—ï¸ Plan de ImplementaciÃ³n

### Tipos de Tareas
| Icono | Tipo | Ejecutor |
|-------|------|----------|
| ðŸ¤– | TAREA AGENTE | Builder |
| ðŸ‘¤ | TAREA USUARIO | Usuario |

### Fase 0: PreparaciÃ³n (ðŸ‘¤/ðŸ¤–)

#### 0.1: ðŸ‘¤ Crear configuraciÃ³n privada
- **Tipo:** ðŸ‘¤ TAREA USUARIO
- **Archivo:** `privada/.env`
- **AcciÃ³n:** Crear
- **DescripciÃ³n:** Crear archivo `.env` con variables
- **Riesgo:** ðŸŸ¢ Bajo
- **Criterio de AceptaciÃ³n:** Archivo existe con variables requeridas

### Fase 1: [Nombre]

#### 1.1: ðŸ¤– [Nombre tarea]
- **Tipo:** ðŸ¤– TAREA AGENTE
- **Archivo:** `src/archivo.py`
- **AcciÃ³n:** Crear/Modificar
- **DescripciÃ³n:** [QuÃ© hacer]
- **Riesgo:** ðŸŸ¢/ðŸŸ¡/ðŸ”´
- **Criterio de AceptaciÃ³n:** [Medible y verificable]

## âš–ï¸ Trade-offs Considerados
| OpciÃ³n | Pros | Contras | DecisiÃ³n |
|--------|------|---------|----------|
| [A] | [+] | [-] | [âœ…/âŒ] |

## ðŸš¨ GuÃ­a de Riesgos
| Nivel | Significado | AcciÃ³n del Builder |
|-------|-------------|-------------------|
| ðŸŸ¢ Bajo | Rutinaria | Intentar 3 veces antes de escalar |
| ðŸŸ¡ Medio | Requiere atenciÃ³n | Intentar 2 veces, escalar si dudas |
| ðŸ”´ Alto | CrÃ­tica | Escalar al primer fallo |

## ðŸ§ª Criterios de AceptaciÃ³n Global
- [ ] [Criterio medible 1]
- [ ] [Criterio medible 2]
- [ ] Todos los tests pasan
- [ ] Linter sin errores
```

## Notas sobre deliverable_type

El campo `deliverable_type` declara la naturaleza del entregable principal del WP.
V1 acepta: `code` (código fuente), `documentation` (docs/markdown), `research` (análisis/reportes), `analysis` (estudios técnicos), `mixed` (combinación).
Valor recomendado por defecto: `code`. WP-089 introducirá dispatch automático de gates según este campo.
