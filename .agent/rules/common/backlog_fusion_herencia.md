# Regla de herencia al absorber fichas de backlog (WOT-2026-042l)

## La regla

Al absorber una ficha en otra (fusion), la ficha resultante:

- toma la **prioridad MAXIMA** del conjunto: una fusion que baja prioridad es
  degradacion silenciosa (el caso que la destapo: absorber una Media con una
  Baja habria escondido el unico criterio de salida operativo del cluster);
- conserva la **UNION de los criterios de salida**: el texto del Reactivation
  no vacio de cada absorbida debe quedar representado en la fila resultante
  (el campo nativo nunca se degrada a prosa del cuerpo).

## Declaracion canonica

La absorcion se declara en la fila resultante con el marcador
`[ABSORBE: <id>]` (varios ids separados por coma). Fusiones historicas no se
reescriben.

## El gate (check_backlog_contract.py, wired en main)

`validate_absorption_inheritance` audita cada fila viva de 8 columnas que
declara el marcador:

- `ABSORPTION_PRIORITY_DEGRADES`: la absorbida (en `_archive/backlog_done.md`)
  tenia prioridad mayor que la resultante.
- `ABSORPTION_REACTIVATION_LOST`: el Reactivation no vacio de la absorbida no
  aparece representado (por containment normalizado) en el texto de la fila
  absorbente.
- `ABSORPTION_LOST_TRACE`: la absorbida no esta ni en la cola viva ni en el
  archive (desaparecio sin fila terminal).

Alcance declarado: solo filas Prioridad-led de 8 columnas; una absorbida aun
viva se salta (la fusion no se ha ejecutado); una fusion legitima que
consolida a prioridad mayor sigue pasando (NON-GOAL: no bloquear
consolidaciones).
