# Corpus de calibracion del umbral de entropia (WOT-2026-041n)

Mediciones de tokens candidatos extraidas de artefactos REALES del sistema. Existe
para desbloquear la deuda declarada en `scripts/ensemble_dispatch.py`: el umbral
`_ENTROPY_BITS_THRESHOLD = 4.0` se eligio como default conservador y **nunca se
calibro**, porque los bundles reales vivian en `.agent/runtime/tmp/` (gitignored) y
se purgaron antes de poder medirlos.

## Que hay aqui

| fichero | que es |
|---|---|
| `metrics_20260811.jsonl` | 2210 filas, una por token candidato. Solo metricas. |
| `extract_entropy_corpus.py` | el extractor que lo regenera. |

Campos por fila: `longitud`, `entropia`, `clases`, `bloqueado_por_detector_actual`,
`forma`, `fuente_idx`.

**No contiene el texto de los tokens.** Verificado en el momento de la extraccion:
0 rutas de maquina, 0 correos, 0 cadenas de 32+ caracteres. Esa es la razon de que
este corpus SI pueda vivir versionado mientras que los bundles de origen no podian:
los bundles llevaban 58 rutas de maquina, 12 correos y 7 tokens de alta entropia.

## Snapshot fechado 2026-08-11 (EVIDENCIA, no criterio de aceptacion)

Barrido de 519 ficheros -> 2210 tokens candidatos -> **143 los bloquearia el
detector actual**. Reparto por forma de esos 143:

    ruta_con_underscores         49
    mixto_sin_forma              47
    nombre_fichero_fechado       26
    identificador_con_guiones    20
    base64_probable               1

Uno de los 143 tiene la forma que el filtro busca. Los otros 142 son estructuras
de nombres del propio repositorio.

Estas cifras son un SNAPSHOT FECHADO, no un DoD: un criterio que fija un numero
caduca solo (AGENTS.md, "criterio invariante, evidencia fechada").

## Limites declarados

- **`forma` es una HEURISTICA sobre la FORMA del token, no un veredicto.** No dice
  "secreto" ni "falso positivo": eso exige criterio humano y es trabajo de
  WOT-2026-041n. Un reparto por forma ORIENTA la calibracion; no la cierra.
- **El corpus tiene un sesgo conocido y medido.** El primer barrido, solo sobre
  bundles, dio 0 nombres-de-fichero entre los bloqueados -- y ese mismo dia dos
  nombres de fichero habian bloqueado un envio legitimo. Causa: el emisor los
  habia ACORTADO en los bundles para que pasaran, de modo que el corpus perdio
  justo los casos que documentaban el falso positivo. Por eso el extractor barre
  tambien fichas y prompts, que los conservan intactos. **Leccion transferible: la
  evasion de un filtro no solo lo esquiva, borra la evidencia de que se equivoca.**
- **No cierra WOT-2026-041n.** Su criterio de salida exige ademas barrer el umbral
  contra la suite real y publicar AMBOS bordes de la meseta. Esto aporta el dato
  que faltaba, no el barrido.

## Como regenerarlo

    python tests/fixtures/entropy_corpus/extract_entropy_corpus.py \
      --workspace <repo_destino> \
      --out tests/fixtures/entropy_corpus/metrics_<fecha>.jsonl

`--workspace` es OBLIGATORIO y no tiene default: el extractor vive en el motor y
lee superficies del destino, asi que la topologia entra como argumento en vez de
derivarse de `__file__`. La primera version SI la derivaba y, al mudarla aqui,
leyo 1 fichero en vez de 519 -- el README prometia una regeneracion que no
funcionaba. Verificado 2026-08-11: control positivo rc=0 reproduciendo el corpus
publicado BYTE A BYTE (310606 bytes), control negativo rc=2 con un workspace
inexistente.

Determinista: no depende del reloj ni del orden del sistema de ficheros.

Origen: bucle adversarial L1113 (2026-08-11). La lente de alternativas midio que
"el texto es ruido para la calibracion matematica" -- basta con la distribucion, y
cuatro numeros no contienen datos personales. Esa observacion es la que hace
posible este fichero.
