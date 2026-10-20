# Integracion con el host destino: precedencia de skills, perfiles y host setup hook (capa 2 de la piramide)

> **Procedencia:** piramide pasada 2 + lote R1, HEAD base
> `8e956837`, 2026-10-19. Secciones origen (verbatim abajo):
> - `## Host-first skill precedence & Config Profiles (WP-2026-090)` -- `AGENTS.md:834-838`
> - `## Host setup hook (WP-2026-094)` -- `AGENTS.md:839-852`
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
