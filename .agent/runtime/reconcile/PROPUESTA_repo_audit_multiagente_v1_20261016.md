# Propuesta v1 — `repo-audit`: auditoría multifase multiagente de repositorios

**Fecha:** 2026-10-16
**Autor:** sesión Claude Code (orquestador_de_agentes_dev)
**Estado:** v3 — tras bucle adversarial DBL-4 (8 lentes, nonce 88d0cc46...),
veredicto unánime CAMBIOS (0 BLOQUEANTES). Lista para redactar el artefacto real.

## -1. Cambios v3 (bucle adversarial DBL-4, 8 lentes independientes)

Composición: `challenger_codex`, `challenger_opencode_glm_flash` (agent/FS);
`challenger_kilo_deepseek_flash`, `challenger_kilo_qwen` (agent/FS vía Kilo,
nan); `challenger_nan_gemma`, `challenger_groq_qwen`, `challenger_mistral`,
`challenger_nvidia_glm_flash` (api, sin FS). Las 8 dieron **CAMBIOS**, ninguna
BLOQUEANTE. Fixes consolidados por convergencia (≥2 lentes independientes):

| # | Fix | Lentes convergentes |
|---|---|---|
| V1 | Gate E5 por capas: literales de string sin frontera, entry-points/pyproject/CI/Makefile, excluir histórico (CHANGELOG/docs), categoría `DEAD (unverified dynamic)` que nunca se autoborra | 8/8 — unánime |
| V2 | gitleaks obligatorio en Fase 1 + no persistir secretos en salida cruda de `.agent/runtime/audit/` | kilo/deepseek, opencode/glm, nvidia/glm-flash |
| V3 | `mutation_cycle.py` obligatorio (no opcional) para borrados sin cobertura de tests | kilo/qwen, opencode/glm, nvidia/glm-flash |
| V4 | Regla determinista de selección de los "5" de Fase 4 (severidad→confianza→fingerprint) | kilo/qwen, opencode/glm, kilo/deepseek |
| V5 | Re-scan post-ejecución en Fase 6 (re-correr Fase 1 + suite, rollback automático si falla) | kilo/qwen, opencode/glm, mistral |
| V6 | Partición real (dedupe por fingerprint compartido) con `audit_portability_legacy_surface.md`, no solo cláusula verbal | kilo/deepseek (evidencia de solapamiento operativo real) |
| V7 | Pin de versiones de vulture/ruff/semgrep/pip-audit + manifest por corrida (nunca `--config auto` suelto) | kilo/deepseek, nvidia/glm-flash |
| V8 | Dueño explícito de Fase 3 (dedupe determinista): nombrar el script/módulo concreto | kilo/deepseek |
| V9 | Gate de privacidad en Fase 0: decidir si el repo permite lentes API-only o exige solo FS local | nan/gemma |
| V10 | Campo `veredicto_adversarial` por hallazgo en Fase 5 (`confirmado\|refutado\|disputado\|diferido_no_loop`); Fase 6 solo ejecuta `confirmado` | kilo/qwen |

**Deuda declarada (NOT VERIFIED, no bloquea v3):** contenido real de
`refactor-manager`/`mutation_cycle.py`/`backlog-admit` no leído en el bundle
de revisión; cifras externas de RepoMod-Bench/QASecClaw deben re-verificarse
antes de citarlas en el ticket final; R6-Git LFS y R7-ramas-no-main (kilo/qwen)
quedan como riesgos de baja prioridad para una iteración futura.

## 0. Cambios v2 (segunda pasada, error-hunting)

El usuario pidió explícitamente que el sistema no solo DETECTE sino que
también **limpie código/archivos antiguos, mejore el flujo de trabajo,
optimice interacciones y haga el sistema eficiente/eficaz/sostenible**. La
v1 era solo detección (Fase 5 read-only). Errores encontrados y su fix:

| # | Error/gap encontrado | Fix aplicado |
|---|---|---|
| E1 | Solo detecta, nunca cierra el lazo de limpieza real | **Fase 6 nueva** (ejecución vía `refactor-manager`/Builder tras ticket aprobado) |
| E2 | "Optimizar flujo de trabajo/interacciones" no tenía categoría de hallazgo | **Categoría `PROCESO`** en Fase 2, para lane `proceso` (prompts/skills) |
| E3 | Ambiguo si el repo auditado es destino o el propio motor (prompts/.md) | **Fase 0 declara ámbito** `motor`/`destino` explícitamente |
| E4 | Presupuesto de Fase 4 sin número concreto | **Tope fijado**: máx. 5 hallazgos crítico/alta por bucle; 3 lentes sin FS por defecto |
| E5 | Ningún gate verifica "nada lo usa" antes de proponer borrado | **Gate de sostenibilidad** en Fase 2: grep/import-graph obligatorio en candidate-to-retire |

## 1. Problema

El usuario quiere una dinámica repetible para auditar un `repo_destino` (o
cualquier repo) en busca de: código obsoleto/dead code, archivos legacy,
vulnerabilidades de seguridad, e incumplimiento de buenas prácticas actuales
de programación. El motor ya tiene piezas parciales:

- `skills/code-audit/SKILL.md`: dead code de un solo agente (vulture +
  deadcode + ruff + git log), SIN fan-out multiagente, SIN seguridad.
- `skills/test-audit/SKILL.md`: mismo patrón pero para la suite de tests.
- `prompts/audit_portability_legacy_surface.md`: legacy, pero ACOTADO al
  propio `repo_motor` (prompts/skills/scripts), no a un repo destino genérico.
- Ningún artefacto cubre seguridad (SAST) ni combina todo con bucle
  adversarial multi-backend.

**Hueco real confirmado por grep/lectura, no supuesto.** Censo ampliado
(petición del usuario de revisar también `suite_optimization.md`,
`persona_system.md` y "demás prompts/skills de optimización de archivos,
código y repos", 30 prompts + 35 skills grepeados por
`optimiz|refactor|legacy|dead.?code|obsolet|audit`):

| Artefacto | Qué hace | Por qué NO cubre esta propuesta |
|---|---|---|
| `prompts/suite_optimization.md` + `skills/suite-optimization` | Recolector→juez que optimiza SEGUNDOS de la suite de tests (run_history.jsonl) | Dominio distinto: velocidad de tests, no dead-code/legacy/seguridad de código de producción |
| `prompts/persona_system.md` | Vocabulario de roles (Persona-Orquestador/Manager/Revisor/Builder) para UNA sesión que encarna turnos del patrón 4-capas | No es auditoría; es nomenclatura de proceso. Reutilizable para NOMBRAR los turnos de Fase 4 si se adopta el patrón 4-capas, no como auditoría en sí |
| `prompts/doc_optimization.md` + `skills/doc-optimization` | Optimiza TOKENS de contexto siempre-cargado (CLAUDE.md/AGENTS.md y @imports) | Dominio distinto: tamaño de contexto, no calidad/seguridad de código |
| `skills/refactor-manager` | Refactor seguro de UN archivo ya identificado, 5 fases, dirigido por Manager, sin fan-out | No decide QUÉ auditar ni tiene multiagente; es el *consumidor* natural de un follow-up de `repo-audit` |
| `skills/repo-compare` | Compara repo local contra OTRO repo de GitHub para ADOPTAR features de alto valor | Dirección opuesta: adopción, no limpieza/auditoría del propio repo |
| `skills/code-audit`, `skills/test-audit`, `prompts/audit_portability_legacy_surface.md` | Ver arriba | Ya contemplados en el diseño (3.3, reuso explícito) |

Ningún artefacto censado se solapa con la propuesta; se confirma el hueco.

## 2. Qué dice el estado del arte (investigación 2026, ver fuentes al final)

1. **El tooling determinista da la verdad de base; el LLM sintetiza, prioriza
   y explica — nunca al revés.** (RepoAudit/ICML 2025, Beagle review-llm-artifacts).
   Un LLM "detectando" dead code sin un escaneo AST real es alucinación cara.
2. **El escalado es el enemigo real.** RepoMod-Bench (arXiv 2602.22518) mide
   caída de pass-rate de agentes de 91.3% (<10K LOC) a 15.3% (>50K LOC). Un
   diseño que lanza un agente a "leer todo el repo" colapsa en repos grandes.
   → Hay que trabajar por **lanes acotados**, igual que `test-audit` CAMPAIGN.
3. **SAST + LLM: dos arquitecturas.** (a) AI-on-top: motor determinista
   (Semgrep/Bandit/ruff-S) + LLM triando después. (b) AI-native: LLM razona
   dentro del escaneo. Para este repo, (a) es más barato, más verificable y
   más alineado con CEM v0 ("evidencia antes que relato").
4. **Deduplicación/triage de falsos positivos con LLM funciona pero con
   riesgo de sobre-filtrar.** Estudios (QASecClaw, "Sifting the Noise")
   muestran que agentes LLM reducen FP de SAST de ~92% a ~6% en el mejor caso,
   pero advierten que un filtro agresivo puede **esconder vulnerabilidades
   reales**. Por eso: fail-open ante duda, nunca fail-closed silencioso, y el
   dedupe final siempre lo hace un fingerprint determinista, no el LLM solo.
5. **Vulture/ruff-S/Bandit/Semgrep se solapan parcialmente** — ruff `--select S`
   cubre buena parte de Bandit; Semgrep aporta cross-file real; vulture cubre
   lo que ty/ruff no cubren (clases/funciones no usadas). No hay necesidad de
   correr los 4 siempre: Bandit O ruff-S (no ambos) + Semgrep + vulture.
6. **Legacy identification en pipelines reales (EPAM, Google Antigravity)**
   empieza por: mapa de dependencias → documentación generada → marcado de
   obsoleto, SIEMPRE con validación humana antes de borrar nada.

## 3. Propuesta: skill `repo-audit` + prompt núcleo

### 3.1 Forma del artefacto

Un **prompt núcleo** (`prompts/repo_audit_multiagent.md`, fuente de verdad,
sin ligar a ningún backend) + una **skill puntero**
(`skills/repo-audit/SKILL.md`, X-09: "skill apunta, prompt gobierna") que
enruta hacia él. Sigue exactamente el patrón ya validado de
`manager-orchestrator-loop` (skill mínima + núcleo portable) y de
`code-audit`/`test-audit` (umbrales, constraints, read-only por defecto).

**No es un script nuevo de Python** salvo donde el recolector determinista
ya puede ser mecanizado (ver 3.3). El multiagente vive en PROMPT, no en código,
porque el fan-out ya existe (`ensemble_dispatch.py loop-round`) y reinventar un
orquestador en Python duplicaría infraestructura ya probada.

### 3.2 Fases (recolector-primero, LLM-después — regla del estado del arte)

**Fase 0 — Acotación obligatoria (anti-colapso de escala) + declaración de ámbito.**
Antes de nada: `git ls-files | wc -l`, tamaño en LOC por lenguaje
(`cloc`/`tokei` si disponible, o `wc -l` por extensión como fallback), y
declarar lanes explícitos (por directorio top-level o por lenguaje). Ningún
agente recibe "audita todo el repo" de una vez — mismo principio que
`test-audit` CAMPAIGN (nunca un solo batch).

**Declaración de ámbito (v2, fix E3):** Fase 0 declara explícitamente si el
repo auditado es `motor` o `destino`. Si es `motor`, se añade un lane
adicional `proceso` (`prompts/*.md` + `skills/*/SKILL.md`) junto a los lanes
de código — ese lane usa Fase 2 con categoría `PROCESO` (ver fix E2) en vez
de las categorías de código. Si el repo auditado ES el motor, declarar
también la cláusula de no-solapamiento con `audit_portability_legacy_surface.md`
(R4): ese prompt cubre naming/alias/stubs del motor consigo mismo;
`repo_audit_multiagent.md` cubre dead-code+security+proceso de forma general,
pueden coexistir sin fusionarse.

**Partición real, no solo verbal (v3, fix V6).** El bucle DBL-4 (lente
kilo/deepseek) midió que ambos prompts escanean las MISMAS rutas
(`prompts/`+`skills/`+`scripts/`) y producen el MISMO formato de salida
con la MISMA categoría `candidate-to-retire` — la cláusula de R4 en v2 era
solo un enunciado, no una partición de ficheros. Fix: cuando el ámbito es
`motor`, el dedupe de Fase 3 (fix V8) incluye los hallazgos de
`audit_portability_legacy_surface.md` en su fingerprint compartido — un
mismo fichero candidate-to-retire nunca genera dos tickets independientes.

**Gate de privacidad (v3, fix V9).** Antes de decidir qué lentes participan
en Fase 4, Fase 0 declara si el `repo_destino` auditado permite enviar
fragmentos de código a lentes API-only (sin FS, terceros externos) o si,
por contener código propietario/sensible, el bucle debe limitarse
estrictamente a lentes con FS local (`channel: agent`). Por defecto, si no
se declara explícitamente que el repo es público/sin restricción, el bucle
usa SOLO lentes `channel: agent` — fail-closed en privacidad.

**Fase 1 — Recolección determinista (sin LLM, por lane).**
Por cada lane, correr SOLO herramientas deterministas y volcar su salida
cruda a `.agent/runtime/audit/repo_audit/<lane>/`:
- Dead code / legacy: `vulture --min-confidence 80`, `deadcode`,
  `ruff check --select C90,ERA,SIM` (ya en `code-audit`, reusado tal cual).
- Seguridad: `ruff check --select S` (cubre Bandit en Python) + `semgrep
  --config auto` si está disponible (cross-file, otros lenguajes) +
  `pip-audit`/`npm audit`/equivalente para dependencias.
- Antigüedad/legacy real: `git log` por antigüedad de archivo (ya en
  `code-audit`) + censo de archivos sin referencias de import entrantes.
- **Secretos (v3, fix V2 — convergencia de 3 lentes del bucle DBL-4):**
  `gitleaks` corre SIEMPRE en Fase 1, antes de persistir cualquier salida
  cruda. Si un escaneo de seguridad produce evidencia de una credencial
  real, esa salida se redacta (`***REDACTED***`) ANTES de escribirse en
  `.agent/runtime/audit/repo_audit/<lane>/` — nunca se persiste texto sin
  redactar, por la norma dura de AGENTS.md ("no guardes credenciales").
- **Reproducibilidad (v3, fix V7):** cada corrida fija versión de
  vulture/ruff/semgrep/pip-audit y persiste un manifest
  (`_meta/run_manifest.json`: versiones + git SHA + hash del raw). Si se usa
  `semgrep --config auto`, el ruleset resuelto se congela en el manifest —
  nunca se re-descarga sin registrar qué reglas se aplicaron esa corrida.
- **Ningún LLM interviene en esta fase.** Es el "ground truth" que cita la
  investigación.

**Fase 2 — Triage/síntesis por lane (1 agente por lane, CON FS).**
Un agente (builder-nan vía Kilo, o Claude subagente si el lane es pequeño)
lee la salida cruda de SU lane + el código real citado, y produce hallazgos
clasificados: `DEAD` / `ABANDONED` / `LEGACY` / `SMELL` / `SECURITY-{crítica,
alta,media,baja}` / `BUENAS-PRACTICAS` (naming, estructura, dependencias
obsoletas, patrones pre-2023 que ya tienen alternativa estándar). Cada
hallazgo exige evidencia citable (archivo:línea + comando reproducible),
igual que CEM v0 y `test-audit` Paso 5 (value bar).

**Categoría `PROCESO` (v2, fix E2) — solo lane `proceso`.** Cuando el lane
es `prompts/`+`skills/` (ver Fase 0, ámbito `motor`), se añade la categoría
`PROCESO`: solapamiento entre prompts/skills, pasos de flujo de trabajo
redundantes o ya sustituidos, fricción en interacciones Manager↔Builder↔Revisor
documentada pero no verificada. Mismo patrón ad-hoc ya usado en esta sesión
para censar `suite_optimization.md`/`persona_system.md`/`refactor-manager`
contra la propuesta — formalizado aquí como categoría reproducible.

**Gate de sostenibilidad (v3, fix E5 ampliado por V1) — obligatorio para DEAD/candidate-to-retire.**
`git grep -l <nombre>` demuestra CERO REFERENCIAS DE TEXTO, no cero USOS
ACTIVOS — las 8 lentes del bucle DBL-4 convergieron en que esto da falso
negativo ante: carga dinámica (`importlib.import_module`, `__import__`,
`eval`/`exec`), reflexión (`getattr`, `hasattr`, `__init_subclass__`),
entry-points/packaging (`pyproject.toml` `[project.scripts]`, console
scripts, plugins de pytest), y referencias por string desde
config/CI/Makefile/templates. El gate v3 exige TODAS las capas siguientes
antes de clasificar `DEAD`:
1. `git grep -l <nombre>` (referencias de texto, igual que v2).
2. Búsqueda de literales de string del nombre SIN frontera de palabra
   (cubre `importlib.import_module("nombre")`, `getattr(obj, "nombre")`).
3. Chequeo de entry-points: `pyproject.toml` (`[project.scripts]`,
   `entry_points`), Makefile, Dockerfile, workflows CI.
4. Excluir histórico del conteo (CHANGELOG, docs de archivo, git log) —
   una mención en un changelog no es "uso activo".
5. Si el símbolo tiene `__all__` en su paquete padre, verificar que no
   aparece ahí (API pública, aunque sin uso interno).

Si CUALQUIER capa encuentra una referencia (o no puede ejecutarse por falta
de herramienta), el hallazgo baja a **`DEAD (unverified dynamic)`** — nunca
se autoborra, siempre requiere revisión humana explícita en Fase 6. Solo si
las 5 capas dan cero control positivo se puede clasificar `DEAD` puro.
Mismo patrón de fondo que `audit_portability_legacy_surface.md` ya exige
para `candidate-to-retire`, ampliado por la convergencia del bucle.

**Fase 3 — Deduplicación determinista entre lanes.**
Fingerprint por (archivo, línea, categoría) para fusionar hallazgos
duplicados entre lanes o entre herramientas (p.ej. ruff-S y Semgrep marcando
la misma línea). Esto es código, no LLM — la investigación es explícita en
que el dedupe final debe ser determinista, no "el LLM decide si es igual".

**Dueño explícito (v3, fix V8):** el dedupe lo ejecuta un script concreto
(`scripts/dedupe_audit_findings.py`, a crear — mismo patrón stdlib-only que
el resto de `scripts/`), nunca queda como afirmación sin asignar. Si el
repo auditado ES el motor, este mismo script aplica el dedupe cruzado con
`audit_portability_legacy_surface.md` (fix V6, ver 3.3) usando fingerprint
compartido para evitar doble-ticket en `candidate-to-retire`.

**Fase 4 — Bucle adversarial de verificación (gobierno, lo que el usuario pidió).**
Sobre el informe consolidado de Fase 2+3 (NO sobre el repo entero — bundle
acotado, lección ya en memoria `obs-diff-only-bundle-fabricates-false-criticals`
y su familia): lentes adversariales que **refutan o confirman** cada hallazgo
de severidad alta/crítica antes de que se proponga ningún follow-up o
eliminación. Ningún hallazgo DEAD/SECURITY-crítica se promueve a ticket sin
pasar este bucle — mismo principio que mutation-verify en `test-audit`.
Composición del bucle pedida por el usuario:
- `challenger_codex_*` (backend real con FS)
- `challenger_opencode_glm_*` (backend real con FS)
- 2x `challenger_kilo_<modelo>` con canal `agent` (FS real vía Kilo) —
  usar DOS modelos nan distintos de los ya censados en `agents.json`
  (p.ej. deepseek + qwen, evitar repetir el mismo modelo dos veces)
- Varias lentes SIN FS (API-only, `channel: api`) para contraste — éstas NO
  pueden refutar un hallazgo por sí solas (lección
  `obs-fileless-lens-verdict-emission-contract`), pero SÍ pueden escalar
  severidad o señalar inconsistencia lógica en el informe consolidado.

**Presupuesto fijado (v2, fix E4):** máximo **5 hallazgos** crítico/alta por
corrida entran al bucle completo (composición de arriba); el resto de
hallazgos crítico/alta de esa corrida quedan en Fase 5 marcados "diferido —
no verificado por bucle, requiere corrida adicional", nunca se promueven
silenciosamente sin pasar el bucle. Lentes sin FS por defecto: **3**, salvo
que el usuario pida explícitamente más (norma ya fichada:
"uno por backend si no se especifica cuántos").

**Regla de selección determinista (v3, fix V4 — 3 lentes convergentes):**
los "5" que entran al bucle se eligen por orden: (1) severidad declarada
(`SECURITY-crítica` > `SECURITY-alta` > `DEAD` > resto), (2) confianza de
la evidencia (nº de capas del gate E5 que SÍ se ejecutaron sin hallar
referencia), (3) fingerprint como desempate estable. Nunca por orden
incidental de generación. `PROCESO` nunca entra a Fase 4 sin pasar primero
por una rúbrica de severidad propia (ver V-PROCESO en 3.2 Fase 2).

**Veredicto por hallazgo (v3, fix V10):** cada hallazgo que pasa por Fase 4
recibe un campo `veredicto_adversarial: {confirmado | refutado | disputado
| diferido_no_loop}`. Fase 6 (ejecución) **solo** actúa sobre hallazgos con
`veredicto_adversarial == confirmado` — cierra la condición de cierre que
antes dependía solo de "pasó el bucle" sin un valor explícito adjunto al
hallazgo.

**Fase 5 — Informe final + follow-ups (nunca ejecuta cambios).**
Igual que `audit_portability_legacy_surface.md`: la skill/prompt es
**read-only por defecto**. Produce un Markdown con Resumen Ejecutivo,
Inventario, Hallazgos (por severidad), Rechazados/Diferidos, y Follow-ups
como tickets pequeños y autocontenidos (`Files Likely Touched`, `Non-goals`,
`deliverable_type`, criterio de cierre binario) — nunca borra ni edita nada
directamente. El humano o un pipeline posterior decide qué follow-up se
convierte en ticket real vía `backlog-admit`.

**Fase 6 — Cierre/ejecución real (nueva, v2, fix E1).**
Cierra el lazo que la v1 dejaba abierto (detección sin limpieza real). Cada
follow-up de Fase 5 aprobado por el humano y admitido como ticket vía
`backlog-admit` se EJECUTA:
- Si es un refactor/borrado de UN archivo ya identificado con gate de
  sostenibilidad pasado (fix E5): vía `skills/refactor-manager` (5 fases,
  nunca cambia comportamiento observable sin aprobación explícita).
- Si es un cambio más amplio (`mixed`/`code` con varios archivos): vía
  Builder normal bajo el patrón estándar Manager→Builder→Revisor del motor.
- `repo-audit` en sí **sigue sin ejecutar nada por su cuenta** — Fase 6 es
  la CONEXIÓN con mecanismos de ejecución ya existentes, no una ejecución
  nueva. El invariante de aprobación humana antes de borrar/modificar se
  mantiene intacto.

**Gate de regresión obligatorio (v3, fix V3+V5 — 3+3 lentes convergentes).**
Ningún borrado de Fase 6 se cierra sin:
1. `scripts/mutation_cycle.py` **obligatorio** (no opcional como en v2) si
   el código borrado no tiene cobertura de tests existente que lo ejercite.
2. Re-scan post-ejecución: re-correr Fase 1 sobre el lane tocado + la suite
   completa del repo auditado. Si algo falla, **rollback automático** del
   commit de Fase 6 antes de reportar "borrado completado".
Sin estos dos pasos, "ejecutado" significa solo "se corrió un comando", no
"se verificó que no rompió nada" — la distinción que varias lentes marcaron
como condición para no escalar a BLOQUEANTE.

### 3.3 Qué NO se reinventa (reuso explícito)

- `ensemble_dispatch.py loop-round` para el fan-out de Fase 4 — NO un
  orquestador nuevo.
- `scripts/mutation_cycle.py` como gate opcional si un follow-up de Fase 5
  propone eliminar código (hereda el mismo gate duro de `test-audit`/`code-audit`).
- `skills/code-audit` y `skills/test-audit` se **invocan**, no se duplican:
  la Fase 1 de dead-code es literalmente sus Pasos 1-4 reutilizados por lane.
- Formato de salida y Constraints calcados de `audit_portability_legacy_surface.md`
  (Resumen/Inventario/Hallazgos/Rechazados/Follow-ups) para no inventar un
  formato nuevo que el resto del motor no reconozca.

### 3.4 Qué SÍ es nuevo

- La noción de **lane + fase recolector/LLM/dedupe/bucle** aplicada a UN
  repo arbitrario (no solo el motor).
- La incorporación de **seguridad** (ruff-S/Semgrep/pip-audit) como categoría
  de hallazgo, ausente hoy en `code-audit`.
- El **bucle adversarial de verificación de hallazgos** antes de proponer
  follow-ups — hoy ni `code-audit` ni `audit_portability_legacy_surface.md`
  pasan sus hallazgos por gobierno adversarial.

## 4. Riesgos declarados (para la segunda pasada)

- **R1 — Repos no-Python.** `agents.json`/el motor están pensados para
  Python. Si el repo auditado es JS/Go/etc., Fase 1 necesita un mapeo de
  herramienta-por-lenguaje que hoy no existe (Semgrep sí es multi-lenguaje;
  vulture/ruff no). Sin esto, la skill solo sirve de verdad para repos Python.
- **R2 — Coste del bucle de Fase 4.** 2 backends reales con FS + 2 nan-FS +
  "varias" sin FS es caro por auditoría completa. Necesita presupuesto
  explícito (cuántos hallazgos críticos como máximo entran al bucle, no
  "todos").
- **R3 — Falsos negativos por sobre-filtrado** (lección de "Sifting the
  Noise"): si Fase 4 filtra agresivo, puede esconder una vulnerabilidad real.
  Mitigación: fail-open declarado — ante desacuerdo entre lentes, el hallazgo
  SOBREVIVE a Fase 5 marcado como disputado, nunca se descarta en silencio.
- **R4 — Solapamiento con `audit_portability_legacy_surface.md`.** Si el
  repo auditado ES el propio motor, hay dos prompts que podrían aplicar.
  Hace falta una cláusula de alcance explícita: ese prompt es para el motor
  consigo mismo (naming/alias/stubs); `repo_audit_multiagent.md` es para
  CUALQUIER repo destino, incluido el motor, pero con lente dead-code+security
  general, no la taxonomía legacy-stub-declared específica del motor.
- **R5 — Dependencias nuevas.** Semgrep no está en `pyproject.toml` hoy.
  AGENTS.md prohíbe pedir dependencias sin aprobación — esto requiere
  aprobación explícita del usuario antes de `uv add`, o degradar Fase 1 de
  seguridad a solo `ruff --select S` + `pip-audit` si Semgrep no se aprueba.

## 5. Fuentes de la investigación

- [RepoAudit (PurCL)](https://gitblind.noratr.app/PurCL/RepoAudit) — framework multiagente de auditoría de bugs, ICML 2025
- [Beagle review-llm-artifacts](https://www.claudepluginhub.com/skills/existential-birds-beagle-core-plugins-beagle-core/llm-artifacts-detection)
- [Top AI SAST tools for 2026 (Corgea)](https://corgea.com/blog/top-ai-sast-tools-for-2026)
- [11 Best AI SAST Tools 2026 (Cycode)](https://cycode.com/?p=13420)
- [RepoMod-Bench (arXiv 2602.22518)](https://arxiv.org/pdf/2602.22518)
- [Automating legacy modernization with Antigravity (Google Codelabs)](https://codelabs.developers.google.com/automating-modernization-with-antigravity)
- [QASecClaw: Multi-Agent LLM FP Reduction (arXiv 2605.01885)](https://arxiv.org/pdf/2605.01885)
- [Sifting the Noise: LLM Agents in Vulnerability FP Filtering (alphaXiv 2601.22952)](https://www.alphaxiv.org/abs/2601.22952)
- [Semgrep vs Bandit (2026)](https://aicodereview.cc/blog/semgrep-vs-bandit)
- [Ruff security rules (bandit S-prefix)](https://pydevtools.com/handbook/how-to/how-to-enable-ruff-security-rules.md)
