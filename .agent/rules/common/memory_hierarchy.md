# Memoria por proyecto: indice/expansion, jerarquia L3/L2/L1 y carga (capa 2)

> **Procedencia:** P6, HEAD base `9b0d0d4a`, 2026-10-20. Seccion origen (verbatim abajo):
> - `## Memoria por proyecto` -- `AGENTS.md:801-856` (zonas 801-821 tambien replicadas en la
>   cuspide como directiva; 823-856 trasladadas integras)
>
> Extractores por encabezado: leer este modulo; la cuspide solo conserva la directiva.
> Censo 2026-10-20: ningun extractor registra esta seccion (`scripts/hermes_build_context_bundle.py`
> registra solo `vocabulario_canonico`, `cem_v0`, `secretos_y_seguridad`).

**Ownership:** este modulo conserva VERBATIM la seccion origen de `AGENTS.md` listada en su
cabecera de procedencia. La cuspide conserva encabezado, directiva (refutaciones
WOT-2026-057a/b, comando canonico de expansion) y puntero. Este modulo es
`referencia-bajo-demanda`: se consulta al disenar o depurar el propio mecanismo de memoria, no
en cada sesion. En divergencia de CONTENIDO manda este modulo; toda modificacion de uno exige
revisar el otro en el mismo commit. No confundir con `.agent/runtime/memory/memory_architecture.md`
(otro objeto: clasificacion de superficies de `.agent/`).
## Memoria por proyecto

**Lo primero, porque es lo que mas se malinterpreta (WOT-2026-057a/b):**

- **`--bootstrap` entrega un INDICE ACOTADO, no el corpus** (el mismo que inyecta
  el hook `SessionStart` en Claude Code, <= 9.000 chars en total, diseno v6
  2026-10-23). Cada linea `- <id>: <titular>` es un titular; el pie declara
  cuantas lecciones NO muestra (con y sin id). Con mediana de 877 chars por
  leccion, la regla accionable vive en la leccion entera, no en el titular.
  `--full` enumera TODAS las lecciones en el mismo formato.
- **`--recall` es la puerta de EXPANSION**, y entrega la leccion ENTERA:
   `python scripts/memory_context.py --recall --query "<termino>"` (ordenado por
   cobertura, con fallback por terminos) o
   `python scripts/memory_context.py --recall --id obs-<slug>` (exacto,
   fail-closed). Ejecutalo ANTES de medir o disenar.
- **El archive portable se lee como UNION de MOTOR + root activo.** Son conjuntos
  DISJUNTOS y ambos importan: el motor trae las lecciones de ingenieria, el
  destino las de topologia. Medido 2026-08-17: 207 + 135, interseccion CERO.
  Cada origen tiene CUOTA en el indice -- la recencia no es relevancia, y sin
  cuota el repo tocado mas recientemente expulsa al otro entero.
- **El hook `SessionStart` inyecta el indice al abrir sesion**, asi que la carga
  del indice dejo de ser una norma que alguien debia recordar. La EXPANSION sigue
  siendo manual.

La jerarquia de tres niveles (L3 -> L2 -> L1) sigue existiendo, pero es el PASO 2
de dos: primero el archive portable unido, despues el mejor tier local.
Centralizado en `bus/memory_loader.py` para bootstrap, review bridge y
pre-compact hook:

- **L3 — `memory_profile.md`** (generado por `memory_consolidate.py --apply`): Perfil breve del proyecto con dominios activos, tickets referenciados y senales recientes. Cargado primero por `memory_loader.get_bootstrap_context()`.
- **L2 — `memory_rules.md`** (generado por `memory_consolidate.py --apply`): Reglas deterministas organizadas por dominio, con IDs estables (R-XXX). Cargado por `memory_loader.get_review_context(domain)` para el review bridge.
- **L1 — `observations.jsonl`**: Fuente de evidencia canonica. Contiene todas las observaciones persistentes. `memory_loader.recall_observations()` ofrece acceso directo con filtro opcional por keyword.
- `MEMORY.md` es un indice humano acotado, con tope de 80 lineas. No es una fuente primaria.
- `scripts/memory_consolidate.py` declara `MEMORY_MD_LINE_CAP = 80` y trunca el indice con un marcador visible cuando se supera el limite. Ademas genera L2 y L3 con `--apply`.
- **Contrato de `MEMORY.md` (WOT-2026-074s): INDICE por topic, nunca volcado
  completo de una senal.** `regen_memory_md` (`scripts/memory_consolidate.py`)
  agrupa las entries por `topic`, lista cada topic bajo su propia seccion
  `## <topic>` con hasta 10 entradas (las mas recientes), y cada `signal` se
  trunca a `MAX_SIGNAL_MEMORY_MD` (200 caracteres) con marcador visible si se
  corta -- el texto COMPLETO de la senal vive en `memory_rules.md` (L2) y en
  `observations.jsonl` (L1), nunca en `MEMORY.md`. Un test que asertara "el
  texto integro de la senal debe aparecer en MEMORY.md" estaria probando el
  contrato EQUIVOCADO (volcado en vez de indice) -- origen de esta nota: un
  test asi (`013e` del repo_destino `Crear_Texto_LLM`) fallo porque asumio esa
  forma, y el fallo era del test, no del artefacto. Recibo re-ejecutable:
  `python scripts/memory_consolidate.py --apply` deja un `MEMORY.md` de hasta
  80 lineas con secciones `## <topic>` (indice), mientras la senal integra de
  cada entrada nueva aparece en `memory_rules.md`.
- `bus/memory_loader.py` es la unica puerta de entrada, y **cada puerta tiene su
  propio tope, nunca uno global** (WOT-2026-057a): `get_bootstrap_context()`
  (archive unido + tier local, CAPADO a un presupuesto de arranque),
  `get_review_context(domain)` (por dominio y **SIN capar** -- un review decide
  APPROVE/CHANGES y no puede perder lecciones; un cap filtrado ahi le costo al
  Manager 14 de 74), `get_compact_context()` (capado por recencia con cuota por
  origen, para el hook de pre-compact).
- **La memoria PRIVADA de un agente no es autoritativa.** Cada backend (Claude Code, Kilo, Codex...) tiene su propio almacen personal, invisible para los demas y para el repo. Lo canonico es lo VERSIONADO: `archive/observations.YYYY-MM.jsonl`, este AGENTS.md, los prompts, las skills y los tests. Si una leccion solo vive en la memoria privada de un backend, para el sistema NO EXISTE.
- **WOT-2026-024r (A1): el archive es la fuente portable de memoria, y el loader LA LEE.** `bus/memory_loader.py` incluye SIEMPRE las entradas de `archive/observations.YYYY-MM.jsonl` en el contexto de bootstrap, recorriendo TODOS los meses, no solo el actual. La precedencia es POR ENTRADA: ante colision de `id` estable gana la copia VIVA de L1, porque pudo editarse despues de archivarse. Antes de A1 el loader solo miraba L3/L2/L1 -- las tres gitignoradas --, asi que la memoria promovida se versionaba, viajaba por git y **no la leia nadie**; coste medido (2026-07-27): una leccion guardada dos veces se reincidio igual y destruyo 7 tests. No fue laguna de memoria: fue memoria escrita, versionada y no leida.
- **Limites declarados de A1 (no son huecos, son alcance):** A1 NO cierra `WOT-2026-024r`. (a) La REGENERACION en bootstrap (quien invoca, cuando, idempotencia, y la reconciliacion con `memory_consolidate`, que hoy regenera L2 desde L1 viva y pierde reglas cuya fuente ya se archivo) es **A2**. (b) A1 **no filtra entradas refutadas**: el schema no tiene campo de vigencia y hay 12 entradas con refutacion en prosa; tocar el schema es NON-GOAL. (c) A1 **no promete portabilidad entre repos**: `scripts/install_agent_system.py` no propaga el `archive/` (0 menciones), asi que un destino nuevo arranca sin el -- eso es `WOT-2026-025o`.
