# Detalle de "Backends y roles" (capa 2 de la piramide)

> **Procedencia:** pasada de optimizacion 2026-10-23, HEAD base `02aba94a803a`. Seccion
> origen (verbatim abajo):
> - `## Backends y roles` -- bullet "Nota de enums de codigo" de `AGENTS.md`
>
> Extractores por encabezado: leer este modulo; la cuspide solo conserva la directiva.

**Ownership:** este modulo conserva VERBATIM el bullet origen de `AGENTS.md` listado en su
cabecera de procedencia. La cuspide conserva encabezado, directiva y puntero. Este modulo es
`referencia-bajo-demanda`: se consulta al trabajar en el mecanismo de resolucion de roles, no
en cada sesion. En divergencia de CONTENIDO manda este modulo; toda modificacion de uno exige
revisar el otro en el mismo commit.

## Nota de enums de codigo (por que NO hay un enum 1:1 con la lista de roles canonicos)

Existen 3 enums de codigo con nombres parecidos y dominios DISTINTOS por diseno
(DEC-router-skills-001 Seccion 7; no se fusionan):

- `.agent/agents_config.py::CANONICAL_ROLES` (valida `role_mapping`/backend resolution).
- `scripts/discover_skills.py::CANONICAL_ROLES` (valida el campo `role` escalar del frontmatter
  de prompts).
- `agents.json::ensemble_profiles` (perfiles `proposer`/`challenger`).

Ninguno de los 3 es, ni pretende ser, una copia literal de la lista de roles canonicos de
`AGENTS.md` -- cada uno valida su propio dominio. Armonizado 2026-10-12 tras bucle adversarial
de 3 lentes (codex, nan-fs, opencode/glm) sobre vocabulario de roles.

## Backends retirados

Goose/Claw retirados (WT-2026-254a); `scripts/orquestador.py` es hoy el lanzador de skills.
(Antes en `AGENTS.md` "Backends y roles"; la linea, que los daba por "motores orquestados por
`scripts/orquestador.py`", salio de la cuspide en `2857b691` sin destino -- se restituye aqui
con la redaccion correcta, WOT-2026-120a.)
