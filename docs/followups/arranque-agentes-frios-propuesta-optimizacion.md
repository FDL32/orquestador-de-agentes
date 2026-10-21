# Propuesta de optimizacion: arranque de agentes en frio (D1/D2/D3 del informe nan-qwen)

- **Slug:** `arranque-agentes-frios-propuesta-optimizacion`
- **Fecha:** 2026-10-21
- **Estado:** PROPUESTA (sin implementar). Requiere decision del usuario por ficha.
- **Origen:** informe `INFORME_revision_arranque_agentes_frios_20261021.md` (sesion `fdl32-nan-qwen-backlog-20261020-3d`, hallazgos H1-H6),
  re-medido de forma independiente por la sesion `fdl32-agents-md-sessionstart-palanca-a-2-c2`.
- **Relacionado:** `docs/followups/sessionstart-hook-utf8-y-memoria-por-cwd-followup.md`.

    ESTADO_FRESCO: raiz=<worktree del motor de la sesion sessionstart-palanca-a>, HEAD=2e480820, verificado=2026-10-21

## 1. Re-medicion de cada hallazgo (veredicto por evidencia)

| Hallazgo | Veredicto | Evidencia re-ejecutada |
|---|---|---|
| H1 memoria depende del cwd | CONFIRMADO, con cifra distinta | cabecera 478 (cwd motor) vs 683 (con `AGENT_PROJECT_ROOT`), el informe dice 684: el archive versionado cambia por checkout, la cifra no es una constante. La cabecera no nombra las superficies. |
| H2 bytes no-UTF-8 | CONFIRMADO y CAUSA DEMOSTRADA | mismo comando de `.claude/settings.json`, cwd=destino: defecto -> INVALIDO (byte `0x97`, offset 1557); `PYTHONUTF8=1` -> VALIDO (9 bytes no-ASCII = 3 rayas de 3 bytes); `PYTHONIOENCODING=cp1252` -> INVALIDO. `locale.getpreferredencoding(False)` por pipe = `cp1252`. |
| H2 alcance | AMPLIADO (no estaba en el informe) | `.agent/hooks/pre_compact_hook.py:345` hace `print(json.dumps(result, ensure_ascii=False))`: misma clase de defecto. Es el otro hook que emite `additionalContext`. |
| H3 `_dev` obsoleto | CONFIRMADO y AGRAVADO | el bootstrap manda `_dev`; ademas `scripts/check_worktree_topology.py` (citado en `.pre-commit-config.yaml`) solo acepta para tickets WOT la worktree `_dev` en rama `main` o una rama `flight/<sufijo>` (lineas ~328-362). Una rama T3 `FDL32/<nombre>` FALLA (rc=1, "usa la worktree _dev"). Probe: ticket sintetico `WOT-2026-999x`, motor y workspace del par T3, rama `FDL32/...`: falla porque esa rama no es `main` en `_dev` ni `flight/<sufijo>` (no se probo que `_dev`/`flight/` pasen). La practica vigente (104f) y el guard se contradicen. |
| H4 sin script de par | CONFIRMADO | `ls scripts` no tiene creador del par; la receta es prosa en AGENTS.md. |
| H5 `closeout_lessons.md` gitignored | CONTRADICHO para el destino | `git cat-file -e HEAD:<ruta>` y `git cat-file -e origin/main:<ruta>` en el destino -> rc=0 en ambos; `git check-ignore -v` -> rc=1 (no ignorado); ultimo commit que lo toca `6a849e7f`; el motor NO lo versiona (`ls-files --error-unmatch` rc=1). La perdida solo ocurre si el Paso 4-bis consulta una raiz que no es el destino (p.ej. el motor code-only) o un destino sin ese commit. |
| H6 memoria privada != sistema | CONFIRMADO como dato | coherente con AGENTS.md; no es accion de esta propuesta. |

Errores del propio informe a corregir antes de citarlo: (1) H5 declara "gitignored" sin haber comprobado `git ls-files` en el destino;
(2) 684 se presenta como constante; (3) H2 atribuye la causa a `_print_context_safely` solo, y existe un segundo hook con el mismo patron;
(4) H3 no vio que el guard de topologia refuerza la contradiccion, lo que cambia D2 de "actualizar prosa" a "alinear guard + prosa".

## 2. Propuesta (por ficha, en orden de ROI/riesgo)

### D1a. Emision UTF-8 estricta en los dos hooks (codigo, bajo riesgo, primero)
- **Cambio minimo:** `ensure_ascii=True` en el `json.dumps` de `session_start_hook.py` (`_print_context_safely`) y de `pre_compact_hook.py:345`.
  El JSON queda ASCII puro, seguro para cualquier codec ASCII-compatible (no se afirma para UTF-16 ni codecs con estado); un consumidor que parsea JSON recupera los mismos caracteres.
  Censo acotado: solo los 2 hooks con `additionalContext`; los demas hooks que escriben a stdout no estan censados.
  El arreglo tiene que ser de CODIGO, no ambiental: la coordinadora midio que exportar `PYTHONUTF8=1` en la shell rompe 9 tests de la suite canonica en Windows (170 passed sin la variable).
  Alternativa descartada: escribir bytes por `sys.stdout.buffer` (depende de que nadie sustituya stdout; mas superficie).
- **Barrera:** test que ejecuta el comando REAL de `SessionStart` (cwd destino sintetico con un caracter `U+2014` en la memoria) con
  `PYTHONUTF8` retirado y `PYTHONIOENCODING=cp1252` FORZADO en el hijo (si no, el test pasa igual con el defecto en un host UTF-8), y exige
  `all(byte < 0x80)`, `bytes.decode("utf-8")` estricto y que `json.loads` devuelva el caracter original. Mismo test para `pre_compact_hook`.
  Mutacion: volver a `ensure_ascii=False` debe hacer caer ambos tests (se ejecuta y se registra). Se adaptan los tests de `_print_context_safely` existentes.
- **No verificado y fuera de esta ficha:** como decodifica Claude Code el stdout invalido. El fix no depende de saberlo.

### D1b. La cabecera del indice nombra las superficies (codigo, riesgo medio)
- `scripts/memory_context.py --bootstrap` imprime, ademas del total, las superficies unidas y su recuento
  POR ORIGEN (formato ilustrativo `motor=<n> destino=<m>`; el invariante testeado define si el total es suma o union deduplicada) y avisa en una linea cuando `AGENT_PROJECT_ROOT` no esta fijado y el cwd es code-only
  ("destino NO cargado"). Es la forma mas barata de que el agente frio detecte media memoria (no la unica: variable, link o raiz explicita); hoy el bootstrap se lo pide y el pie no lo permite.
- Limite medido: el mecanismo `motor_workspace.txt` resuelve por NOMBRE de directorio hermano y no sirve para pares T3
  (prefijo `FDL32-` distinto entre motor y destino); el aviso no debe depender de el. Se usa `motor_destination_link.json` si existe.
- Barrera: test con dos raices sinteticas, cabecera exige ambas superficies y su cuenta; mutacion: quitar la superficie destino.

### D2. Par de worktrees: script + guard + prosa (tres piezas, orden obligatorio)
1. **D2a script `scripts/create_worktree_pair.py`** (codigo): receta verificada del informe (crear motor, crear destino con el MISMO sufijo,
   escribir el link con rutas `Path.as_posix()` (`json.dumps` NO convierte `\`), `uv sync --frozen` en el motor), `--dry-run`. Estados:
   par ausente -> crear (rc 0); completo y coherente -> no-op (rc 0); parcial o incoherente -> rc != 0 con instrucciones de reparacion. Verificacion final con `collect_session_state.py --project-root`. Test hermetico sobre repos git temporales, con `uv sync` sustituido por un fake.
2. **D2b guard de topologia** (decide el usuario): (i) mantener el guard y mover los WOT T3 a ramas `flight/<sufijo>` o cambiar la convencion
   (menor riesgo); (ii) aceptar la rama de un par T3 (`<owner>/<sufijo>` con destino pareado). La opcion (ii) exige un INVARIANTE explicito
   (sufijo de rama == sufijo del directorio destino == par declarado en `motor_destination_link.json`, resuelto con
   `git worktree list --porcelain`) y una matriz de negativos: spoof por nombre, link ausente o viejo, link a otro par, symlink/traversal,
   colision de mayusculas, destino que no es checkout. Decision de producto previa: hoy el guard es deliberadamente estricto (WOT-2026-040q/040p); relajarlo es cambio de
   barrera y exige bucle de gobierno y prueba de que sigue bloqueando el checkout principal detached y el vuelo cruzado.
3. **D2c prosa canonica** (`prompts/orchestrator_session_bootstrap.md`, regla `_dev` y PREFLIGHT): solo despues de D2b, para no
   documentar un camino que el guard rechaza. Es prompt canonico: ticket + bucle de gobierno + X-09 (la skill apunta, el prompt gobierna).
- **Protocolo de IDs** (colision en `backlog.md`): antes de elegir `WOT-2026-NNNx`, `git fetch` y buscar el ID en `origin/main` y ramas
  hermanas; recibo `backlog-admit` antes de insertar. Ya existe como norma; no se anade mecanismo nuevo en esta propuesta.

### D3. `closeout_lessons.md` (re-acotada tras H5 corregido)
- Ya no es "puente que se pierde": en el destino viaja versionado. Accion minima: el Paso 4-bis de `session_hop.md` declara contra QUE raiz
  mide (`<DESTINO_ROOT>`) y la imprime junto a `closeout_lessons_present`, para que un `false` medido en el motor no se lea como ausencia real.
- Es prompt canonico: mismo tratamiento que D2c. No depende de D2b. Prioridad baja.

## 3. Orden y dependencias

    D1a (independiente) -> D1b (independiente) -> D2a (independiente) -> D2b (bucle de gobierno) -> D2c (prosa canonica)
    D3 (prosa canonica, independiente de D2b)

D1a y D2a son codigo con barrera real y no tocan ninguna superficie congelada. D2b y D2c cambian contrato: no se abren sin decision del usuario.

## 4. Decisiones para el usuario

1. Abrir D1a ya (recomendado: es el unico con defecto demostrado y fix de una linea por hook).
2. Abrir D1b y D2a como fichas separadas.
3. D2b: ¿se relaja el guard de topologia para el par T3, o se declara que los tickets WOT corren siempre en `_dev`/`flight/`?
   Hasta decidirlo, el bootstrap sigue contradiciendo la practica.
4. D3 como ticket propio de prosa o descartada.

## 5. Fuera de alcance
- Reducir `AGENTS.md` (Palanca A, otro documento).
- Verificar el decodificado de Claude Code del stdout del hook.
- Auditar si los 31 worktrees son legitimos.

## 6. Adjudicacion del bucle DESIGN_REVIEW (2026-10-21)

Lentes: Groq (`BA31`, RECHAZAR), Qwen (`BA11`, APROBAR_CON_CAMBIOS), Kilo-DeepSeek (`BA07`, APROBAR_CON_CAMBIOS), Mistral (`BA150`,
APROBAR_CON_CAMBIOS). 4 backends distintos, ninguna sustitucion automatica. Adjudicado por contenido, no por conteo de votos.

ACEPTADO (incorporado arriba): test de D1a con codepage forzada y `all(byte < 0x80)` (BA07: la mutacion original era falsa en un host UTF-8);
test de `pre_compact_hook` y censo acotado; invariante, matriz de negativos y opcion de menor riesgo para D2b (las 4 lentes);
estados de D2a y `as_posix`; redaccion de H3 y D1b sin sobreafirmar; evidencia de H5 con `cat-file` contra `origin/main` (varias lentes
pedian mas de un checkout: se midio el commit base); D3 independiente de D2b.

RECHAZADO con razon:
- "D2b antes de D2a" (BA31): D2a solo crea worktrees y link; el guard actua al trabajar un ticket. Sin dependencia.
- "D1b depende de D2a" (BA150): la cabecera vale sola y su aviso indica `AGENT_PROJECT_ROOT`.
- "`ensure_ascii=True` rompe consumidores que esperan texto literal" (BA31/BA11/BA150): el formato ya es JSON; un consumidor JSON recupera
  los caracteres. El decodificado real de Claude Code queda NO VERIFICADO.
- "D1b genera falsos positivos por conteos variables" (BA11): la cabecera informa recuentos, no aplica umbral.
- "RECHAZAR D2b" (BA31/BA11/BA150): ya esta bloqueado por bucle y decision del usuario; se anade invariante y negativos.

Abierto tras el bucle: ninguna lente probo el decodificado real de Claude Code; D2b es decision de producto.
