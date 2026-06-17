# Checklist de Code Review

## Estructura y Organización
- [ ] Imports organizados (stdlib, third-party, local)
- [ ] Sin imports circulares
- [ ] Estructura de archivos sigue estándar del proyecto
- [ ] No hay código duplicado

## Calidad de Código
- [ ] Type hints en todas las funciones
- [ ] Docstrings en funciones públicas (Google style)
- [ ] Nombres descriptivos (funciones, variables, clases)
- [ ] Funciones < 50 líneas (ideal < 30)
- [ ] Sin anidación excesiva (máx 3 niveles)

## Python Moderno
- [ ] Usa `pathlib` (NO `os.path`)
- [ ] Usa f-strings (NO `.format()` o `%`)
- [ ] Type hints con `typing` moderno (`list[str]` vs `List[str]`)
- [ ] Manejo de excepciones específicas (NO bare `except:`)

## Robustez
- [ ] Validación de inputs
- [ ] Manejo de errores con logging
- [ ] Rutas relativas con `pathlib`
- [ ] Sin variables hardcodeadas (usar constantes)

## Seguridad
- [ ] NO secrets en código (API keys, passwords)
- [ ] Variables de entorno via `settings.py`
- [ ] `.gitignore` actualizado
- [ ] Sin `print()` de datos sensibles

## Testing
- [ ] Tests unitarios para lógica crítica
- [ ] Tests de integración si aplica
- [ ] Cobertura > 80% para código nuevo
- [ ] Todos los tests pasan

## Anti-Patrones a Evitar
- [ ] NO God Objects (clases > 500 líneas)
- [ ] NO Magic Numbers (usar constantes nombradas)
- [ ] NO Código muerto (imports/variables no usadas)
- [ ] NO Silent failures (loguear errores)

## Anti-Patrones AP-01 a AP-08
- [ ] AP-01 Mock drift: el patch apunta al simbolo real que llama el codigo bajo test
- [ ] AP-02 Floor assertion: el umbral falla si se comenta la feature que aporta el valor
- [ ] AP-03 Zero-logic wrapper: no hay funciones 1:1 sin logica propia
- [ ] AP-04 Exclusive resource acquisition without reentrancy guard: hay guarda de instancia si existe reentrada
- [ ] AP-05 Return contract drift (None -> bool): los callers usan `is False` / `is True` si el contrato cambio
- [ ] AP-06 Validator evidence missing: el execution log muestra comando, salida y resultado limpio
- [ ] AP-07 Scaffolding misclassified as code: los tickets de solo estructura se tratan como documentation
- [ ] AP-08 Test coverage drift: cada funcion nueva del diff tiene al menos un test directo; suite global pasando no es evidencia suficiente
- [ ] AP-09 Protocol key assumption: si el diff implementa un handler de payload externo, verificar que las claves leídas coinciden con la spec real del protocolo (no nombres supuestos)
- [ ] AP-10 Test surrogate: los tests de integración invocan el módulo/script real, no un sustituto sintético creado en tmp_path; si el test no importa ni llama al artefacto real, es un test del sustituto
- [ ] AP-11 Security gate fail-open: cualquier guarda de seguridad que encuentre config inválida o perfil desconocido debe hacer exit(2)/raise, nunca fallback silencioso a modo permisivo
- [ ] AP-12 Review packet incomplete: si el ticket crea archivos nuevos o entregables no rastreados, el packet de review los enumera y adjunta explicitamente; un diff rastreado incompleto no representa el alcance real
- [ ] AP-13 Supervisor stale process: si el ticket toca `bus/supervisor.py`, verificar que el proceso supervisor se reinició y que el nuevo comportamiento es observable en el bus (p.ej. `BUILDER_RELAUNCH_ATTEMPTED` con el outcome esperado); un test que pase no es evidencia suficiente si el proceso en memoria es el antiguo
- [ ] AP-14 Closeout prompt hallucination: si el ticket modifica prompts de cierre de agente (launcher, `.opencode/agents/`, templates), verificar que las instrucciones dan únicamente el comando canónico completo sin mencionar nombres de parámetros internos que el agente pueda interpretar como flags CLI
- [ ] AP-15 Explicit sequence substitution: si el plan especifica una secuencia de pasos exacta para una operación crítica (p.ej. `git tag -d` + `git tag -a`), verificar que el código implementa esa secuencia en ese orden; rechazar si se sustituyó por un equivalente más corto (p.ej. `git tag -f`) aunque el resultado observable sea idéntico
- [ ] AP-16 Seam inventado / sobreingenieria por vocabulario: rechazar tanto un seam/adapter introducido sin que nada varie a traves de el (un adapter con un solo implementador) como la EXIGENCIA en review de crear interfaces/seams nuevos cuando el `deletion test` muestra que no reaparece complejidad; el vocabulario de diseno describe lo que existe, no fabrica indireccion

## Vocabulario de diseno para review (WOT-2026-010t)

> Origen externo: `mattpocock/skills` `codebase-design` (MIT, Adapted). Lenguaje
> para DESCRIBIR lo que ya existe en el diff, NO para exigir abstracciones nuevas.
> Detalle y ejemplo real: `docs/protocol/manager_review_design_vocabulary_WOT-2026-010t.md`.

- [ ] **deep module:** la pieza tocada, esconde mucho comportamiento tras una
      interfaz pequena? Si la interfaz es casi tan compleja como la
      implementacion (shallow), es candidata a AP-03 (zero-logic wrapper).
- [ ] **interface:** la review cubre TODO lo que un caller debe saber (firma +
      invariantes + orden + modos de error + config requerida), no solo el tipo?
- [ ] **seam:** el cambio introduce un seam (punto donde se altera comportamiento
      sin editar ahi)? Regla: un adapter = seam hipotetico; dos adapters = seam
      real. NO exijas un seam si nada varia a traves de el (sobreingenieria, AP-16).
- [ ] **adapter:** lo etiquetado como adapter rellena un slot real de la
      interfaz, o es indireccion sin variacion? Un adapter sin segundo
      implementador es un seam inventado (AP-16).
- [ ] **deletion test:** si borraras la pieza, reaparece complejidad en N callers
      (gana su sitio) o desaparece sin coste (era pass-through -> AP-03)?
- [ ] **interface is the test surface:** los tests cruzan el mismo seam que los
      callers? Si para probar hay que ir POR DETRAS de la interfaz, la pieza
      tiene la forma equivocada. NO uses esto para exigir mas mocks: usalo para
      preguntar que contrato observable se prueba.

## Aprobacion y Nit
- [ ] Aprobar cuando el cambio mejora la salud del codigo, aunque no sea perfecto: https://google.github.io/eng-practices/review/reviewer/standard.html
- [ ] `Nit` se usa solo para comentarios no bloqueantes, separados de cambios requeridos: https://google.github.io/eng-practices/review/reviewer/comments.html
- [ ] Los cambios pequenos siguen siendo preferibles para acelerar la revision y reducir drift de contexto: https://google.github.io/eng-practices/review/developer/small-cls.html

## Delivery hygiene
- [ ] AP-D01 Scope cleanup destructivo: Builder no usa `git checkout`, `git reset` ni `git revert` sobre archivos fuera de `Files Likely Touched`; si detecta discrepancia, la reporta en `execution_log.md` y pide actualizacion de scope.
- [ ] AP-D02 Artefacto generado sin proteccion: artefactos generados o de runtime (`.agent/context/project-map.json`, `events.jsonl`) quedan excluidos de hooks mutadores y no se reescriben en `pre-push`.
- [ ] AP-D03 Handoff sin ancla de recuperacion: Builder creo M3 (`checkpoint/review-<ticket>`) explicitamente antes de `--mark-ready`; el guard de handoff paso sin bloquear por falta de checkpoint; si hubo discrepancias de scope, se usaron checkpoints en lugar de limpieza destructiva.

## Handoff limpio - comprobaciones pre-review
- [ ] No hay eventos `HANDOFF_BLOCKED` en el bus para este ticket (o si los hay, fueron resueltos explicitamente).
- [ ] El arbol estaba limpio al momento del handoff (sin cambios no commiteados fuera de superficies vivas).
- [ ] Checkpoint M3 existe y es verificable (`git rev-parse checkpoint/review-<ticket>`).
- [ ] Scope discrepancy (si hubo) se reporto como observacion no bloqueante, no como limpieza destructiva.
