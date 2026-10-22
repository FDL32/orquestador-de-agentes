#!/usr/bin/env python3
"""Guard de crecimiento de la cuspide y de drift cuspide <-> capa 2.

Tres escalones en commit-msg (G1 flip confirmado 2026-10-21, WOT-2026-108d;
WOT-2026-116a anade el tercero, politica "no crecer nunca, incluso en
deuda", como escalon ADICIONAL, sin tocar el comportamiento del primero):
  1. grew Y AMBOS ratios <= 1.0x -> BLOCK (exit 1), SIN consultar el mensaje
     (override no exceptua). Sin cambios desde el G1 flip.
  2. grew Y AL MENOS un ratio > 1.0x (la cuspide ya esta "en deuda", por
     encima de cap) -> BLOCK (exit 1) TAMBIEN (WOT-2026-116a). Antes de este
     ticket este caso era WARN (exit 0); el override tampoco exceptua este
     escalon -- "no crecer nunca" es literal, incluida la cuspide en deuda.
  3. sin growth -> silencio, exit 0.
  pre-commit   WARN por cualquier crecimiento (unifica texto con over_cap).
               Sigue sin bloquear nunca (exit 0 siempre): es early warning,
               el BLOCK autoritativo de ambos escalones vive en commit-msg.
  post-commit  parseo del marcador SOLO como telemetria no decisoria.

Tres fases, porque el stage donde git entrega cada dato es distinto:

  pre-commit   medicion staged-vs-HEAD. WARN: imprime el delta y ratios.
               NUNCA bloquea (exit 0 siempre).
  commit-msg   re-mide el mismo indice. BLOCK (exit 1) con cualquier growth,
               dentro o fuera de cap (los dos escalones de arriba); no lee
               el mensaje para decidir en ninguno de los dos.
  post-commit  mide el merge-base real con `origin/main` vs HEAD (WOT-2026-116a:
               no solo el padre inmediato -- un rebase o varios commits locales
               pueden dejar HEAD^ distinto del punto real de divergencia; si
               `origin/main` no resuelve -- remoto ausente, fixture hermetico --
               degrada a HEAD^) y lee el mensaje ya aterrizado. Si hay marcador
               de override + growth, appendea una linea de telemetria al canal
               gitignored. Exit 0 siempre: la telemetria no revoca commits.

Medicion: SIEMPRE sobre los blobs de git (`git show :<path>` para el indice,
`git show HEAD:<path>` / `HEAD^:<path>` para commits), nunca sobre el working
tree. El arbol de trabajo puede ser reescrito por hooks mutadores y un checkout
CRLF en Windows no es lo que entra en git.

Gates, cada uno en su unidad nativa (prohibido convertir bytes <-> chars,
invariante de `prompts/doc_optimization.md:82-98`):
  - Codex: suma en BYTES de los `AGENTS.md` de la jerarquia. Limite 32768.
  - Claude Code: cierre transitivo de `CLAUDE.md` + `@imports`, en CHARS.
    Limite 40000 -- SLO de producto propio de este motor, no un limite
    documentado upstream de Claude Code (WOT-2026-115a).

Drift (WARN-only): si el diff toca la cuspide sin tocar `.agent/rules/common/`
o al reves, se avisa. No bloquea.

Gramatica del override (unica reconocida), modelada sobre el patron de
`prompts/orchestrator_pipeline.md:994-1019`:

  GATE-OVERRIDE: cuspide_growth
  REASON: <una linea no vacia>

`AFFECTED: codex_bytes|claude_chars|both` es opcional y solo se guarda en la
telemetria. El canal de auditoria es
`.agent/runtime/cuspide_growth_overrides.jsonl` (gitignored); la auditoria
durable y versionada es el propio mensaje de commit, consultable con
`git log --grep="GATE-OVERRIDE: cuspide_growth"`.

Before: se invoca como hook (o a mano) con `--phase`; la fase commit-msg recibe
    la ruta de `COMMIT_EDITMSG` como argv[1], igual que los hooks hermanos de
    `.pre-commit-config.yaml`. Resuelve la raiz del motor desde su propia ruta.
During: no escribe nada en pre-commit/commit-msg. En post-commit, y solo si el
    commit aterrizado lleva override + growth, appendea una linea JSON al canal
    local. Todo git va por `subprocess.run` con lista de argumentos, nunca por
    shell.
After: exit 0 en el camino silencioso y en todas las fases no bloqueantes;
    exit 1 en commit-msg con CUALQUIER growth (WOT-2026-116a: tambien si al
    menos un ratio post > 1.0x, "en deuda" -- antes de este ticket ese caso
    era WARN); el override no exceptua ninguno de los dos escalones. Ante
    un error propio (git no disponible, blob ilegible, mensaje ausente) degrada
    a exit 0 con diagnostico en stderr, precedente de
    `scripts/check_commit_message_encoding.py:158-165`: bloquear cada commit
    porque el guard se rompio es peor que el gap que cubre.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import posixpath
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


GATE_CODEX_BYTES = 32768
# SLO de producto propio del motor, no un limite documentado upstream de Claude Code.
# La documentacion de Claude Code recomienda <200 lineas/CLAUDE.md y omite ficheros >4 MiB,
# pero no fija 40.000 caracteres (WOT-2026-115a).
ORCHESTRATOR_CLAUDE_CUSP_MAX_CHARS = 40000
MARKER = "[cuspide-growth]"
AUDIT_LOG_REL = Path(".agent/runtime/cuspide_growth_overrides.jsonl")
LAYER2_PREFIX = ".agent/rules/common/"
LAYER2_SUFFIX = ".md"
MOTOR_ROOT = Path(__file__).resolve().parents[1]

_GIT = shutil.which("git") or "git"
_IMPORT_RE = re.compile(r"^@\s*([^\s#]+)")
_OVERRIDE_RE = re.compile(r"^GATE-OVERRIDE:[ \t]*cuspide_growth[ \t]*$")
_REASON_RE = re.compile(r"^REASON:[ \t]*(\S.*)$")
_AFFECTED_RE = re.compile(r"^AFFECTED:[ \t]*(codex_bytes|claude_chars|both)[ \t]*$")


class MeasurementError(RuntimeError):
    """Error propio del guard mientras resuelve blobs o el cierre de imports."""


@dataclass(frozen=True)
class Metrics:
    """Snapshot de la cuspide medido desde una fuente git concreta."""

    source: str
    agents_bytes: int
    claude_chars: int
    cuspide_files: frozenset[str]
    agents_files: tuple[str, ...]


@dataclass(frozen=True)
class Growth:
    """Veredicto delta-based sobre dos snapshots."""

    delta_bytes: int
    delta_chars: int
    grew: bool
    over_cap: bool


@dataclass(frozen=True)
class Override:
    """Override valido parseado del mensaje de commit."""

    reason: str
    affected: str | None


def strip_comments(message: str) -> str:
    """Elimina las lineas de comentario de git antes de parsear el mensaje.

    Misma forma que `scripts/check_commit_message_encoding.py:80-89`; se
    duplica a proposito para que este guard sea stdlib-only y no dependa del
    sys.path de otro script al ejecutarse como hook.

    Before: `message` es el texto crudo de `COMMIT_EDITMSG`.
    During: filtrado de lineas cuyo primer caracter no-espacio es `#`.
    After: devuelve el mensaje sin comentarios; no lanza.
    """
    return "\n".join(
        line for line in message.splitlines() if not line.lstrip().startswith("#")
    )


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Ejecuta git con lista de argumentos y devuelve el resultado crudo.

    Before: `repo` es una raiz de repositorio; `args` no contienen shell.
    During: `subprocess.run` con captura de stdout/stderr en bytes.
    After: devuelve CompletedProcess; no lanza por exit code distinto de cero.
    """
    return subprocess.run(  # noqa: S603
        [_GIT, "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )


def _decode_lines(raw: bytes) -> list[str]:
    """Convierte la salida de git en lineas no vacias.

    Before: `raw` es stdout de un comando de listado.
    During: decodifica UTF-8 con reemplazo y separa por lineas.
    After: devuelve las lineas sin vacios; no lanza.
    """
    return [line for line in raw.decode("utf-8", errors="replace").splitlines() if line]


def _source_files(repo: Path, source: str) -> list[str]:
    """Lista los ficheros visibles en una fuente git.

    Before: `source` es `INDEX`, `HEAD` o `HEAD^`.
    During: `git ls-files` para el indice; `git ls-tree -r --name-only` para
        commits. Un fallo (p. ej. HEAD inexistente en el primer commit) se
        trata como fuente vacia.
    After: devuelve rutas relativas con `/`; lista vacia si la fuente no existe.
    """
    if source == "INDEX":
        result = _run_git(repo, "ls-files")
    else:
        result = _run_git(repo, "ls-tree", "-r", "--name-only", source)
    if result.returncode != 0:
        return []
    return _decode_lines(result.stdout)


def _blob(repo: Path, source: str, path: str) -> bytes | None:
    """Lee un blob de git sin tocar el working tree.

    Before: `source` es `INDEX`, `HEAD` o `HEAD^`; `path` es relativo al repo.
    During: `git show <source>:<path>` en modo binario. El indice se nombra con
        la sintaxis vacia de git (`:path`), no con la etiqueta interna `INDEX`.
    After: devuelve los bytes exactos del blob, o None si no existe.
    """
    spec = f":{path}" if source == "INDEX" else f"{source}:{path}"
    result = _run_git(repo, "show", spec)
    if result.returncode != 0:
        return None
    return result.stdout


def _resolve_import(raw: str, importer: str, files: set[str]) -> str | None:
    """Resuelve una ruta `@import` contra la lista de ficheros de la fuente.

    Before: `raw` es el token tras `@`; `importer` es la ruta del fichero que
        importa; `files` son las rutas visibles en la fuente git.
    During: normaliza separadores y `..`; prueba primero la raiz del repo y
        despues relativa al directorio del importador.
    After: devuelve la ruta canonica presente en `files`, o None si no existe.
    """
    candidate = raw.replace("\\", "/")
    while candidate.startswith("./"):
        candidate = candidate[2:]
    candidate = candidate.lstrip("/")
    if candidate in files:
        return candidate
    alternate = posixpath.normpath(
        posixpath.join(posixpath.dirname(importer), candidate)
    )
    if alternate in files:
        return alternate
    return None


def _closure(repo: Path, source: str, files: set[str]) -> tuple[frozenset[str], int]:
    """Resuelve el cierre transitivo de `@imports` de `CLAUDE.md` en una fuente.

    Before: `files` es la lista de ficheros visibles en `source`.
    During: recorre `CLAUDE.md`, lee cada blob y acumula CHARs decodificados.
        Un import declarado pero ausente en la fuente es un error de medicion
        (no se inventa un 0 silencioso). Un set de visitados corta ciclos.
    After: devuelve (ficheros del cierre, total de chars); lanza MeasurementError
        si un blob esperado no se puede leer.
    """
    if "CLAUDE.md" not in files:
        return frozenset(), 0
    visited: set[str] = set()
    queue: list[str] = ["CLAUDE.md"]
    total_chars = 0
    while queue:
        rel = queue.pop(0)
        if rel in visited:
            continue
        if rel not in files:
            raise MeasurementError(f"import declarado pero ausente: {rel}")
        raw = _blob(repo, source, rel)
        if raw is None:
            raise MeasurementError(f"blob ilegible en {source}:{rel}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MeasurementError(f"blob no UTF-8 en {source}:{rel}: {exc}") from exc
        visited.add(rel)
        total_chars += len(text)
        for line in text.splitlines():
            match = _IMPORT_RE.match(line)
            if not match:
                continue
            resolved = _resolve_import(match.group(1), rel, files)
            if resolved is None:
                raise MeasurementError(
                    f"import no resuelto en {source}:{rel} -> {match.group(1)}"
                )
            queue.append(resolved)
    return frozenset(visited), total_chars


def measure_snapshot(source: str, repo: Path | None = None) -> Metrics:
    """Mide la cuspide en `INDEX`, `HEAD` o `HEAD^` desde blobs git.

    Before: `source` es una de las tres fuentes; `repo` permite apuntar a un
        fixture hermetico (por defecto, la raiz del motor).
    During: lista los ficheros de la fuente, suma BYTES de cada `AGENTS.md` y
        resuelve el cierre de `CLAUDE.md` en CHARS. No lee el working tree.
    After: devuelve Metrics; una fuente inexistente (primer commit) mide 0.
    """
    root = repo or MOTOR_ROOT
    files = set(_source_files(root, source))
    agents_files = tuple(
        sorted(f for f in files if posixpath.basename(f) == "AGENTS.md")
    )
    agents_bytes = 0
    for rel in agents_files:
        raw = _blob(root, source, rel)
        if raw is None:
            raise MeasurementError(f"blob ilegible en {source}:{rel}")
        agents_bytes += len(raw)
    closure, claude_chars = _closure(root, source, files)
    cuspide = frozenset(set(agents_files) | set(closure))
    return Metrics(
        source=source,
        agents_bytes=agents_bytes,
        claude_chars=claude_chars,
        cuspide_files=cuspide,
        agents_files=agents_files,
    )


def verdict_growth(pre: Metrics, post: Metrics) -> Growth:
    """Aplica la formula de growth y el umbral de cap, sin floats de borde.

    Before: `pre` y `post` son snapshots de la misma fuente del grafo.
    During: calcula deltas y compara ENTEROS contra los caps (`> 1.0x` es
        equivalente exacto a `X > gate`, sin ruido de punto flotante).
    After: devuelve Growth; `over_cap` (algun ratio > 1.0x) distingue QUE
        mensaje de BLOCK emite `_run_commit_msg` (WOT-2026-116a: ambos casos
        -- over_cap y no -- bloquean; over_cap ya no degrada a WARN).
    """
    delta_bytes = post.agents_bytes - pre.agents_bytes
    delta_chars = post.claude_chars - pre.claude_chars
    grew = delta_bytes > 0 or delta_chars > 0
    over_cap = (
        post.agents_bytes > GATE_CODEX_BYTES
        or post.claude_chars > ORCHESTRATOR_CLAUDE_CUSP_MAX_CHARS
    )
    return Growth(
        delta_bytes=delta_bytes,
        delta_chars=delta_chars,
        grew=grew,
        over_cap=over_cap,
    )


def growth_lines(pre: Metrics, post: Metrics, growth: Growth) -> list[str]:
    """Construye las lineas de diagnostico con deltas y ratios POST.

    Before: los snapshots y el veredicto ya estan calculados.
    During: formatea bytes y chars en su unidad nativa; los ratios PRE no se
        imprimen porque no deciden el veredicto.
    After: devuelve lineas estables (los tests extraen `delta_*` y `ratio_*_post`).
    """
    ratio_codex = post.agents_bytes / GATE_CODEX_BYTES
    ratio_cc = post.claude_chars / ORCHESTRATOR_CLAUDE_CUSP_MAX_CHARS
    return [
        (
            f"  AGENTS.md (Codex, bytes): {pre.agents_bytes} -> {post.agents_bytes} "
            f"(delta_bytes={growth.delta_bytes:+d}, "
            f"ratio_codex_post={ratio_codex:.4f})"
        ),
        (
            "  cierre CLAUDE.md (Claude Code, chars): "
            f"{pre.claude_chars} -> {post.claude_chars} "
            f"(delta_chars={growth.delta_chars:+d}, "
            f"ratio_cc_post={ratio_cc:.4f})"
        ),
    ]


def _layer2_files(touched: Iterable[str]) -> set[str]:
    """Filtra las rutas de capa 2 tocadas por el diff.

    Before: `touched` son rutas relativas del diff.
    During: selecciona `.agent/rules/common/*.md`.
    After: devuelve el subconjunto; no lanza.
    """
    return {
        f for f in touched if f.startswith(LAYER2_PREFIX) and f.endswith(LAYER2_SUFFIX)
    }


def verdict_drift(
    touched: set[str], cuspide_files: set[str] | None = None
) -> str | None:
    """Heuristica WARN-only de drift cuspide <-> capa 2 sobre el diff ya resuelto.

    Before: `touched` es el diff de la fase; `cuspide_files` es el cierre ya
        medido (si es None se mide el indice, util para uso aislado).
    During: XOR entre "toca la cuspide" y "toca `.agent/rules/common/*.md`".
    After: devuelve una linea de diagnostico, o None si no hay drift.
    """
    cuspide = (
        cuspide_files
        if cuspide_files is not None
        else measure_snapshot("INDEX").cuspide_files
    )
    touched_cuspide = set(touched) & set(cuspide)
    touched_layer2 = _layer2_files(touched)
    if bool(touched_cuspide) == bool(touched_layer2):
        return None
    if touched_cuspide:
        return (
            "la cuspide se movio sin su capa 2 "
            f"(cuspide={sorted(touched_cuspide)}, capa2=[])"
        )
    return (
        "la capa 2 se movio sin la cuspide "
        f"(cuspide=[], capa2={sorted(touched_layer2)})"
    )


def _strip_comment_lines(message: str) -> list[str]:
    """Devuelve las lineas utiles del mensaje ya sin comentarios.

    Before: `message` es el texto crudo.
    During: aplica `strip_comments` y separa por lineas.
    After: lista de lineas; no lanza.
    """
    return strip_comments(message).splitlines()


def parse_override(message: str) -> Override | None:
    """Parsea la gramatica exacta del override en el mensaje de commit.

    Before: `message` es el texto crudo de `COMMIT_EDITMSG` o `git log -1 -%B`.
    During: elimina comentarios `#`, busca la linea exacta
        `GATE-OVERRIDE: cuspide_growth` y un `REASON:` no vacio a <= 3 lineas.
        `AFFECTED:` es opcional y solo se guarda.
    After: devuelve Override, o None si falta el marcador, el REASON o ambos.
    """
    lines = _strip_comment_lines(message)
    for index, line in enumerate(lines):
        if not _OVERRIDE_RE.match(line):
            continue
        reason: str | None = None
        affected: str | None = None
        for candidate in lines[index + 1 : index + 4]:
            reason_match = _REASON_RE.match(candidate)
            if reason_match and reason is None:
                reason = reason_match.group(1).strip()
        for candidate in lines[index + 1 : index + 5]:
            affected_match = _AFFECTED_RE.match(candidate)
            if affected_match and affected is None:
                affected = affected_match.group(1)
        if reason:
            return Override(reason=reason, affected=affected)
        return None
    return None


def has_override_marker(message: str) -> bool:
    """Indica si el mensaje declara el marcador aunque le falte el REASON.

    Before: `message` es el texto crudo.
    During: misma regla de comentarios que `parse_override`.
    After: True si alguna linea es el marcador exacto; no lanza.
    """
    return any(_OVERRIDE_RE.match(line) for line in _strip_comment_lines(message))


def _staged_touched(repo: Path) -> set[str]:
    """Diff staged-vs-HEAD para pre-commit y commit-msg.

    Before: `repo` es la raiz del repositorio.
    During: `git diff --cached --name-only` (funciona tambien sin HEAD).
    After: devuelve el conjunto de rutas; vacio si git falla.
    """
    result = _run_git(repo, "diff", "--cached", "--name-only")
    if result.returncode != 0:
        return set()
    return set(_decode_lines(result.stdout))


def _commit_touched(repo: Path, revision: str = "HEAD") -> set[str]:
    """Diff del commit aterrizado, incluido el primer commit (sin padre).

    Before: `revision` apunta a un commit existente.
    During: `git diff-tree --root -r --no-commit-id --name-only`.
    After: devuelve el conjunto de rutas; vacio si git falla.
    """
    result = _run_git(
        repo,
        "diff-tree",
        "--root",
        "-r",
        "--no-commit-id",
        "--name-only",
        revision,
    )
    if result.returncode != 0:
        return set()
    return set(_decode_lines(result.stdout))


def _commit_message(repo: Path) -> str:
    """Lee el mensaje del commit HEAD.

    Before: existe HEAD.
    During: `git log -1 --pretty=%B`.
    After: devuelve el mensaje (posiblemente vacio); no lanza.
    """
    result = _run_git(repo, "log", "-1", "--pretty=%B")
    return result.stdout.decode("utf-8", errors="replace").strip()


def _merge_base(repo: Path, base: str = "origin/main", head: str = "HEAD") -> str:
    """Resuelve el punto real de divergencia entre `base` y `head` (WOT-2026-116a).

    Before: `repo` es la raiz del repositorio; `base` puede no existir (remoto
        ausente, fixture hermetico, primer commit sin remoto configurado).
    During: `git merge-base <base> <head>`.
    After: devuelve el SHA del merge-base, o cadena vacia si no resuelve; el
        llamador decide el fallback (nunca lanza).
    """
    result = _run_git(repo, "merge-base", base, head)
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


def _rev(repo: Path, revision: str) -> str:
    """Resuelve una revision a SHA.

    Before: `revision` puede no existir (primer commit).
    During: `git rev-parse`.
    After: devuelve el SHA, o cadena vacia si no resuelve.
    """
    result = _run_git(repo, "rev-parse", revision)
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


def _touches_cuspide(touched: set[str], cuspide_files: set[str]) -> bool:
    """Decide si el diff dispara la fase de growth.

    Before: `touched` es el diff; `cuspide_files` el cierre medido.
    During: interseccion directa, mas cualquier `AGENTS.md`/`CLAUDE.md` por
        nombre (cubre el caso en que el fichero no exista en una fuente).
    After: True si el commit puede afectar a la cuspide.
    """
    if touched & set(cuspide_files):
        return True
    return any(posixpath.basename(f) in {"AGENTS.md", "CLAUDE.md"} for f in touched)


def _append_audit(repo: Path, entry: dict[str, object]) -> None:
    """Appendea una linea JSON al canal local de telemetria.

    Before: `entry` ya esta completo; el canal es gitignored.
    During: crea el directorio si falta y escribe una unica linea con LF
        explicito (evita el MIXTO medido en Windows).
    After: no devuelve nada; una excepcion la captura el llamador (exit 0).
    """
    path = repo / AUDIT_LOG_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(line)


_OVERRIDE_GRAMMAR = [
    "  Override valido (lineas completas del mensaje, sin '#'):",
    "",
    "      GATE-OVERRIDE: cuspide_growth",
    "      REASON: <justificacion de una linea, no vacia>",
    "",
]


def _growth_message_lines() -> list[str]:
    """Instruccion self-service con la gramatica exacta del override.

    Before: hay growth sobre-ratio.
    During: devuelve una copia del bloque que el usuario debe pegar.
    After: no muta la constante compartida; no lanza.
    """
    return list(_OVERRIDE_GRAMMAR)


def _report_block(pre: Metrics, post: Metrics, growth: Growth) -> None:
    """Imprime el BLOCK autoritativo de growth dentro de caps.

    Before: hay grew Y ambos ratio_post <= 1.0x.
    During: escribe el header y las metricas en stderr.
    After: no devuelve nada; el llamador decide el exit 1.
    """
    print(
        f"{MARKER} BLOCK: el commit hace crecer la cuspide y AMBOS ratios "
        "post estan <= 1.0x (el override ya no exceptua).",
        file=sys.stderr,
    )
    for line in growth_lines(pre, post, growth):
        print(line, file=sys.stderr)


def _report_block_debt(pre: Metrics, post: Metrics, growth: Growth) -> None:
    """Imprime el BLOCK del escalon "no crecer nunca, incluso en deuda" (WOT-2026-116a).

    Before: hay grew Y al menos un ratio_post > 1.0 (la cuspide ya esta sobre
        cap, "en deuda"). Antes de este ticket este caso era WARN (exit 0);
        ahora bloquea tambien, como escalon ADICIONAL al BLOCK dentro-de-cap.
    During: escribe el header y las metricas en stderr.
    After: no devuelve nada; el llamador decide el exit 1.
    """
    print(
        f"{MARKER} BLOCK: el commit hace crecer la cuspide con la cuspide YA "
        "en deuda (al menos un ratio_post > 1.0). Politica 'no crecer nunca, "
        "incluso en deuda' (WOT-2026-116a): el override tampoco exceptua.",
        file=sys.stderr,
    )
    for line in growth_lines(pre, post, growth):
        print(line, file=sys.stderr)


def _run_pre_commit(repo: Path) -> int:
    """Fase pre-commit: early warning, nunca bloquea.

    Before: el indice contiene el commit candidato (puede no haber HEAD).
    During: mide HEAD vs INDEX, imprime growth y ratios.
    After: exit 0 siempre; silencio si el diff no toca la cuspide ni la capa 2.
    """
    touched = _staged_touched(repo)
    pre = measure_snapshot("HEAD", repo)
    post = measure_snapshot("INDEX", repo)
    cuspide = set(pre.cuspide_files) | set(post.cuspide_files)
    if not _touches_cuspide(touched, cuspide) and not _layer2_files(touched):
        return 0
    growth = verdict_growth(pre, post)
    if growth.grew:
        if growth.over_cap:
            print(
                f"{MARKER} EARLY WARNING: growth con al menos un ratio_post > 1.0; "
                "esta fase NO bloquea (el BLOCK vive en commit-msg).",
                file=sys.stderr,
            )
        else:
            print(
                f"{MARKER} WARN: growth con AMBOS ratios <= 1.0; BLOCK en commit-msg.",
                file=sys.stderr,
            )
        for line in growth_lines(pre, post, growth):
            print(line, file=sys.stderr)
    drift = verdict_drift(touched, cuspide)
    if drift:
        print(f"{MARKER} WARN drift: {drift}", file=sys.stderr)
    return 0


def _run_commit_msg(repo: Path, message_path: Path | None) -> int:
    """Fase commit-msg: BLOCK con dos escalones (G1 flip + WOT-2026-116a).

    Before: git entrega la ruta de `COMMIT_EDITMSG` como argv[1].
    During: re-deriva la medicion del indice (no confia en pre-commit).
            BLOCK (exit 1) si grew Y AMBOS ratios <= 1.0x (override ignorado,
            G1 flip, sin cambios en este ticket).
            BLOCK (exit 1) TAMBIEN si grew Y al menos un ratio > 1.0x --
            escalon ADICIONAL "no crecer nunca, incluso en deuda"
            (WOT-2026-116a): antes de este ticket era WARN (exit 0); el
            override tampoco exceptua aqui.
    After: exit 1 con cualquier growth (dentro o fuera de cap); exit 0 sin
        growth.
    """
    if message_path is None:
        print(
            f"{MARKER} sin ruta de mensaje; no hay override que evaluar (fail-open)",
            file=sys.stderr,
        )
        return 0

    touched = _staged_touched(repo)
    pre = measure_snapshot("HEAD", repo)
    post = measure_snapshot("INDEX", repo)
    cuspide = set(pre.cuspide_files) | set(post.cuspide_files)
    if not _touches_cuspide(touched, cuspide):
        return 0
    growth = verdict_growth(pre, post)
    if not growth.grew:
        return 0
    if not growth.over_cap:
        # Ambos ratios <= 1.0x -> BLOCK (flip: antes era WARN)
        _report_block(pre, post, growth)
        return 1

    # Al menos un ratio > 1.0x (en deuda) -> BLOCK tambien (WOT-2026-116a:
    # antes de este ticket era WARN, exit 0)
    _report_block_debt(pre, post, growth)
    return 1


def _run_post_commit(repo: Path) -> int:
    """Fase post-commit: telemetria de overrides ya aterrizados.

    Before: el commit ya existe; HEAD^ puede no existir (primer commit).
    During: mide el merge-base real con `origin/main` vs HEAD (WOT-2026-116a):
        un rebase o varios commits locales pueden dejar HEAD^ distinto del
        punto real de divergencia, lo que dejaria fuera growth repartido
        entre varios commits. Si `origin/main` no resuelve (remoto ausente,
        fixture hermetico, primer commit), degrada a HEAD^ -- mismo
        comportamiento que antes de este ticket. Lee el mensaje final y,
        solo si hay override + growth, appendea una linea al canal local.
    After: exit 0 siempre, incluso si el canal falla (la telemetria no revoca
        ni bloquea commits).
    """
    touched = _commit_touched(repo)
    merge_base = _merge_base(repo)
    pre_ref = merge_base or "HEAD^"
    pre = measure_snapshot(pre_ref, repo)
    post = measure_snapshot("HEAD", repo)
    cuspide = set(pre.cuspide_files) | set(post.cuspide_files)
    if not _touches_cuspide(touched, cuspide):
        return 0
    growth = verdict_growth(pre, post)
    if not growth.grew:
        return 0
    override = parse_override(_commit_message(repo))
    if override is None:
        return 0
    sha = _rev(repo, "HEAD")
    parent = _rev(repo, "HEAD^")
    entry: dict[str, object] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": "cuspide_override",
        "commit": sha,
        "parent": parent,
        "pre_ref": pre_ref,
        "delta_bytes": growth.delta_bytes,
        "delta_chars": growth.delta_chars,
        "ratio_codex_pre": pre.agents_bytes / GATE_CODEX_BYTES,
        "ratio_codex_post": post.agents_bytes / GATE_CODEX_BYTES,
        "ratio_cc_pre": pre.claude_chars / ORCHESTRATOR_CLAUDE_CUSP_MAX_CHARS,
        "ratio_cc_post": post.claude_chars / ORCHESTRATOR_CLAUDE_CUSP_MAX_CHARS,
        "reason": override.reason,
        "affected": override.affected,
    }
    try:
        _append_audit(repo, entry)
    except (OSError, ValueError, TypeError) as exc:
        print(
            f"{MARKER} no se pudo escribir {AUDIT_LOG_REL}: {exc} "
            "(telemetria, no bloquea)",
            file=sys.stderr,
        )
        return 0
    print(
        f"{MARKER} audit: override registrado en {AUDIT_LOG_REL} "
        f"commit={sha[:12] or '?'}",
        file=sys.stderr,
    )
    return 0


def _force_utf8_stderr() -> None:
    """Permite diagnosticos con acentos en consolas no UTF-8 (Windows).

    Before: stderr puede estar ligado a una codepage no UTF-8.
    During: reconfigura el stream cuando la implementacion lo soporta.
    After: no devuelve nada; degrada en silencio si no hay `reconfigure`.
    """
    with contextlib.suppress(AttributeError, OSError, ValueError):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _build_parser() -> argparse.ArgumentParser:
    """Construye el parser CLI de las tres fases.

    Before: sin estado previo.
    During: define `--phase`, el positional opcional del mensaje y el override
        de raiz para fixtures hermeticos.
    After: devuelve el parser listo para `parse_args`.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        required=True,
        choices=["pre-commit", "commit-msg", "post-commit"],
        help="Fase del hook que se ejecuta.",
    )
    parser.add_argument(
        "message",
        nargs="?",
        default=None,
        help="Ruta de COMMIT_EDITMSG (solo commit-msg).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Raiz del repo (default: raiz del motor; usado por los tests).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Despacha la fase y degrada a fail-open ante un error propio.

    Before: `argv` son los argumentos del hook (o de un test).
    During: resuelve la raiz y ejecuta la fase; cualquier error de medicion o
        de I/O se reporta en stderr y se convierte en exit 0.
    After: devuelve el exit code de la fase, o 0 si el guard se rompio.
    """
    _force_utf8_stderr()
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    repo = args.repo_root or MOTOR_ROOT
    try:
        if args.phase == "pre-commit":
            return _run_pre_commit(repo)
        if args.phase == "commit-msg":
            message_path = Path(args.message) if args.message else None
            return _run_commit_msg(repo, message_path)
        return _run_post_commit(repo)
    except MeasurementError as exc:
        print(f"{MARKER} error de medicion: {exc} (no bloquea)", file=sys.stderr)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"{MARKER} error propio del guard: {exc} (no bloquea)", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
