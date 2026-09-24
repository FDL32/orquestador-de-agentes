# Edit Shape — como agrupar y validar el batch de limpieza

Adaptado de `openclaw/openclaw`. Se aplica SOLO tras el batch de candidatos
haber pasado por `candidate-evidence.md` completo y haber sido aprobado por el
Manager/usuario (esta skill es read-only por defecto en descubrimiento).

## Agrupacion

- **Un batch coherente por owner boundary.** No mezcles limpieza de
  `tests/unit/` con limpieza de `tests/integration/` en el mismo commit/PR —
  son lanes distintos (ver `SKILL.md` seccion "Dos modos").
- Elimina exports/globals/wrappers test-only que el batch deja huerfanos en la
  MISMA pasada, en vez de conservarlos como alias "por si acaso". Si un test
  eliminado deja produccion muerta que `code-audit` clasificaria DEAD, borrala
  aqui tambien y repórtala en el numstat de produccion.
- Mueve las regresiones RETENIDAS a su owner canonico si el candidato
  identifico que vivian en el boundary equivocado (ver `gate-checklist.md`,
  pregunta 3).
- Consolida aserciones de paquete/dependencia repetidas en un unico contrato
  generico cuando el batch las toca.

## Lo que NO hacer

- No anadir tests de reemplazo que repitan la misma implementacion solo para
  compensar el conteo de eliminados.
- No convertir un candidato con `NECESITA MAS INVESTIGACION` en limpieza para
  subir el numero de eliminaciones del batch.
- Preferir LOC de produccion NETO-NEGATIVO: si el batch no reduce produccion
  cuando deberia (por seams huerfanos que quedaron vivos), no esta completo.

## Validacion (adaptada a las herramientas de este repo)

1. **Nunca editar tests mientras `run_pytest_safe.py` tiene un lock activo en
   el mismo checkout.** Verificar con `python scripts/run_pytest_safe.py --status`
   antes de tocar ficheros.
2. Ejecutar primero el owner y los tests hermanos mas pequeños que cubran el
   cambio:
   `python scripts/run_pytest_safe.py --level unit -- <path-o-filtro>`
   (si el owner o los hermanos tienen marker `integration`/`eval`/`slow` de
   `pytest.ini`, usa `--level all` en su lugar — `--level unit` los
   deselecciona en silencio, ver Paso 6 de `SKILL.md`)
3. Para greps de fuente o aserciones de plan/contrato eliminadas, correr el
   script/dry-run real que posee ese contrato (no re-simular con un mock).
4. Formatear y verificar line endings antes de commitear (ver AGENTS.md,
   "No MEZCLES vias de escritura en el mismo fichero" — usar `Write`/`Edit`
   consistentemente, no heredoc/`cat >>` sobre un fichero creado con Write).
5. Ejecutar `ruff check .` sobre los ficheros tocados.
6. Tras el batch de auditoria, ejecutar la suite canonica COMPLETA UNA sola
   vez, al final, no entre cada eliminacion (mismo principio que AGENTS.md
   "Orden de trabajo: AGRUPA los commits, la suite va la ULTIMA"):
   `python scripts/run_pytest_safe.py --level all`
7. Si el batch toco `.agent/collaboration/` (raro, pero posible si se
   documenta la decision ahi):
   `python .agent/agent_controller.py --validate --json` debe dar `0 errors / 0 warnings`.
8. Inspeccionar `git diff --stat` / `--numstat` y reportar produccion vs.
   tests/test-support POR SEPARADO en el handoff.

## Commit y alcance

- No commitear sin autorizacion explicita del usuario/Manager para ESE batch
  especifico (mismo principio de "Executing actions with care": una
  aprobacion no cubre batches futuros).
- Un batch = un commit coherente (o una serie pequeña si el owner boundary lo
  exige), nunca "elimino todo lo sospechoso de la sesion en un solo commit
  gigante" — dificulta bisect y revision.
