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

## Decisión de destino de memoria (obligatoria antes de escribir)

Antes de escribir cualquier memoria, declara EXPLÍCITAMENTE su destino. No basta con
"guardar en memoria": las tres memorias tienen contratos distintos y no son intercambiables.

| Destino | Qué es | Portable / validable | Cuándo |
|---------|--------|----------------------|--------|
| `Claude privada` | Memoria personal de Claude Code (`~/.claude/.../memory/`) | NO portable, NO validada por el schema del motor | Hábito transversal del usuario/equipo; no es estado del proyecto |
| `portable motor` | `repo_motor/.agent/runtime/memory/archive/observations.YYYY-MM.jsonl` (wings `engine`/`meta`) | Portable + validable por schema; **versionado en git**, se propaga a destinos via sync | Invariante o contrato generalizable; SIEMPRE con confirmación humana |
| `portable destino` | `repo_destino/.agent/runtime/memory/archive/observations.YYYY-MM.jsonl` (wing `project`) | Portable al destino + validable por schema; no sale del destino | Aprendizaje local del proyecto destino |

### El fichero al que se promueve es el ARCHIVE VERSIONADO (no `observations.jsonl`)

> **`.agent/runtime/memory/observations.jsonl` está GITIGNORED** (`.gitignore:104`) en
> TODAS las worktrees. **Escribir ahí NO promueve nada**: ningún commit lo recoge y ningún
> push lo mueve. Es el buffer de runtime (lo escriben los hooks en cada tool call y
> `session_close_observations.py` en cada cierre): telemetría efímera y lección portable
> comparten fichero.
>
> **El único vehículo portable es el ARCHIVE TRACKEADO:**
> `.agent/runtime/memory/archive/observations.YYYY-MM.jsonl` (un fichero por mes, UTC).
> `git ls-files .agent/runtime/memory/archive/` lo confirma.

Procedimiento de promoción (con confirmación humana explícita):

1. Muestra el JSON exacto que se insertaría y **espera aprobación**.
2. Promueve con el reconciliador, que escribe en el archive del checkout canónico y
   valida `--strict` antes y después (fail-closed):

   ```
   python scripts/reconcile_portable_memory.py --source <worktree> --apply
   ```

3. **COMMITEA el archive.** Sin commit, la promoción no existe.
4. Barrera de verificación: `python scripts/check_portable_memory_promotion.py
   --project-root <repo>` reporta toda lección que esté en `observations.jsonl` y NO en
   el archive (**exit 4** = hay huérfanas; exit 1 = la herramienta falló; exit 0 = limpio).

Reglas de decisión (binarias):

1. **Declara el destino antes de escribir** (`Claude privada`, `portable motor`,
   `portable destino`, o `varias` con desglose por entrada). Sin destino declarado, no
   escribas: vuelve a la propuesta.
2. **Evidencia requerida por destino:** una memoria portable (motor o destino) exige
   evidencia verificable (diff, commit, test, exit code, evento de bus o ruta real). Una
   memoria `Claude privada` puede ser preferencia/hábito sin artefacto, pero entonces NO es
   promovible a portable tal cual.
3. **Promoción al archive portable (`archive/observations.YYYY-MM.jsonl`):** solo si la
   entrada valida contra el schema canónico (`skills/_shared/ap-schema.md`) Y contra el
   consumidor real del motor
   (`bus/memory_loader.py`). Si no valida o no hay evidencia, etiquétala `NO PROMOVIBLE`
   con el motivo y déjala en `Claude privada` o como deuda explícita con ticket.
4. **Aprendizaje útil pero privado:** si durante el ciclo guardaste algo en `Claude
   privada`, decide EXPLÍCITAMENTE si debe promoverse a portable. Si sí, aplica las reglas
   2-3. Si no, registra por qué se queda privado (no promovible / fuera de contrato).

### Drift de schema en `observations.jsonl`

Si `observations.jsonl` (motor o destino) está en **drift de schema** respecto a
`skills/_shared/ap-schema.md` (campos no canónicos, `applies_to` inválido, taxonomías
equivalentes mezcladas), **NO añadas nuevas entradas portables**: abre primero un ticket de
migración de schema y deja el aprendizaje como `NO PROMOVIBLE` (o en `Claude privada`) hasta
que el schema esté reconciliado. Añadir entradas nuevas sobre un schema en drift amplía la
deuda en vez de cerrarla.

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
- **Clasificación CEM opcional** (si aplica): clase de fallo evitado, barrera existente o propuesta, tier afectado y deuda residual explícita.
- **Texto propuesto** (en formato canónico JSON si es `observations.jsonl`)

### Canonical schema for `observations.jsonl`

If you propose an entry for `observations.jsonl`, validate it against
`skills/_shared/ap-schema.md` and against the real motor consumer before
promoting it.

- `applies_to` must be a **single string** from the canonical enum:
  `code`, `mixed`, `docs`, or `all`.
  Accepted values: `all`, `code`, `mixed`, `docs`.
- Do not use arrays or compound strings such as `code,mixed`; the migrator
  normalizes them to `mixed`, but that creates unnecessary drift in new memory.
- `category` is **legacy/backward-compatible**. Do not use it in new entries
  unless you are migrating or preserving a historical record.
- If you introduce extra non-canonical fields (for example `memory_class`),
  explain why they exist and avoid mixing two equivalent taxonomies in the same
  entry without a real consumer need.

## Restricciones

> **No des por hecho** que "memoria" significa solo la del proyecto activo.
>
> **No escribas todavía;** primero propón.
>
> Si uno de los sistemas **no es accesible**, dilo explícitamente y limita la propuesta al que sí hayas podido inspeccionar.
>
> **Promoción al `repo_motor`** (wings engine/meta): nunca promuevas al archive versionado
> `orquestador_de_agentes/.agent/runtime/memory/archive/observations.YYYY-MM.jsonl` sin
> confirmación humana explícita. Muestra el JSON exacto que se insertaría y espera aprobación.
>
> **No confundas escribir con promover:** una entrada añadida a
> `.agent/runtime/memory/observations.jsonl` (gitignored) NO viaja. La promoción se hace
> con `scripts/reconcile_portable_memory.py --apply` y se COMMITEA el archive;
> `scripts/check_portable_memory_promotion.py` es la barrera que caza las huérfanas.
