---
name: manager-orchestrator-loop
version: 1.0.0
description: Skill minima que apunta al nucleo del proceso Manager-Builder por contract_id y sha256, SIN herramienta. Usar cuando un Manager necesita orquestar un objetivo con bucles de revision adversarial sobre una estrategia, sobre cada plan y sobre el prompt del ejecutor, en CUALQUIER sistema. No usar para despachar lentes contra un proveedor concreto ni para encargar una tarea a un backend (eso vive en prompts/ensemble_loop.md y prompts/builder_invocation_contract.md).
triggers: [/manager-loop, /manager-orchestrator, /proceso-manager]
author: agent
role: manager
stage: orchestrator
writes_memory: false
quality_gate: false
tags: [core, process, orchestrator, portable]
source_prompt: prompts/manager_orchestrator_loop.md
contract_id: cid-manager-orchestrator-loop-v1
nucleo_sha256: 335c0854073261de747e409f75b3084bad5195cd52f63ce1310987900fe0b6eb
---

# manager-orchestrator-loop

Skill minima para invocar el nucleo del proceso Manager-Builder portatil.
Esta skill SOLO apunta: no re-declara criterios del nucleo ("skill apunta,
prompt gobierna").

## Fuente canonica

- **Nucleo:** `prompts/manager_orchestrator_loop.md`
  - `contract_id: cid-manager-orchestrator-loop-v1`
  - `sha256: 335c0854073261de747e409f75b3084bad5195cd52f63ce1310987900fe0b6eb`

## Adaptador de referencia

- `prompts/manager_orchestrator_loop.adapter_motor.md` (puede no existir aun;
  se creara en WOT-2026-093e). Si existe, el nucleo lo declara como la pieza
  que traduce cada capacidad a los comandos reales del motor.

## Contraproporcion (regla del repo: "skill apunta, prompt gobierna")

PROHIBIDO re-declarar criterios normativos (estados, roles, reglas de validez
de un bucle, plantillas, esquemas, metricas) en esta skill. Estos criterios
viven una vez en el nucleo (`prompts/manager_orchestrator_loop.md`) y esta
skill solo los remite. Si divergen, prevalece el nucleo.

## Identidad de contrato

Antes de seguir NINGUNA instruccion, verifica que el nucleo accesible tiene el
mismo sha256 que se declara aqui:

```bash
# En el repo del motor:
python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <ruta_al_nucleo>
```

El resultado debe ser `335c0854073261de747e409f75b3084bad5195cd52f63ce1310987900fe0b6eb`.
Si no coincide, o si el nucleo no es accesible, DETENTE e informa al
orquestador. No continuar con un nucleo de hash diferente.

## Que gobierna el nucleo

El nucleo (`prompts/manager_orchestrator_loop.md`) define:

- Roles: MANAGER, EJECUTOR (Builder), LENTE, VERIFICADOR, USUARIO.
- Contrato de capacidades: LECTOR_FS, LENTE_TEXTO, EJECUTOR, EVIDENCIA, etc.
- Reglas de validez de un bucle F/S (identidad, recibo de lectura, minimos).
- Maquina de estados: OBJETIVO -> ANALISIS -> ESTRATEGIA -> [bucle] -> DIVISION
  -> [bucle por plan] -> PROMPT_EJECUTOR -> [bucle] -> EJECUCION -> REVISION -> CIERRE -> MEJORA.
- Plantillas por canal (bundle de ficheros vs bundle de texto).
- Esquemas ejecutables (adjudicacion por ronda, metricas).
- Metricas de mejora continua por ciclo.

## Distincion con skills hermanas

- `ensemble_loop`: despachador de lentes (proveedor concreto). El nucleo no
  sabe de proveedores; el ADAPTADOR traduce.
- `builder-implement-from-plan`: contraparte del Builder. El Manager apunta al
  nucleo; el Builder implementa segun work_plan aprobado.
- `manager-review-implementation`: revision de implementacion del Builder. El
  nucleo define el ciclo completo; esta skill cubre la fase REVISION.
