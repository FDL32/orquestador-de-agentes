# Detalle de "Comandos principales" -- runner de tests (capa 2 de la piramide)

> **Procedencia:** pasada de optimizacion 2026-10-23, HEAD base `02aba94a803a`. Seccion
> origen (verbatim abajo):
> - `## Comandos principales` -- bullet "Tests" de `AGENTS.md`
>
> Extractores por encabezado: leer este modulo; la cuspide solo conserva la directiva.

**Ownership:** este modulo conserva VERBATIM el bullet origen de `AGENTS.md` listado en su
cabecera de procedencia. La cuspide conserva encabezado, directiva (prohibicion) y puntero.
Este modulo es `referencia-bajo-demanda`: se consulta al depurar una coleccion de pytest fallida,
no en cada sesion. En divergencia de CONTENIDO manda este modulo; toda modificacion de uno
exige revisar el otro en el mismo commit.

## Por que NO usar `python -m pytest` directo sobre tests que importan el controller

Al insertar `.agent/` en `sys.path`, `runtime` puede resolver a `.agent/runtime/` (que tiene
`__init__.py`) en vez de `<motor>/runtime/`, y la coleccion falla con
`No module named 'runtime.project_root'`.

`scripts/run_pytest_safe.py` configura el entorno correcto y ademas incluye la barrera de
state-leak (falla si la suite muta `.agent/collaboration/`). Usar siempre ese runner en vez de
invocar `pytest`/`python -m pytest` directo sobre tests que importan el controller.
