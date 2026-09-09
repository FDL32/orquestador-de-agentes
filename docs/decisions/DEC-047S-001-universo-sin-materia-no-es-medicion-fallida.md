# DEC-047S-001: `inspeccionados == 0` sin materia auditable no es un falso verde

**Ticket:** WOT-2026-047s (ampliacion)
**Fecha:** 2026-09-09
**Estado:** DECIDED
**Autor:** Operador (decision de diseno), instruido por los bucles L811 (3 rondas) y
L812 (2 rondas), 6 backend_keys distintas (BA05 codex, BA10 deepseek, BA11 qwen,
BA12 mimo, BA13 gemma, BA16 glm)

## Contexto

El `Quality Bar` de `<MOTOR_ROOT>/repo_charter.md` dice, literal:

> **Todo probe publica su denominador:** `denominador / inspeccionados / hits / saltados`
> + LISTA de saltados. `inspeccionados == 0` -> ROJO, nunca verde.
> *(La regla que 8 falso-verdes ensenaron.)*

`scripts/check_encoding_guard.py` la incumple hoy en su forma Y en su fondo:

- **Forma:** no publica NINGUN denominador. En todos sus caminos verdes la salida es
  literalmente vacia (`check_encoding_guard.py:188-189`, `if not files_to_check: return 0`).
- **Fondo:** ese `exit 0` mudo es indistinguible de una auditoria limpia.

> **Snapshot fechado de evidencia (2026-09-09), NO criterio de aceptacion**
> (regla `WOT-2026-024t`): con el indice limpio, `python scripts/check_encoding_guard.py`
> -> `exit_code 0`, salida vacia, 0 ficheros nombrados. Con el indice sucio y mojibake
> real, el MISMO comando -> `exit_code 1` + `Mojibake detected`. Ninguna cifra de este
> DEC es un DoD.

Al redactar el fix aparecio una colision REAL, y es lo que este DEC decide: el hook de
pre-commit invoca el guard con `pass_filenames: false` (sin argumentos), y en un commit
que solo toca binarios su universo queda legitimamente sin materia auditable. Aplicar el
literal del charter ahi convierte un commit normal en un fallo.

## Por que NO se resolvio sin DEC (dos intentos, ambos refutados)

Se declara porque el proceso es la evidencia de que esta decision es NECESARIA y no
comodidad del ejecutor.

1. **Intento 1 -- "`exit 0` siempre".** Refutado por BA10: es exactamente el verde mudo
   que la regla prohibe, en un ticket cuyo objeto ES un falso verde.
2. **Intento 2 -- "el exit code lo decide la VIA (hook vs explicita)".** Refutado por
   BA05: *"clasificar por via de entrada no dice nada sobre si habia algo que auditar"*.
   Un hook con 30 `.py` staged y otro con 0 entran por la misma via y son estados opuestos.
3. **Intento 3 -- "el precedente `pii-leak` ya lo autoriza".** Refutado por BA10 y BA05 en
   DOS rondas consecutivas. El precedente (`check_destination_pii_leak.py:207`,
   `if not audits and discovery.links_total: return 2`) SI distingue "no habia universo"
   de "habia y no se audito" -- y su docstring dice *"A machine with NO links at all is
   the legitimate case and still exits 0"*. **Pero** su rojo es ante un ERROR OPERATIVO
   (apuntar `--motor-root` mal excluye los 17 destinos por identidad de dogfooding),
   no ante un universo sin materia. **El precedente ilumina la distincion; no autoriza
   por si solo a cambiar el significado literal del Quality Bar para otro guard.**

Veredicto convergente de las dos lentes, sostenido en 3 rondas: **es una decision del
dueno del charter, no una lectura derivable.** Este DEC la toma.

## Decision

### 1. El Quality Bar se AMPLIA con una clausula de excepcion nombrada

`inspeccionados == 0` sigue siendo ROJO **por defecto**. Se anade la unica excepcion:

> `inspeccionados == 0` es VERDE **solo si** el universo carece de materia auditable por
> una propiedad del CONTENIDO (no por un fallo de la medicion) **y** el probe publica
> `denominador / inspeccionados / hits / saltados` con la LISTA de saltados.
>
> Si `inspeccionados == 0` proviene de una MEDICION FALLIDA -- el invocador pidio auditar
> un universo y no se audito -- sigue siendo ROJO, sin excepcion.

**El discriminante es la CAUSA del cero, y debe ser derivable en codigo**, no una
apreciacion del autor del guard.

### 2. Por que esta excepcion NO vacia la regla

El `failure_mode` que `OBJ-002` declara es *"un destino se salta EN SILENCIO y el censo
sale verde"*. La excepcion exige publicacion COMPLETA (denominador + lista), asi que el
caso que habilita **no es silencioso** y por tanto no es el fallo que la regla existe para
matar. Un cero publicado con su causa es auditable; un cero mudo no.

La regla conserva sus dientes donde importa: los 8 falso-verdes que la originaron eran
ceros MUDOS.

### 3. Alcance: TODO probe del motor, no solo el guard de encoding

La clausula se redacta en el charter, luego aplica a cualquier probe. No se crea una
excepcion ad-hoc para un fichero: se nombra una distincion que ya existia de facto en
`check_destination_pii_leak` y en `check_backlog_contract` (*"fuera del denominador POR
DISENO"*), y que hasta hoy cada guard resolvia por su cuenta sin contrato comun.

### 4. Lo que este DEC NO decide

- **NO** autoriza a ningun guard a callar su denominador. La publicacion es CONDICION de
  la excepcion, no un extra.
- **NO** cubre el caso de universo equivocado (`WOT-2026-067h`): auditar un universo
  DISTINTO del pedido no es "sin materia", es medicion fallida -> ROJO.
- **NO** modifica `OBJ-002` ni su `success_criteria` sobre `--fleet`, que habla de un
  probe de censo cuyo cero SIEMPRE es error operativo.

## Consecuencias

- `repo_charter.md` gana la clausula de excepcion en su `Quality Bar`.
- `check_encoding_guard.py` pasa a publicar su denominador siempre, y su `exit 0` con
  universo sin materia queda AUTORIZADO y trazado, en vez de ser una violacion silenciosa.
- Cualquier guard futuro que quiera salir verde con `inspeccionados == 0` tiene una
  condicion explicita que cumplir, en vez de un precedente que interpretar.

## Reversibilidad

**Alta.** Revertir la clausula deja el literal anterior; el unico coste es que el guard de
encoding volveria a bloquear commits de solo binarios, que es precisamente el efecto que
esta decision evita. Ningun artefacto depende de la excepcion salvo el propio guard.
