# CEM v0 - Ingenieria sostenible con agentes

Esta regla es una referencia operativa revisable. CEM significa Contrato, Evidencia y Memoria. Su objetivo no es anadir ceremonia fija, sino reducir recurrencias con rigor proporcional.

## Principio central

Un problema no esta cerrado cuando deja de fallar. Esta cerrado cuando entendemos el contrato, dejamos evidencia verificable y convertimos el aprendizaje en barrera automatica o deuda explicita.

## Tiers de rigor

- Tier 0: documentacion, memoria o texto sin impacto runtime. Requiere diff limpio y guard de encoding si aplica.
- Tier 1: tests o fixtures aislados. Requiere test focal y explicacion del contrato que valida.
- Tier 2: codigo de produccion local. Requiere test gobernante, calidad focal y scope claro.
- Tier 3: bus, supervisor, hooks, rutas, seguridad, estado compartido o tooling de cierre. Requiere evidencia focal, prueba contextual y barrera verificada.
- Tier 4: arquitectura o protocolo sistemico. Requiere contrato escrito, plan, reversibilidad y cierre documental.

El tier debe derivarse principalmente de paths tocados, blast radius y reversibilidad, no de la autoevaluacion del Builder.

## Taxonomia de fallos

- Clase A: regresion de contrato. Produccion diverge del comportamiento canonico.
- Clase B: fuga de estado. Cache, cwd, sys.modules, variables globales o filesystem contaminan otros tests.
- Clase C: deriva de fixture o mock. El test ya no representa la API o artefacto real.
- Clase D: entorno o infraestructura. Encoding, rutas, permisos, topologia, plataforma o herramientas.

## Escalera de robustez

Prefiere la barrera mas alta razonable para el riesgo:

- R0: documentar la regla.
- R1: detectar tarde con test o auditoria.
- R2: bloquear en la puerta con hook, gate o validator.
- R3: hacer dificil el error con defaults, scope automatico o mensajes self-service.
- R4: hacer imposible representar el error con estructura, tipos, API unica o fuente canonica.

## Protocolo de clasificacion

- Si sospechas contaminacion, compara aislado vs suite/contexto.
- Si dudas entre test obsoleto y bug real, compara test contra produccion committeada y contrato canonico.
- Si sospechas falso verde, contrasta fixture contra artefacto real.
- Si anades una barrera, inyecta el fallo y confirma que bloquea.

## Roles

Builder: implementa cambios pequenos con contrato, evidencia y barrera proporcional. Si sale de scope, lo justifica antes de seguir.

Manager: revisa si el verde significa realidad. Rechaza falso verde, mocks que oculten drift y evidencia puramente narrativa.

Supervisor: automatiza invariantes, valida topologia, genera handoffs desde fuentes canonicas y hace que los gates sean accionables.

Humano: sostiene el criterio del sistema preguntando que contrato se defiende, que evidencia existe, que barrera queda y que deuda se acepta.

## Relaunch CEM

Un Builder relanzado no debe arrancar amnesico. Antes de relanzar, el Supervisor debe verificar root/topologia. Despues debe generar una capsula fresca desde fuentes canonicas que separe hechos verificados, blockers, hipotesis y siguiente accion. La capsula no es estado vivo acumulativo.

Cuando el Builder escriba en execution_log.md algo no verificado o inferido, debe usar el prefijo canonico `hipotesis:` para que el Supervisor lo incluya en la capsula de relaunch.
Ejemplo: `- hipotesis: el fallo puede deberse a contaminacion de cache — pendiente de confirmar.`
Sin ese prefijo, la inferencia no aparece en la capsula y el siguiente Builder arranca sin ese contexto.

## Metricas ligeras

- Familias recurrentes por periodo.
- Deuda viva: allowlists, skips, xfails, overrides y tickets de deuda.
- Porcentaje de fixes con barrera proporcional.
- Falsos verdes detectados por revision.
- Tiempo desde deteccion de familia hasta barrera.
