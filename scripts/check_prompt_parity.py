#!/usr/bin/env python3
r"""Guard: contratos normativos deben coincidir entre checkout canonico y worktree.

EL FALLO QUE CIERRA (medido 2026-09-25, WOT-2026-076a)
-------------------------------------------------------
La topologia declara dos copias del mismo repo_motor: un checkout canonico de
solo lectura (`orquestador_de_agentes`) y un worktree activo donde se commitea
(`orquestador_de_agentes_dev`). Ambos comparten `.git`, pero nada los mantiene
sincronizados: un commit nuevo en el worktree no se propaga al canonico salvo
`git pull`/`checkout` explicito alli.

Una sesion redacto un prompt de arranque de Builder leyendo
`orchestrator_launch_builder.md` desde el checkout canonico, que estaba
PARADO un commit atras del worktree donde el Builder realmente ejecuta. El
commit que faltaba (`4e15446`, WOT-2026-039m) cambiaba la secuencia de cuando
se corre la suite canonica. El prompt resultante cito la secuencia VIEJA; el
Builder la siguio al pie de la letra (correctamente, desde su punto de vista)
y corrio la suite fuera de la secuencia vigente. La norma M4 ("leelo ENTERO
antes de redactar contra el") no cazo el fallo porque SI se leyo el fichero
entero -- se leyo la copia equivocada.

Bucle adversarial de 4 lentes (claude, codex, qwen3.6, gemma4) sobre este
incidente convergio: WARN es insuficiente para contratos normativos de
ejecucion. La divergencia de ficheros normativos es corrupcion de flujo, no
un detalle cosmetico -- debe FALLAR (exit 1), no solo avisar.

QUE AUDITA Y QUE NO
--------------------
Este guard compara CONTENIDO (hash SHA-256), no solo HEAD del repo: dos
worktrees pueden tener HEADs distintos con el mismo fichero (si el commit que
los separa no lo toco), y ese caso NO es un hallazgo real -- el contrato que
importa es identico. Comparar por HEAD del repo daria falsos positivos en
cualquier divergencia de commits ajena a estos ficheros.

Universo CERRADO: `NORMATIVE_PROMPTS`, la lista de contratos que
`orchestrator_prepare_and_launch_ticket.md` y AGENTS.md citan como fuente de
verdad para un arranque de Builder/Manager. Ampliar la clase de "contrato
normativo" es una decision de producto, no algo que este guard infiera solo.

Before: dos raices de repo_motor (`--canonical-root`, `--worktree-root`),
    ambas checkouts del mismo repositorio git.
During: para cada fichero en `NORMATIVE_PROMPTS`, lee su contenido en ambas
    raices y calcula SHA-256. No ejecuta git; compara los ficheros tal como
    estan en disco, que es lo que un prompt de arranque realmente lee.
After: devuelve (hallazgos, auditados). Un hallazgo es un mismatch de hash
    en un fichero presente en ambas raices, o una ausencia asimetrica. Un
    fichero identico en ambas raices no es un hallazgo aunque el HEAD del
    repo difiera en otros commits.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path


# Universo cerrado: los contratos que un arranque de Builder/Manager cita como
# fuente de verdad (ver `orchestrator_prepare_and_launch_ticket.md` Paso 2 y
# AGENTS.md "Prompt/contrato citado => LEELO ENTERO"). Ampliar esta lista es
# una decision de producto: un fichero fuera de ella no se audita.
NORMATIVE_PROMPTS = (
    "prompts/orchestrator_launch_builder.md",
    "prompts/manager_review.md",
    "prompts/orchestrator_prepare_and_launch_ticket.md",
)


@dataclass(frozen=True)
class Finding:
    """Un hallazgo de paridad: fichero, motivo, y ambos hashes para diagnostico."""

    rel_path: str
    rule: str
    detail: str

    def render(self) -> str:
        return f"{self.rel_path} [{self.rule}] {self.detail}"


def _sha256_of(path: Path) -> str | None:
    """Before: path puede no existir. During: lee bytes crudos. After: hash o None."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def audit(canonical_root: Path, worktree_root: Path) -> tuple[list[Finding], list[str]]:
    """Compara cada contrato normativo entre las dos raices.

    Before: ambas raices son checkouts del mismo repo_motor.
    During: por cada ruta en NORMATIVE_PROMPTS, calcula el hash en ambos
        lados. Ausencia en un solo lado es un hallazgo (R2); hash distinto
        con ambos presentes es un hallazgo (R1).
    After: (hallazgos, rutas_auditadas). El segundo es el denominador
        publicado siempre, incluso en fallo.
    """
    findings: list[Finding] = []
    audited: list[str] = []

    for rel in NORMATIVE_PROMPTS:
        canonical_path = canonical_root / rel
        worktree_path = worktree_root / rel
        audited.append(rel)

        canonical_hash = _sha256_of(canonical_path)
        worktree_hash = _sha256_of(worktree_path)

        if canonical_hash is None and worktree_hash is None:
            findings.append(
                Finding(rel, "R3-ausente-en-ambos", "no existe en ninguna raiz")
            )
            continue
        if canonical_hash is None:
            findings.append(
                Finding(
                    rel,
                    "R2-ausente-canonico",
                    "existe en el worktree pero no en el checkout canonico",
                )
            )
            continue
        if worktree_hash is None:
            findings.append(
                Finding(
                    rel,
                    "R2-ausente-worktree",
                    "existe en el checkout canonico pero no en el worktree",
                )
            )
            continue
        if canonical_hash != worktree_hash:
            findings.append(
                Finding(
                    rel,
                    "R1-contenido-diverge",
                    f"canonico={canonical_hash[:12]} worktree={worktree_hash[:12]}",
                )
            )

    return findings, audited


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Contratos normativos deben ser byte-identicos entre el checkout "
            "canonico de solo lectura y el worktree activo de ejecucion."
        )
    )
    parser.add_argument(
        "--canonical-root",
        required=True,
        help="raiz del checkout canonico (solo lectura)",
    )
    parser.add_argument(
        "--worktree-root",
        required=True,
        help="raiz del worktree activo (donde se commitea)",
    )
    args = parser.parse_args(argv)

    canonical_root = Path(args.canonical_root).resolve()
    worktree_root = Path(args.worktree_root).resolve()

    findings, audited = audit(canonical_root, worktree_root)

    # Denominador publicado siempre: un exit 0 con 0 auditados seria un verde
    # vacuo (universo cerrado, pero declarado, no asumido).
    print(
        f"[prompt-parity] {len(audited)} contrato(s) auditado(s), "
        f"{len(findings)} hallazgo(s)"
    )

    if findings:
        for finding in findings:
            print(f"  - {finding.render()}", file=sys.stderr)
        print(
            "\nUn contrato normativo diverge entre el checkout canonico y el "
            "worktree de ejecucion. Un prompt de arranque redactado desde la "
            "copia equivocada cita una secuencia obsoleta sin que nadie lo "
            "note (medido: WOT-2026-076a, WOT-2026-039m no propagado al "
            "canonico). Sincroniza el checkout canonico "
            f"({canonical_root}) con el worktree ({worktree_root}) antes de "
            "redactar un prompt de arranque contra estos contratos.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
