# Revision proporcional al riesgo

## Alcance y fuente normativa

Esta regla define la decision mecanica previa a una ronda de revision del vuelo.
La herramienta que la ejecuta es `scripts/flight/review_level.py`; sus globs son
la unica lista de superficies de alto riesgo. Esta regla no duplica el contrato
operativo de `prompts/ensemble_loop.md` ni el criterio de decision de
`.agent/rules/common/do_now_vs_defer.md` y CEM v0 (AGENTS.md, seccion CEM):
ambos son la fuente normativa por
remision (X-09, "skill apunta, prompt gobierna").

`review_level.py` es una HERRAMIENTA DE DECISION que corre la coordinadora antes
de lanzar lentes. NO es una barrera automatica ni esta cableada: hoy nadie la
invoca por si solo. La duena es la coordinadora del vuelo. El hijo diferido que
podra cablearla es `integrate_ticket` (cuando exista una decision de proceso y
su gate correspondiente); este ticket no crea ese cableado y no se registra en
`check_guard_wiring` como si fuera una barrera.

## Niveles y medicion del diff

La herramienta imprime `NIVEL=completo` o `NIVEL=delta`, junto con razones
mecanicas. El nivel solo sube:

- `completo` si el diff toca una familia de alto riesgo declarada por el script,
  la ficha declara riesgo alto, o el cambio de produccion alcanza el umbral.
- `delta` solo si el cambio no toca una familia de alto riesgo, la ficha no
  declara riesgo alto y las lineas de produccion estan por debajo del umbral.
- Un rango vacio, una referencia ilegible, una ficha ilegible, un ticket ausente
  o un ticket duplicado son `completo` fail-closed con rc 2.
- Si `--prev-level completo` y el calculo seria `delta`, el nivel se conserva en
  `completo` salvo que `--lower-reason` contenga texto no vacio. En ese caso se
  permite `delta` y se imprime la razon explicita de la bajada. Un nivel previo
  desconocido es `completo` con rc 2; espacios no son un motivo.

Con `--reviewed-sha`, todos los criterios -globs, umbral y si `scripts/` esta
vacio- se calculan sobre el diff entre los arboles `reviewed-sha` y `sha`. Sin
`--reviewed-sha`, se usa el diff entre `base` y `sha`. La comparacion es
`git diff reviewed-sha sha`, no `git log`, y no exige que el primer SHA sea
ancestro: los amend son arboles hermanos y siguen siendo comparables. El caso
de rebase/amend queda cubierto por commits hermanos temporales creados por el
fixture `_sibling_repo` del test focal.

La ficha puede ser una fila real de `backlog.md`, seleccionada por `--ticket` y
`--backlog`. La fila tiene la forma `| Media | <ticket> | ...` y declara riesgo
alto unicamente con el token literal `[RIESGO: alto]` dentro de esa misma linea;
no se edita el backlog para anadirlo. Un brief alternativo puede declarar la
linea exacta `RISK_LEVEL: high`. No se acepta una marca multilinea ni una fila
ausente o duplicada.

El umbral provisional es **50 lineas**, y esta **NO MEDIDO**: las muestras 153s,
153w y 153x disponibles caen en superficies de alto riesgo o documental, por
lo que ninguna mide la zona donde decide el umbral. Se cuentan lineas anadidas
mas eliminadas de produccion; produccion significa `.py`, `.ps1` o `.sh` fuera
de `tests/` y `docs/`. La medicion diferida del ticket exige aplicar esta regla
a los tres tickets siguientes y registrar rondas y horas en `flight_tickets.jsonl`.
Hasta entonces el umbral es conservador y nunca rebaja un riesgo alto. La
lectura conservadora es: delta exige produccion < 50 lineas; 50 ya es completo.

## Parada y operacion

La revision se cierra cuando dos rondas seguidas no hallan un defecto que
corrompa, pierda o silencie un GO o un aviso. Lo demas se registra como deuda
con dueno y vencimiento. El SHA se congela antes de lanzar lentes y el delta se
calcula contra el SHA ya revisado. El implantador corre solo los tests que toca;
la coordinadora corre la puerta de ficheros una vez. Las mutaciones se piden
solo para guards nuevos de produccion.

Cuando una peticion del usuario no es proporcional al riesgo, la coordinadora
lo dice en una o dos lineas, propone la alternativa ligera y deja que el usuario
decida; nunca rebaja en silencio (O10). La eleccion concreta de lentes, nonce,
quorum e integracion pertenece a `prompts/ensemble_loop.md` y a la coordinadora;
esta herramienta solo clasifica.

## Cobertura focal

Los tests de `tests/unit/test_review_level.py` mantienen un control negativo por
familia con rutas versionadas reales del motor: consentimiento, guards, hooks,
ruleset, lentes, integracion, estado compartido, push/sync y cierre. La familia
backlog/FLT se conserva para rutas del workspace destino, pero no tiene ejemplo
versionado en `repo_motor` y por eso se declara explicitamente sin falso ejemplo.
Tambien se cubren solo-tests/docs = delta, fronteras 49/50/51, rango vacio =
completo, entrada ilegible = completo, pequeno cambio dentro de glob alto =
completo, y la monotonicidad de nivel anterior.
