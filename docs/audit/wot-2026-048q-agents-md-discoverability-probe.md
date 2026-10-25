# WOT-2026-048q -- Probe de reconstruccion fresh-context sobre `AGENTS.md`

> Medicion (c) de DEC-048O-001. Universo acotado por el censo de GLM BA06 (2026-08-04): de las
> 24 secciones `##` de `AGENTS.md` (ese conteo era el vigente el 2026-08-04; el conteo
> real HOY, 2026-10-25, es 21 tras varias compresiones del documento -- WOT-2026-114b/c/d/
> e/j, 117a, 120a -- el universo de este sondeo son las mismas 2 secciones nombradas, que
> siguen existiendo sin cambios; un ticket hijo de poda deberia re-baselinear el conteo
> total), solo DOS son candidatas reales a poda -- "Resumen del
> entorno" y "Rutas importantes". **NON-GOAL duro: este reporte NO edita `AGENTS.md`.**

## Metodologia

1. Se copio el arbol completo del motor (sin `.git`, `.venv`, `__pycache__`) a un directorio
   temporal fuera del repo.
2. En esa copia se eliminaron `AGENTS.md`, `CLAUDE.md` y `.claude/`, para simular un agente que
   nunca cargo esas guias. El resto del arbol (README.md, REPOSITORY_STRUCTURE.md, `.agent/`,
   codigo, config, CI) se dejo intacto -- la pregunta real no es "que dice el codigo Python en
   aislamiento" sino "que puede descubrir un agente SIN haber leido `AGENTS.md`", y otra
   documentacion viva es parte legitima de ese universo.
3. Se lanzaron dos invocaciones independientes de `codex exec --sandbox read-only
   --skip-git-repo-check -C <copia>` (backend `gpt-6-astra`, distinto del backend que redacta
   este reporte), una por seccion candidata. El prompt no menciona `AGENTS.md` ni dice que
   ficheros abrir; pide reconstruir el contenido real de cada seccion con cita `fichero:linea` y
   clasificar cada item como RECONSTRUIDO / PARCIAL / NO DEDUCIBLE.
4. Se leyo el transcript completo (no solo el ultimo mensaje) de ambas corridas para verificar que
   las citas son reales.

Transcripts (evidencia primaria, generados 2026-10-25, commiteados en este mismo directorio
tras el hallazgo bloqueante de la ronda 1 de revision -- un Revisor en otra sesion/sandbox
no podia leer el scratch dir efimero fuera del repo). El hook `check-added-large-files`
(limite 500 KB) obligo a recortar el ruido NO citado -- el volcado masivo de `rg --files`/
`rg` sobre el arbol completo (miles de paths sin valor de cita) -- conservando intacta toda
linea con una lectura real de fichero y la respuesta final verbatim de cada agente:
- `docs/audit/wot-2026-048q-transcript1-resumen.txt` (2042 de 10735 lineas originales)
- `docs/audit/wot-2026-048q-transcript2-rutas.txt` (831 de 3272 lineas originales)

## Seccion 1: "Resumen del entorno"

Contenido real de la seccion en AGENTS.md:
```
- Runtime: Python 3.10+, pathlib, typing.
- Package manager: uv (uv add <lib>, nunca pip directo).
- Testing y calidad: pytest, ruff.
- Seguridad: gitleaks, pip-audit.
```

Respuesta del agente fresh-context (verbatim, transcript 1):

1. Python/pathlib/typing -- RECONSTRUIDO: pyproject.toml:5 (requires-python >=3.10,<3.14),
   pathlib.Path en scripts/pip_audit_project.py:19,42,44, typing en bus/utils.py:10,13,26.
2. Gestor de paquetes -- RECONSTRUIDO (uv): .github/workflows/monthly-deps-bump.yml:43,46
   (uv lock --upgrade, uv sync --all-groups), scripts/run_pytest_safe.py:339 (sugiere
   uv add --dev pytest).
   Prohibicion de pip directo -- NO DEDUCIBLE: el agente busco explicitamente y no encontro
   ninguna prohibicion general; solo hay un bloqueo puntual de pip install --upgrade-all en
   .agent_denylist.json:3 (no equivalente), y scripts/run_pytest_safe.py:339 incluso ofrece
   -m pip install pytest como alternativa valida en ese contexto.
3. Testing/calidad -- RECONSTRUIDO: pytest + pytest-asyncio/cov/xdist (pyproject.toml:15-17,
   28), ruff en CI (.github/workflows/quality-gates.yml:37,40), mypy estricto
   (pyproject.toml:74-79), pre-commit (.github/workflows/security-audit.yml:34), vulture
   (.pre-commit-config.yaml:456-461), deadcode (pyproject.toml:27).
4. Seguridad -- RECONSTRUIDO: gitleaks (.github/workflows/security-audit.yml:49), pip-audit
   via wrapper (.pre-commit-config.yaml:436-442, scripts/pip_audit_project.py:61-73,92-99),
   reglas S de ruff (pyproject.toml:51).

### Veredicto seccion 1: PARCIAL

Los 3 bullets factuales (runtime/pathlib/typing, testing/calidad, seguridad) y la mitad factual
del bullet 2 (que uv es el gestor) salen RECONSTRUIDOS con cita exacta -- confirma la hipotesis
de partida del censo GLM BA06 (replica pyproject.toml casi 1:1). La clausula normativa
"nunca pip directo" es, confirmado por busqueda activa del agente, NO DEDUCIBLE: es
convencion-en-cabeza (una decision de proceso, no un hecho observable en codigo) y debe
quedarse si alguna vez se poda esta seccion. Esto reproduce exactamente la EXCEPCION ya
anotada en la fila de backlog.

## Seccion 2: "Rutas importantes"

Respuesta del agente fresh-context (verbatim, transcript 2), por ruta:

| Ruta | Veredicto | Evidencia / matiz |
|---|---|---|
| agent_system/ | RECONSTRUIDO | agent_system/scripts/project_paths.py:3; incluye templates/, docs/, refactor_kit/ |
| agent_system/templates/repomix.config.json | RECONSTRUIDO (parcial dentro) | config real citada linea a linea; el instalador la copia al destino (scripts/install_agent_system.py:1369,1391); no establece la ruta de salida .agent/context/repomix.xml |
| scripts/ | RECONSTRUIDO | install_agent_system.py:1053, discover_skills.py:297, memory_consolidate.py:2, check_collaboration_state_clean.py:88 |
| skills/ | RECONSTRUIDO | skills/README.md:1; discover_skills.py:145,301,325 |
| .agent/collaboration/ | PARCIAL | proposito operacional claro (MANIFEST.workspace:29, runtime/project_root.py:143), pero el matiz "contiene solo seeds neutros" no se confirma como hecho de la copia: la carpeta estaba vacia salvo archive/, y MANIFEST.distribute:128 + check_collaboration_state_clean.py:15 indican que esa distribucion de seeds fue RETIRADA |
| .agent/runtime/memory/ | RECONSTRUIDO | bus/memory_loader.py:15, scripts/memory_consolidate.py:444,565 |
| .agent/context/repomix.xml | NO DEDUCIBLE | el fichero no existe en el arbol inspeccionado (.agent/context/ solo contiene project_map.md); confirmado tambien en el arbol real del motor (ver nota abajo) |
| .agent/council/ | RECONSTRUIDO | council_broker.py:57,81,15,35,54; audit_rules.py:20,40 |
| REPOSITORY_STRUCTURE.md | RECONSTRUIDO | :3,53,63,69,81 (nota: la cita `:53` del propio agente fresh-context apunta a una linea en blanco del fichero real -- `## What is public` esta en `:52` y el primer bullet en `:54`; imprecision de un renglon del agente, no de este reporte, no afecta al veredicto); el agente nota que su afirmacion sobre seeds (:71) no coincide con el contenido observado ni con MANIFEST.distribute:128 |

### Pregunta especifica sobre .agent/collaboration/ (motor vs destino)

El agente respondio explicitamente a los 3 sub-puntos:
- (a) "solo seeds neutros": NO deducible como hecho de la copia (afirmado en
  REPOSITORY_STRUCTURE.md:71, pero sin seeds presentes y con retirada documentada en
  MANIFEST.distribute:128).
- (b) "estado real vive en un repo_destino externo": SI como arquitectura (topologia
  nombrada en .agent/README.md:15, construccion de la ruta de colaboracion bajo la raiz
  seleccionada en runtime/project_root.py:139,154), pero NO pudo verificar una ubicacion
  externa concreta activa (ademas existe fallback al propio motor, :124).
- (c) "enlace via variable de entorno o fichero": SI, implementado y verificable:
  AGENT_PROJECT_ROOT (runtime/project_root.py:106), --project-root
  (.agent/agent_controller.py:7460), motor_destination_link.json
  (scripts/install_agent_system.py:1106,1115, runtime/motor_link.py:36). El fichero de enlace
  en si no estaba presente en la copia (excluido por .gitignore:113).

### Veredicto seccion 2: PARCIAL

La mayoria de las rutas listadas (6 de 8 filas) salen RECONSTRUIDAS con evidencia real de codigo,
incluyendo el matiz motor/destino (b, c) que el censo previo marcaba como mas incierto. Pero hay
dos hallazgos que impiden declarar la seccion RECONSTRUIDA en firme:
1. .agent/context/repomix.xml sale NO DEDUCIBLE porque el fichero no existe actualmente
   en el arbol (verificado tambien contra el repo real del motor: ls .agent/context/ devuelve
   unicamente project_map.md). Esto no es solo "no descubrible" -- es una posible referencia
   obsoleta en AGENTS.md que excede el alcance de este ticket (NON-GOAL: no se edita
   AGENTS.md aqui) y se deja como hallazgo para un ticket hijo de verificacion de vigencia.
2. .agent/collaboration/ sale PARCIAL: el "por que" (vive en repo_destino, no en el motor; el
   motor solo contiene seeds) es arquitectura deducible, pero el hecho concreto "este arbol
   contiene seeds neutros" NO lo es desde esta copia -- contradice lo que la propia
   REPOSITORY_STRUCTURE.md afirma.

## Matiz metodologico declarado (CEM: evidencia antes que relato)

Una parte sustancial de la reconstruccion de la Seccion 2 se apoyo en otra documentacion
(README.md, REPOSITORY_STRUCTURE.md, .agent/README.md), no en codigo/config puro. Esto es
legitimo para responder "que puede descubrir un agente sin AGENTS.md" (esa prosa tambien existe
y seria leida), pero modera la fuerza de cualquier futura decision de podar: si esos otros
documentos tambien derivan o se desincronizan, la garantia de descubribilidad se debilita. Un
ticket hijo que decida podar debe volver a correr este probe sobre el estado real de esos
documentos en el momento de la poda, no asumir que el resultado de hoy es permanente.

## Veredicto consolidado y siguiente paso (DoD (c))

| Seccion | Veredicto | Que podria podarse (en un ticket hijo futuro, NUNCA aqui) |
|---|---|---|
| Resumen del entorno | PARCIAL | Los 3 bullets+medio reconstruidos (runtime/pathlib/typing, uv como gestor, testing/calidad, seguridad); la clausula "nunca pip directo" SE QUEDA |
| Rutas importantes | PARCIAL | 6 de 8 rutas reconstruidas con evidencia solida; .agent/context/repomix.xml necesita una verificacion de vigencia aparte (posible referencia obsoleta); .agent/collaboration/ necesita conservar el matiz "seeds neutros" porque no es verificable desde codigo solo |

Conforme a la clausula (c) del DoD: como AMBAS secciones salen PARCIAL (ninguna RECONSTRUIDA en
firme), no se abre ningun ticket hijo de poda en este momento -- el DoD solo exige el ticket
hijo si "alguna sale RECONSTRUIDA". Se deja documentado que una poda PARCIAL (quitar solo lo
reconstruido, bullet a bullet) seria tecnicamente posible para "Resumen del entorno", pero esa
decision de producto queda fuera de este ticket (NON-GOAL duro) y requeriria su propio DEC o
ticket hijo con medicion antes/despues en sesion real, una seccion por vez.

## Revision fresh-context (backend distinto)

Ronda 1 (backend OpenCode `opencode-go/glm-5.3`, distinto del que redacto este reporte):
DECISION: CHANGES. Hallazgos: (1, bloqueante-ambiental) los transcripts vivian en un scratch
dir externo fuera de la allowlist de permisos de la sesion del Revisor -- resuelto
commiteandolos en este directorio (ver arriba); (2, menor) la cifra "24 secciones" estaba
desfasada frente al AGENTS.md actual (21) -- resuelto con la nota fechada en la cabecera;
(3, menor) la cita `:53` de REPOSITORY_STRUCTURE.md apunta a una linea en blanco -- resuelto
con la nota en la tabla de la Seccion 2. Ver `execution_log.md` del ciclo WOT-2026-048q para
el transcript completo de esta ronda.
