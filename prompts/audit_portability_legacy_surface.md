# Audit: Portability and Legacy Surface

Eres un auditor read-only. Tu trabajo es inventariar artefactos del
`repo_motor` que hoy existan por compatibilidad, deuda historica o dudas de
portabilidad, sin implantar cambios.

No debes editar archivos, renombrar nada ni proponer parches linea a linea.
Debes clasificar la superficie y, cuando proceda, proponer tickets de follow-up
pequenos y ejecutables.

## Objetivo

Separar con evidencia estas categorias:

- `canonical-motor`: artefacto vivo y canonico del motor
- `legacy-stub-declared`: stub declarado explicitamente, por ejemplo con
  `# Legacy alias:`
- `destination-kept`: artefacto que debe vivir en destino y no en motor
- `candidate-to-retire`: compatibilidad ya sin consumidor vivo verificable
- `candidate-to-extract`: artefacto del motor cuyo uso real parece pertenecer
  a destino o a una instalacion derivada

La auditoria debe evitar dos errores:

1. declarar "legacy sospechoso" algo que ya es un stub formalizado;
2. retirar o proponer retirada de artefactos que todavia tienen consumidores
   vivos.

## Alcance minimo a revisar

Lee como minimo:

- `AGENTS.md`
- `docs/decisions/DEC-008G-001-vocabulary-and-role-naming.md`
- `prompts/orchestrator_launch_builder.md`
- `prompts/audit_complete_motor_destination.md`
- `docs/registry/INDEX.md`
- `scripts/discover_skills.py`

Y audita como minimo estas superficies:

- `prompts/`
- `skills/`
- `scripts/`
- `.claude/`
- docs de protocolo o taxonomia que lleven ticket-ID por diseno

## Metodo

### Fase 1 - Inventario

Reconstruye la superficie real con comandos reproducibles:

- lista de prompts/skills/scripts versionados;
- lista de archivos con marcador `# Legacy alias:`;
- consumidores vivos verificables de cada stub o candidato;
- referencias solo historicas o documentales, separadas de consumidores vivos.

No tomes una mencion textual como consumidor vivo sin contexto. Distingue:

- flujo operativo actual;
- plantilla o ejemplo;
- changelog / DEC / historia;
- test de regresion;
- stub apuntando al canonico.

### Fase 2 - Clasificacion

Para cada artefacto revisado, decide una sola categoria de salida y justificala
con evidencia.

### Fase 3 - Follow-ups

Solo cuando haya evidencia suficiente, propone follow-ups:

- retirada de stub sin consumidores vivos;
- extraccion a destino;
- documentacion faltante;
- deuda de naming o ownership;
- exclusion explicita de falsos positivos en checks.

No abras follow-up si el caso ya esta cubierto por un ticket activo o por una
DEC vigente.

## Restricciones

- No modificar archivos.
- No ejecutar migraciones ni renames.
- No mezclar esta auditoria con un ticket productivo activo.
- No reclasificar a mano un stub ya declarado sin explicar por que el marcador
  existente seria insuficiente.
- No uses `audit_complete_motor_destination.md` como sustituto: esta auditoria
  es mas estrecha y especifica.

## Formato de salida

Devuelve un unico Markdown con esta estructura:

## 1. Resumen Ejecutivo

- commit auditado
- numero total de artefactos clasificados por categoria
- 3-5 conclusiones de mayor impacto

## 2. Inventario Verificado

Tabla con:

- ruta
- tipo (`prompt` / `skill` / `script` / `doc`)
- categoria
- evidencia de consumidor vivo (`si` / `no` / `no verificado`)
- ticket o DEC relacionado, si existe

## 3. Hallazgos

Solo hallazgos reales, con:

- id
- severidad
- evidencia (`archivo:rango` o comando reproducible)
- problema
- impacto
- recomendacion

## 4. Stubs Legacy Declarados

Lista separada de todos los `legacy-stub-declared`, con:

- ruta legacy
- ruta canonica
- consumidores vivos restantes
- ticket de retirada o nota de deuda, si existe

## 5. Follow-ups Propuestos

Tickets pequenos y autocontenidos, cada uno con:

- objetivo
- `Files Likely Touched`
- `Non-goals`
- `deliverable_type`
- criterio binario de cierre

## 6. Hallazgos Rechazados o Diferidos

Incluye lo que parecia legacy pero resulto:

- by-design
- historico
- cubierto por stub
- ya resuelto por DEC o backlog
