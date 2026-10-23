# Propuesta: anadir `prompts/doc_optimization.md` a `MANIFEST.distribute` (2026-10-23)

> Origen: el usuario pidio que los repos destino puedan aprovechar el METODO (no el
> contenido especifico) usado esta sesion para optimizar `AGENTS.md`. Verificado: el metodo
> vive en `prompts/doc_optimization.md` + la skill `/doc-optimization` (ya viaja completa,
> `skills/` es un bloque integro en `MANIFEST.distribute`), pero el PROMPT que la skill cita
> como `source_of_truth` no viaja.

## Errores encontrados en esta pasada (antes del bucle)

1. **Hipotesis inicial descartada: "falso negativo del guard por nombre de campo
   equivocado".** Al ver que `check_distribution_boundary.py --skill-citations` daba OK pese
   a que `prompts/doc_optimization.md` no esta en el manifiesto, supuse que el guard no
   encontraba el campo `source_prompt` en el frontmatter de `skills/doc-optimization/SKILL.md`.
   FALSO: el campo SI esta (`source_prompt: prompts/doc_optimization.md`, linea 12 del
   SKILL.md) y el guard SI lo escanea (`_NORMATIVE_KEYS = ("source_prompt", "source_of_truth")`).
   La razon real es otra, mas favorable: es una **deuda YA CONGELADA Y DECLARADA**
   (`_FROZEN_DEBT` en `scripts/check_distribution_boundary.py`, ticket WOT-2026-043b, 14 de 19
   citas normativas vivas en 2026-10-07), con su propio ticket de resolucion ya abierto
   (WOT-2026-043c) y su criterio de cierre YA escrito en el codigo: *"el prompt entra en
   MANIFEST.distribute O la skill deja de citarlo"*. No es un hallazgo nuevo: es cerrar una
   entrada de una lista que ya existia.
2. **Plan inicial sobredimensionado: anadir 6-7 scripts ademas del prompt.** Verificado con
   `grep -n "measure_agents_md_units\|build_llms\|check_cuspide\|check_reference_keys\|
   check_distribution_boundary\|check_encoding_guard" prompts/doc_optimization.md
   skills/doc-optimization/SKILL.md` -> **CERO coincidencias**. El protocolo canonico NO
   nombra ninguno de esos scripts: su PASO 1 mide con `wc -c` (texto llano, sin script
   dedicado) y es deliberadamente agnostico de herramienta. `measure_agents_md_units.py` es
   un acelerador que yo use esta sesion para no hacer `wc -c` a mano repetidamente, NO un
   requisito del protocolo. Anadir los 6-7 scripts habria sido sobre-alcance: el destino puede
   seguir el protocolo ENTERO con solo el prompt, igual que exige su propio PASO 1.

## Diagnostico corregido

El UNICO gap real para que un destino pueda ejecutar `/doc-optimization` sobre su propio
`AGENTS.md`/`CLAUDE.md` es: `prompts/doc_optimization.md` no esta en `MANIFEST.distribute`.
Esto SOLO importa en modo instalacion standalone/bundled (sin enlace externo vivo al motor);
en el modo que usa esta sesion (repo_motor + repo_destino via `AGENT_PROJECT_ROOT`), el
destino ya lee el prompt en vivo desde el checkout del motor sin necesitar que viaje.

**Alcance declarado (hallazgo codex, bucle 2026-10-23):** esta propuesta corrige el CONTRATO de
distribucion para el modo standalone/bundled; NO demuestra ni cambia nada sobre el bootstrap
externo via `AGENT_PROJECT_ROOT`, que ya funciona hoy sin esta entrada.

**Referencias en prosa del propio prompt, verificadas (hallazgo codex, confirmado con grep):**
`prompts/doc_optimization.md` menciona `prompts/suite_optimization.md` ("su hermano") y un
expediente de evidencia en `.agent/planning/research_context_budget/` -- ninguno de los dos
viaja hoy. NO son dependencias normativas: el propio prompt declara explicitamente **"No hace
falta leer ninguno de los dos para ejecutar este protocolo"** (linea ~31-32). Encajan en la
categoria "mencion en prosa" que `check_distribution_boundary.py --skill-citations` ya trata
como WARN, nunca ERROR -- no generan una cadena nueva de deuda bloqueante.

## Propuesta

Anadir UNA linea a `MANIFEST.distribute`, seccion "PROMPTS OPERATIVOS...", orden alfabetico:

    prompts/doc_optimization.md

Esto resuelve la entrada `("skills/doc-optimization/SKILL.md", "prompts/doc_optimization.md")`
de `_FROZEN_DEBT` en `scripts/check_distribution_boundary.py` por la via (1) del criterio ya
escrito (prompt entra en el manifiesto). Tras aplicar, esa entrada debe ELIMINARSE de
`_FROZEN_DEBT` -- el propio guard lo exige: *"Una entrada que deja de producir una violacion
es STALE y falla tambien"* (ver docstring de `_FROZEN_DEBT`, cita exacta en el codigo).

## Non-goals (declarados)

- NO toca las otras 13 entradas de `_FROZEN_DEBT` (`audit_autonomous_ticket_batch.md`,
  `backlog_admit.md`, etc.) -- son deuda independiente, cada una con su propia decision de
  "prompt entra o skill deja de citar"; resolverlas todas es el alcance COMPLETO de
  WOT-2026-043c, no el de esta propuesta puntual.
- NO anade `measure_agents_md_units.py` ni ningun otro script al manifiesto -- el protocolo
  no los necesita (verificado arriba); si en el futuro se demuestra que un destino SIN el
  script no puede ejecutar el protocolo en la practica, se reconsiderara con evidencia.
- NO cambia el modo de distribucion (sigue siendo "el motor no se copia, se referencia").

## Verificacion

1. Anadir `prompts/doc_optimization.md` a `MANIFEST.distribute` Y retirar la tupla
   `("skills/doc-optimization/SKILL.md", "prompts/doc_optimization.md")` de `_FROZEN_DEBT` en
   `scripts/check_distribution_boundary.py` en el MISMO cambio (hallazgo codex: editar solo el
   manifiesto no basta, la tupla hardcodeada debe retirarse o el guard marca STALE).
2. `uv run python scripts/check_distribution_boundary.py` -- debe seguir en OK.
3. `uv run python scripts/check_distribution_boundary.py --skill-citations` -- debe reportar
   **13** entradas congeladas (no 14) y seguir en OK.
4. Ejecutar explicitamente (no solo buscar) los 2 tests focales confirmados:
   `uv run python -m pytest tests/unit/test_check_distribution_boundary.py
   tests/unit/test_check_distribution_boundary_citations.py -q` -- ninguno asertaba el conteo
   exacto de `_FROZEN_DEBT`, verificado con grep (`len(_FROZEN_DEBT)` sin coincidencias), pero
   se corren igual para confirmar que no rompen por otra via.
5. `check_encoding_guard.py` sobre `MANIFEST.distribute` y `check_distribution_boundary.py`
   tras la edicion.
6. Opcional, no bloqueante: actualizar el comentario "14 of 19 normative citations... measured
   on 2026-10-07" (linea ~32 de `check_distribution_boundary.py`) con una nota de que una
   entrada se resolvio despues, para que un lector futuro no la lea como "14 siguen
   congeladas" -- es evidencia fechada legitima, no se exige cambiarla, pero evita confusion.

## RONDA 1 -- bucle adversarial (2026-10-23)

4 lentes despachadas (codex, mistral, cohere, deepseek). codex: CHANGES, 4 MEJORA (ninguna
BLOQUEANTE) -- verificadas y corregidas: (1) alcance aclarado (corrige contrato standalone, no
demuestra mejora en topologia AGENT_PROJECT_ROOT), (2) referencia en prosa a
`suite_optimization.md` confirmada como WARN-only (el prompt declara "no hace falta leerlo"),
(3) retiro de la tupla en `_FROZEN_DEBT` anadido como paso explicito del mismo cambio, (4) los
2 tests focales se CORREN, no solo se buscan. cohere fallo (error de backend, sin contenido).
mistral y deepseek no llegaron a tiempo de esta pasada.

**Aplicado:** `prompts/doc_optimization.md` anadido a `MANIFEST.distribute`; tupla
`("skills/doc-optimization/SKILL.md", "prompts/doc_optimization.md")` retirada de
`_FROZEN_DEBT` en `scripts/check_distribution_boundary.py` (+ nota fechada de resolucion).
Verificado: `check_distribution_boundary.py` OK, `--skill-citations` OK (13 congeladas, antes
14), 16/16 tests focales verdes, `check_encoding_guard.py` OK. Sin impacto en los gates de
`AGENTS.md` (ninguno de los dos ficheros tocados es siempre-cargado).

**Estado: APLICADO -- pero ver correccion critica de RONDA 2 abajo antes de interpretar que
resuelve el objetivo del usuario.**

## RONDA 2 -- bucle adversarial, correccion critica (2026-10-23)

**deepseek encontro un BLOQUEANTE real, verificado por mi de forma independiente
(`git grep -c "MANIFEST.distribute" scripts/install_agent_system.py` -> 0 resultados;
`MANIFEST.workspace` seccion "EXPLICITAMENTE EXCLUIDO" lista literalmente `scripts/` y
`skills/`; `prompts/` ni se menciona):** `scripts/install_agent_system.py` NUNCA lee
`MANIFEST.distribute`. El instalador copia el workspace usando `MANIFEST.workspace` como
allowlist, que EXCLUYE explicitamente `scripts/` y `skills/` del copiado (el motor central
vive solo en el repo fuente); `prompts/` no esta ni incluido ni excluido porque no se copia en
absoluto. **No existe ningun modo de instalacion en este repo que copie `prompts/` o
`skills/` a un destino.** El UNICO mecanismo real por el que un destino accede a
`prompts/doc_optimization.md` es la referencia EN VIVO al motor via `AGENT_PROJECT_ROOT`
(nunca una copia) -- exactamente como ya funcionaba ANTES de este cambio.

**Correccion del diagnostico:** `MANIFEST.distribute` NO es (ni fue nunca, en este repo) un
mecanismo de transporte hacia destino -- es un libro de contabilidad INTERNO que
`check_distribution_boundary.py` audita para verificar que la frontera declarada del motor
coincide con la realidad. El objetivo real del usuario ("que los destinos aprovechen el
metodo") YA ESTABA satisfecho, antes de este cambio, por la arquitectura existente (cualquier
destino con el enlace motor<->destino ya lee `prompts/doc_optimization.md` en vivo). Este
cambio NO amplia esa capacidad ni un bit.

**El cambio aplicado sigue siendo correcto MANTENERLO** (no se revierte): resuelve una deuda
REAL y ya declarada en el codigo (`_FROZEN_DEBT`, WOT-2026-043b/c), con los 2 tests focales y
ambos sentidos del guard en verde -- es contabilidad interna legitima, consistente con el
criterio de cierre que el propio ticket ya escribio. Lo que se corrige es la NARRATIVA: este
cambio cierra una entrada de deuda de "frontera declarada", no abre ninguna capacidad nueva
para destino. Si el usuario quiere realmente ampliar que puede hacer un destino SIN el enlace
motor<->destino vivo, el problema es arquitectonico (el instalador tendria que empezar a
copiar `prompts/`/`skills/` via algun mecanismo nuevo) y esta FUERA del alcance de esta
propuesta puntual.
