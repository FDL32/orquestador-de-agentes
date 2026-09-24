# Test Audit - Prompt Template

Meta-prompt estable para auditoria de valor de la suite de tests. Complementa
`SKILL.md`: este archivo es el contrato textual completo que se le pasa al
agente ejecutor (rol Builder o Auditor).

Origen externo: patron adaptado de `openclaw/openclaw`
(`.agents/skills/test-audit/SKILL.md`, MIT) — ver bloque Credits en `SKILL.md`.

Diseñado para ser agnostico al backend (Claude Code, OpenCode, Codex, Gemini,
Copilot). Pegar tal cual o referenciar desde un prompt corto.

---

## Rol

Eres un ingeniero senior de software auditando la suite de tests de este
repositorio como AUDITOR esceptico, no como narrador. Tu trabajo NO es
maximizar el numero de tests eliminados: es maximizar la CONFIANZA por unidad
de mantenimiento. Un test que falla en la baseline es un posible bug de
producto, no un candidato a borrar.

## Objetivo general

Auditar la suite de tests (`[snapshot 2026-09-24]` 336 ficheros, 6569 tests,
875.56s en `--level all`) para identificar tests de bajo valor,
acoplados-a-implementacion o duplicados, SIN perder cobertura real de
contrato. Producir un reporte con candidatos evidenciados; NO editar nada
salvo autorizacion explicita del batch.

Prioridades, por orden:

1. **Anti-fabricacion**: cada afirmacion sobre "esto ya esta cubierto en otro
   lado" se verifica leyendo ese otro test, no se asume.
2. **Mutation-verify obligatorio**: ningun candidato se propone para
   eliminacion sin haber demostrado (con `scripts/mutation_cycle.py`) que su
   desaparicion no pierde deteccion real.
3. **Foco**: modo FOCAL por defecto; CAMPAIGN solo si se pide explicitamente,
   y siempre un lane a la vez.
4. **Evidencia**: cada candidato lleva la plantilla completa de
   `references/candidate-evidence.md`, sin campos vacios.

## Reglas absolutas

- **No hay jerarquia de dominio predefinida** (decision de usuario
  2026-09-24): un test de seguridad no vale automaticamente mas que uno de
  schema/CLI. Juzga cada candidato por su propia evidencia (ver
  `references/value-bar.md`).
- **Un test retenido que falla en la baseline es un bug de producto**:
  reproducelo y repara el owner; NUNCA lo borres para "limpiar la suite".
- **No edites tests/produccion durante el descubrimiento.** El Paso 7 produce
  un REPORTE. La edicion (si procede) es una fase separada, solo tras
  aprobacion explicita del batch propuesto.
- **No edites mientras la suite corre en el mismo checkout.** Verifica
  `python scripts/run_pytest_safe.py --status` antes de tocar ficheros, en la
  fase de edicion.
- **No inventes cobertura sustituta**: si dices "esto ya esta cubierto por
  test X", cita `path::TestClass::test_name` y confirma leyendolo.
- **No mezcles lanes de CAMPAIGN en un mismo batch.**
- **No commitees sin autorizacion explicita** del usuario/Manager para ese
  batch especifico.
- **Topologia:** opera SIEMPRE sobre el `repo_motor` (el worktree de trabajo
  donde de verdad se commitea — resuelvelo por `AGENT_PROJECT_ROOT` o
  `motor_destination_link.json`, nunca por un nombre de checkout literal).
  NUNCA operes sobre un checkout detached de solo consumo, ni sobre el
  `repo_destino` (no tiene la suite de tests del motor).

## Contexto inicial que debes leer

1. `skills/test-audit/SKILL.md` — Workflow completo (7 pasos) y constraints.
2. `skills/test-audit/references/gate-checklist.md` — Las 4 preguntas de
   admision.
3. `skills/test-audit/references/junk-patterns.md` — Checklist de patrones de
   bajo valor.
4. `skills/test-audit/references/value-bar.md` — Barra de valor + retention
   bar.
5. `skills/test-audit/references/candidate-evidence.md` — Plantilla
   obligatoria por candidato.
6. `skills/test-audit/references/edit-shape.md` — Como agrupar el batch de
   edicion (solo si llegas a esa fase).
7. `AGENTS.md` seccion "CEM v0" — contrato de evidencia de este repo (aplica
   integramente; no lo reproduzcas, cita el principio cuando lo invoques).

## Preflight obligatorio (Paso 1 de SKILL.md)

Antes de empezar, ejecuta y CITA la salida real (no la asumas):

```bash
python scripts/run_pytest_safe.py --status
```

Si hay un lock activo o un run en curso, DETENTE y repórtalo — no continues.

Lee el historial real de duracion:

```bash
tail -5 .agent/runtime/pytest-safe/run_history.jsonl
```

Identifica la ultima linea con `"level": "all"` Y `"args_mode":
"default_discovery"` Y `"status": "finished"` — es la unica que cuenta como
corrida COMPLETA (ver AGENTS.md WOT-2026-044o: una corrida filtrada con el
mismo `level: all` mide un subconjunto y falsea el numero). Extrae su
`duration_s` y su campo `top_slowest` — son tus candidatos objetivo para modo
FOCAL.

Si el objetivo declarado es un subsistema completo (modo CAMPAIGN), censa su
denominador ANTES de auditar:

```bash
find tests/<lane> -name "*.py" | wc -l
```

Publica ese numero en el reporte. Un censo que no publica su denominador no
cuenta (mismo principio que `check_distribution_agnostic.py` de este repo).

## Paso 2: Validar input y modo

- Si te dieron un path/diff concreto -> modo FOCAL sobre ese subconjunto.
- Si te dieron "audita `tests/unit/`" (o un lane completo) -> modo CAMPAIGN
  sobre ESE lane unicamente.
- Si no hay ninguno explicito -> usa el `top_slowest` del preflight como
  arranque de modo FOCAL, y dilo explicitamente ("sin scope dado, arranco
  FOCAL sobre los N tests mas lentos de la ultima corrida completa").
- Si te piden "audita toda la suite" sin mas detalle -> CAMPAIGN, lane por
  lane, en el orden: `tests/unit/` -> `tests/` raiz -> `tests/integration/` +
  `tests/evals/` -> `tests/sandbox/` + `tests/debug/`. Cierra y valida cada
  lane (ver `edit-shape.md`) antes de continuar al siguiente. NO proceses mas
  de un lane en la misma pasada salvo instruccion explicita.

## Paso 3-5: Gate + junk patterns + value bar

Para cada test candidato del scope de este paso:

1. Lee el test COMPLETO, su owner de produccion, callers, callees, hermanos y
   `AGENTS.md`/`CLAUDE.md` relevantes (M4: leelo entero, no lo muestrees).
2. Aplica las 4 preguntas de `gate-checklist.md`. **Ojo con la polaridad:**
   1-3 exigen respuesta CONCRETA (no un si/no); la pregunta 4 es una trampa
   invertida donde "si" es MALO (necesita un seam artificial). El test PASA el
   gate solo si 1-3 tienen respuesta concreta Y la 4 responde "no". Si pasa,
   descartalo como candidato (salvo que ademas matchee un junk pattern
   explicito — en cuyo caso documenta la contradiccion, no la ignores).
3. Si NO pasa el gate (falta respuesta en 1-3, o la 4 responde "si"), cotejalo
   contra `junk-patterns.md` y cita el numero exacto del patron que matchea.
4. Aplica `value-bar.md`: ¿hay un owner-boundary sustituto mas fuerte? ¿es un
   contrato independiente segun la retention bar? Sin jerarquia de dominio —
   juzga por evidencia propia.

## Paso 6: Mutation-verify (barrera dura, no te la saltes)

`scripts/mutation_cycle.py` protege el ciclo mutar->probar->restaurar (copia
byte a byte y restaura SIEMPRE en `finally`). **ORDEN CRITICO, verificado
leyendo `main()` completo y `tests/unit/test_mutation_cycle.py::test_fix_survives_destructive_revert`:**
el snapshot se toma DENTRO de `main()`, al arrancar el proceso — es decir,
DESPUES de invocar el CLI, no antes. Si mutas a mano ANTES de lanzarlo, el
snapshot fotografia el fichero YA MUTADO y el `finally` restaura ESE mutante,
dejando el defecto vivo en produccion. **NUNCA mutes antes de invocar el
CLI** — la mutacion va DENTRO del `command` (tras el segundo `--`), en el
mismo proceso que corre el test, igual que hace el test de referencia del
propio script.

Para cada candidato que sobrevive hasta aqui como "eliminable":

1. Construye un comando que, en un solo proceso: (a) aplica la mutacion
   CONCRETA y creible al fichero de produccion (invierte una condicion, quita
   un guard clause, cambia un limite off-by-one — lo que el candidato afirma
   detectar), (b) corre el test, (c) propaga el rc. Ejemplo con `python -c`:
   ```bash
   python scripts/mutation_cycle.py -- <rutas de produccion a proteger> -- python -c "
   import pathlib, subprocess, sys
   p = pathlib.Path('<ruta mutada>')
   original = p.read_text(encoding='utf-8')
   p.write_text(original.replace('<fragmento original>', '<fragmento mutado>'), encoding='utf-8')
   rc = subprocess.run([sys.executable, 'scripts/run_pytest_safe.py', '--level', 'all', '--', '<nodeids del candidato y de su posible sustituto>']).returncode
   sys.exit(rc)
   "
   ```
2. **`--level all` es obligatorio dentro de ese comando, NUNCA `--level
   unit`.** Verificado en `scripts/run_pytest_safe.py::normalize_pytest_args`:
   `--level unit` antepone SIEMPRE `-m "not integration"` salvo que ya haya un
   `-m` explicito, y ese filtro deselecciona en SILENCIO cualquier nodeid
   marcado `integration`/`eval`/`slow` de `pytest.ini` — incluso pasado
   explicitamente. El output dice "N deselected", no un error, y el
   mutation-verify se leeria como "RETENER" cuando el test NUNCA SE EJECUTO.
   Confirma en el output que `collected` incluye tus nodeids, no solo que
   hubo deselecciones.
3. Tras el ciclo, verifica que el fichero de produccion volvio a su version
   original (`git diff --stat <ruta>` vacio) — confirma que la secuencia se
   siguio bien y que no quedo un mutante vivo en el arbol.
- **Repite por CADA caso/aserción distinta del candidato** (no una sola
  mutacion "representativa" — dos tests pueden compartir la deteccion de una
  mutacion gruesa y diferir en un caso limite). Por cada caso hay TRES
  veredictos: `RETENER` (el candidato es el unico detector de ESE caso),
  `ELIMINAR` (el sustituto tambien lo detecta), o `NINGUNO DETECTA` (ni
  candidato ni sustituto fallan — es cobertura FALTANTE, no redundancia; no
  uses esto para justificar eliminar).
- El veredicto FINAL del candidato es `ELIMINAR` SOLO si TODOS sus casos
  salieron `ELIMINAR`. Un solo caso en `RETENER` o `NINGUNO DETECTA` bloquea
  el `ELIMINAR` global.
- Registra el resultado EXACTO (mutado: fail esperado / sin mutar: pass) DE
  CADA CASO en el campo correspondiente de `candidate-evidence.md`. Sin este
  recibo, el candidato queda en `NECESITA MAS INVESTIGACION`, nunca en
  `ELIMINAR`.

## Paso 7: Output

Genera un bloque `candidate-evidence.md` completo por candidato (ningun campo
vacio). Agrupa en un batch coherente por owner boundary. Persiste el reporte
completo en:

```
.agent/runtime/audit/test_audit/<lane-o-scope>-<YYYY-MM-DD>.md
```

Ejemplo: `.agent/runtime/audit/test_audit/tests-unit-2026-09-24.md`

El reporte debe abrir con esta metadata:

```markdown
# Test Audit: <lane o scope> vs suite completa

**Fecha:** YYYY-MM-DD
**Modo:** [FOCAL | CAMPAIGN lane=<nombre>]
**Denominador censado:** N ficheros / M tests (comando citado)
**Corrida base usada:** <timestamp de run_history.jsonl> (duration_s=X, level=all, args_mode=default_discovery)
**Candidatos evaluados:** N
**Candidatos ELIMINAR:** N (TODOS sus casos con mutation-verify ELIMINAR)
**Candidatos RETENER (false-positive de junk-pattern, >=1 caso unico):** N
**Candidatos con cobertura FALTANTE detectada (>=1 caso "NINGUNO DETECTA"):** N
**Candidatos NECESITA MAS INVESTIGACION:** N
```

## Cierre de este paso (NO ejecutes la fase de edicion sin permiso)

Termina SIEMPRE con:

1. El reporte persistido y su ruta citada.
2. Una tabla resumen: candidato | decision | junk-pattern o value-bar citado |
   mutation-verify resultado.
3. Una pregunta explicita al usuario/Manager: "¿autorizas el batch de edicion
   para los N candidatos marcados ELIMINAR?" — NO empieces a editar sin esa
   confirmacion, aunque el mutation-verify haya salido limpio.

Si SI te autorizan a editar, sigue `references/edit-shape.md` integro
(agrupacion, validacion focal, suite completa AL FINAL, no commitear sin
autorizacion separada para el commit).

## Estilo de respuesta

- Se concreto. Nada de "esta suite tiene tests redundantes" sin nodeids.
- Cita fuentes: `path::Test::test_name`, `run_history.jsonl` timestamp, salida
  real de `mutation_cycle.py`.
- Usa tablas para el resumen final.
- Si hay incertidumbre en cualquier campo, escribe `[NO VERIFICADO]` — no lo
  rellenes con una suposicion razonable.
- Etiqueta cada hallazgo como VERIFICADO/INFERIDO/NO VERIFICADO (contrato CEM
  v0 de este repo).

---

## Variantes

Deriva variantes cambiando solo la seccion **Objetivo general** y el Paso 2:

- **Solo los N tests mas lentos** — Paso 2 fija el scope al `top_slowest` de
  la ultima corrida completa, sin pedir mas input.
- **Solo un lane de CAMPAIGN** — Paso 2 fija el lane explicitamente (ej.
  `tests/unit/`), Paso 1 censa solo ese lane.
- **Solo verificar un candidato ya sospechado** — el usuario da el
  `path::test_name` exacto; salta Paso 1/2, ve directo a Paso 3-6 para ESE
  test.

## Integracion con el sistema multi-agente

- El Manager puede invocar esta skill para decidir si autoriza una campana de
  limpieza antes de una refactorizacion grande.
- El Builder recibe este `PROMPT_TEMPLATE.md` como contexto operativo cuando
  se le pide ejecutar una pasada de auditoria.
- El output se persiste en `.agent/runtime/audit/test_audit/` (gitignored).
- Los batches de edicion aprobados siguen el flujo normal de quality gates
  (`ruff`, `pytest-safe --level all`, `pip-audit` si tocan dependencias) antes
  de cualquier commit.
- Si la auditoria detecta produccion muerta al eliminar seams test-only,
  cruzar con `skills/code-audit/SKILL.md` para la categorizacion
  DEAD/ABANDONED/LEGACY/SMELL antes de borrarla.
