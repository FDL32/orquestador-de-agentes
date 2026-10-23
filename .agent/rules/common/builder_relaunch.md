# Relanzamiento robusto del Builder (capa 2 de la piramide)

> **Procedencia:** piramide pasada 2 + lote R1, HEAD base
> `8e956837`, 2026-10-19. Secciones origen (verbatim abajo):
> - `## Robust Builder Relaunch (WP-2026-084)` -- `AGENTS.md:887-893`
> - Las lineas citadas son de esa HEAD base. Desde WOT-2026-120a (2026-10-23) la cuspide ya no
>   tiene este encabezado: lo funde en `## Referencias de instalacion, review y
>   relanzamiento`, como item por ID WP (directiva + puntero aqui).
>
> Extractores por encabezado: leer este modulo; la cuspide solo conserva la directiva.

**Ownership:** este modulo conserva VERBATIM las secciones origen de `AGENTS.md` listadas en
su cabecera de procedencia. La cuspide conserva encabezado, directiva (prohibiciones,
obligaciones, comando canonico) y puntero. Este modulo es `referencia-bajo-demanda`: se
consulta al trabajar en el mecanismo, no en cada sesion. En divergencia de CONTENIDO manda
este modulo; toda modificacion de uno exige revisar el otro en el mismo commit.

## Robust Builder Relaunch (WP-2026-084)

- **Liveness check**: El supervisor verifica si el Builder está vivo via PID + `tasklist` (Windows) antes de relanzar tras un CHANGES. Fallback: mtime <15 min.
- **Flag `-ResumeBuilder`**: Launcher lo recibe del supervisor en requeue. Skip cleanup agresivo (`Stop-ProjectAgentProcesses`, `Remove-StaleRuntimeArtifacts`, `Assert-StartupAlignment`) para no matar Builder vivo.
- **ADITIVIDAD**: Launcher sin `-ResumeBuilder` (primera apertura) comporta igual que antes. Cero regresión.
- **Diagnóstico**: Supervisor captura stdout/stderr del launcher si falla, loggea a stderr con prefijo `[ticket-supervisor]`.
