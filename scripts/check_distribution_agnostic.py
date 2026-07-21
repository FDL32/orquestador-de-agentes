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
Un hit se exime SOLO si (file, needle, match) coincide EXACTO con una entrada de la
allowlist, donde `match` es el TEXTO de la linea eximida. Si una entrada YA NO
produce hit (linea borrada o editada) la exencion es STALE -> exit 1: una exencion
no puede sobrevivir a la linea que la justificaba.

El ancla es el texto y NO el numero de linea (WOT-2026-026r): el ordinal derivaba
solo -- una edicion aguas arriba desplazaba la linea, la exencion quedaba stale y
la suite se ponia roja por un cambio que no tocaba la fuga. El texto se mueve CON
su linea. Y no se trunca: comparar por un prefijo haria colisionar dos lineas
distintas, que es el matching fuzzy que este guard NO admite.

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
                # WOT-2026-026r: el hit conserva la linea ENTERA. El `[:100]` que
                # habia aqui era solo para IMPRIMIR; desde que el texto es tambien
                # el ANCLA de la allowlist, truncarlo hace COLISIONAR dos lineas
                # distintas que comparten los primeros 100 caracteres -- el
                # matching fuzzy que la ficha declara NON-GOAL, y con el una fuga
                # real quedaria eximida por la exencion de otra linea. El recorte
                # vive ahora en el punto de impresion (`_ellipsis`).
                hits.append((f, i, line.strip()))
    return hits


# --------------------------------------------------------------------- allowlist
def _norm(p: str) -> str:
    return p.replace("\\", "/").strip()


# El ancla de la allowlist es la linea ENTERA: solo se normaliza la indentacion,
# que no debe formar parte del contrato. NO se trunca -- el recorte a 100 chars es
# de PRESENTACION, y aplicarlo a la comparacion volveria FUZZY un matching que la
# ficha exige exacto (hallazgo F5 del review adversarial, medido con un probe de
# colision: dos lineas con el mismo prefijo de 100 chars se eximian entre si).
_DISPLAY_TRUNC = 100


def _norm_match(text: str) -> str:
    return text.strip()


def _ellipsis(text: str) -> str:
    """Recorta SOLO para imprimir; nunca para comparar (WOT-2026-026r, F5)."""
    return text if len(text) <= _DISPLAY_TRUNC else text[:_DISPLAY_TRUNC] + "..."


def partition_hits(
    needle: str,
    hits: list[tuple[str, int, str]],
    allowlist: list[dict],
) -> tuple[list[tuple[str, int, str]], set[int]]:
    """Split hits into (not_exempt, indices of allowlist entries that fired).

    An entry exempts a hit iff (file, needle, match) match EXACTLY, where ``match``
    is the TEXT of the exempted line -- never its ordinal (WOT-2026-026r).

    Anclar en `line:` obligaba a mantener a mano un numero que caduca SOLO: medido
    en la ficha, anadir un comentario aguas arriba en install_agent_system.py
    desplazo el codigo 12 lineas, la exencion quedo STALE y la suite se puso ROJA
    por un cambio que NO tocaba la fuga. El `needle` y el TEXTO ya identifican la
    meta-mencion sin depender de donde caiga en el fichero.

    La mitad que NO se pierde: el matching sigue siendo EXACTO, asi que borrar o
    editar la linea eximida deja la entrada sin disparar -> STALE -> FALLA. Se
    cambia el ancla, no se relaja el criterio (NON-GOAL explicito de la ficha).

    CARDINALIDAD (hallazgo del review adversarial). El ordinal era unico POR
    CONSTRUCCION: eximia una linea y solo una. El texto no lo es, asi que una
    entrada podria eximir N ocurrencias identicas y una fuga real quedaria tapada
    por la exencion de su gemela. Para no relajar nada, una entrada exime UNA
    ocurrencia por defecto; si la meta-mencion aparece legitimamente varias veces,
    se declara `count: N` EXPLICITAMENTE. Las ocurrencias que exceden el cupo se
    reportan como fuga, y un cupo que sobra deja la entrada STALE.
    """
    entries = [
        (idx, e, _norm(str(e.get("file", ""))), _norm_match(e.get("match", "")))
        for idx, e in enumerate(allowlist)
        if e.get("needle") == needle
    ]
    remaining: dict[int, int] = {
        idx: max(1, int(e.get("count", 1) or 1)) for idx, e, _f, _m in entries
    }
    by_key: dict[tuple[str, str], int] = {
        (f, mtext): idx for idx, _e, f, mtext in entries
    }

    not_exempt: list[tuple[str, int, str]] = []
    fired: set[int] = set()
    for f, ln, text in hits:
        idx = by_key.get((_norm(f), _norm_match(text)))
        if idx is not None and remaining.get(idx, 0) > 0:
            remaining[idx] -= 1
            fired.add(idx)
        else:
            # sin entrada, o la entrada ya agoto su cupo declarado
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
            out.append(f"      {f}:{ln}: {_ellipsis(text)}")

    stale_entries = stale_allowlist(allowlist, all_fired)
    if stale_entries:
        stale = True
        out.append("")
        out.append("[dist-agnostic] ERROR: allowlist STALE (no producen hit; la linea")
        out.append(
            "  eximida se borro o cambio -- la exencion no sobrevive a su justificacion):"
        )
        out.extend(
            f"      {e.get('file')} needle={e.get('needle')} "
            f"match={_ellipsis(str(e.get('match', '')))!r}"
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
