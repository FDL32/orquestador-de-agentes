---
name: code-audit
version: 2.0.0
description: Auditoría sistemática de código Python detectando dead code, technical debt, y archivos inactivos usando vulture, deadcode, ruff y git log
triggers: [/code-audit, code-quality, /deadcode]
author: agent
role: shared
stage: review
writes_memory: false
quality_gate: false
tags: [core, system]
---

# code-audit

Skill para ejecutar auditoría completa del codebase identificando código muerto, deuda técnica y patrones problemáticos.

## Overview

La auditoría realiza análisis estático multi-herramienta combinando:
- **vulture**: Detección de símbolos no utilizados (confidence >= 80)
- **deadcode**: Análisis de flujo para código realmente muerto
- **ruff**: Deuda técnica (complejidad ciclomática C90, código antiguo ERA, simplificaciones SIM)
- **git log**: Antigüedad de archivos (commit count para categorizar abandono)

## Workflow

### Paso 0: Verificar Pre-condiciones
- Proyecto contiene archivos Python (`*.py`)
- Herramientas instaladas: `vulture>=2.0`, `deadcode>=2.0`, `ruff`, `git` (opcional)
- Repositorio limpio (cambios guardados)

### Paso 1: Ejecutar Health Check

```bash
python scripts/audit_codebase.py --status
```

**Salida esperada:**
```
Deadcode found X unused items
Ruff executed successfully
Health check passed: all tools executed successfully
```

**Si falla:** Verificar que las herramientas están instaladas con `uv sync`.

### Paso 2: Ejecutar Auditoría Completa

```bash
python scripts/audit_codebase.py --report
```

Este comando ejecuta los 4 analizadores:
1. **Vulture** (subprocess CLI) — símbolos no referenciados
2. **Deadcode** (importado como librería) — análisis de uso real
3. **Ruff** (subprocess CLI) — complejidad y deuda técnica
4. **Git Log** (subprocess) — antigüedad de cambios

**Salida esperada:**
```
Running full audit...
Vulture executed successfully (output not captured due to Windows encoding issues)
Error running deadcode: ...  (tolerable si hay librerías externas sin AST)
Ruff executed successfully
Audit complete.
Report generated: .session/audit_report.md
```

Warnings/Errors parciales son tolerables. El reporte se genera incluso con fallos parciales.

### Paso 3: Inspeccionar Reporte

```bash
cat .session/audit_report.md | head -50
```

Estructura de tabla:

| Archivo | Líneas | Herramienta | Tipo | Línea | Símbolo | Usos | Commits | Acción |
|---------|--------|-------------|------|-------|---------|------|---------|--------|
| `src/foo.py` | 145 | deadcode | function | 23 | `unused_helper` | 0 | 3 | LEGACY |
| `src/bar.py` | 89 | ruff | lint | 12 | C901 | 1 | 15 | SMELL |

**Columnas:**
- **Acción**: Categorización automática (DEAD, LEGACY, ABANDONED, SMELL)
- **Commits**: Cantidad de commits que tocaron ese archivo
- **Usos**: Número de referencias encontradas (0 = unused)

### Paso 4: Categorizar Hallazgos

**DEAD** (commits=0):
- Código nunca commiteado o muy reciente
- Acción: Eliminar inmediatamente

**ABANDONED** (0 < commits < 5):
- Código antiguo, pocos cambios, sin uso detectado
- Acción: Revisar + eliminar después de análisis manual

**LEGACY** (commits >= 5):
- Código histórico con cambios múltiples pero sin uso actual
- Acción: Refactorizar o encapsular (podría ser API pública)

**SMELL** (ruff findings):
- Deuda técnica: complejidad alta, código antiguo, oportunidades de simplificación
- Acción: Mejorar gradualmente en siguiente refactor

### Paso 5: Filtrar por Acción

```bash
# Ver solo código DEAD
grep "| DEAD$" .session/audit_report.md

# Ver solo problemas de ruff (SMELL)
grep "| ruff " .session/audit_report.md

# Ver solo archivos no commiteados (ABANDONED nuevos)
grep "| ABANDONED$" .session/audit_report.md | head -20
```

### Paso 6: Tomar Decisiones

Para cada hallazgo significativo:

1. **DEAD** → Eliminar del código
2. **ABANDONED con 0 commits** → Eliminar
3. **ABANDONED con 1-4 commits** → Validar manualmente antes de eliminar
4. **LEGACY** → Revisar con el equipo (podría ser API interna)
5. **SMELL** → Agendar refactor gradual

Documentar decisiones en `execution_log.md`:

```markdown
### Code Audit Results — [FECHA]

**Hallazgos procesados:**
- DEAD items: X (todos eliminados)
- ABANDONED items: Y (revisados, Z eliminados)
- LEGACY items: W (refactor agendado / API interna confirmada)
- SMELL items: V (deuda técnica acumulada)

**Acciones tomadas:**
- [ ] Eliminados archivos DEAD
- [ ] Revisados ABANDONED manualmente
- [ ] Confirmado status de LEGACY
- [ ] Ruff findings documentados en PROJECT.md
```

## Output Format

### Reporte Markdown (.session/audit_report.md)

Tabla ordenada por archivo + línea:

```markdown
# Audit Report

| Archivo | Líneas | Herramienta | Tipo | Línea | Símbolo | Usos | Commits | Acción |
|---------|--------|-------------|------|-------|---------|------|---------|--------|
...
```

**Filas totales:** Típicamente 100-2000 dependiendo del codebase.

### Categorización

```
DEAD      = sin uso + sin commits (eliminar)
ABANDONED = sin uso + 0-5 commits (revisar + eliminar)
LEGACY    = sin uso + 5+ commits (revisar con equipo)
SMELL     = ruff findings (deuda técnica)
```

## References

- `references/audit-report-template.md` — Plantilla para decisiones por hallazgo
- `references/audit-tools-guide.md` — Umbrales y configuración de cada herramienta
- `scripts/audit_codebase.py` — Script orquestador (descripción de herramientas y parámetros)

## Constraints

### Herramientas y Umbrales

| Herramienta | Parámetro | Valor | Razón |
|-------------|-----------|-------|-------|
| vulture | `--min-confidence` | 80 | Evitar false positives en parámetros opcionales |
| deadcode | `--exclude` | `venv,.venv,__pycache__,.git,agent_system,.agent` | Ignorar venv, cache y frameworks |
| ruff | extends | `C90, ERA, SIM` | Complejidad, código antiguo, simplificaciones |
| git | log | `--oneline --follow` | Rastrear antigüedad del código |

### Exclusiones

```python
exclude = 'venv,.venv,__pycache__,.git,agent_system,.agent'
```

Se ignoran deliberadamente:
- **venv/.venv** — Dependencias aisladas
- **__pycache__** — Compilados Python
- **.git** — Historial externo
- **agent_system/.agent** — Frameworks de referencia

### Limitaciones Conocidas

- **Windows encoding**: Vulture output no se captura en Windows (usar log explícito de vulture)
- **Librerías externas**: Deadcode puede no analizar código de terceros (tolerable)
- **No-git repos**: Audit continúa con warning si no es repo git
- **Tabla grande**: Si hay >2000 filas, considerar filtrar en post-procesamiento

### Reglas de Uso

- **SIEMPRE** ejecutar `--status` primero para validar tooling
- **NUNCA** eliminar código LEGACY sin revisión manual (podría ser API pública)
- **SIEMPRE** documentar decisiones en `execution_log.md`
- **NO** ejecutar audit en paralelo (subprocess contention)

---

**Versión:** 1.0.0  
**Autor:** agent-system  
**Última actualización:** 2026-04-28
