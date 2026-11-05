"""Build a fail-closed, portable review bundle for one flight ticket.

Before: the caller supplies a ticket, base and tip, explicit repository paths,
an FLT, a verification receipt, and an explicit bundle limit.
During: the module resolves commits with argv-only subprocesses, validates the
``verify_delivery`` JSON, checks the declared scope, and writes one bundle.
After: rc 0 means the complete bundle was written; rc 1 means the requested
generation failed; a prior bundle is removed before validation unless the
output is rejected or cannot be removed; rc 2 means invalid CLI input.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any


Runner = Callable[..., subprocess.CompletedProcess[str]]
CURRENT_TICKET_RE = re.compile(r"^WOT-\d{4}-\d+[a-z](?:-[0-9]+)?$")
FOREIGN_TICKET_RE = re.compile(r"\bWOT-\d{4}-\d+[a-z](?:-[0-9]+)?\b")
PATH_LINE_RE = re.compile(r"^\S+:\d+$")
COMMAND_RC_RE = re.compile(r"(?:\brc\s+\d+|\brc=\d+)\s*$", re.IGNORECASE)


class BuildError(ValueError):
    """A user-visible contract failure that must not create a bundle."""


def _is_exact_zero_rc(value: object) -> bool:
    """Return whether a receipt rc is the exact integer zero.

    Before: ``value`` is an untrusted JSON scalar from a delivery receipt.
    During: checks the concrete type before comparing its numeric value.
    After: returns true only for ``int`` zero, excluding booleans and floats.
    """

    return type(value) is int and value == 0


def _run(
    runner: Runner,
    command: Sequence[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one argv command without a shell.

    Before: ``command`` contains a real executable and separate arguments.
    During: calls the injected runner with text capture and no shell parsing.
    After: returns the producer result; OSError is allowed to identify a
    missing executable or cwd to the caller.
    """

    return runner(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )


def _git(
    runner: Runner, repo: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    """Run git against ``repo`` using argv and an explicit cwd.

    Before: ``repo`` is an existing directory and ``arguments`` are git argv.
    During: invokes the real or injected runner with ``git -C repo``.
    After: returns git's captured result without converting failures to success.
    """

    return _run(runner, ["git", "-C", str(repo), *arguments])


def _require_path(raw: str | Path, *, directory: bool = False) -> Path:
    """Resolve an explicit path and reject missing or wrong-kind inputs.

    Before: ``raw`` is a non-empty CLI path supplied by the caller.
    During: resolves it independently of the process cwd and checks its kind.
    After: returns an absolute path, or raises ``BuildError`` with a stable
    diagnostic for fail-closed handling.
    """

    raw_text = str(raw)
    if not raw_text.strip():
        raise BuildError("ruta vacia")
    path = Path(raw_text).expanduser().resolve()
    if not path.exists():
        raise BuildError(f"ruta inexistente: {path}")
    if directory and not path.is_dir():
        raise BuildError(f"no es directorio: {path}")
    if not directory and not path.is_file():
        raise BuildError(f"no es fichero: {path}")
    return path


def _resolve_commit(runner: Runner, repo: Path, raw: str) -> str:
    """Resolve and validate one commit reference.

    Before: ``repo`` is a git repository and ``raw`` is a user-supplied ref.
    During: asks git for a canonical 40-character commit id.
    After: returns the canonical id, or raises ``BuildError`` if git cannot
    resolve a commit object.
    """

    result = _git(runner, repo, "rev-parse", "--verify", f"{raw}^{{commit}}")
    commit = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise BuildError(f"ref de commit invalida: {raw}")
    return commit


def _read_backlog_row(backlog: Path, ticket: str) -> str:
    """Read exactly one literal ticket row from a backlog.

    Before: ``backlog`` is readable UTF-8 text and ``ticket`` is canonical.
    During: scans complete lines and matches the table-cell boundary.
    After: returns the row, or raises ``BuildError`` for missing/duplicate
    contracts; no fallback declaration is fabricated.
    """

    try:
        lines = backlog.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise BuildError(f"backlog ilegible: {exc}") from exc
    matches = [line for line in lines if f"| {ticket} |" in line]
    if len(matches) != 1:
        raise BuildError(f"fila de backlog ausente o duplicada: {ticket}")
    return matches[0]


def _validate_measurements(values: Sequence[str]) -> list[str]:
    """Validate coordinator evidence as path:line or command with rc.

    Before: ``values`` contains only explicit coordinator measurement lines.
    During: applies mechanical line-shape checks without trimming invalid text.
    After: returns normalized lines, or raises ``BuildError`` on the first
    non-measurement line.
    """

    if not values:
        raise BuildError("ALCANCE_COORDINADORA requiere al menos una medicion")
    if any("\n" in value or "\r" in value for value in values):
        raise BuildError("medicion de coordinadora invalida: multilinea")
    normalized = [value.strip() for value in values]
    for value in normalized:
        if not value or not (PATH_LINE_RE.match(value) or COMMAND_RC_RE.search(value)):
            raise BuildError(f"medicion de coordinadora invalida: {value!r}")
    return normalized


def _validate_scope_text(scope: str, ticket: str) -> str:
    """Validate an explicit ticket scope and reject foreign ticket prose.

    Before: ``scope`` is caller-provided text and ``ticket`` is canonical.
    During: requires covered DoD and limit labels and rejects another ticket id
    plus the known stale nocturnal declaration.
    After: returns normalized scope text or raises ``BuildError``.
    """

    text = scope.strip()
    if not text:
        raise BuildError("ALCANCE vacio")
    if "DoD" not in text or "LIMITE" not in text:
        raise BuildError("ALCANCE requiere DoD cubierto y LIMITE")
    foreign = [item for item in FOREIGN_TICKET_RE.findall(text) if item != ticket]
    if foreign or "3feae578" in text or "nocturnas" in text.lower():
        raise BuildError("ALCANCE contiene declaracion de otro ticket")
    return text


def _load_verify_json(
    path: Path,
    *,
    base: str,
    tip: str,
    flt: Sequence[str],
) -> dict[str, Any]:
    """Validate a ``verify_delivery`` receipt against this build request.

    Before: ``path`` is the producer's JSON receipt; base, tip and FLT are
    canonical expected values from the same delivery.
    During: parses the receipt and checks verdict/rc, both SHAs, exact FLT,
    and every applicable step status.
    After: returns the original JSON for embedding; absent, invalid, stale,
    red, or discrepant receipts raise ``BuildError``.
    """

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"verify JSON invalido o ausente: {exc}") from exc
    if not isinstance(payload, dict):
        raise BuildError("verify JSON no es objeto")
    if payload.get("verdict") != "GREEN" or not _is_exact_zero_rc(payload.get("rc")):
        raise BuildError("verify JSON no esta GREEN/rc=0")
    if payload.get("head_sha_start") != tip or payload.get("head_sha_end") != tip:
        raise BuildError("verify JSON obsoleto o tip discrepante")
    if payload.get("base_sha") != base:
        raise BuildError("verify JSON base discrepante")
    steps = payload.get("steps")
    if not isinstance(steps, dict):
        raise BuildError("verify JSON sin steps")
    flt_step = steps.get("flt")
    if not isinstance(flt_step, dict) or sorted(flt_step.get("paths", [])) != sorted(
        flt
    ):
        raise BuildError("verify JSON FLT discrepante")
    bad = [
        name
        for name, step in steps.items()
        if not isinstance(step, dict)
        or step.get("status") != "OK"
        or not _is_exact_zero_rc(step.get("rc"))
    ]
    if bad:
        raise BuildError(
            f"verify JSON contiene pasos no validos: {','.join(sorted(bad))}"
        )
    return payload


def _clone_at_tip(
    runner: Runner,
    source_repo: Path,
    clone_dir: Path,
    tip: str,
) -> None:
    """Create or update the disposable clone and require its exact tip.

    Before: source_repo is a readable git repo and clone_dir is an explicit
    disposable path. During: uses git argv to clone/fetch/checkout detached tip.
    After: clone HEAD equals tip; otherwise raises ``BuildError`` and callers
    must not write a bundle.
    """

    try:
        if not clone_dir.exists():
            clone_dir.parent.mkdir(parents=True, exist_ok=True)
            result = _run(
                runner,
                ["git", "clone", "--no-hardlinks", str(source_repo), str(clone_dir)],
            )
            if result.returncode != 0:
                raise BuildError("clone fallido")
        elif not clone_dir.is_dir():
            raise BuildError(f"clone no es directorio: {clone_dir}")
        fetch = _git(runner, clone_dir, "fetch", str(source_repo))
        if fetch.returncode != 0:
            raise BuildError("fetch del clon fallido")
        checkout = _git(runner, clone_dir, "checkout", "--detach", tip)
        if checkout.returncode != 0:
            raise BuildError("checkout del clon fallido")
        head = _git(runner, clone_dir, "rev-parse", "HEAD").stdout.strip()
    except OSError as exc:
        raise BuildError(f"proceso git no disponible: {exc}") from exc
    if head != tip:
        raise BuildError(f"HEAD del clon discrepante: {head} != {tip}")


def _prepare_output(output: Path) -> None:
    """Remove only a prior bundle, preserving unrelated output files.

    Before: ``output`` is the explicit destination path.
    During: identifies an existing regular bundle by its first line and removes
    it before validation can fail, while refusing unrelated files.
    After: no prior bundle remains, or a ``BuildError`` preserves the file.
    """

    if not output.exists():
        return
    if not output.is_file() or output.is_symlink():
        raise BuildError(f"salida existente no es un bundle: {output}")
    try:
        with output.open("r", encoding="utf-8", newline="") as handle:
            first_line = handle.readline()
    except (OSError, UnicodeError) as exc:
        raise BuildError(f"salida existente ilegible: {output}") from exc
    if not first_line.startswith("# BUNDLE "):
        raise BuildError(f"salida existente no es un bundle: {output}")
    try:
        output.unlink()
    except OSError as exc:
        raise BuildError(f"bundle previo no se pudo eliminar: {output}") from exc


def _validate_temporary_path(temporary: Path) -> None:
    """Reject an existing temporary path that could redirect or replace output.

    Before: ``temporary`` is the derived sibling path for the requested output.
    During: checks dangling links and existing non-regular filesystem objects.
    After: returns only when writing the temporary path is safe by kind.
    """

    if temporary.is_symlink():
        raise BuildError(f"temporal es un enlace simbolico: {temporary}")
    if temporary.exists() and not temporary.is_file():
        raise BuildError(f"temporal no es un fichero regular: {temporary}")


def build_bundle(
    *,
    ticket: str,
    base_ref: str,
    tip_ref: str,
    source_repo: str,
    clone_dir: str,
    output: str,
    backlog: str,
    verify_json: str,
    flt: Sequence[str],
    scope: str,
    coordinator_measurement: Sequence[str],
    bundle_limit_bytes: int,
    bundle_limit_source: str,
    part: bool,
    file_mode: bool,
    runner: Runner = subprocess.run,
) -> Path:
    """Build one complete review bundle.

    Before: the unresolved output component is rejected if it is a symbolic
    link; then output is resolved and any existing bundle at that path is
    removed or rejected before other validation; all remaining paths, contract fields,
    verification JSON, limit and FLT are explicit. During: validates the
    request, resolves refs, validates receipts and evidence, creates an
    exact-tip clone, obtains a full diff, and writes UTF-8 without truncation.
    After: returns output path; a failed requested generation has no prior
    bundle unless the output was rejected (not a bundle, link, directory, or
    unreadable) or could not be removed, and raises ``BuildError``.
    """

    raw_output = Path(output).expanduser()
    if raw_output.is_symlink():
        raise BuildError(f"salida es un enlace simbolico: {raw_output}")
    output_path = raw_output.resolve()
    _prepare_output(output_path)
    if not re.fullmatch(r"WOT-\d{4}-\d+[a-z](?:-[0-9]+)?", ticket):
        raise BuildError("ticket invalido")
    if bundle_limit_bytes <= 0 or not bundle_limit_source.strip():
        raise BuildError("limite y fuente de limite son obligatorios")
    if not flt:
        raise BuildError("FLT vacio")
    source = _require_path(source_repo, directory=True)
    backlog_path = _require_path(backlog)
    verify_path = Path(str(verify_json)).expanduser().resolve()
    clone_path = Path(clone_dir).expanduser().resolve()
    base = _resolve_commit(runner, source, base_ref)
    tip = _resolve_commit(runner, source, tip_ref)
    _read_backlog_row(backlog_path, ticket)
    receipt = _load_verify_json(verify_path, base=base, tip=tip, flt=flt)
    scope_text = _validate_scope_text(scope, ticket) if part else "NO ES PARTE"
    measurements = _validate_measurements(coordinator_measurement)
    _clone_at_tip(runner, source, clone_path, tip)
    diff_result = _git(runner, clone_path, "diff", base, tip)
    if diff_result.returncode != 0:
        raise BuildError("diff del clon fallido")
    diff = diff_result.stdout.replace("\r\n", "\n")
    diff_bytes = len(diff.encode("utf-8"))
    if file_mode:
        diff_block = (
            "MODO CON FICHEROS: el diff completo queda en el clon exacto; "
            "no se incrusta ni se trunca.\n"
            f"CLON: {clone_path}\n"
        )
    else:
        diff_block = f"DIFF UTF-8 ({diff_bytes} bytes)\n{diff}"
    row = _read_backlog_row(backlog_path, ticket)
    content = (
        f"# BUNDLE {ticket}\n\n"
        "INVENTARIO DE EVIDENCIA\n"
        f"TICKET: {ticket}\nBASE: {base}\nTIP: {tip}\n"
        f"BUNDLE_LIMIT_BYTES: {bundle_limit_bytes}\n"
        f"BUNDLE_LIMIT_SOURCE: {bundle_limit_source.strip()}\n"
        "\nALCANCE\n"
        f"{scope_text}\n\n"
        "ALCANCE_COORDINADORA\n"
        + "\n".join(f"- {item}" for item in measurements)
        + "\n\nFILA LITERAL\n"
        + row
        + "\n\nVERIFY_DELIVERY_JSON\n"
        + json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n\n"
        + diff_block
        + "\n"
    )
    content_bytes = len(content.encode("utf-8"))
    if content_bytes > bundle_limit_bytes:
        mode_hint = "; usa --file-mode" if not file_mode else ""
        raise BuildError(
            f"bundle excede limite: {content_bytes}>{bundle_limit_bytes}{mode_hint}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    _validate_temporary_path(temporary)
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(output_path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise BuildError(f"bundle no escrito: {exc}") from exc
    return output_path


def _parser() -> argparse.ArgumentParser:
    """Create the explicit, portable CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--tip", required=True)
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--clone-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--backlog", required=True)
    parser.add_argument("--verify-json", required=True)
    parser.add_argument("--flt", action="append", required=True)
    parser.add_argument("--scope", default="")
    parser.add_argument("--coordinator-measurement", action="append", required=True)
    parser.add_argument("--bundle-limit-bytes", type=int, required=True)
    parser.add_argument("--bundle-limit-source", required=True)
    parser.add_argument("--part", action="store_true")
    parser.add_argument("--file-mode", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and print a stable result.

    Before: argv contains only the explicit inputs accepted by ``_parser``.
    During: delegates to ``build_bundle`` and converts contract failures into
    rc 1 without a traceback; unexpected errors remain visible to development.
    After: rc 0 means one bundle exists; rc 1 means the requested generation
    failed, after prior-bundle cleanup unless output rejection or removal
    failure prevented that cleanup.
    """

    args = _parser().parse_args(argv)
    try:
        output = build_bundle(
            ticket=args.ticket,
            base_ref=args.base,
            tip_ref=args.tip,
            source_repo=args.source_repo,
            clone_dir=args.clone_dir,
            output=args.output,
            backlog=args.backlog,
            verify_json=args.verify_json,
            flt=args.flt,
            scope=args.scope,
            coordinator_measurement=args.coordinator_measurement,
            bundle_limit_bytes=args.bundle_limit_bytes,
            bundle_limit_source=args.bundle_limit_source,
            part=args.part,
            file_mode=args.file_mode,
        )
    except BuildError as exc:
        print(f"BUILD_FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"BUILD_OK: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
