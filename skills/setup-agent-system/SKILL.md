---
name: setup-agent-system
version: 2.0.0
description: Instalar y configurar el sistema de agentes con flujo oficial por etapas y compatibilidad legacy Manager+Builder en un proyecto existente
triggers: [/agent-setup, /agent-install, /init]
author: agent
role: user
stage: setup
writes_memory: false
quality_gate: false
tags: [core, system]
---

# setup-agent-system

Instala el sistema multi-agente en un proyecto Python existente.

## Overview

Configura el flujo oficial por etapas (`plan -> build -> review -> validate`) y mantiene compatibilidad con el flujo legacy Manager + Builder cuando haga falta.

## Workflow

### Paso 1: Verificar Requisitos

- Python 3.10+
- Proyecto con estructura `src/`
- Git inicializado
- `uv` instalado

### Paso 2: Instalar Sistema

**Opción A: Script automático**
```bash
python orquestador_de_agentes/scripts/install_agent_system.py --install
python orquestador_de_agentes/scripts/install_agent_system.py --sync
```

**Opción B: Manual**
```bash
# Copiar directorio .agent/
cp -r agent_system/.agent /ruta/al/proyecto/publica/repo/

# Copiar reglas modulares
cp -r agent_system/.agent/rules /ruta/al/proyecto/publica/repo/.agent/
```

### Paso 3: Configurar Reglas

Copiar contenido de archivos a los agentes:

1. **Ambos agentes:** Copiar archivos de `.agent/rules/common/` a sus instrucciones
2. **Agente Manager:** Copiar archivos de `.agent/rules/manager/` a sus instrucciones
3. **Agente Builder:** Copiar archivos de `.agent/rules/builder/` a sus instrucciones

### Paso 4: Crear Carpeta Privada

```bash
mkdir -p /ruta/al/proyecto/privada
touch /ruta/al/proyecto/privada/.gitkeep
```

**Estructura plana:**
```
privada/
├── .env
├── config.json
└── .gitkeep
```

### Paso 5: Verificar Instalación

```bash
cd /ruta/al/proyecto/publica/repo
python .agent/agent_controller.py
```

Debe mostrar:
```
ROL ACTIVO: MANAGER
Plan: NINGUNO
Acción: CREATE_PLAN
```

### Paso 6: Primer Ciclo

1. **Usuario** → Solicita funcionalidad al Manager
2. **Manager** → Crea `work_plan.md`
3. **Usuario** → Aprueba plan
4. **Builder** → Implementa según plan
5. **Manager** → Revisa y aprueba
6. **Usuario** → Recibe código listo

## Output

Sistema listo con:
- `.agent/` con controller y workflows
- `.manager_rules` y `.builder_rules`
- `privada/` para credenciales
- Quality Gates configurados

## References

- `references/quickstart-checklist.md` - Checklist de instalación
- `EMPEZAR-AQUI.md` - Guía completa del sistema

## Constraints

- **SIEMPRE** copiar reglas a los agentes
- **SIEMPRE** crear carpeta `privada/`
- **SIEMPRE** verificar con `agent_controller.py`
