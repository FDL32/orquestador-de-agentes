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
