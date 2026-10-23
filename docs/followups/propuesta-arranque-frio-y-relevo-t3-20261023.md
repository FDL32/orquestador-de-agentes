# Propuesta: arranque frio real, relevo entre sesiones y simplificacion (2026-10-23)

    ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\optimizacion-arranque-frio-cont-20261022,
    HEAD=02aba94a803a, dirty=si (trabajo de la sesion sin commitear), verificado=2026-10-23

> Protocolo: `prompts/doc_optimization.md` (leido entero). Preguntas del usuario: (1) que mas
> mejora el arranque de una sesion fria, (2) como el cierre puede ayudar a la siguiente sesion,
> (3) que nomenclatura/invocaciones se pueden simplificar o fusionar, (4) objetivo: cumplir el
> limite Codex. Evidencia: medicion propia + 3 investigaciones paralelas, con las cifras clave
> RE-VERIFICADAS por mi (no propagadas sin comprobar).

## 1. Errores encontrados en esta pasada (incluidos los mios)

- **E1 (mio, aplicado hoy, hay que revertirlo): "coste cero" de `.claude/rules/07-...` es FALSO.**
  Claude Code auto-carga de forma nativa TODO `.claude/rules/*.md` sin frontmatter `paths:`
  (evidencia directa: el contenido de 00-06 + README aparecio inyectado al inicio de ESTA
  conversacion; `grep -rn "^paths:" .claude/rules/` = 0 hits). 07 suma 6.984 chars a CADA
  sesion Claude. El fallo: me fie de la etiqueta "Cargas bajo demanda" del README y del medidor,
  en vez de del runtime -- "evidencia antes que relato" aplicado a mi mismo.
- **E2: "gate Claude CERRADO, deficit 0" es probablemente FALSO en la realidad.** El medidor
  (`measure_agents_md_units.py::resolve_closure`) solo cuenta `CLAUDE.md` + `@imports`. Lo que
  llega de verdad a un Claude frio en este repo (medido):

  | Superficie | chars | ¿la cuenta el medidor? |
  |---|---|---|
  | `CLAUDE.md` + `AGENTS.md` | 36.338 | si |
  | `.claude/rules/*.md` (9 ficheros, sin `paths:`) | 25.295 | **no** |
  | Hook SessionStart (`additionalContext`) | 33.792 | **no** |
  | `MEMORY.md` auto-memoria + `~/.claude/CLAUDE.md` | 20.127 | **no** |
  | **Total aproximado** | **~115.500** | 31 % |

  Solo los ficheros de instrucciones del repo ya suman 61.633 chars (1,54x de 40k).
  **[INCIERTO]** si el aviso nativo de 40k cuenta `.claude/rules` (el changelog dice "counts
  instruction files together", lo que sugiere que si) y si cuenta el `additionalContext` del
  hook. Verificacion barata: ver si Claude Code muestra el aviso `chars > 40.0k` al arrancar en
  este repo.
- **E3: el propio `doc_optimization.md` PASO 1 tiene el mismo punto ciego.** Su tabla de clases
  dice que es siempre-cargado "lo marcado 'Siempre' en un indice de reglas". Para Claude Code eso
  es incompleto: es siempre-cargado TODO `.claude/rules/*.md` sin `paths:`, este marcado o no.
  Es una TRAMPA nueva de la misma familia que TRAMPA-2.
- **E4: Codex no ve `.claude/rules`.** Lo que solo vive ahi es invisible para las sesiones T3
  que corren Codex, incluido el contenido de coordinacion T3 de 07.
- **E5: carga doble de memoria.** `.claude/rules/00-startup.md:3` (siempre cargado) ordena
  ejecutar `prompts/_shared/memory_bootstrap.md` (`memory_context.py --bootstrap`, ~29,7k chars),
  pero el hook SessionStart YA inyecto ese indice (33.792 chars). Un agente obediente lo paga dos
  veces.
- **E6: `/quality-gates` esta obsoleto, y es un bug de correccion, no de tamano.**
  `.claude/commands/quality-gates.md` lanza `ruff check .agent/hooks/guard_paths.py tests` (no
  `ruff check .`) y no ejecuta `pip-audit`, lo que contradice "Criterio de cierre" de
  `AGENTS.md`. Un agente frio que lo sigue cierra con un gate parcial.
- **E7: la restriccion dura de `doc_optimization.md` es "UN fichero por corrida".** Esta
  propuesta toca varios ficheros siempre-cargados, asi que se ejecuta como una SECUENCIA de
  corridas, una por fichero y cada una con su before/after; no como un barrido.

## 2. Propuesta, por niveles

### Nivel A -- ganancias limpias (riesgo bajo, contenido intacto)

| # | Cambio | Ahorro en frio | Fila PASO 2 / riesgo |
|---|---|---|---|
| A1 | `00-startup.md`: "en Claude Code el hook SessionStart ya inyecto el indice; ejecuta `--bootstrap` solo en backends sin hook" | ~30k evitados (la carga doble) | corrige una orden duplicada; bajo |
| A2 | Mover 07 a `.agent/rules/common/t3_ade_coordination.md` (sin cambios de contenido) + puntero | 6.984/sesion | contenido condicional (fila 7); corrige E1 |
| A3 | Arreglar `/quality-gates`: `ruff check .`, `ruff format .`, `pip_audit_project.py`, `run_pytest_safe.py` | 0 chars, cierra un bug | bajo |
| A4 | `02-multi-agent-system.md` obsoleto ("unico backend soportado", modelo de copia de plantilla): quitarlo o dejar un puntero a `AGENTS.md` | ~1,1k + una contradiccion menos | bajo |
| A5 | `06-project-manifest-architecture.md` a `.agent/rules/common/` VERBATIM, arreglando de paso dobles lineas en blanco (183/297), celdas `?` con mojibake y `config.json` -> `settings.json` | ~6,6k/sesion | referencia/condicional (filas 5 y 7); bajo |
| A6 | `README.md` de rules: corregir la etiqueta "bajo demanda" (falsa en Claude Code) | 0 | bajo |
| A7 | Medidor: el gate Claude incluye `.claude/rules/*.md` sin `paths:` (WARN, segun PASO 5) + nueva TRAMPA-5 en `doc_optimization.md` (E3) | barrera contra recrecimiento | medio: el gate pasara a ROJO si los A1-A6 no van antes |

Efecto conjunto de A2+A4+A5: ~14,7k chars menos en cada sesion Claude frio. Con A1, se evitan
~30k mas cuando el agente obedece 00-startup.

### Nivel B -- relevo entre sesiones (la pregunta 2)

Hoy hay 4 rutas de cierre que se solapan (`close_chat`, `close_full_audit`, que contiene a la
anterior, `manager-session-closeout` y `session-close-observations`) y ningun artefacto de
relevo que se consuma solo. El hook SessionStart inyecta memoria y salud, pero NO el ARRANQUE de
`session_hop`, que depende de que alguien lo pegue.

- **B1: el hook inyecta un PUNTERO al relevo mas reciente** de esta rama/worktree (ruta + fecha
  + HEAD citado, nunca el contenido). La siguiente sesion re-mide segun el Paso 2 de
  `session_hop`. Mitiga el riesgo de estado obsoleto.
- **B2: seccion "Coordinacion T3" en `prompts/session_hop.md`**, con hilos paralelos activos,
  `delegate_task` sin cerrar (taskId), promesas abiertas a otras sesiones (p.ej. "verifica Gate 2
  contra `e5f910b6` antes de tu push", real de hoy), y worktrees con commits sin publicar de
  cualquier cuenta. Las rellena el AGENTE con `t3_thread_list`/`t3_worktree_list`/`task_status`
  (son MCP, sin CLI que las recoja).
- **B3: una sola ruta de relevo por modo.** Motor code-only: `docs/followups/` (lo que ya se usa
  de hecho). Destino: `orchestrator_pipeline/arranques/`. Documentarlo en `session_hop.md`.

### Nivel C -- simplificacion con mas riesgo (necesita su propia ronda; NO se aplica aqui)

- C1: `orchestrator_session_bootstrap.md` (30,9k, que `CLAUDE.md:22` ordena pegar) duplica el
  bloque CEM de `AGENTS.md`, ya cargado. Pasar ese bloque a puntero es seguro. Pasar el
  vocabulario (6,3k) a puntero degrada una lectura obligada a "bajo demanda": hay que evaluarlo
  aparte.
- C2: los 43 `.claude/skills/*` son envoltorios de doble salto (~17,7k chars de descripciones al
  arrancar). Generarlos desde `skills/` o acortarlos afecta al enrutado de skills y a
  `test_deployed_skills_contract.py`.
- C3: fusionar `audit-pipeline`/`-codeonly` y `orchestrate-pipeline`/`-codeonly` con un flag de
  modo; fusionar `close_chat` y `full_audit` en una entrada con modos.
- C4: limitar el indice que inyecta el hook (33,8k). **Choca con la directiva del usuario de no
  degradar la carga en frio**: ese indice ES la continuidad. Solo con medicion previa de recall.
- C5: `memory_context.py --recall --id`: sugerir los ids mas cercanos cuando no hay coincidencia.
  Elimina un fallo ya documentado y el riesgo es bajo; podria subir a A.
- C6: `01-security`, `05-session-artifacts` con `paths:`, y `00-startup` recortado a punteros.

### Codex (objetivo explicito del usuario)

- Nada de A/B/C cambia `AGENTS.md`, asi que el deficit Codex sigue en **1641 B**, deuda ya
  declarada.
- **Decision abierta (E4):** el contenido T3 movido en A2 sigue invisible para Codex. Hay dos
  opciones:
  - (i) anadir un puntero de unos 70 B al final de la linea `[G1]` de `AGENTS.md`. El deficit
    pasa a ~1711 B.
  - (ii) aceptar que los Codex en T3 no lo vean.
- Recomiendo (i): una sesion T3 de Codex es justo quien mas lo necesita.

## RONDA 1 -- bucle adversarial (2026-10-23): CHANGES, adjudicado y corregido

Recuento: 1 valida (codex/gpt-5.6-luna, CHANGES), 1 INVALIDA y 1 MUDA.
- **mistral-large, INVALIDA:** los 5 ficheros que cita como evidencia no existen
  (`.claude/rules/common/`, `scripts/doc_optimizer.py`, `docs/legacy/quality_process.md`,
  `tests/test_memory_bootstrap.py`, `06-encoding-guard.md`), `git grep "^@.*\.claude/rules"` = 0
  y cita "lineas 800-850" de un `AGENTS.md` de 448. Se descarta como veredicto.
- **glm-5.3, MUDA:** termino sin veredicto ("estoy verificando..."). Se repite en la RONDA 2.

Hallazgos de codex, verificados y aplicados:
1. **E1 "no demostrado" -> ACEPTADO en parte.** La evidencia es del runtime real (este entorno
   inyecto 00-06 + README al inicio de la conversacion), pero ese runtime es Claude Code alojado
   en T3, no la CLI nativa. E1 queda **"observado en este runtime; pendiente de confirmar en la
   CLI nativa"**. A2 se mantiene porque no lamenta nada: mover 07 a una referencia no degrada
   nada aunque la CLI nativa no lo autocargase.
2. **Cifra corregida:** el hook inyecta **33.609 chars** de `additionalContext`. Los 33.792 eran
   bytes del JSON de stdout.
3. **E5 acotado:** la carga doble solo ocurre en arranque `startup`. En `resume`/`compact`/`fork`
   el hook usa contexto compacto (`session_start_hook.py:478-489`).
4. **E8 nuevo (friccion de invocacion):** `python scripts/measure_agents_md_units.py` falla con
   `ModuleNotFoundError` y solo funciona `uv run python -m scripts.measure_agents_md_units`.
   Es la familia de la memoria "subprocess script needs own sys.path bootstrap". Arreglo: que el
   script haga su propio bootstrap de `sys.path`, o documentar la invocacion en su docstring.
5. **Reclasificacion del Nivel A (error de encuadre mio):**
   - A1, A3, A6, A7 y E8 son **correcciones de contrato o de guard**, no traslados del PASO 3.
   - A2, A4 y A5 SI son traslados. Su consumidor es `memory_bootstrap_census.py` (glob
     `.claude/rules/*.md`).
   - Verificado: es un **reporter** (`return 0` siempre, no guard), y 02, 06 y 07 YA figuran
     hoy en su lista de NO CUBIERTOS.
   - Sacarlos cambia su salida en sentido benigno: su universo son las reglas siempre cargadas,
     y dejan de serlo. Esa es la diferencia "justificada bloque a bloque" que exige el PASO 4.
     El before/after del censo se registra en cada corrida.
6. **A5 deja de ser verbatim si repara en el mismo paso.** Se separa en dos commits: (a) traslado
   VERBATIM a `.agent/rules/common/`, (b) reparaciones (blancos dobles, mojibake,
   `config.json` -> `settings.json`) con su propio diff.
7. **Nivel B:**
   - **B1 baja a diseno propio, no se aplica en esta ronda.** Requisitos minimos antes de
     implementarlo: selector determinista (el relevo mas reciente DENTRO de la ruta canonica
     de B3 para esta rama), validacion de ancestro (el HEAD citado es ancestro del HEAD actual;
     si no, se avisa en vez de inyectar), identidad de worktree y caducidad (p.ej. >7 dias se
     marca obsoleto).
   - **B2 se declara BEST-EFFORT:** depende de MCP y de lo que se ve entre cuentas, y no
     garantiza capturar todo. Es una lista de comprobacion, no una garantia.
   - **B3 se mantiene.**
8. **Codex:** recomienda la opcion (i), el puntero de ~70 B. Coincide con la recomendacion de la
   propuesta.

**Alcance que queda para aplicar tras la RONDA 2:** A1, A2, A3, A4, A5 (en dos commits), A6, E8,
B2 (best-effort), B3, el puntero Codex (i) y TRAMPA-5 en `doc_optimization.md`. A7 (ampliar el
gate del medidor) solo DESPUES de A2/A4/A5, para no ponerlo en rojo sin haber trasladado antes.

## RONDA 2 (2026-10-23) + correccion del recuento de la RONDA 1

**Error de despacho mio, corregido:** las lentes opencode "mudas" (glm en R1, kimi en R2) NO
estaban mudas. `task_status.latestTerminalSummary` devuelve el PRIMER mensaje del hijo en las
rutas opencode, no el ultimo; el veredicto completo esta en el hilo
(`t3_thread_read` sobre `childThreadId`). Recuento real:

- R1: codex CHANGES, **glm CHANGES** (recuperado), mistral INVALIDA.
- R2: codex CHANGES (sin bloqueantes), **glm APPROVE**, **kimi CHANGES** (sin bloqueantes).

**Hallazgos nuevos verificados (glm R1 + R2, kimi R2, codex R2), incorporados:**

1. **BLOQUEANTE (glm R1), condicion de A1:** `tests/unit/test_memory_bootstrap_census.py::
   test_shared_doc_citado_por_tres_familias` (:155) exige >=1 fichero de `.claude/rules/` que cite
   `memory_bootstrap`, y el unico es `00-startup.md:3`. **A1 debe CONSERVAR la cita literal** de
   `prompts/_shared/memory_bootstrap.md` y solo acotar cuando se ejecuta ("si el hook
   SessionStart no lo inyecto -- backends sin hook o fuente `resume`/`compact`").
2. **MEJORA (glm R1), barrera de alcance [F6]:** el hook pre-commit `check-process-decision-search`
   cubre `.claude/rules/.*\.md` pero NO `.agent/rules/common/` (`.pre-commit-config.yaml:161`).
   Mover 06/07 los saca de esa barrera. Hoy tienen 0 marcadores `DECISION DE PROCESO` (glm R2
   lo verifico), asi que no se rompe nada, pero la regresion de alcance queda abierta. Decision:
   **extender el regex del hook a `\.agent/rules/common/.*\.md`** en el mismo cambio que A2/A5
   (barrera, no norma).
3. **MEJORA (kimi R2, glm R1, codex R2), consumidores en prosa que hay que repuntar en la misma
   corrida:** `.claude/rules/README.md:10,14,15` (entradas de 02/06/07, no solo la etiqueta
   de A6) y `agent_system/docs/MIGRATION_GUIDE.md:13` (ruta de 06).
4. **MEJORA (glm R1), A7 y PASO 5:** al ampliar el gate Claude, el cierre real queda por encima de
   40k (61,6k hoy; ~47k tras A2/A4/A5). La deuda debe declarar ese SEGUNDO exceso con su propio
   recibo en `docs/followups/agents-md-over-quota-followup.md`. Sin eso hay silencio normativo.
5. **MEJORA (glm R1), B1:** `docs/followups/` mezcla relevos con follow-ups ajenos. B3 debe fijar
   un subdirectorio o patron propio (p.ej. `docs/followups/hops/` o `session-hop-*.md`) antes de
   que B1 pueda tener un selector determinista.
6. **MEJORA (glm R2), alcance real de las reparaciones de 06:** 70 pares de lineas en blanco
   dobles (no "183/297"), `config.json` en :51, celdas `?` en :41-59. Se declara en el commit de
   reparacion.
7. **NIT (glm R2, kimi R2), decisiones fijadas:**
   - **A4: quitar 02** y dejar en su sitio una linea en `README.md` que apunte a
     `AGENTS.md` "Backends y roles". 02 contradice a `AGENTS.md`, asi que un puntero no anadiria
     nada.
   - **E8: bootstrap propio de `sys.path`** en `measure_agents_md_units.py` (arregla la clase de
     fallo y no la documenta).
   - **07 esta untracked:** su "traslado" es su primer commit en el destino.
8. **Ancla del puntero Codex (glm R1):** al final de la linea `[G1]` de `AGENTS.md` (~:212).

**Leccion operativa nueva para `t3_ade_coordination.md` (seccion 2):** (a) leer SIEMPRE el hilo
hijo antes de declarar una lente "muda"; (b) los hijos de `delegate_task` sin `isolation` arrancan
en el worktree del hilo PADRE, no en el repo que nombra el prompt. kimi ejecuto varios comandos en
el checkout equivocado hasta pasarse a rutas absolutas: hay que dar rutas absolutas o `git -C`.

**Estado del bucle:** sin BLOQUEANTES abiertos tras la RONDA 2 (el unico, A1, queda resuelto con
la condicion 1). Listo para aplicar como SECUENCIA de corridas (una por fichero siempre-cargado),
con before/after de `memory_bootstrap_census.py` y del medidor en cada una.

## Aplicacion (2026-10-23, aprobada por el usuario tras la RONDA 2)

Commits, en orden: `7d6d277b` (trabajo previo de la sesion, ya revisado), `8d1dff92` (06
traslado R100), `7603b35a` (06 reparaciones), `f451e6a2` (rules + 00-startup + 02 fuera +
t3_ade_coordination + hook de alcance + README/MIGRATION_GUIDE), `73458b8e` (`/quality-gates` +
medidor por ruta), `79d1ebb5` (puntero Codex), `affe5af6` (`session_hop`), y el commit de A7 +
TRAMPA-5 + recibo de deuda.

Resultado medido: autocarga de `.claude/rules/` 25.295 -> 10.979 chars; censo
`RULES 1/9 -> 1/6` (cubierto intacto); tests focales verdes.

**Tres desviaciones respecto a lo aprobado, todas por evidencia encontrada al aplicar:**

1. **Puntero Codex (opcion i): NO en `AGENTS.md`.** El gate de commit-msg
   `check_cuspide_growth_and_drift.py` aplica "no crecer nunca, incluso en deuda"
   (WOT-2026-116a), y el override no lo exceptua: el commit fue rechazado. Ninguna lente ni
   yo lo comprobamos. Se puso en `flight_push_policy.md`, al que Codex ya llega por `[G1]`:
   0 B en lo siempre-cargado.
2. **B3: el motor code-only NO usa `docs/followups/` como portador de relevo.** La restriccion
   dura de `session_hop.md` prohibe cristalizar estado en ficheros versionados del motor. El
   portador en T3 es el `message` de `t3_thread_launch`; la instancia del 22-oct en
   `docs/followups/` ya violaba esa restriccion.
3. **A7 se limita al medidor (WARN).** El gate bloqueante tiene su propia implementacion del
   cierre (`_closure`) y sigue sin contar `.claude/rules/`. Extenderlo cambia el comportamiento
   de un gate bloqueante: queda declarado como deuda en `agents-md-over-quota-followup.md`.

**Hallazgo colateral:** `tests/unit/test_prompt_summary_headers.py` falla por
`prompts/orchestrator_child_dispatch_cross_claude.md` (entro en `d769067e`, antes de la base
`02aba94a` de esta sesion; no esta en su lista `ADOPTED`). Es anterior a esta sesion y pondra en
rojo la suite canonica.

## Non-goals
- No se resume ni se reescribe el contenido de nada de lo que se mueve (PASO 4: NO resumir).
- No se toca el indice de memoria del hook (C4) sin medir antes el recall.
- No se aplica el Nivel C en esta ronda.

## Verificacion (por corrida, una por fichero)
1. Antes y despues: `measure_agents_md_units` + la suma real de `.claude/rules/*.md` sin `paths:`.
2. Consumidores de cada fichero movido: `git grep -n '<basename>'` sin filtro de extension, en
   especial `memory_bootstrap_census.py` (glob `RULES`), `detect_version.py` (presencia de
   directorio) y los tests que citan `.claude/rules`.
3. A3: ejecutar el `/quality-gates` corregido y comprobar que los cuatro pasos corren.
4. `check_encoding_guard.py` sobre los ficheros tocados (06 tiene mojibake).
