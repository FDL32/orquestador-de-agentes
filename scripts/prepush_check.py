#!/usr/bin/env python3
"""Pre-push Check - canonical delivery preflight wrapper.

Before (Pre-condiciones):
    - El repositorio Git debe existir en el directorio actual o especificado.
    - El usuario invoca este script antes de `git push` como verificacion unica.
    - Los archivos de configuracion (.pre-commit-config.yaml) deben existir.

During (Proceso y Recursos):
    - Ejecuta en secuencia fija:
      (1) delivery_hygiene_check.run_delivery_hygiene_check()
      (2) uv run ruff check .
      (3) uv run ruff format --check .
      (4) agent_controller --validate --json --force
      (5) git status --short
      (6) checks adicionales bloqueantes solo en closeout_mode (backlog contract,
          reconcile, handoff SHA, destination PII, closeout reconciliation,
          motor<->destino integration)
      (7) check_portable_memory_archive_schema.py --motor-root <root>
          (WOT-2026-035b; siempre, no solo en closeout_mode)
    - Ejecuta skills/validate_all.py de forma informacional (no bloqueante).
    - Cada check imprime estado OK/FAIL con diagnostico legible.
    - No modifica archivos; solo verifica y reporta.

After (Post-condiciones y Errores):
    - Retorna exit code 0 si todos los checks bloqueantes pasan.
    - Retorna exit code 1 si algun check bloqueante falla.
    - git status --short no debe mostrar cambios tras la ejecucion.
    - skills/validate_all.py se ejecuta pero no afecta el exit code.
    - Excepciones: subprocess.CalledProcessError si algun comando falla,
      FileNotFoundError si falta algun archivo requerido.

BY-DESIGN (WOT-2026-049c): esto es un gate de CIERRE DE SESION, no de push.
    El nombre ENGANA. Pese a llamarse `prepush_check`, este script NO esta
    cableado al hook `pre-push` y **eso es deliberado**: el `git push` directo
    que lo esquiva existe A PROPOSITO. La decision se tomo con estas medidas
    (2026-08-06), no por olvido:

    - **Coste:** 25 checks en `--closeout-mode`. Los SEGUNDOS son dato
      EMPIRICO, no propiedad deducible del codigo: medidos 2026-08-06 en esta
      maquina dieron 25.0 s (closeout, 3 de los 25 en FAIL informacional) y
      12.0 s (base). Trata la magnitud como orientativa y re-mide si la
      necesitas; lo que NO depende de la maquina es el reparto de checks de
      abajo, que sale del propio codigo. Un `pre-push` cobraria ese coste en
      CADA push, no solo al cerrar.
    - **Alcance equivocado:** la MAYORIA de esos 25 checks son
      closeout-especificos (backlog contract, handoff committed, closeout
      reconciliation, flight plan collision, DEC receipt...). Son preguntas
      que NO tienen sentido ante un `git push` cualquiera: interrogan el
      cierre de un ticket, no la sanidad de unos commits. El reparto se lee
      EN ESTE FICHERO y se re-deriva SIN ejecutar nada: cuenta los
      `results.append` de `run_checks`. Dentro del bloque `if closeout_mode:`
      hay 18; fuera hay 7 (los 5 base mas portable-memory y validate_all).
      18 + 7 = 25, y coincide con lo que la corrida reporta. Es decir, 18 de
      25 -- la mayoria -- solo existen al cerrar. Cablear esto a `pre-push`
      pagaria esas 18 preguntas de cierre en cada push.
    - **Solapamiento:** `ruff-check` ya corre entre los 9 hooks de la etapa
      `pre-push`. Cablear este script lo duplicaria. Re-verificable parseando
      el YAML (no por grep): un hook entra en `pre-push` si `stages` lo
      incluye o si es `None` (hereda todas las etapas) -- 2026-08-06 daba 9,
      con `prepush_check` AUSENTE de `.pre-commit-config.yaml`.
    - **Blast radius:** los hooks son COMPARTIDOS por worktree. Es un hecho
      de la topologia del checkout, no del codigo, asi que va con su comando
      de re-verificacion en vez de pedir fe:
          test -f .git && cat .git          # es un FICHERO, no un directorio
          git rev-parse --git-common-dir    # resuelve FUERA de este arbol
          ls "$(git rev-parse --git-common-dir)/hooks/"
      Medido 2026-08-06: `.git` es un fichero (`gitdir: .../
      orquestador_de_agentes/.git/worktrees/orquestador_de_agentes_dev`), el
      common-dir es `orquestador_de_agentes/.git`, y alli viven `pre-commit`
      y `pre-push`. Cablearlo afectaria a DOS arboles, no solo al activo.
      (Si algun dia este repo deja de ser un worktree, los tres comandos lo
      dicen solos y esta razon decae -- por eso van aqui.)

    Si estas aqui preguntandote "por que esto no bloquea el push": no es un
    hueco que tapar. Cablearlo a `pre-push` es un cambio de politica que
    revierte una decision medida, no un fix.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple


try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 usa el backport
    import tomli as tomllib  # type: ignore[no-redef]


# Bootstrap: motor root must be on sys.path so `runtime.*` imports resolve
# even when this script runs with cwd inside a destination workspace.
_MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))


# Global noqa for S603 - all subprocess calls use hardcoded command lists
# ruff: noqa: S603


class CheckResult(NamedTuple):
    """Resultado de un check individual.

    `skipped` distingue "paso porque se ejecuto y valido" de "paso porque no
    habia nada que validar". Los dos llevan `passed=True` y el informe de
    cierre los mostraba identicos (`[OK] <nombre>`), asi que un gate saltado
    era indistinguible de uno cumplido -- incluido en gates BLOQUEANTES.

    Es un campo y no una convencion de texto a proposito: detectarlo con
    `output.startswith("SKIP")` dejaba fuera los saltos redactados de otra
    forma ("No backlog.md at ... (skipped)") y dependia de mayusculas y del
    idioma del mensaje (bucle L700, lentes Codex y GLM-5.2, 2026-08-02).
    """

    name: str
    passed: bool
    output: str
    is_blocking: bool = True
    skipped: bool = False


def _configure_stdio() -> None:
    """Configura stdout/stderr para no fallar por encoding en Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")


def run_subprocess_check(
    cmd: list[str],
    name: str,
    project_root: Path,
    capture_output: bool = True,
) -> CheckResult:
    """Ejecuta un comando de verificacion y retorna su resultado.

    Args:
        cmd: Lista de argumentos del comando a ejecutar.
        name: Nombre descriptivo del check para el reporte.
        project_root: Raiz del proyecto donde ejecutar el comando.
        capture_output: Si True, captura stdout/stderr para diagnostico.

    Returns:
        CheckResult con nombre, estado, salida y si es bloqueante.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=capture_output,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        passed = result.returncode == 0
        output = (result.stdout or "") + (result.stderr or "") if capture_output else ""
    except FileNotFoundError as e:
        passed = False
        output = f"Comando no encontrado: {e}"
    except Exception as e:
        passed = False
        output = f"Error ejecutando comando: {e}"

    return CheckResult(name=name, passed=passed, output=output, is_blocking=True)


def run_delivery_hygiene_check(
    project_root: Path,
    expected_artifacts: list[str] | None = None,
) -> CheckResult:
    """Ejecuta el check de higiene de entrega.

    WOT-2026-014a: the optional expected_artifacts param is forwarded to
    delivery_hygiene_check.run_delivery_hygiene_check so the closeout pre-push
    gate can forgive known runtime artifacts. Default None preserves current
    behavior (no forgiveness) for all non-closeout callers.

    Args:
        project_root: Raiz del proyecto donde ejecutar el check.
        expected_artifacts: Optional allowlist forwarded to check_git_tree_clean.
            Default None preserves current behavior (any dirty file fails).

    Returns:
        CheckResult con el estado de la higiene de entrega.
    """
    try:
        import io
        from contextlib import redirect_stdout

        # Destination-local scripts must not shadow the canonical motor gate.
        from scripts.delivery_hygiene_check import run_delivery_hygiene_check

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = run_delivery_hygiene_check(
                project_root=project_root,
                expected_artifacts=expected_artifacts,
            )

        output = f.getvalue()
        passed = exit_code == 0

        return CheckResult(
            name="Delivery Hygiene Check",
            passed=passed,
            output=output,
            is_blocking=True,
        )
    except ImportError as e:
        return CheckResult(
            name="Delivery Hygiene Check",
            passed=False,
            output=f"Error importando delivery_hygiene_check: {e}",
            is_blocking=True,
        )
    except Exception as e:
        return CheckResult(
            name="Delivery Hygiene Check",
            passed=False,
            output=f"Error ejecutando delivery_hygiene_check: {e}",
            is_blocking=True,
        )


def _ruff_exclude_args() -> list[str]:
    """Return --extend-exclude arguments for directories outside operational scope.

    _backups/ and uv-cache/ are outside the operational scope of the motor
    and should not be linted or formatted by ruff.
    """
    return [
        "--extend-exclude",
        "_backups/*,uv-cache/*,.agent/runtime/uv-cache/*",
    ]


def run_ruff_check(project_root: Path) -> CheckResult:
    """Ejecuta ruff check en el proyecto.

    Args:
        project_root: Raiz del proyecto donde ejecutar ruff.

    Returns:
        CheckResult con el estado del check de ruff.
    """
    return run_subprocess_check(
        cmd=["uv", "run", "ruff", "check", ".", *_ruff_exclude_args()],
        name="Ruff Check",
        project_root=project_root,
    )


def _format_check_optout(project_root: Path) -> str | None:
    """Devuelve el fichero donde el proyecto DECLINA `ruff format`, o None.

    Un destino puede decidir por diseno no adoptar el formateador. Para que
    el motor lo reconozca sin adivinar, la declaracion es EXPLICITA:

        [tool.motor]
        format-check = false

    Sitio soportado: UNICAMENTE `pyproject.toml`.

    Por que NO se lee del fichero de config de ruff, aunque fuese el sitio
    natural de la decision: ese fichero es config PLANA con esquema CERRADO
    -- ruff valida el fichero entero y `[tool.motor]` (convenio de pyproject)
    le da `unknown field`, igual que una clave suelta en la raiz. Ruff aborta
    y `ruff check` sube de rc=0 a rc=2. Medido 2026-08-02 sobre ruff real.

    La trampa era doble, y por eso ese offering se retiro: declararlo ahi
    romperia el gate de lint que el destino SI adopta y ademas NO concederia
    el opt-out (el TOML deja de parsear, se cae al fail-closed de abajo y se
    devuelve None). Se rompe el lint y se sigue bloqueado. Un destino sin
    `pyproject.toml` debe crearlo solo con esta declaracion.

    Por que explicita y no inferida de `[format]`: la presencia de una
    seccion `[format]` significa lo CONTRARIO con la misma frecuencia -- un
    proyecto que deja el formateador preconfigurado para activarlo mas
    adelante (`quote-style = "preserve"` "por si alguien lo activa algun
    dia"). Inferir el opt-out de ahi apagaria el gate en destinos que nunca
    lo pidieron, que es justo el fallo que este cambio evita.

    Fail-closed: si el TOML no parsea, se devuelve None y el gate muerde. Un
    fichero de config roto no puede ser un permiso.
    """
    for name in ("pyproject.toml",):
        candidate = project_root / name
        if not candidate.is_file():
            continue
        try:
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            continue
        section = data.get("tool", {})
        if not isinstance(section, dict):
            continue
        motor = section.get("motor", {})
        if isinstance(motor, dict) and motor.get("format-check") is False:
            return name
    return None


def run_ruff_format_check(project_root: Path) -> CheckResult:
    """Ejecuta ruff format --check en el proyecto, salvo opt-out declarado.

    Before:
        `project_root` es la raiz del proyecto a verificar. Puede declarar
        `[tool.motor] format-check = false` para declinar el formateador.

    During:
        Si existe la declaracion, NO se invoca ruff: se devuelve un SKIP que
        CITA el fichero que lo autoriza. Si no, se ejecuta
        `ruff format --check .` como siempre.

    After:
        Devuelve un CheckResult siempre bloqueante. Un SKIP sale con
        `passed=True` y procedencia en `output`; un skip sin procedencia
        seria indistinguible de un gate roto.

    Contexto (LEA-2026-002k): un destino con `ruff format` declinado por
    decision anclada en su propia suite quedaba con el cierre bloqueado por
    un rojo CORRECTO que el motor no sabia interpretar.
    """
    optout = _format_check_optout(project_root)
    if optout is not None:
        return CheckResult(
            name="Ruff Format Check",
            passed=True,
            output=(
                f"SKIP: el proyecto declina `ruff format` en {optout} "
                "([tool.motor] format-check = false). El gate NO se ha "
                "ejecutado; la decision es del destino y su fichero la "
                "justifica."
            ),
            is_blocking=True,
            skipped=True,
        )
    return run_subprocess_check(
        cmd=["uv", "run", "ruff", "format", "--check", "."],
        name="Ruff Format Check",
        project_root=project_root,
    )


def run_agent_controller_validate(project_root: Path) -> CheckResult:
    """Ejecuta agent_controller --validate --json --force.

    Resuelve el controller via motor_link (topologia repo_motor + repo_destino).
    Si no hay motor link,
    usa .agent/agent_controller.py local como fallback.

    Args:
        project_root: Raiz del proyecto donde ejecutar el controller.

    Returns:
        CheckResult con el estado de la validacion del controller.
    """
    controller_path = None
    try:
        from runtime.motor_link import resolve_motor_controller

        resolved = resolve_motor_controller(project_root)
        if resolved:
            controller_path = str(resolved)
    except ImportError:
        pass

    if controller_path is None:
        controller_path = ".agent/agent_controller.py"

    return run_subprocess_check(
        cmd=[
            sys.executable,
            controller_path,
            "--validate",
            "--json",
            "--force",
            "--project-root",
            str(project_root),
        ],
        name="Agent Controller Validate",
        project_root=project_root,
    )


def run_git_status_check(project_root: Path) -> CheckResult:
    """Ejecuta git status --short y verifica que el arbol este limpio.

    WT-2026-215: ejecuta git sobre motor_root (repositorio del motor), no
    sobre project_root (workspace destino). Si motor_root no es resoluble,
    reporta un WARN no bloqueante en lugar de FAIL, para soportar la
    arquitectura workspace activo + motor portable.

    Args:
        project_root: Raiz del proyecto (usado para resolver motor_root).

    Returns:
        CheckResult con passed=True si no hay cambios en el arbol.
    """
    try:
        from runtime.motor_link import resolve_motor_root

        motor_root = resolve_motor_root(project_root)
        if motor_root is None:
            return CheckResult(
                name="Git Status Check",
                passed=True,
                output="motor_root no resoluble (motor_destination_link.json ausente); "
                "check de git saltado (no bloqueante)",
                is_blocking=False,
            )
        result = subprocess.run(
            ["git", "status", "--short"],  # noqa: S607
            cwd=motor_root,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        # If git command itself fails, report as non-blocking WARN for
        # workspaces that are not git repos under external-motor topology.
        if result.returncode != 0:
            return CheckResult(
                name="Git Status Check",
                passed=True,
                output=f"Workspace no-repo (git exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}",
                is_blocking=False,
            )

        output = result.stdout.strip()
        passed = not output
        output = f"Arbol sucio detectado:\n{output}" if output else "Arbol Git limpio"

        return CheckResult(
            name="Git Status Check",
            passed=passed,
            output=output,
            is_blocking=True,
        )
    except FileNotFoundError:
        return CheckResult(
            name="Git Status Check",
            passed=True,
            output="Comando 'git' no encontrado en PATH (workspace no-repo tolerado)",
            is_blocking=False,
        )


def run_validate_all(project_root: Path) -> CheckResult:
    """Ejecuta skills/validate_all.py de forma informacional.

    Args:
        project_root: Raiz del proyecto donde ejecutar la validacion.

    Returns:
        CheckResult con el estado (siempre no-bloqueante).
    """
    validate_all_path = _MOTOR_ROOT / "skills" / "validate_all.py"
    try:
        from runtime.motor_link import resolve_motor_root

        resolved_motor_root = resolve_motor_root(project_root)
        if resolved_motor_root is not None:
            candidate = resolved_motor_root / "skills" / "validate_all.py"
            if candidate.exists():
                validate_all_path = candidate
    except ImportError:
        pass

    result = run_subprocess_check(
        cmd=[sys.executable, str(validate_all_path)],
        name="Validate All (informacional)",
        project_root=project_root,
    )
    # Este check es informacional, no bloquea el exit code
    return CheckResult(
        name=result.name,
        passed=result.passed,
        output=result.output,
        is_blocking=False,
    )


def run_backlog_contract_check(project_root: Path) -> CheckResult:
    """Gate bloqueante de cierre: la cola viva del backlog no tiene terminales.

    WOT-2026-015g: el contrato de cola viva (backlog.md) prohibe estados
    terminales (completed/done/closed/absorbed) en la tabla Vista rapida; deben
    archivarse a _archive/backlog_done.md. `validate_backlog` (en
    check_backlog_contract.py) YA detecta esto, pero hasta ahora ningun gate de
    --session-close lo invocaba: el archivado dependia de un paso manual que se
    omitio en 4 sesiones del 27-jun, dejando 10 completed en cola viva y el
    contract en rojo solo visible al ejecutarlo a mano.

    Este gate cierra ese hueco: se ejecuta SOLO en closeout-mode (la cola viva
    solo se valida al cerrar sesion, no en cada push). Si hay violaciones, el
    cierre se BLOQUEA (is_blocking=True) hasta archivar los terminales.

    Before: project_root apunta al repo_destino con .agent/collaboration/backlog.md.
    During: importa validate_backlog y lo aplica al backlog del destino.
    After: CheckResult passed=True si no hay violaciones; False (bloqueante) si las hay.
    """
    name = "Backlog Contract Check (closeout)"
    backlog = project_root / ".agent" / "collaboration" / "backlog.md"
    if not backlog.exists():
        # Sin backlog no hay cola viva que validar; no bloquea el cierre.
        return CheckResult(
            name=name,
            passed=True,
            output=f"No backlog.md at {backlog} (skipped)",
            is_blocking=True,
            skipped=True,
        )
    try:
        from scripts.check_backlog_contract import (
            validate_archive_landing_evidence,
            validate_archive_prose_preservation,
            validate_archive_row_arity,
            validate_archive_states,
            validate_backlog,
            validate_live_archive_integrity,
        )
    except ImportError:
        from check_backlog_contract import (  # type: ignore[no-redef]
            validate_archive_landing_evidence,
            validate_archive_prose_preservation,
            validate_archive_row_arity,
            validate_archive_states,
            validate_backlog,
            validate_live_archive_integrity,
        )
    # WOT-2026-027i / WOT-2026-026z: the live<->archive duplicate check and the
    # archive arity check both need the destino root (they read the archive), so
    # they are wired here alongside validate_backlog rather than inside it.
    # WOT-2026-026t: `validate_archive_states` closes the MIRROR of the defect in
    # this function's own docstring. That text describes how terminal rows piled
    # up in the LIVE queue because no --session-close gate invoked the check; the
    # inverse leak -- a row archived while still `pending`, i.e. pending work
    # filed as history -- was measured at 18 rows on 2026-08-04 and was invisible
    # in BOTH surfaces. The check shipped wired only into the standalone CLI, so
    # the closeout path (the automated one, where it matters) did not run it: an
    # adversarial pass caught that omission here. Same lesson, third time:
    # a guard nobody invokes is a norm, not a barrier.
    # WOT-2026-054b: FOURTH time, same lesson, caught by a governance loop's
    # filesystem lens. `validate_archive_landing_evidence` shipped in the
    # standalone CLI only and was never wired here -- so the landing-evidence
    # contract was a norm, not a barrier, exactly like the docstring above says
    # was already learned three times. Wiring it required freezing the 86
    # censused legacy rows first (_LANDING_EVIDENCE_LEGACY_BASELINE): this check
    # is is_blocking=True, so wiring it without the baseline would have turned
    # every closeout red.
    violations = (
        validate_backlog(backlog)
        + validate_live_archive_integrity(project_root)
        + validate_archive_row_arity(project_root)
        + validate_archive_states(project_root)
        + validate_archive_landing_evidence(project_root)
        + validate_archive_prose_preservation(project_root)
    )
    if violations:
        detail = "\n".join(f"  - {v}" for v in violations)
        output = (
            f"{len(violations)} violation(s) in {backlog}:\n{detail}\n"
            "Archive terminal tickets to _archive/backlog_done.md before closing "
            "(see WOT-2026-015i)."
        )
        return CheckResult(name=name, passed=False, output=output, is_blocking=True)
    return CheckResult(
        name=name,
        passed=True,
        output="live queue contract holds",
        is_blocking=True,
    )


def run_ghost_ticket_ids_check(project_root: Path) -> CheckResult:
    """WOT-2026-053i: un id CITADO en un commit publicado sin fila en el backlog.

    Cierra el hueco INVERSO al de `run_backlog_contract_check`. Aquel valida las
    FILAS que existen; este valida los ids que se CITARON en git y para los que
    nunca se escribio fila. Ninguna de las dos superficies lo ve: la cola no lo
    lista, el archive no lo tiene, y el contrato sale verde igual porque audita
    filas, no citas.

    MEDIDO 2026-08-09 (la fuga que lo origina): `WOT-2026-053f` se cito en un
    commit publicado con CI verde y no tenia fila. Esa MISMA fuga se habia
    corregido HORAS ANTES para `053e`, se documento su causa, y se repitio TRES
    commits despues con el ticket mas importante de la tanda. El censo posterior
    encontro 9 fantasmas historicos, no 1: no era descuido puntual sino un patron
    que ningun mecanismo miraba. Tercera vez de la misma leccion: lo que nadie
    invoca es una norma, no una barrera.

    NO BLOQUEANTE por decision declarada (`is_blocking=False`): la deuda historica
    esta anclada en `GHOST_BASELINE` y el guard solo avisa de fugas NUEVAS. Un
    fantasma es un fallo de REGISTRO, no de codigo -- se corrige anadiendo una
    fila, y frenar un cierre verde por eso convertiria una senal barata en un
    bloqueo caro. Si la fuga se repite pese al aviso, subirlo a bloqueante es
    trabajo de otro ticket, con su propia evidencia.

    Before: `project_root` es el repo_destino; el cwd es el repo git del motor.
    During: delega en `check_ghost_ticket_ids` (lee las dos superficies + git log).
    After: CheckResult passed=False (no bloqueante) nombrando cada fantasma.
    """
    name = "Ghost Ticket IDs (closeout)"
    try:
        from scripts.check_ghost_ticket_ids import (
            GHOST_BASELINE,
            collect_cited_ids,
            collect_row_ids,
        )
    except ImportError:
        from check_ghost_ticket_ids import (  # type: ignore[no-redef]
            GHOST_BASELINE,
            collect_cited_ids,
            collect_row_ids,
        )
    collab = project_root / ".agent" / "collaboration"
    if not collab.is_dir():
        return CheckResult(
            name=name,
            passed=True,
            output=f"No {collab} (skipped)",
            is_blocking=False,
            skipped=True,
        )
    cited = collect_cited_ids(Path.cwd(), 400)
    if cited is None:
        # SKIP explicito: un guard que no puede MEDIR no se inventa un verde.
        return CheckResult(
            name=name,
            passed=True,
            output="git unavailable; cannot measure (skipped)",
            is_blocking=False,
            skipped=True,
        )
    rows = collect_row_ids(collab)
    ghosts = sorted(t for t in cited if t not in rows and t not in GHOST_BASELINE)
    if ghosts:
        detail = "\n".join(f"  - {t} (commit {cited[t]})" for t in ghosts)
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"{len(ghosts)} id(s) citados en git sin fila en ninguna "
                f"superficie:\n{detail}\nAnade su fila (terminal -> archive) "
                "antes de cerrar (WOT-2026-053i)."
            ),
            is_blocking=False,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="ningun id publicado se quedo sin fila",
        is_blocking=False,
    )


def run_contract_formation_check(project_root: Path) -> CheckResult:
    """WOT-2026-023m(c): gate bloqueante de cierre sobre el CF triple del motor.

    ``validate_contract_formation`` ya validaba la ESTRUCTURA de charter +
    plan_graph + ticket_contracts, pero era un guard que NADIE invocaba (declarado
    en ``known_unwired``, owner 023m): un plan_graph mal formado no rompia ningun
    gate = verde de laboratorio. Este gate lo ENCHUFA (no es logica nueva) sobre
    los tres ficheros CANONICOS del motor (``repo_charter.md`` + ``plan_graph.md``
    en raiz + ``.agent/planning/ticket_contracts.md``). Se ejecuta SOLO en
    closeout-mode. El import es ESTATICO para que ``check_guard_wiring`` lo alcance
    (precedente: ``validate_observations``, 035b).

    Nota de ambito: valida el CF del MOTOR (donde viven los ficheros canonicos,
    sha 3fe1363), NO el plan_graph del workspace (esa es superficie de 025v).

    WOT-2026-024h: ``ticket_contracts.md`` ya NO se versiona en el motor
    (DEC-024H-001), asi que el "triple" pasa a ser un CONJUNTO VARIABLE: se valida
    lo que EXISTE. Exigir los tres habria convertido la retirada del seed en un
    SKIP SILENCIOSO que deja charter y plan_graph sin validar -- es decir, 024h
    habria apagado de rebote la barrera que 023m(c) acababa de encender. En
    dogfooding el motor puede seguir teniendo un ticket_contracts.md LOCAL
    (gitignored); si esta, tambien se valida.

    Before: motor_root resoluble. Ningun fichero CF es obligatorio.
    During: importa validate_contract_formation.main y lo corre sobre los ficheros
    CF del motor que existan (charter, plan_graph y -- si esta -- tickets).
    After: CheckResult passed=True si 0 errores; False (bloqueante) si el
    validador reporta errores de estructura. Si NO existe ninguno -> skip no
    bloqueante (un motor sin CF materializado no debe bloquear el push).
    """
    name = "Contract Formation Check (closeout)"
    charter = _MOTOR_ROOT / "repo_charter.md"
    plan_graph = _MOTOR_ROOT / "plan_graph.md"
    tickets = _MOTOR_ROOT / ".agent" / "planning" / "ticket_contracts.md"
    present: list[str] = []
    if charter.exists():
        present += ["--charter", str(charter)]
    if plan_graph.exists():
        present += ["--plan", str(plan_graph)]
    if tickets.exists():
        present += ["--tickets", str(tickets)]
    if not present:
        return CheckResult(
            name=name,
            passed=True,
            output="motor CF triple not materialized (skipped)",
            is_blocking=True,
            skipped=True,
        )
    try:
        from scripts.validate_contract_formation import main as validate_cf_main
    except ImportError:
        from validate_contract_formation import (
            main as validate_cf_main,  # type: ignore[no-redef]
        )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = validate_cf_main(present)
    if rc != 0:
        return CheckResult(
            name=name,
            passed=False,
            output=buf.getvalue().strip()
            or "validate_contract_formation reported errors",
            is_blocking=True,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="motor CF triple valid (0 structure errors)",
        is_blocking=True,
    )


def run_workspace_contract_formation_check(project_root: Path) -> CheckResult:
    """WOT-2026-026l parte A: extiende el alcance del gate CF al repo_destino.

    ``run_contract_formation_check`` solo validaba el triple del MOTOR; el
    ``ticket_contracts.md`` del WORKSPACE (repo_destino) -- donde se acumularon
    72 contratos con 20 errores CF vivos -- NUNCA se miraba. Es el mismo defecto
    de alcance que ``check_encoding_guard`` tuvo cubriendo solo ``.py``
    ("barrera del alcance, no solo del mecanismo"). Este check hermano cubre la
    superficie del destino.

    FASE TRANSITORIA (WARN, no bloqueante): la deuda historica de esos 20 errores
    la limpia la parte B (sub-ticket WOT-2026-026m); bloquear ahora paralizaria
    todo cierre. Cuando B limpie la deuda, un ticket futuro sube este WARN a
    bloqueante para deuda CF NUEVA en el destino.

    Contrato del WARN en este runner (Codex contract-audit): ``run_preflight_check``
    imprime ``result.output`` SOLO si ``not result.passed``. Un WARN modelado como
    ``passed=True`` seria INVISIBLE -- justo la deuda-invisible que 026l combate.
    Por eso WARN == ``passed=False`` + ``is_blocking=False``, nunca ``passed=True``.

    Before: project_root resoluble. Si ``project_root.resolve() == _MOTOR_ROOT``
    (dogfooding del motor, sin destino separado) -> skip: ese ticket_contracts ya
    lo valida el triple del motor. Si el destino no tiene ticket_contracts -> skip.
    During: corre validate_contract_formation SOLO sobre el ticket_contracts del
    destino (no exige charter/plan_graph del destino: superficie de otro ticket).
    After: passed=True + skip si no aplica o esta limpio; passed=False +
    is_blocking=False (WARN visible con fichero+conteo+owner) si hay errores CF.
    """
    name = "Workspace Contract Formation Check (closeout, WARN)"
    # Skip: el motor como su propio project_root ya cubre su triple.
    if project_root.resolve() == _MOTOR_ROOT.resolve():
        return CheckResult(
            name=name,
            passed=True,
            output="project_root is the motor itself (covered by motor triple); skip",
            is_blocking=False,
        )
    tickets = project_root / ".agent" / "planning" / "ticket_contracts.md"
    if not tickets.exists():
        return CheckResult(
            name=name,
            passed=True,
            output=f"no workspace ticket_contracts.md at {tickets} (skip)",
            is_blocking=False,
        )
    try:
        from scripts.validate_contract_formation import main as validate_cf_main
    except ImportError:
        from validate_contract_formation import (
            main as validate_cf_main,  # type: ignore[no-redef]
        )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = validate_cf_main(["--tickets", str(tickets)])
    if rc != 0:
        out = buf.getvalue().strip()
        # Cuenta SOLO las lineas de error individuales (prefijo 'ERROR '), no la
        # linea-resumen 'ERRORS: N' del validador -- si no, el conteo sale +1.
        n_errors = sum(1 for ln in out.splitlines() if ln.startswith("ERROR "))
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"WARN: workspace ticket_contracts.md has {n_errors} CF structure "
                f"error(s) [owner: WOT-2026-026m]. WARN only until "
                f"WOT-2026-026m cleans the historical CF debt; then this becomes "
                f"blocking for NEW workspace CF debt.\n{out}"
            ),
            is_blocking=False,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="workspace ticket_contracts.md CF-clean (0 structure errors)",
        is_blocking=False,
    )


def run_batch_run_accounting_check(project_root: Path) -> CheckResult:
    """WOT-2026-025k: GSR-subset check over autonomous batch_run reports.

    In a `batch_run_<ts>.json` from the autonomous ticket batch, `tickets{}`
    is the CANONICAL index of terminal states. `group_stop_reports` (GSR) must
    never reference a ticket ABSENT from `tickets{}`. Origin (F1 2026-07-16):
    PREDICATE #3 (`contabilidad_completa`) self-declared PASS with an
    incomplete `tickets{}`; an auditor re-deriving the universe SOLELY from
    `tickets{}` would silently lose GSR-only tickets -- a false green.

    WARN, not blocking: this reconciles HISTORICAL reports already on disk
    (`orchestrator_pipeline/reports/batch_run_*.json`); it is not a contract
    this ticket's own scope controls, so it never blocks a push/close. It
    exists to surface accounting gaps the moment a new report lands.

    Before: project_root resoluble; reports dir may or may not exist.
    During: imports check_batch_run_accounting.check_batch_run_accounting
    (static import so check_guard_wiring's AST walker reaches it) and runs it
    over every batch_run_*.json found.
    After: passed=True if no report has an orphan GSR ticket (or none exist);
    passed=False + is_blocking=False (WARN, listing offending reports/tickets)
    otherwise. Never raises: unreadable/malformed reports are skipped.
    """
    name = "Batch Run Accounting Check (GSR-subset, WARN)"
    from scripts.check_batch_run_accounting import check_batch_run_accounting

    reports_dir = project_root / "orchestrator_pipeline" / "reports"
    if not reports_dir.exists():
        return CheckResult(
            name=name,
            passed=True,
            output=f"no {reports_dir} (skip)",
            is_blocking=False,
        )

    findings: dict[str, list[str]] = {}
    for report in sorted(reports_dir.glob("batch_run_*.json")):
        try:
            orphans = check_batch_run_accounting(report)
        except (OSError, ValueError) as exc:
            findings[report.name] = [f"UNREADABLE: {exc}"]
            continue
        if orphans:
            findings[report.name] = orphans

    if findings:
        lines = [
            "WARN: orphan GSR ticket(s) absent from tickets{} [owner: WOT-2026-025k]:"
        ]
        for report_name, orphans in findings.items():
            lines.append(f"  {report_name}: {', '.join(orphans)}")
        return CheckResult(
            name=name,
            passed=False,
            output="\n".join(lines),
            is_blocking=False,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="every batch_run_*.json GSR ticket is present in tickets{}",
        is_blocking=False,
    )


def _batch_run_for_receipt(reports_dir: Path, receipt: Path) -> Path | None:
    """El `batch_run` contra el que anclar el recibo, o None si no hay ancla.

    WOT-2026-058s. **El ancla NO puede elegirla el propio recibo.** Un primer
    intento resolvia `batch_run_<receipt['flight']>.json`, y eso deja al recibo
    auto-eximirse: si miente en `flight`, el fichero no existe, el ancla sale
    `None` y la capa de pertenencia no opina -- exactamente el recibo ajeno que
    §4.bis punto 4 declara falso_verde. Medido 2026-08-23 sobre una copia del
    arbol real: con `flight` ajeno el ancla desaparecia y el hallazgo no salia.

    Se ancla por lo que hay EN DISCO: si el directorio contiene exactamente UN
    `batch_run_*.json`, ese es el vuelo de esta corrida y el recibo se contrasta
    contra el. Con cero (aun sin cerrar) o con varios (el ancla seria ambigua, y
    elegir mal es el falso positivo de 2026-08-13) se devuelve None: esta capa
    prefiere callar antes que acusar con el ancla equivocada.

    Before: `reports_dir` existe. During: solo un glob, sin leer el recibo.
    After: la ruta si hay exactamente uno; None en cualquier otro caso. No lanza.
    """
    candidates = sorted(reports_dir.glob("batch_run_*.json"))
    return candidates[0] if len(candidates) == 1 else None


def run_seal_staleness_check(project_root: Path) -> CheckResult:
    """WOT-2026-055c: seal-staleness over start_context_isolation receipts.

    The start-context-isolation receipt of Paso 0-bis is a DUAL-CONTRACT gate
    that until today only a human audit verified. This check runs the
    seal-staleness guard (`check_seal_staleness.py`: integrity triple-via,
    temporal order, semantic-freshness heuristic) over every
    ``start_context_isolation*.json`` present in the destino's reports dir, so
    a stale/counterfeit receipt surfaces at closeout instead of riding along.

    WARN, not blocking, for the same reason as its sibling
    ``run_batch_run_accounting_check``: it reconciles receipts already on disk
    (legacy flights predate ``scope``/bytes/lines), so it never blocks a
    push/close by itself. It exists to surface the moment a bad seal lands.

    Before: project_root resoluble; reports dir may or may not exist.
    During: imports `check_seal_staleness.check_seal_staleness` (static import
    so check_guard_wiring's AST walker reaches it) and runs it over each
    receipt found; ``[WARN]`` findings never fail the result.
    After: passed=True if no receipt has a hard finding (or none exist);
    passed=False + is_blocking=False (WARN, listing offending receipts)
    otherwise. Never raises: unreadable/malformed receipts are listed.
    """
    name = "Seal-Staleness Check (start_context_isolation, WARN)"
    from scripts.check_seal_staleness import check_seal_staleness

    reports_dir = project_root / "orchestrator_pipeline" / "reports"
    if not reports_dir.exists():
        return CheckResult(
            name=name,
            passed=True,
            output=f"no {reports_dir} (skip)",
            is_blocking=False,
        )

    findings: dict[str, list[str]] = {}
    for receipt in sorted(reports_dir.glob("start_context_isolation*.json")):
        # WOT-2026-058s: pasar el ANCLA de pertenencia, o la capa queda INERTE.
        # Medido 2026-08-23 por dos auditorias independientes: sin
        # `batch_run_path` un recibo de OTRO vuelo pasaba SIN HALLAZGOS, asi que
        # el guard mordia en sus tests y no miraba donde ocurre el fallo
        # ("barrera del alcance"); §4.bis punto 4 lo declara falso_verde.
        #
        # El ancla se deriva del PROPIO recibo (su `flight`), nunca de un vuelo
        # externo: contrastar contra el ancla equivocada es el falso positivo
        # que ese mismo punto documenta (2026-08-13, estuvo a punto de destruir
        # una acreditacion legitima). Si el recibo no nombra su vuelo, o su
        # batch_run no esta en disco, se pasa `None` y esta capa simplemente no
        # opina -- nunca inventa un ancla.
        batch_run = _batch_run_for_receipt(reports_dir, receipt)
        try:
            found = check_seal_staleness(
                receipt, batch_run_path=batch_run, project_root=project_root
            )
        except (OSError, ValueError) as exc:
            findings[receipt.name] = [f"UNREADABLE: {exc}"]
            continue
        hard = [f for f in found if not f.startswith("[WARN]")]
        if hard:
            findings[receipt.name] = hard

    if findings:
        lines = ["WARN: seal-staleness finding(s) [owner: WOT-2026-055c]:"]
        for receipt_name, found in findings.items():
            lines.append(f"  {receipt_name}:")
            lines.extend(f"      {f}" for f in found)
        return CheckResult(
            name=name,
            passed=False,
            output="\n".join(lines),
            is_blocking=False,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="every start_context_isolation*.json is fresh and intact",
        is_blocking=False,
    )


def run_contract_reconcile_check(project_root: Path) -> CheckResult:
    """WOT-2026-024e: frozen contracts in ticket_contracts.md with no scheduling
    row (the batch reads only backlog.md, so it can never execute them).

    The SCRIPT is fail-closed (check_contract_backlog_reconcile.find_orphans lists
    them). The WARN/FAIL verdict lives HERE: WARN by default (is_blocking=False,
    reports but does not fail the close), FAIL when CONTRACT_RECONCILE_STRICT=1
    (is_blocking=True). The toggle is what keeps this a real barrier (it CAN block
    on demand) rather than a never-blocks reporter (WOT-2026-024e / M20).
    """
    name = "Contract-Backlog Reconcile (WOT-2026-024e)"
    strict = os.environ.get("CONTRACT_RECONCILE_STRICT", "").strip() == "1"
    try:
        from scripts.check_contract_backlog_reconcile import find_orphans
    except ImportError:
        from check_contract_backlog_reconcile import (
            find_orphans,  # type: ignore[no-redef]
        )
    orphans = find_orphans(project_root)
    if orphans:
        detail = "\n".join(f"  - {t}" for t in orphans)
        mode = (
            "BLOCKING (CONTRACT_RECONCILE_STRICT=1)."
            if strict
            else "WARN only; set CONTRACT_RECONCILE_STRICT=1 to block."
        )
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"{len(orphans)} frozen contract(s) with no scheduling row:\n{detail}\n"
                f"Materialize a backlog row for each (human action). {mode}"
            ),
            is_blocking=strict,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="every frozen contract has a scheduling row",
        is_blocking=strict,
    )


def run_distributable_planning_check(project_root: Path) -> CheckResult:
    """WOT-2026-024h (C4'): la superficie DISTRIBUIBLE no puede llevar contratos
    de planning REALES del motor.

    Barrera de la retirada decidida en DEC-024H-001 (opcion c): el motor dejo de
    versionar ``.agent/planning/ticket_contracts.md`` porque sus 3 contratos de
    dogfooding (021k/023r/023s) aterrizaban en CADA destino nuevo (medido: un
    ``--install`` real depositaba 3 cabeceras ``## WOT-``). Sin este gate, el seed
    puede volver por la puerta de atras y nadie se entera hasta el siguiente
    destino contaminado.

    Ambito: mide lo que VIAJA -- los paths de planning de ``MANIFEST.workspace``
    tal como estan EN EL ARBOL DE TRABAJO. Estar gitignored NO exime: el
    instalador copia del filesystem, asi que un contrato untracked bajo esa ruta
    llega igual al destino (medido en la ruta productiva; una version previa de
    este gate filtraba por git-tracked y daba FALSO VERDE sobre ese caso).
    Un gate sobre "hay planning" seria falso-rojo permanente; la propiedad
    correcta es "hay contratos REALES en lo que el instalador copiaria".

    BLOQUEANTE a proposito (no WARN opt-in): a diferencia de la deuda historica de
    un destino, esto es un invariante del motor que HOY ya se cumple, asi que no
    puede haber falso-rojo legacy que amnistiar. El import es ESTATICO para que
    ``check_guard_wiring`` lo alcance (precedente: ``validate_observations``, 035b).

    Before: project_root resoluble; el gate mide el MOTOR (_MOTOR_ROOT), no el destino.
    During: ejecuta find_contaminated sobre la superficie distribuible del motor.
    After:  passed=True si no hay contaminacion; False (bloqueante) con el listado
            de fichero->ids si la hay. Read-only.
    """
    name = "Distributable Planning Clean (WOT-2026-024h)"
    try:
        from scripts.check_distributable_planning_clean import find_contaminated
    except ImportError:
        from check_distributable_planning_clean import (
            find_contaminated,  # type: ignore[no-redef]
        )
    hits = find_contaminated(_MOTOR_ROOT)
    if hits:
        detail = "\n".join(
            f"  - {rel}: {', '.join(sorted(set(ids)))}"
            for rel, ids in sorted(hits.items())
        )
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"{len(hits)} distributable planning file(s) carry REAL motor "
                f"contracts (they would travel to every fresh destination):\n{detail}\n"
                "Migrate them to the WORKSPACE ticket_contracts.md (non-destructive "
                "append) and `git rm --cached` the file. Do NOT add a neutral seed: "
                "CG-WOT-2026-024h proved no form passes validate_contract_formation."
            ),
            is_blocking=True,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="no distributable planning surface carries real motor contracts",
        is_blocking=True,
    )


def run_guard_wiring_orphan_check(project_root: Path) -> CheckResult:
    """WOT-2026-026v: deuda declarada cuyo ticket dueno ya esta ARCHIVADO.

    Por que AQUI y no en el hook de pre-commit. `check_guard_wiring` ya corre en
    pre-commit, pero ALLI no hay destino que consultar: el hook corre sobre el motor
    y no puede llevar cableada una ruta de esta maquina sin dejar de ser portable
    (justo lo que prohibe check_distribution_agnostic). Sin destino, la deteccion de
    huerfanos SKIPEA -- y un SKIP permanente convierte la capacidad en una NORMA que
    depende de que alguien recuerde pasar la flag, no en una barrera. El cierre SI
    conoce el destino (`project_root`), asi que es la superficie que corre sola donde
    la comprobacion puede ser REAL. Hallazgo del review adversarial del propio ticket.

    WARN (is_blocking=False) a proposito: la deuda huerfana que existe HOY es
    historica (3 owners archivados, medidos), y bloquear el cierre con ella seria un
    falso-rojo heredado. El import es ESTATICO para que `check_guard_wiring` alcance
    este call-site (precedente: `run_distributable_planning_check`).

    Before: project_root resoluble; el guard lee el backlog VIVO del destino.
    During: cruza cada owner de known_unwired contra la cola viva; BY-DESIGN exento.
    After:  passed=True si no hay huerfanos o el destino no es resoluble (SKIP
            explicito, nunca un verde mudo); False (WARN) con el listado si los hay.
            Read-only.
    """
    name = "Guard Wiring Orphan Debt (WOT-2026-026v)"
    try:
        from scripts.check_guard_wiring import (
            _live_owner_tickets,
            _load_policy,
            _orphan_owners,
            audit,
        )
    except ImportError:
        from check_guard_wiring import (  # type: ignore[no-redef]
            _live_owner_tickets,
            _load_policy,
            _orphan_owners,
            audit,
        )
    live, err = _live_owner_tickets(project_root)
    if live is None:
        return CheckResult(
            name=name,
            passed=True,
            output=f"SKIP: {err}",
            is_blocking=False,
        )
    policy = _load_policy()
    known = policy["known_unwired"]
    _wired, unwired = audit(_MOTOR_ROOT, policy)
    declared = [g for g in unwired if g in known and g not in policy["wired_via"]]
    orphans = _orphan_owners(known, declared, live)
    if orphans:
        detail = "\n".join(f"  - {o}" for o in orphans)
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"{len(orphans)} guard(s) of DECLARED debt whose owner is archived "
                f"while the guard is STILL unwired:\n{detail}\n"
                "Nobody is going to wire these: the declaration stopped bounding the "
                "debt and started hiding it. Reopen the ticket, wire the guard, or "
                "re-declare it with a LIVE owner in scripts/guard_wiring_policy.yaml."
            ),
            is_blocking=False,
        )
    return CheckResult(
        name=name,
        passed=True,
        output=f"no orphan debt ({len(declared)} declared, all owners live/BY-DESIGN)",
        is_blocking=False,
    )


def run_agent_write_enforced_check(project_root: Path) -> CheckResult:
    """WOT-2026-048h: `write: false` sin enforcement posible es DECORATIVO (WARN).

    Cierra la laguna DECLARADA de WOT-2026-048k cableando
    `check_agent_write_enforced` en un camino que corre solo -- citarlo en un
    prompt seria una norma, no una barrera (punto (3) del DoD).

    NACE EN WARN, y es una decision de ALCANCE, no una relajacion: la deuda es
    PREEXISTENTE (`claude` y `codex` no declaran `readonly_agent` hoy), asi que
    nacer bloqueante dejaria el repo en rojo permanente por algo que este ticket
    no contrata arreglar -- tocar `agents.json` es superficie de otro ticket. Es
    el mismo patron con que nacieron `run_workspace_contract_formation_check` y
    `run_flight_plan_collision_check`. Endurecerlo a bloqueante exige antes
    declarar `readonly_agent` en esos dos backends: DECISION DEL OPERADOR.

    Contrato del WARN en este runner: `run_preflight_check` imprime
    `result.output` SOLO si `not result.passed`. Un WARN modelado como
    `passed=True` seria INVISIBLE -- exactamente la deuda-invisible que estos
    gates combaten. Por eso WARN == `passed=False` + `is_blocking=False`.

    Before: `.agent/config/agents.json` del MOTOR (los perfiles del ensemble
        viven ahi, no en el destino).
    During: read-only; delega en `find_unenforced_pairs`, que es puro.
    After: `passed=True` si no hay pares huerfanos o la config no es legible
        (SKIP nombrado); `passed=False` + `is_blocking=False` nombrando CADA par
        (perfil, backend) cuya restriccion no se puede enforcear.
    """
    name = "Agent Write Enforced (WOT-2026-048h, WARN)"

    try:
        from scripts.check_agent_write_enforced import find_unenforced_pairs
    except ImportError:
        return CheckResult(
            name=name,
            passed=True,
            output="SKIP: check_agent_write_enforced no importable",
            is_blocking=False,
        )
    cfg_path = _MOTOR_ROOT / ".agent" / "config" / "agents.json"
    try:
        config = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CheckResult(
            name=name,
            passed=True,
            output=f"SKIP: no se pudo leer {cfg_path}: {exc}",
            is_blocking=False,
        )
    pairs = find_unenforced_pairs(config)
    if not pairs:
        return CheckResult(
            name=name,
            passed=True,
            output="OK: todo perfil con vector (channel: agent) y write:false enforcea.",
            is_blocking=False,
        )
    detalle = "; ".join(f"{p['profile']} -> {p['backend']}" for p in pairs)
    return CheckResult(
        name=name,
        passed=False,
        output=(
            f"WARN ({len(pairs)} par/es): declaran `write: false` sin poder "
            f"enforcearlo, la restriccion es DECORATIVA -- {detalle}. "
            "Deuda PREEXISTENTE (WOT-2026-048h nace WARN a proposito). Remedio: "
            "declarar `readonly_agent` en esos backends; NO quitar `write: false` "
            "(silencia el gate sin quitar el vector)."
        ),
        is_blocking=False,
    )


def _principal_sync_plan(project_root: Path) -> dict | None:
    """Plan READ-ONLY de sync del checkout PRINCIPAL, o None si no es resoluble.

    WOT-2026-048l. Aislado en su propio helper para que el check sea testable sin
    tocar git: los tests monkeypatchean ESTA funcion, no `subprocess`.

    Before: `project_root` es el destino-rol; el motor se resuelve por link.
    During: delega en `sync_principal.plan_sync`, que es el nucleo de decision
        PURO -- no muta nada (ni fetch: se pasa el target ya conocido).
    After: devuelve el dict del plan (`action` in {already_current, advance,
        rescue_then_advance, refuse_named_branch, error}) o None si no hay motor,
        no hay checkout principal, o git no responde.
    """
    try:
        from runtime.motor_link import resolve_motor_root
        from scripts.sync_principal import _detect_primary, plan_sync
    except ImportError:
        return None
    motor_root = resolve_motor_root(project_root)
    if motor_root is None:
        return None
    try:
        primary = _detect_primary(motor_root)
        if primary is None:
            return None
        return plan_sync(motor_root, primary, "origin/main", stamp="prepush")
    except Exception:
        # Un guard que revienta por git es peor que uno que declara SKIP: el
        # cierre no debe caerse por no poder mirar un checkout de consumo.
        return None


def run_principal_freshness_check(project_root: Path) -> CheckResult:
    """WOT-2026-048l: la frescura del PRINCIPAL se comprueba y se AVISA.

    `sync_principal.py` existia, funcionaba y NADIE lo invocaba: 0 hits en este
    fichero y en `agent_controller.py`; el prompt de cierre lo citaba solo para
    NORMALIZAR el estado stale, nunca para prescribirlo. Censo semantico: el
    otro mecanismo (`daily_sync_principal.ps1`) solo se cita a si mismo. Era una
    NORMA, no una barrera -- y su ausencia hizo divergir el propio prompt de
    cierre (297 vs 290 lineas) mientras el operador leia el checkout obsoleto.

    AVISA, NO EJECUTA (decision del DoD (b), no re-decidida aqui): aplicar el
    sync mutaria un checkout que el operador puede estar usando. Por eso
    `is_blocking=False` y por eso el output CITA EL COMANDO EXACTO en vez de
    correrlo -- un aviso que obliga a buscar el remedio no es accionable.

    Before: `project_root` es el destino-rol.
    During: lee el plan read-only via `_principal_sync_plan`. Sin mutacion.
    After: `passed=True` siempre (avisa, no bloquea). El VEREDICTO vive en el
        output: nombra el sha origen y destino cuando hay drift, y declara un
        SKIP EXPLICITO cuando el principal no es resoluble -- nunca un verde mudo.
    """
    name = "Principal Freshness (WOT-2026-048l)"
    plan = _principal_sync_plan(project_root)
    if plan is None:
        return CheckResult(
            name=name,
            passed=True,
            output=(
                "SKIP: no hay checkout principal resoluble (motor sin link, sin "
                "worktree principal, o git no responde). No es un fallo: es un "
                "SKIP nombrado para no dejar un verde mudo."
            ),
            is_blocking=False,
        )
    action = plan.get("action")
    if action == "already_current":
        return CheckResult(
            name=name,
            passed=True,
            output=f"principal AL DIA con origin/main ({plan.get('primary_sha')}).",
            is_blocking=False,
        )
    if action == "refuse_named_branch":
        return CheckResult(
            name=name,
            passed=True,
            output=(
                f"AVISO: el principal esta en la rama '{plan.get('branch')}', no "
                "detached. Es consume-only por diseno (NON-GOAL de 048l: no se "
                "pone en una rama). Revisalo a mano."
            ),
            is_blocking=False,
        )
    if action == "error":
        return CheckResult(
            name=name,
            passed=True,
            output=f"SKIP: {plan.get('reason', 'no se pudo resolver el plan')}",
            is_blocking=False,
        )
    return CheckResult(
        name=name,
        passed=True,
        output=(
            f"AVISO: el checkout principal esta STALE -- {plan.get('primary_sha')} "
            f"-> {plan.get('target_sha')} (accion: {action}). Los destinos "
            "consumen de ahi, asi que un prompt leido en el principal puede estar "
            "obsoleto. Remedio: "
            "python scripts/sync_principal.py --apply --fetch"
        ),
        is_blocking=False,
    )


def run_loop_execution_check(project_root: Path) -> CheckResult:
    """WOT-2026-040b: el bucle de gobierno 1->9->2 corrio de verdad, no degradado.

    Cablea `check_loop_execution` en el cierre -- el punto que corre solo Y conoce
    el destino cuyo `.agent/runtime/ensemble/` guarda los receipts. El import es
    ESTATICO para que `check_guard_wiring` alcance este call-site y cuente el guard
    como CABLEADO (precedente: `run_guard_wiring_orphan_check`). Retirar esta
    invocacion deja el guard UNWIRED -> lo caza check_guard_wiring (mutation del DoD).

    Que verifica: por cada commit de ticket del vuelo, >=N rondas de EJECUCION con
    backend_key DISTINTO y un challenge_nonce emitido FUERA antes de la ronda. Los
    commits a verificar los declara el orquestador via
    `.agent/collaboration/loop_execution_targets.txt` (una linea `sha[ deliverable_type]`
    por commit). SIN ese fichero, SKIPEA EXPLICITAMENTE -- un SKIP mudo convertiria
    la barrera en norma; se IMPRIME el motivo.

    WOT-2026-055q: la barrera NACIO en WARN (`is_blocking=False`) porque ningun
    vuelo emitia todavia receipts con nonce, y el docstring fijaba el criterio de
    endurecimiento: "va con el primer vuelo que emita". ESE VUELO YA EMITIO -- el
    20260812b dejo nonces, receipts y `loop_execution_targets.txt` con 3 commits --
    asi que la rama de FALLO pasa a BLOQUEANTE. Sin ese cambio el check era el
    patron CEM `exit 0 puede significar "no hice nada"`: un vuelo sin gobierno
    atravesaba el cierre sin friccion y solo lo cazaba un humano por escrito.

    Lo que NO cambia (backward-compat deliberada): las tres ramas de SKIP siguen
    `passed=True, is_blocking=False`, para que un vuelo de solo-docs que no declara
    targets no herede un falso-rojo. Ahora ademas llevan `skipped=True`: un SKIP
    que pasa como `[OK]` a secas es indistinguible de un gate cumplido, que es
    justo lo que documenta el docstring de `CheckResult`.

    Before: project_root resoluble.
    During: lee el fichero de targets (si existe) y corre el guard sobre el
        scorecard + emitted_nonces del destino. Read-only.
    After: passed=True si no hay targets (SKIP nombrado, no bloqueante) o todos
        pasan; passed=False e is_blocking=True -- el cierre ABORTA -- con el detalle
        de los commits sin fan-out ejecutado.
    """
    name = "Loop Execution Barrier (WOT-2026-040b)"
    try:
        from scripts.check_loop_execution import audit as _loop_audit
    except ImportError:
        from check_loop_execution import audit as _loop_audit  # type: ignore[no-redef]

    targets_file = (
        project_root / ".agent" / "collaboration" / "loop_execution_targets.txt"
    )
    if not targets_file.exists():
        return CheckResult(
            name=name,
            passed=True,
            output=(
                f"SKIP: no {targets_file.name} (el orquestador no declaro commits de "
                "vuelo a verificar). Emite receipts con emit-nonce y declara los "
                "commits para activar la barrera."
            ),
            is_blocking=False,
            skipped=True,
        )
    commit_shas: list[str] = []
    per_commit_dtype: dict[str, str] = {}
    try:
        for line in targets_file.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            sha = parts[0]
            commit_shas.append(sha)
            if len(parts) > 1:
                per_commit_dtype[sha] = parts[1]
    except OSError as exc:
        return CheckResult(
            name=name,
            passed=True,
            output=f"SKIP: no se pudo leer {targets_file}: {exc}",
            is_blocking=False,
            skipped=True,
        )
    if not commit_shas:
        return CheckResult(
            name=name,
            passed=True,
            output=f"SKIP: {targets_file.name} no declara ningun commit.",
            is_blocking=False,
            skipped=True,
        )

    failures: list[dict] = []
    for sha in commit_shas:
        verdicts = _loop_audit(
            project_root,
            commit_shas=[sha],
            deliverable_type=per_commit_dtype.get(sha),
        )
        failures.extend(v for v in verdicts if not v["ok"])
    if failures:
        detail = "\n".join(
            f"  - {v['commit_sha']}: {len(v['distinct_backends'])}/{v['min_distinct']} "
            f"lentes distintas {v['distinct_backends']}"
            for v in failures
        )
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"{len(failures)} commit(s) sin el fan-out de gobierno 1->9->2 "
                f"ejecutado (o ejecutado DEGRADADO):\n{detail}\n"
                "Cada commit exige >=N rondas con backend_key DISTINTO y un "
                "challenge_nonce emitido FUERA antes de la ronda. El bucle es una "
                "barrera, no una norma (WOT-2026-040b/055q): esto ABORTA el cierre."
            ),
            is_blocking=True,
        )
    return CheckResult(
        name=name,
        passed=True,
        output=f"{len(commit_shas)} commit(s) con fan-out de gobierno ejecutado.",
        is_blocking=False,
    )


def run_flight_plan_collision_check(project_root: Path) -> CheckResult:
    """WOT-2026-027h: colision INTER-plan en queued/ (check HERMANO de validate_batch_dag).

    Por que AQUI. validate_batch_dag valida UN dag y es CIEGO al conjunto; el unico
    punto que corre solo Y conoce el destino cuyo queued/ contiene TODOS los planes es
    el cierre. El import es ESTATICO para que `check_guard_wiring` alcance este
    call-site y cuente el guard como CABLEADO (precedente: `run_guard_wiring_orphan_check`).
    Retirar esta invocacion deja el guard UNWIRED -> lo caza check_guard_wiring
    (mutation del DoD de des-cableado).

    WARN (is_blocking=False) a proposito, precedente run_guard_wiring_orphan_check: el
    queued/ real YA colisiona antes de introducir la barrera (deuda historica medida),
    y bloquear el cierre con ella seria un falso-rojo heredado. El CHECK en si (exit!=0)
    es fiel al contrato "colision SIEMPRE falla, sin allowlist"; es el CABLEADO el que
    nace no bloqueante. Criterio de salida a is_blocking=True: WOT-2026-040r (limpiar
    queued/ hasta exit 0 y endurecer con prueba que falle ante colision fixture).

    Before: project_root resoluble; queued/ puede existir o no.
    During: recorre orchestrator_pipeline/flight_plans/queued/*.json (read-only) y cruza
        ticket-ids y shared_surfaces entre planes.
    After: passed=True si no hay colisiones o queued/ no existe (SKIP nombrado, nunca un
        verde mudo); False (WARN) con el listado si las hay. Read-only.
    """
    name = "Flight Plan Collision (WOT-2026-027h)"
    try:
        from scripts.check_flight_plan_collision import find_collisions
    except ImportError:
        from check_flight_plan_collision import (  # type: ignore[no-redef]
            find_collisions,
        )

    queued_dir = project_root / "orchestrator_pipeline" / "flight_plans" / "queued"
    if not queued_dir.is_dir():
        return CheckResult(
            name=name,
            passed=True,
            output=f"SKIP: no existe {queued_dir} (sin planes en cola).",
            is_blocking=False,
        )
    collisions = find_collisions(queued_dir)
    if collisions:
        detail = "\n".join(f"  - {c.render()}" for c in collisions)
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"{len(collisions)} colision(es) inter-plan en queued/:\n{detail}\n"
                "Un ticket en 2 planes o una shared_surface compartida es una colision "
                "(SIN allowlist). El caso legitimo de coordinacion se resuelve sacando de "
                "queued/ el plan que espera, no relajando el check (WOT-2026-027h)."
            ),
            is_blocking=False,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="queued/ sin colisiones inter-plan",
        is_blocking=False,
    )


def run_handoff_state_sha_check(project_root: Path) -> CheckResult:
    """WOT-2026-024t (superficie 2): a handoff's STATE section must not embed a SHA
    (it rots the instant HEAD moves). WARN by default (is_blocking=False), FAIL when
    HANDOFF_STATE_SHA_STRICT=1. The toggle keeps it a real barrier (it CAN block on
    demand) rather than a never-blocks reporter (M20). Reports every hit; the current
    reports dir may hold a consumed ARRANQUE with a stale SHA -- WARN default avoids a
    false red on that legacy handoff while still surfacing it.
    """
    name = "Handoff State SHA (WOT-2026-024t)"
    strict = os.environ.get("HANDOFF_STATE_SHA_STRICT", "").strip() == "1"
    try:
        from scripts.check_handoff_state_sha import scan_handoffs
    except ImportError:
        from check_handoff_state_sha import scan_handoffs  # type: ignore[no-redef]
    findings = scan_handoffs(project_root)
    if findings:
        detail = "\n".join(
            f"  - {f['file']}:{f['line']} under '{f['heading']}': {f['sha']}"
            for f in findings
        )
        mode = (
            "BLOCKING (HANDOFF_STATE_SHA_STRICT=1)."
            if strict
            else "WARN only; set HANDOFF_STATE_SHA_STRICT=1 to block."
        )
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"{len(findings)} SHA(s) embedded in a handoff STATE section:\n{detail}\n"
                f"Verify state against git instead of embedding a SHA. {mode}"
            ),
            is_blocking=strict,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="no SHA embedded in a handoff state section",
        is_blocking=strict,
    )


def run_handoff_committed_check(motor_root: Path | None = None) -> CheckResult:
    """WOT-2026-040t (Pieza 1): reject a closeout whose work is not committed.

    Wires the rejector into a path that runs on its own. A commit is immutable;
    a working tree is not.

    SCOPE, stated honestly (corrected in review, WOT-2026-040t): closeout is NOT
    the moment the 2026-07-25 incident happened -- that race ran hours earlier,
    during the audit/suite window, and this check would have rejected the dirty
    tree only after three contradictory verdicts already existed. Two known gaps
    remain, both owned by follow-ups rather than silently implied away:
      * handoff time has no invocation: declaring "ready to audit @ sha" to a
        sister auditor triggers nothing.
      * ``--session-close --dry-run`` returns SKIP before prepush runs
        (scripts/closeout_steps/gates.py), which is the exact invocation
        WOT-2026-040j used.
    What this DOES buy: no closeout can certify a tree carrying uncommitted work
    or a repo-global stash.

    BLOCKING by design, unlike its WARN-default neighbours. Those tolerate known
    historical debt; this one has none -- an uncommitted tree or a pending stash
    at closeout time is always a live defect, never legacy. Making it WARN would
    reproduce the M20 never-blocks-reporter shape the policy rejects.

    Scope is the MOTOR repo: refs/stash is global to the repository and shared
    across every flight worktree, so a stash pushed by another flight is limbo
    work indistinguishable from this one's (failure mode F3).
    """
    name = "Handoff Committed (WOT-2026-040t)"
    try:
        from scripts.check_handoff_committed import EXIT_OK, evaluate
    except ImportError:
        from check_handoff_committed import (  # type: ignore[no-redef]
            EXIT_OK,
            evaluate,
        )
    root = (motor_root or Path(__file__).resolve().parent.parent).resolve()
    code, lines = evaluate(root)
    return CheckResult(
        name=name,
        passed=code == EXIT_OK,
        output="\n".join(lines),
        is_blocking=True,
    )


def run_destination_pii_check(
    project_root: Path, motor_root: Path | None = None
) -> CheckResult:
    """WOT-2026-020t: destinations on this machine must not track the link file nor
    .agent/collaboration/ (they carry local absolute paths and leak PII on push).

    The SCRIPT is fail-closed (exit 1 on leaks, exit 2 when an included
    destination cannot be audited). The WARN/FAIL verdict lives HERE: WARN by
    default (the known dirty published destinations are live debt owned by
    WOT-2026-023b, human-gated -- failing every close until a human acts would
    be a false red), FAIL when DESTINATION_PII_STRICT=1. The toggle keeps this
    a real barrier (M20). motor_root defaults to THIS repo: the census is
    machine-wide and anchored at the motor, independent of the project being
    closed.
    """
    name = "Destination PII Leak (WOT-2026-020t)"
    strict = os.environ.get("DESTINATION_PII_STRICT", "").strip() == "1"
    try:
        from scripts.check_destination_pii_leak import run_audit
    except ImportError:
        from check_destination_pii_leak import run_audit  # type: ignore[no-redef]
    root = (
        motor_root if motor_root is not None else Path(__file__).resolve().parent.parent
    )
    audits, _discovery = run_audit(root)
    leaking = [a for a in audits if a.leaking]
    unauditable = [a for a in audits if a.error is not None]
    if leaking or unauditable:
        lines = [
            f"  - LEAK {a.root}: {len(a.tracked_files)} tracked file(s)"
            for a in leaking
        ] + [f"  - UNAUDITABLE {a.root}: {a.error}" for a in unauditable]
        mode = (
            "BLOCKING (DESTINATION_PII_STRICT=1)."
            if strict
            else "WARN only; set DESTINATION_PII_STRICT=1 to block."
        )
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"{len(leaking)} leaking / {len(unauditable)} unauditable "
                f"destination(s):\n" + "\n".join(lines) + "\n"
                f"Untrack is human-gated (WOT-2026-023b); the installer only "
                f"untracks under --untrack-existing. {mode}"
            ),
            is_blocking=strict,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="no destination tracks the managed PII surfaces",
        is_blocking=strict,
    )


def run_closeout_reconciliation_check(project_root: Path) -> CheckResult:
    """WOT-2026-024w: the live backlog must reconcile with the bus SUPERVISOR_CLOSED
    events (drift = a ticket closed on the bus but still live in the backlog, or
    declared-done without its bus event).

    The SCRIPT is fail-closed (run_gate report["all_pass"] False on drift). The
    WARN/FAIL verdict lives HERE: WARN by default, FAIL when
    CLOSEOUT_RECONCILE_STRICT=1. The toggle keeps it a real barrier (M20) that CAN
    block on demand, without failing every close today over pre-existing drift owned
    by older tickets (measured 2026-07-18: 5 drifts from 010s/010u/011f/013o/016a --
    a hard block would be a false red on debt this ticket does not own).
    """
    name = "Closeout Reconciliation (WOT-2026-024w)"
    strict = os.environ.get("CLOSEOUT_RECONCILE_STRICT", "").strip() == "1"
    try:
        from scripts.check_closeout_reconciliation import run_gate
    except ImportError:
        from check_closeout_reconciliation import run_gate  # type: ignore[no-redef]
    report = run_gate(project_root)
    if not report["all_pass"]:
        mode = (
            "BLOCKING (CLOSEOUT_RECONCILE_STRICT=1)."
            if strict
            else "WARN only; set CLOSEOUT_RECONCILE_STRICT=1 to block."
        )
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"backlog<->bus drift detected (bus_closed={report.get('bus_closed')}, "
                f"live_backlog={report.get('live_backlog')}). {mode}"
            ),
            is_blocking=strict,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="live backlog reconciles with the bus SUPERVISOR_CLOSED events",
        is_blocking=strict,
    )


def run_landed_evidence_shape_check(project_root: Path) -> CheckResult:
    """Fail a close whose archived row carries commit evidence the guard cannot read.

    WOT-2026-043t. ``census_archived`` classifies TERMINAL rows; a row whose SHA was
    written into the STATE cell has no terminal state, so it matched none of
    required/audited/skipped_required/skipped_legacy and VANISHED -- while
    ``check_backlog_commits_landed`` still printed ``ERROR=0``. Measured 2026-08-03
    while archiving WOT-2026-040u: the row was real, the SHA was real, and no counter
    ever saw it.

    This is the WIRING half. The detector alone was a NORM: ``census_archived`` is
    called only by that script's CLI, and the CLI runs in no hook -- the static-import
    wiring recorded in ``guard_wiring_policy.yaml`` reaches ``audit``/
    ``parse_archived_commits`` via agent_controller, never the census. Here it runs on
    a path that runs by itself.

    BLOCKING by design, unlike its ``run_closeout_reconciliation_check`` sibling: that
    one defaults to WARN because it reports pre-existing drift owned by older tickets
    (a hard block would be a false red on debt the closing ticket does not own). This
    one has NO such debt -- the real archive measures 0 malformed rows today -- so a
    malformed row can only be introduced by the close being pushed. Blocking on your
    own defect is not a false red.

    Before: ``project_root`` is the destino whose ``_archive/backlog_done.md`` holds
        the closed rows. A missing archive is a PASS (nothing archived yet), never a
        fabricated failure.
    During: reads that one file and runs the pure-string census over it. No git, no
        network, no mutation.
    After: ``passed`` False (blocking) naming every offending ticket, or True.
    """
    name = "Landed Evidence Shape (WOT-2026-043t)"
    try:
        from scripts.check_backlog_commits_landed import census_archived
    except ImportError:
        from check_backlog_commits_landed import (
            census_archived,  # type: ignore[no-redef]
        )

    archive = project_root / ".agent" / "collaboration" / "_archive" / "backlog_done.md"
    if not archive.exists():
        return CheckResult(
            name=name,
            passed=True,
            output=f"SKIP: no {archive.name} in the destino (nothing archived yet)",
        )
    try:
        census = census_archived(archive.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return CheckResult(
            name=name, passed=False, output=f"cannot read {archive}: {exc}"
        )
    malformed = census.get("malformed_evidence_tickets", [])
    if malformed:
        return CheckResult(
            name=name,
            passed=False,
            output=(
                f"{len(malformed)} archived row(s) carry a commit(s) cell but NO "
                f"terminal state, so the landing census cannot see them and its "
                f"ERROR=0 would be a false green. Put the terminal state in its own "
                f"cell and keep the SHA in the commit(s) cell. "
                f"Tickets: {', '.join(malformed)}"
            ),
        )
    return CheckResult(
        name=name,
        passed=True,
        output=(
            f"every archived row with commit evidence is readable by the census "
            f"(required={census['required']} audited={census['audited']})"
        ),
    )


def run_motor_destination_integration_check(
    project_root: Path, motor_root: Path | None = None
) -> CheckResult:
    """WOT-2026-024w: the motor<->destino integration gate (link coherence, single
    canonical authority, context resolution, publish-ready delegation).

    run_integration returns EXIT_OK (0) on a healthy integration; any non-zero is a
    real failure. WARN by default, FAIL when MOTOR_DEST_INTEGRATION_STRICT=1 (M20:
    a real barrier that CAN block, not a never-blocks reporter).
    """
    name = "Motor<->Destino Integration (WOT-2026-024w)"
    strict = os.environ.get("MOTOR_DEST_INTEGRATION_STRICT", "").strip() == "1"
    try:
        from scripts.check_motor_destination_integration import run_integration
    except ImportError:
        from check_motor_destination_integration import (  # type: ignore[no-redef]
            run_integration,
        )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_integration(project_root, motor_root, audit_publication=False)
    if rc != 0:
        mode = (
            "BLOCKING (MOTOR_DEST_INTEGRATION_STRICT=1)."
            if strict
            else "WARN only; set MOTOR_DEST_INTEGRATION_STRICT=1 to block."
        )
        return CheckResult(
            name=name,
            passed=False,
            output=f"integration gate rc={rc}:\n{buf.getvalue().strip()}\n{mode}",
            is_blocking=strict,
        )
    return CheckResult(
        name=name,
        passed=True,
        output="motor<->destino integration gate passed",
        is_blocking=strict,
    )


def run_portable_memory_archive_check(project_root: Path) -> CheckResult:
    """Ejecuta el guard de schema del archive de memoria portable (WOT-2026-035b).

    Valida `.agent/runtime/memory/archive/observations.*.jsonl` (el UNICO
    vehiculo portable de la memoria del motor) contra el schema canonico.
    Blocking: el 2026-07-18 el archive trackeado llevo 2 entradas invalidas
    y ninguna barrera cableada lo detecto antes de este ticket.

    WOT-2026-038j: el guard vive SOLO en el motor, asi que su ruta y su
    `--motor-root` se resuelven contra el MOTOR, nunca contra `project_root`.
    Construirlos desde el destino hacia que el gate se autodestruyese en la
    topologia real (motor != destino) con un FALSO ROJO -- "can't open file
    <destino>/scripts/check_portable_memory_archive_schema.py" -- bloqueando el
    closeout por un fichero que nunca estuvo ahi. Se usa el mismo patron ya
    canonico en este modulo (`run_validate_all`): `_MOTOR_ROOT` como base y
    `resolve_motor_root` solo si resuelve un candidato existente.

    Args:
        project_root: Raiz del proyecto (destino) sobre la que corre el preflight.

    Returns:
        CheckResult con el estado del check de schema del archive.
    """
    motor_root = _MOTOR_ROOT
    try:
        from runtime.motor_link import resolve_motor_root

        resolved_motor_root = resolve_motor_root(project_root)
        if (
            resolved_motor_root is not None
            and (
                resolved_motor_root
                / "scripts"
                / "check_portable_memory_archive_schema.py"
            ).exists()
        ):
            motor_root = resolved_motor_root
    except ImportError:
        pass

    return run_subprocess_check(
        cmd=[
            sys.executable,
            str(motor_root / "scripts" / "check_portable_memory_archive_schema.py"),
            "--motor-root",
            str(motor_root),
        ],
        name="Portable Memory Archive Schema (WOT-2026-035b)",
        project_root=project_root,
    )


def run_dec_receipt_check(project_root: Path) -> CheckResult:
    """Ejecuta la barrera del recibo DEC sobre los buzones de fichas (WOT-2026-042x).

    `WOT-2026-042w` puso la NORMA en los dos prompts de sesion de DISENO: toda
    ficha deja un recibo estructurado (`DEC-<id> (motor)`, `DEC-<id> (destino)`
    o `DEC-no-aplica: <motivo>`). Este cableado es lo que la convierte en
    BARRERA: sin un camino que corra solo, la norma depende de que alguien se
    acuerde. Se cablea AQUI y no en el paso 8.bis del prompt de cierre porque
    `check_guard_wiring.py:11` no cuenta los prompts como superficie -- la cita
    en 8.bis documenta el criterio, nunca lo ejecuta.

    El guard vive SOLO en el motor: su ruta y su `--motor-root` se resuelven
    contra el MOTOR, nunca contra `project_root`, siguiendo el mismo patron que
    `run_portable_memory_archive_check` (WOT-2026-038j: construirlos desde el
    destino produce un FALSO ROJO por un fichero que nunca estuvo ahi).

    El registro del destino se pasa como ARGUMENTO. Resolver la topologia
    motor<->destino DENTRO del guard es una STOP condition del contrato: si el
    registro no existe, no se pasa el flag y todo recibo `(destino)` queda
    NO VERIFICABLE (ERROR), nunca "valido por defecto".

    Args:
        project_root: Raiz del destino sobre la que corre el preflight; de ella
            se derivan los buzones de fichas y el registro de decisiones.

    Returns:
        CheckResult con el estado de la barrera del recibo DEC.
    """
    motor_root = _MOTOR_ROOT
    try:
        from runtime.motor_link import resolve_motor_root

        resolved_motor_root = resolve_motor_root(project_root)
        if (
            resolved_motor_root is not None
            and (resolved_motor_root / "scripts" / "check_dec_receipt.py").exists()
        ):
            motor_root = resolved_motor_root
    except ImportError:
        pass

    cmd = [
        sys.executable,
        str(motor_root / "scripts" / "check_dec_receipt.py"),
        "--motor-root",
        str(motor_root),
    ]

    destino_registry = project_root / ".agent" / "planning" / "decisions.md"
    if destino_registry.is_file():
        cmd += ["--destino-registry", str(destino_registry)]

    for inbox in (
        # Los DOS buzones reales, medidos sobre el destino el 2026-07-29 (6 + 8
        # = las 14 fichas del censo del contrato). El segundo vive bajo
        # `collaboration/`, no bajo `planning/`: pasar solo el primero habria
        # dejado 8 de 14 fichas SIN mirar, con el guard igualmente en verde.
        project_root / "orchestrator_pipeline" / "backlog_inbox",
        project_root / ".agent" / "collaboration" / "backlog_inbox",
    ):
        if inbox.is_dir():
            cmd += ["--inbox", str(inbox)]

    return run_subprocess_check(
        cmd=cmd,
        name="DEC Receipt Barrier (WOT-2026-042x)",
        project_root=project_root,
    )


def run_preflight_check(
    project_root: Path | None = None,
    expected_artifacts: list[str] | None = None,
    closeout_mode: bool = False,
    skip_gates: bool = False,
) -> int:
    """Ejecuta todos los checks de preflight de entrega.

    WOT-2026-014a: the optional expected_artifacts param is forwarded to
    run_delivery_hygiene_check so the closeout pre-push gate can forgive known
    runtime artifacts. Default None preserves current behavior (no forgiveness).

    WOT-2026-015g: closeout_mode=True adds run_backlog_contract_check as a
    blocking gate so --session-close fails if the live backlog still holds
    terminal tickets. Default False preserves the general pre-push behavior
    (the live-queue contract is only enforced at session close).

    Args:
        project_root: Raiz del proyecto. Si None, usa el directorio actual.
        expected_artifacts: Optional allowlist forwarded to check_git_tree_clean.
            Default None preserves current behavior (any dirty file fails).
        closeout_mode: When True, enforce the live backlog contract as a blocking
            gate (session-close only). Default False leaves it off.
        skip_gates: WOT-2026-020i. When True, the checks STILL RUN and their
            results are printed, but a blocking failure no longer forces exit 1:
            the operator explicitly chose to close over pre-existing debt
            (--session-close --skip-gates --force). Default False preserves the
            blocking behavior. Never silences the report -- only its verdict.

    Returns:
        Exit code: 0 si todos los checks bloqueantes pasan, 1 si alguno falla
        (o siempre 0 con skip_gates, que degrada el veredicto a no-bloqueante).
    """
    _configure_stdio()

    if project_root is None:
        project_root = Path.cwd()

    results: list[CheckResult] = []

    # Secuencia fija de checks bloqueantes
    # 1. Delivery Hygiene Check
    results.append(run_delivery_hygiene_check(project_root, expected_artifacts))

    # 2. Ruff Check
    results.append(run_ruff_check(project_root))

    # 3. Ruff Format Check
    results.append(run_ruff_format_check(project_root))

    # 4. Agent Controller Validate
    results.append(run_agent_controller_validate(project_root))

    # 5. Git Status Check
    results.append(run_git_status_check(project_root))

    # 6. Backlog Contract Check (solo en cierre de sesion; bloqueante)
    if closeout_mode:
        results.append(run_backlog_contract_check(project_root))
        # 6a-bis. Ghost Ticket IDs (WOT-2026-053i; no bloqueante). Hueco INVERSO
        # al de arriba: aquel valida las FILAS que existen, este los ids CITADOS
        # en git para los que nunca se escribio fila.
        results.append(run_ghost_ticket_ids_check(project_root))
        # 6b. Contract-Backlog Reconcile (WOT-2026-024e; WARN default, FAIL opt-in)
        results.append(run_contract_reconcile_check(project_root))
        # 6c. Handoff State SHA (WOT-2026-024t s2; WARN default, FAIL opt-in)
        results.append(run_handoff_state_sha_check(project_root))
        # 6c-bis. Handoff Committed (WOT-2026-040t Pieza 1; BLOQUEANTE: un arbol
        # sucio o un stash pendiente en el cierre es siempre defecto vivo)
        results.append(run_handoff_committed_check())
        # 6d. Destination PII Leak (WOT-2026-020t; WARN default, FAIL opt-in)
        results.append(run_destination_pii_check(project_root))
        # 6e. Closeout Reconciliation (WOT-2026-024w; WARN default, FAIL opt-in)
        results.append(run_closeout_reconciliation_check(project_root))
        # 6e-bis. Landed Evidence Shape (WOT-2026-043t; BLOQUEANTE: a diferencia de
        # 6e no arrastra deuda historica -- el archive real mide 0 filas malformadas,
        # asi que una solo puede entrar con el cierre que se esta empujando)
        results.append(run_landed_evidence_shape_check(project_root))
        # 6f. Motor<->Destino Integration (WOT-2026-024w; WARN default, FAIL opt-in)
        results.append(run_motor_destination_integration_check(project_root))
        # 6g. Contract Formation Check (WOT-2026-023m(c); bloqueante en cierre)
        results.append(run_contract_formation_check(project_root))
        # 6h. Workspace Contract Formation Check (WOT-2026-026l parte A; WARN,
        # no bloqueante hasta que 026m limpie la deuda historica del destino)
        results.append(run_workspace_contract_formation_check(project_root))
        # 6i. Batch Run Accounting Check (WOT-2026-025k; GSR-subset, WARN)
        results.append(run_batch_run_accounting_check(project_root))
        # 6i-bis. Seal-Staleness Check (WOT-2026-055c; WARN -- reconcilia
        # recibos start_context_isolation ya en disco, nunca bloquea por si
        # solo; cableado aqui porque este es el unico punto que corre solo Y
        # conoce el reports dir del destino).
        results.append(run_seal_staleness_check(project_root))
        # 6j. Distributable Planning Clean (WOT-2026-024h C4'; bloqueante)
        results.append(run_distributable_planning_check(project_root))
        # 6k. Guard Wiring Orphan Debt (WOT-2026-026v; WARN -- la deuda huerfana
        # de hoy es historica. Va en el cierre y no en pre-commit porque es el
        # unico punto que corre solo Y conoce el destino cuyo backlog decide si
        # un owner sigue vivo.)
        results.append(run_guard_wiring_orphan_check(project_root))
        # 6l. Loop Execution Barrier (WOT-2026-040b; WARN -- el bucle 1->9->2 debe
        # haber corrido de verdad, no degradado, por cada commit de ticket del
        # vuelo. SKIPEA nombrado si el orquestador no declaro commits/targets.)
        results.append(run_loop_execution_check(project_root))
        # 6l-bis. Principal Freshness (WOT-2026-048l; WARN -- AVISA, no ejecuta:
        # aplicar el sync mutaria un checkout que el operador puede estar usando.
        # Va en el cierre porque es el punto que corre solo y resuelve el motor.
        # El script existia y funcionaba desde hacia meses; lo que faltaba era
        # ESTA linea -- sin ella era una norma, no una barrera.)
        results.append(run_principal_freshness_check(project_root))
        # 6l-ter. Agent Write Enforced (WOT-2026-048h; WARN -- `write: false` que
        # no se puede enforcear es DECORATIVO. Nace WARN porque la deuda es
        # PREEXISTENTE (claude/codex sin `readonly_agent`) y arreglarla toca
        # `agents.json`, superficie de otro ticket; endurecer a bloqueante es
        # decision del operador. Cablearlo AQUI es el punto (3) de su DoD:
        # citarlo en un prompt seria una norma, no una barrera.)
        results.append(run_agent_write_enforced_check(project_root))
        # 6m. Flight Plan Collision (WOT-2026-027h; WARN -- el queued/ real ya
        # colisiona antes de la barrera (deuda historica); endurecer a bloqueante
        # en WOT-2026-040r cuando queued/ este limpio. El CHECK en si (exit!=0) es
        # fiel a 'colision SIEMPRE falla, sin allowlist'; el CABLEADO nace WARN.)
        results.append(run_flight_plan_collision_check(project_root))
        # 6n. DEC Receipt Barrier (WOT-2026-042x; la norma de 042w cableada).
        # Va en closeout y no en pre-commit porque su superficie son los buzones
        # de fichas del DESTINO, que este es el unico camino auto-ejecutable que
        # conoce. Las fichas anteriores a GRANDFATHER_CUTOFF degradan a WARN
        # dentro del propio guard (censo medido: 14/14 sin recibo), asi que el
        # cableado no bloquea la deuda historica.
        results.append(run_dec_receipt_check(project_root))

    # 7. Portable Memory Archive Schema (WOT-2026-035b; bloqueante siempre,
    # no solo en closeout_mode: el archive puede corromperse en cualquier push)
    results.append(run_portable_memory_archive_check(project_root))

    # Check informacional (no bloqueante)
    results.append(run_validate_all(project_root))

    # Imprimir reporte
    print("=" * 60)
    print("PREFLIGHT DE ENTREGA - Reporte")
    print("=" * 60)
    print()

    blocking_failed = _print_preflight_report(results)

    _print_preflight_verdict(blocking_failed, skip_gates)

    if skip_gates:
        return 0
    return 0 if not blocking_failed else 1


def _print_preflight_report(results: list[CheckResult]) -> bool:
    """Print one line per check and return whether a blocking check failed.

    Before: `results` es la secuencia de checks ya ejecutados.
    During: imprime `[OK]`/`[FAIL]` por check. Imprime el `output` cuando el
        check FALLA (diagnostico) y tambien cuando PASO SIN EJECUTARSE
        (procedencia del SKIP).
    After: devuelve True si algun check bloqueante fallo. No muta nada.

    Por que un SKIP tiene que imprimirse aunque `passed` sea True: un gate que
    no se ha ejecutado NO es un gate que corrio y paso, y el informe es lo
    unico que lee un humano al cerrar. La condicion original era
    `if not result.passed and result.output`, asi que el SKIP de
    `run_ruff_format_check` -- que sale con `passed=True` y lleva su
    procedencia en `output` -- se presentaba como `[OK] Ruff Format Check` a
    secas. El test de aquel SKIP verificaba el `CheckResult`, no el informe, y
    por eso no lo cazo (bucle L700, lente Codex, 2026-08-02).
    """
    blocking_failed = False

    for result in results:
        status = "[OK]" if result.passed else "[FAIL]"
        blocking_marker = "" if result.is_blocking else " (informacional)"
        print(f"{status} {result.name}{blocking_marker}")

        # Un salto pasa pero NO se ejecuto: su motivo es tan necesario como el
        # diagnostico de un fallo. Se lee del CAMPO, no del texto: la version
        # anterior miraba `output.startswith("SKIP")` y ocultaba los saltos
        # redactados de otra forma, incluidos dos BLOQUEANTES.
        is_skip = result.passed and (
            result.skipped or result.output.strip().startswith("SKIP")
        )
        if is_skip:
            print("      (SKIP: este gate no se ha ejecutado)")
        if result.output and (not result.passed or is_skip):
            # Mostrar solo las primeras lineas del output si hay error
            lines = result.output.strip().split("\n")
            for line in lines[:10]:  # Mostrar max 10 lineas
                print(f"      {line}")
            if len(lines) > 10:
                print(f"      ... y {len(lines) - 10} lineas mas")

        if not result.passed and result.is_blocking:
            blocking_failed = True

        print()

    return blocking_failed


def _print_preflight_verdict(blocking_failed: bool, skip_gates: bool) -> None:
    """Print the closing verdict banner (WOT-2026-020i extracted this to keep
    run_preflight_check under the complexity cap)."""
    print("=" * 60)
    if blocking_failed and skip_gates:
        # The operator asked to skip the gate verdict. Show the failures (never
        # silent) but degrade to non-blocking.
        print("PREFLIGHT CON FALLOS pero --skip-gates activo: cierre NO bloqueado")
        print("  (los fallos de arriba se ignoran por decision explicita del operador)")
    elif blocking_failed:
        print("PREFLIGHT BLOQUEADO: corrija los problemas antes de push")
        print("Ejecute la pasada mutadora manualmente si hace falta:")
        print("  uv run pre-commit run --all-files --hook-stage pre-commit")
        print("Luego vuelva a ejecutar este preflight")
    else:
        print("PREFLIGHT EXITOSO: arbol listo para push")
    print("=" * 60)


def main() -> int:
    """Punto de entrada CLI."""
    _configure_stdio()

    parser = argparse.ArgumentParser(
        description="Pre-push Check - canonical delivery preflight wrapper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/prepush_check.py
    Ejecuta todos los checks de preflight en el directorio actual

  python scripts/prepush_check.py --project-root /ruta/al/proyecto
    Ejecuta los checks en un directorio especifico

Secuencia de checks (todos bloqueantes excepto validate_all):
  1. Delivery Hygiene Check (hooks mutadores, artefactos, arbol limpio)
  2. Ruff Check via `uv run ruff` (linting de Python)
  3. Ruff Format Check via `uv run ruff` (formato de codigo)
  4. Agent Controller Validate (validacion de tickets)
  5. Git Status Check (arbol sin cambios)
  6. Validate All (skills, informacional)

Si el preflight falla:
  - Ejecute la pasada mutadora manualmente: pre-commit run --hook-stage pre-commit
  - Corrija los errores reportados
  - Vuelva a ejecutar este preflight hasta que todos los checks pasen
""",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Raiz del proyecto (default: directorio actual)",
    )
    parser.add_argument(
        "--closeout-mode",
        action="store_true",
        default=False,
        help=(
            "WOT-2026-014a: pass EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS allowlist to "
            "check_git_tree_clean. Only the closeout path should pass this flag; "
            "the general pre-push gate MUST NOT pass it (default behavior unchanged)."
        ),
    )
    parser.add_argument(
        "--skip-gates",
        action="store_true",
        default=False,
        help=(
            "WOT-2026-020i: run the checks and print the report, but degrade a "
            "blocking failure to non-blocking (exit 0). For an operator who "
            "explicitly chooses to close over pre-existing debt."
        ),
    )

    args = parser.parse_args()

    artifacts: list[str] | None = None
    if args.closeout_mode:
        from scripts.delivery_hygiene_check import EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS

        artifacts = EXPECTED_CLOSEOUT_RUNTIME_ARTIFACTS
    return run_preflight_check(
        project_root=args.project_root,
        expected_artifacts=artifacts,
        closeout_mode=args.closeout_mode,
        skip_gates=args.skip_gates,
    )


if __name__ == "__main__":
    sys.exit(main())
