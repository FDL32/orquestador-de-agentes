# Sistema de Skills y Triggers (Fases 2 y 3)

## 1. Triggers en YAML (Forward Compatibility)
Cada skill en `skills/` DEBE declarar un bloque YAML al inicio con palabras clave (triggers) que la activan.

```yaml
---
name: Code Review
version: 1.0.0
description: Revisar cambios de código
triggers: [/codereview, review, /approve]
---
```
- Máximo 3 triggers por skill.
- Valida con `python scripts/discover_skills.py --json`.

## 2. Descubrimiento Automático (Fase 2)
- El script `scripts/discover_skills.py` genera un mapeo `trigger â†’ skill_path`.
- **Integración Goose/Claw:** El orquestador ejecuta el discovery automáticamente en startup y agrega los triggers al prompt del agente. Así, el agente conoce y puede usar los comandos `/implement`, `/review` sin configuración adicional.

## 3. Skill Executor (Fase 3b)
Ejecución directa de un flujo sin agente externo:
`python scripts/orquestador.py --skill /review --query "revisa cambios"`
Esto extrae la sección `## Workflow` del `SKILL.md` correspondiente.

## 4. Testing (Fase 3)
Verifica que los triggers funcionan y Goose/Claw reciben la lista correctamente ejecutando:
`python scripts/test_goose_triggers.py`
