# OpenCode Permission Preflight (capa 2 de la piramide)

> **Procedencia:** pasada de optimizacion 2026-10-23, HEAD base `02aba94a803a`. Seccion
> origen (verbatim abajo):
> - `## Secretos y seguridad` -- bullets "OpenCode Permission Preflight" y portabilidad de
>   `.opencode/opencode.json` de `AGENTS.md`
>
> Extractores por encabezado: leer este modulo; la cuspide solo conserva la directiva. El
> header `## Secretos y seguridad` de `AGENTS.md` esta registrado en
> `scripts/measure_agents_md_units.py::AGENTS_SECTIONS_REGISTRY` (cross-check de header, no de
> cuerpo) -- este modulo NO cambia ese header, solo su cuerpo.

**Ownership:** este modulo conserva VERBATIM el contenido origen. La cuspide conserva
encabezado, directiva y puntero. Este modulo es `referencia-bajo-demanda`: solo relevante
cuando el backend activo es OpenCode y el ticket toca rutas fuera de
`.agent/collaboration/`/`scripts/`. En divergencia de CONTENIDO manda este modulo; toda
modificacion de uno exige revisar el otro en el mismo commit.

## OpenCode Permission Preflight

Si el ticket requiere modificar archivos fuera de `.agent/collaboration/` o `scripts/` del
`repo_destino` (por ejemplo `PROJECT.md`, `AGENTS.md` o `CHANGELOG.md`), el plan o el arranque
debe verificar antes que esas rutas esten permitidas en `.opencode/opencode.json` bajo
`external_directory`. Si no lo estan, el Builder debe bloquear el arranque con diagnostico
claro en vez de continuar ciego. En OpenCode, esa allowlist puede necesitar el root completo
del `repo_destino` (`repo_destino\*`) y no solo permisos por archivo, porque el backend puede
resolver la lectura como acceso al arbol externo completo.

La configuracion versionada de `.opencode/opencode.json` debe permanecer portable y sin rutas
absolutas del `repo_destino` actual. Los permisos `external_directory` especificos del
proyecto se inyectan en runtime desde el launcher y se restauran al terminar; no deben quedar
commiteados en el motor.
