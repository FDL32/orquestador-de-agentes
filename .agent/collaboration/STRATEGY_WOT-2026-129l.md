# STRATEGY - WOT-2026-129l (settings-canonical-drift-warn)

Contrato: `work_plan.md` (mismo directorio). Este documento es el diseno de
implementacion para el Builder; ante divergencia manda el work_plan.

## Diseno del modulo nuevo: `scripts/check_settings_canonical_drift.py`

### Funciones (firmas objetivo, puras donde importa)

```python
TRIGGER_PATHS = frozenset({
    ".agent/hooks/claude_guard_entry.py",
    "scripts/check_claude_settings_portability.py",
})

def touched_paths(project_root: Path) -> tuple[list[str], str | None]:
    """git diff --name-only origin/main...HEAD en project_root.
    Returns (paths, motive) donde motive != None declara indeterminado
    (sin origin/main, git fallo) -> fail-visible (D4)."""

def is_trigger(touched: Sequence[str]) -> bool:
    """True si alguna ruta normalizada esta en TRIGGER_PATHS."""

def resolve_destino_roots(cli_roots, env_value, motor_checkout_root) -> list[Path]:
    """D2: cli > AGENT_DESTINOS_ROOT (os.pathsep) > padre del checkout."""

def discover_destinos(roots: Sequence[Path]) -> tuple[list[Path], list[str]]:
    """Barredo <root>/*/.agent/config/motor_destination_link.json.
    Returns (destinos_resolubles, problemas) - problemas declara links
    ilegibles/JSON invalido (DoD 3); nunca excepcion no capturada."""

def gate_failing_destinos(destinos, gate_script) -> tuple[list[tuple[Path, str]], int]:
    """Por destino con settings.json: python gate_script <settings>, rc!=0 ->
    (falla, resumen 1a linea del gate); sin settings -> se declara en conteo.
    subprocess.run sin pipe; rc de returncode."""

def build_warn(...) -> tuple[str, list[str]]:
    """Compone el bloque NOMBRADO:
    [settings-canonical-drift] WARN ... lineas por destino en rojo con
    comando `python scripts/install_agent_system.py --sync --dest <destino>`
    (D3), conteo al-dia, declaraciones (universo vacio / ilegibles /
    diff indeterminado / sin settings.json)."""

def main(argv=None) -> int:
    """rc 0 siempre salvo error interno (es un WARN, DoD 3)."""
```

### Cableado: `scripts/prepush_check.py`

- Import ESTATICO dentro de la funcion run_ (patron que el propio prepush ya
  declara: "Import ESTATICO en el run_ -> check_guard_wiring lo cuenta WIRED").
- `def run_settings_canonical_drift_check(project_root: Path) -> CheckResult:`
  con `is_blocking=False` SIEMPRE.
- Registro en `run_preflight_check` tras `run_hook_delivery_check` (5-ter),
  fuera del bloque `closeout_mode` (corre en TODO push).
- Contorno del coste: primer paso = `touched_paths` + `is_trigger`; sin
  trigger -> `CheckResult(name, True, "SKIP: diff no toca triggers (WOT-2026-129l)", is_blocking=False)`.
  Trigger positivo -> evalua universo completo.

### `scripts/check_guard_wiring.py`

- NO se edita (los guards se detectan por analisis AST de invocaciones). El
  Builder LO EJECUTA y verifica que `check_settings_canonical_drift` aparece
  cableado. Si no aparece: PARAR, escalar al Manager (no ampliar FLT sin
  aprobacion).

### Tests: `tests/unit/test_settings_canonical_drift.py`

Fixture: `tmp_path` con motor MINI (gate script stub que replica rc por
contenido de settings fixture: settings "stale" -> rc=1, "fresh" -> rc=0; o
reusar el gate real si es barato - PREFERIBLE gate real con settings fixture
copiados, para no mock-drift) + destinos bajo una raiz tmp con
`.claude/settings.json` + `motor_destination_link.json`.

- test_trigger_canonico_lista_destino_desfasado (CA1/a)
- test_diff_fichero_ajeno_sin_aviso (CA1/b -> CA2)
- test_destino_al_dia_no_aparece (CA1/c)
- test_universo_vacio_se_declara (DoD 3)
- test_link_ilegible_se_declara (DoD 3)
- test_diff_indeterminado_se_declara (D4)
- test_wiring_visivel (CA4): segun lo que prefiera la mecanica real:
  invocar `check_guard_wiring` en el repo fixture o asertar la presencia del
  run_ en `run_preflight_check` + `is_blocking=False` - SIN inventar: el
  Builder primero LEE `check_guard_wiring.py` y elige la mecanica que ese
  script realmente implementa, y lo documenta en el docstring del test.

### CHANGELOG.md

- Entrada bajo el bloque de cambios no publicados actual: WOT-2026-129l con
  una frase (aviso de drift canonico de hooks hacia destinos en prepush, WARN).

## Anti-patrones prohibidos (del AGENTS.md y del vuelo)

- Sin `--source`/rutas inventadas: comando de resync D3 literal.
- Sin bloquear jamas el push (is_blocking=False; mutation: intentar un
  escenario que querria bloquear y comprobar que NO bloquea, segun DoD 3).
- Sin tocar `install_agent_system.py` / generador (129p).
- rc real sin pipe (`$LASTEXITCODE` o `returncode`); tests leidos por
  "N passed", no por exit del wrapper.
- Una ruta por bullet en FLT; nada fuera de los 4 ficheros.
