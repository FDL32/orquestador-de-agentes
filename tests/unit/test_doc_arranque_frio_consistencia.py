"""Verificaciones por anclas de la documentacion canonica de arranque en frio.

Before: los documentos del motor estan en el checkout que contiene este test.
During: cada comprobacion lee regiones delimitadas por literales, sin lineas fijas.
After: las contradicciones de los contratos documentales producen un fallo legible.
"""

from __future__ import annotations

import re
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parents[2]
CLOSED_DOCUMENTS = (
    MOTOR_ROOT / "prompts" / "orchestrator_session_bootstrap.md",
    MOTOR_ROOT / "prompts" / "t3_role_session_relief.md",
    MOTOR_ROOT / "INTERACTION_MODES.md",
    MOTOR_ROOT / "QUICKSTART.md",
    MOTOR_ROOT / "README.md",
    MOTOR_ROOT / "docs" / "test_performance" / "test_performance_variance.md",
    MOTOR_ROOT / "docs" / "protocol" / "flight_supervision.md",
    MOTOR_ROOT / ".agent" / "rules" / "common" / "flight_push_policy.md",
)


def _read(path: Path) -> str:
    """Before: `path` identifica un documento de la lista cerrada.

    During: lee el documento sin modificarlo.
    After: devuelve el texto UTF-8 del documento.
    """
    return path.read_text(encoding="utf-8")


def _normal(text: str) -> str:
    """Before: `text` puede contener saltos de linea entre palabras.

    During: compacta cualquier secuencia de espacios.
    After: devuelve una representacion estable para comparar frases.
    """
    return " ".join(text.split())


def _region(text: str, start: str, end: str) -> str:
    """Before: `text` contiene anclas unicas de inicio y fin.

    During: localiza las anclas por contenido y excluye sus delimitadores.
    After: devuelve solo el cuerpo de la region o falla si las anclas no son unicas.
    """
    start_at = text.find(start)
    end_at = text.find(end, start_at + len(start))
    assert start_at >= 0, f"ancla de inicio ausente: {start!r}"
    assert end_at >= 0, f"ancla de fin ausente: {end!r}"
    assert text.find(start, start_at + 1) < 0, f"ancla de inicio duplicada: {start!r}"
    return text[start_at + len(start) : end_at]


def _count_region(
    path: Path, start: str, end: str, pattern: str, expected: int | None = None
) -> int:
    """Before: `path`, anclas y patron forman una especificacion de conteo.

    During: lee una copia logica del documento y cuenta solo dentro de la region.
    After: devuelve el conteo y, si se declara, exige el valor esperado.
    """
    count = len(re.findall(pattern, _region(_read(path), start, end)))
    if expected is not None:
        assert count == expected, (path, pattern, count, expected)
    return count


def test_bootstrap_preflight_modo_vuelo():
    """Before: el bootstrap tiene un preflight delimitado. During: cuenta modos. After: ambos modos y la remision existen."""
    text = _region(
        _read(CLOSED_DOCUMENTS[0]),
        "## Modo ORQUESTADOR de pipeline multi-ticket (paso 0)",
        "## Ciclo canonico de un ticket",
    )
    assert "vuelo activo" in text.lower()
    assert "flight_push_policy" in text
    assert "HEAD == origin/main" in text


def test_bootstrap_ciclo_sin_push_por_ticket():
    """Before: el ciclo tiene paso 4 y PIN de push. During: valida su texto. After: no queda push por ticket."""
    text = _region(
        _read(CLOSED_DOCUMENTS[0]),
        "## Ciclo canonico de un ticket",
        "## Reflejos CEM v0",
    )
    assert "Commit + push" not in text
    assert "flight_push_policy.md" in text
    full = _normal(_read(CLOSED_DOCUMENTS[0]))
    assert (
        _normal("UN solo push al final de TODOS los tickets de la cola/vuelo") in full
    )


def test_quickstart_prefix_wot():
    """Before: QUICKSTART declara el namespace. During: cuenta prefijos. After: solo queda WOT."""
    text = _read(CLOSED_DOCUMENTS[3])
    assert "WT-YYYY" not in text
    assert "WOT-YYYY-NNNx" in text
    assert "cualquier destino" in text


def test_readme_prefix_wot():
    """Before: README documenta dogfooding. During: inspecciona el fichero. After: usa WOT."""
    text = _read(CLOSED_DOCUMENTS[4])
    assert "WT-YYYY" not in text
    assert "WOT-YYYY-NNNx" in text


def test_quickstart_push_policy_remission():
    """Before: QUICKSTART conserva git push. During: normaliza la frase. After: remite la politica."""
    text = _normal(_read(CLOSED_DOCUMENTS[3]))
    assert text.count("flight_push_policy.md") == 1
    assert "git push origin main" in text
    assert "desarrollo sin vuelo activo" in text


def test_quickstart_suite_duration_snapshot():
    """Before: QUICKSTART tiene la cifra historica. During: limita el ambito. After: queda etiquetada."""
    text = _region(
        _read(CLOSED_DOCUMENTS[3]),
        "**Duracion de `--level all` y timeout (WOT-2026-041h).**",
        "**Corre la suite con el `.venv` del repo.**",
    )
    assert text.count("906") == 1
    assert "snapshot de fecha; mide la duracion real con la corrida del comando" in text


def test_relief_checkpoint_home_workspace():
    """Before: relief define checkpoint y guard_paths. During: acota ambos. After: usa repo_root y hogar de vuelo."""
    text = _region(
        _read(CLOSED_DOCUMENTS[1]),
        "## 5. Checkpoint continuo",
        "## 6. Preflight del relanzo",
    )
    assert "C:/tmp/vuelo-" not in text
    assert ".agent/runtime/flight/" in text
    assert "repo_root=repo_destino" in text
    assert "repo_root=motor" in text
    assert "Nunca Write/Edit nativo del agente" not in text


def test_relief_powershell_example_redirect():
    """Before: relief contiene C9b. During: inspecciona el ejemplo. After: la redireccion real queda marcada."""
    text = _region(
        _read(CLOSED_DOCUMENTS[1]),
        "### Sub-requisito 5: medicion sin redireccion de PowerShell (UTF-16)",
        "### PIDs propios del sucesor",
    )
    assert "Get-Item ruta).Length" not in text
    assert "Get-Item ruta > size.txt" in text
    assert "len(open(ruta, 'rb').read())" in text
    assert "C9b" in text


def test_relief_alarm_section_no_old_figures():
    """Before: relief tiene alarma y PIN de compactacion. During: aplica regex de cifras. After: no hay umbrales viejos."""
    text = _region(
        _read(CLOSED_DOCUMENTS[1]),
        "### Alarma de contexto (sintoma)",
        "## 10. Cadena de ancestros (consulta escalonada)",
    )
    assert len(re.findall(r"(?i)[0-9][0-9]{0,3}\s?[kK]\b", text)) == 0
    assert text.count("Umbrales de relevo por contexto") == 1
    assert text.lower().count("segunda compactacion") == 1
    assert "estimacion del vuelo, no medida ni umbral duro" in text


def test_relief_flight_tooling_home_line():
    """Before: relief cita el rotador base. During: cuenta solo los nombres v2. After: cada utilidad vive una vez."""
    text = _read(CLOSED_DOCUMENTS[1])
    sub = _region(
        text, "### Relevos encadenados autorizados (WOT-2026-153z)", "### Cuando aplica"
    )
    for name in ("rotate_coordinator_v2.py", "ctx_acumulado.py", "next_go_relevo.py"):
        assert sub.count(name) == 1
        assert text.count(name) == 1
        assert _read(CLOSED_DOCUMENTS[0]).count(name) == 0
        assert _read(CLOSED_DOCUMENTS[3]).count(name) == 0


def test_interaction_modes_foreground_scoped():
    """Before: INTERACTION_MODES tiene regla foreground. During: delimita su region. After: remite sin cifras."""
    text = _region(
        _read(CLOSED_DOCUMENTS[2]),
        "## Foreground vs background for long-running suite commands",
        "## Minimum terminal commands",
    )
    assert "sin vuelo activo" in text
    assert "espera_trabajo_paralelo" in text
    assert "300" not in text


def test_variance_rule_citation_aligned():
    """Before: variance conserva el incidente. During: inspecciona desde su ancla. After: cita la regla alineada."""
    text = _read(CLOSED_DOCUMENTS[5]).split(
        "## Nota sobre el incidente WOT-2026-010o (background vs foreground)", 1
    )[1]
    assert text.count("Regla operacional") == 1
    assert "espera_trabajo_paralelo" in text
    assert "5m30" in text


def test_flight_supervision_unique_threshold_block():
    """Before: supervision tiene valores y clauses. During: acota el bloque. After: hay una sola semantica sin cifras."""
    path = CLOSED_DOCUMENTS[6]
    text = _read(path)
    heading = (
        "### Umbrales de relevo por contexto (fuente de cifras: flight_roster.json)"
    )
    assert [line for line in text.splitlines() if line == heading] == [heading]
    block = _region(
        text,
        "### Valores vigentes a 2026-10-30 en el roster",
        "### Clauses de la regla",
    )
    assert "flight_roster.json" in block
    threshold_block = block.split(heading, 1)[1]
    assert "precedencia" in threshold_block.lower()
    assert len(re.findall(r"(?i)[0-9][0-9]{0,3}\s?[kK]\b", threshold_block)) == 0
    heading_count = sum(
        _read(doc).splitlines().count(heading) for doc in CLOSED_DOCUMENTS
    )
    assert heading_count == 1


def test_anchor_checker_flags_injected_literal(tmp_path):
    """Before: el verificador trabaja por anclas. During: prueba copia conforme y mutante. After: el mutante cae."""
    source = CLOSED_DOCUMENTS[1]
    copied = tmp_path / source.name
    copied.write_text(_read(source), encoding="utf-8")
    start = "### Alarma de contexto (sintoma)"
    end = "## 10. Cadena de ancestros (consulta escalonada)"
    pattern = r"(?i)[0-9][0-9]{0,3}\s?[kK]\b"
    assert _count_region(copied, start, end, pattern) == 0
    copied.write_text(
        copied.read_text(encoding="utf-8").replace(start, start + "\n350k"),
        encoding="utf-8",
    )
    assert _count_region(copied, start, end, pattern) == 1
    assert _count_region(source, start, end, pattern) == 0


def test_flight_push_policy_citation_by_text():
    """Before: policy remite al bootstrap. During: normaliza su cita. After: no depende de lineas."""
    text = _normal(_read(CLOSED_DOCUMENTS[7]))
    assert ":318-319" not in text
    assert 'seccion "Modo ORQUESTADOR de pipeline multi-ticket (paso 0)"' in text
    assert (
        "UN solo push al final de TODOS los tickets de la cola/vuelo, con OK humano explicito"
        in text
    )
