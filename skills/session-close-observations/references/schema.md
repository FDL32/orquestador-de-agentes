# Schema de Observaciones - Session Close

## Schema Base

```json
{
  "timestamp": "2026-05-25T12:00:00Z",
  "signal": "Descripcion clara y concisa del hecho observado",
  "category": "convention",
  "source_ticket": "WP-2026-132",
  "topic": "memory-management",
  "source": "session-close"
}
```

## Campos

### timestamp (requerido)
- **Tipo**: ISO 8601 string con timezone UTC
- **Formato**: `YYYY-MM-DDTHH:MM:SS.ffffffZ`
- **Ejemplo**: `2026-05-25T12:00:00.000000Z`
- **Nota**: Usar `datetime.now(timezone.utc).isoformat()`

### signal (requerido)
- **Tipo**: string
- **Longitud minima**: 30 caracteres
- **Contenido**: Descripcion objetiva y verificable
- **Evitar**: Opiniones, traces de herramientas, contexto efimero

### category (requerido)
- **Tipo**: enum
- **Valores validos**: `convention`, `decision`, `fact`, `pattern`
- **Invalido**: cualquier otro valor

### source_ticket (requerido)
- **Tipo**: string
- **Formato**: `WP-YYYY-NNN` o referencia equivalente
- **Ejemplo**: `WP-2026-132`, `MAN-2026-045`

### topic (requerido)
- **Tipo**: string
- **Formato**: kebab-case recomendado
- **Ejemplos**: `memory-management`, `session-bootstrap`, `quality-gates`

### source (requerido)
- **Tipo**: string
- **Valores tipicos**: `session-close`, `builder`, `manager`, `supervisor`
- **Proposito**: Trazabilidad del origen

### applies_to (opcional)
- **Tipo**: string o list[string]
- **Valores validos**: `code`, `mixed`, `documentation`, `research`, `analysis`, `all`
- **Default**: `all` (si ausente, aplica a todos los deliverable_types)
- **Proposito**: Filtrar observaciones por tipo de entregable en el prompt del Manager

### anti_pattern_id (opcional)
- **Tipo**: string
- **Formato**: `AP-NN` (e.g. `AP-01`, `AP-07`)
- **Proposito**: Enlazar la observacion con un anti-patron del inventario canonico (`skills/_shared/anti-patterns.md`). Si el AP ya esta codificado como regla, el review_bridge omite la observacion del prompt dinamico para evitar redundancia

## Ejemplos Validos

```json
{
  "timestamp": "2026-05-25T12:00:00.000000Z",
  "signal": "Session-close observations skill creada con schema de 6 campos",
  "category": "fact",
  "source_ticket": "WP-2026-132",
  "topic": "skill-creation",
  "source": "session-close"
}
```

```json
{
  "timestamp": "2026-05-25T12:05:00.000000Z",
  "signal": "Filtros de curacion: hecho, persistencia entre sesiones, utilidad repetida",
  "category": "convention",
  "source_ticket": "WP-2026-132",
  "topic": "memory-filters",
  "source": "session-close"
}
```

## Ejemplos Invalidos

```json
{
  "timestamp": "2026-05-25T12:00:00Z",
  "signal": "Tool edit called",
  "category": "fact"
}
```
**Invalido**: signal es trace de herramienta, < 30 chars

```json
{
  "timestamp": "2026-05-25T12:00:00Z",
  "signal": "Deberiamos mejorar la memoria",
  "category": "opinion"
}
```
**Invalido**: categoria no valida, signal es opinion

```json
{
  "timestamp": "2026-05-25T12:00:00Z",
  "signal": "Falta el campo category"
}
```
**Invalido**: campo requerido ausente
