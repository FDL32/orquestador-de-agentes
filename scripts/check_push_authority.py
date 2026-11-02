#!/usr/bin/env python3
"""WOT-2026-040z / 152k: autoridad de sesion cableada en el camino de push.

El incidente (2026-07-25): una sesion de DISENO pusheo ac984f5..22fae69 a
origin/main porque nada en el codigo conoce el tipo de sesion -- la accion
menos reversible del sistema era la unica sin control de autoridad. Este guard
BLOQUEA el push a main cuando la sesion esta DECLARADA como `diseno` y no se
ha dejado rastro de escape.

Declaracion (decision (b) de 040z): el comando de bootstrap recibe
`--session-type diseno|desarrollo|orquestacion` EXPLICITO y escribe
`.agent/runtime/session/session_type.json` {"tipo", "declared_at",
"declared_by"}. Sin el flag NO se escribe fichero y este guard da WARN
(sesiones legacy) -- nunca adivina el tipo.

Escape (decision (a) de 040z): NO hay flag. El escape es la variable de entorno
DESIGN_PUSH_REASON con motivo NO vacio: el guard registra la linea en
.agent/runtime/session/design_push_log.jsonl (timestamp, motivo, refs) y deja
pasar el push. La via alternativa es REDECLARAR el tipo.

POR QUE EXISTE EL HOOK NATIVO (152k, blocker de 040z-r1). pre-commit NO reenvia
el stdin de git al hook (`stdin_len` medido 0) y solo expone al entorno UNA ref:
la primera linea con remote existente (`_pre_push_ns`). Asi `git push origin
feature-x main` y `git push origin --all` pasaban con PRE_COMMIT_REMOTE_BRANCH=
refs/heads/feature-x y empujaban main. Ademas, pre-commit NO ejecuta los hooks
cuando no hay commits que comprobar (borrado `:main`, ref nueva sobre commits
ya remotos). La unica fuente completa de refs es un hook NATIVO. Forma:

1. `pre-push.legacy` (mecanismo de pre-commit: `_run_legacy` le pasa el stdin
   entero y OR-ea su rc), instalado con `--install-native-hook`. Es un shim
   minimo sin imports del repo que ejecuta `scripts/check_push_authority.py
   --native <remote> <url>` con el stdin de git. Si el repo no trae este script
   (checkout antiguo) el shim sale 0 (legacy).
2. Modo `--native`: parsea TODAS las lineas, evalua (misma logica que abajo,
   con el escape registrado) y deja un MANIFIESTO atomico en
   `<git-common-dir>/push_authority/` con las refs y el veredicto. Si no puede
   escribirlo sale 2 y el push FALLA.
3. Modo hook de pre-commit (sin flags, el cableado de .pre-commit-config.yaml):
   CONSUME el manifiesto de ESTE push (mismo remote name/url, fresco, con la
   sha PRE_COMMIT_TO_REF) y borra lo consumido. FAIL-CLOSED: si la sesion es
   `diseno` (o su declaracion es invalida) y no hay manifiesto, el push se
   bloquea aunque la ref visible sea una rama feature, con la instruccion
   exacta de instalacion (modo B degradado: solo DESIGN_PUSH_REASON desbloquea).
   Sesiones desarrollo/orquestacion y sin declaracion NO cambian (PASS/WARN).

Limitaciones declaradas:
- `git push --no-verify` salta todo hook cliente: la barrera dura es el
  ruleset de main en origin (AGENTS.md).
- El hook nativo es estado LOCAL de `.git/hooks` (no versionado): hay que
  ejecutar `--install-native-hook` una vez por repo (comun a sus worktrees).
  Sin el, un push que pre-commit no ejecuta (borrado de main, ref nueva sobre
  commits ya remotos) NO pasa por ningun guard; con pre-commit si hay hook.
- Depende de la mecanica `.legacy` de pre-commit (pin 4.5.1 en pyproject).
- El fichero de sesion es POR CHECKOUT; un session_type.json viejo en una
  worktree reutilizada puede bloquear a una sesion nueva (el mensaje dice como
  redeclarar). Sesion sin declaracion = WARN, pasa (decision (c) de 040z).

Autoridad vs infraestructura: la restriccion de AUTORIDAD (bloquear main)
depende del tipo de sesion y solo muerde a diseno/invalida; el fallo de
INFRAESTRUCTURA (rc 2: manifiesto no escribible, git-common-dir irresoluble) hace
FALLAR el push de TODAS las sesiones, tambien desarrollo/orquestacion. Un
session_type.json que existe pero esta corrupto es declaracion INVALIDA
(fail-closed), no legacy: legacy es solo el fichero ausente.

Before: cwd o --project-root es la raiz del repo empujado. During: lee la
declaracion; solo si es diseno/invalida resuelve las refs (inyectadas, o del
manifiesto) y las compara por IGUALDAD EXACTA con `refs/heads/main`. After:
0 = autorizado/legacy/no-main; 1 = bloqueado; 2 = error de infraestructura
(incluido no poder escribir el manifiesto). Nunca determina el tipo por si solo.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


SESSION_TYPE_RELPATH = Path(".agent") / "runtime" / "session" / "session_type.json"
PUSH_LOG_RELPATH = Path(".agent") / "runtime" / "session" / "design_push_log.jsonl"
VALID_TYPES = ("diseno", "desarrollo", "orquestacion")
MAIN_REF = "refs/heads/main"
MANIFEST_DIRNAME = "push_authority"
MANIFEST_MAX_AGE_S = 120.0
NATIVE_SENTINEL = "WOT-2026-152k native pre-push shim"
INSTALL_COMMAND = "python scripts/check_push_authority.py --install-native-hook"

NATIVE_SHIM = f"""#!/usr/bin/env python
# {NATIVE_SENTINEL} (instalado por scripts/check_push_authority.py)
import os
import subprocess
import sys

script = os.path.join("scripts", "check_push_authority.py")
if not os.path.isfile(script):
    sys.exit(0)
sys.exit(subprocess.run([sys.executable, script, "--native", *sys.argv[1:]]).returncode)
"""


class PushRefsError(ValueError):
    """Las lineas de push no se pudieron interpretar (se trata como no resuelto)."""


def parse_push_lines(raw: str) -> list[dict[str, str]]:
    """Parsea el stdin de un hook pre-push de git.

    Before: raw trae lineas `<local_ref> <local_sha> <remote_ref> <remote_sha>`
        (una por ref empujada). El borrado `:main` llega con 4 campos
        (`(delete) <ceros> refs/heads/main <sha>`) y se evalua como cualquier
        otra linea; NO es una linea malformada. During: una entrada por linea
        no vacia; una linea sin exactamente 4 campos no es interpretable.
        After: lista de dicts; PushRefsError si alguna linea es malformada
        (refs=None aguas arriba => fail-closed para diseno/invalida).
    """
    lines: list[dict[str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 4:
            raise PushRefsError(f"linea de push no interpretable: {line!r}")
        lines.append(
            {
                "local_ref": parts[0],
                "local_sha": parts[1],
                "remote_ref": parts[2],
                "remote_sha": parts[3],
            }
        )
    return lines


def _is_main_target(remote_refs: list[str]) -> bool:
    """True si alguna ref remota del push es EXACTAMENTE refs/heads/main.

    Igualdad exacta: endswith('/main') casaba refs/heads/feature/main y
    refs/tags/main (ronda 1 de 040z). Incluye borrados (`:main`).
    """
    return any(ref == MAIN_REF for ref in remote_refs)


def _read_declaration(project_root: Path) -> dict | None:
    """Lee session_type.json distinguiendo AUSENTE de EXISTENTE-pero-corrupto.

    Before: project_root es la raiz del repo empujado. During: AUSENTE = no hay
        nada en la ruta (lstat da FileNotFoundError) -> None (sesion legacy sin
        declarar -> WARN, decision (c) de 040z). Cualquier otra cosa que EXISTA
        y no sea un fichero regular legible con un objeto JSON (directorio,
        symlink roto, truncado, `[]`, vacio, error de E/S) devuelve `{}`: tipo
        '' que NO es valido, asi que cae en la ruta fail-closed de declaracion
        INVALIDA (152k rondas 2 y 3). After: dict (posiblemente `{}`) o None
        SOLO si esta ausente.
    """
    path = project_root / SESSION_TYPE_RELPATH
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return {}
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _append_escape_log(project_root: Path, reason: str, remote_refs: list[str]) -> None:
    """Deja rastro auditable del escape (decision (a) de 040z)."""
    log_path = project_root / PUSH_LOG_RELPATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "remote_refs": remote_refs,
        "mechanism": "DESIGN_PUSH_REASON",
    }
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True) + "\n")


def git_common_dir(project_root: Path) -> Path | None:
    """Directorio .git comun (compartido por los worktrees); None si falla."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],  # noqa: S607
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    path = Path(out.stdout.strip())
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def write_manifest(
    common_dir: Path,
    remote_name: str,
    remote_url: str,
    lines: list[dict[str, str]],
    verdict: int,
) -> Path:
    """Escribe el manifiesto de ESTE push de forma atomica (temporal + rename).

    Before: common_dir existe. During: JSON a un temporal en el mismo
        directorio y os.replace. After: ruta del manifiesto; OSError si no se
        pudo (el llamador FALLA el push).
    """
    directory = common_dir / MANIFEST_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    stamp = f"{time.time_ns()}-{os.getpid()}"
    final = directory / f"{stamp}.json"
    tmp = directory / f".{stamp}.tmp"
    payload = {
        "ts": time.time(),
        "remote_name": remote_name,
        "remote_url": remote_url,
        "lines": lines,
        "verdict": verdict,
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    os.replace(tmp, final)
    return final


def _unlink_quietly(path: Path) -> None:
    """Borra un manifiesto; un fallo no debe tumbar la decision del guard."""
    with contextlib.suppress(OSError):
        path.unlink()


def consume_manifests(
    common_dir: Path, env: dict[str, str], now: float | None = None
) -> list[dict]:
    """Manifiestos frescos que corresponden a ESTE push; borra lo consumido.

    Before: env trae las PRE_COMMIT_REMOTE_NAME/URL y PRE_COMMIT_TO_REF del
        push actual (FROM_REF NO se exige: en una rama nueva pre-commit lo calcula). During: descarta (y borra, en try) los caducados;
        acepta solo los del mismo remote name+url y que contengan una linea con
        la sha TO_REF. After: lista (posiblemente vacia).
    """
    current = time.time() if now is None else now
    directory = common_dir / MANIFEST_DIRNAME
    if not directory.is_dir():
        return []
    remote_name = env.get("PRE_COMMIT_REMOTE_NAME", "")
    remote_url = env.get("PRE_COMMIT_REMOTE_URL", "")
    to_ref = env.get("PRE_COMMIT_TO_REF", "")
    found: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        age = current - float(data.get("ts", 0) or 0)
        if not 0 <= age <= MANIFEST_MAX_AGE_S:
            _unlink_quietly(path)
            continue
        if not remote_name or data.get("remote_name") != remote_name:
            continue
        if data.get("remote_url") != remote_url:
            continue
        lines = data.get("lines")
        if not isinstance(lines, list):
            continue
        if to_ref and not any(
            isinstance(ln, dict) and ln.get("local_sha") == to_ref for ln in lines
        ):
            continue
        found.append(data)
        _unlink_quietly(path)
    return found


def _fail_unresolved(label: str) -> None:
    print(
        "[push-authority] FAIL: sesion 'diseno' y NO se pueden determinar las "
        f"refs del push ({label}); fail-closed. Instala el hook nativo UNA vez "
        f"en este repo: {INSTALL_COMMAND}\n"
        "  (alternativa puntual, queda en design_push_log.jsonl: "
        'DESIGN_PUSH_REASON="<motivo>" git push ...)',
        file=sys.stderr,
    )


def evaluate(
    project_root: Path,
    remote_refs: list[str] | None,
    environment: dict[str, str],
    *,
    log_escape: bool = True,
) -> int:
    """Decision del guard (compartida por el modo nativo y el hook de pre-commit).

    Before: remote_refs = TODAS las refs remotas del push, o None si no se
        pudieron determinar. During: lee la declaracion; sin declaracion WARN;
        tipo valido distinto de diseno PASS; diseno/invalido resuelve main
        (None = fail-closed). After: 0/1 segun el docstring del modulo.
    """
    declaration = _read_declaration(project_root)
    if declaration is None:
        # Decision (c) de 040z: sesion legacy sin declaracion -> WARN, no bloquea.
        print(
            "[push-authority] WARN: push SIN declaracion de tipo de sesion "
            "(legacy). Declara con: python scripts/destination_context.py "
            "--bootstrap --project-root <raiz> --session-type "
            "desarrollo|orquestacion|diseno"
        )
        return 0

    tipo = str(declaration.get("tipo", ""))
    if tipo in VALID_TYPES and tipo != "diseno":
        print(
            f"[push-authority] PASS: sesion declarada '{tipo}' "
            "(autoridad de desarrollo/orquestacion)"
        )
        return 0

    reason = environment.get("DESIGN_PUSH_REASON", "").strip()
    if remote_refs is None:
        # FAIL-CLOSED (152k): diseno/invalida y refs desconocidas.
        if tipo == "diseno" and reason:
            if log_escape:
                _append_escape_log(project_root, reason, [])
            print(
                "[push-authority] ESCAPE registrado: refs desconocidas, sesion "
                f"'diseno' con DESIGN_PUSH_REASON='{reason}' (design_push_log.jsonl)"
            )
            return 0
        _fail_unresolved(f"tipo={tipo!r}")
        return 1

    if not _is_main_target(remote_refs):
        print(
            "[push-authority] PASS: el push no va a main "
            f"(refs: {', '.join(remote_refs) or 'ninguna'})"
        )
        return 0

    # WOT-2026-040z ronda 2: tipo ausente o DESCONOCIDO no es autoridad.
    if tipo not in VALID_TYPES:
        print(
            "[push-authority] FAIL: declaracion INVALIDA "
            f"(tipo={tipo!r}, valores validos: {', '.join(VALID_TYPES)}). "
            "Redeclara: python scripts/destination_context.py --bootstrap "
            "--project-root <raiz> --session-type desarrollo",
            file=sys.stderr,
        )
        return 1

    if reason:
        if log_escape:
            _append_escape_log(project_root, reason, remote_refs)
        print(
            "[push-authority] ESCAPE registrado: sesion 'diseno' pusha a "
            f"main con DESIGN_PUSH_REASON='{reason}' "
            "(linea anadida a design_push_log.jsonl, auditable)"
        )
        return 0

    declared_at = declaration.get("declared_at", "?")
    print(
        "[push-authority] FAIL: sesion declarada 'diseno' (declared_at="
        f"{declared_at}) NO puede empujar a main. Opciones exactas:\n"
        "  1. Reddeclarar el tipo (reescribe session_type.json con rastro):\n"
        "     python scripts/destination_context.py --bootstrap "
        "--project-root <raiz> --session-type desarrollo\n"
        "  2. Escape puntual con motivo no vacio (queda en "
        "design_push_log.jsonl):\n"
        '     DESIGN_PUSH_REASON="<motivo>" git push ...',
        file=sys.stderr,
    )
    return 1


def run(
    project_root: Path,
    stdin_remote_refs: list[str] | None = None,
    env: dict[str, str] | None = None,
    now: float | None = None,
) -> int:
    """Hook de pre-commit (sin flags): consume el manifiesto y evalua.

    La restriccion de AUTORIDAD depende del tipo de sesion (solo diseno/invalida
    se bloquea); el fallo de INFRAESTRUCTURA (OSError => rc 2) hace fallar el
    push de cualquier sesion.

    Before: project_root = raiz del repo empujado; stdin_remote_refs = refs
        remotas ya resueltas (tests / uso programatico) o None = resolverlas
        del manifiesto del hook nativo. During: evaluate(); solo si la sesion es
        diseno/invalida se busca el manifiesto de este push. After: 0/1/2 segun
        el docstring del modulo.
    """
    environment = env if env is not None else dict(os.environ)
    try:
        if stdin_remote_refs is not None:
            return evaluate(project_root, stdin_remote_refs, environment)
        refs: list[str] | None = None
        from_native = False
        declaration = _read_declaration(project_root)
        tipo = str((declaration or {}).get("tipo", ""))
        needs_refs = declaration is not None and (
            tipo not in VALID_TYPES or tipo == "diseno"
        )
        if needs_refs:
            common = git_common_dir(project_root)
            manifests = consume_manifests(common, environment, now) if common else []
            if manifests:
                from_native = True
                refs = [
                    str(ln.get("remote_ref", ""))
                    for data in manifests
                    for ln in data["lines"]
                    if isinstance(ln, dict)
                ]
        return evaluate(project_root, refs, environment, log_escape=not from_native)
    except OSError as exc:
        print(f"[push-authority] ERROR: {exc}", file=sys.stderr)
        return 2


def native_gate(
    project_root: Path,
    remote_name: str,
    remote_url: str,
    raw_stdin: str,
    env: dict[str, str] | None = None,
) -> int:
    """Modo --native: evalua con TODAS las refs del stdin de git y deja manifiesto.

    Before: raw_stdin es el stdin del hook pre-push de git. During: parsea
        todas las lineas, evalua (escape registrado aqui) y escribe el
        manifiesto atomico. After: veredicto de evaluate(); 2 si el manifiesto
        no se pudo escribir (el push FALLA: fail-closed).
    """
    environment = env if env is not None else dict(os.environ)
    try:
        try:
            lines = parse_push_lines(raw_stdin)
            refs: list[str] | None = [ln["remote_ref"] for ln in lines]
        except PushRefsError as exc:
            print(f"[push-authority] {exc}", file=sys.stderr)
            lines, refs = [], None
        verdict = evaluate(project_root, refs, environment)
        common = git_common_dir(project_root)
        if common is None:
            raise OSError("no se pudo resolver el git-common-dir")
        write_manifest(common, remote_name, remote_url, lines, verdict)
        return verdict
    except OSError as exc:
        print(f"[push-authority] ERROR (manifiesto): {exc}", file=sys.stderr)
        return 2


def effective_hooks_dir(project_root: Path) -> Path | None:
    """Directorio de hooks EFECTIVO de git (respeta core.hooksPath y worktrees).

    Before: project_root es la raiz de un repo git. During: `git rev-parse
        --git-path hooks` (una ruta relativa se resuelve contra project_root).
        After: Path absoluto (puede NO existir) o None si git falla.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],  # noqa: S607
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    path = Path(out.stdout.strip())
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def install_native_hook(project_root: Path) -> int:
    """Instala `pre-push.legacy` en el hooks dir EFECTIVO de ESTE repo.

    Before: el repo ya tiene el pre-push de pre-commit (`pre-commit install -t
        pre-push`) en el dir de hooks efectivo. During: resuelve ese dir con
        `git rev-parse --git-path hooks` (respeta core.hooksPath y worktrees;
        152k ronda 4: antes usaba `<git-common-dir>/hooks` y con core.hooksPath
        escribia el shim junto a un hook que git no ejecuta y devolvia 0);
        escribe el shim (modo ejecutable); NO pisa ningun nodo existente que no
        sea el shim (fichero ajeno, directorio, symlink roto). Eleccion
        documentada: se RESUELVE el dir efectivo (no se rechaza hooksPath).
        After: 0 instalado/ya instalado; 1 si no hay pre-push de pre-commit en
        el dir efectivo o hay un nodo ajeno en pre-push.legacy (no se pisa); 2
        si no hay git, la resolucion falla o el dir efectivo no existe.
        Nota: un `pre-commit install -t pre-push` posterior puede regenerar la
        cadena .legacy; tras reinstalar pre-commit, vuelve a ejecutar esta
        instalacion para reponer el shim.
    """
    hooks = effective_hooks_dir(project_root)
    if hooks is None:
        print(
            "[push-authority] ERROR: no se pudo resolver el dir de hooks de git",
            file=sys.stderr,
        )
        return 2
    if not hooks.is_dir():
        print(
            f"[push-authority] ERROR: el dir de hooks efectivo no existe: {hooks}",
            file=sys.stderr,
        )
        return 2
    pre_push = hooks / "pre-push"
    legacy = hooks / "pre-push.legacy"
    try:
        managed = pre_push.is_file() and "pre-commit" in pre_push.read_text(
            encoding="utf-8", errors="replace"
        )
        if not managed:
            print(
                f"[push-authority] ERROR: falta el pre-push de pre-commit en {hooks}; "
                "ejecuta antes `pre-commit install -t pre-push`",
                file=sys.stderr,
            )
            return 1
        if os.path.lexists(legacy):
            is_shim = (
                not legacy.is_symlink()
                and legacy.is_file()
                and NATIVE_SENTINEL
                in legacy.read_text(encoding="utf-8", errors="replace")
            )
            if not is_shim:
                print(
                    f"[push-authority] ERROR: ya existe {legacy} y no es el shim; "
                    "no se pisa",
                    file=sys.stderr,
                )
                return 1
        legacy.write_text(NATIVE_SHIM, encoding="utf-8", newline="\n")
        legacy.chmod(legacy.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as exc:
        print(f"[push-authority] ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"[push-authority] hook nativo instalado: {legacy}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Raiz del repo empujado (default: cwd, que en pre-push es la raiz).",
    )
    parser.add_argument(
        "--install-native-hook",
        action="store_true",
        help="Instala el shim pre-push.legacy en el repo (una vez por repo).",
    )
    parser.add_argument(
        "--native",
        action="store_true",
        help="Modo del hook nativo: lee el stdin de git; args: <remote> <url>.",
    )
    parser.add_argument("remote_args", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    if args.install_native_hook:
        return install_native_hook(root)
    if args.native:
        remote_name = args.remote_args[0] if args.remote_args else ""
        remote_url = args.remote_args[1] if len(args.remote_args) > 1 else ""
        return native_gate(root, remote_name, remote_url, sys.stdin.read())
    return run(root)


if __name__ == "__main__":
    raise SystemExit(main())
