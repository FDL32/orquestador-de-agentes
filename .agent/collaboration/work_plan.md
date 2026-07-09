# Plan de Trabajo: retirada del motor Goose/Claw del Refactor-Kit (Opcion A)

## Metadata
- **ID:** WOT-2026-021d
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-10
- **delivery_authority:** repo_motor
- **Prioridad:** MEDIA
- **Asignado a:** Builder

## Objetivo
Retirar el motor de agentes externos Goose/Claw del Refactor-Kit segun la
decision fijada **DEC-021D-001 (accepted, Opcion A)**. El modulo NO es codigo
muerto (9 tests verdes, `__init__` lo exporta, detect_version usa el dir como
marcador) -> se conserva el modulo y sus fases; solo se retira la rama de
invocacion Goose/Claw, dejando el modo MANUAL (stdin, ya existente) como unico
backend. Se corrige de paso el bug de tipo de `_wait_for_approval` y se limpia
el mojibake preexistente del archivo (scope anadido intencional, N5).

## Contexto
`agent_system/refactor_kit/refactor_manager.py` tiene `agent="goose"` por defecto
y ramas goose/claw en `_call_agent`; el modo manual (stdin, l.143-150) ya existe
como fallback. La Opcion A promueve el modo manual a default y retira las ramas
externas. `_wait_for_approval` declara `-> bool` pero devuelve un dict en la rama
`goose_context` (bug de tipo); esa rama existe SOLO para Goose, asi que retirarla
corrige el bug y hace que la funcion devuelva `bool` de verdad.

DEC-021D-001 fija el DoD y excluye explicitamente que WOT-2026-021l toque
`agent_system/refactor_kit/` (frontera limpia entre tickets).

## Configuracion Privada Requerida
Ninguna.

## Alcance EXACTO (verificado in-vivo 2026-07-10, surface == DEC)

### CAMBIAR
- `refactor_manager.py:23` `agent: str = "goose"` -> `agent: str = "manual"`.
- `refactor_manager.py:114-137` (`_call_agent`): retirar las ramas
  `if self.agent == "goose"` / `elif self.agent == "claw"` (subprocess a los
  binarios externos). Conservar el modo MANUAL stdin (l.143-150) como unica ruta.
  El metodo `_call_agent` SE CONSERVA (test_refactor_manager_importable asserta
  `hasattr`).
- `refactor_manager.py:25,30,152-173` (`_wait_for_approval` + `goose_context`):
  retirar el parametro `goose_context` del `__init__` y la rama
  `if self.goose_context: return {dict}`. Dejar solo la ruta stdin que devuelve
  `bool` -> corrige la firma `-> bool`. El metodo SE CONSERVA (hasattr).
- `refactor_manager.py:319` CLI `--agent`: `default="goose"` -> `default="manual"`;
  retirar `choices=["goose","claw"]` (o dejar sin choices).
- `install_refactor_kit.py:39` `"default_agent": "goose"` -> `"manual"`.
- `README.md:21` ejemplo `--agent goose` -> `--agent manual`.
- Mojibake: dejar `refactor_manager.py` ASCII limpio (docstrings/prints con
  UTF-8 doble-codificado, p.ej. acentos corruptos -> texto correcto o ASCII).
  SCOPE ANADIDO INTENCIONAL (N5): deuda de encoding ajena al ticket Goose, pero
  Opcion A ya edita el archivo. (Nota: no se reproducen los bytes corruptos aqui
  para no romper el encoding-guard sobre work_plan.md, que es tracked.)

### CONSERVAR (no tocar)
- Todas las fases (`phase_1..5`), caching, timing, `_get_target_hash`,
  `_should_skip_phase`, `_load_templates`, `run`.
- Nombres de metodo `_call_agent` y `_wait_for_approval` (hasattr test).
- Estructura de directorios del kit (marcador de version).

## Definition of Done (DoD, de DEC-021D-001)
- (a) `git grep "goose\|claw" -- agent_system/refactor_kit/` = 0.
- (b) Nuevo default `manual` funciona: construir `RefactorManager(target=...)` sin
  `agent` usa modo manual; `_wait_for_approval` devuelve `bool`.
- (c) Los 9 tests de refactor_kit (test_refactor_kit_portable.py +
  test_refactor_kit_performance.py) siguen VERDES.
- (d) Bug de tipo de `_wait_for_approval` corregido (firma `-> bool` honrada).
- (e) `refactor_manager.py` ASCII limpio.
- (f) Suite `run_pytest_safe.py --level all` exit 0 (incl. lifecycle/detect_version/
  doctor/migrate/upgrade que referencian el kit como marcador).

## Riesgos y barreras
- `test_refactor_manager_importable` exige `_call_agent`+`_wait_for_approval` por
  nombre -> NO borrar los metodos, solo su interior externo. Barrera: DoD-c.
- `goose_context` no se usa fuera del archivo (git grep verificado) -> retirarlo
  no rompe callers. Barrera: DoD-c + suite.
- El default `manual` no lo ejercen los tests de perf (no pasan `agent`) -> el
  cambio de default es transparente para ellos.
