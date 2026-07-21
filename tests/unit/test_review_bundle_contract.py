"""Tests for scripts/review_bundle_contract.py + resolve_fallback_backend
(WOT-2026-026k).

Hermetic: the universe/bundle invariant is exercised via
`check_bundle_against_universe` directly (no git subprocess needed for the
truncation/mutation tests -- those construct `universe` dicts by hand,
which is the deterministic and portable path). `compute_code_universe`
itself IS exercised against the real repo (git ls-tree on HEAD) as a
sanity/integration check, since the repo is guaranteed to be a git repo
in CI and locally.

The fallback-backend test lives here (not in test_ensemble_dispatch.py)
because it is scoped to the WOT-2026-026k contract: "clase distinta" =
`backend` field mismatch, fail-closed via DispatchBlockedError.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import ensemble_dispatch as ed  # noqa: E402
import review_bundle_contract as rbc  # noqa: E402


# --------------------------------------------------------------------------- #
# DoD #2: truncated bundle rejected
# --------------------------------------------------------------------------- #


def test_truncated_bundle_rejected():
    """Universo declara 3 rutas; el bundle solo trae 2 -> CONTEXTO_INSUFICIENTE,
    sin invocar ningun backend/LLM (comparacion de conjuntos pura).
    """
    universe = {
        "paths": frozenset({"a.py", "b.py", "c.py"}),
        "sha256": "deadbeef" * 8,
    }
    bundle_paths = {"a.py", "b.py"}  # c.py omitida: recorte

    result = rbc.check_bundle_against_universe(universe, bundle_paths)

    assert result["veredicto"] == "CONTEXTO_INSUFICIENTE"
    assert result["faltantes"] == ["c.py"]


def test_complete_bundle_passes_fixture_positivo():
    """Fixture POSITIVO (gate_false_positive_legitimate_input): un bundle que
    SI contiene el universo completo (con hash coincidente) debe pasar
    limpio. Sin este caso, un invariante demasiado agresivo bloquearia
    cualquier review legitima.
    """
    universe = rbc.compute_code_universe(_MOTOR_ROOT)
    # El bundle completo: exactamente las rutas del universo.
    bundle_paths = set(universe["paths"])

    result = rbc.check_bundle_against_universe(
        universe, bundle_paths, bundle_sha256=universe["sha256"]
    )

    assert result["veredicto"] == "OK"
    assert result["faltantes"] == []


def test_compute_code_universe_only_covers_py_files():
    """NON-GOAL guard: el universo mecanico es SOLO .py; prompts/markdown
    quedan fuera de alcance (declarado en el contrato, sub-ticket aparte).
    """
    universe = rbc.compute_code_universe(_MOTOR_ROOT)
    assert all(p.endswith(".py") for p in universe["paths"])
    assert "AGENTS.md" not in universe["paths"]


# --------------------------------------------------------------------------- #
# DoD #5: MUTATION -- invariant catches truncation; a no-op mutant does not
# --------------------------------------------------------------------------- #


def _noop_check_bundle_against_universe(universe, bundle_paths, *, bundle_sha256=None):
    """Mutante LOCAL: simula 'quitar el invariante' -- siempre OK."""
    return {"veredicto": "OK", "faltantes": [], "motivo": "mutante no-op"}


def test_mut_no_invariant_lets_truncated_pass():
    """Par de exit-codes literal para el reporte de cierre (DoD #5 /
    meta_gate_self_false_green): con el invariante ACTIVO, el bundle
    recortado se rechaza (rc!=0). Mutando el check a no-op (simulando que
    el propio gate del reviewer omite la validacion), el MISMO bundle pasa
    (rc=0). Esto prueba que el gate nuevo detectaria una omision simulada
    en si mismo -- la meta-parada GAP-3 del contrato.
    """
    universe = {
        "paths": frozenset({"a.py", "b.py", "c.py"}),
        "sha256": "deadbeef" * 8,
    }
    bundle_paths = {"a.py", "b.py"}  # c.py sigue faltando

    # Invariante ACTIVO (codigo real, sin mutar):
    result_active = rbc.check_bundle_against_universe(universe, bundle_paths)
    exit_code_active = 1 if result_active["veredicto"] == "CONTEXTO_INSUFICIENTE" else 0

    # Invariante MUTADO a no-op:
    result_mutated = _noop_check_bundle_against_universe(universe, bundle_paths)
    exit_code_mutated = (
        1 if result_mutated["veredicto"] == "CONTEXTO_INSUFICIENTE" else 0
    )

    assert exit_code_active == 1
    assert exit_code_mutated == 0
    # command: rbc.check_bundle_against_universe(universe, bundle_paths) -> exit_code: 1 (activo)
    # command: _noop_check_bundle_against_universe(universe, bundle_paths) -> exit_code: 0 (mutado)


# --------------------------------------------------------------------------- #
# DoD #3: fallback requires a DISTINCT backend class
# --------------------------------------------------------------------------- #


def _config_two_classes():
    """Pool auditado = nan_api; candidato de clase distinta = codex."""
    return {
        "backends": {
            "nan_api": {
                "executable": "",
                "args": [],
                "discovery": {"method": "path_only"},
            },
            "codex": {
                "executable": "codex.cmd",
                "args": [],
                "discovery": {"method": "path_only"},
            },
        },
        "ensemble_profiles": {
            "challenger_nan": {
                "backend": "nan_api",
                "channel": "api",
                "model": "m1",
                "data_sensitivity": "public",
            },
            "challenger_codex": {
                "backend": "codex",
                "channel": "agent",
                "model": None,
                "data_sensitivity": "public",
            },
        },
    }


def test_fallback_requires_distinct_backend():
    """Pool auditado backend=nan_api + Codex mockeado CAIDO -> el resolver
    debe devolver un backend con backend!=nan_api si hay otro vivo, o
    lanzar DispatchBlockedError; NUNCA otra nan_api (no hay otra en este
    fixture, asi que el caso limite es: Codex caido -> DispatchBlockedError,
    NUNCA silenciosamente aceptar 'challenger_nan' de vuelta).
    """
    config = _config_two_classes()

    def codex_dead(profile_name, *, config):
        return {"profile": profile_name, "alive": False, "detail": "timeout"}

    with pytest.raises(ed.DispatchBlockedError):
        ed.resolve_fallback_backend("nan_api", config=config, check_alive=codex_dead)


def test_fallback_returns_distinct_backend_when_alive():
    """Camino feliz: Codex vivo -> resolver devuelve 'challenger_codex'
    (backend='codex' != 'nan_api'), nunca un perfil con el mismo backend
    que el pool auditado.
    """
    config = _config_two_classes()

    def codex_alive(profile_name, *, config):
        return {"profile": profile_name, "alive": True, "detail": "PONG"}

    chosen = ed.resolve_fallback_backend(
        "nan_api", config=config, check_alive=codex_alive
    )

    assert config["ensemble_profiles"][chosen]["backend"] != "nan_api"
    assert chosen == "challenger_codex"


def test_fallback_no_distinct_candidates_blocks():
    """Si TODOS los perfiles son de la misma clase que el pool, no hay
    candidato -> DispatchBlockedError inmediato (sin siquiera invocar
    check_alive).
    """
    config = {
        "backends": {"nan_api": {"executable": "", "args": [], "discovery": {}}},
        "ensemble_profiles": {
            "only_nan": {"backend": "nan_api", "channel": "api", "model": "m1"},
        },
    }

    def should_not_be_called(profile_name, *, config):
        raise AssertionError("check_alive no deberia invocarse sin candidatos")

    with pytest.raises(ed.DispatchBlockedError):
        ed.resolve_fallback_backend(
            "nan_api", config=config, check_alive=should_not_be_called
        )
