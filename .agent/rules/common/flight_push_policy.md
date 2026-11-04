#### Push por vuelo: UN solo push al final de TODOS los tickets (2026-10-19)

- DECISION DE PROCESO: la publicacion se difiere al final del vuelo, nunca por ticket (2026-10-19).
  BUSQUEDA-PREVIA: PROTOCOLO ENCONTRADO: `prompts/orchestrator_session_bootstrap.md:318` ("UN solo push al final de la cola, con OK humano explicito"), `prompts/orchestrator_pipeline_codeonly.md:203` ("Push AGRUPADO al final de TODOS los tickets del vuelo ... NO push por ticket") y la seccion 7 de `prompts/manager_orchestrator_loop_backlog.md` (informe antes del push). Esta seccion EXTIENDE esa regla a todo vuelo multi-ticket; no la inventa.

**La publicacion es una accion del VUELO, no del ticket.** Durante un vuelo (batch
autonomo, pipeline code-only o cadena de cierres), cada ticket se cierra EN LOCAL con su
commit y **NO se pushea entre tickets**. El push se ejecuta UNA sola vez, al final del
vuelo: despues del ULTIMO ticket, con la suite canonica verde sobre el HEAD final y los
gates de publicacion de la seccion siguiente (Gate 1/Gate 2) satisfechos.

Motivo: cada push intermedio exige una autorizacion humana y rompe la autonomia del vuelo.
La autorizacion inicial de publicacion se registra en la PREPARACION del vuelo como
INTENCION -- una sola decision, por adelantado, no goteando ticket a ticket (misma
logica que `batch-agrupar-preguntas-antes-de-arrancar`). El push final exige ademas la
CONFIRMACION DEL ARTEFACTO mediante la frase canonica definida y verificada por
`scripts/flight/verify_user_authorization.py`. La frase se emite y consume sobre el
HEAD que se va a empujar; cada integracion del Gate 2 o rechazo non-fast-forward
exige una frase nueva. El verificador lo impone: `collect_push_context` exige
`tested_commit_sha == HEAD` en `scripts/flight/verify_user_authorization.py:1257-1284`,
y `_range_commit_count` rechaza `not-ancestor` en `:1216-1245`.

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

> Este apartado es el mecanismo GIT reactivo (que hacer cuando la rama ya avanzo). La capa
> PROACTIVA previa -- avisar a las otras sesiones T3 antes de tocar una superficie compartida,
> coordinar suite/push y cierre de worktrees -- vive en
> `.agent/rules/common/t3_ade_coordination.md`.

**Gate 1 (nunca se relaja):** antes de que un commit propio EXISTA en cualquier rama
compartida, la suite canonica completa corre sobre ESE commit (regla de arriba, sin excepcion).

**Gate 2 (push con la rama remota avanzada por otras sesiones):** si, al intentar publicar un
commit YA VERIFICADO por el Gate 1, la rama remota avanzo con commits de otras sesiones, el
merge de esos commits se verifica asi:
- Si el merge es disjunto en ficheros (ninguno tocado por ambos lados) **y** el auto-merge de
  Git no reporta conflicto de texto: ademas de `ast.parse`/sintaxis de los ficheros que SI
  cambiaron y confirmar que no quedan marcadores de conflicto (`<<<<<<<`), se exige ADEMAS
  (i) ausencia de dependencia de import cruzada entre los ficheros tocados por cada lado, y
  (ii) que ninguno de los ficheros tocados sea una superficie transversal de alto blast radius
  (`conftest.py`, `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `AGENTS.md`,
  `CLAUDE.md`, `bus/`, `runtime/`, `.agent/agents_config.py`). Si cualquiera de las tres
  condiciones falla, tratar como "mismo fichero compartido" (exige suite completa).
- Si el merge toca el mismo fichero en ambos lados: la suite completa SI debe correr antes de
  publicar -- nunca "suite focalizada" por `-k` (regla `-k` en `AGENTS.md` / [T1], WOT-2026-079d).
- El camino relajado del primer bullet NUNCA es alcanzable para el commit resultante de un
  MERGE: el `tested_commit_sha` del Gate 1 es el del commit padre, nunca el del merge commit.
  La "relajacion" ahorra la RE-suite solo cuando se demuestra ANTES de mergear que el merge es
  disjunto y seguro, nunca despues de que el merge commit ya existe.
- Si tras publicar el remoto volvio a avanzar (`non-fast-forward`), repetir el criterio arriba
  en la nueva ronda, sin acumular re-verificaciones completas solo porque ya se hizo una vez.

**Condiciones de rechazo del Gate 2 (default fail-closed):** el Gate 2 relajado NO aplica si
(1) no existe evidencia VERIFICABLE de que el lado entrante corrio su Gate 1 (`tested_commit_sha`
registrado, evento de bus, log de cierre citable -- no basta "presumiblemente"); (2) el lado
entrante toca una superficie transversal (lista arriba); (3) hay dependencia de import cruzada
entre los ficheros tocados por ambos lados; (4) el commit publicado es un merge commit cuyo
`tested_commit_sha` no coincide con el HEAD resultante; (5) han ocurrido 2+ intentos de push
rechazados consecutivos sin que ninguna ronda haya corrido la suite completa sobre el estado
integrado. El default es FAIL-CLOSED: el Gate 2 relajado es la excepcion estrecha, no el
comportamiento esperado por defecto.

**Alcance:** esta politica SOLO aplica a ramas o flujos donde exista, en algun punto del ciclo
de vida del commit, una verificacion equivalente a `assert_canonical_suite_green` (via
`--mark-ready` de un ticket formal, o via un registro explicito de `tested_commit_sha` en la
bitacora de un vuelo sin ticket). Sin esa evidencia, tratar como si el Gate 1 nunca se hubiera
verificado y exigir suite completa, sin excepcion.

**Riesgo residual declarado:** esta politica asume que cada sesion concurrente aplica su propio
Gate 1 antes de publicar. A diferencia de un equipo con CI real (que tiene un verificador
automatico TERCERO sobre el HEAD integrado), aqui no existe ningun verificador automatico
equivalente -- el riesgo es MAYOR que en un equipo con CI, no igual. `check_suite_freshness.py`
no es comparable: es local y depende de que `pre_handoff_guard` corra aguas abajo, lo cual no
ocurre en un push de vuelo sin ticket formal.
