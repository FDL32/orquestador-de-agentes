#!/usr/bin/env python3
"""Probe barato de interferencia de I/O (hipotesis: Internxt intercepta operaciones).

POR QUE EXISTE (2026-09-17): seis corridas de `--level all` murieron por la manana y la
septima paso en verde (6631 passed) DESPUES de cerrar Internxt. Pero entre medias
cambiaron VARIAS cosas a la vez (se cerraron programas, Procmon entro y salio), asi que
atribuir el exito a Internxt seria correlacion de n=1 sin control. Este probe existe para
convertir esa sospecha en un par A/B barato: ~30 s por brazo en vez de ~20 min de suite.

Mide las TRES superficies que un driver de filtro de ficheros encareceria:
  1. crear/escribir/borrar en %TEMP%  -> donde pytest pone su basetemp
  2. spawn de subprocesos             -> 659 call-sites medidos en la suite
  3. lectura masiva del arbol         -> lo que hace la coleccion de pytest

USO: correr DOS veces cambiando UNA sola variable (Internxt abierto / cerrado). El probe
NO decide y no bloquea nada: imprime numeros para comparar. La decision es del operador.

Before: python 3.10+, el repo del motor existe. No necesita admin ni dependencias.
During: escribe y borra ficheros SOLO bajo %TEMP%/probe_io_<pid>/, que elimina al salir.
    Lanza N subprocesos triviales. Lee ficheros del repo sin modificarlos.
After: imprime metricas por eje (mediana/min/max) y una linea JSON. Nunca lanza.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

MOTOR = Path(__file__).resolve().parents[2]
N_FILES = 300
N_SPAWNS = 25
N_READ = 400


def _median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else float("nan")


def probe_files() -> dict:
    """Crear/escribir/borrar en %TEMP%: la superficie del basetemp de pytest."""
    base = Path(tempfile.gettempdir()) / f"probe_io_{os.getpid()}"
    base.mkdir(parents=True, exist_ok=True)
    payload = b"x" * 4096
    create: list[float] = []
    write: list[float] = []
    delete: list[float] = []
    try:
        paths = []
        for i in range(N_FILES):
            p = base / f"f{i:04d}.tmp"
            t0 = time.perf_counter()
            handle = open(p, "wb")  # noqa: SIM115 - se mide la apertura por separado
            create.append((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter()
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            write.append((time.perf_counter() - t0) * 1000)
            paths.append(p)
        for p in paths:
            t0 = time.perf_counter()
            p.unlink()
            delete.append((time.perf_counter() - t0) * 1000)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return {
        "create_ms_median": round(_median(create), 3),
        "write_fsync_ms_median": round(_median(write), 3),
        "delete_ms_median": round(_median(delete), 3),
        "n": N_FILES,
    }


def probe_spawn() -> dict:
    """Spawn de subprocesos: 659 call-sites de la suite pasan por aqui."""
    venv = MOTOR / ".venv" / "Scripts" / "python.exe"
    exe = str(venv) if venv.exists() else sys.executable
    ts: list[float] = []
    for _ in range(N_SPAWNS):
        t0 = time.perf_counter()
        subprocess.run([exe, "-c", "pass"], capture_output=True)  # noqa: S603
        ts.append((time.perf_counter() - t0) * 1000)
    ordered = sorted(ts)
    return {
        "spawn_ms_median": round(_median(ts), 1),
        "spawn_ms_min": round(ordered[0], 1),
        "spawn_ms_max": round(ordered[-1], 1),
        "interpreter": exe,
        "n": N_SPAWNS,
    }


def probe_read() -> dict:
    """Lectura masiva del arbol: lo que hace la coleccion de pytest."""
    files: list[Path] = []
    for p in (MOTOR / "tests").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        files.append(p)
        if len(files) >= N_READ:
            break
    ts: list[float] = []
    total = 0
    for p in files:
        t0 = time.perf_counter()
        try:
            data = p.read_bytes()
        except OSError:
            continue
        total += len(data)
        ts.append((time.perf_counter() - t0) * 1000)
    return {
        "read_ms_median": round(_median(ts), 3),
        "read_ms_total": round(sum(ts), 1),
        "mb_leidos": round(total / 1048576, 1),
        "n": len(ts),
    }


def probe_env() -> dict:
    """Contexto: sin esto los numeros no son comparables entre brazos."""
    out: dict = {"ts": datetime.now().isoformat(timespec="seconds")}
    try:
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
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

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        out["ram_free_mb"] = status.ullAvailPhys // (1024 * 1024)
        out["ram_used_pct"] = status.dwMemoryLoad
    except Exception as exc:  # pragma: no cover - sonda Windows-only
        out["ram_error"] = str(exc)
    try:
        raw = subprocess.run(  # noqa: S603
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=25,
        ).stdout
        rows = [r for r in raw.splitlines() if r.strip()]
        low = raw.lower()
        out["process_count"] = len(rows)
        out["internxt_vivo"] = "internxt" in low
        out["procmon_vivo"] = "procmon" in low
        out["python_n"] = low.count('"python.exe"')
    except Exception as exc:  # pragma: no cover - sonda Windows-only
        out["tasklist_error"] = str(exc)
    return out


def main() -> int:
    env = probe_env()
    print("=" * 64)
    print("PROBE DE I/O  --  %s" % env.get("ts"))
    print("=" * 64)
    print("CONTEXTO (debe ser comparable entre brazos):")
    print("  Internxt vivo : %-7s <-- LA VARIABLE" % env.get("internxt_vivo"))
    print("  Procmon vivo  : %-7s (debe ser False en AMBOS brazos)" % env.get("procmon_vivo"))
    print("  RAM libre     : %s MB (%s%% en uso)" % (env.get("ram_free_mb"), env.get("ram_used_pct")))
    print("  Procesos      : %s | python vivos: %s" % (env.get("process_count"), env.get("python_n")))
    print()
    files = probe_files()
    print("1) FICHEROS en %%TEMP%% (n=%d)" % files["n"])
    print("   create        : %8.3f ms (mediana)" % files["create_ms_median"])
    print("   write+fsync   : %8.3f ms (mediana)" % files["write_fsync_ms_median"])
    print("   delete        : %8.3f ms (mediana)" % files["delete_ms_median"])
    spawn = probe_spawn()
    print("2) SPAWN de subprocesos (n=%d)" % spawn["n"])
    print(
        "   spawn         : %8.1f ms (mediana)  min=%.1f max=%.1f"
        % (spawn["spawn_ms_median"], spawn["spawn_ms_min"], spawn["spawn_ms_max"])
    )
    read = probe_read()
    print("3) LECTURA del arbol (n=%d, %.1f MB)" % (read["n"], read["mb_leidos"]))
    print(
        "   read          : %8.3f ms (mediana)  total=%.1f ms"
        % (read["read_ms_median"], read["read_ms_total"])
    )
    print()
    print("JSON:", json.dumps({"env": env, "files": files, "spawn": spawn, "read": read}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
