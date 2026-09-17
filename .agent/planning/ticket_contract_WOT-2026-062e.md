# ticket_contracts.md -- WOT-2026-062e

## T-062E-001 -- Telemetría de entorno de corrida

- **ticket_id:** WOT-2026-062e
- **status:** frozen
- **deliverable_type:** code
- **delivery_authority:** repo_motor
- **Objective-Link:** OBJ-062E-001
- **Plan-Link:** PLAN-062E-001
- **Premise:** `scripts/run_pytest_safe.py` no registra el estado del entorno al iniciar la suite (RAM, procesos, CPU, latencia de spawn). Sin datos de contexto, es imposible correlacionar lentitud de suite con presión de recursos.
- **Premise Re-check (read-only):**
  - verificar que `scripts/run_pytest_safe.py` no tiene `_collect_environment()` ni `environment_at_start` en `last-run.json`;
  - verificar que `write_json()` no acepta `fsync`;
  - verificar que `acquire_lock()` no hace dead-run reconciliation;
  - verificar que no hay `STATE_CHANGED` en el bus para el evento de corrida.
- **Context Baseline Evidence:** motor_head=3e3387d; destino_state=WOT-2026-022c COMPLETED; validate_result=por verificar; generated_at=2026-09-17.
- **Files Likely Touched:**
  - Builder: `scripts/run_pytest_safe.py` (Piezas A, B, C)
  - Builder: `tests/unit/test_run_pytest_safe.py` (tests para A, B, C)
  - Read/inspect only: `scripts/pre_handoff_guard.py`, `scripts/run_gates_dispatch.py`, `.agent/runtime/pytest-safe/`
- **Forbidden Surfaces:** bus runtime/events (solo añadir STATE_CHANGED); `privada/`; `.env`; ticket_contracts.md fuera de `.agent/planning/`.
- **DoD (criterios binarios de cierre):**
  - [ ] `_collect_environment()` retorna dict con `ram_free_mb`, `ram_used_pct`, `process_count`, `spawn_ms_mean`, `probe_cost_s`, `probe_errors` — todo stdlib-only.
  - [ ] `write_json()` acepta `fsync=True` y llama `os.fsync(fd)` tras escribir.
  - [ ] `_reconcile_dead_run()` detecta `status: started` + PID muerto, marca como `aborted` y append a `run_history.jsonl`.
  - [ ] `_emit_env_preflight()` emite WARNING si `ram_free_mb < 2048`.
  - [ ] Tests: mutation-verify para cada pieza (sin_fix -> rojo, con_fix -> verde).
  - [ ] `test_write_json_with_fsync` verifica vía mock que `os.fsync` se llama cuando `fsync=True` y NO se llama cuando `fsync=False`.
  - [ ] `ruff check . && ruff format .` pasa.
  - [ ] Suite `run_pytest_safe --level all` -> "N passed / 0 failed"; tested_sha==HEAD.
  - [ ] `validate --json --project-root <workspace_activo>` termina en 0 errors / 0 warnings.
- **Integracion cross-ticket:** `062e` es infraestructura de observabilidad; no desbloquea ni es bloqueado por tickets de funcionalidad.
- **CONTRACT_GAP behavior:** si los probes no pueden ser stdlib-only, si `fsync` no es soportado en Windows, si la dead-run reconciliation rompe el lock existente, o si `validate` no puede pasar, emitir `CG-WOT-2026-062e.md` y bloquear.
- **Builder clarification budget:** 0. Las decisiones de thresholds (RAM < 2048 MB, 20 spawns) son del contrato, no del Builder.
- **STOP conditions:** parar si los probes exigen dependencias externas; parar si `fsync` no es portable; parar si la reconciliation rompe el lock de `acquire_lock`; parar si `validate` deja warnings nuevos.
- **Depende de:** WOT-2026-022c (COMPLETED).
