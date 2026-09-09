from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# WOT-2026-047s: tope de la LISTA de saltados publicada. Un commit masivo de
# binarios no debe inundar la salida; el truncamiento se PUBLICA, nunca es
# silencioso (seria la misma familia de defecto que este ticket cierra).
_LISTA_TOPE = 20


def _resolve_audit_root() -> Path:
    """WOT-2026-043d: raiz del arbol REAL cuyo indice se esta commiteando.

    Before: el cwd del proceso (pre-commit lo fija a la raiz del repo que
        commitea; una invocacion manual desde un subdirectorio tambien vale).
    During: resuelve `git rev-parse --show-toplevel` contra ese cwd. Fail-closed
        (exit 2, diagnosticos en stderr) si git no esta en PATH o el cwd no
        pertenece a un arbol git: sin arbol real que auditar, un rc=0 seria el
        falso verde que este ticket cierra.
    After: la raiz absoluta resuelta del arbol auditado (worktrees incluidos:
        --show-toplevel devuelve la raiz del worktree, no la del main).
    """
    git_executable = shutil.which("git")
    if not git_executable:
        print(
            "[encoding-guard] FAIL-CLOSED: git executable not found in PATH",
            file=sys.stderr,
        )
        raise SystemExit(2)
    candidate = Path.cwd().resolve()
    probe = subprocess.run(  # noqa: S603
        [git_executable, "rev-parse", "--show-toplevel"],
        cwd=candidate,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if probe.returncode != 0:
        print(
            f"[encoding-guard] FAIL-CLOSED: cwd is not inside a git tree: {candidate}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return Path(probe.stdout.strip()).resolve()


def _staged_relative_paths(audit_root: Path) -> list[str]:
    git_executable = shutil.which("git")
    if not git_executable:
        raise RuntimeError("git executable not found in PATH")

    result = subprocess.run(  # noqa: S603
        [git_executable, "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=audit_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _explicit_paths(args: list[str]) -> tuple[list[Path], list[str]] | None:
    """WOT-2026-047s (D3): resuelve los args explicitos SIN descartar en silencio.

    La barrera va en el TIPO, no en un flag (leccion
    obs-degradado-indistinguible-del-legitimo: el camino degradado debe devolver
    un valor de OTRO TIPO, nunca un valor valido empobrecido).

    Before: los argumentos crudos de argv (puede ser []).
    During: sin argumentos devuelve None (la via es el hook: el universo es el
        indice staged). Con argumentos resuelve cada uno a Path y lo clasifica:
        resuelto (existe y es fichero) o irresoluble (se NOMBRA, nunca se
        descarta). Sin I/O mas alla del `exists` de cada candidato.
    After: None sin args; (resueltos, irresolubles) en el orden de argv con args.
        La lista de resueltos VACIA con args presentes ya NO es indistinguible
        de "no me pasaron argumentos": es MEDICION FALLIDA (ROJO por
        DEC-047S-001), no un universo sin materia.
    """
    if not args:
        return None
    resolved: list[Path] = []
    unresolved: list[str] = []
    for raw in args:
        candidate = Path(raw).resolve()
        if candidate.exists() and candidate.is_file():
            resolved.append(candidate)
        else:
            unresolved.append(raw)
    return resolved, unresolved


def _publicar_denominador(
    via: str,
    denominador: int,
    inspeccionados: int,
    hits: int,
    saltados: list[str],
    etiqueta_saltado: str,
) -> None:
    """WOT-2026-047s (D1): publica el denominador en stderr en TODOS los caminos.

    Before: la via del universo (`indice staged` | `argumentos explicitos`), el
        denominador PRE-filtro (entradas staged en via hook; argumentos pasados
        en via explicita), los ficheros efectivamente auditados, los ficheros
        con errores de encoding, y la lista de saltados (relativos en via hook;
        argumentos crudos en via explicita).
    During: imprime la linea estructurada con los CUATRO campos que el Quality
        Bar y DEC-047S-001 exigen, y la LISTA de saltados: una linea por fichero
        hasta `_LISTA_TOPE`; el truncamiento se publica con `... y <N> mas`.
    After: nada (solo stderr). El guard no emite veredictos por stdout.
    """
    print(
        f"[encoding-guard] denominador={denominador} inspeccionados={inspeccionados} "
        f"hits={hits} saltados={len(saltados)} (universo: {via})",
        file=sys.stderr,
    )
    if not saltados:
        return
    for item in saltados[:_LISTA_TOPE]:
        print(f"[encoding-guard] {etiqueta_saltado}: {item}", file=sys.stderr)
    ocultos = len(saltados) - _LISTA_TOPE
    if ocultos > 0:
        print(
            f"[encoding-guard] ... y {ocultos} mas (truncamiento publicado)",
            file=sys.stderr,
        )


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _allowlist_relative(path: Path) -> str | None:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return None


# WOT-2026-058r: allowlist declarable por el DESTINO, para deuda PREEXISTENTE.
# `ALLOWLIST` (motor) esta vacia y `_allowlist_relative()` devuelve None fuera
# del motor, asi que cualquier corrupcion historica del destino bloqueaba el gate
# sin via de excepcion declarada. Medido 2026-08-23 en el cierre de un destino:
# 3 ficheros con corrupcion preexistente (verificada contra los blobs de HEAD~1)
# daban rc=1 y obligaban a re-declararlo en prosa en CADA cierre.
#
# La excepcion es POR FICHERO DECLARADO, nunca por patron: un fichero NUEVO con
# la misma corrupcion sigue bloqueando. Esa asimetria es el punto -- tolerar
# deuda historica sin abrir la puerta a deuda nueva.
_DESTINO_ALLOWLIST_REL = Path(".agent") / "encoding_allowlist.json"


def _destino_allowlist(file_path: Path) -> tuple[set[str], str | None]:
    """Allowlist declarada por el destino que CONTIENE `file_path`.

    Before: `file_path` es la ruta de un fichero a auditar.
    During: sube por los padres buscando `.agent/encoding_allowlist.json`; lo lee
        con utf-8-sig (un BOM no debe tumbar la resolucion). Sin I/O fuera de esa
        cadena de padres.
    After: devuelve (entradas relativas al destino, ticket dueno). Conjunto vacio
        y None si no hay declaracion, es ilegible, o no declara `owner` --
        fail-closed: una allowlist sin dueno no exime nada.
    """
    for parent in [file_path.parent, *file_path.parent.parents]:
        candidate = parent / _DESTINO_ALLOWLIST_REL
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return set(), None
        if not isinstance(data, dict):
            return set(), None
        owner = data.get("owner")
        entries = data.get("entries")
        if not isinstance(owner, str) or not owner.strip():
            return set(), None
        if not isinstance(entries, list):
            return set(), None
        resolved: set[str] = set()
        for entry in entries:
            if isinstance(entry, str) and entry.strip():
                resolved.add((parent / entry).resolve().as_posix())
        return resolved, owner.strip()
    return set(), None


def _collect_file_errors(file_path) -> list[str]:
    """Return all encoding errors for one file (BOM/mojibake/q-mark/text corruption)."""
    from scripts.encoding_guard import file_issues, has_utf8_bom, is_allowlisted

    rel = _display_path(file_path)
    mojibake, q_in_word, text_corruption = file_issues(file_path)
    # WOT-2026-058r: la allowlist del DESTINO se consulta antes que la del motor.
    declared, owner = _destino_allowlist(Path(file_path))
    if declared and Path(file_path).resolve().as_posix() in declared:
        if not mojibake and not q_in_word and not text_corruption:
            return [
                f"Allowlist entry is now clean and should be removed: {rel} "
                f"[owner: {owner}]"
            ]
        print(f"[encoding-guard] allowlisted by destino: {rel} [owner: {owner}]")
        return []

    rel_for_allowlist = _allowlist_relative(file_path)
    if rel_for_allowlist is not None and is_allowlisted(rel_for_allowlist):
        if not mojibake and not q_in_word and not text_corruption:
            return [f"Allowlist entry is now clean and should be removed: {rel}"]
        return []
    errors: list[str] = []
    if has_utf8_bom(file_path):
        errors.append(f"UTF-8 BOM detected in {rel}")
    if mojibake:
        errors.append(f"Mojibake detected in {rel}: {mojibake[:12]}")
    if q_in_word:
        errors.append(f"Question-mark corruption detected in {rel}: {q_in_word[:12]}")
    if text_corruption:
        errors.append(f"Text corruption detected in {rel}: {text_corruption[:12]}")
    return errors


def main() -> int:
    """WOT-2026-047s (D1+D3): publica SIEMPRE su denominador y distingue
    'audite y esta limpio' de 'universo sin materia' de 'medicion fallida'.

    Before: argv. En la via hook (sin argumentos) el cwd debe pertenecer a un
        arbol git (fail-closed exit 2 via `_resolve_audit_root`).
    During: via hook: el universo es el indice staged del arbol del cwd
        (WOT-2026-043d); via explicita: los ficheros que resolvieron de los args
        pasados; los irresolubles se NOMBRAN y cuentan como saltados (D3: nunca
        se cae en silencio al indice, que seria un veredicto sobre OTRA COSA).
        Se audita cada fichero del universo resuelto.
    After: publica la linea estructurada de 4 campos y la LISTA de saltados en
        stderr en TODOS los caminos, mas la senal del caso: vacuo (via hook,
        0 auditables, exit 0 por universo SIN MATERIA, autorizado por
        DEC-047S-001 con denominador publicado), medicion FALLIDA (via
        explicita, 0 resueltos, exit 1), diagnostico de errores (exit 1), o
        verde limpio (exit 0). Nunca un exit 0 mudo.
    """
    from scripts.encoding_guard import iter_staged_files

    explicit = _explicit_paths(sys.argv[1:])
    if explicit is None:
        # WOT-2026-043d: en la ruta staged (la que usa pre-commit con
        # pass_filenames: false) la raiz auditada es la del cwd REAL, no la del
        # modulo: el indice que se valida es el de ESTE commit.
        audit_root = _resolve_audit_root()
        staged_rels = _staged_relative_paths(audit_root)
        files_to_check = iter_staged_files(staged_rels, root=audit_root)
        via = "indice staged"
        etiqueta_saltado = "saltado (fuera de alcance)"
        auditados_resueltos = {path.resolve() for path in files_to_check}
        saltados = [
            rel
            for rel in staged_rels
            if (audit_root / rel).resolve() not in auditados_resueltos
        ]
    else:
        resolved, unresolved = explicit
        files_to_check = resolved
        via = "argumentos explicitos"
        etiqueta_saltado = "ruta irresoluble"
        saltados = unresolved

    errores_por_fichero = [_collect_file_errors(path) for path in files_to_check]
    hits = sum(1 for errores in errores_por_fichero if errores)
    lineas_error = [linea for errores in errores_por_fichero for linea in errores]

    _publicar_denominador(
        via,
        len(files_to_check) + len(saltados),
        len(files_to_check),
        hits,
        saltados,
        etiqueta_saltado,
    )

    if explicit is None and not files_to_check:
        # DEC-047S-001: universo SIN MATERIA (propiedad del contenido, no fallo
        # de la medicion). Verde AUTORIZADO porque el denominador y la LISTA
        # acaban de publicarse: deja de ser un cero mudo.
        print(
            "[encoding-guard] 0 ficheros auditados (universo: indice staged, "
            "0 entradas). Verde VACUO: no se audito nada.",
            file=sys.stderr,
        )
        return 0
    if explicit is not None and not files_to_check:
        # DEC-047S-001: MEDICION FALLIDA -- se pidio auditar N rutas y no se
        # audito ninguna (D3: las irresolubles ya se nombraron arriba).
        print(
            f"[encoding-guard] 0 ficheros auditados (universo: argumentos "
            f"explicitos, {len(saltados)} pedidos, {len(saltados)} irresolubles). "
            "Medicion FALLIDA: se pidio auditar y no se audito nada.",
            file=sys.stderr,
        )
        return 1

    if lineas_error:
        print("Encoding guard blocked this commit:", file=sys.stderr)
        for error in lineas_error:
            print(f"- {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
