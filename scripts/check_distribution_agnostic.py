#!/usr/bin/env python3
r"""Guard: lo que VIAJA no puede nombrar ESTA maquina (WOT-2026-025e / 024z / 025a).

El motor se distribuye a los destinos. Todo fichero versionado que forma parte de
lo distribuido (el denominador de este guard) debe ser AGNOSTICO de la instalacion
concreta: no puede llevar el nombre del workspace activo, el sufijo `_dev` de la
worktree de dogfooding, la raiz de perfiles de usuario ni el username de quien lo
edito. Un literal asi es una FUGA: viaja a cada destino y nombra una maquina que no
es la suya.

Por que este guard, y por que su denominador es EL PUNTO
--------------------------------------------------------
La norma ya estaba escrita (prompts/orchestrator_session_close_full_audit.md,
seccion 3.5: "denominador cerrado, expande skills/, publica el conteo, agujas").
Faltaba el MECANISMO. Y el mecanismo se juega en el DENOMINADOR:

  MANIFEST.distribute tiene 52 entradas no-comentario. 51 son fichero y 1 es un
  DIRECTORIO (`skills/`, que expande a 92 ficheros tracked). La regla ingenua "audita
  solo las entradas que son fichero" audita 51 = 36% y SALTA 92 EN SILENCIO. Ese
  salto silencioso es el defecto de familia 024c ("un guard sin denominador salta
  filas sin avisar"). Aqui NO se distingue fichero de directorio: cada entrada se
  pasa por `git ls-files -- <entrada>`, que expande el directorio sola. 52 -> 143.

FAIL-CLOSED (precedente: el parche de check_commit_worktree.py, 2026-07-14)
--------------------------------------------------------------------------
Si git no esta en el PATH, si `git ls-files` devuelve rc!=0, o si el denominador
sale VACIO -> stderr + exit 1. Un `git ls-files` que funciona sobre un repo con un
MANIFEST no vacio SIEMPRE nombra algo; un denominador vacio solo puede ser un fallo
de la consulta. Nunca exit 0 por ignorancia.

PUBLICA EL DENOMINADOR SIEMPRE (tambien en exit 1). "<N> entradas -> <M> ficheros
versionados auditados". Un probe que no publica su denominador no es una barrera:
no puedes distinguir "0 fugas sobre 143" de "0 fugas sobre 0".

La aguja username: derivada, NUNCA escrita en disco
---------------------------------------------------
El username de esta maquina no puede vivir en un YAML versionado (seria PII, la
regresion que WOT-2026-025a cerro). Se deriva con getpass.getuser() en runtime. Si
el usuario es generico (ci/root/runner/... o < 4 chars) la aguja se SALTA con un
aviso EXPLICITO ("SKIPPED: usuario generico"), nunca un verde silencioso. Env
AGNOSTIC_EXTRA_USERNAMES (coma-separado) anade usernames -> permite EJERCER la rama
activa en test sin depender de quien corra. El match usa \b...\b: un token corto
(p.ej. 'fdl', 3 chars) sin fronteras daria falsos rojos dentro de otras palabras.

ALLOWLIST con dueno y deteccion de STALE (patron guard_wiring_policy)
--------------------------------------------------------------------
Un hit se exime SOLO si (file, line, needle) coincide EXACTO con una entrada de la
allowlist. Si una entrada de allowlist YA NO produce hit (linea movida o borrada)
la exencion es STALE -> exit 1: una exencion no puede sobrevivir al fichero que la
justificaba.

Antes: se corre desde cualquier sitio; resuelve el motor desde la ruta del fichero.
Despues: exit 0 = ninguna aguja tiene hits sin eximir sobre el denominador entero.
         exit 1 = hay una fuga, el denominador no se construye, o la allowlist esta
         stale. Siempre publica el denominador.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


MOTOR_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = MOTOR_ROOT / "scripts" / "distribution_agnostic_policy.yaml"

# Usuarios genericos de CI/servicio: no identifican a una persona -> la aguja
# username no aplica (no es PII y un match seria ruido). Se compara en minusculas.
_GENERIC_USERS = frozenset(
    {"ci", "root", "runner", "administrator", "user", "admin", ""}
)


# --------------------------------------------------------------------- policy I/O
def load_policy(path: Path | None = None) -> dict:
    path = path or POLICY_PATH
    if not path.exists():
        return {"needles": {}, "allowlist": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    return {
        "needles": data.get("needles") or {},
        "allowlist": data.get("allowlist") or [],
    }


# ------------------------------------------------------------------ denominator
def _git_ls_files(root: Path, entry: str) -> tuple[int, list[str]]:
    """(returncode, matched tracked paths) for `git ls-files -- <entry>`. A
    directory entry (skills/) expands to every tracked file under it -- git does
    it, so we never special-case directories. shell=False, never $? after a pipe."""
    git = shutil.which("git")
    if git is None:
        return 1, []
    try:
        p = subprocess.run(  # noqa: S603 - git resuelto por shutil.which, args fijos
            [git, "ls-files", "--", entry],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, []
    files = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    return p.returncode, files


def manifest_entries(root: Path) -> list[str]:
    """Non-comment, non-blank lines of MANIFEST.distribute (52 today)."""
    manifest = root / "MANIFEST.distribute"
    if not manifest.exists():
        return []
    out: list[str] = []
    for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def build_denominator(root: Path) -> tuple[int, list[str], str | None]:
    """Return (n_entries, sorted tracked files, error_or_None).

    Fail-closed: git missing / rc!=0 / empty result -> error string, never a
    silently short denominator. Directories expand via git ls-files (skills/->92)."""
    entries = manifest_entries(root)
    if not entries:
        return 0, [], "MANIFEST.distribute is missing or has no non-comment entries"
    files: set[str] = set()
    for e in entries:
        rc, matched = _git_ls_files(root, e)
        if rc != 0:
            return (
                len(entries),
                [],
                f"`git ls-files -- {e}` failed (rc={rc}; is git on PATH and is "
                f"{root} a repo?)",
            )
        files.update(matched)
    if not files:
        return (
            len(entries),
            [],
            "denominator is EMPTY -- a working `git ls-files` over a non-empty "
            "MANIFEST always names something; refusing to audit 0 files as if green",
        )
    return len(entries), sorted(files), None


# --------------------------------------------------------------------- needles
def resolve_username_needle() -> tuple[re.Pattern | None, str]:
    """(compiled \\b<user>\\b regex | None, message). None + 'SKIPPED' for a generic
    user. AGNOSTIC_EXTRA_USERNAMES lets a test exercise the ACTIVE branch without
    depending on the machine's real user (and without writing it to disk)."""
    users: list[str] = []
    try:
        u = getpass.getuser()
    except Exception:
        u = ""
    if u and u.lower() not in _GENERIC_USERS and len(u) >= 4:
        users.append(u)
    extra = os.environ.get("AGNOSTIC_EXTRA_USERNAMES", "")
    for tok in extra.split(","):
        tok = tok.strip()
        if tok and tok.lower() not in _GENERIC_USERS and len(tok) >= 4:
            users.append(tok)
    users = sorted(set(users))
    if not users:
        return None, f"SKIPPED (usuario generico: {u!r})"
    pat = "|".join(re.escape(x) for x in users)
    return re.compile(r"\b(?:" + pat + r")\b"), f"activa para {users}"


def scan_needle(
    root: Path, files: list[str], rx: re.Pattern
) -> list[tuple[str, int, str]]:
    """(file, 1-based line, line text) for every match. Lectura robusta: bytes +
    decode(errors='replace') -- un fichero no-utf8 se audita degradado, NUNCA se
    salta en silencio (eso seria el defecto 024c otra vez)."""
    hits: list[tuple[str, int, str]] = []
    for f in files:
        try:
            txt = (root / f).read_bytes().decode("utf-8", errors="replace")
        except OSError:
            # Un fichero tracked que no se puede leer es en si mismo un problema:
            # lo reportamos como una "linea" para que no desaparezca en silencio.
            hits.append((f, 0, "<no se pudo leer el fichero>"))
            continue
        for i, line in enumerate(txt.splitlines(), 1):
            if rx.search(line):
                hits.append((f, i, line.strip()[:100]))
    return hits


# --------------------------------------------------------------------- allowlist
def _norm(p: str) -> str:
    return p.replace("\\", "/").strip()


def partition_hits(
    needle: str,
    hits: list[tuple[str, int, str]],
    allowlist: list[dict],
) -> tuple[list[tuple[str, int, str]], set[int]]:
    """Split hits into (not_exempt, indices of allowlist entries that fired).
    An entry exempts a hit iff (file, line, needle) match EXACTLY."""
    exempt_keys = {}
    for idx, entry in enumerate(allowlist):
        if entry.get("needle") != needle:
            continue
        key = (_norm(str(entry.get("file", ""))), int(entry.get("line", -1)))
        exempt_keys[key] = idx
    not_exempt: list[tuple[str, int, str]] = []
    fired: set[int] = set()
    for f, ln, text in hits:
        key = (_norm(f), ln)
        if key in exempt_keys:
            fired.add(exempt_keys[key])
        else:
            not_exempt.append((f, ln, text))
    return not_exempt, fired


def stale_allowlist(allowlist: list[dict], all_fired: set[int]) -> list[dict]:
    """Allowlist entries that never matched a hit -> STALE (line moved/deleted)."""
    return [e for i, e in enumerate(allowlist) if i not in all_fired]


# --------------------------------------------------------------------- audit
def audit(root: Path, policy: dict | None = None) -> tuple[int, list[str]]:
    """Return (exit_code, output_lines). Publishes the denominator on every path."""
    policy = policy or load_policy()
    needles = policy["needles"]
    allowlist = policy["allowlist"]
    out: list[str] = []

    n_entries, files, err = build_denominator(root)
    if err is not None:
        out.append(f"[dist-agnostic] ERROR: {err}")
        out.append(
            f"[dist-agnostic] {n_entries} entradas -> 0 ficheros versionados auditados "
            "(FAIL-CLOSED)"
        )
        return 1, out

    out.append(
        f"[dist-agnostic] {n_entries} entradas -> {len(files)} ficheros versionados "
        "auditados"
    )

    # username needle: resolved at runtime, never from the versioned policy.
    uname_rx, uname_msg = resolve_username_needle()

    all_fired: set[int] = set()
    total_unexempt = 0
    stale = False

    ordered = [*needles.items(), ("username", None)]
    for name, spec in ordered:
        if name == "username":
            if uname_rx is None:
                out.append(f"[dist-agnostic] aguja username: {uname_msg}")
                continue
            rx = uname_rx
        else:
            rx = re.compile(spec["pattern"])
        hits = scan_needle(root, files, rx)
        not_exempt, fired = partition_hits(name, hits, allowlist)
        all_fired |= fired
        total_unexempt += len(not_exempt)
        suffix = f" ({uname_msg})" if name == "username" else ""
        out.append(
            f"[dist-agnostic] aguja {name}: {len(not_exempt)} hits "
            f"({len(fired)} eximidos){suffix}"
        )
        for f, ln, text in not_exempt:
            out.append(f"      {f}:{ln}: {text}")

    stale_entries = stale_allowlist(allowlist, all_fired)
    if stale_entries:
        stale = True
        out.append("")
        out.append("[dist-agnostic] ERROR: allowlist STALE (no producen hit; linea")
        out.append(
            "  movida o borrada -- la exencion no puede sobrevivir a su fichero):"
        )
        out.extend(
            f"      {e.get('file')}:{e.get('line')} needle={e.get('needle')}"
            for e in stale_entries
        )

    if total_unexempt or stale:
        if total_unexempt:
            out.append("")
            out.append(
                "[dist-agnostic] ERROR: lo que viaja no puede nombrar esta maquina."
            )
            out.append(
                "  Des-hardcodea la fuga (habla del ROL, no del NOMBRE; precedente en"
            )
            out.append(
                "  prompts/manager_review.md), o si es una meta-mencion legitima"
            )
            out.append(
                "  declara la exencion en scripts/distribution_agnostic_policy.yaml."
            )
        return 1, out

    out.append(
        "[dist-agnostic] OK: ninguna aguja nombra esta maquina en lo distribuido."
    )
    return 0, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--motor-root", default=str(MOTOR_ROOT))
    args = ap.parse_args(argv)
    root = Path(args.motor_root).resolve()
    code, lines = audit(root)
    stream = sys.stderr if code else sys.stdout
    for ln in lines:
        print(ln, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
