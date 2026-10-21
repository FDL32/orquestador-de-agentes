#### Push por vuelo: UN solo push al final de TODOS los tickets (2026-10-19)



- DECISION DE PROCESO: la publicacion se difiere al final del vuelo, nunca por ticket (2026-10-19).

  BUSQUEDA-PREVIA: PROTOCOLO ENCONTRADO: `prompts/orchestrator_session_bootstrap.md:314` ("UN solo push al final de la cola, con OK humano explicito"), `prompts/orchestrator_pipeline_codeonly.md:199` ("Push AGRUPADO al final de sesion ... NO push por ticket") y `prompts/manager_orchestrator_loop_backlog.md:455` (informe antes del push). Esta seccion EXTIENDE esa regla a todo vuelo multi-ticket; no la inventa.



**La publicacion es una accion del VUELO, no del ticket.** Durante un vuelo (batch

autonomo, pipeline code-only o cadena de cierres), cada ticket se cierra EN LOCAL con su

commit y **NO se pushea entre tickets**. El push se ejecuta UNA sola vez, al final del

vuelo: despues del ULTIMO ticket, con la suite canonica verde sobre el HEAD final y los

gates de publicacion de la seccion siguiente (Gate 1/Gate 2) satisfechos.



Motivo: cada push intermedio exige una autorizacion humana y rompe la autonomia del vuelo.

La autorizacion de publicacion se resuelve en la PREPARACION del vuelo -- una sola

decision, por adelantado, registrada en el arranque/plan de vuelo -- no goteando ticket a

ticket (misma logica que `batch-agrupar-preguntas-antes-de-arrancar`).



- **Sin autorizacion registrada no hay push.** Un vuelo que termina sin decision de

  publicacion queda en estado declarado `PUBLICACION_PENDIENTE_AUTORIZACION`: todo

  commiteado y verde en local, remoto intacto. La autorizacion NUNCA se infiere del

  silencio ni se pide a mitad de vuelo.

- **El push final es unico y agrupado.** Si la rama remota avanzo, aplica el Gate 2 de la

  seccion siguiente; no se reabre el Gate 1 (el `tested_commit_sha == HEAD` del commit

  final ya verificado sigue siendo el ancla).

- **Alcance:** todo vuelo con uno o mas tickets. Un ticket suelto que NO forma parte de un

  vuelo puede pushearse al cerrarlo; si forma parte de un vuelo, espera al final del vuelo.



#### Extension: push a una rama con trafico concurrente de otras sesiones (2026-10-14)



**Gate 1 (nunca se relaja):** antes de que un commit propio EXISTA en cualquier rama

compartida, la suite canonica completa corre sobre ESE commit (regla de arriba, sin excepcion).