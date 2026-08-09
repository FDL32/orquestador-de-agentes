# Escalate to Motor — contrato de redaccion de un escalado destino -> motor

contract_id: cid-escalate-to-motor-v1
Skill canonica: skills/escalate-to-motor/SKILL.md

<!-- PROMPT-SUMMARY
what: Contrato de redaccion para que un repo_destino escale un hallazgo del MOTOR como ficha del buzon `backlog_inbox/`, con recibo reejecutable, procedencia por claim y condicion de rechazo declarada.
when: El usuario (o el agente que opera un destino) detecta un defecto, deuda o propuesta que pertenece al MOTOR y no al destino. Se invoca en el chat del destino.
not: NO es el pipeline de tickets del destino, NO es `manager-resolve-escalation` (que es Builder->Manager intra-repo) y NO autoriza a escribir en `repo_motor`.
-->

## 0. Que es esto y que NO es

Un destino que encuentra un defecto **del motor** no puede arreglarlo: el motor es
read-only desde el destino. Este prompt gobierna **como se redacta el sobre** para
que el motor pueda juzgarlo sin tener que creerse nada.

**No inventa canal.** El canal ya existe y ya se ha usado: el buzon
`<destination_root>/.agent/collaboration/backlog_inbox/*.tickets.md`, que consume el
**Bloque 8.bis** del cierre canonico (`orchestrator_session_close_full_audit.md`).
Este prompt es la pieza que faltaba: el **contrato de emision**. El 8.bis ya define
la ingesta (gate de evidencia, DEDUPE de tres superficies, `reserved_ids`, RECIBO
DEC); aqui no se re-declara ninguno de esos criterios — se remite a el.

## 1. Regla de autoridad (leela antes de escribir nada)

El invariante del motor **no es de ruta, es de AUTORIDAD**. La linea 141 del cierre
canonico prohibe TRES cosas, no una:

> "NO escribir el follow-up en `repo_motor`, NI en el repo_destino de ESTA sesion,
> NI dejarlo solo en memoria."

Consecuencias directas para ti:

- **No parchees el motor.** Ni siquiera "para probar". Un escalado que llega con el
  motor ya tocado se rechaza entero.
- **No te auto-asignes un `WOT-id`.** El id lo pone quien ve el backlog completo.
  Tu ficha va SIN id y SIN estado.
- **No escribas el hallazgo solo en el backlog de TU destino.** Eso lo entierra.
- **Si el buzon no es alcanzable** (destino en otra maquina, sin filesystem
  compartido, sin `motor_destination_link.json` resoluble): **DETENTE**. Nunca
  fabriques la ruta ni la inventes. Es la misma salida que impone la linea 141.
  Emite el sobre en el chat **precedido de la linea literal**
  `[FALLBACK-ESCALADO-NO-ATERRIZADO]` y con el contenido integro que habria ido al
  fichero. **Di explicitamente que NO esta aterrizado y que un humano debe copiarlo
  al buzon**: el consumidor hace glob de `backlog_inbox/*.tickets.md`, asi que lo
  que no es un fichero con ESE sufijo en ESE directorio no lo ve nadie. Un sobre en
  el chat no es un escalado: es un borrador a la espera de aterrizar.

## 1.bis Como resolver las rutas (no las adivines)

Este contrato usa tres placeholders. Resuelvelos ASI, en este orden, y si no puedes,
aplica el fallback de arriba en vez de suponer:

- `<destination_root>`: la raiz del repo destino desde el que operas. Es el
  directorio que contiene `.agent/`. Si operas con `--project-root <ruta>`, es esa
  ruta; si no, sube desde tu cwd hasta el primer ancestro con `.agent/`.
- `<workspace>`: en la topologia normal coincide con `<destination_root>` (el buzon
  y el `backlog.md` que consultas son los del MISMO repo). No son dos sitios.
- `<MOTOR_ROOT>`: **no lo escribas a mano**. Sale del campo `motor_root` de
  `<destination_root>/.agent/config/motor_destination_link.json`. Si ese fichero no
  existe o no resuelve, el destino no esta enlazado al motor: fallback.

## 2. Antes de redactar: el anti-duplicado es OBLIGATORIO

Un escalado duplicado cuesta mas que uno que no llega, porque consume juicio humano
para acabar en "ya estaba". **Busca primero**, en las tres superficies:

```bash
grep -in "<palabra-clave>" <workspace>/.agent/collaboration/backlog.md
grep -in "<palabra-clave>" <workspace>/.agent/collaboration/_archive/backlog_done.md
ls <workspace>/.agent/collaboration/backlog_inbox/
```

**LEE ENTERO cada hit.** No descartes por el titulo: las fichas se redactan como
reglas abstractas y los hallazgos como casos concretos, asi que los titulos no se
parecen aunque el contenido sea el mismo.

Si encuentras el hallazgo ya fichado, **no abras ficha nueva**: escala como
`REPRODUCCION_INDEPENDIENTE`. Vale mas y cuesta menos — una segunda medicion desde
otro repo es evidencia que la ficha original no tenia.

**Que citas depende de DONDE lo encontraste**, porque no todo hit tiene id:

| Donde | Que citas |
|---|---|
| `backlog.md` o `_archive/backlog_done.md` | el `WOT-id` de la fila |
| `backlog_inbox/` (ficha aun sin fusionar) | el **nombre del fichero** (`FP-...tickets.md`): esa ficha todavia NO tiene id, y el fusionador se lo asignara |

Nunca inventes un `WOT-id` para poder citarlo. Si el hit no tiene id, cita el
fichero y dilo: *"vinculada a `<fichero>`, pendiente de id"*.

## 3. Clasificacion (obligatoria, una sola)

| Clase | Cuando | Que exige |
|---|---|---|
| `DEFECTO_REPRODUCIBLE` | Hay comando que falla hoy y pasaria con el fix | RECIBO obligatorio |
| `DEUDA_YA_DECLARADA` | El motor ya la declara en un comentario/ficha | Cita verificable + lo que tu aportas |
| `REPRODUCCION_INDEPENDIENTE` | Ya esta fichado y lo confirmas desde otro repo | Id existente + tu medicion |
| `PROPUESTA_DISENO` | No hay defecto medible; es criterio | Declararlo, no disfrazarlo |

**Sin RECIBO reejecutable, un `DEFECTO_REPRODUCIBLE` degrada a `PROPUESTA_DISENO`.**
No es castigo: es que sin recibo el motor no puede distinguirlo de una opinion.

## 4. Secciones obligatorias del sobre

1. **`CLASIFICACION`** — una de las cuatro de arriba.
2. **`RECIBO REEJECUTABLE`** — comando exacto + `exit_code` + **entorno**: SO,
   version de Python, `sys.stdout.encoding` y locale si el fallo depende de ellos.
   Un recibo sin entorno no es reproducible por un tercero: el mismo comando da
   veredictos opuestos segun el shell (este repo lo tiene medido).
3. **`SUPERFICIE`** — `ruta:linea` del motor. Si no la localizas, dilo; una
   superficie mal atribuida cuesta mas que una ausente.
4. **`PROCEDENCIA POR CLAIM`** — tabla que separa **medido / citado / relato**:

   | Claim | Estado | Como lo verifica el motor |
   |---|---|---|
   | ... | medido aqui | `comando` |
   | ... | CITA del motor, no medicion mia | `sed -n 'X,Yp' fichero` |
   | ... | relato, no reproducible | no verificable; vale como motivacion |

   **Una cita del motor NO es un hallazgo tuyo.** Marcala como cita y da el comando
   que la verifica. Si la cita resulta falsa, tu escalado se cae entero — dilo tu
   antes de que lo descubra el motor.
5. **`ALCANCE HONESTO`** — que NO verificaste. Explicito.
6. **`TRADE-OFF DEL FIX`** — si propones fix: que se PIERDE al aplicarlo. Un fix sin
   coste declarado es un fix no pensado.
7. **`CONDICION DE RECHAZO`** — la frase que mas vale del sobre: *"si el motor
   reejecuta `<comando>` y da `<otro resultado>`, este escalado es erroneo y debe
   cerrarse"*. Un escalado que no puede refutarse no es evidencia.

## 5. Formato de salida: ficha del buzon

El sobre se escribe como `FP-<YYYYMMDD>-escalado-<slug-destino>.tickets.md` en
**el buzon del WORKSPACE DEL MOTOR**, no en el tuyo.

**No adivines la ruta: LEELA de tu propio link** (WOT-2026-053h):

```bash
python -c "import json;print(json.load(open(r'<destination_root>/.agent/config/motor_destination_link.json'))['motor_workspace_root'])"
```

El buzon es ese valor + `/.agent/collaboration/backlog_inbox/`.

Si el campo **no existe o es `null`**, tu link es anterior a `053h` o el motor no
declaro su workspace: **NO deduzcas la ruta** -- aplica el fallback de la seccion 1
y dilo. Ese campo puede faltar legitimamente; inventarlo, no.

**ESTE ES EL ERROR MAS FACIL DE COMETER, y ya ocurrio en el primer uso real del
contrato (2026-08-09).** El sobre se escribio en
`<tu-destino>/.agent/collaboration/backlog_inbox/` -- que existe, acepta el
fichero y no da ningun error -- y ahi **no lo ve nadie**: el Bloque 8.bis corre en
el cierre del MOTOR y hace glob sobre el buzon de SU workspace de dogfooding, no
sobre el de cada destino. Un sobre en tu propio buzon queda en la unica superficie
donde el fusionador no mira.

Regla operativa: el `<destination_root>` del 8.bis es el destino **del motor**
(su workspace de dogfooding), no tu repo. Si no puedes escribir ahi, **no
inventes la ruta**: aplica el fallback de la seccion 1 y dilo. Un sobre en el
buzon equivocado es peor que un fallback declarado, porque parece entregado.

**El sufijo `.tickets.md` es OBLIGATORIO y no es cosmetico:** el consumidor hace
glob de `backlog_inbox/*.tickets.md`. Un fichero en ese directorio con cualquier
otro nombre **no lo ve nadie** — queda como nota inerte.

Medido 2026-08-09 sobre el buzon del workspace: 8 ficheros `.md`, de los que **solo
2 llevan el sufijo**. Los otros 6 son deliberados (README, notas de contexto, trazas
post-fusion) y por eso el glob los ignora sin perdida — pero demuestran que el
directorio acepta cualquier nombre y **nada te avisa** si te equivocas: tu sobre
queda ahi, visible para un humano y ausente para el fusionador.

Formato, celdas y reglas del buzon: **`backlog_inbox/README.md`** y el **Bloque
8.bis**. No los repitas aqui; cumplelos. En particular: la ficha va **sin `Ticket` y
sin `Estado`** (los asigna el fusionador) y debe traer resueltas las demas celdas de
`Vista rapida` para que el fusionador no improvise.

### RECIBO DEC: OBLIGATORIO, y es un GATE BLOQUEANTE

Tu ficha **debe llevar escrito** un recibo DEC en una de estas TRES formas exactas:

```
DEC-<id> (motor)          DEC-<id> (destino)          DEC-no-aplica: <motivo>
```

El motivo de `DEC-no-aplica` va **escrito**: vacio o `n/a` no vale. Un `DEC-<id>`
que cites debe EXISTIR en el registro que su scope declara.

**Por que se dice aqui y no solo se remite al 8.bis** (medido 2026-08-09): esto no
es un criterio de INGESTA que aplique el fusionador, es un CAMPO que la ficha trae
o no trae. `check_dec_receipt.py` esta cableado en `prepush_check` y es
**BLOQUEANTE**: una ficha sin recibo **frena el cierre del motor entero**. El
primer sobre real llego sin el y bloqueo el preflight con
`[FAIL] DEC Receipt Barrier` -- un destino puede, sin saberlo, dejar el motor sin
poder cerrar. La ficha hermana del 2026-08-06 si lo traia, asi que el hueco era de
este contrato, no del emisor.

Si no sabes que DEC citar, la salida honesta es `DEC-no-aplica: <motivo>` con el
motivo real (p.ej. `DEC-no-aplica: escalado de defecto reproducible, sin decision
de diseno asociada`). Nunca lo omitas.

Precedente real que puedes usar como plantilla:
`FP-20260806-escalado-crear-texto-llm-2de2.tickets.md`.

## 6. Higiene de encoding (no es cosmetica)

Escribe el sobre **en ASCII** salvo que el caracter no-ASCII sea el objeto del
hallazgo. Motivo medido: en Windows con `cp1252` y salida redirigida, un unico `→`
tumba el despacho a una lente con `UnicodeEncodeError`, y el mensaje **acusa al
payload en vez de al encoding**. Si el caracter ES el hallazgo, nombralo por su
codepoint (`→`) y no lo pegues literal: una copia normalizada del sobre lo
convertiria en `->` y tu repro pareceria incoherente.

## 7. Que hace el motor con tu sobre

Lo consume el **Bloque 8.bis** del cierre canonico. No hay gate nuevo ni TTL propio:
si el motor cierra sesion, mira el buzon. Tu ficha se fusiona con `WOT-id` asignado,
o se degrada, o se vincula a una existente — y la ficha fusionada **se borra del
buzon**, que es tu senal de que fue procesada.

**No esperes ACK sincrono.** Si necesitas saber el veredicto, busca tu slug en
`backlog.md` del workspace tras el siguiente cierre.

## 8. Antes de citar el contrato: comprueba tu drift

Este prompt, el 8.bis y el formato del buzon **evolucionan**. Tu link al motor
(`motor_destination_link.json`) lleva un `motor_sha` PINEADO que no se actualiza
solo: puedes estar leyendo un contrato viejo y no enterarte.

El motor ya trae la senal. Ejecutala ANTES de redactar:

```bash
python <MOTOR_ROOT>/scripts/destination_context.py --bootstrap --project-root <destination_root>
```

Emite `[WARN] motor drift: N commits detras (link_sha=... vs HEAD=...)` cuando tu
pin se ha quedado atras. Es **SENAL, nunca gate**: no bloquea y no cambia el exit
code. Medido 2026-08-09: un destino real acumulaba **86 commits** de drift y su pin
seguia intacto.

**ESTATUS: esto es una NORMA, no una barrera** (declarado segun la definicion de
AGENTS.md). Verificado 2026-08-09: ningun camino que corra solo — `prepush_check`,
`.pre-commit-config.yaml`, workflows de CI — invoca `destination_context.py`, asi que
**depende de que TU te acuerdes de ejecutarlo**. No se disfraza de gate: si nadie lo
corre, nadie te avisa del drift.

Que hacer con el WARN: **no te fies de tu copia mental del contrato**. Re-lee este
prompt y el Bloque 8.bis desde `motor_root` (que es la ruta viva, no una copia) y
declara en tu sobre el `motor_sha` contra el que lo redactaste. Asi el fusionador
sabe que contrato estabas leyendo.

**Limite declarado:** existe un segundo guard, `compute_contract_surface_drift`
(WOT-2026-053a), que avisa cuando `prompts/`, `skills/`, `AGENTS.md` o `CLAUDE.md`
divergen — pero mide el **checkout de CONSUMO** del motor, no tu destino: desde un
destino devuelve `None` aunque tu pin este a 86 commits. Para ti la senal util es la
de `motor drift` de arriba, y por eso este contrato te la manda ejecutar
explicitamente en vez de darla por supuesta.
