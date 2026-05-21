# Filter Criteria - Repo Compare

Criterios de scoring y filtrado rápido para repositorios GitHub.

---

## Scoring 0-5 (Fase 1)

Evaluar el repo target sobre 5 dimensiones. Cada dimensión suma 0 o 1 punto.

### 1. README claro (0-1)

**1 punto si:**
- Explica qué hace el proyecto en ≤ 3 frases.
- Tiene sección de instalación/uso.
- Menciona casos de uso o features principales.

**0 puntos si:**
- README vacío, placeholder, o solo badges.
- No está claro qué problema resuelve.
- Requiere leer código para entender el propósito.

### 2. Tests/CI presentes (0-1)

**1 punto si:**
- Directorio `tests/` con archivos `.py`.
- `.github/workflows/` con CI configurado (pytest, ruff, etc.).
- `pytest.ini`, `tox.ini`, o `pyproject.toml` con config de tests.

**0 puntos si:**
- No hay `tests/` ni `test/`.
- No hay `.github/workflows/` ni señales de CI.
- Tests desactualizados (> 1 año sin correr).

### 3. Señales mantenimiento (0-1)

**1 punto si:**
- Último commit < 6 meses.
- Issues abiertos respondidos por maintainers.
- Versiones recientes en `pyproject.toml` o CHANGELOG.

**0 puntos si:**
- Último commit > 1 año.
- Issues abiertos sin respuesta (> 30 días).
- Proyecto archivado o abandonado.

### 4. Encaje técnico (0-1)

**1 punto si:**
- Python 3.10+ (coincide con z_scripts).
- Usa `uv`, `pip`, o gestor compatible.
- Deps ligeras o justificadas (no `tensorflow` para algo simple).

**0 puntos si:**
- Python < 3.10 (requiere downgrade o fork).
- Deps pesadas no justificadas (> 100MB, nativas, etc.).
- Requiere infra no disponible (Docker, Kubernetes, DB externa).

### 5. Claridad estructural (0-1)

**1 punto si:**
- Directorios reconocibles: `skills/`, `hooks/`, `tools/`, `agents/`, `prompts/`.
- Separación clara entre código, config, y docs.
- Naming consistente y predecible.

**0 puntos si:**
- Monorepo caótico (todo en raíz).
- Naming inconsistente (`src/`, `code/`, `lib/`, `stuff/` mezclados).
- No está claro dónde está el código principal.

---

## Umbral de decisión

**Total ≥ 3**: Continuar a Fase 2 (exploración).

**Total < 3**: Marcar `[BAJO VALOR]`, abortar con explicación breve.

Ejemplo de abort:
```markdown
## Filtro rápido: [BAJO VALOR] - Score 2/5

- README claro: ✅ 1
- Tests/CI: ❌ 0
- Mantenimiento: ❌ 0 (último commit: 2024-03)
- Encaje técnico: ✅ 1
- Claridad estructural: ❌ 0

**Decisión:** Abortar exploración. El repo no justifica inversión de tiempo.
```

---

## Reglas de descarte rápido

Descartar sin scoring detallado si:

### Monorepo caótico

- Raíz con 50+ archivos sueltos.
- No hay separación entre código, docs, y config.
- `ls` no revela estructura reconocible.

### Deps pesadas no justificadas

- `tensorflow`, `pytorch`, `onnx` para un script simple.
- `selenium`, `playwright` sin justificación de browser automation.
- Deps nativas que requieren compilación (y no hay wheel).

### Ya existe mejor en local

- AUDIT.md indica que z_scripts ya tiene funcionalidad equivalente o superior.
- El repo target es un subconjunto de lo que ya existe.

### Proyecto abandonado

- Último commit > 2 años.
- Issues abiertos sin respuesta.
- Dependencias desactualizadas (CVEs conocidos).

---

## Ejemplo de scoring completo

```markdown
## Filtro rápido: Score 4/5 ✅

| Dimensión | Puntos | Justificación |
|-----------|--------|---------------|
| README claro | 1 | Explica propósito, instalación, y 5 features |
| Tests/CI | 1 | `tests/` con 20 tests, `.github/workflows/ci.yml` |
| Mantenimiento | 1 | Último commit: 2026-05-10 (hace 8 días) |
| Encaje técnico | 1 | Python 3.10+, `uv`, deps ligeras |
| Claridad estructural | 0 | Todo en raíz, no hay `skills/` ni `hooks/` |

**Total:** 4/5 → Continuar a Fase 2 (exploración)
```

---

## Integración con el workflow

Este archivo es referenciado por:

- `SKILL.md` — Paso 3 (Filtro rápido).
- `PROMPT_TEMPLATE.md` — Fase 1 (scoring 0-5).
- Agente ejecutor — Usar como checklist durante la evaluación.
