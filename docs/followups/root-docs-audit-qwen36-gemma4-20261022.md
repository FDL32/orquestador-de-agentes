# Auditoria de documentacion raiz -- qwen3.6 + gemma4 (nan_api) -- 2026-10-22

> Censo exploratorio de solo lectura sobre los ficheros `.md` de la raiz del motor
> (`repo_motor`, `orquestador_de_agentes`). Despachado con `scripts/ensemble_dispatch.py
> loop-round`, `loop_id EXPLORATORY-root-docs-audit-20261022`, fase `DESIGN_REVIEW`, sin
> commit/nonce (exploratorio, no gobierna un cambio pendiente). Dos lentes `nan_api`
> (`challenger_nan_qwen` = qwen3.6, backend_key BA11; `challenger_nan_gemma` = gemma4,
> backend_key BA13), ambas `channel: api`, sin filesystem -- solo vieron el contenido del
> bundle, no releyeron el repo.

## ESTADO_FRESCO del bundle

```
ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\optimizacion-arranque-frio-cont-20261022, HEAD=d4f730fc (corto), dirty=si (2 followups nuevos sin commitear), verificado=2026-10-22
```

19 documentos en el bundle: `CLAUDE.md`, `AGENTS.md`, `AGENT_SECURITY.md`,
`CLOSURE_MODEL.md`, `CONSTITUTION.md`, `CREDITS.md`, `DISTRIBUTION_GUIDE.md`,
`INTERACTION_MODES.md`, `MANUAL_PUBLICATION_CHECKLIST.md`, `PROJECT.md`, `QUICKSTART.md`,
`README.md`, `RELEASE_CHECKLIST.md`, `REPOSITORY_STRUCTURE.md`,
`UPGRADE_CLEANUP_GUIDE.md`, `UPGRADE_GUIDE.md`, `plan_graph.md`, `repo_charter.md`,
`.loop_bundle_optimizacion.md` (fichero TRACKED, ver hallazgo propio abajo), y un
EXCERPT de `CHANGELOG.md` (primeras 200 de 2811 lineas, entradas mas recientes).
Excluidos del bundle por ser proyecciones generadas, no documentacion de autor:
`llms.txt`/`llms-full.txt`, `MANIFEST.distribute`, `MANIFEST.workspace`.

Las dos respuestas, integras y sin resumir, estan abajo. Donde discrepan, se marca
explicitamente. Donde afirman algo verificable, se verifico contra el repo real antes de
incluirlo en la sintesis -- las citas de las lentes por si solas NO son evidencia de
cierre (CEM v0, "ningun auto-reporte de agente es evidencia").

---

## Hallazgos VERIFICADOS (contrastados contra el repo real, no solo citados por la lente)

### 1. `CLOSURE_MODEL.md:46` afirma algo FALSO -- `session_closeout.py` SI existe y SI se usa (eje c, correccion)

**Ambas lentes coincidieron** en señalar esta contradiccion de forma independiente.
Verificado directamente:

- `CLOSURE_MODEL.md:46`: *"the standalone `scripts/session_closeout.py` utility
  referenced in earlier revisions was removed in `WP-2026-061` cleanup. Closeout is
  currently a manual canonical handoff..."*
- `find . -maxdepth 2 -iname session_closeout.py` -> `./scripts/session_closeout.py`
  (existe, exit=0).
- `QUICKSTART.md:463`: *"Delega en `scripts/session_closeout.py` (prepush_check, audit,
  observaciones, memoria, archivado)."*
- `CHANGELOG.md:898`: *".agent/agent_controller.py: new `--session-close` flag that
  delegates to `scripts/session_closeout.py`..."*

**`CLOSURE_MODEL.md` esta STALE y es incorrecto en este punto, no `QUICKSTART.md`.** El
fichero describe un estado (cierre manual sin script) que no corresponde a la realidad
actual del repo: el script existe, se invoca desde `agent_controller.py --session-close`,
y `QUICKSTART.md` lo documenta correctamente. Candidato a fix inmediato, bajo riesgo
(una frase).

### 2. `MANUAL_PUBLICATION_CHECKLIST.md:15` cita una version desactualizada (eje a/c)

Confirmado: `git commit -m "feat: publicar snapshot limpio v9.6.0 - validacion final
completada"` -- `v9.6.0` es una version historica; la version actual declarada en
`CLAUDE.md`/`AGENTS.md`/`README.md` es `v9.17.1`. Es un ejemplo ilustrativo de mensaje de
commit, no un contrato tecnico, pero corroe la confianza del documento como referencia
viva. Fix barato (un numero).

### 3. `.loop_bundle_optimizacion.md` es debris commiteado por accidente (eje a, hallazgo propio, no citado por ninguna lente)

Verificado directamente (no via lente): `git ls-files --error-unmatch
.loop_bundle_optimizacion.md` -> tracked, exit=0. `git log --oneline -- <ese fichero>` ->
ultimo commit `8756e927` (WOT-2026-104l, "clear stale events..."), sin relacion con su
contenido real. El contenido es un bundle de dispatch de UNA ronda de bucle concreta,
fechado 2026-10-19, sobre una propuesta de "esfuerzo maximo + fallback de proveedor para
el trio nativo" -- un artefacto de TRABAJO (payload temporal para `ensemble_dispatch.py`),
no documentacion de autor. **Candidato a `.gitignore` + `git rm --cached`**, no a edicion:
es basura operativa versionada, no un documento a mantener.

### 4. Afirmacion de gemma4 sobre `## Vocabulario canonico` -- REFUTADA, es un FALSO POSITIVO

gemma4 reporto: *"La sección 'Vocabulario canonico' sigue presente a pesar de que el
CHANGELOG indica que fue movida"* (citando el commit WOT-2026-114c). **Verificado y
refutado:** la seccion en `AGENTS.md:69-83` SI es ya el resultado de ese movimiento --
son 8 lineas con un resumen corto de 4 reglas de alto impacto, terminando explicitamente
en *"Ver vocabulario completo... en
[vocabulario_canonico.md](.agent/rules/common/vocabulario_canonico.md)"*. El encabezado
`## Vocabulario canonico` se quedo A PROPOSITO (eso es justo el patron de split
quirurgico que este mismo vuelo aplico tambien a CEM v0): lo que se movio fue el
GLOSARIO EXTENSO (tipos SESION, modos EJECUCION, convencion de worktrees, etc.), no el
encabezado ni el resumen. gemma4 vio el encabezado y asumio incorrectamente que nada se
habia movido, sin poder releer el fichero de destino (`vocabulario_canonico.md` no
estaba en su bundle) para confirmar que el contenido extenso SI esta ahi. **Se documenta
como leccion del propio ejercicio: una lente sin filesystem puede fabricar una
contradiccion cuando solo ve un lado de un split ya ejecutado.**

---

## Hallazgos de las lentes NO verificados de forma independiente aqui (citados tal cual, pendientes de confirmacion si se actua sobre ellos)

- **qwen3.6:** `DISTRIBUTION_GUIDE.md` duplica "Canonical commands", "Legacy aliases" y
  "Version contract" con `UPGRADE_GUIDE.md` casi identicamente.
- **qwen3.6:** `UPGRADE_CLEANUP_GUIDE.md` duplica contenido con `UPGRADE_GUIDE.md` y
  `DISTRIBUTION_GUIDE.md` (comandos `detect_version.py`/`upgrade.py`).
- **qwen3.6:** `INTERACTION_MODES.md` se solapa extensamente con `QUICKSTART.md` (flujos
  de modo chat/terminal, comandos `ticket_supervisor.py`/`manager_review_bridge.py`).
- **gemma4:** `CLAUDE.md` ya remite explicitamente a `QUICKSTART.md` para comandos (esto
  es el patron CORRECTO -- `CLAUDE.md` es deliberadamente delgado y remite, no es una
  duplicacion real; se incluye aqui porque gemma4 lo marco como "redundancia" sin notar
  que es un puntero, no una copia).
- **gemma4:** `INTERACTION_MODES.md` vs `README.md` solapan la tabla de backends
  soportados / "Three-agent loop".
- **gemma4:** `QUICKSTART.md` seccion "0d. Motor dev worktree" es un bloque extenso
  candidato a modulo de referencia (mismo patron que CEM v0).
- **gemma4:** `UPGRADE_CLEANUP_GUIDE.md` se auto-titula "(Legacy)" -- candidato a mover a
  un directorio de archivo historico en vez de la raiz operativa.

Estos 7 puntos coinciden tematicamente entre ambas lentes en un eje comun: **hay
redundancia real entre el cluster `DISTRIBUTION_GUIDE.md` / `UPGRADE_GUIDE.md` /
`UPGRADE_CLEANUP_GUIDE.md`** (los tres tratan version/upgrade/distribucion con
solapamiento de comandos) **y entre el cluster `QUICKSTART.md` / `INTERACTION_MODES.md`**
(ambos documentan flujos operativos chat/terminal). Esto SI vale la pena verificar con
una lectura humana o un diff real antes de fusionar nada -- las lentes no tienen
filesystem y no pudieron correr `diff` entre ficheros, solo compararon texto citado.

## Discrepancias entre las dos lentes

- Solo gemma4 reporto la (falsa) contradiccion de "Vocabulario canonico" (hallazgo #4
  arriba, refutado).
- Solo qwen3.6 encontro la version stale `v9.6.0` en
  `MANUAL_PUBLICATION_CHECKLIST.md` (hallazgo #2, confirmado).
- Solo gemma4 senalo `.loop_bundle_optimizacion.md` como contenido que deberia
  "transicionar a ticket formal" (coincide en DETECTAR el fichero como anomalo, pero
  propone una resolucion distinta a la aqui recomendada -- gemma4 sugiere formalizarlo
  en vez de tratarlo como debris a limpiar; dado que su propio contenido ya es historico,
  de 2026-10-19 y sin relacion con el ticket que ultimo lo toco, "limpiar" parece mas
  ajustado que "formalizar", pero es juicio de producto, no un hecho verificable).
- Ambas coincidieron, sin que se les pidiera explicitamente cruzar referencias, en el
  hallazgo #1 (`CLOSURE_MODEL.md` stale sobre `session_closeout.py`) -- señal fuerte de
  consenso independiente, ademas verificado directamente contra el repo.
- **gemma4 omitio `repo_charter.md` de su tabla** (19 ficheros en el bundle, su tabla
  tiene 18 filas sin ese fichero y sin "sin hallazgos" explicito) -- incompletitud menor
  de su respuesta, no se interpreta como "sin hallazgos" silencioso.

## Sintesis de las lentes (integra, sus propias palabras)

**qwen3.6**, 3 documentos de mayor valor de accion inmediata: `CLOSURE_MODEL.md` (fix
urgente de la contradiccion `session_closeout.py`), `MANUAL_PUBLICATION_CHECKLIST.md`
(version stale + posible fusion con `RELEASE_CHECKLIST.md`), `DISTRIBUTION_GUIDE.md`
(candidato prioritario a fusion con `UPGRADE_GUIDE.md`).

**gemma4**, 3 documentos de mayor valor de accion inmediata: `AGENTS.md` (por la
inconsistencia de Vocabulario canonico -- **refutada en hallazgo #4**, asi que este punto
concreto de gemma4 no aplica, aunque su segunda observacion sobre AGENTS.md -- "CEM v0
candidato a modulo de referencia" -- ya esta RESUELTA por WOT-2026-114d/e de este mismo
vuelo), `.loop_bundle_optimizacion.md` (formalizar como ticket), `UPGRADE_CLEANUP_GUIDE.md`
(mover a modulo legacy).

## Recomendacion consolidada (criterio propio, tras contrastar ambas lentes)

1. **Fix inmediato, bajo riesgo, 1-2 lineas:** corregir `CLOSURE_MODEL.md:46` (hallazgo
   #1, verificado) y `MANUAL_PUBLICATION_CHECKLIST.md:15` (hallazgo #2, verificado). No
   requiere ticket formal ni bucle de gobierno -- es un error factual de documentacion,
   mismo tratamiento que cualquier typo corregido directamente.
2. **Limpieza, bajo riesgo:** `git rm --cached .loop_bundle_optimizacion.md` + anadir el
   patron a `.gitignore` si `ensemble_dispatch.py` genera mas ficheros `.loop_bundle_*.md`
   en la raiz de forma rutinaria (verificar primero si el script los escribe ahi por
   diseño o fue un accidente puntual de una sesion).
3. **Requiere verificacion humana antes de actuar, no ticket inmediato:** la redundancia
   entre `DISTRIBUTION_GUIDE.md`/`UPGRADE_GUIDE.md`/`UPGRADE_CLEANUP_GUIDE.md` y entre
   `QUICKSTART.md`/`INTERACTION_MODES.md` -- ninguna de las dos lentes tenia filesystem
   para confirmar el grado real de solapamiento con un diff; antes de fusionar o recortar
   nada, correr una comparacion real (`diff`/lectura humana) sobre esos pares.
4. **No se recomienda ninguna accion sobre `AGENTS.md`** mas alla de lo que ya cubre
   `docs/followups/palanca-a-fase0-post-114f-remedicion-20261022.md` (el frente de
   Palanca A ya en marcha en este mismo vuelo) -- la unica objecion de las lentes sobre
   AGENTS.md (Vocabulario canonico) fue un falso positivo.
