---
role: orchestrator
route_kind: modulo
---
# Contrato: como lanzar un bucle de ensemble
<!-- PROMPT-SUMMARY
what: Procedimiento operativo para lanzar las lentes de un bucle de ensemble contra proveedores reales con ensemble_dispatch.py loop-round y verificar que la ronda cuenta.
when: Cada vez que una fase pide una revision adversarial (CONTRACT_AUDIT, MANAGER_REVIEW, CLOSE o DESIGN_REVIEW de una propuesta).
not: NO sirve para encargar una tarea a un backend (eso es un Builder real: builder_invocation_contract.md) ni define la forma 1->9->2 del bucle de gobierno (orchestrator_autonomous_ticket_batch.md).
-->

contract_id: cid-ensemble-loop-v1
source_of_truth: este prompt. Los prompts de gobierno (`orchestrator_autonomous_ticket_batch.md`,
`orchestrator_pipeline.md`, `orchestrator_launch_builder.md`, `orchestrator_session_close_full_audit.md`)
APUNTAN aqui para el procedimiento de despacho; si divergen, prevalece este prompt.

Alcance: el procedimiento OPERATIVO para lanzar lentes contra proveedores reales
(`scripts/ensemble_dispatch.py`) y verificar que el bucle cuenta. La FORMA del bucle de gobierno
(1->9->2, fases CONTRACT_AUDIT / MANAGER_REVIEW / CLOSE) sigue definida en
`orchestrator_autonomous_ticket_batch.md`; este contrato no la redefine. Origen: WOT-2026-086a.

Todas las rutas relativas de este documento son del MOTOR (`<motor>/scripts/...`) salvo las que llevan
`<destino>/`. Los artefactos de runtime del ensemble (`scorecard.jsonl`, `emitted_nonces.jsonl`,
`backend_leaders.json`, `backend_quarantine.json`) viven en `<destino>/.agent/runtime/ensemble/`: pasa
siempre `--project-root <destino>`.

## 1. Vocabulario (obligatorio en informes y prompts)

| Termino | Que es | Ejemplo |
|---|---|---|
| proveedor | la API o CLI que sirve modelos. En el codigo se llama `backend` | `nan_api`, `groq_api`, `codex` |
| modelo / lente | un perfil de `ensemble_profiles`, identificado por su `backend_key` | `BA11` = nan qwen3.6 |
| canal | `api` (sin acceso a ficheros) o `agent` (CLI con acceso a ficheros) | api: nan, groq, openrouter, nvidia, tokenharbor; agent: codex, opencode |
| refuter | la lente final con acceso a ficheros | codex (`BA05`) |
| emisor | quien emite el `challenge_nonce`; siempre el chat coordinador | `BA01` |

"backend IA" en `AGENTS.md` significa otra cosa (el producto que ejecuta un rol: Claude Code, Codex).
En este contrato no se usa "backend" suelto: se dice proveedor, modelo/lente o canal.

## 2. Una sola puerta: `loop-round`

Toda ronda de gobierno o de revision se lanza con `ensemble_dispatch.py loop-round`. Es la unica via que
registra la fila en `scorecard.jsonl`, avisa si el bundle no cumple el protocolo y sustituye la lente si
falla (familia -> rendimiento -> ultimo recurso).

PROHIBIDO usar `send_to_profile` (import directo) para gobierno o revision: no registra, no sustituye y la
ronda queda invisible para `leaders`, `status`, `check_loop_execution` y el dashboard. Es una primitiva
interna.

La cuarentena NO impide pedir un perfil concreto: `loop-round` lo llama aunque este en cuarentena. La
cuarentena solo filtra a los SUSTITUTOS (`resolve_fallback_backend`, `resolve_similar_fallback`) y a
`smoke`/`preflight`, que la saltan con `--ignore-quarantine`.

## 3. Procedimiento

### 3.1 Estado de los proveedores (antes de elegir lentes)

    python scripts/ensemble_dispatch.py quarantine --sync --project-root <destino>
    python scripts/ensemble_dispatch.py leaders --project-root <destino>
    python scripts/ensemble_dispatch.py status --project-root <destino>

`leaders` y `status` no se refrescan solos: regeneralos o declara su antiguedad (`generated_at`).
`status` es la ultima exploracion por lente, no el estado de ahora: un `alive:false` sin `failure_mode`
suele ser un timeout puntual, no una lente caida.

Disponibilidad: para las lentes `api`, `smoke --profile <p>` o `preflight` antes de gastar el bundle.
NO hagas ping a las lentes `agent` en cada arranque: un "PONG" a codex costo 11.278 tokens (medido
2026-09-29) porque el CLI carga el contexto del repo. Su estado sale de su ultima ronda.

### 3.2 Elegir lentes

- Una lente por proveedor distinto, salvo que el usuario pida otra cosa.
- Criterio de entrada al pool por defecto: al menos 80% de rondas utiles con 5 o mas rondas medidas.
  Preferir modelos SIN limite de cuota: el ensemble comparte cupo con los agentes de implantacion.
- `codex` es el refuter: cuenta como lente independiente si su ronda es sustantiva y supera los filtros
  del checker (no es el emisor del nonce ni una sustitucion por `BA01`; ver seccion 4).
- El mismo `backend_key` repetido NO son dos lentes.

### 3.3 Preparar el bundle

1. Tres marcadores obligatorios (los comprueba `scripts/check_loop_bundle_protocol.py`; `loop-round` avisa
   si faltan): `INVENTARIO DE EVIDENCIA`; un presupuesto de exploracion (`PRESUPUESTO`, "no mas de ...");
   y la instruccion de responder `NO VERIFICABLE` (literal, con espacio) en vez de afirmar lo que no puede
   comprobar.
1-bis. (WOT-2026-059n) Si el bundle declara `CANAL: agent` (o declara reenvio de su salida a un proceso
   ejecutor), anade tambien `ROL DE LA LENTE: REVISOR/AUDITOR` (o `EJECUTOR`, si es un encargo real de
   implementacion). `check_loop_bundle_protocol.py` BLOQUEA si el canal declarado tiene capacidad ejecutora
   y falta esta seccion; sin `CANAL:` declarado en absoluto, solo avisa (deuda de adopcion, no se bloquea
   retroactivamente). Origen: un bundle `agent` sin framing dejo a una lente con filesystem real confundir
   una propuesta de diseno con un encargo de implementacion.
2. Lentes `api` (sin ficheros): pega la evidencia (fragmentos y mediciones con su comando). Nunca les pidas
   "comprueba si existe X".
3. Lentes `agent` con `repo_scope: destino` (codex): su directorio de trabajo es el DESTINO y leen el motor
   por ruta absoluta (desde WOT-2026-042v; `resolve_lens_repo_root` en `ensemble_dispatch.py`). Dales rutas
   absolutas.
   Si el destino no se resuelve, la fila lo declara en `lens_scope` (`motor:destino-no-resoluble`): en ese
   caso la lente NO vio el destino y su "no existe" sobre un artefacto del destino no vale.
4. Envia a cada lente solo lo que tiene que revisar. Un bundle de mas de 15 KB a un modelo razonador suele
   acabar en `empty_content_despite_sentinel`: pasa antes
   `preflight --content-sample-file <bundle> --backend-keys <lista>`. Limite medido: el preflight valida el
   comienzo del bundle, no el bundle entero.
5. Si generas el bundle con un heredoc de Bash, pon el delimitador entre comillas simples. Sin comillas,
   Bash ejecuta las comillas invertidas del texto y borra palabras del bundle. Si el texto lleva apostrofos,
   escribelo con una herramienta de ficheros en vez de con un heredoc.

### 3.4 Rondas de gobierno: nonce antes de la ronda

Las fases de gobierno (`CONTRACT_AUDIT`, `MANAGER_REVIEW`, `CLOSE`) exigen nonce (WOT-2026-040i). Sin el,
`loop-round` bloquea sin gastar la llamada.

`challenge_nonce es la identidad de ejecucion`: unico por emision, sin duplicados (953 nonces,
953 distintos, medido 2026-09-30). `loop_id` designa la FORMA del bucle (`UNI-N`, `DBL-N`, `ROL-N`,
`CHA-N`); el campo `challenge_nonce` es la identidad de la EJECUCION concreta. WOT-2026-086f: se rechazo
anadir un campo nuevo `shape_id`/`run_id`; el nonce ya cumple ese rol.

     python scripts/ensemble_dispatch.py emit-nonce --commit-sha <sha> --loop-id <forma registrada> \
         --issuer-backend-key BA01 --project-root <destino>
     python scripts/ensemble_dispatch.py loop-round --profile <perfil> --backend-key <BAxx> --rol challenger \
         --content-file <bundle> --ticket <ID> --task-type <task_type> --phase <FASE> --loop-id <forma> \
         --commit-sha <sha> --challenge-nonce <nonce> --data-sensitivity public --project-root <destino>

`--loop-id` debe ser una forma registrada en `ensemble_registry.loop_shapes` de `agents.json` (p.ej.
`UNI-4`, `DBL-4`, `CHA-1`) o un alias legacy (`L700`, `L720`...) que resuelve a una forma. Si no,
`emit-nonce` emite un WARN; si la forma resuelta esta `deprecated`, tambien avisa. `validate_loop_id` en
`scripts/ensemble_dispatch.py` realiza la resolucion de alias y la validacion.

Revision de una propuesta sin commit: fase `DESIGN_REVIEW`, sin nonce, `loop_id` `EXPLORATORY-<tema>`.

`--task-type` debe estar en `TASK_TYPES`. Si no, `loop-round` rechaza, registra el intento con
`failure_mode: usage-error` y sale con codigo distinto de 0.

Valores por fase del ciclo (literal de `PHASE_LOOP_PARAMS` en `scripts/discover_skills.py`, validado por
tests contra `ensemble_dispatch`):

| Fase del ciclo | --phase | --task-type | Nota |
|---|---|---|---|
| F1-backlog | TRIAGE_AUDIT | triage | - |
| F3-auditoria-contrato | CONTRACT_AUDIT | contract-audit | - |
| F6-revision | MANAGER_REVIEW | code-review | `prose` si el entregable es documentation/research/analysis (decision provisional) |
| F7-cierre-sesion | CLOSE | contract-audit | - |

### 3.5 Lanzar

- Lentes de proveedores distintos, en paralelo. Varias del mismo proveedor: como maximo 4 a la vez (nan
  devolvio 429 con 8 concurrentes, medido 2026-09-29) o en secuencia con pausa.
- No declares muda una lente hasta que su proceso haya terminado.

### 3.6 Verificar cada ronda (un exit 0 no basta)

1. Codigos de salida de `loop-round`: 0 la ronda aporto; 1 `[BLOCKED]` (rechazada antes de llamar);
   2 `[ERROR]`; 3 `[NO-APORTA]` (la ronda corrio y se registro, pero el transporte fallo o la respuesta vino
   vacia). Aun con 0, mira la fila del scorecard (`outcome`, `failure_mode`, `output_chars`): una
   sustitucion automatica puede haber respondido en lugar de la lente pedida.
2. Si falla el CLI de un agente, la fila lleva `failure_mode: transport_failed: rc=N; <clase>` (misma
   taxonomia que el canal `api`: `quota_exhausted`, `model_unavailable`, `network_timeout`, `unknown`) y
   la `evidencia` incluye la cola de su stderr tras `[stderr]`. Un fallo de cuota/red del canal `agent`
   tambien deja evento de fallback y entra en cuarentena (ver 3.7).
3. Si la sustitucion automatica cayo en `proposer_claude` (`BA01`) -- stderr muestra
   `[fallback] ... sustituido por 'proposer_claude'` --, esa respuesta NO es una lente independiente.
4. Gobierno: `python scripts/check_loop_execution.py --commit-sha <sha> --project-root <destino>`.

### 3.7 Cuarentena por cuota/red del canal `agent` (WOT-2026-086k)

Un fallo del canal `agent` (codex/opencode) llega como TEXTO, no como excepcion, asi que no pasa por la
sustitucion automatica. Desde WOT-2026-086k `loop-round` SI escribe el evento de fallback cuando ese texto
trae el prefijo `[transport-failed]` y la clase derivada es `quota_exhausted` o `network_timeout`: el evento
va a `fallback_events.jsonl` y de ahi `quarantine --sync` lo proyecta en `backend_quarantine.json`. La
condicion exige ademas `channel == "agent"`: un backend `api` cuyo texto empezara por el prefijo no escribe
evento. No hay sustitucion automatica del canal `agent` en este ticket: `fallback_profile`,
`fallback_backend` y `fallback_backend_key` quedan `null`.

El parser reconoce las TRES variantes con que codex da la hora de reset (en hora LOCAL), sin distinguir
mayusculas: solo-hora ("try again at 3:05 PM"), con fecha explicita ("or try again at Jul 28th, 2026 7:56
PM") y sin hora ("or try again later.", que cae al TTL por defecto). El ancla temporal es el `ts` del
EVENTO de fallo, no el momento del `sync`: una hora solo-hora ya pasada respecto al evento cae al TTL,
nunca se asume el dia siguiente. Si hay varias menciones de `try again` (codex hace eco del prompt), manda
la ULTIMA. `failure_detail` guarda esa ultima linea recortada a 300 caracteres; si no hay ninguna, los
ultimos 300 caracteres de la cola de stderr.

Efecto: VISIBILIDAD, no bloqueo. La lente aparece en `quarantine --sync` y queda excluida como sustituto y
de `smoke`/`preflight`; NO bloquea `loop-round`, que sigue llamando al perfil pedido aunque este en
cuarentena (seccion 2).

### 3.8 Compatibilidad de `loop_id` por lector

| Lector | Antes (L###) | Despues (UNI/DBL/ROL/CHA-N + alias) |
|---|---|---|
| `scorecard.jsonl` | `loop_id` = `L700`/`L710`/`L720`/`L800` | Filas historicas intactas; las nuevas usan la forma directa |
| `emitted_nonces.jsonl` | `loop_id` = `L###` | Igual: el ledger registra lo que se emite |
| `check_loop_execution` | Agrupa por `loop_id` `L###` | Resuelve alias via `loop_shapes[loop_id].alias_of` |
| `phase_value_report` (dashboard) | Filtra por `L###` | Acepta alias legacy y formas directas |
| `leaders` | Backend leaders por `L###` | Mismo: los leaders se calculan por backend_key, no por forma |
| `prepush_check` (token `loop=<id>`) | Token `loop=L700` | Acepta alias legacy y formas directas; `validate_loop_id` advierte si deprecated |
| `fallback_events.jsonl` | Fallback por `L###` | Igual: los fallbacks son por backend_key/perfil |
| `adjudicate` | Adjudica por `loop_id` `L###` | Resuelve alias antes de adjudicar |

### 3.9 Mudez por modelo, lector efectivo y bundle por canal

Tres hechos medidos en la propuesta v3 del proceso portable (secciones 4.4 y 4.6), que este procedimiento
hereda:

- La mudez depende del MODELO, no de un tamano global: un bundle que un modelo responde puede dejar mudo a
  otro. El umbral de 3.3 es una senal, no una regla universal.
- Una lente con ficheros cuenta como LECTORA solo si hay recibo de lectura (llamadas a herramientas de
  lectura en el log del CLI) y su salida cita `ruta:linea` comprobable; si responde sin leer, cuenta como
  lente sin ficheros y se declara.
- El bundle va POR CANAL: el de FICHEROS lleva rutas absolutas y la lista "verifica X en <ruta>", sin
  framing de lente sin ficheros; el de TEXTO lleva el contenido (contrato por contenido) y su framing.

## 4. Definicion unica de "lente independiente"

Cuenta como lente independiente una ronda que cumpla TODO:
- `event == "ronda"` con respuesta sustantiva segun `check_loop_execution.is_substantive` (no muda:
  `output_chars != 0`, `outcome != "no-aportacion"`, evidencia no vacia);
- `backend_key` distinto de las demas lentes contadas;
- no es el emisor del nonce;
- no es una sustitucion por `BA01`.

Las ramas (`comun`/`dif`) y los prompts distintos NO multiplican lentes: solo cuentan `backend_key` distintos.

## 5. Minimos por tipo de entrega

Los fija `check_loop_execution.min_distinct_for(deliverable_type)`: `code`/`mixed` 4, `analysis` 3,
`research`/`documentation` 2. `EXPLORATORY` no tiene barrera. Si tras las sustituciones no se llega al
minimo: reintentar una vez con el siguiente candidato (nunca `BA01`); si sigue sin llegar, el informe declara
el bucle `INSUFICIENTE` y no vale como gobierno.

## 6. Informe de cada bucle

Para cada lente pedida: `backend_key`, proveedor, resultado (`util`, `mudo`, `transport-failed`,
`sin-cuota`, `bloqueada-privacidad`, `sustituida-por-<bk>`, `sustituida-por-BA01`) y si cuenta como
independiente. Al final: lentes independientes conseguidas frente al minimo exigido, y el veredicto de cada
una.

## 7. Uso minimo

Una cuenta por proveedor: nunca cuentas extra para esquivar limites. Sin agregadores de terceros entre el
motor y el proveedor. En cada bundle, solo lo necesario. Ping o preflight antes de mandar un bundle grande.
Los cupos se comparten con los agentes de implantacion: preferir modelos sin limite.

## 8. Pendiente (todavia no existe; no lo invoques)

- `gov_stage`/`step`: WOT-2026-086g.
- `smoke` rapido y paralelo: WOT-2026-086h.
- Estado unificado de proveedores y descubrimiento `/v1/models` en el arranque: WOT-2026-085a.
- Comando `loop` con valores por defecto para chat: WOT-2026-086i.
