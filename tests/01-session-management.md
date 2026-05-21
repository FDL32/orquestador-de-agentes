# ðŸ›ï¸ REGLAS COMUNES - 01 Session Management

---

## ðŸ”„ Protocolo de Inicio (OBLIGATORIO)

**Al inicio de CADA mensaje**, ejecuta:

```bash
python .agent/agent_controller.py
```

Luego:
- Si dice `ROL ACTIVO: [TU_ROL]` â†’ **Es tu turno. ContinÃºa.**
- Si dice `ROL ACTIVO: [OTRO_ROL]` â†’ **NO es tu turno. Informa al usuario.**

---

## ðŸ§­ Router de Complejidad

**Antes de iniciar un trabajo nuevo**, clasifica la tarea para no sobredimensionar el flujo:

- `DIRECTA` â†’ Consulta, explicaciÃ³n, anÃ¡lisis puntual o cambio mecÃ¡nico evidente en 1 archivo.
  No usar flujo multi-agente completo.
- `QUICK` â†’ Fix o mejora en 1-2 archivos, <30 min, sin riesgo de regresiÃ³n ni decisiones de arquitectura.
  Builder directo, sin plan formal.
- `FULL` â†’ >2 archivos, >30 min, nueva funcionalidad, riesgo de regresiÃ³n o decisiones de diseÃ±o.
  Flujo completo Manager â†’ Builder â†’ Manager.

**Regla por defecto:** intenta `QUICK`. Escala a `FULL` solo si aparece complejidad real.

**Si ya existe `work_plan.md` activo o el controller te ha dado un turno concreto:**
respeta el flujo actual y no re-clasifiques a mitad del plan.

---

## â±ï¸ LÃ­mites de SesiÃ³n (OBLIGATORIO)

**La calidad se degrada en sesiones largas.** PrevenciÃ³n obligatoria:

### ðŸ›‘ STOP Inmediato Si:

- â° Llevas **>2 horas** trabajando en el mismo plan
- ðŸ“ Has tocado **>5 archivos** diferentes en esta sesiÃ³n
- ðŸ”„ Has modificado el **mismo archivo >3 veces**
- ðŸ§  Sientes que estÃ¡s "parcheando" en lugar de diseÃ±ar

### ðŸ“‹ Protocolo de STOP

**Cuando alcances un lÃ­mite:**

1. **Verifica completitud:**
   ```bash
   python .agent/agent_controller.py --check-completion
   ```

2. **Si >80% completo:**
   - Termina las tareas pendientes
   - Cambia estado a `READY_FOR_REVIEW` (Builder) o `COMPLETED` (Manager)
   - Entrega al otro agente/usuario

3. **Si <80% completo:**
   - Documenta estado actual en `execution_log.md`
   - Commit con mensaje: `WIP: [breve descripciÃ³n]`
   - **Cierra sesiÃ³n** y descansa
   - Nueva sesiÃ³n = contexto limpio

### ðŸ”„ RecuperaciÃ³n de SesiÃ³n

**Al retomar despuÃ©s de >2 horas:**

```bash
python .agent/agent_controller.py --recover
```

Esto mostrarÃ¡:
- Plan activo
- Archivos modificados recientemente
- Ãšltima actividad

**Importante:** Nueva sesiÃ³n = Oportunidad de revisar decisiones previas con mente fresca.
