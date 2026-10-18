"""Tests for scripts/check_contract_full_read.py (WOT-2026-042z).

Cubre los DoD (a)-(e) del work_plan:
  (a) el check verifica lectura completa y FALLA nombrando fichero + lineas
  (b) distingue LEER de GREPEAR (grep/diff no cuentan)
  (c) MUTATION en DOS direcciones: full-read->VERDE, grep-only->ROJO con
      lineas ausentes enumeradas
  (d) ANTI-FALSO-POSITIVO: muestreo declarado -> WARN, no ERROR
  (e) check_guard_wiring exit 0 (cableado declarado) -- probado via subprocess
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


# ------------------------------------------------------------------ helpers
_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_contract_full_read.py"


def _write_artifact(tmp_path: Path, name: str, content: str) -> Path:
    """Write an artifact file and return its path."""
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _write_telemetry_file(
    tmp_path: Path,
    events: list[dict[str, object]],
) -> Path:
    """Write a tool_usage.jsonl telemetry file and return its path."""
    telemetry_dir = tmp_path / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    telemetry_file = telemetry_dir / "tool_usage.jsonl"
    with telemetry_file.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return telemetry_file


def _create_mini_motor(
    tmp_path: Path,
    files: dict[str, str],
    telemetry_events: list[dict[str, object]] | None = None,
) -> tuple[Path, Path]:
    """Create a minimal motor structure.

    Returns (motor_root, telemetry_dir).
    """
    # Create the motor root as a subdirectory so _SCRIPT can resolve it
    motor_root = tmp_path / "motor"
    motor_root.mkdir(exist_ok=True)
    scripts_dir = motor_root / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    # Copy the check script
    import shutil

    shutil.copy2(_SCRIPT, scripts_dir / "check_contract_full_read.py")

    # Create referenced files
    for rel_path, content in files.items():
        fp = motor_root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    # Create telemetry
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    if telemetry_events is not None:
        telemetry_file = telemetry_dir / "tool_usage.jsonl"
        with telemetry_file.open("w", encoding="utf-8") as f:
            for ev in telemetry_events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    else:
        # Create empty telemetry file so load_read_events doesn't skip
        (telemetry_dir / "tool_usage.jsonl").write_text("", encoding="utf-8")

    return motor_root


def _run_check(
    motor_root: Path,
    artifact_path: Path,
    telemetry_dir: Path | None = None,
) -> tuple[int, str, str]:
    """Run the check script and return (rc, stdout, stderr)."""
    cmd = [
        sys.executable,
        str(_SCRIPT),
        str(artifact_path),
    ]
    if telemetry_dir:
        cmd.append(str(telemetry_dir))
    cmd.append("--motor-root")
    cmd.append(str(motor_root))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(motor_root),
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


# ------------------------------------------------------------------ DoD (a): check verifies full read and FAILS naming file
#              + lineas ausentes


def test_dod_a_full_read_passes(tmp_path: Path) -> None:
    """DoD (a): sesion que leyo el contrato entero -> VERDE."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\n"},
        [
            {
                "context": "Read file prompts/sample.md, 3 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Se debe leer `prompts/sample.md` entero antes de trabajar.",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, stderr = _run_check(motor_root, artifact, telemetry_dir)

    assert rc == 0, (
        f"Expected PASS (rc=0), got rc={rc}\nstdout: {stdout}\nstderr: {stderr}"
    )
    assert "PASS" in stdout or "todos los ficheros citados leidos enteramente" in stdout


def test_dod_a_missing_read_fails(tmp_path: Path) -> Path:
    """DoD (a): fichero citado sin evento Read -> FAIL con nombre + lineas ausentes."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\n"},
        [],  # no telemetry events at all
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Se debe leer `prompts/sample.md` entero antes de trabajar.",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)

    assert rc == 1, f"Expected FAIL (rc=1), got rc={rc}"
    assert "prompts/sample.md" in stdout or "sample.md" in stdout
    assert "FAIL" in stdout or "ERROR" in stdout or "ausentes" in stdout


# ------------------------------------------------------------------ DoD (b): distingue LEER de GREPEAR


def test_dod_b_grep_does_not_count(tmp_path: Path) -> Path:
    """DoD (b): grep/diff NO cuentan como lectura -> FAIL."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\n"},
        [
            # A grep-like context should NOT be treated as a Read event
            {
                "context": "Executed grep prompts/sample.md",
                "tool_name": "grep",
                "timestamp": "2026-10-14T00:00:00Z",
            },
            {
                "context": "Executed diff prompts/sample.md",
                "tool_name": "diff",
                "timestamp": "2026-10-14T00:00:00Z",
            },
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Se debe leer `prompts/sample.md` entero antes de trabajar.",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)

    # grep/diff events should NOT provide read coverage
    assert rc == 1, f"Expected FAIL (grep doesn't count), got rc={rc}\nstdout: {stdout}"


def test_dod_b_read_with_enough_lines_passes(tmp_path: Path) -> Path:
    """DoD (b): evento Read REAL con line_count >= wc -> VERDE."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\nline4\nline5\n"},
        [
            {
                "context": "Read file prompts/sample.md, 5 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Se debe leer `prompts/sample.md` entero antes de trabajar.",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)

    assert rc == 0, f"Expected PASS (real Read covers), got rc={rc}\nstdout: {stdout}"


# ------------------------------------------------------------------ DoD (c): MUTATION en DOS direcciones


def test_dod_c_mutation_full_read_green(tmp_path: Path) -> Path:
    """DoD (c) direccion 1: full read -> VERDE (mutacion: añadir Read -> verde)."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\n"},
        [],  # start with no telemetry
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Se debe leer `prompts/sample.md` entero antes de trabajar.",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    # Without Read: should FAIL
    rc_before, _, _ = _run_check(motor_root, artifact, telemetry_dir)
    assert rc_before == 1, "Without Read: should FAIL"

    # Add the Read event
    telemetry_file = telemetry_dir / "tool_usage.jsonl"
    with telemetry_file.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "context": "Read file prompts/sample.md, 3 lines",
                    "tool_name": "view_file",
                    "timestamp": "2026-10-14T00:00:01Z",
                }
            )
            + "\n"
        )

    # After adding Read: should PASS (mutation: no Read -> Read -> FAIL -> PASS)
    rc_after, stdout_after, _ = _run_check(motor_root, artifact, telemetry_dir)
    assert rc_after == 0, (
        f"After adding Read: should PASS, got rc={rc_after}\nstdout: {stdout_after}"
    )


def test_dod_c_mutation_grep_only_red(tmp_path: Path) -> Path:
    """DoD (c) direccion 2: solo grep -> ROJO con lineas ausentes enumeradas."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\nline4\nline5\n"},
        [
            {
                "context": "Executed grep --line-number prompts/sample.md pattern",
                "tool_name": "grep",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Se debe leer `prompts/sample.md` entero antes de trabajar.",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, stderr = _run_check(motor_root, artifact, telemetry_dir)

    assert rc == 1, f"grep-only should FAIL, got rc={rc}"
    # Should enumerate missing lines
    output = stdout + stderr
    assert "ausentes" in output or "missing" in output.lower(), (
        f"Should enumerate missing lines, got: {output}"
    )


def test_dod_c_mutation_partial_read_red(tmp_path: Path) -> Path:
    """DoD (c): lectura parcial sin declaracion -> ROJO con lineas ausentes."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\nline4\nline5\n"},
        [
            {
                # Read only 2 lines of 5
                "context": "Read file prompts/sample.md, 2 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Se debe leer `prompts/sample.md` entero antes de trabajar.",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, stderr = _run_check(motor_root, artifact, telemetry_dir)

    assert rc == 1, f"Partial read (2/5) without declaration should FAIL, got rc={rc}"
    output = stdout + stderr
    assert "ausentes" in output or "2/5" in output or "2/" in output, (
        f"Should show partial read info, got: {output}"
    )


# ------------------------------------------------------------------ DoD (d): ANTI-FALSO-POSITIVO (muestreo declarado -> WARN)


def test_dod_c_sampling_declared_warn(tmp_path: Path) -> Path:
    """DoD (d): muestreo declarado explicitamente -> WARN, no ERROR."""
    motor_root = _create_mini_motor(
        tmp_path,
        {
            "prompts/sample.md": "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n"
        },
        [
            {
                # Read only 3 lines of 10
                "context": "Read file prompts/sample.md, 3 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        (
            "Muestreo explicito: leo solo :1-3 por <motivo>, riesgo <Z>\n"
            "Referencia: `prompts/sample.md`"
        ),
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    _, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)

    # Should be WARN not ERROR: muestreo declarado pasa con WARN
    output = stdout
    assert "WARN" in output, f"Expected WARN for declared sampling, got: {output}"
    # Should still flag it as incomplete (WARN is not PASS)
    assert (
        "muestreo" in output.lower()
        or "muestr" in output.lower()
        or "sample" in output.lower()
    ), f"Should mention sampling, got: {output}"


def test_dod_c_sampling_no_declaration_fails(tmp_path: Path) -> Path:
    """DoD (d): sin muestreo declarado, lectura parcial -> FAIL (no solo WARN)."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\nline4\nline5\n"},
        [
            {
                "context": "Read file prompts/sample.md, 2 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Referencia: `prompts/sample.md`",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, stderr = _run_check(motor_root, artifact, telemetry_dir)

    # No sampling declaration: partial read -> FAIL
    assert rc == 1, f"Partial read without declaration should FAIL, got rc={rc}"
    output = stdout + stderr
    # Should NOT be just a warning
    assert "ERROR" in output or "FAIL" in output, (
        f"Should have ERROR/FAIL without declaration, got: {output}"
    )


def test_dod_c_sampling_range_covers_full(tmp_path: Path) -> Path:
    """DoD (d): muestreo con rango que cubre todo el fichero -> WARN (cubierta completa)."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\n"},
        [
            {
                "context": "Read file prompts/sample.md, 3 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        (
            "Muestreo explicito: leo solo :1-3 por <motivo>, riesgo <Z>\n"
            "Referencia: `prompts/sample.md`"
        ),
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)

    # The Read event already covers all 3 lines, and the sampling declaration
    # :1-3 also covers all 3 lines -> should be covered
    assert rc == 0, (
        f"Should PASS (covered by both Read and sampling), got rc={rc}\nstdout: {stdout}"
    )


# ------------------------------------------------------------------ DoD (e): cableado en guard_wiring_policy.yaml + check_guard_wiring


def test_dod_e_wiring_declared(tmp_path: Path) -> Path:
    """DoD (e): el hook new está en el pre-commit YAML (CONFIG path del ORC)."""
    precommit = _ROOT / ".pre-commit-config.yaml"
    assert precommit.is_file(), ".pre-commit-config.yaml debe existir"
    content = precommit.read_text(encoding="utf-8")
    assert "check-contract-full-read" in content, (
        ".pre-commit-config.yaml debe contener 'check-contract-full-read'"
    )


def test_dod_e_check_guard_wiring_passes(tmp_path: Path) -> None:
    """DoD (e): check_guard_wiring.py no reporta check_contract_full_read como UNDECLARED.

    El guard es WIRED via CONFIG path (pre-commit YAML entry:), no necesita
    declaracion en guard_wiring_policy.yaml.
    """
    result = subprocess.run(
        [
            sys.executable,
            str(_ROOT / "scripts" / "check_guard_wiring.py"),
        ],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Expected check_guard_wiring to exit 0, got rc={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout + result.stderr
    # Verificar que check_contract_full_read no es UNDECLARED
    # Si aparece en la lista "declared, each with its owner", es UNDECLARED (stale)
    assert (
        "check_contract_full_read" not in output
        or "declared, each with its owner" not in output
    ), f"check_contract_full_read no debe aparecer como UNDECLARED: {output[:500]}"


def test_no_citations_returns_0(tmp_path: Path) -> Path:
    """Artifact sin citas -> PASS (0 citations)."""
    motor_root = _create_mini_motor(tmp_path, {}, [])
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Este artefacto no cita ningun fichero externo.\n",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)
    assert rc == 0, f"Expected PASS with no citations, got rc={rc}\nstdout: {stdout}"


def test_relative_citation_path(tmp_path: Path) -> Path:
    """Cita con ruta relativa se resuelve correctamente."""
    motor_root = _create_mini_motor(
        tmp_path,
        {
            "prompts/sample.md": "line1\nline2\nline3\n",
            "scripts/guard.py": "def check():\n    pass\n",
        },
        [
            {
                "context": "Read file prompts/sample.md, 3 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            },
            {
                "context": "Read file scripts/guard.py, 3 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:01Z",
            },
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        ("Cita 1: `prompts/sample.md`\nCita 2: `scripts/guard.py`\n"),
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, stderr = _run_check(motor_root, artifact, telemetry_dir)
    assert rc == 0, (
        f"Both files should be covered, got rc={rc}\nstdout: {stdout}\nstderr: {stderr}"
    )


def test_quote_style_citation(tmp_path: Path) -> Path:
    """Cita con comillas dobles también se detecta."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/quoted.md": "line1\nline2\n"},
        [
            {
                "context": "Read file prompts/quoted.md, 2 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        'Se debe leer "prompts/quoted.md" entero antes de trabajar.',
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)
    assert rc == 0, f"Quoted citation should be detected, got rc={rc}\nstdout: {stdout}"


def test_backslash_citation_path(tmp_path: Path) -> Path:
    """Cita con backslash se normaliza."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts\\sample.md": "line1\nline2\nline3\n"},
        [
            {
                "context": "Read file prompts\\sample.md, 3 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Cita con backslash: `prompts\\sample.md`",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, stderr = _run_check(motor_root, artifact, telemetry_dir)
    assert rc == 0, (
        f"Backslash citation should work, got rc={rc}\nstdout: {stdout}\nstderr: {stderr}"
    )


def test_read_lines_less_than_wc_fails(tmp_path: Path) -> Path:
    """Read con line_count < wc real -> FAIL enumerando ausentes."""
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\nline4\nline5\n"},
        [
            {
                # Simulates reading a truncated version (only 2 lines captured)
                "context": "Read file prompts/sample.md, 2 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Cita: `prompts/sample.md`",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)
    assert rc == 1, f"Partial read should FAIL, got rc={rc}"
    assert (
        "2/5" in stdout
        or "ausentes" in stdout
        or "3" in stdout
        or "4" in stdout
        or "5" in stdout
    )


def test_nonexistent_file_warning(tmp_path: Path) -> Path:
    """Cita a fichero que no existe en el motor -> WARN (saltado), no ERROR."""
    motor_root = _create_mini_motor(tmp_path, {}, [])
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Cita: `prompts/nonexistent.md` (no existe)",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)
    # Should not fail (can't check what doesn't exist), but should warn
    assert rc == 0, f"Nonexistent file should not fail, got rc={rc}\nstdout: {stdout}"
    assert (
        "no se resolvio" in stdout
        or "saltado" in stdout
        or "WARN" in stdout
        or "unresolved" in stdout.lower()
    )


# ------------------------------------------------------------------ B4: 'lines X-Y' format + B3: session scoping


def test_dod_sampling_lines_x_y_format(tmp_path: Path) -> Path:
    """B4: la forma documentada 'lines 100-200' pasa con WARN, no crash."""
    motor_root = _create_mini_motor(
        tmp_path,
        {
            "prompts/sample.md": "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n"
        },
        [
            {
                "context": "Read file prompts/sample.md, 3 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        (
            "Solo leo lines 1-3 por <motivo>, riesgo <Z>\n"
            "Referencia: `prompts/sample.md`"
        ),
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)

    # Must NOT crash (TypeError from group(2) being None)
    # Should be WARN not ERROR: declared sampling
    assert rc == 0, (
        f"Expected PASS with WARN (lines X-Y format), got rc={rc}\nstdout: {stdout}"
    )
    assert "WARN" in stdout, f"Expected WARN for declared sampling, got: {stdout}"


def test_dod_b3_session_scoping(tmp_path: Path) -> Path:
    """B3: session_id filtrado -> eventos de otra sesion NO cuentan.

    Two sessions: A leyo entero + B solo grepeo. Con --session-id=B, la cita
    debe FALLAR (B no leyo).
    """
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/sample.md": "line1\nline2\nline3\n"},
        [
            # Session A: full read
            {
                "context": "Read file prompts/sample.md, 3 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
                "session_id": "session-a",
            },
            # Session B: only grep (no read)
            {
                "context": "Executed grep prompts/sample.md",
                "tool_name": "grep",
                "timestamp": "2026-10-14T00:00:01Z",
                "session_id": "session-b",
            },
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Referencia: `prompts/sample.md`",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    # Without session filter: session A covers -> PASS
    cmd = [
        sys.executable,
        str(_SCRIPT),
        str(artifact),
        str(telemetry_dir),
        "--motor-root",
        str(motor_root),
    ]
    result_no_filter = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(motor_root), timeout=30
    )
    assert result_no_filter.returncode == 0, (
        f"Without session filter should PASS (session A covers), got rc={result_no_filter.returncode}"
    )

    # With session-b filter: B has no Read -> FAIL
    cmd_with_filter = [*cmd, "--session-id", "session-b"]
    result_filtered = subprocess.run(
        cmd_with_filter, capture_output=True, text=True, cwd=str(motor_root), timeout=30
    )
    assert result_filtered.returncode == 1, (
        f"With --session-id=session-b should FAIL (B only grepped), got rc={result_filtered.returncode}"
    )


def test_dod_b3_full_path_no_suffix_false_positive(tmp_path: Path) -> Path:
    """B3: homonimos en rutas distintas NO se confunden (full path match).

    Two files with same name in different dirs: only the exact match counts.
    """
    motor_root = _create_mini_motor(
        tmp_path,
        {
            "prompts/a/sample.md": "line1\nline2\nline3\n",
            "prompts/b/sample.md": "line1\nline2\nline3\nline4\nline5\n",
        },
        [
            # Read file in prompts/a/ (3 lines)
            {
                "context": "Read file prompts/a/sample.md, 3 lines",
                "tool_name": "view_file",
                "timestamp": "2026-10-14T00:00:00Z",
            }
        ],
    )

    # Artifact cites prompts/b/sample.md (5 lines) — should FAIL because only
    # prompts/a/sample.md was read (same name, different path).
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Cita: `prompts/b/sample.md`",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, _ = _run_check(motor_root, artifact, telemetry_dir)
    assert rc == 1, (
        f"Homonimo en ruta distinta NO debe contar como cobertura. rc={rc}, stdout={stdout}"
    )


# ------------------------------------------------------------------ WOT-2026-104j: lecturas paginadas


_PAGINATED_TOTAL_LINES = 968
_PAGINATED_FIRST_PAGE = 563
_PAGINATED_SECOND_PAGE = 405


def _large_file_content(total_lines: int) -> str:
    """Return deterministic content with exactly ``total_lines`` lines."""
    return "".join(f"line{i}\n" for i in range(1, total_lines + 1))


def test_paginated_read_union_coverage(tmp_path: Path) -> None:
    """DoD (a)/(b)/(d): 2 lecturas paginadas cubren el fichero -> PASS.

    ANTES del fix: max(563, 405) = 563 < 968 -> FAIL. Con union de rangos
    [1,563] U [563,968] -> PASS.
    """
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/large.md": _large_file_content(_PAGINATED_TOTAL_LINES)},
        [
            {
                "context": f"Read file prompts/large.md, {_PAGINATED_FIRST_PAGE} lines, offset=0",
                "tool_name": "view_file",
                "timestamp": "2026-10-18T00:00:00Z",
            },
            {
                "context": (
                    f"Read file prompts/large.md, {_PAGINATED_SECOND_PAGE} lines, "
                    f"offset={_PAGINATED_FIRST_PAGE}"
                ),
                "tool_name": "view_file",
                "timestamp": "2026-10-18T00:00:01Z",
            },
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Se debe leer `prompts/large.md` entero antes de trabajar.",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, stderr = _run_check(motor_root, artifact, telemetry_dir)

    assert rc == 0, (
        f"Lectura paginada completa debe PASS (union de rangos). "
        f"rc={rc}\nstdout: {stdout}\nstderr: {stderr}"
    )
    assert "PASS" in stdout


def test_paginated_read_gap_fails(tmp_path: Path) -> None:
    """DoD (c): 2 lecturas paginadas con HUECO -> FAIL con lineas ausentes.

    [1,300] U [600,900] de 968: faltan 301-599 y 901-968.
    """
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/large.md": _large_file_content(_PAGINATED_TOTAL_LINES)},
        [
            {
                "context": "Read file prompts/large.md, 300 lines, offset=0",
                "tool_name": "view_file",
                "timestamp": "2026-10-18T00:00:00Z",
            },
            {
                "context": "Read file prompts/large.md, 300 lines, offset=600",
                "tool_name": "view_file",
                "timestamp": "2026-10-18T00:00:01Z",
            },
        ],
    )
    artifact = _write_artifact(
        motor_root,
        "artifact.md",
        "Se debe leer `prompts/large.md` entero antes de trabajar.",
    )
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"

    rc, stdout, stderr = _run_check(motor_root, artifact, telemetry_dir)

    assert rc == 1, (
        f"Hueco entre lecturas paginadas debe FAIL. rc={rc}\n"
        f"stdout: {stdout}\nstderr: {stderr}"
    )
    output = stdout + stderr
    assert "ausentes" in output
    assert "301" in output, f"Debe enumerar el primer hueco (301), got: {output}"


def test_mutation_verify_max_logic_fails(tmp_path: Path) -> None:
    """DoD (d): discriminador de la mutacion `max`-de-un-evento.

    El propio fixture prueba la mutacion: la logica `max(line_count)` daria
    max(563, 405) = 563 < 968 -> FAIL, y con la union -> PASS. La mutacion REAL
    (repoblar `check_read_coverage` con `max` y ver el test paginado caer) se
    ejecuta aparte y queda registrada en el recibo del Builder.
    """
    line_counts = [_PAGINATED_FIRST_PAGE, _PAGINATED_SECOND_PAGE]
    assert max(line_counts) < _PAGINATED_TOTAL_LINES, (
        "El fixture debe ser discriminante: la logica max NO puede cubrir el fichero"
    )

    content = _large_file_content(_PAGINATED_TOTAL_LINES)
    first_page_event = {
        "context": f"Read file prompts/large.md, {_PAGINATED_FIRST_PAGE} lines, offset=0",
        "tool_name": "view_file",
        "timestamp": "2026-10-18T00:00:00Z",
    }
    second_page_event = {
        "context": (
            f"Read file prompts/large.md, {_PAGINATED_SECOND_PAGE} lines, "
            f"offset={_PAGINATED_FIRST_PAGE}"
        ),
        "tool_name": "view_file",
        "timestamp": "2026-10-18T00:00:01Z",
    }
    artifact_text = "Se debe leer `prompts/large.md` entero antes de trabajar."

    # Direccion 1: solo la primera pagina (equivale a "max de un evento") -> FAIL
    motor_root = _create_mini_motor(
        tmp_path,
        {"prompts/large.md": content},
        [first_page_event],
    )
    artifact = _write_artifact(motor_root, "artifact.md", artifact_text)
    telemetry_dir = motor_root / ".agent" / "runtime" / "telemetry"
    rc_one_event, stdout_one, _ = _run_check(motor_root, artifact, telemetry_dir)
    assert rc_one_event == 1, (
        f"Un solo evento (563/968) debe FAIL, got rc={rc_one_event}\nstdout: {stdout_one}"
    )

    # Direccion 2: la union de ambas paginas -> PASS
    telemetry_file = telemetry_dir / "tool_usage.jsonl"
    with telemetry_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(second_page_event, ensure_ascii=False) + "\n")
    rc_both, stdout_both, _ = _run_check(motor_root, artifact, telemetry_dir)
    assert rc_both == 0, (
        f"La union de las 2 paginas debe PASS, got rc={rc_both}\nstdout: {stdout_both}"
    )
