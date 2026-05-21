# ðŸ›ï¸ REGLAS COMUNES - 02 Security & Collaboration

---

## ðŸ” Arquitectura de Seguridad

### Estructura del Proyecto

```
proyecto/
â”œâ”€â”€ privada/              # â›” NUNCA acceder - Solo usuario
â”‚   â”œâ”€â”€ .env
â”‚   â”œâ”€â”€ config.json
â”‚   â”œâ”€â”€ credentials.json
â”‚
â””â”€â”€ publica/
    â””â”€â”€ repo/             # âœ… Tu Ã¡rea de trabajo
        â”œâ”€â”€ .agent/
        â”œâ”€â”€ src/
        â”œâ”€â”€ tests/
```

### Tareas segÃºn Ejecutor

| Icono | Tipo | DescripciÃ³n |
|-------|------|-------------|
| ðŸ¤– | TAREA AGENTE | El Builder implementa directamente en `publica/repo/` |
| ðŸ‘¤ | TAREA USUARIO | El Usuario actÃºa en `privada/`. TÃº solo das instrucciones. |

**Para Tareas de Usuario (ðŸ‘¤):**
1. Documentar/Leer instrucciones claras.
2. Incluir pasos para copiar/pegar si es necesario.
3. **ESPERAR** confirmaciÃ³n del usuario.
4. Verificar cambios via `.agent/templates/PRIVATE_REGISTRY.md` (si aplica).

---

## ðŸ“ Sistema de Archivos de ColaboraciÃ³n

| Archivo | PropÃ³sito | Permisos Generales |
|---------|-----------|--------------------|
| `work_plan.md` | PlanificaciÃ³n | Manager escribe / Builder lee |
| `execution_log.md` | BitÃ¡cora | Builder escribe / Manager lee |
| `review_queue.md` | Escalaciones | Ambos escriben (preguntas/respuestas) |
| `notifications.md` | ComunicaciÃ³n | Ambos escriben |
| `TURN.md` | Control de turno | Solo lectura (Auto-generado) |

---

## ðŸŒ¿ Git Protocol (OBLIGATORIO)

**Si el proyecto usa git**, estas reglas aplican siempre:

### Prohibido

- `git add -A` o `git add .` â†’ puede arrastrar archivos ajenos a tu sesiÃ³n
- `git reset --hard` â†’ destruye trabajo no guardado
- `git stash` â†’ mezcla cambios no relacionados
- `git commit --no-verify` â†’ nunca saltarse validaciones

### Obligatorio

- Ejecutar `git status` antes de cualquier `git add`
- AÃ±adir solo archivos concretos: `git add ruta/al/archivo.py`
- Usar mensajes de commit claros, por ejemplo:
  `fix(scope): descripciÃ³n  refs WP-YYYY-NNN`

**Si no hay repositorio git en el proyecto**, ignora esta secciÃ³n sin bloquear el trabajo.

---

## ðŸ—ºï¸ Graphify â€” Consulta Obligatoria en Proyectos Grandes

Si existe `graphify-out/GRAPH_REPORT.md` en el proyecto, consÃºltalo en estos momentos:

| Momento | QuiÃ©n | Para quÃ© |
|---------|-------|----------|
| Inicio de fase IMPLEMENT | Builder | Identificar "hub nodes" (archivos de alto grado) que podrÃ­an verse afectados colateralmente por los cambios del plan |
| Inicio de REVIEW_WORK | Manager | Verificar que el Builder no tocÃ³ archivos de alto grado sin mencionarlos en el log |

**Consulta mÃ­nima:**

```bash
# Ver los 10 archivos mÃ¡s conectados del proyecto
head -30 graphify-out/GRAPH_REPORT.md
```

Si un archivo que vas a modificar aparece en los top-10 de grado, documÃ©ntalo en tu
razonamiento antes de proceder.

**Si el grafo no existe** (proyecto nuevo), ignora esta secciÃ³n sin bloquear el trabajo.
