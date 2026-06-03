---

name: self-audit

version: 2.0.0

description: Auditoría obligatoria que el Builder ejecuta antes de reportar cualquier tarea como completada. Valida tipo de archivo, completitud multi-archivo, regresión y gates globales.

triggers: [/self-audit, audit, /inspect]

author: agent

role: builder

stage: review

writes_memory: false

quality_gate: false

tags: [core, system]

---



# bui-self-audit



## Cuándo usar

Obligatorio antes de escribir en `execution_log.md` que una tarea está completada.

NO usar para tareas de solo lectura o exploración.



## Cuándo NO usar

- Tareas de investigación o análisis sin modificación de archivos

- Lectura de documentación o contexto



---



## Pasos



### Paso 1 À Verificación tipo-específica



Para cada archivo modificado en esta tarea:



**Python:**

```bash

python -m py_compile src/archivo.py

```

- Ü Sin output Æ OK

- Ý Hay output Æ Error de sintaxis. PARA. Corrige antes de continuar.



**YAML:**

```bash

python -c "import yaml; yaml.safe_load(open('data/archivo.yaml', encoding='utf-8')); print('OK')"

```

- Ü Imprime `OK` Æ válido

- Ý Excepción Æ YAML inválido. PARA. Corrige antes de continuar.



**JSON:**

```bash

python -c "import json; json.load(open('data/archivo.json', encoding='utf-8')); print('OK')"

```

- Ü Imprime `OK` Æ válido

- Ý Excepción Æ JSON inválido. PARA. Corrige antes de continuar.



**Si un archivo falla:** no pases al siguiente paso. Corrige y re-verifica ese archivo.



---



### Paso 2 À Protocolo "Ya Existía / Ya Estaba Hecho"



Si la tarea del plan ya estaba implementada antes de que tocaras el código:



1. **Cita la línea exacta y contenido literal** en el log:

   ```

   EXISTE en `src/foo.py` L133:

   `        self._settings = globals().get("settings")`

   El plan pedía exactamente esto. Sin cambios aplicados.

   ```

2. **Verifica** que lo que existe cumple el criterio del plan, no solo que "algo con ese nombre existe".

3. Si lo que existe es diferente al plan Æ implementa el plan y documenta la discrepancia.



**"Ya existía" sin cita de línea = información incompleta. El Manager pedirá evidencia.**



---



### Paso 3 À Verificación de completitud multi-archivo



Si la tarea modificaba N archivos del mismo tipo:



Verifica **cada uno** individualmente. No asumas que si el primero está bien, los demás también.



```bash

# Ejemplo para N archivos YAML

python -c "

import yaml

from pathlib import Path

archivos = list(Path('data/sectors').glob('*.yaml'))

for f in archivos:

    data = yaml.safe_load(f.read_text(encoding='utf-8'))

    if 'seccion_requerida' not in data:

        print(f'FALTA en {f.name}')

    else:

        print(f'OK: {f.name}')

"

```



Si hay FALTAs Æ la tarea no está completa. Completa los archivos que faltan.



---



### Paso 4 À Checklist anti-regresión (solo para ISS / code smell / refactor)



Si esta tarea es un fix de code smell, limpieza o refactor menor, responde estas preguntas antes de continuar:



- [ ] ÿEl código original manejaba algún caso de error que esta versión ignora?

- [ ] ÿLa construcción "fea" existía por una razón defensiva? (ej: `globals().get("x")` devuelve `None` donde una referencia directa lanzaría `NameError`)

- [ ] ÿLeí el código circundante (20 líneas arriba/abajo) para entender el contexto completo?

- [ ] ÿSi el módulo falla al importar, mi versión explota donde la original no?



**Si alguna respuesta es "sí" o "no sé":** documenta la pregunta en `execution_log.md` y resuélvela antes de marcar completo.



Para tareas de nueva funcionalidad o creación de archivos: omitir este paso.



---



### Paso 4b À Reglas de contract para review estructurado



Si la tarea pasó por un review, o si el fix nació de una observación de review, endurece el cierre con estas reglas:



- Rechaza edge cases irreales, riesgos especulativos y rewrites amplios.

- Si un fix disparado por review cambia código, rerun de tests focalizados y rerun de la revisión estructurada.

- Para en cuanto la revisión devuelve 0 findings accionables; no hagas una pasada extra solo para pulir el wording.



Estas reglas refuerzan los pasos 1-4. No sustituyen la verificación tipo-específica ni la frescura documental.



---



### Paso 5 À Verificación de frescura documental



Antes de ejecutar gates de calidad, verifica que la documentación operativa está fresca y sincronizada:



- [ ] `PROJECT.md` refleja el estado real del proyecto y contratos operativos

- [ ] `QUICKSTART.md` documenta flujos operativos actuales sin drift

- [ ] Skills afectados reflejan reglas canónicas sin contradicciones

- [ ] `TURN.md`, `STATE.md`, `execution_log.md` están alineados y sin ambigüedad

- [ ] No hay drift entre documentación e implementación del runtime



Si hay drift Æ corrige la documentación antes de continuar. Frescura documental es obligatoria para reducir drift post-review.



### Paso 6 À Gate completo del proyecto



```bash

ruff check . --exclude .agent

python scripts/run_pytest_safe.py

```



- Ü Ambos pasan Æ puedes reportar

- Ý Alguno falla Æ corrige y vuelve al inicio del gate



---



### Paso 7 À Reportar en execution_log.md con evidencia real



Solo si los pasos 1-6 pasaron sin errores, escribe en `execution_log.md` el output real:



```markdown

### Tarea X.Y À [Descripción] À VERIFICADO



#### Implementación

- Archivo modificado: `src/foo.py` L45-48

- Cambio: [descripción breve]



#### Evidencia de verificación

| Verificación | Comando | Resultado |

|-------------|---------|-----------|

| Sintaxis Python | `py_compile src/foo.py` | Ü OK |

| YAML válido | `yaml.safe_load('data/x.yaml')` | Ü OK |

| Frescura documental | Verificación manual de PROJECT.md, QUICKSTART.md, TURN.md | Ü Sincronizado |

| Ruff | `ruff check src/` | Ü All checks passed |

| Tests | `python scripts/run_pytest_safe.py` | Ü 12 passed, 0 failed |



#### Estado

- [x] Implementado por Builder

- [ ] Verificado por Manager

```



**Sin output real de comandos = el Manager pedirá evidencia antes de revisar.**
