# DEC-bucle-doc-001: Ancla de identidad de un bucle de gobierno sobre un DOCUMENTO

**Ticket:** escalado `FP-20260907 escalado-crear-texto-llm bucle-no-auditable` (ficha en el inbox del destino de dogfooding; el fusionador asigna id)
**Fecha:** 2026-09-07
**Estado:** PROPOSED -- pendiente de FIRMA del operador (dos bloques al final: ancla y triage)
**Autor:** sesion de cierre del motor (Claude Code), recusada de firmar: es parte interesada (sus propios bucles L730/L731/L732 son parte del caso medido)
**Auditada por:** bucle L732 (`contract-audit`, nonce emitido antes, sha40 `c54b9de`): BA05 codex 14.9 KB, BA11 qwen 5.2 KB, BA13 gemma 4.8 KB; BA06 glm MUDA. `check_loop_execution --loop-id L732 --deliverable-type analysis` -> OK 3/3. Esta version incorpora sus hallazgos; la version auditada esta en el historial de git.

`ESTADO_FRESCO: motor HEAD=c54b9de dirty=0 (solo esta DEC untracked); destino HEAD=7719e47 dirty=0; verificado=2026-09-07`

## Contexto

`check_loop_execution` (WOT-2026-040b/043q/055q) audita que un bucle de gobierno
`1->9->2` corrio de verdad: `>=N` rondas con `backend_key` distinto, `challenge_nonce`
emitido FUERA y ANTES (`emitted_nonces.jsonl`), y contenido. **Su unica ancla es
`commit_sha`.** Eso presupone que el objeto bajo revision es un commit.

Medido en el scorecard del destino de dogfooding (rondas CON nonce+sha, desde que existe
el nonce, 2026-07-24; ventana cerrada `ts < 2026-09-07T16:00Z`):

    contract-audit  968 rondas / 73 bucles   <- objeto: un work_plan, un contrato, una ficha
    prompt-audit    522 rondas / 72 bucles   <- objeto: un prompt, un bundle
    triage          192 rondas / 20 bucles   <- objeto: un backlog, un DAG
    adjudication    110 rondas / 27 bucles
    code-review     545 rondas / 56 bucles   <- objeto: un commit (el UNICO caso que el ancla modela)

**Por rondas, el 73% del uso del guard es sobre documentos; por bucles, el 77%** (192
bucles-documento frente a 56 de commit). Todos se anclan hoy a un `commit_sha` por
CONVENCION (el HEAD del momento), no por contrato: el sha no certifica el contenido revisado.

### Las cuatro capas de identidad, y cual falta de verdad

El bucle L732 pidio comparar mas anclas (`ticket_id`, hash solo, mixtas). La comparacion
honesta empieza por separar CAPAS, porque hoy se confunden:

| Capa | Que identifica | Campo | Existe hoy? |
|---|---|---|---|
| Asunto | el trabajo del que trata el bucle | `ticket` (fila del receipt) | Si, libre y no validado |
| Serie / tipo | que protocolo de bucle se aplico | `loop_id` (`L700`, `L720`, ...) | Si -- pero es TIPO, no instancia: el registro tiene 4 ids y `L700` se uso con 157 nonces distintos |
| **Instancia** | UNA corrida concreta del bucle | **`challenge_nonce`** | **Si, y ya es unico por emision**: 566 nonces, solo 3 comparten `loop_id` o sha |
| Version del objeto | QUE bytes se sometieron a revision | (ninguno para documentos) | **No**: para documentos no hay campo |

Hallazgo que reordena la DEC: **la identidad de INSTANCIA que parecia faltar ya existe --
es el nonce**. Lo que el guard hace mal no es carecer de ella sino no usarla: agrupa las
rondas POR SHA (`audit_commit` -> `distinct_execution_backends` sobre todas las filas
del sha) y suma lentes de corridas distintas. Lo unico que falta de verdad para
documentos es la capa 4: la version del objeto.

### Dos consecuencias medidas

1. **Fusion en produccion:** 121 shas anclan mas de un nonce (maximo 17 corridas en un
   mismo sha); 84 anclan mas de un `loop_id`. La ruta productiva (`prepush_check` <-
   `loop_execution_targets.txt`) pasa solo shas. Caso concreto: L730 (prompt de triaje)
   y L731 (propuesta de cableado) comparten `c54b9de`; sin `--loop-id` el guard reporta
   `3/4` mezclando lentes de los dos; con `--loop-id L731`, `2/3`. **Impacto en
   veredictos, medido y modesto:** a N=3, solo 3 shas de 257 son verdes por SUMA sin que
   ninguna corrida llegue sola a N (p.ej. `f5089db`: 8 corridas, ninguna pasa de 2, la
   suma da 4). La fusion es endemica en los datos y rara en los veredictos; su coste real
   es semantico: "N lentes distintas" no significa hoy "N lentes en la MISMA corrida",
   que es lo unico que prueba independencia.
2. **Destinos sin ancla legal:** `emit-nonce` rechaza shas que no resuelven en el MOTOR
   (WOT-2026-059c). Los commits de un `repo_destino` (`CTL-`, ...) viven en el destino,
   luego alli **no existe hoy ningun ancla legal** para un bucle de gobierno: o se ancla
   a un sha del motor ajeno al trabajo (teatro) o se corre sin nonce (inauditable; es lo
   que paso en la sesion que origino el escalado, con `WOT-2026-059n` como deuda viva).

Esta DEC **bloquea P1** (exigir en el escritor del scorecard nonce+sha VALIDOS): sin un
ancla legal para documentos y destinos, P1 convertiria la mayoria del uso real en
"bloqueado en voz alta" el primer dia.

## Opciones comparadas

### Opcion C' (nueva tras L732): el guard cuenta lentes POR INSTANCIA (nonce), sin tocar schema

**Descripcion:** cambio SOLO en `check_loop_execution`: agrupar las rondas validas de un
sha por `challenge_nonce`; el commit pasa si **alguna instancia** alcanza `min_distinct`
con lentes sustantivas; las instancias que no llegan se NOMBRAN (como hoy las mudas).
Endurecimiento barato acoplado: `loop-round` rechaza un nonce ya usado con otro sha u
otro `loop_id` (los 3 casos sucios).

**Ventajas:** cero cambio de schema, de ceremonia y de `targets.txt`; cierra la fusion
para commits Y documentos; hace que `--min-distinct` mida lo que dice; una funcion +
tests + mutacion (dos nonces de 2 lentes -> hoy `4/4` verde, con el fix `2/4` rojo).
Cumple los 8 gates hoy.

**Desventajas:** no aporta identidad de OBJETO (que documento) ni ancla legal a destinos.
Endurece el veredicto: 3 shas historicos pasarian de verde a rojo si se re-auditaran (no
se re-auditan: el closeout mira solo los targets del vuelo).

**Compatibilidad host-first:** total (mismo guard, mismos ficheros). **Validacion
automatica:** la propia mutacion en la suite. **Coste:** bajo. **Reversibilidad:** total.

### Opcion A: `content_sha256` del bundle de ENTRADA como version del objeto, sellado por `emit-nonce`

**Descripcion:** anade la capa 4. `emit-nonce` acepta `--content-file` ademas de
`--commit-sha`; calcula `sha256` de los BYTES EXACTOS del fichero (sin normalizacion: el
fichero pasado ES el objeto; se registran tambien `content_path` y `content_bytes`, como
hace `start_context_isolation.json` con `prompt_path`/`prompt_bytes`) y lo SELLA en el
ledger junto al nonce; `loop-round` copia `content_sha256` al receipt. El join del guard
sigue siendo por instancia (C'); el hash certifica QUE objeto se sometio en ESA instancia.
`loop_execution_targets.txt` gana una forma de linea `content:<sha256> <deliverable_type>`
junto a la actual `sha[ deliverable_type]`; un lector antiguo la reporta como
"ancla no reconocida" (fail-closed nombrado), nunca la ignora en silencio.

**Ventajas:** da ancla legal a los documentos en cualquier repo (un documento se hashea
igual en motor y destino: `059c` deja de ser muro PARA DOCUMENTOS); reutiliza el patron
`prompt_sha256` que ya existe y ya sirvio hoy (exonero a `lote-A-20260805` al correlacionar
por identidad); aditivo (campo opcional; receipts historicos sin el campo = "anclado por
convencion", baseline fechado 2026-09-07, sin backfill).

**Desventajas y consecuencias que el bucle exigio declarar:**
- **No certifica la lectura:** certifica el objeto SOMETIDO y sellado, no que la lente lo
  leyo (eso lo cubre el nonce copiado). La matriz lo dice asi.
- **No da ancla a un code-review de un commit PROPIO del destino:** eso sigue siendo
  `059c/059n`; A solo cubre documentos.
- **Fragmentacion entre rondas:** cada iteracion del documento cambia el hash. NO
  fragmenta el recuento porque `min_distinct` cuenta por NONCE (C'), no por hash: una
  instancia = un nonce = un hash. Lo que si ocurre es que la SERIE de un documento que
  evoluciona queda como una lista de hashes bajo un `ticket`; la identidad estable del
  asunto sigue siendo `ticket`, no el hash.
- **Frontera de confianza:** alguien elige el fichero. Se mitiga registrando ruta y bytes
  en el ledger (auditable a posteriori), no se elimina.
- **Formato de targets:** una forma de linea NUEVA. Es cambio de contrato del lector y del
  escritor (`session_closeout`), no solo "aditivo": se declara y se prueba con ambos
  formatos mezclados en un mismo fichero.
- **Dos regimenes historicos:** receipts con y sin `content_sha256`. Se distinguen por la
  presencia del campo; el censo (P4) los reporta por separado.
- **Coste de hashear, medido:** los bundles reales pesan 7-35 KB; `sha256` de 36 KB tarda
  0,06 ms. No hay coste de I/O que declarar a esa escala; si un dia hay bundles de
  decenas de MB, la senal de reapertura de abajo lo recoge.
- **Otros destinos:** un destino con tooling desactualizado no entiende `content:`; como
  el lector falla cerrado y nombrado, el sintoma es visible, no silencioso. Exige
  sincronizar el motor antes de usar `--content-file` alli.

**Compatibilidad host-first:** media (motor y destino deben ir a la vez para documentos
del destino). **Validacion automatica:** tests con mutacion (receipt con `content:` que no
casa con el ledger -> descartado y NOMBRADO como fabricado) + `check_loop_execution` en
prepush con fixture mixto. **Coste:** medio (tres superficies + tests). **Reversibilidad:**
tecnica alta (campo opcional), operativa media (una vez que los targets lleven `content:`,
retirar el join deja esas rondas fuera del guard).

### Opcion B: declarar que los bucles sobre documentos NO son auditables por `check_loop_execution`

**Descripcion:** prosa en el contrato del guard y en `orchestrator_autonomous_ticket_batch.md`:
el guard audita bucles sobre COMMITS; un bucle sobre documento se evidencia con bundle +
receipts, sin join automatico. P1 exigiria nonce del ledger pero permitiria `commit_sha`
vacio cuando el `task_type` no sea `code-review`.

**Ventajas:** coste cero de codigo; honesta: dice lo que hoy pasa; no bloquea destinos.
Es una decision arquitectonica legitima si se documenta, no "renunciar" (correccion de
BA11 a la version anterior de esta DEC).

**Desventajas:** deja fuera del guard la mayoria del uso, por escrito; P1 tendria que
permitir filas sin sha por tipo, y P4 no podria distinguir "documento sin sha" de
"olvido"; no arregla la fusion (salvo que se combine con C') ni el destino sin ancla.

**Compatibilidad host-first:** total. **Validacion automatica:** ninguna (es prosa).
**Coste:** cero. **Reversibilidad:** total.

### Opcion D (nueva tras L732): `ticket` + `content_sha256`, sin nonce como instancia

**Descripcion:** la identidad del bucle seria (asunto, version del objeto): `ticket` +
hash del bundle, y el guard agruparia por ese par.

**Ventajas:** identidad estable del asunto entre iteraciones; legible por humanos.

**Desventajas:** `ticket` es hoy un campo LIBRE y no validado (`TRIAJE-COLA-20260908`,
`triage-doble-pasada-v1`, `WOT-2026-CIERRE`...): agrupar por el es agrupar por lo que
cada sesion quiso escribir; dos corridas sobre el mismo bundle del mismo ticket se
fundirian igual que hoy por sha (justo lo que C' evita); y hace depender la auditoria de
un campo que ningun guard sella. Si `ticket` se validara y se sellara en `emit-nonce`, D
se convierte en A + una restriccion sobre `ticket` -- que es una mejora ortogonal, no un
ancla alternativa.

**Compatibilidad host-first:** total. **Validacion automatica:** exigiria validar
`ticket` (no existe). **Coste:** medio. **Reversibilidad:** alta.

### Anclas consideradas y descartadas en una linea

- `content_sha256` SOLO (sin nonce): funde dos corridas sobre el mismo bundle; la
  instancia es el nonce.
- `loop_id` obligatorio como instancia (la antigua opcion C): `loop_id` es TIPO;
  convertirlo en instancia exigiria un registro de instancias que el nonce ya es.
- Manifest canonico hasheado (rutas + metadatos): mas superficie que hashear el bundle
  que la lente RECIBE; el bundle ya es el manifest de facto de lo revisado.

## Matriz de tradeoffs

| Criterio | C' (contar por nonce) | A (+ `content_sha256`) | B (declarar no auditable) | D (`ticket`+hash) |
|---|---|---|---|---|
| Cierra la fusion (121 shas) | Si | Si (via C') | No | No (funde por ticket) |
| Certifica el objeto SOMETIDO (no la lectura) | No | Si | No | Si |
| Ancla legal en destinos: documentos | No | Si | Exime | Si |
| Ancla legal en destinos: commits propios | No | No (059c/059n) | Exime | No |
| Desbloquea P1 | Parcial (no destinos) | Si, redefiniendo el requisito a "par valido: nonce del ledger + ancla sellada" | No (P1 con huecos por tipo) | Parcial |
| Compatibilidad host-first | Total | Media | Total | Total |
| Validacion automatica | Mutacion en suite | Mutacion + fixture mixto en prepush | Ninguna | Exigiria validar `ticket` |
| Coste | Bajo | Medio | Cero | Medio |
| Reversibilidad | Total | Tecnica alta / operativa media | Total | Alta |
| Backfill | No | No (dos regimenes declarados) | - | No |
| Riesgo de teatro | Bajo | Bajo-medio (fichero equivocado; mitigado con ruta+bytes) | Alto, declarado | Medio (ticket libre) |

## Decision (PROPUESTA -- la firma es del operador)

**Recomendacion: C' AHORA + A como ticket propio.** C' no espera decision (cumple los 8
gates hoy, no toca schema) y es lo que hace que "N lentes" signifique N lentes en la
misma corrida. A es la unica que anade la capa que falta -- la version del objeto -- y
la unica que da ancla legal a los destinos para documentos, que es la condicion de
despliegue de P1.

**Riesgo declarado (BA05, R3):** que C' se despliegue, alivie el sintoma visible, y A
quede sin hacer por inercia. Mitigacion: A se abre como ticket EN EL MISMO cierre que
implanta C', con P1 como dependiente explicito; si A no se abre, P1 no puede aprobarse.

**Criterio de desempate, para que la matriz no sea relato:** una opcion gana si (a) da
ancla legal a documentos en destinos (sin eso P1 rompe destinos) y (b) su coste es
acotado y reversible. Solo A cumple (a); C' es el paso sin coste que no compite con
ninguna.

**Justificacion:**
1. La capa que falta es la version del objeto (tabla de capas); la instancia ya existe.
   Cualquier opcion que no anada la capa 4 deja a los destinos sin ancla legal.
2. B es legitima pero deja fuera del guard el 73-77% del uso, por escrito.
3. D agrupa por un campo libre y no sellado.
4. A reutiliza un patron que ya funciono hoy y es aditivo; sus consecuencias estan
   declaradas arriba, no escondidas en "desventajas".

**Consecuencias si se firma A (ademas de C'):**
- Ticket propio, `deliverable_type: code`: `emit-nonce --content-file`, copia en
  `loop-round`, join por instancia con `content_sha256` en el receipt, lector/escritor de
  targets con ambas formas de linea, tests con la mutacion de arriba. Va DESPUES de los
  fixes del lector (normalizar sha en la ENTRADA CLI -- la docstring exige match exacto
  y "el caller normaliza la longitud" -- y C') y ANTES de P1.
- Receipts historicos sin `content_sha256` = "anclado por convencion", baseline fechado.
- `WOT-2026-059n` conserva su objeto (targets por prefijo; commits propios del destino).

**Si se firma B:** se escribe en el contrato del guard y del lote; P1 permite sha vacio
para `task_type != code-review` y P4 lo cuenta aparte. C' se implanta igual.

**Si se firma solo C':** se cierra la fusion; P1 NO puede desplegarse en destinos hasta que
059c/059n tengan solucion propia.

## Decision acoplada, con firma SEPARADA: `triage` y la ceremonia

**Correccion tras L732.** La version anterior recomendaba `triage` DENTRO del set de
gobierno porque 192 de 230 rondas ya llevan nonce+sha. Las tres lentes objetaron, con
razon, que prevalencia no es semantica: que se ejecute con mecanica de gobierno no
prueba que deba serlo, y las 38 restantes podian ser triaje ligero legitimo.

**Se midieron las 38.** No son triaje ligero: son fan-outs completos (`fanout-dif`,
`fanout-comun`, `DESIGN_REVIEW`, `PASADA_COMUN/DIFERENCIADA`), 36 con respuesta
sustantiva, en bucles `L700`, `L6002`, `L6003`, `L2602-OLA-CIERRE` (2026-07-18 ->
2026-09-01). Son la misma clase que las 88 de `loop-round` sin par: bucle de gobierno
ejecutado sin ceremonia, no otro tipo de trabajo. La hipotesis "triaje ligero" queda
refutada para este corpus; la objecion logica sigue en pie.

**Regla propuesta que resuelve las dos cosas: la ceremonia la exige la VIA, no el
`task_type`.** `loop-round` existe por definicion para "UNA ronda de un bucle de gobierno
1->9->2, registrada y atestiguable" (su propio `--help`): TODA llamada a `loop-round`
exige el par valido, sea cual sea el `task_type`. `run` (el runner CLI, que nunca
escribe `loop_id`) rechaza los cuatro tipos duros (`contract-audit`, `code-review`,
`prompt-audit`, `adjudication`) y deja pasar `triage`, `prose`, `translation`,
`code-gen`: el triaje ligero de una sola pasada sigue siendo posible por `run`, y el
triaje en fan-out queda cubierto por la via. No hace falta decidir si `triage` "es"
gobierno: hace falta que un fan-out no pueda ser inauditable.

    Opciones para la firma:
    (i)   triage DENTRO del set (por task_type)     -> bloquea tambien el triaje ligero por run
    (ii)  triage FUERA del set (por task_type)      -> deja sin barrera los fan-outs de triaje (38 medidos)
    (iii) por VIA: loop-round exige siempre el par; run rechaza los 4 tipos duros   <- RECOMENDADA

## Senales de reapertura de esta DEC

- Bundles de gobierno por encima de 10 MB (hoy 7-35 KB): revisar el coste de hashear.
- Mas de un `content_sha256` por nonce (violaria "una instancia = un objeto"): defecto.
- Un destino que necesite auditar code-review de commits PROPIOS: 059c/059n, no esta DEC.
- Que `ticket` pase a ser un campo validado y sellado: reevaluar D como capa adicional.

## Lo que esta DEC NO decide

- El contenido completo de P1 (ya especificado en la v3 del escalado) ni su calendario.
- Si `check_loop_execution` debe bloquear tambien en las ramas SKIP (055q): `WOT-2026-059n`.
- Nada sobre firmar el scorecard: la independencia es OPERACIONAL, no criptografica
  (docstring del guard), y el vector que muerde lo cierra el recuento por instancia.

## Lo que NO se verifico

- El censo es de UN destino (dogfooding). No se midio el scorecard de `Crear_Texto_LLM`.
- No se prototipo el join por `content:`; el coste "medio" es estimacion sobre las tres
  superficies leidas.
- No se midio cuantos de los 121 shas con fusion son de destinos (teatro por 059c).
- El impacto en veredictos (3 de 257) esta medido a N=3; a N=4 (code) no se midio.

## Resolucion (a rellenar al firmar)

    ADOPTED / REJECTED: ______  Opcion(es): ______  Fecha: ______  Firmante: ______

## FIRMA 1 -- ancla de identidad (operador)

    Ancla         : [ ] C' ahora + A como ticket   (recomendada)
                    [ ] C' solo
                    [ ] B  (declarar no auditable; evidencia = bundle + receipts) + C'
                    [ ] D  (ticket + content_sha256)
    Firmado por   : ______________________
    Fecha         : ______________________
    Observaciones : ______________________

## FIRMA 2 -- triage y ceremonia (operador)

    Regla         : [ ] (i) triage DENTRO por task_type
                    [ ] (ii) triage FUERA por task_type
                    [ ] (iii) por VIA: loop-round exige siempre el par; run rechaza los 4 tipos duros   (recomendada)
    Firmado por   : ______________________
    Fecha         : ______________________
    Observaciones : ______________________

**Disparador tras las firmas:** C' y los fixes del lector se implantan en el mismo
commit-set; si A, se abre su ticket en ese mismo cierre con P1 como dependiente; si B, se
edita el contrato del guard y del lote. P1 no se despliega antes de que el ancla elegida
exista y la regla de FIRMA 2 este implantada.
