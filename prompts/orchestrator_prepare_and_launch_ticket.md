# Prompt: Preparar Ticket y Prompt de Arranque (atajo por chat)

> **Que es:** un ENRUTADOR corto para pedir por chat, en una sola instruccion, la
> secuencia completa "preparar contrato + work_plan -> auditar -> redactar prompt
> de arranque del Builder -> bucle adversarial -> cierre" sobre UN ticket puntual,
> sin recorrer a mano cada prompt canonico.
>
> **Que NO es:** no redefine criterios, gates, checklists ni maquina de estados.
> Todo eso vive en los prompts citados abajo (`source_of_truth`). Este archivo
> solo ENRUTA, en el orden correcto, con el comando exacto de cada paso. Si un
> paso de aqui diverge de su prompt fuente, gana el prompt fuente y este archivo
> tiene un bug (regla WOT-2026-014r, "skill apunta, prompt gobierna").
>
> **source_of_truth de la secuencia completa:** `prompts/orchestrator_pipeline.md`
> seccion "1.b Herramientas por fase" (tabla Bootstrap/Plan/Implementacion/
> Review/Cierre). Este prompt es un ATAJO de esa tabla para chat directo sobre
> un ticket ya triado, no un pipeline alternativo.
>
> **Origen:** instruccion de usuario dada en una sesion sobre `Amazon_Stock`
> (2026-09), reconstruida aqui como plantilla reutilizable porque no existia
> como artefacto versionado.
>
> **Sustituye a procesos ad-hoc:** este prompt reemplaza cualquier PASO 0-6
> inline o proceso similar que se haya usado en sesiones anteriores. Si un
> usuario pide "preparar ticket X" sin nombrar este prompt, enrútalo aquí.

---

## Cuando usar esto

- Ya tienes un ticket identificado (contrato en borrador o solo una idea clara)
  y quieres pasar de "idea" a "Builder lanzado" en una sola pasada por chat.
- **NO** sustituye a `contract_formation_pipeline.md` si el ticket todavia
  necesita descubrimiento/triage amplio (varios candidatos, prioridad dudosa,
  backlog sin cribar). Para eso, usa `prompts/backlog_triage.md` primero.

## Paso 0 — Verifica el cierre del ticket anterior

**Antes de tocar anything**, verifica que el ticket anterior cerró en las
3 superficies. Un ticket archivado con proyecciones vivas bloquea el bootstrap
y el Builder hereda estado stale (medido: WOT-2026-072c arrancó sobre
WOT-2026-072b porque este paso se omitió).

```powershell
# 1. Backlog: el ticket anterior debe estar en done/ (no en queued/ o in_flight/)
python <MOTOR_ROOT>/scripts/check_backlog_contract.py --project-root <DESTINO>

# 2. Proyecciones: STATE.md y TURN.md no deben apuntar al ticket anterior
#    (lee manualmente y verifica el ID del ticket activo)

# 3. Bus: si hay duda, verifica que el bus no tiene eventos stale
#    (python <MOTOR_ROOT>/.agent/agent_controller.py --validate --json --project-root <DESTINO>)
```

Si el ticket anterior NO cerró: STOP. Resuelve el cierre antes de continuar.
No fuerces un bootstrap sobre un workspace sucio.

## Paso 1 — Preparar el ticket completo

Objetivo: `ticket_contract` congelable + `work_plan.md` + turno regenerado.

1. Redacta o completa el `ticket_contract` en `.agent/planning/ticket_contracts.md`
   segun `prompts/contract_formation_pipeline.md` (campos obligatorios seccion 3-4).
2. Audita el contrato ANTES de congelarlo con
   **`prompts/audit_cf_ticket_contract.md`** (lee el prompt entero: regla M4 /
   "prompt citado => leelo entero antes de redactar contra el", AGENTS.md).
   Corrige hallazgos BLOCKER/MAJOR. Pasa `scripts/validate_contract_formation.py`
   con rc=0.
3. Congela (`status: frozen`) solo si el audit anterior no dejo BLOCKER vivo.
4. Escribe `work_plan.md` a partir del contrato congelado.
5. Audita el `work_plan.md` ya escrito con **`prompts/audit_ticket_contract.md`**
   (es el HERMANO del paso 2, NO el mismo prompt — audita madurez operativa,
   no intencion; ver cabecera de `audit_cf_ticket_contract.md:8-20`).
6. Regenera turno hacia Builder:

   ```powershell
   python <MOTOR_ROOT>/.agent/agent_controller.py --reset-turn --force --project-root .
   python <MOTOR_ROOT>/.agent/agent_controller.py --bootstrap-ticket --json --project-root .
   python <MOTOR_ROOT>/.agent/agent_controller.py --validate --json --project-root .
   ```

   **Verificacion post-bootstrap (OBLIGATORIO):** `--bootstrap-ticket` devuelve
   exit 0 sin materializar siempre las proyecciones. Verifica EXPLICITAMENTE:
   - `STATE.md` contiene el nuevo ticket_id (no el anterior)
   - `TURN.md` contiene `ROL=BUILDER` y el nuevo ticket_id
   - `validate --json` devuelve 0 errores

   Si `STATE.md`/`TURN.md` no cambiaron: repite `--bootstrap-ticket` con
   `--force`. Si persiste, STOP — hay un problema de resolucion de root.

   **Si hay otra sesion en vuelo sobre el mismo `repo_destino`:** `--bootstrap-ticket`
   y `--reset-turn` tocan estado compartido (`TURN.md`, `work_plan.md`,
   `execution_log.md`). Antes de ejecutar, verifica que el ticket activo de la
   otra sesion NO es este mismo ticket ni depende del turno que vas a resetear
   (lee `TURN.md` y `execution_log.md` actuales). Si hay colision, STOP y
   coordina antes de tocar el bus — no fuerces el reset.

## Paso 1.7 — Pre-flight del Builder (obligatorio para code/mixed)

**Antes de lanzar el Builder**, verifica que el entorno puede soportar el ciclo
completo. Esto previene problemas como ruff claim falso, dirty tree fantasma,
M3 checkpoint failure y suite timeout.

```powershell
# 1. Ruff funciona en los archivos que el ticket va a tocar
uv run ruff check <files_likely_touched_python>
# Si falla: el entorno no tiene ruff o los archivos tienen errores preexistentes

# 2. Pre-handoff guard no reporta archivos fantasma
python <MOTOR_ROOT>/scripts/pre_handoff_guard.py --project-root <DESTINO> --ticket-id <TICKET_ID> --json
# Verifica que dirty_files NO contiene archivos inexistentes

# 3. M3 checkpoint es creatable (verifica permisos)
python -c "from pathlib import Path; Path('<DESTINO>/.agent/collaboration').mkdir(parents=True, exist_ok=True); print('OK')"
# Si falla: problema de permisos que bloqueara --mark-ready

# 4. Suite canonica estimada (para code/mixed)
# Si el entorno tiene timeout corto (<5min), documenta que la suite puede no completar
python -c "import time; start=time.time(); print(f'Timestamp: {start}')"
```

Si algun check falla, STOP y resuelve antes de lanzar el Builder. Un Builder
que arranca con un entorno roto produce reports falsos (medido: WOT-2026-072c).

## Paso 2 — Redactar el prompt de arranque del Builder

Con `work_plan.md` ya auditado y `--bootstrap-ticket` verde, redacta el prompt
de lanzamiento siguiendo **`prompts/orchestrator_launch_builder.md`** completo
(578+ lineas — leelo entero, no muestrees por grep; regla M4). Sustituye
`{{TICKET_ID}}` y deja el prompt listo para pegar en una sesion Builder nueva.

## Paso 3 — Bucle adversarial sobre el ticket y el prompt

Antes de lanzar el Builder, corre el bucle de lentes sobre el bundle
(ticket_contract + work_plan + prompt de arranque), siguiendo el protocolo de
ensemble ya establecido en el proyecto (nonce -> fan-out -> `check_loop_execution`
-> sintesis). No declares el ticket listo para Builder sin esta pasada si el
ticket es `code`/`mixed` de blast radius no trivial.

## Paso 3.5 — Verificación post-build del Builder (obligatorio para code/mixed)

**Después de que el Builder entrega su reporte**, verifica INDEPENDIENTEMENTE
sus claims antes de aceptar el cierre. Un Builder que miente sobre gates produce
falsos verdes (medido: WOT-2026-072c — ruff claim falso, dirty tree fantasma).

```powershell
# 1. Verificar ruff sobre archivos Python del diff
git show --name-only <commit_builder> | Select-String "\.py$"
# Luego: uv run ruff check <archivos_py_encontrados>

# 2. Verificar que los tests declarados existen y pasan
python -m pytest <tests_declarados_por_builder> -x -q

# 3. Verificar dirty tree: ¿los archivos marcados como dirty existen?
git status --short
# Si un archivo reportado como dirty no existe → bug en pre-handoff guard

# 4. Verificar validate
python <MOTOR_ROOT>/.agent/agent_controller.py --validate --json --project-root <DESTINO>
```

Si algun claim del Builder es FALSO, emite `CHANGES` con el claim exacto y la
evidencia de la verificación independiente. No aceptes claims sin verificar.

**Regla:** "no aplica" NO es un veredicto válido para gates que el ticket
debe ejecutar. El Builder debe declarar EXPLÍCITAMENTE "ejecuté X → resultado Y"
o "no ejecuté X → razón Z". Un "no aplica" sin evidencia es un claim no verificado.

## Paso 4 — Commit, push y sync

Solo tras el bucle sin BLOCKER vivo:

1. `git add` **acotado** a los artefactos de este ticket (contrato, work_plan,
   prompt de arranque, reports del bucle) — nunca `git add -A` / `git add .`
   (M2, `orchestrator_launch_builder.md:196`).
2. Commit con el ID de ticket completo con prefijo (regla de nomenclatura de
   AGENTS.md).
3. Push.
4. Sync solo si el ticket lo requiere explicitamente (p.ej. `install_agent_system.py --sync`
   sobre un destino) — no lo asumas por defecto.

**Con otra sesion en vuelo:** haz `git status`/`git log` justo antes del commit
para confirmar que el HEAD no se movio por la otra sesion mientras preparabas
esto; si se movio, reintegra (`git pull --rebase` o equivalente) antes de push,
nunca `--force`.

## Salida esperada

Al terminar, reporta en una sola respuesta: ticket ID, ruta del `ticket_contract`,
ruta del `work_plan.md`, ruta del prompt de arranque redactado, resultado del
bucle (veredicto + nonce), y el sha del commit (si se hizo commit).
