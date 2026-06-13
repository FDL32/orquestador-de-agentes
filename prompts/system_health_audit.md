# Prompt: Auditoria de Salud del Sistema (System Health Audit)

contract_id: cid-system-health-audit-v0
Skill canonica: skills/system-health-audit/SKILL.md
Recolector determinista: scripts/collect_system_health.py

## Que es y que NO es

Esta es una auditoria periodica de salud de TODO el sistema multi-agente tras
hacer cambios en el motor y/o en un repo destino. Cubre tres capas:

1. `repo_motor` — salud del motor portable.
2. `repo_destino` — salud del workspace destino.
3. integracion motor+destino — que ambos funcionan juntos.

**Division de responsabilidades (regla fundamental, no negociable):**

- **El script `collect_system_health.py` es un RECOLECTOR, no un auditor.** Solo
  ejecuta checks deterministas, normaliza evidencia y escribe artefactos. NO emite
  juicio, NO clasifica hallazgos como verdad, NO archiva ni borra nada.
- **El agente es el AUDITOR.** Aplica juicio adversarial (Pasada B) sobre la
  evidencia recolectada: triangula intencion/codigo/operacion, clasifica claims como
  VERIFICADO / INFERIDO / NO VERIFICADO, detecta falso verde, root equivocado,
  fixture drift y scope creep.

No conviertas el reporte automatico en "verdad oficial". `findings.json` es
`[RELATO]` estructurado; el veredicto lo produce el agente tras re-derivar.

**Read-only (v0).** El recolector NO muta el working tree y NO tiene
`--apply-fixes` en v0 (se reservo para v1, solo para fixes pequenos tipo drift
doc/CLI cuando exista evidencia verificable). Archivado y saneo SALEN como
tickets, nunca se ejecutan en la misma pasada.

Hereda `prompts/audit_agent_output.md` (CEM v0, evidencia antes que relato, doble
pasada adversarial) y `prompts/system_audit_master.md` (dimensiones de auditoria,
formato de hallazgos, plan por tickets).

## Donde viven las cosas

- **El motor EJECUTA; el destino CONSERVA la evidencia.**
- La salida canonica vive en el `repo_destino`:
  `.agent/audits/system_health/general_audit_YYYYMMDD[_HHMM]/`
- Cada ejecucion crea una carpeta INMUTABLE; no se sobrescriben auditorias previas.
- Indice estable: `.agent/audits/system_health/INDEX.md`.
- Si no hay `repo_destino` (modo motor-only), la salida va a una ruta `--out`
  explicita y se marca cobertura degradada.

## Estructura de salida obligatoria

```
general_audit_YYYYMMDD[_HHMM]/
  00_scope.md                 # topologia, HEADs, comandos, cobertura, limitaciones
  01_motor_audit.md           # hallazgos del repo_motor
  02_workspace_audit.md       # hallazgos del repo_destino
  03_integration_audit.md     # motor+destino: link, install/sync, bus, clone limpio
  04_quality_gates.md         # ruff, pytest-safe (cobertura declarada), encoding, validate
  05_archive_plan.md          # KEEP/ARCHIVE/DELETE por ruta + evidencia + riesgo + rollback
  06_tickets.md               # un ticket por familia, criterio binario, STOP, gates
  07_adversarial_review.md    # Pasada B: claims VERIFICADO/INFERIDO/NO VERIFICADO
  auditoria_general_resumen.md
  findings.json               # evidencia normalizada y RELATIVIZADA (sin rutas personales)
  raw/                        # evidencia bruta (NO publicable por defecto)
```

Cada `.md` empieza con el bloque de cabecera fijo:
`Scope / Repo motor (HEAD) / Repo destino (HEAD) / Fecha / Comandos ejecutados /
Cobertura declarada / Limitaciones`.

## Herramientas que el protocolo ORQUESTA (no reimplementa)

- `scripts/local_audit.py` — snapshot de estado del motor.
- `.agent/agent_controller.py --validate --json --force [--project-root <destino>]`.
- `scripts/discover_skills.py --check-contract` — contrato prompt/skill.
- `scripts/run_gates_dispatch.py` o `scripts/run_pytest_safe.py` + `ruff`.
- `scripts/check_encoding_guard.py` — encoding por bytes.
- `scripts/check_motor_pristine.py --snapshot` + `--check --snapshot-file <f> --report <f>`.
- `scripts/classify_publication.py --repo-root <destino>` — clasificacion publicacion.
- `git ls-files` + `MANIFEST.distribute` / `MANIFEST.workspace` — diff manifest vs tracked.

Distincion con skills hermanas:
- `audit-pipeline` = meta-auditoria post-pipeline de UN ticket cerrado.
- `audit-git-publication` = listo-para-publicar de un repo.
- `system-health-audit` (esta) = salud periodica de las 3 capas tras cambios.

## Fases del protocolo

### Fase 0 — Baseline critico (bloqueante para saneo)
Si la suite canonica esta ROJA, el saneo EJECUTABLE queda bloqueado. Documentar
sigue permitido. Registrar HEAD auditado, comando exacto, exit code REAL (de
`last-run.json`, nunca de `cmd | tail`), tests fallidos y causa comun. Si hay
critico, abrir `0_CRITICAL_BASELINE.md` y priorizarlo sobre todo lo demas.

### Fase 1 — Scope y topologia
Resolver `repo_motor`, `repo_destino`, verificar `AGENT_PROJECT_ROOT` y
`motor_destination_link.json`. Registrar HEADs git de ambos. Declarar modo
(full / motor-only / auto-degradado).

### Fase 2 — Baseline de salud
ruff, run_pytest_safe (declarar cobertura real; si es allowlist parcial NO vender
verde global), encoding guard, validate, estado git. Exit code real, no de pipe.

### Fase 3 — Auditoria del motor
scripts vivos/deprecados, skills, prompts con drift, docs vs CLI, manifests,
guards, memoria/proceso. Triangular intencion/codigo/operacion.

### Fase 4 — Auditoria del destino
copias indebidas de `scripts/`/`skills/`/`agent_system/`, `.agent/collaboration`,
`.agent/runtime/memory`, `_legacy`, archivos reservados o basura, estado operativo
activo vs historico.

### Fase 5 — Auditoria de integracion
install/sync, controller con `--project-root`, bus/events, memory loader,
publication audit, guard_paths, regeneracion de link en clone limpio.

### Fase 6 — Archive plan
KEEP / ARCHIVE / DELETE con evidencia POR RUTA, riesgo y rollback. NO ejecutar
borrados en la misma pasada. KEEP es diagnostico; solo ARCHIVE/DELETE generan ticket.

### Fase 7 — Tickets
Un ticket por familia, criterio binario, STOP conditions, gates requeridos,
prioridad. Los tickets ejecutables se reflejan en `.agent/collaboration/`, no
dentro de la carpeta de auditoria.

### Fase 8 — Pasada adversarial
Aplicar `audit_agent_output.md`. Clasificar cada claim VERIFICADO / INFERIDO /
NO VERIFICADO. Buscar falso verde, root equivocado, fixture drift, scope creep.
Re-derivar por bytes/codigo lo que el script marco como relevante.

## Exit codes del recolector (referencia del agente)

- `0`: recoleccion OK, sin criticos automaticos detectados.
- `1`: recoleccion OK, criticos automaticos (suite roja, secreto, DECIDE pendiente).
- `2`: error de ejecucion/recoleccion.
- `3`: topologia incompleta/degradada cuando se exige `--mode full`.

## Modos

- `--mode full`: requiere motor + destino.
- `--mode motor-only`: solo motor.
- `--mode auto`: detecta y degrada con aviso.

## Redaccion y publicacion

`raw/` puede filtrar rutas personales (`C:\Users\...`), usuario, entorno y timings.
Versionar solo `*.md`, `findings.json`, `INDEX.md`; dejar `raw/` gitignored por
defecto (o versionar solo `raw/*.txt` sanitizados). Antes de publicar cualquier
artefacto, pasarlo por `classify_publication.py`. `findings.json` debe llevar rutas
RELATIVIZADAS.

**Deuda v1 (explicita):** v0 solo relativiza los roots motor/destino en
`findings.json`. Antes de versionar `raw/`, v1 debe sanitizar tambien
`$USERPROFILE`/`$HOME`, hostname y variables de entorno que `raw/` pueda filtrar
(rutas, usuario, timings). Hasta entonces, `raw/` permanece gitignored.

## guard_paths

El hook `guard_paths` bloquea escrituras cross-repo cuando el cwd es el motor. Para
escribir la auditoria en el destino: ejecutar con cwd en el `repo_destino` o un
allowlist ultra-acotado a `.agent/audits/system_health/**`. NO debilitar el guard.

## Que NO hacer

- No tratar el reporte del recolector como veredicto.
- No vender pytest-safe parcial como verde global.
- No archivar ni borrar en la misma pasada que se audita.
- No mezclar familias (saneo topologico, deprecaciones, encoding, memoria) en un commit.
- No llamar "auditoria completa" a una pasada con suite roja.
- No publicar `raw/` ni la propia carpeta de auditoria sin pasar por classify_publication.
- No debilitar guard_paths para escribir mas comodo.

## Mantenimiento

Actualiza este prompt cuando cambie el contrato del recolector, se anada una
herramienta orquestada nueva, o cambie la estructura de `.agent/audits/`.
La plantilla de referencia v0 son los artefactos de `general_audit_20260613`.
