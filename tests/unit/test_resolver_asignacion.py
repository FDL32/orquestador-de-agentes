"""Pruebas de la declaracion y resolucion de asignaciones del vuelo."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "flight"
    / "resolver_asignacion.py"
)


def _load_module():
    """Before: localiza el modulo productivo por ruta. During: lo importa. After: devuelve el modulo."""
    spec = importlib.util.spec_from_file_location(
        "resolver_asignacion_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_module_from(path, name="resolver_asignacion_copy"):
    """Before: path contiene una copia del modulo. During: la importa por ruta. After: devuelve el modulo aislado."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_uuid(number="f130d0e9-6480-4a2c-adb0-b68fd31b9fc0"):
    """Before: se necesita una orden valida. During: conserva el UUID canonico. After: devuelve el texto."""
    return {"messageId": number}


def _three_candidate_fixture():
    """Before: no hay fixture de seleccion. During: crea tres candidatos y sus backends. After: devuelve ambos objetos."""
    module = _load_module()
    assignments = _declaration()
    assignments["co"] = {
        "candidatos": [
            {"backend_key": "C1"},
            {"backend_key": "C2"},
            {"backend_key": "C3"},
        ],
        "nivel": "medio",
        "refugio": [{"backend_key": "BA05", "cuenta": "codex"}],
        "orden": _valid_uuid(),
    }
    backends = {
        "C1": _backend("C1", "f1", "medio", model="m1"),
        "C2": _backend("C2", "f2", "medio", model="m2"),
        "C3": _backend("C3", "f2", "premium", model="m3"),
    }
    return module, assignments, backends


def _backend(key, family, level="base", effort="maximo", model=None, backend="kilo"):
    """Before: recibe los datos minimos de un backend. During: construye su entrada. After: devuelve un registro."""
    return {
        "backend": backend,
        "model": model or f"{family}-model",
        "family": family,
        "nivel": level,
        "niveles": [level],
        "esfuerzo": effort,
    }


def _declaration():
    """Before: no requiere estado externo. During: construye una declaracion minima valida. After: devuelve asignaciones."""
    module = _load_module()
    refuge = [{"backend_key": "BA05", "cuenta": "codex"}]
    return {
        puesto: {
            "candidatos": [{"backend_key": "BA05"}],
            "nivel": "medio",
            "refugio": refuge,
            "orden": {"messageId": None},
        }
        for puesto in module.PUESTOS
    }


def test_load_declaration_requires_all_posts(tmp_path):
    """Before: falta un puesto. During: carga la declaracion. After: falla de forma cerrada."""
    module = _load_module()
    data = {"asignaciones": _declaration()}
    data["asignaciones"].pop(module.PUESTOS[-1])
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(module.AsignacionError):
        module.load_declaration(path)


def test_subtree_hash_is_canonical_and_short_hash_is_prefix():
    """Before: hay una declaracion estable. During: calcula ambos hashes. After: el corto es prefijo exacto."""
    module = _load_module()
    assignments = _declaration()
    assert len(module.subtree_hash(assignments)) == 64
    assert module.short_hash(assignments) == module.subtree_hash(assignments)[:16]


def test_candidate_info_resolves_backend_and_t3_session():
    """Before: existen ambos tipos de candidato. During: normaliza sus metadatos. After: conserva lanzamiento y niveles."""
    module = _load_module()
    backends = {
        "BA05": _backend("BA05", "codex", "medio", "alto", "gpt-5.6-luna", "codex")
    }
    backend_info = module.candidate_info({"backend_key": "BA05"}, backends)
    session_info = module.candidate_info(
        {
            "tipo": "t3_session",
            "familia": "gemini",
            "nivel": "medio",
            "instanceId": "antigravity",
            "model": "gemini-3.8-flash-high",
            "effort": "high",
        },
        backends,
    )
    assert backend_info["familia"] == "codex"
    assert backend_info["niveles"] == ["medio"]
    assert backend_info["lanzamiento"]["backend_key"] == "BA05"
    assert session_info["lanzamiento"]["instanceId"] == "antigravity"
    assert session_info["niveles"] == ["medio"]


def test_resolve_applies_filters_in_order_and_reports_skips():
    """Before: los candidatos fallan por familia, nivel y pendiente. During: resuelve el siguiente valido. After: expone motivos."""
    module = _load_module()
    assignments = _declaration()
    assignments["co"] = {
        "candidatos": [
            {"backend_key": "BA05"},
            {"backend_key": "BA07", "orden": {"messageId": "not-a-uuid"}},
            {
                "backend_key": "BA09",
                "orden": {"messageId": "f130d0e9-6480-4a2c-adb0-b68fd31b9fc0"},
            },
        ],
        "nivel": "medio",
        "refugio": [{"backend_key": "BA05", "cuenta": "codex"}],
        "orden": {"messageId": "f130d0e9-6480-4a2c-adb0-b68fd31b9fc0"},
    }
    backends = {
        "BA05": _backend("BA05", "codex", "alto", "alto", "luna", "codex"),
        "BA07": _backend("BA07", "deepseek", "medio"),
        "BA09": _backend("BA09", "gemma", "base"),
    }
    result = module.resolve(assignments, "co", backends, excluir_familias=("codex",))
    assert result["candidato"]["backend_key"] == "BA09"
    assert [
        (item["candidato"]["backend_key"], item["motivo"])
        for item in result["saltados"]
    ] == [
        ("BA05", "familia"),
        ("BA07", "pendiente_confirmacion"),
    ]

    pending = module.resolve(
        assignments, "co", backends, excluir_familias=("codex", "deepseek")
    )
    assert pending["candidato"]["backend_key"] == "BA09"


def test_resolve_no_candidate_carries_skips():
    """Before: todos los candidatos se excluyen. During: intenta resolver. After: la excepcion conserva el diagnostico."""
    module = _load_module()
    assignments = _declaration()
    backends = {"BA05": _backend("BA05", "codex", "medio")}
    with pytest.raises(module.SinCandidatoError) as error:
        module.resolve(assignments, "co", backends, excluir_familias=("codex",))
    assert error.value.saltados[0]["motivo"] == "familia"


def test_derive_eligible_uses_profiles_and_exclusions():
    """Before: lentes contiene candidatos elegibles y excluidos. During: deriva la cobertura. After: respeta orden y filtros."""
    module = _load_module()
    assignments = _declaration()
    assignments["lentes_p34"] = {
        "candidatos": [
            {"backend_key": key} for key in ("BA05", "BA07", "BA08", "BA09")
        ],
        "nivel": "medio",
        "refugio": [{"backend_key": "BA05", "cuenta": "codex"}],
        "orden": {"messageId": None},
    }
    config = {
        "ensemble_registry": {
            "backend_keys": {
                "BA05": _backend("BA05", "codex", "medio"),
                "BA07": _backend("BA07", "deepseek", "medio"),
                "BA08": _backend("BA08", "qwen", "base"),
                "BA09": _backend("BA09", "gemma", "base"),
            },
            "eligible_coverage": {
                "MANAGER_REVIEW:repo_motor": {"excluded_backend_keys": ["BA07"]}
            },
        },
        "ensemble_profiles": {
            "a": {"backend_key": "BA05"},
            "b": {"backend_key": "BA07"},
            "c": {"backend_key": "BA08"},
            "d": {"backend_key": "BA09"},
        },
    }
    assert module.derive_eligible(assignments, config) == ["BA05", "BA08", "BA09"]


def test_derive_role_models_and_assignments_builder():
    """Before: el builder apunta a BA05. During: deriva modelo y backend. After: devuelve los valores del registro."""
    module = _load_module()
    assignments = _declaration()
    assignments["im.builder"]["orden"] = {
        "messageId": "f130d0e9-6480-4a2c-adb0-b68fd31b9fc0"
    }
    backends = {
        "BA05": _backend("BA05", "codex", "medio", "alto", "gpt-5.6-luna", "codex")
    }
    assert module.derive_role_models_builder(assignments, backends) == "gpt-5.6-luna"
    assert module.derive_role_assignments_builder(assignments, backends) == "codex"


def test_normalize_effort_maps_provider_values_to_registry_vocabulary():
    """Before: candidatos pueden usar effort del proveedor. During: normaliza. After: vocabulario estable y valores canonicos intactos."""
    module = _load_module()
    assert module.normalize_effort("high") == "alto"
    assert module.normalize_effort("xhigh") == "maximo"
    assert module.normalize_effort("alto") == "alto"
    assert module.normalize_effort("custom") == "custom"


def test_m10_derived_values_match_real_agents_json_after_apply():
    """Before: la ronda 2 aun no aplica derivados. During: compara contra el agents.json real. After: deja evidencia del pendiente."""
    module = _load_module()
    document, assignments = module.load_declaration(module.DEFAULT_AGENTS_JSON)
    backends = document["ensemble_registry"]["backend_keys"]
    expected_model = module.derive_role_models_builder(assignments, backends)
    expected_backend = module.derive_role_assignments_builder(assignments, backends)
    assert document["role_models"]["BUILDER"] == expected_model, (
        "m-10: role_models.BUILDER debe conservar el derivado"
    )
    assert document["role_assignments"]["BUILDER"] == expected_backend, (
        "m-10: esperado rojo en ronda 1; ronda 2 debe aplicar render --apply"
    )


def test_real_agents_json_declares_legacy_cells_note():
    """Before: existe el agents.json del worktree. During: inspecciona celdas._legacy. After: verifica sus punteros de migracion."""
    module = _load_module()
    document = json.loads(module.DEFAULT_AGENTS_JSON.read_text(encoding="utf-8"))
    legacy = document["celdas"]["_legacy"]
    assert isinstance(legacy, str)
    assert "CELLS_CUTOFF" in legacy
    assert "asignaciones" in legacy


def _load_registry_ops(path=None, name="registry_ops_round3"):
    """Before: registry_ops puede cargarse por ruta. During: importa el modulo. After: devuelve su API."""
    path = path or (MODULE_PATH.parents[0] / "registry_ops.py")
    return _load_module_from(path, name)


def _round3_fixture(tmp_path):
    """Before: se necesita un vuelo aislado. During: copia config y crea registry/roster. After: devuelve sus rutas."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    agents = tmp_path / "agents.json"
    source = MODULE_PATH.parents[2] / ".agent" / "config" / "agents.json"
    agents.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sessions": []}) + "\n", encoding="utf-8")
    roster = tmp_path / "roster.json"
    roster.write_text(
        json.dumps({"active_roles": {"orquestador": {"estado": "ACTIVO"}}}) + "\n",
        encoding="utf-8",
    )
    return agents, registry, roster


def _alta_args(
    registry_ops,
    agents,
    registry,
    kind,
    apply=False,
    cell=None,
    include_agents=True,
    builder_thread=None,
    order_id="9c01c011-e0c0-414e-87a7-df5b5c02f32c",
    motivo="orden de prueba",
):
    """Before: existe un fixture de alta. During: compone los argumentos productivos. After: devuelve argv."""
    args = [
        "alta",
        "--registry",
        str(registry),
        "--code",
        f"R3-{kind}",
        "--role",
        "implantacion" if kind == "im" else "triaje",
        "--slot",
        kind,
        "--thread-id",
        f"thread-{kind}",
        "--started",
        "2026-11-24T10:00:00+01:00",
        "--status",
        "ACTIVE",
        "--by",
        "round3",
        "--reason",
        "test round3",
        "--orden-message-id",
        order_id,
        "--motivo",
        motivo,
        "--celda-de",
        kind,
    ]
    if include_agents:
        args[3:3] = ["--agents-json", str(agents)]
    if builder_thread is not None:
        args.extend(["--builder-thread-id", builder_thread])
    if cell is not None:
        args.extend(["--celda", json.dumps(cell)])
    if apply:
        args.append("--apply")
    return args


def _run_hashed_alta(tmp_path, kind, apply=False, agents=None, code_suffix=""):
    """Before: hay un fixture aislado. During: ejecuta alta por main. After: devuelve rc y artefactos."""
    registry_ops = _load_registry_ops(name=f"registry_ops_{kind}_{apply}_{code_suffix}")
    if agents is None:
        agents, registry, roster = _round3_fixture(tmp_path)
    else:
        tmp_path.mkdir(parents=True, exist_ok=True)
        registry = tmp_path / f"registry_{kind}_{code_suffix}.json"
        roster = tmp_path / f"roster_{kind}_{code_suffix}.json"
        registry.write_text(json.dumps({"sessions": []}) + "\n", encoding="utf-8")
        roster.write_text(
            json.dumps({"active_roles": {"orquestador": {"estado": "ACTIVO"}}}),
            encoding="utf-8",
        )
    args = _alta_args(registry_ops, agents, registry, kind, apply=apply)
    if apply:
        args.extend(["--roster", str(roster)])
    return registry_ops.main(args), registry, roster


def test_m11_hashed_im_and_tr_alta_freeze_resolved_cells(tmp_path, capsys):
    """Before: agents y registry son fixtures. During: ejecuta dry-run y apply IM/TR. After: celda y recibo siguen la resolucion."""
    registry_ops = _load_registry_ops()
    for kind in ("im", "tr"):
        agents, registry, roster = _round3_fixture(tmp_path / f"fixture_{kind}")
        dry_args = _alta_args(registry_ops, agents, registry, kind)
        assert registry_ops.main(dry_args) == 0
        dry = json.loads(capsys.readouterr().out)
        assert "celda" in dry and "celda_asignacion" in dry
        assert dry["celda_asignacion"]["hash"] == _load_module().short_hash(
            json.loads(agents.read_text(encoding="utf-8"))["asignaciones"]
        )
        apply_args = _alta_args(registry_ops, agents, registry, kind, apply=True)
        apply_args.extend(["--roster", str(roster)])
        assert registry_ops.main(apply_args) == 0
        saved = json.loads(registry.read_text(encoding="utf-8"))["sessions"][0]
        assert saved["celda"] == dry["celda"]
        assert saved["celda_asignacion"] == dry["celda_asignacion"]
        assert (
            saved["celda_asignacion"]["orden"]["messageId"]
            == "9c01c011-e0c0-414e-87a7-df5b5c02f32c"
        )


def test_m11_celda_de_is_mutually_exclusive_and_manual_cell_warns(tmp_path, capsys):
    """Before: alta acepta ambos modos historicos/nuevos. During: combina flags y usa celda manual. After: rc2 conjunto y aviso legacy aislado."""
    registry_ops = _load_registry_ops()
    agents, registry, _roster = _round3_fixture(tmp_path)
    manual = {
        "builder": "codex gpt-5.6-luna",
        "revisor": "gemini gemini-3.8-flash-high",
        "v1": "codex gpt-5.6-luna",
    }
    both = _alta_args(registry_ops, agents, registry, "im", cell=manual)
    assert registry_ops.main(both) == 2
    capsys.readouterr()
    manual_args = _alta_args(registry_ops, agents, registry, "im", cell=manual)
    for flag in ("--celda-de", "--orden-message-id", "--motivo"):
        index = manual_args.index(flag)
        del manual_args[index : index + 2]
    assert registry_ops.main(manual_args) == 0
    assert "registry_ops: DEPRECADO --celda" in capsys.readouterr().err


def test_celdas_edit_does_not_change_hashed_alta(tmp_path):
    """Before: dos fixtures parten de la misma declaracion. During: muta celdas legacy en uno. After: alta hashed queda identica."""
    base_agents, _, _ = _round3_fixture(tmp_path / "base")
    edited_agents, _, _ = _round3_fixture(tmp_path / "edited")
    edited = json.loads(edited_agents.read_text(encoding="utf-8"))
    edited["celdas"]["im"]["builder"] = {"backend_key": "BA269"}
    edited["celdas"]["im"]["revisor"] = {"backend_key": "BA05"}
    edited["celdas"]["im"]["v1"] = {"backend_key": "BA269"}
    edited["celdas"]["im"]["nivel"] = "premium"
    edited["celdas"]["im"]["esfuerzo"] = "bajo"
    edited["celdas"]["tr"]["triador"] = {"backend_key": "BA05"}
    edited["celdas"]["tr"]["revisor"] = {"backend_key": "BA09"}
    edited_agents.write_text(json.dumps(edited), encoding="utf-8")
    for kind in ("im", "tr"):
        left_rc, left_registry, _ = _run_hashed_alta(
            tmp_path / f"left_{kind}",
            kind,
            apply=True,
            agents=base_agents,
            code_suffix="left",
        )
        right_rc, right_registry, _ = _run_hashed_alta(
            tmp_path / f"right_{kind}",
            kind,
            apply=True,
            agents=edited_agents,
            code_suffix="right",
        )
        assert left_rc == right_rc == 0
        left = json.loads(left_registry.read_text(encoding="utf-8"))["sessions"][0]
        right = json.loads(right_registry.read_text(encoding="utf-8"))["sessions"][0]
        assert left["celda"] == right["celda"]
        assert (
            left["celda_asignacion"]["resolucion"]
            == right["celda_asignacion"]["resolucion"]
        )
        if kind == "im":
            assert right["celda"]["nivel"] == "medio"
            assert right["celda"]["esfuerzo"] == "alto"


def test_mutation_alta_reading_celdas_nivel_changes_cell(tmp_path):
    """Before: la alta debe leer nivel de asignaciones. During: un mutante lo toma de celdas. After: el mutante diverge y el control no."""
    source = (MODULE_PATH.parents[0] / "registry_ops.py").read_text(encoding="utf-8")
    needle = 'nivel = revisor["nivel_puesto"]'
    assert source.count(needle) == 1
    mutant_path = tmp_path / "registry_ops_nivel_mutant.py"
    mutant_path.write_text(
        source.replace(needle, 'nivel = legacy["nivel"]'), encoding="utf-8"
    )
    (tmp_path / "check_cell_conformance.py").write_text(
        (MODULE_PATH.parents[0] / "check_cell_conformance.py").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (tmp_path / "resolver_asignacion.py").write_text(
        MODULE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    mutant = _load_module_from(mutant_path, "registry_ops_nivel_mutant")
    _base_agents, _, _ = _round3_fixture(tmp_path / "base")
    edited_agents, _, _ = _round3_fixture(tmp_path / "edited")
    edited = json.loads(edited_agents.read_text(encoding="utf-8"))
    edited["celdas"]["im"]["nivel"] = "premium"
    edited_agents.write_text(json.dumps(edited), encoding="utf-8")

    def run(module, agents, root):
        root.mkdir(parents=True, exist_ok=True)
        registry = root / "registry.json"
        roster = root / "roster.json"
        registry.write_text(json.dumps({"sessions": []}), encoding="utf-8")
        roster.write_text(
            json.dumps({"active_roles": {"orquestador": {"estado": "ACTIVO"}}}),
            encoding="utf-8",
        )
        args = _alta_args(module, agents, registry, "im", apply=True)
        args.extend(["--roster", str(roster)])
        assert module.main(args) == 0
        return json.loads(registry.read_text(encoding="utf-8"))["sessions"][0]

    control = run(
        _load_registry_ops(name="registry_ops_nivel_control"),
        edited_agents,
        tmp_path / "control",
    )
    mutant_result = run(mutant, edited_agents, tmp_path / "mutant")
    assert control["celda"]["nivel"] == "medio"
    assert mutant_result["celda"]["nivel"] == "premium"


def test_hashed_alta_default_agents_json_and_resolution_error(tmp_path):
    """Before: --celda-de puede omitir agents. During: usa default y falla cerrado si la fuente es ilegible. After: rc 2 solo ante error real."""
    registry_ops = _load_registry_ops()
    agents, registry, _roster = _round3_fixture(tmp_path)
    args = _alta_args(registry_ops, agents, registry, "im", include_agents=False)
    assert registry_ops.main(args) == 0
    broken = _alta_args(registry_ops, tmp_path / "missing.json", registry, "im")
    assert registry_ops.main(broken) == 2
    parsed = registry_ops._parser().parse_args(broken)
    with pytest.raises(registry_ops.RegistryError) as caught:
        registry_ops._session_for_alta(parsed, {"sessions": []})
    assert caught.value.code == registry_ops.RC_INVALID


def test_hashed_alta_rejects_non_uuid_order_message_id(tmp_path):
    """Before: el orden identifica una orden UUID. During: pasa texto invalido. After: RegistryError rc 2 y mensaje claro."""
    registry_ops = _load_registry_ops()
    agents, registry, _roster = _round3_fixture(tmp_path)
    args = _alta_args(registry_ops, agents, registry, "im", order_id="not-a-uuid")
    parsed = registry_ops._parser().parse_args(args)
    with pytest.raises(registry_ops.RegistryError, match="UUID") as caught:
        registry_ops._session_for_alta(parsed, {"sessions": []})
    assert caught.value.code == registry_ops.RC_INVALID


def test_hashed_builder_thread_id_is_preserved_and_pairing_uses_it(tmp_path):
    """Before: builder hashado puede declarar hilo. During: alta y pairing leen el threadId. After: la sesion es conforme."""
    registry_ops = _load_registry_ops()
    agents, registry, roster = _round3_fixture(tmp_path)
    args = _alta_args(
        registry_ops,
        agents,
        registry,
        "im",
        apply=True,
        builder_thread="thread:delegated-task:builder-r3",
    )
    args.extend(["--roster", str(roster)])
    assert registry_ops.main(args) == 0
    saved = json.loads(registry.read_text(encoding="utf-8"))["sessions"][0]
    assert saved["celda"]["builder"]["threadId"] == "thread:delegated-task:builder-r3"
    assert saved["celda"]["builder"]["name"]
    assert saved["celda_asignacion"]
    checker = _load_module_from(
        MODULE_PATH.parents[0] / "check_cell_conformance.py", "checker_builder_thread"
    )
    assert checker.check_im([saved], "2026-11-24", agents_json=agents) == 0
    store = tmp_path / "pairing.sqlite"
    connection = sqlite3.connect(store)
    connection.execute(
        "CREATE TABLE orchestration_v2_projection_threads ("
        "thread_id TEXT PRIMARY KEY, deleted_at TEXT, payload_json TEXT, "
        "provider_instance_id TEXT)"
    )
    connection.execute(
        "INSERT INTO orchestration_v2_projection_threads VALUES (?,?,?,?)",
        (
            "thread:delegated-task:builder-r3",
            None,
            json.dumps(
                {
                    "lineage": {
                        "parentThreadId": saved["threadId"],
                        "relationshipToParent": "subagent",
                    }
                }
            ),
            None,
        ),
    )
    connection.commit()
    connection.close()
    assert checker.check_pairing([saved], "2026-11-24", store) == 0


def test_mutation_manual_celda_accepted_without_warning(tmp_path, capsys):
    """Before: el control real avisa sobre --celda. During: muta una copia para quitar el aviso. After: el caso de aviso deja de pasar."""
    source = (MODULE_PATH.parents[0] / "registry_ops.py").read_text(encoding="utf-8")
    needle = 'print("registry_ops: DEPRECADO --celda", file=sys.stderr)'
    assert source.count(needle) == 1
    mutant_path = tmp_path / "registry_ops_mutant.py"
    mutant_path.write_text(source.replace(needle, "pass"), encoding="utf-8")
    (tmp_path / "check_cell_conformance.py").write_text(
        (MODULE_PATH.parents[0] / "check_cell_conformance.py").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    mutant = _load_module_from(mutant_path, "registry_ops_manual_mutant")
    agents, registry, _roster = _round3_fixture(tmp_path / "manual")
    manual = {
        "builder": "codex gpt-5.6-luna",
        "revisor": "gemini gemini-3.8-flash-high",
        "v1": "codex gpt-5.6-luna",
    }
    args = _alta_args(mutant, agents, registry, "im", cell=manual)
    for flag in ("--celda-de", "--orden-message-id", "--motivo"):
        index = args.index(flag)
        del args[index : index + 2]
    assert mutant.main(args) == 0
    assert "DEPRECADO --celda" not in capsys.readouterr().err


def test_m01_real_and_fixture_have_exact_valid_posts():
    """Before: hay declaracion real y fixture. During: se cargan ambas. After: cada puesto cumple el esquema."""
    module = _load_module()
    for path in (module.DEFAULT_AGENTS_JSON, None):
        if path is None:
            document, assignments = {"asignaciones": _declaration()}, _declaration()
        else:
            document, assignments = module.load_declaration(path)
        assert list(assignments) == list(module.PUESTOS)
        for data in assignments.values():
            assert isinstance(data["candidatos"], list) and data["candidatos"]
            assert data["nivel"] in module.NIVELES
            assert isinstance(data["refugio"], list) and data["refugio"]
            assert isinstance(data["orden"], dict) and "messageId" in data["orden"]
        assert isinstance(document["asignaciones"], dict)


def test_mutation_missing_refugio_fails_declaration(tmp_path):
    """Before: existe una copia valida. During: elimina un refugio solo en la copia. After: falla la copia y la original sigue valida."""
    module = _load_module()
    document, _ = module.load_declaration(module.DEFAULT_AGENTS_JSON)
    copy_document = json.loads(json.dumps(document))
    del copy_document["asignaciones"]["co"]["refugio"]
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(copy_document), encoding="utf-8")
    with pytest.raises(module.AsignacionError):
        module.load_declaration(path)
    module.load_declaration(module.DEFAULT_AGENTS_JSON)


def test_m03_excludes_family_before_selecting_next_candidate():
    """Before: tres candidatos ordenados por familia y nivel. During: excluye f1. After: elige c2 y registra solo el descarte familiar."""
    module, assignments, backends = _three_candidate_fixture()
    result = module.resolve(assignments, "co", backends, excluir_familias=("f1",))
    assert result["candidato"] == {"backend_key": "C2"}
    assert result["saltados"] == [
        {"candidato": {"backend_key": "C1"}, "motivo": "familia"}
    ]


def test_m03_rejects_premium_before_pending_check():
    """Before: el unico candidato premium esta pendiente y el puesto es medio. During: resuelve. After: el motivo es nivel."""
    module = _load_module()
    assignments = _declaration()
    assignments["co"] = {
        "candidatos": [{"backend_key": "PREMIUM"}],
        "nivel": "medio",
        "refugio": [{"backend_key": "BA05", "cuenta": "codex"}],
        "orden": {"messageId": None},
    }
    backends = {"PREMIUM": _backend("PREMIUM", "f", "premium")}
    with pytest.raises(module.SinCandidatoError) as error:
        module.resolve(assignments, "co", backends)
    assert error.value.saltados == [
        {"candidato": {"backend_key": "PREMIUM"}, "motivo": "nivel"}
    ]


def test_mutation_ignoring_excluir_familia_returns_first_candidate(tmp_path):
    """Before: el modulo real excluye f1. During: muta una copia aislada. After: solo el mutante devuelve c1."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    needle = 'if info["familia"].casefold() in excluded:'
    assert source.count(needle) == 1
    mutant_path = tmp_path / "resolver_asignacion_mutant.py"
    mutant_path.write_text(source.replace(needle, "if False:"), encoding="utf-8")
    mutant = _load_module_from(mutant_path, "resolver_asignacion_mutant_family")
    real, assignments, backends = _three_candidate_fixture()
    assert (
        real.resolve(assignments, "co", backends, excluir_familias=("f1",))[
            "candidato"
        ]["backend_key"]
        == "C2"
    )
    assert (
        mutant.resolve(assignments, "co", backends, excluir_familias=("f1",))[
            "candidato"
        ]["backend_key"]
        == "C1"
    )


def test_m04_skips_pending_candidate_and_reports_all_pending():
    """Before: el primer candidato hereda orden nula y el segundo tiene UUID. During: resuelve. After: registra pendiente y falla si todos lo son."""
    module = _load_module()
    assignments = _declaration()
    assignments["co"] = {
        "candidatos": [
            {"backend_key": "C1"},
            {"backend_key": "C2", "orden": _valid_uuid()},
        ],
        "nivel": "medio",
        "refugio": [{"backend_key": "BA05", "cuenta": "codex"}],
        "orden": {"messageId": None},
    }
    backends = {
        "C1": _backend("C1", "f1", "medio"),
        "C2": _backend("C2", "f2", "medio"),
    }
    result = module.resolve(assignments, "co", backends)
    assert result["candidato"]["backend_key"] == "C2"
    assert result["saltados"] == [
        {"candidato": {"backend_key": "C1"}, "motivo": "pendiente_confirmacion"}
    ]
    assignments["co"]["candidatos"] = [{"backend_key": "C1"}]
    with pytest.raises(module.SinCandidatoError) as error:
        module.resolve(assignments, "co", backends)
    assert "pendiente_confirmacion" in str(error.value)
    assert error.value.saltados[0]["motivo"] == "pendiente_confirmacion"


def test_mutation_pending_treated_as_valid_returns_pending_candidate(tmp_path):
    """Before: el modulo real descarta pendientes. During: fuerza is_pendiente a falso en una copia. After: el mutante devuelve c1."""
    module = _load_module()
    source = MODULE_PATH.read_text(encoding="utf-8")
    needle = "def is_pendiente(puesto_data, candidate):"
    start = source.index(needle)
    body_start = source.index("    return", start)
    body_end = source.index("\n\n", body_start)
    mutant_source = source[:body_start] + "    return False" + source[body_end:]
    mutant_path = tmp_path / "resolver_asignacion_mutant.py"
    mutant_path.write_text(mutant_source, encoding="utf-8")
    mutant = _load_module_from(mutant_path, "resolver_asignacion_mutant_pending")
    assignments = _declaration()
    assignments["co"]["candidatos"] = [{"backend_key": "C1"}]
    assignments["co"]["orden"] = {"messageId": None}
    backends = {"C1": _backend("C1", "f1", "medio")}
    with pytest.raises(module.SinCandidatoError):
        module.resolve(assignments, "co", backends)
    assert (
        mutant.resolve(assignments, "co", backends)["candidato"]["backend_key"] == "C1"
    )


def test_m12_real_backends_and_required_assignments():
    """Before: existe la declaracion real. During: inspecciona backends y puestos IM/TR. After: coincide con el registro medido."""
    module = _load_module()
    document, assignments = module.load_declaration(module.DEFAULT_AGENTS_JSON)
    expected = [
        "kilo",
        "codex",
        "opencode",
        "claude",
        "nan_api",
        "nvidia_api",
        "groq_api",
        "openrouter_api",
        "tokenharbor_api",
        "gemini_api",
        "cohere_api",
        "mistral_api",
        "llm7_api",
        "kiosapi_api",
        "anthropic_api",
        "default",
    ]
    assert list(document["backends"]) == expected
    revisor = assignments["im.revisor"]["candidatos"][0]
    assert revisor["familia"] == "claude"
    assert revisor["instanceId"] == "claudeAgent"
    assert revisor["model"] == "claude-sonnet-5"
    assert (
        module.effective_orden(assignments["im.revisor"], revisor)
        == "2ebbe20e-2f64-48ad-b298-3187da4861cc"
    )
    assert assignments["im.revisor"]["refugio"] == [
        {"backend_key": "BA05", "cuenta": "codex"},
        {"backend_key": "BA269", "cuenta": "brabander"},
    ]
    im_v1 = module.resolve(
        assignments, "im.v1", document["ensemble_registry"]["backend_keys"]
    )
    tr_revisor = module.resolve(
        assignments, "tr.revisor", document["ensemble_registry"]["backend_keys"]
    )
    assert (im_v1["candidato"], im_v1["info"]["model"], im_v1["orden"]) == (
        {"backend_key": "BA258"},
        "nan/qwen3.6",
        "894583da-d3c1-4dcb-828b-26d677fb7e07",
    )
    assert assignments["im.v1"]["candidatos"] == [
        {"backend_key": "BA258"},
        {"backend_key": "BA259"},
    ]
    assert (
        tr_revisor["candidato"],
        tr_revisor["info"]["model"],
        tr_revisor["orden"],
    ) == (
        {"backend_key": "BA05"},
        "gpt-5.6-luna",
        "f130d0e9-6480-4a2c-adb0-b68fd31b9fc0",
    )


def test_mutation_extra_backend_key_changes_backends_list(tmp_path):
    """Before: hay una lista base de backends. During: anade una clave solo en una copia. After: la lista deja de coincidir."""
    module = _load_module()
    document, _ = module.load_declaration(module.DEFAULT_AGENTS_JSON)
    expected = list(document["backends"])
    mutated = json.loads(json.dumps(document))
    mutated["backends"]["extra_backend"] = {}
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert list(loaded["backends"]) != expected


def test_real_derived_eligible_and_pending_posts():
    """Before: existe la declaracion real. During: deriva cobertura y resuelve pendientes. After: respeta orden y filtros."""
    module = _load_module()
    document, assignments = module.load_declaration(module.DEFAULT_AGENTS_JSON)
    assert module.derive_eligible(assignments, document) == [
        "BA258",
        "BA259",
        "BA150",
        "BA151",
    ]
    assert not set(module.derive_eligible(assignments, document)) & {
        "BA05",
        "BA269",
        "BA02",
        "BA03",
        "BA06",
        "BA254",
    }
    backends = document["ensemble_registry"]["backend_keys"]
    for post in (
        "co_subagentes",
        "supervisora",
        "im.subagentes",
        "tr.subagentes",
        "lente_de_cierre",
        "bucle_retro",
    ):
        with pytest.raises(module.SinCandidatoError) as error:
            module.resolve(assignments, post, backends)
        assert error.value.saltados and all(
            item["motivo"] == "pendiente_confirmacion" for item in error.value.saltados
        )
    first = module.resolve(
        assignments, "lentes_p34", backends, excluir_familias=("codex", "claude")
    )
    second = module.resolve(
        assignments,
        "lentes_p34",
        backends,
        excluir_familias=("codex", "claude", "qwen"),
    )
    assert (first["candidato"]["backend_key"], first["info"]["familia"]) == (
        "BA258",
        "qwen",
    )
    assert (second["info"]["tipo"], second["info"]["familia"]) == (
        "t3_session",
        "gemini",
    )
    assert second["candidato"]["instanceId"] == "antigravity"


def test_cli_main_success_pending_and_unreadable(tmp_path, capsys):
    """Before: hay declaracion real, puesto pendiente y ruta inexistente. During: ejecuta main en tres modos. After: devuelve 0, 2 y 3."""
    module = _load_module()
    assert module.main(["im.revisor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["puesto"] == "im.revisor"
    assert module.main(["co_subagentes"]) == 2
    assert "pendiente_confirmacion" in capsys.readouterr().err
    assert (
        module.main(
            [
                "lentes_p34",
                "--excluir-familia",
                "codex",
                "--excluir-familia",
                "claude",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidato"]["backend_key"] == "BA258"
    assert (
        module.main(["im.revisor", "--agents-json", str(tmp_path / "missing.json")])
        == 3
    )
    assert capsys.readouterr().err


def test_hash_is_stable_scoped_and_changes_with_assignment():
    """Before: hay declaracion real. During: modifica copias dentro y fuera del subarbol. After: solo el cambio interno altera hash."""
    module = _load_module()
    document, assignments = module.load_declaration(module.DEFAULT_AGENTS_JSON)
    first = module.short_hash(assignments)
    assert first == module.short_hash(assignments)
    changed = json.loads(json.dumps(assignments))
    changed["co"]["candidatos"][0]["backend_key"] = "BA269"
    assert module.short_hash(changed) != first
    document_copy = json.loads(json.dumps(document))
    document_copy["role_models"]["BUILDER"] = "changed-outside-subtree"
    assert module.short_hash(document["asignaciones"]) == module.short_hash(
        document_copy["asignaciones"]
    )


@pytest.mark.parametrize("motivo", ["", "   "], ids=["vacio", "espacios"])
@pytest.mark.parametrize("apply", [False, True], ids=["dry-run", "apply"])
def test_hashed_alta_rejects_blank_motivo(tmp_path, motivo, apply):
    """Before: el motivo puede ser vacio textual. During: intenta alta hashed. After: RegistryError rc 2 en dry-run y apply."""
    registry_ops = _load_registry_ops()
    agents, registry, roster = _round3_fixture(tmp_path)
    args = _alta_args(registry_ops, agents, registry, "im", apply=apply, motivo=motivo)
    if apply:
        args.extend(["--roster", str(roster)])
    assert registry_ops.main(args) == 2


def test_hashed_alta_accepts_nonblank_motivo(tmp_path):
    """Before: un motivo textual no vacio identifica la alta. During: ejecuta dry-run. After: rc 0."""
    registry_ops = _load_registry_ops()
    agents, registry, _roster = _round3_fixture(tmp_path)
    args = _alta_args(registry_ops, agents, registry, "im", motivo="motivo valido")
    assert registry_ops.main(args) == 0


def test_mutation_blank_motivo_accepted_without_strip(tmp_path, capsys):
    """Before: el control real rechaza espacios. During: muta una copia para omitir strip. After: el mutante crea recibo que el checker rechaza."""
    source = (MODULE_PATH.parents[0] / "registry_ops.py").read_text(encoding="utf-8")
    needle = "if not isinstance(motivo, str) or not motivo.strip():"
    assert source.count(needle) == 1
    mutant_path = tmp_path / "registry_ops_motivo_mutant.py"
    mutant_path.write_text(
        source.replace(needle, "if not isinstance(motivo, str) or not motivo:"),
        encoding="utf-8",
    )
    (tmp_path / "check_cell_conformance.py").write_text(
        (MODULE_PATH.parents[0] / "check_cell_conformance.py").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (tmp_path / "resolver_asignacion.py").write_text(
        MODULE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    mutant = _load_module_from(mutant_path, "registry_ops_motivo_mutant")
    agents, registry, _roster = _round3_fixture(tmp_path / "fixture")
    args = _alta_args(mutant, agents, registry, "im", motivo="   ")
    assert mutant.main(args) == 0
    item = json.loads(capsys.readouterr().out)
    checker = _load_module_from(
        tmp_path / "check_cell_conformance.py", "checker_motivo_mutant"
    )
    assert checker.check_im([item], "2026-11-24", agents_json=agents) == 2


def _assert_current_eligible_note(document):
    """Valida el contrato vigente de la nota de cobertura derivada."""
    note = document["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]["note"]
    assert isinstance(note, str)
    assert "asignaciones.lentes_p34" in note
    assert "render_asignaciones.py --apply" in note
    assert all(key not in note for key in ("BA03", "BA254", "BA02", "BA06"))


def test_real_eligible_note_describes_derived_view():
    """Before: la nota acompana la vista derivada. During: lee agents.json real. After: conserva instrucciones y no enumera claves antiguas."""
    document = json.loads(
        (MODULE_PATH.parents[2] / ".agent" / "config" / "agents.json").read_text(
            encoding="utf-8"
        )
    )
    _assert_current_eligible_note(document)


def test_mutation_stale_eligible_note_cited_old_keys(tmp_path):
    """Before: una copia sana cumple la nota. During: sustituye la nota por la antigua. After: las mismas aserciones detectan la mutacion."""
    source = MODULE_PATH.parents[2] / ".agent" / "config" / "agents.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    mutated = json.loads(json.dumps(document))
    mutated["ensemble_registry"]["eligible_coverage"]["MANAGER_REVIEW:repo_motor"][
        "note"
    ] = "BA03 y BA254 y BA02 y BA06 eran elegibles."
    with pytest.raises(AssertionError):
        _assert_current_eligible_note(mutated)
