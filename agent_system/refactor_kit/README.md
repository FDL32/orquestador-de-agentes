# Refactor-Kit Portable

Herramienta standalone para realizar reingenierÃ­a de cÃ³digo segura siguiendo el protocolo de 5 fases de `z_scripts`.

## CaracterÃ­sticas
- **Zero Dependencies:** Funciona con la librerÃ­a estÃ¡ndar de Python 3.10+.
- **PortÃ¡til:** Se instala en cualquier proyecto sin contaminar tu entorno global.
- **AgnÃ³stico:** Soporta Goose y Claw como motores de IA.

## InstalaciÃ³n

Desde la raÃ­z de `z_scripts`:
```bash
python agent_system/refactor-kit/install_refactor_kit.py /ruta/a/tu/proyecto
```

## Uso BÃ¡sico

Navega a tu proyecto y ejecuta:
```bash
python .refactor/kit/refactor_manager.py --target src/mi_archivo.py --agent goose
```

## Flujo de 5 Fases
1. **AnÃ¡lisis:** La IA lee el cÃ³digo y documenta invariantes.
2. **PlanificaciÃ³n:** Propuesta de cambio mÃ­nimo sin cÃ³digo.
3. **RefactorizaciÃ³n:** AplicaciÃ³n controlada de los cambios.
4. **ValidaciÃ³n:** EjecuciÃ³n de tests y chequeos de calidad.
5. **IteraciÃ³n:** CorrecciÃ³n de errores si la validaciÃ³n falla.

## Estructura de Artefactos
Los resultados de cada fase se guardan en `.refactor/phases/` en formato JSON para auditorÃ­a.

## Optimizaciones de Performance

### Template Caching
Los templates de prompts se cargan una sola vez al iniciar, eliminando I/O repetitivo.

### Execution Timing
Cada fase mide su tiempo de ejecuciÃ³n con reporte detallado al final:
```
TIMING SUMMARY
============================================================
01_analysis: 2.34s (23.4%)
02_plan: 4.12s (41.2%)
03_refactor: 1.45s (14.5%)
04_validation: 1.89s (18.9%)
05_iteration: 0.20s (2.0%)
TOTAL: 10.00s
```

### Result Caching
DetecciÃ³n automÃ¡tica de cambios usando hash MD5:
- **Primera ejecuciÃ³n:** AnÃ¡lisis completo (~5-10 min)
- **Ejecuciones siguientes (mismo cÃ³digo):** Salta fases completadas (~1 min, 80% mejora)

### Cache Invalidation
Modificaciones al archivo invalidan automÃ¡ticamente el cache, forzando re-anÃ¡lisis.

---
*Parte del ecosistema z_scripts - Multi-Agent Orchestration.*
