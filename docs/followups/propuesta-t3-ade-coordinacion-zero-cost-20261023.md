# Propuesta: documentar coordinacion T3/ADE multi-sesion a coste CERO contra los gates (2026-10-23)

> **SUPERADA (mismo dia).** Su premisa central es FALSA: "`.claude/rules/` no cuenta" solo es
> verdad para el medidor, no para Claude Code, que autocarga todo `.claude/rules/*.md` sin
> `paths:` (TRAMPA-5 de `prompts/doc_optimization.md`). El modulo se movio a
> `.agent/rules/common/t3_ade_coordination.md`. Ver
> `docs/followups/propuesta-arranque-frio-y-relevo-t3-20261023.md`. Se conserva como registro
> del error.

> Origen: el usuario pidio analizar `AGENTS.md`/`CLAUDE.md` desde el cambio de paradigma
> "antes IDE unico con repo abierto (VSC/Antigravity/Zed) -> ahora T3, un ADE con sesiones
> en paralelo (potencialmente multi-cuenta, cada una en su worktree)". Objetivo explicito de
> esta propuesta: **cumplir el limite de Codex** -- no empeorar el deficit ya declarado (1641B)
> al anadir esta documentacion nueva.

## Hallazgo (verificado, no el mio del turno anterior)

Lei `scripts/measure_agents_md_units.py::gates()` y `resolve_closure()`:

- **Gate Codex** (32768 B): `codex_bytes = len(agents_raw)` -- SOLO bytes de `AGENTS.md`.
  `CLAUDE.md` y cualquier fichero de `.claude/rules/` **no cuentan NUNCA** para este gate.
- **Gate Claude** (40000 chars): suma de `resolve_closure(CLAUDE.md)` -- hoy
  `CLAUDE.md` (2008 chars) + `AGENTS.md` (34330 chars) = 36338/40000 (margen 3662 chars).
  `resolve_closure()` solo sigue lineas que empiezan literalmente con `@` (import real), NUNCA
  prosa como "ver `.claude/rules/README.md`" -- confirmado leyendo el codigo (ignora fences,
  seccion por seccion, `stripped.startswith("@")`).
- **Consecuencia:** un fichero nuevo en `.claude/rules/` (sin anadir una linea `@...` a
  `CLAUDE.md`) no entra en NINGUN cierre. Coste contra ambos gates: **0**.

## Error autocorregido (turno anterior, antes de este bucle)

En mi analisis previo del hueco T3/ADE dije: *"probablemente deberia vivir como
referencia-bajo-demanda con un puntero corto"* sin fijar DONDE va ese puntero. Eso dejaba
abierta la opcion de ponerlo en `AGENTS.md` (ya en deficit de 1641B, lo habria empeorado).
Verificado arriba: la ubicacion correcta es un modulo nuevo de `.claude/rules/` + una linea en
`.claude/rules/README.md` (que tampoco cuenta para ningun gate). Cero coste, no "coste bajo".

## El hueco real que se documenta (motivo original del usuario)

La documentacion asume una sesion unica con un repo abierto (modelo IDE clasico). El salto a
T3 como ADE con sesiones PARALELAS (potencialmente multi-cuenta, cada una en su worktree) esta
parcheado reactivamente pero nunca nombrado como el modo normal de operacion:

- **Lo que SI existe hoy:** la regla de aislamiento por worktree (`vocabulario_canonico.md`) y
  el Gate 2 de `flight_push_policy.md` ("push a una rama con trafico concurrente de otras
  sesiones") -- pero Gate 2 es el mecanismo GIT reactivo (que hacer si la rama avanzo), no un
  protocolo de COORDINACION proactiva entre hilos T3 vivos.
- **Lo que NO existe en ningun sitio:** cuando consultar `t3_worktree_list`/`t3_thread_search`
  antes de tocar una superficie compartida (p.ej. `build_llms.py`, `AGENTS.md`,
  `MANIFEST.distribute`), cuando mandar un `t3_thread_send` de aviso antes de escribir, y el
  protocolo de verificacion de resultados de `delegate_task` (medido HOY en esta misma sesion:
  3 de 5 lentes devolvieron afirmaciones falsas o datos obsoletos -- CRLF inexistente, una
  "tabla" que no existe, una palanca ya aplicada que un lens creyo pendiente -- las 3
  descartadas solo porque se verificaron con bytes/grep reales antes de actuar).
- **Leccion de enrutamiento de backends** (medida hoy, nueva): modelos con el mismo nombre
  (`glm-5.3`) enrutan por sub-brokers con cuotas de credito INDEPENDIENTES
  (`openrouter/*`, `aihubmix/*`, `nan/*`, `mistral/*`, `opencode-go/*`) -- si uno falla por
  saldo, no es un fallo de contenido, es ese broker especifico; probar otro sub-broker antes de
  descartar el modelo.

## Propuesta

1. Crear `.claude/rules/07-t3-ade-coordination.md` (modulo numerado, mismo patron que 00-06):
   contenido = las 3 lecciones de arriba (coordinacion proactiva entre hilos, verificacion de
   `delegate_task` antes de confiar, enrutamiento de backends por sub-broker), mas un puntero
   de vuelta a `flight_push_policy.md` Gate 2 (NO lo duplica -- Gate 2 sigue siendo la autoridad
   del mecanismo git; este modulo nuevo es la capa social/operativa por encima).
2. Anadir UNA linea a `.claude/rules/README.md`, seccion "Cargas bajo demanda recomendadas":
   `- \`07-t3-ade-coordination.md\`: si operas con sesiones T3 paralelas (multi-cuenta o
   multi-worktree) sobre el mismo vuelo o el mismo repo.`
3. **NO tocar `AGENTS.md` ni `CLAUDE.md`** -- condicion de diseno de esta propuesta, no un
   efecto secundario.

## Non-goals

- NO cierra el deficit Codex ya existente (1641B) -- eso sigue siendo deuda declarada,
  confirmada por 3 lentes independientes tras verificacion (ver sesion de hoy: codex/gpt-5.6-luna,
  mistral-large, opencode-go/glm-5.3, todas sus propuestas de ahorro fallaron verificacion con
  bytes reales).
- NO reescribe Gate 2 ni `flight_push_policy.md` -- el modulo nuevo remite, no redeclara
  (gobierno X-09).
- NO anade un mecanismo nuevo de deteccion automatica de sesiones concurrentes -- es una norma
  operativa (como), no una barrera cableada; si se demuestra que alguien la olvida 2+ veces
  medidas, escalar a guard (mismo criterio F8 ya adoptado para el eje G).

## Verificacion

1. `uv run python -m scripts.measure_agents_md_units` tras el cambio -- debe seguir mostrando
   EXACTAMENTE `codex=34409/32768` (sin cambio) y `claude=36338/40000` (sin cambio): prueba de
   que el fichero nuevo no entra en ningun cierre.
2. `grep -c "^@" CLAUDE.md` -- debe seguir devolviendo 1 (solo `@AGENTS.md`), confirmando que no
   se anadio ningun import nuevo.
3. Verificar que `.claude/rules/07-t3-ade-coordination.md` no re-declara nada que ya viva en
   `flight_push_policy.md` (grep de las 5 condiciones del Gate 2 relajado -- no deben aparecer
   verbatim en el modulo nuevo).

## Ampliacion de alcance (mismo turno, pedida por el usuario)

El usuario pidio ampliar el contenido mas alla de la palanca de ubicacion: cubrir tambien
comunicacion entre cuentas distintas, comunicacion entre sesiones de la misma cuenta
(`delegate_task`/lentes), coordinacion de suite/push cuando hay sesiones paralelas sobre
`main`, y cierre de ramas/worktrees. Incorporado en el fichero final con 4 secciones (1-4) mas
una seccion de "Disciplina de crecimiento".

## RONDA 1 -- bucle adversarial (2026-10-23)

2 lentes (codex/gpt-5.6-luna, mistral-large), ambas APROBAR_CON_CAMBIOS, convergentes:

- Confirmaron "coste cero contra los gates" como estrictamente correcto (verificado
  independientemente contra `gates()`/`resolve_closure()`).
- codex senalo que `.claude/rules/*.md` SI es leido por `memory_bootstrap_census.py` (censo de
  memoria, glob `RULES`) y por `detect_version.py` (marcador de version por presencia de
  directorio) -- verificado: ninguno de los dos se rompe (el censo debe incluir el fichero
  nuevo por diseno; `detect_version.py` solo chequea presencia de directorio, no una lista
  exacta de ficheros). Aclarado en el fichero final: "no sujeto a los gates" se refiere
  especificamente a los 2 gates de contexto siempre-cargado, no a "invisible para todo".
- Ambas lentes exigieron: (1) parrafo de alcance explicito limitando el fichero a coordinacion
  proactiva T3 (anadido como primer bloque del fichero), (2) declaracion explicita de
  exencion de gates (anadida), (3) disciplina de crecimiento con limite mecanico de tamano
  (anadido ~8 KiB como senal de alarma, norma no barrera, mismo criterio de escalada F8).

**Aplicado:** `.claude/rules/07-t3-ade-coordination.md` creado (4 secciones + disciplina de
crecimiento); `.claude/rules/README.md` actualizado (anadida linea `07-...` Y corregido un gap
preexistente -- `06-project-manifest-architecture.md` no estaba listado). Verificado:
`uv run python -m scripts.measure_agents_md_units` -- gates SIN CAMBIO
(codex=34409/32768 deficit=1641, claude=36338/40000 deficit=0, identicos a antes del cambio);
`grep -c "^@" CLAUDE.md` = 1 (sin imports nuevos); grep de contenido Gate 2 verbatim en el
fichero nuevo = 0 coincidencias.

**Estado: APLICADO.**
