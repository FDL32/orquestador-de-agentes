"""`emit-nonce` valida `--loop-id` contra el registro citable de bucles.

Medido 2026-09-18 (ruta productiva, `main()` del CLI): `emit-nonce` aceptaba
CUALQUIER cadena como `--loop-id` y la APPENDEABA al ledger con exit 0. Probe
real: `--loop-id L999-INVENTADO` -> `exit 0` + fila escrita en
`emitted_nonces.jsonl`. Un `loop_id` fabricado contamina el ledger, que es la
UNICA prueba de que la ceremonia previa ocurrio, y `check_loop_execution` agrupa
por el.

Ademas el registro declara un `status` por bucle (`active`/`deprecated`/
`archived`) y NADIE lo hacia cumplir: `ensemble_dispatch.py` tenia 0 menciones de
`deprecated` y `discover_loops.py` era su unico consumidor, solo para publicarlo.
Lanzar un bucle retirado salia silencioso -- el patron "norma, no barrera" de
AGENTS.md.

ALCANCE: AVISA, no bloquea -- en ninguno de los dos casos.

Una primera version lanzaba `ValueError` ante un `loop_id` inexistente. Rompio 4
tests hermanos y el censo midio 7+ identificadores sinteticos (`LX`, `L-B`,
`L-MOTOR`, `L-DEST`, `L-A`, `L-TEST`, `L-SHATEST`) en 6+ ficheros que los usan A
PROPOSITO para no acoplarse al registro real. Por la hipotesis por defecto del
repo ("si una barrera nueva rompe tests existentes en masa, la barrera mide una
propiedad demasiado ancha") se degrado a WARN. El bloqueo duro es deuda declarada
y exige adaptar antes esos sinteticos.

Lo que el WARN SI cierra: lanzar un bucle `deprecated` en SILENCIO, que es el
fallo real medido (se lanzo `L710`, retirado, sin ningun aviso).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

import ensemble_dispatch as ed  # noqa: E402


def _registry_stub() -> dict:
    """Registro minimo con un bucle activo y uno deprecated."""
    return {
        "ensemble_registry": {
            "statuses": ["active", "deprecated", "archived"],
            "backend_keys": {"BA01": {"backend": "claude", "status": "active"}},
            "loop_shapes": {
                "L720": {"name": "BUC-03", "status": "active", "steps": []},
                "L710": {"name": "BUC-02", "status": "deprecated", "steps": []},
            },
        }
    }


@pytest.fixture
def destino(tmp_path: Path) -> Path:
    d = tmp_path / "destino"
    (d / ".agent" / "runtime" / "ensemble").mkdir(parents=True, exist_ok=True)
    return d


def _ledger_rows(destino: Path) -> list[dict]:
    path = destino / ed.EMITTED_NONCES_REL
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_loop_id_inexistente_avisa_nombrando_los_activos(destino: Path) -> None:
    """Un loop_id fuera del registro produce un WARN visible (antes: silencio).

    Defecto medido: `L999-INVENTADO` pasaba sin decir nada y quedaba archivado en
    el ledger. NO bloquea, por el alcance declarado en el docstring del modulo.
    """
    warning = ed.validate_loop_id("L999-INVENTADO", _registry_stub())

    assert warning is not None, "un loop_id fabricado no puede pasar en silencio"
    assert "L999-INVENTADO" in warning, "el WARN debe nombrar el loop_id"
    assert "L720" in warning, (
        "el WARN debe enumerar los bucles ACTIVOS: un aviso self-service dice "
        "como corregir, no solo que algo va mal"
    )
    assert _ledger_rows(destino) == [], "validate_loop_id no escribe en el ledger"


def test_loop_id_activo_pasa_sin_warning(destino: Path) -> None:
    """Control positivo: el camino bueno sigue funcionando y no avisa de nada."""
    warning = ed.validate_loop_id("L720", _registry_stub())
    assert warning is None, "un bucle activo no genera WARN"


def test_loop_id_deprecated_avisa_pero_no_bloquea(destino: Path) -> None:
    """Un bucle deprecated AVISA (hoy no avisaba nada) pero no rompe la migracion."""
    warning = ed.validate_loop_id("L710", _registry_stub())
    assert warning is not None, "un bucle deprecated debe producir un WARN visible"
    assert "L710" in warning
    assert "deprecated" in warning.lower()
    assert "L720" in warning, "el WARN debe nombrar la alternativa activa"


def test_registro_vacio_no_bloquea(destino: Path) -> None:
    """Fail-OPEN deliberado si el registro no declara `loop_shapes`.

    Un registro sin bucles declarados es un motor sin configurar, no un loop_id
    fabricado: bloquear ahi convertiria en rojo cualquier destino que todavia no
    tenga `ensemble_registry`, que es una carencia de INFRAESTRUCTURA y no un
    defecto de la llamada (misma distincion que `CF_NOT_MATERIALIZED`).
    """
    assert ed.validate_loop_id("L999", {"ensemble_registry": {}}) is None
    assert ed.validate_loop_id("L999", {}) is None


# ---------------------------------------------------------------------------
# WOT-2026-086f: resolucion de alias
# ---------------------------------------------------------------------------


def _registry_with_alias() -> dict:
    """Registro con forma activa, alias legacy y formas parametricas WOT-2026-086f."""
    return {
        "ensemble_registry": {
            "statuses": ["active", "deprecated", "archived"],
            "backend_keys": {"BA01": {"backend": "claude", "status": "active"}},
            "loop_shapes": {
                "DBL-4": {"name": "DBL-4", "status": "active", "steps": []},
                "DBL-3": {"name": "DBL-3", "status": "active", "steps": []},
                "UNI-4": {"name": "UNI-4", "status": "active", "steps": []},
                "L700": {"alias_of": "DBL-4", "status": "deprecated", "name": "BUC-01"},
                "L720": {"alias_of": "DBL-4", "status": "active", "name": "BUC-03"},
                "L710": {"alias_of": "DBL-3", "status": "deprecated", "name": "BUC-02"},
            },
        }
    }


def test_alias_legacy_resuelve_a_forma_activa(destino: Path) -> None:
    """WOT-2026-086f: L720 (alias of DBL-4) pasa sin WARN porque la forma es active.

    Mutation: si DBL-4 estuviera deprecated, L720 deberia producir WARN.
    """
    warning = ed.validate_loop_id("L720", _registry_with_alias())
    assert warning is None, "L720 -> DBL-4 (active) no debe generar WARN"


def test_alias_deprecated_resuelve_a_forma_activa(destino: Path) -> None:
    """WOT-2026-086f: L700 es deprecated como alias, pero resuelve a DBL-4 active.

    El alias deprecated no bloquea la resolucion a una forma activa:
    la validacion mira la forma, no el alias.
    """
    warning = ed.validate_loop_id("L700", _registry_with_alias())
    assert warning is None, (
        "L700 (deprecated alias -> DBL-4 active) no debe generar WARN: "
        "la validacion WOT-2026-086f resuelve el alias y verifica la forma"
    )


def test_alias_apunta_a_forma_inexistente_avisa(destino: Path) -> None:
    """WOT-2026-086f: si el alias apunta a una forma que no existe, se avisa."""
    broken = {
        "ensemble_registry": {
            "statuses": ["active", "deprecated", "archived"],
            "backend_keys": {},
            "loop_shapes": {
                "L999": {"alias_of": "DOES_NOT_EXIST", "status": "deprecated"},
            },
        }
    }
    warning = ed.validate_loop_id("L999", broken)
    assert warning is not None, "alias a forma inexistente debe generar WARN"
    assert "L999" in warning
    assert "DOES_NOT_EXIST" in warning


def test_forma_parametrica_pasa_sin_warning(destino: Path) -> None:
    """WOT-2026-086f: las formas parametricas nuevas pasan como active."""
    warning = ed.validate_loop_id("UNI-4", _registry_with_alias())
    assert warning is None, "UNI-4 (forma parametrica active) no debe generar WARN"


def test_forma_parametrica_inexistente_avisa(destino: Path) -> None:
    """WOT-2026-086f: una forma que no existe produce WARN."""
    warning = ed.validate_loop_id("UNI-99", _registry_with_alias())
    assert warning is not None, "UNI-99 (no existe) debe generar WARN"
    assert "UNI-99" in warning
