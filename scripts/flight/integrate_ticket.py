#!/usr/bin/env python3
"""WOT-2026-143a: integra un ticket en la rama del vuelo DESPUES de auditar su ultimo commit.

El bucle de lentes se exige por TICKET sobre su estado final (opcion B del usuario). Un
`git merge --ff-only` no dispara ningun hook previo (medido: `pre-merge-commit` no corre en
un ff y el `exit 1` de `post-merge` no lo bloquea), asi que ningun hook puede autorizar la
integracion. Este wrapper ES el camino: resuelve el tip del ticket con la MISMA funcion que
el escritor de objetivos del cierre, corre la MISMA `audit()` que `prepush_check`, y solo
si da OK hace el ff y deja un recibo. El paso de cierre `integration_receipts` exige ese
recibo por cada objetivo no declarado en `HISTORIC_LOOP_DEBT`.

Before: `--project-root` es el destino (donde viven scorecard, emitted_nonces y el
    contrato del ticket) y `--motor-root` el worktree del vuelo donde se integra (por
    defecto, el toplevel git del cwd). El script puede vivir en OTRO checkout que el que se
    integra (el clon candidato): los imports salen de ESE checkout, que ya trae
    `_ticket_tip_sha`; el worktree del vuelo no necesita tener este fichero. El arbol
    TRACKED del motor debe estar limpio (los ficheros no versionados no cuentan).
During: `_process_ticket_targets` (el del escritor, con `HEAD..candidato` como ventana) da
    la linea de objetivo; `_parse_loop_execution_targets` + `_loop_accreditation_failures`
    (las de prepush) la auditan. El tip debe ser el HEAD del candidato: un commit posterior
    sin auditar no se integra. Solo con OK corre `git merge --ff-only`. `--attest` no
    fusiona: audita un tip que YA esta integrado a mano (debe ser ancestro del HEAD).
After: rc 0 integrado (o atestado) y recibo escrito de forma atomica en
    `<project-root>/.agent/runtime/integration_receipts/<tip40>.json` (fuera del repo motor;
    el destino lo ignora por `.agent/runtime/*`); rc 1 audit/ff/linealidad en rojo, sin merge
    y sin recibo; rc 2 no verificable (project-root ausente, arbol tracked sucio, git
    ilegible), sin merge y sin recibo: fail-closed. Primera linea de stdout = contrato.

El recibo es OPERACIONAL, no criptografico: quien puede escribir `.agent/runtime/` puede
fabricarlo. La barrera es por AUSENCIA: saltarse el wrapper deja un objetivo sin recibo y el
cierre lo caza; no impide un `git merge` a mano, lo hace visible.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

RECEIPT_SCHEMA = 1
RECEIPT_MODES = ("integrate", "attest")
RECEIPTS_REL = Path(".agent") / "runtime" / "integration_receipts"
_WRAPPER_AUTHORITY = "repo_motor"


def receipt_path(project_root: Path, tip: str) -> Path:
    """Before: `tip` es un SHA40. During: compone la ruta. After: `<root>/<RECEIPTS_REL>/<tip>.json`."""
    return project_root / RECEIPTS_REL / f"{tip}.json"


def write_receipt(project_root: Path, receipt: dict) -> Path:
    """Before: `receipt` lleva `tip`. During: escribe en un temporal del MISMO directorio y
    lo renombra (un lector nunca ve un recibo a medias). After: la ruta escrita; `OSError`
    si el destino no es escribible (el llamante lo convierte en rc 2, sin recibo)."""
    path = receipt_path(project_root, receipt["tip"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(receipt, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(tmp, path)
    return path


def receipt_problem(project_root: Path, tip: str) -> str | None:
    """Before: `tip` es un SHA40 objetivo del cierre. During: lee su recibo. After: None si
    es valido (schema, tip, modo, `audit_ok` verdadero, `head_after` presente); si no, el
    motivo en una frase. Nunca lanza: un recibo ilegible es un motivo."""
    path = receipt_path(project_root, tip)
    if not path.is_file():
        return "sin recibo"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"recibo ilegible ({exc})"
    if not isinstance(data, dict):
        return "recibo no es un objeto JSON"
    if data.get("schema") != RECEIPT_SCHEMA or data.get("tip") != tip:
        return "recibo de otro schema o de otro tip"
    if data.get("mode") not in RECEIPT_MODES or data.get("audit_ok") is not True:
        return "recibo sin audit_ok verdadero o con modo desconocido"
    if not isinstance(data.get("head_after"), str) or not data["head_after"]:
        return "recibo sin head_after"
    return None


def required_receipt_shas(targets_text: str) -> list[str]:
    """Before: `targets_text` es el fichero de objetivos. During: toma el primer token de cada
    linea (sin comentarios) salvo las de `delivery_authority=repo_destino` (el wrapper integra
    el motor; esas no pueden tener recibo). After: los SHA que exigen recibo, en orden y sin
    duplicados. Sin I/O."""
    shas: list[str] = []
    for raw in targets_text.splitlines():
        parts = raw.split("#", 1)[0].split()
        if not parts or "delivery_authority=repo_destino" in parts[1:]:
            continue
        if parts[0] not in shas:
            shas.append(parts[0])
    return shas


def _debt_ficha(sha: str) -> str | None:
    try:
        from scripts.check_loop_execution import historic_debt_ficha
    except ImportError:
        from check_loop_execution import historic_debt_ficha  # type: ignore[no-redef]
    return historic_debt_ficha(sha)


def _tip_in_head(motor_root: Path | None, tip: str) -> bool | None:
    """True/False si `tip` es/no ancestro del HEAD del motor; None si no se pudo comprobar."""
    if motor_root is None:
        return None
    try:
        rc = subprocess.run(  # noqa: S603
            ["git", "-C", str(motor_root), "merge-base", "--is-ancestor", tip, "HEAD"],  # noqa: S607
            capture_output=True,
            timeout=30,
            check=False,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(rc)


def verify_receipts(
    project_root: Path, targets_text: str, motor_root: Path | None
) -> tuple[list[str], list[str]]:
    """Before: `targets_text` es el fichero de objetivos que acaba de escribir el cierre.
    During: por cada SHA que exige recibo y NO esta en `HISTORIC_LOOP_DEBT`, valida su recibo
        (`receipt_problem`) y que el tip siga siendo ancestro del HEAD del motor.
    After: `(problemas, notas)`; `problemas` vacio = todo atestado. Las notas nombran la
        deuda exenta y la ancestria no comprobable (motor no resoluble); no son fallos."""
    problems: list[str] = []
    notes: list[str] = []
    for sha in required_receipt_shas(targets_text):
        ficha = _debt_ficha(sha)
        if ficha is not None:
            notes.append(f"{sha[:12]} exento: deuda historica {ficha}")
            continue
        problem = receipt_problem(project_root, sha)
        if problem is None and _tip_in_head(motor_root, sha) is False:
            problem = "el tip ya no es ancestro del HEAD del motor"
        if problem is None and motor_root is None:
            notes.append(f"{sha[:12]}: ancestria no comprobada (motor no resoluble)")
        if problem is not None:
            problems.append(f"{sha}: {problem}")
    return problems, notes


def _git(root: Path, *args: str) -> tuple[int, str]:
    from scripts.session_closeout import _git_stdout

    rc, out = _git_stdout(root, list(args))
    return rc, out.strip()


def _preflight(
    project_root: Path | None, motor_root: Path, attest: bool
) -> tuple[int, str] | None:
    """None si todo es verificable; si no, `(2, motivo)`. Solo mira ficheros TRACKED."""
    if project_root is None or not (project_root / ".agent").is_dir():
        return 2, f"project-root ausente o sin .agent/: {project_root}"
    if _git(motor_root, "rev-parse", "--git-dir")[0] != 0:
        return 2, f"motor-root no es un repo git: {motor_root}"
    if not attest:
        rc, dirty = _git(motor_root, "status", "--porcelain", "--untracked-files=no")
        if rc != 0 or dirty:
            return (
                2,
                f"arbol tracked del motor sucio o ilegible (rc={rc}): {dirty[:200]}",
            )
    return None


def _target_line(
    ticket: str, project_root: Path, motor_root: Path, since: str
) -> tuple[str | None, int, str]:
    """La linea de objetivo del ticket, resuelta por el escritor del cierre.

    Devuelve `(linea, rc, motivo)`: `rc` 0 con linea; 1 ticket sin objetivo auditable o sin
    tip lineal; 2 git no pudo comprobarlo."""
    from scripts import session_closeout as sc

    try:
        from scripts.prefix_resolver import extract_prefix, resolve_prefix
    except ImportError:
        extract_prefix = resolve_prefix = None  # type: ignore[assignment]
    res = sc._process_ticket_targets(
        ticket, project_root, motor_root, extract_prefix, resolve_prefix, [since]
    )
    if res.status == "SKIP":
        return None, 2, res.detail
    if res.status != "PASS" or len(res.lines) != 1:
        return None, 1, res.detail or f"{ticket}: ningun commit del rango lo entrega"
    return res.lines[0], 0, res.detail


def _audit_line(project_root: Path, line: str) -> tuple[str, list[dict]]:
    """Audita UNA linea con las funciones de prepush. Devuelve `(tip, fallos)`."""
    from scripts import prepush_check as pp

    shas, dtype, loop, _src, _decl, phase, auth = pp._parse_loop_execution_targets(line)
    failures = pp._loop_accreditation_failures(
        project_root, shas, dtype, loop, phase, auth
    )
    return shas[0], failures


def _finish(
    ticket: str, tip: str, mode: str, project_root: Path, motor_root: Path, base: str
) -> tuple[int, list[str]]:
    """Fusiona (solo `integrate`) y escribe el recibo. Ver `integrate` para el contrato."""
    if mode == "integrate":
        rc, out = _git(motor_root, "merge", "--ff-only", tip)
        if rc != 0:
            return 1, [f"FAIL git merge --ff-only {tip[:12]} rc={rc}: {out[:200]}"]
    head_after = _git(motor_root, "rev-parse", "HEAD")[1]
    if mode == "integrate" and head_after != tip:
        return 1, [
            f"FAIL tras el ff el HEAD ({head_after[:12]}) no es el tip {tip[:12]}"
        ]
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "ticket": ticket,
        "tip": tip,
        "base_head": base,
        "head_after": head_after,
        "mode": mode,
        "merged": mode == "integrate",
        "audit_ok": True,
        "debt": _debt_ficha(tip),
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    try:
        path = write_receipt(project_root, receipt)
    except OSError as exc:
        return 2, [f"NO VERIFICABLE recibo no escrito ({exc}); el HEAD ya avanzo"]
    return 0, [f"OK {mode} {ticket} tip {tip[:12]} recibo {path}"]


def integrate(
    ticket: str,
    candidate: str,
    project_root: Path | None,
    motor_root: Path,
    attest: bool = False,
) -> tuple[int, list[str]]:
    """Audita el ultimo commit de `ticket` y, solo con OK, lo integra y deja el recibo.

    Before: ver el docstring del modulo. `candidate` es un ref/SHA que resuelve en `motor_root`.
    During: preflight -> linea de objetivo (ventana `HEAD..candidato`, o la historia del
        candidato en `--attest`) -> tip == candidato -> audit -> `git merge --ff-only` -> recibo.
    After: `(rc, lineas)`; la primera linea es el contrato. rc 0/1/2 como el modulo.
    """
    bad = _preflight(project_root, motor_root, attest)
    if bad is not None or project_root is None:
        return 2, [f"NO VERIFICABLE {bad[1] if bad else 'project-root ausente'}"]
    rc, cand = _git(motor_root, "rev-parse", "--verify", f"{candidate}^{{commit}}")
    rc_h, head = _git(motor_root, "rev-parse", "HEAD")
    if rc != 0 or rc_h != 0:
        return 2, [f"NO VERIFICABLE el candidato {candidate!r} o HEAD no resuelven"]
    anc = (
        ("merge-base", "--is-ancestor", cand, head)
        if attest
        else ("merge-base", "--is-ancestor", head, cand)
    )
    if _git(motor_root, *anc)[0] != 0:
        sentido = "no es ancestro del HEAD" if attest else "no es un ff sobre el HEAD"
        return 1, [f"FAIL el candidato {cand[:12]} {sentido} {head[:12]}"]
    since = cand if attest else f"{head}..{cand}"
    line, rc_t, why = _target_line(ticket, project_root, motor_root, since)
    if line is None:
        return rc_t, [f"{'NO VERIFICABLE' if rc_t == 2 else 'FAIL'} {why}"]
    if f"delivery_authority={_WRAPPER_AUTHORITY}" not in line.split():
        return 1, [f"FAIL {ticket} no declara delivery_authority={_WRAPPER_AUTHORITY}"]
    tip, failures = _audit_line(project_root, line)
    if tip != cand:
        return 1, [
            f"FAIL el tip {tip[:12]} no es el candidato {cand[:12]}: hay commits sin auditar"
        ]
    if failures:
        detail = [
            f"  {v['commit_sha']}: {len(v['distinct_backends'])}/{v['min_distinct']}"
            for v in failures
        ]
        return 1, [f"FAIL audit del bucle en rojo para {ticket}", *detail]
    return _finish(
        ticket, tip, "attest" if attest else "integrate", project_root, motor_root, head
    )


def _cwd_toplevel() -> Path:
    """El toplevel git del cwd; si git no contesta, el propio cwd (el preflight lo rechaza)."""
    rc, top = _git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(top) if rc == 0 and top else Path.cwd()


def main(argv: list[str] | None = None) -> int:
    """Before: argv trae `--ticket`, `--candidate` y `--project-root`. During: resuelve rutas
    y delega en `integrate`; una excepcion inesperada es NO VERIFICABLE, no traceback.
    After: rc 0/1/2 y el contrato en la primera linea de stdout."""
    ap = argparse.ArgumentParser(
        description="Audita e integra el ultimo commit de un ticket."
    )
    ap.add_argument("--ticket", required=True)
    ap.add_argument(
        "--candidate", required=True, help="ref o SHA a integrar (o a atestar)"
    )
    ap.add_argument(
        "--project-root", default="", help="destino (recibo, scorecard, contrato)"
    )
    ap.add_argument(
        "--motor-root", default="", help="worktree del vuelo; por defecto, el de cwd"
    )
    ap.add_argument(
        "--attest", action="store_true", help="solo audita un tip ya integrado"
    )
    args = ap.parse_args(argv)
    project_root = Path(args.project_root).resolve() if args.project_root else None
    motor_root = Path(args.motor_root).resolve() if args.motor_root else _cwd_toplevel()
    try:
        rc, lines = integrate(
            args.ticket, args.candidate, project_root, motor_root, args.attest
        )
    except Exception as exc:
        rc, lines = 2, [f"NO VERIFICABLE defecto del wrapper: {exc!r}"]
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main())
