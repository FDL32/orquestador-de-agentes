# Caso: adjudicación por posición vs. contenido literal (X-09, un nivel arriba)

> Trasladado desde `AGENTS.md` (seccion "Gobierno prompt-hijo<->prompt-nucleo: extension de
> X-09 un nivel arriba", 2026-10-08) via `prompts/doc_optimization.md`, 2026-10-14. `AGENTS.md`
> conserva un puntero de una linea a este fichero; el texto aqui es el original, sin resumir.

**Advertencia del propio caso (correccion posterior, MANAGER_REVIEW con lente nan/deepseek-v4-flash,
2026-10-08):** el bucle de gobierno que motivo esta norma tambien ADJUDICO, por error, que las
reglas de validez 1/2/4/6 de ese mismo prompt-hijo redeclaraban el nucleo -- y ESO era FALSO: esas
4 reglas no tienen correspondencia de CONTENIDO en el nucleo, solo coincidian en NUMERO DE
POSICION dentro de una lista. Las 5 lentes razonaron la premisa por semejanza estructural sin
comparar el texto real (mismo patron que `obs-premise-cited-from-code-not-reasoned`, memoria,
2026-07-15). La leccion para aplicar ESTA norma: antes de declarar que una seccion del hijo
"coincide en objeto" con una seccion del nucleo, COMPARA EL CONTENIDO LITERAL de ambas, no la
posicion en la lista -- un match de numero/titulo no certifica un match de objeto.
