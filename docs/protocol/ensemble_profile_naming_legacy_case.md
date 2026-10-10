# Caso legacy de nomenclatura de perfiles ensemble: `challenger_opencode_glm_5_2`

> Referencia bajo demanda. La norma de forma (`<rol>_<backend>_<familia>[_<caracteristica>]`)
> vive en `AGENTS.md`, seccion "Nomenclatura de perfiles ensemble (`ensemble_profiles` en
> `agents.json`)". Este documento es el caso concreto de excepcion legacy que esa norma cita;
> trasladado aqui por `prompts/doc_optimization.md` (PASO 2, fila 5 "justificacion forense") al
> no ser comando operativo sino historia de un caso puntual.

**Excepcion legacy declarada, NO retroactiva:** `challenger_opencode_glm_5_2`
mantiene su nombre con version completa porque esta CITADO LITERAL en >5
tests como fixture de identidad (`test_058y_*`, la lista `con_arbol` de
`test_...475`, etc.); renombrarlo exige tocar esos tests en el mismo cambio,
no es un rename aislado. No renombrar este perfil sin revisar primero
`grep -rn "challenger_opencode_glm_5_2" tests/`.

**Estado desde 2026-10-02:** ese perfil esta marcado `status: legacy` con
`replaced_by: challenger_opencode_glm_flash` (mismo backend, modelo y `BA06`; el
nombre viejo mentia: su modelo es `glm-5.3-flash`, no 5.2). Marca BLANDA: sigue
invocable por nombre (avisa por stderr) pero queda fuera de toda seleccion
automatica (`selectable_profiles` en `scripts/ensemble_dispatch.py`). Una ruta
nueva que elija perfiles por si sola debe pasar por esa funcion, no por
`config["ensemble_profiles"]` a pelo.
