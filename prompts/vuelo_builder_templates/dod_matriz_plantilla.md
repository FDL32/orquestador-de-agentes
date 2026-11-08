<!-- Marcadores declarados: {{CLAUSULA_ID}} {{CLAUSULA_TEXTO}} {{COMPROBACION}} {{AMBITO}} {{CONTEO_ESPERADO}} {{CONTROL_POSITIVO}} -->

## Plantilla

| id | texto literal | comprobacion | ambito | conteo esperado | control positivo |
|---|---|---|---|---|---|
| {{CLAUSULA_ID}} | {{CLAUSULA_TEXTO}} | {{COMPROBACION}} | {{AMBITO}} | {{CONTEO_ESPERADO}} | {{CONTROL_POSITIVO}} |

## Ejemplo

| id | texto literal | comprobacion | ambito | conteo esperado | control positivo |
|---|---|---|---|---|---|
| b-01 | La admision exige una matriz de DoD | `parse_matriz_table` acepta la tabla | test unitario | 1 tabla | La prueba real devuelve dos tablas y tres filas |
| b-02 | La matriz no se exige retroactivamente | ausencia de rutas de backlog en este test | tests/unit/test_dod_matriz_plantilla.py | 0 rutas | n/a: el test no abre ni importa esas rutas |

La celda `control positivo` no puede estar vacia. Solo en esa columna se permite
`n/a: <motivo>`, con un motivo no vacio; `n/a` sin motivo es invalido. Ninguna
celda puede contener el caracter `|`; si una clausula lo necesita, reformulala.
