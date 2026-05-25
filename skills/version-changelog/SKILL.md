---
name: version-changelog
version: 2.0.0
description: GestiÃ³n de versiones semÃ¡nticas y CHANGELOG.md siguiendo Keep a Changelog y SemVer 2.0
triggers: [/changelog, version, /release]
author: agent
role: shared
stage: close
writes_memory: false
quality_gate: false
tags: [core, system]
---

# version-changelog

Gestiona el ciclo de versiones de un proyecto: bumping semÃ¡ntico, entradas de changelog y etiquetas git. Sigue [SemVer 2.0](https://semver.org) y [Keep a Changelog](https://keepachangelog.com).

## CuÃ¡ndo activar

El Manager activa esta skill:
- Al **cerrar una fase** del work_plan (antes de DONE)
- Cuando el Builder ha completado un conjunto de cambios revisados y aprobados
- Antes de cualquier **publicaciÃ³n o entrega** al usuario

## Conceptos clave

### Reglas SemVer

| Tipo | CuÃ¡ndo | Ejemplo |
|------|--------|---------|
| **PATCH** (0.0.x) | Bug fix, correcciÃ³n interna, mejora sin cambio de API | `1.2.3 â†’ 1.2.4` |
| **MINOR** (0.x.0) | Nueva funcionalidad retrocompatible | `1.2.3 â†’ 1.3.0` |
| **MAJOR** (x.0.0) | Cambio incompatible con versiÃ³n anterior | `1.2.3 â†’ 2.0.0` |
| **pre-release** | Trabajo en progreso | `1.3.0-alpha.1` |

### Secciones del CHANGELOG

```
Added      â†’ nuevas funcionalidades
Changed    â†’ cambios en funcionalidad existente
Deprecated â†’ funcionalidades que serÃ¡n eliminadas
Removed    â†’ funcionalidades eliminadas
Fixed      â†’ correcciÃ³n de bugs
Security   â†’ vulnerabilidades corregidas
```

## Workflow

### Paso 1: Leer versiÃ³n actual

```bash
# Desde pyproject.toml
python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"

# O desde __init__.py
grep -r "__version__" src/ | head -1
```

Si no existe versiÃ³n â†’ inicializar en `0.1.0`.

### Paso 2: Clasificar cambios del ciclo actual

Revisar los cambios implementados (via work_plan.md + execution_log.md) y clasificar:

```markdown
## ClasificaciÃ³n de cambios

**Tipo de bump sugerido:** MINOR  â† (PATCH / MINOR / MAJOR)
**RazÃ³n:** Se aÃ±adieron 2 nuevas funcionalidades sin romper API existente

**Added:**
- Skill `graphify` para exploraciÃ³n eficiente de codebase
- Skill `version-changelog` para gestiÃ³n de versiones

**Fixed:**
- (ninguno)

**Changed:**
- (ninguno)
```

Presentar clasificaciÃ³n al Manager para **validaciÃ³n humana** antes de continuar.

### Paso 3: Calcular nueva versiÃ³n

```python
# Ejemplo de lÃ³gica de bump
current = "1.2.3"
major, minor, patch = map(int, current.split("."))

bump_type = "minor"  # determinado en Paso 2

if bump_type == "major":
    new_version = f"{major+1}.0.0"
elif bump_type == "minor":
    new_version = f"{major}.{minor+1}.0"
else:  # patch
    new_version = f"{major}.{minor}.{patch+1}"

print(f"{current} â†’ {new_version}")
```

### Paso 4: Actualizar CHANGELOG.md

Si no existe `CHANGELOG.md`, crearlo con la plantilla base (ver reference).

AÃ±adir la nueva entrada **al inicio** del archivo, justo despuÃ©s del header:

```markdown
## [1.3.0] - 2026-04-13

### Added
- Skill `graphify` para construcciÃ³n de grafos de conocimiento persistentes
- Skill `version-changelog` para gestiÃ³n semÃ¡ntica de versiones

### Fixed
- CorrecciÃ³n en hook `guard_paths` con rutas con espacios
```

El bloque `[Unreleased]` se vacÃ­a y queda listo para el prÃ³ximo ciclo:

```markdown
## [Unreleased]

### Added
### Changed
### Fixed
```

### Paso 5: Actualizar versiÃ³n en el proyecto

**pyproject.toml:**
```toml
[project]
version = "1.3.0"
```

**src/__init__.py** (si existe):
```python
__version__ = "1.3.0"
```

Buscar y actualizar todos los lugares donde vive la versiÃ³n:
```bash
grep -r "version" pyproject.toml src/__init__.py 2>/dev/null
```

### Paso 6: Actualizar PROJECT.md

AÃ±adir entrada en el historial de PROJECT.md:

```markdown
# Historial de versiones

| VersiÃ³n | Fecha | DescripciÃ³n |
|---------|-------|-------------|
| 1.3.0 | 2026-04-13 | Skills graphify y version-changelog |
| 1.2.0 | 2026-03-15 | Sistema multi-agente v4 |
```

### Paso 7: Git tag (solo si el usuario aprueba)

```bash
git add CHANGELOG.md pyproject.toml src/__init__.py PROJECT.md
git commit -m "chore: bump version to 1.3.0

- Actualiza CHANGELOG con cambios del ciclo
- VersiÃ³n en pyproject.toml y __init__.py"

git tag -a v1.3.0 -m "Release 1.3.0"
```

**IMPORTANTE**: El tag solo se crea si el Manager lo aprueba explÃ­citamente. No crear tags automÃ¡ticamente.

## Plantilla CHANGELOG.md

Ver `references/changelog-template.md`.

## Constraints

- **NUNCA** saltarse la validaciÃ³n humana del tipo de bump (Paso 2 â†’ Manager aprueba)
- **NUNCA** crear git tags sin aprobaciÃ³n explÃ­cita del usuario
- **SIEMPRE** mantener el bloque `[Unreleased]` en CHANGELOG.md
- **SIEMPRE** usar formato ISO-8601 para fechas (`YYYY-MM-DD`)
- Las entradas del changelog deben ser **legibles por humanos**, no mensajes de commit
- Si el proyecto usa `__version__` en mÃºltiples sitios, actualizarlos todos

## References

- `references/changelog-template.md` - Plantilla CHANGELOG.md inicial
- `references/semver-decision-guide.md` - GuÃ­a de decisiÃ³n PATCH/MINOR/MAJOR
