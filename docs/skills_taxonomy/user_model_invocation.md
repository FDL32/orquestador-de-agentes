# User-invoked vs model-invoked: hybrid support (WOT-2026-010s)

> Origen externo: `mattpocock/skills@dcfc232` (`docs/invocation.md`), MIT,
> **Adapted** (concepto; no se copio bundle ni codigo). Fila en `CREDITS.md`.
> Decision de ruta: `WOT-2026-010r` (hibrido sobre break-glass).

## Que se introdujo

Soporte **backward-compatible** del campo de frontmatter
`disable-model-invocation` en el discovery de skills. Es metadata semantica
aditiva: NO retira `triggers:` ni altera `trigger_map`.

| Frontmatter | Semantica | Efecto en dispatch |
|---|---|---|
| `disable-model-invocation: true` | **user-invoked**: el modelo no debe auto-invocar la skill | Ninguno: `triggers:` sigue funcionando para invocacion manual/explicita |
| campo ausente (defecto) | **model-invoked** | Sin cambio respecto al comportamiento previo |
| `disable-model-invocation: false` | model-invoked explicito | Igual que ausente |
| valor invalido (typo, no-bool) | **model-invoked** (fail-safe) | Un typo nunca oculta la skill al modelo |

## Por que hibrido y no break-glass

`010r` verifico **6 consumidores reales** del campo `triggers:`
(`discover_skills.py`, `bus/skill_resolver.py`, `check_skill_collisions.py`,
`local_audit.py`, `orquestador.py`, `validate_agent_config.py`). Retirar
`triggers:` de golpe reescribiria el grafo de resolucion del bus a la vez.
La ruta hibrida permite introducir la taxonomia user/model-invoked **sin tocar
ese grafo**: `triggers:` sigue siendo el contrato de dispatch; el flag nuevo solo
anade intencion semantica para consumidores futuros.

## Implementacion (donde vive)

- `scripts/discover_skills.py::_derive_disable_model_invocation(fm) -> bool`:
  parsea el flag de forma estable (bool real, string "true", o default False).
- `_scan_skills_dir` expone `disable_model_invocation` en cada skill descubierta,
  junto a `status`/`owner`/`aliases`. Clave **aditiva**: no rompe claves previas.
- **`trigger_map` NO se toca:** se construye solo desde `skill['triggers']` de
  skills `active` (discover_skills.py ~L210). El flag vive en la entrada de skill,
  nunca en el map.

## Barrera de paridad (verificada)

`trigger_map` antes y despues del cambio: **90 triggers, hash sha256[:16] =
`699af0bf`** (identico). Tests:
`tests/test_discover_skills.py::TestDisableModelInvocation` cubre flag=true,
ausencia, valor invalido, exposicion por skill y paridad de `trigger_map`.

## Consumidores NO modificados (y por que es seguro)

Los otros 5 consumidores **no se tocaron** (rigor proporcional): el cambio es
aditivo y ninguno lee el campo nuevo (`grep` confirma 0 lecturas de
`disable`/`invocation`; los hits de `.keys()` son sobre otros dicts).
`bus/skill_resolver.py` filtra por **nombre o trigger** contra el role allowlist
(L128-142); la metadata nueva fluye sin afectar ese filtrado. No romperlo ES
respetarlo (criterio binario del ticket).

## Ruta de retirada futura (fuera de 010s)

La retirada de `triggers:` NO ocurre en este ticket. Cuando un ticket posterior
decida migrar el dispatch a resolucion por `disable-model-invocation`:

1. migrar consumidor a consumidor (los 6), cada uno con su test de paridad;
2. solo cuando los 6 ya no lean `triggers:`, retirar el campo de los SKILL.md;
3. mantener `discover_skills.py --json` antes/despues equivalente como barrera;
4. conservar la gate `--check-contract` (prompt<->skill) verde en cada paso.
