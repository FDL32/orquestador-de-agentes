# Known Failure Patterns Registry

Registro canonico de patrones de fallo observados en el motor y reutilizables
en auditorias, cierre de tickets y diseno de barreras.

## Uso

- Cita los patrones como `FP-XXX`.
- Separa siempre hechos verificados de inferencias y fixes candidatos.
- Un patron puede registrar workarounds operativos sin fijar todavia la
  solucion estructural.

---

## FP-001: Drift bus -> STATE.md / TURN.md

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- El bus contiene un `STATE_CHANGED` mas reciente que `STATE.md`.
- `TURN.md` sigue apuntando a un rol anterior.
- `supervisor_state.json.last_processed_sequence` queda por detras del maximo
  `seq` del bus.

### Contrato / realidad verificada

- El bus es la autoridad canonica de hechos y transiciones.
- `STATE.md` y `TURN.md` son proyecciones derivadas.
- Un ticket puede quedar con `bus=READY_FOR_REVIEW` y
  `STATE.md=IN_PROGRESS` si la proyeccion no se materializa a tiempo.

### Causa raiz probable

El supervisor emite o deja pasar eventos canonicos, pero muere o sale por idle
antes de proyectarlos completamente a `STATE.md` y `TURN.md`.

### Mitigacion temporal

- Reconciliar el ticket desde el bus antes de relanzar agentes.
- Tratar el bus como fuente de verdad si `STATE.md` y `TURN.md` divergen.

### Fix estructural candidato

- Hacer durable la proyeccion de estado.
- O forzar reconciliacion automatica cuando `last_processed_sequence` quede por
  detras del bus.

### Tickets relacionados

- `WT-2026-224a`
- `WT-2026-216`
- `WT-2026-214`

---

## FP-002: builder_launch_unverified con ejecucion real

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- El bus emite `BUILDER_RELAUNCH_ATTEMPTED` con
  `outcome=builder_launch_unverified`.
- Poco despues aparece `BUILDER_EXIT` o `STATE_CHANGED -> READY_FOR_REVIEW`.

### Contrato / realidad verificada

- El launcher puede no verificar el arranque del Builder aunque la ventana si
  ejecute trabajo real.
- La ausencia de verificacion no implica necesariamente ausencia de ejecucion.

### Causa raiz probable

La verificacion post-spawn depende de una senal de identidad o lock mas fragil
que la ejecucion real del proceso lanzado.

### Mitigacion temporal

- Revisar si hay `BUILDER_EXIT` posterior antes de asumir relaunch fallido.
- Evitar relanzar automaticamente solo por `builder_launch_unverified`.

### Fix estructural candidato

- Hacer mas robusta la verificacion de arranque.
- O introducir reconciliacion retrospectiva cuando el bus confirma actividad del
  Builder tras el launch no verificado.

### Escalada conocida

Este patron puede aparecer como inicio de una cascada:

- `FP-002`: el launcher no verifica el arranque;
- `FP-001`: el supervisor o la proyeccion quedan por detras del bus;
- `FP-003`: el cierre o handoff posterior detecta round explicito sin lock
  durable.

Observado en la secuencia `WT-2026-224a` `seq=691..696`.

### Tickets relacionados

- `WT-2026-224a`
- `WT-2026-221a`

---

## FP-003: stale_builder_round por lock ausente

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- `HANDOFF_BLOCKED` con `reason=stale_builder_round`.
- El Builder tiene identidad de round explicita, pero `builder_lock.txt` falta
  o no es legible.

### Contrato / realidad verificada

- La proteccion por round puede bloquear closeout o handoff cuando no existe el
  lock esperado para ese round.
- El problema puede aparecer incluso despues de trabajo real del Builder.

### Causa raiz probable

Hay una discrepancia entre la identidad de round entregada al proceso y el
artefacto durable que debe respaldarla.

### Mitigacion temporal

- Contrastar el bloqueo con los ultimos eventos del bus antes de relanzar.
- Verificar si el Builder ya emitio `BUILDER_EXIT` o `READY_FOR_REVIEW`.

### Fix estructural candidato

- Endurecer el contrato de creacion y lectura del lock.
- Reducir la dependencia de artefactos transitorios no confirmados.

### Tickets relacionados

- `WT-2026-221b`
- `WT-2026-224a`

---

## FP-004: Composicion PowerShell multi-linea rota

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- En una ventana hija aparece `= : El termino '=' no se reconoce...`.
- O aparece `Token 'try' inesperado`.
- Observado durante `WT-2026-224a` en una ventana real del Builder.

### Contrato / realidad verificada

- La composicion por concatenacion de bloques PowerShell puede romperse si las
  variables de entorno se expanden antes de tiempo o si falta el salto de linea
  entre bloques.
- El proceso puede abrirse con una linea sintacticamente invalida sin que el
  launcher principal detecte bien la causa.

### Causa raiz probable

Interpolacion prematura de `$env:` o union incorrecta entre prefijos de entorno
y bloques `try { ... }` en el comando compuesto.

### Estado actual

El patron fue identificado y mitigado. El codigo actual ya contiene el separador
explicito entre el prefijo de entorno y el bloque de ejecucion; este registro
documenta la familia del fallo, no afirma que el launcher siga roto hoy.

### Mitigacion temporal

- Inspeccionar el comando generado antes de asumir un fallo semantico del
  Builder.
- Repetir el arranque solo con una version verificada del launcher.

### Fix estructural candidato

- Centralizar la construccion de comandos multi-linea.
- Anadir tests que validen el comando compuesto real, no solo fragmentos.

### Tickets relacionados

- `WT-2026-224a`

---

## FP-005: REVIEW_DECISION con blockers vacios

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- `REVIEW_DECISION` con `decision=CHANGES`.
- Poco despues aparece `HANDOFF_BLOCKED` con `reason=empty_blockers`.

### Contrato / realidad verificada

- Un `CHANGES` sin blockers estructurados deja al supervisor o al Builder sin
  instruccion accionable.
- La barrera puede dispararse aunque el review conceptualmente exista.

### Causa raiz probable

El bridge o el camino de review no siempre serializa blockers de forma
estructurada en el payload canonico.

### Mitigacion temporal

- Tratar el feedback del Manager como fuente operativa si el payload no trae
  blockers estructurados.
- Evitar cerrar el analisis solo en base al `HANDOFF_BLOCKED`.

### Fix estructural candidato

- Garantizar blockers estructurados en todo `REVIEW_DECISION=CHANGES`.
- O degradar el bloqueo a warning cuando falte estructura pero exista feedback

---

## FP-006: Falso blocker por interprete de review distinto al runtime canonico

**Estado de evidencia:** VERIFICADO

### Sintoma observable

- El Manager reejecuta tests focales con una `venv` o Python distinto al que
  uso `pytest-safe`.
- Aparece `ModuleNotFoundError` para dependencias runtime del destino
  (por ejemplo `openpyxl`) aunque:
  - `ruff` pasa;
  - `validate` esta en `0/0`;
  - `last-run.json` muestra suite canonica verde en `HEAD`.

### Contrato / realidad verificada

- En tickets `repo_destino`, la evidencia canonica de suite vive en
  `.agent/runtime/pytest-safe/last-run.json`.
- El interprete autoridad para esa suite puede ser el Python del destino o el
  resuelto por el launcher local, no necesariamente la `venv` del motor.
- Un `ModuleNotFoundError` en el entorno del reviewer no demuestra por si solo
  un defecto del ticket si el runtime canonico del destino si tiene la
  dependencia y la suite fresca en `HEAD` pasa.

### Causa raiz probable

El review mezcla dos entornos distintos:

- entorno del motor usado para inspeccion/auditoria;
- entorno runtime del destino usado por `pytest-safe` o por el launcher
  operativo del proyecto.

### Mitigacion temporal

- Leer `last-run.json` antes de emitir blocker.
- Reproducir los focales con el mismo interprete que figura en `command` dentro
  de `last-run.json`, o con el runtime explicitamente verificado por el launcher
  del destino.
- Si el fallo solo existe en la `venv` del motor, clasificarlo como mismatch de
  entorno de review, no como regresion del ticket.

### Fix estructural candidato

- Hacer que `manager_review` recuerde explicitamente esta comprobacion.
- Documentar en el destino las dependencias runtime verificadas por el launcher.

### Tickets relacionados

- `LEA-2026-001f`
  legible por otra via.

### Tickets relacionados

- `WT-2026-221b`
- `WT-2026-224a`

---

## FP-013: Rearranque desde fuente equivocada de verdad

**Estado de evidencia:** INFERENCIA RAZONABLE

### Sintoma observable

- El launcher o el operador relanza el agente equivocado porque `TURN.md` o
  `STATE.md` no reflejan el ultimo estado del bus.

### Contrato / realidad verificada

- La decision operativa correcta debe derivarse del bus cuando este es legible.
- Las proyecciones documentales son fallback o vistas derivadas, no autoridad
  primaria.

### Verificacion parcial

- La arquitectura bus-first del launcher esta verificada.
- La aplicacion de este patron como causa concreta en una instancia futura debe
  confirmarse caso por caso contra el bus y el launcher.

### Causa raiz probable

Se usa una proyeccion stale para decidir rol o accion en vez de consultar el
estado derivado del bus.

### Mitigacion temporal

- Confirmar el ultimo `STATE_CHANGED` del bus antes de relanzar.
- Si hay drift, reconciliar primero y solo despues lanzar.

### Fix estructural candidato

- Mantener el launcher y los flujos manuales alineados con el estado derivado
  del bus.
- Explicitar mas claramente en tooling y prompts cual es la fuente de verdad.

### Tickets relacionados

- `WT-2026-216`
- `WT-2026-224a`

---

## FP-007: Stub fail-open en codigo topologia-aware elevado a blocker arquitectonico

**Estado de evidencia:** VERIFICADO EN CODIGO Y REVIEW

### Sintoma observable

- Un metodo de `repo_motor` que depende de `motor_root` (resolucion de agente,
  discovery de paths, inyeccion de config) captura `RuntimeError` cuando
  `_motor_root_or_raise()` falla y crea un stub o fallback silencioso.
- El stub permite avanzar en pruebas aisladas o en rondas tacticas, pero
  Manager review para un ticket de codigo que formaliza la topologia lo
  identifica como blocker arquitectonico.

### Contrato / realidad verificada

- En la topologia `repo_motor + repo_destino`, cualquier codigo que degrada
  su comportamiento silenciosamente cuando `motor_root` no es resoluble viola
  el contrato topologico.
- Un fail-open en una ruta de decision (agent spec, cwd de subprocess, path
  discovery) no es un fallback defensivo; es una ruta de ejecucion incorrecta
  disfrazada de resiliencia.

### Causa raiz probable

Se acepta el stub como solucion tactica para desbloquear una ronda
Builder/Manager, sin extraerlo a un ticket de compatibilidad con scope y
aprobacion explicita.

### Mitigacion temporal

- Si el stub es inevitable para avanzar, abrirlo como ticket separado de
  compatibilidad antes de cerrar el ticket principal.

### Fix estructural candidato

- En codigo topologia-aware: llamar a `_motor_root_or_raise()` directamente
  y dejar que `RuntimeError` propague. No capturar la excepcion salvo en el
  perimetro de tests con topologia explicita.
- En tests: usar `_configure_motor_topology(project_root, motor_root)` o
  patron equivalente que construya un `motor_destination_link.json` real y
  un `manager.md` en la ruta esperada. No depender de mocks de
  `_motor_root_or_raise()` como setup principal; preferir topologia explicita
  con fixture real.

### Tickets relacionados

- `WT-2026-237a`

---

## FP-008: Claims sobre git emitidos desde un git bloqueado por dubious ownership

**Estado de evidencia:** VERIFICADO EN PROCESO (sesion publicacion Crear_Texto_LLM, 2026-06-24)

### Sintoma observable

- El agente audita un `repo_destino` cuyo git el sandbox reporta con "dubious
  ownership". Toda lectura git (`status`, `log`, `ls-files`) falla.
- En vez de resolver el bloqueo, el agente emite claims como hechos: "el email
  viajara al historial", "hay rutas absolutas en archivos versionados", "no pude
  verificar git status". Son inferencias presentadas como verificaciones.

### Contrato / realidad verificada

- Un claim sobre estado git (email en historia, paths trackeados, secretos en
  blobs) solo es valido si se sostiene contra `git log/status/ls-files` reales.
- El bloqueo por dubious ownership NO es evidencia de nada; es un obstaculo
  trivial de resolver, no una limitacion del repo.

### Causa raiz probable

Se acepta el primer obstaculo (git bloqueado) como frontera de la auditoria en
vez de resolverlo. El relato sustituye a la evidencia.

### Mitigacion temporal

- Antes de cualquier claim sobre git en un destino:
  `git config --global --add safe.directory "C:/ruta/al/repo_destino"`
- Luego correr `git log/status/ls-files` reales y etiquetar como INFERENCIA solo
  lo genuinamente no verificable.

### Fix estructural candidato

- El bootstrap de destino (`orchestrator_destination_bootstrap.md`) podria incluir
  un preflight que resuelva `safe.directory` para el `destination_root` resuelto
  desde `motor_destination_link.json`, dejando git legible desde el primer comando.

### Tickets relacionados

- (sesion ad-hoc, sin ticket; candidato a follow-up de bootstrap de destino)

---

## FP-009: mailmap de git filter-repo con identidad asumida en vez de verificada

**Estado de evidencia:** VERIFICADO EN GIT (sesion publicacion Crear_Texto_LLM, 2026-06-24)

### Sintoma observable

- Se prepara `git filter-repo --mailmap` para reescribir el email del historial,
  asumiendo el nombre del autor (ej. un nombre humano inventado) sin verificar.
- Si el `name` del mailmap no coincide EXACTO con el de la historia, el rewrite
  puede quedar incompleto y dejar commits con la identidad vieja.
- Caso adicional GitHub: usar un noreply generico
  (`noreply@users.noreply.github.com`) NO vincula los commits a la cuenta del
  usuario. El formato correcto es `<id>+<username>@users.noreply.github.com`.

### Contrato / realidad verificada

- El nombre/email reales se leen de la historia, no se asumen:
  `git log --all --format='%an <%ae>%n%cn <%ce>' | sort -u`.
- El noreply de GitHub que vincula a la cuenta requiere el id numerico,
  resoluble por la API de usuarios de GitHub o herramienta equivalente
  (campo `id`).

### Causa raiz probable

Prisa por dejar el comando "listo" sin el precheck de identidad. El usuario
esceptico lo marco como `NO VERIFICADO`.

### Mitigacion temporal

- Precheck obligatorio de identidades antes de construir el mailmap.
- Resolver el id de GitHub del usuario antes de elegir el email noreply.

### Fix estructural candidato

- En cualquier skill/prompt de publicacion que reescriba email, exigir el
  precheck `git log --all --format=...` y el id de GitHub como pasos previos
  no salteables.

### Tickets relacionados

- (sesion ad-hoc, sin ticket)

---

## FP-010: classify_publication.py marca falso BLOQUEADO_POR_SECRETO por palabra-patron

**Estado de evidencia:** VERIFICADO POR BYTES (sesion publicacion Crear_Texto_LLM, 2026-06-24)

### Sintoma observable

- `classify_publication.py` emite `BLOQUEADO_POR_SECRETO` sobre archivos que NO
  contienen ningun secreto real:
  - codigo que usa `api_key`, `Authorization`, `Bearer`, `X-API-KEY` como nombres
    de variable/parametro leidos de `os.getenv(...)`, sin literal hardcodeado;
  - tests de redaccion de secretos cuyas fixtures son secretos ficticios
    deliberados (`sk-abcdef...`, JWT de ejemplo) para probar que `redact()` los
    censura;
  - documentos de auditoria que citan los patrones (`sk-...`, `AKIA...`) como
    texto explicativo.

### Contrato / realidad verificada

- El veredicto del script es `[RELATO]` inicial, no evidencia final
  (lo dice el propio `audit_git_publication.md`).
- Un finding de secreto debe verificarse por bytes: buscar un literal largo
  ASIGNADO (`=\s*['\"][A-Za-z0-9_\-]{20,}['\"]`). Si solo aparecen los nombres
  de cabecera/variable, es falso positivo irreductible.

### Causa raiz probable

El clasificador hace match por patron lexico de palabras-cabecera, sin distinguir
nombre de variable de valor asignado ni fixture de test de secreto vivo.

### Mitigacion temporal

- Verificar cada finding por bytes con `git cat-file -p <blob>` + grep del
  patron real antes de tratarlo como secreto.
- Falsos positivos irreductibles (codigo de producto legitimo): documentar como
  `accepted_health_exception` con evidencia, propietario y razon. NO purgar
  historia ni romper codigo para silenciar el patron.
- Falsos positivos en legacy ya retirado del tree pero vivo en blobs de historia:
  purgar la ruta legacy con `git filter-repo --invert-paths --path <legacy>/`.

### Fix estructural candidato

- Endurecer `classify_publication.py` para exigir un valor asignado (no solo la
  palabra-cabecera) antes de marcar `secret_pattern`, y para allowlistar
  fixtures de modulos de redaccion conocidos.

### Tickets relacionados

- (sesion ad-hoc, sin ticket; candidato a follow-up del clasificador)

---

## FP-011: guard_paths bloquea la memoria persistente del harness (deuda de infraestructura)

**Estado de evidencia:** VERIFICADO EN CODIGO (sesion publicacion Crear_Texto_LLM, 2026-06-24)

### Sintoma observable

- El agente intenta escribir memoria persistente del harness en
  `C:\Users\<user>\.claude\projects\<proj>\memory\*.md`.
- El hook `guard_paths.py` bloquea con `guard_paths: fuera del repo`
  (`.agent/hooks/guard_paths.py:144`, `_is_within_repo` falla) porque la ruta
  de memoria del harness vive FUERA del arbol de cualquier `repo_root` por
  diseno. Parquear el cwd en el motor no ayuda: el bloqueo es por la ruta
  destino, no por el cwd.

### Contrato / realidad verificada

- El guard es fail-closed correcto: protege contra escrituras fuera del repo.
- Pero la memoria del harness NO es estado del repo; es estado del agente y
  debe poder escribirse. El guard no tiene allowlist para esa ruta.
- Resultado: conflicto estructural. No es fallo de proceso del agente; es deuda
  de infraestructura del guard.

### Causa raiz probable

`_is_protected_path` rechaza toda ruta no relativa a `repo_root` sin una
allowlist explicita para el directorio de memoria del harness.

### Mitigacion temporal

- NO desactivar el guard ni abrir excepcion ad-hoc por escritura.
- Persistir aprendizajes en una superficie DENTRO del repo del motor
  (este archivo, `docs/`) hasta resolver el conflicto.

### Fix estructural candidato

- Anadir al guard una allowlist de la ruta de memoria del harness
  (`~/.claude/projects/*/memory/`) como write_root permitido, o documentar
  formalmente que esa ruta queda fuera del scope del guard estricto.
- Requiere ticket explicito del motor (no abrir sin instruccion del usuario).

### Tickets relacionados

- (deuda abierta, sin ticket; requiere decision del usuario para abrir WP del motor)

---

## FP-012: Mock-drift en test de upgrade -> falso verde sobre operacion destructiva

**Estado de evidencia:** VERIFICADO POR BYTES

### Sintoma observable

- `tests/unit/test_upgrade.py` pasa en verde, pero NO ejercita las copias de
  archivos reales del codigo bajo test.
- La suite verde da confianza sobre una operacion destructiva (copia de arboles
  con `shutil.copytree`/`copy2`) que en realidad nunca se intercepto.

### Contrato / realidad verificada

- `tests/unit/test_upgrade.py:12` importa `UpgradeManager` de
  `scripts.upgrade_agent_system`.
- Pero parchea `scripts.upgrade.shutil.copytree` / `scripts.upgrade.shutil.copy2`
  (8 ocurrencias: lineas 46-47, 83-84, 112-113, 204-205) -> un MODULO DISTINTO.
- El codigo bajo test llama `shutil` directo en
  `scripts/upgrade_agent_system.py:148,151,199,202`. Esos `copytree`/`copy2`
  NO se interceptan porque el patch apunta al `shutil` de `scripts.upgrade`,
  no al de `scripts.upgrade_agent_system`.
- `upgrade.py` y `upgrade_agent_system.py` son forks casi identicos, cada uno
  con su `class UpgradeManager`. `README.md:104` declara canonico `upgrade.py`,
  pero el test ejercita el otro fork.

### Causa raiz probable

Duplicacion estructural: dos forks de `UpgradeManager` (`upgrade.py` vs
`upgrade_agent_system.py`) con `shutil` propio en cada modulo. El test mezcla
import de un fork con patch del otro (anti-patron mock-drift documentado en
AGENTS.md): el patch apunta a `X` pero el codigo llama a `Y`.

### Mitigacion temporal

- No fiarse del verde de `test_upgrade.py` como evidencia de que la copia de
  archivos del upgrade esta cubierta.
- Tratar el verde como falso verde hasta corregir el target del patch.

### Fix estructural candidato

- F2 (ticket `code`, prioridad alta): repuntar los patch a
  `scripts.upgrade_agent_system.shutil.*` (el modulo realmente importado), o
  resolver la duplicacion `UpgradeManager` (unificar forks) y alinear `README`.
- Barrera de salida: el test debe FALLAR si se rompe `copytree`/`copy2` del
  codigo bajo test (probar fail-sin-fix monkeypatcheando a raise).
- Dependencia de orden: la promocion del aprendizaje a `observations.jsonl`
  espera a F1 (migracion de schema via `scripts/migrate_observations.py`),
  pendiente por schema drift de `applies_to`.

### Tickets relacionados

- F1 (pendiente de abrir): migracion de schema de `observations.jsonl`
  (`scripts/migrate_observations.py --apply` + `validate_observations.py
  --strict`). Desbloquea promover este patron a memoria portable.
- F2 (pendiente de abrir): fix de este mock-drift + deduplicacion de
  `UpgradeManager`.

---

## FP-014: `_transport_api` sin `max_tokens` -- modelo razonador agota su presupuesto en `reasoning_content` sin emitir `content`

**Estado de evidencia:** VERIFICADO POR MUTATION-VERIFY (sesion 2026-09-28, bucle
L720 sobre WOT-2026-068k)

### Sintoma observable

- Una ronda de `ensemble_dispatch.py loop-round` contra un backend `nan_api` o
  `nvidia_api` cuyo modelo tiene razonamiento interno (campo
  `reasoning_content` en la respuesta, ej. `mimo-v2.6-flash`) queda colgada
  sin error explicito y sin CPU consumida (`tasklist` muestra `Tiempo de CPU:
  0:00:00` en Windows) durante minutos, mucho mas alla del tiempo tipico de
  esa misma ronda con un payload equivalente.
- Cuando SI produce un veredicto, aparece como
  `empty_content_despite_sentinel: el stream SSE cerro con centinela y
  content vacio` en el scorecard (`ensemble_dispatch.py:902`), o como MUDA en
  `check_loop_execution.py`.
- Reproducido con `curl` directo (sin el wrapper): con `"max_tokens": 10`, el
  modelo devuelve `"content": ""` y `"finish_reason": "length"`, con
  `reasoning_content` mostrando que el presupuesto se agoto pensando ("*The
  user just said 'ping'. This is*...") antes de emitir contenido.

### Contrato / realidad verificada

- `_transport_api` (`scripts/ensemble_dispatch.py`) construia el body sin el
  campo `max_tokens`. Sin limite del lado del cliente, un modelo razonador
  puede consumir un numero de tokens de salida arbitrariamente grande en
  `reasoning_content` sin llegar nunca al `content` final ni al centinela
  `[DONE]` del stream SSE (WOT-2026-063c).
- El guard `empty_content_despite_sentinel` (I3, `ensemble_dispatch.py:900-907`)
  ya rechazaba correctamente una respuesta con `content` vacio -- el defecto
  no estaba ahi, sino en que el cliente nunca acotaba cuanto podia tardar el
  modelo en llegar a ese vacio (o a emitir contenido real).
- El tamano del bundle/payload de ENTRADA NO es la causa: medido contra el
  scorecard historico, varios backend_key (BA05, BA11, BA13) tienen exitos
  con `input_bytes` de hasta ~109 KB, mientras que el mismo backend
  (`nan_mimo_flash`/BA22) fallaba con payloads de entrada mucho menores. El
  eje real es la fiabilidad intrinseca de cada backend_key con modelos
  razonadores, no el tamano del prompt.

### Causa raiz probable

Ausencia de `max_tokens` en el body de `_transport_api`. Un modelo con
razonamiento interno no tiene limite de cliente sobre cuanto puede "pensar"
antes de responder; con un prompt largo y complejo (7 preguntas de auditoria
sobre un bundle de revision), el razonamiento puede crecer sin cota util.

### Mitigacion aplicada (fix estructural, no solo temporal)

- `_transport_api` ahora envia `"max_tokens": _API_MAX_TOKENS` (8192) en el
  body de toda peticion `nan_api`/`nvidia_api`.
- Mutation-verify (curl directo, mismo endpoint que `_transport_api`):
  - `sin_fix` (equivalente, `max_tokens: 10`): `content=""`,
    `finish_reason="length"`, `reasoning_content` no vacio -- confirma el
    atasco.
  - `con_fix` (`max_tokens: 8192`): `content` real y completo, solo 17
    tokens de `reasoning_content` -- el limite generoso no fuerza
    razonamiento largo, solo evita que crezca sin cota.
- El guard `empty_content_despite_sentinel` NO se toco: sigue fallando
  explicito si, incluso con 8192 tokens de presupuesto, el modelo no emite
  `content` (I6 preservado).
- Tests focales (`tests/unit/test_ensemble_dispatch.py -k transport_api`):
  5/5 passed sin cambios -- ningun test fijaba la forma exacta del body.

**LIMITE MEDIDO del fix (2026-09-28, mismo dia):** con un prompt SIMPLE
("ping"), `max_tokens: 8192` resuelve el atasco (ver mutation-verify arriba).
Con un prompt COMPLEJO real (bundle de auditoria de ~26 KB, 7 preguntas de
revision), la MISMA ronda contra el MISMO backend (`nan_mimo_flash`/BA22)
paso de "colgada sin resolver" a "`empty_content_despite_sentinel` en tiempo
razonable" -- el fix convierte un cuelgue silencioso en un FALLO EXPLICITO
rapido (mejora real: ya no bloquea la sesion indefinidamente), pero NO
garantiza que el modelo produzca `content` con prompts complejos. Backends
con este patron deben tratarse como NO FIABLES para bundles de auditoria
grandes, no solo como "lentos": el guard barato es no usarlos para esa
clase de payload, no subir mas `max_tokens` (subir el limite alarga el
`reasoning_content` sin garantia de que ese margen adicional se traduzca en
`content` real).

### Barrera de preflight (IMPLEMENTADA 2026-09-28, cobertura PARCIAL medida)

- El coste medido de este patron en una sola sesion: ~1 hora persiguiendo un
  4o backend para completar un bucle 1->9->2, con multiples reintentos ciegos
  contra el mismo backend_key colgado, antes de aislar la causa con una
  prueba directa (`curl`) fuera del wrapper.
- Implementado `ensemble_dispatch.py preflight` (`preflight_profile()` +
  `_cmd_preflight`, mismo fichero): smoke de contenido NO trivial (pregunta
  de 3 pasos -- suma, antonimo, repetir nonce -- en vez de un simple "ping"),
  timeout corto (60s por defecto, vs 300s del dispatch real), veredicto por
  CONTENIDO (el nonce debe aparecer literal en la respuesta, igual criterio
  que `smoke_profile`). Uso: `ensemble_dispatch.py preflight --backend-keys
  BA05,BA11,BA13,BA22`.
- Secuencial, no paralelo: el proyecto no tenia precedente de concurrencia en
  este modulo y anadirla es expansion de alcance propia. Peor caso con 5
  backends: 5*60s=300s, comparable a UNA ronda con el timeout normal.

**COBERTURA MEDIDA, NO ASUMIDA:** se ejecuto `preflight --profile
challenger_nan_mimo_flash` (el backend que colgo/fallo hoy con el bundle
real) DESPUES de confirmar su fallo con el bundle completo. Resultado:
`alive: true`, respuesta correcta con el nonce -- **el preflight de 3 pasos
NO reproduce el fallo que si aparece con el bundle real de ~26 KB / 7
preguntas de auditoria**. Conclusion honesta: esta barrera detecta backends
MUERTOS o con problemas de transporte basicos (cuota, timeout de red, 402/504),
pero NO predice de forma fiable el patron "razona demasiado con contenido
complejo y nunca emite `content`" -- ese patron parece depender del volumen/
complejidad real del payload, no solo de que el prompt tenga "algo" de
razonamiento. Sigue siendo valioso (evita perder tiempo con backends
GENUINAMENTE caidos antes del fanout), pero NO es una garantia de que un
backend que pasa el preflight aguantara el bundle real.

### Fix estructural aun pendiente

- Preflight con un fragmento REAL del bundle (no un prompt sintetico de 3
  pasos) truncado a un tamano manejable, para acercar mas la señal al
  comportamiento bajo el payload real -- candidato de mejora, no implementado.
- Declarar explicitamente, en el recibo del bucle, que backends se probaron
  en preflight, cuales pasaron, y que esa señal es PARCIAL (no predictiva del
  100% de los fallos) -- para que quien lea el recibo no sobre-confie en un
  preflight verde.

### Tickets relacionados

- (sesion ad-hoc 2026-09-28, sin ticket abierto aun; candidato a ficha nueva
  para refinar el preflight con fragmento de bundle real)
