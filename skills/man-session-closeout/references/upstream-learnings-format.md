# UPSTREAM_LEARNINGS.md Format

## Purpose

`UPSTREAM_LEARNINGS.md` is a human review queue for learnings that may be reusable by the motor.

## Sections

### Pendientes de revision

Use one entry per learning awaiting confirmation.

```markdown
## Pendientes de revision
### 2026-05-28 | origen: WP-2026-163 | estado: dudoso | ttl_wps: 3
- learning: "..."
- razon: "..."
- propuesta de aplicacion en herramienta:
  - `skills/man-create-work-plan/SKILL.md`
  - `skills/man-create-work-plan/references/plan-quality-checklist.md`
- decision del usuario: pendiente
```

### Confirmados

Use when the user approves a learning as valid and reusable.

```markdown
## Confirmados
### 2026-05-28 | origen: WP-2026-163 | estado: generalizable
- learning: "..."
- razon: "..."
- propuesta de aplicacion en herramienta:
  - `skills/...`
- decision del usuario: aceptado
```

### Archivados

Use for expired or discarded learning items.

```markdown
## Archivados
### 2026-05-01 | origen: WP-2026-150 | estado: expirado
- learning: "..."
- motivo de archivo: "TTL vencido sin reclasificacion"
```

## Rules

- `ttl_wps` starts at `3` for `dudoso`
- Decrement only when the closeout skill runs on that repo copy
- Move to `Archivados` when `ttl_wps` reaches `0`
- Do not auto-promote to the motor without human validation
