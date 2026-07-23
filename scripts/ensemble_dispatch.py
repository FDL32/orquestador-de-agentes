#!/usr/bin/env python3
# ruff: noqa: S603
"""Ensemble dispatcher: bucles proposer/challenger multi-backend (WOT-2026-019o).

Before: el agents.json del MOTOR (schema 1.3+) declara `ensemble_profiles`,
    `ensemble_pipelines` y `ensemble_private_roots`, validados en capa UNICA
    por `.agent/agents_config.py::_validate_config`. El scorecard y la
    proyeccion viven en el destino-rol (`--project-root`), NUNCA en el motor.
During: expone subcomandos CLI:
    - `smoke`: round-trip por CONTENIDO (token en la respuesta), nunca por
      exit code (`opencode run` devuelve exit 0 con Auth Error, medido).
    - `run`: ejecuta un pipeline; ROUND 0 = premise_check es INVARIANTE del
      dispatcher (no configurable: las premisas falsas son el modo de fallo
      dominante medido). `task_type` se valida contra `TASK_TYPES` (enum
      cerrado) en la ENTRADA de `run_pipeline`, antes de ROUND 0; invalido
      -> ValueError (WOT-2026-025y, D2). Cada fila de ronda mide
      `latency_ms` con `time.perf_counter()` (monotonico, nunca estimado) y
      porta `session_id` opcional (`--session-id`). Escribe una fila de
      scorecard por CADA intervencion, incluida `no-aportacion` (sin ceros
      hay sesgo de supervivencia).
    - `adjudicate`: el TERCER rol (sesion orquestadora) adjudica el outcome
      con evidencia OBLIGATORIA; registra `adjudicator_backend`
      (OBLIGATORIO) y `adjudicator_model` (opcional) para no perder QUIEN
      adjudico, en campos NUEVOS que no tocan `backend`/`task_type`
      (siguen copiados del SOURCE: mover la identidad ahi corrompe la
      proyeccion, WOT-2026-025y). `session_id` en la fila adjudicada viene
      del flag `--session-id` de la adjudicacion, nunca del source. El veto
      humano usa `--supersede` (evento nuevo, nunca mutacion de filas:
      append-only se preserva por evento).
    - `leaders`: regenera `backend_leaders.json` DERIVADO del scorecard
      (hash de la fuente; lider solo con n>=5; politica de exploracion
      documentada en el propio artefacto).
    Todo envio a backend pasa por `send_to_profile`, cuyo PRIMER paso es
    `privacy_preflight` (fail-closed): backend sin `trusted:true` +
    (`data_sensitivity != public` O rutas bajo `ensemble_private_roots`)
    -> DispatchBlockedError ANTES de tocar red. Auth por-invocacion via la
    env var nombrada en `api_key_env` (`setx` no propaga a procesos vivos,
    medido). GENERACION B2: el dispatcher NUNCA aplica escrituras de un
    backend al arbol; solo captura propuestas (stdout + scorecard).
After: scorecard.jsonl (UTF-8 SIN BOM, append-only) y backend_leaders.json
    actualizados bajo `<destino>/.agent/runtime/ensemble/`; exit 0 en exito,
    1 en bloqueo/validacion, 2 en error de invocacion.

Resolucion de config MOTOR-EXPLICITA (M9 del contrato): la config se resuelve
desde la ubicacion de ESTE script, con independencia de AGENT_PROJECT_ROOT
(cuya prioridad 1 apuntaria al workspace, que no tiene claves ensemble_*).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent
_AGENT_DIR = MOTOR_ROOT / ".agent"
# APPEND, nunca insert(0): con .agent al frente, `runtime` resolveria a
# `.agent/runtime/` en vez de `<motor>/runtime/` (hazard documentado en
# AGENTS.md para la coleccion de pytest).
if str(_AGENT_DIR) not in sys.path:
    sys.path.append(str(_AGENT_DIR))

from agents_config import load_agents_config  # noqa: E402


SCORECARD_REL = Path(".agent/runtime/ensemble/scorecard.jsonl")
LEADERS_REL = Path(".agent/runtime/ensemble/backend_leaders.json")

SCORECARD_FIELDS = [
    "ts",
    "event",
    "ticket",
    "rol",
    "task_type",
    "backend",
    "model",
    "backend_version",
    "ronda",
    "outcome",
    "evidencia",
    "finding_confirmed_by",
    "adjudication_evidence",
    "input_bytes",
    "context_kind",
    "failure_mode",
    # WOT-2026-025y: los 4 campos siguientes van SIEMPRE al final. El
    # prefijo de 16 campos de arriba es INVARIANTE (frozen, ver
    # test_scorecard_fields_prefix_is_frozen): insertar algo en medio
    # reordena la comprehension de append_scorecard y rompe consumidores
    # posicionales.
    "session_id",
    "latency_ms",
    "adjudicator_backend",
    "adjudicator_model",
    # WOT-2026-037b: campos del registro citable de bucles, tambien SIEMPRE
    # al final por el mismo motivo (prefijo frozen invariante).
    "phase",
    "loop_id",
    "backend_key",
]

ADJUDICATED_OUTCOMES = {
    "adoptada",
    "rechazada-redundante",
    "falso-positivo",
    "error-factual",
    "no-aportacion",
}

TASK_TYPES = {
    "code-gen",
    "code-review",
    "prose",
    "translation",
    "triage",
    "contract-audit",
    "adjudication",
    "prompt-audit",
}

LEADER_MIN_N = 5
EXPLORATION_POLICY = (
    "1-de-5 rondas, o al cambiar la version del modelo/backend, el challenger "
    "se elige entre NO-lideres y se registra igual (sin exploracion el ranking "
    "se auto-confirma)"
)

PREMISE_CHECK_PREAMBLE = (
    "ROUND 0 - PREMISE CHECK (invariante del dispatcher): ANTES de refinar o "
    "proponer nada, verifica las premisas factuales del material siguiente. "
    "Lista cada premisa falsa, stale o no verificable con su evidencia. Si "
    "todas sostienen, responde PREMISES-OK y nada mas."
)


class DispatchBlockedError(RuntimeError):
    """El privacy_preflight bloqueo el envio (fail-closed)."""


def load_motor_config() -> dict:
    """Config del MOTOR, motor-explicita (M9): ignora AGENT_PROJECT_ROOT."""
    return load_agents_config(project_root=MOTOR_ROOT)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_project_root(raw: str) -> Path:
    """El destino-rol de los artefactos runtime. NUNCA el propio motor."""
    root = Path(raw).resolve()
    if root == MOTOR_ROOT:
        raise ValueError(
            "El dispatcher NUNCA escribe runtime en repo_motor: --project-root "
            "debe apuntar al destino-rol (workspace / repo_destino)"
        )
    return root


# WOT-2026-027n: gate de CONTENIDO, acotado a ASIGNACION CON VALOR DE ALTA
# ENTROPIA y a prefijos de credencial inequivocos. NUNCA substring suelto.
#
# POR QUE ACOTADO (medido 2026-07-22, no teorico): un gate por substring
# ('token', 'secret', 'api_key', 'sk-') bloquea bundles REALES del repo que
# citan esos terminos en PROSA TECNICA -- incluido el bundle de gobernanza de
# este mismo ticket, con lo que el vuelo se auto-bloquearia en su propio
# MANAGER_REVIEW. Un gate que bloquea el trabajo legitimo ensena al operador a
# saltarselo, y un gate que se saltan es peor que no tenerlo (anti-patron
# "aplicate tu propia vara", AGENTS.md). Los fixtures versionados de
# tests/fixtures/ensemble_bundles/ fijan ese limite: DEBEN pasar.
#
# RIESGO RESIDUAL DECLARADO (no lo cierra este ticket): de los 7 vectores
# medidos, esto cierra .env clasico, clave privada PEM y tokens con prefijo
# reconocible. SIGUEN SALIENDO: valor sin patron, base64 opaco, PII y rutas de
# maquina. Hoy el riesgo es BAJO porque el AGENTE elige que va en el bundle; se
# dispara cuando lo elija el MODELO (WOT-2026-027m, que declara 027n como
# precondicion dura).
_HIGH_ENTROPY_ASSIGNMENT = re.compile(
    r"(password|api_key|token|secret)\s*=\s*[\"'][^\"']{8,}[\"']",
    re.IGNORECASE,
)
_CREDENTIAL_LITERALS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _content_leak(payload_text: str) -> str | None:
    """Nombre del patron de credencial detectado, o None si el payload esta limpio.

    Before: `payload_text` es el material serializado que saldria hacia el
        backend. No se asume ningun encoding ni tamano.
    During: casa (1) asignacion `clave = "<valor de >=8 chars>"` y (2) los
        prefijos de credencial inequivocos. Ambos exigen un VALOR, de modo que
        la mencion en prosa del nombre de la clave no dispara.
    After: retorna la etiqueta del patron (para el `reason` del caller) o None.
        No lanza: el caller decide el veredicto.
    """
    if _HIGH_ENTROPY_ASSIGNMENT.search(payload_text):
        return "asignacion con valor de alta entropia"
    for pattern in _CREDENTIAL_LITERALS:
        if pattern.search(payload_text):
            return f"literal de credencial ({pattern.pattern})"
    return None


def privacy_preflight(
    payload_text: str,
    sensitivity: str | None,
    backend_cfg: dict,
    private_roots: list[str],
) -> tuple[bool, str]:
    """Barrera portable (CI/headless) contra fuga de contenido privado.

    Before: `payload_text` es el material serializado que saldria hacia el
        backend; `sensitivity` viene del caller (CLI) o del perfil; AUSENTE
        se trata como `private` (fail-closed); `backend_cfg` es la entrada de
        `backends` (con `trusted` opcional, ausente = false).
    During: un backend `trusted: true` pasa siempre. Para el resto: bloquea
        si la sensibilidad no es `public`; en la rama `public` bloquea ademas
        si el payload nombra una raiz de `ensemble_private_roots` (filtro por
        RUTA) o si contiene una credencial (filtro por CONTENIDO, WOT-2026-027n:
        `_content_leak`, acotado a asignacion con valor de alta entropia y a
        prefijos inequivocos -- la mencion en prosa NO dispara).
    After: retorna (allowed, reason). El caller DEBE abortar el envio si
        allowed es False; `send_to_profile` lo hace lanzando
        DispatchBlockedError ANTES de tocar red (mutation: sin este paso,
        el payload sale).
    """
    if backend_cfg.get("trusted") is True:
        return True, "backend trusted:true"
    effective = sensitivity or "private"
    if effective != "public":
        return False, (f"data_sensitivity={effective} hacia backend sin trusted:true")
    for root in private_roots or []:
        if root and root in payload_text:
            return False, f"payload contiene raiz privada declarada: {root}"
    leak = _content_leak(payload_text)
    if leak is not None:
        return False, f"payload contiene contenido sensible: {leak}"
    return True, "payload public sin raices privadas ni contenido sensible"


# WOT-2026-029f: api.nan.builders vive tras Cloudflare, que rechaza la firma
# por defecto de urllib (Python-urllib/3.x -> HTTP 403, body "error code: 1010")
# ANTES de evaluar la auth; con un UA explicito la MISMA clave devuelve 200
# (par medido 2026-07-18: "orquestador-ensemble/1.0" -> 200;
# "Python-urllib/3.12" -> 403/1010). Sin esta cabecera, todo el canal nan_api
# muere en el WAF y el 403 se confunde con clave invalida.
ENSEMBLE_USER_AGENT = "orquestador-ensemble/1.0"


def _transport_api(
    profile: dict, backend_cfg: dict, messages: list[dict], timeout: int
) -> str:
    """POST chat-completions con auth por-invocacion (env var de api_key_env)."""
    key_env = profile["api_key_env"]
    api_key = os.environ.get(key_env)
    if not api_key:
        raise RuntimeError(
            f"auth por-invocacion: la variable {key_env} no esta en el entorno"
        )
    body = json.dumps(
        {
            "model": profile.get("model"),
            "messages": messages,
            "temperature": 0,
        }
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 -- https exigido por el validador
        profile["api_base_url"],
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": ENSEMBLE_USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _kill_process_tree(pid: int) -> None:
    """Mata el ARBOL completo del proceso (Windows: taskkill /T /F).

    Motivo (medido 2026-07-16, smoke real): `codex exec` via shim .cmd spawnea
    node.exe que HEREDA los pipes; el timeout de subprocess.run mata solo al
    hijo directo y el communicate() posterior BLOQUEA para siempre esperando
    el EOF del pipe retenido por el descendiente superviviente. Sin kill de
    arbol, un backend colgado congela el smoke/piloto entero.
    """
    if os.name == "nt":
        taskkill = (
            Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
            / "System32"
            / "taskkill.exe"
        )
        subprocess.run(
            [str(taskkill), "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=30,
            shell=False,
        )
    else:  # pragma: no cover -- rama no-Windows
        import contextlib
        import signal

        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


def _transport_agent(
    profile: dict, backend_cfg: dict, messages: list[dict], timeout: int
) -> str:
    """One-shot CLI del backend (p.ej. `claude -p`, `codex exec`).

    El exit code NO se usa como veredicto (exit 0 con Auth Error, medido en
    opencode): el caller valida por CONTENIDO. En timeout se mata el ARBOL de
    procesos (ver _kill_process_tree) y se lanza RuntimeError: el caller lo
    registra como backend caido (STEP_SKIP), nunca lo inventa.

    WOT-2026-026n -- entrega del prompt:
    - Por DEFECTO el prompt va por argv (backward-compat).
    - Si el backend declara ``prompt_via_stdin: true``, el prompt va por STDIN
      (``communicate(input=...)``) y el cmd lleva el sentinel ``-``. Es la causa
      raiz del hang del bucle ``run`` en Windows: ``proposer_claude``
      (channel=agent) metia el payload completo en la linea de comando y el CLI
      colgaba (analogo al WinError 206 de codex, WOT-2026-035c, resuelto igual:
      prompt por stdin). Los backends ``channel: api`` (los nan) no pasan por
      aqui -- van por HTTP y nunca sufrieron el hang.

    WOT-2026-038o -- contrato de AMBITO:
    - `backend_cfg["repo_root"]` (opcional) es el arbol desde el que el hijo
      debe operar. Se pasa como `cwd=` al Popen SOLO si viene declarado; si
      falta, el hijo hereda el cwd del padre (conducta previa intacta).
    - Sin esto, un codex despachado por esta ruta refutaba sobre el arbol del
      PROCESO PADRE, no sobre el repo que la llamada declara. 038l cerro la
      misma clase de fallo en run_codex_audit.py y dejo ESTA ruta declarada
      OUT-OF-SCOPE; aqui se cierra con el mismo patron (repo_root opcional,
      `cwd=` condicional) y sin tocar la firma publica del transporte
      `transport(profile, backend_cfg, messages, timeout)`, que los tests
      inyectan como `_FakeTransport` con esa aridad exacta.
    """
    prompt = "\n\n".join(m["content"] for m in messages)
    via_stdin = bool(backend_cfg.get("prompt_via_stdin"))
    if via_stdin:
        cmd = [backend_cfg["executable"], *backend_cfg.get("args", []), "-"]
        stdin_mode = subprocess.PIPE
        stdin_payload: str | None = prompt
    else:
        cmd = [backend_cfg["executable"], *backend_cfg.get("args", []), prompt]
        stdin_mode = subprocess.DEVNULL
        stdin_payload = None
    repo_root = backend_cfg.get("repo_root")
    popen_kwargs: dict = {}
    if repo_root is not None:
        popen_kwargs["cwd"] = repo_root
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=stdin_mode,
        text=True,
        shell=False,
        encoding="utf-8",
        errors="replace",
        **popen_kwargs,
    )
    try:
        out, _err = proc.communicate(input=stdin_payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid)
        raise RuntimeError(
            f"backend CLI sin respuesta tras {timeout}s; arbol de procesos "
            "matado (pipe-inheritance hang, medido 2026-07-16)"
        ) from None
    return out or ""


def send_to_profile(
    profile_name: str,
    messages: list[dict],
    *,
    config: dict,
    sensitivity: str | None = None,
    transport=None,
    timeout: int = 120,
) -> str:
    """UNICO camino de salida hacia un backend; el preflight corre AQUI.

    Before: `profile_name` existe en `ensemble_profiles` (config validada);
        `messages` es la lista chat-completions; `sensitivity` es la del
        payload (CLI) o None (cae al perfil; ausente en ambos = private).
    During: (1) privacy_preflight fail-closed -- si bloquea, lanza
        DispatchBlockedError SIN tocar red; (2) resuelve transporte por
        `channel` (api|agent) salvo `transport` inyectado (tests hermeticos).
    After: retorna el texto de respuesta del backend (puede ser vacio: el
        caller lo registra como no-aportacion, nunca lo inventa).
    """
    profile = config["ensemble_profiles"][profile_name]
    backend_cfg = config["backends"][profile["backend"]]
    payload_text = json.dumps(messages, ensure_ascii=False)
    effective = sensitivity or profile.get("data_sensitivity")
    allowed, reason = privacy_preflight(
        payload_text,
        effective,
        backend_cfg,
        config.get("ensemble_private_roots", []),
    )
    if not allowed:
        raise DispatchBlockedError(
            f"privacy_preflight BLOQUEA el envio via '{profile_name}': {reason}"
        )
    if transport is None:
        transport = _transport_api if profile["channel"] == "api" else _transport_agent
    return transport(profile, backend_cfg, messages, timeout)


def append_scorecard(project_root: Path, row: dict) -> Path:
    """Append-only, UTF-8 SIN BOM, una linea JSON (claves normalizadas) por evento."""
    path = project_root / SCORECARD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {k: row.get(k) for k in SCORECARD_FIELDS}
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(normalized, ensure_ascii=False) + "\n")
    return path


def _read_scorecard(project_root: Path) -> tuple[list[dict], str]:
    path = project_root / SCORECARD_REL
    raw = path.read_bytes() if path.exists() else b""
    sha = hashlib.sha256(raw).hexdigest()
    rows = [
        json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()
    ]
    return rows, sha


def _adjudicated_cells(rows: list[dict]) -> dict:
    """Ultima adjudicacion por (ticket, ronda, rol); supersede pisa por orden."""
    adjudicated: dict = {}
    for row in rows:
        key = (row.get("ticket"), row.get("ronda"), row.get("rol"))
        if row.get("event") in ("adjudicacion", "supersede"):
            if row.get("outcome") in ADJUDICATED_OUTCOMES:
                adjudicated[key] = row
        elif row.get("event") == "ronda" and row.get("outcome") == "no-aportacion":
            adjudicated.setdefault(key, row)
    return adjudicated


def regenerate_leaders(project_root: Path) -> Path:
    """Proyeccion DERIVADA del scorecard: nunca editada a mano, regenerable.

    Lider por task_type SOLO con n>=LEADER_MIN_N; por debajo, 'sin lider,
    rotar'. Incluye hash sha256 de la fuente (proyeccion desfasada =
    detectable) y la politica de exploracion como campo del artefacto.
    """
    rows, sha = _read_scorecard(project_root)
    per_type: dict = {}
    for row in _adjudicated_cells(rows).values():
        task_type = row.get("task_type") or "desconocido"
        cells = per_type.setdefault(task_type, {})
        cell_key = f"{row.get('backend')}|{row.get('model')}"
        cell = cells.setdefault(
            cell_key,
            {
                "backend": row.get("backend"),
                "model": row.get("model"),
                "n": 0,
                "adoptadas": 0,
                "falsos": 0,
            },
        )
        cell["n"] += 1
        if row.get("outcome") == "adoptada":
            cell["adoptadas"] += 1
        if row.get("outcome") in ("falso-positivo", "error-factual"):
            cell["falsos"] += 1

    por_task_type: dict = {}
    for task_type, cells in per_type.items():
        best = max(
            cells.values(),
            key=lambda c: (c["adoptadas"] / c["n"] if c["n"] else 0.0, c["n"]),
        )
        if best["n"] >= LEADER_MIN_N:
            por_task_type[task_type] = {
                "lider": {"backend": best["backend"], "model": best["model"]},
                "n_muestras": best["n"],
                "tasa_adoptadas": round(best["adoptadas"] / best["n"], 3),
                "falsos": best["falsos"],
            }
        else:
            por_task_type[task_type] = {
                "lider": None,
                "nota": f"sin lider, rotar (n={best['n']} < {LEADER_MIN_N})",
                "n_muestras": best["n"],
            }

    out = {
        "generated_at": _now_iso(),
        "scorecard_sha256": sha,
        "leader_min_n": LEADER_MIN_N,
        "exploration_policy": EXPLORATION_POLICY,
        "por_task_type": por_task_type,
        "derivado": "NUNCA editar a mano: regenerado desde scorecard.jsonl",
    }
    out_path = project_root / LEADERS_REL
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out_path


def _backend_version(backend_cfg: dict) -> str | None:
    """Version del CLI del backend (best-effort); None para channel=api."""
    executable = backend_cfg.get("executable")
    if not executable:
        return None
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
        return (proc.stdout or proc.stderr or "").strip().splitlines()[0][:120]
    except Exception:
        return None


def smoke_profile(
    profile_name: str,
    *,
    config: dict,
    transport=None,
    nonce: str = "PONG-019o",
    timeout: int = 90,
) -> dict:
    """Smoke round-trip por CONTENIDO: el token debe volver en la respuesta."""
    messages = [
        {
            "role": "user",
            "content": (f"Reply with exactly this token and nothing else: {nonce}"),
        }
    ]
    try:
        reply = send_to_profile(
            profile_name,
            messages,
            config=config,
            sensitivity="public",
            transport=transport,
            timeout=timeout,
        )
    except DispatchBlockedError:
        raise
    except Exception as exc:  # STEP_SKIP documentado: backend caido no aborta
        return {
            "profile": profile_name,
            "alive": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }
    alive = nonce in (reply or "")
    return {
        "profile": profile_name,
        "alive": alive,
        "detail": (reply or "")[:200].strip(),
    }


def resolve_fallback_backend(
    pool_backend: str,
    *,
    config: dict,
    check_alive=None,
) -> str:
    """Elige un perfil de backend con `backend` DISTINTO al del pool auditado.

    Before: `pool_backend` es el valor `backend` (p.ej. `nan_api`) del pool
        que se esta auditando; "clase distinta" (WOT-2026-026k) se define
        como `profile["backend"] != pool_backend`, NUNCA una taxonomia mas
        fina. `config` es la config ya cargada (`load_motor_config()` o
        equivalente) con `ensemble_profiles` y `backends`. `check_alive` es
        inyectable para tests hermeticos; por defecto usa `smoke_profile`
        (round-trip real por CONTENIDO, nunca por exit code).
    During: recorre `ensemble_profiles` en orden estable (orden de
        insercion del dict de config), descarta los perfiles cuyo
        `backend` coincide con `pool_backend`, y prueba cada candidato con
        `check_alive(profile_name, config=config)` hasta encontrar uno
        vivo. `check_alive` debe devolver un dict con clave `alive: bool`
        (mismo contrato que `smoke_profile`).
    After: retorna el `profile_name` del primer candidato vivo de clase
        distinta. Si no hay NINGUN candidato de clase distinta (o ninguno
        vivo), lanza `DispatchBlockedError` fail-cerrado: el caller NUNCA
        debe caer de vuelta a `pool_backend` en silencio.
    """
    if check_alive is None:
        check_alive = smoke_profile

    profiles = config.get("ensemble_profiles", {})
    candidates = [
        name
        for name, profile in profiles.items()
        if profile.get("backend") != pool_backend
    ]
    if not candidates:
        raise DispatchBlockedError(
            f"sin candidatos de clase distinta a '{pool_backend}' en "
            "ensemble_profiles: fallback fail-cerrado (WOT-2026-026k)"
        )

    tried: list[str] = []
    for name in candidates:
        result = check_alive(name, config=config)
        tried.append(f"{name}:{'alive' if result.get('alive') else 'dead'}")
        if result.get("alive"):
            return name

    raise DispatchBlockedError(
        f"ningun candidato de clase distinta a '{pool_backend}' esta vivo "
        f"(probados: {', '.join(tried)}); fallback fail-cerrado (WOT-2026-026k)"
    )


def _load_lens_filter():
    """Importa `filter_lens_output` del script hermano (WOT-2026-039c).

    Before: `scripts/filter_lens_output.py` existe (entregado por 027o).
    During: carga por ruta y registra en sys.modules antes de ejecutar
        (el modulo carga a su vez check_bundle_receipts por el mismo patron).
    After: retorna la funcion. Lanza ImportError si no carga: sin filtro NO se
        corre en modo degradado -- un pipeline que declara el filtro y lo
        pierde en silencio seria exactamente el fail-open que este ticket
        cierra.
    """
    path = Path(__file__).resolve().parent / "filter_lens_output.py"
    spec = importlib.util.spec_from_file_location("filter_lens_output", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensivo
        raise ImportError(f"no se puede cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["filter_lens_output"] = module
    spec.loader.exec_module(module)
    return module.filter_lens_output


def _record_round(
    project_root: Path,
    *,
    ticket: str,
    task_type: str,
    rol: str,
    profile: dict,
    backend_version: str | None,
    ronda: int,
    reply: str,
    input_bytes: int,
    context_kind: str,
    failure_mode: str | None = None,
    session_id: str | None = None,
    latency_ms: int | None = None,
    outcome_override: str | None = None,
    phase: str | None = None,
    loop_id: str | None = None,
    backend_key: str | None = None,
) -> None:
    # WOT-2026-039c: `outcome_override` permite registrar una salida DESCARTADA
    # por el filtro de lente sin vaciar `reply` -- vaciarlo para forzar el
    # outcome mentiria sobre lo que respondio el backend y borraria la
    # evidencia. La derivacion original (texto vacio -> no-aportacion) se
    # conserva intacta cuando no se pasa override.
    text = (reply or "").strip()
    append_scorecard(
        project_root,
        {
            "ts": _now_iso(),
            "event": "ronda",
            "ticket": ticket,
            "rol": rol,
            "task_type": task_type,
            "backend": profile["backend"],
            "model": profile.get("model"),
            "backend_version": backend_version,
            "ronda": ronda,
            "outcome": outcome_override or ("no-aportacion" if not text else None),
            "evidencia": text[:500] or "(respuesta vacia)",
            "input_bytes": input_bytes,
            "context_kind": context_kind,
            "failure_mode": failure_mode,
            "session_id": session_id,
            "latency_ms": latency_ms,
            # WOT-2026-026q: ausentes (None) en las rondas del runner CLI, que
            # no pertenece a ningun bucle del registro citable.
            "phase": phase,
            "loop_id": loop_id,
            "backend_key": backend_key,
        },
    )


def run_loop_round(
    profile_name: str,
    content: str,
    *,
    config: dict,
    project_root: Path,
    ticket: str,
    task_type: str,
    rol: str,
    phase: str,
    loop_id: str,
    backend_key: str,
    sensitivity: str,
    ronda: int = 0,
    context_kind: str = "diff",
    transport=None,
    session_id: str | None = None,
) -> str:
    """UNA ronda de un bucle de GOBIERNO (`launched_from: chat`), registrada.

    WOT-2026-026q. `run_pipeline` es el runner de la CLI y registra SOLO sus
    propias rondas; los bucles `1->9->2` (CONTRACT_AUDIT, MANAGER_REVIEW,
    CLOSE) los despacha el chat paso a paso, sin pasar por ese bucle, y por
    eso su telemetria se perdia entera: el scorecard quedaba MUDO y los campos
    `phase`/`loop_id`/`backend_key` del schema (WOT-2026-037b) no tenian ni un
    escritor. Esta funcion es el hueco que faltaba en el RUNNER.

    El registro va AQUI y NO en `send_to_profile` a proposito: esa primitiva la
    comparte el smoke check (`_premise_check`), cuyo trafico NO debe contar --
    un backend caido no puede ensuciar el ranking-- y los callers de
    `run_pipeline` ya registran via `_record_round`. Cablearlo en la primitiva
    produciria doble-conteo mas ruido de smoke.

    Before: `profile_name` existe en `ensemble_profiles`; `task_type` pertenece
        a `TASK_TYPES`; `phase`/`loop_id`/`backend_key` son los del registro
        citable de bucles (`.agent/config/agents.json::ensemble_registry`, ver
        `scripts/discover_loops.py`).
    During: despacha por `send_to_profile` (el preflight de privacidad corre
        alli, fail-closed) cronometrando con `time.perf_counter()`; luego
        APPENDEA exactamente UNA fila via `_record_round`. Una respuesta vacia
        se registra como `no-aportacion`, nunca como fila ausente.
    After: retorna el texto del backend tal cual (el consolidador es el chat,
        nivel 0: esta funcion no interpreta ni adjudica). Propaga
        `DispatchBlockedError` si el preflight bloquea -- en ese caso NO hay
        fila, porque no hubo ronda.
    """
    if task_type not in TASK_TYPES:
        raise ValueError(
            f"task_type '{task_type}' invalido; usa uno de {sorted(TASK_TYPES)}"
        )
    profile = config["ensemble_profiles"][profile_name]
    _t0 = time.perf_counter()
    reply = send_to_profile(
        profile_name,
        [{"role": "user", "content": content}],
        config=config,
        sensitivity=sensitivity,
        transport=transport,
    )
    latency_ms = round((time.perf_counter() - _t0) * 1000)
    _record_round(
        project_root,
        ticket=ticket,
        task_type=task_type,
        rol=rol,
        profile=profile,
        backend_version=_backend_version(config["backends"][profile["backend"]]),
        ronda=ronda,
        reply=reply,
        input_bytes=len(content.encode("utf-8")),
        context_kind=context_kind,
        session_id=session_id,
        latency_ms=latency_ms,
        phase=phase,
        loop_id=loop_id,
        backend_key=backend_key,
    )
    return reply


def run_pipeline(
    pipeline_name: str,
    *,
    config: dict,
    project_root: Path,
    ticket: str,
    task_type: str,
    payload: str,
    sensitivity: str,
    context_kind: str = "diff",
    transport=None,
    max_rounds: int | None = None,
    session_id: str | None = None,
) -> list[dict]:
    """Ejecuta un bucle proposer/challenger. ROUND 0 = premise_check SIEMPRE.

    Before: `task_type` debe pertenecer a `TASK_TYPES` (enum cerrado); es la
        UNICA puerta de validacion (D2b: gobierna el 100% de la provenance,
        `append_scorecard` no revalida).
    During: B2 (default): las respuestas de los backends se capturan como
        PROPUESTAS (retorno + scorecard); este dispatcher no aplica nada al
        arbol. Cada envio a `send_to_profile` se cronometra con
        `time.perf_counter()` (monotonico) y el delta en ms entero se
        persiste como `latency_ms` de la fila. `session_id` (opcional) se
        propaga tal cual a cada fila de ronda.
    After: retorna el transcript en memoria; `ValueError` si `task_type` es
        invalido (WOT-2026-025y, D2), listando `sorted(TASK_TYPES)`.
    """
    if task_type not in TASK_TYPES:
        raise ValueError(
            f"task_type '{task_type}' invalido; usa uno de {sorted(TASK_TYPES)}"
        )
    pipe = config["ensemble_pipelines"][pipeline_name]
    rounds_cap = int(pipe.get("max_rounds", 2))
    total_rounds = min(max_rounds or rounds_cap, rounds_cap)
    participants = (
        ("proposer", pipe["proposer"]),
        ("challenger", pipe["challenger"]),
    )
    versions = {
        rol: _backend_version(
            config["backends"][config["ensemble_profiles"][prof]["backend"]]
        )
        for rol, prof in participants
    }
    input_bytes = len(payload.encode("utf-8"))
    transcript: list[dict] = []

    # ROUND 0: premise_check -- INVARIANTE del dispatcher, no configurable.
    for rol, prof_name in participants:
        profile = config["ensemble_profiles"][prof_name]
        content = f"{PREMISE_CHECK_PREAMBLE}\n\n{payload}"
        _t0 = time.perf_counter()
        reply = send_to_profile(
            prof_name,
            [{"role": "user", "content": content}],
            config=config,
            sensitivity=sensitivity,
            transport=transport,
        )
        latency_ms = round((time.perf_counter() - _t0) * 1000)
        _record_round(
            project_root,
            ticket=ticket,
            task_type=task_type,
            rol=rol,
            profile=profile,
            backend_version=versions[rol],
            ronda=0,
            reply=reply,
            input_bytes=input_bytes,
            context_kind=context_kind,
            session_id=session_id,
            latency_ms=latency_ms,
        )
        transcript.append({"ronda": 0, "rol": rol, "reply": reply})

    # WOT-2026-039c: filtro de salida de lente. Clave AUSENTE = OFF = conducta
    # heredada (aditividad real: los pipelines que no la declaran no cambian).
    # Solo aplica al CHALLENGER y solo en rondas >=1: la ronda 0 es el
    # premise_check, invariante del dispatcher, cuya respuesta legitima no
    # trae bloque cite y quedaria siempre descartada.
    lens_filter_on = bool(pipe.get("lens_output_filter", False))
    filter_lens_output = _load_lens_filter() if lens_filter_on else None

    rubric = pipe.get("rubric", "")
    for ronda in range(1, total_rounds + 1):
        for rol, prof_name in participants:
            profile = config["ensemble_profiles"][prof_name]
            if rol == "proposer":
                instruction = (
                    f"Ronda {ronda} (proposer). Rubrica canonica: {rubric}. "
                    "PROPON tu analisis/patch como texto (B2: el orquestador "
                    "aplica tras diff-review; tu NO escribes ficheros)."
                )
            else:
                instruction = (
                    f"Ronda {ronda} (challenger). Rubrica canonica: {rubric}. "
                    "REFUTA la propuesta anterior con evidencia concreta; si "
                    "no hay objecion CONFIRMADA con evidencia, dilo."
                )
            prior = "\n\n".join(
                f"[{t['rol']} r{t['ronda']}]\n{t['reply']}"
                for t in transcript
                if t["reply"] and not t.get("discarded_reason")
            )
            content = f"{instruction}\n\n=== MATERIAL ===\n{payload}\n\n=== RONDAS PREVIAS ===\n{prior}"
            _t0 = time.perf_counter()
            reply = send_to_profile(
                prof_name,
                [{"role": "user", "content": content}],
                config=config,
                sensitivity=sensitivity,
                transport=transport,
            )
            latency_ms = round((time.perf_counter() - _t0) * 1000)

            discarded_reason = None
            if filter_lens_output is not None and rol == "challenger" and reply:
                accepted, reason, problems = filter_lens_output(
                    reply, project_root, cite_only=True
                )
                if not accepted:
                    discarded_reason = reason
                    if problems:
                        discarded_reason = f"{reason}: {problems[0]}"

            _record_round(
                project_root,
                ticket=ticket,
                task_type=task_type,
                rol=rol,
                profile=profile,
                backend_version=versions[rol],
                ronda=ronda,
                reply=reply,
                input_bytes=input_bytes,
                context_kind=context_kind,
                session_id=session_id,
                latency_ms=latency_ms,
                failure_mode=discarded_reason,
                outcome_override="no-aportacion" if discarded_reason else None,
            )
            entry = {"ronda": ronda, "rol": rol, "reply": reply}
            if discarded_reason:
                # Se APPENDEA con marca (no se omite ni se vacia): el consumidor
                # conserva la salida descartada -- sin ceros hay sesgo de
                # supervivencia -- y el prior de la ronda siguiente la excluye.
                entry["discarded_reason"] = discarded_reason
            transcript.append(entry)
    return transcript


def adjudicate(
    project_root: Path,
    *,
    ticket: str,
    ronda: int,
    rol: str,
    outcome: str,
    evidence: str,
    adjudicator_backend: str | None = None,
    adjudicator_model: str | None = None,
    finding_confirmed_by: str | None = None,
    session_id: str | None = None,
    supersede: bool = False,
) -> Path:
    """Adjudicacion del TERCER rol (o veto humano via --supersede).

    Before: existe una fila `event=ronda` previa para (ticket, ronda, rol);
        `evidence` y `adjudicator_backend` son OBLIGATORIOS (idiom de
        evidence, WOT-2026-025y D4): una adjudicacion sin evidencia es
        relato y una sin adjudicador es anonima.
    During: La evidencia (comando + salida / artefacto) es OBLIGATORIA. El
        evento se APPENDEA (nunca muta filas previas) y regenera la
        proyeccion. `adjudicator_backend`/`adjudicator_model` registran QUIEN
        adjudico en columnas NUEVAS, sin tocar `backend`/`task_type`
        (siguen copiados del SOURCE: HALLAZGO 1, mover la identidad ahi
        corrompe el bucket/cell_key de `regenerate_leaders`).
        `session_id` se toma del FLAG de esta llamada, NUNCA de
        `source.get('session_id')` (es la sesion en que se ADJUDICA, no la
        de la ronda original).
    After: retorna la ruta de `backend_leaders.json` regenerado; lanza
        `ValueError` si `outcome`, `evidence` o `adjudicator_backend` son
        invalidos/ausentes, o si no existe la fila de ronda fuente.
    """
    if outcome not in ADJUDICATED_OUTCOMES:
        raise ValueError(
            f"outcome '{outcome}' invalido; usa uno de {sorted(ADJUDICATED_OUTCOMES)}"
        )
    if not evidence or not evidence.strip():
        raise ValueError(
            "adjudication_evidence es OBLIGATORIA (comando + salida o "
            "artefacto verificable); una adjudicacion sin evidencia es relato"
        )
    if not adjudicator_backend or not adjudicator_backend.strip():
        raise ValueError(
            "adjudicator_backend es OBLIGATORIO (WOT-2026-025y D4): la fila "
            "REGISTRA la identidad de quien adjudico (veto humano usa "
            "--adjudicator-backend human); una adjudicacion sin adjudicador "
            "es anonima"
        )
    rows, _sha = _read_scorecard(project_root)
    source = next(
        (
            r
            for r in reversed(rows)
            if r.get("event") == "ronda"
            and r.get("ticket") == ticket
            and r.get("ronda") == ronda
            and r.get("rol") == rol
        ),
        None,
    )
    if source is None:
        raise ValueError(
            f"no existe fila de ronda para (ticket={ticket}, ronda={ronda}, "
            f"rol={rol}): no se adjudica lo que no se registro"
        )
    append_scorecard(
        project_root,
        {
            "ts": _now_iso(),
            "event": "supersede" if supersede else "adjudicacion",
            "ticket": ticket,
            "rol": rol,
            "task_type": source.get("task_type"),
            "backend": source.get("backend"),
            "model": source.get("model"),
            "backend_version": source.get("backend_version"),
            "ronda": ronda,
            "outcome": outcome,
            "finding_confirmed_by": finding_confirmed_by,
            "adjudication_evidence": evidence,
            "input_bytes": source.get("input_bytes"),
            "context_kind": source.get("context_kind"),
            "session_id": session_id,
            "adjudicator_backend": adjudicator_backend,
            "adjudicator_model": adjudicator_model,
        },
    )
    return regenerate_leaders(project_root)


def _cmd_smoke(args, config) -> int:
    names = (
        [args.profile] if args.profile else sorted(config.get("ensemble_profiles", {}))
    )
    results = [smoke_profile(name, config=config) for name in names]
    print(json.dumps({"smoke": results}, ensure_ascii=False, indent=2))
    alive = sum(1 for r in results if r["alive"])
    print(
        f"[smoke] {alive}/{len(results)} backends vivos (veredicto por "
        "CONTENIDO, no por exit code)",
        file=sys.stderr,
    )
    return 0 if alive else 1


def _cmd_run(args, config) -> int:
    project_root = _resolve_project_root(args.project_root)
    payload = Path(args.payload_file).read_text(encoding="utf-8")
    transcript = run_pipeline(
        args.pipeline,
        config=config,
        project_root=project_root,
        ticket=args.ticket,
        task_type=args.task_type,
        payload=payload,
        sensitivity=args.data_sensitivity,
        context_kind=args.context_kind,
        max_rounds=args.max_rounds,
        session_id=args.session_id,
    )
    print(json.dumps({"transcript": transcript}, ensure_ascii=False, indent=2))
    return 0


def _cmd_adjudicate(args, config) -> int:
    project_root = _resolve_project_root(args.project_root)
    out_path = adjudicate(
        project_root,
        ticket=args.ticket,
        ronda=args.ronda,
        rol=args.rol,
        outcome=args.outcome,
        evidence=args.evidence,
        adjudicator_backend=args.adjudicator_backend,
        adjudicator_model=args.adjudicator_model,
        finding_confirmed_by=args.finding_confirmed_by,
        session_id=args.session_id,
        supersede=args.supersede,
    )
    print(f"[adjudicate] evento registrado; proyeccion regenerada: {out_path}")
    return 0


def _cmd_leaders(args, config) -> int:
    project_root = _resolve_project_root(args.project_root)
    out_path = regenerate_leaders(project_root)
    print(f"[leaders] proyeccion regenerada: {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ensemble dispatcher (WOT-2026-019o): proposer/challenger "
        "multi-backend con scorecard adjudicado."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_smoke = sub.add_parser("smoke", help="round-trip por contenido")
    p_smoke.add_argument("--profile", help="perfil concreto (default: todos)")

    p_run = sub.add_parser("run", help="ejecuta un pipeline")
    p_run.add_argument("--pipeline", required=True)
    p_run.add_argument("--ticket", required=True)
    p_run.add_argument("--task-type", required=True)
    p_run.add_argument("--payload-file", required=True)
    p_run.add_argument(
        "--data-sensitivity",
        required=True,
        choices=["public", "private", "secret"],
    )
    p_run.add_argument("--context-kind", default="diff")
    p_run.add_argument("--max-rounds", type=int, default=None)
    p_run.add_argument("--project-root", required=True)
    p_run.add_argument(
        "--session-id",
        default=None,
        help="sesion scratch opcional (D5: legitimo correr fuera de una)",
    )

    p_adj = sub.add_parser("adjudicate", help="adjudicar outcome de una ronda")
    p_adj.add_argument("--ticket", required=True)
    p_adj.add_argument("--ronda", type=int, required=True)
    p_adj.add_argument("--rol", required=True, choices=["proposer", "challenger"])
    p_adj.add_argument("--outcome", required=True)
    p_adj.add_argument("--evidence", required=True)
    p_adj.add_argument(
        "--adjudicator-backend",
        required=True,
        help="identidad de quien adjudico (OBLIGATORIO, D4); veto humano usa 'human'",
    )
    p_adj.add_argument("--adjudicator-model", default=None)
    p_adj.add_argument("--finding-confirmed-by", default=None)
    p_adj.add_argument(
        "--session-id",
        default=None,
        help="sesion en la que se ADJUDICA (nunca la del source)",
    )
    p_adj.add_argument(
        "--supersede",
        action="store_true",
        help="veto humano: evento supersede (nunca mutacion de filas)",
    )
    p_adj.add_argument("--project-root", required=True)

    p_lead = sub.add_parser("leaders", help="regenerar backend_leaders.json")
    p_lead.add_argument("--project-root", required=True)

    args = parser.parse_args(argv)
    config = load_motor_config()

    handlers = {
        "smoke": _cmd_smoke,
        "run": _cmd_run,
        "adjudicate": _cmd_adjudicate,
        "leaders": _cmd_leaders,
    }
    try:
        return handlers[args.command](args, config)
    except (DispatchBlockedError, ValueError) as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
