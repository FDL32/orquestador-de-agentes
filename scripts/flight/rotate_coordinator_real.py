"""Rotacion GENERAL de coordinadora SALIENTE -> ENTRANTE (staging, no versionado; el escritor no cubre active_roles.orquestador, H91).

Generaliza rotate_coordinator.py (CO-9 -> CO-10). El saliente y el supervisor vigente se LEEN del roster (no se asumen):
  fase A: 1) write_role_estado(orquestador, PENDIENTE_ACK) sobre el saliente (linea canonica; arranca el plazo de 15 min del check (b));
          2) identidad del roster al entrante (PENDIENTE_ACK, predecessor = saliente) y del registro, seguidos, con copia previa y CAS por version;
          3) write_supervisor(saliente) por el escritor (el supervisor vigente pasa a cadena_contexto, cabeza).
  fase B: (tras el ACK medido del entrante, dentro de 900 s de la fase A) write_role_estado(orquestador, ACTIVO) y estado del registro.
Modos: --rehearsal opera SOLO sobre copias en un directorio temporal (ejecuta el guard y un control negativo); --apply-phase A|B opera sobre los reales.
No toca el bloque `autoridad` del registro (la autoridad es de la coordinadora por posicion de rol, no por persona; el usuario retiene push y backends).
"""

import argparse
import copy
import datetime
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


_role_key_load_error: Exception | None = None
try:
    _role_key_path = (
        Path(__file__).resolve().with_name("roster_role_key.py")
    ).resolve()
    _role_key_name = "_flt_roster_role_key_" + str(_role_key_path).replace(
        "\\", "_"
    ).replace(":", "_")
    _role_key_spec = importlib.util.spec_from_file_location(
        _role_key_name, _role_key_path
    )
    if _role_key_spec is None or _role_key_spec.loader is None:
        raise ImportError("no se pudo cargar roster_role_key.py")
    _role_key_module = importlib.util.module_from_spec(_role_key_spec)
    _role_key_spec.loader.exec_module(_role_key_module)
    RosterRoleKeyError = _role_key_module.RosterRoleKeyError
    orchestrator_entry = _role_key_module.orchestrator_entry
    resolve_orchestrator_role = _role_key_module.resolve_orchestrator_role
    set_orchestrator_entry = _role_key_module.set_orchestrator_entry
except Exception as _role_key_exc:
    _role_key_load_error = _role_key_exc

    class RosterRoleKeyError(ValueError):
        """Fallback resolver error for an isolated FLT copy."""

    def orchestrator_entry(_roles, _error=_role_key_exc):
        raise RosterRoleKeyError("roster_role_key.py no disponible") from _error

    def resolve_orchestrator_role(_roles, _error=_role_key_exc):
        raise RosterRoleKeyError("roster_role_key.py no disponible") from _error

    def set_orchestrator_entry(_roles, _entry, _error=_role_key_exc):
        raise RosterRoleKeyError("roster_role_key.py no disponible") from _error


MOTOR = Path()
W = None
FILES = ("flight_roster.json", "session_registry.json", "roster_changes.jsonl")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:12]


def guard(fl, acting):
    cmd = [
        sys.executable,
        str(MOTOR / "scripts/check_roster_matches_acting_thread.py"),
        "--roster-path",
        str(fl / "flight_roster.json"),
        "--acting-thread",
        acting,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")  # noqa: S603 - command uses controlled paths
    return r.returncode, (r.stdout + r.stderr).strip()


def load_registry(path):
    raw = Path(path).read_bytes()
    if b"\r\n" in raw:
        raise AssertionError("el registro contiene finales de linea CRLF")
    data = json.loads(raw.decode("utf-8"))
    if json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8") + b"\n" != raw:
        raise AssertionError("formato del registro no reproducible: no escribo")
    return data


def save_registry(path, data):
    out = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(out)
    os.replace(tmp, path)


def phase_a(fl, a, backups, actor):
    roster_p, reg_p, log_p = (
        fl / "flight_roster.json",
        fl / "session_registry.json",
        fl / "roster_changes.jsonl",
    )
    for p in (roster_p, reg_p, log_p):
        shutil.copy2(
            p,
            backups / (p.name + f".pre_rotacion_{a.in_code.lower().replace('-', '')}"),
        )
    r0 = W._read_roster(roster_p)
    orq0 = orchestrator_entry(r0["active_roles"])
    sup0 = r0["active_roles"]["supervisor"]
    if not (
        orq0["threadId"] == a.out_thread and orq0.get("estado", "ACTIVO") == "ACTIVO"
    ):
        raise AssertionError(
            "el roster no esta en el estado inicial esperado (saliente ACTIVO)"
        )
    if orq0.get("session_code") != a.out_code:
        raise AssertionError("session_code del saliente no coincide")
    old_sup_thread, old_sup_code = sup0["threadId"], sup0["session_code"]
    if not (a.in_thread != a.out_thread and a.in_thread != old_sup_thread):
        raise AssertionError(
            "la identidad entrante coincide con una identidad existente"
        )
    reason = a.reason
    # 1) el saliente congela su ranura
    W.write_role_estado(
        roster_p,
        "orquestador",
        "PENDIENTE_ACK",
        changes_log_path=log_p,
        actor=actor,
        reason=f"relevo planificado {a.out_code} -> {a.in_code}; {reason}",
    )
    # 2) identidad: roster y registro seguidos
    r1 = W._read_roster(roster_p)
    v = orchestrator_entry(r1["active_roles"])["version"]
    new = copy.deepcopy(r1)
    set_orchestrator_entry(
        new["active_roles"],
        {
            "threadId": a.in_thread,
            "session_code": a.in_code,
            "since": now(),
            "set_by": f"{actor} (relevo planificado {a.out_code} -> {a.in_code}; {reason})",
            "predecessor_threadId": a.out_thread,
            "version": v + 1,
            "status": "active",
            "approved_by": a.approved_by,
            "nota": f"{a.in_code} es codigo/etiqueta; la clave `orquestador` del roster es el nombre del campo de la coordinadora y su renombre es un ticket aparte. Cadena en session_registry.json -> cadena_consulta.",
            "estado": "PENDIENTE_ACK",
        },
    )
    W._validate_active_role_fields(orchestrator_entry(new["active_roles"]))
    fresh = W._read_roster(roster_p)
    if orchestrator_entry(fresh["active_roles"])["version"] != v:
        raise AssertionError("CAS: el roster cambio")
    W._atomic_write_json(roster_p, new)
    W._append_change_line(
        log_p,
        by=actor,
        change="orquestador_rotation",
        detail=f"orquestador {a.out_thread} -> {a.in_thread} ({a.in_code}); estado PENDIENTE_ACK; version {v} -> {v + 1}",
        reason="el escritor no cubre active_roles.orquestador (H91): cambio de identidad por protocolo (copia + hash + linea); "
        + reason,
    )
    reg = load_registry(reg_p)
    ts = now()
    sess = {s["code"]: s for s in reg["sessions"]}
    pre = sess.get(a.in_code)
    if pre is not None and not (
        pre["threadId"] == a.in_thread
        and str(pre.get("status", "")).startswith("PENDIENTE")
    ):  # PARCHE CO-72 17:40: el entrante ya figura como PENDIENTE
        raise AssertionError(
            "el entrante figura en el registro pero NO como PENDIENTE de este hilo"
        )
    sess[a.out_code]["role"] = "supervisora"
    sess[a.out_code]["status"] = (
        f"SUPERVISORA directa de {a.in_code} (desde {ts}; vigila con su latido, sin autoridad)"
    )
    sess[old_sup_code]["status"] = (
        f"CASCADA DE CONTEXTO (consultable, sin autoridad ni vigilancia; ex-supervisora, desde {ts}; relevo {a.out_code} -> {a.in_code})"
    )
    if pre is not None:
        pre.update(
            {
                "started": ts,
                "status": "ACTIVA (PENDIENTE_ACK hasta el ACK medido; no actua hasta ACTIVO)",
                "reporta_a": a.out_code,
                "nota": f"Sucesora de {a.out_code}; coordinadora lanzada por {a.out_code} con relevo planificado acordado con la supervisora {old_sup_code} (alta previa de {a.out_code} a las {ts}, actualizada en sitio por la fase A). Paquete: {a.package}.",
            }
        )
    else:
        reg["sessions"].append(
            {
                "code": a.in_code,
                "role": "orquestadora",
                "slot": a.slot,
                "threadId": a.in_thread,
                "started": ts,
                "status": "ACTIVA (PENDIENTE_ACK hasta el ACK medido; no actua hasta ACTIVO)",
                "supersedes": a.out_code,
                "launched_by": a.out_code,
                "nota": f"Coordinadora lanzada por {a.out_code} con relevo planificado acordado con la supervisora {old_sup_code}. Paquete: {a.package}.",
            }
        )
    reg["orquestador_activo"] = a.in_code
    cc = reg["cadena_consulta"]
    prev = [
        e
        for e in cc.get("desde_orquestador", [])
        if e["code"] not in (a.out_code, old_sup_code)
    ]
    cc["desde_orquestador"] = [
        {
            "pos": 1,
            "code": a.out_code,
            "threadId": a.out_thread,
            "rol": "supervisora directa",
            "desde": ts,
        },
        {
            "pos": 2,
            "code": old_sup_code,
            "threadId": old_sup_thread,
            "rol": "cascada de contexto (ex-supervisora; consultable, sin autoridad)",
            "desde": ts,
        },
    ] + [dict(e, pos=i + 3) for i, e in enumerate(prev)]
    cc["latidos_en_cascada"] = (
        f"{a.out_code} -> {a.in_code}; {a.in_code} -> implantadores vivos. El supervisor no tiene vigilante propio: el latido de {a.in_code} comprueba que {a.out_code} sigue viva y avisa al usuario si cae."
    )
    cc["nota_relevo"] = (
        f"{a.in_code} releva a {a.out_code} el {ts}; {a.out_code} pasa a supervisora; {old_sup_code} pasa a la cascada de contexto; {reason}"
    )
    cc["registrado_por"], cc["registrado"] = actor, ts
    reg["actualizado"] = ts
    save_registry(reg_p, reg)
    W._append_change_line(
        log_p,
        by=actor,
        change="registry_rotation",
        detail=f"session_registry.json: alta {a.in_code}, {a.out_code} supervisora, {old_sup_code} a cascada, orquestador_activo={a.in_code}, cadena_consulta; bloque autoridad INTACTO; copia previa {backups.as_posix()}",
        reason=reason,
    )
    # 3) supervisor por el escritor (el vigente pasa a cadena_contexto, cabeza)
    W.write_supervisor(
        roster_p,
        a.out_thread,
        a.out_code,
        changes_log_path=log_p,
        actor=actor,
        reason=f"relevo planificado {a.out_code} -> {a.in_code}; el supervisor es la coordinadora anterior (regla estructural); {reason}",
    )


def phase_b(fl, a, actor):
    """Activate the incoming coordinator and record its post-rotation window.

    Before: phase A has installed the incoming identity in roster and registry.
    During: write ACTIVO, one active timestamp, and its seven-minute deadline.
    After: the incoming registry row is ready for the heartbeat detector.
    """
    W.write_role_estado(
        fl / "flight_roster.json",
        "orquestador",
        "ACTIVO",
        changes_log_path=fl / "roster_changes.jsonl",
        actor=actor,
        reason=f"ACK medido de {a.in_code}; relevo completado; {a.reason}",
    )
    reg_p = fl / "session_registry.json"
    reg = load_registry(reg_p)
    active_ts = now()
    deadline = datetime.datetime.fromisoformat(active_ts) + datetime.timedelta(
        minutes=7
    )
    for s in reg["sessions"]:
        if s["code"] == a.in_code:
            s["status"] = f"ACTIVA (ACK medido {active_ts})"
            s["activo_ts"] = active_ts
            s["post_relevo_plazo"] = deadline.isoformat(timespec="seconds")
    reg["actualizado"] = active_ts
    save_registry(reg_p, reg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--motor-root", default=Path(__file__).resolve().parents[2])
    ap.add_argument("--fl-dir", required=True)
    ap.add_argument("--backups-dir", required=True)
    ap.add_argument("--out-code", default="CO-10")
    ap.add_argument("--out-thread", default="mcp:faa4a4cd-6d32-4bb1-a936-ee99a5925c39")
    ap.add_argument("--in-code", default="CO-11")
    ap.add_argument("--in-thread", default="mcp:00000000-0000-0000-0000-00000000c011")
    ap.add_argument("--slot", default="coordinadora-11")
    ap.add_argument("--package", default="diseno/ARRANQUE_CO-11_20261030.md")
    ap.add_argument(
        "--actor",
        default="CO-9",
        help="quien ejecuta el script (la supervisora), no el saliente",
    )
    ap.add_argument(
        "--approved-by",
        default="supervisora CO-9 (sin objecion; mensaje co9-co10-relevo-co11-1235)",
    )
    ap.add_argument(
        "--reason",
        default="relevo planificado de la coordinadora por contexto agotado (ventana de no-relevo medida abierta), acordado con la supervisora",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--rehearsal", action="store_true")
    g.add_argument("--apply-phase", choices=["A", "B"])
    a = ap.parse_args()
    global MOTOR, W
    MOTOR = Path(a.motor_root).resolve()
    if not MOTOR.is_dir():
        print(f"--motor-root no es un directorio: {MOTOR}")
        return 3
    sys.path.insert(0, str(MOTOR / "scripts"))
    W = importlib.import_module("flight_roster_writer")
    backups_dir = Path(a.backups_dir).resolve()
    backups_dir.mkdir(parents=True, exist_ok=True)
    real = Path(a.fl_dir)
    if a.rehearsal:
        before = {p: sha(real / p) for p in FILES}
        tmp = Path(tempfile.mkdtemp(prefix="rot_v2_"))
        fl = tmp / "fl"
        fl.mkdir()
        for p in FILES:
            shutil.copy2(real / p, fl / p)
        bk = backups_dir
        rc, out = guard(fl, a.out_thread)
        print(
            f"ESTADO INICIAL guard acting={a.out_code}: rc",
            rc,
            out[-200:].replace("\n", " | "),
        )
        phase_a(fl, a, bk, a.actor)
        rc, out = guard(fl, a.in_thread)
        print(
            f"TRAS FASE A guard acting={a.in_code}: rc",
            rc,
            out[-300:].replace("\n", " | "),
        )
        rc_old, _ = guard(fl, a.out_thread)
        print(
            f"TRAS FASE A guard acting={a.out_code} (control: debe FALLAR, ya no es la coordinadora): rc",
            rc_old,
        )
        phase_b(fl, a, a.actor)
        rc, out = guard(fl, a.in_thread)
        print(
            f"TRAS FASE B guard acting={a.in_code}: rc",
            rc,
            out[-300:].replace("\n", " | "),
        )
        r = json.loads((fl / "flight_roster.json").read_text(encoding="utf-8"))
        print(
            "roster final: orquestador",
            orchestrator_entry(r["active_roles"])["session_code"],
            orchestrator_entry(r["active_roles"])["estado"],
            "| supervisor",
            r["active_roles"]["supervisor"]["session_code"],
            "| cascada",
            [e["session_code"] for e in r["cadena_contexto"]],
        )
        g2 = load_registry(fl / "session_registry.json")
        print(
            "registro final: orquestador_activo",
            g2["orquestador_activo"],
            "| autoridad intacta:",
            g2["autoridad"]
            == load_registry(real / "session_registry.json")["autoridad"],
            "| cadena_consulta",
            [(e["pos"], e["code"]) for e in g2["cadena_consulta"]["desde_orquestador"]],
        )
        # control negativo: roster rotado pero registro SIN rotar -> el guard debe fallar
        fl2 = tmp / "fl2"
        fl2.mkdir()
        for p in FILES:
            shutil.copy2(real / p, fl2 / p)
        W.write_role_estado(
            fl2 / "flight_roster.json",
            "orquestador",
            "PENDIENTE_ACK",
            changes_log_path=fl2 / "roster_changes.jsonl",
            actor=a.actor,
            reason="control",
        )
        r1 = W._read_roster(fl2 / "flight_roster.json")
        n2 = copy.deepcopy(r1)
        orchestrator_entry(n2["active_roles"]).update(
            {
                "threadId": a.in_thread,
                "session_code": a.in_code,
                "predecessor_threadId": a.out_thread,
                "version": orchestrator_entry(r1["active_roles"])["version"] + 1,
            }
        )
        W._atomic_write_json(fl2 / "flight_roster.json", n2)
        rc2, out2 = guard(fl2, a.in_thread)
        print(
            "CONTROL NEGATIVO (roster rotado, registro NO): rc",
            rc2,
            "(debe ser 1)",
            out2[-300:].replace("\n", " | "),
        )
        after = {p: sha(real / p) for p in FILES}
        print("FICHEROS REALES INTACTOS:", before == after, after)
        print("tmp", tmp)
        return
    if a.in_thread.endswith("c011"):
        sys.exit(
            "--in-thread es el marcador de ensayo: pasa el threadId real de la entrante"
        )
    if a.apply_phase == "A":
        phase_a(real, a, backups_dir, a.actor)
        print(f"FASE A aplicada; guard acting={a.in_code}:", guard(real, a.in_thread))
    else:
        phase_b(real, a, a.actor)
        print(f"FASE B aplicada; guard acting={a.in_code}:", guard(real, a.in_thread))


if __name__ == "__main__":
    raise SystemExit(main())
