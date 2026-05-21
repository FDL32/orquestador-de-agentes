# Audit Tools â€” Configuration & Interpretation Guide

DescripciÃ³n de herramientas, umbrales y cÃ³mo interpretar resultados.

## Herramientas Configuradas

### 1. Vulture (AnÃ¡lisis EstÃ¡tico de SÃ­mbolos)

**PropÃ³sito:** Encontrar cÃ³digo, variables y parÃ¡metros no utilizados.

**Comando:**
```bash
vulture . --exclude venv,.venv --min-confidence 80 --sort-by-size
```

**ConfiguraciÃ³n:**
- `--min-confidence 80`: Ignora patrones ambiguos (parÃ¡metros opcionales, etc.)
- `--sort-by-size`: Ordena por lÃ­neas de cÃ³digo (mÃ¡s relevante primero)

**InterpretaciÃ³n:**
```
src/foo.py:15: unused variable 'temp'
src/bar.py:42: unused function 'helper'
```

| Finding | Significado | Confiabilidad |
|---------|-------------|---------------|
| unused variable | Nunca leÃ­da tras asignaciÃ³n | â­â­â­ (muy confiable) |
| unused function | Nunca llamada en el cÃ³digo | â­â­â­ |
| unused parameter | Argumento nunca usado | â­â­ (puede ser intencional) |

**Falsos positivos comunes:**
- ParÃ¡metros en callbacks (handlers)
- Variables usadas solo en strings (f-strings)
- Atributos dinÃ¡micos (setattr/getattr)

---

### 2. Deadcode (AnÃ¡lisis de Flujo de Control)

**PropÃ³sito:** CÃ³digo alcanzable pero nunca ejecutado en prÃ¡ctica.

**LibrerÃ­a Python:**
```python
from deadcode.actions import parse_arguments, find_python_filenames, find_unused_names
```

**ConfiguraciÃ³n:**
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
| filename | Archivo que contiene el sÃ­mbolo |
| type_ | Tipo (function, class, method, variable) |
| name_line | LÃ­nea donde se define |
| number_of_uses | Cantidad de referencias encontradas (0=unused) |

**Diferencia con vulture:**
- Deadcode: AnÃ¡lisis de flujo mÃ¡s profundo
- Vulture: BÃºsqueda textual de referencias

---

### 3. Ruff (Deuda TÃ©cnica)

**PropÃ³sito:** Detectar complejidad, cÃ³digo antiguo y oportunidades de simplificaciÃ³n.

**Comando:**
```bash
ruff check . --exclude venv,.venv
```

**Reglas Configuradas:**

| Regla | CÃ³digo | DescripciÃ³n |
|-------|--------|-------------|
| McCabe Complexity | C90 | FunciÃ³n con ciclos/condiciones >10 |
| Dead Code Elimination | ERA | `try/except` siempre falla |
| Simplifications | SIM | CÃ³digo que puede simplificarse |

**Ejemplos:**
```
src/complex.py:10: C901 function is too complex (11 > 10)
src/old.py:5: ERA001 unnecessary try block
src/simple.py:20: SIM105 use set(x) instead of `if x in ...`
```

**Acciones:**
- **C90X**: Refactorizar funciÃ³n grande en funciones pequeÃ±as
- **ERA**: Eliminar try/except innecesario
- **SIM**: Aplicar sugerencia o ignorar si contexto es claro

---

### 4. Git Log (AntigÃ¼edad)

**PropÃ³sito:** Medir abandono midiendo frecuencia de commits.

**Comando:**
```bash
git log --oneline --follow -- src/foo.py | wc -l
```

**InterpretaciÃ³n:**
- **commits = 0**: Archivo nuevo, nunca commiteado
- **commits < 5**: CÃ³digo antiguo, poco mantenimiento
- **commits >= 5**: CÃ³digo histÃ³rico, posiblemente importante

**CategorizaciÃ³n:**
```
DEAD: commits = 0  + sin referencias
ABANDONED: 0 < commits < 5  + sin referencias
LEGACY: commits >= 5  + sin referencias
```

---

## Decision Matrix

| Hallazgo | Tool | Commits | Usos | AcciÃ³n Recomendada |
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
McCabe Threshold (ruff C90):    10 (funciÃ³n compleja si >10)
Deadcode Exclude:               venv,.venv,__pycache__,.git,agent_system,.agent
Legacy Threshold (git commits): 5+ = posible API interna
```

---

**Ãšltima actualizaciÃ³n:** 2026-04-28
