# Contrato de ficha de backlog: redactada_por

ESTATUS: NORMA para la redaccion humana; la barrera automatica es c-14 en closeout/pre-push.

## 1. Contrato

Cada ficha de backlog debe tener una sola linea con la clave exacta `redactada_por`.
La comparacion del guard no distingue mayusculas como tolerancia, pero las fichas se escriben en minusculas.
La clave `redactada_por` usa el vocabulario `tr`, `co`, `im`.

Valores permitidos: `tr`, `co`, `im`

- `tr`: ficha redactada por una sesion de triaje TR. Exige `triador_modelo` y lineas `lente_N` con APPROVE de otras familias.
- `co`: ficha redactada o admitida por una sesion coordinadora CO.
- `im`: ficha redactada o dirigida por una sesion implantadora IM.

El valor es el rol de la sesion que admitio o dirigio la ficha; no decide mas que eso.

## 2. Cuando se comprueba

Se comprueban las altas posteriores a `LENSES_CUTOFF_SHA`, leyendo la ficha del COMMIT DE ALTA.
Una edicion sin commitear no cuenta porque el alta debe ser reproducible desde su commit.

## 3. Causas y accion

- `clave_ausente_o_mal_escrita`: anadir o corregir la unica clave `redactada_por`.
- `clave_duplicada`: conservar una sola linea `redactada_por`.
- `valor_fuera_de_vocabulario`: corregir el valor usando el vocabulario permitido.
- `ficha_no_presente_en_commit_de_alta`: incluir la ficha en el commit que da de alta la fila.

## 4. Comprobacion antes del commit de alta

Antes de commitear el alta, ejecutar:

`python scripts/check_backlog_admission.py --check-ficha <ruta>`

El limite declarado es que no hay integracion en `backlog_db_compare.py --emit-recibo` (ticket hijo 161y propuesto).
Esta comprobacion al alta es norma + CLI, y la barrera automatica sigue siendo closeout/pre-push
(`prepush_check.run_backlog_admission_check` y el hook del destino).

## 5. Residuo de hook de push (m-06)

NORMA: un rc distinto de cero conocido de un hook de push no se difiere como residual sin ticket y dueno.
El informe del push debe nombrar ticket y dueno; si no existen, se abren antes de diferir.
La comprobacion automatica queda pendiente de ticket posterior.
