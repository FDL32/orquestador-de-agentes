#!/usr/bin/env python3
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
TASK_STALE_S = 25 * 60  # la tarea corre cada 10 min: mas de 2 ciclos
TASK_FUTURE_S = 5 * 60  # un ts_tarea mas alla de esto en el futuro es ilegible
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
TASK_REGISTERED_NAME = "task_registered.json"
TASK_STATE_NAME = "task_state.json"
OWNED_PREFIXES = ("cupo-", "cola-", "git-", "disco", "hook-", "detector-")
GIT_MARKERS = ("index.lock", "MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD")

_CA = None
CFG = None
DETECTOR_NAMES = (
    "quota",
    "cola",
    "git",
    "disco",
    "hook",
    "tarea",
    "im-ocioso",
    "cola-despachable",
)
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
        return []
    if not q.exists():
        out["ciego_cupo"] = True
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
    if CFG.motor is None:
        out["ciego_git"] = True
        return []
    found = []
    previo = _count(st.get("motor_sucio"))
    for p in _worktrees():
        if p.exists():
            found += _git_markers(p)
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


def check_tarea(out):
    """Detector de la tarea programada (D25): solo actua si existe la marca de registro.

    Before: ``CFG.ops`` es el directorio de operacion. Sin ``task_registered.json`` la tarea
        NO esta registrada y no se avisa de nada.
    During: con marca lee ``task_state.json``; un ``ts_tarea`` ausente, ilegible, no finito,
        mas de 5 min en el futuro o de mas de 25 min de antiguedad es tarea muerta.
    After: lista con ``tarea-muerta`` AVISO (owner stall) o vacia.
    """
    if not os.path.lexists(CFG.ops / TASK_REGISTERED_NAME):
        return []
    out["tarea_registrada"] = True
    ts = _load_json_dict(CFG.ops / TASK_STATE_NAME).get("ts_tarea")
    now = time.time()
    if _is_finite(ts) and ts <= now + TASK_FUTURE_S and now - ts <= TASK_STALE_S:
        return []
    if _is_finite(ts) and ts <= now + TASK_FUTURE_S:
        why = f"lleva {int((now - ts) / 60)} min sin correr"
    else:
        why = "su reloj ts_tarea falta o es ilegible"
    return [("tarea-muerta", "AVISO", f"La tarea programada de vigilancia: {why}")]


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
    )
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


def _detect(out, st, only=None):
    """Ejecuta todos los detectores aislando el fallo de cada uno.

    Before: ``out`` es el acumulador y ``st`` el estado del tick.
    During: invoca quota, cola, git, disco, hook, tarea e im-ocioso; captura
        excepciones y anade ``detector-roto``.
    After: devuelve ``(hallazgos, roto)`` y conserva los resultados de detectores sanos.
    """
    found, broke = [], False
    detectors = {
        "quota": lambda: check_quota(out),
        "cola": lambda: check_cola(out, st),
        "git": lambda: check_git(out, st),
        "disco": lambda: check_disk(out),
        "hook": lambda: check_hook(out),
        "tarea": lambda: check_tarea(out),
        "im-ocioso": lambda: check_im_ocioso(out, st),
        "cola-despachable": lambda: check_cola_despachable(out, st),
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
    During: reconcilia solo prefijos no ciegos, borra claves ausentes y resuelve ``tarea-muerta`` recuperada.
    After: deja el ledger reconciliado para owner ``stall`` y no devuelve ningun valor.
    """
    blind = {
        "cupo-": out.get("ciego_cupo"),
        "cola-": out.get("ciego_cola"),
        "git-": out.get("ciego_git"),
        "hook-": out.get("ciego_hook"),
    }
    prefixes = tuple(p for p in OWNED_PREFIXES if not blind.get(p))
    cleared = ca.reconcile(prefixes, {k for k, _, _ in found}, a.dry_run, owner="stall")
    if cleared:
        print("resueltas (borradas, una recaida avisa de nuevo):", cleared)
    if "tarea-muerta" not in {k for k, _, _ in found} and (
        "event:tarea-muerta" in ca.load_state()
    ):
        ca.resolve("tarea-muerta", a.dry_run)


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
    if a.test_detector:
        if broke:
            print("STALL_CHECK_BROKEN: detector de prueba fallo")
            return 2
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
