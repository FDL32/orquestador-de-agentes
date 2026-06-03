# Audit Report — Decision Template

Plantilla para procesar hallazgos de `audit_report.md` y documentar decisiones.

## Proceso por Hallazgo

Para cada fila en `.session/audit_report.md`:

```
| src/foo.py | 145 | deadcode | function | 23 | unused_func | 0 | 3 | LEGACY |
                                                                     ↑    ↑
                                                                   ACCIÓN
                                                                (calculado)
```

### 1. Identificar Categoría

| Acción | Critério | Decisión por Defecto |
|--------|----------|----------------------|
| **DEAD** | `commits = 0` | ?? Eliminar |
| **ABANDONED** | `0 < commits < 5` | ??? Revisar manual |
| **LEGACY** | `commits >= 5` | ?? Revisar con equipo |
| **SMELL** | ruff findings | ?? Agendar refactor |

### 2. Validar Antes de Eliminar

Nunca eliminar sin verificar:

```python
# Checklist para DEAD/ABANDONED
- [ ] Símbolo realmente no usado en codebase (grep -r "nombre")
- [ ] No es exportado en __all__ (API pública)
- [ ] No es usado por tests (grep tests/)
- [ ] No está documentado como estable en docstring
```

### 3. Documentar Decisión

```markdown
### Hallazgo: src/foo.py:23 `unused_func` (LEGACY)

**Categoría:** LEGACY (commits=3)

**Análisis:**
- Línea 23: función sin referencias encontradas
- Último commit: 2026-02-15 (hace 72 días)
- Estado: Histórico, potencial API interna

**Decisión:** REVISIÓN REQUERIDA
- [ ] Confirmar que no es parte de API pública
- [ ] Si es interna, eliminar
- [ ] Si es pública, documentar en docstring

**Ejecutado por:** [Usuario]  
**Fecha:** 2026-04-28
```

### 4. Categorías de Acción Final

| Acción | Descripción | Cuando Aplicar |
|--------|-------------|----------------|
| **DELETE** | Eliminar código | DEAD + manual confirmation |
| **REFACTOR** | Mejorar/simplificar | SMELL (ruff findings) |
| **DOCUMENT** | Marcar como API interna | LEGACY + validado equipo |
| **INVESTIGATE** | Análisis manual pendiente | ABANDONED + duda |
| **IGNORE** | Falso positivo | Todos (si aplica) |

---

**Uso:** Copiar plantilla arriba para cada hallazgo significativo en `execution_log.md`.
