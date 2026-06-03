# Audit Tools - Configuration & Interpretation Guide

Descripción de herramientas, umbrales y cómo interpretar resultados.

## Herramientas Configuradas

### 1. Vulture (Análisis Estático de Símbolos)

**Propósito:** Encontrar código, variables y parámetros no utilizados.

**Comando:**
```bash
vulture . --exclude venv,.venv --min-confidence 80 --sort-by-size
```

**Configuración:**
- `--min-confidence 80`: Ignora patrones ambiguos (parámetros opcionales, etc.)
- `--sort-by-size`: Ordena por líneas de código (más relevante primero)

**Interpretación:**
```
src/foo.py:15: unused variable 'temp'
src/bar.py:42: unused function 'helper'
```

| Finding | Significado | Confiabilidad |
|---------|-------------|---------------|
| unused variable | Nunca leída tras asignación | *** (muy confiable) |
| unused function | Nunca llamada en el código | *** |
| unused parameter | Argumento nunca usado | ** (puede ser intencional) |

**Falsos positivos comunes:**
- Parámetros en callbacks (handlers)
- Variables usadas solo en strings (f-strings)
- Atributos dinámicos (setattr/getattr)

---

### 2. Deadcode (Análisis de Flujo de Control)

**Propósito:** Código alcanzable pero nunca ejecutado en práctica.

**Librería Python:**
```python
from deadcode.actions import parse_arguments, find_python_filenames, find_unused_names
```

**Configuración:**
```python
exclude = 'venv,.venv,__pycache__,.git,agent_system,.agent'
```

**Output:**
```
src/foo.py:23: unused_func (function)
  Scoped: module.unused_func
  Type: function
  Uses: 0
```

| Campo | Uso |
|-------|-----|
| filename | Archivo que contiene el símbolo |
| type_ | Tipo (function, class, method, variable) |
| name_line | Línea donde se define |
| number_of_uses | Cantidad de referencias encontradas (0=unused) |

**Diferencia con vulture:**
- Deadcode: Análisis de flujo más profundo
- Vulture: Búsqueda textual de referencias

---

### 3. Ruff (Deuda Técnica)

**Propósito:** Detectar complejidad, código antiguo y oportunidades de simplificación.

**Comando:**
```bash
ruff check . --exclude venv,.venv
```

**Reglas Configuradas:**

| Regla | Código | Descripción |
|-------|--------|-------------|
| McCabe Complexity | C90 | Función con ciclos/condiciones >10 |
| Dead Code Elimination | ERA | `try/except` siempre falla |
| Simplifications | SIM | Código que puede simplificarse |

**Ejemplos:**
```
src/complex.py:10: C901 function is too complex (11 > 10)
src/old.py:5: ERA001 unnecessary try block
src/simple.py:20: SIM105 use set(x) instead of `if x in ...`
```

**Acciones:**
- **C90X**: Refactorizar función grande en funciones pequeñas
- **ERA**: Eliminar try/except innecesario
- **SIM**: Aplicar sugerencia o ignorar si contexto es claro

---

### 4. Git Log (Antigüedad)

**Propósito:** Medir abandono midiendo frecuencia de commits.

**Comando:**
```bash
git log --oneline --follow -- src/foo.py | wc -l
```

**Interpretación:**
- **commits = 0**: Archivo nuevo, nunca commiteado
- **commits < 5**: Código antiguo, poco mantenimiento
- **commits >= 5**: Código histórico, posiblemente importante

**Categorización:**
```
DEAD: commits = 0  + sin referencias
ABANDONED: 0 < commits < 5  + sin referencias
LEGACY: commits >= 5  + sin referencias
```

---

## Decision Matrix

| Hallazgo | Tool | Commits | Usos | Acción Recomendada |
|----------|------|---------|------|-------------------|
| Variable `x` | vulture | 0 | 0 | DELETE |
| Function `f` | deadcode | 2 | 0 | REVIEW + DELETE |
| Helper `h` | deadcode | 8 | 0 | REVIEW CON EQUIPO |
| C901 (complexity) | ruff | N/A | N/A | REFACTOR |
| SIM (simplify) | ruff | N/A | N/A | APPLY o IGNORE |

---

## Umbrales Globales

```
Minimum Confidence (vulture):   80%
McCabe Threshold (ruff C90):    10 (función compleja si >10)
Deadcode Exclude:               venv,.venv,__pycache__,.git,agent_system,.agent
Legacy Threshold (git commits): 5+ = posible API interna
```

---

**Última actualización:** 2026-04-28
