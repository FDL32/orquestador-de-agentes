#!/usr/bin/env python3
"""Backlog admission guard (WOT-2026-054m): el PASO 0 cableado como barrera.

La norma PASO 0 de `prompts/_shared/finding_triage_protocol.md` exige barrer
antes de clasificar y declarar un recibo (superficies, entradas, vecinos).
Hasta este guard la norma era SOLO prosa (lineas 61-65 del protocolo). Este
modulo la enforcea en el unico punto mecanizable: el alta de un id NUEVO al
backlog del repo del alta.

Before (Pre-condiciones):
    - `--git-root` apunta a un repo git que TRACKA las superficies del backlog
      (repo del alta; en el closeout es el project_root del destino).
    - Modo rango (default): `--base`/`--head` o, por defecto, el rango
      `merge-base(origin/main, HEAD)..HEAD`. El staging NO es el rango.
    - El recibo del alta viaja en el MENSAJE del commit del alta (una linea
      `BACKLOG-ADMISSION-RECIBO: {json}` por candidato) o llega por
      `--recibo-file` (modo directo) / `--revalidate --recibo <file>`.

During (Proceso y Recursos):
    - Extrae ids de las FILAS ANADIDAS del diff del rango (anclado a forma de
      fila `^+|`, nunca al id suelto) y declara ALTA solo si el id NO estaba
      en la UNION de cola viva + archive en la revision PADRE del commit
      (comparacion de conjuntos de ids; una consulta a la cola actual ya ve
      el id recien incorporado: prohibido usarla como referencia temporal).
    - CONTRASTA cada recibo (nunca lo cree): campos obligatorios, coherencia
      interna (suma de entradas por superficie == entradas_censadas),
      re-conteo externo sobre las superficies declaradas del repo del alta en
      la revision de referencia (`load_backlog_rows` para backlog/archive;
      lineas no vacias para memoria jsonl; fichas para inbox), huella
      `corpus_sha` re-derivada con el mismo algoritmo, `algoritmo`/`umbral`
      contra las constantes del contrato, propuesta semantica con ids,
      vecinos con forma. Los bytes se NORMALIZAN CRLF->LF antes de hashear
      (evita divergencia blob vs working tree por autocrlf).
    - Emite SOLO veredictos MECANICOS: SIN_RECIBO / RECIBO_INCOHERENTE /
      ALTA_CONCURRENTE (falla) y RECIBO_COHERENTE (pasa). NUNCA etiquetas
      semanticas: `DUPLICADO_DE`/`ABSORBE_A`/`VINCULADA_A` viajan como
      PROPUESTA del autor del recibo y su resolucion es humana.
    - Altas concurrentes (regla determinista, sin heuristicas): la segunda
      alta FALLA con ALTA_CONCURRENTE si reintroduce un id ya anadido por una
      alta anterior del rango, o si su corpus no re-deriva en su revision
      padre y una alta ANTERIOR toco una superficie declarada en su recibo.
    - `--revalidate` re-ejecuta el contraste contra el corpus ACTUAL (working
      tree): mismo sha -> 0; distinto -> 1 con instruccion de re-barrido.

After (Post-condiciones y Errores):
    - exit 0 = RECIBO_COHERENTE (incluye 0 altas en el rango); exit 1 = fallo
      mecanico (SIN_RECIBO / RECIBO_INCOHERENTE / ALTA_CONCURRENTE); exit 2 =
      medicion fallida (git/IO; mensaje con marcador, NUNCA veredicto).
    - El informe publica sus denominadores: rango, commits, superficies
      escaneadas, filas anadidas vistas, ids extraidos, altas detectadas,
      recibos encontrados y veredicto por alta. Read-only: este modulo no
      escribe nada (los temporales de materializacion viven en tempfile y se
      borran).
    - LIMIT declarado (contrato T-054M-001 D3): las superficies FUERA del
      repo del alta (`repo: externo`) se DECLARAN en `corpus`, cuentan en la
      coherencia interna, pero NO se re-cuentan ni se pinean mecanicamente.

Schema del recibo (v1, una linea JSON tras el marcador):
    {"recibo_version": 1, "candidato_id": "WOT-2026-XXXXx",
     "candidato_contenido_sha": "<sha256 de la fila anadida, sin CR/LF>",
     "corpus": [{"path": "<rel>", "tipo": "backlog|archive|memoria|inbox",
                 "repo": "alta|externo", "entradas": N}, ...],
     "corpus_sha": "<sha256 canonico>", "entradas_censadas": N,
     "algoritmo": "backlog_db_compare", "umbral": 0.12,
     "veredicto_propuesta": {"tipo": "NUEVA|VINCULADA_A|DUPLICADO_DE|ABSORBE_A",
                             "ids": ["..."]},
     "vecinos": [{"id": "...", "score": 0.14}, ...]}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

try:
    from scripts.backlog_db_compare import load_backlog_rows
except ImportError:  # pragma: no cover - ejecucion directa fuera del motor
    from backlog_db_compare import load_backlog_rows  # type: ignore[no-redef]

RECIBO_MARKER = "BACKLOG-ADMISSION-RECIBO:"
CORPUS_VERSION = "backlog-admission-corpus-v1"
# Literales del contrato T-054M-001 (requisito F2.3): los pinea un test.
ALGORITMO_REQUERIDO = "backlog_db_compare"
UMBRAL_REQUERIDO = 0.12
DEFAULT_BACKLOG = ".agent/collaboration/backlog.md"
DEFAULT_ARCHIVES = (".agent/collaboration/_archive/backlog_done.md",)

# Deuda declarada (WOT-2026-054m D7): el guard se introdujo (fea0ae9,
# 2026-09-15) pero su cableado a prepush_check --closeout-mode nunca paso
# cutoff_sha, asi que ninguna sesion ejecuto --session-close hasta que el
# gate se activo de verdad. La fusion de buzon 6d341ff (2026-09-23,
# "Bloque 5/8.bis") acumulo 56 altas sin recibo, ninguna revisable
# retroactivamente (los sobres origen ya se drenaron). Amnistiadas a
# WARN_GRANDFATHERED por este commit puntual, nunca por fecha: un cutoff
# temporal se movería solo con cada commit nuevo; un SHA concreto es un
# invariante fijo que no amnistia nada posterior (WOT-2026-024t: criterio
# invariante, no medicion que caduca). Verificado 2026-09-24: 56/56 altas
# de 6d341ff pasan a WARN_GRANDFATHERED; cualquier alta post-cutoff sin
# recibo real sigue fallando SIN_RECIBO (no relaja el gate para nada nuevo).
GRANDFATHER_CUTOFF_SHA_DEFAULT = "6d341ff3d40dfbeb468859f0ccba312f10f5f1cc"
# Forma canonica de id del contrato (requisito F2.1): acepta legacy WP-/WT-.
ID_RE = re.compile(r"\b[A-Z]{2,6}-\d{4}-\d{2,3}[a-z]?\b")

VER_SIN_RECIBO = "SIN_RECIBO"
VER_WARN_GRANDFATHERED = "WARN_GRANDFATHERED"
VER_INCOHERENTE = "RECIBO_INCOHERENTE"
VER_CONCURRENTE = "ALTA_CONCURRENTE"
VER_COHERENTE = "RECIBO_COHERENTE"
FAIL_VERDICTS = (VER_SIN_RECIBO, VER_INCOHERENTE, VER_CONCURRENTE)
SEMI_FAIL_VERDICTS = (VER_WARN_GRANDFATHERED,)
SEMANTIC_TIPOS = {"DUPLICADO_DE", "ABSORBE_A", "VINCULADA_A"}
VALID_PROPUESTA_TIPOS = SEMANTIC_TIPOS | {"NUEVA"}
RECIBO_VERSION = 1

EXT_RECOUNT_MARKDOWN = "markdown"
EXT_RECOUNT_LINES = "lines"
EXT_RECOUNT_INBOX = "inbox"
_TIPO_RECOUNT = {
    "backlog": EXT_RECOUNT_MARKDOWN,
    "archive": EXT_RECOUNT_MARKDOWN,
    "memoria": EXT_RECOUNT_LINES,
    "inbox": EXT_RECOUNT_INBOX,
}


class MeasurementError(RuntimeError):
    """Fallo de medicion (git/IO): rc=2, nunca un veredicto."""


def git(repo: Path, *args: str) -> str:
    """Ejecuta git en `repo` y devuelve stdout; MeasurementError si falla."""

    proc = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise MeasurementError(
            f"git {' '.join(args)} rc={proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()[:200]}"
        )
    return proc.stdout


def git_bytes(repo: Path, *args: str) -> bytes:
    """Ejecuta git y devuelve stdout crudo en bytes."""

    proc = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise MeasurementError(
            f"git {' '.join(args)} rc={proc.returncode}: "
            f"{(proc.stderr or b'').decode('utf-8', 'replace').strip()[:200]}"
        )
    return proc.stdout


def norm_newlines(data: bytes) -> bytes:
    """Normaliza CRLF/CR a LF: misma huella en blob y en working tree."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_ids(text: str) -> set[str]:
    """Ids con forma canonica en `text` (borde de palabra)."""
    return set(ID_RE.findall(text))


def row_line_ids(line: str) -> set[str]:
    """Ids de UNA linea anadida del diff, si tiene forma de fila (`|`)."""
    body = line[1:] if line.startswith("+") else line
    if not body.lstrip().startswith("|"):
        return set()
    return canonical_ids(body)


def _row_ids_of_content(content: bytes) -> set[str]:
    """Ids de todas las filas de un contenido (union de superficies)."""
    ids: set[str] = set()
    for line in norm_newlines(content).decode("utf-8", "replace").splitlines():
        if line.lstrip().startswith("|"):
            ids.update(canonical_ids(line))
    return ids


def rev_content(repo: Path, rev: str, relpath: str) -> bytes | None:
    """Contenido normalizado de `relpath` en `rev`, o None si no resuelve."""

    proc = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "show", f"{rev}:{relpath}"],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return norm_newlines(proc.stdout)


def _surface_mode(recibo_surface: dict) -> str | None:
    """Regla de re-conteo declarada por tipo, o None si el tipo es ajeno."""
    return _TIPO_RECOUNT.get(str(recibo_surface.get("tipo", "")))


def _count_markdown(content: bytes) -> int:
    """Filas que parsea load_backlog_rows sobre contenido materializado."""
    tmp = Path(tempfile.gettempdir()) / f"admission_{_sha(content)[:16]}.md"
    tmp.write_bytes(content)
    try:
        rows, _cov = load_backlog_rows(tmp)
        return len(rows)
    finally:
        tmp.unlink(missing_ok=True)


def _count_lines(content: bytes) -> int:
    return sum(1 for ln in content.split(b"\n") if ln.strip())


def _dir_children_at_rev(repo: Path, rev: str, relpath: str) -> list[tuple[str, bytes]]:
    out = git(repo, "ls-tree", "-r", rev, "--", relpath)
    children: list[tuple[str, bytes]] = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        _meta, path = line.split("\t", 1)
        child_rel = path.strip()
        if not child_rel.lower().endswith(".md"):
            continue
        content = rev_content(repo, rev, child_rel)
        if content is not None:
            children.append((child_rel, content))
    return children


def _dir_children_on_disk(root: Path, relpath: str) -> list[tuple[str, bytes]]:
    base = root / relpath
    if not base.is_dir():
        return []
    return [
        (child.relative_to(root).as_posix(), norm_newlines(child.read_bytes()))
        for child in sorted(base.rglob("*.md"))
    ]


def _surface_fingerprint(
    repo: Path, relpath: str, rev: str | None, root: Path
) -> tuple[str, int] | None:
    """(huella, fichas_si_dir) de una superficie en la referencia, o None.

    rev=None -> working tree (modo revalidate). Devuelve None si la superficie
    no resuelve en la referencia (queda declarada como sin_pin).
    """
    if rev is None:
        target = root / relpath
        if target.is_file():
            content = norm_newlines(target.read_bytes())
            return _sha(content), 0
        if target.is_dir():
            children = _dir_children_on_disk(root, relpath)
            if not children:
                return None
            blob = "\n".join(f"{p}:{_sha(c)}" for p, c in children)
            return _sha(blob.encode("utf-8")), len(children)
        return None
    content = rev_content(repo, rev, relpath)
    if content is not None:
        return _sha(content), 0
    children = _dir_children_at_rev(repo, rev, relpath)
    if children:
        blob = "\n".join(f"{p}:{_sha(c)}" for p, c in children)
        return _sha(blob.encode("utf-8")), len(children)
    return None


def derive_corpus_sha(
    repo: Path, surfaces: list[dict], rev: str | None, root: Path
) -> tuple[str, list[str], int]:
    """Huella canonica sobre las superficies resolvibles del repo del alta.

    Devuelve (corpus_sha, rutas_sin_pin, reconto_total). El algoritmo es fijo
    y versionado (CORPUS_VERSION); el recibo y el guard derivan IGUAL.
    """
    parts = [CORPUS_VERSION]
    sin_pin: list[str] = []
    reconto = 0
    for surface in sorted(surfaces, key=lambda s: str(s.get("path", ""))):
        relpath = str(surface.get("path", ""))
        if not relpath or str(surface.get("repo", "alta")) != "alta":
            continue
        resolved = _surface_fingerprint(repo, relpath, rev, root)
        if resolved is None:
            sin_pin.append(relpath)
            continue
        huella, _n_children = resolved
        parts.append(f"{surface.get('tipo', '')}\t{relpath}\t{huella}")
        reconto += _recount_surface(repo, surface, rev, root)
    return _sha("\n".join(parts).encode("utf-8")), sin_pin, reconto


def _recount_surface(repo: Path, surface: dict, rev: str | None, root: Path) -> int:
    """Re-conteo mecanico de UNA superficie segun su tipo declarado."""
    mode = _surface_mode(surface)
    relpath = str(surface.get("path", ""))
    if mode is None or not relpath:
        return 0
    if mode == EXT_RECOUNT_INBOX:
        if rev is None:
            return len(_dir_children_on_disk(root, relpath))
        return len(_dir_children_at_rev(repo, rev, relpath))
    if rev is None:
        target = root / relpath
        if not target.is_file():
            return 0
        content = norm_newlines(target.read_bytes())
    else:
        content = rev_content(repo, rev, relpath)
        if content is None:
            return 0
    if mode == EXT_RECOUNT_MARKDOWN:
        return _count_markdown(content)
    return _count_lines(content)


def parse_recibos_from_message(message: str) -> list[tuple[dict | None, str]]:
    """Recibos del mensaje de un commit: [(json_o_None, linea_cruda)]."""
    found: list[tuple[dict | None, str]] = []
    for line in message.splitlines():
        stripped = line.strip()
        if not stripped.startswith(RECIBO_MARKER):
            continue
        raw = stripped[len(RECIBO_MARKER) :].strip()
        try:
            found.append((json.loads(raw), raw))
        except json.JSONDecodeError:
            found.append((None, raw))
    return found


def _load_recibo_file(path: Path) -> list[dict | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return list(data)
    return [data]


def _check_recibo_identity(recibo: dict) -> list[str]:
    """Campos de identidad: version, candidato canonico, sha de la fila."""
    issues: list[str] = []
    if recibo.get("recibo_version") != RECIBO_VERSION:
        issues.append(f"recibo_version != {RECIBO_VERSION}")
    cid = recibo.get("candidato_id")
    if not isinstance(cid, str) or not ID_RE.fullmatch(cid):
        issues.append("candidato_id no canonico")
    if not isinstance(recibo.get("candidato_contenido_sha"), str) or not recibo.get(
        "candidato_contenido_sha"
    ):
        issues.append("candidato_contenido_sha ausente")
    return issues


def _check_recibo_corpus(recibo: dict) -> list[str]:
    """Superficies declaradas: forma, tipo recontable y entradas enteras."""
    issues: list[str] = []
    corpus = recibo.get("corpus")
    if not isinstance(corpus, list) or not corpus:
        return ["corpus vacio o ausente"]
    for surface in corpus:
        if not isinstance(surface, dict) or not surface.get("path"):
            issues.append("superficie de corpus sin path")
            break
        if _surface_mode(surface) is None and str(surface.get("repo")) == "alta":
            issues.append(f"tipo de superficie no recontable: {surface.get('tipo')}")
            break
        n = surface.get("entradas") if isinstance(surface, dict) else None
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            issues.append("superficie de corpus sin entradas entero")
            break
    return issues


def _check_recibo_metrica(recibo: dict) -> list[str]:
    """Algoritmo, umbral y entradas_censadas contra las constantes del contrato."""
    issues: list[str] = []
    if recibo.get("algoritmo") != ALGORITMO_REQUERIDO:
        issues.append(
            f"algoritmo {recibo.get('algoritmo')!r} != {ALGORITMO_REQUERIDO!r}"
        )
    umbral = recibo.get("umbral")
    if not isinstance(umbral, (int, float)) or isinstance(umbral, bool):
        issues.append("umbral no numerico")
    elif abs(float(umbral) - UMBRAL_REQUERIDO) > 1e-9:
        issues.append(f"umbral {umbral} != {UMBRAL_REQUERIDO}")
    entradas = recibo.get("entradas_censadas")
    if not isinstance(entradas, int) or isinstance(entradas, bool) or entradas < 0:
        issues.append("entradas_censadas no entero >= 0")
    return issues


def _check_recibo_propuesta(recibo: dict) -> list[str]:
    """Propuesta semantica (F2.5) y vecinos (F2.6): forma, nunca semantica."""
    issues: list[str] = []
    entradas = recibo.get("entradas_censadas")
    propuesta = recibo.get("veredicto_propuesta")
    if (
        not isinstance(propuesta, dict)
        or propuesta.get("tipo") not in VALID_PROPUESTA_TIPOS
    ):
        issues.append("veredicto_propuesta.tipo invalido")
    elif propuesta.get("tipo") in SEMANTIC_TIPOS:
        ids = propuesta.get("ids")
        if not isinstance(ids, list) or not ids:
            issues.append(f"propuesta {propuesta.get('tipo')} sin ids")
        elif any(not isinstance(i, str) or not ID_RE.fullmatch(i) for i in ids):
            issues.append("propuesta con ids no canonicos")
    vecinos = recibo.get("vecinos")
    if not isinstance(vecinos, list):
        issues.append("vecinos ausente")
    else:
        if isinstance(entradas, int) and entradas >= 2 and not vecinos:
            issues.append("vecinos vacio con entradas_censadas >= 2")
        for vecino in vecinos:
            if not isinstance(vecino, dict) or not vecino.get("id"):
                issues.append("vecino sin id")
                break
            score = vecino.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                issues.append("vecino con score no numerico")
                break
    return issues


def _check_recibo_suma_interna(recibo: dict) -> list[str]:
    """Coherencia interna (D3): suma de entradas por superficie == censadas."""
    corpus = recibo.get("corpus")
    entradas = recibo.get("entradas_censadas")
    if not isinstance(corpus, list) or not isinstance(entradas, int):
        return []
    total = 0
    for surface in corpus:
        n = surface.get("entradas") if isinstance(surface, dict) else None
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            return []
        total += n
    if total != entradas:
        return [
            f"suma de entradas por superficie ({total}) != entradas_censadas ({entradas})"
        ]
    return []


def _check_recibo_fields(recibo: dict) -> list[str]:
    """Campos obligatorios y forma; lista de motivos (vacio = conforme)."""
    issues: list[str] = []
    if not isinstance(recibo.get("corpus_sha"), str) or not recibo.get("corpus_sha"):
        issues.append("corpus_sha ausente")
    issues.extend(_check_recibo_identity(recibo))
    issues.extend(_check_recibo_corpus(recibo))
    issues.extend(_check_recibo_metrica(recibo))
    issues.extend(_check_recibo_propuesta(recibo))
    issues.extend(_check_recibo_suma_interna(recibo))
    return issues


def _added_rows_of_commit(
    repo: Path, sha: str, surfaces: list[str]
) -> tuple[list[str], list[str]]:
    """(filas anadidas, filas eliminadas) del commit para las superficies."""
    diff = git(repo, "show", "--format=", "--unified=0", sha, "--", *surfaces)
    added: list[str] = []
    removed: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") and line[1:].lstrip().startswith("|"):
            added.append(line[1:])
        elif line.startswith("-") and line[1:].lstrip().startswith("|"):
            removed.append(line[1:])
    return added, removed


def _touched_paths(repo: Path, sha: str) -> set[str]:
    out = git(repo, "show", "--format=", "--name-only", sha)
    return {
        line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()
    }


def _externo_paths(recibo: dict) -> list[str]:
    """Rutas de superficies repo:externo declaradas (LIMIT: no re-contadas)."""
    return sorted(
        str(s.get("path", ""))
        for s in recibo.get("corpus", [])
        if isinstance(s, dict) and str(s.get("repo")) == "externo" and s.get("path")
    )


def _alta_entradas_declaradas(surfaces: list[dict]) -> int:
    """Suma de entradas declaradas de las superficies del repo del alta."""
    return sum(
        s.get("entradas") for s in surfaces if str(s.get("repo", "alta")) == "alta"
    )


def _audit_revalidate(repo: Path, recibo: dict) -> tuple[int, list[str], list[dict]]:
    """Modo consumidor (D5): contraste contra el corpus ACTUAL del working tree."""
    lines: list[str] = []
    issues = _check_recibo_fields(recibo)
    sin_pin: list[str] = []
    if not issues:
        surfaces_declared = [s for s in recibo.get("corpus", []) if isinstance(s, dict)]
        corpus_sha, sin_pin, reconto = derive_corpus_sha(
            repo, surfaces_declared, None, repo
        )
        alta_entradas = _alta_entradas_declaradas(surfaces_declared)
        if reconto != alta_entradas:
            issues.append(
                f"re-conteo actual ({reconto}) != entradas declaradas del "
                f"repo del alta ({alta_entradas})"
            )
        if corpus_sha != recibo.get("corpus_sha"):
            issues.append(
                "corpus actual difiere del recibo: REHACE EL BARRIDO "
                "(el corpus censado ya no es el corpus vivo)"
            )
    if sin_pin:
        lines.append(f"superficies declaradas sin pin mecanico: {', '.join(sin_pin)}")
    externo = _externo_paths(recibo)
    if externo:
        lines.append(
            f"superficies externas NO_RECONTADA (LIMIT declarado): {', '.join(externo)}"
        )
    if issues:
        lines.append(
            f"VEREDICTO: {VER_INCOHERENTE} (revalidate) para {recibo.get('candidato_id')}"
        )
        lines.extend(f"  - {i}" for i in issues)
        finding = {
            "candidato_id": recibo.get("candidato_id"),
            "veredicto": VER_INCOHERENTE,
            "motivos": issues,
        }
        return 1, lines, [finding]
    lines.append(
        f"VEREDICTO: {VER_COHERENTE} (revalidate) para {recibo.get('candidato_id')}"
    )
    return 0, lines, []


def _concurrencia_de(
    raw_id: str, issues: list[str], altas_procesadas: list[dict], declared: list[dict]
) -> tuple[bool, list[str]]:
    """Regla determinista D6. Devuelve (es_concurrente, motivos_anadidos).

    (a) reintroduccion de un id ya anadido por una alta anterior CON recibo;
    (b) corpus que no re-deriva Y solape de superficies con una alta anterior.
    Mutar `issues` es intencional: los motivos viajan en el veredicto.
    """
    corpus_no_re_deriva = any("corpus_sha no re-deriva" in issue for issue in issues)
    declared_paths = {str(s.get("path", "")) for s in declared if isinstance(s, dict)}
    for prev in altas_procesadas:
        if prev["id"] == raw_id and prev.get("recibo"):
            issues.append(
                f"reintroduccion del id {raw_id} ya anadido con recibo "
                f"por {prev['commit'][:12]}"
            )
            return True, issues
        solape = prev["touched"] & declared_paths
        if solape and corpus_no_re_deriva:
            issues.append(
                f"la alta anterior {prev['commit'][:12]} toco superficies declaradas: "
                f"{', '.join(sorted(solape))}"
            )
            return True, issues
    return False, issues


def _veredicto_con_recibo(
    repo: Path,
    sha: str,
    raw_id: str,
    added: list[str],
    subject: str,
    recibo: dict,
    altas_procesadas: list[dict],
) -> tuple[list[str], dict, dict]:
    """Veredicto de UNA alta con recibo: (lineas, hallazgo, registro_alta).

    Contraste fail-closed (D3): campos, re-conteo externo en la revision padre,
    corpus_sha re-derivado, sha de la fila y concurrencia determinista (D6).
    """
    candidate_line = next((r for r in added if raw_id in row_line_ids(r)), "")
    content_sha = _sha(candidate_line.rstrip("\r\n").encode("utf-8"))
    issues = _check_recibo_fields(recibo)
    sin_pin: list[str] = []
    if not issues:
        declared = [s for s in recibo.get("corpus", []) if isinstance(s, dict)]
        corpus_sha, sin_pin, reconto = derive_corpus_sha(
            repo, declared, f"{sha}^", repo
        )
        alta_entradas = _alta_entradas_declaradas(declared)
        if reconto != alta_entradas:
            issues.append(
                f"re-conteo en la revision padre ({reconto}) != entradas "
                f"declaradas del repo del alta ({alta_entradas})"
            )
        if corpus_sha != recibo.get("corpus_sha"):
            issues.append("corpus_sha no re-deriva en la revision padre del alta")
        if recibo.get("candidato_contenido_sha") != content_sha:
            issues.append("candidato_contenido_sha no coincide con la fila anadida")
        concurrente, issues = _concurrencia_de(
            raw_id, issues, altas_procesadas, declared
        )
    else:
        concurrente = False
    lines: list[str] = []
    if sin_pin:
        lines.append(f"superficies declaradas sin pin mecanico: {', '.join(sin_pin)}")
    veredicto = (
        (VER_CONCURRENTE if concurrente else VER_INCOHERENTE)
        if issues
        else VER_COHERENTE
    )
    lines.append(f"ALTA {raw_id} en {sha[:12]} '{subject}' -> VEREDICTO: {veredicto}")
    lines.extend(f"  - {issue}" for issue in issues)
    externo = _externo_paths(recibo)
    if externo:
        lines.append(
            "  superficies externas NO_RECONTADA (LIMIT declarado): "
            f"{', '.join(externo)}"
        )
    finding = {
        "commit": sha[:12],
        "candidato_id": raw_id,
        "veredicto": veredicto,
        "motivos": issues,
    }
    registro = {
        "commit": sha,
        "id": raw_id,
        "veredicto": veredicto,
        "recibo": True,
    }
    return lines, finding, registro


def _parent_row_ids(repo: Path, sha: str, surfaces: list[str]) -> set[str]:
    """Ids presentes en la UNION de superficies en la revision PADRE del sha."""
    ids: set[str] = set()
    for surface in surfaces:
        content = rev_content(repo, f"{sha}^", surface)
        if content is not None:
            ids |= _row_ids_of_content(content)
    return ids


def _recibo_de_candidato(
    raw_id: str,
    recibo_files: dict[str, dict],
    msg_recibos: list[tuple[dict | None, str]],
) -> dict | None:
    """Recibo del candidato: fichero --recibo-file o mensaje del commit."""
    recibo = recibo_files.get(raw_id)
    if recibo is not None:
        return recibo
    for parsed, _raw in msg_recibos:
        if isinstance(parsed, dict) and parsed.get("candidato_id") == raw_id:
            return parsed
    return None


def _registrar_sin_recibo(
    lines: list[str],
    findings: list[dict],
    altas_procesadas: list[dict],
    sha: str,
    raw_id: str,
    subject: str,
    touched: set[str],
    grandfathered: bool = False,
) -> None:
    """Alta sin recibo: linea por-alta, hallazgo y registro sin recibo.

    Si `grandfathered` es True, degrada a WARN_GRANDFATHERED citando el censo
    17/30 (57%) de altas historicas sin recibo; el veredicto global no falla.
    """
    if grandfathered:
        veredicto = VER_WARN_GRANDFATHERED
        lines.append(
            f"ALTA {raw_id} en {sha[:12]} '{subject}' -> VEREDICTO: {veredicto} "
            f"(grandfathered pre-cutoff; censo 17/30 (57%) sin recibo)"
        )
        findings.append(
            {
                "commit": sha[:12],
                "candidato_id": raw_id,
                "veredicto": veredicto,
                "motivos": [
                    f"alta de id nuevo {raw_id} en '{subject}' sin recibo de barrido; "
                    "degradada a WARN_GRANDFATHERED (commit ancestro del cutoff SHA; "
                    "censo 17/30 (57%) sin recibo)"
                ],
            }
        )
        altas_procesadas.append(
            {
                "commit": sha,
                "id": raw_id,
                "touched": touched,
                "veredicto": veredicto,
                "recibo": False,
                "grandfathered": True,
            }
        )
    else:
        lines.append(
            f"ALTA {raw_id} en {sha[:12]} '{subject}' -> VEREDICTO: {VER_SIN_RECIBO}"
        )
        findings.append(
            {
                "commit": sha[:12],
                "candidato_id": raw_id,
                "veredicto": VER_SIN_RECIBO,
                "motivos": [
                    f"alta de id nuevo {raw_id} en '{subject}' sin recibo de barrido"
                ],
            }
        )
        altas_procesadas.append(
            {
                "commit": sha,
                "id": raw_id,
                "touched": touched,
                "veredicto": VER_SIN_RECIBO,
                "recibo": False,
            }
        )


def _broken_recibo_findings(
    sha: str, msg_recibos: list[tuple[dict | None, str]]
) -> list[dict]:
    """Hallazgos por recibo en mensaje que no parsea como JSON (fail-closed)."""
    n_broken = sum(1 for parsed, _raw in msg_recibos if parsed is None)
    if not n_broken:
        return []
    return [
        {
            "commit": sha[:12],
            "veredicto": VER_INCOHERENTE,
            "motivos": ["recibo en mensaje no parsea como JSON"] * n_broken,
        }
    ]


def _recibos_huerfanos(
    sha: str,
    subject: str,
    msg_recibos: list[tuple[dict | None, str]],
    nuevos: set[str],
    pids: set[str],
    findings: list[dict],
) -> list[dict]:
    """Recibos sin alta nueva detectable en el commit: segunda alta concurrente."""
    hallazgos: list[dict] = []
    for parsed, _raw in msg_recibos:
        if not isinstance(parsed, dict):
            continue
        cid = parsed.get("candidato_id")
        if not isinstance(cid, str) or cid in nuevos or cid in pids:
            continue
        ya = any(
            f["candidato_id"] == cid and f["veredicto"] == VER_CONCURRENTE
            for f in findings
        )
        if not ya:
            hallazgos.append(
                {
                    "commit": sha[:12],
                    "candidato_id": cid,
                    "veredicto": VER_CONCURRENTE,
                    "motivos": [
                        f"recibo de {cid} en '{subject}' sin alta nueva detectable: "
                        "el id ya existia en la revision padre (segunda alta concurrente)"
                    ],
                }
            )
    return hallazgos


def _is_ancestor(repo: Path, maybe_ancestor: str, commit: str) -> bool:
    """Verifica si `maybe_ancestor` es ancestro de `commit` en `repo`."""
    try:
        _proc = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(repo),
                "merge-base",
                "--is-ancestor",
                maybe_ancestor,
                commit,
            ],
            capture_output=True,
            check=False,
        )
        return _proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _audit_commit(
    repo: Path,
    sha: str,
    surfaces: list[str],
    recibo_files: dict[str, dict],
    altas_procesadas: list[dict],
    lines: list[str],
    findings: list[dict],
    cutoff_sha: str | None = None,
) -> tuple[int, int, int]:
    """Audita UN commit: (filas_anadidas, ids_extraidos, recibos_de_mensaje).

    Mutar `lines`, `findings` y `altas_procesadas` es intencional: es el informe
    acumulado del rango (patron del modulo).
    """
    added, _removed = _added_rows_of_commit(repo, sha, surfaces)
    added_ids: set[str] = set()
    for row in added:
        added_ids |= row_line_ids(row)
    pids = _parent_row_ids(repo, sha, surfaces)
    nuevos = added_ids - pids
    subject = git(repo, "log", "-1", "--format=%s", sha).strip()
    msg_recibos = parse_recibos_from_message(git(repo, "log", "-1", "--format=%B", sha))
    n_recibos_msg = sum(1 for parsed, _raw in msg_recibos if isinstance(parsed, dict))
    findings.extend(_broken_recibo_findings(sha, msg_recibos))
    touched = _touched_paths(repo, sha)
    for raw_id in sorted(nuevos):
        recibo = _recibo_de_candidato(raw_id, recibo_files, msg_recibos)
        if recibo is None:
            grandfathered = cutoff_sha is not None and _is_ancestor(
                repo, sha, cutoff_sha
            )
            _registrar_sin_recibo(
                lines,
                findings,
                altas_procesadas,
                sha,
                raw_id,
                subject,
                touched,
                grandfathered=grandfathered,
            )
            continue
        extra_lines, finding, registro = _veredicto_con_recibo(
            repo, sha, raw_id, added, subject, recibo, altas_procesadas
        )
        lines.extend(extra_lines)
        findings.append(finding)
        registro["touched"] = touched
        altas_procesadas.append(registro)
    findings.extend(
        _recibos_huerfanos(sha, subject, msg_recibos, nuevos, pids, findings)
    )
    return len(added), len(added_ids), n_recibos_msg


def audit_range(
    repo: Path,
    base: str,
    head: str,
    surfaces: list[str],
    extra_recibos: list[dict] | None = None,
    revalidate: dict | None = None,
    cutoff_sha: str | None = None,
) -> tuple[int, list[str], list[dict]]:
    """Auditoria del rango (o revalidacion single-recibo si revalidate).

    Devuelve (exit_code, lineas_informe, hallazgos_json). exit 2 = medicion
    fallida; 1 = fallo mecanico; 0 = coherente (incluye 0 altas).
    """
    lines: list[str] = []
    findings: list[dict] = []
    if revalidate is not None:
        return _audit_revalidate(repo, revalidate)

    commits = [
        c
        for c in git(
            repo, "log", "--reverse", "--format=%H", f"{base}..{head}"
        ).splitlines()
        if c.strip()
    ]
    n_added_rows = 0
    n_ids = 0
    n_recibos_msg = 0
    n_recibos_file = len(extra_recibos or [])
    altas_procesadas: list[dict] = []

    recibo_files: dict[str, dict] = {}
    for recibo in extra_recibos or []:
        cid = recibo.get("candidato_id")
        if isinstance(cid, str):
            recibo_files[cid] = recibo

    for sha in commits:
        rows_n, ids_n, recibos_n = _audit_commit(
            repo,
            sha,
            surfaces,
            recibo_files,
            altas_procesadas,
            lines,
            findings,
            cutoff_sha=cutoff_sha,
        )
        n_added_rows += rows_n
        n_ids += ids_n
        n_recibos_msg += recibos_n

    lines.insert(
        0, f"rango auditado: {base[:12]}..{head[:12]} ({len(commits)} commit(s))"
    )
    lines.insert(1, f"superficies: {', '.join(surfaces)}")
    lines.insert(
        2,
        f"filas anadidas vistas: {n_added_rows}; ids extraidos: {n_ids}; "
        f"altas detectadas: {len(altas_procesadas)}",
    )
    lines.insert(
        3,
        f"recibos encontrados: {n_recibos_msg} en mensajes de commit "
        f"+ {n_recibos_file} via --recibo-file",
    )
    fails = [f for f in findings if f.get("veredicto") in FAIL_VERDICTS]
    grandfathered = [
        f for f in findings if f.get("veredicto") == VER_WARN_GRANDFATHERED
    ]
    if fails:
        lines.append(
            f"VEREDICTO GLOBAL: FALLO ({len(fails)} alta(s) sin recibo coherente)"
        )
        if grandfathered:
            lines.append(
                f"  grandfathered: {len(grandfathered)} alta(s) pre-cutoff "
                f"(censo 17/30 (57%) sin recibo)"
            )
        return 1, lines, findings
    lines.append(f"VEREDICTO GLOBAL: {VER_COHERENTE}")
    if grandfathered:
        lines.append(
            f"  grandfathered: {len(grandfathered)} alta(s) pre-cutoff "
            f"(censo 17/30 (57%) sin recibo)"
        )
    return 0, lines, findings


def _audit_closeout(
    repo: Path, cutoff_sha: str | None = None
) -> tuple[int, list[str], bool, list[dict]]:
    """Camino del closeout: rango por defecto + SKIP nombrado si no resuelve.

    Devuelve (exit_code, lineas_informe, skipped_real, hallazgos_json). El
    tercer elemento es un BOOLEANO de skip, nunca la lista de hallazgos: los
    consumidores lo desempaquetan para decidir verde/skip, y confundirlos
    invierte el veredicto (falso verde exactamente cuando hay altas fallidas).

    cutoff_sha=None usa GRANDFATHER_CUTOFF_SHA_DEFAULT (deuda declarada de
    WOT-2026-054m D7): sin este default, el gate bloquea CUALQUIER cierre de
    sesion con las 56 altas historicas de 6d341ff, que nunca pasaron por el
    gate porque este nunca corrio en un cierre real hasta que se detecto
    (2026-09-24). Pasar cutoff_sha="" explicito (string vacio) desactiva el
    grandfather por completo, para quien necesite auditar sin amnistia.
    """
    surfaces = [DEFAULT_BACKLOG, *DEFAULT_ARCHIVES]
    if cutoff_sha is None:
        cutoff_sha = GRANDFATHER_CUTOFF_SHA_DEFAULT
    elif cutoff_sha == "":
        cutoff_sha = None
    try:
        base = git(repo, "merge-base", "origin/main", "HEAD").strip()
        head = git(repo, "rev-parse", "HEAD").strip()
    except MeasurementError as exc:
        return (
            0,
            [f"SKIP: rango no resoluble ({exc}); el gate no se ha ejecutado"],
            True,
            [],
        )
    if base == head:
        return (
            0,
            [f"0 commits en el rango {base[:12]}..{head[:12]}: 0 altas que contrastar"],
            False,
            [],
        )
    code, lines, findings = audit_range(
        repo, base, head, surfaces, cutoff_sha=cutoff_sha
    )
    return code, lines, False, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backlog admission guard (WOT-2026-054m): PASO 0 como barrera."
    )
    parser.add_argument(
        "--git-root", type=Path, default=None, help="Repo del backlog (default: cwd)"
    )
    parser.add_argument(
        "--base",
        default=None,
        help="Base del rango (default: merge-base origin/main HEAD)",
    )
    parser.add_argument(
        "--head", default=None, help="Extremo del rango (default: HEAD)"
    )
    parser.add_argument(
        "--backlog-file",
        default=DEFAULT_BACKLOG,
        help="Superficie viva (relativa al repo)",
    )
    parser.add_argument(
        "--archive-file",
        action="append",
        default=None,
        help="Superficie archive (repetible)",
    )
    parser.add_argument(
        "--recibo-file",
        action="append",
        type=Path,
        default=None,
        help="Recibo JSON externo (repetible)",
    )
    parser.add_argument(
        "--revalidate",
        action="store_true",
        help="Modo consumidor: contrasta contra el corpus ACTUAL",
    )
    parser.add_argument(
        "--recibo",
        type=Path,
        default=None,
        help="Recibo a revalidar (obligatorio con --revalidate)",
    )
    parser.add_argument(
        "--grandfather-cutoff-sha",
        default=None,
        help="SHA de corte grandfather: las altas anteriores a este SHA "
        "se degradan a WARN_GRANDFATHERED (nunca ERROR).",
    )
    parser.add_argument("--json", action="store_true", help="Reporte JSON a stdout")
    args = parser.parse_args(argv)

    repo = (args.git_root or Path.cwd()).resolve()
    surfaces = [args.backlog_file] + (args.archive_file or list(DEFAULT_ARCHIVES))
    try:
        extra: list[dict] = []
        for path in args.recibo_file or []:
            extra.extend(r for r in _load_recibo_file(path) if isinstance(r, dict))
        if args.revalidate:
            if args.recibo is None:
                parser.error("--revalidate exige --recibo <file>")
            recibo = json.loads(args.recibo.read_text(encoding="utf-8"))
            code, lines, findings = audit_range(
                repo, "", "", surfaces, revalidate=recibo
            )
        elif args.base and args.head:
            code, lines, findings = audit_range(
                repo,
                args.base,
                args.head,
                surfaces,
                extra_recibos=extra,
                cutoff_sha=args.grandfather_cutoff_sha,
            )
        else:
            code, lines, skipped, findings = _audit_closeout(
                repo,
                cutoff_sha=args.grandfather_cutoff_sha,
            )
            if skipped:
                print("\n".join(lines))
                return 0
    except MeasurementError as exc:
        print(f"MEDICION_FALLIDA: {exc}")
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(f"MEDICION_FALLIDA: {exc}")
        return 2
    if args.json:
        print(
            json.dumps(
                {"exit": code, "lines": lines, "findings": findings},
                ensure_ascii=False,
                indent=1,
            )
        )
    else:
        print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
