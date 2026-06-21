# Focal test selector (WOT-2026-010l)

> Ergonomia local de iteracion para el Builder. NO es evidencia valida de
> handoff: por construccion una corrida focal produce `args_mode=explicit_args`,
> asi que `010q` la sigue bloqueando para `--mark-ready`.

## Que hace

`scripts/test_selection.py` lee el diff real del working tree del motor
(reutilizando el seam canonico `.agent/scope_gate.py::get_changed_files`, sin
abrir un parser git paralelo) y propone un subset reproducible de tests para
iterar localmente mas rapido. Cuando no puede demostrar un mapeo seguro, **falla
abierto a la suite canonica completa** con una razon auditable.

## Como invocarlo

```bash
python scripts/run_pytest_safe.py --select-from-diff
```

- Si el selector resuelve un subset seguro, el runner lo anexa como argumentos
  explicitos de pytest y avisa en consola que la corrida es focal.
- Si el selector replega, el runner imprime la razon y ejecuta la suite
  canonica completa.

El modo sin la flag es identico al de siempre (aditividad total): cero
regresion para `--level all` ni para el discovery por defecto.

## Mapeo archivo -> tests (conservador y auditable)

- Un test cambiado (`tests/**/test_*.py` o `tests/**/*_test.py`) se incluye a si
  mismo.
- Un cambio en `scripts/<name>.py` selecciona los tests cuyo nombre contiene
  `<name>` bajo `tests/` (`test_<name>.py`, `<name>_test.py`, etc.).
- Cualquier ruta que no resuelva a un test concreto y seguro NO se adivina: si
  el conjunto final queda vacio, se replega.

## Cuando replega a la suite canonica (fail-open)

El selector devuelve `mode="fallback"` con una `reason` legible cuando:

| Situacion | `reason` (prefijo) |
|-----------|--------------------|
| `git diff` no se puede leer / no hay repo | `no_diff_available` |
| El diff no resuelve archivos bajo una raiz conocida | `empty_diff` |
| Cambio en archivo troncal (`pyproject.toml`, `pytest.ini`, `.agent/**`) | `structural_change` |
| El mapeo no resuelve ningun test | `no_safe_mapping` |
| El modulo selector no carga | `selector_unavailable` |

La razon queda registrada en `.agent/runtime/pytest-safe/last-run.json` bajo
`focal_selection.reason` cuando se invoca con `--select-from-diff`, de modo que
el repliegue es auditable a posteriori. No existe pass-open silencioso: ante
cualquier duda se corre la suite canonica completa.

## Como detectar que replego

- En consola: `[pytest-safe] Focal selection fell open to full suite: <reason>`.
- En `last-run.json`: `focal_selection.fell_open == true` y la `reason`.
- En cualquier caso, `level` y `args_mode` del run reflejan lo que realmente se
  ejecuto, que es lo que `010q` inspecciona para el handoff.

## Relacion con el contrato de cierre

- El selector no toca la politica de handoff ni el schema de `last-run.json`.
- Una corrida focal nunca satisface `--mark-ready`: `010q` exige `level=all` +
  `args_mode=default_discovery`, y el subset focal siempre es `explicit_args`.
