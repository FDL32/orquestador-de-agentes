# scripts/tools — wrappers anti-trampa de shell (WOT-2026-022p)

Scripts pequeños (stdlib only) que ENVUELVEN los encantamientos de shell que los
agentes fallan repetidamente a mano. **Prefiere el wrapper al encantamiento
manual**: cada uno cierra una clase de auto-engaño con evidencia real.

| Wrapper | Trampa que evita | Uso |
|---------|------------------|-----|
| `run_and_exit.py` | `$?` tras un pipe lee el exit del CONSUMIDOR (`tail`), no del productor: un `cmd` que falla piped a `tail` parece exit 0 (autoengano-por-pipe, llegó a memoria 2026-07-11). | `python scripts/tools/run_and_exit.py [--tail N] -- <cmd> [args...]` → imprime las últimas N líneas + `exit_code:` REAL del comando, y sale con ese código. |
| `winpath.py` | Pasar `/c/Users/...` (MSYS) a pathlib produce `C:\c\Users\...` inexistente (4 falsos negativos en 1 sesión). | `python scripts/tools/winpath.py /c/Users/x` → `C:\Users\x`. Import: `from scripts.tools.winpath import to_windows_path`. |

## Regla operativa

- Cuando necesites el **exit code** de un comando cuya salida también quieras
  ojear: `run_and_exit.py`, NO `cmd | tail` + `$?`.
- Cuando tengas una ruta en forma `/c/...` que va a pathlib o a una tool de
  Windows: normalízala con `winpath.py` (o `to_windows_path`) primero.

Ambos son stdlib only (subprocess, pathlib, re, argparse). Cero dependencias.
