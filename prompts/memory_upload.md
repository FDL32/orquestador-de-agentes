# Prompt: Subida de Memoria

Revisa la última implantación del Builder, la revisión del Manager y el ciclo de planificación.

¿Hay algún aprendizaje suficientemente valioso como para incorporarlo a nuestra estructura de memoria?

## Pasos previos a cualquier propuesta

1. **Inspecciona y compara los niveles de memoria disponibles:**
   - Memoria portable del proyecto (`repo_destino`): `.agent/runtime/memory/`
   - Memoria portable del motor (`repo_motor`): `orquestador_de_agentes/.agent/runtime/memory/`
   - Memoria persistente de Claude Code: `~/.claude/.../memory/`
2. **Lee la documentación** relacionada con la redacción, niveles y estructura de la memoria.
3. **Analiza** si el aprendizaje ya existe total o parcialmente en alguno de los sistemas.
4. **Detecta** posibles duplicados, solapamientos o fusiones útiles con puntos ya establecidos.

## Criterios de clasificación antes de proponer

### Horizonte del cambio

Antes de proponer memoria, pregúntate: **¿este aprendizaje empuja al sistema hacia su arquitectura objetivo o solo describe un parche local?**

- **Promover** aprendizajes que reduzcan futuras reestructuraciones: invariantes de diseño, contratos entre componentes, decisiones arquitectónicas con razonamiento.
- **No promover como memoria estable** fixes de corto plazo que solo compensan síntomas, salvo que también dejen explícita la deuda estructural o el ticket que los reemplazará.
- Si el aprendizaje es un hotfix, la entrada de memoria debe registrar *la causa raíz pendiente*, no solo la solución parcial.

### Realismo de fixtures y seeds

Antes de promover un aprendizaje nacido de tests, pregúntate: ¿el fixture o seed reproduce el formato y contrato reales, o solo valida un stub/localismo del test?

- No promover aprendizajes extraídos de un verde si el test pasa contra un fixture inventado que no coincide con los artefactos reales del `repo_motor` o `repo_destino`.
- Si el caso afecta a parsers, paths, estados o markdown operativo, contrasta siempre el fixture con los archivos reales canónicos antes de concluir si el bug está en producción o en el test.
- Cuando fixture y realidad divergen, el aprendizaje valioso no es "el test pasó", sino qué contrato real debe imponer el fixture para que la suite vuelva a ser señal fiable.
- Si detectas un patrón repetido de fixtures irreales o seeds que no espejan producción, trátalo como aprendizaje de `contrato-operativo` o `deuda-temporal`, no como incidente aislado.
### Topología de repos

Este sistema opera con dos repositorios distintos. Cada propuesta de memoria debe especificar a cuál aplica:

| Nombre canónico | Qué es | Ruta local |
|-----------------|--------|-----------|
| `repo_motor` | Motor portable, fuente canónica del sistema | `orquestador_de_agentes/` |
| `repo_destino` | Proyecto que usa el motor; tiene su propio `.agent/` | Varía por proyecto |
| `workspace_activo` | Raíz operativa con `.agent/` desde la que corre el ticket actual | Coincide con `repo_destino` en la topología actual |
| `entorno_multi_root` | IDE abierto con `repo_motor` + `repo_destino` simultáneamente | VS Code multi-folder |

**Regla:** no uses "workspace" a secas. Usa el nombre canónico que corresponda.
Si un aprendizaje afecta git, CI, memoria, paths, prompts o tooling, especifica a cuál repo aplica.
Si afecta a ambos, dilo explícitamente.

### Wings de memoria

| Wing | Qué captura | Dónde vive |
|------|-------------|-----------|
| `engine` | Arquitectura, bus, código del motor | `repo_motor` → se propaga a destinos via sync |
| `meta` | Proceso, review, colaboración | `repo_motor` → se propaga a destinos via sync |
| `project` | Aprendizajes locales del proyecto destino | `repo_destino`, no sale |

La promoción de `engine`/`meta` al `repo_motor` es **siempre manual y con confirmación humana**.

## Formato de la propuesta

Antes de escribir nada, dame una propuesta con estos campos:

- **Aprendizaje detectado**
- **Por qué merece memoria**
- **Si ya existe algo parecido**
- **Si conviene fusionarlo** con una memoria existente
- **Tipo de aprendizaje:**
  - `arquitectura-estable` — invariante de diseño, contrato entre componentes
  - `contrato-operativo` — regla de proceso, flujo de trabajo
  - `nomenclatura` — vocabulario canónico, definiciones
  - `hotfix-local` — solución puntual con deuda estructural pendiente
  - `deuda-temporal` — problema conocido, sin solución definitiva aún
- **Ámbito exacto:**
  - `repo_motor` — aplica solo al motor portable
  - `repo_destino` — aplica solo al proyecto destino
  - `ambos` — aplica a los dos; indica qué parte a cada uno
- **Wing sugerido:** `engine` / `meta` / `project`
- **Dónde debería vivir:**
  - Solo en memoria del `repo_destino`
  - Solo en memoria del `repo_motor` (requiere confirmación para promoción upstream)
  - En memoria de Claude (hábito transversal del usuario/equipo)
  - En varios (especificar)
- **Archivo exacto a tocar**
- **Texto propuesto** (en formato canónico JSON si es `observations.jsonl`)

## Restricciones

> **No des por hecho** que "memoria" significa solo la del proyecto activo.
>
> **No escribas todavía;** primero propón.
>
> Si uno de los sistemas **no es accesible**, dilo explícitamente y limita la propuesta al que sí hayas podido inspeccionar.
>
> **Promoción al `repo_motor`** (wings engine/meta): nunca escribas en `orquestador_de_agentes/.agent/runtime/memory/observations.jsonl` sin confirmación humana explícita. Muestra el JSON exacto que se insertaría y espera aprobación.
