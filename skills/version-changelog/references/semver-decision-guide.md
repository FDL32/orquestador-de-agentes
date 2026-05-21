# GuÃ­a de decisiÃ³n SemVer: PATCH / MINOR / MAJOR

## Ãrbol de decisiÃ³n

```
Â¿Rompe la API o el comportamiento existente?
â”œâ”€â”€ SÃ â†’ MAJOR
â””â”€â”€ NO â†’ Â¿AÃ±ade nueva funcionalidad?
          â”œâ”€â”€ SÃ â†’ MINOR
          â””â”€â”€ NO â†’ PATCH
```

## Ejemplos por tipo

### PATCH (0.0.x) â€” solo cuando NO hay cambios funcionales
- CorrecciÃ³n de bug que no cambia la API
- Mejora de rendimiento interna
- Fix de typo en documentaciÃ³n
- ActualizaciÃ³n de dependencia menor sin cambios de comportamiento
- Refactor interno sin cambio de interfaz

### MINOR (0.x.0) â€” nueva funcionalidad, retrocompatible
- Nueva funciÃ³n, clase, o mÃ³dulo aÃ±adido
- Nueva opciÃ³n en funciÃ³n existente (con valor por defecto)
- Nueva skill o comando
- Nuevo endpoint o salida adicional
- Deprecar (no eliminar) una funcionalidad

### MAJOR (x.0.0) â€” cambio incompatible
- Eliminar funciÃ³n, clase, o argumento existente
- Cambiar nombre de funciÃ³n o mÃ³dulo pÃºblico
- Cambiar firma de funciÃ³n (argumentos requeridos)
- Cambiar formato de salida o comportamiento observable
- Cambiar versiÃ³n mÃ­nima de Python requerida
- MigraciÃ³n de base de datos o esquema incompatible

## Casos especiales

### Proyecto en 0.x.y (pre-1.0)
En fase 0.x.y, cualquier cambio puede ir en MINOR sin llegar a MAJOR.
La API pÃºblica no se considera estable hasta 1.0.0.

### MÃºltiples cambios en un ciclo
Aplicar el bump del cambio **mÃ¡s alto** en el ciclo:
- 3 fixes + 1 feature + 0 breaking â†’ MINOR (no 3x PATCH + 1 MINOR)
- 1 breaking + 10 features â†’ MAJOR

### Hotfix sobre versiÃ³n anterior
Si hay que parchear una versiÃ³n antigua (ej. 1.2.x mientras se trabaja en 1.3):
â†’ Crear rama `hotfix/1.2.x` y bump de PATCH desde esa rama
