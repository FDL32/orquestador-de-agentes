#!/usr/bin/env python3
# ruff: noqa: RUF100
"""Detectores deterministas de causas de parada de un vuelo (se ejecuta en CADA tick del latido).

Before: ``comms_alert.py`` y ``notify_user.ps1`` viven junto a este fichero (nunca se
    carga codigo del directorio de operacion). Hace falta un directorio de operacion
    existente y ABSOLUTO (``--ops-dir`` o ``FLIGHT_OPS_DIR``, sin resolver = rc 2) con el
    estado ``stall_state.json`` y el ultimo cupo ``quota_last.txt``; el directorio del
    vuelo (``--flight-dir`` o ``FLIGHT_DIR``) aporta la cola del usuario: sin resolver el
    detector de cola queda ciego y se AVISA (``detector-sin-config``).
During: solo lectura (git status, ficheros, disco); avisa con ``comms_alert.event()`` y
    limita por clave. No llama a T3: lo que necesita estado de hilos lo mide el LLM del tick.
    Un detector ciego (cola ausente, git que no responde, configuracion invalida) avisa
    con AVISO (``detector-ciego-cola``, ``detector-ciego-git``, ``detector-sin-config``) y
    no borra las claves de las causas que no puede ver.
After: imprime una linea por hallazgo y un resumen. rc 0 = sin hallazgos, rc 1 = hubo
    hallazgos (avisados o ya avisados; ES NORMAL), rc 2 = el script o un aviso FALLO
    (``STALL_CHECK_BROKEN`` en la salida salvo aviso fallido): no se fie del silencio.
    En ``stall_state.json`` el latido escribe ``ts_latido`` (D25) y el contador ``motor_sucio``.
"""

import argparse
import calendar
import contextlib
import datetime as dt
import glob
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace


OPS_DIR_ENV = "FLIGHT_OPS_DIR"
FLIGHT_DIR_ENV = "FLIGHT_DIR"
NO_WINDOW = 0x08000000
FREE_GB_DEFAULT = 5.0
QUOTA_STALE_MIN = 40
QUOTA_SOFT_FALLBACK = 92
QUOTA_HARD_FALLBACK = 97
HEARTBEAT_STALE_S = 35 * 60
HEARTBEAT_KEY = "latido-muerto"
HEARTBEAT_OWNER = "task"
SIBLING_GLOBS = ("implantador-*", "triaje-*")
COLA_REL = Path("diseno") / "COLA_PARA_USUARIO.md"
GO_LINE_RE = re.compile(
    r"^- \[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] "
    r"\[(?P<owner>[A-Z]{2,3}-[0-9]{1,4})\] ABIERTA BLOQUEA \| "
    r"(?P<id>go-[a-z0-9](?:[a-z0-9-]{0,59}[a-z0-9])?): (?P<what>.*)$"
)
GO_RESOLVED_RE = re.compile(
    r"^- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] "
    r"\[[A-Z]{2,3}-[0-9]{1,4}\] RESUELTA(?:-SIN-EFECTO)? \| "
    r"(?P<id>go-[a-z0-9](?:[a-z0-9-]{0,59}[a-z0-9])?): .*$"
)
QUOTA_NAME = "quota_last.txt"
QUOTA_READ_MAX = 4096
DIAG_TICKS = 2
URGENTE_TICKS = 4
TICK_GAP_MAX_MIN = 30
OCIO_TICKS_MIN = 2
OCIO_IM_MIN = 2
GRACIA_IM_MIN = 5
GRACIA_MIN = 15
EXPOSICION_H = 24
ILEGIBLES_MAX_FRAC = 0.5
HUERFANO_CAP_TICK = 10
CO_TOPE = 3
CO_GRACIA_MIN = 15
CO_TITLE_RE = re.compile(r"^CO-\d{1,4}(?:\s|$)")
CO_TERMINAL_RUNS = frozenset(
    {"completed", "failed", "interrupted", "cancelled", "canceled"}
)
QUEUE_MOTIVES = {
    "NO_DECLARADO",
    "CADUCADO",
    "CERO",
    "SIN_BRIEF",
    "FLT_NO_DISJUNTO",
    "TOPE_ALCANZADO",
    "SIN_GO",
    "BUILDER_O_LENTE_VIVO",
    "CUPO",
    "OTRO",
}
FLIGHT_ROSTER_NAME = "flight_roster.json"
STATE_NAME = "stall_state.json"
TASK_STATE_NAME = "task_state.json"
OWNED_PREFIXES = (
    "cupo-",
    "cola-",
    "ocio-con-cola",
    "git-",
    "disco",
    "hook-",
    "detector-",
    "huerfano-",
    "gasto-",
    "co-sin-asentar",
)
GIT_MARKERS = ("index.lock", "MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD")

_CA = None
CFG = None
DETECTOR_NAMES = (
    "quota",
    "cola",
    "git",
    "ocio-con-cola",
    "disco",
    "hook",
    "im-ocioso",
    "cola-despachable",
    "huerfano",
)
DETECTOR_NAMES += ("presupuesto-nan",)
DETECTOR_NAMES += ("co-sin-asentar",)
RETIRED_EVENT_KEYS = ("tarea-muerta", "celda-no-conforme")
NAN_POOL_CREDITS = 7000.0
NAN_RESET_AT = "2026-12-07T00:00:00+00:00"
NAN_UNKNOWN_KEY = "nan_unknown_streak"
NAN_SOURCE_ENV = ("NAN_OPENCODE_DB", "NAN_KILO_DB")
NAN_AGENTS_ENV = "NAN_AGENTS_JSON"
_CELL_CHECKER = None


def _load_alert():
    """Carga ``comms_alert.py`` de junto a ESTE fichero (D17), una sola vez.

    Before: ``comms_alert.py`` existe junto a ``__file__``.
    During: importlib por ruta; nunca busca en el directorio de operacion.
    After: devuelve el modulo (cacheado); propaga la excepcion de carga.
    """
    global _CA
    if _CA is None:
        path = Path(__file__).resolve().with_name("comms_alert.py")
        spec = importlib.util.spec_from_file_location("comms_alert", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CA = mod
    return _CA


def _load_cell_checker():
    """Carga el comprobador de celdas por ruta del motor.

    Before: ``check_cell_conformance.py`` vive junto a este detector.
    During: usa importlib para conservar el aislamiento de imports del vuelo.
    After: devuelve el modulo cacheado o propaga el fallo de carga al aislador.
    """
    global _CELL_CHECKER
    if _CELL_CHECKER is None:
        path = Path(__file__).resolve().with_name("check_cell_conformance.py")
        spec = importlib.util.spec_from_file_location("check_cell_conformance", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"no se pudo cargar {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _CELL_CHECKER = module
    return _CELL_CHECKER


def _load_json_dict(path):
    """Lee un JSON que debe ser un diccionario; cualquier otra forma = ``{}``.

    Before: ``path`` es un Path (puede no existir).
    During: lee con utf-8-sig (tolera BOM) y parsea.
    After: dict; vacio si el fichero falta, no se lee, no es JSON, no es un objeto o es
        tan anidado que desborda el parser.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _state():
    """Carga el estado persistente del latido.

    Before: ``CFG.state`` apunta a ``stall_state.json``.
    During: delega en ``_load_json_dict`` para leer utf-8-sig y tolerar entradas ilegibles.
    After: devuelve un diccionario o ``{}`` si el fichero falta, es invalido o no es objeto.
    """
    return _load_json_dict(CFG.state)


def _count(value):
    """Normaliza el contador persistido de un worktree sucio.

    Before: ``value`` puede tener cualquier tipo por proceder del estado JSON.
    During: acepta solo un entero no booleano entre cero y un millon exclusivo.
    After: devuelve el entero aceptado o ``0`` para cualquier otra forma.
    """
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**6:
        return value
    return 0


def _is_finite(value):
    """Comprueba si un valor es un numero finito y no booleano.

    Before: ``value`` puede ser cualquier objeto del estado.
    During: valida ``int`` o ``float`` no booleano y aplica ``math.isfinite`` dentro
        de una guarda contra el desborde de conversion a ``float``.
    After: devuelve ``True`` solo para numeros finitos convertibles a ``float``;
        devuelve ``False`` para booleanos, objetos de otro tipo, valores no finitos
        y enteros cuyo ``float()`` desborda, sin propagar ``OverflowError``.
    """
    if not (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _git(path, *args):
    """Ejecuta git (ruta absoluta de ``shutil.which``) y devuelve (rc, stdout).

    Before: ``path`` es un directorio; git esta en el PATH.
    During: ``git -C path args`` con timeout de 30 s y sin ventana (en Windows).
    After: (returncode, stdout sin espacios); FileNotFoundError si no hay git y
        TimeoutExpired si no responde (el llamador los trata como detector roto).
    """
    exe = shutil.which("git")
    if exe is None:
        raise FileNotFoundError("git no esta en el PATH")
    flags = NO_WINDOW if os.name == "nt" else 0
    r = subprocess.run(  # noqa: S603 - ruta absoluta de git, argumentos propios
        [exe, "-C", str(path), *args],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=flags,
        check=False,
    )
    return r.returncode, (r.stdout or "").strip()


def _quota_accounts(text):
    """Cuentas de quota_tick: porcentajes, ilegible, STALE y cuenta desconocida.

    Before: ``text`` es la salida de una linea ``QUOTA ... | <cuenta> <ventana> <pct>%[ STALE] | ...``.
    During: por cuenta (hasta el siguiente ``|``) toma el ULTIMO token ``<algo>%`` (el productor
        imprime ``<cuenta> <ventana> <pct>%`` y la ventana va cruda, puede contener ``N%``) y lo
        lee ENTERO como imprime Python el ``block_pct`` crudo: entero, decimal (97.0, 92.5), con
        signo y con exponente (1e+20, 1e-05, 1.5e+300, 1E5); un valor entero exacto se devuelve int.
    After: ``(pcts, sin_pct, stale, desconocida)``; ``None%``, ``inf%`` o ausencia de ``%``
        cuentan como sin porcentaje; un segmento ajeno con ``N%`` marca ``desconocida``.
        El segmento codex se excluye por prefijo y quota_tick sanea ``|`` dentro de su parte informativa.
    """
    pcts, sin_pct, stale, desconocida, account_pcts = [], False, False, False, []
    for segment in text.split("|")[1:]:
        if re.match(r"\s*codex(?:\s|$)", segment):
            continue
        m = re.match(r"\s*(?:alvarovans|brabander)(?=\s)(.*)", segment)
        if m is None:
            desconocida = desconocida or re.search(r"\S+%", segment) is not None
            continue
        rest = m.group(1)
        stale = stale or re.search(r"\bSTALE\b", rest) is not None
        # el pct es el ULTIMO token: la ventana se imprime cruda y puede contener "N%"
        toks = re.findall(r"\S+%", rest)
        num = (
            re.fullmatch(r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)%", toks[-1])
            if toks
            else None
        )
        value = float(num.group(1)) if num else math.inf
        if math.isfinite(value):
            normalized = int(value) if value.is_integer() else value
            pcts.append(normalized)
            account_pcts.append((m.group(0).split()[0], normalized))
        else:
            sin_pct = True
    return pcts, sin_pct, stale, desconocida, account_pcts


def check_quota(out):
    """Detector de cupo: lee ``quota_last.txt`` (salida de quota_tick.py).

    Before: ``CFG.quota`` apunta al fichero (o es None si la configuracion era invalida).
    During: lee como mucho ``QUOTA_READ_MAX + 1`` caracteres; si la lectura supera la cota,
        queda ciego + ``cupo-no-medido`` sin truncar en silencio. Ausente = ciego + ``cupo-no-medido``;
        sin porcentajes (o una cuenta sin el suyo) =
        ciego + ``cupo-ilegible``; mas de 40 min, cabecera ``QUOTA NO_MEDIDO`` o una cuenta
        ``STALE`` = ciego + ``cupo-no-medido``; maximo >= 97 URGENTE, >= 92 AVISO.
    After: lista de (clave, nivel, texto); ``out`` recibe ``ciego_cupo`` y ``cupo_max``. Un cupo
        ciego no borra las claves ``cupo-*`` ya avisadas (lo impide el reconcile).
    """
    q = CFG.quota
    if q is None:
        out["ciego_cupo"] = True
        out["cupo_max"] = None
        return []
    if not q.exists():
        out["ciego_cupo"] = True
        out["cupo_max"] = None
        return [
            (
                "cupo-no-medido",
                "AVISO",
                "Cupo sin medir: no existe la salida de quota_tick.py",
            )
        ]
    age_min = (time.time() - q.stat().st_mtime) / 60
    with q.open("r", encoding="utf-8", errors="replace") as stream:
        text = stream.read(QUOTA_READ_MAX + 1)
    if len(text) > QUOTA_READ_MAX:
        out["ciego_cupo"] = True
        out["cupo_max"] = None
        return [
            (
                "cupo-no-medido",
                "AVISO",
                f"La salida del cupo supera la cota de lectura de {QUOTA_READ_MAX} caracteres",
            )
        ]
    pcts, sin_pct, stale, desconocida, account_pcts = _quota_accounts(text)
    declara = re.search(r"\bNO_MEDIDO\b", text.split("|", 1)[0]) is not None
    razones = _quota_reasons(age_min, declara, stale)
    ilegible = (not pcts or sin_pct) and not declara
    found = []
    if razones or ilegible:
        out["ciego_cupo"] = True
    if ilegible:
        found.append(
            (
                "cupo-ilegible",
                "AVISO",
                "La salida del cupo no tiene porcentajes legibles",
            )
        )
    if razones:
        found.append(("cupo-no-medido", "AVISO", "; ".join(razones)))
    if desconocida:
        found.append(
            (
                "cupo-cuenta-desconocida",
                "AVISO",
                "La salida del cupo contiene una cuenta no reconocida",
            )
        )
    found += _quota_levels(account_pcts)
    out["cupo_max"] = max(pcts) if pcts else None
    return found


def _quota_reasons(age_min, declara_no_medido, stale):
    """Construye las razones por las que una medicion de cupo queda ciega.

    Before: ``age_min`` es la antiguedad y los otros argumentos indican cabecera o cuenta stale.
    During: compara la antiguedad con ``QUOTA_STALE_MIN`` y prioriza ``NO_MEDIDO`` sobre ``STALE``.
    After: devuelve una lista de textos de razon, posiblemente vacia, sin efectos laterales.
    """
    razones = []
    if age_min > QUOTA_STALE_MIN:
        razones.append(f"El cupo lleva {int(age_min)} min sin medirse")
    if declara_no_medido:
        razones.append("quota_tick declara NO_MEDIDO")
    elif stale:
        razones.append("una cuenta del cupo esta STALE")
    return razones


def _quota_levels(pcts):
    """Clasifica el peor porcentaje de cupo en un hallazgo.

    Before: ``pcts`` contiene porcentajes ya parseados y puede estar vacio.
    During: toma el maximo y aplica los cortes 97 (URGENTE) y 92 (AVISO).
    After: devuelve como mucho ``cupo-97`` o ``cupo-92``; sin corte devuelve ``[]``.
    """
    if not pcts:
        return []
    if pcts and isinstance(pcts[0], tuple):
        worst_account, worst = max(pcts, key=lambda item: item[1])
    else:
        worst_account, worst = "desconocida", max(pcts)
    soft = getattr(CFG, "quota_soft", QUOTA_SOFT_FALLBACK)
    hard = getattr(CFG, "quota_hard", QUOTA_HARD_FALLBACK)
    fallback = " (corte de respaldo)" if getattr(CFG, "quota_fallback", True) else ""
    if worst >= hard:
        return [
            (
                "cupo-97",
                "URGENTE",
                f"Cupo de {worst_account} al {worst}% (corte duro {hard}%){fallback}: los implantadores se interrumpen",
            )
        ]
    if worst >= soft:
        return [
            (
                "cupo-92",
                "AVISO",
                f"Cupo de {worst_account} al {worst}% (congelado suave {soft}%){fallback}",
            )
        ]
    return []


def check_cola(out, st):
    """Detector de la cola del usuario: toda linea ABIERTA no resuelta es una causa.

    Before: ``CFG.cola`` apunta a ``COLA_PARA_USUARIO.md`` (o es None sin flight-dir).
    During: lee con utf-8-sig; ABIERTA sin RESUELTA avisa (BLOQUEA = URGENTE, si no AVISO);
        la clave ``cola-<sha1[:8]>`` de la linea es estable entre ticks. El resumen se
        redacta y DESPUES se acota a 60 caracteres (D21).
    After: lista de hallazgos; cola ausente = ciego + ``detector-ciego-cola`` AVISO.
    """
    del st
    out.setdefault("session_codes", {})
    if CFG.cola is None:
        out["ciego_cola"] = True
        return []
    if not CFG.cola.exists():
        out["ciego_cola"] = True
        return [
            (
                "detector-ciego-cola",
                "AVISO",
                "El detector de la cola esta ciego: no existe COLA_PARA_USUARIO.md",
            )
        ]
    alert_mod = _load_alert()
    redact = alert_mod.redact
    found = []
    abiertas = 0
    lines = CFG.cola.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    resolved_go = {
        match.group("id") for line in lines if (match := GO_RESOLVED_RE.fullmatch(line))
    }
    for line in lines:
        go_match = GO_LINE_RE.fullmatch(line)
        if go_match and go_match.group("id") in resolved_go:
            continue
        if "ABIERTA" not in line or "RESUELTA" in line:
            continue
        abiertas += 1
        if go_match:
            key = go_match.group("id")
            what = alert_mod.redact_literal_first(
                go_match.group("what"), preserve_literal=True
            )
            out["session_codes"][key] = go_match.group("owner")
            found.append((key, "URGENTE", what))
            continue
        h = hashlib.sha1(line.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        resumen = re.sub(r"^- \[[^\]]*\] \[[^\]]*\] ABIERTA \| ", "", line)
        nivel = "URGENTE" if "BLOQUEA" in line else "AVISO"
        found.append(
            (
                "cola-" + h,
                nivel,
                f"Decision pendiente del usuario [cola-{h}]: {redact(resumen)[:60]}",
            )
        )
    out["cola_abiertas"] = abiertas
    return found


def _worktrees():
    """Reune el motor y sus worktrees hermanos sin duplicados.

    Before: ``CFG.motor`` y ``CFG.wt_globs`` contienen la raiz y los globos a vigilar.
    During: expande los globos, normaliza las rutas cuando puede y deduplica con ``normcase``.
    After: devuelve una lista de ``Path`` que empieza por el motor y no repite rutas.
    """
    seen, paths = set(), []
    for p in [
        CFG.motor,
        *(Path(x) for g in CFG.wt_globs for x in sorted(glob.glob(g))),
    ]:
        try:
            key = os.path.normcase(str(p.resolve()))
        except OSError:
            key = os.path.normcase(str(p))
        if key not in seen:
            seen.add(key)
            paths.append(p)
    return paths


def _git_markers(p):
    """Hallazgos de bloqueo de git (index.lock, MERGE_HEAD, ...) en UN worktree.

    Before: ``p`` puede no ser un repositorio o puede tener una entrada ``.git`` rota; la
        entrada se detecta sin seguir enlaces mediante ``os.path.lexists``; un enlace colgante cuenta.
    During: una entrada ``.git`` ausente se trata como no-repo; si existe pero ``rev-parse``
        falla, se emite un AVISO con solo el basename de ``p``; después busca los marcadores.
    After: ``list`` de hallazgos ``git-*`` sin rutas absolutas; el no-repo sigue siendo silencio.
    """
    git_entry = p / ".git"
    if not os.path.lexists(git_entry):
        return []
    rc, gitdir = _git(p, "rev-parse", "--absolute-git-dir")
    if rc != 0:
        return [
            (
                f"git-gitdir-{p.name}",
                "AVISO",
                f"Git no pudo resolver su directorio de datos en {p.name}",
            )
        ]
    gd = Path(gitdir)
    return [
        (
            f"git-{name.lower()}-{p.name}",
            "AVISO",
            f"Git bloqueado en {p.name}: existe {name}",
        )
        for name in GIT_MARKERS
        if (gd / name).exists()
    ]


def check_git(out, st):
    """Detector de git: bloqueos en el motor y hermanos, y motor sucio dos ticks seguidos.

    Before: ``CFG.motor`` es un directorio absoluto (None = configuracion invalida).
    During: marcadores de bloqueo por worktree; ``git status --porcelain`` del motor sin
        ficheros sin seguimiento; el contador ``motor_sucio`` del estado sube con cada tick
        sucio y vuelve a 0 al limpiar (un valor no entero del estado cuenta 0).
    After: lista de hallazgos; si status falla = ciego + ``detector-ciego-git`` AVISO.
        git ausente o sin responder PROPAGA (el llamador lo marca ``detector-roto``).
    """
    out["git_marcadores"] = []
    if CFG.motor is None:
        out["ciego_git"] = True
        return []
    found = []
    previo = _count(st.get("motor_sucio"))
    for p in _worktrees():
        if p.exists():
            markers = _git_markers(p)
            out["git_marcadores"] += markers
            found += markers
    rc, porc = _git(CFG.motor, "status", "--porcelain", "--untracked-files=no")
    n = len([x for x in porc.splitlines() if x.strip()]) if rc == 0 else -1
    out["motor_sucio"] = n
    if n < 0:
        out["ciego_git"] = True
        found.append(
            (
                "detector-ciego-git",
                "AVISO",
                "El detector de git esta ciego: git status fallo en el motor",
            )
        )
    st["motor_sucio"] = (previo + 1) if n > 0 else 0
    if n > 0 and st["motor_sucio"] >= 2:
        found.append(
            (
                "git-motor-sucio",
                "AVISO",
                f"La rama del vuelo lleva {n} ficheros modificados en dos ticks seguidos (integrate_ticket exige limpio)",
            )
        )
    return found


def _load_queue_checker():
    """Load the sibling queue eligibility module by filesystem path.

    Before: ``cola_apta.py`` is next to this detector and exposes ``cola_apta``.
    During: import the sibling without relying on the current working directory.
    After: return the loaded module or propagate its import failure.
    """
    path = Path(__file__).resolve().with_name("cola_apta.py")
    spec = importlib.util.spec_from_file_location("cola_apta", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _reset_ocio_con_cola(st):
    """Reset the persisted ocio-con-cola streak and identity.

    Before: ``st`` is the mutable heartbeat state.
    During: clear both the consecutive-tick counter and its identity snapshot.
    After: the next qualifying tick starts a fresh streak.
    """
    st["ocio_con_cola_ticks"] = 0


def _is_im_ready(row):
    """Return whether one cola_apta row is an IM-READY work item.

    Before: ``row`` is a dictionary returned by the sibling queue module.
    During: apply the five fixed IM-READY fields without considering TR state.
    After: return a boolean eligibility decision.
    """
    return (
        row.get("apta")
        and row.get("tiene_brief")
        and row.get("flt_conocido")
        and not row.get("flt_conflicto")
    )


def _started_within_grace(session):
    """Return whether a registry session started within the grace window.

    Before: ``session`` may contain an ISO-8601 ``started`` field.
    During: parse the field and compare it with the detector clock.
    After: return true only for a parseable non-future start no older than five minutes.
    """
    raw = session.get("started")
    if not isinstance(raw, str):
        return False
    try:
        started = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=dt.timezone.utc)
    now = getattr(CFG, "nan_now", None) or (
        dt.datetime.fromisoformat(os.environ["NAN_NOW"]).astimezone(dt.timezone.utc)
        if "NAN_NOW" in os.environ
        else dt.datetime.fromtimestamp(time.time(), tz=dt.timezone.utc)
    )
    age = (now - started.astimezone(dt.timezone.utc)).total_seconds()
    return 0 <= age <= GRACIA_IM_MIN * 60


def check_ocio_con_cola(out, st):  # noqa: C901 - source gates stay explicit
    """Detect queued IM-ready work with fewer than two stable live IMs.

    Before: ``CFG`` resolves flight, registry, store, and quota paths; ``out`` contains
        the results of the preceding queue and git detectors.
    During: measure live IMs through the shared checker/store, apply the started grace,
        inspect the sibling queue module, and reject measurable approval, queue, quota,
        or git explanations.
    After: return the ``ocio-con-cola`` AVISO only after two qualifying ticks; persist
        the identity and streak, or reset them whenever any gate is false.
    """
    if (
        CFG.registry is None
        or not CFG.registry.is_file()
        or CFG.store is None
        or not CFG.store.is_file()
    ):
        _reset_ocio_con_cola(st)
        return []
    checker = _load_cell_checker()
    sessions = checker._registry(CFG.registry)
    connection, _, settled = checker._store_lookup(CFG.store)
    try:
        live = checker.live_ims(sessions, settled)
        live_ids = {
            str(session.get("threadId") or session.get("code")) for session in live
        }
        live_ids.update(
            str(session.get("threadId") or session.get("code"))
            for session in sessions
            if session.get("role") == "implantacion" and _started_within_grace(session)
        )
        try:
            pending = connection.execute(
                "SELECT 1 FROM projection_pending_approvals "
                "WHERE resolved_at IS NULL AND "
                "(lower(COALESCE(status, '')) IN ('pending', 'pendiente') "
                "OR (decision IS NULL AND lower(COALESCE(status, '')) NOT IN ('resolved', 'resuelta'))) LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            out["ocio_con_cola_ciego"] = "e1-desconocido"
            _reset_ocio_con_cola(st)
            return []
    finally:
        connection.close()
    evento_e1 = pending is not None
    out["ocio_con_cola_evento_e1"] = evento_e1
    if "cupo_max" not in out:
        out["ocio_con_cola_ciego"] = "cuota-desconocida"
        _reset_ocio_con_cola(st)
        return []
    if out.get("ciego_cupo") or out.get("cupo_max") is None:
        out["ocio_con_cola_ciego"] = "cuota-desconocida"
        _reset_ocio_con_cola(st)
        return []
    block_pct = out["cupo_max"]
    evento_e3 = bool(block_pct >= getattr(CFG, "quota_soft", QUOTA_SOFT_FALLBACK))
    flight_dir = CFG.cola.parent.parent if CFG.cola is not None else None
    if flight_dir is None or CFG.registry is None:
        _reset_ocio_con_cola(st)
        return []
    backlog = Path(flight_dir).parents[2] / "collaboration" / "backlog.md"
    try:
        queue_checker = _load_queue_checker()
        rows = queue_checker.cola_apta(backlog, CFG.registry, backlog.parent)
    except (OSError, ImportError, TypeError, ValueError):
        rows = []
    im_vivos = len(live_ids)
    if im_vivos < OCIO_IM_MIN:
        pass
    else:
        _reset_ocio_con_cola(st)
        return []
    hay_im_ready = any(_is_im_ready(row) for row in rows)
    if (
        not hay_im_ready
        or evento_e1
        or out.get("cola_abiertas", 0) > 0
        or evento_e3
        or out.get("git_marcadores")
    ):
        _reset_ocio_con_cola(st)
        return []
    prior_ids = set(st.get("ocio_con_cola_ids", []))
    if "ocio_con_cola_ids" in st and prior_ids != live_ids:
        _reset_ocio_con_cola(st)
        st["ocio_con_cola_ids"] = sorted(live_ids)
        return []
    ticks = _count(st.get("ocio_con_cola_ticks")) + 1
    st.update({"ocio_con_cola_ticks": ticks, "ocio_con_cola_ids": sorted(live_ids)})
    if ticks < OCIO_TICKS_MIN:
        return []
    return [("ocio-con-cola", "AVISO", "Hay trabajo IM-READY y menos de dos IM vivos")]


def check_disk(out):
    """Detecta si queda menos disco libre que el umbral configurado.

    Before: ``CFG.disk_anchor`` identifica la unidad y ``CFG.free_gb_min`` su minimo en GB.
    During: consulta ``shutil.disk_usage``, convierte bytes a GB y guarda el redondeo en ``out``.
    After: devuelve el aviso ``disco`` si queda por debajo o ``[]``; propaga errores de la consulta.
    """
    anchor = CFG.disk_anchor
    free_gb = shutil.disk_usage(anchor).free / 1e9
    out["disco_libre_gb"] = round(free_gb)
    if free_gb < CFG.free_gb_min:
        label = str(anchor).rstrip("\\/") or str(anchor)
        return [("disco", "AVISO", f"Quedan {free_gb:.1f} GB libres en {label}")]
    return []


def check_hook(out):
    """Detector del hook de seguridad de la rama del vuelo (``claude_guard_entry.py``).

    Before: ``CFG.motor`` puede ser ``None`` o una ruta existente.
    During: valida primero que ``git rev-parse`` resuelva el worktree; un fallo deja el
        detector ciego y no se interpreta como hook ausente.
    After: hook ausente en un worktree válido = URGENTE; no-worktree o repo roto = AVISO ciego.
    """
    if CFG.motor is None:
        out["ciego_hook"] = True
        return []
    rc, _ = _git(CFG.motor, "rev-parse", "--absolute-git-dir")
    if rc != 0:
        out["ciego_hook"] = True
        return [
            (
                "detector-ciego-hook",
                "AVISO",
                "El detector del hook esta ciego: git no pudo resolver el worktree",
            )
        ]
    guard = CFG.motor / ".agent" / "hooks" / "claude_guard_entry.py"
    out["hook_guard_existe"] = guard.exists()
    if not guard.exists():
        return [
            (
                "hook-seguridad",
                "URGENTE",
                "No existe .agent/hooks/claude_guard_entry.py en la rama del vuelo: el hook de seguridad bloquea TODA escritura",
            )
        ]
    return []


def self_check(a):
    """Comprueba que existen y compilan los tres scripts (junto a ``__file__``), la cola y el motor.

    Before: nada que configurar salvo flight-dir/motor (el ops-dir no hace falta).
    During: lee los ficheros del propio directorio; compila los .py; resuelve cola y motor.
    After: imprime ``self-check: OK`` o los problemas; devuelve 0 o 2.
    """
    here = Path(__file__).resolve().parent
    bad = []
    for name in ("comms_alert.py", "notify_user.ps1", "flight_stall_check.py"):
        f = here / name
        if not f.exists():
            bad.append("falta " + name)
        elif name.endswith(".py"):
            try:
                compile(f.read_text(encoding="utf-8-sig"), str(f), "exec")
            except (SyntaxError, ValueError, OSError) as exc:
                bad.append(f"sintaxis {name}: {type(exc).__name__}")
    cfg, causes, fatal = _resolve_paths(a, None)
    bad += causes
    if fatal:
        bad.append(fatal)
    if cfg.cola is not None and not cfg.cola.exists():
        bad.append("no existe la cola del usuario")
    if cfg.motor is not None and not cfg.motor.exists():
        bad.append("no existe el motor")
    print("self-check:", "OK" if not bad else "; ".join(bad))
    return 0 if not bad else 2


def _is_unc(cand):
    """Comprueba si una ruta representa un recurso UNC de red.

    Before: ``cand`` es un ``Path`` construido desde la configuracion.
    During: inspecciona ``drive`` y excluye la forma extendida local ``\\?\\C:``.
    After: devuelve ``True`` para drives UNC de red y ``False`` para rutas locales.
    """
    return cand.drive.startswith("\\\\") and not re.fullmatch(
        r"\\\\\?\\[A-Za-z]:", cand.drive
    )


def _resolve_dir(raw, label):
    """Resuelve y valida un directorio local de configuracion.

    Before: ``raw`` es una ruta candidata y ``label`` identifica el parametro.
    During: rechaza UNC y rutas relativas, resuelve con ``strict=True`` y comprueba que sea directorio.
    After: devuelve el ``Path`` real o lanza ``ValueError`` con la causa etiquetada.
    """
    cand = Path(raw)
    if _is_unc(cand):
        raise ValueError(f"{label} en ruta de red (UNC) no admitida")
    if not cand.is_absolute():
        raise ValueError(f"{label} debe ser una ruta absoluta")
    try:
        real = cand.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} no existe o no se resuelve") from exc
    if not real.is_dir():
        raise ValueError(f"{label} no es un directorio")
    return real


def _resolve_paths(a, ops):  # noqa: C901
    """Resuelve cola, motor, worktrees, cupo y umbral de disco (argumento > entorno > derivado).

    Before: ``a`` son los argumentos; ``ops`` es el directorio de operacion ya resuelto
        (None en ``--self-check``).
    During: cada ruta invalida deja ciego SOLO a su detector y suma una causa; el umbral
        de disco invalido es un error de configuracion.
    After: (cfg, causas de detector-sin-config, error fatal o None).
    """
    env = os.environ
    causes = []
    cfg = SimpleNamespace(
        ops=ops,
        state=None,
        cola=None,
        motor=None,
        quota=None,
        quota_soft=QUOTA_SOFT_FALLBACK,
        quota_hard=QUOTA_HARD_FALLBACK,
        quota_fallback=True,
        tick_trace=None,
        roster_quota={},
        session_code=None,
        registry=None,
        store=Path(
            env.get("T3_STATE_DB", Path.home() / ".t3" / "userdata" / "statev2.sqlite")
        ),
        nan_sources={},
    )
    default_nan = {
        "opencode": Path.home() / ".local" / "share" / "opencode" / "opencode.db",
        "kilo": Path.home() / ".local" / "share" / "kilo" / "kilo.db",
    }
    for name, variable in zip(("opencode", "kilo"), NAN_SOURCE_ENV, strict=True):
        raw_source = env.get(variable, str(default_nan[name]))
        cfg.nan_sources[name] = Path(raw_source) if raw_source else None
    cfg.wt_globs, cfg.free_gb_min, cfg.disk_anchor = [], FREE_GB_DEFAULT, Path("/")
    if ops is not None:
        cfg.state = ops / STATE_NAME
    raw = a.flight_dir or env.get(FLIGHT_DIR_ENV)
    try:
        if not raw:
            raise ValueError(
                f"flight-dir sin resolver: pasa --flight-dir o define {FLIGHT_DIR_ENV}"
            )
        cfg.cola = _resolve_dir(raw, "flight-dir") / COLA_REL
        cfg.registry = Path(raw) / "session_registry.json"
        roster = Path(raw) / FLIGHT_ROSTER_NAME
        if roster.is_file():
            try:
                value = json.loads(roster.read_text(encoding="utf-8"))
                quota = value.get("quota", {})
                if isinstance(quota, dict):
                    cfg.roster_quota = quota
                    soft_valid = _is_finite(quota.get("soft_freeze_block_pct"))
                    hard_valid = _is_finite(quota.get("hard_stop_block_pct"))
                    if soft_valid:
                        cfg.quota_soft = quota["soft_freeze_block_pct"]
                    if hard_valid:
                        cfg.quota_hard = quota["hard_stop_block_pct"]
                    cfg.quota_fallback = not (soft_valid and hard_valid)
                candidate = (
                    value.get("active_roles", {})
                    .get("orquestador", {})
                    .get("session_code")
                )
                if re.fullmatch(r"[A-Z]{2,3}-[0-9]{1,4}", str(candidate or "")):
                    cfg.session_code = candidate
            except (OSError, ValueError, AttributeError):
                pass
        cfg.tick_trace = Path(raw) / "ops" / "tick_trace.jsonl"
    except ValueError as exc:
        causes.append(str(exc))
    raw = a.motor_wt or env.get("STALL_MOTOR_WT")
    motor = Path(raw) if raw else Path(__file__).resolve().parents[2]
    if _is_unc(motor):
        causes.append("motor-wt en ruta de red (UNC) no admitida")
    elif motor.is_absolute():
        cfg.motor = motor
        cfg.disk_anchor = Path(motor.anchor or "/")
        globs = env.get("STALL_WT_GLOB")
        cfg.wt_globs = (
            [globs]
            if globs
            else [glob.escape(str(motor.parent)) + os.sep + g for g in SIBLING_GLOBS]
        )
    else:
        causes.append("motor-wt debe ser una ruta absoluta")
    raw = a.quota_file or env.get("STALL_QUOTA_FILE")
    if raw and _is_unc(Path(raw)):
        causes.append("quota-file en ruta de red (UNC) no admitida")
    elif raw and not Path(raw).is_absolute():
        causes.append("quota-file debe ser una ruta absoluta")
    elif raw:
        cfg.quota = Path(raw)
    elif ops is not None:
        cfg.quota = ops / QUOTA_NAME
    if ops is not None:
        cfg.tick_trace = ops / "tick_trace.jsonl"
    fatal = _free_gb_min(cfg, env.get("STALL_FREE_GB_MIN"))
    return cfg, causes, fatal


def check_im_ocioso(out, st):
    """Avisa cuando hay menos de dos IM vivos y existe cola apta.

    Before: ``CFG`` tiene registry/store resueltos y ``out`` fue poblado por
        ``check_cola``.
    During: carga el comprobador compartido, consulta solo los hilos de las
        sesiones y usa su predicado ``live_ims``; no notifica ni escribe estado.
    After: devuelve un hallazgo ``im-ocioso`` o una causa ciega; los fallos de
        lectura se propagan para que ``_detect`` produzca ``detector-roto``.
    """
    del st
    if out.get("cola_abiertas", 0) <= 0:
        return []
    if CFG.registry is None or not CFG.registry.is_file():
        out["im_ocioso_ciego"] = "registry"
        return [
            ("detector-ciego-im-ocioso", "AVISO", "Detector IM ocioso sin registry")
        ]
    if CFG.store is None or not CFG.store.is_file():
        out["im_ocioso_ciego"] = "store"
        return [
            (
                "detector-ciego-im-ocioso",
                "AVISO",
                "Detector IM ocioso sin almacen T3",
            )
        ]
    checker = _load_cell_checker()
    sessions = checker._registry(CFG.registry)
    connection, _, settled = checker._store_lookup(CFG.store)
    try:
        vivos = checker.live_ims(sessions, settled)
    finally:
        connection.close()
    if len(vivos) < 2:
        return [("im-ocioso", "AVISO", f"Hay {len(vivos)} IM vivos con cola apta")]
    return []


def _free_gb_min(cfg, raw):
    """Fija el umbral de disco a partir de la configuracion textual.

    Before: ``cfg`` es el namespace de configuracion y ``raw`` es el valor opcional del entorno.
    During: convierte ``raw`` a ``float`` y valida finitud y no negatividad; si falta conserva el default.
    After: devuelve ``None`` cuando es valido o el texto del error fatal cuando no lo es.
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value < 0:
        return "STALL_FREE_GB_MIN invalido (numero finito no negativo)"
    cfg.free_gb_min = value
    return None


def _save_state(st):
    """Guarda el estado del latido de forma atomica (tmp UNICO por PID + replace).

    Before: ``CFG.state`` y su directorio existen; ``st`` es serializable.
    During: escribe ``stall_state.<pid>.tmp`` y lo sustituye con os.replace.
    After: el estado viejo queda integro si algo falla; el tmp se limpia y el OSError se propaga.
    """
    tmp = CFG.state.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
        )
        os.replace(tmp, CFG.state)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _save_task_state(ts):
    """Guarda el reloj de la tarea con un temporal propio y sustitucion atomica.

    Before: ``CFG.ops`` existe y ``ts`` es un numero finito del reloj inyectado o real.
    During: escribe solo ``task_state.<pid>.tmp`` y lo sustituye por ``task_state.json``.
    After: queda un estado JSON con ``ts_tarea``; ante un fallo se elimina el temporal y se
        propaga ``OSError`` sin tocar el estado anterior.
    """
    target = CFG.ops / TASK_STATE_NAME
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps({"ts_tarea": ts}, ensure_ascii=False, indent=1),
            encoding="utf-8",
            newline="\n",
        )
        os.replace(tmp, target)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _heartbeat_observation(st, now):
    """Clasifica el reloj del latido actual o el campo ``ts`` de transicion.

    Before: ``st`` es el diccionario tolerante de ``stall_state.json`` y ``now`` es el reloj.
    During: prefiere ``ts_latido``; si falta usa el ``ts`` legado, acepta solo relojes finitos
        no futuros y considera stale solo si pasa de 35 minutos (exclusivo).
    After: devuelve ``(ok, nombre_reloj, motivo)``; no escribe estado ni emite avisos.
    """
    if "ts_latido" in st:
        name, value = "ts_latido", st.get("ts_latido")
    elif "ts" in st:
        name, value = "ts antiguo", st.get("ts")
    else:
        return False, "ts_latido", "ts_latido ausente"
    if not _is_finite(value) or value > now:
        return False, name, f"{name} ausente o ilegible"
    age = now - value
    if age > HEARTBEAT_STALE_S:
        return False, name, f"{name} viejo: lleva {int(age / 60)} min sin actualizar"
    return True, name, "fresco"


def _heartbeat_check(a, ca):
    """Ejecuta exclusivamente la sonda que la tarea programada usa cuando T3 esta cerrado.

    Before: ``CFG`` esta resuelto, ``ca`` esta configurado y ``a`` contiene heartbeat-check.
    During: lee ``stall_state.json``, clasifica ``ts_latido`` o el ``ts`` de transicion, avisa
        solo ``latido-muerto`` con owner ``task`` y, fuera de dry-run, escribe ``ts_tarea``.
    After: devuelve 0 si el reloj es fresco, 2 si es viejo/ilegible o si falla el aviso/estado;
        nunca ejecuta los detectores ni escribe ``ts_latido``.
    """
    st = _load_json_dict(CFG.state)
    now = time.time()
    fresh, clock_name, reason = _heartbeat_observation(st, now)
    found = [] if fresh else [(HEARTBEAT_KEY, "URGENTE", reason)]
    state_failed = False
    if not a.dry_run:
        try:
            _save_task_state(now)
        except OSError as exc:
            print(
                f"STALL_CHECK_BROKEN: task_state: {type(exc).__name__}: {str(exc)[:120]}"
            )
            state_failed = True
    if fresh:
        if "event:" + HEARTBEAT_KEY in ca.load_state() and not a.dry_run:
            ca.resolve(HEARTBEAT_KEY, False)
        print(f"heartbeat-check: {clock_name} {reason}")
        return 2 if state_failed else 0
    if a.dry_run:
        print(f"URGENTE {HEARTBEAT_KEY} dry-run: {reason}")
        return 2
    notify_rc = _notify_all(ca, found, a, {}, owner=HEARTBEAT_OWNER)
    return max(2, notify_rc) if state_failed else 2


def _trace_records():
    """Read the bounded tick trace through its production compatibility reader.

    Before: ``CFG.tick_trace`` points to the operation trace file.
    During: parse JSONL records and ignore malformed lines without inventing queue state.
    After: return ordered dictionaries, including legacy v1 records without new fields.
    """
    target = getattr(CFG, "tick_trace", None) or (CFG.ops / "tick_trace.jsonl")
    if not target.is_file():
        return []
    records = []
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines()[
        -256:
    ]:
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _trace_ts(record):
    """Parse an offset-bearing trace timestamp or return null."""
    raw = record.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _queue_reason(record):
    """Validate the CUPO motive against the same tick's destination summary."""
    motive = record.get("cola_motivo")
    if motive != "CUPO":
        return motive if motive in QUEUE_MOTIVES else "OTRO", "motivo " + str(
            motive or "NO_DECLARADO"
        )
    destination = record.get("destino")
    accounts = record.get("quota_accounts")
    if (
        not isinstance(destination, str)
        or not destination
        or not isinstance(accounts, list)
    ):
        return "OTRO", "motivo OTRO NO_MEDIDO"
    for item in accounts:
        if not isinstance(item, dict) or item.get("cuenta") != destination:
            continue
        pct = item.get("block_pct")
        state = item.get("estado_operativo")
        if (
            _is_finite(pct) and pct >= getattr(CFG, "quota_soft", QUOTA_SOFT_FALLBACK)
        ) or state in {
            "CAMBIO",
            "PREPARACION",
        }:
            return "CUPO", f"motivo CUPO: {destination} {pct}%"
    return "OTRO", "motivo OTRO NO_MEDIDO"


def check_cola_despachable(out, st):
    """Report a dispatchable queue left idle across consecutive heartbeat ticks.

    Before: tick trace records and registry/store configuration are available.
    During: require two close positive queue declarations and fewer than two live IMs.
    After: return an AVISO or URGENTE finding without launching or mutating any IM.
    """
    del st
    records = _trace_records()
    if (
        not records
        or CFG.registry is None
        or not CFG.registry.is_file()
        or CFG.store is None
        or not CFG.store.is_file()
    ):
        return []
    checker = _load_cell_checker()
    sessions = checker._registry(CFG.registry)
    connection, _, settled = checker._store_lookup(CFG.store)
    try:
        live = checker.live_ims(sessions, settled)
    finally:
        connection.close()
    if len(live) >= 2:
        return []
    streak = []
    for record in reversed(records):
        queue = record.get("cola_despachable")
        if not isinstance(queue, int) or isinstance(queue, bool) or queue <= 0:
            break
        if streak:
            current_ts = _trace_ts(streak[-1])
            prior_ts = _trace_ts(record)
            if (
                current_ts is None
                or prior_ts is None
                or (current_ts - prior_ts).total_seconds() > TICK_GAP_MAX_MIN * 60
            ):
                break
        streak.append(record)
        if len(streak) >= URGENTE_TICKS:
            break
    if len(streak) < DIAG_TICKS:
        return []
    latest = streak[0]
    _motive, detail = _queue_reason(latest)
    level = "URGENTE" if len(streak) >= URGENTE_TICKS else "AVISO"
    return [
        (
            "cola-despachable-ociosa",
            level,
            f"Cola despachable ociosa ({len(streak)} ticks), {detail}",
        )
    ]


def now_utc():
    """Return the timezone-aware UTC clock used by the orphan detector.

    Before: the process clock is available and returns seconds since the epoch.
    During: convert the current timestamp to an explicit UTC datetime.
    After: return a timezone-aware ``datetime`` suitable for age comparisons.
    """
    return dt.datetime.fromtimestamp(time.time(), tz=dt.timezone.utc)


def _huerfano_blind(out, cause):
    """Build the observable fail-closed result for the orphan detector.

    Before: ``out`` is the current tick accumulator and ``cause`` names a known blindness.
    During: record the cause and create one diagnostic finding without changing stall state.
    After: return the diagnostic finding; the caller upgrades the tick to rc 2.
    """
    out["huerfano_ciego"] = cause
    return [
        (
            "detector-ciego-huerfano",
            "AVISO",
            f"Detector huerfano ciego: {cause}",
        )
    ]


def _huerfano_registry():
    """Read literal thread identifiers from the selected registry.

    Before: ``CFG.registry`` points to the flight registry file.
    During: decode the JSON object and preserve each identifier as a string without normalization.
    After: return the exact identifier set or raise ``ValueError`` for a missing or malformed file.
    """
    if CFG.registry is None or not CFG.registry.is_file():
        raise ValueError("registry-missing")
    try:
        value = json.loads(CFG.registry.read_text(encoding="utf-8"))
        sessions = value.get("sessions") if isinstance(value, dict) else None
        if not isinstance(sessions, list):
            raise ValueError("registry-missing")
        return {
            str(item.get("threadId"))
            for item in sessions
            if isinstance(item, dict) and item.get("threadId") is not None
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("registry-missing") from exc


def _huerfano_date(raw, current):
    """Parse an aware creation timestamp and return its age in minutes.

    Before: ``raw`` is the projection ``created_at`` value and ``current`` is UTC-aware.
    During: parse ISO-8601 without accepting naive or future timestamps.
    After: return a non-negative age in minutes, or ``None`` for an invalid date.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = dt.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        return None
    age = (current - value.astimezone(dt.timezone.utc)).total_seconds() / 60
    return age if age >= 0 else None


def check_huerfano(out, st):  # noqa: C901 - explicit fail-closed branches are contractual
    """Find first-level agent threads absent from the literal session registry.

    Before: ``CFG.store`` and ``CFG.registry`` resolve to readable flight artifacts; ``out``
        is the tick accumulator and ``st`` is the existing heartbeat state.
    During: read projection rows and pending approvals in SQLite read-only mode, validate the
        payload/date contract, classify the UTC window, and calculate stable SHA-1 alert keys.
        The cap applies only to emitted findings while ``huerfano_activos`` retains every live key.
    After: return AVISO/URGENTE findings, expose active keys and counters, or return an observable
        fail-closed finding with ``out["huerfano_ciego"]``; never mutate ``st``.
    """
    del st
    if CFG.registry is None:
        return _huerfano_blind(out, "registry-missing")
    if CFG.store is None or not CFG.store.exists():
        return _huerfano_blind(out, "store-missing")
    try:
        connection = sqlite3.connect(f"file:{CFG.store}?mode=ro", uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
    except (OSError, sqlite3.Error) as exc:
        return _huerfano_blind(
            out, "store-unavailable" if isinstance(exc, OSError) else "store-corrupt"
        )
    try:
        try:
            rows = connection.execute(
                "SELECT thread_id, runtime_mode, created_at, deleted_at, payload_json "
                "FROM orchestration_v2_projection_threads WHERE deleted_at IS NULL"
            ).fetchall()
            pending = (
                connection.execute(
                    "SELECT 1 FROM projection_pending_approvals WHERE resolved_at IS NULL "
                    "AND (lower(COALESCE(status, '')) IN ('pending', 'pendiente') "
                    "OR (decision IS NULL AND lower(COALESCE(status, '')) NOT IN ('resolved', 'resuelta'))) LIMIT 1"
                ).fetchone()
                is not None
            )
        except sqlite3.OperationalError as exc:
            return _huerfano_blind(
                out,
                "store-corrupt"
                if "no such table" in str(exc).lower()
                else "store-unavailable",
            )
        except sqlite3.DatabaseError:
            return _huerfano_blind(out, "store-corrupt")
    finally:
        connection.close()
    if not rows:
        return _huerfano_blind(out, "store-empty")
    try:
        registered = _huerfano_registry()
    except ValueError as exc:
        return _huerfano_blind(out, str(exc))
    current = now_utc()
    illegible = 0
    bad_dates = 0
    candidates = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            illegible += 1
            continue
        lineage = payload.get("lineage") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or not isinstance(lineage, dict)
            or "parentThreadId" not in lineage
            or "createdBy" not in payload
        ):
            illegible += 1
            continue
        age = _huerfano_date(row["created_at"], current)
        if age is None:
            bad_dates += 1
            continue
        if (
            lineage["parentThreadId"] is not None
            or payload["createdBy"] != "agent"
            or str(row["thread_id"]) in registered
            or row["deleted_at"] is not None
            or age <= GRACIA_MIN
            or age > EXPOSICION_H * 60
        ):
            continue
        thread_id = str(row["thread_id"])
        key = "huerfano-" + hashlib.sha1(str(thread_id).encode("utf-8")).hexdigest()[:12]  # noqa: S324  # fmt: skip
        level = (
            "URGENTE" if pending or row["runtime_mode"] == "full-access" else "AVISO"
        )
        candidates.append((key, level, thread_id, row["created_at"]))
    out["huerfano_ilegibles"] = illegible
    out["huerfano_fecha_ilegible"] = bad_dates
    if illegible / len(rows) >= ILEGIBLES_MAX_FRAC:
        return _huerfano_blind(out, "payload-illegible")
    candidates.sort(key=lambda item: item[3])
    activos = {item[0] for item in candidates}
    total = len(candidates)
    if total > HUERFANO_CAP_TICK:
        activos.add("huerfano-resumen")
    out["huerfano_activos"] = sorted(activos)
    found = [
        (key, level, f"Hilo huerfano {thread_id} fuera del registry")
        for key, level, thread_id, _created in candidates[:HUERFANO_CAP_TICK]
    ]
    if total > HUERFANO_CAP_TICK:
        found.append(("huerfano-resumen", "AVISO", f"{total} hilos huerfanos vigentes"))
    return found


def _nan_json_records(path):
    """Read a bounded JSON fixture/source used by the NaN detector.

    Before: ``path`` identifies a readable JSON source.
    During: read at most one megabyte and accept a list or one mapping.
    After: return ``(records, reason)``; malformed or oversized input is UNKNOWN.
    """
    try:
        with path.open("rb") as handle:
            raw = handle.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return [], "source-too-large"
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, ValueError, RecursionError):
        return [], "source-corrupt"
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value, None
    if isinstance(value, dict):
        return [value], None
    return [], "source-schema"


def _nan_period_start(now=None):
    """Calculate the starting timestamp of the current Nan accounting period.

    Before: ``now`` is an optional UTC datetime; when absent it resolves from CFG or wall clock.
    During: read the reset day and UTC time from configuration and determine the closest past reset boundary.
    After: return the exact UTC datetime for the period start.
    """
    if now is None:
        raw_now = getattr(CFG, "nan_now", None)
        if raw_now is not None:
            now = raw_now
        elif "NAN_NOW" in os.environ:
            now = dt.datetime.fromisoformat(os.environ["NAN_NOW"])
        else:
            now = dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    else:
        now = now.astimezone(dt.timezone.utc)

    raw = os.environ.get(NAN_AGENTS_ENV)
    path = Path(raw) if raw else None
    data = _load_json_dict(path) if path and path.exists() else {}
    registry = data.get("ensemble_registry", {})
    if not isinstance(registry, dict):
        registry = {}
    presupuesto = registry.get("presupuesto_nan", {})
    periodo = presupuesto.get("periodo", {}) if isinstance(presupuesto, dict) else {}
    if not periodo:
        canon_path = (
            Path(__file__).resolve().parents[2] / ".agent" / "config" / "agents.json"
        )
        canon_data = _load_json_dict(canon_path)
        canon_reg = canon_data.get("ensemble_registry", {})
        canon_presupuesto = (
            canon_reg.get("presupuesto_nan", {}) if isinstance(canon_reg, dict) else {}
        )
        periodo = (
            canon_presupuesto.get("periodo", {})
            if isinstance(canon_presupuesto, dict)
            else {}
        )
    dia = int(periodo.get("dia_reinicio", 7))
    hora_str = str(periodo.get("hora_reinicio_utc", "18:31:00"))
    parts = hora_str.split(":")
    hour = int(parts[0]) if len(parts) > 0 else 18
    minute = int(parts[1]) if len(parts) > 1 else 31
    second = int(parts[2]) if len(parts) > 2 else 0

    max_day_curr = calendar.monthrange(now.year, now.month)[1]
    candidate_curr = dt.datetime(
        now.year,
        now.month,
        min(dia, max_day_curr),
        hour,
        minute,
        second,
        0,
        tzinfo=dt.timezone.utc,
    )
    if now >= candidate_curr:
        return candidate_curr

    if now.month == 1:
        prev_year = now.year - 1
        prev_month = 12
    else:
        prev_year = now.year
        prev_month = now.month - 1
    max_day_prev = calendar.monthrange(prev_year, prev_month)[1]
    return dt.datetime(
        prev_year,
        prev_month,
        min(dia, max_day_prev),
        hour,
        minute,
        second,
        0,
        tzinfo=dt.timezone.utc,
    )


def _nan_pricing_table():
    """Read the Nan model pricing table and metadata declarations from agents.json.

    Before: agents.json contains ensemble_registry with precios and backend_keys.
    During: resolve rates per million credits for all declared keys and aliases.
    After: return (pricing_map, meta_config).
    """
    raw = os.environ.get(NAN_AGENTS_ENV)
    path = Path(raw) if raw else None
    data = _load_json_dict(path) if path and path.exists() else {}
    registry = data.get("ensemble_registry", {})
    if not isinstance(registry, dict):
        registry = {}
    if not registry.get("precios") or not registry.get("backend_keys"):
        canon_path = (
            Path(__file__).resolve().parents[2] / ".agent" / "config" / "agents.json"
        )
        canon_data = _load_json_dict(canon_path)
        canon_reg = canon_data.get("ensemble_registry", {})
        if not registry.get("precios"):
            registry["precios"] = canon_reg.get("precios", {})
        if not registry.get("backend_keys"):
            registry["backend_keys"] = canon_reg.get("backend_keys", {})
        if not registry.get("presupuesto_nan"):
            registry["presupuesto_nan"] = canon_reg.get("presupuesto_nan", {})
    precios = registry.get("precios", {})
    backend_keys = registry.get("backend_keys", {})
    presupuesto = registry.get("presupuesto_nan", {})

    meta_cfg = {
        "gratuitos": set(
            presupuesto.get(
                "modelos_gratuitos_declarados", ["nan/qwen3.6", "nan/gemma4"]
            )
        ),
        "fuera_pool": set(
            presupuesto.get("proveedores_fuera_del_pool", ["opencode", "opencode-go"])
        ),
        "periodo": presupuesto.get("periodo", {}),
    }

    pricing_map = {}
    for k, pinfo in precios.items():
        rate = pinfo.get("precio_por_m_creditos", {})
        tin = float(rate.get("entrada_sin_cache", 0.0))
        tcache = float(rate.get("cache", 0.0))
        tout = float(rate.get("salida", 0.0))
        binfo = backend_keys.get(k, {})
        m = binfo.get("model")
        if m:
            pricing_map[m] = (tin, tcache, tout)
            if m.startswith("nan/"):
                pricing_map[m[4:]] = (tin, tcache, tout)
            else:
                pricing_map[f"nan/{m}"] = (tin, tcache, tout)
        pricing_map[k] = (tin, tcache, tout)

    return pricing_map, meta_cfg


def _nan_parse_model(model_raw):
    """Normalize model identifiers from string or JSON structure to (provider, model_id)."""
    if isinstance(model_raw, dict):
        mid = model_raw.get("id") or model_raw.get("model") or ""
        prov = (
            model_raw.get("providerID")
            or model_raw.get("provider")
            or model_raw.get("backend")
            or ""
        )
        return str(prov), str(mid)
    if isinstance(model_raw, str):
        raw = model_raw.strip()
        if raw.startswith("{") and raw.endswith("}"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    mid = parsed.get("id") or parsed.get("model") or ""
                    prov = (
                        parsed.get("providerID")
                        or parsed.get("provider")
                        or parsed.get("backend")
                        or ""
                    )
                    return str(prov), str(mid)
            except (ValueError, TypeError):
                pass
        if "/" in raw:
            parts = raw.split("/", 1)
            return parts[0], parts[1]
        return "", raw
    return "", ""


def _nan_sqlite_records(path, source):  # noqa: C901
    """Read a bounded metadata sample and a complete credit aggregate.

    Before: ``path`` is an existing SQLite database and ``source`` names its producer.
    During: open URI read-only; if an explicit credit column exists, aggregate via 24h window;
        if the real session table exists with token columns, aggregate within the dynamic
        period and multiply by model rates; ignore unbilled tokens and provider models outside the pool.
    After: return ``(records, provenance, reason)`` without mutating the database.
    """
    connection = None
    records = []
    schema = []
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5.0)
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name LIMIT 100"
            )
        ]
        preferred = (
            ("message", "session")
            if source == "opencode"
            else (
                "session_message",
                "message",
                "session",
            )
        )
        selected_table = None
        has_credit_col = False
        for table in preferred:
            if table not in tables:
                continue
            columns = [
                row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            if not columns:
                continue
            schema.append(f"{table}({','.join(columns)})")
            credit_columns = [
                column
                for column in columns
                if column.lower()
                in {"credits", "credit", "cost_credits", "costcredits"}
            ]
            if credit_columns:
                selected_table = table
                has_credit_col = True
                credit_column = credit_columns[0]
                break

        if has_credit_col:
            now_ms = int(time.time() * 1000)
            since_ms = now_ms - 24 * 60 * 60 * 1000
            columns = [
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{selected_table}")')
            ]
            time_column = next(
                (
                    column
                    for column in ("time_created", "time_updated")
                    if column in columns
                ),
                None,
            )
            if time_column is None:
                return [], [], "source-schema-sin-ventana"
            selected = ",".join(f'"{column}"' for column in columns)
            metadata_query = (
                f'SELECT {selected} FROM "{selected_table}" '  # noqa: S608
                f'WHERE "{time_column}" >= ? AND "{time_column}" <= '
                f'? ORDER BY "{time_column}" DESC LIMIT 256'  # noqa: S608
            )
            rows = connection.execute(
                metadata_query,
                (since_ms, now_ms),
            ).fetchall()
            metadata = [dict(zip(columns, row, strict=True)) for row in rows]
            total = connection.execute(
                f'SELECT SUM("{credit_column}") FROM "{selected_table}" '  # noqa: S608
                f'WHERE "{time_column}" >= ? AND "{time_column}" <= ?',
                (since_ms, now_ms),
            ).fetchone()[0]
            if total is None:
                return [], [], "source-no-credits"
            aggregate = {"credits": total, "__nan_aggregate__": True}
            for record in metadata:
                raw_data = record.get("data")
                try:
                    payload = (
                        json.loads(raw_data) if isinstance(raw_data, str) else None
                    )
                except (TypeError, ValueError, RecursionError):
                    payload = None
                if isinstance(payload, dict):
                    for key in (
                        "nivel",
                        "level",
                        "autorizacion",
                        "authorization",
                        "peticion_usuario",
                        "user_request",
                        "ritmo_24h",
                        "rate_24h",
                    ):
                        if key in payload and key not in aggregate:
                            aggregate[key] = payload[key]
            records.extend(
                [aggregate]
                + [{**record, "__nan_metadata_only__": True} for record in metadata]
            )
            return records, schema, None

        if "session" in tables:
            columns = [
                row[1] for row in connection.execute('PRAGMA table_info("session")')
            ]
            if not any("session(" in s for s in schema):
                schema.append(f"session({','.join(columns)})")
            if (
                "time_created" in columns
                and "tokens_input" in columns
                and "model" in columns
            ):
                selected_table = "session"
                start_dt = _nan_period_start()
                start_ms = int(start_dt.timestamp() * 1000)
                now_dt = getattr(CFG, "nan_now", None)
                if now_dt is None and "NAN_NOW" in os.environ:
                    now_dt = dt.datetime.fromisoformat(os.environ["NAN_NOW"])
                now_ms = int((now_dt.timestamp() if now_dt else time.time()) * 1000)

                pricing_map, meta_cfg = _nan_pricing_table()
                agg_query = (
                    'SELECT "model", SUM("tokens_input"), '
                    'SUM(COALESCE("tokens_cache_read", 0)), SUM("tokens_output") '
                    'FROM "session" WHERE "time_created" >= ? AND "time_created" <= ? '
                    'GROUP BY "model"'
                )
                agg_rows = connection.execute(agg_query, (start_ms, now_ms)).fetchall()

                total_credits = 0.0
                for model_raw, tin, tcache, tout in agg_rows:
                    tin = tin or 0
                    tcache = tcache or 0
                    tout = tout or 0
                    if tin + tcache + tout == 0:
                        continue
                    prov, mid = _nan_parse_model(model_raw)
                    if (
                        prov in meta_cfg["fuera_pool"]
                        or any(
                            mid.startswith(f"{fp}/") for fp in meta_cfg["fuera_pool"]
                        )
                        or mid.endswith("-free")
                    ):
                        continue

                    canon = (
                        f"nan/{mid}"
                        if prov in ("", "nan", "nan_api") and not mid.startswith("nan/")
                        else (f"{prov}/{mid}" if prov else mid)
                    )
                    if (
                        canon in meta_cfg["gratuitos"]
                        or mid in meta_cfg["gratuitos"]
                        or f"nan/{mid}" in meta_cfg["gratuitos"]
                    ):
                        cost = 0.0
                    elif canon in pricing_map:
                        rt = pricing_map[canon]
                        cost = (tin * rt[0] + tcache * rt[1] + tout * rt[2]) / 1000000.0
                    elif mid in pricing_map:
                        rt = pricing_map[mid]
                        cost = (tin * rt[0] + tcache * rt[1] + tout * rt[2]) / 1000000.0
                    else:
                        unknown_label = canon or str(model_raw)
                        return [], schema, f"modelo-no-tarifado:{unknown_label}"
                    total_credits += cost

                selected = ",".join(f'"{col}"' for col in columns)
                metadata_query = (
                    f'SELECT {selected} FROM "session" '  # noqa: S608
                    f'WHERE "time_created" >= ? AND "time_created" <= ? '
                    f'ORDER BY "time_created" DESC LIMIT 256'
                )
                meta_rows = connection.execute(
                    metadata_query, (start_ms, now_ms)
                ).fetchall()
                metadata = [dict(zip(columns, row, strict=True)) for row in meta_rows]
                aggregate = {"credits": total_credits, "__nan_aggregate__": True}
                for record in metadata:
                    raw_data = record.get("metadata") or record.get("data")
                    try:
                        payload = (
                            json.loads(raw_data) if isinstance(raw_data, str) else None
                        )
                    except (TypeError, ValueError, RecursionError):
                        payload = None
                    if isinstance(payload, dict):
                        for key in (
                            "nivel",
                            "level",
                            "autorizacion",
                            "authorization",
                            "peticion_usuario",
                            "user_request",
                            "ritmo_24h",
                            "rate_24h",
                        ):
                            if key in payload and key not in aggregate:
                                aggregate[key] = payload[key]
                if "nivel" not in aggregate and "level" not in aggregate:
                    aggregate["nivel"] = "alto"
                records.extend(
                    [aggregate]
                    + [{**record, "__nan_metadata_only__": True} for record in metadata]
                )
                return records, schema, None

    except (OSError, sqlite3.Error, ValueError):
        return [], [], "source-corrupt"
    finally:
        if connection is not None:
            with contextlib.suppress(sqlite3.Error):
                connection.close()
    if not schema:
        return [], [], "source-schema"
    if selected_table is None:
        return [], [], "sin-campo-de-creditos"
    return records, schema, None


def _nan_source_records(path, source):
    """Load one configured NaN source while preserving UNKNOWN semantics.

    Before: ``path`` is optional and may point to JSON test data or SQLite production data.
    During: choose the bounded reader and attach source/schema provenance.
    After: return ``(records, provenance, reason)``; absence is never reported as zero.
    """
    if path is None:
        return [], [f"{source}:unconfigured"], "source-unconfigured"
    if not path.exists() or not path.is_file():
        return [], [f"{source}:{path.name}:absent"], "source-absent"
    if path.suffix.lower() == ".json":
        records, reason = _nan_json_records(path)
        if reason is None and not _nan_numbers(records):
            reason = "source-no-credits"
        return records, [f"{source}:{path.name}:json"], reason
    records, schema, reason = _nan_sqlite_records(path, source)
    return records, [f"{source}:{path.name}:" + ";".join(schema)], reason


def _nan_numbers(value, keys=None):
    """Extract bounded credit values from a source record.

    Before: ``value`` is decoded source data.
    During: recursively inspect mappings/lists and recognize explicit credit/cost keys only.
    After: return finite numeric credit amounts, never token counts or arbitrary numbers.
    """
    keys = keys or {
        "credits",
        "credit",
        "cost_credits",
        "costcredits",
        "total_cost",
    }
    found = []
    if isinstance(value, dict):
        if value.get("__nan_metadata_only__"):
            return found
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if (
                normalized in keys
                and isinstance(item, (int, float))
                and not isinstance(item, bool)
            ):
                if math.isfinite(float(item)) and float(item) >= 0:
                    found.append(float(item))
            elif isinstance(item, (dict, list)):
                found.extend(_nan_numbers(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.extend(_nan_numbers(item, keys))
    return found


def _nan_has_invalid_credit(value):
    """Return whether an explicit credit field is negative, non-finite, or malformed."""
    keys = {"credits", "credit", "cost_credits", "costcredits", "total_cost"}
    if isinstance(value, dict):
        if value.get("__nan_metadata_only__"):
            return False
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in keys:
                if not isinstance(item, (int, float)) or isinstance(item, bool):
                    return True
                try:
                    if not math.isfinite(float(item)) or float(item) < 0:
                        return True
                except (OverflowError, ValueError):
                    return True
            elif isinstance(item, (dict, list)) and _nan_has_invalid_credit(item):
                return True
    elif isinstance(value, list):
        return any(_nan_has_invalid_credit(item) for item in value)
    return False


def _nan_agents_registry():
    """Read the configured per-level ceiling registry without inventing defaults."""
    raw = os.environ.get(NAN_AGENTS_ENV)
    path = (
        Path(raw)
        if raw
        else Path(__file__).resolve().parents[2] / ".agent" / "config" / "agents.json"
    )
    data = _load_json_dict(path)
    registry = data.get("ensemble_registry")
    ceilings = (
        registry.get("uso_maximo_por_tipo") if isinstance(registry, dict) else None
    )
    if not isinstance(ceilings, dict):
        return {}, "techo-ausente"
    valid = {}
    for level, ceiling in ceilings.items():
        if isinstance(level, str) and level and _is_finite(ceiling) and ceiling >= 0:
            valid[level] = float(ceiling)
    return (valid, None) if valid else ({}, "techo-ausente")


def _nan_metadata(records, ceilings):
    """Collect level, authorization and session-cap metadata from sampled records.

    Before: ``records`` are bounded dictionaries from the two sources.
    During: inspect only explicit T2/T3 field names and preserve missing values as ``None``.
    After: return ``(levels, authorizations, cap, user_request, rate_24h)``.
    """
    levels, authorizations = [], []
    cap = None
    user_request = False
    rate = None
    for record in records:
        if not isinstance(record, dict):
            continue
        level = record.get("nivel", record.get("level"))
        authorization = record.get("autorizacion", record.get("authorization"))
        if isinstance(level, str) and level:
            levels.append(level)
        if isinstance(authorization, str) and authorization:
            authorizations.append(authorization)
        if isinstance(level, str) and level in ceilings:
            candidate = ceilings[level]
            cap = float(candidate) if cap is None else min(cap, float(candidate))
        user_request = user_request or bool(
            record.get("peticion_usuario", record.get("user_request"))
        )
        candidate_rate = record.get("ritmo_24h", record.get("rate_24h"))
        if isinstance(candidate_rate, (int, float)) and math.isfinite(
            float(candidate_rate)
        ):
            rate = float(candidate_rate)
    return levels, authorizations, cap, user_request, rate


def _nan_projection(used, rate, now):
    """Project pool exhaustion using the mandatory reset and seven-day thresholds.

    Before: ``used`` and ``rate`` are measured finite credits and ``now`` is UTC-aware.
    During: with a positive rate calculate exhaustion from the remaining pool and compare it
        to reset and now; a non-positive rate means no observable spending, so there is no
        projected exhaustion to warn about (never an instant URGENTE).
    After: return projection metadata including pool, reset, period, rate and level, with
        ``agotamiento_proyectado`` and ``nivel`` set to ``None`` when the rate is not positive.
    """
    reset = dt.datetime.fromisoformat(NAN_RESET_AT).astimezone(dt.timezone.utc)
    reset_rodado = False
    while reset < now:
        next_month = reset.month % 12 + 1
        next_year = reset.year + (reset.month // 12)
        reset = reset.replace(
            year=next_year,
            month=next_month,
            day=min(reset.day, calendar.monthrange(next_year, next_month)[1]),
        )
        reset_rodado = True
    remaining = max(0.0, NAN_POOL_CREDITS - used)
    exhaustion = None
    level = None
    if remaining <= 0:
        # Pool ya agotado: agotamiento inmediato aunque el ritmo observable sea 0 (m3/H1).
        exhaustion = now
    elif rate > 0:
        try:
            exhaustion = now + dt.timedelta(hours=remaining / rate)
        except (OverflowError, ValueError):
            exhaustion = None
        if exhaustion is None:
            return {
                "pool": NAN_POOL_CREDITS,
                "periodo": "mensual",
                "reinicio": reset.isoformat(),
                "ritmo_observado_24h": rate * 24,
                "agotamiento_proyectado": None,
                "nivel": None,
                "motivo": "sin-agotamiento-observable",
                "reset_rodado": reset_rodado,
            }
    if exhaustion is not None:  # noqa: SIM102 - guard de None; la comparacion estricta de abajo es patron del mutante M2
        if exhaustion < reset:
            level = (
                "URGENTE" if (exhaustion - now).total_seconds() < 7 * 86400 else "AVISO"
            )
    return {
        "pool": NAN_POOL_CREDITS,
        "periodo": "mensual",
        "reinicio": reset.isoformat(),
        "ritmo_observado_24h": rate * 24,
        "agotamiento_proyectado": (
            exhaustion.isoformat() if exhaustion is not None else None
        ),
        "nivel": level,
        "reset_rodado": reset_rodado,
    }


def _nan_unknown_findings(values, records, ceilings, streak):
    """Build the fail-closed findings for an UNKNOWN NaN reading.

    Before: ``values``/``levels``/``authorizations``/``cap`` reflect only the sources that
        were readable and ``streak`` counts consecutive UNKNOWN readings.
    During: deny the cap and the unauthorized premium from the readable partial sum
        (monotone: adding sources can only raise it) and escalate once at two readings.
    After: return the ordered ``gasto-*`` findings; the projection is never evaluated here.
    """
    found = []
    partial = sum(values)
    for record, amount in _nan_session_amounts(records):
        level = record.get("nivel", record.get("level"))
        cap = ceilings.get(level) if isinstance(level, str) else None
        authorization = record.get("autorizacion", record.get("authorization"))
        partial = amount
        if cap is not None and partial > cap:
            found.append(
                (
                    "gasto-tope",
                    "URGENTE",
                    f"Uso parcial {partial:g} supera el tope autorizado {cap:g}",
                )
            )
        if level == "premium" and not _valid_authorization(authorization):
            found.append(
                (
                    "gasto-premium",
                    "URGENTE",
                    "Gasto premium sin autorizacion registrada",
                )
            )
    if streak >= 2:
        found.append(
            (
                "gasto-unknown",
                "AVISO",
                "Fuentes NaN ausentes, corruptas o ambiguas tras dos lecturas",
            )
        )
    return found


def _valid_authorization(value):
    """Accept only a non-empty authorization identifier, never a denial marker."""
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value.strip().upper() != "DENEGADA"
    )


def _nan_session_amounts(records):
    """Return one finite credit amount and metadata tuple per measured record."""
    result = []
    for record in records:
        if not isinstance(record, dict) or record.get("__nan_metadata_only__"):
            continue
        values = _nan_numbers(record)
        if values:
            result.append((record, sum(values)))
    return result


def _nan_measured_findings(projection, user_request, records, ceilings, used):
    """Build the findings for a fully measured NaN reading.

    Before: ``projection`` comes from ``_nan_projection`` and the metadata from readable sources.
    During: a user request never suppresses a finding and elevates the projection to
        URGENTE (DISENO s.7 / FICHA s.1); premium and cap denials stay unconditional.
    After: return the ordered ``gasto-*`` findings for the tick.
    """
    found = []
    if projection["nivel"]:
        elevated = "URGENTE" if user_request else projection["nivel"]
        detail = "El pool NaN se agotara antes del reinicio"
        if user_request:
            detail += "; la peticion de usuario eleva el estado a URGENTE"
        found.append(("gasto-presupuesto", elevated, detail))
    for record, amount in _nan_session_amounts(records):
        level = record.get("nivel", record.get("level"))
        authorization = record.get("autorizacion", record.get("authorization"))
        cap = ceilings.get(level) if isinstance(level, str) else None
        used = amount
        if level == "premium" and not _valid_authorization(authorization):
            found.append(
                (
                    "gasto-premium",
                    "URGENTE",
                    "Gasto premium sin autorizacion registrada",
                )
            )
        if cap is not None and used > cap:
            found.append(
                (
                    "gasto-tope",
                    "URGENTE",
                    f"Uso {used:g} supera el tope autorizado {cap:g}",
                )
            )
    return found


def check_nan_budget(out, st):
    """Measure NaN budget, premium authorization, projection and session cap.

    Before: ``CFG`` resolves optional source paths and ``st`` is the mutable stall state.
    During: read sources read-only, retain UNKNOWN, update the atomic receipt payload and
        emit only the contractual ``gasto-*`` findings.
    After: return findings; only the later production ``_save_state`` can persist ``st``.
    """
    paths = getattr(CFG, "nan_sources", {})
    if not any(paths.values()):
        out["nan_sources_unconfigured"] = True
        return []
    records, provenance, reasons = [], [], []
    for source, path in paths.items():
        values, source_provenance, reason = _nan_source_records(path, source)
        records.extend(values)
        provenance.extend(source_provenance)
        if reason:
            reasons.append(reason)
    ceilings, ceiling_reason = _nan_agents_registry()
    if ceiling_reason:
        reasons.append(ceiling_reason)
    levels, authorizations, _cap, user_request, explicit_rate = _nan_metadata(
        records, ceilings
    )
    values = _nan_numbers(records)
    if _nan_has_invalid_credit(records):
        reasons.append("creditos-invalidos")
    measured_records = _nan_session_amounts(records)
    if values and any(
        _amount > 0
        and (
            not isinstance(record.get("nivel", record.get("level")), str)
            or not record.get("nivel", record.get("level"))
            or record.get("nivel", record.get("level")) not in ceilings
        )
        for record, _amount in measured_records
    ):
        reasons.append("nivel-o-techo-ausente")
    if not values and not reasons:
        # Sin valores de credito legibles hay UNKNOWN, nunca un cero fabricado,
        # aunque la fuente aporte un ritmo explicito (V1 r2 NIT-8).
        reasons = ["source-no-credits"]
    if reasons:
        streak = _count(st.get(NAN_UNKNOWN_KEY)) + 1
        st[NAN_UNKNOWN_KEY] = streak
        out.update(
            {
                "nan_status": "UNKNOWN",
                "nan_unknown_reason": reasons,
                "nan_provenance": provenance,
            }
        )
        receipt = {
            "nivel": levels[0] if levels else None,
            "uso": None,
            "uso_parcial": sum(values) if values else None,
            "autorizacion": authorizations[0] if authorizations else None,
            "procedencia": provenance,
            "peticion_usuario": user_request,
            "proyeccion": None,
        }
        st["nan_receipt"] = receipt
        # El tope y el premium NO dependen de la proyeccion ni de que TODAS las
        # fuentes sean legibles (V1 r1 hallazgo 1); UNKNOWN solo calla la proyeccion.
        return _nan_unknown_findings(values, records, ceilings, streak)
    used = sum(values)
    st[NAN_UNKNOWN_KEY] = 0
    if explicit_rate is not None:
        explicit_rate /= 24.0
    rate = explicit_rate if explicit_rate is not None else used / 24.0
    now = dt.datetime.fromtimestamp(time.time(), tz=dt.timezone.utc)
    projection = _nan_projection(used, rate, now)
    out.update(
        {
            "nan_status": "MEASURED",
            "nan_used": used,
            "nan_provenance": provenance,
            "nan_projection_level": projection["nivel"],
            "nan_projection": projection,
        }
    )
    receipt = {
        "nivel": levels[0] if levels else None,
        "uso": used,
        "autorizacion": authorizations[0] if authorizations else None,
        "procedencia": provenance,
        "peticion_usuario": user_request,
        "proyeccion": projection,
    }
    st["nan_receipt"] = receipt
    return _nan_measured_findings(projection, user_request, records, ceilings, used)


def check_co_sin_asentar(out, st):  # noqa: C901 - ramas fail-closed del contrato
    """Detect first-level unsettled coordinator threads outside the active triad.

    Before: ``CFG.store`` points to the selected T3 projection and ``CFG.registry``
        identifies the flight directory; ``st`` is the heartbeat state.
    During: read the store through the canonical read-only checker, classify first-level
        CO rows and their latest runs, then reread the flight roster and apply the cap/
        grace rules without writing any state.
    After: return one stable AVISO or an observable fail-closed AVISO, preserving the
        blindness cause in ``out`` for reconciliation.
    """
    del st

    def blind(cause):
        """Return the observable fixed-key blindness finding.

        Before: ``cause`` identifies why the store or roster cannot be measured.
        During: record the cause in ``out`` and build the fixed-key AVISO tuple.
        After: return one finding without writing external state.
        """
        out["co_sin_asentar_ciego"] = cause
        return [("co-sin-asentar", "AVISO", f"CO sin asentar: {cause}")]

    if CFG.store is None or not CFG.store.is_file():
        return blind("store no medido")

    checker = _load_cell_checker()
    connection = None
    try:
        connection, _, settled = checker._store_lookup(CFG.store)
        rows = connection.execute(
            "SELECT thread_id, title, created_at, payload_json "
            "FROM orchestration_v2_projection_threads WHERE deleted_at IS NULL"
        ).fetchall()
        latest_runs = {}
        for thread_id, status, ordinal in connection.execute(
            "SELECT thread_id, status, ordinal FROM orchestration_v2_projection_runs"
        ):
            if not isinstance(thread_id, str) or not isinstance(status, str):
                raise checker.MeasurementError("run ilegible")
            if isinstance(ordinal, bool) or not isinstance(ordinal, (int, float)):
                raise checker.MeasurementError("ordinal de run ilegible")
            if isinstance(ordinal, float) and not ordinal.is_integer():
                raise checker.MeasurementError("ordinal de run ilegible")
            try:
                ordinal_value = int(ordinal)
            except (TypeError, ValueError) as exc:
                raise checker.MeasurementError("ordinal de run ilegible") from exc
            previous = latest_runs.get(thread_id)
            if previous is None or ordinal_value > previous[0]:
                latest_runs[thread_id] = (ordinal_value, status.casefold())
        unsettled = []
        for row in rows:
            title = row["title"] if isinstance(row, sqlite3.Row) else row[1]
            if not isinstance(title, str) or CO_TITLE_RE.match(title) is None:
                continue
            payload_raw = (
                row["payload_json"] if isinstance(row, sqlite3.Row) else row[3]
            )
            try:
                payload = json.loads(payload_raw)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise checker.MeasurementError("payload CO ilegible") from exc
            if not isinstance(payload, dict):
                raise checker.MeasurementError("payload CO no es objeto")
            lineage = payload.get("lineage")
            if lineage is not None and not isinstance(lineage, dict):
                raise checker.MeasurementError("lineage CO ilegible")
            parent = lineage.get("parentThreadId") if lineage else None
            if parent not in (None, ""):
                continue
            thread_id = row["thread_id"] if isinstance(row, sqlite3.Row) else row[0]
            if settled(thread_id):
                continue
            created_at = row["created_at"] if isinstance(row, sqlite3.Row) else row[2]
            try:
                created = dt.datetime.fromisoformat(
                    str(created_at).strip().replace("Z", "+00:00")
                )
            except (TypeError, ValueError) as exc:
                raise checker.MeasurementError("created_at CO ilegible") from exc
            if created.tzinfo is None:
                raise checker.MeasurementError("created_at CO naive")
            code_match = re.match(r"^CO-\d{1,4}", title)
            if code_match is None:
                raise checker.MeasurementError("codigo CO ilegible")
            unsettled.append(
                {
                    "code": code_match.group(0),
                    "threadId": str(thread_id),
                    "created": created.astimezone(dt.timezone.utc),
                    "running": (
                        thread_id in latest_runs
                        and latest_runs[thread_id][1] not in CO_TERMINAL_RUNS
                    ),
                }
            )
    except (checker.MeasurementError, sqlite3.Error, OSError, TypeError, ValueError):
        return blind("store no medido")
    finally:
        if connection is not None:
            connection.close()

    total = len(unsettled)
    if total == 0:
        return []

    if CFG.registry is None:
        return blind("roster no medido")
    roster_path = CFG.registry.parent / FLIGHT_ROSTER_NAME
    try:
        roster = json.loads(roster_path.read_text(encoding="utf-8"))
        roles = roster.get("active_roles") if isinstance(roster, dict) else None
        orchestrator = roles.get("orquestador") if isinstance(roles, dict) else None
        if (
            not isinstance(orchestrator, dict)
            or not orchestrator.get("threadId")
            or not orchestrator.get("session_code")
        ):
            raise ValueError("orquestador sin threadId")
        supervisor = roles.get("supervisor") if isinstance(roles, dict) else None
        if (
            not isinstance(supervisor, dict)
            or not isinstance(supervisor.get("threadId"), str)
            or not supervisor["threadId"].strip()
            or not isinstance(supervisor.get("session_code"), str)
            or not supervisor["session_code"].strip()
        ):
            raise ValueError("supervisor ilegible")
        if "ancestro_directo" in roles:
            ancestro = roles["ancestro_directo"]
            if (
                not isinstance(ancestro, dict)
                or not isinstance(ancestro.get("threadId"), str)
                or not ancestro["threadId"].strip()
                or not isinstance(ancestro.get("session_code"), str)
                or not ancestro["session_code"].strip()
            ):
                raise ValueError("ancestro_directo ilegible")
        since_raw = orchestrator.get("since")
        since = (
            dt.datetime.fromisoformat(since_raw.strip().replace("Z", "+00:00"))
            if isinstance(since_raw, str)
            else None
        )
        if since is None or since.tzinfo is None:
            raise ValueError("since ilegible")
        triad = []
        for role_name in ("orquestador", "supervisor", "ancestro_directo"):
            role = roles.get(role_name) if isinstance(roles, dict) else None
            if isinstance(role, dict):
                triad.append(
                    (
                        str(role.get("threadId") or ""),
                        str(role.get("session_code") or ""),
                    )
                )
    except (OSError, TypeError, ValueError, json.JSONDecodeError, RecursionError):
        return blind("roster no medido")

    def in_triad(item):
        """Return whether a candidate matches a literal active role identity.

        Before: ``item`` is an unsettled CO and ``triad`` contains roster identities.
        During: compare its exact thread ID and extracted code to each role.
        After: return a boolean membership result without changing either input.
        """
        return any(
            item["threadId"] == thread_id or item["code"] == code
            for thread_id, code in triad
        )

    candidates = [
        item for item in unsettled if not item["running"] and not in_triad(item)
    ]
    candidates.sort(key=lambda item: (item["created"], item["code"]), reverse=True)
    out["co_sin_asentar"] = [
        {"code": item["code"], "threadId": item["threadId"]} for item in candidates
    ]
    overdue = (
        now_utc() - since.astimezone(dt.timezone.utc)
    ).total_seconds() > CO_GRACIA_MIN * 60
    if total <= CO_TOPE and not (overdue and candidates):
        return []
    if candidates:
        detail = "asentar " + ", ".join(item["code"] for item in candidates)
    else:
        detail = "ninguno asentable"
    text = f"{total} CO de primer nivel sin asentar (tope {CO_TOPE}"
    if overdue and candidates:
        text += f"; pasados {CO_GRACIA_MIN} min del ACTIVO {orchestrator.get('session_code', 'desconocido')}"
    text += f"): {detail}"
    if not isinstance(roles.get("ancestro_directo"), dict):
        text += "; terna parcial: conserva el primero como ancestro directo hasta 194b"
    return [("co-sin-asentar", "AVISO", text)]


def _detect(out, st, only=None):
    """Ejecuta todos los detectores aislando el fallo de cada uno.

    Before: ``out`` es el acumulador y ``st`` el estado del tick.
    During: invoca quota, cola, git, disco, hook e im-ocioso; captura
        excepciones y anade ``detector-roto``.
    After: devuelve ``(hallazgos, roto)`` y conserva los resultados de detectores sanos.
    """
    found, broke = [], False
    detectors = {
        "quota": lambda: check_quota(out),
        "cola": lambda: check_cola(out, st),
        "ocio-con-cola": lambda: check_ocio_con_cola(out, st),
        "git": lambda: check_git(out, st),
        "disco": lambda: check_disk(out),
        "hook": lambda: check_hook(out),
        "im-ocioso": lambda: check_im_ocioso(out, st),
        "cola-despachable": lambda: check_cola_despachable(out, st),
        "huerfano": lambda: check_huerfano(out, st),
        "presupuesto-nan": lambda: check_nan_budget(out, st),
        "co-sin-asentar": lambda: check_co_sin_asentar(out, st),
    }
    selected = [only] if only else list(DETECTOR_NAMES)
    for name in selected:
        fn = detectors[name]
        try:
            found += fn()
        except Exception as exc:
            broke = True
            found.append(
                (
                    "detector-roto",
                    "AVISO",
                    f"Un detector de paradas fallo: {str(exc)[:80]}",
                )
            )
    return found, broke


def _notify_all(ca, found, a, out, owner="stall"):
    """Publica o establece como baseline los hallazgos del tick.

    Before: ``ca`` ofrece ``event``/``mark_seen``; ``found``, ``a`` y ``out`` contienen resultados y modos.
    During: recorre cada hallazgo, marca baseline o llama a ``ca.event`` e imprime el resultado.
    After: devuelve 0 sin hallazgos, 1 con hallazgos o 2 si algun aviso fallo.
    """
    rc = 0
    for key, level, what in found:
        rc = max(rc, 1)
        if a.baseline:
            ca.mark_seen(key, level, owner, a.dry_run)
            print(f"BASELINE {level} {key}")
            continue
        session_code = out.get("session_codes", {}).get(key) or getattr(
            CFG, "session_code", None
        )
        r = ca.event(
            key,
            level,
            None,
            what,
            False,
            a.dry_run,
            owner=owner,
            session_code=session_code,
            preserve_literal=key in out.get("session_codes", {}),
        )
        if r == 2:
            rc = 2
        suffix = " aviso fallido" if r == 2 else ""
        print(f"{level} {key} rc_aviso={r}{suffix} {what}")
    return rc


def _reconcile(ca, out, found, a):
    """Reconcilia las claves propias que ya no corresponden al estado observado.

    Before: ``ca`` mantiene el ledger; ``out``, ``found`` y ``a`` describen ceguera, hallazgos y dry-run.
    During: reconcilia solo prefijos no ciegos, borra claves ausentes y resuelve las claves de ``RETIRED_EVENT_KEYS``.
    After: deja el ledger reconciliado para owner ``stall`` y no devuelve ningun valor.
    """
    blind = {
        "cupo-": out.get("ciego_cupo"),
        "cola-": out.get("ciego_cola"),
        "ocio-con-cola": False,
        "git-": out.get("ciego_git"),
        "hook-": out.get("ciego_hook"),
        "huerfano-": out.get("huerfano_ciego"),
        # Un tick NaN en UNKNOWN (o con las fuentes sin configurar) no puede ver la
        # causa de sus claves gasto-*: no las reconcilia mientras este ciego.
        "gasto-": out.get("nan_status") == "UNKNOWN"
        or bool(out.get("nan_sources_unconfigured")),
        "co-sin-asentar": out.get("co_sin_asentar_ciego"),
    }
    if out.get("ocio_con_cola_ciego"):
        blind["ocio-con-cola"] = True
    prefixes = tuple(p for p in OWNED_PREFIXES if not blind.get(p))
    live_keys = {k for k, _, _ in found}
    if not blind.get("huerfano-") and "huerfano_activos" in out:
        live_keys = {key for key in live_keys if not key.startswith("huerfano-")} | set(
            out.get("huerfano_activos") or ()
        )
    cleared = ca.reconcile(prefixes, live_keys, a.dry_run, owner="stall")
    if cleared:
        print("resueltas (borradas, una recaida avisa de nuevo):", cleared)
    for key in RETIRED_EVENT_KEYS:
        if f"event:{key}" in ca.load_state():
            ca.resolve(key, a.dry_run)


def run(a):  # noqa: C901 - detector legacy mas el modo heartbeat aislado
    """Un tick: carga el aviso, resuelve la configuracion, detecta, avisa y guarda el reloj.

    Before: argumentos ``a`` (dry_run, baseline, ops_dir, ...).
    During: con ``--heartbeat-check`` retorna antes de cargar ``_state`` o ejecutar
        ``_detect``; esa rama lee ``ts_latido`` (o el ``ts`` de transicion), avisa y
        solo escribe ``ts_tarea`` fuera de ``--dry-run``.
    After: rc 0/1/2; ``--heartbeat-check`` no escribe ``ts_latido``; en la rama
        normal, ``--dry-run`` no escribe estado y ``ts_latido`` se escribe en cada
        ejecucion no-dry, tambien con ``--baseline``.
    """
    global CFG
    try:
        ca = _load_alert()
    except Exception as exc:
        print(f"STALL_CHECK_BROKEN: no se pudo cargar comms_alert.py: {str(exc)[:120]}")
        return 2
    try:
        ops = ca.configure(a.ops_dir)
    except ca.OpsDirError as exc:
        print(f"STALL_CHECK_BROKEN: ops-dir: {str(exc)[:160]}")
        return 2
    CFG, causes, fatal = _resolve_paths(a, ops)
    if fatal:
        print(f"STALL_CHECK_BROKEN: {fatal}")
        return 2
    if a.heartbeat_check:
        if causes:
            print("STALL_CHECK_BROKEN: " + "; ".join(causes[:3]))
            return 2
        return _heartbeat_check(a, ca)
    st, out = _state(), {}
    detector = None if a.test_detector == "todos" else a.test_detector
    found, broke = _detect(out, st, detector)
    if not a.test_detector and CFG.registry is None:
        found = [item for item in found if item[0] != "detector-ciego-huerfano"]
        out.pop("huerfano_ciego", None)
    if out.get("huerfano_ciego"):
        print(
            f"detector-ciego-huerfano: {out['huerfano_ciego']}",
            file=sys.stderr,
        )
    if a.test_detector:
        if out.get("huerfano_ciego"):
            print("STALL_CHECK_BROKEN: detector huerfano ciego")
            return 2
        if broke:
            print("STALL_CHECK_BROKEN: detector de prueba fallo")
            return 2
        if a.test_detector == "presupuesto-nan" and not a.dry_run:
            _save_state(st)
        print("resumen:", json.dumps(out, ensure_ascii=False))
        print("test-detector:", a.test_detector, "hallazgos=", len(found))
        return 0 if a.test_detector == "todos" else 1 if found else 0
    if causes:
        found.insert(
            0,
            (
                "detector-sin-config",
                "AVISO",
                "Detector sin configurar: " + "; ".join(c[:80] for c in causes),
            ),
        )
    active_events = {key for key in ca.load_state() if str(key).startswith("event:")}
    if not found and not active_events and not ca.clear_group(a.dry_run):
        print("STALL_CHECK_WARNING: no se pudo limpiar nuestro Group de avisos")
    rc = _notify_all(ca, found, a, out)
    if out.get("huerfano_ciego"):
        rc = 2
    if not a.dry_run and not a.baseline and not broke:
        _reconcile(ca, out, found, a)
    if not a.dry_run:
        st["ts_latido"] = time.time()
        st.pop("ts", None)
        st.pop("cola_vistas", None)
        _save_state(st)
    print("resumen:", json.dumps(out, ensure_ascii=False), f"hallazgos={len(found)}")
    if broke:
        print(
            "STALL_CHECK_BROKEN: un detector fallo (ver detector-roto); el resto de la comprobacion es parcial"
        )
        rc = 2
    return rc


def main(argv=None):
    """CLI del detector de paradas.

    Before: argumentos de linea de comandos (o ``argv``).
    During: ``--self-check`` comprueba los ficheros; si no, corre un tick.
    After: rc 0/1/2; una excepcion no prevista sale como rc 2 con ``STALL_CHECK_BROKEN``.
    """
    ap = argparse.ArgumentParser(
        description="Detectores de parada de vuelo (solo lectura) con aviso de escritorio"
    )
    ap.add_argument("--dry-run", action="store_true", help="no avisa ni guarda estado")
    ap.add_argument(
        "--baseline",
        action="store_true",
        help="da por ya avisado lo que hay ahora (sin notificar): primer arranque",
    )
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="comprueba que existen y compilan los tres scripts",
    )
    ap.add_argument(
        "--heartbeat-check",
        action="store_true",
        help="sondea ts_latido y escribe solo ts_tarea",
    )
    ap.add_argument(
        "--ops-dir", help=f"directorio de operacion; por defecto ${OPS_DIR_ENV}"
    )
    ap.add_argument(
        "--flight-dir",
        help=f"directorio del vuelo (cola); por defecto ${FLIGHT_DIR_ENV}",
    )
    ap.add_argument(
        "--motor-wt", help="worktree del motor vigilado; por defecto el de este script"
    )
    ap.add_argument(
        "--quota-file",
        help="ultima salida de quota_tick.py; por defecto <ops-dir>/quota_last.txt",
    )
    ap.add_argument(
        "--test-detector",
        nargs="?",
        const="todos",
        help="ejecuta un detector aislado, o todos si no se da nombre",
    )
    a = ap.parse_args(argv)
    if a.test_detector and a.test_detector not in ("todos", *DETECTOR_NAMES):
        ap.error("--test-detector exige 'todos' o uno de: " + ", ".join(DETECTOR_NAMES))
    if a.heartbeat_check and (a.baseline or a.self_check or a.test_detector):
        ap.error(
            "--heartbeat-check no se combina con --baseline, --self-check ni "
            "--test-detector"
        )
    if a.heartbeat_check and (not a.ops_dir or not a.flight_dir):
        ap.error("--heartbeat-check exige --ops-dir y --flight-dir")
    try:
        return self_check(a) if a.self_check else run(a)
    except Exception as exc:
        print(f"STALL_CHECK_BROKEN: {type(exc).__name__}: {str(exc)[:160]}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
