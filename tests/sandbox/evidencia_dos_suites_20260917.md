# EVIDENCIA: dos suites --level all concurrentes sobre el mismo repo

Capturada 2026-09-17 antes de terminarlas. Motor _dev HEAD 5c2eefc.
Metodo: Get-CimInstance Win32_Process + Get-Process. exit_code: 0.

## Arbol de procesos (literal)
```
27592  ppid=27612  cpu=     1,3s start=17:18:34
43032  ppid=27592  cpu=     0,0s start=17:18:47
45232  ppid=43032  cpu= 1.119,7s start=17:18:47
19524  ppid=34316  cpu=     1,1s start=17:19:55
34016  ppid=19524  cpu=     0,0s start=17:20:06
40868  ppid=34016  cpu= 1.116,9s start=17:20:06
```

## Cadena A (lock actual) vs Cadena B (declarada aborted)

| | Cadena A | Cadena B |
|---|---|---|
| wrapper | 19524 (`--level all --force-unlock`) | 27592 (`--level all`) |
| shim | 34016 | 43032 |
| worker | 40868 | 45232 |
| arranco | 17:19:55 | 17:18:34 |
| run_history | `status: started` | **`aborted` 15:18:35** |
| realidad | viva | **VIVA, nunca murio** |

## Lock
```
{
  "pid": 19524,
  "started_at": "2026-09-17T15:19:56+00:00",
  "cwd": "C:\\Users\\fdl\\Proyectos_Python\\orquestador_de_agentes_dev"
}```

## Sandboxes generados
```
session_40868: 4752 factories  80M
session_45232: 4754 factories  81M
tests/sandbox TOTAL: 105696 entradas, 161M
```

## Como se produjo (leido en codigo, no inferido)
1. 17:18:34 arranca B (27592) y toma el lock.
2. 17:19:55 arranca A (19524) con `--force-unlock`: `acquire_lock` (:672-684) borra
   el LOCK_FILE **aunque `is_pid_running(lock_pid)` sea True**.
3. A ejecuta `_reconcile_dead_run()` y marca B como `aborted` -- pero B seguia VIVA.

**La fila `aborted` de las 15:18:35 describe como muerta una corrida que a las
18:5x seguia ejecutandose con 1115 s de CPU.** Es falsa en su CONTENIDO, no solo
en su timestamp (que el forense ya explica como inflado por reconciliacion).
