# Review Packet Hardening — WOT-2026-010i

> Origen: la review de `WOT-2026-010e` detecto tres fallos que el tooling solo
> encontro tarde. Este ticket los convierte en barreras mecanicas con
> diagnostico self-service, antes de que el packet llegue al Manager.

## Barreras anadidas

### 1. Forbidden Surfaces como contrato ejecutable

Las rutas declaradas en `## Forbidden Surfaces` del `work_plan.md` ya no son
solo prosa de auditoria: un diff que toque una de ellas bloquea el handoff.

- **Parser:** `.agent/scope_gate.py::parse_forbidden_surfaces(content, *, project_root)`,
  que reutiliza `_extract_section_paths` — las mismas heuristicas de token de
  ruta que gobiernan Files Likely Touched. Una entrada conceptual como
  `cache pytest` o `xdist/sharding` no resuelve a una ruta concreta y por tanto
  no genera falsos positivos.
- **Consumo:** `scripts/pre_handoff_guard.py::check_forbidden_surfaces` compara
  los archivos cambiados contra el conjunto Forbidden (resuelto contra
  `project_root` y `motor_root` cuando difieren).
- **Diagnostico:** nombra la ruta exacta y remedia: revertir el cambio o usar
  un ticket cuyas Forbidden Surfaces no la listen.

### 2. Commit visible para tickets code/mixed

Un packet `code` o `mixed` sin un commit del repo_motor que nombre el ticket no
puede pasar a review.

- **Funcion:** `scripts/pre_handoff_guard.py::assert_ticket_commit_visible`.
- **Regla:** escanea los ultimos N (20) mensajes de commit del repo_motor en
  busca del `ticket_id`. Si no aparece -> bloquea con remediacion accionable.
- **Excepcion documental:** `documentation`, `research` y `analysis` estan
  exentos (pueden cerrar sobre artefactos documentales sin commit de codigo).
- **Fail-closed:** un fallo de git para un ticket code/mixed bloquea, nunca
  pasa en silencio.

### 3. Test semantico de `_resolve_destino`

`scripts/encoding_post_write_hook.py::_resolve_destino` debe leer
`destination_root` de `motor_destination_link.json`, nunca `motor_root`.

- **Test:** `tests/unit/test_encoding_post_write_hook.py::
  test_resolve_destino_returns_destination_root_not_motor_root` afirma el valor
  EXACTO retornado con `motor_root` y `destination_root` distintos y reales, mas
  un negativo explicito (`!= motor_root`). Blinda el bug de `010e` aunque ya
  este corregido.

## Tests de fallback honestos

El test de fallback que observa el efecto real de subprocess ya existe:
`test_check_subprocess_invokes_check_encoding_guard` invoca `_check_subprocess`
directamente y verifica que detecta un BOM via el subprocess real, no por un
truco de entorno que el codigo neutralice. No se anade un duplicado cosmetico.

## Regla operativa resultante

Antes del Manager, el pre-handoff bloquea mecanicamente:
1. diff sobre una Forbidden Surface declarada,
2. packet code/mixed sin commit visible del ticket,
3. (via test de regresion) lectura del campo equivocado en `_resolve_destino`.

Cada barrera produce un diagnostico que nombra la ruta o campo implicado y la
accion de remediacion, sin requerir que el Builder lea el codigo del guard.
