# Plantilla de Investigacion - deep-research

Esta plantilla define el formato canonico para los reportes de investigacion previa.

## Estructura obligatoria

El archivo de output debe contener las siguientes secciones en orden:

```markdown
# Investigacion: <topic>

**Fecha:** YYYY-MM-DD
**Autor:** <agente o humano>
**Ticket relacionado:** WP-YYYY-NNN (si aplica)

## Contexto

<Resumen del estado actual del sistema basado en la lectura de PROJECT.md, work_plan.md, execution_log.md y observaciones recientes.>

<Incluir referencias explicitas a archivos y secciones cuando sea relevante.>

## Gaps

<Lista de informacion faltante o ambigua identificada durante la investigacion.>

- [ ] Gap 1: descripcion clara
- [ ] Gap 2: descripcion clara
- [ ] ...

## Fuentes

<Lista de fuentes consultadas, clasificadas por tipo.>

### Locales
- `ruta/al/archivo.py` - descripcion breve
- ...

### Externas (GitHub u otras)
- `owner/repo/path:L#` - descripcion breve
- ...

### No verificadas
- [NO VERIFICADO] fuente potencial - razon de la limitacion

## Recomendacion

<Acción inmediata sugerida basada en la investigacion.>

**Accion sugerida:** <abrir WP | actualizar DOCUMENTACION | investigar mas | no accion necesaria>

**Razon:** <justificacion clara>

**Archivos a tocar:** <lista de Files Likely Touched si se sugiere abrir WP>

---

*Reporte generado por deep-research skill v1.0.0*
```

## Reglas de llenado

1. **Contexto**: Debe citar al menos 3 archivos base leidos. No inventar contenido.
2. **Gaps**: Cada gap debe ser accionable. Si no es accionable, marcar como `[BLOCKER]`.
3. **Fuentes**: Clasificar explicitamente como `Locales`, `Externas` o `No verificadas`.
4. **Recomendacion**: Debe ser binaria (hacer X o no hacer nada). No dejar ambiguedad.

## Persistencia

El archivo se guarda en:
```
.agent/runtime/research/<topic-kebab-case>-<YYYY-MM-DD>.md
```

Ejemplo: `.agent/runtime/research/ecc-capability-pack-2026-05-27.md`

Este path esta excluido de git. No commitear investigaciones.

## Ejemplo minimo

```markdown
# Investigacion: ECC capability pack

**Fecha:** 2026-05-27
**Autor:** Builder
**Ticket relacionado:** WP-2026-157

## Contexto

El sistema actual carece de una skill formal de investigacion previa.
`skills/repo-compare/` existe pero compara repositorios, no produce contexto
estructurado antes de abrir un ticket.

`skills/_shared/ap-schema.md` y `observations.jsonl` sostienen el patron AP
en la practica, pero falta endurecer el contrato.

## Gaps

- [ ] No existe skill documental para investigacion pre-plan
- [ ] El contrato AP no tiene validador automatico
- [ ] No hay harness minimo de regresion para flujos criticos

## Fuentes

### Locales
- `skills/_shared/ap-schema.md` - define campos de observaciones
- `bus/review_bridge.py` - implementa review de Manager
- `.agent/hooks/guard_paths.py` - guarda de seguridad

### Externas
- [NO VERIFICADO] ECC original - MCP GitHub no disponible

## Recomendacion

**Accion sugerida:** abrir WP para crear deep-research skill + validador + eval harness

**Razon:** Los gaps identificados son bloqueantes para mejora continua del sistema.

**Archivos a tocar:**
- `skills/deep-research/SKILL.md` (nuevo)
- `skills/_shared/ap-schema.md` (actualizar)
- `scripts/validate_observations.py` (nuevo)
- `tests/evals/` (nuevo)

---

*Reporte generado por deep-research skill v1.0.0*
```
