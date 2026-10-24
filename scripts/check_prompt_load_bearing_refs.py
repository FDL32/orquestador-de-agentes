#!/usr/bin/env python3
r"""Guard: un prompt que viaja no declara normativo el planning del destino (WOT-2026-090p).

Los prompts de MANIFEST.distribute viajan a cada destino. Si uno dice que un diseno es
"load-bearing"/normativo y ese diseno solo existe en `.agent/planning/` de otro
destino (p.ej. el de dogfooding), la referencia no resuelve en ningun otro sitio y lo
que el prompt declara normativo es inalcanzable. `check_distribution_agnostic.py` no
lo ve: busca nombres de maquina, no ficheros citados.

Regla (unidad = parrafo, separado por linea en blanco, sin prefijos `>`)
-----------------------------------------------------------------------
Un parrafo FALLA si a la vez:
  1. cita el planning del destino, ausente del motor: `.agent/planning/` o
     "workspace planning". Los tokens con prefijo de destino (`DESTINO_ROOT/`,
     `<DESTINO>/`, `<DESTINO_ROOT>/`, `<repo_destino>`) se excluyen: apuntan al
     destino por contrato. Los artefactos de workspace (`STATE.md`, `work_plan.md`...)
     NO cuentan: existen en cada destino (medido: 15 falsos positivos al incluirlos).
  2. lleva un marcador normativo (load-bearing, normativ[oa], source_of_truth,
     binding, must read, obligado cumplimiento, referencia canonica, canonical
     reference). "obligatorio" NO es marcador: es prosa generica.
  3. NO lleva marcador de procedencia (procedencia, provenance, no normativ,
     not normative, "No hace falta leerlo").
La correccion es degradar la cita a procedencia no normativa (patron en
`prompts/doc_optimization.md`) o traer el contenido al motor.

LIMITES DECLARADOS (Review 2; el guard solo cubre lo que declara, no se arregla aqui):
  - La unidad es el PARRAFO: si el marcador normativo y la cita al planning caen en
    parrafos distintos (separados por linea en blanco), el guard NO los une y escapa.
  - El token de ruta es solo `.agent/planning/` o "workspace planning": una ruta
    `planning/x.md` sin `.agent/` escapa.
  - El vocabulario normativo es lexico (marcadores de arriba): un parrafo que declara
    autoridad con otras palabras escapa.

Denominador (misma tecnica que check_distribution_agnostic)
-----------------------------------------------------------
Entradas de MANIFEST.distribute expandidas con `git ls-files -- <entrada>` (un
directorio expande solo), UNION `EXTRA_SCOPE` (prompts cuyo SKILL viaja pero que no
estan en el manifest). Solo ficheros `.md`. Publica "N entradas -> M ficheros" siempre.
FAIL-CLOSED: git ausente, rc!=0 o denominador vacio -> exit 1.

Antes: se corre desde cualquier sitio; resuelve el motor desde la ruta del fichero.
Despues: exit 0 = ningun parrafo viola; exit 1 = hay hits (fichero:linea), o el
denominador no se construye.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent

# Prompts cuyo SKILL viaja pero que MANIFEST.distribute no lista.
EXTRA_SCOPE: tuple[str, ...] = ("prompts/orchestrator_autonomous_ticket_batch.md",)

# Deuda declarada y CERRADA: fichero -> ticket dueno. Un hit aqui es WARN (no cuenta
# para el exit code); si el fichero ya no tiene hits, el check FALLA para que la
# exencion no se fosilice.
KNOWN_DEBT: dict[str, str] = {
    "prompts/orchestrator_child_dispatch_multiticket_multibackend_unlimited.md": "WOT-2026-124a",
    "skills/orchestrate-child-dispatch-multiticket-multibackend-unlimited/SKILL.md": "WOT-2026-124a",
}

_DEST_TOKEN_RX = re.compile(
    r"(?:<DESTINO_ROOT>|<DESTINO>|DESTINO_ROOT|<repo_destino>)[^\s`]*"
)
_PLANNING_RX = re.compile(r"\.agent/planning/|workspace planning", re.I)
_NORMATIVE_RX = re.compile(
    r"load-bearing|normativ[oa]|source_of_truth|binding|must read"
    r"|obligado\s+cumplimiento|referencia\s+can[oó]nica|canonical\s+reference",
    re.I,
)
_PROVENANCE_RX = re.compile(
    r"procedencia|provenance|no normativ|not normative|No hace falta leerlo", re.I
)


def _git(root: Path, *args: str) -> tuple[int, list[str]]:
    """(rc, non-blank stdout lines) of a git call; (1, []) if git is unusable."""
    git = shutil.which("git")
    if git is None:
        return 1, []
    try:
        p = subprocess.run(  # noqa: S603 - git resuelto por shutil.which, args fijos
            [git, *args], capture_output=True, text=True, cwd=str(root), timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, []
    return p.returncode, [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def manifest_entries(root: Path) -> list[str]:
    """Non-comment, non-blank lines of MANIFEST.distribute (empty if missing)."""
    manifest = root / "MANIFEST.distribute"
    if not manifest.exists():
        return []
    lines = manifest.read_text(encoding="utf-8", errors="replace").splitlines()
    return [s for s in (ln.strip() for ln in lines) if s and not s.startswith("#")]


def build_denominator(root: Path) -> tuple[int, list[str], str | None]:
    """Return (n_entries, sorted tracked .md files, error_or_None).

    Before: root is a git repo with a MANIFEST.distribute.
    During: tracked-files listing per manifest entry, UNION EXTRA_SCOPE.
    After: fail-closed -> error string on missing manifest, git rc!=0 or empty set.
    """
    entries = manifest_entries(root)
    if not entries:
        return 0, [], "MANIFEST.distribute is missing or has no non-comment entries"
    files: set[str] = set()
    for e in [*entries, *EXTRA_SCOPE]:
        rc, matched = _git(root, "ls-files", "--", e)
        if rc != 0:
            return len(entries), [], f"`git ls-files -- {e}` failed (rc={rc})"
        files.update(matched)
    md = sorted(f for f in files if f.lower().endswith(".md"))
    if not md:
        return len(entries), [], "denominator is EMPTY; refusing to audit 0 files"
    return len(entries), md, None


def _paragraphs(text: str) -> list[list[tuple[int, str]]]:
    """Blank-line separated blocks of (line_no, text) with `>` prefixes stripped."""
    blocks: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"^\s*(?:>\s?)+", "", raw).strip()
        if not line:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append((i, line))
    if cur:
        blocks.append(cur)
    return blocks


def _planning_ref_line(lines: list[tuple[int, str]]) -> int | None:
    """Line number of the first planning-of-destino reference, else None."""
    for ln, line in lines:
        if _PLANNING_RX.search(_DEST_TOKEN_RX.sub("", line)):
            return ln
    return None


def find_violations(
    paths: list[Path], root: Path | None = None
) -> list[tuple[str, int, str]]:
    """Pure core: (file, line, text) for each violating paragraph in ``paths``.

    Before: ``paths`` are readable .md files.
    During: split into paragraphs, apply the 3-part rule (planning ref AND normative
        marker AND no provenance marker). No git access here.
    After: hits in input order; an unreadable file is reported at line 0, never
        skipped in silence.
    """
    hits: list[tuple[str, int, str]] = []
    for p in paths:
        label = p.relative_to(root).as_posix() if root else p.as_posix()
        try:
            text = p.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            hits.append((label, 0, "<no se pudo leer el fichero>"))
            continue
        for lines in _paragraphs(text):
            joined = " ".join(t for _n, t in lines)
            if not _NORMATIVE_RX.search(joined) or _PROVENANCE_RX.search(joined):
                continue
            ref_line = _planning_ref_line(lines)
            if ref_line is not None:
                hits.append((label, ref_line, joined[:100]))
    return hits


def apply_known_debt(
    hits: list[tuple[str, int, str]], known_debt: dict[str, str]
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]], list[str]]:
    """Split hits into (blocking, warned, settled_debt_files).

    Before: ``known_debt`` maps file -> owner ticket (closed, declared list).
    During: a hit in a KNOWN_DEBT file is WARN-only; any other hit blocks. A
        KNOWN_DEBT file with NO hit is "settled" (its exemption is now fossil).
    After: pure, no I/O; ``settled`` is sorted.
    """
    warned = [h for h in hits if h[0] in known_debt]
    blocking = [h for h in hits if h[0] not in known_debt]
    hit_files = {h[0] for h in hits}
    settled = sorted(f for f in known_debt if f not in hit_files)
    return blocking, warned, settled


def audit(
    root: Path, known_debt: dict[str, str] | None = None
) -> tuple[int, list[str]]:
    """Return (exit_code, output_lines); the denominator is published on every path.

    Before: ``root`` is a git repo; ``known_debt`` defaults to KNOWN_DEBT.
    During: denominator -> scan -> split hits by KNOWN_DEBT.
    After: exit 1 on a blocking hit, a settled KNOWN_DEBT file, or a denominator
        failure; WARN-only hits (owned debt) do not affect the exit code.
    """
    debt = KNOWN_DEBT if known_debt is None else known_debt
    n_entries, files, err = build_denominator(root)
    if err is not None:
        return 1, [
            f"[load-bearing-refs] ERROR: {err}",
            f"[load-bearing-refs] {n_entries} entradas -> 0 ficheros (FAIL-CLOSED)",
        ]
    out = [f"[load-bearing-refs] {n_entries} entradas -> {len(files)} ficheros"]
    hits = find_violations([root / f for f in files], root)
    blocking, warned, settled = apply_known_debt(hits, debt)
    out.extend(
        f"      WARN {f}:{ln}: deuda conocida, dueno {debt[f]}: {text}"
        for f, ln, text in warned
    )
    out.extend(f"      {f}:{ln}: {text}" for f, ln, text in blocking)
    out.extend(
        f"[load-bearing-refs] ERROR: deuda saldada: retira la exencion de {f} "
        f"({debt[f]}) de KNOWN_DEBT"
        for f in settled
    )
    if blocking:
        out.append(
            "[load-bearing-refs] ERROR: parrafo normativo cita planning del destino "
            "(ausente del motor). Degrada la cita a procedencia no normativa "
            "(patron: prompts/doc_optimization.md) o trae el contenido al motor."
        )
    if blocking or settled:
        return 1, out
    out.append(
        "[load-bearing-refs] OK: ninguna referencia normativa apunta al planning "
        "del destino."
    )
    return 0, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--motor-root", default=str(MOTOR_ROOT))
    args = ap.parse_args(argv)
    code, lines = audit(Path(args.motor_root).resolve())
    stream = sys.stderr if code else sys.stdout
    for ln in lines:
        print(ln, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
