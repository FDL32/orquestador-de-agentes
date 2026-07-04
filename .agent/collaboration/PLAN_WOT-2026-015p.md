# PLAN - WOT-2026-015p

Degradar privada/ a fallback temporal (no solucion final) en la doc de seguridad del
motor + documentar la politica escalonada de secretos por contexto.

## Resumen

deliverable_type: documentation. Blast radius: 3 archivos .md del repo_motor, 0
superficie de codigo/bus/estado/hooks/CI. delivery_authority: repo_motor.

## Premisa verificada en Fase 0 (Orquestador)

- Los 3 archivos target existen en la ruta viva (no en _backups/, gitignored):
  .claude/rules/01-security-architecture.md,
  skills/secure-existing-project/SKILL.md, prompts/audit_agent_output.md.
- skills/secure-existing-project/references/cascade-config-pattern.md es PURO
  CODIGO sin afirmaciones de seguridad -> confirmado, NO es target.
- AGENTS.md seccion "Secretos y seguridad" sigue vigente tal cual -> NO TOCAR.
- Doctrina fuente: .agent/runtime/memory/observations.jsonl, topics
  secrets-architecture-escalonada (confidence 0.9) y
  grep-env-vuelca-secreto-en-dod (confidence 0.95). Ambas verificadas presentes
  en el archivo real (lineas 43 y 44).

## Pasos (detalle completo en work_plan.md)

1. PASO 1 (IMPLEMENT): 01-security-architecture.md -- reemplazar el punto 1 de
   "Politica de Secretos" e insertar la jerarquia escalonada
   (keyring/DPAPI, SOPS+age, OAuth2/OIDC) antes de la lista numerada. No tocar
   la linea 3 (enlace a AGENTS.md) ni "Controles Activos".
2. PASO 2 (IMPLEMENT): secure-existing-project/SKILL.md -- bump version a
   2.1.0, nota de arquitectura en Overview, nuevo "Paso 7 (opcional)" tras
   Paso 6, nuevo bullet en Constraints. No tocar Pasos 1-6 ni References.
3. PASO 3 (IMPLEMENT, opcional CONFIRMADO): audit_agent_output.md seccion
   3 "Tests y gates" -- nuevo bullet sobre grep -q/-c con ancla ^CLAVE=,
   escrito SIN acentos (estilo del archivo). No reordenar bullets existentes.
4. PASO 4 (VERIFY): check_encoding_guard.py sobre los 3 .md, exit 0.

## Definition of Done (global, 1:1 con criterio binario de la ficha)

- [ ] 01-security-architecture.md describe privada/ como fallback temporal (no
      solucion final) y enlaza/documenta la politica escalonada.
- [ ] secure-existing-project/SKILL.md refleja la jerarquia keyring/SOPS/OIDC
      por contexto, no solo privada/.
- [ ] audit_agent_output.md seccion 3 refuerza la regla grep-sin-volcado.
- [ ] check_encoding_guard.py exit 0 sobre los 3 .md tocados.

## Decision de Review

Single-review. Blast radius estrictamente documental, reversibilidad total,
doctrina prescrita (no derivada) por observations de memoria con confidence
0.9/0.95. Riesgo residual es de forma (ancla rota, encoding), cubierto por DoD
por paso + check_encoding_guard + una sola lectura de diff.

## Riesgos

- Bajo: cambio documental puro, sin tocar codigo/bus/estado/hooks/CI, totalmente
  reversible.
- Bajo: doctrina no ambigua, el Builder transcribe, no decide arquitectura.

## Veredicto

PLAN APPROVED.
