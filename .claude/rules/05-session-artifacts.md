# Patrón `.session/` (Directorio Durable de Artifacts Temporales)

## Propósito
Aislar `work_plan.md`, `execution_log.md` y otros artifacts temporales de desarrollo en un directorio separado (`.session/`), manteniendo la raíz limpia para documentación permanente como `PROJECT.md` o `CHANGELOG.md`.

## Estructura
```text
.session/                          ← Directorio durable de sesión
├── work_plan.md                   (aprobado por Manager, ejecutado por Builder)
├── execution_log.md               (bitácora de ejecución actual)
└── [borradores temporales]        (permitido guardar cualquier scratch aquí)
```

## Ciclo de vida
- **Durable:** Persiste entre sesiones.
- **Sobrescrito:** Manager/Builder sobreescriben el contenido para la próxima tarea.
- **No archivado:** Las decisiones arquitectónicas importantes NUNCA se quedan aquí de forma permanente. **Deben consolidarse post-sesión** moviendo el conocimiento al `PROJECT.md` o `CHANGELOG.md`.

## Relación con TURN.md
- `TURN.md` es el "turno actual del agente", NO un artefacto de sesión temporal.
- Permanece en `.agent/collaboration/TURN.md` (y su modificación está bloqueada por `guard_paths`).

## Forward Compatibility
- Agentes externos como Goose leerán/escribirán `work_plan.md` directamente desde `.session/` de manera agnóstica al motor interno.
