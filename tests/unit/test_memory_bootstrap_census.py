"""Tests para memory_bootstrap_census.py (WOT-2026-058c).

Contrato T-058C-001 (DoD c y d):
  (c) MUTACION: retirar la cita de un rol -> el censo lo NOMBRA.
  (d) CONTROL NEGATIVO: una superficie que solo menciona --status NO cuenta
      como cubierta.

Hermetico: fixture en tmp_path; solo test_shared_doc_citado_por_tres_familias
lee el arbol real del motor.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]

_census_spec = importlib.util.spec_from_file_location(
    "memory_bootstrap_census",
    _MOTOR_ROOT / "scripts" / "memory_bootstrap_census.py",
)
_census_mod = importlib.util.module_from_spec(_census_spec)
sys.modules["memory_bootstrap_census"] = _census_mod
_census_spec.loader.exec_module(_census_mod)


def _make_motor(tmp: Path, structure: dict[str, str]) -> Path:
    for rel, body in structure.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def _run_census(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(_MOTOR_ROOT / "scripts" / "memory_bootstrap_census.py"),
            "--root",
            str(root),
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_mutacion_cita_rol(tmp_path: Path) -> None:
    """Una superficie con SOLO la cita al shared ('memory_bootstrap') es CUBIERTA;
    sin la cita, el censo la NOMBRA en NO_CUBIERTAS."""
    motor = _make_motor(
        tmp_path,
        {
            "prompts/alpha.md": "# Prompt Alpha\nContenido generico.\n",
            "skills/beta/SKILL.md": "# Skill Beta\nDescripcion.\n",
            ".claude/rules/gamma.md": "# Rule Gamma\nRegla basica.\n",
        },
    )

    # Sin cita: todas son NO_CUBIERTAS
    result = _run_census(motor)
    assert result.returncode == 0
    stdout = _normalize(result.stdout)
    assert "prompts/alpha.md" in stdout
    assert "skills/beta/SKILL.md" in stdout
    assert "rules/gamma.md" in stdout
    assert "NO_CUBIERTAS:" in stdout

    # Con cita en alpha: alpha pasa a CUBIERTA
    alpha = motor / "prompts/alpha.md"
    alpha.write_text(
        "# Prompt Alpha\nVer memory_bootstrap.md para el mecanismo.\n",
        encoding="utf-8",
    )
    result = _run_census(motor)
    assert result.returncode == 0
    stdout = _normalize(result.stdout)
    assert "prompts/alpha.md" not in stdout.split("NO_CUBIERTAS:")[1]
    assert "skills/beta/SKILL.md" in stdout.split("NO_CUBIERTAS:")[1]
    assert ".claude/rules/gamma.md" in stdout.split("NO_CUBIERTAS:")[1]


def test_control_negativo_status(tmp_path: Path) -> None:
    """Una superficie que solo menciona 'memory_context.py --status' NO cuenta
    como cubierta (el token --status jamas suma)."""
    motor = _make_motor(
        tmp_path,
        {
            "prompts/delta.md": "# Delta\nEjecuta: memory_context.py --status\n",
            "skills/epsilon/SKILL.md": "# Epsilon\nVerificacion.\n",
        },
    )
    result = _run_census(motor)
    assert result.returncode == 0
    assert "prompts/delta.md" in _normalize(result.stdout).split("NO_CUBIERTAS:")[1]


def test_invocacion_cuenta(tmp_path: Path) -> None:
    """Una superficie con 'memory_context.py --recall --query x' SI cuenta como
    cubierta sin citar el shared."""
    motor = _make_motor(
        tmp_path,
        {
            "prompts/zeta.md": "# Zeta\nRecall: memory_context.py --recall --query 'test'\n",
            "skills/eta/SKILL.md": "# Eta\nBasico.\n",
        },
    )
    result = _run_census(motor)
    assert result.returncode == 0
    assert "prompts/zeta.md" not in _normalize(result.stdout).split("NO_CUBIERTAS:")[1]


def test_denominador(tmp_path: Path) -> None:
    """La salida contiene los totales por familia y el formato n/total (para TP-03)."""
    motor = _make_motor(
        tmp_path,
        {
            "prompts/one.md": "# One\nmemory_context.py --bootstrap\n",
            "skills/sk1/SKILL.md": "# SK1\nVer memory_bootstrap.\n",
            "skills/sk2/SKILL.md": "# SK2\nBasico.\n",
            ".claude/rules/r1.md": "# R1\nmemory_context.py --recall\n",
        },
    )
    result = _run_census(motor)
    assert result.returncode == 0
    lines = result.stdout.strip().split("\n")
    families_found = set()
    for line in lines:
        m = re.match(r"^(PROMPTS|SKILLS|RULES): (\d+)/(\d+)$", line)
        if m:
            families_found.add(m.group(1))
    assert families_found == {"PROMPTS", "SKILLS", "RULES"}
    m_total = re.search(r"^TOTAL: (\d+)/(\d+)$", result.stdout, re.MULTILINE)
    assert m_total, f"TOTAL line missing in output:\n{result.stdout}"
    assert int(m_total.group(2)) == 1 + 2 + 1


def test_shared_doc_citado_por_tres_familias() -> None:
    """INVARIANTE con suelo: >=1 rol de cada familia cita el shared en el arbol
    REAL del motor. Pinna el SUELO, nunca la lista cerrada de nombres."""
    families = {
        "PROMPTS": sorted(_MOTOR_ROOT.glob("prompts/*.md")),
        "SKILLS": sorted(_MOTOR_ROOT.glob("skills/*/SKILL.md")),
        "RULES": sorted(_MOTOR_ROOT.glob(".claude/rules/*.md")),
    }
    for label, files in families.items():
        hits = 0
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: S112 - skip unreadable files in census
                continue
            if "memory_bootstrap" in text:
                hits += 1
        assert hits >= 1, (
            f"Familia {label}: ninguna superficie cita 'memory_bootstrap' "
            f"en el arbol real del motor ({len(files)} ficheros revisados)"
        )
