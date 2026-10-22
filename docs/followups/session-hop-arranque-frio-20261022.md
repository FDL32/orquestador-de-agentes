# Puente de continuidad -- flight "optimizacion-arranque-frio" -- 2026-10-22

> **Nota de alcance:** `prompts/session_hop.md` (contract_id `cid-session-hop-v1`), leido
> ENTERO antes de escribir esto, esta diseñado para topologia `repo_motor + repo_destino`
> (escribe su salida en `<DESTINO_ROOT>/orchestrator_pipeline/arranques/`, usa
> `collect_session_state.py --project-root <DESTINO_ROOT>`, su "Restriccion dura" prohibe
> cristalizar estado en ficheros versionados DEL MOTOR). **Esta sesion es motor CODE-ONLY,
> sin `repo_destino`** -- verificado: `runtime.project_root.is_motor_code_only() == True`,
> no existe `orchestrator_pipeline/` en este checkout. El prompt NO aplica tal cual a esta
> topologia. Este documento es el fallback declarado: un brief de continuidad versionado
> en el propio motor, siguiendo la convencion ya establecida en este mismo vuelo (bloques
> `ESTADO_FRESCO` con comando + fecha, igual que los followups de Palanca A/CEM v0), no el
> output formal de `session_hop.md`.

## Estado [snapshot 2026-10-22]

- **HEAD:** `d4f730fc7b3b7d75b03b4705ba546c5607998073` -- `git rev-parse HEAD`, exit=0.
- **Rama:** `FDL32/optimizacion-arranque-frio-cont-20261022` -- `git branch --show-current`, exit=0.
- **Arbol:** sucio con UN fichero nuevo, `docs/followups/palanca-a-fase0-post-114f-remedicion-20261022.md`
  (el informe de medicion de este mismo brief, ver mas abajo) -- `git status --porcelain`, exit=0.
  Se committea junto con este documento.
- **Commits locales sin publicar (10, remoto `origin/main` intacto):**
  `git log --oneline origin/main..HEAD`, exit=0:
  ```
  d4f730fc WOT-2026-114f: corrige comentario stale del hook check-reference-keys + documenta RONDA 3 del bucle
  264830ad WOT-2026-114e: acorta citas (ver F1) -> [F1] y anade anclas navegables
  b6cc0df2 WOT-2026-114d: claves de referencia (ver X#) + split quirurgico de CEM v0 en AGENTS.md
  1905f762 docs: resuelve 4 puntos adicionales de Codex (ronda 2) sobre el guard check_reference_keys.py
  8f520189 docs: corrige atribucion de DEC y refina spec del guard check_reference_keys.py (ronda 1 del bucle)
  426a2ef5 WOT-2026-114c: Fase 2 Palanca A -- mueve ## Vocabulario canonico a modulo
  e2bca241 WOT-2026-114b: retira Hermes (bundle de contexto para agente externo)
  8bdeb3f6 docs: propuesta de optimizacion Hermes/repo-audit + bucle adversarial (EXPLORATORY-hermes-repo-audit-20261022)
  ca8426e4 WOT-2026-114a: baseline E7 pinned e independiente de la funcion bajo prueba
  a374ce09 WOT-2026-114a: registro Hermes re-apuntable por source (Fase 1 Palanca A)
  ```
  Push diferido al final del vuelo con OK humano explicito (regla "Push por vuelo",
  `AGENTS.md`). **La sesion siguiente NO pushea sin autorizacion registrada.**

## Lo cerrado en este vuelo (WOT-2026-114a a 114f)

- 114a: baseline E7 + registro Hermes re-apuntable.
- 114b: retiro de Hermes (bundle de contexto para agente externo).
- 114c: Fase 2 Palanca A -- mueve `## Vocabulario canonico` fuera de `AGENTS.md`.
- 114d: split quirurgico de `## CEM v0` + convencion de claves de referencia (`docs/registry/reference_keys.md`, guard `scripts/check_reference_keys.py`).
- 114e: acorta citas `(ver F1)` -> `[F1]` + anclas navegables (`<a id="f1">`) en el fichero de referencia y la leyenda.
- 114f: corrige comentario stale del hook `check-reference-keys` + RONDA 3 del bucle adversarial (8/9 lentes convergen, 0 defectos reales; opencode/glm bloqueado 3ra vez consecutiva por su bug conocido de `external_directory`).

Cada uno paso sus propios quality gates (ruff/tests focales/pre-commit completo). Ver
commits arriba para detalle; no se repite aqui.

## Estado de los gates de cuspide [snapshot 2026-10-22, comando: `uv run python scripts/measure_agents_md_units.py --json` a HEAD `d4f730fc`]

| Gate | Baseline Fase 0R (HEAD `279d2705`, 2026-10-21) | Ahora (HEAD `d4f730fc`) |
|---|---|---|
| AGENTS.md (Codex, bytes, limite 32768) | 61370 B = 1,87x | 42557 B = 1,30x |
| CLAUDE.md+@AGENTS.md (Claude, chars, limite 40000) | 63292 = 1,58x | 44486 = 1,11x |

**Ningun gate esta cerrado todavia.** Deficit restante: 9789 B (Codex) / 4486 chars (Claude).

## Decision abierta para la sesion siguiente

Ver `docs/followups/palanca-a-fase0-post-114f-remedicion-20261022.md` (medicion fresca de
este mismo dia, commiteado junto a este brief). Resumen del veredicto: **CANDIDATO
ENCONTRADO** -- la subseccion `### Orden de trabajo: AGRUPA los commits... (WOT-2026-026t)`
dentro de `## Convenciones` tiene ~6400 B movibles estimados (4 piezas: incidente del
trio Manager/Builder/Revisor, incidente del filtro `-k`, "Push por vuelo" ya duplicado en
`.agent/rules/common/flight_push_policy.md`, y "Extension: push" con el Gate 2 completo
sin duplicar todavia). Ese movimiento cerraria el gate Claude y dejaria el gate Codex en
~1,10x (de 1,30x), no cerrado del todo.

Ese mismo documento tambien declara una **correccion metodologica** al informe Fase 0R
anterior: su veredicto "SIN CANDIDATO MOVIBLE" se baso en que PASO 3(d) consideraba
`build_llms.py` (que lee `AGENTS.md` completo para `llms-full.txt`) como un veto universal
-- pero `llms-full.txt` es una proyeccion NO cargada en el arranque en frio del agente, asi
que ese veto no debia aplicar a los dos gates reales. La practica (CEM v0 se movio de
todas formas y el gate SI mejoro la cantidad medida) confirma la correccion.

**La sesion siguiente debe decidir, no asumir:**
1. ¿Abrir un ticket WOT-2026-114g (o siguiente sufijo libre) para el split de
   `WOT-2026-026t` siguiendo el mismo patron que 114d/e (refutacion corta se queda, caso
   forense se muda, bucle adversarial de verificacion)?
2. ¿O declarar el frente cerrado en este punto (mejora real de 1,87x/1,58x a 1,30x/1,11x)
   y dejar el resto como deuda con ticket futuro?

## Deuda declarada (no se arregla en este vuelo)

- **Bug de infraestructura `external_directory` en opencode/glm:** reproducido 3 veces
  consecutivas en este mismo vuelo (RONDA 1, 2, 3 del bucle adversarial de CEM v0).
  Bloquea sistematicamente esa lente con `NO VERIFICABLE`, honesto pero inutil para
  cobertura. Candidato a ticket propio, prioridad baja-media (no bloquea nada, solo resta
  una lente de 9 en cada bucle).

## Que invocar primero en la sesion siguiente

1. Lee `prompts/orchestrator_session_bootstrap.md` para fijar rol y metodo (este brief NO
   lo sustituye, solo transporta continuidad -- por diseño de `session_hop.md`).
2. Lee este documento + `docs/followups/palanca-a-fase0-post-114f-remedicion-20261022.md`
   enteros para el ESTADO y la decision abierta de arriba.
3. Re-mide antes de actuar: no confies en las cifras de este brief mas alla de su fecha
   `[snapshot 2026-10-22]` -- vuelve a correr `measure_agents_md_units.py --json` y
   `git log --oneline origin/main..HEAD` al arrancar.

## Lo que NO hacer

- No pushear sin autorizacion humana explicita (10 commits locales, remoto intacto).
- No asumir que el veredicto "CANDIDATO ENCONTRADO" de la remedicion es una orden de
  implementar: es un informe de analisis, la decision de abrir el ticket es del usuario.
- No reintentar indefinidamente la lente opencode/glm por el mismo bug conocido -- es un
  resultado honesto (`NO VERIFICABLE`), no un fallo de despacho a corregir reintentando.
