---
name: self-audit
version: 2.0.0
description: AuditorÃ­a obligatoria que el Builder ejecuta antes de reportar cualquier tarea como completada. Valida tipo de archivo, completitud multi-archivo, regresiÃ³n y gates globales.
triggers: [/self-audit, audit, /inspect]
author: agent
role: builder
stage: review
writes_memory: false
quality_gate: false
tags: [core, system]
---

# bui-self-audit

## CuÃ¡ndo usar
Obligatorio antes de escribir en `execution_log.md` que una tarea estÃ¡ completada.
NO usar para tareas de solo lectura o exploraciÃ³n.

## CuÃ¡ndo NO usar
- Tareas de investigaciÃ³n o anÃ¡lisis sin modificaciÃ³n de archivos
- Lectura de documentaciÃ³n o contexto

---

## Pasos

### Paso 1 â VerificaciÃ³n tipo-especÃ­fica

Para cada archivo modificado en esta tarea:

**Python:**
```bash
python -m py_compile src/archivo.py
```
- â Sin output â OK
- â Hay output â Error de sintaxis. PARA. Corrige antes de continuar.

**YAML:**
```bash
python -c "import yaml; yaml.safe_load(open('data/archivo.yaml', encoding='utf-8')); print('OK')"
```
- â Imprime `OK` â vÃ¡lido
- â ExcepciÃ³n â YAML invÃ¡lido. PARA. Corrige antes de continuar.

**JSON:**
```bash
python -c "import json; json.load(open('data/archivo.json', encoding='utf-8')); print('OK')"
```
- â Imprime `OK` â vÃ¡lido
- â ExcepciÃ³n â JSON invÃ¡lido. PARA. Corrige antes de continuar.

**Si un archivo falla:** no pases al siguiente paso. Corrige y re-verifica ese archivo.

---

### Paso 2 â Protocolo "Ya ExistÃ­a / Ya Estaba Hecho"

Si la tarea del plan ya estaba implementada antes de que tocaras el cÃ³digo:

1. **Cita la lÃ­nea exacta y contenido literal** en el log:
   ```
   EXISTE en `src/foo.py` L133:
   `        self._settings = globals().get("settings")`
   El plan pedÃ­a exactamente esto. Sin cambios aplicados.
   ```
2. **Verifica** que lo que existe cumple el criterio del plan, no solo que "algo con ese nombre existe".
3. Si lo que existe es diferente al plan â implementa el plan y documenta la discrepancia.

**"Ya existÃ­a" sin cita de lÃ­nea = informaciÃ³n incompleta. El Manager pedirÃ¡ evidencia.**

---

### Paso 3 â VerificaciÃ³n de completitud multi-archivo

Si la tarea modificaba N archivos del mismo tipo:

Verifica **cada uno** individualmente. No asumas que si el primero estÃ¡ bien, los demÃ¡s tambiÃ©n.

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

Si hay FALTAs â la tarea no estÃ¡ completa. Completa los archivos que faltan.

---

### Paso 4 â Checklist anti-regresiÃ³n (solo para ISS / code smell / refactor)

Si esta tarea es un fix de code smell, limpieza o refactor menor, responde estas preguntas antes de continuar:

- [ ] Â¿El cÃ³digo original manejaba algÃºn caso de error que esta versiÃ³n ignora?
- [ ] Â¿La construcciÃ³n "fea" existÃ­a por una razÃ³n defensiva? (ej: `globals().get("x")` devuelve `None` donde una referencia directa lanzarÃ­a `NameError`)
- [ ] Â¿LeÃ­ el cÃ³digo circundante (20 lÃ­neas arriba/abajo) para entender el contexto completo?
- [ ] Â¿Si el mÃ³dulo falla al importar, mi versiÃ³n explota donde la original no?

**Si alguna respuesta es "sÃ­" o "no sÃ©":** documenta la pregunta en `execution_log.md` y resuÃ©lvela antes de marcar completo.

Para tareas de nueva funcionalidad o creaciÃ³n de archivos: omitir este paso.

---

### Paso 4b â Reglas de contract para review estructurado

Si la tarea pasó por un review, o si el fix nació de una observación de review, endurece el cierre con estas reglas:

- Rechaza edge cases irreales, riesgos especulativos y rewrites amplios.
- Si un fix disparado por review cambia código, rerun de tests focalizados y rerun de la revisión estructurada.
- Para en cuanto la revisión devuelve 0 findings accionables; no hagas una pasada extra solo para pulir el wording.

Estas reglas refuerzan los pasos 1-4. No sustituyen la verificación tipo-específica ni la frescura documental.

---

### Paso 5 â VerificaciÃ³n de frescura documental

Antes de ejecutar gates de calidad, verifica que la documentaciÃ³n operativa estÃ¡ fresca y sincronizada:

- [ ] `PROJECT.md` refleja el estado real del proyecto y contratos operativos
- [ ] `QUICKSTART.md` documenta flujos operativos actuales sin drift
- [ ] Skills afectados reflejan reglas canÃ³nicas sin contradicciones
- [ ] `TURN.md`, `STATE.md`, `execution_log.md` estÃ¡n alineados y sin ambigÃ¼edad
- [ ] No hay drift entre documentaciÃ³n e implementaciÃ³n del runtime

Si hay drift â corrige la documentaciÃ³n antes de continuar. Frescura documental es obligatoria para reducir drift post-review.

### Paso 6 â Gate completo del proyecto

```bash
ruff check . --exclude .agent
python scripts/run_pytest_safe.py
```

- â Ambos pasan â puedes reportar
- â Alguno falla â corrige y vuelve al inicio del gate

---

### Paso 7 â Reportar en execution_log.md con evidencia real

Solo si los pasos 1-6 pasaron sin errores, escribe en `execution_log.md` el output real:

```markdown
### Tarea X.Y â [DescripciÃ³n] â VERIFICADO

#### ImplementaciÃ³n
- Archivo modificado: `src/foo.py` L45-48
- Cambio: [descripciÃ³n breve]

#### Evidencia de verificaciÃ³n
| VerificaciÃ³n | Comando | Resultado |
|-------------|---------|-----------|
| Sintaxis Python | `py_compile src/foo.py` | â OK |
| YAML vÃ¡lido | `yaml.safe_load('data/x.yaml')` | â OK |
| Frescura documental | VerificaciÃ³n manual de PROJECT.md, QUICKSTART.md, TURN.md | â Sincronizado |
| Ruff | `ruff check src/` | â All checks passed |
| Tests | `python scripts/run_pytest_safe.py` | â 12 passed, 0 failed |

#### Estado
- [x] Implementado por Builder
- [ ] Verificado por Manager
```

**Sin output real de comandos = el Manager pedirÃ¡ evidencia antes de revisar.**
