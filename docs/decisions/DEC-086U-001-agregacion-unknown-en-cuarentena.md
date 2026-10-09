# DEC-086U-001: agregacion de la clase `unknown` en la cuarentena de ensemble

**Ticket:** WOT-2026-086u (escindido de WOT-2026-086k el 2026-10-09 al archivar ese ticket)
**Fecha:** 2026-10-09
**Estado:** **DECIDED**
**Decidido por:** Usuario, 2026-10-09 (respuestas via AskUserQuestion durante Contract Formation
de `T-086U-001`).

---

## DECISION 1 (mecanismo de agregacion): `unknown` se agrega igual que `network_timeout`, SIN `reset_at`

`_quarantine_buckets` (`scripts/ensemble_dispatch.py`) agrega hoy `quota_exhausted` (por perfil o
por backend segun `quota_scope`) y `network_timeout` (por perfil); cualquier otra clase, incluida
`unknown`, cae en la rama `else: continue` y se descarta en silencio.

**Se decide:** `unknown` se agrega EXACTAMENTE con el mismo patron que `network_timeout` --
`(by_profile, perfil)` -- pero SIN intentar derivar `reset_at`: un `UnknownError` (p.ej. el
`UnknownError: Unexpected server error` medido repetidamente contra `opencode-go`) no trae
ninguna hora de reset parseable, a diferencia de la cuota de `codex` (que si la trae y ya resuelve
`WOT-2026-086k`). El campo `reset_at` del bucket queda `None` siempre para esta clase, y
`_quarantine_tables` aplica su camino `default_ttl` YA EXISTENTE (sin constante nueva).

**Se RECHAZA** un bucket/estructura separada para `unknown`: el patron de agregacion por
`(section, key)` ya existente es suficiente: anadir una rama `elif cls ==
_FAILURE_CLASS_UNKNOWN: section, key = "by_profile", ev.get("failed_profile")` junto a la de
`network_timeout` es el cambio minimo.

## DECISION 2 (umbral de repeticion): N=1, mismo criterio que las clases existentes

La ficha original de backlog (redactada 2026-09-30/2026-10-07, antes de este Contract Formation)
dejaba abierta la pregunta de un "umbral N de repeticiones consecutivas" antes de cuarentenar por
`unknown`, con la nota explicita de "a calibrar con barrido, nunca hardcodeado sin medicion".

**Se decide: N=1 — el mismo criterio binario que `quota_exhausted`/`network_timeout` ya aplican
hoy** (CUALQUIER evento de esa clase agrega al bucket; no hay umbral de repeticion para esas dos
clases en el codigo actual, verificado en `_quarantine_buckets`). Introducir un umbral NUEVO
("3+ consecutivos") para `unknown` especificamente, sin un barrido real que lo sostenga, seria
exactamente la heuristica no medida que el charter del motor rechaza (`NG-RAIZ`: "el motor no
decide politica por heuristica... no inventa... reglas sin medirlas").

**Se RECHAZA** un umbral de repeticion consecutiva (`3+`) sin barrido previo. Si en el futuro se
mide que `unknown` produce demasiado ruido de cuarentena (falsos positivos por un fallo aislado),
eso es una DEC nueva con datos reales, no una decision a priori de este ticket.

**Consecuencia practica:** un UNICO evento `unknown` ya pone en cuarentena al perfil (mismo
comportamiento que ya existe hoy para `network_timeout`). El `count` del bucket sigue
acumulandose con eventos repetidos (ya lo hace el codigo actual), pero no condiciona si entra en
cuarentena o no -- solo informa cuantas veces se repitio.

---

## Impacto en el contrato formal T-086U-001

Estas 2 decisiones resuelven las 2 preguntas que impedian congelar el contrato (mecanismo de
agregacion, umbral de repeticion). El resto de campos (Forbidden Surfaces, DoD, Files Likely
Touched) se redactan con criterios binarios en el contrato, sin decision de producto adicional.
