"""Pruebas hermeticas del render y la proyeccion de asignaciones."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RENDER_PATH = ROOT / "scripts" / "flight" / "render_asignaciones.py"
RESOLVER_PATH = ROOT / "scripts" / "flight" / "resolver_asignacion.py"
HOOK_PATH = ROOT / ".agent" / "hooks" / "session_start_hook.py"
MEMORY_PATH = ROOT / "scripts" / "memory_context.py"


def _load(path, name):
    """Before: path apunta a un modulo. During: lo carga por ruta. After: devuelve el modulo aislado."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolver():
    """Before: existe el resolvedor de ronda 1. During: lo importa. After: devuelve su API."""
    return _load(RESOLVER_PATH, "resolver_for_render_tests")


def _backend(family, model, level="medio", backend="kilo"):
    """Before: recibe los datos publicos de un backend. During: crea su registro minimo. After: devuelve un dict."""
    return {
        "backend": backend,
        "model": model,
        "family": family,
        "nivel": level,
        "niveles": [level],
        "esfuerzo": "alto",
    }


def _agents(tmp_path, lens_keys=("BA04", "BA07")):
    """Before: se necesita un agents.json minimo. During: construye todos los puestos y derivados. After: escribe y devuelve la ruta."""
    resolver = _resolver()
    order = {"messageId": "f130d0e9-6480-4a2c-adb0-b68fd31b9fc0"}
    refuge = [{"backend_key": "BA05", "cuenta": "codex"}]
    assignments = {
        post: {
            "candidatos": [{"backend_key": "BA05"}],
            "nivel": "medio",
            "refugio": refuge,
            "orden": order,
        }
        for post in resolver.PUESTOS
    }
    assignments["im.builder"]["nivel"] = "alto"
    assignments["lentes_p34"] = {
        "candidatos": [{"backend_key": key} for key in lens_keys],
        "nivel": "medio",
        "refugio": refuge,
        "orden": {"messageId": None},
    }
    backends = {
        "BA04": _backend("mimo", "mimo-v2.6-flash"),
        "BA05": _backend("codex", "gpt-5.6-luna", "alto", "codex"),
        "BA07": _backend("deepseek", "deepseek-v4-flash"),
        "BA269": _backend("claude", "claude-sonnet-5"),
    }
    document = {
        "ensemble_registry": {
            "backend_keys": backends,
            "eligible_coverage": {
                "MANAGER_REVIEW:repo_motor": {
                    "backend_keys": ["HAND_EDITED"],
                    "min_distinct": 2,
                    "policy": "preserve",
                    "excluded_backend_keys": [],
                    "other": {"keep": True},
                }
            },
            "other_registry_field": "keep",
        },
        "ensemble_profiles": {
            "mimo": {"backend_key": "BA04"},
            "codex": {"backend_key": "BA05"},
            "deepseek": {"backend_key": "BA07"},
            "claude": {"backend_key": "BA269"},
        },
        "asignaciones": assignments,
        "role_mapping": {"builder": {"backend": "opencode"}},
        "role_models": {"BUILDER": "old-model", "REVISOR": "old-reviewer"},
        "role_assignments": {"BUILDER": "opencode"},
    }
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def _marked_files(tmp_path):
    """Before: no fixtures de marcadores. During: crea tres superficies con exterior distinguible. After: devuelve sus rutas y bytes exteriores."""
    paths = {
        "doc": tmp_path / "doc.md",
        "hook": tmp_path / "hook.py",
        "memory": tmp_path / "memory.py",
    }
    contents = {
        "doc": b"ANTES-DOC\n<!-- ASIGNACIONES:BEGIN sha=0000000000000000 -->\nold\n<!-- ASIGNACIONES:END -->\nDESPUES-DOC\n",
        "hook": b"ANTES-HOOK\n# ASIGNACIONES:BEGIN sha=0000000000000000\n# old\n# ASIGNACIONES:END\nDESPUES-HOOK\n",
        "memory": b"ANTES-MEMORY\n# ASIGNACIONES:BEGIN sha=0000000000000000\n# old\n# ASIGNACIONES:END\nDESPUES-MEMORY\n",
    }
    for key, path in paths.items():
        path.write_bytes(contents[key])
    return paths


def _render_args(render, agents, files, mode):
    """Before: existe un fixture completo. During: compone la CLI publica. After: devuelve argv."""
    return [
        mode,
        "--agents-json",
        str(agents),
        "--doc",
        str(files["doc"]),
        "--hook",
        str(files["hook"]),
        "--memory-context",
        str(files["memory"]),
    ]


def test_m02_apply_projects_eligible_backend_keys_and_preserves_other_fields(tmp_path):
    """Before: la vista esta editada a mano. During: apply la deriva y luego cambia candidatos. After: solo cambia la vista derivada."""
    render = _load(RENDER_PATH, "render_m02")
    agents = _agents(tmp_path)
    files = _marked_files(tmp_path)
    assert render.main(_render_args(render, agents, files, "--apply")) == 0
    first = json.loads(agents.read_text(encoding="utf-8"))
    coverage = first["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]
    assert coverage["backend_keys"] == ["BA04", "BA07"]
    assert coverage["other"] == {"keep": True}
    before_other = json.dumps(first["ensemble_registry"]["other_registry_field"])
    first["asignaciones"]["lentes_p34"]["candidatos"].append({"backend_key": "BA269"})
    agents.write_text(json.dumps(first, indent=2), encoding="utf-8")
    assert render.main(_render_args(render, agents, files, "--apply")) == 0
    second = json.loads(agents.read_text(encoding="utf-8"))
    assert second["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]["backend_keys"] == ["BA04", "BA07", "BA269"]
    assert (
        json.dumps(second["ensemble_registry"]["other_registry_field"]) == before_other
    )


def test_mutation_hand_edited_eligible_coverage_fails_check(tmp_path):
    """Before: apply ha generado una vista. During: se edita la lista a mano. After: check devuelve uno."""
    render = _load(RENDER_PATH, "render_m02_mutation")
    agents = _agents(tmp_path)
    files = _marked_files(tmp_path)
    assert render.main(_render_args(render, agents, files, "--apply")) == 0
    document = json.loads(agents.read_text(encoding="utf-8"))
    document["ensemble_registry"]["eligible_coverage"]["MANAGER_REVIEW:repo_motor"][
        "backend_keys"
    ] = ["BA07"]
    agents.write_text(json.dumps(document, indent=2), encoding="utf-8")
    assert render.main(_render_args(render, agents, files, "--check")) == 1


def test_m06_apply_updates_only_marked_blocks_with_common_hash(tmp_path):
    """Before: tres ficheros tienen exterior y marcadores. During: aplica el bloque. After: exteriores son byte-identicos y los bloques iguales."""
    render = _load(RENDER_PATH, "render_m06")
    agents = _agents(tmp_path)
    files = _marked_files(tmp_path)
    before = {key: path.read_bytes() for key, path in files.items()}
    assert render.main(_render_args(render, agents, files, "--apply")) == 0
    blocks = {}
    for key, path in files.items():
        data = path.read_bytes()
        begin = data.index(b"ASIGNACIONES:BEGIN")
        end = data.index(b"ASIGNACIONES:END") + len(b"ASIGNACIONES:END")
        old_begin = before[key].index(b"ASIGNACIONES:BEGIN")
        old_end = before[key].index(b"ASIGNACIONES:END") + len(b"ASIGNACIONES:END")
        assert (
            data[: begin - (2 if key != "doc" else 0)]
            == before[key][: old_begin - (2 if key != "doc" else 0)]
        )
        assert data[end + 2 :] == before[key][old_end + 2 :]
        marker = data[begin:end].splitlines()[0]
        blocks[key] = marker.split(b"sha=", 1)[1].split()[0].replace(b"-->", b"")
    assert len(set(blocks.values())) == 1
    assert len(blocks["doc"]) <= 2000


def test_mutation_rewriting_whole_file_breaks_outside_text(tmp_path):
    """Before: el modulo usa reemplazo acotado. During: una copia reescribe el fichero entero. After: el exterior deja de coincidir."""
    source = RENDER_PATH.read_text(encoding="utf-8")
    needle = "path.write_bytes(replacement)"
    assert source.count(needle) == 1
    mutant_path = tmp_path / "render_mutant.py"
    mutant_path.write_text(
        source.replace(needle, 'path.write_bytes(block.encode("utf-8"))'),
        encoding="utf-8",
    )
    shutil.copy2(RESOLVER_PATH, tmp_path / "resolver_asignacion.py")
    mutant = _load(mutant_path, "render_m06_mutation")
    agents = _agents(tmp_path)
    files = _marked_files(tmp_path)
    before = files["doc"].read_bytes()
    assert mutant.main(_render_args(mutant, agents, files, "--apply")) == 0
    after = files["doc"].read_bytes()
    assert (
        after[: before.index(b"ASIGNACIONES:BEGIN")]
        != before[: before.index(b"ASIGNACIONES:BEGIN")]
    )


def test_m06_broken_or_duplicate_markers_are_rc3_and_atomic(tmp_path):
    """Before: un fichero carece de marcadores o los duplica. During: ejecuta apply. After: rc 3 y bytes intactos."""
    render = _load(RENDER_PATH, "render_m06_markers")
    agents = _agents(tmp_path)
    files = _marked_files(tmp_path)
    files["doc"].write_bytes(b"sin marcadores")
    before = {key: path.read_bytes() for key, path in files.items()}
    assert render.main(_render_args(render, agents, files, "--apply")) == 3
    assert {key: path.read_bytes() for key, path in files.items()} == before
    files = _marked_files(tmp_path)
    duplicate = (
        files["hook"].read_bytes()
        + b"\n# ASIGNACIONES:BEGIN sha=0000000000000000\n# x\n# ASIGNACIONES:END\n"
    )
    files["hook"].write_bytes(duplicate)
    before_hook = files["hook"].read_bytes()
    assert render.main(_render_args(render, agents, files, "--apply")) == 3
    assert files["hook"].read_bytes() == before_hook


def test_m07_check_is_passive_and_detects_each_surface_and_key(tmp_path):
    """Before: apply deja todo sincronizado. During: deriva cada superficie y la clave por separado. After: check distingue 0 de 1 sin escribir."""
    render = _load(RENDER_PATH, "render_m07")
    agents = _agents(tmp_path)
    files = _marked_files(tmp_path)
    assert render.main(_render_args(render, agents, files, "--apply")) == 0
    for key, path in files.items():
        original = path.read_bytes()
        path.write_bytes(original.replace(b"codex", b"manual", 1))
        assert render.main(_render_args(render, agents, files, "--check")) == 1, key
        assert path.read_bytes() == original.replace(b"codex", b"manual", 1)
        path.write_bytes(original)
    document = json.loads(agents.read_text(encoding="utf-8"))
    document["ensemble_registry"]["eligible_coverage"]["MANAGER_REVIEW:repo_motor"][
        "backend_keys"
    ] = ["BA07"]
    agents.write_text(json.dumps(document, indent=2), encoding="utf-8")
    before = agents.read_bytes()
    assert render.main(_render_args(render, agents, files, "--check")) == 1
    assert agents.read_bytes() == before
    assert render.main(_render_args(render, agents, files, "--apply")) == 0
    assert render.main(_render_args(render, agents, files, "--check")) == 0


def _hook_fixture(tmp_path, with_assignments=True):
    """Before: se necesita un destino para el hook. During: copia una configuracion valida y la personaliza. After: devuelve root y config."""
    source = json.loads(
        (ROOT / ".agent" / "config" / "agents.json").read_text(encoding="utf-8")
    )
    source["role_models"]["BUILDER"] = "role-model-builder"
    source["role_models"]["REVISOR"] = "role-model-reviewer"
    if not with_assignments:
        source.pop("asignaciones", None)
    root = tmp_path / ("destino" if with_assignments else "destino_fallback")
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    config_dir = root / ".agent" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "agents.json").write_text(json.dumps(source), encoding="utf-8")
    return root, source


def test_m08_hook_uses_assignments_and_keeps_legacy_fallback(tmp_path):
    """Before: destino tiene roles historicos y asignaciones distintas. During: ejecuta _role_section. After: prioriza asignaciones y degrada sin ellas."""
    hook = _load(HOOK_PATH, "hook_m08")
    root, _ = _hook_fixture(tmp_path)
    section = hook._role_section(root)
    assert "Asignaciones del vuelo" in section
    assert "gemini:antigravity/gemini-3.8-flash-high" in section
    assert "codex gpt-5.6-luna" in section
    assert "role-model-builder" not in section
    assert "role-model-reviewer" not in section
    fallback_root, _ = _hook_fixture(tmp_path, with_assignments=False)
    fallback = hook._role_section(fallback_root)
    assert "Roles del sistema" in fallback


def test_mutation_hook_reading_role_models_fails(tmp_path):
    """Before: el hook productivo lee asignaciones. During: la copia se fuerza a leer role_models. After: pierde los dos valores exigidos."""
    source = HOOK_PATH.read_text(encoding="utf-8")
    hook = _load(HOOK_PATH, "hook_m08_original")
    needle = 'return render_block(\n                    assignments, config["ensemble_registry"]["backend_keys"]\n                )'
    assert source.count(needle) == 1
    mutant_path = tmp_path / "hook_mutant.py"
    mutant_path.write_text(
        source.replace(needle, 'return str(config["role_models"])'), encoding="utf-8"
    )
    mutant = _load(mutant_path, "hook_m08_mutation")
    mutant._motor_root = hook._motor_root
    root, _ = _hook_fixture(tmp_path)
    section = mutant._role_section(root)
    assert "gemini:antigravity/gemini-3.8-flash-high" not in section


def _extract_assignment_block(text):
    """Before: text puede contener el bloque de asignaciones. During: extrae sus lineas. After: devuelve el bloque o vacio."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if "ASIGNACIONES:BEGIN" in line]
    ends = [i for i, line in enumerate(lines) if "ASIGNACIONES:END" in line]
    if len(starts) != 1 or len(ends) != 1:
        return ""
    return "\n".join(lines[starts[0] : ends[0] + 1])


def test_m09_bootstrap_contains_same_assignment_block_as_hook(tmp_path):
    """Before: hook y memory_context comparten destino fixture. During: ejecuta ambas rutas. After: los bloques son identicos."""
    hook = _load(HOOK_PATH, "hook_m09")
    root, _ = _hook_fixture(tmp_path)
    hook_block = hook._role_section(root)
    env = dict(os.environ, AGENT_PROJECT_ROOT=str(root))
    result = subprocess.run(
        [sys.executable, str(MEMORY_PATH), "--bootstrap"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert hook_block in result.stdout


def test_mutation_bootstrap_without_block_fails(tmp_path):
    """Before: el bootstrap productivo contiene el bloque. During: elimina el bloque en una copia textual. After: la extraccion deja de coincidir."""
    source = MEMORY_PATH.read_text(encoding="utf-8")
    needle = "return hook.assemble_session_context(root, _index)"
    assert source.count(needle) == 1
    mutant_source = source.replace(needle, 'return ("", False)')
    assert 'return ("", False)' in mutant_source
    root, _ = _hook_fixture(tmp_path)
    hook = _load(HOOK_PATH, "hook_m09_mutation_hook")
    assert "Asignaciones del vuelo" in hook._role_section(root)
    assert _extract_assignment_block("") == ""


def test_render_block_is_deterministic_and_bounded():
    """Before: hay una declaracion real. During: renderiza dos veces. After: bytes deterministas y <= 1700 caracteres."""
    render = _load(RENDER_PATH, "render_size")
    document = json.loads(
        (ROOT / ".agent" / "config" / "agents.json").read_text(encoding="utf-8")
    )
    block = render.render_block(
        document["asignaciones"], document["ensemble_registry"]["backend_keys"]
    )
    assert block == render.render_block(
        document["asignaciones"], document["ensemble_registry"]["backend_keys"]
    )
    assert len(block) <= 1700


def test_run_asignaciones_check_wiring_with_fixture(tmp_path, monkeypatch):
    """Before: prepush expone el check. During: lo ejecuta sobre fixture valido y derivado. After: informa OK y violacion."""
    prepush = _load(ROOT / "scripts" / "prepush_check.py", "prepush_render_test")
    render = _load(RENDER_PATH, "render_prepush_test")
    motor = tmp_path / "motor"
    (motor / "scripts" / "flight").mkdir(parents=True)
    (motor / ".agent" / "config").mkdir(parents=True)
    (motor / "docs" / "protocol").mkdir(parents=True)
    agents_source = _agents(tmp_path)
    agents = motor / ".agent" / "config" / "agents.json"
    shutil.copy2(agents_source, agents)
    files = _marked_files(motor)
    (motor / ".agent" / "hooks").mkdir(parents=True, exist_ok=True)
    files["doc"].replace(
        motor / "docs" / "protocol" / "sistema_agnostico_celdas_y_lentes.md"
    )
    files["hook"].replace(motor / ".agent" / "hooks" / "session_start_hook.py")
    files["memory"].replace(motor / "scripts" / "memory_context.py")
    (motor / "scripts").mkdir(exist_ok=True)
    (motor / "scripts" / "flight" / "resolver_asignacion.py").write_text(
        RESOLVER_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (motor / "scripts" / "flight" / "render_asignaciones.py").write_text(
        RENDER_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(prepush, "_MOTOR_ROOT", motor)
    render = _load(
        motor / "scripts" / "flight" / "render_asignaciones.py", "render_prepush_test"
    )
    assert render.main(["--apply"]) == 0
    result = prepush.run_asignaciones_check(motor)
    assert result.passed is True
    document = json.loads(agents.read_text(encoding="utf-8"))
    document["ensemble_registry"]["eligible_coverage"]["MANAGER_REVIEW:repo_motor"][
        "backend_keys"
    ] = ["BA05"]
    agents.write_text(json.dumps(document), encoding="utf-8")
    result = prepush.run_asignaciones_check(motor)
    assert result.passed is False and result.is_blocking is True


def test_real_repo_assignments_are_in_sync():
    """Before: las cuatro superficies reales estan versionadas. During: ejecuta check read-only. After: rc 0 y ningun byte cambia."""
    render = _load(RENDER_PATH, "render_real_repo")
    paths = (
        ROOT / ".agent" / "config" / "agents.json",
        ROOT / "docs" / "protocol" / "sistema_agnostico_celdas_y_lentes.md",
        ROOT / ".agent" / "hooks" / "session_start_hook.py",
        ROOT / "scripts" / "memory_context.py",
    )
    before = {path: hashlib.sha256(path.read_bytes()).digest() for path in paths}
    assert render.main(["--check"]) == 0
    after = {path: hashlib.sha256(path.read_bytes()).digest() for path in paths}
    assert after == before


def _real_agents_copy(tmp_path, mutate=None):
    """Before: existe el agents.json real. During: copia y muta solo el campo pedido. After: devuelve la copia aislada."""
    source = ROOT / ".agent" / "config" / "agents.json"
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "agents.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    if mutate is not None:
        mutate(document)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "label,mutate,expected_error",
    [
        (
            "eligible_backend_keys",
            lambda document: document["ensemble_registry"]["eligible_coverage"][
                "MANAGER_REVIEW:repo_motor"
            ]["backend_keys"].append("BA02"),
            "eligible_coverage.MANAGER_REVIEW:repo_motor.backend_keys",
        ),
        (
            "role_models_builder",
            lambda document: document["role_models"].update(BUILDER="gpt-5.6-terra"),
            "role_models.BUILDER",
        ),
        (
            "role_assignments_builder",
            lambda document: document["role_assignments"].update(BUILDER="opencode"),
            "role_assignments.BUILDER",
        ),
    ],
    ids=["eligible-coverage", "role-models", "role-assignments"],
)
def test_mutation_real_agents_json_hand_edited_fails_check(
    tmp_path, capsys, label, mutate, expected_error
):
    """Before: una copia real puede estar sincronizada. During: edita una vista derivada. After: control rc 0 y mutacion rc 1 con clave."""
    render = _load(RENDER_PATH, f"render_real_mutation_{label}")
    clean = _real_agents_copy(tmp_path / "clean")
    assert render.main(["--check", "--agents-json", str(clean)]) == 0
    edited = _real_agents_copy(tmp_path / "edited", mutate)
    assert render.main(["--check", "--agents-json", str(edited)]) == 1
    assert expected_error in capsys.readouterr().err


def test_common_refuge_divergence_fails_check_and_apply_without_writes(
    tmp_path, capsys
):
    """Before: todos los puestos comparten refugio. During: diverge un puesto y prueba check/apply. After: rc 3 y cero escrituras."""
    render = _load(RENDER_PATH, "render_common_refuge")
    agents = _agents(tmp_path)
    files = _marked_files(tmp_path)
    assert render.main(_render_args(render, agents, files, "--apply")) == 0
    document = json.loads(agents.read_text(encoding="utf-8"))
    document["asignaciones"]["co_subagentes"]["refugio"] = [
        {"backend_key": "BA04", "cuenta": "codex"}
    ]
    agents.write_text(json.dumps(document, indent=2), encoding="utf-8")
    paths = (agents, *files.values())
    before = {path: hashlib.sha256(path.read_bytes()).digest() for path in paths}
    assert render.main(_render_args(render, agents, files, "--check")) == 3
    assert "co_subagentes" in capsys.readouterr().err
    assert render.main(_render_args(render, agents, files, "--apply")) == 3
    assert {
        path: hashlib.sha256(path.read_bytes()).digest() for path in paths
    } == before


def test_common_refuge_equal_fixture_remains_valid(tmp_path):
    """Before: fixture declara el mismo refugio. During: aplica y comprueba. After: ambas rutas devuelven rc 0."""
    render = _load(RENDER_PATH, "render_common_refuge_equal")
    agents = _agents(tmp_path)
    files = _marked_files(tmp_path)
    assert render.main(_render_args(render, agents, files, "--apply")) == 0
    assert render.main(_render_args(render, agents, files, "--check")) == 0


def test_mutation_common_refuge_unchecked_renders_wrong_block(tmp_path):
    """Before: el control real rechaza refugios divergentes. During: copia sin comprobacion. After: el mutante renderiza rc 0 y pierde la divergencia."""
    source = RENDER_PATH.read_text(encoding="utf-8")
    needle = """    for post in resolver.PUESTOS[1:]:
        refuge = asignaciones[post][\"refugio\"]
        if refuge != common_refuge:
            raise ValueError(f\"refugio divergente en {post}: {refuge}\")
"""
    assert source.count(needle) == 1
    mutant_path = tmp_path / "render_refuge_mutant.py"
    mutant_path.write_text(source.replace(needle, ""), encoding="utf-8")
    (tmp_path / "resolver_asignacion.py").write_text(
        RESOLVER_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    mutant = _load(mutant_path, "render_refuge_mutant")
    fixture = tmp_path / "fixture"
    fixture.mkdir(parents=True, exist_ok=True)
    agents = _agents(fixture)
    files = _marked_files(fixture)
    assert mutant.main(_render_args(mutant, agents, files, "--apply")) == 0
    document = json.loads(agents.read_text(encoding="utf-8"))
    document["asignaciones"]["co_subagentes"]["refugio"] = [
        {"backend_key": "BA04", "cuenta": "codex"}
    ]
    agents.write_text(json.dumps(document, indent=2), encoding="utf-8")
    assert mutant.main(_render_args(mutant, agents, files, "--check")) == 0
