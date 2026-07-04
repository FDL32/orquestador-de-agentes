# Work Plan - WOT-2026-015p

## Metadata
- **ID:** WOT-2026-015p
- **Estado:** COMPLETED
- **deliverable_type:** documentation
- **Titulo:** Degradar privada/ a fallback temporal (no solucion final) en la doc de
  seguridad del motor + documentar la politica escalonada de secretos por contexto.
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Actualizar la documentacion de seguridad del motor para que privada/ deje de
presentarse como "la" solucion de secretos y pase a describirse como fallback
operativo temporal (separacion por convencion + .gitignore + hook guard_paths,
NO barrera criptografica), documentando ademas la jerarquia canonica de secretos por
contexto:

- Local mono-usuario -> keyring / OS DPAPI
- Compartido/versionado cifrado -> SOPS + age
- Productivo/backend -> OAuth2 / OIDC / token efimero
- privada/ = solo fallback operativo cuando ninguna de las anteriores es viable
  todavia.

Doctrina fuente (NO reinterpretar, transcribir literalmente el contenido, no la
redaccion caracter a caracter): .agent/runtime/memory/observations.jsonl, topics
secrets-architecture-escalonada (confidence 0.9, source ADU-DEC-006) y
grep-env-vuelca-secreto-en-dod (confidence 0.95).

Verificacion del objetivo (comando literal): tras aplicar los 3 pasos IMPLEMENT,
.venv/Scripts/python.exe scripts/check_encoding_guard.py .claude/rules/01-security-architecture.md skills/secure-existing-project/SKILL.md prompts/audit_agent_output.md
debe salir con exit code 0, y el texto de la jerarquia (keyring/DPAPI, SOPS+age,
OAuth2/OIDC) debe aparecer literalmente en 01-security-architecture.md y en SKILL.md
(verificable con grep -c sobre cada archivo).

## Contexto (Fase 0 del Orquestador, verificado en vivo)

- Los 3 archivos target EXISTEN en la ruta viva del repo (no en _backups/, que esta
  gitignored y no se toca):
  - .claude/rules/01-security-architecture.md
  - skills/secure-existing-project/SKILL.md (version actual 2.0.0)
  - prompts/audit_agent_output.md
- skills/secure-existing-project/references/cascade-config-pattern.md es PURO
  CODIGO de carga (config.py/settings.py en bloques de codigo), SIN ninguna
  afirmacion de politica de seguridad -> confirmado leyendo el archivo completo:
  NO es target de contenido, NO TOCAR.
- AGENTS.md seccion "Secretos y seguridad" (linea 397) contiene reglas operativas
  basicas ("no toques privada/", "no desactives guard_paths") que siguen siendo
  ciertas bajo el nuevo encuadre (fallback, no solucion final) -> NO TOCAR, fuera de
  scope de este ticket.
- El enlace de 01-security-architecture.md linea 3 a
  ../../AGENTS.md#secretos-y-seguridad sigue siendo valido -> NO ROMPER ese ancla.

## Files Likely Touched

### repo_motor

- .claude/rules/01-security-architecture.md
- skills/secure-existing-project/SKILL.md
- prompts/audit_agent_output.md (opcional, CONFIRMADO incluir por el humano)

## Read/inspect only (Manager-only / no tocar)

- .agent/runtime/memory/observations.jsonl (fuente de doctrina; leer topics
  secrets-architecture-escalonada y grep-env-vuelca-secreto-en-dod, NO editar)
- skills/secure-existing-project/references/cascade-config-pattern.md (puro codigo
  de config, sin afirmaciones de seguridad; NO es target)
- AGENTS.md (seccion "Secretos y seguridad" sigue vigente tal cual; NO TOCAR)

## Plan de Implementacion

### PASO 1 (IMPLEMENT) - .claude/rules/01-security-architecture.md

Que cambia: reemplazar el punto 1 de la lista bajo "## Politica de Secretos"
(actualmente: "1. privada/: FUERA del workspace del agente. Contiene .env
y configuracion sensible. NUNCA leer ni escribir aqui.") e insertar ANTES de la lista
numerada un bloque nuevo con la jerarquia escalonada. Renumerar los puntos 2 y 3
existentes solo si el formato final lo requiere (mantenerlos con el mismo contenido).

Contenido exacto a insertar (el Builder debe usar este texto como base, ajustando
solo formato Markdown, no doctrina). Bloque de contenido (delimitado por las lineas
=== INICIO CONTENIDO === y === FIN CONTENIDO ===; cada linea de ese bloque va
literal en el archivo target, incluyendo los backticks de codigo inline):

=== INICIO CONTENIDO PASO 1 ===
## Politica de Secretos

**Nota de alcance:** `privada/` es un **fallback operativo local**, no la solucion
de seguridad final. La jerarquia canonica por contexto es:

- **Local mono-usuario:** keyring / OS DPAPI.
- **Compartido o versionado cifrado:** SOPS + age.
- **Productivo / backend:** OAuth2 / OIDC / token efimero.
- **`privada/`** solo aplica como separacion por convencion (fuera del workspace del
  agente + `.gitignore` + hook `guard_paths`) cuando ninguna de las opciones
  anteriores es viable todavia; NO es una barrera criptografica.

1. **`privada/`**: FUERA del workspace del agente. Contiene `.env` y configuracion
   sensible como fallback operativo mientras no exista una alternativa de la
   jerarquia anterior. NUNCA leer ni escribir aqui.
2. **Workspace del agente**: usa `.env.example` con variables vacias; nunca un
   `.env` real.
3. **Carga de secretos**: siempre via variables de entorno desde `privada/` u otro
   mecanismo de la jerarquia anterior, nunca hardcodeadas en codigo del repo.
- **PROHIBIDO** hardcodear tokens/passwords. Usar siempre variables de entorno y
  `***REDACTED***` en logs.
=== FIN CONTENIDO PASO 1 ===

Restricciones:
- NO tocar la linea 3 (enlace ../../AGENTS.md#secretos-y-seguridad); ese enlace
  sigue siendo cierto.
- NO tocar "## Controles Activos" (hook guard_paths, pip-audit, State Drift,
  Allowlist) -- es mecanica vigente, no doctrina de secretos.
- Enlazar la politica escalonada puede ser inline (como arriba) o con una linea
  adicional apuntando a skills/secure-existing-project/SKILL.md (Paso 2); esto es
  opcional, no bloqueante.
- Mantener el estilo Markdown existente (headers ##, listas numeradas, negritas).

DoD Paso 1:
- [ ] El texto de la jerarquia (keyring/DPAPI, SOPS+age, OAuth2/OIDC) aparece
      literalmente en el archivo.
- [ ] privada/ esta descrito con "fallback operativo" (o equivalente semantico
      igual de explicito) y NO como "solucion final" en ningun punto.
- [ ] La linea 3 (enlace a AGENTS.md) permanece intacta.
- [ ] "## Controles Activos" permanece intacta byte a byte (diff no debe tocarla).
- [ ] .venv\Scripts\python.exe scripts\check_encoding_guard.py .claude/rules/01-security-architecture.md
      exit 0.

### PASO 2 (IMPLEMENT) - skills/secure-existing-project/SKILL.md

Que cambia:

1. Frontmatter: bump `version: 2.0.0` -> `version: 2.1.0`.
2. Anadir al final de "## Overview" (tras la linea "Convierte un proyecto con
   credenciales expuestas a uno seguro con separacion privada/publica.") el
   siguiente parrafo:

=== INICIO CONTENIDO PASO 2a (Overview) ===
> **Nota de arquitectura:** la separacion `privada/`/`publica/` de este skill es un
> **fallback operativo por convencion** (util cuando el proyecto aun no tiene
> alternativa mejor), no la solucion de seguridad final. Segun el contexto del
> proyecto, prefiere: **keyring / OS DPAPI** para apps locales mono-usuario, **SOPS +
> age** para secretos compartidos o versionados cifrados, y **OAuth2 / OIDC / tokens
> efimeros** para sistemas productivos o backends. Este workflow documenta el
> fallback `privada/`; no sustituye esas opciones cuando son viables.
=== FIN CONTENIDO PASO 2a ===

3. Nueva seccion insertada inmediatamente despues de "### Paso 6: Verificar" y ANTES
   de "## Output", titulada "### Paso 7 (opcional): Evaluar alternativa de la
   jerarquia escalonada":

=== INICIO CONTENIDO PASO 2b (Paso 7 nuevo) ===
### Paso 7 (opcional): Evaluar alternativa de la jerarquia escalonada

Antes de dar la migracion por completa, evalua si `privada/` es la opcion correcta a
largo plazo o solo el fallback inmediato:

- **El proyecto es local y mono-usuario?** Considera migrar a `keyring` (Python) u
  OS DPAPI (Windows) en vez de `.env` en disco.
- **Los secretos deben compartirse entre desarrolladores o versionarse cifrados?**
  Considera SOPS + age.
- **El proyecto corre en un backend o entorno productivo?** Considera OAuth2 / OIDC
  / tokens efimeros en vez de credenciales estaticas.

Si ninguna alternativa es viable todavia, `privada/` con `.gitignore` + hook
`guard_paths` sigue siendo el fallback operativo valido -- pero queda registrado
como decision temporal, no como arquitectura final.
=== FIN CONTENIDO PASO 2b ===

4. "## Constraints": anadir un cuarto bullet al final:

=== INICIO CONTENIDO PASO 2c (Constraints) ===
- **`privada/` es fallback, no solucion final**: si el proyecto tiene mejor
  alternativa disponible (keyring/DPAPI, SOPS+age, OAuth2/OIDC), documentarla como
  siguiente paso en vez de asumir que la separacion `privada/`/`publica/` cierra el
  tema de seguridad.
=== FIN CONTENIDO PASO 2c ===

Restricciones:
- NO tocar "## References" (sigue apuntando a cascade-config-pattern.md, que NO se
  toca, y security-checklist.md).
- NO tocar los Pasos 1-6 existentes (auditoria, estructura, migracion, config,
  gitignore, verificacion) -- son mecanica operativa valida, no doctrina a degradar.
- Mantener el estilo existente: headers ###, bloques de codigo con backticks,
  bullets con -.

DoD Paso 2:
- [ ] version en frontmatter = 2.1.0.
- [ ] El Overview incluye la nota de arquitectura con los 3 terminos
      (keyring/DPAPI, SOPS+age, OAuth2/OIDC/tokens efimeros).
- [ ] Existe el nuevo "Paso 7 (opcional)" entre Paso 6 y "## Output".
- [ ] "## Constraints" tiene el nuevo bullet sobre privada/ como fallback.
- [ ] Los Pasos 1-6 y "## References" permanecen sin cambios de contenido.
- [ ] .venv\Scripts\python.exe scripts\check_encoding_guard.py skills/secure-existing-project/SKILL.md
      exit 0.

### PASO 3 (IMPLEMENT, opcional CONFIRMADO incluir) - prompts/audit_agent_output.md

Que cambia: anadir un bullet nuevo al final de la seccion "### 3. Tests y gates"
(tras el ultimo bullet actual, que termina en "Un DoD que verifica un patron string o
una ruta ficticia esta verificando lo equivocado.") y ANTES del header
"### 4. Produccion vs tests".

Contenido exacto a insertar (mismo estilo que los bullets existentes -- negrita al
inicio + explicacion + criterio verificable). Bloque de contenido:

=== INICIO CONTENIDO PASO 3 ===
- **Checks de presencia de secretos no deben volcar el valor:** un DoD o gate que
  verifica si una clave existe en `.env`/config sensible debe usar `grep -q`/`grep -c`
  (o equivalente) con una regex **anclada al nombre de la clave** (p.ej. `^CLAVE=`),
  nunca un `grep`/`Select-String` sin anclar que imprima la linea completa con el
  valor en stdout/logs. Si el output auditado muestra un comando de verificacion de
  secretos, confirma que su salida es solo exit code o un conteo, no el contenido de
  la linea. Un gate que "pasa" mostrando el secreto en el log de CI/consola es un
  fallo de higiene aunque el resultado booleano sea correcto.
=== FIN CONTENIDO PASO 3 ===

RESTRICCION CRITICA DE ENCODING: prompts/audit_agent_output.md es un archivo
sin acentos ni caracteres especiales (estilo "generico", "patron", "ANIDADOS",
"minimo", etc. -- verificado leyendo el archivo completo). El bullet nuevo de arriba
YA esta escrito sin acentos (anclada, patron, practica, etc. sin tilde) replicando el
estilo del resto del documento; el Builder debe copiarlo tal cual, sin "corregir"
tildes, para no introducir una inconsistencia de estilo/encoding frente al resto del
archivo. (check_encoding_guard.py no exige ausencia de tildes -- valida
bytes/mojibake/BOM, no estilo -- pero el Builder debe preservar el estilo exacto del
archivo target).

Restricciones adicionales:
- NO reordenar los bullets existentes de la seccion 3.
- NO tocar "### 4. Produccion vs tests" ni ninguna otra seccion del documento.
- NO tocar el formato de tabla en "## Formato de salida obligatorio" ni las secciones
  de clasificacion CEM.

DoD Paso 3:
- [ ] El bullet nuevo existe al final de la seccion "3. Tests y gates", antes de
      "### 4. Produccion vs tests".
- [ ] Menciona explicitamente grep -q o -c y la ancla ^CLAVE= (o formulacion
      equivalente igual de concreta).
- [ ] El bullet esta escrito SIN acentos, replicando el estilo del resto del archivo.
- [ ] El resto del archivo (secciones 1-8, formato de salida, clasificacion CEM)
      permanece sin cambios -- diff debe mostrar solo la insercion del bullet.
- [ ] .venv\Scripts\python.exe scripts\check_encoding_guard.py prompts/audit_agent_output.md
      exit 0.

### PASO 4 (VERIFY) - Verificacion final combinada

Comando:
.venv\Scripts\python.exe scripts\check_encoding_guard.py .claude/rules/01-security-architecture.md skills/secure-existing-project/SKILL.md prompts/audit_agent_output.md

Exit code 0, sin mojibake/BOM/? en palabra en ninguno de los 3 archivos.

## Quality Gates

- Builder ejecuta:
  - .venv\Scripts\python.exe scripts\check_encoding_guard.py .claude/rules/01-security-architecture.md skills/secure-existing-project/SKILL.md prompts/audit_agent_output.md
    (exit 0 obligatorio)
  - Lectura manual del diff final (git diff -- .claude/rules/01-security-architecture.md skills/secure-existing-project/SKILL.md prompts/audit_agent_output.md)
    confirmando que NO se tocaron las secciones marcadas como "NO TOCAR" en cada paso.
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - .venv\Scripts\python.exe .agent\agent_controller.py --validate --json --project-root .

## STOP conditions

- Si el unico modo de "enlazar la politica escalonada" en el Paso 1 requiere crear un
  archivo nuevo fuera de los 3 targets confirmados: NO lo crees: documenta la
  jerarquia inline (ya especificado arriba) en vez de inventar un cuarto archivo.
- Si el Builder detecta que cascade-config-pattern.md SI contiene afirmaciones de
  seguridad (contradiciendo la Fase 0): DETENTE y escala, no lo edites sin
  confirmacion.
- Si tocar el Paso 2 o el Paso 1 rompe el ancla ../../AGENTS.md#secretos-y-seguridad
  o cualquier otro enlace relativo existente: DETENTE y corrige antes de continuar.

## Non-goals

- NO tocar skills/secure-existing-project/references/cascade-config-pattern.md
  (puro codigo de config, sin afirmaciones de seguridad; confirmado en Fase 0).
- NO tocar AGENTS.md seccion Secretos y seguridad (reglas operativas basicas que
  siguen vigentes sin cambio; fuera de scope de este ticket documental).
- NO crear un archivo nuevo fuera de los 3 targets confirmados (01-security-architecture.md,
  SKILL.md, audit_agent_output.md) para enlazar la politica escalonada; se documenta
  inline en los targets existentes.
- NO reordenar ni tocar los Pasos 1-6 de SKILL.md, la seccion References de SKILL.md,
  ni los bullets existentes (1-8) de audit_agent_output.md seccion 3: el cambio se
  limita a insertar contenido nuevo sin reescribir lo vigente.
- NO romper el ancla ../../AGENTS.md#secretos-y-seguridad de 01-security-architecture.md
  linea 3.

## Riesgos

- Bajo: cambio puramente documental (deliverable_type=documentation), blast radius
  limitado a 3 archivos .md, sin tocar codigo, bus, hooks, CI ni estado. Totalmente
  reversible con git diff/git checkout.
- Bajo: la doctrina de contenido viene prescrita literalmente por 2 observations de
  memoria (confidence 0.9 y 0.95) -- no hay juicio de arquitectura que el Builder deba
  inventar, solo transcripcion fiel y ubicacion correcta en cada archivo.

## Decision Arquitectonica

Se opta por degradar el tono de privada/ INLINE en los 3 archivos existentes (sin
crear un archivo nuevo de politica de seguridad) porque: (a) la doctrina ya vive
canonicamente en observations.jsonl (secrets-architecture-escalonada,
grep-env-vuelca-secreto-en-dod) y los 3 targets son los puntos de lectura reales de
agentes/desarrolladores (rule de Claude Code, skill de migracion, prompt de
auditoria); (b) cascade-config-pattern.md se descarta como target porque es codigo
puro sin superficie de afirmacion de politica, evitando mezclar codigo y doctrina en
el mismo archivo; (c) AGENTS.md se preserva sin cambio porque sus reglas operativas
(no tocar privada/, no desactivar guard_paths) siguen siendo ciertas bajo el nuevo
encuadre de fallback -- no hay contradiccion que forzar un cambio alli.

## Decision sobre REVIEW

Single-review basta. No se exige Review 2 adversarial. Justificacion:
- Blast radius estrictamente documental (deliverable_type=documentation), 0
  superficie de codigo/bus/estado/hooks/CI.
- Reversibilidad total y trivial.
- Doctrina no ambigua (prescrita por observations con confidence 0.9/0.95, no
  derivada por el Builder).
- Riesgo residual es de forma (ancla rota, enlace a archivo inexistente, mojibake),
  cubierto por DoD explicito por paso + check_encoding_guard + un solo review
  leyendo el diff de 3 archivos pequenos.

## Criterios de Aceptacion Global (1:1 con el criterio binario de la ficha)
- [ ] 01-security-architecture.md describe privada/ como fallback temporal (no
      solucion final) y enlaza/documenta la politica escalonada.
- [ ] secure-existing-project/SKILL.md (y/o su reference) refleja la jerarquia
      keyring/SOPS/OIDC por contexto, no solo privada/.
- [ ] prompts/audit_agent_output.md seccion 3 refuerza la regla grep-sin-volcado
      (target opcional incluido).
- [ ] .venv\Scripts\python.exe scripts\check_encoding_guard.py exit 0 sobre los 3
      .md tocados.
