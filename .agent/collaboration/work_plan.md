# Plan de Trabajo: collect_system_health senala STALENESS del last-run que lee

## Metadata
- **ID:** WOT-2026-021n
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Creado:** 2026-07-10
- **delivery_authority:** repo_motor
- **Prioridad:** BAJA
- **Asignado a:** Builder

## Objetivo
`collect_system_health` lee el `last-run.json` del root elegido (destino si `dest_ok`,
motor si motor-only) y reporta `exit_code`/`source`/`state_leak`/`finished_at`, PERO
NO compara su `tested_commit_sha` con el HEAD del repo de ENTREGA. Un last-run puede
estar STALE (testigo viejo) sin marca alguna: el colector lo trata como evidencia
fresca. Fix: leer `tested_commit_sha` del last-run y compararlo con el HEAD del repo de
entrega (resuelto por `delivery_authority`, no por la ubicacion del fichero); anadir
campo `stale: bool` al `pytest_safe_last_run` + warn `pytest_safe_last_run_stale`
cuando difieren. Es TRANSPARENCIA del testigo, NO un critical (el veredicto de
verde/rojo lo sigue dando exit_code + clasificacion 021m).

## Contexto
Hermano de WOT-2026-021m (b6aea54) y 021c (4f316ce): mismo fichero
`collect_system_health.py`, misma funcion `_read_pytest_last_run` / campo
`pytest_safe_last_run`. El patron code-only ya cerro 021m+021c sobre este fichero
(bajo riesgo, rodado). Evidencia VERIFICADA 2026-07-10: la auditoria
general_audit_20260710_0914 leyo el last-run del DESTINO con
`tested_commit_sha=602e3c78`, finished_at 2026-07-09, mientras el HEAD del workspace
era `bef3ff9`. Precedente del patron: `pre_handoff_guard.py` (l.564-603) ya compara
`tested_commit_sha != delivery HEAD` -> `stale_run`, pero eso vive en el guard de
handoff, NO en el colector de salud.

## Configuracion Privada Requerida
Ninguna.

## Alcance EXACTO (verificado in-vivo 2026-07-10; REVISADO tras plan-audit adversarial)

### BLOCKER del plan-audit (CONFIRMADO in-vivo) -> el HEAD a comparar lo decide
### `delivery_authority`, NO la ubicacion del fichero (`dest_ok`)
La 1a version del plan comparaba contra `dest_head if dest_ok else motor_head` (root
cuyo last-run FILE se lee). ERROR confirmado in-vivo: `tested_commit_sha` lo estampa
`run_pytest_safe._delivery_head_sha()` = HEAD de `_delivery_repo_root()` (l.113-123),
que devuelve el destino SOLO si `_delivery_authority()=="repo_destino"` (leido del
work_plan del destino), si no el MOTOR (DEFAULT `repo_motor`). La UBICACION del fichero
last-run va por `PROJECT_ROOT`/`dest_ok`; el SHA ESTAMPADO va por `delivery_authority`.
Son EJES INDEPENDIENTES. En la topologia mas comun (un destino corre su suite para un
ticket `delivery_authority: repo_motor`), el last-run vive bajo el destino pero
`tested_commit_sha` = HEAD del MOTOR -> comparar contra `dest_head` daria stale=True
ESPURIO en cada run fresco. PRUEBA in-vivo: el SHA de la evidencia `602e3c78` NO existe
en el destino (workspace: `bad object`) y SI en el motor (`602e3c7 docs(prompts)
WOT-2026-019n`); el work_plan del destino tiene `delivery_authority: repo_motor`. => el
testigo debe compararse contra el HEAD del MOTOR, no del destino.

### Coherencia del root (regla correcta)
Resolver el HEAD de comparacion por `delivery_authority` (espejo de
`run_pytest_safe._delivery_repo_root` y `pre_handoff_guard.resolve_delivery_root`):
- `dest_ok` Y `delivery_authority(destino) == repo_destino` -> comparar vs `dest_head`.
- resto (`repo_motor`, o motor-only) -> comparar vs `motor_head`.
`motor_head` (l.267) y `dest_head` (l.268) ya estan en scope; solo hace falta leer el
`delivery_authority` del destino (regex sobre su work_plan; sin git nuevo).

### CAMBIAR (`scripts/collect_system_health.py`)
- Nuevo helper `_read_delivery_authority(root: Path) -> str`: lee
  `<root>/.agent/collaboration/work_plan.md`, regex
  `delivery_authority\s*:?\**\s*(?:repo_destino|destino)` (IGNORECASE) ->
  "repo_destino"; default "repo_motor" si falta/ilegible. Espejo EXACTO de
  `pre_handoff_guard._read_delivery_authority_from_content` (misma regex) para que el
  SHA estampado y el HEAD comparado usen el MISMO criterio.
- `_read_pytest_last_run` (l.128-152): anadir al dict devuelto
  `"tested_commit_sha": d.get("tested_commit_sha")` (usar `.get`; None en records
  `started`/dry-run/fixtures viejos; no petar).
- Caller (tras l.306, donde ya se pone `source`): resolver el HEAD de entrega
  `delivery_head = dest_head if (dest_ok and
  _read_delivery_authority(dest_root) == "repo_destino") else motor_head`.
  Calcular `stale` y anadir `pytest_last["stale"]`. Regla (TRUTHINESS, NUNCA
  `is not None`): `stale = bool(pytest_last.get("present") and tested_sha and
  delivery_head and tested_sha != delivery_head)`. Si falta `tested_commit_sha` (None)
  O `delivery_head` es None/"" -> `stale = False` (indeterminado != stale; sin marca
  espuria). `present False` -> `stale False` (no hay tested_sha).
- Deteccion automatica (bloque l.328-349): anadir, DESPUES de la clasificacion de
  exit_code de 021m y del bloque `missing`, `if pytest_last.get("stale"):
  warnings.append("pytest_safe_last_run_stale")`. Es WARN, jamas critical.

### CONSERVAR (no tocar)
- La clasificacion por causa de 021m (failed/error -> critical; state_leak -> warn;
  else -> critical fail-safe): intacta; opera sobre exit_code, ortogonal a stale.
- El campo `source` de 021c y la eleccion del root leido de 021c (l.305-306): intactos.
- El critical `pytest_safe_last_run_missing`: intacto.
- El resto de checks (ruff, validate, inventarios), findings.json, skeletons, INDEX.

## Definition of Done (DoD)
- (a) Fixture STALE (`tested_commit_sha != delivery_head`): `pytest_last["stale"] is
  True` + `"pytest_safe_last_run_stale"` en warnings.
- (b) Fixture FRESH (`tested_commit_sha == delivery_head`): `stale is False`, sin warn.
- (c) BLOCKER: dest_ok + `delivery_authority: repo_motor` (default) + last-run con
  tested_sha = MOTOR head (distinto del dest head) -> `stale is False` (compara vs
  motor, no vs dest -> NO false-positive). SHAs de motor y dest DISTINTOS en el fixture.
- (d) dest_ok + `delivery_authority: repo_destino` + tested_sha != dest head -> stale
  True (compara vs dest).
- (e) Edge SIN sha (last-run sin tested_commit_sha) -> `stale is False` (no espuria).
- (f) Edge delivery_head None/"" -> `stale is False`.
- (g) NON-GOAL duro: `stale` NUNCA en `criticals`; stale + exit 0 -> 0 criticals.
- (h) Test unitario que cubre (a)-(g) + mutation-verify (romper la comparacion o el
  eje delivery_authority -> el test de stale/blocker falla).
- (i) py_compile + ruff + ASCII limpios (encoding-guard scope: `scripts/**/*.py`).
- (j) Suite `run_pytest_safe --level all` -> "N passed / 0 failed"; tested_sha==HEAD.

## Riesgos y barreras
- (BLOCKER plan-audit) El eje es `delivery_authority`, NO la ubicacion del fichero.
  Barrera: DoD-c/-d con SHAs motor!=dest y ambos valores de delivery_authority.
- Truthiness (no `is not None`) para que None/"" colapsen a stale False. Barrera: DoD-e/-f.
- NON-GOAL DURO: stale es WARN, jamas critical. Barrera: DoD-g (assert explicito).
- NO tocar la clasificacion 021m. NO agrupar con 021k ni 021i. Cierre 021n SOLO.
- El fixture `_fake_run_factory` devuelve UN solo SHA (`abc1234def`) para todo
  rev-parse -> los tests del BLOCKER DEBEN inyectar SHAs motor!=dest (monkeypatch de
  `_git_head` o de la resolucion) o el eje divergente NO se ejercita.
