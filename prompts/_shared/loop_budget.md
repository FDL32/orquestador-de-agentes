# Loop Budget Template (cid-loop-readiness-v0, condicion #3)

> Template canonico de presupuesto declarativo por pipeline.
> El campo max_iterations es OBLIGATORIO para que la condicion #3 del gate
> loop-readiness (cid-loop-readiness-v0) sea TRUE.
> Fuente: WOT-2026-014u. Origen externo: cobusgreyling/loop-engineering.

---

## Campos obligatorios

```
max_iterations: <entero>
```
OBLIGATORIO. Entero positivo. Tope de iteraciones para el pipeline.
Debe estar declarado en el INPUT del gate antes de arrancar /goal.
El evaluador NO estima ni calcula este valor en runtime.
Ejemplo: `max_iterations: 50`

```
token_budget_estimated: <entero o null>
```
OBLIGATORIO (puede ser null solo si cost_mode es measured).
Estimacion del total de tokens por pipeline completo.
Si cost_source=measured en todos los entries del run-log, puede ser null.
Si cost_source=estimated en alguna entrada, debe ser un entero.
Ejemplo: `token_budget_estimated: 200000`

```
cost_mode: estimated | measured
```
OBLIGATORIO. Modo de calculo del presupuesto.
- `estimated`: los tokens del run-log usan cost_source=estimated (metodo de
  estimacion declarado en notes de cada entrada).
- `measured`: los tokens del run-log usan cost_source=measured (dato real
  del harness o API de la plataforma LLM).
PROHIBIDO mezclar sin etiqueta explicita en notes.
Ejemplo: `cost_mode: estimated`

```
notes: <texto libre>
```
OPCIONAL. Notas sobre como calibrar el presupuesto usando datos del
run-log anterior (ver loop_run_log.md).

---

## Ejemplo completo

```yaml
max_iterations: 50
token_budget_estimated: 200000
cost_mode: estimated
notes: |
  Calibrado con el promedio de las ultimas 3 ejecuciones.
  Si cost_per_accepted_change supera 10000 tokens por cambio, revisar
  el scope del pipeline antes de la proxima ejecucion.
```

---

## Interpretacion como orden de magnitud

Cuando cost_mode es estimated, todos los valores del run-log son aproximaciones.
Interpretarlos como ordenes de magnitud, no como valores exactos. La precision
mejora cuando cost_mode cambia a measured con datos reales del harness.

El campo token_budget_estimated sirve como TECHO operativo: si el run-log
acumula tokens > token_budget_estimated, el pipeline debe detenerse y escalar
al Manager antes de continuar.

---

## Relacion con el gate loop-readiness

La condicion #3 del gate cid-loop-readiness-v0 exige:

  El work_plan declara un ENTERO como tope de iteraciones o tokens.
  El ENTERO debe estar declarado en el INPUT del gate.
  El evaluador NO estima ni calcula el presupuesto en runtime.

Este template provee el campo max_iterations que satisface esa condicion.
Sin este campo declarado como entero en el input del gate, la condicion #3
es FALSE y la tarea NO es loop-ready.

Para calibrar el valor de max_iterations, consultar el run-log del pipeline
anterior (ver loop_run_log.md, campo iteration_index final).
