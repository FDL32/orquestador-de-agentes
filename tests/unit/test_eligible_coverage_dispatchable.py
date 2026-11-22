"""Tests de despachabilidad de la cobertura elegible declarada."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ensemble_dispatch as ed  # noqa: E402


LEGACY_KILO_EXEMPT = frozenset(
    {
        "BA03",
        "BA07",
        "BA02",
        "BA04",
        "BA08",
        "BA09",
    }
)
"""Exenciones Kilo explícitas de WOT-2026-222a, fechadas 2026-11-23.

Retirar claves de este conjunto es otro ticket, con revisión de las auditorías
históricas; no se permite exentar por backend, comodín ni "except kilo".
"""

LENSES_TICKET_222C = ("BA258", "BA259", "BA150", "BA151")
"""Cuatro lentes de nivel base o medio que WOT-2026-222c declara elegibles.

Su presencia se exige AQUI ademas del test c-01: quitar una de ellas de la
lista deja este archivo en rojo (mutacion 1 de la FICHA s.3), no solo c-01.
"""


def test_eligible_coverage_keys_are_dispatchable():
    """Comprueba que cada elegible no legado tiene un perfil despachable.

    Before: la configuración real del motor está disponible en el worktree.
    During: recorre la entrada de cobertura, el registro y los perfiles sin
        parches ni monkeypatches, aplicando la política productiva de lentes.
    After: cada clave no exenta tiene registro activo, perfil y al menos una
        ruta aceptada por ``enforce_profile_policy``.
    """
    config = ed.load_motor_config()
    entry = config["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]
    registry = config["ensemble_registry"]["backend_keys"]
    profiles = config["ensemble_profiles"]

    for key in entry["backend_keys"]:
        if key in LEGACY_KILO_EXEMPT:
            continue
        registry_entry = registry.get(key)
        assert registry_entry is not None, f"clave elegible ausente del registro: {key}"
        assert registry_entry.get("status") == "active", (
            f"clave elegible no activa: {key}"
        )
        matching_profiles = [
            profile
            for profile in profiles.values()
            if profile.get("backend_key") == key
        ]
        assert matching_profiles, f"clave elegible sin perfil: {key}"
        dispatchable = False
        for profile in matching_profiles:
            try:
                ed.enforce_profile_policy(
                    profile,
                    caller="lens",
                    backend_cfg=config["backends"][profile["backend"]],
                )
            except ed.DispatchBlockedError:
                continue
            dispatchable = True
            break
        assert dispatchable, f"clave elegible sin perfil despachable: {key}"


def test_ticket_lenses_stay_declared_eligible():
    """Comprueba que las cuatro lentes base/medio del ticket siguen en la lista.

    Before: la configuración real del motor está disponible en el worktree.
    During: contrasta la presencia de cada lente del ticket en ``backend_keys``
        de la entrada de cobertura, sin parches ni monkeypatches.
    After: cada lente ausente deja el test en rojo nombrándola.
    """
    config = ed.load_motor_config()
    entry = config["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]
    declared = set(entry["backend_keys"])
    for key in LENSES_TICKET_222C:
        assert key in declared, (
            f"lente base/medio ausente de la cobertura elegible: {key}"
        )


def test_legacy_kilo_exempt_keys_are_kilo():
    """Comprueba que toda exención histórica corresponde realmente a Kilo.

    Before: la configuración real del motor está disponible en el worktree.
    During: contrasta cada clave del conjunto explícito contra el registro.
    After: ninguna clave exenta puede ocultar un backend distinto de Kilo.
    """
    config = ed.load_motor_config()
    registry = config["ensemble_registry"]["backend_keys"]

    for key in LEGACY_KILO_EXEMPT:
        assert registry[key]["backend"] == "kilo", (
            f"clave exenta no pertenece a Kilo: {key}"
        )
