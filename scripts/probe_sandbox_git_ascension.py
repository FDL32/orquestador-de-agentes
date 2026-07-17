#!/usr/bin/env python3
"""Probe determinista del ascenso de git desde un fixture roto (WOT-2026-021k).

EL DANO QUE MIDE
----------------
Un test que monta un fixture git DENTRO del arbol del repo y deja su `.git`
incompleto hace que `git rev-parse` ASCIENDA al repo padre: `symbolic-ref`
devuelve la rama del PADRE y check_worktree_topology responde **rc=0**
("topologia correcta") para una topologia que NO es la suya. Es un FALSO-VERDE
SILENCIOSO: un guard que APRUEBA lo que no puede verificar.

Esto NO depende del azar (a diferencia del flaky historico de WOT-2026-021g, que
ya no se dispara desde que WOT-2026-020p apago su disparador). Se reproduce a
voluntad, y por eso sirve como Premise Re-check.

LAS 4 CONDICIONES NECESARIAS Y SUFICIENTES
------------------------------------------
1. el fixture cuelga DENTRO del arbol de un repo padre cuya worktree en `main`
   tiene basename acabado en `_dev`  (un padre SINTETICO basta);
2. su `.git` esta INCOMPLETO (basta borrar `.git/HEAD`) -> git ASCIENDE;
3. el workspace del fixture declara un link con `ticket_prefix: "WOT"`, para que
   Verification B RESUELVA y no corte antes. SIN ESTO EL PROBE MIENTE: devuelve
   rc=2 y ENMASCARA el rc=0 que hay detras;
4. sin GIT_CEILING_DIRECTORIES en un ANCESTRO ESTRICTO.

LA REGLA DEL CEILING (verificada; es facil de entender al reves)
---------------------------------------------------------------
    ceiling en EL DIRECTORIO QUE GIT ESCANEA  -> ASCIENDE (NO protege)
    ceiling en CUALQUIER ANCESTRO ESTRICTO    -> CORTA    (protege)

Los 2 tests del motor que hoy llevan barrera ponen el ceiling en `tmp_path` y
prueban `tmp_path/<algo>`: ancestro estricto -> SI PROTEGEN. (Una version previa
de este probe los llamo "placebos"; era FALSO, y nacio de etiquetar como
"sandbox" un ceiling puesto en el propio dir escaneado, que no es lo que hacen.)

FAIL-CLOSED (rc=2) ES EL VEREDICTO CORRECTO, NO UN FALLO: con un `.git` corrupto
la topologia NO ES DETERMINABLE. El objetivo del ticket es eliminar el rc=0, no
alcanzar un rc=1.

Uso:
    python scripts/probe_sandbox_git_ascension.py
    exit 0 = el probe corrio (mira la salida para el veredicto)

No muta el repo: todo ocurre bajo C:\\tmp (ruta CORTA obligatoria -- una ruta
profunda hace que git falle con "Filename too long").
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Ruta CORTA a proposito: un arbol profundo hace que `git init` muera con
# "Filename too long" al escribir los hooks de ejemplo.
WORK_ROOT = Path(tempfile.gettempdir()).drive + "\\tmp\\probe_git_ascension"


def _force_rmtree(path: Path) -> None:
    """rmtree que SI borra en Windows: git deja ficheros read-only dentro de
    .git y shutil.rmtree los rechaza (WinError 5). Con ignore_errors el arbol
    queda a medias y el siguiente mkdir falla con WinError 183."""

    def _onerror(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if path.exists():
        shutil.rmtree(path, onerror=_onerror)


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        [shutil.which("git") or "git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _build_parent(root: Path) -> tuple[Path, Path]:
    """Topologia REAL del motor: primario detached + worktree `_dev` en `main`."""
    motor = root / "motor"
    motor.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=motor)
    _git("config", "user.email", "probe@example.com", cwd=motor)
    _git("config", "user.name", "Probe", cwd=motor)
    (motor / "README.md").write_text("probe\n", encoding="utf-8")
    _git("add", "-A", cwd=motor)
    _git("commit", "-m", "base", cwd=motor)
    # git rechaza la misma rama en 2 worktrees: hay que detachar el primario ANTES
    _git("checkout", "--detach", "main", cwd=motor)
    dev = root / "motor_dev"
    _git("worktree", "add", str(dev), "main", cwd=motor)
    return motor, dev


def _build_fixture(dev_tree: Path, damage: str) -> Path:
    """Fixture git DENTRO del arbol del padre, con el .git danado (CONDICION 1+2)."""
    fixture = dev_tree / "tests" / "sandbox" / f"probe_{damage}"
    fixture.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=fixture)
    if damage == "delete_HEAD":
        (fixture / ".git" / "HEAD").unlink(missing_ok=True)
    elif damage == "delete_git":
        _force_rmtree(fixture / ".git")
    return fixture


def _build_workspace(root: Path, motor: Path) -> Path:
    """CONDICION 3. Sin el link WOT, resolve_prefix devuelve None, Verification B
    corta con rc=2 y ENMASCARA el rc=0 que hay detras."""
    ws = root / "orquestador_de_agentes_workspace"
    cfg = ws / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "motor_destination_link.json").write_text(
        json.dumps(
            {
                "motor_root": str(motor),
                "destination_root": str(ws),
                "motor_version": "v9.17.1",
                "destination_id": "orquestador_de_agentes_workspace",
                "ticket_prefix": "WOT",
            }
        ),
        encoding="utf-8",
    )
    return ws


def probe(damage: str, ceiling: str) -> int:
    """ceiling: 'none' | 'scanned_dir' (NO protege) | 'strict_ancestor' (protege)."""
    case_root = Path(WORK_ROOT) / f"{damage}_{ceiling}"
    _force_rmtree(case_root)
    motor, dev = _build_parent(case_root)
    fixture = _build_fixture(dev, damage)
    workspace = _build_workspace(case_root, motor)

    key = "GIT_CEILING_DIRECTORIES"
    previous = os.environ.get(key)
    if ceiling == "scanned_dir":
        os.environ[key] = str(fixture)  # el dir que git escanea -> NO corta
    elif ceiling == "strict_ancestor":
        os.environ[key] = str(fixture.parent)  # ancestro estricto -> SI corta
    else:
        os.environ.pop(key, None)
    try:
        for module in ("prefix_resolver", "check_worktree_topology"):
            sys.modules.pop(module, None)
        import check_worktree_topology as cwt

        rc, message = cwt.check_topology("WOT-2026-021k", fixture, motor, workspace)
        note = ""
        if rc == 0:
            note = "  <-- FALSO-VERDE: aprueba una topologia que no es la suya"
        elif rc == 2:
            note = "  (fail-closed: 'no determinable' = CORRECTO)"
        print(f"  damage={damage:12} ceiling={ceiling:16} -> rc={rc}{note}")
        if rc == 0:
            print(f"      msg: {message}")
        return rc
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
        _force_rmtree(case_root)


def main() -> int:
    print("=== PROBE: ascenso de git desde un fixture roto (WOT-2026-021k) ===")
    print("El fixture NO es la worktree _dev -> el guard NUNCA deberia aprobarlo.")
    print("  rc=0 -> git ASCENDIO al padre y el guard APROBO   (EL DANO)")
    print("  rc=2 -> fail-closed, 'no determinable'            (CORRECTO)")
    print()
    false_greens = 0
    for damage in ("none", "delete_HEAD", "delete_git"):
        for ceiling in ("none", "scanned_dir", "strict_ancestor"):
            if probe(damage, ceiling) == 0:
                false_greens += 1
    _force_rmtree(Path(WORK_ROOT))
    print()
    if false_greens:
        print(f"PREMISA VIVA: {false_greens} falso(s)-verde(s) (rc=0).")
        print()
        print("Lee la columna ceiling: 'scanned_dir' NO corta el ascenso; solo")
        print("'strict_ancestor' protege. Un fixture autouse global DEBE poner el")
        print("ceiling en un ANCESTRO ESTRICTO del tmp_path de cada test.")
        print()
        print("ESTADO (WOT-2026-023p): el fixture autouse global de tests/conftest.py")
        print("YA lo cumple -- pone el ceiling en tmp_path.PARENT, que es ancestro")
        print("ESTRICTO de tmp_path, de modo que corta incluso con cwd == tmp_path.")
        print("Este probe CONFIRMA el codigo; antes de 023p lo contradecia (el")
        print("fixture ponia el ceiling EN tmp_path == dir escaneado -> ignorado).")
        print()
        print("Y OJO: ni el ancestro estricto devuelve rc=1 -- devuelve rc=2. Eso NO")
        print("es un fallo: con un .git corrupto la topologia NO es determinable, y")
        print("fail-closed es el veredicto honesto. El objetivo es MATAR el rc=0.")
    else:
        print("PREMISA MUERTA: 0 falsos-verdes -> REENCUADRAR antes de tocar nada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
