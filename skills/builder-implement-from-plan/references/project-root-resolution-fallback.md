# Project root resolution fallback

**Por que esto es un paso obligatorio, no una obviedad:** `resolve_project_root()`
(`runtime/project_root.py`) cae al MOTOR por defecto
(`Path(__file__).resolve().parent.parent`) cuando `AGENT_PROJECT_ROOT` no esta
exportada -- y el `STATE.md`/`work_plan.md` DEL MOTOR existen, son legibles y
NO dan error: describen el seed de dogfooding del propio motor (hoy
`ACTIVE_TICKET: WOT-2026-022c / STATUS: COMPLETED`, ticket de julio, ver
`WOT-2026-070q`), no el ticket real. Un Builder que se abre en un IDE
multi-root (motor + destino a la vez) y lee `STATE.md` con una ruta relativa
o sin declarar su raiz puede leer el fichero DEL MOTOR sin ningun sintoma de
error -- ambos ficheros existen, ambos son validos, y solo uno es el tuyo.
REPRODUCIDO EN VIVO: una sesion (Kilo/qwen3.6) abierta "en este mismo repo"
sin `--project-root`/`AGENT_PROJECT_ROOT` explicito leyo el `STATE.md` del
motor y reporto un ticket (`WOT-2026-022c`) que no tenia nada que ver con el
`{{TICKET_ID}}` real que vivia en el destino.
