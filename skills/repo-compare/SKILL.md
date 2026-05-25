---
name: repo-compare
version: 2.0.0
description: Comparar proyecto local con repositorio GitHub para detectar funcionalidades de alto valor
triggers: [/repo-compare, /compare, /gh-compare]
author: agent
role: shared
stage: support
writes_memory: false
quality_gate: false
tags: [core, system]
---

# repo-compare

Skill para comparar el proyecto local (`z_scripts/`) con cualquier repositorio público de GitHub y detectar funcionalidades, utilidades o patrones de alto valor que se puedan incorporar.

Usa `.agent/runtime/audit/AUDIT.md` como **Fase 0 autoritativa** del contexto local, eliminando hallucinación sobre "qué ya existe". Lee el repo remoto vía GitHub MCP (`mcp__github__get_file_contents`, `mcp__github__search_code`).

## When to activate

- Cuando recibes una URL de GitHub (`https://github.com/<owner>/<repo>`) y quieres detectar funcionalidades portables.
- Cuando el Manager o usuario pregunta "¿qué podemos aprender de este repo?".
- Cuando quieres evaluar si un repo merece inversión de tiempo antes de explorarlo en profundidad.

## When NOT to activate

- Si no hay AUDIT.md fresco (< 24h) y no se puede regenerar.
- Si el repo target es privado (MCP GitHub solo lee públicos).
- Si el usuario solo quiere una búsqueda puntual de código (usar `mcp__github__search_code` directo).

## Workflow (5 pasos)

### Paso 1: Preflight AUDIT
- Verificar `.agent/runtime/audit/AUDIT.md`:
  - Si falta o `generated_at > 24h`: intentar ejecutar `python scripts/local_audit.py --quick` automáticamente.
  - Si el entorno no permite shell: pedir al usuario que lo ejecute.
- Cargar `AUDIT.md` como contexto Fase 0.

### Paso 2: Validar input
- Requiere URL GitHub `https://github.com/<owner>/<repo>`.
- Si no se proporciona: pedir al usuario.

### Paso 3: Filtro rápido (Fase 1 del prompt)
- Score 0-5 sobre 5 dimensiones: README claro, tests/CI presentes, señales mantenimiento, encaje técnico, claridad estructural.
- Si total < 3 → marcar `[BAJO VALOR]`, abortar con explicación breve.

### Paso 4: Exploración (Fase 2)
- Usar `mcp__github__get_file_contents` y `mcp__github__search_code`.
- **Cap operativo**: max 8-12 archivos × 500 líneas por archivo.
- Si archivo > 500 líneas: leer primeras 100 + grep dirigido por patrones específicos.
- Orden: README → estructura raíz → `skills/`, `hooks/`, `tools/`, `agents/` → `prompts/`, `.rules`, `.agent/` → `tests/`, CLI → `.github/workflows/`.

### Paso 5: Output (Fase 3+4)
- 3-5 oportunidades con plantilla canónica (ver `references/output-format.md`).
- Cada oportunidad incluye:
  - Campo `¿Ya existe en z_scripts?` citando ruta + sección de AUDIT.md (no `Yes/No` a secas).
  - Campo `📎 Fuente verificada: [AUDIT.md sección X | GitHub: owner/repo/path:L# | Ambos]`.
- Matriz final (Impacto / Esfuerzo / Encaje / Decisión).
- Sección "Qué Ignorar" + "Acción Inmediata".
- **Bloque candidato CREDITS** al final del reporte (ver `references/output-format.md` sección "Credits Block Template"): tabla con una fila Markdown lista para pegar en `CREDITS.md` cuando el humano decida adoptar la idea. **El agente NO escribe en CREDITS.md directamente** — solo emite el bloque sugerido.
- Persistir output a `.agent/runtime/compare/<owner>-<repo>-<ref>-<YYYY-MM-DD>.md` (default `ref=HEAD`, idealmente capturar SHA real vía `mcp__github__list_commits` paginación 1).

## Constraints

- **Skill PURA**: no crear ningún `.py` bajo `skills/repo-compare/`. El agente invocador usa sus propias herramientas (MCP GitHub).
- **No inventar**: si no puedes verificar algo, escribe `[NO VERIFICADO]` o `[NO ENCONTRADO]`.
- **AUDIT.md es Fase 0**: si AUDIT.md indica que algo ya existe, marcar `[YA EXISTE]` automáticamente.
- **Cap operativo medible**: máximo 12 archivos remotos leídos. Contar invocaciones de `mcp__github__get_file_contents`.
- **Output gitignored**: `.agent/runtime/compare/` está en `.gitignore`. No commitear comparaciones generadas.

## References

- `PROMPT_TEMPLATE.md` — Prompt completo con 5 fases + cap operativo + invariantes anti-fabricación.
- `references/output-format.md` — Plantilla de oportunidad + matriz + secciones finales.
- `references/filter-criteria.md` — Scoring 0-5 y umbral 3 (BAJO VALOR).
- `skills/refactor-manager/SKILL.md` — Patrón arquitectónico replicado (skill pura + prompt template + references/).

## Troubleshooting

**P: ¿Qué si MCP GitHub no está disponible o falla (rate limit, auth)?**
R: Documentar en `execution_log.md` la razón. Dejar el smoke como tarea humana pendiente. NO marcar el WP como READY_FOR_REVIEW sin smoke ejecutado o documentado como bloqueado.

**P: ¿Qué si el repo target tiene archivos muy grandes (> 500 líneas)?**
R: Aplicar cap operativo: leer primeras 100 líneas + `mcp__github__search_code` con patrones dirigidos. Documentar en el output qué se truncó.

**P: ¿Qué si AUDIT.md está stale (> 24h)?**
R: Ejecutar `python scripts/local_audit.py --quick` antes de continuar. Si no se puede, pedir al usuario que lo ejecute.

## Example usage

```bash
# Usuario activa la skill
/repo-compare https://github.com/Aider-AI/aider

# El agente ejecuta:
# FASE 1: Verifica AUDIT.md (fresco? si no, regenerar)
# FASE 2: Filtro rápido (score 0-5, si < 3 abortar)
# FASE 3: Exploración (≤ 12 archivos × ≤ 500 líneas)
# FASE 4: Oportunidades (3-5 entradas con plantilla)
# FASE 5: Persistir output a .agent/runtime/compare/Aider-AI-aider-<sha>-2026-05-18.md
```
