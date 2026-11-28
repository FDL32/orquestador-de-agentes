ESTATUS: NORMA (no barrera). Ficha WOT-2026-160o (2026-11-08). Origen: P9 (vuelo_pilares.md, RATIFICADA, 96c8ad52-4bf5-4bf7-ad4a-9b6d4cad698d) y orden del usuario (mensaje 63ce37dc-9be5-47f2-af14-30ac7530dc36). Citado desde AGENTS.md ("### Espera => trabajo avanzable").

# Espera => trabajo en paralelo no perjudicial

1. Por que: 2026-11-06 CO-48 y el IM de 152q esperaron una hora sin lanzar; 2026-11-08 CO-56 cerro tres turnos de espera con "sigo esperando" y el usuario pidio la enumeracion dos veces.
2. Subordinacion: la enumeracion es obligatoria; hacer cada item pasa los 8 gates de `.agent/rules/common/do_now_vs_defer.md` (Hacer ahora vs aplazar; aplazar gana ante duda). El trabajo de espera NO es un arreglo: solo lectura, preparacion o registro, sin alterar el proceso principal ni decidir por el usuario.
3. Ejemplos por rol (pocos):
   - Coordinadora: verificar GO, registrar pendientes, preparar scope y mutantes, hallazgos, handoff, registrar la limpieza pendiente.
   - Implantador: preparar mutantes y la matriz del DoD mientras corre el builder.
   - Manager: leer el diff, preparar preguntas de revision.
   - Builder: ejecutar un gate focal, releer el DoD.
4. Interrupcion: al llegar el resultado esperado se detiene el trabajo de espera y se atiende.
5. Coste como registro: mide el contexto propio con `ctx_usage.py` (hoy vive en la carpeta de operaciones del vuelo, fuera del repo; el LATIDO declara su ruta), antes y despues de cada turno de espera. El tope se fija tras medir dos vuelos, sin umbral inventado.
6. Antipatrones:
   - Bloquear una tool-call o un bucle until/sleep en primer plano mas de 300 s. MEDIDO 2026-11-10 (CO-66, transcript del hilo): 11 llamadas Bash de 570 a 576 s en 24 h, todas con timeout explicito del llamante, esperando lentes y un reintento de BA07; el Stop hook no las ve (dispara por el texto del ultimo mensaje) y tick_trace no corre mientras la llamada bloquea. Regla: espera con run_in_background o Monitor (el harness avisa al terminar) y entre medias ejecuta la lista de trabajo avanzable. Revision LN-ESP1: `diseno/CONSOLIDACION_BUCLE_ESPERA_20261110.md` (barrera que bloquea: PreToolUse Bash, ticket pendiente).
   - Cerrar con "sigo esperando" sin lista. MEDIDO: `diseno/OPERACION_EN_CURSO_CO-56.md` entrada #31 (2026-11-08 11:56) -- CO-56 cerro tres turnos asi (tras IM-94 11:41, tras IM-95 11:47, tras IM-95 11:58) y solo enumero cuando el usuario lo pidio (mensajes f697e88c-328c-4376-be6b-a0d0a0cf18e8 y 63ce37dc-9be5-47f2-af14-30ac7530dc36).
   - Escribir una hora que no sale de `date`. MEDIDO: `diseno/APRENDIZAJE_RELEVOS_ENCADENADOS_20261105.md:357` (fila K-67, CO-40: horas sin medir en 4 mensajes) y `diseno/OPERACION_EN_CURSO_CO-15.md:174` (entrada 42: horas inventadas en 2 entradas).
   - Tocar el FLT de un IM vivo. Regla preventiva, SIN incidente medido en este vuelo.
   - Mutar el HEAD con una suite en curso. Regla preventiva, SIN incidente medido en este vuelo.
   - Lanzar mas de los topes. MEDIDO: `HALLAZGOS_protocolo_vuelos_autonomos.md:46` (H29: maximo 2 qwen3.6 concurrentes) y ficha WOT-2026-146a (topes 2/2/3, pendiente de asentar por el usuario).
   - Hacer commits en el motor antes de la suite final. Ver `AGENTS.md`, seccion "Orden de trabajo: AGRUPA los commits, la suite va la ULTIMA (WOT-2026-026t)".
   - Montar o traer la rama de preparacion tocando la rama probada, o hacerlo con una suite en curso en el worktree del vuelo. Regla preventiva, SIN incidente medido (C1, R2, R3, R4).
7. Lo que NO esta en la norma: lanzar triaje si hay menos de 2 IM (H178, RATIFICADA en P8 del canon).
8. Indicador: el de P9 (minutos de IM ocioso con cola pendiente) mas un contador nuevo (turnos de espera cerrados sin entrada sobre turnos de espera totales). Barrera futura: campo `idle_checklist` en `scripts/flight/tick_trace.py`, como ficha si el contador no baja a 0 en dos vuelos seguidos.
   Indicador O3: minutos de espera larga CON paquete listo al llegar el resultado / minutos de espera larga totales (se suma al de P9).

9. Mecanismo opt-in del Stop hook (WOT-2026-160p): el gancho puede exigir un
   marcador de decision de espera mediante el centinela
   `.agent/runtime/espera_checklist_mode.json`. Se arma, desarma y consulta
   con `python scripts/espera_checklist_mode.py on [--mode observe|block]`,
   `python scripts/espera_checklist_mode.py off` y
   `python scripts/espera_checklist_mode.py status`. Ademas, el arranque de
   sesion lo arma en `observe` si no habia ninguno (WOT-2026-161g); si el
   fichero ya existe -- `observe` vigente o caducado, ilegible, o `block` -- no
   lo toca: la caducidad de 24 h (WOT-2026-160z) se evalua en lectura y no se
   refresca.
   Las dos formas exactas son `[ESPERA:HECHO: avance realizado]` y
   `[ESPERA:NADA: no habia trabajo avanzable]`.

   El arranque de sesion avisa en `additionalContext` y `systemMessage` ante
   `CENTINELA-ESPERA-EXPIRADO` o `CENTINELA-ESPERA-ILEGIBLE`; el aviso es
   fail-open, solo lectura y no rearma el centinela. Hay silencio comprobable
   para centinela ausente, vacio/{}, y `{"mode":"off"}` (este ultimo se
   evalua antes de la caducidad). `{mode:off}` lo escribe `turn_off` (apagado durable P-E: estado escrito con fecha y motivo opcional --reason, idempotente, no la borra ni la re-arma el arranque). El
   remedio es `python scripts/espera_checklist_mode.py on [--mode observe|block]`.
   El mapeo del Stop hook es `EXPIRADO` o `SIN-FECHA-LEGIBLE`.

## Rama de preparacion

Esta seccion es NORMA, no barrera. Fija como desplegar una rama de preparacion durante una
espera larga y como traerla despues sin choques. Su invocador automatico, un guard cableado,
todavia NO existe y se registra como deuda en la subseccion 8.

### Estatus de origen (honesto)

Este bloque deriva de una propuesta revisada en DOS rondas de DESIGN_REVIEW con las lentes
BA02 y BA03. En la ronda 2 BA03 dio APPROVE y BA02 dio CHANGES por dos hallazgos mayores,
N-A y N-B, que se aplicaron. El tope de rondas se alcanzo: NO hay tercera ronda ni APPROVE
de BA02 sobre la version final. La rama prep/ nunca se ha creado con las herramientas del
vuelo. Lo que sigue sin verificar se declara en la subseccion 10.

### 1. Principio

La rama de preparacion existe para que el tiempo muerto de un proceso largo produzca artefactos
de implantacion listos: plan, fichas, FLT desnudo y disjunto, briefs, matriz del DoD y mutantes,
sin tocar el HEAD bajo prueba ni la rama que se va a publicar.

### 2. Reglas (R1 a R4)

R1. Preparar no es implantar. La preparacion por defecto es solo documentacion y fichas. El
borrador de codigo si puede redactarse durante la espera, sin ejecutar pytest. Integrarlo,
archivarlo o ejecutar su pytest exige que la suite en curso haya terminado. Nada se integra,
se archiva ni se cita como cerrado hasta traerse a la rama del vuelo.

R2. La rama de preparacion se crea desde el HEAD bajo prueba, en su worktree. No se commitea
sobre la rama probada ni sobre la rama que se publica.

R3. Regla unica contra el bloqueo compartido: con suite o `run_pytest_safe` en curso ningun
implantador corre pytest. No hay excepcion por `--wait-lock`: termina en rc 75 y solo vale para
focales entre lotes. En paralelo solo va trabajo sin pytest. La implantacion con codigo arranca
al terminar la suite.

<!-- ACTIVIDAD: A-12 | integrar un IM y verificar | PARCIAL | dueno=aqui | deuda=pendiente -->
R4. Traer sigue esta cadena real: (1) rebasar con `git rebase <base>`. La orden
`git rebase --ff-only` NO existe (medido 2026-11-14 y re-medido 2026-11-15, con git 2.53 y
el error "unknown option ff-only"). (2) Desde el worktree del vuelo, ejecutar `git merge --ff-only
prep/<lote>-<AAAAMMDD>`, solo con ese worktree sin suite ni proceso en curso, HEAD limpio y sin
`.git/rebase-merge` ni `MERGE_HEAD`. Antes se comprueba `git merge-base --is-ancestor <punta
del vuelo> prep/<lote>-<AAAAMMDD>`; el comportamiento sin y con rebase fue medido en un repo
de prueba el 2026-11-14. (3) La suite canonica completa corre UNA vez sobre la punta final y
solo cuando el lote va a publicarse; la suite va la ULTIMA y `tested_commit_sha == HEAD`, como
recoge `scripts/pre_handoff_guard.py:770`; no hay commits entre esa suite y la frase de push.
(4) La publicacion sigue `.agent/rules/common/flight_push_policy.md`: un push al final de todos
los tickets del vuelo, o uno intermedio solo con la frase canonica verificada por
`scripts/flight/verify_user_authorization.py`. La rama prep/ NUNCA se publica.

### 3. Mapa de choques (C1 a C13)

C1. GIT y checkout compartido: prep/ vive en su worktree; nunca se hace checkout en el
worktree del vuelo ni en el del workspace; solo la coordinadora la crea.
C2. Bloqueo de `run_pytest_safe` y CPU: se cubre con R3, sin duplicar la regla.
C3. Reloj: una suite que cruza una suspension puede dar rojo falso en TTL. Antes de una suite
larga se desactiva la suspension por inactividad en AC y se lee la duracion de cada fallo antes
de diagnosticar; un test de 1 h de TTL tardo 3641 s, medido 2026-11-14.
C4. Suite y lentes: el plan exige suite sin IM, lentes ni nonce vivos. Las lentes arrancan
despues de la suite; los subagentes de solo lectura de O4 y O5 no cuentan como vivos porque no
escriben ni usan pytest.
C5. Workspace y contabilidad: la contabilidad solo se escribe en main, una vez al integrar;
no se hace durante la preparacion. Hay 38 worktrees del workspace, medido 2026-11-14, pero
eso no convierte "un solo arbol" en la regla.
C6. `backlog.md`: solo la coordinadora lo escribe, solo con recibo y solo al integrar; prep/
nunca lo edita.
C7. IDs: los candidatos usan id PROVISIONAL; los definitivos y sus filas se asignan en lote al
integrar, con barrido y recibo por fila. Un id sin fila admitida no sale del paquete.
C8. Roster, registry y ledger de avisos: la preparacion no lanza IM ni crea hilos; solo la
coordinadora los toca.
C9. Topes del vuelo: IM simultaneos, FLT disjuntos, cuentas distintas, una ronda de lentes a
la vez. La preparacion no los relaja ni los reserva en silencio.
C10. Nombres: se usa el prefijo prep/, no flight/ ni implantador/; queda a verificar en un
ticket posterior a esta norma que `integrate_ticket.py`, el latido y el roster no hagan glob
sobre prep/.
C11. Push: se aplica R4(4); prep/ no se publica nunca.
<!-- ACTIVIDAD: A-18 | ctx_acumulado y marcado del objetivo | PARCIAL | dueno=aqui | deuda=pendiente -->
C12. Contexto de la coordinadora: las lecturas pesadas van a subagentes de solo lectura con
resumen acotado. Se mide con `ctx_acumulado.py`, el del latido, en la carpeta de operaciones
del vuelo y fuera del repo; el punto 5 ya declara `ctx_usage.py` fuera del repo para sesiones
ajenas.
C13. Lentes con escritura: tras cada ronda, `git status` de ambos repos debe tener 0 lineas y
el HEAD no debe cambiar; si no, la ronda no cuenta. Como `diseno/` esta ignorada por git,
ademas se compara un listado del arbol de diseno/ con ruta, tamano y fecha antes y despues.

### 4. Cuando SI y cuando NO

SI: espera mayor que T_min y cola pendiente sin ficha lista. T_min = 15 min es PUNTO DE
PARTIDA e incluye el coste de montar. La suite dura entre 39 y 99 min, medido 2026-11-14:
39 min 28 s limpia y 1 h 40 min con una suspension. AGENTS.md aun dice "~7 min": cifra
desactualizada y deuda de otra fila.

NO: espera menor que T_min; si exigiria tocar la rama probada; cola vacia; o la decision es
del usuario. El coste es una suite completa solo al publicar y solo hay una rama de preparacion
activa.

### 5. Paquete y recibo, y donde vive cada cosa (residencia)

El paquete contiene una tabla de candidatos con id PROVISIONAL, una frase, FLT desnudo,
`deliverable_type` y dependencias; pares de FLT disjuntos; brief por ticket; zona caliente y
su resultado; y un RECIBO con sha de la base, ficheros leidos, comandos con rc literal y lo no
verificado.

La carpeta de operaciones del vuelo es local e ignorada por git: la ignora el `.gitignore` del
WORKSPACE, no el del motor, via `.agent/runtime/*`. El paquete no entra en prep/ ni se versiona,
y un `git clean -fdx` lo borraria. El RECIBO se respalda fuera de los repos con su sha256 al
crearlo y al cerrar, sin escribir rutas absolutas de usuario. Lo que deba sobrevivir se copia a
`.agent/planning/staged/<lote>-<AAAAMMDD>/` al integrar o se commitea como documentacion en
`prep/<lote>-<AAAAMMDD>`. Un guard que corra desde el motor recibe la ruta del vuelo por
argumento. Sin recibo la preparacion no cuenta como avance en el HANDOFF. El RECIBO alimenta
el marcador del Stop hook, punto 9 de esta norma: `[ESPERA:HECHO: <avance>]`.

### 6. Zona caliente (control mecanico, reproducible)

`ZONA_CALIENTE = git diff --name-only origin/<rama del vuelo>..<punta de la rama del vuelo>`
es el delta no publicado, obtenido con un comando. Se recalcula en cada rebase de prep/ y antes
de lanzar cada IM, y se contrasta con el FLT de cada ticket preparado: si hay solape, no entra.
No se incluye lo que toca la suite.

### 7. Ciclo de vida

La rama es `prep/<lote>-<AAAAMMDD>`, una rama activa por proceso largo. Al caducar se rebasa o
se descarta con motivo. El respaldo usa `git bundle create` y `git bundle verify`. Los commits
de prep/ pasan los mismos hooks; NO se usa `--no-verify`. Al integrar o descartar se limpia el
worktree. Al llegar el resultado la preparacion CEDE: se atiende primero ese resultado y
despues se rebasa.

### 8. Barrera: deuda declarada (norma sin invocador no es barrera)

Falta el guard `check_prep_branch_isolation.py`, que deberia comprobar un commit de prep/* que toca un fichero de la zona caliente vigente, prep/* sin RECIBO con la ruta del vuelo por argumento, y una base de prep/* que no sea ancestro de la punta del vuelo. Su cableado iria en el latido o `tick_trace`, o en `prepush_check`.

DEUDA DECLARADA SIN TICKET: hasta que esta norma aterrice no hay fila admitida para ese guard y esta norma NO lo cita como existente; el ticket hijo POR ADMITIR despues de que esta aterrice. El criterio de salida es: guard cableado y probado con un mutante que mete un fichero de la zona caliente.

### 9. Optimizaciones

O1. Orden de valor: FLT desnudo y disjunto, brief con el DoD literal, matriz del DoD, tabla
de zona caliente, mutantes y hallazgos.
O2. Plantilla unica del paquete, la de la seccion 5.
O3. El indicador remite al punto 8 de esta norma.
O4. La tabla de candidatos la produce un subagente de solo lectura; la coordinadora la verifica
por muestreo declarado.
O5. Al arrancar se toma la instantanea de la zona caliente y se despachan subagentes de lectura
antes de la suite; las lentes quedan en cola para el primer tick posterior a la suite.

### 10. Lo que NO esta resuelto (se declara)

- No esta probado que `integrate_ticket.py`, roster y latido traten prep/* como lote del mismo
  vuelo.
- T_min (15 min) y el tope de una rama son puntos de partida; el coste de montaje no esta
  medido.
- La rama de workspace para contabilidad no se ha ejecutado; hasta probarla, la contabilidad se
  aplica una sola vez al integrar.
- AGENTS.md dice que la suite tarda "~7 min" frente a 39 a 99 min medido 2026-11-14; queda
  para un ticket de documentacion aparte.
