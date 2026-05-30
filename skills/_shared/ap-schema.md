# AP Schema Canonico

Plantilla compartida para registrar anti-patrones de forma consistente entre Builder, Manager y memoria.

## En `anti-patterns.md`

- ID estable: `AP-NN - Nombre`.
- Una linea de descripcion: que hace mal el agente.
- Una linea de efecto: consecuencia observable.

## En `code-rules.md`

- Regla imperativa, corta y accionable.
- Incluir un ejemplo `NO` y un ejemplo `SI` cuando aplique.
- La regla debe derivarse directamente del anti-patron.

## En `review-checklist.md`

- Una comprobacion bloqueante y verificable por diff o evidencia.
- Debe permitir al Manager decidir sin inferir.

## En `observations.jsonl`

```json
{
  "timestamp": "ISO-8601",
  "topic": "kebab-del-patron",
  "signal": "Que fallo exactamente y que regla se deriva",
  "source": "human_audit_WP-XXXX | session-YYYY-MM-DD",
  "domain": "security-gates | integration-tests | protocol-handlers | bus-architecture | review-quality | config-schema | testing | delivery-hygiene | builder-contract",
  "applies_to": "code | mixed | docs | all",
  "confidence": 0.95,
  "impact": "low | medium | high",
  "source_ticket": "WP-YYYY-NNN",
  "pattern_id": "AP-NN (opcional)",
  "recommended_followup": "descripcion de accion futura (opcional)"
}
```

### Campos obligatorios (canonico)

- `timestamp` (string): ISO-8601 con zona horaria (ej. `2026-05-27T12:00:00Z`).
- `topic` (string): identificador kebab-case del patron o hallazgo.
- `signal` (string): descripcion clara de que fallo y que regla se deriva.
- `source` (string): origen de la observacion (`human_audit_WP-XXXX`, `session-YYYY-MM-DD`, etc.).
- `domain` (string): categoria estable del dominio (ver valores permitidos arriba).
- `applies_to` (string): donde impacta la observacion (`code`, `mixed`, `docs`, `all`).
- `confidence` (float): valor entre `0.0` y `1.0` que indica certeza del hallazgo.
- `source_ticket` (string): ticket que genero la observacion.

### Campos opcionales (canonico)

- `impact` (string): impacto estimado (`low`, `medium`, `high`).
- `pattern_id` (string): ID del anti-patron si la observacion promueve uno (ej. `AP-09`).
- `recommended_followup` (string): accion futura recomendada cuando exista.
- `surface` (array de strings): lista de archivos o modulos concretos afectados.
- `anti_pattern_id` (string): **obligatorio cuando la observacion eleva un bug a AP**. Debe referenciar un ID existente en `anti-patterns.md` (ej. `AP-09`).

### Campos legacy (retrocompatibles)

- `category` (string): `convention | decision | fact | pattern`.

### Reglas de validacion

- `confidence` debe estar en el rango `[0.0, 1.0]`.
- `applies_to` debe ser uno de: `code`, `mixed`, `docs`, `all`.
- `domain` debe elegir un valor util y estable de la lista anterior.
- `anti_pattern_id` solo puede usarse si el ID ya existe en `anti-patterns.md`.
- **Orden obligatorio**: primero se escribe en `anti-patterns.md`; luego se propaga a `code-rules.md`, `review-checklist.md` y `observations.jsonl`.
- Cada AP nuevo debe tener las cuatro superficies alineadas.

## Ejemplo minimo (canonico)

```json
{
  "timestamp": "2026-05-27T12:00:00Z",
  "topic": "protocol-key-assumption",
  "signal": "guard_paths leyo tool_calls/shell_command en vez de tool_input/command; produccion y tests compartian la misma suposicion erronea.",
  "source": "human_audit_WP-2026-154",
  "domain": "protocol-handlers",
  "applies_to": "code",
  "confidence": 0.95,
  "impact": "high",
  "source_ticket": "WP-2026-154",
  "surface": [".agent/hooks/guard_paths.py", "tests/test_guard_paths.py"],
  "anti_pattern_id": "AP-09"
}
```

## Ejemplo legacy (retrocompatible)

```json
{
  "timestamp": "2026-05-27T12:00:00Z",
  "topic": "ticket-completion",
  "signal": "Ticket WP-2026-132 completado: Implement session close observations",
  "source": "session-close",
  "category": "fact",
  "source_ticket": "WP-2026-132"
}
```

## Reglas

- Cada AP nuevo debe tener las cuatro superficies alineadas.
- El validador `scripts/validate_observations.py` verifica el contrato y rechaza entradas invalidas con codigo de salida 1.
