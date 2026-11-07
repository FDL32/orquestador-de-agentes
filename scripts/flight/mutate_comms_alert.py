"""Arnes de mutacion para scripts/flight/comms_alert.py (WOT-2026-153p).

Uso: python mutate_153i.py --repo <worktree> [--box 1A|1B|1C|all] [--ids N1,N2] [--inject-bad-pattern]
Before: repo es una raiz existente y contiene scripts/flight/comms_alert.py; las mutaciones activas son
    patrones versionados que deben casar exactamente una vez.
During: valida patrones, crea una copia temporal del directorio de scripts/flight y ejecuta un
    executor inyectable en serie; el executor por defecto lanza pytest con timeout acotado.
After: devuelve rc 0 solo sin supervivientes ni errores de validacion; un timeout (rc 99) no es
    una muerte. El original nunca se escribe y cada copia temporal se elimina en finally.
"""

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile
import time


MUT = []

# Patrones medidos contra la base 9fbe371: los retirados no se silencian; cada
# motivo es parte del contrato y se comprueba por el test focal.
RETIRED = {
    "N1": "obsoleto tras 159a: bloque de excepciones reescrito",
    "N2": "obsoleto tras 159a: bloque de excepciones reescrito",
    "E2": "obsoleto tras 159a: normalizacion de estado reescrita",
    "N7": "obsoleto tras 159a: implementacion del lock reescrita",
    "X14": "obsoleto tras 159a: parser reescrito",
    "N30": "obsoleto tras 159a: escaneo reescrito",
    "N31": "obsoleto tras 159a: escaneo reescrito",
    "N32": "obsoleto tras 159a: escaneo reescrito",
    "D19b": "duplicado en la base vigente; no es una mutacion univoca",
    "N38": "duplicado en la base vigente; no es una mutacion univoca",
    "N42": "obsoleto tras 159a: parser reescrito",
    "N44": "obsoleto tras 159a: parser reescrito",
    "N46": "obsoleto tras 159a: parser reescrito",
    "D15a": "obsoleto tras 159a: resultado normalizado reescrito",
    "Q4a": "obsoleto tras 159a: lectura de cola reescrita",
    "N50": "duplicado en la base vigente; no es una mutacion univoca",
    "N54": "obsoleto tras 159a: sanitizacion reescrita",
    "N56b": "obsoleto: rama PowerShell sustituida",
    "N56c": "obsoleto: rama PowerShell sustituida",
    "N57": "obsoleto: rama PowerShell sustituida",
    "SJ3": "obsoleto: rama PowerShell sustituida",
    "B1a": "obsoleto tras 159a: split del ledger reescrito",
    "B1c": "duplicado en la base vigente; no es una mutacion univoca",
    "C1a": "obsoleto tras 159a: carga de estado reescrita",
}


def m(mid, box, pattern, repl, target="comms_alert.py"):
    MUT.append((mid, box, target, pattern, repl))


# ---- caja 1A ----
m(
    "N1",
    "1A",
    "    except (OSError, ValueError, RecursionError):\n        return {}\n    return data if",
    "    except (ValueError, RecursionError):\n        return {}\n    return data if",
)
m(
    "N2",
    "1A",
    "    except (OSError, ValueError, RecursionError):\n        return {}\n    return data if",
    "    except (OSError, RecursionError):\n        return {}\n    return data if",
)
m(
    "E1",
    "1A",
    'STATE.read_text(encoding="utf-8-sig")',
    'STATE.read_text(encoding="utf-8")',
)
m("E2", "1A", "    return data if isinstance(data, dict) else {}", "    return data")
m(
    "N3",
    "1A",
    "        os.replace(tmp, STATE)\n",
    '        STATE.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")\n',
)
m(
    "N4",
    "1A",
    'tmp = STATE.with_suffix(f".{os.getpid()}.tmp")',
    'tmp = STATE.with_suffix(".tmp")',
)
m(
    "M14",
    "1A",
    "    with _Lock(LOCK):\n        st = load_state()",
    "    if True:\n        st = load_state()",
)
m(
    "N5",
    "1A",
    'LOCK = base / "comms_alert.oslock"',
    'LOCK = base / "comms_alert_state.json"',
)
m(
    "N6",
    "1A",
    "msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)",
    "msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)",
)
m(
    "N7",
    "1A",
    '(1 byte en el offset 0) SIN esperar; OSError si no."""\n    fh.seek(0)',
    '(1 byte en el offset 0) SIN esperar; OSError si no."""\n    fh.seek(os.getpid() % 1000 + 1)',
)
m("N8", "1A", 'self.fh = open(self.path, "a+b")', 'self.fh = open(self.path, "wb")')
m(
    "N9",
    "1A",
    "                self.held = True\n                return self",
    "                self.held = True\n                self.fh.close()\n                return self",
)
m(
    "N10",
    "1A",
    "    with _Lock(LOCK):\n        st = load_state()",
    "    with _Lock(STATE):\n        st = load_state()",
)
m(
    "N11",
    "1A",
    "                    return self\n                _real_time.sleep(0.1)",
    "                    pass\n                _real_time.sleep(0.1)",
)
m(
    "N12",
    "1A",
    "                _real_time.sleep(0.1)",
    "                if os.path.getmtime(self.path) < _real_time.time() - 30:\n                    self.fh.close()\n                    os.unlink(self.path)\n                    return self\n                _real_time.sleep(0.1)",
)
m(
    "N13",
    "1A",
    "        except OSError:\n            return self\n        while True:",
    "        except OSError:\n            raise\n        while True:",
)
m(
    "N14",
    "1A",
    "                if _real_time.time() >= end:\n                    print(",
    '                if _real_time.time() >= end:\n                    raise TimeoutError("agotado")\n                    print(',
)
m(
    "N15",
    "1A",
    "                if exc.errno not in _CONTENTION:\n                    return self",
    "                if exc.errno not in _CONTENTION:\n                    raise",
)
m(
    "N16",
    "1A",
    "        if self.fh is None:\n            return\n        try:\n            if self.held:",
    "        return\n        try:\n            if self.held:",
)
m(
    "N17",
    "1A",
    "        except OSError:\n            pass\n        finally:",
    "        except OSError:\n            raise\n        finally:",
)
m(
    "N20",
    "1A",
    "    def __exit__(self, *exc):\n        if self.fh is None:",
    "    def __exit__(self, *exc):\n        if self.fh is None or exc[0] is not None:",
)
m(
    "N21",
    "1A",
    '    return 1 if rec.get("level") in (None, "URGENTE") else 0',
    '    return 0 if rec.get("level") in (None, "URGENTE") else 0',
)
m(
    "N22",
    "1A",
    '    if rec is None:\n        return "nueva"',
    "    if rec is None:\n        return None",
)
m(
    "M8",
    "1A",
    '    if rec.get("acked"):\n        return None\n    if level == "URGENTE" and rec.get("level") == "AVISO":',
    '    if level == "URGENTE" and rec.get("level") == "AVISO":',
)
m(
    "N23",
    "1A",
    '    if level == "URGENTE" and rec.get("level") == "AVISO":\n        return "sube de nivel"\n',
    "",
)
m(
    "M3",
    "1A",
    '        return "persiste" if now - rec.get("last", 0) >= wait else None',
    '        return "persiste"',
)
m("M11", "1A", "BACKOFF_MIN = (30, 60, 120, 240)", "BACKOFF_MIN = (30, 60, 120, 120)")
m(
    "M4",
    "1A",
    "    return None\n\n\ndef _record(",
    '    return "repite"\n\n\ndef _record(',
)
m("N24", "1A", '"first": (rec or {}).get("first", now),', '"first": now,')
m("X10", "1A", "    if level not in LEVELS:", "    if False:")
m(
    "N25",
    "1A",
    '    why = "forzado" if force else _due(rec, level, now)',
    "    why = _due(rec, level, now)",
)
m(
    "M1",
    "1A",
    "        if rc == 0:\n            update_state(lambda s: _record(s, key, level, now, owner))",
    "        if True:\n            update_state(lambda s: _record(s, key, level, now, owner))",
)
m(
    "N26",
    "1A",
    '    update_state(\n        lambda s: s.__setitem__(\n            "event:" + key,',
    '    update_state(\n        lambda s: s.get(\n            "event:" + key,',
)
m(
    "N27",
    "1A",
    "    if dry:\n        return\n    now = time.time()\n    update_state(",
    "    if False:\n        return\n    now = time.time()\n    update_state(",
)
m(
    "X14",
    "1A",
    '        print(f"sin registro de {key}")\n        return 10\n    if not dry:\n\n        def f(s):',
    '        print(f"sin registro de {key}")\n        pass\n    if not dry:\n\n        def f(s):',
)
m(
    "N28",
    "1A",
    "    if not dry:\n\n        def f(s):",
    "    if True:\n\n        def f(s):",
)
m(
    "N29",
    "1A",
    '        update_state(lambda s: s.pop("event:" + key, None))',
    '        update_state(lambda s: s.get("event:" + key, None))',
)
m(
    "N30",
    "1A",
    '        print(f"sin registro de {key}")\n        return 10\n    if not dry:\n        update_state(lambda s: s.pop(',
    '        print(f"sin registro de {key}")\n        return 0\n    if not dry:\n        update_state(lambda s: s.pop(',
)
m(
    "N31",
    "1A",
    '    if not dry:\n        update_state(lambda s: s.pop("event:" + key, None))',
    '    if True:\n        update_state(lambda s: s.pop("event:" + key, None))',
)
m(
    "M2",
    "1A",
    "            if not dry:\n                del s[k]",
    "            if not dry:\n                pass",
)
m(
    "M12",
    "1A",
    "            if owner is not None and dueno not in (owner, None):",
    "            if False:",
)
m(
    "N32",
    "1A",
    "            gone.append(k[6:])\n            if not dry:\n                del s[k]\n\n    if dry:\n        f(load_state())\n    else:\n        update_state(f)",
    "            gone.append(k[6:])\n            del s[k]\n\n    update_state(f)",
)
m(
    "N33",
    "1A",
    '                k.startswith("event:")\n                and k[6:]',
    '                (k.startswith("event:") or k == "_last_scan_offset")\n                and k[6:]',
)
m(
    "N34",
    "1A",
    "dueno not in (owner, None):",
    'dueno not in (owner, None, "check", "task", "stall"):',
)
m(
    "P1",
    "1A",
    'OPS_DIR_ENV = "FLIGHT_OPS_DIR"',
    'OPS_DIR_ENV = "FLIGHT_OPS_DIR"\n_X = "C:/Users/fdl/tmp_or8"',
)
m(
    "P2",
    "1A",
    "    raw = arg if arg else env.get(OPS_DIR_ENV)",
    "    raw = (arg if arg else env.get(OPS_DIR_ENV)) or str(pathlib.Path.cwd())",
)
m(
    "P3",
    "1A",
    '    LEDGER_LOCK = base / "comms_ledger.oslock"\n    return base',
    '    LEDGER_LOCK = base / "comms_ledger.oslock"\n    globals()["NOTIFY"] = base / "notify_user.ps1"\n    return base',
)


# ---- extras de 1A cerradas en 1B (deuda 2 y Q3) ----  (E5 y E7 RETIRADOS en la ronda 1: con A2 un `last` no numerico ya no llega a _due/event, el `_num` era codigo muerto y se quito)
m("E3", "1B", "    last = _num(st.get(key), 0)", "    last = st.get(key, 0)")
m(
    "E4",
    "1B",
    "    return None\n\n\ndef _nu(rec):",
    '    return {"level": None, "first": v, "last": v, "n": 1, "acked": False}\n\n\ndef _nu(rec):',
)
m(
    "E6",
    "1B",
    "    if isinstance(nu, int) and not isinstance(nu, bool):\n        return nu",
    "    if True:\n        return nu",
)
m(
    "E8",
    "1B",
    '                r = _rec(s["event:" + key]) or _rec(0)',
    '                r = _rec(s["event:" + key])',
)
m(
    "E9",
    "1B",
    '            dueno = (_rec(s[k]) or {}).get("owner")',
    '            dueno = _rec(s[k]).get("owner")',
)
# ---- caja 1B ----
m("N35", "1B", 'open(LEDGER, "a+b")', 'open(LEDGER, "r+b")')
m("X11", "1B", '            if fh.read(1) != b"\\n":', "            if False:")
m(
    "N36",
    "1B",
    '    if dry:\n        print("DRY-RUN notify:", title, "|", message)\n        return 0',
    '    if dry:\n        print("DRY-RUN notify:", title, "|", message)',
)
m("X15", "1B", "            creationflags=flags,\n", "")
m(
    "D19b",
    "1B",
    '        "-NonInteractive",\n',
    '        "-NonInteractive",\n        "-ExecutionPolicy",\n        "Bypass",\n',
)
m("N37", "1B", "    return r.returncode", "    return 0")
m(
    "M17",
    "1B",
    "    except (subprocess.TimeoutExpired, OSError) as exc:",
    "    except OSError as exc:",
)
m(
    "N38",
    "1B",
    "    exe = _powershell_exe()\n    if exe is None:",
    '    exe = _powershell_exe() or "powershell"\n    if exe is None:',
)
m("X8", "1B", "    if not force and now - last < THROTTLE_S:", "    if False:")
m(
    "N39",
    "1B",
    "    last = _num(st.get(key), 0)",
    "    last = max([_num(v, 0) for v in st.values()] or [0])",
)
m(
    "X9",
    "1B",
    "        if rc == 0:\n            update_state(lambda s: s.__setitem__(key, now))",
    "        if True:\n            update_state(lambda s: s.__setitem__(key, now))",
)
m(
    "N40",
    "1B",
    '                "ALERT" if rc == 0 else "ALERT_FALLIDO",\n                _nota("-", "manual", rc, what),',
    '                "ALERT",\n                _nota("-", "manual", rc, what),',
)
m(
    "N41",
    "1B",
    "    return 0 if rc == 0 else 2\n\n\ndef _is_num",
    "    return 0\n\n\ndef _is_num",
)
m(
    "N42",
    "1B",
    '    rc = notify(title or (f"Vuelo: {key}"), what, dry)\n    if not dry:',
    '    rc = notify(title or (f"Vuelo: {key}"), what, dry)\n    if True:',
)
m(
    "N43",
    "1B",
    '        "nota": nota,\n    }',
    '        "nota": nota,\n        "extra": 1,\n    }',
)
m(
    "N44",
    "1B",
    "    if offset is None:\n        offset = size\n    elif not _is_int(offset)",
    "    if offset is None:\n        offset = 0\n    elif not _is_int(offset)",
)
m("X12", "1B", "or offset < 0 or offset > size:", "or offset < 0:")
m("M13", "1B", "    consumed = cut + 1 if cut >= 0 else 0", "    consumed = len(raw)")
m(
    "X13",
    "1B",
    '"FAIL" in val or "parent_not_active" in val or fused.search(val)',
    "False",
)
m(
    "N45",
    "1B",
    "                if isinstance(val, dict) and not _is_own(val):",
    "                if not _is_own(val):",
)
m(
    "M9",
    "1B",
    '    if d.get("from") == "comms_alert":\n        return True',
    "    if False:\n        return True",
)
m(
    "D20a",
    "1B",
    '    return d.get("by") == "comms_alert" and str(d.get("mensaje_id", "")).startswith(\n        OWN_PREFIX\n    )',
    '    return d.get("by") == "comms_alert"',
)
m(
    "D20b",
    "1B",
    '        "mensaje_id": f"{OWN_PREFIX}{uuid.uuid4()}",',
    '        "mensaje_id": f"{uuid.uuid4()}",',
)
m(
    "D20c",
    "1B",
    '        "mensaje_id": f"{OWN_PREFIX}{uuid.uuid4()}",',
    '        "mensaje_id": f"{OWN_PREFIX}fijo",',
)
m(
    "Q7a",
    "1B",
    "            elif not _RE_OWN_FRAGMENT.search(val) and (",
    "            elif True and (",
)
m(
    "N46",
    "1B",
    '    if not (verdict.upper().startswith("FAIL") or verdict in failures):',
    '    if not (verdict.upper() == "FAIL" or verdict in failures):',
)
m(
    "N47",
    "1B",
    '    return frozenset(_helper().VALID_RESULTADOS) - {"enviado"}',
    '    return frozenset(_helper().VALID_RESULTADOS) - {"enviado", "parent_not_active"}',
)
m(
    "D15a",
    "1B",
    '    if not (verdict.upper().startswith("FAIL") or verdict in failures):',
    '    if not verdict.upper().startswith("FAIL"):',
)
m(
    "D15c",
    "1B",
    '    verdict = str(d.get("resultado") or d.get("status") or d.get("result") or "")',
    '    verdict = str(d.get("resultado") or d.get("status") or "")',
)
m(
    "N48",
    "1B",
    '    pna = "parent_not_active" in (str(d.get("error")) + verdict)',
    "    pna = False",
)
m(
    "M10",
    "1B",
    "    if rc != 2 and not dry:\n        update_state(setoff)",
    "    if not dry:\n        update_state(setoff)",
)
m(
    "N49",
    "1B",
    "    if not new:\n        if not dry:\n            update_state(setoff)",
    "    if not new:\n        if True:\n            update_state(setoff)",
)
m(
    "N49b",
    "1B",
    "    if rc != 2 and not dry:\n        update_state(setoff)",
    "    if rc != 2:\n        update_state(setoff)",
)
m(
    "Q4a",
    "1B",
    '        print(f"scan FALLO: {exc}")\n        return 2\n    offset = load_state()',
    '        print(f"scan FALLO: {exc}")\n        return 10\n    offset = load_state()',
)
m(
    "N50",
    "1B",
    "        return resolve(a.resolve, a.dry_run)",
    "        return ack(a.resolve, a.dry_run)",
)
m("N51", "1B", 'owner="manual"', "owner=None")
m("N52", "1B", "    title = redact(title)\n", "")
m(
    "N53",
    "1B",
    '    out = _RE_THREAD.sub("mcp:<hilo>", str(text))',
    '    out = _RE_THREAD.sub("mcp:<hilo>", str(text)[:TEXT_LIMIT])',
)
m(
    "N54",
    "1B",
    "    return out\n\n\ndef ledger_append(row):",
    '    return out + "."\n\n\ndef ledger_append(row):',
)
m(
    "N55",
    "1B",
    '    with _Lock(LEDGER_LOCK), open(LEDGER, "a+b") as fh:',
    '    with open(LEDGER, "a+b") as fh:',
)
m(
    "D21a",
    "1B",
    "    clean = {\n        k: (redact(v) if k in _FREE_FIELDS and isinstance(v, str) else v)\n        for k, v in row.items()\n    }",
    "    clean = dict(row)",
)
m("D21b", "1B", "TEXT_LIMIT = 160", "TEXT_LIMIT = 1600")
m(
    "P4",
    "1B",
    '_HELPER_PATH = Path(__file__).resolve().with_name("send_with_ledger.py")',
    '_HELPER_PATH = Path.cwd() / "send_with_ledger.py"',
)


# ---- offset no entero del scan (cerrado en 1C, mismo patron fail-open que la deuda 2) ----
m(
    "Q3a",
    "1C",
    "    elif not _is_int(offset) or offset < 0 or offset > size:\n        offset = 0",
    "    elif False:\n        offset = 0",
)
m("Q3b", "1C", "or offset < 0 or offset > size:", "or offset > size:")
m(
    "Q3c",
    "1C",
    "    return isinstance(v, int) and not isinstance(v, bool)\n\n\ndef _rec",
    "    return isinstance(v, int)\n\n\ndef _rec",
)
m(
    "Q3d",
    "1C",
    "        offset = 0  # estado basura",
    "        offset = size  # estado basura",
)
m("Q3e", "1C", "    elif not _is_int(offset) or offset < 0", "    elif offset < 0")

# ---- notify_user.ps1 (filas 75-77) ----
PS = "notify_user.ps1"
m("M5", "1C", "if ($toastFail) { exit 3 }\n", "", PS)
m("M5b", "1C", "if ($toastFail) { exit 3 }", "if ($toastFail) { exit 1 }", PS)
m(
    "N56",
    "1C",
    "try {\n  if ($SimulateToastFailure) {",
    "try {\n  if ($NoFlash) { return }\n  if ($SimulateToastFailure) {",
    PS,
)
m("N56b", "1C", "if (-not $NoFlash) { try {", "if ($true) { try {", PS)
m(
    "N56c",
    "1C",
    "if (-not $NoFlash) { [console]::beep",
    "if ($true) { [console]::beep",
    PS,
)
m(
    "N57",
    "1C",
    "$out = @()\n",
    "$out = @()\nif ($env:NOTIFY_TEST -eq '1') { $NoFlash = [switch]$true }\n",
    PS,
)
m(
    "N57b",
    "1C",
    "[switch]$SimulateToastFailure,",
    "[switch]$Banner, [switch]$SimulateToastFailure,",
    PS,
)
m("SJ1", "1C", "if ($SimulateToastFailure) { throw", "if ($false) { throw", PS)
m("SJ2", "1C", '$out += "toast=FALLO(', '$out += "toast=fallo(', PS)
m(
    "SJ3",
    "1C",
    '  $out += "flash_ventanas=$n"\n',
    "  $out += \"flash_ventanas=$n\"\n  $out += 'banner=omitido'\n",
    PS,
)

# ---- ronda 1 de lentes (A1-A4) ----
m(
    "A1a",
    "1C",
    "            elif not _RE_OWN_FRAGMENT.search(val) and (",
    '            elif "comms_alert" not in val and (',
)
m(
    "A1b",
    "1C",
    '        out.append(("obj", obj))',
    '        out.append(("obj", obj))\n        break',
)
m(
    "A1c",
    "1C",
    "                if isinstance(val, dict) and not _is_own(val):",
    "                if isinstance(val, dict):",
)
m("A1d", "1C", '            out.append(("frag", line[pos:end]))', "            pass")
m(
    "A2a",
    "1C",
    '            v.get("level") in LEVELS\n            and isinstance',
    "            isinstance",
)
m("A2b", "1C", '            and isinstance(v.get("acked", False), bool)\n', "")
m("A2c", "1C", '            and ("last" not in v or _is_num(v["last"]))\n', "")
m("A3b", "1C", "or offset < 0 or offset > size:", "or offset < 0 or offset >= size:")
m(
    "A3c",
    "1C",
    "    elif not _is_int(offset) or offset < 0 or offset > size:\n        offset = 0",
    "    elif not _is_int(offset) or offset < 0 or offset > size:\n        offset = size",
)
m("M19", "1C", '    out = _RE_UUID.sub("<uuid>", out)\n', "")

# Q2a RETIRADO en la ronda 2: con la resincronizacion de _split_line (B1) un BOM delante del primer objeto queda como fragmento vacio y el objeto se parsea igual; quitar el removeprefix ya no cambia ningun resultado (mutante equivalente; el codigo se conserva como defensa explicita).
# ---- ronda 2 (B1, B2, B4) ----
m(
    "B1a",
    "1C",
    "            nxt = _RE_OBJ_START.search(line, pos + 1)",
    "            nxt = None",
)
m(
    "B1c",
    "1C",
    "        except (ValueError, RecursionError):",
    "        except ValueError:",
)
m(
    "B2a",
    "1C",
    "and not isinstance(v, bool) and abs(v) < 1e15",
    "and not isinstance(v, bool)",
)
m("B4a", "1C", '(1 if level == "URGENTE" else 0)', "1")

# ---- ronda 3 (C1, C2, C3) ----
m(
    "C1a",
    "1C",
    "    except (OSError, ValueError, RecursionError):\n        return {}",
    "    except (OSError, ValueError):\n        return {}",
)
m("C2a", "1C", "re.compile(r'\\{\\s*[\"}]')", "re.compile(r'\\{')")
m("C2b", "1C", "re.compile(r'\\{\\s*[\"}]')", "re.compile(r'\\{[\"}]')")
m("C3a", "1C", "and abs(v) < 1e15", "and abs(v) < 1e8")
m("C3a2", "1C", "and abs(v) < 1e15", "and abs(v) < 1e18")
m("C3b", "1C", "and not isinstance(v, bool) and abs(v) < 1e15", "and abs(v) < 1e15")


def die(msg):
    print("ARNES-ABORTA: " + msg, flush=True)
    sys.exit(1)


def _selected(box, ids, visible):
    """Return active mutations selected by CLI, keeping visible ones opt-in."""
    wanted = {item for item in ids.split(",") if item}
    result = [
        item for item in MUT if item[0] not in RETIRED and box in ("all", item[1])
    ]
    if wanted:
        result = [item for item in result if item[0] in wanted]
    if not visible:
        result = [item for item in result if item[0] not in {"SJ1", "N56b", "N56c"}]
    return result


def validate(repo, mutations):
    """Validate exact matches, compilability, and non-equivalence of mutations."""
    src_dir = pathlib.Path(repo).resolve() / "scripts" / "flight"
    seen = set()
    errors = []
    for mid, _box, fn, pattern, replacement in mutations:
        if mid in seen:
            errors.append(f"{mid}: id duplicado")
        seen.add(mid)
        try:
            original = (src_dir / fn).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{mid}: no se puede leer {fn}: {exc}")
            continue
        count = original.count(pattern)
        if count != 1:
            errors.append(f"{mid}: el patron casa {count} veces (debe ser 1)")
            continue
        mutated = original.replace(pattern, replacement)
        if mutated == original:
            errors.append(f"{mid}: la mutacion no difiere del original")
            continue
        if fn.endswith(".py"):
            try:
                compile(mutated, fn, "exec")
            except SyntaxError as exc:
                errors.append(f"{mid}: el codigo mutado no compila ({exc})")
    return errors


def _default_executor(repo, env, tests, timeout=180):
    """Run one focal test serially; callers may inject a deterministic executor."""
    command = [
        sys.executable,
        "-I",
        "-m",
        "pytest",
        *tests,
        "-x",
        "-q",
        "-o",
        "addopts=",
        "-p",
        "no:cacheprovider",
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - command is assembled from controlled CLI/test paths
            command,
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 99, "CRASH-TIMEOUT"
    output = (completed.stdout or "") + (completed.stderr or "")
    why = next(
        (line for line in output.splitlines() if line.startswith(("FAILED", "ERROR"))),
        output.strip().splitlines()[-1] if output.strip() else "",
    )
    return completed.returncode, why


def run_mutation(repo, mutation, tests, executor=None):
    """Run one mutation against a temporary copy and always remove that copy."""
    mid, box, fn, pattern, replacement = mutation
    src_dir = pathlib.Path(repo).resolve() / "scripts" / "flight"
    execute = executor or _default_executor
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="mutate_comms_") as tmp_name:
        tmp = pathlib.Path(tmp_name)
        for source in src_dir.iterdir():
            if source.suffix in (".py", ".ps1"):
                (tmp / source.name).write_text(
                    source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
                )
        original = (src_dir / fn).read_text(encoding="utf-8")
        (tmp / fn).write_text(
            original.replace(pattern, replacement), encoding="utf-8", newline="\n"
        )
        env = dict(os.environ, COMMS_ALERT_UNDER_TEST=str(tmp / "comms_alert.py"))
        rc, why = execute(repo, env, tests)
    return mid, box, rc, why, time.time() - started


def main(argv=None, executor=None):
    """Validate and optionally execute selected mutations without touching the source tree."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--box", default="all")
    parser.add_argument("--ids", default="")
    parser.add_argument("--tests", default="tests/unit/test_comms_alert.py")
    parser.add_argument("--inject-bad-pattern", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args(argv)
    mutations = _selected(args.box, args.ids, args.visible)
    if args.inject_bad_pattern:
        mutations.insert(
            0,
            (
                "BAD",
                args.box,
                "comms_alert.py",
                "ESTE PATRON NO EXISTE EN EL CODIGO",
                "x",
            ),
        )
    if not mutations:
        print("ARNES-ABORTA: tabla de patrones vacia", flush=True)
        return 1
    errors = validate(args.repo, mutations)
    if errors:
        for error in errors:
            print("ARNES-ABORTA: " + error, flush=True)
        return 1
    print(
        f"patrones validados: {len(mutations)} (cada uno casa 1 vez, compila y difiere)",
        flush=True,
    )
    if args.validate_only:
        return 0
    killed, survivors, timeouts = 0, [], []
    tests = [item for item in args.tests.split(",") if item]
    for mutation in mutations:
        mid, box, rc, why, elapsed = run_mutation(
            args.repo, mutation, tests, executor=executor
        )
        if rc == 99:
            timeouts.append(mid)
        elif rc != 0:
            killed += 1
        else:
            survivors.append(mid)
        label = (
            "KILLED"
            if rc != 0 and rc != 99
            else ("TIMEOUT" if rc == 99 else "SOBREVIVE")
        )
        print(f"{label} {mid} {box} {elapsed:.1f}s {why[:110]}", flush=True)
    print(
        f"RESUMEN: matadas {killed}/{len(mutations)}; timeouts: {timeouts or 'ninguno'}; supervivientes: {survivors or 'ninguno'}"
    )
    return 1 if survivors or timeouts else 0


if __name__ == "__main__":
    raise SystemExit(main())
