# Refactor Kit Portable

## Propósito
Proveer un framework de refactorización automatizada en 5 fases que funciona en CUALQUIER proyecto Python, de forma portátil y sin dependencias externas (solo librería estándar).

## Arquitectura (`agent_system/refactor_kit/`)
- `refactor_manager.py`: Orquestador de las 5 fases.
- `install_refactor_kit.py`: Copia el sistema a nuevos proyectos.
- `prompt_templates/`: Prompts agnósticos al agente.
- `README.md`: Documentación de uso del kit.

## Workflow de 5 Fases
1. **Análisis:** Identifica problemas y propone mejoras en un archivo.
2. **Plan:** Crea un plan detallado de cambios específicos.
3. **Refactor:** Ejecuta los cambios autorizados.
4. **Validación:** Verifica con linter/tests.
5. **Iteración:** Si hay fallos, corrige y repite validación (auto-healing).

## Reglas para el Builder
- **Zero Dependencies:** El código dentro de `agent_system/refactor_kit/` solo puede depender de la librería estándar de Python. No importes módulos del motor ni de proyectos externos.
- Valida cualquier cambio al kit con los gates canónicos: `ruff check agent_system/refactor_kit/` y `python scripts/run_pytest_safe.py`.
