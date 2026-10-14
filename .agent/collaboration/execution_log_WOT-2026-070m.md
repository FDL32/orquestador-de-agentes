# Receipt Paso 0 — WOT-2026-070m (BUI-070m-r4)

generado por script: rev070m_r4_variants.py
modelo: nan/qwen3.6 (builder r4)
fecha: 2026-10-14
actor/shell/cwd/PATH (equivalencia de ruta productiva):
  actor: python.exe (worktree bui-070m)
  shell: PowerShell 5.1 (win32)
  cwd: C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev\.kilo\worktrees\bui-070m
  python: C:\Users\fdl\Proyectos_Python\orquestador_de_agentes_dev\.kilo\worktrees\bui-070m\.venv\Scripts\python.exe

---

## 4 Variantes sobre fixture hermética NUEVA por variante

Cada variante usa un `tempfile.mkdtemp()` con `.git` propio,
drift re-establecido (STATE.md vs bus), y mide mtime + bytes +
sha256 + line-endings ANTES/DESPUES.

### Variante (i): A_force_heal
  Flags: `--validate --json --force`
  exit_code: 1
  state_changed: True
  mtime ANTES: 1791967799.3709536
  bytes ANTES: 50
  sha256 ANTES: 0f7d48ccb3d91854dea0369c7079b36094e5c72c9c00fa8303135f758e4cb4ba
  line-endings ANTES: CRLF=2 bare_LF=0
  mtime DESPUES: 1791967801.4122832
  bytes DESPUES: 55
  sha256 DESPUES: 7761a67063f2087fc19b93a50450ec9bccc15977a384c56abac57eff1b554bb8
  line-endings DESPUES: CRLF=2 bare_LF=0
  contenido ANTES: 'ACTIVE_TICKET: WOT-TEST-001\r\nSTATUS: IN_PROGRESS'
  contenido DESPUES: 'ACTIVE_TICKET: WOT-TEST-001\r\nSTATUS: READY_FOR_REVIEW'

### Variante (ii): B_force_noheal
  Flags: `--validate --json --force --no-heal`
  exit_code: 1
  state_changed: False
  mtime ANTES: 1791967801.4773755
  bytes ANTES: 50
  sha256 ANTES: 0f7d48ccb3d91854dea0369c7079b36094e5c72c9c00fa8303135f758e4cb4ba
  line-endings ANTES: CRLF=2 bare_LF=0
  mtime DESPUES: 1791967801.4773755
  bytes DESPUES: 50
  sha256 DESPUES: 0f7d48ccb3d91854dea0369c7079b36094e5c72c9c00fa8303135f758e4cb4ba
  line-endings DESPUES: CRLF=2 bare_LF=0
  contenido ANTES: 'ACTIVE_TICKET: WOT-TEST-001\r\nSTATUS: IN_PROGRESS'
  contenido DESPUES: 'ACTIVE_TICKET: WOT-TEST-001\r\nSTATUS: IN_PROGRESS'

### Variante (iii): C_noForce_noheal
  Flags: `--validate --json --no-heal`
  exit_code: 1
  state_changed: False
  mtime ANTES: 1791967804.2460408
  bytes ANTES: 50
  sha256 ANTES: 0f7d48ccb3d91854dea0369c7079b36094e5c72c9c00fa8303135f758e4cb4ba
  line-endings ANTES: CRLF=2 bare_LF=0
  mtime DESPUES: 1791967804.2460408
  bytes DESPUES: 50
  sha256 DESPUES: 0f7d48ccb3d91854dea0369c7079b36094e5c72c9c00fa8303135f758e4cb4ba
  line-endings DESPUES: CRLF=2 bare_LF=0
  contenido ANTES: 'ACTIVE_TICKET: WOT-TEST-001\r\nSTATUS: IN_PROGRESS'
  contenido DESPUES: 'ACTIVE_TICKET: WOT-TEST-001\r\nSTATUS: IN_PROGRESS'

### Variante (iv): D_noForce_heal
  Flags: `--validate --json`
  exit_code: 1
  state_changed: True
  mtime ANTES: 1791967806.4852536
  bytes ANTES: 50
  sha256 ANTES: 0f7d48ccb3d91854dea0369c7079b36094e5c72c9c00fa8303135f758e4cb4ba
  line-endings ANTES: CRLF=2 bare_LF=0
  mtime DESPUES: 1791967808.0018053
  bytes DESPUES: 55
  sha256 DESPUES: 7761a67063f2087fc19b93a50450ec9bccc15977a384c56abac57eff1b554bb8
  line-endings DESPUES: CRLF=2 bare_LF=0
  contenido ANTES: 'ACTIVE_TICKET: WOT-TEST-001\r\nSTATUS: IN_PROGRESS'
  contenido DESPUES: 'ACTIVE_TICKET: WOT-TEST-001\r\nSTATUS: READY_FOR_REVIEW'

---

## Veredicto final

- Variante A (`--validate --json --force`): reescribe STATE.md -> DEBIA CAMBIAR
- Variante B (`--validate --json --force --no-heal`): NO reescribe -> el fix propuesto (WOT-2026-070m) confirma
- Variante C (`--validate --json --no-heal`, plan iii): NO reescribe -> confirma que `--force` es irrelevante para el heal
- Variante D (`--validate --json`, sin force SIN no-heal): reescribe -> **es el refutador REAL** de '--force causa la reescritura': sin `--force` y sin `--no-heal` SÍ reescribe, asi que el discriminante es `--no-heal`, no `--force`

## Evidencia de cierre

- **4/4 aserciones PASSED** (ver abajo)
- **SHA256 ANTES verificable:** reproducir con `Get-FileHash` sobre el STATE.md de la fixture
- **state_changed discriminante:** `--no-heal` presente -> no escribe; ausente -> escribe (con o sin `--force`)

---

### Aserciones
- [PASS] A (force+heal) CAMBIA
- [PASS] B (force+no-heal) NO cambia
- [PASS] C (iii: no-force+no-heal) NO cambia
- [PASS] D (no-force+heal) CAMBIA -> refuta --force

---

Nota: fixture hermética NUEVA por variante (tempfile.mkdtemp + .git propio).
Cero interacción con el workspace real wt_kilo_067a ni impl-vuelo2-20261013.
