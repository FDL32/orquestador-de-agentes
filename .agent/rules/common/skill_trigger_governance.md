# Gobierno de triggers de skills — vocabulario cerrado y conflict_policy

> Modulo de referencia (`referencia-bajo-demanda`). Citado desde
> `docs/registry/reference_keys.md` (letra `D`). Validado por
> `scripts/check_reference_keys.py` (formato de cita/ancla) y por
> `scripts/check_skill_collisions.py` (contenido: formato de trigger +
> resolucion de conflict_policy).
>
> Origen: WOT-2026-118a, consenso R3 sobre Eje D de `reference_keys.md`
> ("anadir `conflict_policy` y un vocabulario CERRADO de triggers para que
> el solape de disparadores sea verificable mecanicamente").
>
> **Restriccion de diseno heredada (verificada antes de escribir esto, no
> descubierta de cero):** `scripts/check_reference_keys.py::parse_legend()`
> mapea una letra de leyenda a EXACTAMENTE un fichero destino. Por eso TODAS
> las claves D viven en este unico fichero, replicando el patron ya
> existente `F1`-`F7` de `cem_v0_evidencia_forense.md` -- un eje D de
> multiples claves que enruten a ficheros distintos esta bloqueado por esa
> funcion y no se intenta aqui.
>
> **Verificacion de cobertura de citas (pendiente que el consenso R3 dejo
> explicitamente sin cerrar, resuelta en WOT-2026-118a):** `discover_citation_files()`
> (`scripts/check_reference_keys.py` ~L159) escanea UNICAMENTE `AGENTS.md`
> y `.agent/rules/common/*.md`. NO escanea `CLAUDE.md`, `prompts/` ni
> `skills/`. Como este modulo (y toda cita `[D#]` que lo use) vive dentro de
> `.agent/rules/common/`, queda DENTRO de la cobertura actual del guard sin
> necesidad de extenderlo: el gap de cobertura es real, pero no bloquea el
> Eje D -- solo bloquearia una cita `[D#]` puesta directamente en `CLAUDE.md`,
> `prompts/*.md` o `skills/*/SKILL.md`, que no es el caso de ningun citador
> vivo hoy. Cerrar ese gap de cobertura mas alla de `AGENTS.md`+`common/` NO
> es parte de este ticket (decision declarada, no implicita).

<a id="d1"></a>
**D1.** **Vocabulario cerrado del FORMATO de un trigger** (no de su contenido semantico):
un trigger declarado en `triggers:` de un `SKILL.md` debe cumplir la forma
`^/?[a-z][a-z0-9-]*$` -- un token kebab-case en minusculas, con un `/` opcional
al inicio. Esto NO es una lista fija de palabras permitidas (eso romperia los
~80 triggers vivos sin aportar nada): es un vocabulario cerrado de FORMA, que
hace el solape de triggers verificable por comparacion de string exacta sin
ambiguedad de mayusculas/espacios/prosa libre. Verificado contra el estado
real del repo antes de adoptarlo (WOT-2026-118a): CADA trigger vivo en
`skills/*/SKILL.md` ya cumple esta forma -- la adopcion es no-disruptiva.
Validado por `scripts/check_skill_collisions.py::_invalid_trigger_formats()`;
una violacion es SIEMPRE un error (independiente de `conflict_policy`), porque
un trigger mal formado nunca puede resolverse de forma determinista.

<a id="d2"></a>
**D2.** **`conflict_policy` -- vocabulario cerrado, valores `deny-wins` | `host-wins`:**
dos skills que declaran el MISMO trigger son un conflicto; `conflict_policy`
decide si ese conflicto se DENIEGA (bloquea la barrera, exit 1) o se RESUELVE
deterministicamente sin bloquear.
  - `deny-wins` (default, comportamiento historico sin cambio de
    `check_skill_collisions.py` previo a este ticket): CUALQUIER trigger
    duplicado entre dos `SKILL.md` -- sin importar si uno vive en
    `skills/` (bundle) y el otro en `.agent/skills/` (host) -- es un
    conflicto denegado. Es la politica mas estricta y la que se aplica si no
    se declara ninguna.
  - `host-wins`: formaliza mecanicamente, de forma CONSERVADORA, la
    precedencia host-first que `scripts/discover_skills.py::discover_skills()`
    YA aplica en runtime (cualquier trigger reclamado por ALGUN skill de
    `.agent/skills/` se elimina de la lista de triggers de TODO skill
    homonimo-de-trigger de `skills/`, sin exigir que sean 1:1, antes de
    construir `trigger_map`). **Correccion tras revision adversarial
    (WOT-2026-118a, hallazgo Codex):** la primera redaccion de esta nota
    afirmaba que `host-wins` resolvia "exactamente lo que el runtime YA
    resuelve, ni mas ni menos" -- es FALSO: el runtime resuelve tambien el
    caso 1:N (un host contra varios bundles con el mismo trigger) y N:1,
    mientras que el guard, por diseno, solo rescata el par 1:1 {una ruta
    `skills/`, una ruta `.agent/skills/`}. `host-wins` es un SUBCONJUNTO
    CONSERVADOR deliberado de la resolucion real del runtime, no una
    equivalencia -- se queda corto a proposito (fail-closed en los casos
    1:N/N:1/mismo-layer) en vez de asumir que generalizar la regla sin
    evidencia adicional es seguro. Cualquier otro patron (dos skills del
    MISMO layer con el mismo trigger, un host contra 2+ bundles, o 3+
    ficheros en conflicto) sigue siendo un conflicto denegado incluso bajo
    `host-wins`.
  - **Gap cerrado por este ticket:** antes de WOT-2026-118a,
    `check_skill_collisions.py` (hook `check-skill-collisions`, pre-commit)
    trataba un par host/bundle como colision bloqueante aunque
    `discover_skills.py` ya lo resolviera sin ambiguedad en runtime --
    inconsistencia real entre la barrera y el comportamiento productivo que
    protegia. `--conflict-policy host-wins` existe para que un proyecto que
    deliberadamente override-ea un trigger de bundle desde su `.agent/skills/`
    pueda declarar esa politica explicitamente en vez de que el pre-commit
    la bloquee por sorpresa.

<a id="d3"></a>
**D3.** **Resolucion determinista, no silenciosa:** bajo `host-wins`, un par
resuelto se sigue IMPRIMIENDO (quien gano, quien quedo sombreado) -- se
reporta como informacion, no se oculta -- pero no contribuye al exit code.
La determinacion de "resuelto" depende solo de la ESTRUCTURA del conjunto de
rutas en conflicto (sus layers), nunca del orden de descubrimiento ni de
ningun estado mutable, para que dos corridas del mismo arbol den siempre el
mismo veredicto.
