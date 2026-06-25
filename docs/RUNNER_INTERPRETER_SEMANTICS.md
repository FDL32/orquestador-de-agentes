# Canonical-suite runner: interpreter vs tested_commit_sha (two independent axes)

> **Estado:** VERIFICADO EN CODIGO contra `scripts/run_pytest_safe.py` (motor HEAD
> al crear este doc) y reproducido empiricamente. Origen: reconciliacion de una
> ambiguedad detectada en el cierre de `WOT-2026-013k`.

## Resumen (la regla)

`run_pytest_safe.py` decide DOS cosas por **ejes distintos e independientes**. No
los confundas: tratarlos como uno solo (p.ej. "todo por `delivery_authority`" o
"siempre en el motor") produce errores operativos reales.

| Eje | Lo decide | Disparador real |
|-----|-----------|-----------------|
| **Interprete** de la suite | `resolve_test_interpreter()` (`scripts/run_pytest_safe.py:141`) | El **workspace activo** (`PROJECT_ROOT`, derivado de `AGENT_PROJECT_ROOT`) **!= motor** **Y** ese workspace **tiene `.venv`** -> usa ese venv; si no, `sys.executable`. **NO** depende de `delivery_authority`. |
| **`tested_commit_sha`** estampado en `last-run.json` | `_delivery_head_sha()` (`scripts/run_pytest_safe.py:169`) via `_delivery_repo_root()` (`:112`) | **`delivery_authority`** del `work_plan` activo: `repo_destino` -> HEAD del destino; `repo_motor` (default) -> HEAD del motor. |

## Detalle, con citas al codigo

### Eje 1 — interprete: `resolve_test_interpreter()` (`:141`)

```python
active = _PROJECT_ROOT.resolve()           # PROJECT_ROOT viene de AGENT_PROJECT_ROOT
motor  = _PROJECT_ROOT_BOOTSTRAP.resolve()  # el motor donde vive el runner
if active != motor:                         # :162
    venv_py = _venv_python(active)
    if venv_py is not None:
        return str(venv_py)                 # :165  -> venv del workspace activo
return sys.executable                        # motor / single-repo / sin venv destino
```

El disparador es la **presencia de `.venv`** en el workspace activo, no
`delivery_authority`. Introducido por CTL-2026-007b (Fase 2.4) para que la suite
de un destino corra con SUS dependencias (p.ej. `loguru`) y no falle por
coleccion (exit 2) bajo el interprete del motor.

### Eje 2 — `tested_commit_sha`: `_delivery_head_sha()` (`:169`) / `_delivery_repo_root()` (`:112`)

```python
def _delivery_repo_root() -> Path:
    if _delivery_authority() == "repo_destino":   # :120
        return _PROJECT_ROOT                        # HEAD del destino
    return _PROJECT_ROOT_BOOTSTRAP                   # HEAD del motor (default)
```

El `last-run.json` estampa el HEAD del **repo de entrega** segun
`delivery_authority`, para que el pre-handoff gate compare contra el commit que se
esta entregando (WOT-2026-010c).

## Regla operativa (que hacer)

- **Ticket `delivery_authority: repo_motor`** (codigo entregado vive en el motor):
  corre la suite canonica **SIN** exportar `AGENT_PROJECT_ROOT` apuntando al
  workspace. Si lo apuntas y el workspace tiene `.venv`, el runner usara ESE venv;
  si no tiene `pytest` instalado, veras `No module named pytest` y **la suite NO
  corre**.
- **Ticket `delivery_authority: repo_destino`** (codigo entregado vive en el
  destino): **SI** exporta `AGENT_PROJECT_ROOT=<destino>` para que el runner use el
  venv del destino (con sus deps) y estampe el HEAD del destino.

En ambos casos la evidencia de cierre es **el `last-run.json`** (`status=finished`,
`exit_code`, `tested_commit_sha == delivery HEAD`, `level`, `args_mode`, y
resultado real `N passed` / ausencia de `failed`), **nunca** el exit del proceso
wrapper que orquesta la corrida.

## Caso de evidencia (NO norma): WOT-2026-013k

`013k` es `delivery_authority: repo_motor`. La primera corrida de cierre uso
`AGENT_PROJECT_ROOT=<workspace>` (receta cross-repo del prompt, que aplica a
`repo_destino`). El runner eligio el `.venv` del workspace, que **no tiene
pytest** -> `No module named pytest`, suite NO corrida. El **artefacto** lo
capturo correctamente: el `last-run.json` del workspace quedo en `exit_code: 1`
(el gate SI detecta el fallo). La corrida correcta fue con el interprete del motor
(sin `AGENT_PROJECT_ROOT` al workspace) -> 3197 passed, `tested_commit_sha` ==
motor HEAD. El "0" enganoso era solo el exit del proceso wrapper de fondo, no del
gate.

Reproduccion empirica de los dos ejes (resumen):

| Caso | Interprete | `tested_commit_sha` |
|------|-----------|---------------------|
| motor (sin `AGENT_PROJECT_ROOT`) | `sys.executable` | HEAD del motor |
| `AGENT_PROJECT_ROOT=<workspace>` con `.venv`, pero `delivery_authority=repo_motor` | venv del **workspace** | HEAD del **motor** |

La segunda fila es la trampa: el interprete cambia por el `.venv`, pero el SHA
sigue el `delivery_authority`. Son ejes distintos.

## Notas que esto corrige

- El prompt canonico `prompts/orchestrator_launch_builder.md` (seccion
  "Cierre cross-repo", ~`:201`) ya condiciona la receta a
  `delivery_authority: repo_destino`. La impreciscion que causo el error de 013k
  vivia en un prompt one-off (efimero, no versionado), no en el canonico.
- Cualquier nota previa que afirme "el guard siempre lee `last-run.json` del MOTOR,
  incluso para `repo_destino`; corre en repo_motor" esta **obsoleta**
  (pre-CTL-2026-007b) y queda corregida por este documento.
