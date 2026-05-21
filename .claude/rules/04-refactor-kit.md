# Refactor Kit Portable (v2.6+)

## Propósito
Proveer un framework de refactorización automatizada en 5 fases que funciona en CUALQUIER proyecto Python, de forma portátil y **sin dependencias** del sistema `z_scripts`.

## Arquitectura (`agent_system/refactor-kit/`)
- `refactor_manager.py`: Orquestador de las 5 fases.
- `install_refactor_kit.py`: Copia el sistema a nuevos proyectos.
- `prompt_templates/`: Prompts agnósticos al agente.

## Workflow de 5 Fases
1. **Análisis:** Identifica problemas y propone mejoras en un archivo.
2. **Plan:** Crea un plan detallado de cambios específicos.
3. **Refactor:** Ejecuta los cambios autorizados.
4. **Validación:** Verifica con linter/tests.
5. **Iteración:** Si hay fallos, corrige y repite validación (auto-healing).

## Reglas para el Builder
- **Zero Dependencies:** Nunca importes código de `z_scripts` dentro del directorio `refactor-kit/`. Todo debe depender de la librería estándar de Python.
- Valida siempre corriendo `python scripts/test_refactor_kit_portable.py` antes de cualquier merge de cambios al kit.
