# Niveles de Escalación

## 🔴 Alta Urgencia

**Señales:** Bloqueo total, decisión crítica, deadline inminente

**Ejemplos:** "No puedo decidir arquitectura", "Bug crítico bloquea todo"

**Formato:** `### 🚨 ESC-001: [Título] - 🔴 BLOQUEADO`

---

## 🟡 Media Urgencia

**Señales:** Problema técnico complejo, trade-offs similares

**Ejemplos:** "¿pandas o polars?", "¿Dónde poner validación?"

**Formato:** `### 🟡 ESC-002: [Título] - 🟡 CONSULTA`

---

## 🟢 Baja Urgencia

**Señales:** Sugerencia de mejora, optimización

**Ejemplos:** "¿Extraer en helper?", "Librería alternativa"

**Formato:** `### 💡 ESC-003: [Título] - 🟢 SUGERENCIA`

---

## Anti-Patrones

**NO:** "No funciona, ayuda" (sin contexto)
**Sí:** Describir intentos + mensajes de error + opciones

## Respuesta del Manager

```markdown
**Respuesta del Manager:** [FECHA]
- **Decisión:** [Opción elegida]
- **Razonamiento:** [Por qué]
- **Próximo paso:** [Acción específica]
- **Estado:** ✅ RESOLVED
```
