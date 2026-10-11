"""Tests for scripts/check_arranque_material_paths.py (WOT-2026-055s).

Barrera del DoD (c)/(d): material de arranque (ARRANQUE_/ENCARGO_/PROPUESTA_/
INCIDENT_) mal colocado en la RAIZ del destino -> ROJO por una barrera CABLEADA;
en la ruta declarada `orchestrator_pipeline/arranques/` -> VERDE; dentro de
`orchestrator_pipeline/reports/*` (Forbidden Surface con su propia allowlist de
prefijos) NUNCA dispara.

Cobertura (una idea por test):
  T-RED-RAIZ    : DoD (c) direccion ROJA -- ARRANQUE_MUTACION_PRUEBA.md en la
                  raiz -> find_misplaced lo lista y audit devuelve exit 1.
  T-VERDE-RUTA  : DoD (c) direccion VERDE -- el MISMO fichero movido a la ruta
                  declarada -> exit 0 y no se lista.
  T-NEG-REPORTS : DoD (d) control negativo -- prefijo gobernado DENTRO de
                  reports/ jamas dispara (raiz limpia -> exit 0).
  T-AMBITO      : ambito SOLO raiz, no recursivo -- prefijo gobernado en otro
                  subdirectorio no cuenta (ambito deliberado del contrato).
  T-CUATRO      : los 4 prefijos gobernados (README+.gitignore del destino) se
                  detectan en la raiz.
  T-DENOM       : el denominador (N ficheros, M gobernados) se publica SIEMPRE,
                  verde incluido.
  T-ORDEN       : find_misplaced devuelve nombres en orden alfabetico.
  T-FAILCLOSED  : raiz inexistente -> exit 1 (sin verde mudo sobre 0 ficheros).
  T-CLI         : main() --destino-root refleja audit() en ambos sentidos.
  T-CABLEADO    : run_arranque_material_paths_check (prepush) es BLOQUEANTE y
                  refleja audit() -- la barrera cableada del DoD (c).
  T-CALLSITE    : la linea de invocacion vive DENTRO del bloque `if
                  closeout_mode:` de prepush_check (cableado a un camino auto).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_arranque_material_paths",
    _ROOT / "scripts" / "check_arranque_material_paths.py",
)
cap = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cap)


def _write(path: Path, text: str = "prueba WOT-2026-055s\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


# ----------------------------------------------------------- T-RED-RAIZ (DoD c)
def test_arranque_en_raiz_es_rojo(tmp_path: Path):
    _write(tmp_path / "ARRANQUE_MUTACION_PRUEBA.md")
    assert cap.find_misplaced(tmp_path) == ["ARRANQUE_MUTACION_PRUEBA.md"]
    code, out = cap.audit(tmp_path)
    joined = "\n".join(out)
    assert code == 1
    assert "ARRANQUE_MUTACION_PRUEBA.md" in joined
    # el remitido a la ruta declarada es parte del diagnostico, no solo el conteo
    assert cap.DECLARED_ROUTE in joined


# --------------------------------------------------------- T-VERDE-RUTA (DoD c)
def test_el_mismo_fichero_en_la_ruta_declarada_es_verde(tmp_path: Path):
    _write(tmp_path / "ARRANQUE_MUTACION_PRUEBA.md")
    assert cap.audit(tmp_path)[0] == 1
    # MUTACION direccion 2: mover el MISMO fichero a la ruta declarada
    declared = tmp_path / "orchestrator_pipeline" / "arranques"
    declared.mkdir(parents=True)
    (tmp_path / "ARRANQUE_MUTACION_PRUEBA.md").replace(
        declared / "ARRANQUE_MUTACION_PRUEBA.md"
    )
    code, out = cap.audit(tmp_path)
    joined = "\n".join(out)
    assert code == 0
    assert "ARRANQUE_MUTACION_PRUEBA.md" not in joined


# ------------------------------------------------------ T-NEG-REPORTS (DoD d)
def test_control_negativo_reports_nunca_dispara(tmp_path: Path):
    """Forbidden Surface explicita: reports/* tiene su PROPIA allowlist de
    prefijos (backlog_triage_*, batch_run_*, MUTATION_WOT-*, ...) y jamas se
    comporta distinto por este guard."""
    _write(tmp_path / "orchestrator_pipeline" / "reports" / "ARRANQUE_en_reports.md")
    _write(tmp_path / "orchestrator_pipeline" / "reports" / "INCIDENT_en_reports.md")
    assert cap.find_misplaced(tmp_path) == []
    code, out = cap.audit(tmp_path)
    joined = "\n".join(out)
    assert code == 0
    assert "ARRANQUE_en_reports.md" not in joined
    assert "INCIDENT_en_reports.md" not in joined


# --------------------------------------------------------------- T-AMBITO
def test_prefijo_gobernado_en_otro_subdirectorio_no_cuenta(tmp_path: Path):
    """Ambito SOLO raiz (no recursivo), decidido en el contrato: un fichero
    gobernado que no esta ni en la raiz ni en la ruta declarada tampoco es
    fallo de ESTE guard."""
    _write(tmp_path / "docs" / "ARRANQUE_en_subdirectorio.md")
    _write(tmp_path / "orchestrator_pipeline" / "flight_plans" / "ENCARGO_x.md")
    assert cap.find_misplaced(tmp_path) == []
    assert cap.audit(tmp_path)[0] == 0


# ----------------------------------------------------------------- T-CUATRO
@pytest.mark.parametrize(
    "name",
    ["ARRANQUE_a.md", "ENCARGO_b.md", "PROPUESTA_c.md", "INCIDENT_d.md"],
)
def test_los_cuatro_prefijos_gobernados_se_detectan_en_raiz(tmp_path: Path, name: str):
    _write(tmp_path / name)
    assert cap.find_misplaced(tmp_path) == [name]
    code, out = cap.audit(tmp_path)
    assert code == 1
    assert name in "\n".join(out)


def test_fichero_sin_prefijo_en_raiz_no_dispara(tmp_path: Path):
    _write(tmp_path / "NOTAS_sueltas.md")
    assert cap.find_misplaced(tmp_path) == []
    assert cap.audit(tmp_path)[0] == 0


# ------------------------------------------------------------------ T-DENOM
def test_denominador_publicado_siempre_verde_incluido(tmp_path: Path):
    code, out = cap.audit(tmp_path)
    joined = "\n".join(out)
    assert code == 0
    assert "0 fichero(s) en la raiz" in joined
    assert "0 con prefijo gobernado" in joined


def test_denominador_publicado_tambien_en_rojo(tmp_path: Path):
    _write(tmp_path / "ARRANQUE_x.md")
    _write(tmp_path / "sueltas.md")
    code, out = cap.audit(tmp_path)
    joined = "\n".join(out)
    assert code == 1
    assert "2 fichero(s) en la raiz" in joined
    assert "1 con prefijo gobernado" in joined


# ------------------------------------------------------------------- T-ORDEN
def test_find_misplaced_devuelve_orden_alfabetico(tmp_path: Path):
    for name in ("ARRANQUE_z.md", "ENCARGO_a.md", "PROPUESTA_m.md"):
        _write(tmp_path / name)
    assert cap.find_misplaced(tmp_path) == [
        "ARRANQUE_z.md",
        "ENCARGO_a.md",
        "PROPUESTA_m.md",
    ]


# -------------------------------------------------------------- T-FAILCLOSED
def test_raiz_inexistente_es_fail_closed(tmp_path: Path):
    code, out = cap.audit(tmp_path / "no_existe")
    assert code == 1
    assert any("fail-closed" in ln for ln in out)
    assert cap.find_misplaced(tmp_path / "no_existe") == []


# -------------------------------------------------------------------- T-CLI
def test_cli_destino_root_refleja_audit(tmp_path: Path):
    assert cap.main(["--destino-root", str(tmp_path)]) == 0
    _write(tmp_path / "ARRANQUE_cli.md")
    assert cap.main(["--destino-root", str(tmp_path)]) == 1


# --------------------------------------------------------------- T-CABLEADO
def test_run_arranque_material_paths_check_es_bloqueante_y_refleja_audit(
    tmp_path: Path,
):
    """DoD (c): la deteccion vive en una barrera CABLEADA (prepush closeout),
    no en un script que nadie invoca."""
    from scripts.prepush_check import run_arranque_material_paths_check

    limpio = run_arranque_material_paths_check(tmp_path)
    assert limpio.is_blocking is True
    assert limpio.passed is True
    assert "fichero(s) en la raiz" in limpio.output  # denominador publicado

    _write(tmp_path / "ARRANQUE_prueba_cableado.md")
    rojo = run_arranque_material_paths_check(tmp_path)
    assert rojo.is_blocking is True
    assert rojo.passed is False
    assert "ARRANQUE_prueba_cableado.md" in rojo.output


def test_callsite_vive_dentro_del_bloque_closeout():
    src = (_ROOT / "scripts" / "prepush_check.py").read_text(encoding="utf-8")
    call = "results.append(run_arranque_material_paths_check(project_root))"
    assert call in src, "el check existe pero nadie lo invoca -> norma, no barrera"
    closeout = re.search(r"\n    if closeout_mode:\n", src)
    assert closeout is not None
    assert src.index(call) > closeout.start(), (
        "la invocacion debe vivir DENTRO del bloque if closeout_mode:, que es el "
        "camino automatico que conoce el project_root del destino"
    )
