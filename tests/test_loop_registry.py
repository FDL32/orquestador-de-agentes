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
    for i, step in enumerate(shape["steps"]):
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
