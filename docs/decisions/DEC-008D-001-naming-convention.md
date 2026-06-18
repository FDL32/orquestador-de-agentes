# DEC-008D-001: Convencion de Naming para Prompts, Skills y Scripts

**Ticket:** WOT-2026-008d
**Fecha:** 2026-06-18
**Estado:** DECIDED
**Autor:** Builder (Claude Code, Opus 4.8)

## Contexto

El motor define artefactos operativos en tres superficies con convenciones
lexicas hasta ahora implicitas (nunca versionadas):

- `prompts/*.md` — plantillas de instruccion para agentes.
- `skills/<dir>/SKILL.md` — micro-habilidades con frontmatter `triggers:`.
- `scripts/*.py` — utilidades CLI.

El estado real (verificado en disco, 2026-06-18) ya es mayoritariamente
consistente: 20 prompts en `snake_case`, 29 skills en `kebab-case` con prefijos
de rol `bui-`/`man-`, y scripts CLI verbo-primero (`check_*`, `discover_*`,
`generate_*`, `validate_*`, `archive_*`, `run_*`). No existe contrato escrito
que lo fije, asi que un artefacto nuevo fuera de convencion entra sin friccion
y degrada el orden alfabetico y la agrupacion por actor.

Esta DEC fija la convencion **antes** de cualquier rename y define la autoridad
de validacion. Sin esta DEC no hay rename (contrato T-008D-001).

## Decision

### 1. Convencion lexica por tipo

| Tipo | Convencion | Ejemplo | Regla |
|------|-----------|---------|-------|
| prompt (`prompts/*.md`) | `snake_case` | `launch_builder.md` | `[a-z0-9]+(_[a-z0-9]+)*\.md` |
| skill (`skills/<dir>/`) | `kebab-case` | `bui-implement-from-plan` | `[a-z0-9]+(-[a-z0-9]+)*` |
| script CLI (`scripts/*.py`) | `snake_case`, **verbo primero** | `check_skill_collisions.py` | verbo inicial de un set cerrado |

Verbos iniciales permitidos para scripts CLI accionables:
`check_`, `validate_`, `generate_`, `discover_`, `archive_`, `run_`,
`collect_`, `classify_`, `install_`, `upgrade_`, `migrate_`, `memory_`.
Scripts que son librerias/modulos de apoyo (no CLI accionable directo) quedan
fuera del gate por ahora (no se fuerza verbo); el gate cubre la superficie
prompt+skill, que es la que crea/ensena nomenclatura nueva.

### 2. Prefijos de rol (actor primero)

Las skills y prompts ligados a un rol del pipeline anteponen el actor:

- `bui-` / `man-` para skills (forma corta, ya en uso).
- En prompts, el actor va **primero**: `launch_builder`, no `builder_launch`;
  la accion describe lo que el orquestador hace al actor.

**Regla canonica actor-primero:** cuando un artefacto nombra a un actor del
pipeline (`manager`, `builder`) Y una accion, el actor va primero
(`manager_review`, no `review_manager`). Esto agrupa alfabeticamente por actor
y hace el inventario predecible. Forma corta (`man-`/`bui-`) y forma larga
(`manager`/`builder`) son ambas validas; no se mezclan dentro de un mismo
artefacto.

### 3. Contrato de shim / frontmatter

El rename de un nombre publico NO se hace con `git mv` a secas: rompe
`source_prompt` (skills que apuntan al prompt) y referencias prose vivas.
El contrato de compatibilidad es:

- **Fuente de verdad de aliases:** frontmatter `legacy_aliases: [old_name, ...]`
  en el artefacto renombrado. Sin sidecar JSON, sin manifest central
  (coherente con DEC-008B-001 Opcion 4: discovery recursivo sin manifest).
- **`canonical_name`:** derivado del filename actual (basename sin extension).
  No se almacena redundante; es el nombre del archivo en disco.
- **`naming_status`:** derivado — `legacy` si el basename viola la convencion
  pero esta declarado como excepcion conocida; `canonical` en caso normal.
- **Shim para nombre publico antiguo:** cuando se renombra un prompt con
  consumidores `source_prompt` vivos, se conserva un stub-alias ejecutable en
  la ruta antigua que referencia el canonico, hasta su retirada en `008e`.
  Patron vivo de referencia: `prompts/audit_plan.md` (stub-alias de
  `audit_ticket_contract.md`).

### 4. Ortogonalidad con disable-model-invocation (010s)

La convencion lexica (este DEC) es **ortogonal** a la taxonomia
`disable-model-invocation` / `user-invoked` vs `model-invoked` (010s). El nombre
no codifica el modo de invocacion: una skill `user-invoked` y una `model-invoked`
siguen la misma regla kebab-case. `--check-naming` NO inspecciona
`disable_model_invocation`; `discover_skills.py --json` y el INDEX siguen siendo
la autoridad de esa metadata. Cero acoplamiento.

### 5. Autoridad de validacion: `discover_skills.py --check-naming`

Se decide **extender `discover_skills.py`** con un flag `--check-naming` (no
crear script nuevo, no tocar `check_skill_collisions.py`):

- `discover_skills.py` ya es el dueno del discovery recursivo y del frontmatter;
  la validacion de naming vive junto a `--check-contract` (mismo patron CLI,
  mismo `_get_bundle_root`).
- `check_skill_collisions.py` permanece **read-only para este ticket**: valida
  colisiones de triggers/nombres, una preocupacion distinta de la lexica. No se
  modifica porque la autoridad de naming es `discover_skills.py --check-naming`.
- `pre_handoff_guard.py` NO recibe logica de naming (Forbidden). El gate corre
  via `run_gates_dispatch.py`, no en la barrera de handoff.

`--check-naming` valida prompts y skills contra la convencion, trata los nombres
declarados como excepcion legacy (ver seccion 6) como conformes, y falla closed
(exit 1) ante un nombre nuevo fuera de convencion.

### 6. Piloto: validacion sin rename arriesgado

`review_manager.md` es el unico artefacto en convencion noun_verb que la regla
actor-primero pediria renombrar a `manager_review.md`. Tiene **6 consumidores
`source_prompt`/prose vivos** verificados:
`skills/{audit-pipeline,man-review-implementation,orchestrate-pipeline}/SKILL.md`
y `prompts/{audit_complete_motor_destination,audit_pipeline,orchestrator_pipeline}.md`.

Renombrarlo en este ticket excederia el "piloto minimo reversible" del contrato
(6 actualizaciones atomicas + shim). **Decision:** el piloto de 008d es
**validacion-only**:

- `--check-naming` se entrega y valida el arbol vivo (que ya conforma salvo el
  caso `review_manager`).
- `review_manager.md` se declara **excepcion legacy conocida** en
  `discover_skills.py` (lista `KNOWN_LEGACY_NAMES`), con su rename atomico
  asignado explicitamente a `008e`. Asi el gate queda verde sin un rename de
  6-referencias en un ticket marcado como piloto minimo.
- No se mueve ninguna carpeta, no se rompe `source_prompt`, `--check-contract`
  queda verde.

El rename real `review_manager -> manager_review` (con shim + 6 updates
atomicas + `legacy_aliases`) queda como primer trabajo de `008e`, ya con la
convencion y el gate congelados por esta DEC.

## Consecuencias

- **Positivas:** convencion versionada y ejecutable; barrera fail-closed contra
  nombres nuevos no conformes; cero riesgo de romper consumidores vivos; el
  rename arriesgado queda aislado en su propio ticket con la regla ya fija.
- **Negativas / deuda:** `review_manager.md` sigue en disco con nombre legacy
  hasta `008e`; la lista `KNOWN_LEGACY_NAMES` es deuda explicita con criterio de
  salida (vaciarla al cerrar `008e`).
- **Scripts no-CLI** quedan fuera del gate v0; ampliarlo es trabajo futuro si
  aparece deriva.

## Criterio de salida de la deuda legacy

`008e` debe: renombrar `review_manager.md -> manager_review.md`, anadir
`legacy_aliases: [review_manager]` al canonico, crear stub-alias en la ruta
antigua, actualizar los 6 consumidores, y vaciar `KNOWN_LEGACY_NAMES` en
`discover_skills.py`. Tras eso `--check-naming` debe quedar verde sin excepciones.
