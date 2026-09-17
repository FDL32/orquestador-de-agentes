#!/usr/bin/env python3
"""Vigia EXTERNO de corridas de suite: registra la muerte con su contexto.

POR QUE EXISTE (2026-09-17, forense de `debug_forense_suites_20260917.md`): seis
corridas de `--level all` murieron y las cuatro hipotesis emitidas se refutaron. Lo que
falto no fue otra hipotesis: fue no poder atribuir la muerte. El historial NO registra
quien lanzo, y `last-run.json` solo tiene la foto del ARRANQUE, asi que una corrida que
muere a mitad deja un hueco de ~20 minutos sin datos.

QUE HACE, y por que es EXTERNO. Muestrea cada N segundos y escribe una linea JSON por
muestra. No modifica `run_pytest_safe.py` -- ese fichero es entregable de WOT-2026-062e
y esta bajo revision; tocarlo mientras su Builder trabaja crearia conflicto. El vigia
observa desde fuera, asi que tambien sirve para corridas lanzadas por OTRO agente, que es
justo el caso que no se pudo atribuir.

QUE REGISTRA por muestra:
  - la CADENA DE PADRES del proceso del lock, hasta el primer no-python, con nombre y
    linea de comando: responde "QUIEN lanzo esto", el campo que el historial no tiene.
  - RAM libre, numero de procesos, y si estan vivos Procmon / Internxt / los IDEs.
  - el estado de `last-run.json` (status, exit_code, passed).
  - un CENSO de procesos python vivos, para ver si el arbol se reduce antes de morir.

QUE PRUEBA, y que no. Acota la muerte a una ventana de N segundos en vez de a 20 minutos,
y deja escrito el contexto del ultimo instante con vida. **No nombra al asesino**: si la
terminacion viene de un proceso ajeno a la cadena de padres, esto no lo ve. Para eso hace
falta auditoria de procesos de Windows (4688/4689), que exige admin.

USO:
    python tests/sandbox/debug_suite_watchdog.py --project-root <repo> [--interval 20]

Termina solo cuando la corrida deja de estar viva, e imprime un VEREDICTO con la ultima
muestra y la transicion observada.

Before: python 3.10+. No necesita admin ni dependencias.
During: lee `pytest.lock` y `last-run.json` del repo indicado; consulta `tasklist` y
    `wmic`. Escribe SOLO en su fichero de salida. Nunca mata ni toca procesos.
After: deja un `.jsonl` con una muestra por linea y devuelve 0. Nunca lanza.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _ram() -> tuple[int, int]:
    """(MB libres, % en uso). (-1, -1) si la sonda falla."""
    try:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.ullAvailPhys // (1024 * 1024), status.dwMemoryLoad
    except Exception:
        return -1, -1


def _cim(pid: int) -> dict:
    """Datos de UN proceso via PowerShell CIM. {} ante cualquier fallo.

    NO usa `wmic`: Microsoft lo retiro de Windows 11 reciente y en esta maquina no
    existe (`FileNotFoundError [WinError 2]`, medido 2026-09-17). La v1 de este vigia
    lo usaba y devolvia [] EN SILENCIO, dejando la cadena de padres vacia -- que es
    justo el dato que el vigia existe para capturar. Una sonda que falla callada es
    peor que una que no existe.
    """
    script = (
        f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' -ErrorAction SilentlyContinue; "
        "if ($p) { [pscustomobject]@{ ProcessId=$p.ProcessId; ParentProcessId=$p.ParentProcessId; "
        "Name=$p.Name; CommandLine=$p.CommandLine } | ConvertTo-Json -Compress }"
    )
    try:
        raw = subprocess.run(  # noqa: S603
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _parent_chain(pid: int, limit: int = 8) -> list[dict]:
    """Cadena de padres hasta el primer no-python. RESPONDE 'quien lanzo esto'."""
    chain: list[dict] = []
    current = pid
    for _ in range(limit):
        row = _cim(current)
        if not row or not row.get("Name"):
            chain.append({"pid": current, "name": "?", "cmd": "(sonda CIM sin datos)"})
            break
        chain.append(
            {
                "pid": current,
                "name": row.get("Name"),
                "cmd": (row.get("CommandLine") or "")[:160],
            }
        )
        if (row.get("Name") or "").lower() != "python.exe":
            break
        try:
            current = int(row.get("ParentProcessId") or 0)
        except (TypeError, ValueError):
            break
        if current <= 0:
            break
    return chain


def _alive(pid: int) -> bool:
    try:
        raw = subprocess.run(  # noqa: S603
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=25,
        ).stdout
        return str(pid) in raw
    except Exception:
        return False


def _process_census() -> dict:
    """Cuantos procesos hay y que actores relevantes viven."""
    try:
        raw = subprocess.run(  # noqa: S603
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=30
        ).stdout
    except Exception:
        return {"error": "tasklist failed"}
    low = raw.lower()
    return {
        "total": len([r for r in raw.splitlines() if r.strip()]),
        "python_n": low.count('"python.exe"'),
        "procmon": "procmon" in low,
        "internxt": "internxt" in low,
        "code": low.count('"code.exe"'),
        "cursor": low.count('"cursor.exe"'),
    }


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    root = Path(args.project_root).resolve()
    base = root / ".agent" / "runtime" / "pytest-safe"
    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parent / f"watchdog_{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    )

    print(f"[watchdog] repo    : {root}")
    print(f"[watchdog] salida  : {out}")
    print(f"[watchdog] muestreo: cada {args.interval:.0f} s")

    lock_path = base / "pytest.lock"
    if not lock_path.exists():
        print("[watchdog] no hay pytest.lock: no hay corrida que vigilar.")
        return 0
    lock = _read_json(lock_path)
    pid = int(lock.get("pid") or 0)
    if not pid or not _alive(pid):
        print(f"[watchdog] el lock apunta a pid={pid}, que NO vive. Nada que vigilar.")
        return 0

    chain = _parent_chain(pid)
    print(f"[watchdog] vigilando pid={pid} (lock de {lock.get('started_at')})")
    print("[watchdog] CADENA DE PADRES -- esto es lo que el historial no registra:")
    for node in chain:
        print(f"[watchdog]   {node['pid']:>7} {node['name']:<14} {node['cmd'][:100]}")

    last: dict = {}
    samples = 0
    with out.open("w", encoding="utf-8") as handle:
        while True:
            free_mb, used_pct = _ram()
            run = _read_json(base / "last-run.json")
            sample = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "lock_pid": pid,
                "lock_alive": _alive(pid),
                "ram_free_mb": free_mb,
                "ram_used_pct": used_pct,
                "census": _process_census(),
                "run_status": run.get("status"),
                "run_exit_code": run.get("exit_code"),
                "run_passed": run.get("passed"),
                "parent_chain": chain if samples == 0 else None,
            }
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
            handle.flush()
            samples += 1
            last = sample

            if not sample["lock_alive"]:
                print("\n" + "=" * 64)
                print("[watchdog] VEREDICTO: el proceso del LOCK ya no vive")
                print("=" * 64)
                print(f"  ultima muestra   : {sample['ts']}")
                print(f"  last-run.status  : {sample['run_status']}")
                print(f"  last-run.exit    : {sample['run_exit_code']}")
                print(f"  RAM libre        : {sample['ram_free_mb']} MB ({sample['ram_used_pct']}%)")
                print(f"  procesos python  : {sample['census'].get('python_n')}")
                print(f"  procesos totales : {sample['census'].get('total')}")
                if sample["run_status"] == "started":
                    print("\n  -> MUERTE SIN CIERRE: el runner no escribio su desenlace.")
                    print("     La ventana de muerte queda acotada a los ultimos "
                          f"{args.interval:.0f} s.")
                else:
                    print("\n  -> CIERRE NORMAL: el runner escribio su desenlace.")
                print(f"\n  muestras: {samples} | fichero: {out}")
                break

            time.sleep(args.interval)

    print(f"[watchdog] fin. ultima RAM libre: {last.get('ram_free_mb')} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
