# Registro de excepciones YAML (WOT-2026-119a)

Sustituye el mecanismo de override por commit-message de
`scripts/check_cuspide_growth_and_drift.py` (WOT-2026-108d, hoy impotente a
proposito -- ver el docstring de `scripts/override_registry.py` para el
analisis completo de por que ese mecanismo era irreparable).

## Formato de un override activo

Un fichero `.yaml` en ESTE directorio (nunca en `_archive/`) con los 5 campos
obligatorios:

```yaml
id: OVERRIDE-WOT-2026-XXXXX-001
scope:
  - ruta/literal/exacta/al/fichero.py
expiry: 2026-11-15          # fecha ISO YYYY-MM-DD; obligatoria, nunca indefinida
aprobador: nombre.apellido  # quien autorizo la excepcion, NUNCA quien la consume
justificacion: >-
  Motivo concreto, no vacio, de por que esta excepcion es necesaria y por que
  expira en la fecha indicada.
```

## Las 4 salvaguardas (verificadas por `scripts/check_override_registry.py`)

- **(a) Anti-auto-aprobacion:** el override NO puede anadirse o modificarse en
  el MISMO commit que un fichero dentro de su propio `scope`. Aterrizalo en un
  commit previo, revisado antes de que exista el cambio que excepciona.
- **(b) Expiry barrido por un proceso real:** el hook `commit-msg` (cableado en
  `.pre-commit-config.yaml`, corre en CADA commit) bloquea si un override
  activo ya expiro y sigue sin archivar. El hook `pre-commit` ya avisa antes
  de eso.
- **(c) Scope estricto:** `scope` es una lista de rutas LITERALES. Ningun
  comodin (`*`, `?`, `[`, `]`) -- un YAML con comodines en `scope` es
  malformado y el registro entero falla fail-closed.
- **(d) Fail-closed:** un YAML ilegible, incompleto o con tipos incorrectos en
  CUALQUIER fichero de este directorio bloquea el commit con exit 1, nunca
  degrada a exit 0 silencioso.

## Archivar un override vencido

Muevelo a `_archive/` (crear el directorio si no existe). `load_overrides()`
no es recursivo: un override en `_archive/` deja de contar como activo sin
necesitar ningun campo `status`.
