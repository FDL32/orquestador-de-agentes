# Palanca A: propuesta corregida tras lectura crítica de la Fase 0

## Alcance

Este documento propone el siguiente paso; no implementa Palanca C, anidados ni
ningún traslado de contenido de `AGENTS.md`.

## Hallazgos de la pasada fresca

1. La Fase 0 no demuestra todavía que la pirámide sea inviable. Su clasificación
   contradice PASO 2 de `prompts/doc_optimization.md`: trata como movibles
   comandos canónicos, prohibiciones duras y docstrings marcados como
   `SIEMPRE`.
2. La afirmación de que solo 1 de 5 grupos es movible no censa todos los
   consumidores. `scripts/build_llms.py` genera `llms-full.txt`, y la adaptación
   de Hermes ya aparece como consumidor previsto en el diseño original.
3. Los suelos de 4.348 B y 4.257 B no son reproducibles desde la tabla: mezcla
   estimaciones con bytes, padres con hijos y filas solapadas. La suma publicada
   tampoco coincide con la suma de las filas.
4. El censo de duplicación busca rutas, no contenido. Hay reglas CEM
   reproducidas en `.agent/rules/common/sustainable_engineering.md` y
   `flight_push_policy.md`; por tanto, el negativo de duplicación no está
   probado.
5. La aritmética publicada es condicional e incoherente: `61047 - 32507 +
   4348 = 32888`, que deja el resultado por encima del gate; con 4.257 B el
   resultado sería 28.631 B, pero ninguna cifra está fijada por un recibo
   reproducible.
6. La comprobación de comportamiento debe ser por regla trasladada y por
   backend, antes/después. Un umbral agregado de 4.000 B no cubre una regla
   crítica pequeña y dos fallos de Gemma no prueban causalidad.

## Propuesta

### Fase 0R: medición corregida, antes de elegir lever

Rehacer la Fase 0 con una tabla de unidades no solapadas. Para cada candidato
se conserva el texto exacto y se registra: ruta, encabezado, bytes UTF-8,
clasificación PASO 2, consumidor, condición de destino, y referencia al
recibo. Se cuentan por separado los gates Codex (bytes) y Claude (caracteres),
con la raíz absoluta y `HEAD` estampados.

La selección debe respetar la prioridad de PASO 2 y excluir cualquier bloque
que sea refutación, prohibición dura, comando canónico, contenido extraído por
encabezado o leído por un consumidor programático. El resultado terminal puede
ser `SIN CANDIDATO MOVIBLE`; no se fuerza un traslado para cerrar una cifra.

### Censo de consumidores y duplicación

Ejecutar el censo sin filtrar por extensión y verificar la salida real de cada
consumidor. Comparar contenido normalizado, no solo referencias de ruta, para
encontrar copias verbatim o casi verbatim. Los bloques compartidos se asignan
una sola vez al presupuesto: no se suman ahorros de candidatos solapados.

### Gate de comportamiento

Para cada candidato que sobreviva, ejecutar los consumidores antes y después
con el mismo bundle. La evidencia mínima es igualdad de salida, o una
justificación bloque a bloque. Una regresión en una sola regla invalida ese
candidato aunque el total de bytes mejore.

### Palanca C como piloto posterior, solo si Fase 0R aún lo exige

Si, y solo si, la medición corregida demuestra un déficit real, proponer un
piloto limitado sobre la regla de que un `exit 0` puede significar “no hice
nada”. El origen conservaría intactas la refutación, las obligaciones, las
excepciones y los contraejemplos; los casos históricos mantendrían sus IDs,
fechas y procedencia en `docs/followups/agents-md-over-quota-followup.md`, como
referencia alcanzable para una sesión de diseño; el cargador que debe resolver
la referencia en un piloto es `bus/memory_loader.py` mediante
`get_review_context(domain)` (no se presume que una mención textual sea
cargable). Hermes recibiría el bloque original con procedencia verificable.
Esto requiere una modificación explícita del contrato: el piloto tendría que
cambiar `prompts/doc_optimization.md`, PASO 3(c), que exige literalmente que
una refutación no sea “ni entera ni repartida”. La propuesta no autoriza ese
cambio: requiere una decisión humana explícita y un nuevo bucle
`DESIGN_REVIEW` antes de cualquier implementación.

Mientras Fase 0R no esté cerrada, la opción recomendada es deuda declarada con
owner humano y criterio de salida, no implementar ningún lever. El artefacto de
deuda abierto es `docs/followups/agents-md-over-quota-followup.md`; se considera
cerrado solo cuando ambos gates quedan <= 1.0x, o cuando el usuario decide
expresamente aceptar la deuda.

## Resultado esperado del bucle

El bucle `DESIGN_REVIEW` debe adjudicar si Fase 0R es condición previa, si el
piloto C respeta CEM y si la deuda queda correctamente acotada. Esta propuesta
no autoriza cambios en `AGENTS.md`.

## Inventario de evidencia

La evidencia primaria son los cuatro documentos fuente revisados, el código de
los consumidores censados y las mediciones reproducibles con raíz absoluta,
`HEAD` y salida before/after. Las cifras de la Fase 0 anterior se tratan como
hipótesis hasta repetirlas.

## Salida declarada

Cada lente debe devolver: veredicto, hallazgos priorizados, objeciones no
resueltas y cambios concretos a Fase 0R o al piloto. No debe editar el árbol ni
implementar un lever. Si una afirmación o comprobación no puede verificarse,
debe responder literalmente `NO VERIFICABLE` en vez de inferirla.
