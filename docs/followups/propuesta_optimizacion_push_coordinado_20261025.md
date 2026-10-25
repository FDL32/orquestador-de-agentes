---
status: proposal
owner: sesion-alvarovans-vuelo_nocturno_alvarovans_20261024
related: scripts/check_backlog_admission.py, scripts/backlog_db_compare.py, scripts/check_backlog_contract.py, .agent/rules/common/t3_ade_coordination.md, .agent/rules/common/t3_delegate_task_verification.md
---

## ENCARGO PARA LA LENTE (rol challenger, fase DESIGN_REVIEW)

NO implementes nada. Da veredicto `APROBAR` / `APROBAR_CON_CAMBIOS` / `CAMBIOS` sobre la
propuesta de abajo, evaluando COHERENCIA INTERNA y SUFICIENCIA, no re-verificando el
filesystem (el Manager ya corrio los comandos citados).

INVENTARIO DE EVIDENCIA: todo lo citado abajo se midio EN VIVO esta sesion (2026-10-25,
`vuelo_nocturno_alvarovans_20261024`), coordinando 3 sesiones T3 (alvarovans, brabander,
memoria-opus55) sobre el mismo repo_motor + 3 ramas distintas de repo_destino.

PRESUPUESTO DE EXPLORACION: no abras ficheros fuera de este documento.

SALIDA DECLARADA: marca `NO VERIFICABLE` por punto si no puedes contrastarlo desde tu cwd.

# Propuesta: coordinacion de push multi-sesion y gate de admision de backlog (2026-10-25, 2a pasada)

## 1. Errores y puntos de mejora medidos esta sesion

### 1.1 Colision de ID de backlog NO detectada hasta el push (real, resuelto en vivo)
Dos sesiones (alvarovans y memoria-opus55) dieron de alta `WOT-2026-126a` de forma
independiente y concurrente (09:13 vs 10:33), con contenido totalmente distinto. El barrido
previo de `backlog_admit.md` (`find_similar_signals.py`) NO lo cazo porque cada sesion solo
barre SU PROPIO checkout -- no ve la rama hermana. Se detecto solo porque memoria-opus55
corrio su propio barrido de refs cross-rama DESPUES de ver el commit motor de alvarovans
citando el ID en el subject. Resuelto: renumerado manual a `WOT-2026-127c` tras barrido
cross-rama explicito (`git show <rama>:.agent/collaboration/backlog.md`).
**Gap:** `scripts/backlog_db_compare.py --emit-recibo` calcula su corpus SOLO contra el
checkout local; no hay ningun paso que barra `git ls-remote`/ramas hermanas conocidas ANTES
de la emision del recibo (ventana pre-commit) -- no antes de proponer el ID en si, que es un
paso separado y anterior.

### 1.2 El hook `check-backlog-admission` no distingue corrupcion real de concurrencia esperada
El hook fail-closed audita el rango `origin/main..HEAD` recontando el corpus en cada commit
de alta. Con 3 sesiones admitiendo tickets en paralelo sobre la MISMA rama (antes de rebase),
el recuento del padre YA NO coincide con el declarado en el recibo -- el veredicto
`ALTA_CONCURRENTE` es el resultado ESPERADO de trabajar en paralelo, no evidencia de un
recibo fabricado. Hoy el hook emite el mismo `rc=1` bloqueante para `ALTA_CONCURRENTE`
(concurrencia benigna, reparable re-emitiendo el recibo tras rebase) y `RECIBO_INCOHERENTE`
(el recibo se emitio con el corpus YA mutado -- un defecto de secuencia real). Mezclar ambos
en un solo `rc=1` sin distincion empuja al operador a tratar los dos casos igual.

### 1.3 Reparar un recibo ya publicado puede exigir reescribir decenas de commits
Se intento reparar un recibo `RECIBO_INCOHERENTE` de un commit (`WOT-2026-117a`) ya publicado
en una rama remota. Al medir el rango real, ese commit tenia MAS DE 40 commits legitimos
encima en la misma rama (cierres de ticket, un vuelo completo, merges de `origin/main`),
varios de los cuales TAMBIEN tocan `backlog.md`. Reescribirlo exige un rebase de alto riesgo
sobre historia ya publicada, con riesgo de desincronizar en cascada los recuentos de corpus
de cada commit intermedio. Decision tomada: NO reescribir (deuda declarada, no se fuerza
push). **Gap:** no existe ningun criterio escrito de "cuando SI vale la pena reparar un
recibo retroactivamente vs. cuando se declara deuda y se sigue" -- la decision se tomo ad-hoc
en el momento.

### 1.4 Dos sesiones resolviendo conflictos de merge en `backlog.md`/`backlog_done.md` a mano
El merge entre dos ramas destino (alvarovans + memoria-opus55) produjo 7 bloques de conflicto
de texto en `backlog.md` y 3 en `backlog_done.md`, resueltos a mano por el Manager (criterio:
"version mas reciente/cerrada gana"). El gate `check_backlog_contract.py`, corrido DESPUES de
resolver a mano, caza 2 clases de defecto que la resolucion manual introdujo sin que el
Manager los viera venir: una fila `pending` en `backlog.md` que YA estaba `completed` en
`backlog_done.md` (contradiccion viva-vs-archivada), y 4 filas duplicadas DENTRO del propio
archive (el mismo ticket archivado 2 veces, con texto byte-identico). El gate si los caza,
pero solo DESPUES del merge completo -- no hay ayuda estructurada DURANTE la resolucion de
conflictos que senale "esta fila que vas a mantener ya existe en otro estado en otro lado".

## 2. Propuesta

- **(a) Barrido cross-rama en la emision del recibo:** `backlog_db_compare.py --emit-recibo`
  anade un flag opcional `--peer-refs <ref1,ref2,...>` (o detecta automaticamente combinando
  `git for-each-ref refs/remotes` con un `git ls-remote` si no se pasa: `for-each-ref` solo ve
  refs YA fetchadas, asi que sin `ls-remote` un push hermano sin fetch previo no dispararia el
  warning) y advierte (no bloquea, el Manager decide) si el ID candidato ya aparece como fila
  viva en alguna rama hermana. El warning se dispara en la EMISION del recibo (ventana
  pre-commit), no en el momento de proponer el ID: cerrar el gap de 1.1 hasta la ventana
  pre-commit es el alcance declarado; proponer el ID sigue siendo un paso anterior y separado.
- **(b) Separar el veredicto del hook en dos clases de salida:** `RECIBO_INCOHERENTE` sigue
  `rc=1` bloqueante (recibo emitido contra un corpus ya mutado -- defecto de secuencia real).
  Para `ALTA_CONCURRENTE`, UN SOLO predicado exacto que particiona el espacio de casos: WARN
  no bloqueante SI Y SOLO SI el corpus al padre del commit auditado coincide con el corpus al
  padre de OTRO commit de alta DEL MISMO RANGO auditado (concurrencia legitima entre
  sesiones); en CUALQUIER OTRO caso escala a `rc=1` -- incluido el caso intermedio en que el
  corpus del padre coincide con un commit auditado que NO es de alta (sospechoso: el corpus
  no cuadra con ningun alta conocida del rango). No hay modo no-default indefinido: este es
  el unico comportamiento nuevo del hook, sin flag que lo altere. Mutation-verify (3 casos):
  (1) alta concurrente real, corpus del padre = corpus al padre de otra alta del rango ->
  WARN, exit 0; (2) alta con corpus que no cuadra con nada del rango -> `rc=1`; (3) caso
  intermedio, corpus del padre coincide con un commit auditado no-alta -> `rc=1`.
- **(c) Criterio escrito para "reparar vs declarar deuda":** anadir a
  `.agent/rules/common/t3_delegate_task_verification.md` (o un modulo nuevo si no cabe) una
  regla corta: reparar un recibo YA PUBLICADO solo si (i) NINGUN otro ref publicado (otra
  rama, tag, o merge dentro de una rama ajena) referencia el commit ni su historia, y (ii) el
  commit esta en ventana near-tip de su rama: a lo sumo `N = 5` commits publicados encima,
  que se reescriben juntos en un solo rebase (N pineado, sin "p.ej."); si no cumple AMBAS,
  se declara deuda con ticket dueno y NO se fuerza push.
- **(d) Pre-chequeo de duplicados antes de cerrar un merge manual:** tras resolver conflictos
  a mano en `backlog.md`/`backlog_done.md` y ANTES de `git commit`, correr
  `check_backlog_contract.py` como paso intermedio obligatorio (ya se hace, pero la leccion es
  hacerlo ANTES de considerar el merge "resuelto", no solo antes del push) -- esto ya es
  practica real de esta sesion. Se documenta como UNA nota en `t3_ade_coordination.md`
  Seccion 3 (la situacion es multi-sesion; `backlog_admit.md` gobierna el alta de sesion
  unica), evitando doble declaracion normativa (X-09). Es la mitigacion MINIMA elegida: no
  da ayuda estructurada DURANTE la resolucion de conflictos (el gap 1.4 queda abierto y asi
  se declara), solo convierte en obligatorio el chequeo antes de dar el merge por resuelto.

## 3. Non-goals

No propone automatizar la resolucion de conflictos de `backlog.md` (sigue siendo criterio
humano/Manager); no propone un mecanismo de lock distribuido entre sesiones T3 para altas de
backlog (fuera de alcance, el barrido cross-rama de (a) es deteccion, no prevencion).

## 4. Verificacion

- (a): test que simula 2 branches con el mismo ID y confirma que el flag advierte; y un
  segundo test del camino auto-detect SIN flag, incluyendo un push hermano sin fetch previo
  cubierto por el `git ls-remote` del modo auto-detect.
- (b): mutation en los 3 sentidos del predicado (casos 1-3 declarados en (b)) sobre un
  fixture de rango con 2 altas concurrentes legitimas, 1 alta con corpus huerfano y 1 corpus
  de padre que coincide con un commit auditado no-alta.
- (c): ninguna verificacion de codigo, es una norma; se cita en el modulo.
- (d): ninguna verificacion de codigo nueva, es documentacion de practica ya ejercida.
