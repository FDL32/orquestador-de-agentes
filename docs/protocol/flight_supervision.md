# Protocolo de supervision de vuelo: relevo, autoridad y cuentas

> **Origen:** WOT-2026-136h. Regla de cuenta y envios entre sesiones indexados y versionados aqui;
> autoridad, supervision y relevo solo indexados (X-09).

---

## 1. Alcance y fuentes

Este protocolo es la casa versionada de lo que antes vivia solo en datos de runtime
fuera de commit y en el idioma de la mensajeria entre sesiones.

**Fuentes del diseno:**
- La regla de cuenta se transcribe del bloque `quota` del roster y
  `REGLA_CUENTA_vigente.md` (solo lectura; no se editan por commit).
- Los envios entre sesiones se basan en `t3_thread_send` (herramienta MCP, no un programa).
- La autoridad, supervision y relevo viven en `prompts/t3_role_session_relief.md`
  (seccion 11): este documento los INDEXA por seccion y por campo de datos,
  no los repite (X-09).

**NON-GOAL:** Enviar mensajes reales ni un transporte MCP (eso es `t3_thread_send`,
herramienta del agente). Editar el roster vivo, el registro, o `REGLA_CUENTA_vigente.md`.

---

## 2. Autoridad

**Hogar normativo:** `prompts/t3_role_session_relief.md` seccion 11
("Autoridad, supervision y relevo de la coordinadora", subsecciones:
"Precondicion mecanica", "Tabla de funciones", "Regla de supervision estructural",
"Cierre al relevar", "Decision sobre un `SALIENTE_MUERTO`", "Resolucion de la
coordinadora por un implantador", "Fuente de la cadena").

**Campos de datos:**
- Roster: `active_roles.orquestador`, `active_roles.supervisor`, `active_roles._schema_note`.
- Registro: `cadena_consulta` (fuente de la cadena de supervision, solo consistencia).

---

## 3. Supervision estructural

**Hogar normativo:** `prompts/t3_role_session_relief.md` seccion 11
("Regla de supervision estructural").

**Campos de datos:**
- Roster: `active_roles.supervisor` (supervisora directa),
  `cadena_contexto` (lista, nivel 1 del roster), `excepcion_supervisor` (si existe,
  solo cuando hay excepcion vigente), `predecessor_threadId`.
- Registro: `cadena_consulta` (posicion 1 = supervisora directa).

---

## 4. Relevo

**Hogar normativo:** `prompts/t3_role_session_relief.md` (secciones 2-9):
"Clases de fallo", "Tercer discriminador: cupo/cuenta agotada", "Arbol A/B por
ranura con umbral configurable", "Progreso observable", "Checkpoint continuo",
"Preflight del relanzo", "Plantilla del sucesor", "Verificacion de la
coordinadora", "Self-hop del orquestador", "Cadena de ancestros".

**Campos de datos:**
- Roster: `active_roles.<rol>.estado` (ACTIVO, PENDIENTE_ACK, SALIENTE_MUERTO),
  `active_roles.<rol>.threadId`, `predecessor_threadId`.
- Registro: `cadena_consulta` (consulta escalonada),
  `roster_changes.jsonl` (evento `ancestor_unavailable`).

---

## 5. Regla de cuenta (contrato)

La regla de cuenta define cuando mover un hilo entre cuentas: `cuenta preferida`
y `cuenta de refugio` (con `proveedor de cuenta de refugio`). Este documento
define el CONTRATO de la regla vigente; los numeros de la politica de cuenta se
declaran como "valores vigentes a 2026-10-30 en el roster", sin copia
ejecutable (ningun codigo ni prompt los lee de aqui).

- `REGLA_CUENTA_vigente.md` y el bloque `quota` del roster pasan a ser punteros a
  este contrato; este fichero es el contrato y declara los valores a la fecha.
  Este protocolo no edita el roster ni retira `REGLA_CUENTA_vigente.md`: mientras
  no se retire, vale la clausula de `numbers_source` (ver "Precedencia ante
  discrepancia").
- La `cuenta preferida` y la `cuenta de refugio` viven en el roster
  (`quota.account_policy.preferred_account`, `quota.account_policy.harbor_account`);
  el `proveedor de cuenta de refugio` vive en
  `quota.account_policy.provider_map`.

### Valores vigentes a 2026-10-30 en el roster

| Campo de la politica | Valor | Fuente |
|---|---|---|
| soft_freeze_block_pct | 92 | roster `quota.soft_freeze_block_pct` (umbral soft: ver P1) |
| hard_stop_block_pct | 97 | roster `quota.hard_stop_block_pct` (umbral hard: ver P1 y "Precedencia ante discrepancia") |
| enter_when_block_pct_le | 60 | roster `quota.account_policy.enter_when_block_pct_le` (P3 IR) |
| harbor_block_pct_max | 80 | roster `quota.account_policy.harbor_block_pct_max` (P3 IR y refugio valido del umbral hard) |
| leave_when_block_pct_ge | 90 | roster `quota.account_policy.leave_when_block_pct_ge` (P2 VOLVER) |
| min_dwell_min | 45 | roster `quota.account_policy.min_dwell_min` (P3 IR) |
| enter_requires_consecutive_valid_readings | 2 | roster `quota.account_policy.enter_requires_consecutive_valid_readings` (P3 IR) |
| max_moves_per_tick | 1 | roster `quota.account_policy.max_moves_per_tick` (P4 Banda) |

**Nota:** ningun codigo ni prompt lee estos numeros desde el protocolo; el dato
vivo sigue siendo el roster. El censo de ocho nombres de campo (en el test) es
un PROXY declarado de "esos literales", con UNA excepcion explicita: el fixture
congelado de 136c bajo `tests/fixtures/`, que no se edita.

### Clauses de la regla

Las clausulas P1 a P8 se aplican en este orden de precedencia.

- **P1 Umbrales (`quota`):** los dos umbrales y su efecto se transcriben LITERAL de
  cada fuente; las fuentes NO coinciden en el efecto del umbral hard (ver "Precedencia
  ante discrepancia"). Los numeros son los de la tabla de valores vigentes.
  - Umbral soft, roster `quota.action_soft`: "FREEZE de tickets nuevos: las sesiones
    terminan el ticket en curso y paran".
  - Excepcion del umbral soft, roster `quota.reserve_for_orquestadora`: "la orquestadora
    para sus propios bucles en soft; conserva margen para cerrar e integrar".
  - Umbral hard, roster `quota.action_hard`: "mover PRECEDE a interrumpir: si hay
    refugio valido (cuenta de refugio con block_pct <= account_policy.harbor_block_pct_max
    y lectura fresca, stale=false) se mueve el hilo segun account_policy;
    t3_thread_interrupt de implantacion y triaje si NO hay refugio valido o la lectura
    esta stale o nula; el ticket queda aparcado con su estado escrito".
  - Umbral hard, `REGLA_CUENTA_vigente.md` P1: "interrupt de implantadores, precede
    a todo".
- **P2 VOLVER:** hilo en preferida y preferida.block_pct >= 90 y
  refugio.block_pct < 90 -> mover a refugio AHORA (el dwell NO aplica a salir) (roster
  `quota.account_policy.min_dwell_applies_to`).
  Si ambas >= 90: no mover, FREEZE soft y avisar a la supervisora directa de la
  coordinadora (cadena de supervision del roster).
- **P3 IR (entrar en preferida), TODAS a la vez:** preferida.block_pct (maximo de
  ventanas, venga de la ventana que venga: si la bloqueante es la semanal vale igual
  mientras este <= 60; si la semanal supera 60 no se entra, porque un reset de 5h no la
  alivia) <= 60 en DOS lecturas consecutivas validas (stale=false, no nulas; 2 min entre
  ellas o la del tick anterior del ledger); refugio.block_pct <= 80; no ambas >= 90;
  hilo no running (hueco natural); ningun movimiento de ese hilo en los ultimos 45 min;
  no haber hecho VOLVER desde el ultimo reset de la cuenta preferida (roster
  `quota.account_policy.after_leave_wait_until_reset`).
- **P4 Banda 61..89:** no mover. Sin historial de ritmo: un solo hilo de cebo y esperar
  2 ticks antes de mover otro. Maximo 1 movimiento por tick. Orden de movimiento (roster
  `quota.account_policy.move_order`): implantacion y despues triaje.
- **P5 Fail-closed:** monitor stale, nulo o con error; proveedor no mapeado; hilo
  fuera de alcance -> no mover y anotar (roster `quota.account_policy.stale_fail_closed`).
  Nunca inventar valores.
- **P6 Registro y aviso en cada movimiento:** ledger, una linea en `roster_changes.jsonl`
  (by/change/detail/reason) y aviso por `t3_thread_send` (mode=queue, prefijo `mcp:`)
  al hilo movido. `t3_thread_configure` aplica en el PROXIMO turno.
- **P7 Verificacion:** DOS lecturas: la configuracion del hilo
  (`t3_thread_configuration`) y el proveedor efectivo del SIGUIENTE run
  (`recentRuns[0].providerInstanceId`) sin `parent_not_active`. Si falla: VOLVER y
  avisar al usuario.
- **P8 Frontera:** el cambio de host del Manager no altera un despacho ya
  lanzado; se acepta fuera de frontera de ticket SOLO con el hilo no running; nunca
  durante un turno de verificacion de commit (roster `quota.account_policy.apply_at`).

### Cuando se mira cada umbral

- `quota.check_every` (roster): "cada latido de la orquestadora y antes de autorizar
  un ticket nuevo". El roster fija esa UNICA cadencia para el bloque `quota`: no
  declara una cadencia distinta por umbral, de modo que se mira el umbral soft y el
  hard en la misma comprobacion.
- El `block_pct` que se compara es el maximo de las ventanas (5h y semanal) de la
  cuenta donde corre el hilo (`quota.account_policy.block_pct_definition`).
- P5 (fail-closed) rige la lectura: monitor stale, nulo o con error no autoriza a
  mover.

### Alcance

- Se mueven solo los hilos que gobierna la coordinadora: implantacion y triaje si hay
  uno vivo (se comprueba con `t3_thread_list`, NO con el registro de sesiones, que
  esta desfasado).
- Sobre implantacion y triaje, P2 VOLVER y P3 IR los aplica el latido de la
  coordinadora vigente, que se resuelve leyendo `orquestador_activo` del registro de
  sesiones; no se nombra una sesion concreta.
- NUNCA sesiones supervisoras ni asentadas.
- Para la propia coordinadora, VOLVER lo ejecuta su supervisora directa (resuelta de
  `cadena_consulta`, posicion 1) desde su latido, solo si se cumplen a la vez:
  preferida.block_pct >= 90, refugio.block_pct < 90, ambas lecturas con stale=false,
  la coordinadora no esta running, no existe marca de NO_MOVER, y el run de la
  supervisora tiene cupo. Verificacion P7 con dos lecturas. Si la supervisora directa
  no puede ejecutarlo, VOLVER es MANUAL del usuario y se avisa por el buzon de la
  supervisora. La coordinadora no se mueve a si misma.
- P3 IR sobre la coordinadora: no se automatiza; la mueve el usuario (roster
  `quota.account_policy.coordinator_policy_ref`: politica de la coordinadora, este punto
  y el anterior).

### Estado de las fuentes

`REGLA_CUENTA_vigente.md` (fuera del repo) y el bloque `quota` del roster (runtime,
fuera de commit) son las dos fuentes de las que se transcribe este contrato. El
roster YA contiene `quota.account_policy` (el dato vivo de los numeros y de la
politica de movimiento); este ticket no edita el roster ni retira
`REGLA_CUENTA_vigente.md`.

**No transcrito (sigue en la fuente, por seccion):** el objetivo de la regla (estar en
la cuenta preferida siempre que tenga cupo y usar la de refugio cuando no lo tenga), la
nota de que el mapa cuenta-proveedor (`quota.account_policy.provider_map_status`) es una
inferencia por comportamiento no verificada
por la configuracion oficial (seccion "Cuentas y proveedores"), "Lo que esta regla NO
decide" y el latido de reset con su invariante de latidos (seccion "Latido de reset" y
la enmienda de la coordinadora). Tampoco se transcribe la frase de procedencia de P1
("Los dos son del roster y no se redefinen aqui"): no es una condicion, porque la tabla
de valores y P1 ya citan el roster. Del bloque `quota` del roster no se transcribe
`quota.account_policy.supersedes_cc_watch` (alcance de una regla personal del usuario,
fuera del repo, que la fuente ya cubre en "Lo que esta regla NO decide"), ni los
metadatos del bloque `quota` (`source`, que es el comando del monitor y una ruta de
maquina, `version`, `updated_at` y `updated_by`) ni la nota de esquema "sin claves de
rol" de `quota.account_policy.scope`.

**Adaptaciones al transcribir (declaradas):** el protocolo no nombra sesiones ni cuentas
(N5), asi que (1) el aviso de P2, que la fuente dirige a una sesion nombrada, se escribe
como "la supervisora directa de la coordinadora (cadena de supervision del roster)";
(2) en P4 el hilo de cebo, que la fuente nombra, queda como "un solo hilo de cebo"; (3)
en P8 se omite el parentesis explicativo de la fuente sobre el canal del despacho: no es
una condicion; (4) el Alcance de la fuente y la cola de `numbers_source` nombran sesiones
concretas: el protocolo no las nombra y las sustituye por "NUNCA sesiones supervisoras ni
asentadas" y por la descripcion de la fuente; (5) en P6 la fuente nombra el fichero del
ledger: el protocolo no lo transcribe, porque la ruta del ledger va siempre por argumento
(seccion 6).

### Indice de campos de quota

Cada clave del bloque `quota` del roster, con su ruta completa entre comillas invertidas,
y donde se desarrolla en este protocolo. `No transcrito` remite a la declaracion de
"Estado de las fuentes". `exenta (padre)`: las dos claves hijas de
`quota.account_policy.provider_map` son un nombre de cuenta y de proveedor (N5), asi que
no se escriben aqui y las cubre la fila de su padre. El indice es una fotografia a
2026-10-30 de las claves, no de sus valores: el dato vivo sigue siendo el roster, y ningun
codigo ni prompt lo lee de aqui (un chequeo de deriva contra el roster vivo queda fuera de
este ticket).

| Clave de `quota` (ruta completa) | Donde se desarrolla |
|---|---|
| `quota.source` | No transcrito |
| `quota.check_every` | Cuando se mira cada umbral |
| `quota.soft_freeze_block_pct` | Valores vigentes |
| `quota.hard_stop_block_pct` | Valores vigentes |
| `quota.action_soft` | P1 |
| `quota.action_hard` | P1 |
| `quota.reserve_for_orquestadora` | P1 |
| `quota.account_policy` | Estado de las fuentes |
| `quota.account_policy.scope` | Alcance; No transcrito (nota de esquema) |
| `quota.account_policy.provider_map` | Seccion 5 (contrato); sus claves hijas: exenta (padre) |
| `quota.account_policy.provider_map_status` | No transcrito |
| `quota.account_policy.preferred_account` | Seccion 5 (contrato) |
| `quota.account_policy.harbor_account` | Seccion 5 (contrato) |
| `quota.account_policy.block_pct_definition` | Cuando se mira cada umbral |
| `quota.account_policy.enter_when_block_pct_le` | Valores vigentes |
| `quota.account_policy.enter_requires_consecutive_valid_readings` | Valores vigentes |
| `quota.account_policy.harbor_block_pct_max` | Valores vigentes |
| `quota.account_policy.leave_when_block_pct_ge` | Valores vigentes |
| `quota.account_policy.min_dwell_min` | Valores vigentes |
| `quota.account_policy.min_dwell_applies_to` | P2 |
| `quota.account_policy.after_leave_wait_until_reset` | P3 |
| `quota.account_policy.stale_fail_closed` | P5 |
| `quota.account_policy.max_moves_per_tick` | Valores vigentes |
| `quota.account_policy.move_order` | P4 |
| `quota.account_policy.apply_at` | P8 |
| `quota.account_policy.supersedes_cc_watch` | No transcrito |
| `quota.account_policy.coordinator_policy_ref` | Alcance |
| `quota.account_policy.numbers_source` | Precedencia ante discrepancia |
| `quota.account_policy.version` | No transcrito |
| `quota.account_policy.updated_at` | No transcrito |
| `quota.account_policy.updated_by` | No transcrito |

### Precedencia ante discrepancia

El roster declara en `quota.account_policy.numbers_source` que el fichero de la regla
manda sobre su bloque hasta retirarlo: "si difiere de este bloque manda ese fichero
hasta retirarlo". Aplicada esa clausula tal cual, mientras
`REGLA_CUENTA_vigente.md` no se retire manda ese fichero donde las dos fuentes
difieran.

### Huecos detectados

- **ABIERTO: efecto del umbral hard.** El roster (`quota.action_hard`) dice que mover
  PRECEDE a interrumpir y distingue refugio valido de sin refugio; `REGLA_CUENTA_vigente.md`
  P1 dice "interrupt de implantadores, precede a todo". Este protocolo transcribe las dos
  y NO elige: la decision es de la coordinadora o del usuario, y alinear el roster o la
  regla es otro ticket. Mientras tanto aplica la clausula de precedencia de arriba.
- **ABIERTO: lectura stale o nula.** `REGLA_CUENTA_vigente.md` P5 (fail-closed) dice
  "monitor stale, nulo o con error; proveedor no mapeado; hilo fuera de alcance -> no
  mover y anotar"; el roster (`quota.action_hard`) dice que con la lectura stale o nula
  se interrumpe a implantacion y triaje si no hay refugio valido. Este protocolo
  transcribe las dos y NO elige; misma decision pendiente que el hueco anterior.
- **ABIERTO: escrituras concurrentes del ledger.** El helper no serializa: sin lock,
  dos `record` simultaneos pueden intercalar y `check` y `record` no son atomicos (ver
  seccion 6, "Limite: sin serializacion de escrituras"). El helper es ADVISORY y el
  agente decide; la mitigacion posible es otro ticket y no se admite aqui.
- Lectura no vinculante de la supervisora directa (opinion, no decide): el roster
  deberia ganar, porque `REGLA_CUENTA_vigente.md` se declara interina y los numeros de
  los umbrales son del roster.
- Duda sobre el alcance de `numbers_source`: habla de numeros, pero su texto dice "si
  difiere de este bloque"; este protocolo no decide si cubre tambien los efectos.

---

## 6. Envios entre sesiones

La mensajeria entre sesiones tiene un camino que se puede comprobar. Un script
no envia mensajes: `t3_thread_send` es una herramienta MCP del agente. El helper
de este modulo (`scripts/flight/send_with_ledger.py`) VALIDA antes y REGISTRA
despues.

### Prefijo del destino

El threadId del supervisor debe tener el prefijo `mcp:`. Lo valida la funcion
compartida en `scripts/flight/thread_id.py` (`has_mcp_prefix`): la valida el
escritor, el guard del roster en el supervisor y el helper en el destino de un
envio (clave `a`). Es el unico fichero de `scripts/` con el literal `"mcp:"`
como prefijo exigido; el escritor, el guard y el helper la importan.

### Modos

El parametro `mode` de `t3_thread_send` admite (segun el esquema real de la
herramienta): `auto`, `queue`, `steer`, `restart`. El helper valida que el modo
sea uno de este conjunto cerrado.

### Un unico intento ante `parent_not_active`

Ante un fallo `parent_not_active`, `check` rehusa cualquier reintento
(cero reintentos). La verificacion se hace LEYENDO el ledger: si existe un
registro previo con `resultado = "parent_not_active"` para el mismo `mensaje_id`,
`check` retorna rc 1.

Un registro previo `enviado` NO es terminal: el ledger es un registro, no una
maquina de estados.

Ante otros fallos (`thread_not_found`, `error`), `check` autoriza UN reintento,
rehusando cuando ya hay dos registros fallidos del mismo `mensaje_id`.

**Orden de prioridad de las reglas:** primero `parent_not_active` (rehuso),
despues `enviado` (no terminal, autoriza), despues otros fallos con tope de 2
de `thread_not_found` y `error`. Un `resultado` fuera del vocabulario cerrado
no cuenta como fallo.

### Codigos de salida del helper

- `check` / `record`: `0` = autorizado / escrito; `1` = rehusado (razon por
  stdout); `2` = uso o argumentos invalidos o error de entorno (p. ej.
  `thread_id.py` no cargable, o un ledger que existe y no se puede abrir para
  anexar: en ambos casos no se escribe nada).
- Nunca `3`, que en los `check_*` del repo significa "no aplica".

### `check` exige `--a` y `--modo`

Ambos son argumentos obligatorios (`required=True`); su ausencia produce rc 2.

### `record` rehusa rc 1

Cuando el destino no tiene prefijo `mcp:`, el modo o el `resultado` estan fuera
del vocabulario cerrado, o falta `by` o `mensaje_id` (no vacio).

### `rc 2` = error de entorno

`thread_id.py` no cargable (p. ej. modulo ilegible, error de import), o ledger
que existe pero no se puede abrir para anexar (permisos, directorio en vez de
fichero): en ambos casos `record` no escribe nada y la causa va por stdout.

### Ruta del ledger siempre por argumento

Nunca por valor de defecto. Tanto `check` como `record` requieren `--ledger`.

### El agente envia

El helper no envia: el agente usa `t3_thread_send` (MCP tool). El helper:
- `check`: lee el ledger y devuelve autorizado o rehusado.
- `record`: anade UNA linea de esquema fijo al ledger.

### Limite: sin serializacion de escrituras

El helper no toma ningun lock. Dos `record` simultaneos sobre el mismo ledger pueden
intercalar sus escrituras, y `check` y `record` no son atomicos entre si: dos agentes
pueden ejecutar `check` antes de que ninguno registre y recibir ambos "autorizado". El
helper es ADVISORY: valida y registra, y el agente decide si envia. Una mitigacion
(lock o escritura atomica) seria otro ticket; este protocolo declara el limite y no lo
resuelve.

---

## 7. Ledger de envios

### Esquema fijo (9 claves)

Cada linea del ledger tiene exactamente estas claves:

```
ts, by, a, modo, resultado, error, providerInstanceId, mensaje_id, nota
```

- `ts`: timestamp UTC (lo pone SIEMPRE el reloj del helper, nunca un argumento).
- `by`: actor que registra (argumento obligatorio, no vacio).
- `a`: destino (threadId, con prefijo `mcp:`).
- `modo`: modo de envio (`auto`, `queue`, `steer`, `restart`).
- `resultado`: `enviado`, `parent_not_active`, `thread_not_found`, `error`.
- `error`: descripcion del error (si hay).
- `providerInstanceId`: instancia del proveedor (si hay).
- `mensaje_id`: identificador del mensaje.
- `nota`: nota libre.

### Politica legacy

El ledger vivo mezcla muchos conjuntos de claves (cientos de textos libres de
antiguo). La politica legacy se mide por CONJUNTO DE CLAVES, nunca por conteo:
una linea es legacy si su conjunto de claves difiere del fijo. La clave `threadId`
no existe como campo en el ledger vivo (el destino va en `a`).

El validador (`scripts/flight/validate_ledger.py`) informa las lineas legacy sin
bloquear: rc 0 incluso con legacy; rc 2 solo si el fichero no se puede leer.

### Casos degenerados

1. **Ledger inexistente:** `check` AUTORIZA (no hay intentos previos) y `record`
   lo crea. El validador sale rc 2 (ilegible). Ante un ledger inexistente o ilegible el
   helper es ADVISORY: `check` autoriza y no sale rc 2.
2. **Ledger vacio:** `check` autoriza. El validador informa 0 lineas, rc 0.
3. **Linea con JSON invalido:** `check` la IGNORA al contar intentos. El validador
   la cuenta como no-JSON.
4. **Ultima linea sin `\n`:** se lee bien (`splitlines`); `record` la completa con
   salto antes de anadir.
5. **`mensaje_id` repetido:** la regla de un unico intento ante `parent_not_active`
   se aplica sobre los registros del mismo id (ver seccion 6).
6. **`ts` y `by`:** `ts` lo pone el reloj del helper; `by` es argumento obligatorio
   no vacio (regla ya fijada).

---
