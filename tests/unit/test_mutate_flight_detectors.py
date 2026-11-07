"""Pruebas del arnés de mutación de los detectores de vuelo."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "flight" / "mutate_flight_detectors.py"


def _load_harness():
    """Carga el arnés sin ejecutar sus corridas.

    Before: ``HARNESS`` apunta al script versionado del ticket.
    During: importa el módulo mediante su ruta, sin alterar ``sys.path``.
    After: devuelve el módulo cargado o propaga el error de importación.
    """
    spec = importlib.util.spec_from_file_location("mutate_flight_detectors", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalogo_de_mutaciones_y_reanclajes_es_completo():
    """El arnés conserva el denominador completo y los 12 reanclajes de 153j."""
    module = _load_harness()

    assert len(module.MUT) == 180
    assert module.RETIRED == {}
    assert set(module.REANCHORED) == {
        "E7",
        "N70",
        "N64",
        "Q3c",
        "X16",
        "Q7b",
        "Q7c",
        "T5",
        "T6",
        "Q1",
        "Q2",
        "Q14",
    }
    assert all(module.REANCHORED.values())


def test_cada_patron_casa_una_vez_compila_y_cambia_el_objetivo():
    """La validación reproduce las tres barreras del contrato D23."""
    module = _load_harness()
    for _mid, _box, target, pattern, replacement in module.MUT:
        source = (ROOT / "scripts" / "flight" / target).read_text(encoding="utf-8")
        assert source.count(pattern) == 1
        mutated = source.replace(pattern, replacement)
        assert mutated != source
        compile(mutated, target, "exec")


def test_patron_inexistente_no_se_considera_mutacion_valida():
    """Un patrón ausente falla cerrado, evitando falsos verdes del arnés."""
    module = _load_harness()
    source = (ROOT / "scripts" / "flight" / module.STALL).read_text(encoding="utf-8")
    assert source.count("PATRON_AUSENTE_153P") == 0
