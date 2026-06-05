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
5. Continua con `rg` y lectura directa de archivos bajo demanda.

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
