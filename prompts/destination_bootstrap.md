# Destination Bootstrap Prompt

Pega este bloque al iniciar una sesion en un `repo_destino` (proyecto que consume
el motor `orquestador_de_agentes` como dependencia externa). Proporciona el arranque
canonico para orientarse sin Repomix, Graphify ni Node.

---

## Prompt (copia y pega)

```
Estas operando sobre un `repo_destino` del motor `orquestador_de_agentes`.

## Lectura obligatoria antes de actuar

1. Lee `.agent/config/motor_destination_link.json` para conocer la ruta absoluta
   del motor y la configuracion del destino.
2. Resuelve `motor_root` desde ese archivo (clave `motor_root`).
3. Ejecuta el generador de mapa compacto:
   `python <motor_root>/scripts/destination_context.py --bootstrap --project-root .`
4. Lee el mapa generado en `.agent/context/destination_map.md`.
5. Valida el estado canonico del destino:
   `python <motor_root>/.agent/agent_controller.py --validate --json --project-root .`
   La salida aporta en un solo comando: errores de estado, drift plan/log,
   warnings de prosa del ticket activo, invariantes del bus y prefijo de
   tickets. Triarla antes de tocar nada.
6. Si el usuario pide implantar varios tickets desde `backlog.md` por chat,
   usa `<motor_root>/prompts/orchestrator_pipeline.md` y la skill
   `<motor_root>/skills/orchestrate-pipeline/SKILL.md` (`/pipeline`).
7. Si el destino aun no esta instalado o sincronizado con el motor, no uses
   este bootstrap como sustituto del setup: aplica primero
   `<motor_root>/skills/setup-agent-system/SKILL.md`.
8. Si el objetivo es preparar el destino para Git/publicacion, distingue dos
   gates:
   - estado operativo publicable: `python <motor_root>/scripts/check_destino_publish_ready.py --project-root . --motor-root <motor_root>`;
   - auditoria de primera publicacion: `<motor_root>/prompts/audit_git_publication.md`.
9. Continua con `rg` y lectura directa de archivos bajo demanda.

## Vocabulario canonico

| Termino | Descripcion |
|---------|-------------|
| `repo_motor` | `orquestador_de_agentes/` — motor portable, fuente canonica |
| `repo_destino` | Este proyecto — donde viven el estado, tickets y config |
| `motor_root` | Ruta absoluta al `repo_motor` desde `motor_destination_link.json` |

Regla de repos: las operaciones git del tooling corren en `repo_motor`.
El estado operativo (tickets, memoria) vive en `repo_destino`.

## Comportamiento esperado

- Responde breve, optimizando tokens. Sin emojis.
- Antes de cambios destructivos, confirma con el usuario.
- Si el usuario pide algo que ya existe, revisa primero antes de proponer nada nuevo.
- Usa `rg` para busquedas rapidas en el arbol; combo `rg` + `read` para entender
  archivos sin cargar el arbol completo.

## Preflight de seguridad (host-extends)

Antes de operar cualquier ticket que toque hooks, CI o install (o que retire copias
motor-provides), confirma EXPLICITAMENTE, ademas de los pasos anteriores:

1. Topologia resuelta: `repo_motor`, `repo_destino` y `AGENT_PROJECT_ROOT` (o
   `.agent/config/motor_destination_link.json`) apuntan al destino correcto. Sin esto, no
   arranques Builder.
2. Settings Claude portables y guard fail-closed: si existe un `.claude/settings.json`
   trackeado, corre `python <motor_root>/scripts/check_claude_settings_portability.py
   .claude/settings.json`. Debe pasar: sin `permissions.allow` trackeado, hook de escritura
   presente, entrypoint canonico fail-closed.
3. Resolvers vivos: para cualquier retirada de copias locales (`scripts/`, `skills/`,
   `agent_system/`, `.agent/hooks/`), verifica que ningun consumidor vivo (hook, CI,
   launcher) resuelve aun contra la copia a retirar. `install --sync` NO es un mecanismo
   seguro de poda host-extends hasta cerrar WOT-2026-003d.

Si cualquiera falla, detente y reporta antes de tocar codigo.

## Encaje en el ciclo de vida del destino

- Instalacion/sync: `skills/setup-agent-system/SKILL.md`.
- Arranque de sesion en destino ya instalado: este prompt.
- Ejecucion de backlog: `prompts/orchestrator_pipeline.md`.
- Salud post-cambio motor+destino: `prompts/audit_post_change_system_health.md`.
- Pre-publicacion operativa: `scripts/check_destino_publish_ready.py`.
- Preparacion para publicacion Git: `prompts/audit_git_publication.md`.
```

---

## Cuando usarlo

- Primera interaccion con un agente nuevo en un `repo_destino` (no en el motor).
- Al recuperarse de una sesion comprimida donde el agente perdio contexto del destino.
- Al retomar un ticket en un destino que no tiene contexto de Repomix fresco.

## Cuando NO usarlo

- Si ya hay un `work_plan.md` activo IN_PROGRESS — el agente debe leer primero ese.
- En el `repo_motor` (motor-root): usa `session_bootstrap.md` en su lugar.
- Si Repomix ya esta disponible y prefieres ese nivel de detalle.

## Mantenimiento

Actualiza este archivo cuando:
- Cambia la interfaz de `destination_context.py`.
- Se anade o quita un paso canonico del flujo de bootstrap.
- Cambia el formato de `motor_destination_link.json`.
- Cambia el flujo `/pipeline` o su skill asociada.
