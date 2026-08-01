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
  "source": "human_audit_WOT-XXXX | session-YYYY-MM-DD",
  "domain": "ver tabla 'Dominios canonicos' mas abajo",
  "applies_to": "code | mixed | docs | all",
  "confidence": 0.95,
  "impact": "low | medium | high",
  "source_ticket": "WOT-YYYY-NNNx",
  "pattern_id": "AP-NN (opcional)",
  "recommended_followup": "descripcion de accion futura (opcional)"
}
```

### Campos obligatorios (canonico)

- `timestamp` (string): ISO-8601 con zona horaria (ej. `2026-05-27T12:00:00Z`).
- `topic` (string): identificador kebab-case del patron o hallazgo.
- `signal` (string): descripcion clara de que fallo y que regla se deriva.
- `source` (string): origen de la observacion (`human_audit_WOT-XXXX`, `session-YYYY-MM-DD`, etc.).
- `domain` (string): categoria estable del dominio (ver "Dominios canonicos").
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
- `domain` debe ser uno de los de la tabla "Dominios canonicos" (abajo), elegido
  por su criterio de exclusion, no por parecido tematico.
- `anti_pattern_id` solo puede usarse si el ID ya existe en `anti-patterns.md`.
- **Orden obligatorio**: primero se escribe en `anti-patterns.md`; luego se propaga a `code-rules.md`, `review-checklist.md` y `observations.jsonl`.
- Cada AP nuevo debe tener las cuatro superficies alineadas.

## Dominios canonicos

Fuente unica: `bus/observation_domains.py` (`DOMAIN_SPECS`). Esta tabla se
verifica contra ese modulo en `tests/unit/test_observation_domains.py`: si
anades un dominio en el codigo y no aqui (o al reves), el test falla.

`deliverable_types` NO es decorativo: es el ENRUTADO. Determina en que manager
reviews se recupera la observacion. Un dominio que valida pero no enruta produce
memoria que nadie lee jamas (origen: LEA-2026-002o).

OJO: `deliverable_types` usa el vocabulario del work plan
(`code|documentation|research|analysis|mixed`), que NO es el de `applies_to`
(`code|mixed|docs|all`). Son enums distintos: uno dice `docs`, el otro
`documentation`.

| dominio | criterio (excluyente) | deliverable_types |
| --- | --- | --- |
| `security-gates` | Barrera de seguridad o permisos cuyo fallo ABRE acceso. Frente a `testing`: el dano es exposicion, no falso verde. | `code, mixed` |
| `integration-tests` | Fallo que solo aparece al combinar componentes reales. Frente a `testing`: la unidad pasaba; el defecto vive en la juntura. | `code, mixed` |
| `protocol-handlers` | Forma exacta del mensaje que viaja entre agentes o herramientas (claves, anidamiento). Frente a `config-schema`: el dato circula, no se persiste. | `code, mixed` |
| `bus-architecture` | Topologia y estado operativo del PROPIO bus: terminacion, recuperacion, autoridad de lectura. Frente a `cross-phase-state`: el objeto es el bus, no un dato de dominio que lo atraviesa. | `code, mixed` |
| `review-quality` | Criterios de evidencia y decision del Manager al revisar una entrega. Frente a `builder-contract`: es el lado que juzga, no el que produce. | `code, documentation, research, analysis, mixed` |
| `config-schema` | Forma y acceso seguro a configuracion persistida o parseada. Frente a `protocol-handlers`: el dato se guarda y se relee, no se envia. | `code, mixed` |
| `testing` | El test como instrumento: cobertura, ortogonalidad, falso verde. Frente a `contract-fixtures`: el hallazgo agota UNA superficie. | `code, mixed` |
| `delivery-hygiene` | Que se commitea, donde, con que nombre, y si el cierre esta completo. Frente a `review-quality`: es mecanica de entrega, no juicio sobre el contenido. | `code, mixed` |
| `builder-contract` | Obligaciones del Builder al implementar: alcance, evidencia, no exceder el ticket. Frente a `review-quality`: es el lado que produce, no el que juzga. | `code, mixed` |
| `contract-fixtures` | Elevar una identidad compartida a fixture transversal cuando el mismo fallo aparece por TERCERA vez. Frente a `testing`: el hallazgo es la reincidencia a traves de superficies, y la accion es crear la fixture comun, no arreglar el test que fallo. | `code, mixed` |
| `warning-contracts` | Avisos contrastados contra un historico: excluir la ejecucion en curso, distinguir reintento de repeticion. Frente a `review-quality`: el objeto es el aviso que emite una herramienta y su ventana de comparacion, no la evidencia de una revision. | `code, mixed` |
| `cross-phase-state` | Estado persistido entre fases: procedencia, vigencia, invalidacion, relectura. Frente a `bus-architecture`: el objeto es un dato de dominio que sobrevive a la fase que lo escribio y que otra fase relee, no la topologia del bus. | `code, mixed` |

## Ejemplo minimo (canonico)

```json
{
  "timestamp": "2026-05-27T12:00:00Z",
  "topic": "protocol-key-assumption",
  "signal": "guard_paths leyo tool_calls/shell_command en vez de tool_input/command; produccion y tests compartian la misma suposicion erronea.",
  "source": "human_audit_WOT-2026-154",
  "domain": "protocol-handlers",
  "applies_to": "code",
  "confidence": 0.95,
  "impact": "high",
  "source_ticket": "WOT-2026-154",
  "surface": [".agent/hooks/guard_paths.py", "tests/test_guard_paths.py"],
  "anti_pattern_id": "AP-09"
}
```

## Ejemplo legacy (retrocompatible)

> legacy-compat (WOT-2026-010a): este ejemplo conserva deliberadamente un ID
> historico `WP-2026-132` para demostrar que el schema sigue aceptando
> observaciones de tickets legacy. NO es un generador de nomenclatura nueva;
> los IDs nuevos usan el prefijo canonico `WOT-`.

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
