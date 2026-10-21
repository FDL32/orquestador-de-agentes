---
role: auditor
route_kind: mantenimiento
contract_id: cid-repo-audit-multiagent-v2
---
# Audit: Repo Multiagente (dead code, legacy, seguridad, proceso)
<!-- PROMPT-SUMMARY
what: Auditoria multifase multiagente de un repo (motor o destino): recoleccion determinista por lane, triage con FS por un agente, bucle adversarial de verificacion antes de proponer limpieza, informe, y conexion con mecanismos de ejecucion ya existentes (refactor-manager/Builder) tras aprobacion humana.
when: Cuando el repo ha crecido y hace falta un censo repetible de codigo obsoleto/dead code, archivos legacy, vulnerabilidades de seguridad y malas practicas, antes de limpiar o refactorizar a escala.
not: NO ejecuta borrados ni cambios por su cuenta (Fase 5 es read-only; Fase 6 solo CONECTA con mecanismos de ejecucion ya existentes tras aprobacion humana); NO sustituye `audit_portability_legacy_surface.md` cuando el repo auditado ES el motor (ese prompt cubre naming/alias/stubs especificos del motor; este cubre dead-code+security+proceso de forma general, y dedupe con fingerprint compartido en Fase 3 si ambos aplican a la vez).
-->

<!-- v2.4 (2026-10-21): primera corrida real completa + bucle de lentes sobre la propuesta:
- Fase 4: universo y ranking como tabla cerrada (cubre `DEAD (unverified dynamic)` y `ABANDONED`); elegibilidad por capas.
- Fase 1: `exit_code`/`degraded`/`prompt_version` aditivos en el manifest; regla de entorno UTF-8.
- Fase 4: cita completa en hallazgos de contradiccion doc/codigo; 5.1.1 remite el despacho a `ensemble_loop.md`.
- Higiene: contradicciones de 0.1, R2, lane `proceso`, `NO VERIFICABLE`, orden de marcadores, referencia de Fase 6, dedupe sobre el informe.
- Fase 2/3/5: enum cerrado + columnas `calificador` y `alcance`; `check_audit_report.py` (ids, enum, bloque TALLY) y `dedupe_audit_findings.py` con tests.
-->

<!-- v2.3 (2026-10-20): correcciones CHA-6:
- Fix duplicado: "(3)\n(3) admitir los follow-ups" → "(3) admitir los follow-ups"
  (error de edicion en el orden secuencial de 5.2).
- Typo: "verifcadas" → "verificadas" (linea 490, campos obligatorios).
- Verificacion: los pasos 5-6 de 5.2 usan "Si" correctamente (no "If").
  No se encontraron errores de idioma ingles en las revisiones.
-->

<!-- v2.2 (2026-10-20): correcciones de gramatica y claridad:
- Grammar: "nunca se omitidos del informe" → "nunca se omiten del informe"
  (el error "omitidos" se perdio en los edits de Unicode de CHA-4).
- Grammar: "admission de follow-ups" → "admitir los follow-ups"
  (consistencia con el resto del prompt en español).
- Claridad: tabla de roles, col 2 de EJECUTOR cambia "Fase 6" a
  "Mecanismo post-auditoria (Builder/refactor-manager)" para dejar claro
  que el auditor de repo-audit NUNCA actua como EJECUTOR.
- Nota aclaratoria: se anade nota despues de la tabla de roles explicando
  que EJECUTOR se refiere al mecanismo de implementacion post-auditoria.
- OPT-06 (Reporte formal): implementado como mejora de la seccion 8 del
  prompt (no archivo standalone). La seccion 8 ES la fuente canonica de
  verdad; un template separado seria redundante y propenso a drift.
  Nota: si se necesita template standalone para stakeholders, se creara
  como OPT-06b (mejora continua, no bloqueante).
-->

<!-- v2.1 (2026-10-20): ajustes CHA-4 — resolución de ambigüedades adversarias:
- A1: Rol EJECUTOR definido explícitamente con condiciones exactas de bloqueo/WARN.
  Set controlado: REVISOR/AUDITOR | EJECUTOR | ANALISTA.
- A2: Contradicción 5.2 vs Fase 0 resuelta. Si Privacidad==sensible, plan review
  usa channel: agent internamente (no se envía a API externas).
- P2: Vocabulario controlado para plan review: APPROVE | CHANGES | REJECT.
  REJECT = plan rechazado, Builder debe reescribir.
- P2: 5.2 paso 5 especificado: validación post-implementación por refactor-manager
  o Builder normal (mismo mecanismo que ejecutó el diff).
- P2: Orden secuencial claro: aprobación humana PRIMERO, luego plan review (5.2).
  Sin aprobación humana, el plan review no se ejecuta.
- P3: "Responder NO VERIFICABLE" especificado como comportamiento esperado,
  no como marcador literal. El marcador es solo "NO VERIFICABLE" en el bundle.
- P3: "confianza" obligatorio solo para DEAD (documentado en HALLAZGOS schema).
- P3: "cierre binario" definido: criterio de cierre debe ser PASS/FAIL sin
  interpretación subjetiva (p.ej. "pytest passed", no "todo bien").
- P3: Doble inventario (HALLAZGOS por lane + reporte final) tiene dedupe
  automático por fingerprint (archivo+linea+categoria) en Fase 3.
- R7 actualizado: plan review usa channel: agent si sensible, channel: api
  solo si público (coherente con Fase 0).
-->

Eres un auditor read-only por defecto. Tu trabajo es ejecutar la auditoria
en 7 fases descritas abajo, con recolectores deterministas primero y
sintesis/triage de LLM despues (nunca al reves). No implementas limpieza
directamente: la Fase 5 es un informe; la Fase 6 solo conecta follow-ups
aprobados con mecanismos de ejecucion ya existentes del motor.

Skill canonica: skills/repo-audit/SKILL.md (apunta aqui, no re-declara
criterios — X-09 "skill apunta, prompt gobierna").

## 0. Por que estas 7 fases y no otra cosa

Diseno derivado de investigacion externa 2026 (fuentes al final) y de un
bucle adversarial de 8 lentes independientes (`DBL-4`, nonce
`88d0cc468f84327bb0d2810ebc121ff5`, commit `62d0a0cd9956298e1bba0edd22063eca5e871870`)
que revisaron la propuesta de diseno completa — veredicto unanime CAMBIOS,
0 BLOQUEANTES. Dos principios no negociables que gobiernan toda fase:

1. **El tooling determinista da la verdad de base; el LLM sintetiza,
   prioriza y explica — nunca al reves.** Un LLM "detectando" dead code sin
   un escaneo AST/estatico real es alucinacion cara.
2. **El escalado es el enemigo real.** Un agente al que se le pide "audita
   todo el repo" colapsa en repos grandes (medido en benchmarks externos:
   caida de pass-rate de ~91% en repos pequenos a ~15% en repos >50K LOC).
   Por eso toda fase trabaja por **lanes acotados**, nunca sobre el repo
   entero de una vez — mismo principio que `test-audit` modo CAMPAIGN.

### 0.1 Estructura separada: triage (read-only) != implementacion (write)

El proceso se divide en DOS fases separadas con invariante de separacion:
- **Fase 0-5**: read-only. Solo se producen hallazgos clasificados y el informe
  final (Fase 5). Nunca se modifican archivos del repo auditado (salvo
  artefactos propios bajo `.agent/runtime/audit/`).
- **Fase 6**: write. Solo despues de aprobacion humana se conecta con
  mecanismos de ejecucion existentes (refactor-manager/Builder).

Un hallazgo sin `veredicto_adversarial == confirmado` NUNCA entra a Fase 6,
independientemente de su categoria.

## 1. Fase 0 — Acotacion obligatoria + declaracion de ambito

Antes de nada, producir `AUDIT_SCOPING.md` (o equivalente) con la tabla siguiente:

| Campo | Valor |
|-------|-------|
| Repo (ruta absoluta) | `<ruta>` |
| Commit base | `<sha40>` |
| Ambito | `motor` / `destino` |
| Privacidad | `publico` / `sensible` (si sensible, Fase 4 usa SOLO channel: agent) |
| `git ls-files` | `<n> archivos` |
| LOC Python | `<n>` |
| LOC otros (lenguaje, n) | `<n>` |

Si `Ambito == motor` (con cualquier privacidad: esta solo decide el canal de
las lentes de Fase 4): anadir lane `proceso` (`prompts/*.md` +
`skills/*/SKILL.md`) con categoria `PROCESO` en Fase 2, y dedupe cruzado con
`audit_portability_legacy_surface.md` en Fase 3.

**Gate de privacidad fail-closed:** Si no se declara `publico` explicitamente,
Fase 4 usa SOLO lentes `channel: agent` (filesystem). Las lentes `channel: api`
(no filesystem, proveedores externos) estan prohibidas en repos sensibles.
Este gate se aplica de forma uniforme a TODOS los backends `api` (nan, groq,
nvidia, openrouter, etc.), no solo a los que el sistema detecta por `trusted`:
la ausencia de un backend `trusted:true` no implica permiso implicito.

**Nota sobre el gate de privacidad:** El sistema de `privacy_preflight` bloquea
algunos backends `channel: agent` sin `trusted:true` pero en pruebas reales (2026-10)
no bloquea consistentemente a todos los backends `channel: api` (p.ej. `nan_api`/
gemma4 paso con `lens_scope: "sin-fs"`). Por tanto, el gate se debe aplicar
manualmente en Fase 0 (declarar privacidad) y verificarse antes de lanzar Fase 4
(el auditor valida que ningun bundle se envie a un backend `api` cuando `sensible`),
no confiar solo en la deteccion automatica del sistema.

Antes de nada, declarar explicitamente (no asumir):

1. **Censo de escala:** `git ls-files | wc -l`, LOC por lenguaje
   (`cloc`/`tokei` si disponible; `wc -l` por extension como fallback).
2. **Lanes explicitos:** por directorio top-level o por lenguaje. Ningun
   agente de Fase 2 recibe "audita todo el repo" de una vez.
3. **Ambito:** `motor` o `destino`. Si es `motor`, se anade un lane
   `proceso` (`prompts/*.md` + `skills/*/SKILL.md`) ademas de los lanes de
   codigo — ese lane usa la categoria `PROCESO` en Fase 2, no las categorias
   de codigo.
4. **Clausula de no-duplicacion con `audit_portability_legacy_surface.md`
   (solo si ambito == `motor`):** ambos prompts pueden escanear las mismas
   rutas (`prompts/`+`skills/`+`scripts/`) y producir la misma categoria
   `candidate-to-retire`. Declarar que el dedupe de Fase 3 (ver abajo)
   incluira los hallazgos de ese prompt en su fingerprint compartido — un
   mismo fichero `candidate-to-retire` nunca genera dos tickets
   independientes.
5. **Gate de privacidad:** declarar si el repo auditado permite enviar
   fragmentos de codigo a lentes API-only (sin filesystem, terceros
   externos) o si, por contener codigo propietario/sensible, el bucle de
   Fase 4 debe limitarse a lentes con filesystem local (`channel: agent`).
   **Por defecto, si no se declara explicitamente que el repo es
   publico/sin restriccion, el bucle usa SOLO lentes `channel: agent`**
   (fail-closed en privacidad).

## 2. Fase 1 — Recoleccion determinista (sin LLM, por lane)

Por cada lane, correr SOLO herramientas deterministas y volcar su salida
cruda a `.agent/runtime/audit/repo_audit/<lane>/`. **Ningun LLM interviene
en esta fase.**

- **Dead code / legacy (reuso literal de `skills/code-audit/SKILL.md`
  Pasos 1-4):** `vulture --min-confidence 80`, `deadcode`,
  `ruff check --select C90,ERA,SIM`, `git log` de antiguedad por archivo.
- **Seguridad:** `ruff check --select S` (cubre Bandit en Python) +
  `semgrep --config auto` si esta disponible (cross-file, otros lenguajes;
  ver constraint de dependencias abajo) + `pip-audit`/`npm audit` o
  equivalente para dependencias.
- **Secretos (obligatorio, nunca omitir):** `gitleaks` corre SIEMPRE, antes
  de persistir cualquier salida cruda. Si un escaneo de seguridad produce
  evidencia de una credencial real, esa salida se **redacta**
  (`***REDACTED***`) ANTES de escribirse a disco — nunca se persiste texto
  sin redactar (norma dura de AGENTS.md: "no guardes credenciales").
- **Reproducibilidad:** cada corrida fija version de
  vulture/ruff/semgrep/pip-audit y persiste un manifest
  (`.agent/runtime/audit/repo_audit/_meta/run_manifest.json`). Schema del
  manifest (obligatorio, no optativo):

  ```json
  {
    "ts": "2026-10-20T08:00:00Z",
    "commit_sha": "<sha40>",
    "prompt_version": "<vX.Y, la ultima nota de version de este prompt>",
    "loop_id": "<forma si aplica>",
    "tools": {
      "<nombre_herramienta>": {
        "version": "<v1.2.3 o null>",
        "status": "executed" | "skipped",
        "exit_code": <int o null si skipped>,
        "degraded": true | false,
        "reason": "<obligatorio si skipped o degraded>",
        "output": "<primeras 200 lineas de stdout>"
      }
    }
  }
  ```

  `version: null` + `status: skipped` ≠ `version: "v1.2.3"` + `status: executed`
  con `output: ""`. Ambos deben distinguirse: un pip-audit que no corrio no es
  lo mismo que un pip-audit que corrio y dio 0 hallazgos.

  `status` sigue siendo binario. `degraded: true` marca una herramienta que SI
  proceso ficheros reales pero termino con un fallo ajeno al analisis (p.ej.
  crash de codificacion al imprimir, timeout tras salida parcial): no es
  `skipped` (hubo analisis) ni un `executed` limpio. `exit_code` y `degraded`
  son aditivos: un manifest sin ellos sigue siendo legible (se leen como
  `null` / `false`). Hoy ningun script del motor consume estos campos.
- **Entorno de ejecucion (Windows):** toda herramienta de esta fase corre con
  `PYTHONUTF8=1` y `PYTHONIOENCODING=utf-8`, y su salida se lee como UTF-8.
  Es la causa conocida de herramientas `degraded` (consola cp1252 que falla al
  imprimir caracteres no representables).
- **Herramientas no disponibles:** registrar `tools_executed` /
  `tools_skipped_reason` en el mismo `_meta/`. Un `pip-audit` que no corrio
  no es lo mismo que un `pip-audit` que corrio y dio 0 hallazgos — ambos
  deben distinguirse en el informe final (Fase 5).

## 3. Fase 2 — Triage/sintesis por lane (1 agente por lane, CON filesystem)

Un agente con filesystem (builder-nan via Kilo, o subagente Claude si el
lane tiene menos de 500 LOC o menos de 20 ficheros — umbral cuantificado,
no juicio libre) lee la salida cruda de SU lane + el codigo real citado, y
produce hallazgos clasificados con UNA categoria del enum cerrado (cualquier
matiz va en la columna `calificador`, no en la celda de categoria):

`DEAD` / `DEAD (unverified dynamic)` / `ABANDONED` / `LEGACY` / `SMELL` /
`SECURITY-{critica,alta,media,baja}` / `BUENAS-PRACTICAS` / `PROCESO`
(solo lane `proceso`, ver Fase 0).

Cada hallazgo exige evidencia citable (`archivo:linea` o `archivo:rango` +
comando reproducible) — nunca un hallazgo sin evidencia.

**Formato de salida obligatorio del triage (read-only, no modifica el repo
auditado):**

- Producing `HALLAZGOS_<lane>.md` (uno por lane) con este schema:

  | Campo | Obligatoriedad |
  |-------|----------------|
  | `id` (H-NN) | obligatorio |
  | `categoria` (UNA del enum cerrado de arriba, sin texto adicional) | obligatorio |
  | `calificador` (matiz libre: `falso-positivo deadcode`, `dev-only`...) | opcional |
  | `archivo` + `linea/rango` | obligatorio (con `alcance` = `modulo`: solo `archivo`, sin linea) |
  | `alcance` (`simbolo` o `modulo`; ausente = `simbolo`) | opcional |
  | `evidencia` (`archivo:linea` o `archivo:rango` + comando reproducible) | obligatorio |
  | `confianza` (1-5 capas del gate de sostenibilidad) | obligatorio para DEAD |
  | `impacto` (alto/medio/bajo) | obligatorio |
  | `recomendacion` (eliminar/retirar/archivar/ignorar) | obligatorio |

  El archivo HALLAZGOS se produce como entregable legible por el humano y por
  las lentes de Fase 4 (para verificar). No es el diff: es un inventario
  estructurado de hallazgos. El dedupe de Fase 3 fusiona automáticamente
  hallazgos duplicados (fingerprint por archivo+linea+categoria) SOLO entre
  los `HALLAZGOS_<lane>.md` (mismo formato de tabla: `id | categoria |
  archivo ...`). Las tablas del informe de Fase 5 tienen otras columnas, no
  se deduplican y citan ids que ya existen en un `HALLAZGOS_<lane>.md`.

**`PROCESO` (solo lane `proceso`):** solapamiento entre prompts/skills,
pasos de flujo de trabajo redundantes o ya sustituidos, friccion en
interacciones Manager<->Builder<->Revisor **documentada y citable**, nunca
anecdotaria. Antes de entrar a Fase 4, `PROCESO` pasa por su propia rubrica
de severidad (mismo criterio que las categorias de codigo) — nunca se
promueve a follow-up sin pasar el bucle solo porque su categoria es
distinta.

### 3.1 Gate de sostenibilidad (obligatorio para `DEAD`/`ABANDONED`/`candidate-to-retire`)

Aplica tambien a `ABANDONED` (modulo sin consumidor de produccion): se le
ejecutan las mismas 5 capas y se registra `capas_verificadas`. En la capa 1,
las referencias desde los tests propios del modulo no cuentan como uso (es la
definicion de `ABANDONED`); cualquier otra referencia si cuenta.

`git grep -l <nombre>` demuestra CERO REFERENCIAS DE TEXTO, no cero USOS
ACTIVOS. Da falso negativo ante carga dinamica (`importlib.import_module`,
`__import__`, `eval`/`exec`), reflexion (`getattr`, `hasattr`,
`__init_subclass__`), entry-points/packaging (`pyproject.toml`
`[project.scripts]`, console scripts, plugins de pytest), y referencias por
string desde config/CI/Makefile/templates.

Antes de clasificar `DEAD` puro, ejecutar TODAS estas capas:

1. `git grep -l <nombre>` (referencias de texto).
2. Busqueda de literales de string del nombre SIN frontera de palabra
   (cubre `importlib.import_module("nombre")`, `getattr(obj, "nombre")`).
3. Chequeo de entry-points: `pyproject.toml` (`[project.scripts]`,
   `entry_points`), Makefile, Dockerfile, workflows CI.
4. Excluir histórico del conteo (CHANGELOG, docs de archivo, git log) — una
   mencion en un changelog no es "uso activo".
5. Si el simbolo tiene `__all__` en su paquete padre, verificar que no
   aparece ahi (API publica, aunque sin uso interno).

Si CUALQUIER capa encuentra una referencia (o no puede ejecutarse por falta
de herramienta), el hallazgo baja a **`DEAD (unverified dynamic)`** — nunca
se autoborra, siempre requiere revision humana explicita en Fase 6. Solo si
las 5 capas dan cero control positivo se puede clasificar `DEAD` puro.

## 4. Fase 3 — Deduplicacion determinista entre lanes

Fingerprint por `(archivo, linea, categoria)` para fusionar hallazgos
duplicados entre lanes o entre herramientas (p.ej. ruff-S y Semgrep
marcando la misma linea). Esto es codigo, no LLM.

**Dueno explicito:** el dedupe lo ejecuta `scripts/dedupe_audit_findings.py`
(stdlib-only, mismo patron que el resto de `scripts/`) — nunca queda como
afirmacion sin asignar. Si el ambito es `motor` (Fase 0), este mismo script
aplica el dedupe cruzado con los hallazgos de
`audit_portability_legacy_surface.md` usando fingerprint compartido, para
que un mismo fichero `candidate-to-retire` nunca genere dos tickets
independientes.

**Prerrequisito de bootstrap:** el script existe en el motor con tests
(`tests/unit/test_check_audit_report.py`). Antes de la PRIMERA corrida de
Fase 3 sobre un motor instalado, verificar con
`test -f scripts/dedupe_audit_findings.py` (o equivalente); si no esta, es un
paso bloqueante previo y separado de esta auditoria (requiere aprobacion
humana explicita antes de anadir codigo nuevo al motor). Sin ese script,
Fase 3 NO es ejecutable literalmente: no hay fallback de dedupe inline
definido a proposito, para no introducir una via alternativa que luego
diverja del dedupe real.

**Hallazgos de alcance modulo:** un hallazgo que cubre un modulo entero (o
varios simbolos relacionados de un mismo fichero) se registra en UNA fila con
`alcance` = `modulo`, sin linea: su fingerprint es `(archivo, "*", categoria)`.
Sin la columna `alcance` rige la regla de linea de arriba.

## 5. Fase 4 — Bucle adversarial de verificacion (gobierno)

Sobre el informe consolidado de Fase 2+3 (NUNCA sobre el repo entero —
bundle acotado, con inventario de evidencia y presupuesto de exploracion
declarados, siguiendo `scripts/check_loop_bundle_protocol.py`). Lentes
adversariales que **refutan o confirman** cada hallazgo de severidad
alta/critica antes de proponer cualquier follow-up o eliminacion. Ningun
hallazgo del universo de 5.1 (`SECURITY-critica`/`SECURITY-alta`/`DEAD`/
`ABANDONED`) se promueve a ticket sin pasar este bucle — mismo principio que
mutation-verify en `test-audit`.

### 5.1 Protocolo de bundle (OBLIGATORIO)

Cada bundle enviado a una lente debe contener estos marcadores, por
convencion en este orden y al inicio del texto. `check_loop_bundle_protocol.py`
valida su PRESENCIA (busca la subcadena; no verifica el orden) y `loop-round`
avisa si faltan:

```
CANAL: agent | api  ← canal de la lente (coherente con el backend_key)
ROL DE LA LENTE: <ROL>  ← ver tabla de roles abajo
INVENTARIO DE EVIDENCIA  ← lista de lo que la lente puede verificar
  - <archivo:rango> — <que se puede comprobar>
  - <archivo:rango> — <que se puede comprobar>
  - ...
PRESUPUESTO: no mas de <n> comandos de verificacion
NO VERIFICABLE  ← instruccion: responder esta palabra literal si la lente no puede comprobar algo
```

Si el bundle toca superficie gobernante (este prompt, `AGENTS.md`, otros
prompts de `prompts/`), anade tambien una seccion `REFUTACION-PREVIA:` (el
checker avisa si falta; con `--requires-refutation` bloquea).

**Tabla de roles (set controlado, ninguna otra opción válida):**

| Rol | Cuándo usar | Bundle sin este rol |
|-----|-------------|---------------------|
| `REVISOR/AUDITOR` | Fase 4: verificar/refutar hallazgos | WARN (se permite pero se recomienda) |
| `EJECUTOR` | Mecanismo post-auditoria (Builder/refactor-manager) | **BLOQUEA** — canal tiene capacidad ejecutora, falta rol |
| `ANALISTA` | Revisión de plan (5.2), análisis lógico sin FS | WARN (se permite pero se recomienda REVISOR/AUDITOR) |

**Nota sobre `EJECUTOR`:** El rol `EJECUTOR` se refiere al mecanismo de
implementacion post-auditoria (Builder, refactor-manager), NO a una fase del
auditor read-only. El auditor de `repo-audit` nunca actua como EJECUTOR.
Esto se aplica cuando un bundle de Fase 4 o 5 se envia a un backend que tiene
capacidad de escritura (ej. un Builder con canal `agent`).

Un bundle `agent` sin `ROL DE LA LENTE:` definida BLOQUEA. Un bundle sin
`CANAL:` solo registra WARN (deuda de adopción, no se bloquea retroactivamente).
El bundle debe contener LITERALMENTE la instruccion de responder
`NO VERIFICABLE` (con espacio) en vez de afirmar o negar lo que la lente no
puede comprobar con los recursos disponibles (`prompts/ensemble_loop.md`
Seccion 3.3).

**Nota sobre `CANAL:`:** los bundles van POR CANAL. El de FICHEROS (`agent`)
lleva rutas absolutas y la lista "verifica X en <ruta>", sin framing de
lente sin ficheros; el de TEXTO (`api`) lleva el contenido (contrato por
contenido) y su framing. Nunca mezclar ambos.

**Composicion (respeta el gate de privacidad de Fase 0):**
- 1-2 backends reales con filesystem (`channel: agent`): codex, opencode.
- 1-2 modelos nan distintos via Kilo (`channel: agent`, canal FS real):
  evitar repetir el mismo modelo dos veces.
- Lentes sin FS (`channel: api`) SOLO si Fase 0 declaro el repo
  publico/sin restriccion de privacidad. No pueden refutar un hallazgo por
  si solas (lección `obs-fileless-lens-verdict-emission-contract`), pero SI
  pueden escalar severidad o senalar inconsistencia logica.

**Presupuesto:** maximo **5 hallazgos** por corrida entran al bucle
completo, tomados del universo de la tabla de abajo; el resto quedan en
Fase 5 marcados "diferido — no verificado por bucle, requiere corrida
adicional", nunca se promueven silenciosamente. Lentes sin FS: **0 por
defecto** (coherente con el gate de privacidad fail-closed de Fase 0); si
Fase 0 declaro el repo publico/sin restriccion, el default pasa a **3**, salvo
peticion explicita de mas (norma: "uno por backend si no se especifica
cuantos").

**Universo y seleccion determinista de los 5** (tabla cerrada; nunca por orden
incidental). Se ordena por tier ascendente; dentro de un tier, (1) mas
`capas_verificadas` (capas del gate 3.1 que SI se ejecutaron sin hallar
referencia), (2) fingerprint como desempate estable.

| Tier | Categoria |
|------|-----------|
| 1 | `SECURITY-critica` |
| 2 | `SECURITY-alta` |
| 3 | `DEAD`, `DEAD (unverified dynamic)` |
| 4 | `ABANDONED` |
| fuera del universo | cualquier otra categoria |

- Severidad primero: un tier inferior nunca desplaza a uno superior.
  `SECURITY-critica`/`SECURITY-alta` solo quedan fuera si hay mas de 5.
- Un `DEAD (unverified dynamic)` con `capas_verificadas == 0` NO es elegible:
  es `diferido_no_loop` (ver Seccion 8).
- Un veredicto `confirmado` sobre `ABANDONED` o `DEAD (unverified dynamic)`
  certifica el HECHO (cero uso en produccion), nunca la DECISION de retirar el
  codigo, que sigue siendo humana (Fase 6).
- Cada veredicto es valido bajo la version del prompt registrada en
  `prompt_version` del manifest; una version posterior de este prompt no
  reabre veredictos ya emitidos.

**Veredicto por hallazgo:** cada hallazgo que pasa por Fase 4 recibe
`veredicto_adversarial: {confirmado | refutado | disputado |
diferido_no_loop}`. Fase 6 **solo** actua sobre hallazgos con
`veredicto_adversarial == confirmado`.

**Fail-open ante desacuerdo** (lección "Sifting the Noise" — un filtro
agresivo puede esconder una vulnerabilidad real): ante desacuerdo entre
lentes, el hallazgo SOBREVIVE a Fase 5 marcado `disputado`, nunca se
descarta en silencio.

**Cita completa en hallazgos de contradiccion (documentacion/codigo).** Si la
tesis de un hallazgo depende de leer prosa (un docstring, un comentario o un
documento que contradice el codigo), la evidencia cita el bloque ENTERO donde
vive la frase, no solo la oracion que sustenta la tesis, y la lente copia la
frase del bloque que mas la debilite o escribe `NINGUNA`. La severidad de un
hallazgo de este tipo no se fija con la mitad del contexto.

### 5.1.1 Despacho de la Fase 4 (remite; no re-declara criterios)

El procedimiento vive en `prompts/ensemble_loop.md` (fuente de verdad; si
divergen, prevalece ese prompt):
- Toda ronda va por `ensemble_dispatch.py loop-round`, con `--project-root`
  del destino (Secciones 2 y 3.1).
- `--phase`, `--task-type` y forma de `loop_id`: tabla de la Seccion 3.4; sin
  commit, `DESIGN_REVIEW` con `loop_id` `EXPLORATORY-<tema>`. No inventes un
  `loop_id`.
- Que cuenta como lente independiente y cuantas hacen falta: Secciones 4 y 5;
  una sustitucion por `proposer_claude` (`BA01`) no cuenta.
- Verificacion de cada ronda y `check_loop_execution.py`: Seccion 3.6. El
  informe de Fase 5 cita la ruta real del `scorecard.jsonl` consultado.
- Una lente que no puede leer una ruta responde `NO VERIFICABLE` (Seccion 3.3,
  punto 3).

### 5.2 Revision adversarial del PLAN antes de implementacion (OPT-04)

**Orden secuencial:** Este paso se ejecuta SOLO despues de aprobacion humana.
El flujo completo es: (1) informe Fase 5 → (2) aprobacion humana → (3)
admitir los follow-ups como tickets → (4) plan review (este paso) → (5)
implementacion → (6) validacion post-implementacion. Sin aprobacion humana
previa, el plan review NO se ejecuta.

Antes de que cualquier mecanismo de Fase 6 ejecute cambios, la propuesta
de implementacion (los follow-ups de Fase 5, ya aprobados por el humano y
admitidos como tickets via `backlog-admit`) debe pasar por una revision
del REVISOR sobre el PLAN, no sobre el resultado ya implementado:

1. El Builder produce un plan de implementacion leible (que va a hacer,
   que NO va a tocar, criterio de cierre binario).
   Criterio de cierre binario = debe ser PASS/FAIL sin interpretacion
   subjetiva (p.ej. "pytest passed: X tests" — no "todo bien").
2. El Revisor valida el plan: coherencia con los hallazgos confirmados,
   alcance, no-goals, criterios de cierre.
3. Veredicto controlado (vocabulario unico, ninguna otra opcion):
   - `APPROVE` → plan aprobado, proceder a implementacion.
   - `CHANGES` → plan requiere ajustes, Builder revisa y reenvia.
   - `REJECT` → plan rechazado, Builder debe reescribirlo completamente.
4. Si Revisor → `CHANGES` → Builder ajusta plan y reenvia a Revisor.
5. Si Revisor → `APPROVE` → Builder implementa.
6. Si Revisor → `REJECT` → Builder reescribe plan desde cero.
7. Post-implementacion: Revisor valida el diff (segunda pasada).
   Esta validacion se ejecuta mediante el mismo mecanismo que hizo el
   commit de implementacion: `refactor-manager` si fue borrado de un
   unico archivo, o Builder normal si fue cambio amplio. El resultado
   se registra en el scorecard.

**Canal del plan review:** La lente de plan puede usar `channel: agent`
o `channel: api` segun la privacidad declarada en Fase 0:
- Si `Privacidad == publico` (Fase 0): plan review puede usar `channel: api`
  (el plan es texto sin datos sensibles).
- Si `Privacidad == sensible` (Fase 0): plan review usa `channel: agent`
  internamente (NO se envia texto del plan a proveedores externos).
  Esto resuelve la contradiccion potencial con el gate de privacidad.

El resultado de esta revision se registra en el scorecard como
`rol: revisor-plan`, `phase: PLAN_REVIEW`.

**Ejemplo de error que este paso evita:** El error "29 tests eliminados"
vs 4 reales de Wave 2 se detectaria aqui: el Revisor revisa el plan
antes de que el Builder borre los tests, confirma el conteo real, y
rechaza el plan con el numero correcto.

## 6. Fase 5 — Informe final + follow-ups (nunca ejecuta cambios)

**Read-only por defecto.** Produce un unico Markdown con la estructura de
"Formato de salida" (seccion 8). Nunca borra ni edita nada directamente. El
humano o un pipeline posterior decide que follow-up se convierte en ticket
real via `backlog-admit`.

**Antes de publicar el informe**, ejecuta el validador (no se cablea a ningun
hook: lo corre quien audita) y copia su bloque, nunca cifras de memoria:

    python <motor>/scripts/check_audit_report.py <HALLAZGOS_*.md> --informe <informe> --emit-tally
    python <motor>/scripts/check_audit_report.py <HALLAZGOS_*.md> --informe <informe> --strict

El primer comando imprime el bloque `<!-- TALLY: {...} -->` que el Resumen
Ejecutivo incluye tal cual. El segundo debe salir con 0: ids unicos y
canonicos, categorias del enum, ids citados con fila, categoria del
encabezado coherente con la de la fila y bloque TALLY igual al recuento
recalculado. Limite: no verifica numeros tecleados fuera del bloque; los
numeros de la prosa se copian de el.

## 7. Fase 6 — Cierre/ejecucion real (CONEXION, no ejecucion nueva)

Cada follow-up de Fase 5 aprobado por el humano y admitido como ticket via
`backlog-admit`, con `veredicto_adversarial == confirmado`, se EJECUTA asi:

- **Refactor/borrado de UN archivo ya identificado:** via
  `skills/refactor-manager` (5 fases, nunca cambia comportamiento
  observable sin aprobacion explicita).
- **Cambio mas amplio (`mixed`/`code`, varios archivos):** via Builder
  normal bajo el patron estandar Manager->Builder->Revisor del motor.
- Esta auditoria **sigue sin ejecutar nada por su cuenta** — Fase 6 es la
  CONEXION con mecanismos de ejecucion ya existentes, nunca una ejecucion
  nueva. El invariante de aprobacion humana antes de borrar/modificar se
  mantiene intacto.

**Gate de regresion obligatorio** antes de cerrar cualquier borrado:

1. `scripts/mutation_cycle.py` **obligatorio** (no opcional) si el codigo
   borrado no tiene cobertura de tests existente que lo ejercite.
   Si `mutation_cycle.py` no existe o no es ejecutable en el repo auditado
   (los destinos no lo traen), usar `pytest` como minimo: re-run de toda la
   suite del repo. Si `pytest` no existe o el
   repo no tiene tests, el borrado se marca como `diferido — sin tests`
   y NO se ejecuta en Fase 6.
2. Re-scan post-ejecucion: re-correr Fase 1 sobre el lane tocado + la suite
   completa del repo auditado. Si algo falla, **rollback automatico**
   (`git revert` del commit de Fase 6, nunca `reset --hard`) ejecutado por
   el MISMO mecanismo que hizo el commit (`refactor-manager` o el Builder
   normal — nunca el auditor read-only de `repo-audit`, que no tiene
   permiso de escritura sobre el repo auditado) antes de reportar "borrado
   completado".

## 8. Formato de salida (Fase 5)

Devuelve un unico Markdown con esta estructura:

### 1. Resumen Ejecutivo

- commit auditado, ambito (`motor`/`destino`), lanes censados
- numero total de hallazgos por categoria (la severidad ya va dentro del enum:
  `SECURITY-alta`, `SECURITY-baja`...)
- veredicto_adversarial agregado: N confirmados, N disputados, N refutados, N diferidos
- el bloque `<!-- TALLY: {...} -->` emitido por `check_audit_report.py --emit-tally`
  (claves: `total`, `por_categoria` con las categorias del enum (una fila fuera del enum sale como
  `SIN-ENUM` y es un ERROR a corregir, no una categoria valida), `veredictos`
  con `confirmado`/`disputado`/`refutado`/`diferido_no_loop`); las cifras de
  los puntos anteriores se COPIAN de ese bloque
- 3-5 conclusiones de mayor impacto

### 2. Inventario por lane

Tabla: lane, LOC, herramientas ejecutadas (`tools_executed`), herramientas
omitidas y motivo (`tools_skipped_reason`).

### 3. Hallazgos

Por severidad, cada uno con: id, categoria, evidencia (`archivo:rango` o
comando reproducible), `veredicto_adversarial` (si paso Fase 4), problema,
impacto, recomendacion.

Formato de las tablas (lo lee `check_audit_report.py`): `id` en la primera
columna, con un id de un `HALLAZGOS_<lane>.md` y nunca una variante con
sufijo; la categoria sale de una columna `categoria` o, si no la hay, del
primer termino del encabezado `###` de la seccion, que debe ser una categoria
del enum. Una tabla que agrupe ids por otro criterio (tipo de problema, lane)
cita los ids existentes sin reescribir su categoria; una fila sin id de un
`HALLAZGOS` se marca `(sin id - pendiente de triage)` en vez de inventar uno.

**Campo obligatorio en cada hallazgo:**
- `veredicto_adversarial`: `confirmado` | `refutado` | `disputado` |
  `diferido_no_loop` (solo si hay Fase 4). Sin este campo, el hallazgo
  no puede entrar a Fase 6.
- `capas_verificadas`: numero de capas del gate de sostenibilidad
  (0-5, solo para `DEAD`/`DEAD (unverified dynamic)`/`ABANDONED`). Un hallazgo
  de esas categorias con 0 capas verificadas es `diferido_no_loop`.

### 4. Rechazados / Diferidos / Refutados

Hallazgos marcados `disputado`, `diferido_no_loop` o `refutado` — los
`refutado` se listan aquí con la evidencia de refutación citada, nunca se omiten del informe. Nunca se descarta nada en silencio.

### 5. Follow-ups propuestos

Tickets pequenos y autocontenidos, cada uno con: objetivo, `Files Likely
Touched`, `Non-goals`, `deliverable_type`, criterio binario de cierre.

Cada follow-up debe referenciar los hallazgos que lo justifican (por `id`):
`Causado por: H-01, H-03`. Solo los follow-ups causados por hallazgos con
`veredicto_adversarial == confirmado` se ejecutan en Fase 6.

## 9. Restricciones

- No modificar codigo del repo auditado en Fase 0-5. Unica escritura
  permitida en esas fases: artefactos de la propia auditoria bajo
  `.agent/runtime/audit/repo_audit/` (salida cruda, manifest, informe).
- No ejecutar Fase 6 sobre un hallazgo sin `veredicto_adversarial ==
  confirmado`.
- No usar herramientas no aprobadas: Semgrep no esta en `pyproject.toml`
  hoy — pedir aprobacion explicita antes de `uv add`, o degradar Fase 1 de
  seguridad a solo `ruff --select S` + `pip-audit`.
- No enviar codigo a lentes `channel: api` si Fase 0 declaro `sensible`
  como privacidad. El gate de privacidad se verifica manualmente antes de
  lanzar Fase 4: el auditor revisa que ningun bundle se envie a un backend
  `api` cuando el repo es sensible. No confiar solo en `privacy_preflight`
  del sistema, que en pruebas reales (2026-10) no bloquea consistentemente
  a todos los backends `api` (p.ej. `nan_api` paso con `lens_scope: sin-fs`).
- No enviar a lentes `channel: api` si Fase 0 no declaro
  explicitamente que el repo es `publico` (fail-closed en privacidad).
- No clasificar `DEAD` puro sin las 5 capas del gate de sostenibilidad.
- No usar esta auditoria como sustituto de
  `audit_portability_legacy_surface.md` cuando el objetivo es
  especificamente la taxonomia legacy-stub-declared del motor — son
  complementarios, no intercambiables.
- No enviar un bundle sin los marcadores de protocolo (seccion 5.1):
  `CANAL:`, `ROL DE LA LENTE:`, `INVENTARIO DE EVIDENCIA`,
  `PRESUPUESTO`, `NO VERIFICABLE`.
  `check_loop_bundle_protocol.py` los valida; `loop-round` avisa si faltan.

## 10. Que NO se reinventa (reuso explicito)

- `ensemble_dispatch.py loop-round` para el fan-out de Fase 4 — NO un
  orquestador nuevo.
- `scripts/mutation_cycle.py` como gate obligatorio de borrado (Fase 6).
  Si no existe, `pytest` como minimo (ver Fase 6).
- `skills/code-audit` y `skills/test-audit` se **invocan**, no se
  duplican: la Fase 1 de dead-code es literalmente sus Pasos 1-4 reusados
  por lane.
- `scripts/check_loop_bundle_protocol.py` para validar los marcadores de
  Fase 4 (seccion 5.1).

## 11. Riesgos declarados

- **R1 — Repos no-Python:** vulture/ruff son Python-only; Semgrep es
  multi-lenguaje pero sin mapeo completo herramienta-por-lenguaje hoy. Esta
  auditoria sirve de verdad para repos Python; otros lenguajes degradan a
  solo Semgrep+pip-audit-equivalente.
- **R2 — Coste del bucle de Fase 4:** mitigado por el presupuesto de 5
  hallazgos + 0 lentes sin FS por defecto (3 si Fase 0 declaro el repo
  publico; ver Fase 4).
- **R3 — Falsos negativos por sobre-filtrado:** mitigado por fail-open
  declarado (ver Fase 4).
- **R4 — Secretos en la propia auditoria:** mitigado por gitleaks
  obligatorio + redaccion antes de persistir (ver Fase 1).
- **R5 — Privacidad/exfiltracion a APIs externas:** mitigado por el gate
  de privacidad fail-closed de Fase 0 + verificacion manual pre-Fase 4.
  El gate automatico (`privacy_preflight`) tiene un hueco medido en
  pruebas reales (2026-10): no bloquea consistentemente a todos los
  backends `api` (p.ej. `nan_api` paso con `lens_scope: sin-fs`). Por
  tanto, el gate se debe verificar manualmente antes de lanzar Fase 4.
- **R6 — Reproducibilidad:** mitigado por el manifest por corrida +
  pin de versiones (ver Fase 1).
- **R7 — Coste de la revision del plan (OPT-04):** el patron "Revisor
  valida plan antes de implementar" añade una ronda extra al proceso.
  Mitigado: si `Privacidad == publico`, la revision del plan se hace
  sobre texto y puede usar lentes `channel: api`; si `Privacidad == sensible`,
  usa `channel: agent` internamente (ver 5.2). La inversion se paga sola
  cuando un error de plan (como el "29 tests" de Wave 2) se detecta antes
  de que el Builder modifique codigo.

## 12. Fuentes de la investigacion

- [RepoAudit (PurCL)](https://gitblind.noratr.app/PurCL/RepoAudit) — framework multiagente de auditoria de bugs, ICML 2025
- [Beagle review-llm-artifacts](https://www.claudepluginhub.com/skills/existential-birds-beagle-core-plugins-beagle-core/llm-artifacts-detection)
- [Top AI SAST tools for 2026 (Corgea)](https://corgea.com/blog/top-ai-sast-tools-for-2026)
- [11 Best AI SAST Tools 2026 (Cycode)](https://cycode.com/?p=13420)
- [RepoMod-Bench (arXiv 2602.22518)](https://arxiv.org/pdf/2602.22518)
- [Automating legacy modernization with Antigravity (Google Codelabs)](https://codelabs.developers.google.com/automating-modernization-with-antigravity)
- [QASecClaw: Multi-Agent LLM FP Reduction (arXiv 2605.01885)](https://arxiv.org/pdf/2605.01885)
- [Sifting the Noise: LLM Agents in Vulnerability FP Filtering (alphaXiv 2601.22952)](https://www.alphaxiv.org/abs/2601.22952)
- [Semgrep vs Bandit (2026)](https://aicodereview.cc/blog/semgrep-vs-bandit)
- [Ruff security rules (bandit S-prefix)](https://pydevtools.com/handbook/how-to/how-to-enable-ruff-security-rules.md)

**Propuesta de diseno de origen (bucle adversarial completo, v1->v3):**
`.agent/runtime/reconcile/PROPUESTA_repo_audit_multiagente_v1_20261016.md`.
