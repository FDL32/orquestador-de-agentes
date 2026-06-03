# Guía de decisión SemVer: PATCH / MINOR / MAJOR

## Árbol de decisión

```
¿Rompe la API o el comportamiento existente?
|-- SÍ -> MAJOR
|-- NO -> ¿Añade nueva funcionalidad?
    |-- SÍ -> MINOR
          └── NO → PATCH
```

## Ejemplos por tipo

### PATCH (0.0.x) — solo cuando NO hay cambios funcionales
- Corrección de bug que no cambia la API
- Mejora de rendimiento interna
- Fix de typo en documentación
- Actualización de dependencia menor sin cambios de comportamiento
- Refactor interno sin cambio de interfaz

### MINOR (0.x.0) — nueva funcionalidad, retrocompatible
- Nueva función, clase, o módulo añadido
- Nueva opción en función existente (con valor por defecto)
- Nueva skill o comando
- Nuevo endpoint o salida adicional
- Deprecar (no eliminar) una funcionalidad

### MAJOR (x.0.0) — cambio incompatible
- Eliminar función, clase, o argumento existente
- Cambiar nombre de función o módulo público
- Cambiar firma de función (argumentos requeridos)
- Cambiar formato de salida o comportamiento observable
- Cambiar versión mínima de Python requerida
- Migración de base de datos o esquema incompatible

## Casos especiales

### Proyecto en 0.x.y (pre-1.0)
En fase 0.x.y, cualquier cambio puede ir en MINOR sin llegar a MAJOR.
La API pública no se considera estable hasta 1.0.0.

### Múltiples cambios en un ciclo
Aplicar el bump del cambio **más alto** en el ciclo:
- 3 fixes + 1 feature + 0 breaking → MINOR (no 3x PATCH + 1 MINOR)
- 1 breaking + 10 features → MAJOR

### Hotfix sobre versión anterior
Si hay que parchear una versión antigua (ej. 1.2.x mientras se trabaja en 1.3):
→ Crear rama `hotfix/1.2.x` y bump de PATCH desde esa rama
