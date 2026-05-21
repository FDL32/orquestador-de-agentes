# Audit Report â€” Decision Template

Plantilla para procesar hallazgos de `audit_report.md` y documentar decisiones.

## Proceso por Hallazgo

Para cada fila en `.session/audit_report.md`:

```
| src/foo.py | 145 | deadcode | function | 23 | unused_func | 0 | 3 | LEGACY |
                                                                     â†‘    â†‘
                                                                   ACCIÃ“N
                                                                (calculado)
```

### 1. Identificar CategorÃ­a

| AcciÃ³n | CritÃ©rio | DecisiÃ³n por Defecto |
|--------|----------|----------------------|
| **DEAD** | `commits = 0` | âœ‚ï¸ Eliminar |
| **ABANDONED** | `0 < commits < 5` | ðŸ‘ï¸ Revisar manual |
| **LEGACY** | `commits >= 5` | âš ï¸ Revisar con equipo |
| **SMELL** | ruff findings | ðŸ“ Agendar refactor |

### 2. Validar Antes de Eliminar

Nunca eliminar sin verificar:

```python
# Checklist para DEAD/ABANDONED
- [ ] SÃ­mbolo realmente no usado en codebase (grep -r "nombre")
- [ ] No es exportado en __all__ (API pÃºblica)
- [ ] No es usado por tests (grep tests/)
- [ ] No estÃ¡ documentado como estable en docstring
```

### 3. Documentar DecisiÃ³n

```markdown
### Hallazgo: src/foo.py:23 `unused_func` (LEGACY)

**CategorÃ­a:** LEGACY (commits=3)

**AnÃ¡lisis:**
- LÃ­nea 23: funciÃ³n sin referencias encontradas
- Ãšltimo commit: 2026-02-15 (hace 72 dÃ­as)
- Estado: HistÃ³rico, potencial API interna

**DecisiÃ³n:** REVISIÃ“N REQUERIDA
- [ ] Confirmar que no es parte de API pÃºblica
- [ ] Si es interna, eliminar
- [ ] Si es pÃºblica, documentar en docstring

**Ejecutado por:** [Usuario]  
**Fecha:** 2026-04-28
```

### 4. CategorÃ­as de AcciÃ³n Final

| AcciÃ³n | DescripciÃ³n | Cuando Aplicar |
|--------|-------------|----------------|
| **DELETE** | Eliminar cÃ³digo | DEAD + manual confirmation |
| **REFACTOR** | Mejorar/simplificar | SMELL (ruff findings) |
| **DOCUMENT** | Marcar como API interna | LEGACY + validado equipo |
| **INVESTIGATE** | AnÃ¡lisis manual pendiente | ABANDONED + duda |
| **IGNORE** | Falso positivo | Todos (si aplica) |

---

**Uso:** Copiar plantilla arriba para cada hallazgo significativo en `execution_log.md`.
