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
TASK_STALE_S = 25 * 60  # la tarea corre cada 10 min: mas de 2 ciclos
TASK_FUTURE_S = 5 * 60  # un ts_tarea mas alla de esto en el futuro es ilegible
SIBLING_GLOBS = ("implantador-*", "triaje-*")
COLA_REL = Path("diseno") / "COLA_PARA_USUARIO.md"
QUOTA_NAME = "quota_last.txt"
STATE_NAME = "stall_state.json"
TASK_REGISTERED_NAME = "task_registered.json"
TASK_STATE_NAME = "task_state.json"
OWNED_PREFIXES = ("cupo-", "cola-", "git-", "disco", "hook-", "detector-")
GIT_MARKERS = ("index.lock", "MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD")

_CA = None
CFG = None


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
    """Estado del latido (``stall_state.json``): ausente o ilegible = vacio (se reescribe)."""
    return _load_json_dict(CFG.state)


def _count(value):
    """Contador entero no negativo y acotado; cualquier otra forma (cadena, bool, NaN) = 0."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**6:
        return value
    return 0


def _is_finite(value):
    """True para un numero real finito (un bool no cuenta)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


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
    """Cuentas de la salida de quota_tick: (porcentajes validos, hay cuenta sin porcentaje, hay STALE).

    Before: ``text`` es la salida de una linea ``QUOTA ... | <cuenta> <ventana> <pct>%[ STALE] | ...``.
    During: por cuenta (hasta el siguiente ``|``) toma el ULTIMO token ``<algo>%`` (el productor
        imprime ``<cuenta> <ventana> <pct>%`` y la ventana va cruda, puede contener ``N%``) y lo
        lee ENTERO como imprime Python el ``block_pct`` crudo: entero, decimal (97.0, 92.5), con
        signo y con exponente (1e+20, 1e-05, 1.5e+300, 1E5); un valor entero exacto se devuelve int.
    After: ``(pcts, sin_pct, stale)``; ``None%``, ``inf%`` o ausencia de ``%`` cuentan como sin porcentaje.
    """
    pcts, sin_pct, stale = [], False, False
    for m in re.finditer(r"(?:alvarovans|brabander)([^|]*)", text):
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
            pcts.append(int(value) if value.is_integer() else value)
        else:
            sin_pct = True
    return pcts, sin_pct, stale


def check_quota(out):
    """Detector de cupo: lee ``quota_last.txt`` (salida de quota_tick.py).

    Before: ``CFG.quota`` apunta al fichero (o es None si la configuracion era invalida).
    During: ausente = ciego + ``cupo-no-medido``; sin porcentajes (o una cuenta sin el suyo) =
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
    text = q.read_text(encoding="utf-8", errors="replace")[:400]
    pcts, sin_pct, stale = _quota_accounts(text)
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
    found += _quota_levels(pcts)
    out["cupo_max"] = max(pcts) if pcts else None
    return found


def _quota_reasons(age_min, declara_no_medido, stale):
    """Razones por las que el cupo no vale como medicion (antiguedad, cabecera NO_MEDIDO, STALE)."""
    razones = []
    if age_min > QUOTA_STALE_MIN:
        razones.append(f"El cupo lleva {int(age_min)} min sin medirse")
    if declara_no_medido:
        razones.append("quota_tick declara NO_MEDIDO")
    elif stale:
        razones.append("una cuenta del cupo esta STALE")
    return razones


def _quota_levels(pcts):
    """Hallazgo por el peor porcentaje: >= 97 URGENTE (cupo-97), >= 92 AVISO (cupo-92)."""
    if not pcts:
        return []
    worst = max(pcts)
    if worst >= 97:
        return [
            (
                "cupo-97",
                "URGENTE",
                f"Cupo de una cuenta al {worst}% (corte duro 97%): los implantadores se interrumpen",
            )
        ]
    if worst >= 92:
        return [
            (
                "cupo-92",
                "AVISO",
                f"Cupo de una cuenta al {worst}% (congelado suave 92%)",
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
    redact = _load_alert().redact
    found = []
    abiertas = 0
    for line in CFG.cola.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if "ABIERTA" not in line or "RESUELTA" in line:
            continue
        abiertas += 1
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
    """Motor mas los worktrees hermanos, sin repetir ninguno (el motor casa con su propio glob)."""
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
    """Hallazgos de bloqueo de git (index.lock, MERGE_HEAD, ...) en UN worktree."""
    rc, gitdir = _git(p, "rev-parse", "--absolute-git-dir")
    if rc != 0:
        return []
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
    """Detector de disco libre en la unidad del motor (umbral ``CFG.free_gb_min``)."""
    anchor = CFG.disk_anchor
    free_gb = shutil.disk_usage(anchor).free / 1e9
    out["disco_libre_gb"] = round(free_gb)
    if free_gb < CFG.free_gb_min:
        label = str(anchor).rstrip("\\/") or str(anchor)
        return [("disco", "AVISO", f"Quedan {free_gb:.1f} GB libres en {label}")]
    return []


def check_hook(out):
    """Detector del hook de seguridad de la rama del vuelo (``claude_guard_entry.py``)."""
    if CFG.motor is None:
        out["ciego_hook"] = True
        return []
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
    """True para una ruta de red (``\\\\servidor\\recurso``); la forma ``\\\\?\\C:`` es local."""
    return cand.drive.startswith("\\\\") and not re.fullmatch(
        r"\\\\\?\\[A-Za-z]:", cand.drive
    )


def _resolve_dir(raw, label):
    """Resuelve un directorio ABSOLUTO y existente (sin UNC); ValueError con la causa si no."""
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


def _resolve_paths(a, ops):
    """Resuelve cola, motor, worktrees, cupo y umbral de disco (argumento > entorno > derivado).

    Before: ``a`` son los argumentos; ``ops`` es el directorio de operacion ya resuelto
        (None en ``--self-check``).
    During: cada ruta invalida deja ciego SOLO a su detector y suma una causa; el umbral
        de disco invalido es un error de configuracion.
    After: (cfg, causas de detector-sin-config, error fatal o None).
    """
    env = os.environ
    causes = []
    cfg = SimpleNamespace(ops=ops, state=None, cola=None, motor=None, quota=None)
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
    fatal = _free_gb_min(cfg, env.get("STALL_FREE_GB_MIN"))
    return cfg, causes, fatal


def _free_gb_min(cfg, raw):
    """Fija ``cfg.free_gb_min`` desde ``STALL_FREE_GB_MIN``; devuelve el error fatal o None."""
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


def _detect(out, st):
    """Corre los detectores; uno roto no tapa a los demas (``detector-roto`` AVISO)."""
    found, broke = [], False
    for fn in (
        lambda: check_quota(out),
        lambda: check_cola(out, st),
        lambda: check_git(out, st),
        lambda: check_disk(out),
        lambda: check_hook(out),
        lambda: check_tarea(out),
    ):
        try:
            found += fn()
        except Exception as exc:  # noqa: PERF203 - un detector roto no tapa a los demas
            broke = True
            found.append(
                (
                    "detector-roto",
                    "AVISO",
                    f"Un detector de paradas fallo: {str(exc)[:80]}",
                )
            )
    return found, broke


def _notify_all(ca, found, a):
    """Avisa (o marca con --baseline) cada hallazgo; devuelve el rc (1 hallazgos, 2 aviso fallido)."""
    rc = 0
    for key, level, what in found:
        rc = max(rc, 1)
        if a.baseline:
            ca.mark_seen(key, level, "stall", a.dry_run)
            print(f"BASELINE {level} {key}")
            continue
        r = ca.event(key, level, None, what, False, a.dry_run, owner="stall")
        if r == 2:
            rc = 2
        print(f"{level} {key} rc_aviso={r} {what}")
    return rc


def _reconcile(ca, out, found, a):
    """Borra las claves de SU owner que el detector ya no ve y resuelve ``tarea-muerta`` si se recupero."""
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


def run(a):
    """Un tick: carga el aviso, resuelve la configuracion, detecta, avisa y guarda el reloj.

    Before: argumentos ``a`` (dry_run, baseline, ops_dir, ...).
    During: ver el docstring del modulo.
    After: rc 0/1/2; con ``--dry-run`` no escribe estado; ``ts_latido`` se escribe en
        cada ejecucion no-dry, tambien con ``--baseline``.
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
    st, out = _state(), {}
    found, broke = _detect(out, st)
    if causes:
        found.insert(
            0,
            (
                "detector-sin-config",
                "AVISO",
                "Detector sin configurar: " + "; ".join(c[:80] for c in causes),
            ),
        )
    rc = _notify_all(ca, found, a)
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
    a = ap.parse_args(argv)
    try:
        return self_check(a) if a.self_check else run(a)
    except Exception as exc:
        print(f"STALL_CHECK_BROKEN: {type(exc).__name__}: {str(exc)[:160]}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
