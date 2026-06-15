# plan_graph.md -- python_service_minimal

## PLAN-001 -- Implementar servicio health-check

- **Objetivo:** crear service.py con GET health endpoint que devuelva {"status": "ok"} cod 200.
- **Tickets:** T-HEALTH-001
- **Dependencias de plan:** ninguna (PLAN-001 es el unico plan).
- **Superficies de archivo:** service.py (nuevo), pyproject.toml.
- **Interfaces externas:** ninguna en v1.
- **shared_dependencies:** pyproject.toml (si existe proyecto mayor).

---

## Impact Simulation

| Plan | Superficies | Shared deps | Conflicto esperado | Mitigacion | Paralelizable |
|------|-------------|------------|--------------------|-------------|---------------|
| PLAN-001 | service.py, pyproject.toml | pyproject.toml (si proyecto mayor) | Otro plan que toque pyproject.toml al mismo tiempo | Serializar | no |

Colision detectada: si existiera PLAN-002 tocando pyproject.toml,
habria conflicto de lock. Decision: serializar.

---

## Merge Regression Audit

No aplica con un unico plan. Si se anadiera PLAN-002 sobre pyproject.toml,
antes de integrar ambos: revalidar que el lock resuelve sin conflicto y
correr la suite sobre la union, no por plan. Si falla, re-clasificar a
requires_serialization y abrir CONTRACT_GAP.

---

## Forbidden Surfaces (para tickets derivados de PLAN-001)

Todo ticket de PLAN-001 tiene prohibido tocar:

- Archivos de BD (*.db, migrations/, models.py con ORM).
- auth.py o modulos de autenticacion.
- Endpoints distintos del endpoint de health.
- .env con credenciales reales.
- Tests que levanten una BD real.
