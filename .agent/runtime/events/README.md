# `.agent/runtime/events/` — el bus canonico se PODA

> WOT-2026-042k. Esta nota vive en el sitio que se LEE (el directorio del bus),
> no solo en el que se ESCRIBE (`scripts/archive_event_bus.py`). Motivo medido
> (2026-07-27): quien se equivoca leyendo el bus nunca abre el escritor.

## Lo que tienes que saber antes de concluir nada

**Un `events.jsonl` corto o vacio NO significa que el bus este muerto, ni que el
proyecto no tenga historia.** Significa, casi siempre, que los tickets terminales
ya se archivaron.

```
.agent/runtime/events/
├── events.jsonl                      <- bus VIVO: solo tickets NO terminales
├── archive/
│   └── events.<TICKET>.jsonl         <- historico, UN fichero por ticket cerrado
└── logs/
```

## La poda

`scripts/archive_event_bus.py` mueve fuera del bus vivo todos los eventos de un
ticket en cuanto su ultimo `STATE_CHANGED` lo deja en estado terminal
(`COMPLETED`, `SUPERSEDED`, `BLOCKED_FINAL`, legacy `CLOSED`, mas `HUMAN_GATE`,
que este rotador archiva deliberadamente como cierre por escalado).

Destino: `.agent/runtime/events/archive/events.<TICKET>.jsonl`. El bus vivo
conserva unicamente los tickets no terminales.

## Regla de lectura

**Quien reconstruya historia debe mirar LOS DOS sitios.** El bus vivo es una
ventana al trabajo en curso, no el registro completo.

```bash
# El bus vivo: puede estar vacio y ser correcto.
wc -l .agent/runtime/events/events.jsonl

# La historia real:
ls .agent/runtime/events/archive/ | wc -l
grep -h '"event_type"' .agent/runtime/events/archive/events.<TICKET>.jsonl
```

Incidente que origina esta nota: se leyeron 12 eventos del bus vivo y se
concluyo «el bus esta muerto», con 196 ficheros de ticket en `archive/` a un
`ls` de distancia. La ausencia de senal en el bus vivo no es senal de ausencia:
es, por diseño, el resultado normal de la poda.

## Alcance

- El bus (`events.jsonl`, `archive/`, `logs/`) esta gitignorado: es estado
  operativo por destino, nunca compartido entre proyectos.
- Este README SI se versiona en el motor y viaja a los destinos con el
  instalador; es la unica pieza tracked del directorio.
- La autoridad canonica del estado sigue siendo el bus (vivo + archive), no las
  proyecciones (`TURN.md`, `STATE.md`, `work_plan.md`, `execution_log.md`).
