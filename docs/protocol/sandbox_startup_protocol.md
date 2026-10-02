# Protocolo de arranque del sandbox de agentes (AppContainer) — válido para varios IDEs

> Un solo procedimiento de arranque, independiente del IDE, y una tabla de **puntos de enganche** por IDE. Lo que protege es
> **lo que arranca el lanzador** `scripts/sandbox_launcher.ps1`; lo demás queda fuera de la barrera. Cifras y límites medidos
> en el spike del 2026-10-02 (informe `SPIKE_barrera_fs_appcontainer_20261002.md` del destino).

## 1. Qué garantiza y qué no

| Garantiza (medido, con python, node y git) | NO garantiza |
|---|---|
| El proceso lanzado lee y escribe solo bajo la raíz del sandbox (`work\`, `home\`); fuera falla, también por junction. | Nada de lo que **no** pase por el lanzador: un terminal normal, una extensión que lanza su propio agente, el propio IDE. |
| Su entorno no trae secretos (lista blanca de variables estándar; el resto se elimina). | Una lista de hosts: la red es **todo o nada** (`-Net` concede internet completo). |
| El canario comprueba, antes de cada arranque, que dentro se lee y fuera no; si no, **no arranca** (fail-closed). | Que el agente sea inofensivo con lo que sí ve: ve `work\` y la red si se la das. |
| Sin admin, sin instalar nada, deshacible (`down`). | Un agente lanzado a mano como el usuario conserva todo su acceso (AppLocker no activo, WDAC de usuario apagado). |

## 2. Tres niveles de integración (de más a menos fuerte)

| Nivel | Qué significa | Cuándo se puede |
|---|---|---|
| **L1 — el IDE lanza el agente a través del lanzador** | El proceso del agente nace dentro del contenedor. | Cuando el IDE permite configurar el **comando** que arranca el agente. |
| **L2 — terminal por defecto = shell del sandbox** | Los comandos que el agente ejecuta en el terminal del IDE pasan por el contenedor. | Cuando el IDE respeta su perfil de terminal por defecto para el agente. |
| **L3 — sin enganche** | El agente corre fuera de tu máquina o fuera del alcance del lanzador. | Agentes en la nube o embebidos. La defensa pasa a ser de **datos**: solo se le entrega un snapshot y credenciales acotadas. |

## 3. Procedimiento de arranque (igual para todos los IDEs)

1. **Comprobar** (`powershell -NoProfile -ExecutionPolicy Bypass -File <motor>\scripts\sandbox_launcher.ps1 verify`). Código 0 = barrera efectiva
   (levanta el sandbox si hace falta y ejecuta el canario). Código distinto de 0 = **no arrancar ningún agente**.
2. **Preparar el trabajo** dentro de la raíz, **nunca** apuntando a un repo real:
   - lente de solo lectura: `snapshot -Source <repo> -Name <n>` (exporta los ficheros **sin `.git`**: sin historial ni remotos);
   - agente que escribe: `clone -Source <repo> -Name <n>` (el cambio vuelve como parche, no por escritura en el original).
3. **Credenciales**: ninguna por defecto. Si el agente la necesita, una clave **dedicada** y solo por nombre: `-PassEnv NOMBRE_VARIABLE`
   (el lanzador imprime solo los nombres que pasa). Nunca la clave principal.
4. **Red**: sin `-Net` por defecto. Con `-Net` el agente llega a su proveedor y a cualquier otro host.
5. **Lanzar** con `run -Exe <agente> -ExeArgs '<args>' -Cwd <n> [-Net] [-PassEnv ...]` o `shell [-Net]` para una consola dentro. Sin terminal
   (CI, tareas sin consola) añade `-NullStdin`; **con un cliente que habla por stdio (ACP) no lo uses**.
6. **Observar**: los mensajes del lanzador van a **stderr**; el stdout es solo el del agente (imprescindible para ACP).
7. **Recoger resultados**: el contenedor no escribe fuera de `work\`; lo que deba salir lo copias tú desde `work\<n>` o como parche.
8. **Cerrar**: `down` (quita permisos, perfil y unidad); `-Purge` borra además la raíz.

## 4. Reglas duras

- **No montar el repo real.** Nada bajo `C:\Users` es accesible desde el contenedor (medido): el trabajo vive bajo la raíz del sandbox
  (por defecto `C:\agent_sandbox`, mapeada a una letra con `subst`, que git necesita).
- **`snapshot` antes que `clone`** para revisión: `opencode` se **cuelga dentro del contenedor al detectar un repo git** (medido, incluso con
  un repo de un archivo) y funciona sobre la exportación sin `.git`.
- **El canario no se desactiva** (`-NoCanary` existe solo para depurar el lanzador).
- **Un IDE que no pasa por el lanzador no está protegido**, aunque tenga sandbox propio: decláralo en el informe del arranque.

## 5. Puntos de enganche por IDE

Estado de cada afirmación: **V** = verificado en esta máquina; **D** = según la documentación oficial, no probado aquí; **?** = sin confirmar.

| IDE | Enganche | Nivel | Estado y fuente |
|---|---|---|---|
| **VS Code** (instalado) | Tareas por carpeta en `.vscode/tasks.json` que llaman al lanzador (`up`, `status`, `snapshot`, `shell`, `down`). | L1 para lo que lanzas tú | **V** la línea de comandos de las tareas (ejecutada sin interfaz). **?** Su apertura en el panel de VS Code. |
| VS Code | Perfil de terminal `Sandbox (AppContainer)` en el `.code-workspace` o en la configuración de usuario (los perfiles no se pueden definir por carpeta). | L2 | **?** No aplicado ni probado: ver snippet 6.1. |
| **Zed** (instalado) | `agent_servers` en `settings.json` con `type: custom`, `command`, `args`, `env`; Zed hospeda el hilo y el agente lo ejecuta el comando indicado. | L1 | **D** [Zed — External Agents](https://zed.dev/docs/ai/external-agents). **?** Que `opencode`/`claude` hablen ACP a través del lanzador: ver 6.2. |
| **Kiro** (instalado) | En Windows los comandos del agente corren en el **perfil de terminal por defecto**; hay una petición abierta para elegir otro shell solo para el agente. Hooks en `.kiro/hooks/`. | L2 | **D** [Terminal — Kiro](https://kiro.dev/docs/ide/chat/terminal/), [issue #9442](https://github.com/kirodotdev/Kiro/issues/9442). **?** Que un perfil que envuelve el lanzador sea aceptado por su integración de shell. |
| **Cursor** (no instalado aquí) | Perfil de terminal por defecto; el CLI tiene su propio `sandbox.json` (red denegada por defecto). | L2 débil | **D** hay informes de que en Windows el agente **no respeta** el perfil por defecto y usa WSL o el shell del sistema ([foro 1](https://forum.cursor.com/t/agent-runs-in-system-shell-instead-of-configured-default-terminal-profile/151871), [foro 2](https://forum.cursor.com/t/agent-mode-not-using-default-terminal-on-windows/136758)). No fiarse de L2 aquí. |
| **Devin** (no instalado aquí) | La variante principal corre en una **VM en la nube**; la variante local se aísla con bubblewrap, Seatbelt o **WSL 2** (no nativo en Windows). | L3 | **D** [Devin: sandboxes y CLI](https://fast.io/resources/devin-software-engineer/), [Cognition y el terminal](https://runtimewire.com/article/cognition-devin-cloud-terminal-ssh). El lanzador no aplica: se le entrega un snapshot y credenciales acotadas. |

Resumen operativo: **solo Zed y el propio VS Code permiten, según lo comprobado, que el IDE lance el agente por el lanzador (L1)**. Kiro y
Cursor dependen del perfil de terminal (L2) y en Cursor es poco fiable en Windows. Devin queda fuera de la barrera por diseño.

## 6. Snippets (NO aplicados salvo las tareas de VS Code)

### 6.1 VS Code / Kiro / Cursor — perfil de terminal (en el `.code-workspace` o en la configuración de usuario)
```json
"terminal.integrated.profiles.windows": {
  "Sandbox (AppContainer)": {
    "path": "powershell.exe",
    "args": ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             "${workspaceFolder:orquestador_de_agentes_dev}\\scripts\\sandbox_launcher.ps1", "shell", "-Net"],
    "icon": "shield"
  }
}
```
Para que el agente use este terminal habría que fijarlo como `terminal.integrated.defaultProfile.windows`; en Cursor puede ignorarse (ver 5).

### 6.2 Zed — agente externo a través del lanzador (ejemplo SIN PROBAR)
```json
"agent_servers": {
  "opencode-sandbox": {
    "type": "custom",
    "command": "powershell.exe",
    "args": ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "<motor>\\scripts\\sandbox_launcher.ps1",
             "run", "-Exe", "opencode", "-ExeArgs", "acp", "-Cwd", "<snapshot>", "-Net"]
  }
}
```
Sin `-NullStdin` (ACP usa stdin) y con los mensajes del lanzador en stderr. `opencode acp` y la clave del proveedor (`-PassEnv`) quedan por comprobar.

## 7. Prueba de aceptación por IDE (antes de dar un IDE por integrado)

1. `verify` da 0 y, con la barrera rota a propósito, da distinto de 0.
2. Desde el agente lanzado por el IDE: leer un fichero fuera de `work\` **falla**; escribir fuera **falla**.
3. Desde el agente: `set` (o equivalente) **no** muestra variables KEY/TOKEN/SECRET.
4. El informe del arranque declara el **nivel** (L1/L2/L3) y qué parte del IDE queda fuera de la barrera.

## 8. Pendiente y límites declarados

- **`opencode` 1.18.34 dentro del contenedor (medido 2026-10-02, ronda sin credenciales):** el mismo binario, **fuera** del contenedor, responde
  "OK" en 7 s con el nivel gratuito y sin clave, así que el servicio y la versión sirven (la 1.16.2 recibe un HTTP 426 y exige la 1.18.0 o superior).
  **Dentro** se queda parado sin error (`booting location services`). Con la ruta real en vez de la unidad `subst` falla al instante con
  `EPERM: lstat 'C:\'`: **el agente recorre los directorios padre hasta la raíz del disco y el contenedor no puede consultar `C:\`.** Es la
  misma causa que ya impedía arrancar a `node` sin sus banderas y a `git` fuera de una raíz propia; `subst` solo convierte el error en un
  cuelgue. Descartado como causa: la descarga de `ripgrep` (preinstalado y verificado), el loopback (funciona dentro), la vigilancia de ficheros
  (variables de desactivación sin efecto) y el repo git (el snapshot no tiene `.git`). **Sin admin no hay arreglo conocido**; con admin bastaría una
  ACE de solo lectura, *solo esta carpeta*, para el contenedor sobre `C:\` (ver la ficha). Mientras tanto: **`opencode` 1.18.x no es viable dentro del
  contenedor** y las lentes con ficheros siguen sin un candidato probado.
- `claude -p` arranca dentro del contenedor y se queda parado justo tras su inicialización, sin error (causa sin aislar; sin credenciales no se
  puede descartar el almacén de credenciales de Windows). `opencode` sí funciona sobre un snapshot, pero **no se ha probado una ronda con
  credenciales**, que es lo que falta para llamarlo integrado.
- Un CLI de agente necesita su credencial y red a su proveedor, justo lo que el sandbox niega por defecto: la clave dedicada y `-Net` son una
  decisión del operador, y una lista de hosts exige admin (regla de firewall por contenedor o proxy).
- El modo interactivo (`shell`) arranca y muestra el prompt dentro del contenedor, pero su uso real con teclado en un terminal de IDE **no se ha probado**.
- El lanzador solo termina el proceso principal por plazo (`-TimeoutSec`); no mata el árbol de hijos.
- Persistencia: el mapeo `subst` no sobrevive a un reinicio; el lanzador lo recrea.
