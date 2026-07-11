# Prompt: Optimizacion de suite basada en evidencia (recolector -> juez)

> **Modo:** propone y (opcionalmente) aplica UN piloto de optimizacion de la
> suite de tests del motor, guiado por EVIDENCIA (run_history.jsonl + durations),
> con disciplina CEM: NUNCA mock-drift, NUNCA relajar asserts, NUNCA tocar
> barreras git reales salvo mejora de fixture demostrablemente segura.

contract_id: cid-suite-optimization-v1
Skill canonica: skills/suite-optimization/SKILL.md
source_of_truth: este prompt. La skill es wrapper operativo; si divergen,
prevalece este prompt.

Hereda la filosofia de `prompts/audit_agent_output.md` (CEM v0, evidencia antes
que relato) y la consigna adversarial de `prompts/manager_review.md` (intentar
tumbar la propia propuesta antes de aplicarla).

## Relacion con la telemetria (021t/021w)

- **WOT-2026-021t** inyecta `--durations=25` -> la tabla "slowest N durations"
  cae en `last-run.log` en cada corrida.
- **WOT-2026-021w** persiste cada corrida en
  `.agent/runtime/pytest-safe/run_history.jsonl` (counts, duracion, top-slowest,
  tested_commit_sha; fichero gitignored, schema PII-scrubbed).
- Este prompt es el JUEZ que LEE esa evidencia. **Recolector antes que juez:** no
  optimices a ciegas ni desde una atribucion de pytest; deriva el objetivo del
  run_history real.

---

## PASO 0: leer la evidencia (no la intuicion)

1. Leer las ultimas N corridas `--level all` de `run_history.jsonl` (filtrar las
   parciales: `passed`/`duration_s` no None y `top_slowest` no vacio; una corrida
   focal `-k` o un dry-run NO tiene tabla de durations). Usar la corrida
   COMPLETA mas reciente como base.
2. Ordenar `top_slowest` por segundos. Anotar `phase` (setup/call/teardown) y
   `nodeid` de cada fila.
3. Anotar la duracion total y el conteo (para medir el % que cada candidato
   representa del wall-clock).

---

## PASO 1: clasificar cada lento por CAUSA PROBABLE (no por su numero)

Para cada fila del top-slowest, clasificar la CAUSA. Las categorias y su
tratamiento:

| Categoria | Senal | Tratamiento |
|---|---|---|
| **teardown-de-atribucion** | `phase == teardown` en un test cuyo cuerpo AISLADO es rapido; el coste real es de un fixture session-scoped que pytest imputa al ultimo test que lo toco | **NO es un test lento.** Re-derivar el objetivo real; el coste vive en el fixture, no en el test. Ver la TRAMPA-1 abajo. |
| **git-real (plumbing)** | el test construye repos git efimeros REALES (init/clone/rebase/squash/revert) para validar un CONTRATO de git | **NO tocar** (non-goal). Es coste genuino que la barrera exige. Mockear = mock-drift que mata la barrera. |
| **IO-de-arbol-real** | el test escanea/lee el arbol real del proyecto | Verificar si un fixture MAS PEQUENO da la misma cobertura SIN perder la senal de "arbol real". Si la cobertura del arbol real es el punto, NO tocar. |
| **fixture-heavy** | el coste esta en setup/fixtures compartibles y el AISLAMIENTO lo permite (los tests no se contaminan si comparten el estado) | Candidato a subir el scope del fixture (function -> module/session) SOLO si ningun test muta el estado compartido. |
| **subprocess-spawn** | muchos spawns secuenciales de subprocesos (git, python) | Verificar si son combinables SIN cambiar el contrato; normalmente NO lo son (cada uno prueba un caso). |

---

## PASO 2: elegir el piloto -- las DOS condiciones DURAS

Un candidato solo es piloto valido si cumple AMBAS:

**(a) NO toca zona prohibida:** ni sandbox/hermeticidad (familia 021k/020p, con
diseno abierto), ni git-plumbing que valida contrato real, ni relaja un assert,
ni introduce mock-drift.

**(b) El coste es ELIMINABLE, no solo RE-ATRIBUIDO.** Esta es la trampa capital.
Antes de proponer, PRUEBA que el cambio hace DESAPARECER el coste, no que lo
MUEVE a otro sitio. Un coste que solo cambia de lugar es 0s de ahorro con riesgo
neto positivo.

Si el unico candidato real cae en zona prohibida O su coste no es eliminable
-> NO aplicar. Entregar una PROPUESTA fully-evidenced + abrir follow-up ligado a
la familia que corresponda (021k/020p para sandbox). Un metodo honesto que
concluye "los cuellos actuales son coste genuino o requieren sesion dedicada" es
un RESULTADO valido, no un ticket vacio.

---

## TRAMPAS VERIFICADAS (aprendizajes con evidencia; no re-descubrir)

### TRAMPA-1: la atribucion de pytest miente (teardown session-scoped)
El "teardown de ~5.8-7.58s" que pytest imputa a
`test_work_plan_schema.py::test_deliverable_type_with_extra_spaces` NO es un test
lento: es el teardown del fixture session-scoped autouse
`_project_temp_environment` (tests/conftest.py) que borra los cientos de dirs de
fixtures git acumulados al final de la sesion; pytest lo imputa al ULTIMO test
que toco el fixture. Ese fichero AISLADO da teardown 0.03s.
[EVIDENCIA: WOT-2026-021t closeout + backlog 021x l.480]. **Re-derivar el
objetivo del run_history, NUNCA de esta atribucion.**

### TRAMPA-2: "duplicado" != "redundante" != "optimizable" (coste que se mueve)
`_rmtree_robust(SESSION_RUNTIME_ROOT)` se llama DOS veces: en el teardown del
fixture (`tests/conftest.py`, tras restaurar tempdir) y en `pytest_sessionfinish`.
Parece "redundante -> quitar una". **ES FALSO:** el coste (~5.8s) es BORRAR
cientos de dirs, y ocurre UNA sola vez estes donde estes. Si quitas la 1a
llamada, la 2a encuentra el arbol y borra los mismos dirs -> mismo coste, 0s de
ahorro, y ADEMAS pierdes el defense-in-depth (la 2a es el backup si la 1a falla;
ambas anotadas WOT-2026-013i). **REGLA: antes de llamar "redundante" a una
operacion duplicada, PRUEBA que el trabajo desaparece, no que la LLAMADA se
mueve. Coste = trabajo hecho, no numero de call-sites.**
[EVIDENCIA: refutacion adversarial verificada 2026-07-11, sesion cadena 021w/x].

---

## PASO 3: aplicar el piloto (si (a)+(b) se cumplen) CON before/after + guard

Si hay un piloto valido:

1. **Medir ANTES:** correr el/los test(s) focal(es) aislados y registrar el tiempo
   real (no la atribucion). `run_pytest_safe.py <focal>` o
   `python -m pytest <nodeid> --durations=0 -p no:cacheprovider`.
2. **Aplicar** el cambio minimo (subir scope de fixture, eliminar trabajo
   REALMENTE redundante, etc.).
3. **Medir DESPUES:** mismo comando; el tiempo debe BAJAR de forma real.
4. **GUARD anti-relajacion (obligatorio):** demostrar por MUTATION que el
   contrato del test optimizado NO se relajo -- romper el codigo que el test
   cubre debe seguir rompiendo el test. Un test mas rapido que ya no falla ante
   el bug que cubria es una REGRESION disfrazada de optimizacion.
5. **Suite completa** `--level all` verde (leer "N passed/failed", no el exit del
   wrapper) para confirmar 0 regresion + 0 nuevo flaky.

Si NO hay piloto valido: documentar la propuesta con before/after ESTIMADO y el
guard que haria falta, y abrir el follow-up. NO aplicar nada.

---

## Non-goals (duros)

- NO activar `xdist --level all` (es la familia 020p, sesion dedicada).
- NO reescribir la suite entera.
- NO mockear tests de git plumbing que validan contrato real.
- NO relajar asserts ni bajar umbrales para "ir mas rapido".
- NO tocar el sandbox/hermeticidad de tests (familia 021k/020p) sin su sesion.

---

## Salida

- Un informe corto: evidencia (top-slowest de run_history), clasificacion por
  causa, el candidato elegido (o "ninguno aplicable" con razon), y -si se
  aplico- el before/after + el guard de no-relajacion.
- Si se aplico: el diff del piloto + la evidencia de mutation-guard.
- Si NO: la propuesta + el follow-up abierto (con ID de familia).

## Restriccion dura

- SOLO propone/aplica UN piloto por corrida. No un sweep.
- La evidencia manda sobre la intuicion y sobre la atribucion de pytest.
- Ante duda entre "eliminable" y "re-atribuido": es re-atribuido -> NO aplicar.
