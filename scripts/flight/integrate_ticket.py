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
    fusiona y no ejecuta la puerta `review_level`: audita un tip que YA esta
    integrado a mano (debe ser ancestro del HEAD).
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
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from scripts.flight.review_level import Classification


MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

from scripts.flight.verify_user_authorization import (  # noqa: E402, I001
    ticket_window_gitleaks_gate,
)

RECEIPT_SCHEMA = 1
RECEIPT_MODES = ("integrate", "attest", "cherry-pick")
RECEIPTS_REL = Path(".agent") / "runtime" / "integration_receipts"
_WRAPPER_AUTHORITY = "repo_motor"

# c-13: debt grandfathering is deliberately an exact, full-ID allowlist.
FROZEN_FAMILY_GRANDFATHER_IDS = (
    "WOT-2026-161j",
    "WOT-2026-161k",
    "WOT-2026-161l",
    "WOT-2026-161m",
    "WOT-2026-161n",
    "WOT-2026-161o",
    "WOT-2026-161q",
    "WOT-2026-161r",
    "WOT-2026-161s",
    "WOT-2026-161t",
)


class FamilyCheckError(ValueError):
    """Before: se recibe una ficha, canon o registro de familia declarativo.

    During: valida que el dato tenga la forma necesaria para medir c-13.
    After: el dato es interpretable o se lanza este error fail-closed.
    """


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
    if data.get("mode") == "cherry-pick":
        if not isinstance(data.get("audited_tip"), str) or not data["audited_tip"]:
            return "recibo cherry-pick sin audited_tip"
        if not isinstance(data.get("blobs"), dict):
            return "recibo cherry-pick sin blobs"
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


def _blob_sha(motor_root: Path, ref: str, path: str) -> str | None:
    """Before: `ref` y `path` identifican una entrada Git del motor.

    During: resuelve el blob con `git rev-parse`; una ruta ausente se representa
        como `None`, igual que una eliminacion en ambos extremos.
    After: devuelve el SHA del blob, `None` si la entrada no existe o si Git no
        pudo resolverla.
    """
    rc, blob = _git(motor_root, "rev-parse", "--verify", f"{ref}:{path}")
    return blob if rc == 0 and blob else None


def _changed_paths(motor_root: Path, base: str, tip: str) -> tuple[int, list[str], str]:
    """Before: `base` y `tip` son commits validos del motor.

    During: obtiene las rutas del diff de la ventana auditada.
    After: devuelve `(rc, rutas, salida)` y no modifica el repositorio.
    """
    rc, output = _git(motor_root, "diff", "--name-only", base, tip)
    return rc, output.splitlines() if rc == 0 else [], output


def _compare_blobs(
    motor_root: Path, head: str, tip: str, paths: list[str]
) -> tuple[list[str], dict[str, str | None]]:
    """Before: `head` es el resultado aplicado y `tip` el tip auditado.

    During: compara cada ruta modificada por ambos commits y conserva el blob
        esperado del tip, incluyendo `None` para borrados.
    After: devuelve `(rutas_distintas, blobs_del_tip)` sin escribir en Git.
    """
    mismatches: list[str] = []
    blobs: dict[str, str | None] = {}
    for path in paths:
        expected = _blob_sha(motor_root, tip, path)
        actual = _blob_sha(motor_root, head, path)
        blobs[path] = expected
        if expected != actual:
            mismatches.append(path)
    return mismatches, blobs


def audited_sha_for(
    project_root: Path, sha: str, motor_root: Path | None = None
) -> str:
    """Before: `sha` es el objetivo integrado y el destino contiene sus recibos.

    During: si hay un recibo cherry-pick valido, repite contra Git la prueba de
        blobs entre `audited_tip` y `sha`, devolviendo el tip auditado solo si
        todas las rutas y los blobs registrados siguen coincidiendo.
    After: devuelve el tip auditado en verde; ante cualquier ausencia, entrada
        invalida, ref ilegible o divergencia devuelve el propio `sha`.
    """
    path = receipt_path(project_root, sha)
    try:
        if receipt_problem(project_root, sha) is not None:
            return sha
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return sha
    if not isinstance(data, dict):
        return sha
    audited_tip = data.get("audited_tip")
    blobs = data.get("blobs")
    if (
        data.get("mode") != "cherry-pick"
        or not isinstance(audited_tip, str)
        or not audited_tip
        or not isinstance(blobs, dict)
    ):
        return sha
    root = motor_root or _cwd_toplevel()
    if _git(root, "rev-parse", "--verify", f"{sha}^{{commit}}")[0] != 0:
        return sha
    if _git(root, "rev-parse", "--verify", f"{audited_tip}^{{commit}}")[0] != 0:
        return sha
    for raw_path, expected in blobs.items():
        if not isinstance(raw_path, str) or not (
            expected is None or isinstance(expected, str)
        ):
            return sha
        audited_blob = _blob_sha(root, audited_tip, raw_path)
        integrated_blob = _blob_sha(root, sha, raw_path)
        if audited_blob != integrated_blob or audited_blob != expected:
            return sha
    return audited_tip


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
        from scripts.prefix_resolver import (
            extract_prefix,
            resolve_prefix,
            resolve_prefix_known,
        )
    except ImportError:
        extract_prefix = resolve_prefix = resolve_prefix_known = None  # type: ignore[assignment]
    resolve_prefix = sc._known_prefix_adapter(
        resolve_prefix_known, resolve_prefix, project_root
    )
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


def _run_review_level(
    ticket: str, base: str, tip: str, project_root: Path, motor_root: Path
) -> Classification:
    """Run the review classifier over the candidate integration window.

    Before: ``base`` and ``tip`` resolve in ``motor_root`` and the destination
        contains the live backlog.
    During: executes the canonical script as a subprocess and parses its output.
    After: returns a classification, converting malformed output to rc 2.
    """
    from scripts.flight.review_level import Classification

    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "scripts/flight/review_level.py",
            "--base",
            base,
            "--sha",
            tip,
            "--backlog",
            str(project_root / ".agent" / "collaboration" / "backlog.md"),
            "--ticket",
            ticket,
            "--repo",
            str(motor_root),
        ],
        cwd=MOTOR_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    level = "completo"
    reasons: list[str] = []
    for line in completed.stdout.splitlines():
        if line.startswith("NIVEL="):
            level = line.partition("=")[2]
        elif line.startswith("RAZON="):
            reasons.append(line.partition("=")[2])
    if completed.returncode != 0 and not reasons:
        reasons.append("review-level-sin-razon")
    if level not in {"completo", "delta"}:
        return Classification("completo", ("review-level-ilegible",), 2)
    return Classification(level, tuple(reasons), completed.returncode)


def _finish(  # noqa: C901
    ticket: str,
    tip: str,
    mode: str,
    project_root: Path,
    motor_root: Path,
    base: str,
    classification: Classification | None = None,
    merge_base: str | None = None,
) -> tuple[int, list[str]]:
    """Apply the review gate, then integrate and write the receipt.

    Before: ``classification`` is the result of the review-level subprocess for
        an integration, or ``None`` for attest mode. `merge_base` is required
        only by cherry-pick mode.
    During: blocks fail-closed classifications before any Git mutation; then
        applies either ff-only or the audited cherry-pick and atomically records
        the level, reasons and blob evidence.
    After: returns the wrapper contract without leaving a receipt on a block.
    """
    if mode in {"integrate", "cherry-pick"} and classification is not None:
        allowed, review_fields = review_level_gate(classification)
        if not allowed:
            reason = ", ".join(classification.reasons) or "revision-ilegible"
            print(reason, file=sys.stderr)
            return 2, [f"NO VERIFICABLE review_level {reason}"]
    else:
        review_fields = {}
    blob_paths: list[str] = []
    blobs: dict[str, str | None] = {}
    if mode == "cherry-pick":
        if merge_base is None:
            return 2, ["NO VERIFICABLE cherry-pick sin merge-base"]
        paths_rc, blob_paths, paths_output = _changed_paths(motor_root, merge_base, tip)
        if paths_rc != 0:
            return 2, [
                f"NO VERIFICABLE no se pudo listar la ventana {merge_base[:12]}..{tip[:12]}: "
                f"{paths_output[:200]}"
            ]
    if mode == "integrate":
        rc, out = _git(motor_root, "merge", "--ff-only", tip)
        if rc != 0:
            return 1, [f"FAIL git merge --ff-only {tip[:12]} rc={rc}: {out[:200]}"]
    elif mode == "cherry-pick":
        rc, out = _git(motor_root, "cherry-pick", f"{merge_base}..{tip}")
        if rc != 0:
            abort_rc, abort_out = _git(motor_root, "cherry-pick", "--abort")
            abort_detail = ""
            if abort_rc != 0:
                abort_detail = f"; abort rc={abort_rc}: {abort_out[:160]}"
            return 1, [
                f"FAIL conflicto en git cherry-pick {merge_base[:12]}..{tip[:12]}"
                f"{abort_detail}"
            ]
    head_after = _git(motor_root, "rev-parse", "HEAD")[1]
    if mode == "integrate" and head_after != tip:
        return 1, [
            f"FAIL tras el ff el HEAD ({head_after[:12]}) no es el tip {tip[:12]}"
        ]
    if mode == "cherry-pick":
        mismatches, blobs = _compare_blobs(motor_root, head_after, tip, blob_paths)
        if mismatches:
            reset_rc, reset_out = _git(motor_root, "reset", "--hard", base)
            reset_detail = ""
            if reset_rc != 0:
                reset_detail = f"; reset rc={reset_rc}: {reset_out[:160]}"
            return 1, [
                "FAIL prueba de blobs distinta tras cherry-pick: "
                + ", ".join(mismatches)
                + reset_detail
            ]
    receipt_tip = head_after if mode == "cherry-pick" else tip
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "ticket": ticket,
        "tip": receipt_tip,
        "base_head": base,
        "head_after": head_after,
        "mode": mode,
        "merged": mode in {"integrate", "cherry-pick"},
        "audit_ok": True,
        "debt": _debt_ficha(tip),
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        **review_fields,
    }
    if mode == "cherry-pick":
        receipt.update(
            {
                "audited_tip": tip,
                "merge_base": merge_base,
                "blobs": blobs,
            }
        )
    try:
        path = write_receipt(project_root, receipt)
    except OSError as exc:
        return 2, [f"NO VERIFICABLE recibo no escrito ({exc}); el HEAD ya avanzo"]
    return 0, [f"OK {mode} {ticket} tip {receipt_tip[:12]} recibo {path}"]


def review_level_gate(classification: Classification) -> tuple[bool, dict[str, object]]:
    """Convert a review classification into an integration decision.

    Before: ``classification`` comes from the review-level CLI and has a stable
        level, reasons tuple, and return code.
    During: accepts only rc zero and prepares receipt fields; any other rc is a
        fail-closed block.
    After: returns ``(allowed, fields)`` without filesystem or Git side effects.
    """
    if classification.rc != 0:
        return False, {}
    return True, {
        "level": classification.level,
        "reasons": list(classification.reasons),
    }


def check_pilares_views(motor_root: Path) -> tuple[int, list[str]]:
    """Comprueba que las vistas del canon de pilares estan frescas antes de integrar (WOT-2026-219b)."""
    canon_path = motor_root / ".agent" / "rules" / "common" / "vuelo_pilares.md"
    if not canon_path.exists():
        return 0, []
    try:
        from scripts.flight.check_pilares_views_fresh import verify_views_fresh

        if not verify_views_fresh(project_root=motor_root):
            return 1, [
                "FAIL vistas de pilares no frescas o ausentes en motor. "
                "Ejecuta `python scripts/flight/check_pilares_views_fresh.py --generate` antes de integrar."
            ]
        return 0, []
    except Exception as exc:
        return 2, [f"NO VERIFICABLE error comprobando vistas de pilares: {exc}"]


def integrate(  # noqa: C901
    ticket: str,
    candidate: str,
    project_root: Path | None,
    motor_root: Path,
    attest: bool = False,
    cherry_pick: bool = False,
) -> tuple[int, list[str]]:
    """Audita el ultimo commit de `ticket` y, solo con OK, lo integra y deja el recibo.

    Before: ver el docstring del modulo. `candidate` es un ref/SHA que resuelve en `motor_root`.
    During: preflight -> linea de objetivo (ventana `HEAD..candidato`, la ventana
        `merge-base..candidato` en cherry-pick, o la historia del candidato en
        `--attest`) -> tip == candidato -> audit -> aplicacion -> recibo.
    After: `(rc, lineas)`; la primera linea es el contrato. rc 0/1/2 como el modulo.
    """
    if cherry_pick and attest:
        return 2, ["NO VERIFICABLE --cherry-pick es excluyente con --attest"]
    bad = _preflight(project_root, motor_root, attest)
    if bad is not None or project_root is None:
        return 2, [f"NO VERIFICABLE {bad[1] if bad else 'project-root ausente'}"]
    rc, cand = _git(motor_root, "rev-parse", "--verify", f"{candidate}^{{commit}}")
    rc_h, head = _git(motor_root, "rev-parse", "HEAD")
    if rc != 0 or rc_h != 0:
        return 2, [f"NO VERIFICABLE el candidato {candidate!r} o HEAD no resuelven"]
    merge_base: str | None = None
    if cherry_pick:
        rc_mb, merge_base = _git(motor_root, "merge-base", head, cand)
        if rc_mb != 0 or not merge_base:
            return 2, [
                f"NO VERIFICABLE no hay merge-base entre HEAD {head[:12]} y candidato {cand[:12]}"
            ]
        since = f"{merge_base}..{cand}"
    else:
        anc = (
            ("merge-base", "--is-ancestor", cand, head)
            if attest
            else ("merge-base", "--is-ancestor", head, cand)
        )
        if _git(motor_root, *anc)[0] != 0:
            sentido = (
                "no es ancestro del HEAD" if attest else "no es un ff sobre el HEAD"
            )
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
    family_lines: list[str] = []
    if not attest:
        family_rc, family_lines = check_family(ticket, tip, project_root, motor_root)
        if family_rc != 0:
            return family_rc, family_lines
        views_rc, views_lines = check_pilares_views(motor_root)
        if views_rc != 0:
            return views_rc, views_lines
    classification = None
    if not attest:
        review_base = merge_base if cherry_pick else head
        classification = _run_review_level(
            ticket, review_base, tip, project_root, motor_root
        )
        gitleaks_decision = ticket_window_gitleaks_gate(motor_root, since)
        if gitleaks_decision.reason == "gitleaks-findings":
            detail = gitleaks_decision.detail or "sin detalle reproducible"
            return 1, [
                "FAIL hallazgo de gitleaks en la ventana del ticket",
                f"  {detail}",
            ]
        if not (
            gitleaks_decision.allowed and gitleaks_decision.reason == "gitleaks-clean"
        ):
            detail = gitleaks_decision.detail or "sin detalle reproducible"
            return 2, [
                f"NO VERIFICABLE gate de gitleaks ({gitleaks_decision.reason})",
                f"  {detail}",
            ]
    # --attest queda fuera del alcance de este ticket: no se escanea (NO VERIFICADO).
    finish_rc, finish_lines = _finish(
        ticket,
        tip,
        "attest" if attest else ("cherry-pick" if cherry_pick else "integrate"),
        project_root,
        motor_root,
        head,
        classification,
        merge_base if cherry_pick else None,
    )
    return finish_rc, [*finish_lines, *family_lines]


def parse_ficha_models(text: str) -> dict[str, tuple[str, str]]:
    """Extrae autor y revisor desde las claves planas de una ficha.

    Before: `text` contiene una ficha con `autor_modelo:` y
        `revisor_modelo:` en formato `backend|model`.
    During: recorre la ficha ENTERA linea a linea (la clave se lee en cualquier
        seccion, tipicamente la 1 Metadatos); rechaza valor vacio, partes
        adicionales y clave REPETIDA.
    After: devuelve `{"autor": (backend, model), "revisor": (...)}` o lanza
        `FamilyCheckError` nombrando la clave defectuosa.
    """
    found: dict[str, tuple[str, str]] = {}
    keys = {"autor_modelo": "autor", "revisor_modelo": "revisor"}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        normalized_key = key.strip().casefold()
        if normalized_key not in keys:
            continue
        parts = [part.strip() for part in value.split("|")]
        if not separator or len(parts) != 2 or any(not part for part in parts):
            raise FamilyCheckError(f"clave {normalized_key} mal formada")
        result_key = keys[normalized_key]
        if result_key in found:
            raise FamilyCheckError(f"clave {normalized_key} repetida")
        found[result_key] = (parts[0], parts[1])
    for raw_key, result_key in keys.items():
        if result_key not in found:
            raise FamilyCheckError(f"falta la clave {raw_key}")
    return found


def canon_p33_status(text: str) -> str | None:
    """Obtiene el estado de la fila P33 del canon de pilares.

    Before: `text` es el Markdown del canon que puede contener una tabla P33.
    During: divide cada fila en celdas y acepta solo la fila cuya primera celda
        es exactamente `P33`.
    After: devuelve la tercera celda limpia o `None` si la fila no existe.
    """
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) >= 3 and cells[0] == "P33":
            return cells[2]
    return None


def family_violations(
    author_family: str, reviewer_family: str, lenses: list[dict]
) -> list[str]:
    """Nombra cada lente contada que comparte familia con autor o revisor.

    Before: `author_family` y `reviewer_family` son familias resueltas y cada
        lente tiene backend, model, backend_key y family.
    During: compara por igualdad y conserva una violacion independiente por
        cada coincidencia, incluso si coincide con ambos.
    After: devuelve las lineas de fallo en orden de entrada; no tiene I/O.
    """
    violations: list[str] = []
    for lens in lenses:
        for role, family in (("autor", author_family), ("revisor", reviewer_family)):
            if lens["family"] == family:
                violations.append(
                    f"lente {lens['backend_key']} {lens['backend']}/{lens['model']} "
                    f"(familia {lens['family']}) comparte familia con el {role} "
                    f"(familia {family})"
                )
    return violations


def check_family(  # noqa: C901
    ticket: str,
    candidate: str,
    project_root: Path | None,
    motor_root: Path,
) -> tuple[int, list[str]]:
    """Comprueba c-13 para las lentes contadas del commit candidato.

    Before: `project_root` contiene la ficha y los artefactos del bucle, el
        canon P33 del motor esta disponible y el motor esta limpio.
    During: valida preflight, resuelve el candidato, lee ficha/canon, cuenta
        rondas sustantivas y resuelve cada familia desde MODEL_FAMILY_MAP.
    After: devuelve rc 0 conforme, rc 1 por familia compartida o rc 2 si no
        puede medirse; nunca fusiona ni escribe.
    """
    bad = _preflight(project_root, motor_root, False)
    if bad is not None or project_root is None:
        return 2, [
            f"NO VERIFICABLE familia {ticket}: {bad[1] if bad else 'project-root ausente'}"
        ]
    rc, candidate_sha = _git(
        motor_root, "rev-parse", "--verify", f"{candidate}^{{commit}}"
    )
    if rc != 0 or not candidate_sha:
        return 2, [f"NO VERIFICABLE familia {ticket}: candidato no resoluble"]
    ficha_path = project_root / ".agent" / "collaboration" / f"FICHA_{ticket}.md"
    canon_path = motor_root / ".agent" / "rules" / "common" / "vuelo_pilares.md"
    from scripts.check_loop_execution import (
        FamilyResolutionError,
        counted_lenses_for_commit,
        model_family,
    )

    if not ficha_path.is_file():
        if ticket in FROZEN_FAMILY_GRANDFATHER_IDS:
            return 0, [
                f"WARN grandfathered familia {ticket}: ficha ausente "
                f"(id completo {ticket})"
            ]
        return 2, [
            f"NO VERIFICABLE familia {ticket}: ficha ausente (id completo {ticket})"
        ]
    try:
        ficha_text = ficha_path.read_text(encoding="utf-8")
        try:
            declarations = parse_ficha_models(ficha_text)
        except FamilyCheckError as exc:
            missing = str(exc).startswith("falta la clave ")
            if missing and ticket in FROZEN_FAMILY_GRANDFATHER_IDS:
                return 0, [
                    f"WARN grandfathered familia {ticket}: ficha sin declaracion "
                    f"(id completo {ticket})"
                ]
            raise
        status = canon_p33_status(canon_path.read_text(encoding="utf-8"))
        if status != "RATIFICADA":
            reason = (
                "P33 ausente" if status is None else f"P33 no RATIFICADA ({status})"
            )
            return 2, [f"NO VERIFICABLE familia {ticket}: {reason}"]
        from scripts.ensemble_dispatch import MODEL_FAMILY_MAP

        records = counted_lenses_for_commit(project_root, candidate_sha)
        if not records:
            return 2, [f"NO VERIFICABLE familia {ticket}: cero lentes contadas"]
        author_family = model_family(*declarations["autor"], MODEL_FAMILY_MAP)
        reviewer_family = model_family(*declarations["revisor"], MODEL_FAMILY_MAP)
        lenses: list[dict] = []
        for record in records:
            family = model_family(record["backend"], record["model"], MODEL_FAMILY_MAP)
            lenses.append({**record, "family": family})
    except (
        OSError,
        FamilyCheckError,
        FamilyResolutionError,
        KeyError,
        ValueError,
    ) as exc:
        return 2, [f"NO VERIFICABLE familia {ticket}: {exc}"]
    violations = family_violations(author_family, reviewer_family, lenses)
    if violations:
        return 1, [
            f"FAIL familia {ticket}: {len(violations)} violacion(es)",
            *violations,
        ]
    return 0, [f"OK familia {ticket} {len(lenses)} lentes contadas"]


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
    ap.add_argument(
        "--cherry-pick",
        action="store_true",
        help="audita y aplica la ventana del ticket por cherry-pick",
    )
    ap.add_argument(
        "--check-family",
        action="store_true",
        help="comprueba c-13 sin fusionar ni escribir recibo",
    )
    args = ap.parse_args(argv)
    project_root = Path(args.project_root).resolve() if args.project_root else None
    motor_root = Path(args.motor_root).resolve() if args.motor_root else _cwd_toplevel()
    try:
        if args.cherry_pick and args.attest:
            rc, lines = 2, ["NO VERIFICABLE --cherry-pick es excluyente con --attest"]
        elif args.cherry_pick and args.check_family:
            rc, lines = (
                2,
                ["NO VERIFICABLE --cherry-pick es excluyente con --check-family"],
            )
        elif args.check_family:
            rc, lines = check_family(
                args.ticket, args.candidate, project_root, motor_root
            )
        else:
            rc, lines = integrate(
                args.ticket,
                args.candidate,
                project_root,
                motor_root,
                args.attest,
                args.cherry_pick,
            )
    except Exception as exc:
        rc, lines = 2, [f"NO VERIFICABLE defecto del wrapper: {exc!r}"]
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main())
