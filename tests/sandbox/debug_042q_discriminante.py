"""WOT-2026-042q -- discriminante de la RUTA PRODUCTIVA del --session-close.

NO arregla nada. Instrumenta el camino REAL y REGISTRA cual de H-a..H-f ocurre.

Contrato (DoD de la fila viva de backlog.md:177):
  (a) instrumentar la RUTA PRODUCTIVA (no una simulacion) y registrar:
      si se alcanza el refresh post-close, el valor de _get_current_plan_id(),
      la ruta ABSOLUTA de _session_file(), que rama se toma (save/clear), y
      cualquier excepcion que trague el try/except de :6213.
  (b) el probe DISCRIMINA: cada hipotesis tiene un observable que la separa.
  (c) CONTROL POSITIVO: si la corrida sin el defecto tambien sale verde, no mide nada.

Se ejecuta con el interprete del motor y AGENT_PROJECT_ROOT apuntando al destino,
que es como corre en produccion.

Uso:
    python tests/sandbox/debug_042q_discriminante.py [normal|control-positivo]
"""

from __future__ import annotations

import json
import os
import pathlib
import sys


MOTOR = pathlib.Path(__file__).resolve().parents[2]


def _banner(txt: str) -> None:
    print("\n" + "=" * 72)
    print(txt)
    print("=" * 72)


def _recibo() -> None:
    """Recibo de equivalencia de ruta productiva (CEM). Sin esto es exploratorio."""
    _banner("RECIBO DE CONTEXTO (equivalencia de ruta productiva)")
    print(f"sys.executable      = {sys.executable}")
    print(f"cwd                 = {os.getcwd()}")
    print(f"AGENT_PROJECT_ROOT  = {os.environ.get('AGENT_PROJECT_ROOT')}")
    print(f"MOTOR (por __file__)= {MOTOR}")


def main() -> int:
    _recibo()

    sys.path.insert(0, str(MOTOR / ".agent"))
    sys.path.insert(0, str(MOTOR))

    import agent_controller
    import session_tracker

    _banner("ESTADO PREVIO (el fixture vivo)")
    sf = session_tracker._session_file()
    print(f"_session_file()          = {sf}")
    print(f"  existe                 = {sf.exists()}")
    if sf.exists():
        print(f"  mtime_ns               = {sf.stat().st_mtime_ns}")
        print(f"  contenido              = {sf.read_text(encoding='utf-8').strip()}")
    print(f"_get_current_plan_id()   = {session_tracker._get_current_plan_id()!r}")
    print(f"SESSION_TRACKER_AVAILABLE= {agent_controller.SESSION_TRACKER_AVAILABLE}")

    state = agent_controller.read_file(agent_controller.STATE_FILE)
    terminal = agent_controller._state_status_is_terminal(state or "")
    print(f"STATE_FILE               = {agent_controller.STATE_FILE}")
    print(f"_state_status_is_terminal= {terminal}")

    # ---- INSTRUMENTACION: las cinco observables del DoD (a) -------------------
    trace: dict[str, object] = {
        "refresh_reached": False,
        "plan_id_seen": None,
        "session_file_abs": str(sf),
        "branch": None,
        "exception": None,
        "subprocess_launched": False,
    }

    real_save = agent_controller.save_session
    real_clear = agent_controller.clear_session

    def traced_refresh() -> None:
        trace["refresh_reached"] = True
        # Reproduce la MISMA logica de :6205-6214, observando cada paso.
        if not agent_controller.SESSION_TRACKER_AVAILABLE:
            trace["branch"] = "noop-tracker-unavailable"
            return
        try:
            from session_tracker import _get_current_plan_id

            pid = _get_current_plan_id()
            trace["plan_id_seen"] = pid
            if pid != "N/A":
                trace["branch"] = "save_session"
                real_save()
            else:
                trace["branch"] = "clear_session"
                real_clear()
        # Se CAPTURA y se REGISTRA a proposito: observar lo que el
        # try/except de :6213 se traga en silencio ES el DoD (a).
        except Exception as exc:
            trace["exception"] = f"{type(exc).__name__}: {exc}"

    real_run = agent_controller.subprocess.run

    def traced_run(*a, **kw):
        trace["subprocess_launched"] = True
        return real_run(*a, **kw)

    agent_controller._refresh_session_tracker_after_close = traced_refresh
    agent_controller.subprocess.run = traced_run

    modo = sys.argv[1] if len(sys.argv) > 1 else "normal"
    force = modo == "control-positivo"

    _banner(f"EJECUTANDO _handle_session_close(force_mode={force}, dry_run=True)")
    print("dry_run=True: el closeout real NO debe mutar el destino.")
    print("La guarda de :6305 se evalua ANTES del dry_run: eso es lo que discrimina.")

    rc = agent_controller._handle_session_close(
        dry_run=True,
        skip_slow=True,
        ticket=None,
        tickets=None,
        force_mode=force,
        json_output=False,
    )

    _banner("TRAZA")
    print(f"return_code              = {rc}")
    for k, v in trace.items():
        print(f"{k:25}= {v!r}")

    _banner("VEREDICTO")
    _veredicto(trace)

    print(json.dumps(trace, indent=2, default=str))
    return 0


def _veredicto(trace: dict[str, object]) -> None:
    """Traduce las observables a la hipotesis H-* que separan.

    Cada rama depende de un observable DISTINTO, que es lo que hace que el
    probe discrimine en vez de confirmar (DoD (b)).
    """
    if not trace["subprocess_launched"] and not trace["refresh_reached"]:
        print("H-a: la guarda de :6305 (STATE.md terminal, sin --force) RETORNO ANTES.")
        print("     El refresh NO se alcanza. exit 0 == 'no hice nada'.")
    elif trace["subprocess_launched"] and not trace["refresh_reached"]:
        print(
            "H-b: se paso la guarda y se lanzo el closeout, pero el refresh NO corrio"
        )
        print("     (dry_run salta :6368-6380). Consistente con H-b.")
    elif trace["refresh_reached"]:
        print(f"El refresh SI se alcanzo. rama={trace['branch']!r}")
        if trace["exception"]:
            print(f"H-e: excepcion tragada por el try/except: {trace['exception']}")
        elif trace["branch"] == "save_session":
            print("H-f/A3: save_session() corrio y copia el active_plan resoluble.")
        elif trace["branch"] == "clear_session":
            print("clear_session() alcanzable: el id NO era resoluble.")


if __name__ == "__main__":
    raise SystemExit(main())
