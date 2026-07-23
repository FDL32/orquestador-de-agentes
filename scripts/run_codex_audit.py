"""Run a Codex M4-recipe audit invocation and validate its output by CONTENT.

Before:
    - `codex` (the ChatGPT/Codex CLI, shim `codex.cmd` on Windows, bare
      `codex` on POSIX) is resolvable on PATH, or an explicit executable is
      injected via `codex_executable` / `--codex-executable` for testing.
    - Caller has a prompt string ready, either literal (`--prompt`), from a
      file (`--prompt-file`), or piped via stdin (default when neither flag
      is given and stdin is not a TTY).
During:
    - Builds the "M4" command around `codex exec`:
      `codex exec --sandbox read-only --skip-git-repo-check
      -c service_tier=fast -` (the trailing `-` sentinel tells `codex exec`
      to read the prompt from STDIN instead of argv). The prompt text is
      NOT part of argv: on Windows, `CreateProcess` has a ~32KB command-line
      limit ([WinError 206]), which a large audit prompt can exceed if
      passed positionally (reproduced in auditoria 19219, contrato+objetivo
      ~35KB).
    - Launches it with `subprocess.Popen(..., stdin=subprocess.PIPE,
      stdout=PIPE, stderr=PIPE, text=True, shell=False, encoding="utf-8",
      errors="replace")`, mirroring the productive shape measured in
      `scripts/ensemble_dispatch.py::_transport_agent` (Windows
      pipe-inheritance hang, 2026-07-16 smoke), and delivers the prompt via
      `proc.communicate(input=prompt, timeout=timeout)`. When `repo_root`
      is given (keyword-only, `str | Path | None`, default `None`), it is
      passed as `cwd=repo_root` to that `Popen` call, so `codex exec`'s own
      `rg`/`git grep` resolve relative paths against that tree instead of
      the parent process's inherited cwd (WOT-2026-038l: an agent with a
      filesystem must be told WHERE to search, not just WHAT to analyze).
      When `repo_root is None`, `cwd=` is NOT passed at all (today's
      inherited-cwd behavior is preserved exactly) and a single warning is
      emitted to STDERR noting that codex will see the inherited parent
      cwd; the warning never fires when `repo_root` is given, and never
      goes to STDOUT.
    - On `subprocess.TimeoutExpired`, kills the FULL process tree (Windows:
      `taskkill /T /F`; POSIX: `os.kill(pid, SIGKILL)`) before raising,
      replicating the minimal shape of
      `scripts/ensemble_dispatch.py::_kill_process_tree` (not imported: that
      module pulls in `agents_config` + sys.path mutation at import time,
      which is unwanted weight for this narrow helper).
After:
    - Returns a structured dict: `returncode` (int), `stdout` (str),
      `stdout_bytes` (int, `len(stdout.encode("utf-8", errors="replace"))`),
      `ok` (bool), `reason` (str), `failure_mode` (`str | None`).
    - `failure_mode` distinguishes an EXHAUSTED QUOTA from a generic
      failure (WOT-2026-027g). The quota banner goes to STDERR while stdout
      stays non-empty, so the "0 bytes = dead" rule below never fires for
      it and the bare returncode cannot tell it apart from a crash.
    - CEM hard-won lesson encoded here: exit code is NOT the verdict (codex
      can exit 0 on an Auth Error). The caller must validate by CONTENT.
      Per CEM, 0 bytes of stdout means the backend is DEAD (529), regardless
      of returncode. That case is UNAMBIGUOUS: this helper raises
      `CodexAuditEmptyOutputError` (a `RuntimeError` subclass) instead of
      returning `ok=False`, so a caller cannot silently ignore it by
      forgetting to check a dict key. All other outcomes (non-empty stdout,
      any returncode) return normally with `ok` reflecting `returncode == 0`
      and `reason` explaining the verdict.
    - CLI (`main`): exit 0 on non-empty output regardless of the wrapped
      command's own returncode (the wrapped returncode is reported in the
      printed JSON, per "exit code is not the verdict"); exit 2 on the
      0-bytes/dead case; exit 1 on invocation errors (e.g. codex binary not
      found, timeout).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_CODEX_EXECUTABLE = "codex.cmd" if os.name == "nt" else "codex"
DEFAULT_TIMEOUT = 300
M4_ARGS = [
    "exec",
    "--sandbox",
    "read-only",
    "--skip-git-repo-check",
    "-c",
    "service_tier=fast",
]


# WOT-2026-027g: patrones de CUOTA AGOTADA en stderr. El banner real medido
# en vivo (2026-07-21, 8 invocaciones consecutivas) es "You have hit your
# usage limit."; los otros dos cubren las variantes de rate-limit/quota que
# emite la misma familia de backends. Se casan sobre stderr en minusculas.
#
# Por que hace falta un detector y no basta el rc: en este fallo stdout NO
# queda vacio (codex ya habia emitido texto), asi que el contrato "0 bytes =
# backend muerto" no lo caza, y el rc=1 es indistinguible del de un crash
# cualquiera. Sin mirar el PATRON de stderr, cuota y panic son el mismo
# fallo generico.
# "quota" a SECAS no esta en la lista a proposito (hallazgo convergente de las
# lentes deepseek y gemma4, CONFIRMADO midiendo: casaba "disk quota exceeded"
# y "user quota configuration invalid", que no son cuota de backend). Se exige
# el termino acompanado, que es como lo emiten los backends reales.
_QUOTA_STDERR_PATTERNS = (
    "usage limit",
    "quota exceeded",
    "quota reached",
    "out of quota",
    "insufficient quota",
    "rate limit",
)

# Frases de cuota que NO son de backend cuando aparecen con este SUJETO
# (disco/fs/inodos). Se evaluan DENTRO de la misma linea diagnostica, nunca
# sobre el stderr entero.
_NOT_BACKEND_QUOTA_CONTEXTS = (
    "disk quota",
    "disk space",
    "quota configuration",
    "filesystem quota",
    "inode",
)

# Prefijos que marcan una linea de DIAGNOSTICO del proceso, por oposicion al
# cuerpo (que en codex incluye el prompt ECHOADO). Ver `_diagnostic_lines`.
_DIAGNOSTIC_LINE_PREFIXES = (
    "error:",
    "warning:",
    "fatal:",
    "stream error:",
)


def _diagnostic_lines(stderr: str) -> list[str]:
    """Lineas de DIAGNOSTICO del stderr, descartando el cuerpo echoado.

    Before: `stderr` es el texto crudo capturado del proceso.
    During: parte en lineas y conserva solo las que empiezan por un prefijo
        de `_DIAGNOSTIC_LINE_PREFIXES` (en minusculas, ignorando sangria).
    After: retorna la lista de lineas diagnosticas en minusculas (vacia si
        no hay ninguna).

    POR QUE EXISTE (hallazgo de Codex en el MANAGER_REVIEW de
    WOT-2026-027g, verificado midiendo): `codex exec` ECHOA el prompt
    ENTERO por stderr. Tratar ese stderr como una BOLSA DE TEXTO y buscar
    patrones por presencia global es incorrecto en las DOS direcciones:
      - falso POSITIVO: un fallo generico cuyo prompt echoado mencione
        "usage limit" (p.ej. el bundle de review de ESTE ticket) se
        etiquetaba como cuota;
      - falso NEGATIVO: una exclusion global ("disk quota") presente en el
        material bajo revision anulaba un banner de cuota autentico.
    Anclar en la LINEA diagnostica cierra ambas: el material auditado vive
    en lineas sin prefijo y deja de contaminar la clasificacion.
    """
    lines = []
    for raw_line in (stderr or "").splitlines():
        line = raw_line.strip().lower()
        if line.startswith(_DIAGNOSTIC_LINE_PREFIXES):
            lines.append(line)
    return lines


def _detect_failure_mode(stderr: str) -> str | None:
    """Clasifica el stderr en un failure_mode conocido, o None.

    Before: `stderr` es el texto capturado del proceso (puede ser vacio).
    During: casa en minusculas contra `_QUOTA_STDERR_PATTERNS`; no toca red
        ni disco.
    After: retorna `"quota"` si ALGUNA linea DIAGNOSTICA anuncia cuota de
        backend agotada, `None` en cualquier otro caso (stderr vacio, fallo
        generico con el mismo returncode, cuota que no es de backend --de
        disco/fs--, o mencion de cualquiera de esos terminos en el cuerpo
        echoado). La distincion es por CONTENIDO y POR LINEA, nunca por rc
        ni por la mera presencia de stderr.

        UNIDAD DE DECISION = LA LINEA, no el stderr entero (hallazgo de
        Codex, verificado midiendo): `codex exec` echoa el prompt completo
        por stderr, asi que una busqueda global se contamina con el
        material bajo revision en AMBAS direcciones. Cada linea diagnostica
        se juzga sola: si nombra un sujeto no-backend (disco, fs, inodos)
        no cuenta, y si no, basta un patron de cuota para clasificar. Asi
        "disk quota exceeded" y "quota exceeded for this organization"
        pueden convivir en el mismo stderr y solo la segunda decide.
    """
    for line in _diagnostic_lines(stderr):
        if any(context in line for context in _NOT_BACKEND_QUOTA_CONTEXTS):
            continue
        if any(pattern in line for pattern in _QUOTA_STDERR_PATTERNS):
            return "quota"
    return None


class CodexAuditEmptyOutputError(RuntimeError):
    """Raised when the codex invocation produced 0 bytes of stdout.

    Per CEM: 0 bytes of output means the backend is DEAD (529), even if the
    process exited with returncode 0. Exit code is not the verdict; content
    is. Callers MUST handle this exception explicitly rather than trusting a
    dict-shaped `ok` flag that could be overlooked.
    """


def _kill_process_tree(pid: int) -> None:
    """Kill the FULL process tree of `pid` (Windows: taskkill /T /F).

    Minimal replica of `scripts/ensemble_dispatch.py::_kill_process_tree`
    (not imported to avoid that module's import-time sys.path mutation and
    `agents_config` dependency). Same rationale: `codex exec` via the
    `.cmd` shim on Windows spawns `node.exe`, which inherits the pipes; a
    plain kill of the direct child leaves `communicate()` blocked forever
    waiting on EOF from the surviving descendant (measured 2026-07-16).
    """
    if os.name == "nt":
        taskkill = (
            Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
            / "System32"
            / "taskkill.exe"
        )
        subprocess.run(  # noqa: S603
            [str(taskkill), "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=30,
            shell=False,
        )
    else:  # pragma: no cover -- non-Windows branch
        import contextlib
        import signal

        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


def run_codex_audit(
    prompt: str,
    *,
    codex_executable: str = DEFAULT_CODEX_EXECUTABLE,
    timeout: int = DEFAULT_TIMEOUT,
    extra_args: list[str] | None = None,
    repo_root: str | Path | None = None,
) -> dict:
    """Run `codex exec` with the M4 recipe and validate output by content.

    Before: `codex_executable` must be resolvable (bare name via PATH, or an
        injected path/script for tests). `prompt` is the audit instruction
        text delivered to `codex exec` via STDIN (not argv), to avoid
        Windows' ~32KB `CreateProcess` command-line limit ([WinError 206])
        on large prompts. `repo_root` (keyword-only, `str | Path | None`,
        default `None`) is the absolute tree codex should search from; if
        `None`, codex inherits the parent process's cwd (today's behavior).
    During: builds `[codex_executable, *M4_ARGS, *extra_args, "-"]` (the
        `-` sentinel tells `codex exec` to read the prompt from stdin) and
        runs it via `subprocess.Popen` with `stdin=PIPE`, passing
        `cwd=repo_root` ONLY when `repo_root is not None` (an omitted
        `cwd=` preserves the exact inherited-cwd behavior of before this
        param existed), sending `prompt` through
        `proc.communicate(input=prompt, timeout=timeout)` and capturing
        stdout+stderr as text (UTF-8, replace-on-error). When `repo_root is
        None`, emits ONE warning to STDERR (never STDOUT) noting codex will
        see the inherited parent cwd. On timeout, kills the process tree
        and re-raises as `TimeoutError` with diagnostic context (no silent
        success is invented).
    After: on 0-byte stdout, raises `CodexAuditEmptyOutputError` (backend is dead
        per CEM), regardless of returncode. Otherwise returns a dict with
        `returncode`, `stdout`, `stdout_bytes`, `ok` (`returncode == 0`),
        `reason`, and `failure_mode` (`"quota"` when stderr carries the
        usage-limit banner, else `None`; always `None` when `ok`).
        WOT-2026-027g: the quota failure is NOT covered by the 0-bytes
        contract -- stdout stays non-empty and the banner travels on stderr,
        so without classifying by PATTERN it is indistinguishable from any
        other non-zero exit.
    """
    if repo_root is None:
        print(
            "WARNING: run_codex_audit: no repo_root given; codex will see "
            "the inherited parent cwd, not a declared search tree "
            "(WOT-2026-038l)",
            file=sys.stderr,
        )

    cmd = [codex_executable, *M4_ARGS, *(extra_args or []), "-"]
    popen_kwargs = {}
    if repo_root is not None:
        popen_kwargs["cwd"] = repo_root
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        text=True,
        shell=False,
        encoding="utf-8",
        errors="replace",
        **popen_kwargs,
    )
    try:
        out, err = proc.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid)
        raise TimeoutError(
            f"codex exec timed out after {timeout}s; process tree killed "
            "(pipe-inheritance hang, see ensemble_dispatch.py 2026-07-16)"
        ) from None

    stdout = out or ""
    stdout_bytes = len(stdout.encode("utf-8", errors="replace"))

    if stdout_bytes == 0:
        raise CodexAuditEmptyOutputError(
            f"codex exec returned 0 bytes of stdout (returncode={proc.returncode}); "
            "0 bytes = backend dead (529), regardless of exit code. "
            f"stderr={err or ''!r}"
        )

    returncode = proc.returncode
    ok = returncode == 0
    # WOT-2026-027g: se clasifica SOLO en el camino de fallo. Un rc=0 nunca
    # lleva etiqueta, aunque el stderr contenga ruido que case el patron.
    failure_mode = None if ok else _detect_failure_mode(err or "")
    if ok:
        reason = "codex exec succeeded: non-empty stdout, returncode 0"
    elif failure_mode == "quota":
        reason = (
            f"codex exec sin cuota (usage limit) segun stderr, exit {returncode}; "
            "no es un fallo generico: reintentar mas tarde o rotar de backend"
        )
    else:
        reason = (
            f"codex exec returned non-zero exit ({returncode}) but produced "
            "non-empty stdout; content preserved, exit code is not the verdict"
        )
    return {
        "returncode": returncode,
        "stdout": stdout,
        "stdout_bytes": stdout_bytes,
        "ok": ok,
        "reason": reason,
        "failure_mode": failure_mode,
    }


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    if args.prompt_file is not None:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise SystemExit(
            "no prompt provided: use --prompt, --prompt-file, or pipe via stdin"
        )
    return sys.stdin.read()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a Codex M4-recipe audit (codex exec --sandbox read-only "
            "--skip-git-repo-check -c service_tier=fast) and validate the "
            "result by CONTENT, not exit code."
        )
    )
    prompt_group = parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt", help="Literal prompt text.")
    prompt_group.add_argument(
        "--prompt-file", help="Path to a file containing the prompt text."
    )
    parser.add_argument(
        "--codex-executable",
        default=DEFAULT_CODEX_EXECUTABLE,
        help=f"Codex executable to invoke (default: {DEFAULT_CODEX_EXECUTABLE}).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help=(
            "Absolute tree codex should search from (passed as cwd= to the "
            "Popen). If omitted, codex inherits the parent process's cwd "
            "and a warning is printed to stderr (WOT-2026-038l)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint.

    Before: argv holds an optional --prompt / --prompt-file / stdin source.
    During: reads the prompt, invokes `run_codex_audit`, prints a JSON
        result to stdout.
    After: exit 0 when stdout was non-empty (regardless of the wrapped
        codex process's own returncode, which is reported inside the JSON
        body per "exit code is not the verdict"); exit 2 when codex
        produced 0 bytes of stdout (backend dead, CodexAuditEmptyOutputError);
        exit 1 on any other invocation error (binary not found, timeout).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        prompt = _read_prompt(args)
    except SystemExit as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        result = run_codex_audit(
            prompt,
            codex_executable=args.codex_executable,
            timeout=args.timeout,
            repo_root=args.repo_root,
        )
    except CodexAuditEmptyOutputError as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}, indent=2))
        return 2
    except (TimeoutError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0 if result["ok"] or result["stdout_bytes"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
