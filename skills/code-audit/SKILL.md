---
name: code-audit
version: 2.0.0
description: AuditorÃ­a sistemÃ¡tica de cÃ³digo Python detectando dead code, technical debt, y archivos inactivos usando vulture, deadcode, ruff y git log
triggers: [/code-audit, code-quality, /deadcode]
author: agent
role: shared
stage: review
writes_memory: false
quality_gate: false
tags: [core, system]
---

# code-audit

Skill para ejecutar auditorÃ­a completa del codebase identificando cÃ³digo muerto, deuda tÃ©cnica y patrones problemÃ¡ticos.

## Overview

La auditorÃ­a realiza anÃ¡lisis estÃ¡tico multi-herramienta combinando:
- **vulture**: DetecciÃ³n de sÃ­mbolos no utilizados (confidence >= 80)
- **deadcode**: AnÃ¡lisis de flujo para cÃ³digo realmente muerto
- **ruff**: Deuda tÃ©cnica (complejidad ciclomÃ¡tica C90, cÃ³digo antiguo ERA, simplificaciones SIM)
- **git log**: AntigÃ¼edad de archivos (commit count para categorizar abandono)

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

**Si falla:** Verificar que las herramientas estÃ¡n instaladas con `uv sync`.

### Paso 2: Ejecutar AuditorÃ­a Completa

```bash
python scripts/audit_codebase.py --report
```

Este comando ejecuta los 4 analizadores:
1. **Vulture** (subprocess CLI) â€” sÃ­mbolos no referenciados
2. **Deadcode** (importado como librerÃ­a) â€” anÃ¡lisis de uso real
3. **Ruff** (subprocess CLI) â€” complejidad y deuda tÃ©cnica
4. **Git Log** (subprocess) â€” antigÃ¼edad de cambios

**Salida esperada:**
```
Running full audit...
Vulture executed successfully (output not captured due to Windows encoding issues)
Error running deadcode: ...  (tolerable si hay librerÃ­as externas sin AST)
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

| Archivo | LÃ­neas | Herramienta | Tipo | LÃ­nea | SÃ­mbolo | Usos | Commits | AcciÃ³n |
|---------|--------|-------------|------|-------|---------|------|---------|--------|
| `src/foo.py` | 145 | deadcode | function | 23 | `unused_helper` | 0 | 3 | LEGACY |
| `src/bar.py` | 89 | ruff | lint | 12 | C901 | 1 | 15 | SMELL |

**Columnas:**
- **AcciÃ³n**: CategorizaciÃ³n automÃ¡tica (DEAD, LEGACY, ABANDONED, SMELL)
- **Commits**: Cantidad de commits que tocaron ese archivo
- **Usos**: NÃºmero de referencias encontradas (0 = unused)

### Paso 4: Categorizar Hallazgos

**DEAD** (commits=0):
- CÃ³digo nunca commiteado o muy reciente
- AcciÃ³n: Eliminar inmediatamente

**ABANDONED** (0 < commits < 5):
- CÃ³digo antiguo, pocos cambios, sin uso detectado
- AcciÃ³n: Revisar + eliminar despuÃ©s de anÃ¡lisis manual

**LEGACY** (commits >= 5):
- CÃ³digo histÃ³rico con cambios mÃºltiples pero sin uso actual
- AcciÃ³n: Refactorizar o encapsular (podrÃ­a ser API pÃºblica)

**SMELL** (ruff findings):
- Deuda tÃ©cnica: complejidad alta, cÃ³digo antiguo, oportunidades de simplificaciÃ³n
- AcciÃ³n: Mejorar gradualmente en siguiente refactor

### Paso 5: Filtrar por AcciÃ³n

```bash
# Ver solo cÃ³digo DEAD
grep "| DEAD$" .session/audit_report.md

# Ver solo problemas de ruff (SMELL)
grep "| ruff " .session/audit_report.md

# Ver solo archivos no commiteados (ABANDONED nuevos)
grep "| ABANDONED$" .session/audit_report.md | head -20
```

### Paso 6: Tomar Decisiones

Para cada hallazgo significativo:

1. **DEAD** â†’ Eliminar del cÃ³digo
2. **ABANDONED con 0 commits** â†’ Eliminar
3. **ABANDONED con 1-4 commits** â†’ Validar manualmente antes de eliminar
4. **LEGACY** â†’ Revisar con el equipo (podrÃ­a ser API interna)
5. **SMELL** â†’ Agendar refactor gradual

Documentar decisiones en `execution_log.md`:

```markdown
### Code Audit Results â€” [FECHA]

**Hallazgos procesados:**
- DEAD items: X (todos eliminados)
- ABANDONED items: Y (revisados, Z eliminados)
- LEGACY items: W (refactor agendado / API interna confirmada)
- SMELL items: V (deuda tÃ©cnica acumulada)

**Acciones tomadas:**
- [ ] Eliminados archivos DEAD
- [ ] Revisados ABANDONED manualmente
- [ ] Confirmado status de LEGACY
- [ ] Ruff findings documentados en PROJECT.md
```

## Output Format

### Reporte Markdown (.session/audit_report.md)

Tabla ordenada por archivo + lÃ­nea:

```markdown
# Audit Report

| Archivo | LÃ­neas | Herramienta | Tipo | LÃ­nea | SÃ­mbolo | Usos | Commits | AcciÃ³n |
|---------|--------|-------------|------|-------|---------|------|---------|--------|
...
```

**Filas totales:** TÃ­picamente 100-2000 dependiendo del codebase.

### CategorizaciÃ³n

```
DEAD      = sin uso + sin commits (eliminar)
ABANDONED = sin uso + 0-5 commits (revisar + eliminar)
LEGACY    = sin uso + 5+ commits (revisar con equipo)
SMELL     = ruff findings (deuda tÃ©cnica)
```

## References

- `references/audit-report-template.md` â€” Plantilla para decisiones por hallazgo
- `references/audit-tools-guide.md` â€” Umbrales y configuraciÃ³n de cada herramienta
- `scripts/audit_codebase.py` â€” Script orquestador (descripciÃ³n de herramientas y parÃ¡metros)

## Constraints

### Herramientas y Umbrales

| Herramienta | ParÃ¡metro | Valor | RazÃ³n |
|-------------|-----------|-------|-------|
| vulture | `--min-confidence` | 80 | Evitar false positives en parÃ¡metros opcionales |
| deadcode | `--exclude` | `venv,.venv,__pycache__,.git,agent_system,.agent` | Ignorar venv, cache y frameworks |
| ruff | extends | `C90, ERA, SIM` | Complejidad, cÃ³digo antiguo, simplificaciones |
| git | log | `--oneline --follow` | Rastrear antigÃ¼edad del cÃ³digo |

### Exclusiones

```python
exclude = 'venv,.venv,__pycache__,.git,agent_system,.agent'
```

Se ignoran deliberadamente:
- **venv/.venv** â€” Dependencias aisladas
- **__pycache__** â€” Compilados Python
- **.git** â€” Historial externo
- **agent_system/.agent** â€” Frameworks de referencia

### Limitaciones Conocidas

- **Windows encoding**: Vulture output no se captura en Windows (usar log explÃ­cito de vulture)
- **LibrerÃ­as externas**: Deadcode puede no analizar cÃ³digo de terceros (tolerable)
- **No-git repos**: Audit continÃºa con warning si no es repo git
- **Tabla grande**: Si hay >2000 filas, considerar filtrar en post-procesamiento

### Reglas de Uso

- **SIEMPRE** ejecutar `--status` primero para validar tooling
- **NUNCA** eliminar cÃ³digo LEGACY sin revisiÃ³n manual (podrÃ­a ser API pÃºblica)
- **SIEMPRE** documentar decisiones en `execution_log.md`
- **NO** ejecutar audit en paralelo (subprocess contention)

---

**VersiÃ³n:** 1.0.0  
**Autor:** agent-system  
**Ãšltima actualizaciÃ³n:** 2026-04-28
