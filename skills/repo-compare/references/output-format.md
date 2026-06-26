# Output Format - Repo Compare

Plantilla canónica para reportar oportunidades detectadas en la comparación de repositorios.

---

## Plantilla de Oportunidad

Cada oportunidad detectada debe seguir esta estructura:

```markdown
### OPORTUNIDAD #N: [Nombre descriptivo]

**Ubicación en repo target:** `path/to/file.py:L#-L#` (o `path/to/dir/` si es patrón)
**Líneas clave:**
```python
# Copiar 3-10 líneas más relevantes
# (suficiente para entender el patrón, no el archivo completo)
```
**Fuente:** `mcp__github__get_file_contents` + verificación cruzada

**¿Qué hace?**
[Descripción en 2-3 frases. Sé concreto: qué input, qué output, qué efecto]

**¿Qué valor aporta a el proyecto local?**
[Justificación concreta: qué problema resuelve, qué gap cubre, qué mejora]

**¿Ya existe en el proyecto local?**
- **Estado:** [Sí / No / Parcial / [YA EXISTE]]
- **Cita AUDIT.md:** [Sección X, ruta Y]: "[texto o paráfrasis de lo que dice AUDIT.md]".
  - Ejemplo: "AUDIT.md sección 4.2 menciona `scripts/local_audit.py` que ya recopila estado operativo".
  - Ejemplo: "AUDIT.md sección 3.1 no menciona nada similar en `skills/`".

**Compatibilidad con charter**
- **Estado:** [Compatible / Choca / [NO VERIFICADO] / Intent Audit: no verificable]
- **Cita `repo_charter.md`:** [Sección X]: "[texto o paráfrasis de la restricción o criterio relevante]".
  - Si no existe `repo_charter.md`, escribir explícitamente `Intent Audit: no verificable`.

**📎 Fuente verificada:** [AUDIT.md sección X | GitHub: owner/repo/path:L# | Ambos]
- `AUDIT.md sección X`: La evidencia viene del snapshot local.
- `GitHub: owner/repo/path:L#`: La evidencia viene del repo remoto.
- `Ambos`: Verificado en ambas fuentes (ej. patrón similar pero con diferencias).

**Nota de topología (pre-ticket):**
- [ ] Parece cambio solo de `repo_destino`
- [ ] Parece cambio solo de `repo_motor`
- [ ] Parece cambio en `ambos`
- [ ] Requiere verificar topología antes de planificar

**Dependencias nuevas:**
- [ ] Ninguna
- [ ] `lib1`, `lib2` (justificar si pesadas: > 10MB, nativas, etc.)
- [ ] Requiere `uv add <lib>`

**Encaje técnico:**
- **Python:** [3.10+ / 3.11+ / Requiere upgrade]
- **Arquitectura:** [Alto/Medio/Bajo] — [razón: coincide con `skills/`, `bus/`, etc.]
- **Deps:** [Ligeras/Medias/Pesadas] — [lista o justificación]

**Plan de incorporación:**
1. [Paso 1: leer/entender el código original]
2. [Paso 2: adaptar a estructura el proyecto local (rutas, naming, convenciones)]
3. [Paso 3: escribir tests de validación (si aplican)]
4. [Paso 4: documentar en AGENTS.md / CHANGELOG.md]
5. [Paso 5: ejecutar quality gates (ruff, pytest, validate)]

**Dificultad estimada:** [S (≤1h) / M (1-4h) / L (>4h)]
- **Razón:** [líneas a adaptar, complejidad, deps, tests necesarios]

**Prioridad:** [Alta / Media / Baja]
- **Razón:** [impacto vs esfuerzo: "alto impacto, bajo esfuerzo" = Alta]

**Decisión:** [INCORPORAR AHORA / INCORPORAR DESPUÉS / IGNORAR]
- **Razón:** [justificación basada en impacto, esfuerzo, encaje]
```

---

## Matriz Final

Tabla resumen de todas las oportunidades:

```markdown
| Oportunidad | Impacto (1-10) | Esfuerzo (h) | Encaje (%) | Decisión |
|-------------|----------------|--------------|------------|----------|
| #1: [Nombre corto] | X | Y | Z% | [AHORA/DESPUÉS/IGNORAR] |
| #2: [Nombre corto] | X | Y | Z% | [AHORA/DESPUÉS/IGNORAR] |
| #3: [Nombre corto] | X | Y | Z% | [AHORA/DESPUÉS/IGNORAR] |
| #4: [Nombre corto] | X | Y | Z% | [AHORA/DESPUÉS/IGNORAR] |
| #5: [Nombre corto] | X | Y | Z% | [AHORA/DESPUÉS/IGNORAR] |
```

**Columnas:**
- **Impacto (1-10):** ¿Cuánto valor aporta a el proyecto local? (10 = transforma el flujo, 1 = cosmético)
- **Esfuerzo (h):** Horas estimadas de incorporación (incluye tests + docs).
- **Encaje (%):** ¿Qué tan bien coincide con la arquitectura actual? (100% = drop-in, 0% = requiere rediseño)
- **Decisión:**
  - `AHORA`: Incorporar en el próximo WP.
  - `DESPUÉS`: Vale la pena, pero hay prioridades mayores.
  - `IGNORAR`: No aporta valor suficiente o ya existe mejor en local.

---

## Sección: Qué Ignorar

Lista explícita de funcionalidades del repo target que **NO** se van a incorporar:

```markdown
### Qué Ignorar

- **[Funcionalidad X]**: [razón: ya existe mejor en local / deps pesadas / fuera de scope / acoplamiento alto]
  - **Ubicación:** `path/to/file.py`
  - **Por qué ignorar:** [justificación en 1-2 frases]

- **[Funcionalidad Y]**: [razón: no portable / requiere infra no disponible / duplica esfuerzo]
  - **Ubicación:** `path/to/dir/`
  - **Por qué ignorar:** [justificación]
```

**Objetivo:** Evitar que el lector asuma que "todo lo que no se menciona es incorporable". Explicitar qué se descarta y por qué.

---

## Sección: Acción Inmediata

Próximo paso concreto para el equipo:

```markdown
### Acción Inmediata

**Próximo paso:** [Descripción de la tarea o WP para incorporar la oportunidad #1]

**Acción sugerida:**
```text
# Si la oportunidad es simple/local y NO toca arquitectura/topología/seguridad:
# usar el skill vigente `refactor-manager` (trigger `/refactor`) en el backend actual
/refactor  (query: "Incorporar [funcionalidad] desde [owner/repo]")

# Si la oportunidad toca arquitectura, topología repo_motor/repo_destino o seguridad:
# abrir primero work-plan / ticket_contract con manager-create-work-plan

# [DEPRECATED - WT-2026-254a] Lo deprecated es esta invocación legacy vía scripts/orquestador.py
#   python scripts/orquestador.py --skill /refactor --query "..."
# pertenecía al motor Goose/Claw. No usar en proyectos nuevos.
```

**Criterio de aceptación:**
- [ ] [Funcionalidad] incorporada en `skills/` o `scripts/`
- [ ] Tests pasan (`python scripts/run_pytest_safe.py`)
- [ ] `ruff check .` PASS
- [ ] `python .agent/agent_controller.py --validate --json --force` PASS
- [ ] Documentado en `CHANGELOG.md`
```

---

## Credits Block Template

Al final del reporte, después de "Acción Inmediata", emitir un bloque candidato listo para pegar en `CREDITS.md` cuando el humano decida adoptar la idea. **El agente NO escribe en CREDITS.md directamente** — solo emite la fila sugerida.

```markdown
---

## Credits — Candidate row for `CREDITS.md`

Si decides adoptar alguna de las oportunidades anteriores, añade esta fila a `CREDITS.md` (tabla principal):

| WOT | Source | Pattern | License | Adapted vs Ported |
|----|--------|---------|---------|-------------------|
| WOT-XXXX-XXX (TBD) | [<owner/repo>@<sha-corto>](https://github.com/<owner>/<repo>/tree/<sha>) | <pattern name> | <license, [verify] si no comprobado> | <Adapted / Ported / Inspiration> |

**Notas para completar:**
- `WP`: rellenar al abrir el ticket que adopta la idea.
- `License`: verificar manualmente en el repo source (LICENSE file). El agente NO debe auto-rellenar este campo — usa `[verify]` si no está comprobado.
- `Adapted vs Ported`:
  - **Ported**: código/texto copiado con mínima modificación.
  - **Adapted**: patrón reutilizado, implementación nuestra difiere materialmente.
  - **Inspiration**: idea inspiró pero implementación predates o difiere completamente.
```

**Reglas para emitir este bloque:**
- Solo si **al menos una oportunidad** tiene decisión `AHORA` o `DESPUÉS`. Si todo es `IGNORAR`, no emitir credits block (nada se va a adoptar).
- Solo el bloque pegable, no escribir en `CREDITS.md`. La decisión final de cuándo adoptar es humana.
- `project-finalize` Paso 8d verificará que la fila existe en `CREDITS.md` cuando cierre un WP con `Origen externo:` o `Inspired by:` en `work_plan.md`.

---

## Metadata del Reporte

Al inicio del archivo persistido, incluir:

```markdown
# Repo Compare: [owner/repo] vs el proyecto local

**Fecha:** YYYY-MM-DD
**Repo target:** https://github.com/<owner>/<repo>
**SHA target:** `<sha>` (obtenido vía `mcp__github__list_commits` perPage=1)
**AUDIT.md:** [fresco (< 24h) / regenerado / stale]
**Archivos leídos:** N (máx 12)
**Oportunidades detectadas:** N (3-5)

---
```

---

## Ejemplo completo (oportunidad #1)

```markdown
### OPORTUNIDAD #1: Local Audit Tool

**Ubicación en repo target:** `scripts/local_audit.py:1-50`
**Líneas clave:**
```python
def generate_audit_snapshot() -> dict:
    """Recopilar estado operativo del repositorio."""
    return {
        "generated_at": datetime.now().isoformat(),
        "structure": collect_structure(),
        "skills": collect_skills(),
        "scripts": collect_scripts(),
    }
```
**Fuente:** `mcp__github__get_file_contents` + verificación cruzada

**¿Qué hace?**
Script que recopila el estado operativo del repositorio (estructura, skills, scripts) y emite un snapshot JSON/Markdown para contexto de agentes.

**¿Qué valor aporta a el proyecto local?**
Permite a los agentes entender rápidamente qué existe en el proyecto sin leer todo el árbol. Reduce hallucination y acelera onboarding.

**¿Ya existe en el proyecto local?**
- **Estado:** [YA EXISTE]
- **Cita AUDIT.md:** AUDIT.md sección 4.1 menciona `scripts/local_audit.py` que ya genera `audit.json` y `AUDIT.md`.

**📎 Fuente verificada:** Ambos (AUDIT.md sección 4.1 + GitHub: owner/repo/scripts/local_audit.py:L1-50)

**Dependencias nuevas:** Ninguna (usa `pathlib`, `json`, `datetime` del stdlib)

**Encaje técnico:**
- **Python:** 3.10+ (coincide)
- **Arquitectura:** Alto (ya existe patrón similar en `scripts/`)
- **Deps:** Ligeras (stdlib)

**Plan de incorporación:** N/A (ya existe en local)

**Dificultad estimada:** S (≤1h) — [solo verificar que la versión local está actualizada]

**Prioridad:** Baja — [ya existe]

**Decisión:** IGNORAR — [ya existe en el proyecto local]
```

---

## Ejemplo de conflicto con charter (oportunidad descartada por intent)

Caso del modo de fallo: la funcionalidad NO existe en local y es técnicamente buena, pero **choca con una restricción del charter**. El campo `Compatibilidad con charter` debe rellenarse con `Choca` + cita, y la decisión cae a `IGNORAR` por intent (no por encaje técnico). Así se rellena de forma consistente entre agentes:

```markdown
### OPORTUNIDAD #N: Telemetría remota de uso (analytics opt-out)

**Ubicación en repo target:** `telemetry/collector.py:1-80`
**Fuente:** `mcp__github__get_file_contents` + verificación cruzada

**¿Qué hace?**
Envía métricas de uso (comandos, latencias, errores) a un endpoint remoto para análisis agregado, con opt-out por config.

**¿Ya existe en el proyecto local?**
- **Estado:** No
- **Cita AUDIT.md:** AUDIT.md sección 5.x no menciona telemetría ni envío de datos a red.

**Compatibilidad con charter**
- **Estado:** Choca
- **Cita `repo_charter.md`:** Sección `Security Constraints`: "ningún componente envía datos del usuario fuera de la máquina local". La telemetría remota viola esta restricción de forma directa, independientemente del opt-out.

**📎 Fuente verificada:** Ambos (AUDIT.md sección 5.x + GitHub: owner/repo/telemetry/collector.py:L1-80)

**Encaje técnico:** Alto (Python 3.10+, deps ligeras) — pero **irrelevante**: el conflicto de intent manda sobre el encaje técnico.

**Decisión:** IGNORAR — choca con `Security Constraints` del charter (no por falta de encaje técnico, sino por intent). No abrir ticket.
```

> **Regla:** cuando `Compatibilidad con charter` = `Choca`, la `Decisión` es `IGNORAR` por intent aunque el encaje técnico sea Alto. El charter manda sobre la conveniencia técnica (ver `audit_agent_output.md §2.b Intent Audit`). Si el charter NO existe, el campo es `Intent Audit: no verificable` y la decisión se toma solo por criterio técnico.
