# Prompt: Auditoría del Plan del Builder

> **Modo:** Solo lectura. No implantes nada. No reescribas archivos.
>
> Identifica problemas y propón correcciones exactas.

---

## Alcance obligatorio

Lee estos archivos antes de evaluar nada.

**Determina el ID del ticket activo** desde `work_plan.md` o `STATE.md` — no lo asumas manualmente. Si hay varios drafts, trabaja solo con el que coincida con el ID activo.

### Estado del sistema

- `.agent/collaboration/work_plan.md`
- `.agent/collaboration/PLAN_WT-<ID>.md`
- `.agent/collaboration/AUDIT_WT-<ID>.md`
- `.agent/collaboration/TURN.md`
- `.agent/collaboration/execution_log.md`
- `.agent/collaboration/STATE.md`
- `.agent/collaboration/backlog.md`

### Memoria y protocolo del sistema

- `.agent/runtime/memory/MEMORY.md`
- `.agent/runtime/memory/closeout_lessons.md` (si existe)
- Observations relevantes en `observations.jsonl` que afecten al protocolo de este ticket

### Código fuente

Lee el código fuente real de cualquier función, módulo o flag nombrado en el PLAN (no asumas que el nombre en el plan es correcto — verifícalo con `Read` o `Grep`).

---

## Checklist de madurez

Recorre ítem por ítem.

1. **Formato exacto de strings críticos**
   ¿El plan especifica literales exactos donde el motor los valida con regex? ¿O usa variantes aproximadas que fallarán silenciosamente?

2. **Destructividad explícita**
   ¿Toda operación de escritura sobre archivos que el usuario puede haber editado tiene un guard documentado (`if not exists`, backup, etc.)?

3. **Criterio de cierre binario**
   ¿El criterio de aceptación es un comando ejecutable que devuelve 0 o un test que pasa/falla? ¿O es subjetivo ("verificar que funcione")?

4. **Tests para invariantes críticos**
   ¿Cada guard o condición de seguridad tiene un test que lo cubre? "Cubierto por `--dry-run`" no cuenta.

5. **Integración con flags existentes**
   ¿Hay algún placeholder manual que ya podría rellenarse con un flag CLI existente?

6. **Existencia de tests nombrados**
   Para cada test en "Tests Esperados": ¿ya existe en la suite (no-regresión) o es un deliverable nuevo? Marca cuál es cuál. Tests listados como nuevos que ya existen producen duplicados silenciosos.

7. **Snippets como especificaciones ejecutables**
   ¿Cada regex, import path, literal string o snippet en el plan es sintácticamente correcto? Verifica en REPL o fuente real — un escape incorrecto en el plan se convierte en un test roto sin traza.

8. **Files Likely Touched — paths relativos al motor**
   ¿Algún path empieza con `orquestador_de_agentes/`? Ese prefijo produce intersección vacía con `git diff --name-only` y bloquea `--mark-ready`. Los paths deben ser relativos al root del repo git del motor (`bus/redact.py`, no `orquestador_de_agentes/bus/redact.py`).

9. **Dual-contract sync (`work_plan.md` ↔ `PLAN_WT-*`)**
   ¿Toda corrección está aplicada en ambos archivos? El scope gate lee `work_plan.md`; el Builder lee `PLAN_WT-*`. Una corrección en solo uno de los dos pasa inadvertida y requiere rondas adicionales.

10. **Contrato por `deliverable_type`**
   El plan debe estar organizado segun el tipo real de entrega. Para
   `documentation` / `research` / `analysis`, no exijas commit de codigo,
   pytest ni ruff salvo que el plan toque codigo. Exige artefactos declarados,
   existencia en disco y una linea final en `execution_log.md` que combine
   artefacto + gate (`validate`, `passed` o `success`) sin `pendiente`.
   Para `code` / `mixed`, verifica diff/commit productivo y gates de codigo.
   Si el plan tiene subsecciones `Builder`, `Read/inspect only` o
   `Manager-only`, confirma que solo `Builder` cuenta como entregable.

---

## Verificaciones adicionales

### Funciones, rutas y APIs

Para cada función nombrada en el PLAN, lee el archivo fuente real y confirma que existe con ese nombre y firma exactos. No des por bueno el nombre en el plan.

### Corrección parcial en artefacto equivocado

Si una corrección aparece aplicada en `work_plan.md` pero no en `PLAN_WT-*` (o viceversa), señálalo como hallazgo explícito con el archivo donde falta replicarla; no lo trates como inconsistencia menor. Este patrón requirió rondas adicionales en tickets previos.

### Packaging y handoff listos para review

Esta sección evalúa si el paquete está listo para review aunque el código sea correcto.

- Si el ticket está en fase pre-review o `mark-ready`, verifica si existe commit visible del ticket y si el diff del packet sería revisable por el Manager.
- ¿`execution_log.md` registra evidencia explícita de pytest / ruff / gates requeridos?
- ¿`TURN.md` refleja el ciclo real del ticket (arranque normal vs CHANGES)?

> **Packaging no sustituible por tests en verde:** No des por suficiente que pytest o ruff pasen si:
> - no hay commit visible del ticket
> - el review packet no tendría diff verificable
> - `execution_log.md` no deja evidencia suficiente de los gates
>
> En ese caso, clasifica el problema como `PACKAGING/HANDOFF`, no como calidad de código.

### TURN.md autosuficiente

No asumas que el Builder podrá leer `manager_feedback_*` ni otras superficies fuera del motor durante un ciclo CHANGES. Todo blocker accionable debe quedar materializado en `TURN.md`. Si `TURN.md` solo dice "Manager requested changes" sin blockers concretos, el Builder queda ciego y repetirá el error.

### Quality gates ejecutables

- ¿Los comandos de calidad en el PLAN son ejecutables desde el repo correcto?
- ¿Las rutas de ruff apuntan a archivos que realmente existen y serán tocados?
- ¿El `--validate` usa el `--project-root` correcto para Modelo B?

- ¿Los gates corresponden al `deliverable_type` declarado? Un ticket
  documental debe cerrar por artefacto verificable + evidencia de validate, no
  por pytest/ruff fabricados. Un ticket de codigo no debe escapar sin diff,
  commit y tests aplicables.

### Planes documentales / research / analysis

Si `deliverable_type` es `documentation`, `research` o `analysis`, verifica:

- `Files Likely Touched` separa archivos que Builder crea/modifica de fuentes
  `Read/inspect only` y gates `Manager-only`.
- Cada artefacto Builder tiene ruta concreta y criterio binario de existencia.
- El plan indica que Builder debe registrar una linea final tipo:
  `Reporte .agent/runtime/compare/<archivo>.md creado. Validate: exit code 0, 0 errors, 0 warnings.`
- Las fuentes leidas para contexto no aparecen como entregables requeridos.
- El Manager conserva un gate de revision de contenido, aunque no haya tests de
  codigo.

### PowerShell bajo Set-StrictMode

Si el PLAN toca funciones PowerShell que accedan a objetos de `ConvertFrom-Json`
o `PSCustomObject`, no basta con parseo sintáctico del `.ps1`:
verifica que la función tiene un test funcional bajo `Set-StrictMode -Version Latest`
con un fixture JSON mínimo real (no un mock). El acceso `$obj.prop` y
`.PSObject.Properties.Name` pueden fallar en runtime aunque el parse sea OK.

### Consistencia entre archivos

| Par de archivos | Qué debe coincidir |
|---|---|
| `work_plan.md` ↔ `PLAN_WT-*` | Files Likely Touched, TPs, fases y scope |
| `PLAN_WT-*` ↔ `AUDIT_WT-*` | Criterios de aceptación expresados de forma verificable |
| `execution_log.md` y `TURN.md` | No deben contradecir el estado operativo que exige el AUDIT |

Comprueba la consistencia especialmente si el ticket fue relanzado varias veces.

### Drift de bus y ticket zombie

Comprueba que el estado canónico (`STATE.md`, `execution_log.md`, `TURN.md`) esté alineado con el bus proyectado del ticket activo. Detecta:

- Estado en `execution_log` que no concuerda con la fase del bus
- `TURN.md` con turno o instrucción del ciclo anterior
- Ticket marcado como activo en `work_plan.md` pero con estado cerrado o en conflicto en `STATE.md` o `backlog.md`

Un drift de bus hará fallar el flujo aunque el contrato del ticket esté bien redactado.

---

## Modo de revisión

Revisión escéptica y concreta. Busca:

- Ambigüedades que permitan al Builder fabricar una implementación "verde" pero incorrecta
- Supuestos implícitos no escritos
- Campos vagos o no verificables
- Pasos que bloquearán el scope gate o el `--mark-ready`
- Errores de packaging o handoff

Si un problema ya ocurrió en tickets anteriores y hay una lección en memoria aplicable, cítala y no dupliques la crítica — solo confirma que aplica aquí. Si no puedes verificar algo localmente, dilo explícitamente.

---

## Formato de salida obligatorio

### 1. Hallazgos

Ordenados por severidad: `CRÍTICO` / `ALTO` / `MEDIO` / `BAJO`

Cada hallazgo incluye:

- Archivo y sección/línea si es posible
- Por qué es un problema
- Cómo fallaría: Builder / Manager / scope gate / `--mark-ready` / packaging
- Corrección exacta propuesta (string literal si aplica)
- Si es una corrección parcial, indica explícitamente en qué archivo falta replicarla
- **Etiqueta de evidencia** (obligatoria):
  - `VERIFICADO EN CÓDIGO <archivo:símbolo>` — comprobado en el archivo fuente real; cita el archivo exacto y el símbolo (función, clase o constante). Ejemplo: `VERIFICADO EN CÓDIGO bus/review_bridge.py:_git_diff_stat`
  - `VERIFICADO EN DOCUMENTACIÓN` — comprobado en artefactos del ticket
  - `INFERENCIA RAZONABLE` — deducido sin verificación directa en fuente

> No presentes una inferencia como hecho confirmado.

### 2. Huecos no bloqueantes pero rentables

Mejoras que reducen riesgo sin ser blockers.

### 3. Veredicto final

Uno de:

- **✅ LISTO PARA BUILDER**
- **⚠️ LISTO CON AJUSTES MENORES**
- **🛑 NO LANZAR TODAVÍA** _(razón principal)_

Independientemente del veredicto, cierra con dos bloques:

**Deben corregirse antes de lanzar Builder:**
- [lista exacta de hallazgos bloqueantes con archivo y corrección]

**Pueden diferirse a follow-up:**
- [lista de hallazgos no bloqueantes con razón de por qué no bloquean]
