# STRATEGY WOT-2026-129b: `create_worktree_pair.py --base-ref`

## TP Check (premisa verificada en vivo, HEAD def13f4a6c4f52714d86222e26c114380e35f656)
`scripts/create_worktree_pair.py::git_worktree_add` (linea ~96-123) llama
`git worktree add -b <branch> <worktree>` SIN punto de partida (usa el HEAD
del repo principal). `run_verify` (linea ~192-206) corre
`collect_session_state.py` pero su returncode se IGNORA; el sumario final
(linea ~365-370) imprime "worktree pair creado" incondicionalmente, incluso
en `--dry-run` (donde ademas `run_verify` se ejecuta DE VERDAD contra un
`destino_worktree` que no existe). Premisa CONFIRMADA.

## Non-goals
- NO se toca `write_link()` ni el schema del payload del link
  (`motor_root`/`destination_root`/`motor_sha`/`created_at`): anadir
  `ticket_prefix`/`destination_id` es WOT-2026-126d, ticket distinto. No lo
  absorbemos, no lo pisamos: si WOT-2026-126d aterriza primero, este ticket
  se adapta via rebase, no al reves.
- NO se cambia el comportamiento de `uv_sync_failed` (linea 342-358): sigue
  imprimiendo el sumario y devolviendo 1 si falla, eso es intencional y
  fuera de esta ficha.

## Decision de diseno 1: `--base-ref` (default `origin/main`)
Nueva funcion `resolve_start_point(repo: Path, base_ref: str, dry_run: bool) -> str`:
1. Si NO `dry_run`: `git -C repo fetch` best-effort, con
   `env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}` y `timeout=30` (si
   expira o falla, se captura -- `subprocess.TimeoutExpired` y
   `CalledProcessError`/rc!=0 ambos tratados como "fetch_ok = False", NO
   se propaga como error todavia: un repo sin remoto configurado es un caso
   LEGITIMO, no un fallo).
2. SIEMPRE (ambos modos, es de solo lectura): `git -C repo rev-parse
   --verify <base_ref>^{commit}`. Si falla: `raise ValueError(f"--base-ref
   '{base_ref}' no existe en {repo} (ni tras fetch). Verifica el remoto o
   pasa un --base-ref valido.")`.
3. **Correccion CONTRACT_AUDIT (BA07, ronda 1): si `fetch_ok` es False Y el
   paso 2 SI resuelve** (ref local stale de un fetch anterior, remoto hoy
   caido), imprimir a stderr `[WARN] --base-ref '{base_ref}' resuelto sin
   poder actualizar {repo} via fetch; puede estar desactualizado.` -- NO
   bloqueante, solo visibilidad del caso "remoto caido silencioso" que BA07
   senalo como hueco.
4. Devuelve `base_ref` tal cual (git acepta el nombre del ref directamente
   como start-point de `worktree add`; no hace falta resolver a sha).

**Correccion CONTRACT_AUDIT (BA07, ronda 1, BLOCKER de orden): `resolve_start_point`
NO se llama tras validar `is_git_repo` a secas.** Solo tiene sentido dentro
de la rama `state == "absent"` (justo antes de "Step 4: Create motor
worktree", linea ~318 de hoy): un par YA `complete` (no-op) o `partial`
(diagnostico) no debe fallar por un `--base-ref` irresoluble que es
irrelevante para esos dos casos -- eso rompe el diagnostico existente de
`_print_partial_diagnostic` para repos legitimos sin `origin` configurado.
Orden correcto: `is_git_repo` -> calcular rutas -> `classify_pair_state`
-> SOLO si `state == "absent"`: `resolve_start_point` para motor_repo y
para destino_repo (remotos DISTINTOS, cada uno el suyo) -> si cualquiera
lanza `ValueError`: imprimir a stderr, devolver 1, sin crear ningun
worktree -> si ambos resuelven: crear motor, crear destino, con el
`start_point` correspondiente a CADA uno.

`git_worktree_add(repo, worktree, branch, start_point, dry_run)` anade el
parametro `start_point` y lo pasa como argumento final de `git worktree add
-b <branch> <worktree> <start_point>`. El mensaje `[DRY-RUN] haria: ...`
incluye `start_point`. La rama de retry sin `-b` (branch ya existe) NO lleva
`start_point` (una rama existente conserva su propia punta; sin cambios ahi).

CLI: `--base-ref` (default `"origin/main"`), aplicado IGUAL para motor y
destino (mismo nombre de ref, resuelto cada vez contra el remoto de SU
propio repo).

## Decision de diseno 2: gating por verificacion (DoD punto 2)
Step 8 (verify) y step 9 (sumario) de `main()`:
- `dry_run=True`: NO ejecutar `run_verify` de verdad (hoy es un bug: corre
  contra un `destino_worktree` que no existe). Imprimir
  `"[DRY-RUN] haria: verificacion con collect_session_state.py"` y tratar
  como "no aplica" (no hay rc real que gatear).
- `dry_run=False`: `verify_rc = run_verify(destino_worktree)`. Si
  `verify_rc != 0`: imprimir `[ERROR] La verificacion del par
  (collect_session_state.py) fallo con rc=<verify_rc>. Los worktrees se
  crearon pero no se consideran listos.` a stderr, devolver 1, **sin**
  imprimir el sumario "worktree pair creado".
- Sumario final: el texto exacto `"worktree pair creado"` SOLO se imprime
  si `not dry_run and verify_rc == 0`. En `dry_run`, el mensaje es
  `"[DRY-RUN] se crearia el par:"` (nunca el texto "worktree pair creado").
  El `return 1 if uv_sync_failed else 0` final no cambia (fuera de alcance,
  ver Non-goals).

**Verificado EN VIVO (Manager, condicion bloqueante compartida por BA03 y
BA07 ronda 1):** `collect_session_state.py --project-root <repo README-only>`
-> `RC=0` (medido en un fixture temporal minimo, sin `.agent/`). Confirma
que `run_verify` siempre devuelve 0 hoy, por lo que los tests existentes
1/2/6 (primera corrida, path real no-monkeypatcheado) NO se rompen con el
gating nuevo: `verify_rc` sera 0 igual que antes, "worktree pair creado"
sigue imprimiendose. Condicion de BA03/BA07 CERRADA por medicion, no por
argumento.

**Nota CONTRACT_AUDIT (BA07, ronda 1, riesgo declarado, NO bloqueante):**
`scripts/collect_session_state.py::main()` tiene UN solo `return 0`
(linea 661) -- es un recolector puro, nunca devuelve != 0 por diseno
propio (su propio docstring en `run_verify` ya lo dice: "no aborta
main()"). Este ticket construye el GATE correctamente (expone y verifica
`verify_rc`); que el emisor de hoy sea siempre verde es una propiedad de
`collect_session_state.py`, NO de este mecanismo, y queda fuera de
alcance (no se toca ese script aqui). Por eso los tests 3 y 4 de abajo
MONKEYPARCHEAN `run_verify` en vez de depender de que el recolector real
falle -- es la unica forma de ejercitar la rama hoy, y el gate queda listo
para cuando `collect_session_state.py` tenga semantica de fallo real en un
ticket futuro.

## Fixture de tests: origin real, hermetico (decision para no romper los 8 tests existentes)
`test_absent_creates_pair`/`test_dry_run_absent`/etc. NO pasan `--base-ref`
(usan el default `origin/main`) y HOY `_git_init_main` no crea ningun
remoto -> con el default nuevo, fallarian con el ValueError de arriba.
Fix: **anadir a `_git_init_main` (el helper compartido, usado por los 8
tests existentes) la creacion de un remoto `origin` real y hermetico**:
clonar el repo recien creado a un bare adyacente (`repo_path.parent /
f"{repo_path.name}_origin.git"`), `git remote add origin <bare>`, `git
fetch origin`. Esto deja `origin/main` resoluble LOCALMENTE (sin red) y
es inerte para los tests que no llegan al path de creacion de worktree
(parcial/completo). Los 8 tests existentes siguen verdes SIN modificar sus
asserts, solo por el fixture reforzado.

## Tests nuevos (ademas de que los 8 existentes sigan verdes)
1. `test_base_ref_used_not_principal_head`: el repo motor principal avanza
   un commit DESPUES de crear el bare `origin` (o se le anade un segundo
   commit solo en `origin/main` via push desde otro clon) de forma que
   `origin/main` y el HEAD actual del principal DIFIEREN; crear el par con
   `--base-ref origin/main` (default) y verificar que el worktree del
   motor nace en el sha de `origin/main`, NO en el HEAD actual del
   principal (`git -C motor_wt rev-parse HEAD^{commit}` separate del
   `git -C motor_principal rev-parse HEAD`, deben diferir y el del
   worktree debe coincidir con el de `origin/main`).
2. `test_base_ref_missing_errors_clearly`: `--base-ref no-existe-nunca`
   -> rc 1, mensaje de error nombra el ref y el repo, `git worktree list`
   NO muestra ningun worktree nuevo (nada parcial creado).
3. `test_verify_failure_blocks_success_message`: monkeypatchear
   `create_worktree_pair.run_verify` para devolver 1 (no tocar
   `collect_session_state.py` real) -> rc 1, "worktree pair creado" NO
   aparece en la salida combinada, SI aparece un mensaje `[ERROR]` que
   menciona la verificacion.
4. `test_dry_run_never_calls_real_verify`: monkeypatchear
   `create_worktree_pair.run_verify` para que lance `AssertionError` si se
   llama; correr con `--dry-run` y `--base-ref main` (ref local, sin red);
   rc 0, "worktree pair creado" (sin prefijo DRY-RUN) NO aparece.

## Riesgo residual declarado (BA07, no bloqueante)
Si `verify_rc != 0`, los worktrees y el link YA quedaron creados en disco
(el gate solo bloquea el MENSAJE/rc de ESA corrida). Una segunda corrida
clasifica el par como `complete` (classify_pair_state) y devuelve 0 SIN
volver a verificar -- el gate es evitable con un rerun. Aceptado como
limite de este ticket (cambiar la semantica de `complete` para que
re-verifique siempre es un cambio de diseno mayor, no de 1 funcion); si
se quiere cerrar, es ticket propio.

## Gates focales (Manager, no solo informe del Builder)
- `uv run pytest tests/unit/test_create_worktree_pair.py -q` (los 8
  existentes + los 4 nuevos = 12 verdes).
- `ruff check . && ruff format --check .`
- `python scripts/check_guard_wiring.py` (este cambio NO introduce un guard
  nuevo cableado a pre-commit; no deberia alterar el censo -- confirmar que
  sigue en 0 diffs de wiring).
- `git grep -n "base-ref\|base_ref" scripts/create_worktree_pair.py
  tests/unit/test_create_worktree_pair.py` debe mostrar uso real, no solo
  mencion en docstring.
