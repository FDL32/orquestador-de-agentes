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
- El script `scripts/discover_skills.py` genera un mapeo `trigger → skill_path`.
- **Integración Claude Code:** El discovery se invoca con `python scripts/discover_skills.py --json` para listar skills disponibles.
- ~~**Integración Goose/Claw:**~~ **[DEPRECATED - WT-2026-254a]** La integración Goose/Claw está deprecada.

## 3. Skill Executor (Fase 3b)
Ejecución directa de un flujo sin agente externo:
`python scripts/orquestador.py --skill /review --query "revisa cambios"`
Esto extrae la sección `## Workflow` del `SKILL.md` correspondiente.

## 4. Testing (Fase 3) [DEPRECATED - WT-2026-254a]
~~`python scripts/test_goose_triggers.py`~~ — Movido a `tests/deprecated/test_goose_triggers.py`.
Para verificar el trigger map: `python scripts/discover_skills.py --json`
