# T3 ADE: Coordinacion Multi-Sesion (referencia bajo demanda)

> **Alcance de este modulo (fijado tras bucle adversarial 2026-10-23, 2/2 APROBAR_CON_CAMBIOS):**
> SOLO coordinacion proactiva entre sesiones/hilos T3 paralelos. NO redeclara seguridad,
> encoding, memoria ni el mecanismo GIT reactivo de `flight_push_policy.md` (Gate 1/Gate 2) --
> remite a ellos. Si un cambio futuro necesita anadir contenido fuera de "coordinacion entre
> sesiones T3", ese contenido va a OTRO modulo, no aqui.
>
> **No sujeto a los gates de contexto siempre-cargado:** verificado leyendo
> `scripts/measure_agents_md_units.py` -- el gate Codex mide solo bytes de `AGENTS.md`; el gate
> Claude sigue solo lineas `@` literales desde `CLAUDE.md` (hoy, unicamente `@AGENTS.md`). Este
> fichero no es importado por ninguno de los dos, luego no cuenta para ningun gate. Eso NO
> significa "sin disciplina de tamano": ver "Disciplina de crecimiento" al final.
>
> **Por que existe:** el motor fue disenado asumiendo una sesion unica con el repo abierto (el
> modelo IDE clasico: VSC, Antigravity, Zed). T3 opera como ADE con sesiones PARALELAS,
> potencialmente en cuentas humanas distintas, cada una en su propio worktree/rama, sobre el
> mismo flight o flights relacionados. Lo que sigue es la capa de coordinacion que ese cambio de
> paradigma necesita y que no vivia escrita en ningun sitio -- solo criterio ad-hoc.

## 1. Comunicacion entre cuentas distintas (cross-account)

Cuando dos sesiones T3 bajo cuentas humanas DISTINTAS (p.ej. dos worktrees del mismo repo,
cada uno ligado a una cuenta) trabajan en el mismo flight o en flights que tocan superficies
compartidas:

- **Antes de tocar una superficie de alto blast radius** (`AGENTS.md`, `CLAUDE.md`,
  `MANIFEST.distribute`, `MANIFEST.workspace`, `llms-full.txt`, cualquier script que las
  regenere como `build_llms.py`): manda un `t3_thread_send` a la otra sesion, si existe,
  declarando que vas a tocarla. No asumas que no hay nadie trabajando ahi solo porque tu hilo
  no la toco antes.
- **Para saber si existe otra sesion activa**, usa `t3_thread_list`/`t3_worktree_list` antes de
  asumir que tienes el campo libre, en particular antes de una operacion que regenera un
  artefacto derivado compartido (ejemplo real, 2026-10-23: dos sesiones coordinaron antes de
  que una regenerase `llms-full.txt`, para no pisar el trabajo de la otra).
- **El mecanismo GIT reactivo** (que hacer si la rama remota avanzo con commits de la otra
  cuenta) ya esta resuelto en `.agent/rules/common/flight_push_policy.md` Gate 2 -- este modulo
  NO lo repite, solo cubre el AVISO proactivo ANTES de llegar a ese punto.
- Verifica siempre el estado real del otro lado antes de actuar sobre su aviso: un mensaje de
  coordinacion ("ya hice X, suite verde, HEAD=sha") es una AFIRMACION, no evidencia -- si tu
  decision depende de ella (p.ej. vas a publicar contra ese HEAD), confirma con un comando
  propio (`git log`, `git show`) antes de confiar, igual que exige CEM v0 para cualquier
  auto-reporte.

## 2. Comunicacion entre sesiones de la MISMA cuenta (delegate_task, lentes, bucles)

- **`childThreadId` es almacenamiento, no un objetivo para una ronda nueva.** Para cada ronda
  de revision adversarial, vuelve a llamar `delegate_task` (no reuses el hilo hijo via
  `t3_thread_send`), pasando el brief original + hallazgos previos + objeciones sin resolver.
- **Verifica SIEMPRE el resultado de un `delegate_task` antes de actuar sobre el, en especial
  afirmaciones concretas con numeros (bytes, conteos, nombres de fichero).** Medido en esta
  misma sesion (2026-10-23): de 5 lentes dispachadas en una ronda de brainstorming, 3
  devolvieron datos falsos o obsoletos (un conteo de bytes CRLF inexistente, una "tabla" que no
  existe en el fichero real, una palanca que el lens creia pendiente pero ya estaba aplicada
  horas antes) -- las 3 se descartaron solo porque se verificaron con `grep`/lectura directa
  antes de aplicar ningun cambio. Un lens que no verifica su propia fuente puede sonar seguro y
  estar citando estado obsoleto.
- **Enrutamiento de backends por sub-broker:** un mismo nombre de modelo (p.ej. `glm-5.3`)
  puede estar disponible via multiples sub-brokers con cuotas de credito INDEPENDIENTES
  (`openrouter/*`, `aihubmix/*`, `nan/*`, `mistral/*`, `opencode-go/*`). Si una ruta falla por
  saldo/credito agotado, no es necesariamente un fallo del modelo o del contenido de tu
  prompt -- prueba OTRO sub-broker para el mismo modelo antes de descartar la idea o el lens.
  Usa `orchestrator_capabilities` para listar las rutas disponibles por proveedor.
- **Antes de declarar una lente "muda", lee su hilo.** En rutas opencode,
  `task_status.latestTerminalSummary` puede ser el PRIMER mensaje del hijo ("estoy
  verificando..."), no su veredicto: lee `childThreadId` con `t3_thread_read`. Medido
  2026-10-23: 2 de 6 lentes dadas por mudas tenian veredicto completo, y una traia el unico
  BLOQUEANTE real de la ronda.
- **Un hijo sin `isolation` arranca en el worktree del hilo PADRE**, no en el repo que nombra el
  prompt. Da rutas absolutas o `git -C <repo>` en el encargo. Medido: una lente ejecuto varios
  comandos en el checkout equivocado antes de corregirse.

## 3. Coordinacion de suite y push cuando hay sesiones paralelas sobre `main`

Esto es una extension de uso RUTINARIO (no de borde) de lo que ya definen
`.agent/rules/common/wot_026t_orden_trabajo_forense.md` y
`.agent/rules/common/flight_push_policy.md`:

- Antes de correr la suite canonica como gate FINAL de un vuelo, comprueba si otra sesion
  paralela ya publico en `origin/main` desde que empezaste (`git fetch` + comparar
  `origin/main` contra tu base). Si avanzo, el Gate 2 de `flight_push_policy.md` decide si
  necesitas re-suite completa o si el camino relajado aplica -- no asumas que tu suite sigue
  siendo valida contra el HEAD real de origin.
- Con sesiones T3 paralelas, esto pasa con frecuencia (no es el caso raro que el Gate 2 parecia
  describir originalmente): trata la verificacion de "¿avanzo origin/main mientras yo
  trabajaba?" como parte normal del cierre de cualquier vuelo con mas de una sesion activa en
  el mismo repo, no como una excepcion.

## 4. Cierre de ramas / worktrees al terminar un flight

- Al cerrar un flight que vivio en su propio worktree T3, usa `t3_worktree_list` para
  confirmar el estado antes de considerar el worktree "libre" -- no asumas que esta inactivo
  solo porque tu hilo termino de usarlo.
- No borres ni reutilices el worktree/rama de OTRA sesion sin confirmar primero (via
  `t3_thread_send` o releyendo su ultimo estado) que esa sesion considera su trabajo cerrado y
  publicado. Un worktree con commits locales sin push es trabajo en curso, no basura.
- `t3_worktree_handoff` mueve el HILO que llama, no otro hilo -- no sirve para "liberar" el
  worktree de otra sesion a distancia.

## Disciplina de crecimiento (para no convertir esto en cajon de sastre)

Al no estar sujeto a los gates de bytes/chars, este modulo podria crecer sin control. Norma
(no barrera cableada -- escalar a guard solo tras 2+ casos MEDIDOS de deriva real, mismo
criterio que `decision_capsule_schema.md` / F8 de `cem_v0_evidencia_forense.md`):

- Cada seccion nueva debe caer estrictamente dentro de "coordinacion proactiva entre sesiones T3
  paralelas" (apartados 1-4 arriba). Contenido de seguridad, encoding, memoria o el mecanismo
  GIT reactivo va a su modulo propio y se enlaza, nunca se copia aqui.
- Si este fichero supera ~8 KiB, es señal de que esta absorbiendo contenido que pertenece a otro
  modulo -- revisar y partir, no seguir anadiendo.
