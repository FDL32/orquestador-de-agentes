# Contrato de MANIFEST.distribute y MANIFEST.workspace (capa 2 de la piramide)

> **Procedencia:** piramide pasada 2 + lote R1, HEAD base
> `8e956837`, 2026-10-19. Secciones origen (verbatim abajo):
> - `## MANIFEST.distribute y MANIFEST.workspace (WP-2026-111)` -- `AGENTS.md:214-230`
>
> Extractores por encabezado: leer este modulo; la cuspide solo conserva la directiva.

**Ownership:** este modulo conserva VERBATIM las secciones origen de `AGENTS.md` listadas en
su cabecera de procedencia. La cuspide conserva encabezado, directiva (prohibiciones,
obligaciones, comando canonico) y puntero. Este modulo es `referencia-bajo-demanda`: se
consulta al trabajar en el mecanismo, no en cada sesion. En divergencia de CONTENIDO manda
este modulo; toda modificacion de uno exige revisar el otro en el mismo commit.

## MANIFEST.distribute y MANIFEST.workspace (WP-2026-111)

Los archivos `MANIFEST.distribute` y `MANIFEST.workspace` en la raiz del repositorio definen el contrato estricto del motor central y el workspace destino:

- **MANIFEST.distribute**: Define la frontera del motor central (codigo operativo del repo fuente). El motor NO se copia; este manifiesto delimita que rutas forman parte del codigo operativo.
- **MANIFEST.workspace**: Define que se conserva EN el workspace destino (estado, memoria, eventos, configuracion del proyecto).
- **Arquitectura**: El motor vive una unica vez en `orquestador_de_agentes/`; cada proyecto destino conserva solo su `.agent/` de workspace y referencia el motor externo.

**Superficies vivas en `.agent/collaboration/`** (NO archivar, el codigo las escribe):
- `work_plan.md`, `TURN.md`, `STATE.md`, `execution_log.md`, `notifications.md`, `review_queue.md`

**Excluidos del workspace** (historial, runtime transitorio, caches):
- `PLAN_WP-*.md`, `AUDIT_WP-*.md`, `_archive/`, `archive/`
- `.agent/runtime/tmp/`, `uv-cache/`, `test_logs/`, `__pycache__/`, `reviews/`, `compare/`
- `.ruff_cache/`, `.cache/`, `.uv-cache/`, `.venv/`
- Logs y diagnosticos: `debug.log`, `opencode_models_error.log`
