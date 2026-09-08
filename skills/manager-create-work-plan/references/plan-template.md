# Template de Plan de Trabajo

```markdown
# Plan de Trabajo: [Título]

## Metadata
- **ID:** WOT-[YYYY]-[NNN][x]
- **Estado:** 🟡 IN_PLANNING
- **deliverable_type:** code | documentation | research | analysis | mixed
- **Creado:** [YYYY-MM-DD]
- **Prioridad:** HIGH/MEDIUM/LOW
- **Asignado a:** Builder

## 🎯 Objetivo
[Descripción clara en 2-3 líneas]

## 📋 Contexto
[Situación actual, problema a resolver]

## Configuración Privada Requerida
- [ ] `.env` - Variables de entorno
- [ ] `config.json` - Configuración personal

## Plan de Implementación

### Tipos de Tareas
| Icono | Tipo | Ejecutor |
|-------|------|----------|
| 🤖 | TAREA AGENTE | Builder |
| 👤 | TAREA USUARIO | Usuario |

### Fase 0: Preparación (👤/🤖)

#### 0.1: 👤 Crear configuración privada
- **Tipo:** 👤 TAREA USUARIO
- **Archivo:** `privada/.env`
- **Acción:** Crear
- **Descripción:** Crear archivo `.env` con variables
- **Riesgo:** 🟢 Bajo
- **Criterio de Aceptación:** Archivo existe con variables requeridas

### Fase 1: [Nombre]

#### 1.1: 🤖 [Nombre tarea]
- **Tipo:** 🤖 TAREA AGENTE
- **Archivo:** `src/archivo.py`
- **Acción:** Crear/Modificar
- **Descripción:** [Qué hacer]
- **Riesgo:** 🟢/🟡/🔴
- **Criterio de Aceptación:** [Medible y verificable]

## Trade-offs Considerados
| Opción | Pros | Contras | Decisión |
|--------|------|---------|----------|
| [A] | [+] | [-] | [Aceptada/Descartada] |

## Decision Arquitectonica
[Qué pieza del sistema cambia y por qué ESA y no otra. Si el cambio conecta con
un mecanismo que ya existe, nómbralo con su ruta. Respuesta válida y frecuente:
"ninguna: es un cambio local de N líneas que no altera ninguna interfaz" — y por
qué eso es cierto. Prefiere una frase honesta a un párrafo ritual.]

## Non-goals
[Qué queda FUERA de este ticket, y por qué. Lo que otro ticket ya cubre, lo que
exige una decisión que aún no está tomada, o la superficie vecina que sería
tentador tocar de paso. Si de verdad no hay ninguno, dilo así: "ninguno: la
superficie es un único fichero y no hay vecina adyacente".]

## 🚨 Guía de Riesgos
| Nivel | Significado | Acción del Builder |
|-------|-------------|-------------------|
| 🟢 Bajo | Rutinaria | Intentar 3 veces antes de escalar |
| 🟡 Medio | Requiere atención | Intentar 2 veces, escalar si dudas |
| 🔴 Alto | Crítica | Escalar al primer fallo |

## 🧪 Criterios de Aceptación Global
- [ ] [Criterio medible 1]
- [ ] [Criterio medible 2]
- [ ] Todos los tests pasan
- [ ] Linter sin errores
```

## Notas sobre deliverable_type

El campo `deliverable_type` declara la naturaleza del entregable principal del WP.
V1 acepta: `code` (código fuente), `documentation` (docs/markdown), `research` (análisis/reportes), `analysis` (estudios técnicos), `mixed` (combinación).
Valor recomendado por defecto: `code`. WP-089 introducirá dispatch automático de gates según este campo.
