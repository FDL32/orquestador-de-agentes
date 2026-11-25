"""Tests para check_process_decision_search.py (WOT-2026-104b y WOT-2026-231a).

Cablea la norma AGENTS.md "Decision de proceso sin instruccion exacta =>
BUSCA protocolo documentado antes de suponer uno" como barrera de FORMA.

WOT-2026-231a extiende con:
- Recibo PRIMARY_SOURCE_CHECK estructurado (TIPIFICADA-FORMA y NO TIPIFICADA)
- Resolucion y medicion viva de universo versionado
- Verificacion de citas (ruta, linea, subcadena literal)
- Modo obligatorio (--mandatory)
- Integracion con hook pre-commit y prueba de mutacion
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


MOTOR_ROOT = Path(__file__).resolve().parents[2]
GUARD = MOTOR_ROOT / "scripts" / "check_process_decision_search.py"

sys.path.insert(0, str(MOTOR_ROOT / "scripts"))
import check_process_decision_search as guard  # noqa: E402


_SIN_BUSQUEDA = "DECISION DE PROCESO: adoptamos X sin revisar nada antes.\n"


def _run(tmp_path: Path, text: str) -> subprocess.CompletedProcess:
    artefacto = tmp_path / "artefacto.md"
    artefacto.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(GUARD), str(artefacto)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_sin_marcador_no_aplica(tmp_path):
    r = _run(tmp_path, "Texto normal sin ningun marcador de proceso.\n")
    assert r.returncode == 0
    assert "no aplica" in r.stdout


def test_marcador_sin_busqueda_previa_bloquea(tmp_path):
    r = _run(tmp_path, _SIN_BUSQUEDA)
    assert r.returncode == 1
    assert "falta la seccion 'BUSQUEDA-PREVIA:'" in r.stderr


def test_marcador_con_no_encontre_protocolo_pasa(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: adoptamos X.\n"
        "BUSQUEDA-PREVIA: NO ENCONTRE PROTOCOLO tras grep en AGENTS.md.\n",
    )
    assert r.returncode == 0


def test_marcador_con_protocolo_encontrado_pasa(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: adoptamos X.\n"
        "BUSQUEDA-PREVIA: PROTOCOLO ENCONTRADO: prompts/ensemble_loop.md\n",
    )
    assert r.returncode == 0


def test_protocolo_encontrado_sin_ruta_bloquea(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: adoptamos X.\nBUSQUEDA-PREVIA: PROTOCOLO ENCONTRADO:\n",
    )
    assert r.returncode == 1
    assert "sin ruta" in r.stderr


def test_excepcion_trivial_con_texto_pasa(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: corrijo un typo en un comentario.\n"
        "BUSQUEDA-PREVIA: EXCEPCION: trivial -- typo sin ambiguedad de proceso.\n",
    )
    assert r.returncode == 0


def test_excepcion_trivial_sin_texto_bloquea(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: adoptamos X.\nBUSQUEDA-PREVIA: EXCEPCION: trivial\n",
    )
    assert r.returncode == 1
    assert "sin texto de justificacion" in r.stderr


def test_busqueda_previa_sin_forma_valida_bloquea(tmp_path):
    r = _run(
        tmp_path,
        "DECISION DE PROCESO: adoptamos X.\n"
        "BUSQUEDA-PREVIA: lo pense un rato y decidi que esta bien.\n",
    )
    assert r.returncode == 1
    assert "ninguna de las 3 formas validas" in r.stderr


def test_marcador_dentro_de_fence_no_dispara(tmp_path):
    r = _run(
        tmp_path,
        "Documentacion de ejemplo:\n"
        "```\n"
        "DECISION DE PROCESO: <texto>\n"
        "```\n"
        "Resto del documento sin BUSQUEDA-PREVIA.\n",
    )
    assert r.returncode == 0
    assert "no aplica" in r.stdout


def test_artefacto_inexistente_devuelve_2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(GUARD), str(tmp_path / "no_existe.md")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2


def test_mutacion_quitar_chequeo_busqueda_previa_invierte_el_veredicto(monkeypatch):
    """MUTACION (WOT-2026-104b, correccion de ambos lentes del bucle DBL-2):
    sin mutar, un documento con el marcador y sin BUSQUEDA-PREVIA: BLOQUEA
    (check_artifact devuelve un defecto, no None). Si se revierte el
    chequeo de busqueda_previa_defect() a 'siempre None' (equivalente a
    quitar la exigencia), el MISMO documento deja de bloquear. El test
    CLI bloqueante de arriba (test_marcador_sin_busqueda_previa_bloquea)
    fallaria contra esa version mutada -- esta prueba demuestra que la
    mutacion invierte el veredicto, confirmando que el test real depende
    del chequeo real y no es un falso verde."""
    veredicto_real = guard.check_artifact(_SIN_BUSQUEDA)
    assert veredicto_real is not None  # sin mutar: bloquea

    monkeypatch.setattr(guard, "busqueda_previa_defect", lambda text: None)
    veredicto_mutado = guard.check_artifact(_SIN_BUSQUEDA)
    assert veredicto_mutado is None  # mutado: deja de bloquear (veredicto invertido)


# =============================================================================
# WOT-2026-231a: PRIMARY_SOURCE_CHECK receipt, mandatory mode, and hook tests
# =============================================================================

_VALID_RECEIPT_TIPIFICADA = """
# Evidencia de admision
PRIMARY_SOURCE_CHECK:
  estado: TIPIFICADA-FORMA
  semantica_certificada: false
  comando: git ls-files
  cwd: .
  root: .
  fecha: 2026-11-24T13:00:00Z
  rc: 0
  universo:
    AGENTS.md: 1
  conteo_total: 1
  citas:
    - ruta: AGENTS.md
      linea: 1
      texto: "AGENTS.md - Instrucciones transversales"
"""

_VALID_RECEIPT_NO_TIPIFICADA = """
# Evidencia de admision conflictiva
PRIMARY_SOURCE_CHECK:
  estado: NO TIPIFICADA
  semantica_certificada: false
  comando: git ls-files
  cwd: .
  root: .
  fecha: 2026-11-24T13:00:00Z
  rc: 0
  conflicto: "Discrepancia detectada entre contrato y ejecucion local"
  siguiente_peldano: supervisora
  universo:
    AGENTS.md: 1
  conteo_total: 1
  control_positivo:
    universo:
      AGENTS.md: 1
    cita:
      ruta: AGENTS.md
      linea: 1
      texto: "AGENTS.md - Instrucciones transversales"
"""


def _run_mandatory(tmp_path: Path, text: str) -> subprocess.CompletedProcess:
    artefacto = tmp_path / "artefacto.md"
    artefacto.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(GUARD), "--mandatory", str(artefacto)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(MOTOR_ROOT),
    )


def test_mandatory_sin_recibo_falla(tmp_path):
    """m-06: --mandatory exige recibo PRIMARY_SOURCE_CHECK incluso sin marcador."""
    r = _run_mandatory(tmp_path, "Texto plano sin ningun marcador ni recibo.\n")
    assert r.returncode == 1
    assert (
        "modo obligatorio activado pero falta el recibo 'PRIMARY_SOURCE_CHECK:'"
        in r.stderr
    )


def test_mandatory_con_recibo_valido_pasa(tmp_path):
    """m-06: --mandatory pasa con recibo PRIMARY_SOURCE_CHECK valido."""
    r = _run_mandatory(tmp_path, _VALID_RECEIPT_TIPIFICADA)
    assert r.returncode == 0
    assert "declara recibo valido" in r.stdout
    assert (
        "la forma verificable ha sido contrastada; la semantica de la cita queda fuera del checker"
        in r.stdout
    )


def test_recibo_tipificada_citas_validacion(tmp_path):
    """m-04: valida resolucion de citas: ruta en universo, linea en rango, texto literal."""
    # Linea fuera de rango
    recibo_linea_invalida = _VALID_RECEIPT_TIPIFICADA.replace(
        "linea: 1", "linea: 999999"
    )
    r1 = _run_mandatory(tmp_path, recibo_linea_invalida)
    assert r1.returncode == 1
    assert "no existe en 'AGENTS.md'" in r1.stderr

    # Texto que no coincide
    recibo_texto_invalido = _VALID_RECEIPT_TIPIFICADA.replace(
        'texto: "AGENTS.md - Instrucciones transversales"',
        'texto: "Texto inexistente que no esta en linea 1"',
    )
    r2 = _run_mandatory(tmp_path, recibo_texto_invalido)
    assert r2.returncode == 1
    assert "no contiene el texto citado" in r2.stderr


def test_recibo_universo_conteo_y_raices(tmp_path):
    """m-03: checker mide conteo vivo, rechaza suma discordante o raiz vacia."""
    # Suma declarada no coincide con conteo_total
    recibo_suma_erronea = _VALID_RECEIPT_TIPIFICADA.replace(
        "conteo_total: 1", "conteo_total: 999"
    )
    r1 = _run_mandatory(tmp_path, recibo_suma_erronea)
    assert r1.returncode == 1
    assert "conteo_total (999) no coincide con la suma del universo (1)" in r1.stderr

    # Raiz declarada inexistente o vacia
    recibo_raiz_vacia = """
PRIMARY_SOURCE_CHECK:
  estado: TIPIFICADA-FORMA
  semantica_certificada: false
  comando: git ls-files
  cwd: .
  root: .
  fecha: 2026-11-24T13:00:00Z
  rc: 0
  universo:
    directorio_inexistente_xyz: 5
  conteo_total: 5
  citas:
    - ruta: directorio_inexistente_xyz/foo.md
      linea: 1
      texto: "algo"
"""
    r2 = _run_mandatory(tmp_path, recibo_raiz_vacia)
    assert r2.returncode == 1
    assert "esta vacia (0 ficheros encontrados)" in r2.stderr


def test_recibo_fuente_omitida_fuera_de_universo(tmp_path):
    """m-04 / limite mecanico: cita valida pero raiz no declarada en el universo del recibo."""
    recibo_omision = """
PRIMARY_SOURCE_CHECK:
  estado: TIPIFICADA-FORMA
  semantica_certificada: false
  comando: git ls-files
  cwd: .
  root: .
  fecha: 2026-11-24T13:00:00Z
  rc: 0
  universo:
    AGENTS.md: 1
  conteo_total: 1
  citas:
    - ruta: scripts/check_process_decision_search.py
      linea: 1
      texto: "def _measure_root_count"
"""
    r = _run_mandatory(tmp_path, recibo_omision)
    assert r.returncode == 1
    assert "esta fuera del universo declarado o es una fuente omitida" in r.stderr


def test_recibo_no_tipificada_valido_y_defectos(tmp_path):
    """m-05: NO TIPIFICADA exige conflicto, siguiente_peldano tipificado y control_positivo."""
    # Valido
    r_ok = _run_mandatory(tmp_path, _VALID_RECEIPT_NO_TIPIFICADA)
    assert r_ok.returncode == 0
    assert "declara recibo valido" in r_ok.stdout

    # Falta conflicto
    recibo_sin_conflicto = _VALID_RECEIPT_NO_TIPIFICADA.replace(
        'conflicto: "Discrepancia detectada entre contrato y ejecucion local"',
        'conflicto: ""',
    )
    r1 = _run_mandatory(tmp_path, recibo_sin_conflicto)
    assert r1.returncode == 1
    assert "falta el campo obligatorio 'conflicto'" in r1.stderr

    # Siguiente peldano no tipificado
    recibo_peldano_invalido = _VALID_RECEIPT_NO_TIPIFICADA.replace(
        "siguiente_peldano: supervisora",
        "siguiente_peldano: inventado",
    )
    r2 = _run_mandatory(tmp_path, recibo_peldano_invalido)
    assert r2.returncode == 1
    assert "el campo 'siguiente_peldano' ('inventado') debe ser uno de:" in r2.stderr

    # control_positivo con universo discordante
    recibo_cp_universo_mismatch = _VALID_RECEIPT_NO_TIPIFICADA.replace(
        "      AGENTS.md: 1\n    cita:",
        "    cita:",
    )
    r3 = _run_mandatory(tmp_path, recibo_cp_universo_mismatch)
    assert r3.returncode == 1
    assert (
        "el universo del control_positivo no coincide con las raices declaradas"
        in r3.stderr
    )


def test_recibo_rechaza_conteo_de_raiz_distinto_del_medido(tmp_path):
    """m-07: el conteo declarado por raiz debe coincidir con el conteo vivo."""
    receipt = _VALID_RECEIPT_TIPIFICADA.replace(
        "    AGENTS.md: 1", "    AGENTS.md: 2"
    ).replace("conteo_total: 1", "conteo_total: 2")
    result = _run_mandatory(tmp_path, receipt)
    assert result.returncode == 1
    assert "raiz 'AGENTS.md'" in result.stderr
    assert (
        "declarado para la raiz 'AGENTS.md' (2) no coincide con el medido (1)"
        in result.stderr
    )


def test_control_positivo_rechaza_mismos_nombres_conteos_distintos(tmp_path):
    """m-08: el control positivo compara nombres y conteos del universo."""
    receipt = _VALID_RECEIPT_NO_TIPIFICADA.replace(
        "      AGENTS.md: 1\n    cita:",
        "      AGENTS.md: 2\n    cita:",
    )
    result = _run_mandatory(tmp_path, receipt)
    assert result.returncode == 1
    assert "claves y conteos" in result.stderr


def test_recibo_no_cuenta_fichero_no_versionado_en_raiz(tmp_path):
    """m-07: el universo no puede inflarse con un fichero no trackeado."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    sources = repo / "sources"
    sources.mkdir()
    (sources / "AGENTS.md").write_text(
        "AGENTS.md - Instrucciones transversales\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "sources/AGENTS.md"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=test",
            "commit",
            "-m",
            "base",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (sources / "ignored.md").write_text("no es fuente versionada\n", encoding="utf-8")
    receipt = (
        _VALID_RECEIPT_TIPIFICADA.replace("    AGENTS.md: 1", "    sources: 2")
        .replace("conteo_total: 1", "conteo_total: 2")
        .replace("ruta: AGENTS.md", "ruta: sources/AGENTS.md")
    )
    defect, _ = guard.validate_primary_source_receipt(
        guard.extract_receipt_data(receipt), repo
    )
    assert defect is not None
    assert "raiz 'sources' (2) no coincide con el medido (1)" in defect


def test_recibo_rechaza_certificacion_de_semantica(tmp_path):
    """Rechazo tajante: el recibo no puede pretender certificar semantica."""
    recibo_semantica = _VALID_RECEIPT_TIPIFICADA.replace(
        "semantica_certificada: false",
        "semantica_certificada: true",
    )
    r = _run_mandatory(tmp_path, recibo_semantica)
    assert r.returncode == 1
    assert "la semantica de la cita no puede declararse como certificada" in r.stderr


def test_hook_entry_mandatory_execution_from_yaml(tmp_path):
    """m-06/m-07: ejecuta el entry real leido de .pre-commit-config.yaml con PyYAML.

    PyYAML ya se importa en tests/unit (p. ej. test_hook_ci_alignment.py,
    test_check_guard_denominator_policy.py, test_precommit_py_staged.py).
    """
    config_file = MOTOR_ROOT / ".pre-commit-config.yaml"
    with open(config_file, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    entry_cmd = None
    for repo in cfg.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") == "check-primary-source-mandatory":
                entry_cmd = hook.get("entry")
                break

    assert entry_cmd is not None
    assert "--mandatory" in entry_cmd

    cmd_parts = entry_cmd.split()
    script_idx = -1
    for i, p in enumerate(cmd_parts):
        if p.endswith("check_process_decision_search.py"):
            script_idx = i
            break
    assert script_idx != -1
    base_args = [
        sys.executable,
        str(MOTOR_ROOT / cmd_parts[script_idx]),
        *cmd_parts[script_idx + 1 :],
    ]

    # 1) Fixture sin marcador y sin recibo -> falla con rc 1
    fixture_sin_recibo = tmp_path / "sin_recibo.md"
    fixture_sin_recibo.write_text(
        "Texto plano sin marcador ni recibo.\n", encoding="utf-8"
    )
    r1 = subprocess.run(
        [*base_args, str(fixture_sin_recibo)],
        capture_output=True,
        text=True,
        cwd=str(MOTOR_ROOT),
    )
    assert r1.returncode == 1
    assert (
        "modo obligatorio activado pero falta el recibo 'PRIMARY_SOURCE_CHECK:'"
        in r1.stderr
    )

    # 2) Fixture con recibo valido -> pasa con rc 0
    fixture_valido = tmp_path / "valido.md"
    fixture_valido.write_text(_VALID_RECEIPT_TIPIFICADA, encoding="utf-8")
    r2 = subprocess.run(
        [*base_args, str(fixture_valido)],
        capture_output=True,
        text=True,
        cwd=str(MOTOR_ROOT),
    )
    assert r2.returncode == 0
    assert "declara recibo valido" in r2.stdout


def test_hook_entry_mutation_test_removes_mandatory(tmp_path):
    """MUTANTE (m-06/m-07): quita --mandatory de una COPIA del YAML.

    El test real exige rc 1 contra un fichero sin marcador ni recibo.
    Al ejecutar el entry del YAML mutado (sin --mandatory), el checker devuelve rc 0 (no aplica),
    demostrando que el mutante pone rojo el test que exige rc 1.
    """
    yaml_copy = tmp_path / ".pre-commit-config.yaml"

    config_file = MOTOR_ROOT / ".pre-commit-config.yaml"
    content = config_file.read_text(encoding="utf-8")

    mutated_content = content.replace(
        "entry: uv run python scripts/check_process_decision_search.py --mandatory",
        "entry: uv run python scripts/check_process_decision_search.py",
    )
    assert mutated_content != content, "La mutacion debe modificar el entry"
    yaml_copy.write_text(mutated_content, encoding="utf-8")

    with open(yaml_copy, encoding="utf-8") as f:
        mutated_cfg = yaml.safe_load(f)

    mutated_entry = None
    for repo in mutated_cfg.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") == "check-primary-source-mandatory":
                mutated_entry = hook.get("entry")
                break

    assert mutated_entry is not None
    assert "--mandatory" not in mutated_entry

    cmd_parts = mutated_entry.split()
    script_idx = -1
    for i, p in enumerate(cmd_parts):
        if p.endswith("check_process_decision_search.py"):
            script_idx = i
            break
    mutated_args = [
        sys.executable,
        str(MOTOR_ROOT / cmd_parts[script_idx]),
        *cmd_parts[script_idx + 1 :],
    ]

    fixture = tmp_path / "sin_recibo.md"
    fixture.write_text("Texto plano sin marcador ni recibo.\n", encoding="utf-8")

    r_mutated = subprocess.run(
        [*mutated_args, str(fixture)],
        capture_output=True,
        text=True,
        cwd=str(MOTOR_ROOT),
    )

    # Con el entry mutado (sin --mandatory), devuelve 0 (no aplica) en lugar de 1
    # Esto confirma que el test que asume r.returncode == 1 quedaria en ROJO
    assert r_mutated.returncode == 0
    assert "no declara DECISION DE PROCESO: (no aplica)" in r_mutated.stdout
