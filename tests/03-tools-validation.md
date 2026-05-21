# ðŸ›ï¸ REGLAS COMUNES - 03 Tools & Validation

---

## ðŸ§  GestiÃ³n de Contexto

- Ejecuta `/compact` manualmente cuando el contexto supere el 50%, si la herramienta lo soporta.
- No esperes a que la compactaciÃ³n automÃ¡tica ocurra en mitad de una tarea importante.
- Antes de compactar, deja estado real en `execution_log.md` o `STATE.md` segÃºn tu rol.
- DespuÃ©s de compactar o retomar sesiÃ³n, vuelve a ejecutar `python .agent/agent_controller.py`
  y relee los archivos crÃ­ticos del plan activo.

---

## ðŸ› ï¸ Validaciones Tipo-EspecÃ­ficas (OBLIGATORIAS)

Antes de dar por bueno un archivo, ambos agentes deben asegurar que cumple su sintaxis bÃ¡sica:

- **Python:** `python -m py_compile <archivo_modificado>`
- **YAML:** `python -c "import yaml; yaml.safe_load(open('<archivo_modificado>', encoding='utf-8'))"`
- **JSON:** `python -c "import json; json.load(open('<archivo_modificado>', encoding='utf-8'))"`

---

## ðŸŽ¯ Recordatorio Final

- âœ… **Protocolo de inicio** obligatorio en cada mensaje
- âœ… **LÃ­mites de sesiÃ³n** para mantener calidad
- âœ… **Seguridad** siempre: privada/ fuera del alcance
- âœ… **ColaboraciÃ³n** clara: usa archivos de estado correctamente
