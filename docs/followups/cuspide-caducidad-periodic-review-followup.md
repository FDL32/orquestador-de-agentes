# Follow-up: cuspide-caducidad-periodic-review

- **Slug:** `cuspide-caducidad-periodic-review-followup`
- **Fecha:** 2026-10-21
- **Dueno:** decision de usuario para abrir WP
- **Estado:** abierto (deuda)
- **Referencia:** `prompts/doc_optimization.md` PASO 5 (barrera/deuda), `AGENTS.md` (pasada 2 piramide)

## Problema

No existe periodicidad declarada ni mecanismo para revisar si la cuspite de AGENTS.md ha
crecido o decrecido desde la ultima optimizacion. La piramide mueve contenido a modulo, pero
ningun guard periodicamente re-mide los gates Codex (32768 B) y Claude Code (40000 C).

## Criterio de cierre

Un script de revision periodica (cron, GitHub Action, o hook) que re-mida los gates de
pasada 2 (77372/79288 -> 60586/62421 tras movidas) y alerte si la cuspite vuelve a
superar los umbrales. Ratio Codex: 1.85x. Ratio Claude: 1.56x.

## Estado_FRESCO (2026-10-21)

```
ESTADO_FRESCO: raiz=C:\Users\fdl\.t3\worktrees\orquestador_de_agentes\FDL32-agents-md-optimization-cont, HEAD=d640dca5, dirty=2, verificado=2026-10-21T06:22 (hora local del host)
```

- Pasada 2 movio ~17 KB netos. Cuspite actual: 60586 B / 62421 C.
- Gates actuales: 60586/32768 = **1.85x** (Codex), 62421/40000 = **1.56x** (Claude Code).
- Ambas cifras siguen por encima de los gates -> deuda ABIERTA.
- Palanca A (AGENTS.md anidados) se requiere para cerrar ambos gates (definido en contrato).