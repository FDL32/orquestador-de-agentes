# Propuesta: segunda pasada sobre arranque de sesion, AGENTS.md y CLAUDE.md (2026-10-23)

> Origen: el usuario pidio una segunda pasada sobre el proceso de arranque y sobre
> `AGENTS.md`/`CLAUDE.md`/etc., buscando errores y mejoras, propuesta y bucle ANTES de
> aplicar. **Restriccion de diseno anadida por el usuario:** el arranque de sesion debe ser
> AGNOSTICO de backend (hoy Claude Code, manana Codex/OpenCode/Kilo/Copilot).
>
> ESTADO_FRESCO (worktree `optimizacion-arranque-frio-cont-20261022`, HEAD `d06f4279`,
> arbol limpio, 43 commits por delante de origin/main `62e99493`, suite NO corrida aun):
> `measure_agents_md_units.py` -> codex=34409/32768 (deficit 1641 B), claude=47317/40000
> (deficit 7317 chars; incluye 6 ficheros `.claude/rules` autocargados = 10979 chars).

## Principio de diseno (agnosticismo)

1. **El contrato de arranque es UNO y vive en superficies que leen TODOS los backends:**
   `AGENTS.md` + `prompts/orchestrator_session_bootstrap.md` + `prompts/_shared/memory_bootstrap.md`.
2. **Los hooks de un backend son ACELERADORES, nunca la unica ruta.** Un hook solo puede
   ahorrar un paso si deja en contexto un artefacto OBSERVABLE (indice con lineas
   `[truncated]` + pie de recuento); el contrato agnostico es "si no lo ves, ejecuta el
   comando". Esa comprobacion por presencia funciona igual en cualquier backend.
3. **`CLAUDE.md` y `.claude/rules/` solo contienen pegamento especifico de Claude Code**
   (hooks, `paths:`, comandos slash). Contenido normativo agnostico ahi es invisible para
   Codex/OpenCode: es un hueco, no una optimizacion.

## Hallazgo CRITICO (P0): el hook SessionStart nunca ha inyectado la memoria

**Evidencia (censo, no muestra):** 647 transcripts de Claude Code de este repo
(`~/.claude/projects/*orquestador*/*.jsonl`). El hook corrio y emitio la memoria en su stdout
**577 veces en 219 sesiones**; el harness lo registro como `hook_success` con
`content: ''` y **0 adjuntos `hook_additional_context`**. Control positivo en los MISMOS
transcripts: los hooks SessionStart de plugins (carta) SI producen `hook_additional_context`.

**Causa:** `.agent/hooks/session_start_hook.py:533` emite `{"additionalContext": ...}` en la
raiz del JSON. El esquema de Claude Code para SessionStart es
`{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...}}`; un
campo desconocido en la raiz se ignora. Se pierden los 3 bloques: indice de memoria
(29978 chars), roles por agents.json (284) y contratos M4/M5 (3345) -- este ultimo declarado
"NUNCA se omite" en el docstring.

**Por que los tests no lo vieron:** `tests/unit/test_session_start_hook.py` (468, 494, 507,
611, 630) parsea `["additionalContext"]` en la raiz: valida la forma que el codigo elige, no
la que el consumidor real acepta (CEM "Fixtures realistas" / "Barrera verificada").
`pre_compact_hook.py:344` usa la misma forma; ademas PreCompact no admite inyeccion de
contexto en Claude Code -- a verificar, no a asumir.

**Consecuencias en docs (premisas falsas hoy):** `AGENTS.md:356` ("El hook SessionStart
inyecta el indice"), `.claude/rules/00-startup.md` ("~30k chars duplicados"),
`prompts/orchestrator_session_bootstrap.md:41-45` ("YA te lo inyecto ... duplicarias ~29 KB").
Ninguna rompe nada porque todas condicionan a "si lo ves en tu contexto" -- pero el agente
Claude NUNCA lo ve, asi que o ejecuta `--bootstrap` a mano o arranca con 0 lecciones. Mi
recuento previo de "carga real" (sumaba 33.6k del hook) estaba inflado en esa cantidad.

**Propuesta P0:**
- a. Hook: emitir `hookSpecificOutput` (con `hookEventName` = el evento recibido). Mantener
  `ensure_ascii=True` y el fail-open.
- b. Tests: actualizar los 5 parseos y anadir UN test de contrato que fije el esquema oficial
  (falla si vuelve a la raiz).
- c. Evidencia de cierre por ruta productiva: tras el fix, abrir una sesion nueva y verificar
  en su transcript un `hook_additional_context` con "Memoria del proyecto". Sin eso no se
  declara arreglado.
- d. `pre_compact_hook`: verificar contra la documentacion de Claude Code si PreCompact
  admite contexto; si no, declararlo deuda (no arreglar a ciegas en este vuelo).
- e. ~~Coste: activar el hook anade ~33.6k chars por arranque~~ **CORREGIDO tras R1 (pista de
  kimi, verificada en https://code.claude.com/docs/en/hooks):** "A hook's `additionalContext`
  ... and its plain stdout, are capped at 10,000 characters. Over the limit: Claude Code saves
  the output to a file ... and replaces it with the file path and a preview of up to the first
  2,000 characters. Claude Code doesn't ask Claude to read the file, so keep anything Claude
  must always see within the cap." Con el esquema arreglado y 33.6k, Claude veria solo 2k de
  preview (la cabecera del indice) y PERDERIA roles y M4/M5, que van al final. El recorte NO es
  una decision aparte: es parte del fix. Diseno: orden = pista de expansion + roles + M4/M5
  (~3.7k) primero, despues un indice compacto (solo `id` + titular, sin cuerpo truncado) hasta
  un presupuesto total de <=9.500 chars medido por test; el corpus completo sigue en
  `--recall`. La misma doc confirma: PreCompact no admite `additionalContext` (solo
  `decision: block`), luego `pre_compact_hook.py:344` es inerte -> deuda declarada.

## P1: agnosticismo del contrato de arranque (AGENTS.md)

- a. **AGENTS.md no tiene el imperativo agnostico de carga de memoria.** Solo
  `.claude/rules/00-startup.md` (invisible para Codex) dice "ejecuta el mecanismo al
  arrancar"; `AGENTS.md:356` dice a TODOS los backends que un hook de Claude ya lo hizo.
  Sustituir la linea 356 por: "Al arrancar, si tu contexto no trae el indice (lineas
  `[truncated]` + pie), ejecuta `python scripts/memory_context.py --bootstrap`; algunos
  backends lo inyectan por hook (Claude Code: SessionStart)". Neto ~+60 B (se financia con P2).
- b. Mover a `AGENTS.md` NADA mas que ese imperativo; el resto ya esta en
  `prompts/orchestrator_session_bootstrap.md` (agnostico).

## P2: errores y ahorro en AGENTS.md (gate Codex, bloqueante "no crecer")

| # | Cambio | Ahorro aprox. |
|---|---|---|
| a | Bullets `AGENTS.md:141-150` ("Lee PROJECT.md...", FLT...) cuelgan del `###` "Decision de proceso" por error de estructura: subirlos bajo `## Convenciones` antes del primer `###` | 0 B |
| b | `.session/repomix_local.xml`/`repomix_remote.xml` en "Rutas importantes": `.session/` no existe; solo los usa `skills/repo-compare/SKILL.md`, que ya los documenta | ~230 B |
| c | Linea Goose/Claw DEPRECATED (WT-2026-254a) -> `.agent/rules/common/backends_roles_detail.md` | ~190 B |
| d | Atribucion "Adaptado de ... `dify-agent`" (ya en `CREDITS.md`) | ~70 B |
| e | 71 caracteres no-ASCII (acentos/rayas) en un fichero por lo demas ASCII; 77 B extra | ~77 B |

Total ~570 B: financia P1-a y reduce el deficit Codex (no lo cierra: queda ~1.1 KB de deuda
declarada). Ningun test/script cita esos textos (grep verificado en `tests/` y `scripts/`).

## P3: CLAUDE.md y .claude/rules solo con pegamento Claude (gate Claude)

- a. `CLAUDE.md:9` version `v9.17.1` hardcodeada: `AGENTS.md:85` ya la sustituyo por "ver
  `PROJECT.md`"; incoherencia y caducidad. Quitar.
- b. `CLAUDE.md:14-22` (leer PROJECT.md, bootstrap prompt) duplican `AGENTS.md:141,144`.
  Ademas "lee `CHANGELOG.md` primero" = 164 KB por cambio no trivial: sustituir por "las
  entradas recientes". Dejar en CLAUDE.md solo: `@AGENTS.md`, nota de hooks/`paths:`,
  comandos slash.
- c. `.claude/rules/03-skills-discovery.md` y `04-refactor-kit.md`: anadir frontmatter
  `paths:` (`skills/**`, `scripts/discover_skills.py`; `agent_system/refactor_kit/**`) -> solo
  cargan al tocar esos ficheros. -2248 chars.
- d. `.claude/rules/05-session-artifacts.md` (3230) es contenido AGNOSTICO (cerrar ticket =
  traspaso backlog -> `_archive/backlog_done.md`) escondido en una ruta solo-Claude: moverlo a
  `.agent/rules/common/` (fusionar con `collaboration_live_surfaces.md`, ya enlazado desde
  `AGENTS.md:259`, coste Codex 0) y quitar la "Nota historica" sobre `.session/`.
- e. `.claude/rules/00-startup.md`: el flujo Manager->Builder y los quality gates duplican
  PROJECT.md/AGENTS.md; el imperativo de memoria pasa a AGENTS.md (P1). Queda solo el
  pegamento Claude (hook) o se elimina.
- f. `.claude/rules/README.md`: con `paths: [".claude/rules/**"]` solo carga al editar reglas.
- Estimado Claude: ~-8 k chars (cerraria el deficit de 7317), SIN contar el +33.6k del P0.
  Nota: con P0 aplicado el gate Claude (que no mide el hook) seguira sin reflejar la carga
  real; anotar como deuda del medidor, igual que TRAMPA-5.

## Fuera de alcance / deuda

- Recorte del indice de 60 entradas (tras medir P0 en vivo).
- Equivalente del hook para OpenCode/Kilo (plugin): no existe; el contrato agnostico cubre.
- Coordinacion con la sesion paralela `autonomo-dag-20261023` (alvarovans): su base es
  `e5f910b6` (mismo tree que origin/main `62e99493`, push no-FF trivial); merge-tree predice
  1 conflicto en `docs/registry/ROUTER.md` (generado: se regenera). Ya avisada.

## Orden de aplicacion propuesto

1. P0 (codigo + tests) -> 2. P1+P2 en el mismo commit (el gate Codex bloquea crecer) ->
3. P3 -> 4. memoria versionada de la leccion del hook -> 5. integracion con el push de la otra
sesion -> 6. suite `--level all` UNA vez al final -> 7. pedir autorizacion de push.

## RONDA 1 -- bucle adversarial (2026-10-23)

Lentes con veredicto real: codex gpt-5.6-luna (**CAMBIOS**), GLM 5.3 flash-free por OpenCode
directo (**APROBAR_CON_CAMBIOS**), Claude Sonnet 5.5 cuenta alvarovans (**APROBAR_CON_CAMBIOS**).
Mistral Large 4 en curso. Caidas sin veredicto (proveedor, no contenido): opencode-go/glm-5.3 y
opencode-go/kimi-k3 (colgados 25 min, cancelados), openrouter (sin credito), aihubmix (sin
saldo), google/gemini (sin API key). P0 confirmado por las 3 lentes.

Cada hallazgo verificado por el orquestador con comando propio antes de aceptarlo:

| # | Hallazgo (lente) | Verificacion | Cambio al diseno |
|---|---|---|---|
| 1 | Test P0 debe ejecutar el hook y afirmar `hookSpecificOutput.hookEventName`; caso negativo (codex) | n/a | Aceptado |
| 2 | No son 5 parseos: `["additionalContext"]` aparece 27 veces; `:978` y `:1013` asertan `set(out.keys()) == {"additionalContext"}` -- fijan la forma erronea (sonnet; glm vio la 6a en `:642`) | `grep` confirma 978/1013 y 27 apariciones | Invertir esos 2 tests, no solo actualizarlos |
| 3 | Test de contrato que muerda: claves de raiz subconjunto de las documentadas + parametrizar sobre todos los hooks JSON de `settings.json` (sonnet) | doc oficial | Aceptado; el control real del consumidor sigue siendo P0-c (transcript) |
| 4 | Partes fijas ~4.1k, no 3.7k (falta linea de salud); quedan ~5.2k = ~45-55 entradas de 483 (sonnet) | medicion del hook real | Presupuesto y suelo de entradas medidos por test sobre arbol real |
| 5 | La puerta `compact/resume/fork` tambien supera el tope (29.141 chars medidos) y pierde roles+M4/M5 (sonnet) | `echo {"source":"compact"}` -> 29141 | El recorte cubre AMBAS puertas |
| 6 | Ensamblador con prioridad: pista > roles > M4/M5 > salud > indice; solo el indice se recorta (sonnet) | `session_start_hook.py:397-409` lee M4/M5 sin tope | Aceptado |
| 7 | Presupuesto en `memory_loader` (`max_chars=None` por defecto), no en el hook, para que hook y `--bootstrap` no diverjan (sonnet) | n/a | Aceptado |
| 8 | Las lineas solo-titular no llevan `[truncated]`: la comprobacion por presencia de P1-a fallaria. Marcador = cabecera `# Portable Memory (tracked archive)` + pie "no mostrada(s)" (sonnet) | `orchestrator_session_bootstrap.md:42-44` | Reescribir el marcador en AGENTS.md y bootstrap |
| 9 | 78 de 483 lecciones sin `id`: la pista debe ofrecer `--query <topic>` (sonnet) | no re-medido | Aceptado |
| 10 | `00-startup.md:31` es la UNICA fuente de "scripts de un solo uso -> `tests/sandbox/debug_*.py`, nunca en la raiz" (glm) | `git grep` confirma unica | Rescatar en AGENTS.md Convenciones |
| 11 | Jerarquia de secretos (keyring/DPAPI -> SOPS+age -> OAuth) solo en `01-security-architecture.md`, invisible a Codex/OpenCode (glm) | `git grep keyring\|SOPS` en AGENTS.md y `.agent/rules/common`: 0 | Mover a `.agent/rules/common/` con puntero desde "Secretos y seguridad" |
| 12 | `test_memory_bootstrap_census.py::test_shared_doc_citado_por_tres_familias` exige que un `.claude/rules/*.md` cite `memory_bootstrap`; solo lo hace `00-startup.md` (sonnet) | `sed -n 152,171p` confirma | `00-startup.md` se conserva como pegamento Claude con esa cita |
| 13 | P2-c Goose viola fila 2 (codex) / premisa "no existe" falsa porque existe `orquestador.py` (glm) | `orquestador.py:3,12`: es el "Orquestador de skills v3.0"; Goose solo en comentario historico. Sonnet coincide: quitable | Se mantiene quitarla; ademas la linea es FALSA hoy ("motores orquestados por `orquestador.py`"). La frase se escribe en `backends_roles_detail.md` (no la menciona hoy) |
| 14 | P3-b: la lectura previa de CHANGELOG no esta en AGENTS.md (codex) | `AGENTS.md:447` solo la cita como destino | Pasa a AGENTS.md como "entradas recientes" |
| 15 | P3-d: el mandato "cerrar ticket = traspaso" + `check_backlog_contract.py` es fila 2/3 y debe quedar en AGENTS.md (codex); coste en bytes Codex declarado (sonnet) | `05-session-artifacts.md:28-31` | Aceptado; financiado con P2 |
| 16 | Fusionar en `collaboration_live_surfaces.md` obliga a regenerar `llms-full.txt` (`build_llms.py:137`) (sonnet) | n/a | Regenerar en el mismo commit |

Error de una lente descartado: sonnet cita `.claude/rules/02-multi-agent-system.md`, que en esta
rama ya no existe (leyo otro worktree); no afecta a sus conclusiones.

**Balance de bytes AGENTS.md tras R1:** P2 ahorra ~570 B; P1 (imperativo, propuesta glm 164 B
menos la linea actual) + #10 + #11 + #14 + #15 anaden ~600-700 B. Resultado aproximadamente
neutro: el gate "no crecer" obliga a medir antes del commit y, si sube, recortar mas (no hay
override). El deficit Codex de 1641 B sigue como deuda declarada.

| 17 | `tests/test_migration_bootstrap.py:629` lee `.claude/rules/00-startup.md` (mistral) | `sed -n 620,640p` confirma | Refuerza #12: `00-startup.md` no se borra |

Mistral Large 4 hizo verificaciones reales (orquestador.py = lanzador v3.0, consumidor #17) pero
su run termino SIN veredicto final; cuenta como evidencia parcial, no como voto.

## DISENO REVISADO tras R1 (objeto de la RONDA 2)

**P0 -- hook SessionStart (codigo):**
1. `bus/memory_loader.py`: parametro `max_chars: int | None = None` en `get_bootstrap_context`
   y `get_compact_context`. `None` = comportamiento actual (no rompe tests de formato). Con
   presupuesto: cabecera `# Portable Memory (tracked archive)` + lineas `id` + titular (las 78
   sin `id` -> titular + pista `--query <topic>`) hasta llenar el presupuesto + pie que declara
   cuantas NO se muestran. Mismo artefacto para el hook y para `--bootstrap`.
2. `.agent/hooks/session_start_hook.py`: ensamblador con prioridad pista > roles > M4/M5 >
   salud > indice; el indice recibe `max_chars = 9500 - len(partes_fijas)`; emite
   `{"hookSpecificOutput": {"hookEventName": <evento recibido>, "additionalContext": ...}}`.
   Aplica a startup Y a compact/resume/fork.
3. Tests: invertir `test_session_start_hook.py:978,1013`; actualizar los parseos de raiz;
   test de contrato (claves de raiz subconjunto de las documentadas + `hookEventName`),
   parametrizado sobre los hooks JSON de `.claude/settings.json`; test de presupuesto
   `len <= 9500` y suelo de entradas sobre el arbol real, para ambas puertas.
4. `memory_context.py --bootstrap`: decision abierta para R2 -- (a) mantener el corpus completo
   por defecto (backends sin hook reciben mas que Claude) o (b) emitir la forma acotada por
   defecto con `--full` opcional (simetria total; recomendada por sonnet).
5. Cierre: transcript de una sesion nueva con `hook_additional_context` que contenga la cabecera.
6. `pre_compact_hook.py`: deuda declarada (PreCompact no admite contexto segun la doc).

**P1 -- AGENTS.md (agnostico), reemplaza `AGENTS.md:356-357`:**
`- **Sin indice en tu contexto (cabecera "Portable Memory" + pie): ejecuta python scripts/memory_context.py --bootstrap; un hook solo lo sustituye si el indice queda visible.**`
Y alinear con el mismo marcador `prompts/orchestrator_session_bootstrap.md:41-45` y
`.claude/rules/00-startup.md`.

**P2 -- AGENTS.md, ahorro:** b (`.session/`), c (Goose: fuera; la frase correcta "Goose/Claw
retirados (WT-2026-254a); `scripts/orquestador.py` es hoy el lanzador de skills" se escribe en
`backends_roles_detail.md`), d (dify), e (ASCII), a (recolocar bullets, 0 B).

**P3 -- AGENTS.md, rescates agnosticos (cuestan bytes):** regla `tests/sandbox/debug_*.py`;
puntero a la jerarquia de secretos movida a `.agent/rules/common/secrets_hierarchy.md`;
"lee las entradas recientes de CHANGELOG"; mandato cerrar-ticket=traspaso +
`check_backlog_contract.py`.

**P4 -- solo-Claude:** `CLAUDE.md` sin version ni duplicados; `paths:` en 03, 04 y README;
05 -> `.agent/rules/common/` (fusion con `collaboration_live_surfaces.md` + regenerar llms);
`00-startup.md` reducido a pegamento con la cita a `memory_bootstrap` (exigida por 2 tests);
`01-security-architecture.md` reducido a lo especifico de Claude (hook `guard_paths`).

**Gate:** `AGENTS.md` no puede crecer (BLOCK sin override). Si P1+P3 superan el ahorro de P2,
recortar mas antes del commit; nunca forzar.

## RONDA 2 -- bucle adversarial (2026-10-23)

Veredictos: codex **CAMBIOS**, sonnet 5.5 (alvarovans) **APROBAR_CON_CAMBIOS**, GLM 5.3
flash-free **APROBAR_CON_CAMBIOS**. Consenso 3/3: Goose sale de AGENTS.md (codex y glm retiran su
objecion: `orquestador.py:3,12` = lanzador de skills v3.0, la linea `AGENTS.md:36` es falsa);
P0-4 = **(b) `--bootstrap` acotado por defecto + `--full`** (3/3).

| # | Hallazgo R2 (lente) | Verificacion | Decision |
|---|---|---|---|
| 18 | Fallback `session_start_hook.py:589` emite `{"additionalContext": ""}` en la raiz (codex, sonnet) | `grep` confirma | Migrar tambien |
| 19 | `hookEventName` literal `"SessionStart"`, no derivado del payload (codex, sonnet) | matcher `""` en settings | Fijo |
| 20 | El recorte por chars newest-first puede desalojar un origen (motor/destino): regresion del fallo que 057a arreglo con `_cap_preserving_origins` (sonnet, BLOQUEA el diseno) | `memory_loader.py:693` | Recorte DESPUES del reparto por origen; test con 2 origenes |
| 21 | El presupuesto no cubre `local` (L3/L2/L1) ni "Refutadas o supersedidas"; `get_bootstrap_context` concatena sin limite comun (codex, sonnet) | `memory_loader.py:799-816` confirma | El limite aplica al string final |
| 22 | Formato "solo titular" sin especificar (sonnet) | `_format_archive_line` trunca a 320 | Especificado abajo |
| 23 | M4/M5 y `_health_line` sin tope: el indice puede quedar a 0 (sonnet) | `session_start_hook.py:397-409` | Suelo + test rojo |
| 24 | Los dobles `lambda:` sin args de los tests del hook rompen al pasar `max_chars` (codex) | `test_session_start_hook.py:959,964,994,999` | Actualizar dobles |
| 25 | `check_claude_settings_portability.py:98-100` codifica "PreCompact emite additionalContext" (sonnet) | no re-verificado | Entra en la deuda PreCompact |
| 26 | Margen bajo 10k: medir con el JSON real o bajar a ~9k (sonnet) | doc: cap por string | Tope total 9.000 |
| 27 | Cierre P0-c debe ver roles y M4/M5 en el transcript, no solo "algo" (sonnet) | n/a | Aceptado |
| 28 | Textos a reescribir con (b): `memory_bootstrap.md:27-29`, ayuda `memory_context.py:7,71,546` (cifras 207/342 caducas) (sonnet) | n/a | Aceptado |
| 29 | Mas agnostico solo-Claude en `01-security-architecture.md`: politica pip-audit "sin mitigacion o doc en PROJECT.md" (`:35`), allowlist de lectura remota (`:40-41`), privada/.env.example/REDACTED (`:17-25`) (glm) | `sed` + `git grep mitigaci`: 0 fuera | Ver P4 revisado |
| 30 | `05`: la regla "solo el controller/supervisor materializa TURN.md" debe viajar (glm) | `05:34-36` | Ver P4 revisado |
| 31 | `00-startup.md` no debe heredar "~30k duplicados" ni "el hook inyecta" (glm) | n/a | Aceptado |

## DISENO v3 (objeto de la RONDA 3, solo P0-presupuesto y P4)

**P0 presupuesto (resuelve 20-24, 26):**
- Una constante `INDEX_BUDGET_CHARS` (p.ej. 4.500) en `bus/memory_loader.py`, usada por el hook
  Y por `--bootstrap` (mismo formateador, mismo indice: "mismo artefacto" literal).
- `get_bootstrap_context(max_chars=None)` / `get_compact_context(max_chars=None)`: `None` =
  comportamiento actual. Con valor: (1) `_cap_preserving_origins` como hoy; (2) render compacto
  por entrada: `- <id>: <senal cortada a 100 chars>` o, sin `id`, `- <topic> (usa --recall --query)`;
  (3) si no cabe, se descartan entradas de la cola MAS ANTIGUA de cada origen alternando origenes
  (nunca se vacia un origen mientras el otro conserve mas de su cuota proporcional); (4) `local`
  (L3/L2/L1) y "Refutadas" reciben sub-tope fijo con marcador de corte; (5) cabecera + pie
  siempre presentes; `assert len(result) <= max_chars`.
- Hook: total = pista + roles + M4/M5 + salud(tope 400) + indice(`INDEX_BUDGET_CHARS`); test
  sobre el arbol real: `total <= 9.000` y `entradas_mostradas >= suelo` (p.ej. 30), ambas puertas.
  Si las partes fijas crecen y rompen el total, el test falla en rojo nombrando la parte.
- `--bootstrap` por defecto = misma forma acotada; `--full` = corpus actual.

**P4 revisado (resuelve 29-31):** en vez de rescatar frases sueltas, MOVER ENTEROS a
`.agent/rules/common/` el contenido agnostico de `01-security-architecture.md` (jerarquia,
privada/.env.example/REDACTED, politica pip-audit, state drift, allowlist remota) y de
`05-session-artifacts.md` (incluida la regla de TURN.md), dejando en `.claude/rules/` solo el
pegamento Claude (hook `guard_paths`) y punteros. En `AGENTS.md` solo los mandatos de fila 2/3
(cierre de ticket + comando; secretos ya estan en "Secretos y seguridad") con puntero.

## RONDA 3 -- bucle adversarial (2026-10-23)

Veredictos: codex **CAMBIOS** (omisiones de redaccion de la v3 + P4 debe respetar PASO 2),
sonnet 5.5 alvarovans **APROBAR_CON_CAMBIOS** (medido contra el hook real en 24a8827b).

| # | Hallazgo R3 (lente) | Decision |
|---|---|---|
| 32 | La v3 debe repetir explicitamente filas 18, 19, 24 (fallback :596, `hookEventName` literal en todas las puertas, dobles `lambda`) (codex) | Aceptado: el diseno final es autosuficiente |
| 33 | El limite se verifica sobre el payload final emitido; funcion de presupuesto exacta; tests corpus vacio / 1 origen / 2 origenes / local grande; tests CLI `--bootstrap` acotado y `--full` (codex) | Aceptado |
| 34 | P4 "mover enteros" viola PASO 2: las prohibiciones duras deben seguir siempre cargadas (codex) | Aceptado: una linea por prohibicion en AGENTS.md; solo el detalle se mueve |
| 35 | Reusar `_cap_preserving_origins(vigent, N)` buscando el mayor N cuyo render cabe, en vez de un algoritmo nuevo de alternancia (sonnet) | Aceptado |
| 36 | NO `assert` en produccion: el hook captura `Exception` y un desborde de bytes acabaria en memoria vacia; recorte duro no lanzante, assert solo en test (sonnet) | Aceptado |
| 37 | Medido: `- <id>: <senal 100>` con 4.500 = 25 entradas (suelo 30 inalcanzable). Senal 60 + cabecera minima = ~33-35. Suelo 25; con 2 origenes >=10 cada uno (sonnet) | Aceptado |
| 38 | Sub-topes: local <= ~800, Refutadas <= ~400; test con `local` no vacio (sonnet) | Aceptado |
| 39 | Partes fijas medidas 4.142 (M4/M5 = 3.347, 81%); margen 158-358 B bajo 9.000; tope a M4/M5 con fallback (sonnet) | Aceptado |
| 40 | Sin id: `- <topic>: <senal 60> (--recall --query <topic>)` (sonnet) | Aceptado |
| 41 | Archive: 483 entradas pero 398 dedup_key distintos (85 duplicados exactos): la cabecera "483 lesson(s)" esta inflada (sonnet) | Deuda / candidato para la pasada de repos de referencia |
| 42 | Ficheros nuevos de `.agent/rules/common/` deben darse de alta en `MANIFEST.distribute` y `build_llms.py`; `check_distribution_boundary` no detecta ficheros no listados: test que muerda (sonnet) | Aceptado |

**Tension a decidir con el usuario:** el indice acotado muestra ~33 entradas frente a las 60
truncadas actuales. Para Claude es una ganancia neta (hoy recibe 0). Para backends sin hook que
ejecutan `--bootstrap` es una reduccion, compensada por `--recall` (obligatorio) y `--full`.

## REFERENCIAS EXTERNAS -- /repo-compare de 7 repos (2026-10-23)

Informes (gitignored) en `.agent/runtime/compare/`: mem0ai-mem0-2c81af3, MemPalace-mempalace-f41e8e7,
vectorize-io-hindsight-35451e5, pingcap-tidb-ab30f36, volcengine-OpenViking-2260f68 (AGPL: solo
patron), supermemoryai-supermemory-f300151, rohitg00-agentmemory-1c99508. Todos 4/5 en el filtro
(pierden "encaje tecnico": vector DB/LLM/TS/Go); lo portable son patrones stdlib.

**Convergencias (>=2 repos independientes):**
- Esquema `hookSpecificOutput.hookEventName="SessionStart"` (mem0, hindsight, OpenViking, agentmemory) -> confirma P0.
- Llenado por lineas enteras dentro del presupuesto, pie con recuento y comando de expansion (MemPalace, supermemory, agentmemory, OpenViking) -> confirma filas 35-37.
- Bloque delimitado "datos, no instrucciones" (supermemory, agentmemory) -> nuevo marcador de presencia.
- Fallo del hook nunca silencioso (MemPalace: emite "ejecuta --bootstrap"; hindsight: error visible) -> sustituye el `{"additionalContext": ""}` de :596.
- Copia/registro local de lo inyectado (mem0, OpenViking) -> habria delatado el P0.
- Orden por algo mas que recencia: carril estable (supermemory, `memory_class`) y decaimiento/calor por uso (MemPalace, OpenViking, agentmemory).
- Ciclo de vida de lecciones: `valid_until` (mem0, supermemory), refuerzo en vez de duplicado (agentmemory, supermemory), casi-duplicados Jaccard en dry-run (agentmemory), "una leccion recuperada es hipotesis: actualiza la existente" (TiDB).
- Recuperacion por relevancia en el primer prompt (mem0, hindsight) -> Claude-only, fase 2.
- Continuidad al cerrar: resumen determinista SessionEnd (agentmemory), recordatorio de checkpoint (MemPalace), documento de continuidad con secciones fijas (OpenViking), "Surprises & Discoveries" (TiDB).

**Defectos locales descubiertos de paso:** `memory_context.py:309` corta TODO el recall al primer
item que no cabe (hindsight); 0 de 483 entradas usan refuted/superseded (supermemory); solo 26/483
llevan `memory_class` (supermemory); 85 duplicados exactos (sonnet R3); titulares cortados a mitad
de palabra `memory_loader.py:761` (supermemory).

## DISENO v4 (propuesto tras referencias externas)

Cambios sobre v3 dentro del alcance actual:
1. Indice de arranque en DOS CARRILES: estable (lecciones `memory_class` estable, cupo fijo) +
   reciente (resto, por `_cap_preserving_origins` con busqueda de N). Cuando no cabe `id: titular`,
   las restantes vigentes pasan a solo `id` en una linea compacta, y el pie publica tres recuentos
   (con titular / solo id / omitidas) + comando `--recall`. Resuelve la tension 33-vs-60: ninguna
   leccion vigente queda invisible.
2. Corte en limite de palabra; lineas enteras o nada.
3. Bloque `<memory-index readonly>` ... `</memory-index>`: marcador de presencia unico para el hook,
   `--bootstrap` y AGENTS.md P1 (sustituye "cabecera + pie").
4. Fallo del hook: nunca vacio; emite el imperativo agnostico "no se pudo cargar la memoria: ejecuta
   `python scripts/memory_context.py --bootstrap`" + `systemMessage` visible.
5. Registro local de lo inyectado (`.agent/runtime/` gitignored: chars, entradas, carriles, sha del
   archive) -> barrera observable contra otro P0 silencioso.
6. Pista de expansion con momentos nombrados (informe de fallo, antes de escribir test, antes de
   commit, antes de disenar) en vez de la orden generica.
7. Fix pequeno: `memory_context.py:309` salta el item que no cabe y sigue.
8. Test: `--recall` encuentra lecciones que NO estan en el indice acotado.

Fuera de alcance -> backlog (largo plazo, cada uno con medicion previa): ciclo de vida
(`valid_until`, refuerzo, dedupe de los 85, Jaccard dry-run, uso real de refuted/superseded);
orden por calor/uso (empezar registrando expansiones); hook `UserPromptSubmit` de recall por
relevancia (Claude-only, refuerzo opcional); resumen determinista en SessionEnd citado por el
siguiente SessionStart; resumen intermedio por dominio (nivel L1 de OpenViking); AGENTS.md por
subarbol (TiDB; verificar soporte en Kilo/OpenCode).

## PASADA DE REVISION sobre v4 (2026-10-23) -- errores encontrados

Medido sobre el archive real (483 entradas, HEAD 24a8827b) antes de proponer v5:

| # | Error / mejora en v4 | Evidencia | Correccion |
|---|---|---|---|
| E1 | "Ninguna leccion vigente queda invisible" es FALSO: un carril "solo id" para todas las lecciones ocupa 18.415 chars (405 ids, media 43,5 chars); no cabe en 4.500 | calculo sobre el archive | El carril solo-id llena el hueco restante y el pie declara las omitidas; la promesa es "nada se pierde EN SILENCIO", no "todo se ve" |
| E2 | El carril estable no tiene cupo: las 26 entradas con `memory_class` (19 `contrato-operativo`, 5 `arquitectura-estable`, 1 `governance-rule`, 1 `operational-rule`) a ~110 chars = ~2.900, el 64% del indice | Counter sobre `memory_class` | Cupo fijo del carril estable (<= 8 lineas, mas recientes dentro de la clase); el resto del cupo, al carril reciente |
| E3 | "El registro local de lo inyectado habria delatado el P0" es FALSO: el hook SI emitia 33k; lo descartaba el CONSUMIDOR. Un log del emisor habria dicho "todo bien" | censo de transcripts: 577 `hook_success` con stdout lleno, 0 `hook_additional_context` | El detector real es el lado consumidor: diagnostico `scripts/check_hook_delivery.py` (Claude-only, WARN, nunca gate) que busca `hook_additional_context` del SessionStart en el transcript mas reciente. El log del emisor pasa a backlog (no aporta deteccion) |
| E4 | El registro local escribiria desde un hook cuyo contrato es "Solo lectura; ninguna escritura" (`session_start_hook.py:66`) | docstring | Con E3, se elimina del alcance: el contrato del hook no cambia |
| E5 | Los repos discrepan en la ruta de fallo: MemPalace/hindsight emiten aviso; agentmemory imprime nada y sale 0 | informes | Se mantiene emitir el imperativo agnostico corto (<200 chars): es lo unico que convierte un fallo en accion para cualquier backend |
| E6 | 0 de 483 entradas usan `status` refuted/superseded; 84 duplicados exactos por (topic, signal) | Counter | Confirma que el ciclo de vida es deuda real -> backlog con prioridad alta, no "algun dia" |
| E7 | `memory_context.py:309`: `if omitted or ...` omite TODO lo posterior al primer item que no cabe | lectura | Fix en alcance (1 linea + test) |
| E8 | La cifra 32,5%->72,5% (hindsight) es del propio vendor, 40 turnos | informe | Se adopta la idea (momentos nombrados, coste ~0) sin citar la cifra como evidencia |
| E9 | Las 7 comparaciones las hicieron subagentes de una sola familia de modelo; solo re-verifique lo que entra en alcance | -- | Limite declarado; el bucle de v5 lo cubre con lentes de otra familia |
| E10 | Alcance: el vuelo ya lleva 44 commits sin publicar; P0+v4 (loader, hook, CLI, tests, docs) es otro cambio grande | `git rev-list` | Dos bloques de commits en el mismo vuelo: T1 docs agnosticos (P1-P4), T2 hook+loader (P0+v5); suite --level all UNA vez al final; un push |

## DISENO v5 (objeto del bucle)

**T2 -- hook + loader (P0):**
1. Esquema `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...}}` en
   todas las puertas y en el fallback; tests :978/:1013 invertidos; test de contrato (claves de raiz
   documentadas) con caso negativo; dobles `lambda` actualizados.
2. Ensamblador: pista con momentos nombrados > roles > M4/M5 (tope + fallback) > salud (tope 400) >
   indice. Total <= 9.000 sobre el payload final; recorte duro no lanzante; assert solo en tests.
3. Indice (constante `INDEX_BUDGET_CHARS` compartida hook/CLI, mismo formateador):
   `<memory-index readonly>` + cabecera minima; carril estable (`memory_class` presente, <= 8
   lineas); carril reciente via `_cap_preserving_origins(vigent, N)` buscando el mayor N que cabe;
   linea `- <id>: <senal 60, corte en palabra>` o `- <topic>: <senal 60> (--recall --query <topic>)`;
   hueco sobrante -> linea compacta de ids; pie con recuentos (titular / solo id / omitidas) +
   comando; sub-topes local <= 800 y Refutadas <= 400; suelo 25 (>= 10 por origen con 2 origenes).
4. `--bootstrap` acotado por defecto, `--full` = corpus actual; textos y ayuda actualizados.
5. Fallo: imperativo agnostico corto ("memoria no cargada: ejecuta `python scripts/memory_context.py
   --bootstrap`") + `systemMessage`.
6. Fix `memory_context.py:309` + test; test "`--recall` encuentra lecciones fuera del indice".
7. `scripts/check_hook_delivery.py` (WARN, Claude-only) + cierre P0-c: transcript nuevo con
   `hook_additional_context` que contenga `<memory-index` Y roles Y M4/M5.

**T1 -- docs agnosticos:** P1 (imperativo con marcador `<memory-index>`), P2 (ahorro), P3/P4 con
prohibiciones duras en AGENTS.md (una linea cada una) y detalle a `.agent/rules/common/` dado de
alta en `MANIFEST.distribute` + `build_llms.py`; `00-startup.md` como pegamento con la cita a
`memory_bootstrap`; medir el gate antes del commit.

**Backlog (largo plazo, con medicion previa):** ciclo de vida (E6: `valid_until`, refuerzo, dedupe
de los 84, Jaccard dry-run, usar refuted/superseded, "leccion = hipotesis"); registro de
expansiones para orden por uso; resumen determinista en SessionEnd citado por el siguiente
arranque; recall por relevancia en `UserPromptSubmit` (Claude-only); L1 por dominio; AGENTS.md por
subarbol (verificar Kilo/OpenCode).

## RONDA 4 -- bucle sobre v5 (2026-10-23)

4 lentes: codex CAMBIOS, kilo/nan/deepseek-v4-flash CAMBIOS, sonnet (cuenta alvarovans)
APROBAR_CON_CAMBIOS, opencode/glm-5.3 APROBAR_CON_CAMBIOS. Sin BLOQUEANTE. Verificado por el
orquestador leyendo codigo o grep (HEAD 24a8827b): #45, #50, #54.

| # | Lente | Hallazgo | Veredicto orquestador |
|---|---|---|---|
| 43 | glm | El imperativo de AGENTS.md DELETREA `<memory-index readonly>`: un backend sin hook encuentra el literal en la propia instruccion y nunca ejecuta `--bootstrap` (falso positivo permanente) | ACEPTADO, critico. Regla: ninguna superficie siempre-cargada contiene el substring emitido; se describe, no se deletrea. Test que lo asserta |
| 44 | glm | Texto del imperativo sin tag: 126 B, neto +29 B | ACEPTADO |
| 45 | glm, kilo | Quedan marcadores `[truncated]` obsoletos: AGENTS.md:346, `templates/startup/builder_{kilo,codex}.md:3`, `prompts/_shared/memory_bootstrap.md:27`, `orchestrator_session_bootstrap.md:42` | ACEPTADO (verificado grep). DoD: grep vacio sobre esas rutas |
| 46 | glm | `--full` sin envoltorio provoca recarga doble | ACEPTADO: `--full` emite el mismo envoltorio |
| 47 | glm, kilo | El pie debe ofrecer enumeracion (`--full`) y decir "esto es indice: expande antes de disenar" | ACEPTADO |
| 48 | glm | Declarar que para backends sin hook el detector es la comprobacion por presencia | ACEPTADO, una frase |
| 49 | glm, kilo | `--bootstrap` CLI no entrega roles, M4/M5 ni la pista de momentos: el backend sin hook recibe la version pobre | ACEPTADO: el ensamblador completo se mueve a `bus/memory_loader.py`; hook y CLI lo llaman igual |
| 50 | kilo | Superficies de despacho Kilo no ordenan cargar memoria: `dispatch_builder/revisor.template.md` (0 menciones), `builder_invocation_contract.md:75-83`, `orchestrator_launch_builder.md:221-242` (afirma que el padre "recibio el indice automaticamente", :224) | ACEPTADO (verificado grep): T1 las edita; paso 0 = `--bootstrap`, luego `--recall` |
| 51 | kilo | Barrera agnostica: `check_builder_dispatch_prompt.py --require-memory-bootstrap` (hoy WARN) + censo `memory_bootstrap_census.py` ampliado a `templates/startup/` y `prompts/kilo_trio_dispatch/` | ACEPTADO (barrera de forma del prompt de despacho). Recibo `--receipt`: APLAZADO (prueba emision, no lectura) |
| 52 | sonnet | Carril solo-id vestigial: "mayor N que cabe" deja 0-2 ids | ACEPTADO: se ELIMINA; el pie da recuentos + `--full` |
| 53 | sonnet | Archive sin deduplicar (398 dedup_key / 483; carril estable rinde 6 de 8) | ACEPTADO: dedup por `dedup_key` antes de carriles y recuentos |
| 54 | sonnet | `_cap_preserving_origins` devuelve SIN ordenar y SIN filtrar plantillas en las ramas `len<=cap` (:483) y `flat<=cap` (:520-522) | ACEPTADO, verificado leyendo codigo. Fix: filtrar y ordenar en toda salida; test de orden con 2 origenes |
| 55 | sonnet | Carril estable congelado (memory_class solo 06-07..07-18; 19/26 misma clase) | ACEPTADO: cupo 5, diversificado por topic, documentado como "solo ve lo etiquetado" |
| 56 | sonnet | Puerta compacta (resume/compact, 29.315 chars medidos) no acotada en v5 | ACEPTADO: mismo ensamblador para `get_compact_context`; test por `source` startup/resume/compact |
| 57 | sonnet | `check_hook_delivery.py`: filtrar por `attachment.type`+`hookEvent`, `content` es lista; casar por `cwd` registrado, no por slug ni mtime; respetar `CLAUDE_CONFIG_DIR`; distinguir "sin transcript" de "sin attachment" | ACEPTADO como spec del checker |
| 58 | sonnet | Presupuesto 4.300; tope en el total 9.000 | ACEPTADO: `INDEX_BUDGET_CHARS = 4300`, total <= 9000 asertado sobre el payload |
| 59 | sonnet | Corpus vacio != fallo de carga | ACEPTADO: mensajes distintos |
| 60 | codex | Nombrar funcion de presupuesto + tests de borde (vacio, 1 origen, 2 origenes, local grande) + tests CLI `--bootstrap`/`--full` | ACEPTADO |
| 61 | codex | P4 conserva tambien refutaciones y comandos operativos, no solo prohibiciones | ACEPTADO |
| 62 | codex | `check_hook_delivery.py` sin cablear = norma | ACEPTADO: cableado WARN en `prepush_check` + `guard_wiring_policy.yaml` |
| 63 | codex, kilo | Suelos `min(25, disponibles)` y `min(10, disponibles por origen)` | ACEPTADO |

## DISENO v6 (consolida R4)

**T2 -- codigo (hook + loader + CLI):**
1. Hook emite `hookSpecificOutput.hookEventName/additionalContext` en todos los caminos, incluido el
   fallback; invertir tests :978/:1013; test de contrato con caso negativo; actualizar dobles lambda.
2. `bus/memory_loader.py::assemble_session_context(source)`: UN ensamblador para hook (startup,
   resume, compact) y CLI. Orden: pista de momentos > roles > M4/M5 (tope + fallback) > salud (tope
   400) > indice. Total <= 9000 sobre el payload final; recorte duro sin excepcion (assert solo en tests).
3. Indice (`format_memory_index(budget=INDEX_BUDGET_CHARS)`, 4300): dedup por `dedup_key`; envoltorio
   `<memory-index readonly>`; carril estable cupo 5 diversificado por topic; carril reciente con
   `_cap_preserving_origins` corregido, excluyendo las estables; lineas
   `- <id>: <signal 60 a frontera de palabra>` o `- <topic>: ... (--recall --query <topic>)`; SIN
   carril solo-id; pie con "esto es un indice; expande con --recall antes de disenar", recuentos
   (mostradas / omitidas con id / omitidas sin id) y `--full`. Suelos min(25, disp.) y min(10, disp. por origen).
4. `memory_context.py --bootstrap` = ensamblador acotado; `--full` = corpus entero en el mismo
   envoltorio; arreglar :309; test de que `--recall` encuentra lecciones fuera del indice.
5. Fallo != vacio: mensajes distintos; el fallo emite el imperativo agnostico + `systemMessage`.
6. `scripts/check_hook_delivery.py` (Claude-only, WARN) con la spec #57, cableado en `prepush_check`
   + `guard_wiring_policy.yaml`. Evidencia de cierre: transcript con `<memory-index`, roles y M4/M5.
7. `check_builder_dispatch_prompt.py --require-memory-bootstrap` y censo ampliado.
8. Tests: bordes, orden newest-first con 2 origenes, `source` x3, CLI `--bootstrap/--full`, y
   "ninguna superficie siempre-cargada contiene `<memory-index`".

**T1 -- docs:**
1. Imperativo en AGENTS.md sin deletrear el tag: "Si tu contexto no trae el bloque delimitado del
   indice de memoria: ejecuta `python scripts/memory_context.py --bootstrap`." Reescribir AGENTS.md:345-347.
2. Mismo paso 0 en `templates/startup/builder_{kilo,codex}.md`, `kilo_trio_dispatch/dispatch_{builder,revisor}`,
   `builder_invocation_contract.md:75-83`, `orchestrator_launch_builder.md:221-242`,
   `_shared/memory_bootstrap.md:27`, `orchestrator_session_bootstrap.md:41-45`. DoD: grep `truncated` vacio.
3. Ahorros P2 (`.session`, Goose, dify, ASCII, reubicaciones); prohibiciones, refutaciones y comandos
   operativos quedan en AGENTS.md una linea cada uno; detalle a `.agent/rules/common/` registrado en
   MANIFEST.distribute y build_llms.py. `00-startup.md` se mantiene como pegamento.
4. Frase: para backends sin hook, el detector de entrega es la comprobacion por presencia.

**Orden:** T2 y T1 en commits separados, suite canonica UNA vez al final, `tested_commit_sha == HEAD`,
aviso a la sesion alvarovans, push solo con autorizacion.

**Backlog:** recibo `--receipt`; ciclo de vida de lecciones; registro de uso; resumen SessionEnd;
recall en UserPromptSubmit; L1 por dominio; AGENTS.md por subarbol; proveedor nan en el Kilo de T3.
