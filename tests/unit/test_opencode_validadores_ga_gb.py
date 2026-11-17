# ruff: noqa: S608, UP031
import ast
import builtins

# ============================================================
# AUTOPRUEBA v6 (184d v6) - TR69 / WOT-2026-184d
# Ronda 5 (CO-110, BA253): 1 MAYOR + 2 MENOR. Igual que v4/v5,
# EXTRAE los dos bloques ```python LITERALES de la ficha y los EJECUTA
# con exec tal cual (ciclo real conexion/cierre). Nuevos en v6:
#   MAYOR: el origen de los literales del NODO queda fijado en el
#     contrato (ficha sec. 6): el nodo INCRUSTA los bloques byte a
#     byte y afirma su sha256 contra los hashes PUBLICADOS en la
#     ficha; este driver VERIFICA esa cadena en cada ejecucion
#     (sha256(bloque extraido) == publicado).
#   MENOR-2: 51 casos = 23 GA + 20 GB + 8 CLS (se anyaden
#     GA_VENTANA_VACIA rc 3 y GB_IDENTIDAD_NULA rc 2, que CASOS
#     EXIGIDOS ya pedia).
#   MENOR-3: FICHA y CONFIG son argumentos OBLIGATORIOS (G2 fija el
#     comando literal con rutas explicitas; CONFIG = la raiz
#     implantada por 184c en el motor, scripts/flight/nieto_root/...
#     opencode.json). Sin rutas relativas magicas.
# Intercepciones DECLARADAS: sqlite3 URI->fixture ro; sys argv/exit;
# fabrica set() sin argumentos armada solo en los 6 casos con texto.
# ============================================================
import hashlib
import json
import os
import sqlite3
import tempfile
import traceback
import types


HERE = os.path.dirname(os.path.abspath(__file__))
# FICHA y CONFIG se fijan en main() desde argv (G2 del brief fija el
# comando literal); sin rutas relativas magicas.
CONFIG = None

T = "Permission denied by policy"
MIXED_OUT = (
    "Permission denied earlier; access granted now; operation executed successfully"
)
T_MAS_APROBADO = T + "; access approved now"
BA254_R2_PHRASE = "Permission denied earlier; access approved now; command succeeded"

WIN = ("2026-11-01", "2026-12-01")
LAUNCHER = "mcp:09de2400-1111-2222-3333-444455556666"
CO109_LITERAL = "mcp:3f2d1e4f-8d82-4b34-bbbc-ac5870414e07"


BLOCK_GA_SHA256 = "327a974d0035b0b3858dac7f3f822655dada711aad5f7996584e853760fa7a95"
BLOCK_GB_SHA256 = "72eef092bb013ef79380acba00354195d3b9bd1d58312cc6b4aa4081f8b0ec40"
GA_SRC = (
    'import json, sqlite3, sys\nfrom fnmatch import fnmatch\nconfig_path, abuela = sys.argv[1], sys.argv[2]\ndecl = json.load(open(sys.argv[3], encoding="utf-8"))\nini, fin = sys.argv[4], sys.argv[5]\nitems_ini, items_fin = sys.argv[6], sys.argv[7]\nALIAS = {"edit": "edit", "write": "edit", "apply_patch": "edit",\n         "list_mcp_resources": "read", "list_mcp_resource_templates": "read",\n         "read_mcp_resource": "read"}\nTOOL_TYPES = {"dynamic_tool", "tool_call"}\nCMD_TYPES = {"command_execution"}\ndef permiso_de(tool):\n    if tool == "bash":\n        return "bash"\n    return ALIAS.get(tool, tool)\ndef _cmd_of(inp):\n    if isinstance(inp, str):\n        return inp\n    if isinstance(inp, dict):\n        return inp.get("command")\n    return None\ndef _agent_values(inp_json):\n    if not inp_json:\n        return []\n    try:\n        d = json.loads(inp_json)\n    except Exception:\n        return []\n    if not isinstance(d, dict):\n        return []\n    tgt = d.get("target")\n    opts = tgt.get("options") if isinstance(tgt, dict) else None\n    vals = []\n    if isinstance(opts, list):\n        for o in opts:\n            if isinstance(o, dict) and o.get("id") == "agent" and o.get("value") is not None:\n                vals.append(o.get("value"))\n    return vals\ncfg = json.load(open(config_path, encoding="utf-8-sig"))\nperm = cfg.get("agent", {}).get("nieto", {}).get("permission", {})\nrules = []\nfor k, v in perm.items():\n    if isinstance(v, dict):\n        for sub, act in v.items():\n            rules.append(("bash", sub, act))\n    else:\n        rules.append((k, "*", v))\ndef find_last(name, cmd=None):\n    last = {"action": "ask"}\n    for p, pat, act in rules:\n        if fnmatch(name, p) and (cmd is None or fnmatch(cmd, pat)):\n            last = {"action": act}\n    return last\nlanz = decl.get("lanzamientos") if isinstance(decl, dict) else None\nif not isinstance(lanz, list) or len(lanz) != 2:\n    print("declaraciones=", 0 if lanz is None else len(lanz), "ERROR=declaraciones_deben_ser_exactamente_2")\n    sys.exit(2)\nids = [l.get("threadId") for l in lanz]\ncrids = [l.get("clientRequestId") for l in lanz]\nif any(not x for x in ids) or any(not x for x in crids):\n    print("declaraciones=2 ERROR=campos_vacios")\n    sys.exit(2)\nif len(set(ids)) != 2 or len(set(crids)) != 2:\n    print("declaraciones=2 ERROR=lanzamientos_no_distintos")\n    sys.exit(2)\nif abuela in ids:\n    print("declaraciones=2 ERROR=la_abuela_no_puede_ser_lanzamiento")\n    sys.exit(2)\ncon = sqlite3.connect("file:C:/Users/fdl/.t3/userdata/statev2.sqlite'
    + chr(63)
    + "mode=ro\", uri=True)\ncur = con.cursor()\nrows = cur.execute(\n    \"SELECT thread_id, json_extract(payload_json,'$.lineage.parentThreadId'), \"\n    \"json_extract(payload_json,'$.lineage.relationshipToParent'), json_extract(payload_json,'$.createdBy') \"\n    \"FROM orchestration_v2_projection_threads WHERE created_at>="
    + chr(63)
    + " AND created_at<="
    + chr(63)
    + '",\n    (ini, fin),\n).fetchall()\nif not rows:\n    print("hilos_del_store= 0 lanzamientos_declarados= 2 ERROR=ventana_vacia")\n    sys.exit(3)\ndeclared = set(ids)\nseen = set()\nextras = 0\norphans = 0\nbad = 0\nviolaciones = []\nfor tid, parent, rel, created in rows:\n    if tid in declared:\n        seen.add(tid)\n        if parent != abuela or rel != "subagent":\n            bad += 1\n    else:\n        extras += 1\n        if created == "agent" and parent is None:\n            orphans += 1\n    for it in cur.execute(\n        "SELECT json_extract(payload_json,\'$.toolName\'), json_extract(payload_json,\'$.input\'), type "\n        "FROM orchestration_v2_projection_turn_items "\n        "WHERE thread_id='
    + chr(63)
    + " AND updated_at>="
    + chr(63)
    + " AND updated_at<="
    + chr(63)
    + '",\n        (tid, items_ini, items_fin),\n    ).fetchall():\n        tool, inp, typ = it\n        if typ in TOOL_TYPES:\n            if not tool:\n                violaciones.append((tid[:40], "toolName_ausente:" + str(typ)))\n                continue\n            res = find_last(permiso_de(tool), cmd=(_cmd_of(inp) if tool == "bash" else None))\n        elif typ in CMD_TYPES:\n            res = find_last("bash", cmd=_cmd_of(inp))\n            tool = "bash"\n        else:\n            continue\n        if res.get("action") != "allow":\n            violaciones.append((tid[:40], tool))\nmissing = sorted(declared - seen)\nabuela_items = cur.execute(\n    "SELECT json_extract(payload_json,\'$.toolName\'), json_extract(payload_json,\'$.input\') FROM orchestration_v2_projection_turn_items "\n    "WHERE thread_id='
    + chr(63)
    + ' AND type IN (\'dynamic_tool\',\'tool_call\')",\n    (abuela,),\n).fetchall()\nagent_ok = 0\nagent_noreg = 0\nagent_viol = []\nfor l in lanz:\n    crid = l.get("clientRequestId")\n    vals = []\n    n_hits = 0\n    for tool_rec, inp_json in abuela_items:\n        if not tool_rec or not inp_json:\n            continue\n        if "delegate_task" not in tool_rec and "thread_launch" not in tool_rec:\n            continue\n        try:\n            d = json.loads(inp_json)\n        except Exception:\n            continue\n        if not isinstance(d, dict) or d.get("clientRequestId") != crid:\n            continue\n        n_hits += 1\n        vals.extend(_agent_values(inp_json))\n    if n_hits > 1:\n        agent_viol.append((crid, "coincidencias_multiplas=" + str(n_hits)))\n    elif n_hits == 0 or not vals:\n        agent_noreg += 1\n    elif all(v == "nieto" for v in vals):\n        agent_ok += 1\n    else:\n        agent_viol.append((crid, vals))\ncon.close()\nprint("hilos_del_store=", len(rows), "lanzamientos_declarados=", len(declared),\n      "huerfanos=", orphans, "faltan=", missing, "parentesco_mal=", bad,\n      "extras=", extras, "violaciones_herramienta=", len(violaciones),\n      "detalle_violaciones=", violaciones[:5],\n      "agent_nieto_ok=", agent_ok,\n      "agent_no_registrado=", agent_noreg,\n      "violaciones_agent=", agent_viol)\nok = ((not missing) and orphans == 0 and bad == 0 and extras == 0\n      and not violaciones and not agent_viol)\nsys.exit(0 if ok else 1)\n'
)
GB_SRC = (
    'import json, sqlite3, sys\nfrom fnmatch import fnmatch\nconfig_path = sys.argv[1]\n# Lista cerrada de TEXTOS COMPLETOS de rechazo observados en el store REAL.\n# VACIA en v3: el texto real aun no existe (G-B PENDIENTE). Se rellena en la\n# PRIMERA ejecucion viva con el texto medido y archivado alli; solo ese texto\n# exacto (output completo, tras trim) cuenta como rechazo.\nCLOSED_REJECTION_TEXTS = set()\nNATIVAS = {"skill", "webfetch", "websearch", "todowrite", "task", "read", "grep", "glob", "write", "edit", "bash"}\nCANON_BASH = {"git status", "python -B -m pytest", "ls"}\nTOOL_TYPES = {"dynamic_tool", "tool_call"}\nCMD_TYPES = {"command_execution"}\ndef clasificar(salida, textos):\n    s = (salida or "").strip()\n    if s in textos:\n        return "permiso_denegado"\n    return "no_rechazo"\ncfg = json.load(open(config_path, encoding="utf-8-sig"))\nperm = cfg.get("agent", {}).get("nieto", {}).get("permission", {})\nrules = []\nfor k, v in perm.items():\n    if isinstance(v, dict):\n        for sub, act in v.items():\n            rules.append(("bash", sub, act))\n    else:\n        rules.append((k, "*", v))\nnamed = [p for p, pat, act in rules if act == "deny" and "*" not in p and p not in NATIVAS]\nexpected31 = set(named)\nfor n in named:\n    expected31.add("t3-code_" + n)\n    expected31.add("t3_code_" + n)\nexpected31.add("task")\ncatalogo = json.load(open(sys.argv[2], encoding="utf-8"))\npruebas = catalogo.get("pruebas")\nnielto_mcp = catalogo.get("nielto_mcp")\nbash_hilos = catalogo.get("bash_hilos") or {}\nif not isinstance(pruebas, list) or len(pruebas) != 34 or not nielto_mcp or len(bash_hilos) != 3:\n    print("pruebas=", 0 if not isinstance(pruebas, list) else len(pruebas), "ERROR=catalogo_no_canonico")\n    sys.exit(2)\nids = [p.get("id") for p in pruebas]\nif len(set(ids)) != 34 or any(not x for x in ids):\n    print("ids=ERROR no_unicos_o_vacios")\n    sys.exit(2)\nmcp = [p for p in pruebas if p.get("kind") == "mcp"]\nbash = [p for p in pruebas if p.get("kind") == "bash"]\nif len(mcp) != 31 or len(bash) != 3:\n    print("mcp=", len(mcp), "bash=", len(bash), "ERROR=reparto_canonico")\n    sys.exit(2)\nif set(bash_hilos.keys()) != CANON_BASH:\n    print("bash_comandos_DISTINTOS del canonico:", "faltan=", sorted(CANON_BASH - set(bash_hilos)),\n          "sobran=", sorted(set(bash_hilos) - CANON_BASH))\n    sys.exit(2)\nbinputs = [p.get("input") for p in bash]\nif set(binputs) != CANON_BASH or len(set(binputs)) != 3:\n    print("bash_inputs_DISTINTOS del canonico:", "faltan=", sorted(CANON_BASH - set(binputs)),\n          "sobran=", sorted(set(binputs) - CANON_BASH))\n    sys.exit(2)\nhilos_decl = [nielto_mcp] + list(bash_hilos.values())\nif len(set(hilos_decl)) != 4:\n    print("hilos_no_distintos=", len(set(hilos_decl)), "esperados= 4 (NIETO-MCP + 3 NIETO-BASH distintos)")\n    sys.exit(2)\ngot = [p.get("tool") for p in mcp]\nif set(got) != expected31 or len(set(got)) != 31:\n    print("conjunto_mcp_DISTINTO del_derivado:", "faltan=", sorted(expected31 - set(got)), "sobran=", sorted(set(got) - expected31))\n    sys.exit(2)\nfor p in pruebas:\n    if not p.get("turn_item_id") or not p.get("run"):\n        print("falta_identidad=", p.get("id"))\n        sys.exit(2)\n    if p["kind"] == "mcp":\n        if p.get("hilo") != nielto_mcp or not p.get("tool") or p.get("input") is None:\n            print("mcp_identidad_invalida=", p.get("id"))\n            sys.exit(2)\n    else:\n        if not isinstance(p.get("input"), str) or not p["input"] or bash_hilos.get(p["input"]) != p.get("hilo"):\n            print("bash_hilo_o_input_invalido=", p.get("id"))\n            sys.exit(2)\ntids = [p["turn_item_id"] for p in pruebas]\nruns = [p["run"] for p in pruebas]\nif len(set(tids)) != 34:\n    print("turn_item_id NO unicos: reutilizacion=", 34 - len(set(tids)))\n    sys.exit(3)\nif len(set(runs)) != 34:\n    print("run NO unicos: reutilizacion=", 34 - len(set(runs)))\n    sys.exit(3)\ncon = sqlite3.connect("file:C:/Users/fdl/.t3/userdata/statev2.sqlite'
    + chr(63)
    + "mode=ro\", uri=True)\ncur = con.cursor()\nok = 0\nfallos = []\nestructurales = 0\nfor p in pruebas:\n    rows = cur.execute(\n        \"SELECT turn_item_id, run_id, json_extract(payload_json,'$.toolName'), \"\n        \"json_extract(payload_json,'$.input'), status, json_extract(payload_json,'$.output'), type \"\n        \"FROM orchestration_v2_projection_turn_items WHERE thread_id="
    + chr(63)
    + " AND turn_item_id="
    + chr(63)
    + " AND run_id="
    + chr(63)
    + '",\n        (p["hilo"], p["turn_item_id"], p["run"]),\n    ).fetchall()\n    if len(rows) != 1:\n        fallos.append((p["id"], "filas=" + str(len(rows))))\n        estructurales += 1\n        continue\n    _, _, tool_rec, input_rec, status, salida, typ = rows[0]\n    if p["kind"] == "mcp":\n        if typ not in TOOL_TYPES:\n            fallos.append((p["id"], "type_no_herramienta=" + str(typ)))\n            estructurales += 1\n            continue\n        if tool_rec != p["tool"]:\n            fallos.append((p["id"], "tool_rec=" + str(tool_rec)))\n            estructurales += 1\n            continue\n        try:\n            canon = json.dumps(json.loads(input_rec), sort_keys=True) == json.dumps(p["input"], sort_keys=True)\n        except Exception:\n            canon = False\n        if not canon:\n            fallos.append((p["id"], "input_json_distinto"))\n            estructurales += 1\n            continue\n    else:\n        if typ in CMD_TYPES:\n            if tool_rec is not None and tool_rec != "bash":\n                fallos.append((p["id"], "tool_rec=" + str(tool_rec)))\n                estructurales += 1\n                continue\n        elif typ in TOOL_TYPES:\n            if tool_rec != "bash":\n                fallos.append((p["id"], "tool_rec=" + str(tool_rec)))\n                estructurales += 1\n                continue\n        else:\n            fallos.append((p["id"], "type_no_herramienta=" + str(typ)))\n            estructurales += 1\n            continue\n        if input_rec != p["input"]:\n            fallos.append((p["id"], "input_distinto"))\n            estructurales += 1\n            continue\n    if clasificar(salida, CLOSED_REJECTION_TEXTS) == "permiso_denegado":\n        ok += 1\n    else:\n        fallos.append((p["id"], "no_denegado"))\ncon.close()\nif estructurales:\n    print("pruebas=", len(pruebas), "permiso_denegado=", ok, "fallos=", fallos, "estructurales=", estructurales)\n    sys.exit(1)\nif not CLOSED_REJECTION_TEXTS:\n    print("pruebas=", len(pruebas), "PENDIENTE=sin_textos_de_rechazo_reales_archivados",\n          "CLOSED_REJECTION_TEXTS=vacia fallos=", fallos)\n    sys.exit(4)\nprint("pruebas=", len(pruebas), "permiso_denegado=", ok, "fallos=", fallos)\nsys.exit(0 if (ok == 34 and not fallos) else 1)\n'
)
assert hashlib.sha256(GA_SRC.encode("utf-8")).hexdigest() == BLOCK_GA_SHA256
assert hashlib.sha256(GB_SRC.encode("utf-8")).hexdigest() == BLOCK_GB_SHA256
# ---------------- driver de ejecucion de bloques ----------------


def _raise_exit(code=0):
    raise SystemExit(code)


def run_block(src, argv, fixture_path, armed=False):
    """exec del bloque literal tal cual, con las intercepciones declaradas."""
    real_import = builtins.__import__

    def hooked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sqlite3":

            def connect(*args, **kw):
                if args and isinstance(args[0], str) and "statev2" in args[0]:
                    args = (
                        "file:" + fixture_path.replace("\\", "/") + "?mode=ro",
                        *args[1:],
                    )
                return sqlite3.connect(*args, **kw)

            return types.SimpleNamespace(connect=connect, Error=sqlite3.Error)
        if name == "sys":
            return types.SimpleNamespace(argv=list(argv), exit=_raise_exit)
        return real_import(name, globals, locals, fromlist, level)

    def set_factory(*a):
        if not a and armed:
            return {T}
        return set(*a)

    bdict = dict(vars(builtins))
    bdict["__import__"] = hooked_import
    bdict["set"] = set_factory
    g = {"__builtins__": bdict}
    try:
        exec(compile(src, "<bloque_literal>", "exec"), g, g)  # noqa: S102
        return "NO_EXIT", g
    except SystemExit as e:
        code = e.code
        rc = 0 if code is None else (code if isinstance(code, int) else 1)
        return rc, g
    except BaseException as e:
        print("EXCEPCION_EN_BLOQUE", type(e).__name__, str(e))
        traceback.print_exc()
        return "EXC:" + type(e).__name__, g


# ---------------- fixtures (mismas formas que la v3) ----------------


def build_store():
    path = os.path.join(tempfile.mkdtemp(), "st.db")
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE orchestration_v2_projection_threads (thread_id TEXT, project_id TEXT, title TEXT, "
        "default_provider TEXT, runtime_mode TEXT, interaction_mode TEXT, active_provider_thread_id TEXT, "
        "created_at TEXT, updated_at TEXT, archived_at TEXT, deleted_at TEXT, payload_json TEXT, provider_instance_id TEXT)"
    )
    cur.execute(
        "CREATE TABLE orchestration_v2_projection_turn_items (turn_item_id TEXT, thread_id TEXT, run_id TEXT, "
        "node_id TEXT, provider_thread_id TEXT, provider_turn_id TEXT, parent_item_id TEXT, ordinal INTEGER, "
        "type TEXT, status TEXT, updated_at TEXT, payload_json TEXT)"
    )
    con.commit()
    return con, path


def add_thread(
    con,
    tid,
    parent="mcp:ABUELA",
    rel="subagent",
    created="agent",
    created_at="2026-11-17T00:00:00.000Z",
):
    payload = json.dumps(
        {
            "createdBy": created,
            "lineage": {"parentThreadId": parent, "relationshipToParent": rel},
        }
    )
    con.execute(
        "INSERT INTO orchestration_v2_projection_threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            tid,
            "p",
            "t",
            "opencode",
            "full-access",
            "default",
            None,
            created_at,
            created_at,
            None,
            None,
            payload,
            "opencode",
        ),
    )


def add_item(con, iid, tid, run, typ, status, payload, upd="2026-11-17T00:00:00.000Z"):
    con.execute(
        "INSERT INTO orchestration_v2_projection_turn_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            iid,
            tid,
            run,
            "n",
            None,
            None,
            None,
            0,
            typ,
            status,
            upd,
            json.dumps(payload),
        ),
    )


def add_launch_calls(con, agent_values):
    for i, (crid, av) in enumerate(
        zip(["cr-1", "cr-2"], agent_values, strict=False), 1
    ):
        target = {"providerInstanceId": "opencode", "model": "nan/x"}
        if av is not None:
            target["options"] = [
                {"id": "variant", "value": "high"},
                {"id": "agent", "value": av},
            ]
        add_item(
            con,
            "ti-launch-%d" % i,
            "mcp:ABUELA",
            "run-l%d" % i,
            "dynamic_tool",
            "completed",
            {
                "toolName": "t3-code_delegate_task",
                "input": {
                    "clientRequestId": crid,
                    "title": "lote",
                    "target": target,
                    "task": "mision",
                },
            },
        )


def build_catalogo():
    cfg = json.load(open(CONFIG, encoding="utf-8-sig"))
    permission = cfg["agent"]["nieto"]["permission"]
    native_tools = set()
    for node in ast.walk(ast.parse(GB_SRC)):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "NATIVAS"
            for target in node.targets
        ):
            native_tools = ast.literal_eval(node.value)
            break
    named = [
        name
        for name, action in permission.items()
        if isinstance(action, str)
        and action == "deny"
        and name not in native_tools
        and "*" not in name
    ]
    pruebas = []
    n = 0
    for x in named:
        for pre in ("", "t3_code_", "t3-code_"):
            n += 1
            pruebas.append(
                {
                    "id": "mcp-%02d" % n,
                    "kind": "mcp",
                    "tool": pre + x,
                    "hilo": "hilo-nieto-mcp",
                    "input": {"arg": n},
                    "run": "run-%02d" % n,
                    "turn_item_id": "ti-%02d" % n,
                }
            )
    n += 1
    pruebas.append(
        {
            "id": "mcp-task",
            "kind": "mcp",
            "tool": "task",
            "hilo": "hilo-nieto-mcp",
            "input": {"x": 1},
            "run": "run-task",
            "turn_item_id": "ti-task",
        }
    )
    for i, c in enumerate(["git status", "python -B -m pytest", "ls"], 1):
        pruebas.append(
            {
                "id": "bash-%d" % i,
                "kind": "bash",
                "input": c,
                "hilo": "hilo-bash-%d" % i,
                "run": "run-bash-%d" % i,
                "turn_item_id": "ti-bash-%d" % i,
            }
        )
    return {
        "nielto_mcp": "hilo-nieto-mcp",
        "bash_hilos": {
            c: "hilo-bash-%d" % i
            for i, c in enumerate(["git status", "python -B -m pytest", "ls"], 1)
        },
        "pruebas": pruebas,
    }


def fill_store(con, cat, mode="green", out=None):  # noqa: C901
    hilos = [cat["nielto_mcp"], *list(cat["bash_hilos"].values())]
    for h in hilos:
        add_thread(con, h)
    for p in cat["pruebas"]:
        tool = p["tool"] if p["kind"] == "mcp" else "bash"
        tid = p["hilo"]
        run = p["run"]
        inp = p["input"]
        typ = "dynamic_tool"
        text_out = out if out is not None else "Permission denied by policy"
        if mode == "input_wrong" and p["kind"] == "mcp":
            inp = {"WRONG": True}
        elif mode == "bash_read_tool" and p["kind"] == "bash":
            tool = "read"
        elif mode == "foreign_run":
            run = p["run"] + "-OTRO"
        elif mode == "other_thread":
            tid = "hilo-intruso"
        elif mode == "key_order" and p["kind"] == "mcp":
            pass
        elif mode == "user_message_evidence":
            typ = "user_message"
            tool = None
            inp = None
        elif mode == "command_exec" and p["kind"] == "bash":
            typ = "command_execution"
            tool = None
            inp = p["input"]
        if mode == "key_order" and p["kind"] == "mcp":
            store_inp = dict(reversed(list(inp.items())))
        else:
            store_inp = inp
        payload = {"output": text_out}
        if tool is not None:
            payload["toolName"] = tool
        if store_inp is not None:
            payload["input"] = store_inp
        add_item(con, p["turn_item_id"], tid, run, typ, "error", payload)


def ga_decl():
    return {
        "lanzamientos": [
            {"clientRequestId": "cr-1", "threadId": "hilo-hijo"},
            {"clientRequestId": "cr-2", "threadId": "hilo-nieto"},
        ]
    }


def dump_tmp(obj, suffix):
    path = os.path.join(tempfile.mkdtemp(), "d" + suffix)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return path


# ---------------- ejecucion de los 47 casos ----------------


def _run_all():  # noqa: C901
    global CONFIG
    from pathlib import Path

    CONFIG = str(
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "flight"
        / "nieto_root"
        / ".opencode"
        / "opencode.json"
    )
    assert os.path.isfile(CONFIG)
    results = {}
    ns_gb = None

    def run_ga(tag, setup, abuela="mcp:ABUELA", decl=None):
        con, path = build_store()
        setup(con)
        con.commit()
        con.close()
        decl_path = dump_tmp(decl if decl is not None else ga_decl(), ".json")
        argv = [
            "validador_GA.py",
            CONFIG,
            abuela,
            decl_path,
            WIN[0],
            WIN[1],
            WIN[0],
            WIN[1],
        ]
        rc, _ = run_block(GA_SRC, argv, path, armed=False)
        results[tag] = rc

    def run_gb(
        tag,
        mode="green",
        mutate=None,
        fill_cat=None,
        armed=False,
        out=None,
        setup_store=None,
    ):
        cat = build_catalogo()
        if mutate:
            mutate(cat)
        con, path = build_store()
        if setup_store is not None:
            setup_store(con, cat)
        else:
            fill_store(con, fill_cat if fill_cat is not None else cat, mode, out=out)
        con.commit()
        con.close()
        cat_path = dump_tmp(cat, ".json")
        argv = ["validador_GB.py", CONFIG, cat_path]
        rc, g = run_block(GB_SRC, argv, path, armed=armed)
        results[tag] = rc
        return g

    # ---- G-A (23 casos) ----
    run_ga("GA_VACIO", lambda con: None, decl={"lanzamientos": []})
    # r5 (MENOR-2): ventana de creacion vacia -> rc 3 (CASOS EXIGIDOS (2) y matriz GA-1)
    run_ga("GA_VENTANA_VACIA", lambda con: None)

    def base_threads(con):
        add_thread(con, "hilo-hijo")
        add_thread(con, "hilo-nieto")

    def ga_case(
        tag, tool, typ="dynamic_tool", upd="2026-11-17T00:00:00.000Z", payload=None
    ):
        def setup(con):
            base_threads(con)
            if payload is None:
                pl = {"toolName": tool, "input": {"filePath": "x"}, "output": "ok"}
            else:
                pl = payload
            add_item(con, "ti-x1", "hilo-nieto", "r0", typ, "completed", pl, upd=upd)

        run_ga(tag, setup)

    def setup_verde(con):
        base_threads(con)
        add_item(
            con,
            "ti-r1",
            "hilo-nieto",
            "r0",
            "dynamic_tool",
            "completed",
            {"toolName": "read", "input": {"filePath": "x"}, "output": "ok"},
        )
        add_item(
            con,
            "ti-r2",
            "hilo-hijo",
            "r0b",
            "dynamic_tool",
            "completed",
            {"toolName": "write", "input": {"filePath": "y"}, "output": "ok"},
        )

    run_ga("GA_VERDE", setup_verde)

    ga_case("GA_DELEGATE", "t3-code_delegate_task")
    ga_case("GA_FORK", "t3-code_t3_thread_fork")
    ga_case("GA_LAUNCH", "t3-code_t3_thread_launch")
    ga_case("GA_SKILL", "skill")
    ga_case("GA_WEBFETCH", "webfetch")
    ga_case("GA_TASK", "task")
    ga_case("GA_MCP_NEW_LAUNCH", "mcp__new__launch")
    ga_case("GA_UPPER_DELEGATE", "T3-CODE_DELEGATE_TASK")
    ga_case("GA_ALIAS_APPLY_PATCH", "apply_patch")
    ga_case("GA_ALIAS_LIST_MCP", "list_mcp_resources")
    ga_case(
        "GA_USER_MESSAGE",
        None,
        typ="user_message",
        payload={"toolName": None, "input": None, "output": "hola, esto es un mensaje"},
    )
    ga_case(
        "GA_REASONING",
        None,
        typ="reasoning",
        payload={"toolName": None, "input": None, "output": "pensamiento intermedio"},
    )
    ga_case("GA_OUTSIDE_WINDOW", "task", upd="2099-01-01T00:00:00.000Z")

    run_ga(
        "GA_MISMO_ID",
        lambda con: None,
        decl={
            "lanzamientos": [
                {"clientRequestId": "cr-1", "threadId": "hilo-x"},
                {"clientRequestId": "cr-2", "threadId": "hilo-x"},
            ]
        },
    )

    def setup_lanzador(con):
        add_thread(con, "hilo-hijo", parent=LAUNCHER)
        add_thread(con, "hilo-nieto", parent=LAUNCHER)

    run_ga("GA_ABUELA_LITERAL_CO109", setup_lanzador, abuela=CO109_LITERAL)

    def setup_agent_plan(con):
        base_threads(con)
        add_launch_calls(con, ["plan", "nieto"])

    run_ga("GA_AGENT_INCORRECTO", setup_agent_plan)

    def setup_agent_ok(con):
        base_threads(con)
        add_launch_calls(con, ["nieto", "nieto"])

    run_ga("GA_AGENT_NIETO_OK", setup_agent_ok)

    def setup_agent_noreg(con):
        base_threads(con)
        add_launch_calls(con, [None, None])

    run_ga("GA_AGENT_NO_REGISTRADO", setup_agent_noreg)

    # ronda 4: regresion BA254 C7 - la lectura ajena que CONTIENE los ids
    # (subcadena) y un target.options agent=plan NO debe contar
    def setup_subcadena(con):
        base_threads(con)
        add_launch_calls(con, ["nieto", "nieto"])
        add_item(
            con,
            "ti-ajeno",
            "mcp:ABUELA",
            "run-aj",
            "dynamic_tool",
            "completed",
            {
                "toolName": "read",
                "input": {
                    "filePath": "x.txt",
                    "nota": "referencias a cr-1 y cr-2 en texto libre",
                    "clientRequestId": "cr-1",
                    "target": {"options": [{"id": "agent", "value": "plan"}]},
                },
                "output": "ok",
            },
        )

    run_ga("GA_SUBCADENA_AJENO", setup_subcadena)

    # ronda 4: coincidencias multiples - dos llamadas de lanzamiento con
    # el MISMO clientRequestId exacto => violacion fail-closed
    def setup_multi(con):
        base_threads(con)
        add_launch_calls(con, ["nieto", "nieto"])
        add_item(
            con,
            "ti-launch-dup",
            "mcp:ABUELA",
            "run-dup",
            "dynamic_tool",
            "completed",
            {
                "toolName": "t3-code_delegate_task",
                "input": {
                    "clientRequestId": "cr-1",
                    "target": {"options": [{"id": "agent", "value": "plan"}]},
                    "task": "duplicado",
                },
            },
        )

    run_ga("GA_AGENT_MULTI", setup_multi)

    # ---- G-B (20 casos) ----
    def m_noid(c):
        # r5 (MENOR-2): identidad nula -> rc 2 (CASOS EXIGIDOS (12))
        c["pruebas"][0]["turn_item_id"] = None

    run_gb("GB_IDENTIDAD_NULA", mutate=m_noid)

    def m_skill(c):
        for p in c["pruebas"]:
            if p["kind"] == "mcp":
                p["tool"] = "skill"

    run_gb("GB_31_SKILL", mutate=m_skill)

    run_gb("GB_INPUT_AJENO", mode="input_wrong")
    run_gb("GB_BASH_TOOL_READ", mode="bash_read_tool")

    def m_reuse(c):
        for p in c["pruebas"]:
            p["turn_item_id"] = "ti-mismo"
            p["run"] = "run-mismo"

    run_gb("GB_REUSO_CATALOGO", mutate=m_reuse)

    def setup_reutiliza(con, cat):
        add_thread(con, cat["nielto_mcp"])
        add_item(
            con,
            "ti-mismo",
            cat["nielto_mcp"],
            "run-mismo",
            "dynamic_tool",
            "error",
            {"toolName": "skill", "input": {"a": 1}, "output": T},
        )

    run_gb("GB_REUTILIZA_34", setup_store=setup_reutiliza)

    run_gb("GB_FOREIGN_RUN", mode="foreign_run")
    run_gb("GB_ITEM_OTRO_HILO", mode="other_thread")

    def m_extra(c):
        for p in c["pruebas"]:
            if p["kind"] == "mcp":
                p["input"] = dict(p["input"], extra=True)

    run_gb("GB_EXTRA_FIELD", mutate=m_extra, fill_cat=build_catalogo())

    run_gb("GB_USER_MESSAGE_EVIDENCE", mode="user_message_evidence")

    def m_arb(c):
        c["bash_hilos"].pop("ls")
        c["bash_hilos"]["echo harmless"] = "hilo-bash-3"
        for p in c["pruebas"]:
            if p["kind"] == "bash" and p["input"] == "ls":
                p["input"] = "echo harmless"

    run_gb("GB_ARBITRARY_BASH", mutate=m_arb)

    def m_col(c):
        c["bash_hilos"] = {x: c["nielto_mcp"] for x in c["bash_hilos"]}
        for p in c["pruebas"]:
            if p["kind"] == "bash":
                p["hilo"] = c["nielto_mcp"]

    run_gb("GB_COLLAPSED_THREADS", mutate=m_col)

    # PENDIENTE (lista vacia): rc 4 aunque el output diga denegacion
    run_gb("GB_PENDIENTE_VACIO")
    run_gb("GB_PENDIENTE_FRASE_BA254", out=BA254_R2_PHRASE)

    # CON TEXTO (arma set() -> {T} en la constante literal)
    run_gb("GB_VERDE_TEXTOS", armed=True)

    def m_key2(c):
        for p in c["pruebas"]:
            if p["kind"] == "mcp":
                base = dict(p["input"])
                base["zz"] = "v"
                p["input"] = base

    run_gb("GB_KEY_ORDER", mutate=m_key2, mode="key_order", armed=True)

    run_gb("GB_COMMAND_EXECUTION_TEXTOS", mode="command_exec", armed=True)
    run_gb("GB_MIXED_GRANTED_TEXTOS", out=MIXED_OUT, armed=True)
    run_gb("GB_T_MAS_APROBADO", out=T_MAS_APROBADO, armed=True)

    def setup_frase(con, cat):
        fill_store(con, cat, "green", out=T)
        con.execute(
            "UPDATE orchestration_v2_projection_turn_items SET payload_json=? WHERE turn_item_id=?",
            (
                json.dumps(
                    {
                        "toolName": cat["pruebas"][0]["tool"],
                        "input": cat["pruebas"][0]["input"],
                        "output": BA254_R2_PHRASE,
                        "status": "error",
                    }
                ),
                cat["pruebas"][0]["turn_item_id"],
            ),
        )
        con.commit()

    ns = run_gb("GB_FRASE_BA254_R2", armed=True, setup_store=setup_frase)
    ns_gb = ns

    # ---- clasificador (8 casos; funcion literal reutilizada del bloque extraido) ----
    clasificar = ns_gb["clasificar"]
    cls = {
        "CLS_exacto_en_lista": (T, {T}, "permiso_denegado"),
        "CLS_vacio_deny": (T, set(), "no_rechazo"),
        "CLS_tool_not_found": ("Tool not found: permission denied", {T}, "no_rechazo"),
        "CLS_granted": ("permission granted", {T}, "no_rechazo"),
        "CLS_frase_ba254": (BA254_R2_PHRASE, {T}, "no_rechazo"),
        "CLS_t_mas_acceso_aprobado": (T_MAS_APROBADO, {T}, "no_rechazo"),
        "CLS_trim": ("   " + T + "\n", {T}, "permiso_denegado"),
        "CLS_vacio_lista_todo_no_rechazo": (
            "access granted now; command succeeded",
            set(),
            "no_rechazo",
        ),
    }
    for tag, (sal, textos, esperado) in cls.items():
        results[tag] = 0 if clasificar(sal, textos) == esperado else 1

    orden = [
        "GA_VACIO",
        "GA_VENTANA_VACIA",
        "GA_VERDE",
        "GA_DELEGATE",
        "GA_FORK",
        "GA_LAUNCH",
        "GA_SKILL",
        "GA_WEBFETCH",
        "GA_TASK",
        "GA_MCP_NEW_LAUNCH",
        "GA_UPPER_DELEGATE",
        "GA_ALIAS_APPLY_PATCH",
        "GA_ALIAS_LIST_MCP",
        "GA_USER_MESSAGE",
        "GA_REASONING",
        "GA_OUTSIDE_WINDOW",
        "GA_MISMO_ID",
        "GA_ABUELA_LITERAL_CO109",
        "GA_AGENT_INCORRECTO",
        "GA_AGENT_NIETO_OK",
        "GA_AGENT_NO_REGISTRADO",
        "GA_SUBCADENA_AJENO",
        "GA_AGENT_MULTI",
        "GB_31_SKILL",
        "GB_IDENTIDAD_NULA",
        "GB_INPUT_AJENO",
        "GB_BASH_TOOL_READ",
        "GB_REUSO_CATALOGO",
        "GB_REUTILIZA_34",
        "GB_FOREIGN_RUN",
        "GB_ITEM_OTRO_HILO",
        "GB_EXTRA_FIELD",
        "GB_USER_MESSAGE_EVIDENCE",
        "GB_ARBITRARY_BASH",
        "GB_COLLAPSED_THREADS",
        "GB_PENDIENTE_VACIO",
        "GB_PENDIENTE_FRASE_BA254",
        "GB_VERDE_TEXTOS",
        "GB_KEY_ORDER",
        "GB_COMMAND_EXECUTION_TEXTOS",
        "GB_MIXED_GRANTED_TEXTOS",
        "GB_T_MAS_APROBADO",
        "GB_FRASE_BA254_R2",
        "CLS_exacto_en_lista",
        "CLS_vacio_deny",
        "CLS_tool_not_found",
        "CLS_granted",
        "CLS_frase_ba254",
        "CLS_t_mas_acceso_aprobado",
        "CLS_trim",
        "CLS_vacio_lista_todo_no_rechazo",
    ]
    esperado = {
        "GA_VACIO": 2,
        "GA_VENTANA_VACIA": 3,
        "GA_VERDE": 0,
        "GA_DELEGATE": 1,
        "GA_FORK": 1,
        "GA_LAUNCH": 1,
        "GA_SKILL": 1,
        "GA_WEBFETCH": 1,
        "GA_TASK": 1,
        "GA_MCP_NEW_LAUNCH": 1,
        "GA_UPPER_DELEGATE": 1,
        "GA_ALIAS_APPLY_PATCH": 0,
        "GA_ALIAS_LIST_MCP": 0,
        "GA_USER_MESSAGE": 0,
        "GA_REASONING": 0,
        "GA_OUTSIDE_WINDOW": 0,
        "GA_MISMO_ID": 2,
        "GA_ABUELA_LITERAL_CO109": 1,
        "GA_AGENT_INCORRECTO": 1,
        "GA_AGENT_NIETO_OK": 0,
        "GA_AGENT_NO_REGISTRADO": 0,
        "GA_SUBCADENA_AJENO": 0,
        "GA_AGENT_MULTI": 1,
        "GB_31_SKILL": 2,
        "GB_IDENTIDAD_NULA": 2,
        "GB_INPUT_AJENO": 1,
        "GB_BASH_TOOL_READ": 1,
        "GB_REUSO_CATALOGO": 3,
        "GB_REUTILIZA_34": 1,
        "GB_FOREIGN_RUN": 1,
        "GB_ITEM_OTRO_HILO": 1,
        "GB_EXTRA_FIELD": 1,
        "GB_USER_MESSAGE_EVIDENCE": 1,
        "GB_ARBITRARY_BASH": 2,
        "GB_COLLAPSED_THREADS": 2,
        "GB_PENDIENTE_VACIO": 4,
        "GB_PENDIENTE_FRASE_BA254": 4,
        "GB_VERDE_TEXTOS": 0,
        "GB_KEY_ORDER": 0,
        "GB_COMMAND_EXECUTION_TEXTOS": 0,
        "GB_MIXED_GRANTED_TEXTOS": 1,
        "GB_T_MAS_APROBADO": 1,
        "GB_FRASE_BA254_R2": 1,
        "CLS_exacto_en_lista": 0,
        "CLS_vacio_deny": 0,
        "CLS_tool_not_found": 0,
        "CLS_granted": 0,
        "CLS_frase_ba254": 0,
        "CLS_t_mas_acceso_aprobado": 0,
        "CLS_trim": 0,
        "CLS_vacio_lista_todo_no_rechazo": 0,
    }
    print(
        "== RESULTADOS 184d v6 (bloques LITERALES extraidos de la ficha, sha256 publicado verificado, ejecutados con exec) =="
    )
    print("bloques_extraidos=", 2, "GA_bytes=", len(GA_SRC), "GB_bytes=", len(GB_SRC))
    for k in orden:
        print(k, "rc=", results[k], "esperado=", esperado[k])
    wrong = [k for k in orden if results[k] != esperado[k]]
    print("desvios=", wrong)
    print("total_casos=", len(orden))
    return 0 if not wrong else 1


def test_validadores_ga_gb_casos_adversariales():
    """Before: use temporary real-shaped store fixtures.

    During: execute both embedded validator blocks through the 51-case matrix.
    After: every literal return code and classifier result matches the contract.
    """
    assert _run_all() == 0
