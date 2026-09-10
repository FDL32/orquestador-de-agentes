#!/usr/bin/env python3
r"""Guard: un prompt de arranque no puede mandar leer runtime SIN ruta absoluta.

EL FALLO QUE CIERRA (medido 2026-09-10, coste: un vuelo detenido)
------------------------------------------------------------------
El prompt de arranque de `WOT-2026-067m` decia, en el punto donde el Builder decide:

    Confirma que `work_plan.md` activo apunta a `WOT-2026-067m` [...]

Sin prefijo de raiz. En esta topologia existen DOS `.agent/collaboration/`: el del
WORKTREE del motor (SEED NEUTRO con tickets viejos) y el del DESTINO (el operativo).
El Builder resolvio contra su cwd, leyo `WOT-2026-022c COMPLETED` y reporto
`RUNTIME_NOT_BOOTSTRAPPED`. Su razonamiento fue CORRECTO; el prompt era ambiguo.
`AGENTS.md:142` ya decia "Nunca usar repo_motor/.agent/collaboration/ como operativo":
la NORMA existia, faltaba el MECANISMO.

POR QUE CRITERIO ESTRECHO Y NO "LINEA ACCIONABLE" (bucle L720, 5/5 lentes)
--------------------------------------------------------------------------
La v1 proponia clasificar "lineas accionables" (bloques de comando + menciones de
runtime). El bucle lo REFUTO por unanimidad, y el argumento decisivo se VERIFICO en el
fichero: la linea culpable esta en COLUMNA 0 -- es PROSA, no un bloque indentado. La
rama "bloques de comando" NO habria cazado el fallo que origino esta barrera. Solo lo
caza la rama de los cuatro ficheros de runtime, que ES el criterio estrecho.

EL FALSO POSITIVO QUE HAY QUE EVITAR (medido, no hipotetico)
------------------------------------------------------------
Una regla literal ("toda mencion lleva ruta") marcaria la CORRECCION ya aplicada. En el
mismo fichero hay 4 menciones LEGITIMAS sin ruta: un rotulo de bloque de evidencia, una
referencia al contrato, y dos lineas de prosa de DoD/STOP. De ahi los filtros
SINTACTICOS de abajo: reducen la heuristica, no la eliminan.

DENOMINADOR PUBLICADO SIEMPRE, tambien en fallo. Un `exit 0` con 0 prompts auditados es
universo vacio, no un verde: se reporta exit != 0 (fail-closed).

FRONTERA CON check_distribution_agnostic.py: aquel PROHIBE rutas absolutas, pero su
denominador es MANIFEST.distribute (lo que VIAJA a otros destinos). Este audita prompts
de arranque del DESTINO, que NO estan en ese manifiesto. Conjuntos DISJUNTOS: lo que
viaja debe ser agnostico; un arranque de un solo uso debe ser literal.

Before: `project_root` es una raiz de destino resoluble.
During: lee `<project_root>/.agent/planning/builder_prompt_*.md` (read-only) y aplica
    R1 (referencia operativa sin ruta absoluta) y R2 (placeholder sin expandir).
After: `(hallazgos, auditados)`. Nunca lanza por contenido; los errores de lectura se
    reportan como hallazgo propio, no se tragan.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# Los cuatro ficheros de runtime operativo: los que existen en DOS raices a la vez y
# por eso son ambiguos sin prefijo. La lista es CERRADA a proposito.
RUNTIME_FILES = ("work_plan.md", "STATE.md", "TURN.md", "execution_log.md")

# Un placeholder sin expandir: el prompt canonico es plantilla y DEBE llevarlos, pero
# una proyeccion de arranque con `{{...}}` no es un arranque (el Builder lo reporto).
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")

# Marca de ruta absoluta de destino. No se busca una ruta concreta de maquina (seria
# PII y no viajaria): basta con que la linea ancle la mencion a una raiz explicita.
ABSOLUTE_HINT_RE = re.compile(
    r"(?:[A-Za-z]:[\\/])|(?:<DESTINO_ROOT>[\\/])|(?:<destino>[\\/])", re.IGNORECASE
)

# Verbos que convierten una MENCION en una ORDEN DE LECTURA. Este es el discriminante,
# y es POSITIVO a proposito: se busca la orden, no se intenta enumerar la prosa.
#
# BARRIDO que lo fija (2026-09-10, sobre los 3 prompts vivos): una regla que marcaba toda
# mencion daba 13 hits, de los que solo 4 eran ordenes reales -- 9 falsos positivos (69%).
# Enumerar la prosa es inagotable; enumerar el imperativo es una lista corta y cerrada.
# Sin este filtro la barrera muere por ruido, que es como mueren las barreras.
_READ_VERBS = (
    "confirma",
    "verifica",
    "inspecc",
    "registra en",
    "lee ",
    "leer ",
    "consulta",
)


@dataclass(frozen=True)
class Finding:
    """Un hallazgo con su fichero, linea y motivo: sin esos tres no es accionable."""

    path: Path
    lineno: int
    rule: str
    line: str

    def render(self) -> str:
        return f"{self.path.name}:{self.lineno} [{self.rule}] {self.line.strip()[:110]}"


def _is_read_order(line: str) -> bool:
    """True si la linea ORDENA leer un fichero de runtime, no solo lo menciona.

    Discriminante POSITIVO (se busca el imperativo), no negativo (enumerar la prosa
    seria inagotable). Filtro SINTACTICO: casa verbos literales, no interpreta
    intencion.

    Medido sobre los 3 prompts vivos: marcar toda mencion daba 13 hits con 9 falsos
    positivos; exigir el verbo deja 4, que son las ordenes reales -- incluida la
    linea 40 pre-fix que detuvo el vuelo.
    """
    low = line.lower()
    return any(verb in low for verb in _READ_VERBS)


def scan_prompt(path: Path) -> list[Finding]:
    """Aplica R1 y R2 a un prompt. Nunca lanza: un fallo de lectura ES un hallazgo."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding(path, 0, "R0-unreadable", f"no se pudo leer: {exc}")]

    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if PLACEHOLDER_RE.search(line):
            findings.append(Finding(path, lineno, "R2-placeholder", line))
        if not any(name in line for name in RUNTIME_FILES):
            continue
        if not _is_read_order(line):
            continue
        if ABSOLUTE_HINT_RE.search(line):
            continue
        findings.append(Finding(path, lineno, "R1-ruta-ambigua", line))
    return findings


def audit(project_root: Path) -> tuple[list[Finding], list[Path]]:
    """Devuelve (hallazgos, prompts_auditados). El segundo ES el denominador."""
    planning = project_root / ".agent" / "planning"
    prompts = sorted(planning.glob("builder_prompt_*.md")) if planning.is_dir() else []
    findings: list[Finding] = []
    for prompt in prompts:
        findings.extend(scan_prompt(prompt))
    return findings, prompts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prompts de arranque: runtime con ruta absoluta, sin placeholders."
    )
    parser.add_argument("--project-root", required=True, help="raiz del repo_destino")
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    findings, prompts = audit(project_root)

    # El denominador se publica SIEMPRE, incluso en fallo: sin el no se distingue
    # "0 hallazgos sobre 3" de "0 hallazgos sobre 0".
    print(
        f"[launch-prompt-paths] {len(prompts)} prompt(s) auditado(s), "
        f"{len(findings)} hallazgo(s)"
    )

    if not prompts:
        print(
            "[launch-prompt-paths] ERROR: universo VACIO en "
            f"{project_root / '.agent' / 'planning'}. Un exit 0 aqui seria un verde "
            "vacuo (fail-closed).",
            file=sys.stderr,
        )
        return 1

    for finding in findings:
        print(f"  - {finding.render()}")
    if findings:
        print(
            "\nUn prompt de arranque manda leer runtime que existe en DOS raices. Sin "
            "ruta absoluta el Builder resuelve contra su cwd y lee el ticket ajeno del "
            "seed neutro (AGENTS.md:142). Escribe la ruta completa del destino.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
