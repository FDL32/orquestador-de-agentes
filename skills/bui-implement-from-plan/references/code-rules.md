# Reglas de CÃ³digo Python

## Pathlib (SIEMPRE)

**âŒ NUNCA:** `os.path.join()` â†’ **âœ… SIEMPRE:** `Path() / "file"`

```python
from pathlib import Path
path = Path("folder") / "file.txt"
content = Path("file.txt").read_text(encoding="utf-8")
Path("folder").mkdir(parents=True, exist_ok=True)
```

## Type Hints (OBLIGATORIO)

Todas las funciones deben tener type hints:

```python
def load_config(path: Path) -> dict[str, any]:
    """Carga configuraciÃ³n desde archivo."""
    ...

def save_data(data: list[dict], output_path: Path) -> None:
    """Guarda datos en archivo."""
    ...
```

**Tipos comunes:** `str`, `int`, `list[T]`, `dict[K,V]`, `Path`, `any`

## Docstrings

Toda funciÃ³n pÃºblica debe tener docstring:

```python
def validate_email(email: str) -> bool:
    """Valida formato de email.

    Args:
        email: DirecciÃ³n a validar

    Returns:
        True si vÃ¡lido, False si no
    """
    ...
```

## Manejo de Errores

**âŒ NUNCA bare except:**
```python
try:
    process()
except:  # âŒ
    pass
```

**âœ… SIEMPRE especÃ­fico:**
```python
from loguru import logger

try:
    process()
except ValueError as e:
    logger.error(f"Error: {e}")
    raise
except FileNotFoundError:
    logger.warning("Archivo no encontrado")
    return default_value
```

## Logging (NO print)

```python
from loguru import logger
logger.info("Procesando...")
logger.debug(f"Valor: {value}")
logger.warning("Archivo no existe")
logger.error(f"Error: {e}")
```

## Constantes (NO nÃºmeros mÃ¡gicos)

```python
TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

if timeout > TIMEOUT_SECONDS:
    pass
```

## ConfiguraciÃ³n sectorial (NO hardcoding)

Si un valor depende del sector, NO lo escribas en Python:
âŒ `if sector == "religioso": lista = ["casulla", "alba"]`
âœ… `lista = sector_cfg.raw.get("interlinks", {}).get("patterns", {})`

Los YAMLs de sector son el Ãºnico lugar donde viven los datos sectoriales.

## NormalizaciÃ³n de datos â€” punto Ãºnico

Si un dato puede llegar en varios formatos (segÃºn la fuente), normaliza en el punto de SALIDA (el mÃ©todo que lo produce), no en cada punto de ENTRADA (los mÃ©todos que lo consumen):
âŒ Cada consumer hace `data.get("wrapper", {}).get("field") or data.get("field")`
âœ… El productor hace `data = unwrap(data)` antes del return; los consumers hacen `data.get("field")`

## Logging — sin f-strings en mensajes

Con loguru, pasar el valor como argumento en lugar de interpolarlo en el mensaje:

❌ `logger.info(f"Procesando ticket: {ticket_id}")`
✅ `logger.info("Procesando ticket: {}", ticket_id)`

El motivo: si el nivel de log está desactivado, la interpolación con f-string evalúa la expresión igualmente. Pasando el argumento, loguru la evalúa solo si el mensaje se va a emitir.

## Mutable defaults (PROHIBIDO)

❌
```python
def cargar(items: list = [], config: dict = {}):
    ...
```
✅
```python
def cargar(items: list | None = None, config: dict | None = None):
    if items is None:
        items = []
    if config is None:
        config = {}
```

Los valores `[]`, `{}` y `set()` como defaults son compartidos entre todas las llamadas. El fallo es silencioso y aparece lejos del origen.

## assert — solo para invariantes internas

`assert` puede deshabilitarse con `python -O`. No usarlo para validar input externo ni precondiciones de producción.

❌
```python
assert ticket_id, "ticket_id no puede estar vacío"
assert path.exists(), f"No existe: {path}"
```
✅
```python
if not ticket_id:
    raise ValueError("ticket_id no puede estar vacío")
if not path.exists():
    raise FileNotFoundError(f"No existe: {path}")
```

`assert` sí es correcto en tests (`pytest`) y para invariantes que nunca deberían fallar en producción (comprobaciones de lógica interna).

## Truthiness implícita — reglas claras

Usar la verdad implícita de Python en lugar de comparaciones explícitas de longitud o igualdad con `None`:

| Comprobación | ❌ Evitar | ✅ Usar |
|---|---|---|
| Secuencia vacía | `if len(seq) == 0:` | `if not seq:` |
| Secuencia con elementos | `if len(seq) > 0:` | `if seq:` |
| Nulo | `if x == None:` | `if x is None:` |
| No nulo | `if x != None:` | `if x is not None:` |
| Booleano | `if flag == True:` | `if flag:` |

Excepción legítima: `if len(seq) == 0:` es aceptable cuando la intención es distinguir explícitamente entre `None` (ausente) y `[]` (presente pero vacío).

## Anti-patrones que el Manager rechaza como BLOCKER

### AP-01 — Mock drift

El patch apunta a un símbolo diferente del que el código bajo test realmente llama.
El test pasa aunque no esté probando nada.

❌ El código usa `open()` built-in pero el test parchea `pathlib.Path.open`.
✅ Parchea exactamente el símbolo importado en el módulo bajo test: `unittest.mock.patch("bus.review_bridge.open")`.

Regla: traza la cadena de imports hasta el caller real; parchea en ese namespace.

### AP-02 — Floor assertion

El umbral de la aserción numérica ya está satisfecho por el valor base, sin necesidad de la feature que se prueba.

❌ `assert score >= 150` cuando el score de recencia base ya alcanza ~20 000 000.
✅ Calcula primero el baseline sin la feature y elige un umbral estrictamente mayor: `assert score > baseline_without_feature`.

Regla: toda aserción numérica debe fallar si se comenta el código que aporta el valor esperado.

### AP-03 — Zero-logic wrapper

Una función cuyo cuerpo completo es una llamada delegada 1:1 sin lógica propia añade indirección cognitiva sin valor. Inlinea o elimina.

❌
```python
def sync_state(self) -> None:
    self._internal_sync()   # cuerpo completo
```
✅ Los callers llaman directamente a `_internal_sync()`, o la función añade validación, logging o transformación real.

### AP-04 — Adquisición de recurso exclusivo sin guarda de reentrada

Métodos que adquieren un lock (archivo, semáforo, flag de proceso) y son llamados desde múltiples sites del mismo objeto deben protegerse contra la doble adquisición.

❌ Dos call-sites distintos llaman a `bootstrap()` → segundo intento → `FileExistsError` con el propio PID → el supervisor nunca arranca.
✅ Añade un flag de instancia antes de la syscall:

```python
def _acquire_lock(self) -> bool:
    if self._lock_held:          # guarda de reentrada
        return True
    # ... O_CREAT | O_EXCL ...
    self._lock_held = True
    return True
```

### AP-05 — Drift del contrato de retorno (None → bool)

Cambiar el tipo de retorno de una función (p.ej. de `None` implícito a `bool`) sin actualizar todos los callers introduce bugs silenciosos cuando el caller usa `if not result:`.

❌
```python
# Antes: bootstrap() retornaba None implícito
if not self.bootstrap():   # None es falsy → siempre ejecutaba el bloque
    return
# Después de cambiar a bool, None de un mock también es falsy → falso positivo
```
✅ Usa comparación explícita en todos los callers:
```python
if self.bootstrap() is False:
    return
```

Regla: cuando cambies un tipo de retorno, busca todos los callers con `grep` y actualiza las guardas.

### AP-06 — Validador declarado sin evidencia en el log

Si `work_plan.md` declara un validador explícito (p.ej. `python skills/validate_all.py`), el `execution_log.md` debe contener:
1. El comando exacto tal como se ejecutó.
2. El resultado literal (stdout/stderr relevante).
3. Un indicador numérico verificable (0 errores, 0 skills inválidas, etc.).

❌ El log dice "validación completada" sin mostrar salida ni número.
✅ El log incluye:
```
$ python skills/validate_all.py
All 12 skills valid. 0 errors.
```

El Manager rechaza cualquier ticket donde el validador declarado no aparezca en el log con evidencia explícita.

### AP-07 — Clasificación errónea de scaffolding estructural como `code`

Un ticket cuyo único entregable son directorios vacíos, `.gitkeep`, archivos de configuración estáticos o documentación es de tipo `documentation`, no `code`.

❌ `deliverable_type: code` para un WP que solo crea `references/.gitkeep` en varias carpetas.
✅ `deliverable_type: documentation` — no se invocan gates de ruff ni pytest sobre entregables que no son Python.

Regla: si no hay ningún archivo `.py` nuevo o modificado entre los entregables declarados, el tipo no es `code`.

### AP-09 — Protocol key assumption (implementación contra contrato asumido)

Cuando implementes un handler que lee un payload externo (hook, webhook, IPC), verifica el contrato real del protocolo antes de escribir cualquier código. No uses nombres de clave supuestos.

❌
```python
# Asumido — nunca verificado contra la spec real
tool_calls = data.get("tool_calls", [])
shell_command = data.get("shell_command", "")
```
✅
```python
# Claude Code PreToolUse real: {"tool_name": "...", "tool_input": {...}}
tool_input = data.get("tool_input", {})
command = tool_input.get("command", "")
```

Regla: antes de leer cualquier clave de un payload externo, localiza la documentación o spec del protocolo y verifica el nombre exacto. Si el handler siempre sale con exit(0), probablemente está leyendo la clave equivocada.

### AP-10 — Test surrogate (test que prueba un sustituto, no el código real)

Los tests de integración deben invocar el módulo o script real, no un sustituto sintético creado en tmp_path que imita el comportamiento esperado.

❌
```python
# Crea un script falso que "simula" guard_paths y lo testea
hook_script = tmp_path / "test_hook.py"
hook_script.write_text("... lógica imitada ...")
result = subprocess.run([sys.executable, str(hook_script)], ...)
```
✅
```python
# Invoca el script real con el payload en formato correcto
HOOK_SCRIPT = Path(__file__).parent.parent / ".agent" / "hooks" / "guard_paths.py"
result = subprocess.run([sys.executable, str(HOOK_SCRIPT)], input=json.dumps(payload), ...)
```

Regla: si el test no importa ni invoca el módulo real bajo test, no es un test de integración — es un test del sustituto. Busca la ruta al artefacto real y úsala directamente.

### AP-11 — Security gate fail-open on config error

Cualquier componente que actúe como guarda de seguridad debe fallar cerrado (block) ante configuración inválida, perfil desconocido o ausencia de datos esperados. Nunca hacer fallback silencioso a un modo permisivo.

❌
```python
# Fallback silencioso a "standard" aunque el perfil no exista
profile_config = profiles.get(profile_name, profiles.get("standard", {}))
```
✅
```python
# Fail-closed: si el perfil declarado no existe, bloquear y reportar
profile_config = profiles.get(profile_name)
if not isinstance(profile_config, dict):
    print(f"guard: perfil '{profile_name}' no encontrado — config invalida", file=sys.stderr)
    sys.exit(2)
```

Regla: en gates de seguridad, el camino de error es siempre block, no allow. La degradación silenciosa es más peligrosa que un bloqueo explicable.

### AP-12 — Review packet incomplete (untracked deliverables invisible to diff)

Cuando el ticket crea archivos nuevos no rastreados o entregables que no aparecen en `git diff`, el review packet debe incluirlos explicitamente junto con el diff rastreado.

❌
```python
# El packet se construye solo con git diff HEAD y omite los ficheros nuevos.
review_diff = git_diff_head_only()
```
✅
```python
# Incluye tracked + untracked deliverables antes de pedir review.
review_diff = build_review_packet(include_untracked=True)
```

Regla: si el ticket entrega archivos nuevos, el packet de review debe enumerarlos y adjuntarlos de forma explicita. Un diff sin los untracked no representa el alcance real.

### AP-13 — Supervisor process serves stale code after hot-patch

El proceso supervisor carga sus módulos al arrancar. Si se despliega un fix en disco mientras el proceso sigue corriendo, el proceso ejecuta el código anterior indefinidamente.

❌
```bash
# Se corrige bus/supervisor.py. El proceso supervisor en background ignora el cambio.
# BUILDER_RELAUNCH_ATTEMPTED nunca aparece en el bus tras REVIEW_DECISION -> changes.
```
✅
```bash
# Después de cualquier cambio en bus/supervisor.py: verificar que no hay supervisor_lock.txt
# y reiniciar el proceso antes de asumir que el fix está activo.
Test-Path .agent/runtime/supervisor_lock.txt  # debe devolver False antes de relanzar
```

Regla: cualquier ticket que toque `bus/supervisor.py` debe incluir en los criterios de aceptación que el proceso supervisor se reinicia y que el nuevo comportamiento es observable en el bus (p.ej. `BUILDER_RELAUNCH_ATTEMPTED` con el `outcome` esperado). Un test que pase no es evidencia suficiente si el proceso en memoria sigue siendo el antiguo.

### AP-14 — Closeout prompt con nombres de parámetros dispara alucinación de CLI

Cuando un prompt de cierre de agente enumera los parámetros de una función interna, el agente en sesión nueva (sin historial de conversación) construye un flag CLI inventado combinando esos nombres en lugar de usar el comando canónico.

❌
```
# Prompt que dispara la alucinación — menciona los tres parámetros de _emit_builder_exit():
"Emite BUILDER_EXIT en el bus con ticket_id, exit_reason y completion_summary antes de cerrar."
# El agente fabrica: --emit-exit builder --ticket-id ... --exit-reason ... --completion-summary ...
```
✅
```
# Prompt que deja un único camino de acción:
"Ejecuta python .agent/agent_controller.py --mark-ready --json --force al final.
Este comando emite automáticamente BUILDER_EXIT. No uses ningún otro comando para cerrar."
```

Regla: en instrucciones de cierre de agente, dar únicamente el comando canónico completo. No mencionar nombres de parámetros internos ni efectos secundarios que el agente pueda intentar producir manualmente. Aplica a cualquier archivo leído por un agente en sesión nueva: `.opencode/agents/builder.md`, prompts del launcher, y cualquier regla de cierre en templates.

### AP-08 — Test coverage drift (funciones nuevas sin tests directos)

Ejecutar el suite existente y ver que pasa no es evidencia de cobertura si las funciones nuevas introducidas en el diff no aparecen en ningún test.

❌ El Builder añade `_parse_inventory()`, `_load_inventory()` y `_render_inventory()` y declara "pytest pasa" — pero ningún test llama directamente a esas funciones.
✅ Cada función nueva introducida en el diff tiene al menos un test que la invoca directamente, incluyendo el path de fallback si aplica.

Regla: antes de declarar READY_FOR_REVIEW, verifica que cada `def` nuevo o `method` nuevo aparezca al menos una vez como llamada directa en `test_*.py`. Si no aparece, el test no existe.

## Delivery hygiene - scope safety y artefactos generados

Si durante la implementacion aparece un archivo fuera de `Files Likely Touched`, **NO** lo revivas ni lo borres con `git checkout`, `git reset` o `git revert`.

**NO:** limpiar un archivo no declarado para "dejar el arbol limpio".
**SI:** anotar la discrepancia de scope en `execution_log.md` y pedir al Manager una actualizacion explicita del plan.

Los artefactos generados o de runtime deben quedar excluidos de hooks mutadores. Si un hook los toca en `pre-push`, el Builder debe parar y reportarlo, no aceptar una reescritura silenciosa.

**NO:** dejar que `end-of-file-fixer` o `ruff format` muten `.agent/context/project-map.json` o `events.jsonl` durante `pre-push`.
**SI:** verificar esos archivos de forma no mutadora y mantener el scope de entrega congelado antes del handoff.

## Checkpoints semanticos - M3 requerido antes de handoff

El Builder debe crear el checkpoint M3 (`checkpoint/review-<ticket>`) de forma explicita antes de ejecutar `--mark-ready`. El guard de handoff bloquea si M3 no existe.

**Comando:**
```bash
python scripts/create_checkpoint.py --milestone M3 --ticket-id WP-2026-XXX
```

**Checkpoints disponibles:**
- `M0`: `checkpoint/base-<ticket>` - Inicio del ticket
- `M1`: `checkpoint/design-<ticket>` - Diseño aprobado
- `M2`: `checkpoint/implementation-<ticket>` - Implementacion completa
- `M3`: `checkpoint/review-<ticket>` - Listo para review (**REQUERIDO** antes de `--mark-ready`)
- `M4`: `checkpoint/closed-<ticket>` - Ticket cerrado

**NO:** intentar auto-crear M3 desde `--mark-ready`; el checkpoint debe ser una ancla real creada de forma explicita.
**SI:** crear M3 como paso manual verificable antes del handoff; el guard validara su existencia.

El script emite `BUILDER_MILESTONE` al bus con `{milestone, tag, sha}` para trazabilidad. Si la tag ya existe, hace skip con aviso y no falla.
