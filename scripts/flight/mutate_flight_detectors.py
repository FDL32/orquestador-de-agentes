"""Arnes de mutacion para flight_stall_check.py y quota_tick.py (WOT-2026-153p).

Uso: python -X utf8 -I mutate_flight_detectors.py --repo <worktree> [--box 2A|2B|all]
     [--ids N1,N2] [--tests TEST] [--workers 1] [--inject-bad-pattern]
     [--validate-only] [--control]
Reglas D23: cada patron casa EXACTAMENTE una vez, el codigo mutado compila y difiere del original; patron ausente, duplicado
o mutacion invalida => el arnes SALE con rc 1 sin seguir. Un superviviente no adjudicado => rc 1. Los mutantes EQUIVALENTES
declarados (EQUIV) se informan aparte y no cuentan como supervivientes. Solo rc 1 de pytest es KILLED; rc 99 es
TIMEOUT y otros rc no cero son ERROR. La ejecución activa es siempre serial y la copia contiene el árbol completo.
"""

import argparse
import concurrent.futures
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time


MUT = []
STALL = "flight_stall_check.py"
QUOTA = "quota_tick.py"
# mutantes equivalentes declarados: id -> motivo
EQUIV = {}
TESTS_BY_TARGET = {
    "flight_stall_check.py": "tests/unit/test_flight_stall_check.py",
    "quota_tick.py": "tests/unit/test_quota_tick.py",
}


def m(mid, box, pattern, repl, target=STALL):
    MUT.append((mid, box, target, pattern, repl))


# ---------------- caja 2A: flight_stall_check.py (filas 78-121 del Anexo B y formas nuevas O1-O10) ----------------
# --- D17 / carga ---
m(
    "N58",
    "2A",
    "    try:\n        ca = _load_alert()\n    except Exception as exc:",
    '    try:\n        ca = _load_alert()\n        _t = Path(a.ops_dir) / "comms_alert.py"\n        if _t.exists():\n            _s = importlib.util.spec_from_file_location("comms_alert", _t)\n            ca = importlib.util.module_from_spec(_s)\n            _s.loader.exec_module(ca)\n    except Exception as exc:',
)
m(
    "N59",
    "2A",
    'no se pudo cargar comms_alert.py: {str(exc)[:120]}")\n        return 2',
    'no se pudo cargar comms_alert.py: {str(exc)[:120]}")\n        pass',
)
# --- estado ---
m(
    "N60",
    "2A",
    "    except (OSError, ValueError, RecursionError):\n        return {}\n    return data if",
    "    except (OSError, RecursionError):\n        return {}\n    return data if",
)
m(
    "C1a",
    "2A",
    "    except (OSError, ValueError, RecursionError):\n        return {}\n    return data if",
    "    except (OSError, ValueError):\n        return {}\n    return data if",
)
m(
    "N60b",
    "2A",
    "    except (OSError, ValueError, RecursionError):\n        return {}\n    return data if",
    "    except (ValueError, RecursionError):\n        return {}\n    return data if",
)
m(
    "E1",
    "2A",
    'path.read_text(encoding="utf-8-sig"))\n    except',
    'path.read_text(encoding="utf-8"))\n    except',
)
m("E2", "2A", "    return data if isinstance(data, dict) else {}", "    return data")
m(
    "E3",
    "2A",
    "    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**6:\n        return value\n    return 0",
    "    return value",
)
m(
    "E4",
    "2A",
    "isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**6",
    "isinstance(value, int) and 0 <= value < 10**6",
)
m(
    "E5",
    "2A",
    "and not isinstance(value, bool) and 0 <= value < 10**6",
    "and not isinstance(value, bool) and 0 <= value",
)
m(
    "E6",
    "2A",
    "and not isinstance(value, bool) and 0 <= value < 10**6",
    "and not isinstance(value, bool) and value < 10**6",
)
m(
    "N81",
    "2A",
    "        os.replace(tmp, CFG.state)",
    '        CFG.state.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")',
)
m(
    "N86",
    "2A",
    'tmp = CFG.state.with_suffix(f".{os.getpid()}.tmp")',
    'tmp = CFG.state.with_suffix(".tmp")',
)
m(
    "E7",
    "2A",
    "        os.replace(tmp, CFG.state)",
    '        CFG.state.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")',
)
m("N82", "2A", '        st["ts_latido"] = time.time()', "        pass")
m("E8", "2A", '        st.pop("ts", None)\n', "")
m(
    "X17",
    "2A",
    '    if not a.dry_run:\n        st["ts_latido"]',
    '    if True:\n        st["ts_latido"]',
)
# --- git ---
m(
    "N61",
    "2A",
    '        raise FileNotFoundError("git no esta en el PATH")',
    '        return 1, ""',
)
m(
    "N69",
    "2A",
    "        if p.exists():\n            found += _git_markers(p)",
    "        if True:\n            found += _git_markers(p)",
)
EQUIV["N69"] = (
    "rev-parse de una ruta ausente falla (rc 128) y _git_markers devuelve [] igual: la guarda p.exists() es redundante"
)
m(
    "N70",
    "2A",
    '    rc, gitdir = _git(p, "rev-parse", "--absolute-git-dir")\n    if rc != 0:\n        return [',
    '    rc, gitdir = _git(p, "rev-parse", "--absolute-git-dir")\n    if False:\n        return [',
)
m(
    "N71",
    "2A",
    'GIT_MARKERS = ("index.lock", "MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD")',
    'GIT_MARKERS = ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD")',
)
m(
    "X5",
    "2A",
    'GIT_MARKERS = ("index.lock", "MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD")',
    'GIT_MARKERS = ("index.lock", "REBASE_HEAD", "CHERRY_PICK_HEAD")',
)
m(
    "N72",
    "2A",
    'GIT_MARKERS = ("index.lock", "MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD")',
    'GIT_MARKERS = ("index.lock", "MERGE_HEAD", "CHERRY_PICK_HEAD")',
)
m(
    "N73",
    "2A",
    'GIT_MARKERS = ("index.lock", "MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD")',
    'GIT_MARKERS = ("index.lock", "MERGE_HEAD", "REBASE_HEAD")',
)
m("N74", "2A", "if rc == 0 else -1", "if rc == 0 else 0")
m(
    "X4",
    "2A",
    '    if n > 0 and st["motor_sucio"] >= 2:',
    '    if n > 0 and st["motor_sucio"] >= 1:',
)
m(
    "N75",
    "2A",
    'st["motor_sucio"] = (previo + 1) if n > 0 else 0',
    'st["motor_sucio"] = (previo + 1) if n > 0 else previo',
)
m(
    "N76",
    "2A",
    '"status", "--porcelain", "--untracked-files=no"',
    '"status", "--porcelain"',
)
m(
    "Q2g1",
    "2A",
    '    if n < 0:\n        out["ciego_git"] = True\n        found.append(',
    '    if n < 0:\n        out["ciego_git"] = True\n        [].append(',
)
m(
    "Q2g2",
    "2A",
    '    if n < 0:\n        out["ciego_git"] = True',
    "    if n < 0:\n        pass",
)
m("D1b", "2A", "        if key not in seen:", "        if True:")
m("D1c", "2A", "glob.escape(str(motor.parent))", "str(motor.parent)")
m(
    "D1d",
    "2A",
    '    if CFG.motor is None:\n        out["ciego_git"] = True\n        return []',
    '    if False:\n        out["ciego_git"] = True\n        return []',
)
m("D1e", "2A", '        "git-": out.get("ciego_git"),', '        "git-": None,')
# --- cupo, cola, disco, hook (filas 82-92, 103, 104) ---
m(
    "N62",
    "2A",
    '        out["ciego_cupo"] = True\n        return [\n            (\n                "cupo-no-medido",',
    '        return [\n            (\n                "cupo-no-medido",',
)
m(
    "X3a",
    "2A",
    "    if age_min > QUOTA_STALE_MIN:\n        razones.append(",
    "    if age_min > 4000:\n        razones.append(",
)
m(
    "X3b",
    "2A",
    '    if razones or ilegible:\n        out["ciego_cupo"] = True',
    '    if ilegible:\n        out["ciego_cupo"] = True',
)
m(
    "Q3a",
    "2A",
    "    if age_min > QUOTA_STALE_MIN:\n        razones.append(",
    "    if False:\n        razones.append(",
)
m(
    "M18",
    "2A",
    "    ilegible = (not pcts or sin_pct) and not declara",
    "    ilegible = sin_pct and not declara",
)
m(
    "X2",
    "2A",
    '                "cupo-97",\n                "URGENTE",',
    '                "cupo-97",\n                "AVISO",',
)
m("N63", "2A", "    if worst >= 92:", "    if worst >= 99:")
m("Q3b", "2A", "    if worst >= 97:", "    if worst >= 99:")
m(
    "N64",
    "2A",
    '        m = re.match(r"\\s*(?:alvarovans|brabander)(?=\\s)(.*)", segment)',
    '        m = re.match(r"\\s*alvarovans(?=\\s)(.*)", segment)',
)
m(
    "Q3c",
    "2A",
    '        if m is None:\n            desconocida = desconocida or re.search(r"\\S+%", segment) is not None\n            continue',
    '        if m is not None:\n            desconocida = desconocida or re.search(r"\\S+%", segment) is not None\n            continue',
)
m(
    "N65",
    "2A",
    '        out["ciego_cola"] = True\n        return [\n            (\n                "detector-ciego-cola",',
    '        return [\n            (\n                "detector-ciego-cola",',
)
m(
    "Q2c",
    "2A",
    '                "detector-ciego-cola",\n                "AVISO",',
    '                "detector-ciego-cola",\n                "URGENTE",',
)
m(
    "N66",
    "2A",
    'if "ABIERTA" not in line or "RESUELTA" in line:',
    'if "ABIERTA" not in line:',
)
m("X1", "2A", 'nivel = "URGENTE" if "BLOQUEA" in line else "AVISO"', 'nivel = "AVISO"')
m(
    "N67",
    "2A",
    '"cola-" + h,\n                nivel,',
    '"cola-" + str(abiertas),\n                nivel,',
)
m("N68", "2A", "{redact(resumen)[:60]}", "{redact(resumen)}")
m("N68b", "2A", "{redact(resumen)[:60]}", "{redact(resumen[:60])}")
m("N68c", "2A", "{redact(resumen)[:60]}", "{resumen[:60]}")
m(
    "Q4a",
    "2A",
    'read_text(encoding="utf-8-sig", errors="replace").splitlines()',
    'read_text(encoding="utf-8", errors="replace").splitlines()',
)
m("X6", "2A", "    if free_gb < CFG.free_gb_min:", "    if free_gb > CFG.free_gb_min:")
m(
    "Q5a",
    "2A",
    "free_gb = shutil.disk_usage(anchor).free / 1e9",
    "free_gb = shutil.disk_usage(anchor).free / 1e6",
)
m("Q5b", "2A", "shutil.disk_usage(anchor)", 'shutil.disk_usage("/")')
m(
    "X7",
    "2A",
    "    if not guard.exists():\n        return [",
    "    if guard.exists():\n        return [",
)
m("Q6a", "2A", '        "hook-": out.get("ciego_hook"),', '        "hook-": None,')
m(
    "Q6b",
    "2A",
    '        out["ciego_hook"] = True\n        return []',
    "        return []",
)
m("D1f", "2A", '        "cupo-": out.get("ciego_cupo"),', '        "cupo-": None,')
m("D1g", "2A", '        "cola-": out.get("ciego_cola"),', '        "cola-": None,')
# --- self-check, main, run ---
m(
    "N77",
    "2A",
    "    return 0 if not bad else 2\n\n\ndef _is_unc",
    "    return 0\n\n\ndef _is_unc",
)
m(
    "N77b",
    "2A",
    '        if not f.exists():\n            bad.append("falta " + name)',
    "        if not f.exists():\n            pass",
)
m(
    "N77c",
    "2A",
    '                compile(f.read_text(encoding="utf-8-sig"), str(f), "exec")',
    "                pass",
)
m(
    "N77d",
    "2A",
    "    if cfg.cola is not None and not cfg.cola.exists():",
    "    if False:",
)
m(
    "N77e",
    "2A",
    "    if cfg.motor is not None and not cfg.motor.exists():",
    "    if False:",
)
m("N77f", "2A", "    bad += causes\n", "")
m("N84", "2A", "return self_check(a) if a.self_check else run(a)", "return run(a)")
m(
    "N85",
    "2A",
    '    except Exception as exc:\n        print(f"STALL_CHECK_BROKEN: {type(exc).__name__}: {str(exc)[:160]}")\n        return 2',
    '    except ZeroDivisionError as exc:\n        print(f"STALL_CHECK_BROKEN: {type(exc).__name__}: {str(exc)[:160]}")\n        return 2',
)
m(
    "M16",
    "2A",
    "        )\n        rc = 2\n    return rc",
    "        )\n        rc = rc\n    return rc",
)
m(
    "M6",
    "2A",
    "        if r == 2:\n            rc = 2",
    "        if r == 2:\n            rc = rc",
)
m("N78", "2A", "        rc = max(rc, 1)", "        rc = max(rc, 0)")
m(
    "N79",
    "2A",
    "        if a.baseline:\n            ca.mark_seen",
    "        if False:\n            ca.mark_seen",
)
m(
    "X16",
    "2A",
    "            ca.mark_seen(key, level, owner, a.dry_run)",
    "            pass",
)
m(
    "N80",
    "2A",
    "    if not a.dry_run and not a.baseline and not broke:",
    "    if not a.dry_run and not a.baseline:",
)
m(
    "N80b",
    "2A",
    "    if not a.dry_run and not a.baseline and not broke:",
    "    if not a.baseline and not broke:",
)
m(
    "N80c",
    "2A",
    "    if not a.dry_run and not a.baseline and not broke:",
    "    if not a.dry_run and not broke:",
)
m(
    "M7",
    "2A",
    '    cleared = ca.reconcile(prefixes, {k for k, _, _ in found}, a.dry_run, owner="stall")',
    "    cleared = []",
)
m(
    "M15",
    "2A",
    "    prefixes = tuple(p for p in OWNED_PREFIXES if not blind.get(p))",
    "    prefixes = OWNED_PREFIXES",
)
m("Q7a", "2A", 'found}, a.dry_run, owner="stall")', "found}, a.dry_run, owner=None)")
m(
    "Q7b",
    "2A",
    "            owner=owner,\n            session_code=session_code,",
    '            owner="manual",\n            session_code=session_code,',
)
m("Q7c", "2A", "        r = ca.event(\n", "        r = ca.resolve(\n")
# --- tarea (D25) ---
m(
    "N83",
    "2A",
    "    if not os.path.lexists(CFG.ops / TASK_REGISTERED_NAME):\n        return []",
    "    if False:\n        return []",
)
m(
    "N83b",
    "2A",
    "    if not os.path.lexists(CFG.ops / TASK_REGISTERED_NAME):",
    "    if not (CFG.ops / TASK_REGISTERED_NAME).exists():",
)
EQUIV["N83b"] = (
    "una marca que es un symlink roto: .exists() y lexists difieren, pero la prueba de marca como directorio no lo distingue (ver Q6 del informe: la marca como symlink roto queda sin prueba en Windows sin permiso de symlink)"
)
m("T1", "2A", "TASK_STALE_S = 25 * 60", "TASK_STALE_S = 2500 * 60")
m("T2", "2A", "TASK_FUTURE_S = 5 * 60", "TASK_FUTURE_S = 500 * 60")
m(
    "T3",
    "2A",
    "ts <= now + TASK_FUTURE_S and now - ts <= TASK_STALE_S",
    "now - ts <= TASK_STALE_S",
)
m(
    "T4",
    "2A",
    "    if _is_finite(ts) and ts <= now + TASK_FUTURE_S and",
    "    if ts is not None and ts <= now + TASK_FUTURE_S and",
)
m(
    "T5",
    "2A",
    "    if not (isinstance(value, (int, float)) and not isinstance(value, bool)):",
    "    if not isinstance(value, (int, float)):",
)
m(
    "T6",
    "2A",
    "        return math.isfinite(value)\n    except OverflowError:",
    "        return True\n    except OverflowError:",
)
m("N87", "2A", '        ca.resolve("tarea-muerta", a.dry_run)', "        pass")
m(
    "T7",
    "2A",
    '    if "tarea-muerta" not in {k for k, _, _ in found} and (',
    "    if False and (",
)
# --- configuracion (D1, D2) ---
m(
    "P1",
    "2A",
    "FREE_GB_DEFAULT = 5.0",
    'FREE_GB_DEFAULT = 5.0\n_X = "C:/Users/fdl/tmp_or8"',
)
m(
    "P2",
    "2A",
    "    raw = a.flight_dir or env.get(FLIGHT_DIR_ENV)",
    "    raw = a.flight_dir or env.get(FLIGHT_DIR_ENV) or str(Path.cwd())",
)
m("P3", "2A", "    elif motor.is_absolute():", "    elif True:")
m("P4", "2A", "    elif raw and not Path(raw).is_absolute():", "    elif False:")
m(
    "P5",
    "2A",
    "    if not cand.is_absolute():\n        raise ValueError(",
    "    if False:\n        raise ValueError(",
)
m("P6", "2A", "    if not real.is_dir():", "    if False:")
m("P7", "2A", "real = cand.resolve(strict=True)", "real = cand.resolve()")
EQUIV["P7"] = (
    "sin strict, una ruta ausente se normaliza igual y la guarda is_dir() la rechaza con la misma causa visible (no cambia ningun resultado)"
)
m("P8", "2A", 'cand.drive.startswith("\\\\\\\\")', 'cand.drive.startswith("\\\\\\\\x")')
m("U1", "2A", "    if _is_unc(motor):\n", "    if False:\n")
m(
    "P9",
    "2A",
    "    if not math.isfinite(value) or value < 0:",
    "    if not math.isfinite(value):",
)
m("P10", "2A", "    if not math.isfinite(value) or value < 0:", "    if value < 0:")
m("P11", "2A", "        value = math.nan", "        value = 0.0")
m(
    "P12",
    "2A",
    '    raw = a.quota_file or env.get("STALL_QUOTA_FILE")',
    "    raw = a.quota_file",
)
m(
    "P13",
    "2A",
    '    raw = a.motor_wt or env.get("STALL_MOTOR_WT")',
    "    raw = a.motor_wt",
)
m(
    "P14",
    "2A",
    "    raw = a.flight_dir or env.get(FLIGHT_DIR_ENV)",
    "    raw = env.get(FLIGHT_DIR_ENV) or a.flight_dir",
)
m(
    "P15",
    "2A",
    "        cfg.quota = ops / QUOTA_NAME",
    "        cfg.quota = ops / 'otro.txt'",
)
m(
    "P16",
    "2A",
    "motor = Path(raw) if raw else Path(__file__).resolve().parents[2]",
    "motor = Path(raw) if raw else Path(__file__).resolve().parents[1]",
)
m(
    "P17", "2A", "            if causes:\n", "            if causes:\n"
) if False else None
m(
    "SC1",
    "2A",
    '                "Detector sin configurar: " + "; ".join(c[:80] for c in causes),',
    '                "Detector sin configurar: ",',
)
m(
    "SC2",
    "2A",
    '                "detector-sin-config",\n                "AVISO",',
    '                "detector-sin-config",\n                "URGENTE",',
)
m(
    "SC3",
    "2A",
    '    if fatal:\n        print(f"STALL_CHECK_BROKEN: {fatal}")\n        return 2',
    '    if False:\n        print(f"STALL_CHECK_BROKEN: {fatal}")\n        return 2',
)
m(
    "SC4",
    "2A",
    '        print(f"STALL_CHECK_BROKEN: ops-dir: {str(exc)[:160]}")\n        return 2',
    '        print(f"STALL_CHECK_BROKEN: ops-dir: {str(exc)[:160]}")\n        pass',
)


# ---------------- caja 2B: quota_tick.py (filas 122-129 del Anexo B y formas nuevas Q-O1..Q-O6) ----------------
def q(mid, pattern, repl):
    m(mid, "2B", pattern, repl, target=QUOTA)


q(
    "N88",
    '        raise NoMedidoError(f"monitor: {type(exc).__name__} {str(exc)[:80]}") from exc',
    '        return {"a": {"block_pct": 0, "stale": False}}',
)
q("N89", "        if not ok or stale:", "        if not ok:")
q("N90", "    if worst >= hard:", "    if worst >= 99:")
q("N91", 'return "AVISO" if worst >= WARN_PCT else "OK"', 'return "AVISO"')
q("N92", "        value = quota.get(key, default)", "        value = default")
q(
    "N93",
    '        return f"codex NO_MEDIDO {type(exc).__name__}"',
    '        raise NoMedidoError("codex")',
)
q(
    "N94",
    '    except (OSError, ValueError, RecursionError) as exc:\n        raise NoMedidoError(f"roster:',
    '    except (ValueError, RecursionError) as exc:\n        raise NoMedidoError(f"roster:',
)
q("N95", 'if __name__ == "__main__":\n    sys.exit(main())', "sys.exit(main())")
q(
    "Q1",
    "        return not math.isnan(value)\n    except OverflowError:",
    "        return True\n    except OverflowError:",
)
q(
    "Q2",
    "    if not (isinstance(value, (int, float)) and not isinstance(value, bool)):",
    "    if not isinstance(value, (int, float)):",
)
q("Q3", "ok = _is_real(pct) and pct != -math.inf", "ok = _is_real(pct)")
q(
    "Q4",
    "if not isinstance(accounts, dict) or not accounts:",
    "if not isinstance(accounts, dict):",
)
q(
    "Q5",
    "    if not all(isinstance(v, dict) for v in accounts.values()):",
    "    if False:",
)
q("Q6", "math.isfinite(value) and value > 0", "math.isfinite(value) and value >= 0")
q(
    "Q7",
    "_is_real(value) and math.isfinite(value) and value > 0",
    "_is_real(value) and value > 0",
)
q("Q8", 'read_text(encoding="utf-8-sig"))', 'read_text(encoding="utf-8"))')
q(
    "Q9",
    "    except (OSError, ValueError, RecursionError) as exc:",
    "    except (OSError, ValueError) as exc:",
)
q("Q10", "    if _is_unc(cand):", "    if False:")
q(
    "Q10b",
    "    if not cand.is_absolute():\n        raise NoMedidoError(",
    "    if False:\n        raise NoMedidoError(",
)
q("Q10c", "    if not cand.is_dir():", "    if False:")
q("Q11", '[str(_powershell()), "-NoProfile"', '["powershell", "-NoProfile"')
q("Q12", "            timeout=90,", "            timeout=900,")
q("Q13", '"-NoProfile", "-File", monitor, "-Json"', '"-File", monitor, "-Json"')
q(
    "Q14",
    '            c.stdout.strip().replace("\\n", " ").replace("|", "/")[:110]',
    '            c.stdout.strip().replace("\\n", " ").replace("|", "/")[:1100]',
)
q("Q15", 'or (Path.home() / ".codex")', 'or "x"')
q("Q16", 'mark = " umbrales-roster-invalidos" if invalid else ""', 'mark = ""')
q(
    "Q17",
    "            out.append(default)\n            invalid = True",
    "            out.append(default)",
)
q("Q18", "{' STALE' if stale else ''}", "''")
q("Q19", '"HARD": 5', '"HARD": 4')
q("Q20", "    if worst >= soft:", "    if worst > soft:")
q(
    "Q21",
    '    if bad:\n        return "NO_MEDIDO"',
    '    if False:\n        return "NO_MEDIDO"',
)
q(
    "Q22",
    "a.flight_dir or env.get(FLIGHT_DIR_ENV)",
    "env.get(FLIGHT_DIR_ENV) or a.flight_dir",
)
q("Q23", "a.monitor or env.get(MONITOR_ENV)", "env.get(MONITOR_ENV) or a.monitor")
q("Q24", "a.probe or env.get(PROBE_ENV)", "env.get(PROBE_ENV) or a.probe")
q("Q25", 'return f"codex NO_MEDIDO sin {PROBE_ENV}"', 'return ""')
q("Q26", "    except NoMedidoError:\n        raise\n", "")
q(
    "Q27",
    '        print(f"QUOTA NO_MEDIDO interno',
    '        print(f"QUOTA otro interno',
)
q("Q28", "                min(", "                min(") if False else None
q("Q29", '        raise NoMedidoError("monitor: SystemRoot ausente")', "        pass")
q(
    "Q30",
    '            check=False,\n        )\n        accounts = json.loads(r.stdout)["accounts"]',
    '            check=False,\n        )\n        accounts = json.loads(r.stdout)["accounts"]',
) if False else None
# ---- ronda 1 (adjudicacion 153j): A1..A7 ----
m(
    "A1a",
    "2A",
    're.fullmatch(r"([-+]?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)%", toks[-1])',
    're.fullmatch(r"([-+]?\\d+(?:[eE][-+]?\\d+)?)%", toks[-1])',
)
m(
    "A1b",
    "2A",
    "pcts.append(int(value) if value.is_integer() else value)",
    "pcts.append(int(value))",
)
m(
    "A2a",
    "2A",
    "    ilegible = (not pcts or sin_pct) and not declara",
    "    ilegible = not pcts and not declara",
)
m(
    "A2b",
    "2A",
    "    elif stale:\n        razones.append(",
    "    elif False:\n        razones.append(",
)
m(
    "A2c",
    "2A",
    "    if declara_no_medido:\n        razones.append(",
    "    if False:\n        razones.append(",
)
m(
    "A2d",
    "2A",
    'stale = stale or re.search(r"\\bSTALE\\b", rest) is not None',
    "stale = False",
)
m(
    "A2e",
    "2A",
    "value = float(num.group(1)) if num else math.inf",
    "value = float(num.group(1)) if num else 0.0",
)
m(
    "A2f",
    "2A",
    "    ilegible = (not pcts or sin_pct) and not declara",
    "    ilegible = (not pcts or sin_pct)",
)
m(
    "A2g",
    "2A",
    'declara = re.search(r"\\bNO_MEDIDO\\b", text.split("|", 1)[0]) is not None',
    "declara = False",
)
q("A3a", "        if r.returncode != 0:", "        if False:")
q("A3b", "        if r.returncode != 0:", "        if r.returncode > 2:")
m("A4", "2A", '"cola-": out.get("ciego_cola"),', '"cola-": True,')
m(
    "A5a",
    "2A",
    "    try:\n        return self_check(a) if a.self_check else run(a)\n",
    "    if a.self_check:\n        return self_check(a)\n    try:\n        return run(a)\n",
)
m(
    "A5b",
    "2A",
    "    if fatal:\n        bad.append(fatal)",
    "    if False:\n        bad.append(fatal)",
)
m(
    "A6a",
    "2A",
    "    if free_gb < CFG.free_gb_min:",
    "    if free_gb <= CFG.free_gb_min:",
)
m("A6b", "2A", "FREE_GB_DEFAULT = 5.0", "FREE_GB_DEFAULT = 9.0")
m("A7a", "2A", "    if raw and _is_unc(Path(raw)):", "    if False:")
m("A7b", "2A", 'r"\\\\\\\\\\?\\\\[A-Za-z]:", cand.drive', 'r"NOPE", cand.drive')
m(
    "A7c",
    "2A",
    'return cand.drive.startswith("\\\\\\\\") and not re.fullmatch(',
    'return cand.drive.startswith("\\\\\\\\") and not cand.drive.startswith("\\\\\\\\?\\\\") and not re.fullmatch(',
)
q("A7d", 'r"\\\\\\\\\\?\\\\[A-Za-z]:", cand.drive', 'r"NOPE", cand.drive')
q(
    "A7e",
    'return cand.drive.startswith("\\\\\\\\") and not re.fullmatch(',
    'return cand.drive.startswith("\\\\\\\\") and not cand.drive.startswith("\\\\\\\\?\\\\") and not re.fullmatch(',
)
# ---- ronda 2: A8 (token numerico completo) ----
m(
    "A8a",
    "2A",
    're.fullmatch(r"([-+]?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)%", toks[-1])',
    're.fullmatch(r"(\\d+(?:\\.\\d+)?)%", toks[-1])',
)
m(
    "A8b",
    "2A",
    're.fullmatch(r"([-+]?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)%", toks[-1])',
    're.fullmatch(r"([-+]?\\d+(?:\\.\\d+)?)%", toks[-1])',
)
m(
    "A8c",
    "2A",
    're.fullmatch(r"([-+]?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)%", toks[-1])',
    're.fullmatch(r"(\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)%", toks[-1])',
)
m(
    "A8d",
    "2A",
    're.fullmatch(r"([-+]?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)%", toks[-1])',
    're.fullmatch(r"([-+]?\\d+(?:\\.\\d+)?(?:[e][-+]?\\d+)?)%", toks[-1])',
)
m(
    "A8e",
    "2A",
    're.fullmatch(r"([-+]?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)%", toks[-1])',
    're.fullmatch(r"([-+]?\\d+(?:\\.\\d+)?(?:[eE]\\d+)?)%", toks[-1])',
)
# ---- ronda 3: A9 (el pct es el ULTIMO token % del segmento) ----
m("A9a", "2A", "toks[-1])", "toks[0])")
m("A9c", "2A", 're.findall(r"\\S+%", rest)', 're.findall(r"[\\d.eE+-]+%", rest)')
m("A9d", "2A", "if toks\n", "if False\n")


def die(msg):
    print("ARNES-ABORTA: " + msg, flush=True)
    return 1


def _selected(box, ids):
    """Selecciona mutaciones activas sin incluir retiradas.

    Before: ``box`` es una caja válida y ``ids`` una lista separada por comas.
    During: filtra ``MUT`` por caja e identificador, preservando el orden versionado.
    After: devuelve la tabla seleccionada; una tabla vacía se deja visible para abortar.
    """
    wanted = {item for item in ids.split(",") if item}
    return [
        item
        for item in MUT
        if item[0] not in RETIRED
        and box in ("all", item[1])
        and (not wanted or item[0] in wanted)
    ]


def validate(repo, mutations):
    """Valida cardinalidad, cambio y compilación de mutaciones.

    Before: ``repo`` contiene los dos módulos objetivo y ``mutations`` es una tabla iterable.
    During: lee cada objetivo, detecta ids repetidos, exige una coincidencia y compila Python.
    After: devuelve todos los errores encontrados sin ejecutar pytest ni abortar por el primero.
    """
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


def _default_executor(repo, env, tests, timeout=900):
    """Ejecuta la focal y devuelve su rc sin reinterpretarlo."""
    command = [
        sys.executable,
        "-X",
        "utf8",
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
        completed = subprocess.run(  # noqa: S603 - focal controlada por el arnés
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


def run_mutation(repo, mutation, tests=None, executor=None):
    """Ejecuta una mutación contra el árbol completo de una copia temporal.

    Before: ``repo`` contiene ambos objetivos y ``mutation`` es una entrada validada.
    During: copia todo ``scripts/flight``, elige por objetivo la focal canónica cuando
        no hay ``--tests``, aplica la mutación solo con patrón no nulo y llama al ejecutor.
    After: devuelve id, caja, rc, diagnóstico y duración; control conserva el original
        byte a byte y la copia se elimina incluso si el ejecutor lanza una excepción.
    """
    mid, box, fn, pattern, replacement = mutation
    src_dir = pathlib.Path(repo).resolve() / "scripts" / "flight"
    execute = executor or _default_executor
    tests = tests or [TESTS_BY_TARGET[fn]]
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="mutate_detectors_") as tmp_name:
        tmp = pathlib.Path(tmp_name)
        shutil.copytree(src_dir, tmp, dirs_exist_ok=True)
        original = (src_dir / fn).read_text(encoding="utf-8")
        if pattern is not None:
            (tmp / fn).write_text(
                original.replace(pattern, replacement), encoding="utf-8", newline="\n"
            )
        env = dict(
            os.environ,
            STALL_CHECK_UNDER_TEST=str(tmp / STALL),
            QUOTA_TICK_UNDER_TEST=str(tmp / QUOTA),
            MUTATION_COPY_ROOT=str(tmp),
        )
        rc, why = execute(repo, env, tests)
    return mid, box, rc, why, time.time() - started


def _classify_rc(rc):
    """Clasifica resultados del ejecutor: solo rc 1 es muerte."""
    return {0: "SURVIVE", 1: "KILLED", 99: "TIMEOUT"}.get(rc, "ERROR")


def main(argv=None, executor=None):  # noqa: C901 - CLI y adjudicación serial
    """Valida y ejecuta mutaciones serialmente con ejecutor inyectable."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--box", default="all")
    ap.add_argument("--ids", default="")
    ap.add_argument(
        "--workers", type=int, default=1, help="aceptado; ejecución serial, se ignora"
    )
    ap.add_argument("--tests")
    ap.add_argument("--inject-bad-pattern", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--control", action="store_true")
    a = ap.parse_args(argv)
    repo = pathlib.Path(a.repo).resolve()
    mutations = _selected(a.box, a.ids)
    if a.inject_bad_pattern:
        mutations.insert(
            0, ("BAD", a.box, STALL, "ESTE PATRON NO EXISTE EN EL CODIGO", "x")
        )
    if not mutations:
        print("ARNES-ABORTA: tabla de patrones vacia", flush=True)
        return 1
    errors = validate(repo, mutations)
    if errors:
        for error in errors:
            print("ARNES-ABORTA: " + error, flush=True)
        return 1
    print(
        f"patrones validados: {len(mutations)} (cada uno casa 1 vez, compila y difiere)",
        flush=True,
    )
    if a.validate_only:
        return 0
    tests = [item for item in a.tests.split(",") if item] if a.tests else None
    if a.control:
        mutations = [("CONTROL", "-", STALL, None, None)]
    killed, survivors, timeouts, errors = 0, [], [], []
    for mutation in mutations:
        mid, box, rc, why, elapsed = run_mutation(
            repo, mutation, tests, executor=executor
        )
        label = "CONTROL" if a.control else _classify_rc(rc)
        if a.control:
            print(f"CONTROL rc={rc} {elapsed:.1f}s {why}", flush=True)
            return 0 if rc == 0 else 1
        if rc == 99:
            timeouts.append(mid)
            print(f"{label} {mid} {box} {elapsed:.1f}s {why[:110]}", flush=True)
        elif label == "KILLED":
            killed += 1
            print(f"{label} {mid} {box} {elapsed:.1f}s {why[:110]}", flush=True)
        elif label == "SURVIVE":
            if mid in EQUIV:
                print(f"EQUIVALENTE {mid} {box} {elapsed:.1f}s {why[:110]}", flush=True)
            else:
                survivors.append(mid)
                print(f"SURVIVE {mid} {box} {elapsed:.1f}s {why[:110]}", flush=True)
        else:
            errors.append((mid, rc))
            print(f"{label} {mid} {box} {elapsed:.1f}s {why[:110]}", flush=True)
    print(
        f"RESUMEN: matadas {killed}/{len(mutations)}; timeouts: {timeouts or 'ninguno'}; "
        f"errores: {errors or 'ninguno'}; supervivientes: {survivors or 'ninguno'}"
    )
    if errors:
        return 1
    return 1 if survivors or timeouts else 0


def _legacy_run_one(args):
    """Ejecuta una mutación aislada con limpieza garantizada.

    Before: ``args`` contiene una mutación validada, la raíz del repositorio y su focal.
    During: copia los módulos ejecutables a un directorio temporal, inyecta sus rutas por
        entorno y ejecuta pytest serialmente con ``-x`` y un timeout de 900 segundos.
    After: devuelve identificador, rc, diagnóstico y duración; el directorio temporal se
        elimina también si pytest lanza una excepción o agota el timeout.
    """
    mid, box, fn, pat, rep, repo, tests, src_dir = args
    tests = [TESTS_BY_TARGET[fn]] if fn in TESTS_BY_TARGET else tests
    orig = (src_dir / fn).read_text(encoding="utf-8")
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="mutate_detectors_legacy_") as tmp_name:
        tmp = pathlib.Path(tmp_name)
        for f in src_dir.iterdir():
            if f.suffix in (".py", ".ps1"):
                (tmp / f.name).write_text(
                    f.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
                )
        (tmp / fn).write_text(
            orig.replace(pat, rep) if pat is not None else orig,
            encoding="utf-8",
            newline="\n",
        )
        env = dict(
            os.environ,
            STALL_CHECK_UNDER_TEST=str(tmp / STALL),
            QUOTA_TICK_UNDER_TEST=str(tmp / QUOTA),
        )
        try:
            r = subprocess.run(  # noqa: S603 - ejecuta la focal solicitada por el arnés
                [
                    sys.executable,
                    "-X",
                    "utf8",
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
                ],
                cwd=str(repo),
                env=env,
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            out = (r.stdout or "") + (r.stderr or "")
            rc = r.returncode
            why = next(
                (x for x in out.splitlines() if x.startswith(("FAILED", "ERROR"))),
                out.strip().splitlines()[-1] if out.strip() else "",
            )
        except subprocess.TimeoutExpired:
            rc, why = 99, "CRASH-TIMEOUT"
    return mid, box, rc, why, time.time() - t0


def _legacy_main():  # noqa: C901 - retained only as historical implementation
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--box", default="all")
    ap.add_argument("--ids", default="")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--tests", default="tests/unit/test_flight_stall_check.py")
    ap.add_argument("--inject-bad-pattern", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument(
        "--control",
        action="store_true",
        help="corre la suite SIN mutar (debe dar rc 0)",
    )
    a = ap.parse_args()
    repo = pathlib.Path(a.repo).resolve()
    src_dir = repo / "scripts" / "flight"
    want = [x for x in a.ids.split(",") if x]
    muts = [
        x
        for x in MUT
        if x is not None and (a.box in ("all", x[1])) and (not want or x[0] in want)
    ]
    if a.inject_bad_pattern:
        muts = [("BAD", a.box, STALL, "ESTE PATRON NO EXISTE EN EL CODIGO", "x"), *muts]
    seen_legacy = set()
    for mid, _box, fn, pat, rep in muts:
        if mid in seen_legacy:
            die("id duplicado " + mid)
        seen_legacy.add(mid)
        orig = (src_dir / fn).read_text(encoding="utf-8")
        n = orig.count(pat)
        if n != 1:
            die(f"{mid}: el patron casa {n} veces (debe ser 1)")
        new = orig.replace(pat, rep)
        if new == orig:
            die(mid + ": la mutacion no difiere del original")
        try:
            compile(new, fn, "exec")
        except SyntaxError as exc:
            die(f"{mid}: el codigo mutado no compila ({exc})")
    print(
        f"patrones validados: {len(muts)} (cada uno casa 1 vez, compila y difiere)",
        flush=True,
    )
    if a.validate_only:
        sys.exit(0)
    jobs = [
        (mid, box, fn, pat, rep, repo, a.tests.split(","), src_dir)
        for mid, box, fn, pat, rep in muts
    ]
    if a.control:
        jobs = [("CONTROL", "-", STALL, None, None, repo, a.tests.split(","), src_dir)]
    killed, survivors, equiv_surv = 0, [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for mid, box, rc, why, dt in ex.map(_legacy_run_one, jobs):
            ok = (
                rc != 0 and rc != 99
            )  # un timeout NO es una muerte: queda como no adjudicado
            if a.control:
                print(f"CONTROL rc={rc} {dt:.1f}s {why}", flush=True)
                sys.exit(0 if rc == 0 else 1)
            if ok:
                killed += 1
            elif mid in EQUIV:
                equiv_surv.append(mid)
            else:
                survivors.append(mid)
            tag = "KILLED" if ok else ("EQUIVALENTE" if mid in EQUIV else "SOBREVIVE")
            print(f"{tag:<11} {mid:<5} {box:<4} {dt:.1f}s {why[:110]}", flush=True)
    total = len(muts)
    print(
        f"RESUMEN: matadas {killed}/{total}; equivalentes declarados "
        f"{equiv_surv or 'ninguno'}; supervivientes: {survivors or 'ninguno'}"
    )
    sys.exit(1 if survivors else 0)


RETIRED = {}
REANCHORED = {
    "E7": "153j vigente: limpieza atomica del estado",
    "N70": "153j vigente: diagnostico de gitdir no resoluble",
    "N64": "153j vigente: parseo de cuentas del cupo",
    "Q3c": "153j vigente: nombres de cuentas del cupo",
    "X16": "153j vigente: marca de eventos del tick",
    "Q7b": "153j vigente: owner stall del evento",
    "Q7c": "153j vigente: dry-run del evento",
    "T5": "159a: _is_finite valida no booleanos",
    "T6": "159a: _is_finite valida finitud",
    "Q1": "159a: _is_real rechaza NaN",
    "Q2": "159a: _is_real rechaza bool",
    "Q14": "153j vigente: salida de sonda acotada",
}

if __name__ == "__main__":
    raise SystemExit(main())
