Modulo de detalle para AGENTS.md "## Convenciones de docstrings y testing", puntos 1 y 3 (WOT-2026-160o). Texto VERBATIM movido sin resumir (`prompts/doc_optimization.md` PASO 4, non-goal "no resumir la evidencia al moverla").

Correccion a `docs/followups/palanca-a-fase0-medicion-informe.md` (WOT-2026-110c, 2026-10-21): esa pasada clasifico todo el bloque "## Convenciones de docstrings y testing" como PASA la condicion (d) completo, pero su censo de consumidores no cubria los terminos "Mock drift"/"Floor assertion" ni sus ejemplos literales. `skills/test-audit/references/junk-patterns.md:70,75` SI cita esos ejemplos exactos como "documentado en AGENTS.md" / "ejemplo real de AGENTS.md". Por eso el punto 2 de AGENTS.md (Mock drift, Floor assertion) NO se movio: solo los puntos 1 y 3, que no tienen esa dependencia, se trasladaron aqui.

### 1. Docstrings como especificación de ejecución (Docstrings-as-Spec)

Cada función, clase o módulo operativo del sistema debe contar con un docstring claro y estructurado en **3 fases**. El agente o auditor contrastará la firma técnica con esta especificación semántica para asegurar el cumplimiento:
- **Before (Pre-condiciones):** Qué estados, variables, archivos o privilegios requiere la función antes de invocarse.
- **During (Proceso y Recursos):** Cuál es el flujo de transformación de datos, qué efectos colaterales (I/O, llamadas de red) realiza y qué recursos del sistema consume.
- **After (Post-condiciones y Errores):** Qué salidas exactas se garantizan, cómo cambian los estados canónicos y qué excepciones específicas se interceptan y lanzan.

### 3. Anti-patrones de implementación

- **Zero-logic wrapper:** una función cuyo cuerpo completo es una única llamada delegada 1:1 sin lógica propia debe ser inlineada o eliminada. Añade indirección cognitiva sin valor.

(= AP-03 en `skills/_shared/anti-patterns.md`.)
