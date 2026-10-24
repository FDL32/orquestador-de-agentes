# Evidence contract (cid-evidence-contract-v0)
<!-- PROMPT-SUMMARY
what: Fuente unica del criterio "evidencia antes que relato": que cuenta como evidencia, la regla probe-o-hipotesis y las etiquetas VERIFICADO / INFERIDO / NO VERIFICADO.
when: Al redactar o auditar cualquier afirmacion causal, historica o de estado, o al citar este criterio desde otra superficie.
not: NO es la barrera de ejecucion (el Stop hook native_stop_hook.py) ni el contrato CEM completo (prompts/audit_agent_output.md).
-->

> Fuente unica de verdad del criterio de evidencia. Adoptada en WOT-2026-044v
> (2026-10-24). Gobierno: skill apunta, prompt gobierna (AGENTS.md; X-09).
> Las demas superficies (AGENTS.md, prompts, skills) REMITEN aqui con una frase corta;
> no repiten el criterio. El test `tests/unit/test_evidence_contract_single_source.py`
> falla si una superficie distinta de este fichero lo re-declara.

---

## Norma

- **Evidencia antes que relato:** ningun auto-reporte de agente es evidencia; usa diff,
  exit code, test, evento de bus, commit o artefacto verificable.
- Toda afirmacion causal, historica o de estado va precedida de un probe ejecutado,
  o marcada como hipotesis.

## Etiquetas de hallazgo

Etiqueta cada hallazgo VERIFICADO / INFERIDO / NO VERIFICADO. Si algo es inferencia,
etiquetalo como inferencia. Solo cuentan como evidencia diff, exit code, salida real
de test, evento de bus, commit/SHA, bytes y git.

## Vinculo con el Stop hook

La barrera de EJECUCION de esta norma vive en `.agent/hooks/native_stop_hook.py`, que
exige abrir una linea del mensaje final con `[EVIDENCIA]` o `[HIPOTESIS]` tras mutar el
repo. Esos marcadores y su mecanismo se CITAN aqui, no se redefinen: la fuente de su
forma es el hook.

## Alcance

DECISION fechada 2026-10-24: `skills/*/references/` queda DENTRO del universo escaneado
por `tests/unit/test_evidence_contract_single_source.py` (si aparece alli una
re-declaracion del criterio, el test cae) pero FUERA de reescritura, porque el censo de
WOT-2026-044v dio 0 re-declaraciones en esas rutas.

Universo escaneado: `AGENTS.md`, `CLAUDE.md`, `prompts/`, `skills/` (incluye
`references/`) y `.agent/rules/`. Fuera de alcance: `.agent/hooks/native_stop_hook.py`,
`CONSTITUTION.md`, `.agent/rules/common/do_now_vs_defer.md`, `llms-full.txt` (derivado).
