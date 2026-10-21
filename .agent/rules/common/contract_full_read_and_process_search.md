### Prompt/contrato citado => LEELO ENTERO antes de redactar contra el (2026-07-29)

**Norma dura, no consejo.** Si un prompt te lo pegan en el chat, lo enlaza otro prompt que te
pegaron, o un proceso lo declara como su contrato, **lo abres y lo lees ENTERO antes de producir
nada que se mida contra el**. `grep` dirigido, `diff` contra otra copia y lectura de la seccion que
creias relevante **NO cuentan como leerlo**: son muestreo, y el muestreo no puede ver lo que OMITES.

- **El grep responde tu pregunta, no la del contrato.** Solo encuentra lo que ya sospechabas que
  estaba; las clausulas que no imaginaste son justo las que no vas a grepear.
- **Es aplicacion directa de M4** (`prompts/orchestrator_launch_builder.md:140-155`, *"validador
  citado => ejecutalo antes de redactar"*) a la superficie NORMATIVA: si un validador ejecutable
  define el formato de un artefacto, un contrato define el formato de un PROCESO. M4 cubria solo lo
  primero; esta norma cierra lo segundo.
- **Coste medido y asumible:** los 7 prompts canonicos del pipeline suman ~2400 lineas. Es
  drasticamente mas barato que el fallo que evita.
- **Enrutar NO exime de leer.** Este repo prohibe re-declarar criterios normativos (*"skill apunta,
  prompt gobierna"*): sigues sin copiarlos, pero **no puedes enrutar hacia un contrato que no has
  leido** -- no sabrias que clausulas existen para nombrarlas.
- **Si decides NO leer entero, DECLARALO ANTES** con su motivo y su riesgo. Un muestreo declarado es
  una decision; un muestreo silencioso que se presenta como cobertura es `falso_verde`.

**Fallo real que la origina (2026-07-29, cazado por el USUARIO, no por el bucle):** se redacto el
prompt de arranque de un vuelo trabajando `prompts/orchestrator_autonomous_ticket_batch.md` (571
lineas) por grep + diff, sin abrirlo entero. Quedaron fuera `:193-220` (un `MANAGER_REVIEW` **por
ticket** y la forma exacta `1->9->2` con lector-FS obligatorio), `:355-380` (`GROUP_STOP_REPORT`) y
`:439-462` (cierre bloqueante: `batch_run_<ts>.json` + auditoria hermana + condicion 6
dual-contract). El prompt resultante decia *"antes de CADA fan-out emite el nonce"* sin decir cuantos
ni cuando, y `MANAGER_REVIEW` aparecia **0 veces**: un ejecutor podia implementar dos tickets, correr
UN bucle al final y creerse conforme.

**Agravante que hace la norma insuficiente por si sola:** ese prompt SE PASO por un bucle de 4 lentes
y **ninguna lo cazo**, porque a las lentes se les paso el contrato **por REFERENCIA (rutas), no por
CONTENIDO**: solo podian auditar coherencia interna. La barrera complementaria -- que el recolector
meta el contenido del contrato EN el bundle -- esta fichada como `WOT-2026-042y`. Lo predijo, literal,
una leccion que ya estaba en memoria: `obs-api-only-reader-reads-current-state-not-ought-to-be`
(*"un review multi-backend necesita un lector-con-filesystem o un bundle que incluya la semantica
explicita"*).

### Decision de proceso sin instruccion exacta => BUSCA protocolo documentado antes de suponer uno (2026-10-14)

**Norma con barrera de FORMA parcial desde 2026-10-18 (WOT-2026-104b)**, no barrera
semantica: `scripts/check_process_decision_search.py` (cableado como hook pre-commit en
el motor sobre `prompts/**/*.md`, `.claude/rules/**/*.md`, `AGENTS.md`, `CLAUDE.md`, y como
hook pre-push en el destino sobre `.agent/planning/*.md`/`STRATEGY_WOT-*.md` CAMBIADOS en
el rango a publicar) bloquea un artefacto que se AUTODECLARA con el marcador
`DECISION DE PROCESO:` si no declara ademas una seccion `BUSQUEDA-PREVIA:` valida
(`PROTOCOLO ENCONTRADO: <ruta>` / `NO ENCONTRE PROTOCOLO` / `EXCEPCION: trivial
<justificacion>`). **Limite declarado, no oculto:** verifica que la propiedad este
DECLARADA, no que sea VERAZ -- mismo patron de `check_loop_bundle_protocol.py` --, y NO
detecta una decision de proceso que el autor no etiquete con el marcador explicito: ese
sigue siendo el modo de fallo n=3/n=4 de abajo, sin barrera mecanica. Es la regla hermana
ANTERIOR de la regla de arriba, no su generalizacion: aquella exige leer entero un contrato YA
CITADO; esta exige BUSCAR si existe uno ANTES de suponer que no hay ninguno. Son dos eslabones
secuenciales de la misma cadena (buscar -> si se encuentra, leer entero), no una conteniendo a
la otra.

**Antes de tratar de resolver una decision de proceso por razonamiento propio, el agente
comprueba primero si existe un protocolo YA ESCRITO para ese caso.** Comprobacion minima:
(a) `grep`/busqueda por palabra clave en `AGENTS.md` y en los prompts de `prompts/` cuyo nombre
sugiere el dominio (p.ej. `*_loop.md`, `*_invocation_contract.md`, `*_closeout*.md`);
(b) `python scripts/memory_context.py --recall --query <termino>` sobre la memoria portable,
que indexa precisamente casos medidos de este tipo; (c) si el dominio tiene un `contract_id`
conocido o sospechado, leerlo ENTERO (aplica la regla de arriba).

**Declaracion explicita cuando no se encuentra nada:** si la busqueda no encuentra protocolo
aplicable, el agente lo declara ("busque en X, Y, Z; no encontre protocolo para este caso")
antes de proponer su propia solucion ad-hoc.

**No aplica a:** decisiones triviales sin ambiguedad de proceso (un typo, una pregunta de hecho
verificable con una sola lectura), ni a tareas ya en curso bajo un contrato ya verificado en la
misma sesion. **Declaracion simetrica:** quien invoque esta excepcion de trivialidad debe
declararlo en una linea antes de proceder ("EXCEPCION: trivial -- X no es decision de proceso
porque Y"), igual que la declaracion exigida cuando no se encuentra protocolo. Sin esa
declaracion, la excepcion no aplica.

**¿Que cuenta como decision de proceso?** SI cuenta: decisiones sobre dispatch de
Builder/Revisor, merge/push a rama compartida, gates de cierre/closeout, formato de memoria o
bitacora, criterios de fusion de roles, cualquier decision que otro agente en otra sesion pueda
necesitar replicar. NO cuenta: correccion ortografica, pregunta de hecho verificable con una
sola lectura de fichero, eleccion de nombre de variable o formato de commit sin convencion
previa declarada.

**Evidencia (n=3, tres sesiones independientes, mismo patron):** (1) 2026-09-26, dispatch plano
sin `loop_id`/`nonce` para una decision de cierre de sesion, corregido solo cuando el usuario
pidio explicitamente revisar `ensemble_loop.md` (`obs-ensemble-adhoc-abbreviation-must-be-declared-before-dispatch`);
(2) 2026-10-07, un revisor nan se dejo de ejecutar en 3 de 14 vuelos sin que nadie declarara la
desviacion (`obs-removing-a-control-stage-must-be-declared-and-attributed`); (3) 2026-10-14,
propuesta de politica de suite/merge redactada sin comprobar antes si `builder_invocation_contract.md`
o `ensemble_loop.md` ya cubrian el caso. Las tres correcciones ocurrieron solo por intervencion
explicita del usuario, nunca por iniciativa del propio agente -- confianza media, no ley
universal, pero suficiente para justificar esta norma con deuda de barrera declarada. (4)
2026-10-18, dispatch de un batch del bucle ensemble con timeout de background de 300000ms
sin comprobar antes `backends.kilo.timeout_s` en `agents.json` (declarado 900s), pese a
haber leido `prompts/ensemble_loop.md` Seccion 3.10 entera en la MISMA sesion -- 4 rondas
murieron por limite de tiempo y tuvieron que relanzarse; corregido solo cuando el usuario
pregunto directamente por el incumplimiento. Las cuatro correcciones ocurrieron solo por
intervencion explicita del usuario, nunca por iniciativa del propio agente.

**Candidato de barrera implementado PARCIALMENTE (WOT-2026-104b, 2026-10-18):**
`check_process_decision_search.py` (ver arriba) NO es el candidato original ("auditar
automaticamente una propuesta de proceso nueva contra los `contract_id`s declarados en
`prompts/`") -- ese candidato exigiria deteccion de INTENCION (que un texto ES una
decision de proceso sin que el autor lo declare), que sigue sin existir y sigue fuera de
alcance (no hay oraculo para eso sin juicio humano). Lo que SI existe es un mecanismo mas
debil: sube el coste de redactar una decision de proceso SIN declarar su busqueda previa,
de cero a tener que escribir una frase -- no lo elimina. Riesgo de performatividad
declarado: un agente puede escribir `BUSQUEDA-PREVIA: NO ENCONTRE PROTOCOLO` sin haber
buscado de verdad, o citar una ruta inventada en `PROTOCOLO ENCONTRADO:`; el guard no lo
detecta (barrera de FORMA, no de VERDAD). Mientras no exista deteccion de intencion ni
verificacion de veracidad, ambos riesgos permanecen abiertos.
