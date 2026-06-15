# repo_charter.md -- python_service_minimal

> Arquetipo de validacion para WOT-2026-007b.

## Product Intent

Exponer en un servicio Python un endpoint HTTP de health/check que devoelva {"status": "ok"} con codigo 200.

## Architecture Constraints

- Python 3.10+, FastAPI o stdlib-only.
- Single-file: service.py.
- Sin BD, sin estado compartido.

## Non-Goals

- No persistencia.
- No autenticacion en v1.
- No multi-endpoint en v1.
- No dockerizacion obligatoria de v1.

## Quality Bar

- ruff check service.py sin errores.
- Test de humo: GET health response json {status: ok} y codigo 200.
- Tiempo de respuesta < 100ms en local.

## Security Constraints

- No credenciales hardcodeadas.
- No variables de entorno con secretos en v1.
- El endpoint no expone rutas del sistema.

---

## OBJ-001 -- Endpoint health operativo

- **Descripcion:** el servicio expone GET health que devuelve {"status": "ok"} con codigo 200 y sin autenticacion.
- **failure_modes:**
  - El endpoint devuelve codigo distinto de 200.
  - La respuesta no contiene el campo status.
  - El servicio no arranca sin configuracion manual adicional.
  - Se introduce una dependencia de BD que no existe en el entorno CI.

---

## Negative Audit Checklist

El contrato/auditoria debe rechazar cualquier propuesta que:

- [ ] Introduzca una capa de BD state persistente (viola Non-Goal).
- [ ] Aumente el acoplamiento entre la logica de health y otros modulos.
- [ ] Exija que el usuario edite service.py o este charter directamente (debe ser DEC-*).
- [ ] Degrade la trazabilidad (p.ej. quitar el campo status de la respuesta).
- [ ] Introduzca autenticacion sin abrir un ticket separado.
- [ ] Introduzca mas de un endpoint sin re-charter.
