# ticket_contracts.md -- python_service_minimal

> Solo contratos frozen pasan a work_plan.md.
  CONTRACT_GAP es la unica via para invalidar.

---

## T-HEALTH-001 -- Implementar endpoint de salud del servicio

- **ticket:** T-HEALTH-001
- **status:** frozen
- **Objective-Link:** OBJ-001 (Endpoint de salud operativo)
- **Plan-Link:** PLAN-001
- **Premise:** el repositorio tiene pyproject.toml o se crea;
  FastAPI y uvicorn son instalables sin conflicto;
  el entorno tiene Python 3.10+.
- **Premise Re-check (read-only):** antes de activar, verificar:
  - python --version >= 3.10
  - uv add fastapi uvicorn --dry-run no genera conflicto
  - No existe ya un service.py que requiera merge
- **Files Likely Touched:**
  - Builder: service.py (nuevo)
  - Builder: pyproject.toml (anadir fastapi, uvicorn)
  - Read only: README.md (si existe)
- **Forbidden Surfaces:**
  - Archivos BD (*.db, migrations, ORM models)
  - auth.py o modulos de autenticacion
  - Endpoints adicionales distintos al endpoint de salud
  - .env con credenciales reales
- **DoD:**
  - service.py con GET de salud devuelve Json status ok con codigo 200.
  - ruff check service.py exit 0.
  - Test humo documentado: curl localhost:8000 devuelve 200 y JSON.
  - No se han tocado Forbidden Surfaces.
- **STOP conditions:**
  - Si el entorno no tiene Python 3.10+: CONTRACT_GAP, no improvisar.
  - Si pyproject.toml tiene conflicto irreconciliable: CONTRACT_GAP.
  - Si se detecta necesidad de auth o BD: charter incorrecto; COTRACT_GAP.
- **CONTRACT_GAP behavior:** el Builder escribe
  contract_gaps/CG-T-HEALTH-001.md, bloquea el ticket
  y lo devuelve a Contract Formation.
- **Builder clarification rate esperado:** 0 (el contrato debe ser autocontenido).
- **Integration cross-ticket:** ninguna en v1 (unico ticket).
- **Mapeo a work_plan.md:**
  ```
  ## Metadata
  - ID: T-HEALTH-001
  - Estado: READY_TO_START
  - deliverable_type: code
  - delivery_authority: repo_destino
  ## Objetivo: [copiar de DoD]
  ## Files Likely Touched: [copiar de contrato]
  ## Criterios Binarios: [copiar de DoD]
  ## STOP conditions: [copiar de contrato]
  ```
  Ningun campo se inventa: todo proviene del contrato frozen.

---

## Fila de backlog generada

| Prioridad | Ticket | Titulo | Estado | Depende de |
|-----------|--------|--------|--------|------------|
| Alta | T-HEALTH-001 | Endpoint de salud | READYT_TO_START | - |
