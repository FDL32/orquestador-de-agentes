# Prompt: Auditoria del Repo Charter (Contract Formation)

> **Modo:** Solo lectura. No implantes nada. No reescribas archivos.
> Auditoria adversarial de la *idea/charter* de un repo ANTES de descomponerlo en
> planes y tickets. Identifica defectos y propon correcciones exactas; no las apliques.
>
> **No dupliques `audit_agent_output.md`.** El `Intent Audit` (seccion 2.b) y la
> `Impact Simulation` (seccion 2.c) de ese prompt son la fuente canonica. Aqui solo
> los **enrutas y especializas** para el `repo_charter.md`.

---

## Entradas obligatorias

Lee antes de evaluar:

- `repo_charter.md` (objeto de la auditoria). **Resolucion de ruta:** en el MOTOR vive en la
  RAIZ (`<motor>/repo_charter.md`), porque el motor no es un `repo_destino`; en un `repo_destino`
  vive en `<destino>/.agent/planning/repo_charter.md`. Busca primero la raiz del motor, luego el
  planning del destino.
- `.agent/planning/evidence_catalog.md` (para verificar que los claims del charter
  tienen evidencia con fiabilidad declarada).
- `.agent/planning/decisions.md` (decisiones `DEC-*` que sostienen el charter).
- `prompts/contract_formation_pipeline.md` (contrato de que campos exige el charter).
- `prompts/audit_agent_output.md` secciones 2.b y 2.c (marco general).

Si falta `repo_charter.md`, dilo y recomienda Contract Formation; no inventes intencion.

## Checklist especifica del charter

1. **Secciones minimas presentes y con contenido real:** `Product Intent`,
   `Architecture Constraints`, `Non-Goals`, `Quality Bar`, `Security Constraints`.
   Una seccion vacia o de relleno es un defecto, no una formalidad cumplida.
2. **Objetivos verificables:** cada `OBJ-*` declara `description`, `success_criteria`
   binario y `failure_modes` concretos (no genericos). Un `OBJ-*` sin `failure_modes`
   no es auditable: marcalo.
3. **failure_modes reales:** describen condiciones que harian fallar el objetivo
   aunque un ticket local pareciera cumplido (no repiten el success_criteria negado).
4. **Negative Audit Checklist accionable:** lista antipatrones verificables que
   invalidan la aceptacion (acoplamiento motor-destino, usuario editando codigo,
   degradar seguridad/trazabilidad, complejidad sin reducir riesgo). >= 2 items.
5. **Coherencia evidencia <-> intencion:** los claims fuertes del `Product Intent`
   se apoyan en evidencia del `evidence_catalog` con fiabilidad suficiente. Evidencia
   externa/inferida media/baja no puede sostener una afirmacion estrategica sin corroborar.
6. **El usuario decide, no escribe:** el charter no exige que el usuario edite codigo
   ni Markdown tecnico; lo incierto vive como `DEC-*`, no como tarea de edicion.
7. **Intent Audit (rutado a 2.b):** aplica el `Intent Audit` de `audit_agent_output.md`
   tomando ESTE charter como fuente de intencion. No redefinas el procedimiento.

## Severidad de hallazgos

- **BLOCKER:** seccion minima ausente; `OBJ-*` sin `failure_modes`; charter pide al
  usuario editar codigo/Markdown; claim estrategico sin evidencia.
- **MAJOR:** Negative Audit Checklist generica o < 2 items; `success_criteria` no binario.
- **MINOR:** redaccion ambigua que no bloquea auditoria.
- **NIT:** estilo/orden.

## STOP conditions

- Si el charter no existe o esta en placeholder: detente, reporta y recomienda genesis.
- Si detectas que el charter contradice un `DEC-*` ya aceptado: marca CONTRACT conflict.
- Si para juzgar la intencion tendrias que inventar producto: marca
  `Intent Audit: no verificable`, no apruebes por buena fe.

## Salida (apta para bucle de mejora)

Entrega:
- `DECISION: APPROVE | CHANGES`.
- Hallazgos por severidad, cada uno con seccion/`OBJ-*` afectado y correccion exacta.
- Si `CHANGES`, una lista de ediciones concretas que el Manager (no el usuario)
  debe aplicar al charter antes de pasar a `plan_graph`.
