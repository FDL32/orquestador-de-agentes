# Work Plan - WOT-2026-019p

## Metadata
- **ID:** WOT-2026-019p
- **Estado:** COMPLETED
- **deliverable_type:** code
- **Titulo:** Retry acotado en write_artifact_atomic ante PermissionError transitorio de os.replace (WinError 5)
- **Creado:** 2026-07-07
- **Prioridad:** Media
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Anadir un retry con backoff acotado ante PermissionError transitorio
(WinError 5 en Windows) alrededor del rename atomico de
write_artifact_atomic (`bus/supervisor.py`), extraido a dos funciones de
modulo (`_replace_once_or_none` y `_atomic_replace_with_retry`) para no
elevar la complejidad ciclomatica de write_artifact_atomic por encima del
limite C90=10 (ruff C901) y sin anidar un try/except dentro de un for
(ruff PERF203), preservando el fail-closed si el rename sigue fallando
tras agotar los reintentos. Exito verificable con dos tests nuevos en
`tests/test_approval_state_revision_and_skill_access.py` (positivo y
negativo) mas `ruff check` en exit code 0 sobre `bus/supervisor.py`.

## Contexto / Root Cause

tests/test_supervisor.py::test_bootstrap_bus_precedence_over_turn_divergence
fallo 1 vez con PermissionError [WinError 5] Acceso denegado durante el
rename atomico .tmp_XXXX.tmp -> supervisor_state.json. Evidencia: log de
019m (2026-07-06); el mismo test aislado paso 3/3 y una re-corrida completa
de la suite sobre el mismo HEAD dio exit 0, transitorio confirmado, no un
fallo deterministico de logica.

Superficie exacta: bus/supervisor.py, metodo write_artifact_atomic,
bloque l.234-249:

    fd, temp_path = tempfile.mkstemp(
        dir=str(artifact_path.parent), prefix=".tmp_", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(temp_path, str(artifact_path))
    except Exception:
        import contextlib
        with contextlib.suppress(OSError):
            os.unlink(temp_path)
        raise

El for attempt in range(max_retries) externo (l.195) solo reintenta ante
FileExistsError del lock (conflicto OCC/lock), no ante un PermissionError
del os.replace: el except Exception de l.244 limpia el temp file y
re-lanza sin reintentar. Causa probable: otro proceso (antivirus,
indexador de Windows, handle residual) retiene brevemente el .tmp entre
el open y el rename.

## Non-goals

- No se toca el retry OCC externo del lock (for attempt in
  range(max_retries), l.195-216) ni su logica de deteccion de lock
  obsoleto (stale lock recovery, l.200-206).
- No se cambia la firma de write_artifact_atomic (parametros, tipo de
  retorno, excepciones publicas).
- No se anaden dependencias externas nuevas; el retry usa unicamente
  time.sleep (ya importado en el metodo, l.190) y manejo de excepciones
  estandar.
- No se modifica el comportamiento en el caso feliz (sin PermissionError):
  el retorno y el contenido escrito son identicos a hoy.
- No se usa `# noqa: C901` bajo ninguna circunstancia para resolver el
  hallazgo de complejidad; la resolucion es la extraccion de las 2
  funciones descrita en la Fase 1.1 y en Decision Arquitectonica.
- No se usa `# noqa: PERF203` como primera respuesta al hallazgo de
  overhead try/except-en-loop; la Fase 1.1 exige primero la
  reestructuracion en 2 funciones (verificada empiricamente por el
  Manager antes de aprobar este plan: ruff check da "All checks passed!"
  con esa estructura). Un `# noqa: PERF203` puntual y documentado solo
  se autoriza como ultimo recurso si el Manager, en el review, confirma
  que la reestructuracion entregada por el Builder difiere de la
  especificada y ruff sigue reportando PERF203 pese a ello.
- No se usa un per-file-ignore en pyproject.toml para PERF203 sobre
  bus/supervisor.py (silenciaria PERF203 en todo el archivo, no solo en
  el punto puntual; el unico precedente de ese ignore en el repo es
  sobre un archivo de tests, no sobre codigo de produccion).

## Files Likely Touched

- bus/supervisor.py
- tests/test_approval_state_revision_and_skill_access.py

## Plan de Implementacion

### Tipos de Tareas
| Icono | Tipo | Ejecutor |
|-------|------|----------|
| Bot | TAREA AGENTE | Builder |

### Fase 1: Retry acotado extraido a 2 funciones de modulo sin try/except en el loop (Bot)
#### 1.1: Bot Anadir _replace_once_or_none + _atomic_replace_with_retry y usarlos en write_artifact_atomic
- **Tipo:** TAREA AGENTE
- **Archivo:** bus/supervisor.py
- **Accion:** Modificar
- **Descripcion:** ACTUALIZADO dos veces tras hallazgos de ruff:
  (1) C901 (write_artifact_atomic supero complejidad 10 con el bucle
  inline) resuelto extrayendo un helper de modulo; (2) PERF203
  (try-except dentro de un for incurre en overhead) disparado por el
  helper de un solo nivel, resuelto ahora separando el intento
  individual del bucle de reintento en DOS funciones de modulo, ninguna
  de las cuales tiene un try/except anidado dentro de un for. Ambas
  verificadas empiricamente con ruff check usando el extend-select real
  del proyecto (E, F, B, S, RUF, N, W, I, PERF, UP, C90, ERA, SIM):
  All checks passed!.

  Definir, en bus/supervisor.py, ANTES de class SequentialTicketSupervisor
  (antes de la linea 93 actual), dos funciones de modulo nuevas, en este
  orden:

  1. _replace_once_or_none(temp_path: str, artifact_path: Path) ->
     PermissionError | None: intenta os.replace(temp_path,
     str(artifact_path)) dentro de un try/except que NO esta dentro de
     ningun for (es una funcion de nivel superior sin loop). Si tiene
     exito, no retorna nada explicito (retorno implicito None). Si
     captura PermissionError, retorna el objeto de excepcion capturado
     (except PermissionError as exc: return exc) en vez de re-lanzarlo o
     silenciarlo.

  2. _atomic_replace_with_retry(temp_path: str, artifact_path: Path,
     attempts: int = 3) -> None: un bucle for replace_attempt in
     range(attempts) SIN try/except propio (el try/except vive
     unicamente dentro de _replace_once_or_none). En cada iteracion,
     llama a last_error = _replace_once_or_none(temp_path,
     artifact_path); si last_error is None, hace return inmediato
     (exito); si no, y no es el ultimo intento
     (replace_attempt < attempts - 1), hace un import time local y
     time.sleep(0.01 * (replace_attempt + 1)) antes de continuar a la
     siguiente iteracion. Si el for termina sin haber retornado (los
     attempts intentos fallaron), hace raise last_error fuera del for,
     re-lanzando el objeto de excepcion guardado de la ultima iteracion
     (el traceback original permanece adjunto al objeto en Python 3; no
     se necesita raise ... from porque no hay un except activo en el
     punto del raise).

  Este diseno preserva el mismo backoff, el mismo limite de intentos (3)
  y el mismo criterio de excepcion (PermissionError generico, sin
  sys.platform ni .winerror) que las versiones previas, solo
  reestructurado en 2 funciones para que ningun for contenga un
  try/except en su cuerpo. En write_artifact_atomic, dentro del bloque
  try existente de la escritura atomica (l.240-249 en la numeracion
  pre-019p), la unica linea os.replace(temp_path, str(artifact_path)) se
  sustituye por una sola linea de llamada:
  _atomic_replace_with_retry(temp_path, artifact_path). El except
  Exception exterior de ese mismo bloque (limpieza del .tmp con
  os.unlink + raise) no cambia: sigue envolviendo la llamada al helper
  igual que antes envolvia la linea de os.replace directa, preservando
  el fail-closed. bus.supervisor.os.replace sigue siendo el punto de
  monkeypatch correcto para los tests de la Fase 2, porque
  _replace_once_or_none vive en el mismo modulo bus.supervisor y sigue
  invocando os.replace (el modulo os importado a nivel de modulo, linea
  4); ningun test de la Fase 2 cambia su mecanismo de monkeypatch.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** git diff -- bus/supervisor.py muestra: (i)
  dos funciones de modulo nuevas, _replace_once_or_none y
  _atomic_replace_with_retry, definidas antes de class
  SequentialTicketSupervisor, ninguna con un try/except anidado dentro de
  un for; (ii) dentro de write_artifact_atomic, el bloque try de la
  escritura atomica reemplaza el bucle inline por una unica linea de
  llamada a _atomic_replace_with_retry; (iii) el resto del metodo
  write_artifact_atomic (lock, OCC, lectura de revision) permanece
  byte-identico a la version pre-019p. ruff check bus/supervisor.py sale
  con exit code 0, sin C901 (write_artifact_atomic recupera complejidad
  <=10) y sin PERF203 (ninguna de las 2 funciones nuevas tiene
  try/except dentro de un for; verificado empiricamente por el Manager
  en una reproduccion aislada con el extend-select real del proyecto
  antes de aprobar este plan).
- **Si falla:** Si tras esta reestructuracion ruff check SIGUE
  reportando C901 o PERF203 sobre cualquiera de las 2 funciones nuevas o
  sobre write_artifact_atomic, el Builder ejecuta ruff check
  bus/supervisor.py y pega el output literal en execution_log, y escala
  al Manager con ese output antes de anadir cualquier noqa (ver
  Non-goals y Decision Arquitectonica: el noqa C901 sigue prohibido; un
  noqa PERF203 puntual solo esta autorizado como ultimo recurso si el
  Manager confirma en el review que ninguna reestructuracion adicional
  es razonable, no como primera respuesta del Builder).

### Fase 2: Test de barrera cross-platform (Bot)
#### 2.1: Bot Test positivo, retry exitoso ante PermissionError transitorio
- **Tipo:** TAREA AGENTE
- **Archivo:** tests/test_approval_state_revision_and_skill_access.py
- **Accion:** Modificar (anadir tests nuevos junto a
  test_supervisor_write_artifact_atomic y variantes existentes)
- **Descripcion:** Anadir la funcion de test
  test_supervisor_write_artifact_atomic_retries_transient_permission_error
  con parametros (tmp_path, monkeypatch): instanciar
  SequentialTicketSupervisor igual que test_supervisor_write_artifact_atomic
  (mismo patron de collaboration_dir, runtime_dir, auto_sync=False).
  Monkeypatchear bus.supervisor.os.replace con una funcion que use un
  contador (closure o list mutable) para lanzar PermissionError(5,
  "Access is denied") en la 1a invocacion y, en la 2a invocacion,
  delegar al os.replace real (guardar referencia al original ANTES de
  monkeypatchear, via original_replace = bus.supervisor.os.replace, y
  llamarlo dentro del fake). Llamar
  supervisor.write_artifact_atomic(test_file, new_content) y verificar:
  (a) no propaga ninguna excepcion; (b) el valor de retorno (revision)
  no es None; (c) test_file.read_text(encoding="utf-8") == new_content;
  (d) el contador de invocaciones del fake es exactamente 2. El test no
  depende de sys.platform ni asume Windows: construye el PermissionError
  manualmente y no lee el atributo winerror (Windows-only).
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** El test nuevo, ejecutado solo con pytest
  apuntando a
  tests/test_approval_state_revision_and_skill_access.py y el nombre
  test_supervisor_write_artifact_atomic_retries_transient_permission_error
  con -v, pasa (exit 0) DESPUES del fix de la Fase 1
  (_replace_once_or_none + _atomic_replace_with_retry en uso). MUTATION:
  revirtiendo temporalmente el call-site de write_artifact_atomic a la
  linea directa os.replace(temp_path, str(artifact_path)) sin retry (o
  haciendo que _atomic_replace_with_retry haga return tras la primera
  llamada a _replace_once_or_none sin reintentar), el mismo test FALLA
  (la PermissionError de la 1a invocacion se propaga sin llegar a la 2a).
  El Builder documenta en execution_log el comando literal FAIL-sin-fix
  y PASS-con-fix.
- **Si falla:** Escalar al Manager si el monkeypatch de os.replace no es
  interceptable en el punto esperado (p.ej. si el import de os en
  bus/supervisor.py cambiase de forma); no improvisar un mecanismo de
  fallo distinto sin documentarlo.

#### 2.2: Bot Test negativo, fail-closed tras agotar reintentos
- **Tipo:** TAREA AGENTE
- **Archivo:** tests/test_approval_state_revision_and_skill_access.py
- **Accion:** Modificar (anadir junto al test de 2.1)
- **Descripcion:** Anadir la funcion de test
  test_supervisor_write_artifact_atomic_reraises_after_exhausting_replace_retries
  con parametros (tmp_path, monkeypatch): mismo patron de instanciacion.
  Monkeypatchear bus.supervisor.os.replace con una funcion que SIEMPRE
  lanza PermissionError(5, "Access is denied") en las 3 invocaciones (o
  las que defina attempts en _atomic_replace_with_retry, por defecto 3). Verificar con pytest.raises(PermissionError)
  que supervisor.write_artifact_atomic(test_file, new_content) re-lanza
  la excepcion original tras agotar los reintentos (no la oculta ni la
  convierte en ConcurrentStateError ni en ningun otro tipo). Verificar
  tambien que el archivo temporal con prefijo .tmp_ y sufijo .tmp no
  queda huerfano en collaboration_dir tras la excepcion (el except
  Exception exterior de l.244-249 ya limpia el temp con os.unlink; el
  test confirma que list(collaboration_dir.glob) para ese patron da
  lista vacia despues de la excepcion).
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** El test pasa (exit 0) tras el fix de la
  Fase 1 (helper _atomic_replace_with_retry en uso; confirma que el
  fail-closed final sigue re-lanzando en vez de tragarse el error
  indefinidamente). No requiere mutation adicional: este test ya pasa
  incluso SIN el fix de la Fase 1 (hoy tambien re-lanza, solo que en el
  primer intento); su proposito es fijar el contrato de fail-closed para
  que un futuro cambio no lo rompa silenciosamente. El Builder lo
  documenta como test de regresion, no como test que distingue
  pre/post-fix.
- **Si falla:** Escalar al Manager si el temp file queda huerfano tras
  agotar los reintentos (indicaria que el cleanup de l.246-248 no cubre
  el nuevo bucle).

### Fase 3: Verificacion y cierre de calidad (Bot)
#### 3.1: Bot Gates de calidad y suite completa
- **Tipo:** TAREA AGENTE
- **Archivo:** N/A (solo comandos)
- **Accion:** Verificar
- **Descripcion:** Ejecutar en orden: ruff check sobre bus/supervisor.py
  y tests/test_approval_state_revision_and_skill_access.py; la suite
  completa via el runner del proyecto (run_pytest_safe con nivel all o
  el equivalente documentado en AGENTS.md) y registrar el
  tested_commit_sha; el comando de validacion del controller con flags
  --validate --json --project-root apuntando al punto actual. Los tres
  comandos deben salir en verde antes de marcar READY_FOR_REVIEW.
- **Riesgo:** Bajo
- **Criterio de Aceptacion:** ruff check exit 0 sin warnings sobre los 2
  archivos tocados; la suite completa termina en exit 0 y su
  tested_commit_sha coincide con el HEAD del commit de entrega; la
  validacion del controller reporta errors en 0.
- **Si falla:** Si la suite completa revela OTRO flaky no relacionado
  (distinto de este ticket), documentarlo en execution_log y escalar al
  Manager en vez de intentar arreglarlo fuera de scope.

## Calidad

| Fase | Comando de verificacion |
|------|--------------------------|
| 1.1 | git diff -- bus/supervisor.py (confirma _replace_once_or_none + _atomic_replace_with_retry extraidas + call-site de 1 linea); ruff check bus/supervisor.py (exit 0, sin C901 y sin PERF203) |
| 2.1 | pytest tests/test_approval_state_revision_and_skill_access.py -k test_supervisor_write_artifact_atomic_retries_transient_permission_error -v (FAIL sin el bucle de la Fase 1, PASS con el) |
| 2.2 | pytest tests/test_approval_state_revision_and_skill_access.py -k test_supervisor_write_artifact_atomic_reraises_after_exhausting_replace_retries -v |
| 3.1 | ruff check bus/supervisor.py tests/test_approval_state_revision_and_skill_access.py; suite completa (tested_commit_sha == HEAD); python .agent/agent_controller.py --validate --json --project-root . |

## Decision Arquitectonica

El retry se acota exclusivamente a la linea `os.replace` (no al bloque
try completo) porque el sintoma observado (WinError 5 transitorio) ocurre
especificamente en el rename, no en la apertura/escritura del archivo
temporal; envolver mas superficie de la necesaria ocultaria errores reales
de escritura bajo el mismo mecanismo de reintento. Se distingue
`PermissionError` de forma generica (sin depender de `sys.platform` ni de
leer `.winerror` de forma insegura) para que la logica de produccion sea
identica en Windows y Linux: en Linux el bucle nuevo no encuentra la
excepcion y se comporta exactamente igual que hoy (cero intentos extra,
cero retraso). El backoff es corto (decenas de milisegundos) y el numero
de intentos bajo (3) para no enmascarar un problema real de permisos
detras de una espera larga; si el recurso sigue bloqueado tras esos 3
intentos, el fail-closed existente (re-lanzar la excepcion) se preserva
sin modificacion de comportamiento.

ACTUALIZADO (hallazgo post-implementacion): la primera version inline del
bucle de retry (dentro del propio write_artifact_atomic) elevo la
complejidad ciclomatica McCabe del metodo de <=10 a 13, incumpliendo el
limite C90=10 configurado en pyproject.toml (regla C901 de ruff). Se
decide EXTRAER el bucle a una funcion de modulo nueva,
_atomic_replace_with_retry, en vez de silenciar el hallazgo con
`# noqa: C901`. Razon: un noqa oculta el sintoma pero deja
write_artifact_atomic con mas ramas de decision de las necesarias para
su responsabilidad principal (lock + OCC + escritura), mientras que
extraer el retry a una funcion propia (a) devuelve write_artifact_atomic
a su complejidad original, (b) aisla la logica de reintento como una
unidad con una unica responsabilidad, mas facil de testear de forma
independiente en el futuro, y (c) no introduce deuda tecnica marcada con
un supresor de lint. La funcion vive en el mismo modulo (no en un archivo
nuevo) porque su unico consumidor es write_artifact_atomic y no justifica
un modulo separado; vive fuera de la clase (funcion, no metodo) porque no
necesita ningun atributo de self, solo sus 2 parametros. El punto de
monkeypatch de los tests de la Fase 2 (bus.supervisor.os.replace) no
cambia: el helper nuevo sigue invocando os.replace del mismo modulo.

SEGUNDO ACTUALIZADO (hallazgo post-implementacion #2): con el helper de
una sola funcion _atomic_replace_with_retry ya extraido (resolviendo
C901), ruff reporto PERF203 (`try`-`except` dentro de un `for` incurre
en overhead) sobre el `except PermissionError` anidado en el `for` del
helper. Se descartan (a) `# noqa: PERF203` puntual y (b) un
per-file-ignore en pyproject.toml como primera respuesta, y se elige (c)
reestructurar: separar el intento individual
(`_replace_once_or_none`, con su try/except FUERA de cualquier for) del
bucle de reintento (`_atomic_replace_with_retry`, con un for que NO
contiene try/except propio, solo llama a la funcion de intento y
decide reintentar o re-lanzar segun su valor de retorno). Esta
estructura fue verificada empiricamente por el Manager antes de aprobar
este plan, ejecutando `ruff check` con el `extend-select` real del
proyecto (E, F, B, S, RUF, N, W, I, PERF, UP, C90, ERA, SIM) sobre un
archivo aislado con exactamente ese diseno: resultado "All checks
passed!" (sin C901, sin PERF203, sin B904 por el `raise last_error`
fuera de un bloque except activo). Razon para preferir la
reestructuracion sobre el noqa: es codigo de produccion critico (el
escritor atomico del estado del bus); el unico precedente de
per-file-ignore para PERF203 en el repo es sobre un archivo de tests
(tests/test_pre_commit_hooks.py), no sobre codigo de produccion, por lo
que extender ese precedente a bus/supervisor.py ampliaria una excepcion
pensada para tests hacia produccion sin justificacion nueva. La
reestructuracion elegida no complica la lectura: separa dos
responsabilidades ya implicitas en el diseno anterior ("intentar una
vez" vs "orquestar los reintentos"), cada una mas facil de razonar y
testear por separado que el bucle unico previo.

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| Retry acotado (3 intentos, backoff aprox 10-20ms) solo alrededor de os.replace | Cambio minimo, no toca OCC ni lock, inocuo en Linux | No elimina la causa raiz externa (antivirus, indexador) | Aceptada |
| Reintentar el bloque try completo (incl. reabrir y reescribir el temp file) | Cubriria tambien fallos de escritura transitorios | Amplia el blast radius fuera de lo pedido; el fallo observado es solo en el rename | Descartada |
| Aumentar max_retries o retry_delay_ms del bucle OCC externo para que tambien cubra este caso | Reutiliza infraestructura existente | Ese bucle solo dispara ante FileExistsError del lock; mezclar semanticas (lock vs rename) complica el codigo y el test | Descartada |
| Extraer el retry a una funcion de modulo _atomic_replace_with_retry | Resuelve C901 sin silenciar el lint; retry queda testeable como unidad propia; write_artifact_atomic recupera su complejidad original | Anade una funcion nueva al modulo (superficie ligeramente mayor) | Aceptada (reemplaza al bucle inline tras el hallazgo de ruff) |
| Anadir `# noqa: C901` en la firma de write_artifact_atomic | Cambio de una linea, mas rapido | Silencia el sintoma sin reducir la complejidad real del metodo; deuda tecnica que un futuro cambio puede agravar sin aviso del linter | Descartada |
| Separar el intento individual (_replace_once_or_none) del bucle de reintento (_atomic_replace_with_retry) para que ningun for contenga un try/except | Resuelve PERF203 sin silenciar el lint; verificado empiricamente con el extend-select real; cada funcion queda con una unica responsabilidad clara | Anade una segunda funcion de modulo (superficie ligeramente mayor que un solo helper) | Aceptada (reemplaza al helper de una funcion tras el hallazgo PERF203) |
| Anadir `# noqa: PERF203` puntual sobre el except del helper de una funcion | Cambio de una linea, mas rapido que reestructurar | Silencia el sintoma en codigo de produccion critico sin necesidad, dado que existe una reestructuracion limpia y verificada | Descartada (queda como ultimo recurso documentado si el Builder no logra reproducir la reestructuracion) |
| Per-file-ignore de PERF203 para bus/supervisor.py en pyproject.toml | Resuelve el hallazgo en una linea de configuracion | Silencia PERF203 en TODO el archivo, no solo en el punto puntual; el unico precedente de este ignore en el repo es sobre un archivo de tests | Descartada |

## Guia de Riesgos
| Nivel | Significado | Accion del Builder |
|-------|-------------|-------------------|
| Bajo | Rutinaria | Intentar 3 veces antes de escalar |
| Medio | Requiere atencion | Intentar 2 veces, escalar si dudas |
| Alto | Critica | Escalar al primer fallo |

## Criterios de Aceptacion Global
- [ ] os.replace dentro de write_artifact_atomic (via el helper
      _atomic_replace_with_retry) reintenta hasta 3 veces ante
      PermissionError transitorio y completa con exito si un intento
      posterior tiene exito.
- [ ] _replace_once_or_none y _atomic_replace_with_retry existen como
      funciones de modulo en bus/supervisor.py, definidas antes de class
      SequentialTicketSupervisor; ningun for de ninguna de las dos
      contiene un try/except propio (el try/except vive solo dentro de
      _replace_once_or_none, que no tiene loop). write_artifact_atomic
      invoca a _atomic_replace_with_retry con una unica linea en el
      punto donde antes estaba la llamada directa a os.replace.
- [ ] Test de barrera 2.1 es FAIL-sin-fix y PASS-con-fix, cross-platform
      (monkeypatch, sin depender de sys.platform ni del atributo
      winerror).
- [ ] Test de barrera 2.2 confirma que el fail-closed re-lanza tras
      agotar los reintentos (no se traga el error) y no deja archivos
      temporales huerfanos.
- [ ] El retry OCC externo (lock, l.195-216) y su logica de stale lock
      quedan byte-identicos.
- [ ] ruff check y --validate --json en 0 errores y 0 warnings nuevos,
      SIN usar `# noqa: C901` (write_artifact_atomic recupera complejidad
      <=10) y SIN usar `# noqa: PERF203` ni per-file-ignore (la
      reestructuracion en 2 funciones evita el hallazgo por diseno,
      verificado empiricamente antes de aprobar este plan).
- [ ] El cambio es inocuo en Linux (sin PermissionError, el bucle nuevo
      no anade retraso ni cambia el resultado del caso feliz).

## 2026-07-07 Handoff: Manager a Builder
**Plan:** WOT-2026-019p
**Accion requerida:** Implementar segun work_plan.md
**Estado:** PENDING
