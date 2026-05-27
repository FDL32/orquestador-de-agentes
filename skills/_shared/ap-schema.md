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
  "applies_to": "code | mixed | docs | all",
  "surface": [".agent/hooks/guard_paths.py", "tests/test_guard_paths.py"],
  "anti_pattern_id": "AP-NN",
  "confidence": 0.95,
  "domain": "security-gates | integration-tests | protocol-handlers | bus-architecture | review-quality | config-schema | testing"
}
```

## Ejemplo minimo

```json
{
  "timestamp": "2026-05-27T12:00:00Z",
  "topic": "protocol-key-assumption",
  "signal": "guard_paths leyo tool_calls/shell_command en vez de tool_input/command; produccion y tests compartian la misma suposicion errónea.",
  "source": "human_audit_WP-2026-154",
  "applies_to": "code",
  "surface": [".agent/hooks/guard_paths.py", "tests/test_guard_paths.py"],
  "anti_pattern_id": "AP-09",
  "confidence": 0.95,
  "domain": "protocol-handlers"
}
```

## Reglas

- `confidence` va de `0.0` a `1.0`.
- `domain` debe elegir un valor util y estable.
- `applies_to` debe indicar donde impacta la observacion.
- `surface` debe listar archivo o modulo concreto cuando la observacion apunta a una parte especifica del sistema.
- `anti_pattern_id` es obligatorio cuando la observacion formaliza un AP; en observaciones genericas puede omitirse.
- `anti_pattern_id` solo puede usarse si el ID ya existe en `anti-patterns.md`. Orden obligatorio: primero se escribe en `anti-patterns.md`; luego se propaga a `code-rules.md`, `review-checklist.md` y `observations.jsonl`.
- Cada AP nuevo debe tener las cuatro superficies alineadas.
