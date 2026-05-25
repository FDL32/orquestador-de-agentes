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
