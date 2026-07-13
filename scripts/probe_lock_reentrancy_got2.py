#!/usr/bin/env python3
"""Probe DETERMINISTA del falso rojo "got 2" (WOT-2026-023r).

QUE DEMUESTRA
-------------
``tests/test_init_session_scratch.py::TestMaidenVoyage::
test_takeover_competition_exactly_one_wins`` fallaba de forma intermitente con
``AssertionError: Exactly 1 should win, got 2``. NO es un flaky y NO es un bug del
lock: es el ASSERT del test el que es incompatible con la semantica de ownership
``(pid, session_id)`` que definio WOT-2026-023n.

El test lanza DOS HILOS DEL MISMO PROCESO con el MISMO ``sid``. El estado que
dispara la rama idempotente de 023n (lock vivo + mismo pid + mismo sid) NO lo pone
el fixture -- el fixture monta un lock EXPIRADO y de pid AJENO (999999), con el que
esa rama no se alcanza. **LO FABRICA EL HILO A**: su ``_takeover_lock`` borra el
lock ajeno y escribe uno NUEVO con ``os.getpid()`` y el MISMO ``sid``. El hilo B
llega despues, lee ESE lock (vivo, mismo pid, mismo sid) y entra por la rama que
``_acquire_lock`` documenta literalmente ("held by THIS process for THIS session
-> True, idempotent") -> devuelve True -> wins=2.

No son dos propietarios: es UNA REENTRADA LEGITIMA del mismo propietario logico.

POR QUE ERA INTERMITENTE (y por que ``wins == 2`` TAMPOCO seria un assert valido)
---------------------------------------------------------------------------------
El probe serializa las DOS intercalaciones posibles, sin hilos y sin azar:

    ESCENARIO 1  A-luego-B          -> wins=2  (B reentra sobre el lock de A)
    ESCENARIO 2  los dos en takeover -> wins=1  (el perdedor del marker se rinde)

AMBOS resultados son CORRECTOS bajo la semantica de 023n. Por eso, con el MISMO
sid, ``wins`` vale 1 o 2 segun el scheduling: ni ``assert wins == 1`` ni
``assert wins == 2`` son deterministas. El arreglo NO es cambiar el 1 por un 2
(seria el mismo pecado con el signo contrario): es que los dos contendientes usen
sids DISTINTOS, y entonces ``wins == 1`` es estable en AMBAS intercalaciones.

ESTE PROBE SIGUE VERDE DESPUES DEL FIX
--------------------------------------
No reproduce un bug de produccion: PINEA UNA PREMISA. La reentrada idempotente es
comportamiento CORRECTO y 023r no toca produccion. Si algun dia este probe deja de
imprimir wins=2 en el escenario 1, la premisa del ticket ha MUERTO y hay que
reencuadrar antes de tocar el test.

Uso:
    python scripts/probe_lock_reentrancy_got2.py

Sale con 0 si reproduce (escenario 1 -> wins=2, escenario 2 -> wins=1), 1 si no.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import init_session_scratch as iss  # noqa: E402


SID = "s-probe"
FOREIGN_PID = 999999


def _fixture_session_dir(work: Path, tag: str) -> Path:
    """El fixture EXACTO del test: lock EXPIRADO de un pid AJENO."""
    session_dir = work / tag / ".agent" / "runtime" / "session" / SID
    session_dir.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    old_lock = {
        "pid": FOREIGN_PID,
        "session_id": "old",
        "op": "init",
        "created_at": now.isoformat(),
        "expires_at": (now - timedelta(seconds=100)).isoformat(),
    }
    (session_dir / "lock.json").write_text(json.dumps(old_lock), encoding="utf-8")
    return session_dir


def _describe_lock(session_dir: Path) -> str:
    lock_path = session_dir / "lock.json"
    if not lock_path.exists():
        return "<sin lock.json>"
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    return (
        f"pid={data['pid']} session_id={data['session_id']!r} "
        f"live={iss._lock_is_live(data)}"
    )


def scenario_a_then_b(work: Path) -> int:
    """Hilo A completa el takeover y LUEGO entra B. Es el 'got 2'."""
    session_dir = _fixture_session_dir(work, "a_then_b")
    print("ESCENARIO 1 -- A-luego-B (la intercalacion que rompia el test)")
    print(f"  os.getpid()      = {os.getpid()}")
    print(f"  lock inicial     = {_describe_lock(session_dir)}  <- expirado, pid ajeno")

    r_a = iss._acquire_lock(session_dir, SID, "init")
    print(f"  hilo A adquiere  = {r_a}   (takeover: borra el ajeno y escribe el suyo)")
    print(f"  lock TRAS A      = {_describe_lock(session_dir)}  <- lo fabrico A")

    r_b = iss._acquire_lock(session_dir, SID, "init")
    print(f"  hilo B adquiere  = {r_b}   <- lee el lock de A: mismo pid, mismo sid")
    print("                            -> rama 'THIS process / THIS session' (023n)")

    wins = sum(1 for r in (r_a, r_b) if r is True)
    print(f"  wins = {wins}   (el test asertaba wins == 1)\n")
    return wins


def scenario_both_in_takeover(work: Path) -> int:
    """Los dos hilos entran en _takeover_lock; el perdedor del marker se rinde."""
    session_dir = _fixture_session_dir(work, "both_takeover")
    marker = session_dir / iss.TAKEOVER_NAME
    print("ESCENARIO 2 -- los dos en el takeover (la intercalacion que pasaba)")

    # El marker ya existe = el otro contendiente esta DENTRO del takeover.
    fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    r_loser = iss._acquire_lock(session_dir, SID, "init")
    print(f"  perdedor marker  = {r_loser}   (age < TAKEOVER_TTL -> se rinde)")

    marker.unlink()
    r_winner = iss._acquire_lock(session_dir, SID, "init")
    print(f"  ganador marker   = {r_winner}")

    wins = sum(1 for r in (r_loser, r_winner) if r is True)
    print(f"  wins = {wins}   <- MISMO test, MISMO sid, resultado DISTINTO\n")
    return wins


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="probe_got2_", dir=tempfile.gettempdir()))
    try:
        wins_1 = scenario_a_then_b(work)
        wins_2 = scenario_both_in_takeover(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("-" * 68)
    ok = wins_1 == 2 and wins_2 == 1
    if ok:
        print(f"PREMISA VIVA: con el MISMO sid, wins vale {wins_2} o {wins_1} segun la")
        print("intercalacion, y AMBOS son correctos -> el assert del test no puede")
        print("ser determinista. La competicion REAL exige sids DISTINTOS.")
        return 0

    print(f"PREMISA MUERTA: esperaba wins=2 / wins=1, obtuve {wins_1} / {wins_2}.")
    print("El mecanismo de WOT-2026-023r ha cambiado: PARA y reencuadra el ticket.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
