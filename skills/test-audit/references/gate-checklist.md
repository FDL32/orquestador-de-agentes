# Gate Checklist — 4 preguntas de admision, en dos modos

Adaptado de `openclaw/openclaw`. Uso dual:

- **Modo escritura** (preventivo): antes de anadir cualquier test nuevo,
  responder las 4 preguntas. Una respuesta faltante significa NO anadirlo
  todavia.
- **Modo auditoria** (retroactivo, Paso 3 de `SKILL.md`): para cada test
  EXISTENTE candidato, responder las mismas 4 preguntas COMO SI se fuera a
  escribir hoy. Si NO respondería "si" a las 4, es candidato a eliminacion —
  pasa a `junk-patterns.md` y `value-bar.md`.

## Las 4 preguntas

**Polaridad de cada pregunta (leela ANTES de aplicar el gate en `SKILL.md`
Paso 3 / `PROMPT_TEMPLATE.md`): las preguntas 1-3 piden una EXPLICACION
verificable, no un si/no; la pregunta 4 es la UNICA que es una trampa
booleana, y su respuesta deseable es "NO".** Un test "pasa el gate" cuando: 1,
2 y 3 tienen respuesta CONCRETA y verificable (no ausente, no vaga), Y la
pregunta 4 responde "no" (no necesita un seam artificial). Si CUALQUIERA de
1-3 no tiene respuesta concreta, o la pregunta 4 responde "si", el test es
candidato a revisar contra `junk-patterns.md`/`value-bar.md`.

1. **¿Que comportamiento observable, invariante o contrato independiente
   protege?** (exige respuesta CONCRETA, no si/no)
   - Respuesta valida: cita el contrato exacto (ej. "el schema de
     `work_plan.md` acepta `deliverable_type` en {code, mixed, documentation,
     research, analysis} y rechaza cualquier otro valor").
   - Respuesta invalida (= no pasa el gate): "prueba la funcion X" (eso es
     implementacion, no comportamiento), o ninguna respuesta identificable.

2. **¿Que regresion creible hace que falle?** (exige respuesta CONCRETA)
   - Debe poder describirse un cambio de codigo CONCRETO que rompa el test.
     Si no se puede imaginar un cambio real que lo rompa sin ser una
     refactorizacion cosmetica, el test no esta protegiendo nada (= no pasa el
     gate).

3. **¿Por que la cobertura existente NO detecta ya ese fallo?** (exige
   respuesta CONCRETA)
   - Cada contrato tiene UN owner primario en la frontera mas fuerte donde se
     puede probar. Otra capa solo necesita su propio test si cubre un riesgo
     INDEPENDIENTE (ej. un fallo de transporte o de lifecycle que el owner no
     puede alcanzar desde su posicion).
   - Preferir extender un caso table-driven o un fixture compartido antes que
     anadir un test casi-duplicado; si hace falta, consolidar el setup
     duplicado en el mismo cambio.
   - Si no hay razon independiente (ya existe un owner que cubre exactamente
     esto): no pasa el gate — es duplicado.

4. **¿Necesita un seam de produccion (export, flag, wrapper, hook de
   inyeccion) que ningun caller de produccion necesita?** (pregunta INVERTIDA:
   la respuesta DESEABLE es "NO")
   - Si la respuesta es **SI**: NO pasa el gate. Mueve el test al boundary
     real en vez de crear el seam — un seam que solo existe para el test es
     deuda, no infraestructura.
   - Si la respuesta es **NO** (el test ejercita un boundary que produccion ya
     necesita por si misma): esta pregunta esta satisfecha.

## Regla de refactor-preservante

Un test que se rompe bajo una refactorizacion que preserva el comportamiento
esta aseverando IMPLEMENTACION, no comportamiento. Hay que reescribirlo en el
boundary correcto antes de aterrizarlo (modo escritura) o antes de contarlo
como retenido (modo auditoria).

## Tests de regresion de bug (caso especial)

- Un test de regresion de bug DEBE fallar en el codigo PRE-fix por la razon
  correcta, y pasar tras la reparacion en el owner real.
- Un test de regresion que nunca demostrablemente fallo prueba el mock, no el
  fix. Verificalo: revierte temporalmente el fix (o usa `mutation_cycle.py`
  sobre el owner) y confirma que el test cae con el mensaje esperado, no con
  un error distinto.
- Una sola regresion en el boundary owner cubre el bug. No repliques el mismo
  escenario en cada capa que el bug atraviesa (ver AGENTS.md: "una superficie
  acotada, no una familia").

## Aplicacion a este repo

Ejemplo real de fallo capturado por esta misma regla: `WOT-2026-039l`
(mutation-verify tautologico, ver `CHANGELOG`/commit `cd62081`). El
mutation-verify original comparaba el resultado MUTADO contra el mismo valor
esperado SIN mutar — es decir, la pregunta 2 ("¿que regresion creible hace que
falle?") no tenia respuesta real: ninguna mutacion lo habria hecho fallar. Se
corrigio con un fixture donde la produccion y la mutacion SI divergen
observablemente.
