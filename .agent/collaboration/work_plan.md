# Work Plan - WOT-2026-019j

## Metadata
- **ID:** WOT-2026-019j
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** El scope gate no reconoce el heading `## Builder` para tickets
  `deliverable_type=mixed`.
- **Prioridad:** Baja
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Hacer que un `work_plan.md` con `deliverable_type: mixed` que declara sus
entregables bajo la seccion Builder (en vez de la seccion FLT canonica) valide
sin warning y pase `--mark-ready` sin necesitar `--scope-override`, igual que
ya ocurre hoy para `analysis`/`documentation`/`research`.

(Nota: esta prosa evita deliberadamente el literal de heading FLT con doble
almohadilla; el parser de secciones detecta por substring y una mencion en
prosa lo confundiria -- follow-up 019l.)

## Contexto (Fase 0 del Orquestador, verificado en esta sesion por el Manager)

`_DOC_DELIVERABLE_TYPES = frozenset({"analysis", "documentation", "research"})`
(`.agent/scope_gate.py:58`) NO incluye `mixed`. Tres funciones dependen de este
conjunto (o de una cadena que termina en el mismo parser) como guard del
fallback a `## Builder`. Confirmado por lectura directa de cada una:

1. `scope_gate.parse_files_likely_touched` (linea 331-349): si la seccion
   FLT canonica (heading `Files Likely Touched`) no produce archivos Y
   `deliverable_type in _DOC_DELIVERABLE_TYPES`, cae a `## Builder`. Resuelve
   el whitelist real que
   usa `--validate`. Con `mixed`, el fallback nunca se activa, whitelist
   vacio, `scope_gate.check_scope_gate` (linea 476-536) emite el warning
   "No Files Likely Touched section in work_plan.md" (linea 504).
2. `scope_gate.files_likely_touched_tokens` (linea 131-145): MISMO guard
   (`if not tokens and deliverable_type in _DOC_DELIVERABLE_TYPES`), usado
   para los tokens crudos de checks de extension/congruencia
   (`agent_controller._check_deliverable_type_file_congruence`, linea 1241).
   Es una superficie separada en el mismo archivo; debe alinearse por
   coherencia aunque hoy `_check_deliverable_type_file_congruence` NUNCA se
   invoca con `value="mixed"` (su propio guard,
   `_DOC_DELIVERABLE_TYPES_CONGRUENCE` en `agent_controller.py:1238`, tampoco
   incluye `mixed`, ver Non-goals: ESE conjunto NO se toca, es un chequeo
   semanticamente distinto e inverso).
3. El checkpoint del mark-ready: `agent_controller.py` linea 3352
   (`_handle_mark_ready`) llama `_parse_raw_flt_paths(plan_content)`, alias
   (linea 3582) de `motor_checkpoint.parse_raw_flt_paths` (linea 180-200), que
   llama `scope_gate.parse_flt_raw_paths(..., target="motor")` (linea 274-301)
   que llama `scope_gate.parse_flt_raw_buckets` (linea 244-271) que llama
   `scope_gate._parse_flt_section` (linea 169-209). `_parse_flt_section` SOLO
   reconoce el heading FLT canonico por substring (linea 184) y NO recibe
   `deliverable_type` como parametro en ningun punto de la cadena, ni tiene
   fallback a `## Builder`. Los doc-types no sufren esto porque
   `_handle_mark_ready` los trata como `_non_code_ticket` (linea 3340:
   `_dt_mr in {"documentation", "research", "analysis"}`) y SALTA el
   checkpoint entero (linea 3341-3342: `checkpoint_scope_pass = True`). Pero
   `mixed` NO esta en ese set, cae al checkpoint (linea 3344 en adelante)
   que en la linea 3352 llama `_parse_raw_flt_paths(plan_content)` SIN pasar
   `deliverable_type`, el fallback a `## Builder` nunca se activa: cada
   archivo del checkpoint git se reporta "outside Files Likely Touched"
   (linea 3367-3382), exige `--scope-override`.

Otros 2 call-sites de la MISMA `_parse_raw_flt_paths` (verificados por el
Manager, no mencionados originalmente en la ficha pero parte de la misma
cadena de codigo, dentro de `_handle_pre_handoff`):
- Linea 3636 (guard de autocorreccion BOM de `.opencode/opencode.json`): en
  este punto de la funcion NO existe todavia ninguna variable de
  `deliverable_type` (se lee mas adelante, en la linea 3726, como `_dt_ph`).
- Linea 3914 (commit-or-block de cambios productivos sin commitear en
  `repo_motor`): en este punto SI existe `_dt_ph` (definida en la linea 3726,
  antes de 3914 en el flujo de ejecucion de la funcion).
Ambos comparten la misma funcion publica; dejarlos sin el parametro
perpetuaria el mismo bug en `--pre-handoff` para tickets `mixed` con
`## Builder` (bloqueo silencioso identico al del mark-ready). Se corrigen en
el mismo PASO por coherencia de la firma publica, no por texto literal de la
ficha original (que solo cita el checkpoint del mark-ready como ejemplo
verificado).

`_VALID_DELIVERABLE_TYPES = {"code", "documentation", "research", "analysis",
"mixed"}` (`agent_controller.py:1200`) confirma que `mixed` es un tipo valido
de primera clase, no un tipo secundario.

## Decision Arquitectonica

**Superficies 1 y 2 (`scope_gate.py`). Elegida: opcion (a), conjunto
compartido nuevo.** Crear
`_FLT_BUILDER_FALLBACK_TYPES = _DOC_DELIVERABLE_TYPES | {"mixed"}` en
`scope_gate.py` (junto a la definicion de `_DOC_DELIVERABLE_TYPES`, linea 58)
y usarlo como guard en `parse_files_likely_touched` (linea 347) y
`files_likely_touched_tokens` (linea 143), en vez de anadir
`or deliverable_type == "mixed"` en cada sitio por separado. Motivo: un unico
punto de verdad para "que deliverable_types caen al fallback de `## Builder`"
evita que una futura superficie nueva olvide anadir `mixed` de forma
independiente; el conjunto documenta la relacion explicitamente.
`.agent/agent_controller.py:1238` (`_DOC_DELIVERABLE_TYPES_CONGRUENCE`) NO se
toca: es un conjunto hermano con proposito inverso (advertir cuando un
doc-type declara codigo), y anadir `mixed` ahi rompería su logica (mixed con
codigo es legitimo, no debe advertir).

**Superficie 3 (`_parse_flt_section` y su cadena). Elegida: opcion (a), pasar
`deliverable_type` explicito por la cadena de llamadas, con default `"code"`
en cada nivel para preservar el comportamiento actual de los otros 2
call-sites de `agent_controller.py` que no cambian su logica
(`agent_controller.py:3636` recibe una lectura local nueva de
`deliverable_type` calculada ahi mismo, ver Fase 3; `:3914` pasa `_dt_ph` ya
existente).** Cadena exacta a modificar:
- `motor_checkpoint.parse_raw_flt_paths(plan_content, *, deliverable_type:
  str = "code")`: pasa `deliverable_type` a
  `scope_gate.parse_flt_raw_paths(..., deliverable_type=deliverable_type)`.
- `scope_gate.parse_flt_raw_paths(..., *, deliverable_type: str = "code")`:
  pasa a `parse_flt_raw_buckets(..., deliverable_type=deliverable_type)`.
- `scope_gate.parse_flt_raw_buckets(..., *, deliverable_type: str = "code")`:
  pasa a `_parse_flt_section(lines, deliverable_type=deliverable_type)`.
- `scope_gate._parse_flt_section(lines, *, deliverable_type: str = "code")`:
  si el escaneo de la seccion FLT canonica no produce ninguna entrada
  (`entries` vacio al terminar el bucle) Y `deliverable_type in
  _FLT_BUILDER_FALLBACK_TYPES`, re-escanea `lines` buscando `## Builder` con
  la MISMA logica de deteccion de inicio/fin de seccion que ya usa para FLT
  (heading exacto, corta en el siguiente `## `, ignora namespaces `### `
  porque `## Builder` no los usa), y devuelve esas entradas como
  `(None, raw_path)` (namespace plano, sin `has_namespaces`).

Blast-radius: quirurgico y fail-closed. El default `"code"` en cada nivel de
la cadena preserva EXACTAMENTE el comportamiento actual para los 2 call-sites
de `agent_controller.py` que no se tocan en su logica (solo en pasar o no el
argumento), y para cualquier otro caller no listado en este repo (ninguno mas
existe, confirmado por grep). La opcion descartada (b), fallback
incondicional a `## Builder` en `_parse_flt_section` cuando no hay `## Files
Likely Touched` sin mirar `deliverable_type`, se descarta porque ampliaria
el fallback a CUALQUIER ticket `code` que por error omita la seccion FLT y
tenga una seccion `## Builder` con otro proposito (p.ej. notas de
implementacion), cambiando semantica para tickets que hoy dependen de que el
checkpoint bloquee si falta el whitelist.

## Files Likely Touched

### repo_motor

- `.agent/scope_gate.py` (anadir `_FLT_BUILDER_FALLBACK_TYPES`; extender el
  guard en `parse_files_likely_touched` y `files_likely_touched_tokens`;
  anadir el parametro `deliverable_type` con fallback a `## Builder` en
  `_parse_flt_section`, `parse_flt_raw_buckets` y `parse_flt_raw_paths`)
- `.agent/motor_checkpoint.py` (anadir el parametro `deliverable_type` a
  `parse_raw_flt_paths`, default `"code"`, pasandolo a
  `scope_gate.parse_flt_raw_paths`)
- `.agent/agent_controller.py` (3 call-sites de `_parse_raw_flt_paths`: linea
  3352 pasa `deliverable_type=_dt_mr`, ya existe en ese scope; linea 3636
  pasa `deliverable_type` leido localmente con `_read_deliverable_type`
  porque `_dt_ph` aun no existe en ese punto de la funcion; linea 3914 pasa
  `deliverable_type=_dt_ph`, ya existe en ese scope. Sin cambios de firma
  publica en ninguna otra funcion de este archivo.)
- `tests/unit/test_scope_gate_deliverable_aware.py` (actualizar
  `test_mixed_does_not_parse_builder_section`, que hoy afirma el
  comportamiento CONTRARIO al DoD de este ticket, a
  `test_mixed_parses_builder_section_as_whitelist`; anadir cobertura
  equivalente a los tests `analysis`/`documentation`/`research` existentes
  pero para `mixed`, incluyendo el caso `## Files Likely Touched` +
  `## Builder` simultaneos donde FLT gana)
- `tests/unit/test_scope_gate_topology.py` (anadir tests de
  `parse_flt_raw_paths`/`parse_flt_raw_buckets`/
  `motor_checkpoint.parse_raw_flt_paths` con `deliverable_type="mixed"` y una
  seccion `## Builder` sin `## Files Likely Touched`; verificar que
  `deliverable_type="code"` (default, sin el parametro) preserva el
  comportamiento actual de los tests ya existentes en este archivo, ej.
  `test_raw_flt_no_section_returns_empty`)
- `tests/unit/test_motor_checkpoint.py` (anadir un test de
  `parse_raw_flt_paths` con `deliverable_type="mixed"` + `## Builder`)

## Read/inspect only (Manager-only / no tocar)

- `.agent/agent_controller.py` lineas 1234-1264
  (`_DOC_DELIVERABLE_TYPES_CONGRUENCE`, `_check_deliverable_type_file_congruence`):
  conjunto hermano de proposito INVERSO (advertir cuando un doc-type declara
  un archivo de codigo). NO incluye ni debe incluir `mixed`. No se modifica.
- `tests/test_agent_controller.py` clase `TestDeliverableTypeFileCongruence`
  (linea 4281-4340): cubre el guard anterior; debe seguir en verde sin
  cambios en su codigo.

## Plan de Implementacion

### PASO 1 (IMPLEMENT) - scope_gate.py, superficies 1 y 2

1. Anadir, junto a `_DOC_DELIVERABLE_TYPES` (linea 58):
   `_FLT_BUILDER_FALLBACK_TYPES = _DOC_DELIVERABLE_TYPES | {"mixed"}`
2. En `files_likely_touched_tokens` (linea 143), cambiar
   `if not tokens and deliverable_type in _DOC_DELIVERABLE_TYPES:` por
   `if not tokens and deliverable_type in _FLT_BUILDER_FALLBACK_TYPES:`.
3. En `parse_files_likely_touched` (linea 347), cambiar
   `if not files and deliverable_type in _DOC_DELIVERABLE_TYPES:` por
   `if not files and deliverable_type in _FLT_BUILDER_FALLBACK_TYPES:`.
4. NO modificar `_DOC_DELIVERABLE_TYPES` en si (sigue usandose tal cual donde
   ya se usaba antes de este ticket, si hay otros usos); solo sustituir el
   conjunto usado en el guard de estas 2 funciones.
5. NO tocar `_check_deliverable_type_file_congruence` ni
   `_DOC_DELIVERABLE_TYPES_CONGRUENCE` en `agent_controller.py`.

DoD Paso 1:
- [ ] `_FLT_BUILDER_FALLBACK_TYPES` existe y es
      `_DOC_DELIVERABLE_TYPES | {"mixed"}`.
- [ ] `scope_gate.parse_files_likely_touched(plan, project_root=ROOT,
      deliverable_type="mixed")` devuelve los paths de `## Builder` cuando no
      hay `## Files Likely Touched`.
- [ ] `scope_gate.files_likely_touched_tokens(plan, deliverable_type="mixed")`
      devuelve los tokens crudos de `## Builder` en las mismas condiciones.
- [ ] `deliverable_type="code"` sigue devolviendo `set()` vacio cuando solo
      hay `## Builder` (comportamiento sin cambios, TP-05 con el DoD
      binario de la ficha).

### PASO 2 (IMPLEMENT) - scope_gate.py, superficie 3 (cadena FLT raw)

1. `_parse_flt_section(lines, *, deliverable_type: str = "code") ->
   tuple[bool, list[tuple[str | None, str]]]`: anadir el parametro. Al final
   del escaneo de `## Files Likely Touched`, si `entries` esta vacio Y
   `deliverable_type in _FLT_BUILDER_FALLBACK_TYPES`, ejecutar un segundo
   escaneo de `lines` buscando la seccion `## Builder` (misma logica de
   deteccion de inicio, `"## Builder" in stripped and
   stripped.startswith("## ")`, y de fin, corta en el siguiente `## ` que no
   sea `### `, que ya usa el escaneo de FLT) y devolver esas entradas con
   namespace `None` (no se procesan sub-headings `### ` dentro de
   `## Builder`: esa seccion nunca los usa en el repo, y namespaces solo
   tienen sentido para FLT). `has_namespaces` se mantiene en `False` para el
   resultado de fallback.
2. `parse_flt_raw_buckets(work_plan_content, *, delivery_authority: str =
   "repo_motor", deliverable_type: str = "code") -> dict[str, set[str]]`:
   anadir el parametro y pasarlo a `_parse_flt_section(lines,
   deliverable_type=deliverable_type)`.
3. `parse_flt_raw_paths(work_plan_content, *, delivery_authority: str =
   "repo_motor", target: str = "authority", deliverable_type: str = "code")
   -> set[str]`: anadir el parametro y pasarlo a
   `parse_flt_raw_buckets(work_plan_content,
   delivery_authority=delivery_authority, deliverable_type=deliverable_type)`.
4. NO cambiar la logica de namespaces (`### repo_motor`/`### repo_destino`)
   ni el comportamiento de `parse_flt_namespaced` mas alla de que ahora puede
   recibir entradas provenientes del fallback (siempre namespace `None`,
   enrutadas por `delivery_authority` exactamente igual que las lineas planas
   de FLT ya se enrutan hoy en `parse_flt_raw_buckets`, linea 264-269).

DoD Paso 2:
- [ ] `scope_gate.parse_flt_raw_paths(plan, deliverable_type="mixed",
      target="motor")` devuelve los paths de `## Builder` cuando no hay
      `## Files Likely Touched` y `delivery_authority="repo_motor"`.
- [ ] `scope_gate.parse_flt_raw_paths(plan, deliverable_type="code")` (sin
      cambiar la llamada, default `"code"`) sigue devolviendo `set()` para un
      plan con solo `## Builder`, igual que antes del ticket.
- [ ] Un plan con `## Files Likely Touched` Y `## Builder` simultaneos usa
      SOLO las entradas de FLT (el fallback nunca se activa si `entries` de
      FLT ya tiene contenido), para cualquier `deliverable_type`.

### PASO 3 (IMPLEMENT) - motor_checkpoint.py y 3 call-sites de agent_controller.py

1. `motor_checkpoint.parse_raw_flt_paths(plan_content: str, *,
   deliverable_type: str = "code") -> set[str]`: anadir el parametro y
   pasarlo a `scope_gate.parse_flt_raw_paths(plan_content,
   delivery_authority="repo_motor", target="motor",
   deliverable_type=deliverable_type)`.
2. `agent_controller.py` linea 3352 (dentro de `_handle_mark_ready`, bajo
   `if cp_valid and cp_files:`): cambiar
   `flt_motor_paths = _parse_raw_flt_paths(plan_content)` por
   `flt_motor_paths = _parse_raw_flt_paths(plan_content,
   deliverable_type=_dt_mr)` (`_dt_mr` ya definido en la linea 3339, dentro
   de la misma funcion, antes de este punto).
3. `agent_controller.py` linea 3636 (dentro de `_handle_pre_handoff`, guard
   BOM de `.opencode/opencode.json`): antes de la llamada, anadir
   `_dt_bom = _read_deliverable_type(plan_content)` y cambiar
   `_flt_paths = _parse_raw_flt_paths(plan_content)` por
   `_flt_paths = _parse_raw_flt_paths(plan_content,
   deliverable_type=_dt_bom)`. `_read_deliverable_type` es pura (regex sobre
   el string), sin efectos secundarios ni coste relevante de llamarla de
   nuevo mas adelante en la misma funcion (linea 3726, `_dt_ph`).
4. `agent_controller.py` linea 3914 (dentro de `_handle_pre_handoff`,
   commit-or-block de `repo_motor`): cambiar
   `flt_motor_paths = _parse_raw_flt_paths(plan_content)` por
   `flt_motor_paths = _parse_raw_flt_paths(plan_content,
   deliverable_type=_dt_ph)` (`_dt_ph` ya definido en la linea 3726, antes de
   este punto en el flujo de ejecucion de la funcion).
5. NO modificar ninguna otra logica de `_handle_mark_ready` ni
   `_handle_pre_handoff` (guards de HUMAN_GATE, circuit breaker, checkpoint
   tags, commit automatico, etc. quedan intactos).

Restricciones:
- NO anadir el parametro `deliverable_type` a ninguna funcion de
  `scope_gate.py`/`motor_checkpoint.py` distinta de las 5 listadas en PASO 1,
  PASO 2 y este PASO 3 (`parse_files_likely_touched`,
  `files_likely_touched_tokens`, `_parse_flt_section`,
  `parse_flt_raw_buckets`, `parse_flt_raw_paths`,
  `motor_checkpoint.parse_raw_flt_paths`).
- NO tocar `_DOC_DELIVERABLE_TYPES_CONGRUENCE` ni
  `_check_deliverable_type_file_congruence` en `agent_controller.py`.
- NO cambiar el default de ningun parametro nuevo: siempre `"code"`, para que
  cualquier llamada existente sin el argumento preserve el comportamiento
  actual byte a byte.

DoD Paso 3:
- [ ] `motor_checkpoint.parse_raw_flt_paths(plan, deliverable_type="mixed")`
      devuelve los paths de `## Builder` cuando no hay
      `## Files Likely Touched`.
- [ ] `motor_checkpoint.parse_raw_flt_paths(plan)` (sin el argumento) sigue
      devolviendo exactamente lo mismo que antes del ticket para los 5 tests
      existentes de `tests/unit/test_scope_gate_topology.py` (linea
      253-279): `test_raw_flt_motor_only_namespace`,
      `test_raw_flt_excludes_destino_namespace`,
      `test_raw_flt_destino_only_returns_empty`,
      `test_raw_flt_flat_backward_compat`,
      `test_raw_flt_no_section_returns_empty`.
- [ ] Un `work_plan.md` de prueba con `deliverable_type: mixed` y una seccion
      `## Builder` (sin `## Files Likely Touched`) pasa `--mark-ready` sin
      `--scope-override`, cuando el diff del checkpoint coincide con los
      archivos declarados en `## Builder`.

### PASO 4 (IMPLEMENT) - Tests de regresion y mutation-check

1. En `tests/unit/test_scope_gate_deliverable_aware.py`:
   - Renombrar `test_mixed_does_not_parse_builder_section` (linea 173-174) a
     `test_mixed_parses_builder_section_as_whitelist` e invertir su
     asercion: `_parse(_MIXED_BUILDER_ONLY, deliverable_type="mixed")` debe
     devolver el path resuelto de `bus/foo.py` (no `set()`).
   - Anadir `test_mixed_gate_no_warning_when_covered`: replica de
     `test_analysis_builder_section_no_warning_when_covered` pero con
     `deliverable_type="mixed"` y `_MIXED_BUILDER_ONLY`, afirmando
     `result["valid"] is True` y `result["warnings"] == []`.
   - Anadir `test_mixed_with_flt_uses_flt_not_builder`: replica de
     `test_analysis_with_flt_uses_flt_not_builder` (linea 180-183) pero con
     `deliverable_type="mixed"` sobre una fixture equivalente a
     `_ANALYSIS_FLT_AND_BUILDER` con `deliverable_type: mixed`.
2. En `tests/unit/test_scope_gate_topology.py`:
   - Anadir una fixture de work_plan con `deliverable_type: mixed` y solo
     `## Builder` (sin `## Files Likely Touched`).
   - Anadir `test_raw_paths_mixed_falls_back_to_builder_section`: llama
     `scope_gate.parse_flt_raw_paths(fixture, deliverable_type="mixed",
     target="motor")` y afirma que devuelve los paths de `## Builder`.
   - Confirmar (ejecutando la suite, no anadiendo aserciones nuevas) que
     `test_raw_flt_no_section_returns_empty` y los otros 4 tests de la
     seccion "parse_raw_flt_paths (motor_checkpoint) namespace-aware tests"
     (linea 248-279) siguen pasando sin cambios en su codigo.
3. En `tests/unit/test_motor_checkpoint.py`: anadir
   `test_parse_raw_flt_paths_mixed_falls_back_to_builder`, siguiendo el mismo
   patron de fixture que el punto anterior, pero invocando
   `motor_checkpoint.parse_raw_flt_paths` directamente (no
   `scope_gate.parse_flt_raw_paths`).

Mutation check (documentar en `execution_log.md` con salida literal de
pytest): revertir temporalmente el cambio de PASO 1 (quitar `mixed` de
`_FLT_BUILDER_FALLBACK_TYPES`, o revertir a `_DOC_DELIVERABLE_TYPES` en las 2
funciones) Y el cambio de PASO 2/PASO 3 (quitar el parametro
`deliverable_type` de `_parse_flt_section`/`parse_flt_raw_buckets`/
`parse_flt_raw_paths`/`motor_checkpoint.parse_raw_flt_paths`, o forzar que el
fallback nunca se active) debe hacer que los tests nuevos de este PASO 4
FALLEN mostrando de nuevo el comportamiento pre-fix (whitelist vacio,
warning "No Files Likely Touched", bloqueo del checkpoint). Restaurar el fix
debe hacer que vuelvan a pasar. Documentar ambas corridas (roja y verde) con
salida literal de pytest.

Restricciones:
- NO modificar ningun otro test existente de los 4 archivos listados en
  Files Likely Touched mas alla de lo descrito arriba (el resto de tests
  debe seguir pasando sin cambios en su codigo).
- NO eliminar cobertura existente de `code`/`analysis`/`documentation`/
  `research` en ninguno de los 4 archivos de test.

DoD Paso 4:
- [ ] Los tests nuevos/renombrados de
      `tests/unit/test_scope_gate_deliverable_aware.py`,
      `tests/unit/test_scope_gate_topology.py` y
      `tests/unit/test_motor_checkpoint.py` pasan tras el fix.
- [ ] MUTATION: revertir el fallback (PASO 1 + PASO 2/3) hace que los tests
      nuevos FALLEN reproduciendo el sintoma pre-fix, documentado con salida
      literal de pytest. Restaurar el fix hace que vuelvan a pasar.
- [ ] Toda la suite de los 4 archivos de test (mas
      `tests/test_agent_controller.py`, en particular
      `TestDeliverableTypeFileCongruence`) sigue en verde, sin cambios en las
      aserciones de los tests que ya existian antes de este ticket.

## Quality Gates

- Builder ejecuta (interprete canonico: `.venv/Scripts/python.exe`, NO el
  `python` del PATH):
  - `pytest tests/unit/test_scope_gate.py tests/unit/test_scope_gate_deliverable_aware.py tests/unit/test_scope_gate_isolation.py tests/unit/test_scope_gate_topology.py tests/unit/test_motor_checkpoint.py -v`
    (exit 0, 0 fallos).
  - `pytest tests/test_agent_controller.py -k "DeliverableType or ScopeGate or MarkReady or PreHandoff" -v`
    (exit 0, 0 fallos; nombres de clase exactos a confirmar por el Builder
    leyendo el archivo, sin renombrar tests existentes).
  - `ruff check .agent/scope_gate.py .agent/motor_checkpoint.py .agent/agent_controller.py tests/unit/test_scope_gate_deliverable_aware.py tests/unit/test_scope_gate_topology.py tests/unit/test_motor_checkpoint.py`
    (exit 0).
  - `ruff format --check .agent/scope_gate.py .agent/motor_checkpoint.py .agent/agent_controller.py tests/unit/test_scope_gate_deliverable_aware.py tests/unit/test_scope_gate_topology.py tests/unit/test_motor_checkpoint.py`
    (exit 0).
  - Repro manual del DoD binario de la ficha: crear un `work_plan.md` de
    prueba (fixture temporal, no el `work_plan.md` real del ticket) con
    `deliverable_type: mixed` y `## Builder` listando un archivo real que
    exista en el checkpoint git; confirmar `--validate --json` sin warning
    "No Files Likely Touched" y `--mark-ready` sin `--scope-override`
    (usando ese `work_plan.md` de prueba, restaurado despues a este mismo
    `work_plan.md` real antes de continuar).
  - `scripts/run_pytest_safe.py` (suite completa, stamp fresco sobre HEAD;
    level=all, exit_code=0).
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - `.agent/agent_controller.py --validate --json --project-root .`

## STOP conditions

- Si el fix anade `mixed` a `_DOC_DELIVERABLE_TYPES_CONGRUENCE` o modifica
  `_check_deliverable_type_file_congruence`: DETENTE, fuera de alcance y
  rompe la semantica inversa de ese guard.
- Si alguno de los tests nuevos NO falla al revertir el fix (mutation check
  ausente o mal ejecutado): DETENTE, el test es un placebo.
- Si algun test existente de los 4 archivos de test listados en Files Likely
  Touched, o de `TestDeliverableTypeFileCongruence` en
  `tests/test_agent_controller.py`, se rompe con el cambio: DETENTE, escala
  antes de forzar el test existente a pasar cambiando su asercion.
- Si el Builder cambia el default de cualquier parametro nuevo a un valor
  distinto de `"code"`, o hace que el fallback a `## Builder` se active para
  `deliverable_type="code"` sin `## Builder` declarado explicitamente:
  DETENTE y escala, ampliaria la superficie mas alla de lo aprobado.
- Si el Builder modifica la logica de namespaces (`### repo_motor`/
  `### repo_destino`) de `_parse_flt_section` mas alla de anadir el fallback
  a `## Builder`: DETENTE y escala.

## Non-goals

- NO anadir `mixed` a `_DOC_DELIVERABLE_TYPES_CONGRUENCE` ni cambiar
  `_check_deliverable_type_file_congruence` (`agent_controller.py`).
- NO cambiar el contrato de namespaces `### repo_motor`/`### repo_destino` de
  `## Files Likely Touched`.
- NO cambiar el comportamiento de `--validate`/`--mark-ready` para
  `deliverable_type="code"` sin `## Builder`.
- NO anadir un fallback incondicional (sin mirar `deliverable_type`) a
  `## Builder` cuando falta `## Files Likely Touched` (opcion de diseno
  descartada explicitamente).
- NO tocar `scripts/run_gates_dispatch.py`,
  `scripts/check_deliverables_exist.py` ni ningun otro script fuera de los
  archivos listados en Files Likely Touched.

## Riesgos

- Bajo: el fallback nuevo en `_parse_flt_section` podria, en teoria, capturar
  una seccion `## Builder` con contenido no destinado a scope gate para un
  ticket `mixed`, mitigado porque el mismo patron ya es el contrato
  establecido para `analysis`/`documentation`/`research` desde
  WOT-2026-009a, sin incidentes conocidos, y `mixed` es semanticamente el
  tipo mas cercano a "code" que ya puede mezclar entregables de codigo y de
  Builder-como-doc.
- Bajo: anadir un parametro con default a una funcion usada en 3 call-sites
  de `agent_controller.py` (ademas de los tests) podria introducir un typo en
  alguno de los 3 sitios, mitigado por los tests de regresion de PASO 4 que
  cubren `motor_checkpoint.parse_raw_flt_paths` directamente, y por el DoD
  Paso 3 que exige verificar los 5 tests existentes de
  `test_scope_gate_topology.py` sin cambios.
- Bajo: la linea 3636 de `agent_controller.py` necesita una lectura local
  nueva de `deliverable_type` (no reutiliza `_dt_ph`, que se define despues),
  mitigado porque `_read_deliverable_type` es pura y ya se llama 2 veces en
  otros puntos de este mismo archivo sin problema (confirmado por grep).

## Decision sobre REVIEW

Review 2 adversarial fresh-context NO obligatoria por regla generica de
blast-radius (cambio de parsing puro en 2 modulos de libreria + tests, sin
tocar CI/workflows ni logica de negocio del checkpoint mas alla de pasar un
parametro ya calculado). Recomendada como minimo que el Manager en review
re-ejecute el repro manual del DoD binario (crear el `work_plan.md` de prueba
mixed+Builder, correr `--validate` y `--mark-ready`) con sus propios ojos, y
revise el diff literal de `.agent/scope_gate.py` para confirmar que el
fallback respeta la prioridad de `## Files Likely Touched` sobre
`## Builder` en todos los casos.

## Criterios de Aceptacion Global (1:1 con el DoD binario de la ficha)

- [ ] Un `work_plan.md` `mixed` con `## Builder` valida 0/0 (sin warning "No
      Files Likely Touched section"), verificado con
      `.agent/agent_controller.py --validate --json --project-root .` sobre
      una fixture de prueba.
- [ ] `--mark-ready` de ese `work_plan.md` mixed pasa sin `--scope-override`
      (el checkpoint gate en `_handle_mark_ready` reconoce `## Builder` via
      `deliverable_type=_dt_mr` pasado a `_parse_raw_flt_paths`).
- [ ] MUTATION: revertir el fallback (PASO 1 + PASO 2/3) hace que reaparezcan
      el warning y el bloqueo, documentado con salida literal de pytest y/o
      del comando repro. Restaurar el fix hace que ambos desaparezcan de
      nuevo.
- [ ] Tests existentes de `scope_gate`/`motor_checkpoint` (los 5 de
      `test_scope_gate_topology.py` citados en el DoD Paso 3, mas
      `test_scope_gate.py`, `test_scope_gate_isolation.py`,
      `test_motor_checkpoint.py`, y `TestDeliverableTypeFileCongruence` en
      `tests/test_agent_controller.py`) siguen en verde sin cambios en su
      codigo.
- [ ] El contrato de superficies del `--validate` no cambia: `code` sin
      `## Builder` sigue emitiendo el mismo warning que antes; solo se alinea
      el parser para que `mixed` acepte `## Builder` igual que los doc-types.
- [ ] `ruff check`/`ruff format --check` exit 0 sobre los 6 archivos
      modificados.
- [ ] `scripts/run_pytest_safe.py` verde (stamp fresco sobre HEAD, level=all,
      exit_code=0).
- [ ] `agent_controller.py --validate --json --project-root .` exit 0/0 tras
      el cierre (sobre el `work_plan.md` real del ticket, no la fixture de
      prueba).
