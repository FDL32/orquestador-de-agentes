#!/usr/bin/env python
"""Recolector de estado para el arranque de una sesion nueva (WOT session-hop).

Que protege
-----------
Un arranque de sesion transporta DOS cosas: el METODO (que no caduca y vive
versionado en ``prompts/session_hop.md``) y el ESTADO (que caduca en horas). Cuando
el estado se COPIA en vez de RE-MEDIRSE, se convierte en premisa falsa heredada.

Medido en este repo en dos dias: un arranque declaraba el destino en ``eb721cb``
cuando era ``f34aa80``; decia "237 pending" cuando eran 240 (239 al dia siguiente);
mandaba expandir 4 slugs de memoria de los que 3 daban ``rc=1``; y un mismo censo
dio 157 -> 152 -> 154.

Este script emite ese estado MEDIDO, con el comando y el exit code de cada dato,
para que el arranque no lo invente.

CONTRATO DE AUTORIDAD (no negociable)
-------------------------------------
**Este script RECOLECTA; el AGENTE juzga.** Mismo contrato que
``backlog_reconcile.py`` (*"This script NEVER classifies"*). Su salida no contiene
NINGUN veredicto: ni ``APTO_AUTONOMO``, ni ``LIKELY_DONE``, ni ``APROBADO``, ni
``LISTO``, ni ``BLOQUEANTE``. Si un consumidor busca ahi una conclusion, no la va a
encontrar, y eso es deliberado: el juicio exige leer la evidencia, y la evidencia es
lo que este script entrega.

El test ``test_collect_session_state.py`` fija esa lista de terminos CERRADA. Una
lista abierta ("ninguna palabra de veredicto") no seria testeable, y por tanto
tampoco un contrato.

CONTRATO DE FALLO (el caso que mas importa)
-------------------------------------------
Con arbol SUCIO, suite STALE o un gate en rojo, este script **sigue saliendo 0 y
REPORTA esos hechos**. Un recolector que se cae cuando el arbol no esta sano es
inutil justo cuando hace falta.

``rc != 0`` queda reservado a fallo del PROPIO recolector: ruta irresoluble o I/O.
Nunca a un hallazgo sobre el repo.

Before / During / After
-----------------------
Before: ``--project-root`` apunta a un destino existente; ``--motor-root`` se deriva
    si se omite (el repo que contiene este script).
During: ejecuta comandos read-only (git, gates, lectura de JSON). No escribe en
    ninguna superficie operativa: ni ``backlog.md``, ni ``STATE.md``, ni el bus.
After: imprime un bloque markdown pegable (o JSON con ``--json``) donde cada dato
    lleva su ``command:`` y su ``exit_code:``. Exit 0 salvo fallo del recolector.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent

# Terminos de VEREDICTO que esta salida no puede contener. Lista CERRADA a
# proposito: es lo que hace el contrato testeable (ver el test hermano). Una lista
# abierta ("ninguna palabra de juicio") no se puede verificar de forma reproducible.
FORBIDDEN_VERDICTS = (
    "APTO_AUTONOMO",
    "REQUIERE_HUMANO",
    "DISENO_PRIMERO",
    "LIKELY_DONE",
    "LIKELY_PENDING",
    "NEEDS_HUMAN_VERIFY",
    "APROBADO",
    "CAMBIOS NECESARIOS",
    "LISTO",
    "BLOQUEANTE",
)

# WOT-2026-085a: la cuarentena de ensemble se DERIVA EN MEMORIA al arranque.
# El subprocess importa `ensemble_dispatch` y reutiliza SUS constantes de ruta
# (`FALLBACK_EVENTS_REL`, `QUARANTINE_REL`), sin duplicarlas en este modulo.
#
# D7: un fallo de esta pieza NUNCA bloquea el arranque. El subprocess que
# importa `ensemble_dispatch` corre con un timeout EXPLICITO y bajo (medido:
# ~80 ms en esta maquina); el default de `_run` (120 s) seria un umbral que no
# declara intencion.
QUARANTINE_TIMEOUT_S = 5

# D3/D7: los 4 casos de causa se declaran con textos DISTINTOS y no
# fusionables. "fuente vacia" (0 eventos) es una medicion valida; "no medido"
# es ignorancia. El operador actua distinto en cada uno.
LABEL_LINK = "cuarentena: enlace motor-destino no disponible"
LABEL_MODULE = "cuarentena: modulo no disponible"
LABEL_EMPTY = "fuente vacia (0 eventos)"

# El subprocess `python -c` replica `collect_mode` (aislamiento por import). El
# script imprime UNA linea JSON (ASCII puro via `ensure_ascii`, para no depender
# del encoding de stdout en Windows) y devuelve siempre 0 cuando pudo emitirla;
# el recolector externo traduce rc!=0 / stdout no-JSON a "no medido".
_QUARANTINE_SCRIPT_TEMPLATE = """
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _emit(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.write("\\n")
    sys.stdout.flush()
    raise SystemExit(0)


_project_root = Path(__PROJECT_ROOT__)
_link = _project_root / ".agent" / "config" / "motor_destination_link.json"
try:
    _motor = Path(
        json.loads(_link.read_text(encoding="utf-8"))["motor_root"]
    ).resolve()
except (OSError, ValueError, KeyError, TypeError):
    _motor = None
if _motor is None or not _motor.exists():
    _emit({"status": "no_link", "cause": __LABEL_LINK__})

try:
    sys.path.insert(0, str(_motor / "scripts"))
    import ensemble_dispatch as _ed

    _config = _ed.load_motor_config()
    _src = _project_root / _ed.FALLBACK_EVENTS_REL
    _raw = _src.read_bytes() if _src.exists() else b""
    _now = datetime.now(timezone.utc)
    _buckets = _ed._quarantine_buckets(_raw, now=_now, config=_config)
    _by_backend, _by_profile = _ed._quarantine_tables(
        _buckets, config=_config, now=_now
    )
except Exception as _exc:
    _emit(
        {
            "status": "no_module",
            "cause": __LABEL_MODULE__ + " (" + type(_exc).__name__ + ": " + str(_exc) + ")",
        }
    )

_events = 0
_skipped = 0
_last_ts = None
for _line in _raw.decode("utf-8", "replace").splitlines():
    if not _line.strip():
        continue
    try:
        _ev = json.loads(_line)
    except ValueError:
        _skipped += 1
        continue
    _events += 1
    _ts = _ev.get("ts")
    if isinstance(_ts, str) and (_last_ts is None or _ts > _last_ts):
        _last_ts = _ts

_disk = None
_dpath = _project_root / _ed.QUARANTINE_REL
if _dpath.exists():
    try:
        _ddata = json.loads(_dpath.read_text(encoding="utf-8"))
        _disk = {
            "generated_at": _ddata.get("generated_at"),
            "fallback_events_sha256": _ddata.get("fallback_events_sha256"),
            "coincide_fuente": (
                _ddata.get("fallback_events_sha256")
                == hashlib.sha256(_raw).hexdigest()
            ),
        }
    except (OSError, ValueError):
        _disk = None

_emit(
    {
        "status": "empty" if _events == 0 else "measured",
        "cause": None,
        "by_backend": _by_backend,
        "by_profile": _by_profile,
        "events": _events,
        "skipped": _skipped,
        "source_present": _src.exists(),
        "source_sha256": hashlib.sha256(_raw).hexdigest(),
        "last_event_ts": _last_ts,
        "disk": _disk,
    }
)
"""


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> dict:
    """Ejecuta un comando read-only y devuelve su recibo.

    El ``exit_code`` sale de ``subprocess.returncode``, NUNCA de ``$?`` tras un pipe:
    ``cmd | tail`` devuelve el rc de ``tail``, que casi siempre es 0 (leccion
    recurrente de este repo).
    """
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "command": " ".join(cmd),
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        # NO se propaga: un comando que no arranca es un HECHO a reportar, no un
        # motivo para tumbar la recoleccion entera.
        return {
            "command": " ".join(cmd),
            "exit_code": None,
            "stdout": "",
            "stderr": f"no ejecutable: {exc}",
        }


def _git(root: Path, *args: str) -> dict:
    return _run(["git", "-C", str(root), *args])


def collect_repo(role: str, root: Path) -> dict:
    """Hechos de un repo: HEAD, rama, sucio (tracked vs untracked), sin publicar."""
    if not root.exists():
        return {"role": role, "path": str(root), "exists": False}

    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(root, "status", "--porcelain")
    unpushed = _git(root, "log", "--oneline", "origin/main..HEAD")

    lines = [ln for ln in status["stdout"].splitlines() if ln.strip()]
    tracked = [ln for ln in lines if not ln.startswith("??")]
    untracked = [ln for ln in lines if ln.startswith("??")]

    return {
        "role": role,
        "path": str(root),
        "exists": True,
        "head": head["stdout"][:40],
        "branch": branch["stdout"],
        # tracked vs untracked SEPARADOS: un arranque que los suma reporta "sucio"
        # cuando lo unico presente son artefactos nuevos de otra sesion.
        "dirty_tracked": len(tracked),
        "dirty_untracked": len(untracked),
        "untracked_sample": [ln[3:] for ln in untracked[:5]],
        "unpushed_count": len(
            [ln for ln in unpushed["stdout"].splitlines() if ln.strip()]
        ),
        "unpushed": [ln for ln in unpushed["stdout"].splitlines() if ln.strip()][:10],
        "receipts": [head, status, unpushed],
    }


def collect_suite(motor_root: Path) -> dict:
    """Sello de la suite canonica frente al HEAD real.

    El campo se llama ``tested_commit_sha`` (lo escribe ``run_pytest_safe.py``), y
    ``level``/``args_mode`` importan tanto como el sha: una corrida filtrada se
    registra igual con ``level: all`` pero mide un SUBCONJUNTO.
    """
    path = motor_root / ".agent" / "runtime" / "pytest-safe" / "last-run.json"
    if not path.exists():
        return {"present": False, "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return {"present": True, "path": str(path), "unreadable": str(exc)}

    head = _git(motor_root, "rev-parse", "HEAD")["stdout"]
    tested = data.get("tested_commit_sha")
    return {
        "present": True,
        "path": str(path),
        "tested_commit_sha": tested,
        "head": head,
        "matches_head": bool(tested) and tested == head,
        "level": data.get("level"),
        "args_mode": data.get("args_mode"),
        "exit_code": data.get("exit_code"),
        "passed": data.get("passed"),
        "skipped": data.get("skipped"),
    }


def collect_gates(motor_root: Path, project_root: Path) -> list[dict]:
    """Gates read-only, cada uno con su rc REAL. Un rojo aqui NO tumba la corrida."""
    py = sys.executable
    return [
        _run(
            [
                py,
                str(motor_root / "scripts" / "check_backlog_contract.py"),
                "--project-root",
                str(project_root),
            ],
            cwd=motor_root,
        ),
        _run(
            [py, str(motor_root / "scripts" / "check_guard_wiring.py")],
            cwd=motor_root,
        ),
    ]


def collect_memory_slugs(motor_root: Path, slugs: list[str]) -> list[dict]:
    """Verifica CADA slug antes de que el arranque lo cite.

    Un arranque que ordena expandir un slug inexistente le regala al ejecutor un paso
    imposible. Solo los ``rc=0`` son citables.
    """
    py = sys.executable
    out = []
    for slug in slugs:
        rec = _run(
            [
                py,
                str(motor_root / "scripts" / "memory_context.py"),
                "--recall",
                "--id",
                slug,
            ],
            cwd=motor_root,
            timeout=60,
        )
        out.append(
            {
                "slug": slug,
                "exit_code": rec["exit_code"],
                "citable": rec["exit_code"] == 0,
            }
        )
    return out


def collect_inbox(project_root: Path) -> dict:
    inbox = project_root / ".agent" / "collaboration" / "backlog_inbox"
    fichas = (
        sorted(p.name for p in inbox.glob("*.tickets.md")) if inbox.exists() else []
    )
    fp = project_root / "orchestrator_pipeline" / "flight_plans"
    return {
        "inbox_path": str(inbox),
        "fichas_count": len(fichas),
        "fichas": fichas,
        "queued": sorted(p.name for p in (fp / "queued").glob("*.json"))
        if (fp / "queued").exists()
        else [],
        "in_flight": sorted(p.name for p in (fp / "in_flight").glob("*"))
        if (fp / "in_flight").exists()
        else [],
    }


def collect_mode(motor_root: Path) -> dict:
    """Modo de despliegue: se DETECTA, nunca se asume (un vuelo ya se equivoco)."""
    rec = _run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, '.'); "
            "from runtime.project_root import is_motor_code_only; "
            "print(is_motor_code_only())",
        ],
        cwd=motor_root,
    )
    return {
        "command": rec["command"],
        "exit_code": rec["exit_code"],
        "is_motor_code_only": rec["stdout"].strip(),
    }


def collect_quarantine(motor_root: Path, project_root: Path) -> dict:
    """Cuarentena ensemble DERIVADA EN MEMORIA desde `fallback_events.jsonl`.

    Before: `project_root` es el destino-rol (fuente UNICA: `fallback_events.jsonl`
        resuelto via el link motor-destino, D7). `motor_root` se usa como `cwd`
        del subprocess. Ninguno se modifica.
    During: lanza un `python -c` aislado (`timeout` explicito y bajo) que importa
        `ensemble_dispatch` y aplica `_quarantine_buckets` + `_quarantine_tables`
        SIN invocar `quarantine --sync` y SIN escribir `backend_quarantine.json`
        (DEC-085A-001 Decision 1). Traduce el recibo a una causa declarada.
    After: dict con `command`, `exit_code`, `by_backend`, `by_profile` (vacios si
        no hubo medicion) y `cause` (None = medicion valida). Distingue 4 casos
        no fusionables (D3/D7): fuente vacia, no medido (rc!=0), enlace
        motor-destino ausente, modulo no disponible. NUNCA lanza.
    """
    script = (
        _QUARANTINE_SCRIPT_TEMPLATE.replace("__PROJECT_ROOT__", repr(str(project_root)))
        .replace("__LABEL_LINK__", repr(LABEL_LINK))
        .replace("__LABEL_MODULE__", repr(LABEL_MODULE))
    )
    rec = _run(
        [sys.executable, "-c", script],
        cwd=motor_root,
        timeout=QUARANTINE_TIMEOUT_S,
    )
    result = {
        "command": rec["command"],
        "exit_code": rec["exit_code"],
        "by_backend": {},
        "by_profile": {},
        "cause": None,
        "status": "no_measure",
        "events": None,
        "skipped": None,
        "source_present": None,
        "source_sha256": None,
        "last_event_ts": None,
        "disk": None,
    }
    payload = None
    if rec["exit_code"] == 0 and rec["stdout"]:
        try:
            payload = json.loads(rec["stdout"])
        except ValueError:
            payload = None
    if not isinstance(payload, dict):
        # D3/D7: subprocess caido / stdout corrupto -> "no medido" (rc=N),
        # DISTINTO de "fuente vacia" y de las causas de enlace/modulo.
        result["cause"] = f"no medido (rc={rec['exit_code']})"
        return result
    result["status"] = payload.get("status", "measured")
    result["cause"] = payload.get("cause")
    result["by_backend"] = payload.get("by_backend") or {}
    result["by_profile"] = payload.get("by_profile") or {}
    result["events"] = payload.get("events")
    result["skipped"] = payload.get("skipped")
    result["source_present"] = payload.get("source_present")
    result["source_sha256"] = payload.get("source_sha256")
    result["last_event_ts"] = payload.get("last_event_ts")
    result["disk"] = payload.get("disk")
    return result


def build_report(motor_root: Path, project_root: Path, slugs: list[str]) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "EVIDENCIA FECHADA, no criterio. Cada dato lleva su comando: re-mide "
            "antes de citar. Este bloque no contiene veredictos por contrato."
        ),
        "repos": [
            collect_repo("repo_motor", motor_root),
            collect_repo("repo_destino", project_root),
        ],
        "mode": collect_mode(motor_root),
        "suite": collect_suite(motor_root),
        "gates": collect_gates(motor_root, project_root),
        "memory_slugs": collect_memory_slugs(motor_root, slugs),
        "inbox": collect_inbox(project_root),
        "quarantine": collect_quarantine(motor_root, project_root),
    }


def render_markdown(rep: dict) -> str:
    out: list[str] = []
    out.append(f"## ESTADO MEDIDO [snapshot {rep['generated_at']}]")
    out.append("")
    out.append(f"> {rep['note']}")
    out.append("")
    out.append("### Topologia")
    out.append("")
    out.append(
        "| Rol | Ruta | HEAD | Rama | dirty tracked | untracked | sin publicar |"
    )
    out.append("|---|---|---|---|---|---|---|")
    for r in rep["repos"]:
        if not r.get("exists"):
            out.append(f"| {r['role']} | {r['path']} | (no existe) | - | - | - | - |")
            continue
        out.append(
            f"| {r['role']} | {r['path']} | `{r['head'][:7]}` | {r['branch']} | "
            f"{r['dirty_tracked']} | {r['dirty_untracked']} | {r['unpushed_count']} |"
        )
    out.append("")
    out.append(
        f"Modo (repo medido: repo_motor): "
        f"`is_motor_code_only() = {rep['mode']['is_motor_code_only']}` "
        f"(`exit_code: {rep['mode']['exit_code']}`) -- **detectado, no asumido**."
    )
    out.append("")

    s = rep["suite"]
    out.append("### Suite canonica")
    out.append("")
    # WOT-2026-060j: la ATRIBUCION es parte del dato. `collect_suite` lee
    # SIEMPRE el sello del motor, aunque se invoque con --project-root <destino>,
    # y en esta topologia coexisten varios `last-run.json` con veredictos
    # DISTINTOS (motor, destino y worktree). Sin nombrar la raiz, un lector
    # razonable atribuye al destino un dato que es del motor. El rol es el
    # vocabulario canonico (`repo_motor`), no la ruta: la ruta ya viaja abajo.
    out.append("- repo medido: repo_motor (el sello del motor, NO el del destino).")
    if not s.get("present"):
        out.append(f"- `last-run.json` ausente en `{s['path']}`.")
    elif s.get("unreadable"):
        out.append(f"- `last-run.json` ilegible: {s['unreadable']}")
    else:
        out.append(
            f"- `tested_commit_sha`: `{str(s['tested_commit_sha'])[:7]}` | "
            f"HEAD: `{str(s['head'])[:7]}` | coincide: **{s['matches_head']}**"
        )
        out.append(
            f"- `level={s['level']}` `args_mode={s['args_mode']}` "
            f"`exit_code={s['exit_code']}` passed={s['passed']} skipped={s['skipped']}"
        )
    out.append("")

    out.append("### Gates (rc real, sin pipe)")
    out.append("")
    out.extend(
        f"- `{g['command']}` -> `exit_code: {g['exit_code']}`" for g in rep["gates"]
    )
    out.append("")

    out.append("### Slugs de memoria")
    out.append("")
    citable = [m["slug"] for m in rep["memory_slugs"] if m["citable"]]
    no_cit = [m["slug"] for m in rep["memory_slugs"] if not m["citable"]]
    out.append(
        f"- Citables (`rc=0`): {', '.join(f'`{s}`' for s in citable) or '(ninguno)'}"
    )
    if no_cit:
        out.append(
            f"- **NO citables (`rc!=0`)**: {', '.join(f'`{s}`' for s in no_cit)} "
            "-- no los ordenes expandir."
        )
    out.append("")

    i = rep["inbox"]
    out.append("### Buzon y planes")
    out.append("")
    out.append(f"- fichas en `backlog_inbox/`: **{i['fichas_count']}**")
    out.append(f"- `flight_plans/queued/`: {len(i['queued'])}")
    out.append(f"- `flight_plans/in_flight/`: {len(i['in_flight'])}")
    out.append("")
    out.extend(_render_quarantine(rep.get("quarantine") or {}))
    return "\n".join(out)


def _render_quarantine(q: dict) -> list[str]:
    """Seccion de cuarentena: datos + causa declarada, NUNCA veredicto.

    Distingue explicitamente las 4 causas (D3/D7) para que un operador sepa si
    "no hay nadie en cuarentena" o "no se pudo medir", y declara la antiguedad
    del artefacto en disco (D4) en vez de asumirlo vigente.
    """
    out = ["### Cuarentena de ensemble (arranque)", ""]
    out.append(
        "- repo medido: repo_motor (fuente: `fallback_events.jsonl` del destino, "
        "derivada EN MEMORIA; nunca se invoca `quarantine --sync`)."
    )
    out.append(f"- `exit_code: {q.get('exit_code')}`")
    cause = q.get("cause")
    if cause:
        out.append(f"- **{cause}**")
    else:
        by_backend = q.get("by_backend") or {}
        by_profile = q.get("by_profile") or {}
        for name, entry in sorted(by_backend.items()):
            out.append(
                f"- backend `{name}` EN CUARENTENA hasta `{entry.get('expires_at')}` "
                f"({entry.get('reason_class')})."
            )
        for name, entry in sorted(by_profile.items()):
            out.append(
                f"- perfil `{name}` EN CUARENTENA hasta `{entry.get('expires_at')}` "
                f"({entry.get('reason_class')}, backend `{entry.get('backend')}`)."
            )
        if not by_backend and not by_profile:
            events = q.get("events")
            if q.get("status") == "empty" or events == 0:
                out.append(f"- **{LABEL_EMPTY}**: no hay ninguna lente en cuarentena.")
            else:
                out.append(
                    f"- sin cuarentena vigente ({events} evento(s) leido(s), "
                    f"{q.get('skipped')} saltado(s); ninguna vigente ahora mismo)."
                )
        last_ts = q.get("last_event_ts")
        out.append(
            f"- ultimo evento de la fuente: `{last_ts}`"
            if last_ts
            else "- ultimo evento de la fuente: (ninguno)."
        )
        disk = q.get("disk")
        if disk:
            coincide = str(bool(disk.get("coincide_fuente"))).lower()
            out.append(
                f"- `backend_quarantine.json` EN DISCO: `generated_at: "
                f"{disk.get('generated_at')}`, `coincide_fuente: {coincide}` "
                "(sha256 del `fallback_events.jsonl` fuente). No se asume vigente."
            )
        else:
            out.append(
                "- `backend_quarantine.json` EN DISCO: ausente (sin artefacto stale "
                "que desmentir)."
            )
    out.append("")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Recolecta el estado medido para el arranque de una sesion nueva. "
            "RECOLECTA, no juzga: su salida no contiene veredictos."
        )
    )
    ap.add_argument("--project-root", required=True, help="raiz del repo_destino")
    ap.add_argument(
        "--motor-root",
        default=None,
        help="raiz del motor (por defecto: el de este script)",
    )
    ap.add_argument(
        "--slug",
        action="append",
        default=None,
        help="slug de memoria a verificar (repetible)",
    )
    ap.add_argument(
        "--json", action="store_true", help="salida JSON en vez de markdown"
    )
    args = ap.parse_args()

    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        # rc != 0 SOLO por fallo del recolector, nunca por un hallazgo del repo.
        print(
            f"[session-hop] ERROR: --project-root no existe: {project_root}",
            file=sys.stderr,
        )
        return 2

    motor_root = Path(args.motor_root).resolve() if args.motor_root else MOTOR_ROOT
    slugs = args.slug or [
        "obs-guard-green-only-counts-if-your-row-entered-its-denominator",
        "obs-dod-invariant-not-measurement",
    ]

    rep = build_report(motor_root, project_root, slugs)
    print(
        json.dumps(rep, ensure_ascii=False, indent=2)
        if args.json
        else render_markdown(rep)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
