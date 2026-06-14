# decisions.md -- python_service_minimal

### DEC-001 -- Framework HTTP

- **tier:** T1b
- **status:** accepted
- **decided_by:** user
- **options:** [A] FastAPI + uvicorn | [B] stdlib http.server
- **recommendation:** [A] FastAPI porque EVID-001 muestra implementacion minima y es el estandar actual.
- **evidence:** EVID-001 (alta fiabilidad)
- **impact:** si [B], sin dependencia externa pero mas verbose.
- **reversibility:** alta (cambio de framework es reemplazo de service.py).
- **invalidates:** -
- **supersedes:** -
- **date:** 2026-06-15

---

### DEC-002 -- Scope v1: solo endpoint health, sin persistencia

- **tier:** T1a
- **status:** accepted
- **decided_by::** user
- **options:** [A] Un endpoint health, sin BD, sin auth (recomendado) | [B] health + metrics + BD
- **recommendation:** [A] porque EVID-002 define smoke-test minimo.
- **evidence:** EVID-002 (user_doc, alta fiabilidad)
- **impact:** [B] rompe Non-Goal de no persistencia.
- **reversibility:** bajo (anadir BD en v2 es additive; quitarla seria destructiva).
- **invalidates:** cualquier ticket que asuma BD en el mismo plan.
- **supersedes:** -
- **date:** 2026-06-15
