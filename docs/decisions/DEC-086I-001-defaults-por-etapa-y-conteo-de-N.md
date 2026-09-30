# DEC-086I-001: Defaults de forma por etapa, y si el refuter cuenta en N

**Ticket:** WOT-2026-086i (draft, bloqueado por decisiones pendientes)
**Fecha:** 2026-09-30
**Estado:** **DECIDED**
**Decidido por:** Usuario, 2026-09-30 (respuestas via AskUserQuestion sobre
`PROPUESTA_D1_D2_D3_D5_P10_ratificacion_20260930.md`, workspace).
**Autor de la propuesta:** 2 investigadores del workflow `review-086-decisions-tickets-proposal`
(D-1) + verificacion del orquestador contra el scorecard real.

---

## DECISION 1 (D-1): default de forma por etapa, con margen si falta el refuter

Se ratifica la propuesta O2 de `PROPUESTA_bucles_revision_integral_20260929.md` seccion 5 (D-1) CON
la enmienda 1 (margen de +1):

- Etapa de gobierno (`CONTRACT_AUDIT`, `MANAGER_REVIEW`, `CLOSE`, detectada por `--commit-sha` presente
  o por un ticket activo -- `work_plan.md` no `COMPLETED` -- cuyo ID coincide con `--ticket`): default
  `UNI-4`. **Si el refuter (codex/BA05) no esta disponible, sube a `UNI-5`** (una lente API mas), en vez
  de aceptar `UNI-4` sin refuter.
- Etapa dicha pero no reconocida: tratar como gobierno (`UNI-4`, con el mismo margen si falta refuter).
- Etapa no dicha y con ticket activo: segun `deliverable_type` (`code`/`mixed` -> gobierno;
  `documentation`/`research`/`analysis` -> `UNI-3`).
- Etapa no dicha y sin ticket activo: `EXPLORATORY` (`UNI-2`).
- La forma (UNI/DBL/...) y la etapa (gobierno/diseno/exploratorio) NO acoplan el nonce: bajar N nunca
  quita la exigencia de nonce en las 3 fases de gobierno.

### Premisa verificada antes de decidir

Medido sobre el scorecard del destino (2026-09-30, ventana 2026-08-31..2026-09-30): con codex
disponible, `UNI-4` en gobierno da 0,969 de tasa util con reintento (0,917 sin reintento); sin codex,
0,775 con reintento (0,596 sin reintento). La caida medida de disponibilidad de codex duro ~21 minutos
(22:26-22:47 UTC del 2026-09-29). El margen de +1 cubre exactamente esa perdida de tasa util.

### Condicion de reapertura declarada

Si al implementar `loop` (WOT-2026-086i) con su reintento se mide un >=95% de aprobados sin codex con
`UNI-4` sobre >=20 corridas reales, la enmienda de margen deja de aportar y puede retirarse -- pero
retirarla es una decision nueva, no automatica.

---

## DECISION 2 (D-5 x D-2): el refuter (codex) SI cuenta en N

**Se ratifica:** el refuter cuenta en N, alineado con lo que la barrera real (`check_loop_execution.
structurally_valid_rounds`) ya hace hoy -- cuenta cualquier `backend_key` distinto, sin filtrar por rol,
excluyendo solo al emisor del nonce (BA01). **Esto NO exige tocar `check_loop_execution.py`.**

Consecuencia directa para el registro de formas (WOT-2026-086f, DEC-086F-001): `L720` (BA05 + 4 nan) se
alias-mapea a `DBL-5`, no a `DBL-4`.

### Premisa verificada antes de decidir

Contradiccion medida entre 4 fuentes: `ensemble_loop.md:66` y P8 decian que el refuter NO cuenta;
`check_loop_execution.structurally_valid_rounds` SI lo cuenta (no filtra por rol); el registro `L720`
lo pone DENTRO del fan-out; `orchestrator_autonomous_ticket_batch.md` lo trata como paso "2" tras la
sintesis. Sobre 163 commits con nonce en la ventana medida, 38 (23%) solo alcanzan el minimo de
`code`/`mixed` GRACIAS a contar a codex -- excluirlo de verdad habria dejado esos 38 commits por debajo
del minimo retroactivamente.

### Lo que esta decision NO hace

No excluye de verdad al refuter de N (eso exigiria el campo `step` de WOT-2026-086g mas un cambio de
`check_loop_execution.py`, que se abre como ticket aparte si en el futuro se decide que una ronda que ya
vio la sintesis de BA01 no es independiente).

### Clausula CEM anadida (toda refutacion factual se comprueba)

Toda refutacion del refuter (o de cualquier lente) que afirme un hecho del arbol ("ya aplicado", "no
existe", "la linea X dice Y") se comprueba antes de adoptarla (comando+salida o fichero:linea), re-
ejecutado por quien orquesta el bucle. Motivo medido: el 2026-09-30 Codex, sobre esta misma decision,
refuto una cifra ("81,1% en vez de 93,4%") que resulto ser su propio error de conteo (incluia filas
`exploracion`, que el codigo excluye explicitamente de la barrera de independencia). Ver Anexo.

### Nivel de razonamiento de codex

Se mantiene `model_reasoning_effort: "low"` para el rol de refuter (decision del usuario, 2026-09-30):
el coste extra de subirlo no esta medido y hoy el refuter tiene 93,1-93,4% de utilidad con `low`.

---

## Anexo: verificacion en vivo de las 2 objeciones de Codex sobre esta misma DEC (2026-09-30)

Durante el bucle real que valido la propuesta (`EXPLORATORY-propuesta-086`, `prompt-audit`, 5/5 lentes:
BA05 codex, BA11 nan/qwen3.6, BA13 nan/gemma4, BA24 nvidia/nemotron, BA30 groq/qwen), Codex (BA05) hizo
dos objeciones que el orquestador verifico y REFUTO tras el bucle:

1. **"Codex tiene 81,1% de utilidad, no 93,4%."** FALSO. Codex conto 359-360 rondas incluyendo
   `task_type: exploracion` (pings/smoke), que el propio codigo (`TASK_TYPES` en
   `scripts/ensemble_dispatch.py`) excluye explicitamente de la barrera de independencia por ser trafico
   de sondeo, no de gobierno. Recontando sin `exploracion`: 296 utiles / 318 atribuibles (excluyendo
   errores del llamante como `usage-error`/`missing-nonce`) = **93,1%**, que confirma el 93,4% original
   dentro del margen de redondeo. Recuento:
   `python -c "import json; rows=[json.loads(l) for l in open(r'<destino>/.agent/runtime/ensemble/scorecard.jsonl',encoding='utf-8') if l.strip()]; ..."` -> `93.1`.
2. **"No pude verificar que BA06 no corre en solo lectura (`opencode agent list` fallo con
   `EEXIST: mkdir 'C:\Users\fdl\.config\opencode'`)."** Fue un fallo transitorio de la propia herramienta
   de Codex (el directorio ya existia; condicion de carrera de `opencode`), no un hecho sobre BA06.
   Reproducido directamente por el orquestador: `opencode agent list` con `cwd=<destino>` da
   `build, compaction, explore, general, plan, summary, title, manager` (SIN `auditor`); con
   `cwd=<motor>` da los mismos MAS `auditor, builder` (CON `auditor`). El hallazgo de seguridad de BA06
   (documentado en `HALLAZGO_BA06_no_readonly_en_destino_20260930.md`, destino) queda CONFIRMADO por
   reproduccion directa.

Ninguna de las dos objeciones cambia el veredicto de esta DEC. Se documentan aqui porque la clausula CEM
que esta misma DEC introduce exige comprobar toda refutacion factual antes de adoptarla -- incluidas las
del propio refuter.
