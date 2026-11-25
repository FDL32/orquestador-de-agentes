# Arranque Agnostico de Coordinadora (Checklist Canonico de 5 Pasos)

Referencia canonica obligatoria para cualquier coordinadora (Claude, Codex, Gemini,
OpenCode) al asumir el mando en un vuelo o tras un relevo. Garantiza disciplina
uniforme, evitando la anidacion indebida de subagentes y ejecuciones sin lentes.

## Paso 1: Verificacion de identidad y rol (identidad)

Antes de operar, la sesion confirma su identidad y rol contra el flight roster:
- Comando: `python scripts/check_roster_matches_acting_thread.py --acting-thread <threadId> --role orquestador`
  (especificando `--roster-path <ruta>` si no esta en variable de entorno).
- Retorno esperado: rc 0 (coincidencia confirmada). Si el roster no existe (rc 3),
  verificar manualmente en el registro de sesiones antes de asumir el rol.
- Si retorna error o el rol no coincide (rc 1), detener la ejecucion.

## Paso 2: Activacion del latido de 15 minutos (latido)

Tras tomar posesion (Fase B), definir objetivo y primera accion, y activar el latido:
- Mecanismo: herramienta MCP `schedule_task` (servidor `t3-code`).
- Parametros requeridos:
  - `schedule`: `{"type":"interval","everyMs":900000}` (intervalo exacto de 15 min, P21).
  - `bindToCurrentThread`: `true` (el pulso retorna a este hilo de coordinacion).
- El latido actua como red de seguridad periodica (P8/P9) y debe mantenerse activo.

## Paso 3: Verificacion de repositorios y contrato de backlog (repos)

Asegurar integridad de superficies antes de admitir o despachar tickets:
- Comprobar que los arboles de trabajo asignados estan limpios (`git status --porcelain` vacio).
- Ejecutar: `python scripts/check_backlog_contract.py --project-root <workspace>`
- Retorno esperado: rc 0 estricto.
- Verificar la BASE del motor asignada al vuelo y el hash sha12 de cada ficha admitida.

## Paso 4: Lanzamiento de IM y TR en hilos T3 aislados (hilos T3 aislados)

Despacho estricto de sesiones operativas de implantacion (IM) y triaje/revision (TR):
- Obligatorio: invocar `t3_thread_launch` con `workspaceStrategy` independiente
  (worktree propio y rama aislada dedicados a la sesion).
- Prohibicion expresa: NUNCA lanzar un IM o TR como subagente interno en el propio
  hilo de la coordinadora (prohibido `delegate_task` para crear sesiones IM/TR).
- Nota de celda: las sub-tareas internas propias del IM (como el builder child bajo
  P35/P36) operan dentro del hilo del IM, nunca en el hilo de coordinacion.

## Paso 5: Celda de lentes P34 multifamilia (lentes P34)

Cumplimiento estricto de los protocolos P33/P34 de revision y triaje adversarial:
- Por cada sesion de IM: someter obligatoriamente a 2 lentes independientes.
- Por cada sesion de TR: someter obligatoriamente a 2 lentes independientes.
- Regla de diversidad obligatoria (P33/P34): las 2 lentes deben pertenecer a familias
  distintas a la del autor y distintas entre si (ejemplo: DeepSeek + Qwen para sesiones
  Gemini o Claude), cubriendo laboratorios distintos. Prohibido operar con una sola familia.
- Ningun ticket puede considerarse apto para admision o integracion sin 2 lentes conformes.

## Monitorizacion de contexto y planificacion del relevo

- Monitorear el consumo de contexto del hilo propio en cada ciclo de latido.
- Planificar el relevo con antelacion antes de alcanzar saturacion de ventana.
- Ejecutar la rotacion mediante `scripts/flight/rotate_coordinator.py` (o
  `rotate_coordinator_real.py` / script de relevo del vuelo en repo_destino).
- Consultar `docs/protocol/flight_supervision.md` para el protocolo formal.
- Mantener la directriz de backend vigente establecida para el vuelo.
