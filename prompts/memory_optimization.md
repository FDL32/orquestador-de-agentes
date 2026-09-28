# Prompt: Optimizacion de memoria basada en evidencia (recolector -> juez)

> **Modo:** propone y (opcionalmente) aplica UN piloto de optimizacion del
> SISTEMA de memoria del motor (no de una leccion individual), guiado por
> EVIDENCIA medida contra el estado real de L1/L2/L3, con disciplina CEM:
> NUNCA relaja el schema, NUNCA borra observations sin gate de evidencia,
> NUNCA cambia el contrato de salida de `bus/memory_loader.py` sin declarar
> el cambio como tal.

contract_id: cid-memory-optimization-v1
Hermano de `prompts/suite_optimization.md` (mismo patron recolector->juez,
mismas dos condiciones duras del PASO 2, mismo formato de salida). Si
diverge de ese prompt en la FORMA del proceso (no en el contenido de
memoria), prevalece la forma ya validada en `suite_optimization.md`.

No confundir con `prompts/memory_upload.md` (GATE de promocion de UNA
leccion antes de escribirla) ni con `scripts/memory_consolidate.py`
(el MECANISMO que genera L2/L3 desde L1). Este prompt es el JUEZ que decide
SI y COMO afinar ese mecanismo -- no promueve lecciones, optimiza el
sistema que las sirve.

## Por que existe (a diferencia de "solo correr memory_consolidate.py")

`memory_consolidate.py --apply` regenera L2/L3 de forma determinista, pero
NO decide si el sistema en su conjunto necesita un cambio estructural:
subir/bajar `MAX_L2_RULES`, resolver el desfase entre lo que el bootstrap
lee (archive unido) y lo que L2 refleja (buffer local), o declarar que el
ratio de ruido en L1 exige una fase de limpieza antes de seguir
consolidando. Ese juicio es exactamente el que `suite_optimization.md` hace
para tests: leer evidencia, clasificar causa, elegir UN piloto medible.

---

## PASO 0: leer la evidencia (no la intuicion)

No hay un `run_history.jsonl` equivalente para memoria (medido 2026-09-28:
`grep -n "history" scripts/memory_consolidate.py` -> solo referencias a
`observations.jsonl` como historial, ningun fichero de corridas). El
disparador se basa en el ESTADO ACTUAL medido, no en tendencia entre
corridas -- declaralo explicitamente si alguna vez se acumula suficiente
historial para medir tendencia real.

Comandos de recoleccion (todos read-only, ejecutar contra `repo_motor` y
opcionalmente `repo_destino` si aplica):

```
wc -l .agent/runtime/memory/memory_rules.md
grep -c "^#### R-" .agent/runtime/memory/memory_rules.md
wc -l .agent/runtime/memory/observations.jsonl
python scripts/memory_consolidate.py --dry-run   # cuenta recent/archivable, noise descartado
python -c "from bus.memory_loader import get_memory_tier_status; print(get_memory_tier_status())"
```

Y para el archive portable (union motor+destino, la fuente que
`get_bootstrap_context` sirve de verdad):

```
find .agent/runtime/memory/archive -name "observations.*.jsonl" | xargs wc -l
```

---

## PASO 1: clasificar cada senal por CAUSA PROBABLE (no por su numero)

| Senal | Umbral disparador | Causa probable | Tratamiento |
|---|---|---|---|
| **L2 al tope** | reglas en `memory_rules.md` >= 90% de `MAX_L2_RULES` (scripts/memory_consolidate.py:46) | el corte por orden-de-lista empieza a expulsar reglas relevantes en silencio (Hallazgo C de PROPUESTA_20260928_rediseno_memoria.md) | Candidato a piloto: medir CUALES reglas se expulsarian en la proxima consolidacion (comparar `recent` con y sin `archivable`) antes de subir el tope a ciegas. |
| **Desfase bootstrap vs L2** | `get_bootstrap_context()` sirve N entradas del archive unido y `memory_rules.md` fue generado sin ese archive (verificar fecha de ultima consolidacion vs. fecha de ultima entrada del archive) | WOT-2026-058b: `_regenerate_l2_l3` proyecta solo desde `observations.jsonl` local, no desde el archive completo | **NO tocar sin resolver 058b primero** -- es deuda ya fichada, no un piloto nuevo de este prompt. |
| **Ratio de ruido en L1** | `noise` descartado por `is_noise()` (memory_consolidate.py) > 50% de las entradas totales de `observations.jsonl` | mayoria de L1 es telemetria de `post_tool_hook`, no lecciones reales (ya documentado: "80% de L1 es post_tool_hook") | Verificar si el ratio sigue esa magnitud o empeoro; si empeoro, candidato a ajustar el filtro `is_noise` (nunca a relajar el umbral de 30 chars sin medir falsos negativos). |
| **IDs R-XXX inestables** | una consolidacion reciente desplazo IDs ya citados en otro artefacto (prompt, skill, memoria) | asignacion posicional por `enumerate()` tras sort, sin tabla persistente (Hallazgo D) | Candidato a piloto SOLO si hay una cita real rota medida (no hipotetica) -- ver PASO 2 condicion (b). |
| **Fallback de `audience`/`wing` saturado** (si Fase 2 del rediseno ya esta implementada) | > 70% de entradas caen en "aplica a todos" tras inferencia por keywords | la heuristica de inferencia no discrimina lo suficiente | Candidato a afinar keywords de `_infer_wing`/`_infer_audience`, nunca a inventar un clasificador nuevo. |

---

## PASO 2: elegir el piloto -- las DOS condiciones DURAS

Un candidato solo es piloto valido si cumple AMBAS (identicas en espiritu a
`suite_optimization.md` PASO 2):

**(a) NO toca zona prohibida:** no relaja `validate_observations.py --strict`,
no cambia el schema de `observations.jsonl` sin migracion declarada, no
borra entradas del archive versionado sin gate de evidencia
(`check_portable_memory_promotion.py`), no reescribe `bus/memory_loader.py`
de forma que cambie su contrato de salida (formato markdown, topes por
consumidor) sin declararlo como cambio de contrato, no resuelve por su
cuenta una decision de producto ya pendiente (WOT-2026-025o, WOT-2026-042e)
-- esas son tickets propios, no piloto de este prompt.

**(b) El coste/riesgo es ELIMINABLE, no solo RE-ATRIBUIDO.** Ejemplo de
trampa (misma forma que TRAMPA-2 de `suite_optimization.md`): "reducir
`MAX_L2_RULES` de 30 a 20 para que quepa mas margen" no elimina el problema
de expulsion silenciosa, lo agrava -- mueve el corte, no lo resuelve.

Si el unico candidato real cae en zona prohibida O su coste no es
eliminable -> NO aplicar. Entregar una PROPUESTA fully-evidenced + abrir
follow-up ligado al ticket que corresponda (WOT-2026-058b, WOT-2026-042e,
etc. segun la Seccion 8 del anexo de PROPUESTA_20260928_rediseno_memoria.md).

---

## TRAMPAS VERIFICADAS (no re-descubrir)

### TRAMPA-1: un `MEMORY.md` desfasado no es "poca memoria", es "indice
desactualizado"
Medido: `MEMORY.md` del motor puede quedar semanas desfasado (2.310 bytes
del 11-jul frente a un corpus del 17-ago) porque `local_audit.py` lo lee
pero nada fuerza su regeneracion en cada sesion. Sintoma: "parece que hay
poca memoria" cuando en realidad el corpus crecio y el indice no se
regenero. Verificar SIEMPRE la fecha de `MEMORY.md` contra la fecha de la
entrada mas reciente del archive antes de diagnosticar "falta memoria".

### TRAMPA-2: `bus/memory_loader.py` no es un validador de schema
Es un loader TOLERANTE ("never raises", strings vacios ante JSON corrupto).
Si el disparador usa `get_memory_tier_status()` y sale limpio, eso NO
certifica que el schema este sano -- solo que los ficheros existen y son
legibles. La barrera real de schema es
`python scripts/validate_observations.py --strict` (exit 0 obligatorio
antes de fiarse de cualquier conteo de entradas).

---

## PASO 3: aplicar el piloto (si (a)+(b) se cumplen) CON before/after + guard

1. **Medir ANTES:** correr el comando de recoleccion relevante y registrar
   el numero real (p.ej. cuantas reglas se expulsarian en la proxima
   consolidacion, o el ratio de ruido real).
2. **Aplicar** el cambio minimo (ajustar un umbral con justificacion
   medida, afinar un filtro, anadir un campo opcional con fallback
   fail-open -- nunca un cambio de arquitectura completo en el mismo
   piloto).
3. **Medir DESPUES:** mismo comando; el numero debe mejorar de forma real,
   no solo desplazarse.
4. **GUARD anti-relajacion (obligatorio):** demostrar por mutation que el
   cambio no relaja una barrera existente -- p.ej., si se toca
   `is_noise()`, un test que confirma que telemetria real sigue
   descartandose tras el cambio.
5. Suite focal del modulo tocado (`tests/unit/test_memory_*.py` o
   equivalente) verde; no hace falta la suite `--level all` completa salvo
   que el cambio toque codigo compartido con otros consumidores.

Si NO hay piloto valido: documentar la propuesta con before/after ESTIMADO
y abrir el follow-up correspondiente. NO aplicar nada.

---

## Non-goals (duros)

- NO migra el archive ni decide WOT-2026-025o (Opcion A/B) -- eso es
  decision de producto, no piloto de optimizacion.
- NO implementa las Fases 1-3 del rediseno de memoria
  (PROPUESTA_20260928_rediseno_memoria.md) -- este prompt optimiza el
  sistema EXISTENTE, no construye el nuevo diseno.
- NO relaja `validate_observations.py --strict` para "que pase mas rapido".
- NO borra entradas de `observations.jsonl`/archive sin el gate de
  evidencia ya existente.
- NO cambia el contrato de salida de `get_bootstrap_context()`/
  `get_review_context()`/`get_compact_context()` (formato, topes) sin
  declararlo explicitamente como cambio de contrato, nunca como "piloto".

---

## Salida

- Un informe corto: evidencia (comandos + numeros reales de PASO 0),
  clasificacion por causa (tabla del PASO 1), el candidato elegido (o
  "ninguno aplicable" con razon), y -si se aplico- el before/after + el
  guard de no-relajacion.
- Si se aplico: el diff del piloto + la evidencia de mutation-guard.
- Si NO: la propuesta + el follow-up abierto (con ID de ticket si aplica).

## Restriccion dura

- SOLO propone/aplica UN piloto por corrida. No un sweep de todo el
  sistema de memoria a la vez.
- La evidencia manda sobre la intuicion. Sin `run_history.jsonl`
  equivalente, el disparador es sobre ESTADO ACTUAL medido, no tendencia --
  declararlo asi en cada corrida hasta que exista telemetria acumulada.
- Ante duda entre "eliminable" y "re-atribuido": es re-atribuido -> NO
  aplicar.
