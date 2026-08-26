"""Tests del detector de INSTRUCCION SIN INVOCADOR (WOT-2026-042m).

Contrato T-042M-001 (DoD binario de la ficha):
  (a) el detector existe y esta CABLEADO en un camino que corre solo;
  (b) MUTATION: un prompt que ordene ejecutar un script sin invocador
      automatico hace CAER el check;
  (c) los falsos positivos conocidos (BY-DESIGN / deuda declarada) se declaran
      con dueno, no se silencian.

El detector es de la HUELLA, no del cumplimiento (ficha): cruza dos objetos
discretos -- una cita de fichero en prompts/skills y el veredicto WIRED que
check_guard_wiring ya calcula. NO analiza prosa (muro WOT-2026-025c).

Hermetico: motor sintetico en tmp_path; el veredicto de audit() se calcula
sobre el arbol sintetico (policy vacia -> todo lo no cableado es UNWIRED).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    path = _MOTOR_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cpw = _load("check_prompt_wired_invocations")


def _motor(tmp_path: Path, prompts: dict[str, str] | None = None) -> Path:
    """Motor sintetico minimo: prompts/ + skills/ + scripts/ con un guard.

    El guard `check_zzz` se crea SOLO (sin cablear): es el caso base de la
    huella (citado sin invocador).
    """
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "check_zzz.py").write_text("# guard\n", encoding="utf-8")
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "skills" / "s").mkdir(parents=True, exist_ok=True)
    for rel, body in (prompts or {}).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    # El check_guard_wiring del motor real se importa; audit() lee MOTOR_ROOT.
    # Para el sintetico, audit(tmp_path) con policy vacia.
    return tmp_path


def _collect_names(root: Path) -> set[str]:
    return set(cpw.collect_citations(root).keys())


def test_042m_dod_a_detector_exists_and_scans_prompts(tmp_path: Path):
    """DoD (a): el detector existe y escanea prompts/*.md y skills/*/SKILL.md."""
    motor = _motor(
        tmp_path,
        {
            "prompts/cierre.md": "Corre `python scripts/check_zzz.py` antes de cerrar.\n",
            "skills/mi-skill/SKILL.md": "Barrera: scripts/check_zzz.py\n",
        },
    )
    names = _collect_names(motor)
    assert "check_zzz" in names


def test_042m_dod_b_unwired_script_cited_is_a_finding(tmp_path: Path):
    """DoD (b): un script citado sin invocador automatico es un HALLAZGO.

    `check_zzz` existe (denominador) pero NO esta cableado: audit() con policy
    vacia lo deja UNWIRED. El detector lo reporta como instruccion sin
    invocador. Mutation: si el detector no consultara audit(), este test cae.
    """
    motor = _motor(tmp_path, {"prompts/cierre.md": "Corre scripts/check_zzz.py.\n"})
    cgw = cpw._load_guard_wiring()
    hallazgos, _infos = cpw.classify(cpw.collect_citations(motor), cgw)
    assert any(name == "check_zzz" for name, _o, _w in hallazgos), hallazgos


def test_042m_dod_b_mutation_causes_failure(tmp_path: Path):
    """DoD (b), MUTACION por la ruta CLI: exit !=0 al citar un script sin cablear.

    El par es la barrera: el mismo motor con el prompt SEGURO da exit 0;
    con el prompt que cita un guard no cableado da exit 1.
    """
    motor = _motor(tmp_path)
    safe = motor / "prompts" / "ok.md"
    safe.write_text("Sin citas.\n", encoding="utf-8")
    rc_safe = cpw.main(["--motor-root", str(motor)])
    assert rc_safe == 0

    bad = motor / "prompts" / "bad.md"
    bad.write_text("Corre scripts/check_zzz.py.\n", encoding="utf-8")
    rc_bad = cpw.main(["--motor-root", str(motor)])
    assert rc_bad == 1


def test_042m_dod_c_declared_debt_is_not_a_finding(tmp_path: Path):
    """DoD (c): un guard citado PERO declarado como deuda con dueno no es hallazgo.

    La ficha: "los falsos positivos conocidos (BY-DESIGN como check_publication_gate)
    se declaran con dueno, no se silencian". Con una policy que declara check_zzz
    en known_unwired con dueno, el detector lo reporta como DECLARADO (INFO), no
    como hallazgo.
    """
    motor = _motor(tmp_path, {"prompts/cierre.md": "Barrera: scripts/check_zzz.py\n"})
    policy_yaml = motor / "scripts" / "guard_wiring_policy.yaml"
    policy_yaml.write_text(
        "known_unwired:\n  check_zzz: WOT-2026-000x\n", encoding="utf-8"
    )
    cgw = cpw._load_guard_wiring()
    # Reemplazar el path de la policy para que el sintetico la lea
    orig = cgw.POLICY_PATH
    cgw.POLICY_PATH = policy_yaml
    try:
        hallazgos, infos = cpw.classify(cpw.collect_citations(motor), cgw)
    finally:
        cgw.POLICY_PATH = orig
    assert not any(name == "check_zzz" for name, _o, _w in hallazgos), hallazgos
    assert any("check_zzz" in i and "DECLARADO" in i for i in infos), infos


def test_042m_non_prefixed_py_is_not_a_guard():
    """Un .py SIN prefijo guard (util) no es objeto del detector (declarado)."""
    text = "Corre python scripts/util_contador.py para el conteo."
    matches = cpw._GUARD_SCRIPT_RE.findall(text)
    assert matches == []


def test_042m_citations_deduplicate_origin(tmp_path: Path):
    """La misma cita en el mismo fichero no duplica el origen."""
    motor = _motor(
        tmp_path,
        {"prompts/cierre.md": "A: scripts/check_zzz.py\nB: scripts/check_zzz.py\n"},
    )
    citations = cpw.collect_citations(motor)
    origins = citations.get("check_zzz", [])
    assert len(origins) == 1, origins  # deduplicado por fichero
