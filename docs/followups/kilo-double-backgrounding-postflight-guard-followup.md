# Follow-up: kilo-double-backgrounding-postflight-guard

- **Slug:** `kilo-double-backgrounding-postflight-guard-followup`
- **Fecha:** 2026-10-21
- **Dueno:** decision de usuario para abrir WP
- **Estado:** abierto (deuda)
- **Referencia:** `prompts/builder_invocation_contract.md:178-217` (seccion 1.4)

## Problema

No existe un guard mecanico que rechace el uso de `&` (backgrounding manual) cuando la
herramienta invocadora ya gestiona el backgrounding (`background_process`, `Task background=true`).
Un Builder puede lanzar `kilo run ... & ; echo PID` por iniciativa propia, matando al hijo
al hacer cleanup del PID.

## Criterio de cierre

Un guard (hook pre-commit, hook de tool-call del agente, o script de validacion de dispatch)
que detecte y rechace `&` en comandos `kilo run` cuando el launcher usa `background_process`
o `Task background=true`.

## Estado_FRESCO (2026-10-21)

```
ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\FDL32-agents-md-optimization-cont, HEAD=2e62019f, dirty=3, verificado=2026-10-21T06:08 (hora local del host)
```

- La nota operativa existe en `prompts/builder_invocation_contract.md` (NORMA, no barrera).
- Ningun guard mecanico intercepta el `&` en el dispatch de Kilo.
- El riesgo es medido: n=1 incidente real (2026-10-18, vuelo 4 capas, opencode/glm).