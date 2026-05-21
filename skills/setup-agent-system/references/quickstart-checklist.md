# Checklist de InstalaciÃ³n RÃ¡pida

## Pre-requisitos
- [ ] Python 3.10+
- [ ] Git instalado
- [ ] `uv` instalado (`pip install uv`)

## InstalaciÃ³n
- [ ] Ejecutar script de instalaciÃ³n o copiar manual
- [ ] Verificar `.agent/` existe en `publica/repo/`
- [ ] Verificar `.agent/rules/` existe con archivos modulares

## ConfiguraciÃ³n de Agentes
- [ ] Copiar archivos de `.agent/rules/common/` a ambos agentes
- [ ] Copiar archivos de `.agent/rules/manager/` al agente Manager
- [ ] Copiar archivos de `.agent/rules/builder/` al agente Builder

## Estructura de Seguridad
- [ ] Crear carpeta `privada/`
- [ ] Verificar `.gitignore` incluye `privada/`

## VerificaciÃ³n
- [ ] Ejecutar `python .agent/agent_controller.py`
- [ ] Confirmar estado inicial: MANAGER / CREATE_PLAN

## Primer Uso
- [ ] Crear solicitud al Manager
- [ ] Verificar que crea `work_plan.md`
- [ ] Aprobar plan
- [ ] Verificar que Builder implementa

## SoluciÃ³n de Problemas

### "No es tu turno"
Verificar `TURN.md` y abrir el agente correcto.

### "No se encuentra .agent"
Verificar ruta: debe estar en `publica/repo/.agent/`

### Errores de import
Verificar que `uv sync` se ejecutÃ³ correctamente.
