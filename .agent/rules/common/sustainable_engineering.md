# CEM v0 - Ingenieria sostenible con agentes

Esta regla es una referencia operativa revisable. CEM significa Contrato, Evidencia y Memoria. Su objetivo no es anadir ceremonia fija, sino reducir recurrencias con rigor proporcional.

## Principio central

Un problema no esta cerrado cuando deja de fallar. Esta cerrado cuando entendemos el contrato, dejamos evidencia verificable y convertimos el aprendizaje en barrera automatica o deuda explicita.

## Tiers de rigor

- Tier 0: documentacion, memoria o texto sin impacto runtime. Requiere diff limpio y guard de encoding si aplica.
- Tier 1: tests o fixtures aislados. Requiere test focal y explicacion del contrato que valida.
- Tier 2: codigo de produccion local. Requiere test gobernante, calidad focal y scope claro.
- Tier 3: bus, supervisor, hooks, rutas, seguridad, estado compartido o tooling de cierre. Requiere evidencia focal, prueba contextual y barrera verificada.
- Tier 4: arquitectura o protocolo sistemico. Requiere contrato escrito, plan, reversibilidad y cierre documental.

El tier debe derivarse principalmente de paths tocados, blast radius y reversibilidad, no de la autoevaluacion del Builder.

## Taxonomia de fallos

- Clase A: regresion de contrato. Produccion diverge del comportamiento canonico.
- Clase B: fuga de estado. Cache, cwd, sys.modules, variables globales o filesystem contaminan otros tests.
- Clase C: deriva de fixture o mock. El test ya no representa la API o artefacto real.
- Clase D: entorno o infraestructura. Encoding, rutas, permisos, topologia, plataforma o herramientas.

## Escalera de robustez

Prefiere la barrera mas alta razonable para el riesgo:

- R0: documentar la regla.
- R1: detectar tarde con test o auditoria.
- R2: bloquear en la puerta con hook, gate o validator.
- R3: hacer dificil el error con defaults, scope automatico o mensajes self-service.
- R4: hacer imposible representar el error con estructura, tipos, API unica o fuente canonica.

## Protocolo de clasificacion

- Si sospechas contaminacion, compara aislado vs suite/contexto.
- Si dudas entre test obsoleto y bug real, compara test contra produccion committeada y contrato canonico.
- Si sospechas falso verde, contrasta fixture contra artefacto real.
- Si anades una barrera, inyecta el fallo y confirma que bloquea.

## Roles

Builder: implementa cambios pequenos con contrato, evidencia y barrera proporcional. Si sale de scope, lo justifica antes de seguir.

Manager: revisa si el verde significa realidad. Rechaza falso verde, mocks que oculten drift y evidencia puramente narrativa.

Supervisor: automatiza invariantes, valida topologia, genera handoffs desde fuentes canonicas y hace que los gates sean accionables.

Humano: sostiene el criterio del sistema preguntando que contrato se defiende, que evidencia existe, que barrera queda y que deuda se acepta.

## Relaunch CEM

Un Builder relanzado no debe arrancar amnesico. Antes de relanzar, el Supervisor debe verificar root/topologia. Despues debe generar una capsula fresca desde fuentes canonicas que separe hechos verificados, blockers, hipotesis y siguiente accion. La capsula no es estado vivo acumulativo.

Cuando el Builder escriba en execution_log.md algo no verificado o inferido, debe usar el prefijo canonico `hipotesis:` para que el Supervisor lo incluya en la capsula de relaunch.
Ejemplo: `- hipotesis: el fallo puede deberse a contaminacion de cache — pendiente de confirmar.`
Sin ese prefijo, la inferencia no aparece en la capsula y el siguiente Builder arranca sin ese contexto.

## Metricas ligeras

- Familias recurrentes por periodo.
- Deuda viva: allowlists, skips, xfails, overrides y tickets de deuda.
- Porcentaje de fixes con barrera proporcional.
- Falsos verdes detectados por revision.
- Tiempo desde deteccion de familia hasta barrera.

## Reglas operativas CEM (verbatim de AGENTS.md, WOT-2026-036e)

Las siguientes 5 reglas se copian VERBATIM (palabra por palabra) desde la seccion
"CEM v0 - Contrato, Evidencia y Memoria" de `AGENTS.md`. Son una seleccion, no la
seccion completa; la fuente canonica sigue siendo `AGENTS.md`. Esta es una
extraccion aditiva de fase A (WOT-2026-036e), sin reescritura ni parafraseo.

- **Un `exit 0` puede significar "no hice nada":** en operaciones IDEMPOTENTES o con SKIP (cierres, syncs, instaladores), `exit 0` es indistinguible de "ya estaba hecho" o "me salte el trabajo". `exit code` es evidencia NECESARIA pero no SUFICIENTE para estas: verifica el ARTEFACTO (fichero/informe/diff/contador que la operacion debia producir), no solo el codigo de salida; y busca en la salida las palabras de skip (`already`, `skipped`, `nothing to do`, `none present`, `up to date`, `no files to check`). Y lee el CODIGO antes de temer un flag: un `--force` puede vencer SOLO la idempotencia sin tocar los gates (leer 12 lineas convierte un "no me atrevo" en un cierre real). Caso: `--session-close` dio `exit 0` sin cerrar nada (`[INFO] Session already completed`), disparado por un `.session_state.json` STALE que ademas se contradecia con `work_plan.md` (2026-07-15).
- **Equivalencia de ruta productiva (evidencia exploratoria vs evidencia de cierre):** un `exit_code:` solo es evidencia de CIERRE si el probe **reproduce la ruta que corre en produccion**. Aplica **rigor proporcional**: obligatorio para todo lo que toca runtime (hooks, guards, CI, tests, scripts ejecutables, instalador); se salta para docs, typos y prosa sin logica de ejecucion.
  - **Asimetria dura:** un probe que NO reproduce la ruta productiva puede **REFUTAR** una hipotesis, pero **NUNCA CONFIRMAR un cierre**. La confirmacion es la que mata: hoy el probe de PowerShell *confirmo* una hipotesis falsa, y fue el probe en la ruta REAL (Git Bash) el que la refuto.
  - **Recibo obligatorio (no basta afirmarlo):** el probe **imprime** su propio contexto -- `sys.executable`, `cwd`, la parte relevante de `PATH`/env, y la cadena de launcher-- y ese recibo se pega junto al `exit_code:`. Sin recibo, es evidencia exploratoria por defecto.
  - **Declara y justifica:** actor real, launcher real, shell, cwd, PATH/env, fichero/config leido, y **POR QUE** ese probe reproduce la ruta productiva.
  - **Vector git (WOT-2026-020r):** si el probe invoca git, pregunta explicitamente **¿el cwd tiene su propio `.git`?** Si no lo tiene, el walk-up de git **alcanza el repo REAL** y te contesta el arbol de la maquina, no el fixture: el probe NO es hermetico y su verde no significa nada.
  - **Por que esto es una regla y no un consejo:** un probe en la ruta equivocada se ve IDENTICO a uno bueno -- tiene `command:` y tiene `exit_code:` -- y por eso atraviesa a los revisores. Casos: `check_entrypoint_fails_closed` valida el entrypoint con `[sys.executable, ENTRYPOINT]` mientras produccion lo lanza **por shell** con `python` pelado, asi que prueba una ruta que produccion nunca toma; y el diagnostico de WOT-2026-020o midio `python` en **PowerShell** cuando el hook corre en **Git Bash**, lo que subio la ficha a Alta y ato WOT-2026-024f a ella sobre una premisa falsa (2026-07-15).
  - **ESTATUS DECLARADO: esto es una NORMA, no una barrera** (segun la definicion de "Barrera cableada" de esta misma lista: nadie la invoca sola, depende de que el agente se acuerde). Se declara asi a proposito en vez de disfrazarla de gate. El recibo es mecanizable y los checks POR DOMINIO si son cableables (p.ej. el censo de WOT-2026-024f debe resolver en Git Bash); un verificador GENERICO de equivalencia no es trivial, porque **no existe oraculo universal de "la ruta productiva"**: para comparar contra produccion hay que ejecutar en produccion, y entonces la comparacion sobra. Deuda declarada con dueno: **WOT-2026-025f**.
- **El conflicto entre probes ES el hallazgo:** si dos mediciones del mismo hecho se contradicen, **no elijas la que confirma tu tesis, ni promedies, ni descartes la incomoda**: averigua QUE mide cada una, porque casi siempre **una de las dos no es produccion**. `python -c "pass"` dio TRES exit codes el mismo dia en la misma maquina -- `subprocess(shell=False)` -> 0 (CreateProcess resuelve primero el dir del ejecutable PADRE: el python del venv), cmd/PowerShell -> 1 (shim `python.BAT`), Git Bash -> 0 (el `python.exe` real). Dos de los tres producian un veredicto FALSO sobre produccion: uno un falso VERDE y otro un falso ROJO. La contradiccion es material de auditoria de primer nivel, no ruido a resolver por mayoria.
- **Barrera cableada:** ademas de morder, algo tiene que INVOCARLA. Un guard solo es barrera si lo llama un camino que corre solo (pre-commit, CI, `prepush_check`, closeout, preflight, controlador, hooks de tool-call). Citarlo en un prompt, una skill o este AGENTS.md **no es cableado: es una norma**, y una norma depende de que alguien se acuerde. Barrera de la barrera: `scripts/check_guard_wiring.py` (WOT-2026-024u) - un guard nuevo sin cablear FALLA; la deuda legacy solo puede quedar en WARN si esta DECLARADA con su ticket dueno.
- **Barrera del alcance, no solo del mecanismo:** un guard puede estar cableado, morder, y no mirar donde ocurre el fallo. Caso historico: `check_encoding_guard` es fail-closed y corre en pre-commit, pero durante meses se limitaba a `.py`; por eso DOS fugas de markup de modelo vivieron sin detectar dentro de `AGENTS.md` y `MANUAL_PUBLICATION_CHECKLIST.md` - esta ultima desde el commit inicial del repo (WOT-2026-024x). Ya CORREGIDO (WOT-2026-025n): desde df674bb el guard cubre `.md` (TEXT_EXTENSIONS + GLOB_PATTERNS `*.md`, `prompts/**/*.md`, ...), asi que hoy SI mira donde ocurrio aquel fallo. El PRINCIPIO sigue vigente: un guard nuevo se audita por DONDE mira, no solo por si muerde.
- **Criterio invariante, evidencia fechada:** un DoD debe ser un INVARIANTE, no una MEDICION. Un criterio que fija un numero ("quedan 11 hits", "243 auditorias") caduca solo, sin que nadie toque la ficha, y el Builder ya no puede distinguir "el numero cambio porque el mundo avanzo" de "cambio porque he roto algo". El numero es EVIDENCIA: va etiquetado como snapshot fechado, nunca como criterio de aceptacion (WOT-2026-024t).

**Nota de exclusion (WOT-2026-036e):** el bullet de `AGENTS.md` "Aplicate tu
propia vara (y que lo diga otro)" (linea 286, entre las dos reglas de Barrera
copiadas arriba) queda FUERA de esta fase A a proposito. No se copia como
regla verbatim aqui; es candidata a fase B (WOT-2026-036f). Se deja constancia
explicita de la exclusion para no silenciarla.
