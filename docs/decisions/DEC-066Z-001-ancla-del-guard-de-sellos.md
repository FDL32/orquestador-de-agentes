# DEC-066Z-001: Ancla externa para `check_seal_staleness`

**Ticket:** WOT-2026-066z
**Fecha:** 2026-09-08
**Estado:** DECIDED
**Autor:** Operador (decision de diseno), instruido por el bucle L745 (loop_id L720)

## Contexto

`scripts/check_seal_staleness.py` declara en su docstring que resuelve *"the
prompt REALLY consumed (arg wins, else receipt.prompt_path)"*. Su UNICO
consumidor automatico, `scripts/prepush_check.py::run_seal_staleness_check`
(call-site `:1030-1032`), le pasa `receipt`, `batch_run_path` y `project_root`,
pero **nunca `prompt_path`**.

Consecuencia medida: el `arg` gana cero veces en produccion y el guard cae
siempre en `receipt["prompt_path"]`, es decir, el fichero que el propio recibo
declara. **El sello se compara consigo mismo.** Un `seal fresh` verde no
significa *"el prompt ejecutado coincide con el sellado"*, sino *"el recibo dice
lo que dice"*.

> **Snapshot fechado de evidencia (2026-09-08), NO criterio de aceptacion**
> (regla `WOT-2026-024t`): `grep -c "prompt=" scripts/prepush_check.py` -> `0`
> sobre `4c88913`. Ninguna cifra de este DEC es un DoD.

El `work_plan.md` del ticket eleva la eleccion del ancla a decision de diseno con
valvula CONTRACT_GAP, porque *"elegir mal no deja el guard como estaba: lo deja
peor"*. Este DEC cierra esa eleccion.

## Las dos vias candidatas

- **Via A** -- anclar a `batch_run["executor_prompt"]`.
- **Via B** -- que el emisor del sello declare en el recibo la ruta del prompt
  realmente ejecutado (campo nuevo).

## Decision

### 1. Se adopta la VIA B, sola

La cascada de `_prompt_integrity` queda en tres niveles, de mayor a menor
prioridad:

    1. `prompt_path` pasado como argumento          (ya existe, sin cambios)
    2. NUEVO: el campo del recibo que declara el prompt REALMENTE ejecutado
    3. `receipt["prompt_path"]`                     (comportamiento actual)

### 2. La VIA A queda RECHAZADA, y el motivo es de procedencia, no de coste

`prompts/orchestrator_autonomous_ticket_batch.md:221-224` declara el orden de
escritura de los dos artefactos:

> *"The executor writes `start_context_isolation.json` in the destino-rol reports
> dir BEFORE touching any ticket, with `status: PENDING` [...] the later
> `batch_run_<ts>.json` **only COPIES the resolved receipt**."*

`batch_run` **copia del recibo**. Anclar ahi no aporta una fuente independiente:
es el mismo dato un paso mas tarde, es decir, auto-justificacion de segundo
orden. La via A no cierra el defecto que motiva el ticket.

**Correccion de un dato del `work_plan`, para que no se herede el error:** el
contrato afirma que `executor_prompt` es *"PROSA LIBRE (valor literal observado:
una descripcion con numero de lineas, no una ruta)"*. Medido sobre los 5
`batch_run_*.json` que hoy tienen el campo, los 5 son RUTAS (4 limpias, 1 con un
sufijo `(cid-...)`). El dato del contrato es incorrecto. **Pero eso no rehabilita
la via A**: se rechaza por procedencia, no porque el parseo fuera caro.

### 3. De donde sale la independencia (lo que hace que la via B NO sea tautologica)

Es la objecion que las tres lentes del bucle marcaron como CRITICA, y se responde
con el mismo contrato:

- Ningun script del arbol escribe `start_context_isolation.json`. Los tres que lo
  nombran (`check_seal_staleness`, `prepush_check`, `check_batch_run_accounting`)
  solo lo LEEN. El recibo lo escribe un ACTOR, no el codigo que lo audita.
- El recibo se escribe **antes** de tocar ningun ticket, con `status: PENDING`.
- `:225` declara ademas: *"**A third party resolves it** BEFORE the executor
  mutates anything. External resolution is a PREVENTIVE gate"*.

La independencia no viene de que el campo lo escriba otro proceso, sino de que el
recibo se sella ANTES de la ejecucion y lo resuelve un tercero. Un ejecutor que
mas tarde consuma un prompt distinto del sellado produce una discrepancia de
bytes que el guard SI puede ver, porque `actual_sha` se calcula sobre el fichero
resuelto y no sobre lo que el recibo afirma.

### 4. Lo que este DEC NO decide

- **El fallback de nivel 3 se CONSERVA en esta entrega.** Las tres lentes
  coincidieron en que mantener `receipt["prompt_path"]` deja viva una via de
  falso verde, y **tienen razon**. Pero retirarlo roza el DoD 4 del ticket
  (*"un vuelo SIN `batch_run` y sin ancla derivable NO se convierte en rojo
  garantizado"*) y es una decision de politica distinta de la eleccion del ancla.
  **Deuda declarada con dueno: ficha propia, no este ticket.**
- El regimen WARN de `run_seal_staleness_check` sigue siendo WARN a proposito.
- No se toca `_batch_run_for_receipt` ni el anclaje de `batch_run_path` (entrega
  de `WOT-2026-058s`).

## Procedencia de esta decision

Bucle adversarial **L745** sobre el registro citable `L720` (BUC-03),
`challenge_nonce f6ce5742405c2ce8e16c59194e4de346`, `commit_sha 4c88913`.

3 lentes ejecutoras de 5 (BA16 y BA06 quedaron MUDAS; una lente muda no es un
veredicto y no se cuenta):

| Lente | Backend | Veredicto |
|---|---|---|
| BA11 | nan/qwen3.6 | CAMBIOS NECESARIOS |
| BA05 | codex/gpt-5.4-mini | CAMBIOS NECESARIOS |
| BA15 | nan/qwen3.8-flash | NO ACEPTAR TODAVIA |

Las tres refutaron la propuesta inicial (via B principal + via A como fallback):
la cascada de 4 niveles trasladaba la auto-justificacion en vez de romperla, y
tomar ambas vias contradecia el *"UNA DE LAS DOS vias"* del contrato.

**Limite declarado de las lentes, y por que no se siguen al pie de la letra:**
BA11 y BA05 recomendaron la via A como cierre minimo por considerarla *"externa
al recibo"*. Las dos marcaron LIMITE por no tener filesystem, y la verificacion
posterior con acceso al arbol mostro lo contrario (`batch_run` copia del recibo).
Se conserva su CRITICO sobre el fallback -- que es correcto y queda fichado como
deuda -- y se descarta su recomendacion de ancla, por evidencia.
