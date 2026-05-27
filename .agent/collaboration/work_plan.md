# Work Plan - WP-2026-154

## Metadata
- **ID:** WP-2026-154
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** Strictness profiles and live guard_paths activation
- **Asignado a:** Builder

## Objetivo
Convertir `guard_paths.py` de stub en un hook funcional y anadir perfiles de strictness en `agents.json` con migracion compatible, sin romper la configuracion existente.

## Decision Arquitectonica
- `guard_paths.py` debe ejecutar la logica real en `__main__` en lugar de devolver siempre `{"continue": True}`.
- El contrato del hook es `exit(0)` para allow y `exit(2)` para block; la razon de bloqueo va a `stderr`, no a `stdout`.
- `guard_paths.py` lee `agents.json` directamente con `json.loads` desde `Path(__file__).resolve().parent.parent / "config" / "agents.json"`; no debe importar `agents_config.py` para resolver el perfil.
- `agents.json` incorpora `strictness_profile` como selector canonico y un mapa `profiles` con `minimal`, `standard` y `strict`.
- `standard` conserva la proteccion actual; `minimal` reduce el conjunto activo a la superficie sensible minima; `strict` endurece el guard sin bloquear superficies canonicas vivas como `execution_log.md`. El scope gate de `strict` lee `Files Likely Touched` del `work_plan.md` activo; si no hay plan activo (estado COMPLETED o archivo ausente), fail-open aplicando solo los patrones base de `standard`.
- La migracion 1.1 -> 1.2 backfillea `strictness_profile = standard` para configs antiguas.
- `agents_config.py` valida el nuevo schema y expone helpers estables para lectura del perfil.
- `agents.json` sigue siendo la autoridad de configuracion.
- Origen externo: affaan-m/ECC repo-compare 2026-05-27.
- Inspired by: ECC hook profiles and confidence-scored curation.
- `agents_config.py` debe seguir funcionando en pytest. La correccion prescrita para este ticket es un `tests/conftest.py` que asegura que el project root se resuelva antes que `.agent/` en el path de import, sin tocar la logica de produccion.

## Trade-offs Considered
| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| Binary hook stub | No schema work | Dead code stays dead | Rejected |
| Hardcode strictness in hook | Fast | Drifts from config and is harder to tune | Rejected |
| Config-driven strictness profiles | Portable, testable, backwards compatible | Small migration needed | Chosen |

## Files Likely Touched
- `.agent/hooks/guard_paths.py`
- `.agent/agents_config.py`
- `.agent/config/agents.json`
- `tests/conftest.py` (patch si existe, crear si no existe)
- `tests/test_guard_paths.py`
- `tests/unit/test_agents_config.py`

## Fases
0. Verify `pytest --collect-only` on the target tests does not raise `ImportError`; fix the path precedence in `tests/conftest.py` if it does.
1. Add `strictness_profile` plus `profiles` to `agents.json` and migrate schema 1.1 -> 1.2 with a standard default.
2. Validate the new config shape in `agents_config.py` and expose profile access helpers for runtime use.
3. Wire `guard_paths.py` to load the selected profile, emit stderr reasons, and return the real hook exit codes instead of unconditional continue.
4. Add focused tests for the three profiles, migration backfill, hook output behavior, and the strict-mode contract.

## Calidad
- `python scripts/run_pytest_safe.py --collect-only tests/test_guard_paths.py tests/unit/test_agents_config.py`
- `python scripts/run_pytest_safe.py tests/test_guard_paths.py tests/unit/test_agents_config.py -q`
- `ruff check .agent/hooks/guard_paths.py .agent/agents_config.py tests/test_guard_paths.py tests/unit/test_agents_config.py`
- `python .agent/agent_controller.py --validate --json --force`

## Criterios de aceptacion
- `guard_paths.py` no devuelve `{"continue": True}` incondicionalmente en `__main__`.
- `guard_paths.py` usa `exit(0)` / `exit(2)` y escribe la razon de bloqueo en `stderr`.
- `guard_paths.py` lee `agents.json` directamente y no depende de `agents_config.py` para seleccionar el perfil.
- `agents.json` version 1.2 soporta `strictness_profile` y migra configs legacy a `standard`.
- `minimal`, `standard` y `strict` tienen comportamiento distinto y testeado.
- `pytest --collect-only` sobre `tests/test_guard_paths.py` y `tests/unit/test_agents_config.py` sale limpio antes de ejecutar los tests.
- `execution_log.md` y otras superficies canonicas vivas no quedan bloqueadas por defecto en modo strict.
- Los tests y la validacion canonica pasan sin regresiones.
