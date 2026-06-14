# Repo Charter - <nombre del repo/proyecto> (PLANTILLA)

> Copia a `DESTINO_ROOT/.agent/planning/repo_charter.md` y rellena.
> Declara intencion y limites del repo. El usuario aprueba via `DEC-*`; no edita
> este archivo directamente en operacion normal.

## Product Intent
<Que problema resuelve y para quien. 2-5 frases. Sin solucion tecnica todavia.>

## Architecture Constraints
- <restriccion 1: lenguaje, runtime, dependencias permitidas, topologia...>
- <restriccion 2>

## Non-Goals
- <lo que este repo explicitamente NO hara (anti-scope a nivel producto)>

## Quality Bar
- <criterios de calidad medibles: gates, cobertura, latencia, portabilidad...>

## Security Constraints
- <secretos, superficies prohibidas, datos sensibles, permisos>

## Objetivos

### OBJ-001 - <titulo>
- description: <que se logra>
- success_criteria: <condicion binaria de exito>
- failure_modes:
  - <condicion concreta que haria fallar el objetivo aunque un ticket local
    pareciera cumplido>
  - <otra>
- related_plans: [PLAN-00x]

<!-- repetir OBJ-00x segun haga falta -->

## Negative Audit Checklist
Antipatrones verificables que **invalidan la aceptacion** si aparecen:
- [ ] aumenta acoplamiento motor-destino sin justificacion
- [ ] exige que el usuario edite codigo o Markdown tecnico
- [ ] degrada seguridad o trazabilidad
- [ ] introduce complejidad sin reducir riesgo
- [ ] <antipatron especifico de este repo>

## Decisiones pendientes
- <referencia a DEC-00x en decisions.md que bloquean el charter>
