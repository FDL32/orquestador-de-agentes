"""Seam-guard for the citable ensemble loop registry (WOT-2026-037b).

Single anti-drift source of truth: ``.agent/config/agents.json::ensemble_registry``.
Three branches, each with an executed mutation proving the guard bites:

(a) PARITY: docs/registry/loop_registry.md == projection(ensemble_registry).
    Mutation: hand-edit the .md -> RED.
(b) ZERO ORPHANS: every backend_key/loop_id referenced from ensemble_profiles /
    ensemble_pipelines / loop_shapes' own steps exists in the registry.
    Mutation: SYNTHETIC fixture with a dangling BA##/L### reference -> RED
    (there are 0 real BUC-/CHA- citations in prompts today, so this branch
    cannot depend on real prompt files without being an unreachable mutation).
(c) CCO-CONSOLIDATOR RULE: no step with function=="consolidator" appears in
    any loop_shape whose launched_from=="chat" (by DATA, not prose).
    Mutation: fixture with a chat-launched loop carrying a consolidator step
    -> RED.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import discover_loops as dl  # noqa: E402


AGENTS_CONFIG_PATH = PROJECT_ROOT / ".agent" / "config" / "agents.json"
REGISTRY_MD_PATH = PROJECT_ROOT / "docs" / "registry" / "loop_registry.md"


def _load_config() -> dict:
    return json.loads(AGENTS_CONFIG_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (a) Parity: loop_registry.md == projection(ensemble_registry)
# ---------------------------------------------------------------------------


def test_registry_md_exists():
    assert REGISTRY_MD_PATH.exists(), (
        "docs/registry/loop_registry.md must exist (WOT-2026-037b deliverable)"
    )


def test_registry_md_matches_live_projection():
    """PARITY branch. Mutation proof (executed manually, see execution_log.md):
    hand-appending a stray line to loop_registry.md makes this assertion RED
    because the file no longer equals render_registry_md(discover_loops())."""
    is_stale, diag = dl.check_registry_md_stale(
        config_path=AGENTS_CONFIG_PATH, bundle_root=PROJECT_ROOT
    )
    assert not is_stale, diag


def test_registry_md_projection_is_deterministic():
    """Same registry input renders the same markdown byte-for-byte twice."""
    result = dl.discover_loops(AGENTS_CONFIG_PATH)
    first = dl.render_registry_md(result)
    second = dl.render_registry_md(result)
    assert first == second


def test_parity_detector_flags_stale_md(tmp_path):
    """PARITY branch, EXECUTABLE mutation (not just the manual one in the
    docstring): write a .md that DIVERGES from the live projection into a
    temp bundle_root and assert check_registry_md_stale() returns stale.

    This proves the detector BITES: if check_registry_md_stale were weakened
    to always return (False, ""), THIS test goes RED. The happy-path test
    above cannot catch that weakening; this one can.
    """
    md_path = tmp_path / dl.REGISTRY_REL_PATH
    md_path.parent.mkdir(parents=True, exist_ok=True)
    # Real projection + a stray appended line -> guaranteed divergence.
    real = dl.render_registry_md(dl.discover_loops(AGENTS_CONFIG_PATH))
    md_path.write_text(real + "\nSTALE STRAY LINE\n", encoding="utf-8")
    is_stale, diag = dl.check_registry_md_stale(
        config_path=AGENTS_CONFIG_PATH, bundle_root=tmp_path
    )
    assert is_stale, "a divergent .md must be flagged stale"
    assert "stale" in diag.lower()


def test_parity_detector_flags_missing_md(tmp_path):
    """PARITY branch, missing-file mutation: an absent .md is stale."""
    is_stale, diag = dl.check_registry_md_stale(
        config_path=AGENTS_CONFIG_PATH, bundle_root=tmp_path
    )
    assert is_stale, "a missing .md must be flagged stale"
    assert "does not exist" in diag.lower()


def test_parity_detector_passes_on_fresh_md(tmp_path):
    """Negative control: a freshly generated .md is NOT stale (proves the
    detector is not a constant-True either)."""
    dl.generate_registry_md(config_path=AGENTS_CONFIG_PATH, bundle_root=tmp_path)
    is_stale, diag = dl.check_registry_md_stale(
        config_path=AGENTS_CONFIG_PATH, bundle_root=tmp_path
    )
    assert not is_stale, diag


# ---------------------------------------------------------------------------
# (b) Zero orphans: every backend_key / loop_id reference resolves.
# ---------------------------------------------------------------------------


def _find_orphans(config: dict) -> list[str]:
    """Return human-readable orphan diagnostics for the given config dict.

    A reference is orphaned if it points at a backend_key or loop_id that
    does not exist in ensemble_registry. Checks three reference surfaces:
    ensemble_profiles[*].backend_key, ensemble_pipelines[*].loop_id, and
    loop_shapes[*].steps[*].backend_key (self-referential within the
    registry).
    """
    registry = config.get("ensemble_registry", {})
    backend_keys = set(registry.get("backend_keys", {}).keys())
    loop_ids = set(registry.get("loop_shapes", {}).keys())

    orphans: list[str] = []

    for name, profile in config.get("ensemble_profiles", {}).items():
        key = profile.get("backend_key")
        if key is not None and key not in backend_keys:
            orphans.append(
                f"ensemble_profiles.{name}.backend_key={key!r} not in backend_keys"
            )

    for name, pipeline in config.get("ensemble_pipelines", {}).items():
        loop_id = pipeline.get("loop_id")
        if loop_id is not None and loop_id not in loop_ids:
            orphans.append(
                f"ensemble_pipelines.{name}.loop_id={loop_id!r} not in loop_shapes"
            )

    for loop_id, shape in registry.get("loop_shapes", {}).items():
        for i, step in enumerate(shape.get("steps", [])):
            key = step.get("backend_key")
            if key is not None and key not in backend_keys:
                orphans.append(
                    f"loop_shapes.{loop_id}.steps[{i}].backend_key={key!r} "
                    "not in backend_keys"
                )

    return orphans


def test_zero_orphans_live_registry():
    """The REAL agents.json has zero orphaned references today."""
    config = _load_config()
    orphans = _find_orphans(config)
    assert orphans == [], f"orphaned references found: {orphans}"


def test_zero_orphans_mutation_dangling_backend_key_is_caught():
    """ZERO ORPHANS branch, mutation (a): SYNTHETIC fixture with a dangling
    backend_key in ensemble_profiles -> the orphan detector must catch it.
    Uses an in-test fixture (not real prompt files: 0 real BUC-/CHA-
    citations exist today, so a real-file mutation would be unreachable)."""
    fixture = {
        "ensemble_registry": {
            "backend_keys": {"BA01": {"backend": "claude"}},
            "loop_shapes": {},
        },
        "ensemble_profiles": {
            "ghost_profile": {"backend_key": "BA99"},  # dangling on purpose
        },
        "ensemble_pipelines": {},
    }
    orphans = _find_orphans(fixture)
    assert orphans == [
        "ensemble_profiles.ghost_profile.backend_key='BA99' not in backend_keys"
    ]


def test_zero_orphans_mutation_dangling_loop_id_is_caught():
    """ZERO ORPHANS branch, mutation (b): SYNTHETIC fixture with a dangling
    loop_id in ensemble_pipelines -> caught."""
    fixture = {
        "ensemble_registry": {
            "backend_keys": {},
            "loop_shapes": {"L700": {"steps": []}},
        },
        "ensemble_profiles": {},
        "ensemble_pipelines": {
            "ghost_pipeline": {"loop_id": "L999"},  # dangling on purpose
        },
    }
    orphans = _find_orphans(fixture)
    assert orphans == [
        "ensemble_pipelines.ghost_pipeline.loop_id='L999' not in loop_shapes"
    ]


def test_zero_orphans_mutation_dangling_step_backend_key_is_caught():
    """ZERO ORPHANS branch, mutation (c): a loop_shape step citing a
    backend_key that does not exist in backend_keys -> caught."""
    fixture = {
        "ensemble_registry": {
            "backend_keys": {"BA01": {"backend": "claude"}},
            "loop_shapes": {
                "L700": {
                    "steps": [
                        {
                            "phase": "collector",
                            "function": "participant",
                            "backend_key": "BA77",
                        },
                    ]
                }
            },
        },
        "ensemble_profiles": {},
        "ensemble_pipelines": {},
    }
    orphans = _find_orphans(fixture)
    assert orphans == [
        "loop_shapes.L700.steps[0].backend_key='BA77' not in backend_keys"
    ]


# ---------------------------------------------------------------------------
# (c) CCO-consolidator rule: no consolidator step in a chat-launched loop.
# ---------------------------------------------------------------------------


def _find_cco_violations(registry: dict) -> list[str]:
    """Return diagnostics for any consolidator step in a chat-launched loop.

    By DATA: iterates loop_shapes, and for any shape with
    launched_from == "chat", flags any step whose function == "consolidator".
    A lector-FS participant step (function="participant") never triggers
    this; only an explicit function="consolidator" does.
    """
    violations: list[str] = []
    for loop_id, shape in registry.get("loop_shapes", {}).items():
        if shape.get("launched_from") != "chat":
            continue
        for i, step in enumerate(shape.get("steps", [])):
            if step.get("function") == "consolidator":
                violations.append(
                    f"loop_shapes.{loop_id}.steps[{i}] has function='consolidator' "
                    "in a chat-launched loop (CCO-consolidator invariant violated)"
                )
    return violations


def test_cco_consolidator_rule_live_registry():
    """The REAL ensemble_registry has zero consolidator steps in chat-launched
    loops today (L700/L800 are both chat-launched with participant-only steps)."""
    config = _load_config()
    registry = config.get("ensemble_registry", {})
    violations = _find_cco_violations(registry)
    assert violations == [], f"CCO-consolidator violations found: {violations}"


def test_cco_consolidator_rule_mutation_is_caught():
    """CCO-CONSOLIDATOR branch mutation: inject a chat-launched loop with a
    consolidator step via fixture -> the detector must flag it RED."""
    fixture = {
        "loop_shapes": {
            "L900": {
                "launched_from": "chat",
                "steps": [
                    {
                        "phase": "synthesis",
                        "function": "consolidator",
                        "backend_key": "BA01",
                    },
                ],
            }
        }
    }
    violations = _find_cco_violations(fixture)
    assert violations == [
        "loop_shapes.L900.steps[0] has function='consolidator' "
        "in a chat-launched loop (CCO-consolidator invariant violated)"
    ]


def test_cco_consolidator_rule_allows_consolidator_in_programmatic_loop():
    """Negative control: a consolidator step in a launched_from='programmatic'
    loop is NOT a violation (the invariant only restricts chat-launched loops)."""
    fixture = {
        "loop_shapes": {
            "L901": {
                "launched_from": "programmatic",
                "steps": [
                    {
                        "phase": "synthesis",
                        "function": "consolidator",
                        "backend_key": "BA01",
                    },
                ],
            }
        }
    }
    violations = _find_cco_violations(fixture)
    assert violations == []


def test_cco_consolidator_rule_allows_participant_lector_fs_in_chat_loop():
    """Negative control: a participant lector-FS step in a chat-launched loop
    is NOT a violation (only function='consolidator' triggers it)."""
    fixture = {
        "loop_shapes": {
            "L700": {
                "launched_from": "chat",
                "steps": [
                    {
                        "phase": "fanout-lector-fs",
                        "function": "participant",
                        "backend_key": "BA01",
                    },
                ],
            }
        }
    }
    violations = _find_cco_violations(fixture)
    assert violations == []


# ---------------------------------------------------------------------------
# Schema sanity: every loop_shape step carries an explicit function field.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("loop_id", ["L700", "L800"])
def test_every_step_has_explicit_function_field(loop_id):
    config = _load_config()
    shape = config["ensemble_registry"]["loop_shapes"][loop_id]
    # WOT-2026-086f: alias legacy no tienen 'steps' propio, solo alias_of.
    # Si tiene steps, cada step debe tener un campo 'function' explicito.
    steps = shape.get("steps", [])
    for i, step in enumerate(steps):
        assert "function" in step, f"{loop_id}.steps[{i}] missing 'function' field"
        assert step["function"] in ("participant", "consolidator")


def test_status_semantics_are_documented_in_the_projection():
    """La proyeccion debe DEFINIR que significa cada `status`, no solo listarlos.

    LOAD-BEARING (medido 2026-09-04): el enum vivia en
    `agents.json::ensemble_registry.statuses` como tres strings SIN semantica, y
    la definicion no existia en docs, AGENTS.md ni en el codigo. Consecuencia:
    se marco `BA05` (codex) como `deprecated` tras 3 `transport-failed` en UNA
    sesion --un fallo TEMPORAL-- y eso lo saco de todos los bucles adversariales.
    Ningun gate lo detecto: el registro quedaba internamente coherente. Lo cazo
    el usuario.

    Este test es el ancla: sin el, la seccion puede desaparecer en un refactor
    del generador y el enum vuelve a quedar sin semantica en silencio.
    """
    texto = REGISTRY_MD_PATH.read_text(encoding="utf-8")

    # La distincion que se perdio: fallo temporal != obsolescencia.
    assert "Ningun fallo de ejecucion cambia un `status`" in texto
    # La salida para el fallo cronico, sin la cual la regla produce zombis.
    assert "`archived` con su evidencia" in texto or "se `archived`" in texto
    # El instrumento antes que el backend.
    assert "la ULTIMA hipotesis" in texto
    # La colision de enums entre catalogos.
    assert "catalogo de" in texto and "SKILLS" in texto

    for status in ("active", "deprecated", "archived"):
        assert f"`{status}`" in texto, f"falta la definicion de {status}"


def test_status_enum_matches_the_documented_one():
    """El enum vivo y el documentado no pueden divergir en silencio."""
    registry = dl.load_registry()
    statuses = set(registry.get("statuses", []))
    assert statuses == {"active", "deprecated", "archived"}, (
        f"el enum vivo es {sorted(statuses)}; si cambia, actualiza la tabla de "
        "semantica en discover_loops.py (la proyeccion se genera desde ahi)"
    )


# ---------------------------------------------------------------------------
# (d) PROFILE<->REGISTRY PARITY: el hueco por el que vivio el drift de BA06
# ---------------------------------------------------------------------------


def test_ensemble_registry_backend_keys_match_live_profiles():
    """Cada perfil vivo y su backend_key en el registro declaran EL MISMO modelo.

    Hueco medido (WOT-2026-082a, 2026-09-29): las ramas existentes comparan
    loop_registry.md contra ensemble_registry (a) y buscan referencias
    colgantes (b), pero NINGUNA comparaba ensemble_registry contra
    ensemble_profiles -- donde vivia el drift real: BA06 declaraba
    `opencode-go/glm-5.2` mientras el perfil vivo (`challenger_opencode_glm_5_2`)
    declara `opencode-go/glm-5.3-flash` desde el commit 055aba5. La suite
    seguia verde porque el md y el registro eran coherentes ENTRE SI (ambos
    mienten igual).

    During: itera los PERFILES (no el registro), asi que los backend_keys
    deprecated sin perfil vivo (BA14/BA17-19, historico intencional) quedan
    fuera del alcance.

    After: falla listando cada (perfil, backend_key, modelo-registro vs
    modelo-perfil) divergente. MUTATION (worktree aislado, WOT-2026-082a):
    revertir BA06 a glm-5.2 en agents.json -> ROJO con el mismatch listado;
    con el fix -> VERDE.
    """
    config = _load_config()
    profiles = config.get("ensemble_profiles", {})
    backend_keys = config.get("ensemble_registry", {}).get("backend_keys", {})
    mismatches = []
    for name, prof in profiles.items():
        bk = prof.get("backend_key")
        if not bk:
            continue
        entry = backend_keys.get(bk)
        if entry is None:
            mismatches.append(
                f"{name}: backend_key {bk} no existe en ensemble_registry"
            )
            continue
        if (entry.get("backend"), entry.get("model")) != (
            prof.get("backend"),
            prof.get("model"),
        ):
            mismatches.append(
                f"{name}: registro {bk} declara "
                f"{entry.get('backend')}/{entry.get('model')} pero el perfil "
                f"declara {prof.get('backend')}/{prof.get('model')}"
            )
    assert not mismatches, (
        f"ensemble_registry miente sobre perfiles vivos (drift tipo BA06): {mismatches}"
    )


# ---------------------------------------------------------------------------
# (e) WOT-2026-086f: formas parametricas, alias, sin backend_key fijo
# ---------------------------------------------------------------------------


def test_loop_shapes_zero_steps_with_backend_key():
    """WOT-2026-086f DoD D1: ningun step de loop_shapes tiene `backend_key`.

    Mutation: reintroducir un `backend_key` en un step de una forma nueva pone
    ROJO este test.
    """
    config = _load_config()
    shapes = config["ensemble_registry"]["loop_shapes"]
    violations = []
    for shape_id, shape in shapes.items():
        for i, step in enumerate(shape.get("steps", [])):
            if step.get("backend_key"):
                violations.append(
                    f"{shape_id}.steps[{i}].backend_key={step['backend_key']!r} "
                    f"no debe existir (WOT-2026-086f DoD D1)"
                )
    assert violations == [], f"steps con backend_key encontrados: {violations}"


def test_legacy_loop_ids_resolve_to_existing_form():
    """WOT-2026-086f DoD D2: cada alias legacy resuelve a una forma existente.

    El censo real (DEC-086F-001): L700->DBL-4, L710->DBL-3, L720->DBL-4,
    L800->CHA-1. Los tests usan el registro vivo, no los valores exactos --
    lo que importa es que el alias resuelva a una forma en loop_shapes.

    Mutation: cambiar `alias_of` a un nombre que no exista en el registro
    pone ROJO este test.
    """
    config = _load_config()
    shapes = config["ensemble_registry"]["loop_shapes"]
    for shape_id, shape in shapes.items():
        alias_of = shape.get("alias_of")
        if alias_of is not None:
            assert alias_of in shapes, (
                f"el alias '{shape_id}' apunta a '{alias_of}' que no existe "
                f"en loop_shapes (WOT-2026-086f DoD D2)"
            )


def test_form_parametric_list_complete():
    """WOT-2026-086f DoD D1: la lista cerrada de formas incluye las formas
    UNI-N, DBL-N, ROL-N y CHA-N segun el parametrico.
    """
    config = _load_config()
    shapes = config["ensemble_registry"]["loop_shapes"]
    # Solo contar formas NO alias (las que no tienen alias_of)
    forms = {sid for sid, shape in shapes.items() if "alias_of" not in shape}
    # Rango exacto del registro vivo:
    # UNI: 2..5, DBL: 2..6, ROL: 2..4, CHA: 1..5
    for prefix, lo, hi in (("UNI", 2, 5), ("DBL", 2, 6), ("ROL", 2, 4), ("CHA", 1, 5)):
        for n in range(lo, hi + 1):
            assert f"{prefix}-{n}" in forms, (
                f"falta la forma '{prefix}-{n}' en loop_shapes"
            )
