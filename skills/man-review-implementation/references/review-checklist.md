# Checklist de Code Review

## Estructura y OrganizaciÃ³n
- [ ] Imports organizados (stdlib, third-party, local)
- [ ] Sin imports circulares
- [ ] Estructura de archivos sigue estÃ¡ndar del proyecto
- [ ] No hay cÃ³digo duplicado

## Calidad de CÃ³digo
- [ ] Type hints en todas las funciones
- [ ] Docstrings en funciones pÃºblicas (Google style)
- [ ] Nombres descriptivos (funciones, variables, clases)
- [ ] Funciones < 50 lÃ­neas (ideal < 30)
- [ ] Sin anidaciÃ³n excesiva (mÃ¡x 3 niveles)

## Python Moderno
- [ ] Usa `pathlib` (NO `os.path`)
- [ ] Usa f-strings (NO `.format()` o `%`)
- [ ] Type hints con `typing` moderno (`list[str]` vs `List[str]`)
- [ ] Manejo de excepciones especÃ­ficas (NO bare `except:`)

## Robustez
- [ ] ValidaciÃ³n de inputs
- [ ] Manejo de errores con logging
- [ ] Rutas relativas con `pathlib`
- [ ] Sin variables hardcodeadas (usar constantes)

## Seguridad
- [ ] NO secrets en cÃ³digo (API keys, passwords)
- [ ] Variables de entorno via `settings.py`
- [ ] `.gitignore` actualizado
- [ ] Sin `print()` de datos sensibles

## Testing
- [ ] Tests unitarios para lÃ³gica crÃ­tica
- [ ] Tests de integraciÃ³n si aplica
- [ ] Cobertura > 80% para cÃ³digo nuevo
- [ ] Todos los tests pasan

## Anti-Patrones a Evitar
- [ ] NO God Objects (clases > 500 lÃ­neas)
- [ ] NO Magic Numbers (usar constantes nombradas)
- [ ] NO CÃ³digo muerto (imports/variables no usadas)
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

## Aprobacion y Nit
- [ ] Aprobar cuando el cambio mejora la salud del codigo, aunque no sea perfecto: https://google.github.io/eng-practices/review/reviewer/standard.html
- [ ] `Nit` se usa solo para comentarios no bloqueantes, separados de cambios requeridos: https://google.github.io/eng-practices/review/reviewer/comments.html
- [ ] Los cambios pequenos siguen siendo preferibles para acelerar la revision y reducir drift de contexto: https://google.github.io/eng-practices/review/developer/small-cls.html
