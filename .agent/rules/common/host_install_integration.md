# Integracion con el host destino: precedencia de skills, perfiles y host setup hook (capa 2 de la piramide)

> **Procedencia:** piramide pasada 2 + lote R1, HEAD base
> `8e956837`, 2026-10-19. Secciones origen (verbatim abajo):
> - `## Host-first skill precedence & Config Profiles (WP-2026-090)` -- `AGENTS.md:834-838`
> - `## Host setup hook (WP-2026-094)` -- `AGENTS.md:839-852`
> - Las lineas citadas son de esa HEAD base. Desde WOT-2026-120a (2026-10-23) la cuspide ya no
>   tiene estos encabezados: los funde en `## Referencias de instalacion, review y
>   relanzamiento`, con un item por ID WP (directiva + puntero aqui).
>
> Extractores por encabezado: leer este modulo; la cuspide solo conserva la directiva.

**Ownership:** este modulo conserva VERBATIM las secciones origen de `AGENTS.md` listadas en
su cabecera de procedencia. La cuspide conserva encabezado, directiva (prohibiciones,
obligaciones, comando canonico) y puntero. Este modulo es `referencia-bajo-demanda`: se
consulta al trabajar en el mecanismo, no en cada sesion. En divergencia de CONTENIDO manda
este modulo; toda modificacion de uno exige revisar el otro en el mismo commit.

## Host-first skill precedence & Config Profiles (WP-2026-090)

- **Host-first precedence**: Cuando el bundle `orquestador_de_agentes` se instala en un proyecto de destino (host), las skills definidas en el host (`<destino>/.agent/skills/`) toman precedencia absoluta sobre las homónimas del bundle (`orquestador_de_agentes/skills/`). El bundle actúa estrictamente como un fallback determinista.
- **Config Profiles**: `agents.json` define `"active_profile"`. El repo local de desarrollo usa `"engine-dev"`. El instalador `install_agent_system.py` cambia automáticamente este valor a `"host-project"` en el destino durante `--install` o `--sync`.

## Host setup hook (WP-2026-094)

El proyecto destino puede declarar un script ejecutable `.agent/host-setup.sh`
(o `.ps1` en Windows) que `scripts/install_agent_system.py` detecta tras la
copia del bundle. Comportamiento:

- Si el hook existe: el instalador muestra las primeras 20 líneas + pide
  confirmación humana (`y/N`) antes de ejecutarlo. `--yes` salta el prompt.
- Si el hook devuelve exit != 0: el install aborta y propaga el código.
- Si el hook no existe: silencio (backward-compat absoluto).

Plantillas: `.agent/host-setup.sh.example` / `.agent/host-setup.ps1.example`.
Origen del patrón: OpenHands `.openhands/setup.sh` (MIT).

## Actualizar el `agents.json` de un destino (WOT-2026-137b)

> Esta seccion NO es verbatim de `AGENTS.md`: es propia de este modulo (WOT-2026-137b,
> DoD 9). El `agents.json` es del destino (desde WOT-2026-140a el `--sync` no lo pisa y
> solo avisa); el motor aporta el comando y la senal, el destino decide y commitea.

**Cuando:** `destination_context.py --bootstrap` imprime `[WARN] agents.json drift: ...`
(schema del destino menor que el del motor, o roles del `role_mapping` del motor sin
declarar), o el `--sync` imprime `[WARN] config/agents.json: PROTEGIDO`. Es una senal, nunca
un gate: no cambia ningun exit code.

**Procedimiento, destino a destino** (cada destino abre SU ficha con SU prefijo; el motor no
abre fichas de destino). `<motor>` = `motor_root` del link; `<destino>` = su raiz. Se usa el
`agents_config.py` DEL MOTOR: ese modulo no viaja al destino (`MANIFEST.workspace`).

1. **Medir**: `python <motor>/scripts/destination_context.py --bootstrap --project-root <destino>`
   y leer el `[WARN] agents.json drift`. Antes de seguir, `git status` del destino: el arbol de
   `.agent/config/` debe estar limpio, para que el diff sea solo el del migrate.
2. **Ensayo**: `python <motor>/.agent/agents_config.py --migrate --dry-run --project-root <destino>`.
   Lista `applied` (migraciones pendientes) y no escribe. Si falla con traceback (BOM, no UTF-8,
   JSON truncado), PARAR: el migrate lee de forma laxa y no es quien debe arreglar ese fichero.
3. **Aplicar**: el mismo comando sin `--dry-run`. Deja un backup por migracion aplicada,
   `agents.json.bak.<ts>` (y `-1`, `-2`... dentro del mismo segundo); el primero es el original.
   Comprobar que son tantos ficheros como migraciones y NO versionarlos.
4. **Roles que el migrate no siembra** (p. ej. `revisor`): declararlos a mano en el
   `agents.json` VERSIONADO del destino (no en `agents.local.json`, que esta ignorado por git),
   como `"role_mapping": {"<rol>": {"backend": "<b>"}}` con `<b>` ya presente en `backends` del
   destino y sin modelo (el modelo es un override opcional). El rol `reviewer` se rechaza
   (rc 1): el nombre canonico es `revisor`.
5. **Validar**: repetir el paso 1 (sin `[WARN] agents.json drift`) y
   `python <motor>/.agent/agents_config.py get_backend_for_role revisor --project-root <destino>`
   (un rol sin declarar resuelve a `default` en silencio).
6. **Commit en el destino**, con su prefijo; el ensayo del paso 2 y los hashes antes/despues
   van en su informe.

La reparacion automatica de `role_mapping.revisor` y el alias `reviewer` -> `revisor` NO
existen (viven en WOT-2026-137a, diferidas): hasta entonces el paso 4 es manual.
