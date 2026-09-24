# Value Bar y Retention Bar

Adaptado de `openclaw/openclaw`. Decision de usuario para este repo
(2026-09-24): **no hay jerarquia de dominio predefinida** entre categorias de
contrato (seguridad no vale automaticamente mas que schema/CLI, ni bus/estado
mas que gates). Cada candidato se juzga por su EVIDENCIA propia, caso a caso.

## Value bar (regla general)

Un test justifica su coste de mantenimiento si protege:

- un comportamiento observable,
- una regresion creible (ver `gate-checklist.md`, pregunta 2), o
- un contrato independientemente significativo (ver retention bar abajo).

En auditoria, un test EXISTENTE que necesitaria cambiar por una reorganizacion
de codigo que preserva comportamiento es SOSPECHOSO, no automaticamente
eliminable — investigar antes de decidir. El gate de escritura (para tests
NUEVOS) SI rechaza ese patron de inmediato.

## Antes de juzgar cualquier candidato

Leer COMPLETO (no muestrear, mismo principio M4 de AGENTS.md aplicado a
tests):

1. el test candidato entero;
2. su owner de produccion (la funcion/modulo/script que ejercita);
3. el entry point real (CLI, hook, gate) que invoca a ese owner en produccion;
4. callers y callees relevantes;
5. tests hermanos que pudieran solaparse;
6. el enrutamiento de CI/pre-commit/pre-push si el test es un guard;
7. historial relevante (`git log -p` del test y del owner) para entender por
   que se anadio;
8. `AGENTS.md`/`CLAUDE.md` raiz y de scope, por si documentan el contrato.

Si el candidato afirma proteger un comportamiento respaldado por una
dependencia externa, inspeccionar el codigo o los tipos de esa dependencia
directamente — no asumir su contrato de memoria.

## Retention bar — que SI se conserva

Conservar un test cuando aplica **independientemente** a:

- un contrato de API publica, SDK de plugin/skill, protocolo, config,
  migracion, storage, seguridad, plataforma, default, byte de prompt,
  cross-language generado, paquete, release, o arquitectura;
- **call ordering** cuando el orden es comportamiento observable (ej. el
  orden Manager->Builder->suite descrito en `orchestrator_launch_builder.md`);
- **regresiones con un modo de fallo creible** (ver `gate-checklist.md`);
- **inspeccion de fuente** cuando es la guarda independiente MAS BARATA: falla
  cuando el contrato cambia (la clave/byte/ruta visible al usuario) y
  sobrevive a un refactor de solo-identificadores. Distinto del junk pattern 4
  (grep exacto de import/string) en que aqui el grep SI apunta a algo que un
  usuario/consumidor externo observaria si cambiase.
- un test retenido que **falla en la baseline actual**: tratarlo como posible
  bug de producto, reproducirlo y reparar el owner en vez de borrar el test.

**Static o slow NO es razon de eliminacion por si sola.** Un test que se
parece a "prueba de implementacion" puede seguir siendo el contrato
independiente correcto — hay que refutarlo con evidencia (mutation-verify,
Paso 6 de `SKILL.md`) antes de retirarlo.

## Aplicacion sin jerarquia de dominio (este repo)

No asumas que un test de `tests/evals/` (seguridad) vale mas por defecto que
uno de `tests/test_check_naming.py` (convencion de nombres, vive en la raiz
de `tests/`, no en `tests/unit/` — verificado con `find`). En este
repo concreto, ejemplos de retencion fuerte medidos en `top_slowest`
(`run_history.jsonl`, corrida `2026-09-24T20:27:27`):

- `test_eval_guard_paths.py::test_in_process_blocks_privada_path` — protege el
  guard de seguridad que bloquea escritura en `privada/`; retencion alta por
  el propio dominio de seguridad, PERO la razon real es que es la UNICA prueba
  in-process de ese bloqueo (pregunta 3 del gate), no porque "seguridad
  siempre gana".
- `test_observation_domains.py::test_ninguna_copia_del_enum_en_el_arbol` — es
  una inspeccion de fuente (grep de un enum), pero cae en la excepcion de
  retencion: el enum es un contrato que un consumidor externo (otro script)
  observa, y el test sobrevive a un refactor de identificadores porque busca
  el VALOR del enum, no su nombre de variable. Verificar esto caso a caso
  antes de asumirlo.
- `test_check_naming.py::test_no_live_ref_to_legacy_man_skill_dirs` — parece
  "solo naming", pero protege el contrato de nomenclatura de tickets descrito
  en AGENTS.md (WOT vs legacy WP/WT); es un contrato real de convencion
  documentada, no cosmetico.

Ninguno de los tres se retiene "porque es lento" ni "porque es de seguridad":
se retienen porque, tras leer el owner completo, responden que si a las 4
preguntas del gate. Aplica el mismo estandar de lectura a cualquier otro
candidato, sin dar por buena la retencion solo por la carpeta en la que vive.
