# Plan de Trabajo: init_session_scratch.py (session-scratch infra, WOT-A)

## Metadata
- **ID:** WOT-2026-022c
- **Estado:** IN_PROGRESS
- **deliverable_type:** code
- **Creado:** 2026-07-11
- **delivery_authority:** repo_motor
- **Prioridad:** MEDIA
- **Asignado a:** Orquestador (implementacion directa)

## Objetivo
Crear `scripts/init_session_scratch.py --project-root <repo>` (OBLIGATORIO) con 6
subcomandos: `init`, `add`, `list`, `audit`, `archive`, `gc`. Gestiona
`<root>/.agent/runtime/session/<session_id>/`. Es la MAIDEN VOYAGE de la capacidad
session-scratch: estrenarla en este ticket AISLADO (no encadenar 022d/022e/022f).

## Contexto
REENCUADRE v3 (2026-07-11): el DoD original se apoyaba en 6 premisas FALSAS, todas
verificadas contra codigo vivo por un plan-audit adversarial (workflow de 7 lentes +
4 auditorias externas independientes, todas convergentes). NO se implemento nada: el
plan-audit cazo los BLOCKER antes de gastar Builder. El backlog ya esta corregido
(workspace c17b098). Ver WOT-2026-022i (bug is_pid_running) y WOT-2026-021q (lock
worktree _dev).

## Las 6 premisas FALSAS corregidas (verificadas en codigo vivo)
1. `resolve_project_root` es `@lru_cache(maxsize=1)` SIN args -> clave CONSTANTE; se
   calienta en IMPORT-TIME -> el override NO gana. Fix: `--project-root` OBLIGATORIO;
   el script NUNCA llama a `resolve_project_root()` -> la trampa DEJA DE EXISTIR.
2. MANIFEST.distribute es CODIGO MUERTO (solo `.exists()` como marcador). El motor NO
   se copia; los destinos lo referencian con `--project-root`.
3. `.agent/runtime/session/` NO esta ignorado en motor NI workspace (`git check-ignore`
   vacio). Anadir la entrada en AMBOS es DoD BINARIO.
4. `write_text` TRUNCA + `except Exception` NO captura `KeyboardInterrupt` -> Ctrl-C a
   mitad de un `add` DESTRUYE el ledger. Fix: writer con lock del SO + O_APPEND.
5. El keep-last-K=10 es de SESIONES ARCHIVADAS, no de records. NO capar el manifest.
6. `run_pytest_safe.acquire_lock` usa `os.kill(pid,0)` -> `SystemError` sobre proceso
   ajeno vivo ESCAPA de `except OSError` -> REVIENTA. Canon correcto:
   `bus/builder_locks.py`.

## Los 5 BLOCKER del plan-audit v2 (con probes EJECUTADOS)
- **B1**: `O_APPEND` puro NO es append-only seguro en Windows (pierde/corrompe records
  bajo concurrencia). Fix: writer con lock exclusivo del SO (msvcrt.locking/fcntl.flock).
- **B2**: `os.open` sin `O_BINARY` traduce LF->CRLF -> ledger corrupto. Fix: `O_BINARY`
  siempre (via `getattr(os,'O_BINARY',0)`, portable).
- **B3**: `os.replace()` de un DIRECTORIO falla si destino existe o hay fd abierto.
  Fix: `archive` fail-closed (destino NO debe existir; cerrar fd; capturar PermissionError).
- **B4**: marker `.takeover` fosilizado = DEADLOCK PERMANENTE. Fix: marker con TTL
  propio (60s); si mtime es mas viejo, se considera abandonado.
- **B5**: sentinela `SENTINEL-<uuid4>` RECHAZADO por SESSION_ID_RE. Fix: sufijo del
  regex ampliado a `[0-9a-f]{4,32}`; sentinela = `<fecha>-<sha>-<uuid4().hex>` (32 hex).
- **B6**: `builder_locks._is_pid_alive` es fail-CERRADO-a-muerto. Canon correcto =
  `conftest.py:114` (fail-safe a VIVO). Copiar conftest, no builder_locks.

## Alcance EXACTO

### CREAR `scripts/init_session_scratch.py`
- **D1**: MOTOR_ROOT para sys.path (from `__file__`); DATA_ROOT from `--project-root`.
  NUNCA `resolve_project_root()` -> la trampa lru_cache deja de existir.
- **D2**: `--project-root` OBLIGATORIO + validacion fail-closed (existe + `.agent/`)
  ANTES de crear nada. Typo -> exit 2 (no arbol fantasma, CTL-2026-007b).
- **D3**: contenedor `mkdir(parents=True)`, leaf `<session_id>` con `os.mkdir` EXCLUSIVO.
- **D4'**: session_id = `<YYYYMMDD-HHMM>-<short-sha|nogit>-<secrets.token_hex(2)>`.
  ALLOWLIST regex: `^\d{8}-\d{4}-(?:[0-9a-f]{4,40}|nogit)-[0-9a-f]{4,32}$` en TODOS los
  enumeradores. `_archive` NUNCA matchea (empieza por `_`). Inyectable por `--session-id`.
- **D6**: required CONDICIONAL por event. `lock_reclaimed` -> `frozenset()` VACIO (NO
  exige generator/artifact_path). Si exigiera -> sesion INARCHIVABLE PARA SIEMPRE.
- **D7**: repo_role: motor / no_motor / unknown (marcador `.agent/agent_controller.py`).
  Override explicito por `--repo-role`.
- **D8**: prompt_version.sha256 sobre BYTES NORMALIZADOS (CRLF->LF + rstrip).
- **D9**: artifact_path RELATIVO al session dir, validado ANTES del writer.
  `try/except ValueError` LOCAL (no tragar en el fail-open).
- **D10'**: lock.json = `{pid, session_id, op, created_at, expires_at}`. LOCK_TTL=900s.
  `lock_is_live()` = TTL puro por `expires_at` (patron `builder_alive`:128-132).
  `is_pid_alive_best_effort()` = patron `conftest.py:114` (fail-safe a VIVO), AUXILIAR
  SOLO en `archive`/`gc`. Takeover ATOMICO (`O_CREAT|O_EXCL`) + marker con TTL 60s +
  record `lock_reclaimed`. `release_lock`: unlink SOLO si pid Y session_id son mios.
- **D11**: `audit`: exit 1 por defecto (lo usa `archive`) + `--report-only` exit 0
  SIEMPRE (canon `validate_observations.py:414` `--dry-run`).
- **D12'**: `archive` fail-closed. Orden: raiz valida -> session_id matchea regex y
  dir existe -> lock VIVO ajeno -> STOP -> audit interno LIMPIO -> si no, STOP ->
  destino `_archive/<id>` NO debe existir -> `os.replace()` capturando PermissionError.
- **D13**: `.gitignore` en MOTOR y WORKSPACE (DoD binario, `git check-ignore`).
- **W1**: Writer del ledger con lock del SO (`msvcrt.locking` en nt, `fcntl.flock` en
  posix). `O_BINARY` siempre. Append-only ESTRICTO. SIN tail-cap.
- **E1**: Exit codes hibrido por clase de fallo:
  - Infraestructura (manifest no escribible, disco, lock SO): exit 0 + `degraded: true`.
  - Uso (artifact_path fuera de politica, event desconocido, falta campo required
    condicional, --project-root invalido): exit 2.
  - OK: exit 0.

### Subcomandos
- `init`: idempotente. RESUME solo si identidad COMPLETA coincide. Identidad ausente
  o distinta -> fail-closed (exit 2).
- `add`: append record a manifest.jsonl. fail-OPEN (exit 0 + degraded) o exit 2 (uso).
  JSON stdout: `{written, degraded, reason}`.
- `list`: enumerar sesiones (con ALLOWLIST, excluye `_archive`).
- `audit`: exit 1 por defecto / `--report-only` exit 0 SIEMPRE.
- `archive`: fail-closed. Mover sesion a `_archive/`.
- `gc`: keep-last-K=10 de SESIONES ARCHIVADAS. `--dry-run` (reporta sin escribir).

### CONSERVAR / NO TOCAR
- `bus/builder_locks.py` (canon del lock, se CITA no se importa).
- `tests/conftest.py:114` (canon pid-alive, se CITA no se importa).
- `bus/redact.py` (redact_payload, se IMPORTA).
- Las 4 superficies downstream (bootstrap l.94/96/192; PASO 0 pipelines; Bloque 2.5
  session_close; preflight findings) -> 022c NO las toca.

## Definition of Done (DoD)
- (a) M1 agnosticismo, 3 ejes DISJUNTOS: cwd=dir NEUTRAL, __file__=motor,
  --project-root=repoA/repoB (2 repos git bajo `conftest.REAL_SYSTEM_TEMP`, NO tmp_path).
  Subproceso `env=os.environ.copy()`. Asserts en orden: returncode==0, POSITIVO, NEGATIVO.
- (b) T-LEDGER-CONC: N procesos concurrentes x M `add` -> todas las lineas presentes y
  parseables; 0 bytes CRLF en el fichero.
- (c) T-TAKEOVER-FOSIL: marker `.takeover` viejo -> takeover NO se bloquea. Mutation:
  quitar TTL del marker -> deadlock -> test FALLA.
- (d) T-ARCHIVE-DEST-EXISTE: `_archive/<id>` ya existe -> archive STOP fail-closed,
  sesion INTACTA en `session/`.
- (e) Test negativo fail-open (manifest no escribible -> exit 0 + degraded) Y test exit 2
  de uso (artifact_path fuera de politica -> exit 2).
- (f) `lock_reclaimed` sin generator/artifact_path -> audit LIMPIO.
- (g) CRLF/LF -> mismo sha256 de `prompt_version`.
- (h) `list`/`gc` ignoran `_archive`. `gc` keep-last-K=10 de archivadas.
- (i) Aislamiento ESTRUCTURAL: (a) todo harness pasa --project-root tmp; (b) sentinela
  por session_id UNICO Y CONFORME; (c) fixture session-scoped hashea SOLO
  `<motor>/.agent/runtime/session/`; (d) mutation aislando la rama.
- (j) Maiden voyage: 2 sesiones SIMULTANEAS no colisionan; interrupcion entre audit y
  archive deja sesion INTACTA; reclamacion de lock expirado por takeover atomico (2
  procesos compiten, gana EXACTAMENTE 1).
- (k) `.gitignore` en MOTOR y WORKSPACE: `git check-ignore` confirma.
- (l) py_compile + ruff + ASCII limpios (encoding-guard scope `scripts/**/*.py`).
- (m) Suite `run_pytest_safe --level all` -> "N passed / 0 failed"; tested_sha==HEAD.

## MUTATIONS (cada barrera, su mutante)
1. quitar `(root/".agent").is_dir()` -> test raiz invalida FALLA
2. `lock_reclaimed` required={generator,artifact_path} -> test anti-fosilizacion FALLA
3. writer sin lock del SO -> T-LEDGER-CONC FALLA (records perdidos)
4. writer sin `O_BINARY` -> assert 0 bytes CRLF FALLA
5. marker `.takeover` sin TTL -> T-TAKEOVER-FOSIL FALLA (deadlock)
6. `archive` sin check destino existente -> T-ARCHIVE-DEST-EXISTE FALLA
7. `release_lock` -> unlink incondicional -> test lock ajeno FALLA
8. `lock_is_live` mirando pid ademas del TTL -> test TTL-puro FALLA
9. enumeradores sin filtro regex -> test `_archive` FALLA
10. `normalize_prompt_bytes` sin CRLF->LF -> test hash FALLA
11. `audit --report-only` heredando exit -> su test FALLA
12. `add` propagando excepcion de IO -> test negativo (exit 0 + degraded) FALLA

## Riesgos y barreras
- lru_cache trap: `--project-root` OBLIGATORIO, NUNCA `resolve_project_root()`.
- Writer corruption: lock del SO + O_BINARY (B1/B2).
- Takeover deadlock: marker con TTL (B4).
- archive PermissionError: fail-closed, sesion INTACTA (B3).
- Fosilizacion: required CONDICIONAL por event (D6).
- PII: whitelist de campos + redact_payload como red secundaria.
- Aislamiento: estructural, no disciplina (WOT-2026-022g).
