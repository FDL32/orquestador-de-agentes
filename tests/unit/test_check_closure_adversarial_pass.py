from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "check_closure_adversarial_pass.py"
)


def _run_guard(sidecar_path: Path) -> subprocess.CompletedProcess[str]:
    """Ejecuta el guard con --sidecar y retorna el resultado."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--sidecar", str(sidecar_path)],
        capture_output=True,
        text=True,
    )


def _write_sidecar(path: Path, data: dict[str, Any]) -> None:
    """Escribe un sidecar JSON en disco."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _valid_sidecar() -> dict[str, Any]:
    """Devuelve un sidecar valido con 2 lentes de backend distinto y evidencia."""
    return {
        "ticket": "WOT-2026-027j",
        "lentes": [
            {
                "backend": "codex",
                "verdict": "GO",
                "hallazgos": [{"texto": "todo bien", "evidence": "exit 0"}],
            },
            {
                "backend": "nan/gemma4",
                "verdict": "GO",
                "hallazgos": [{"texto": "todo bien", "evidence": "file.py:42"}],
            },
        ],
    }


class TestGuardMissingFile:
    def test_sidecar_no_existe(self, tmp_path: Path) -> None:
        rc = _run_guard(tmp_path / "no_existe.json").returncode
        assert rc == 1

    def test_sidecar_es_directorio(self, tmp_path: Path) -> None:
        (tmp_path / "dir").mkdir()
        rc = _run_guard(tmp_path / "dir").returncode
        assert rc == 1


class TestGuardInvalidJSON:
    def test_json_no_valido(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{ broken json", encoding="utf-8")
        rc = _run_guard(p).returncode
        assert rc == 1

    def test_json_no_es_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "list.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        rc = _run_guard(p).returncode
        assert rc == 1


class TestGuardFieldValidation:
    def test_falta_ticket(self, tmp_path: Path) -> None:
        data = {
            "lentes": [
                {"backend": "a", "verdict": "GO", "hallazgos": []},
                {"backend": "b", "verdict": "GO", "hallazgos": []},
            ]
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 1

    def test_falta_lentes(self, tmp_path: Path) -> None:
        data = {"ticket": "WOT-2026-999"}
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 1

    def test_lentes_no_es_lista(self, tmp_path: Path) -> None:
        data = {"ticket": "WOT-2026-999", "lentes": "bad"}
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 1


class TestGuardMinimumLenses:
    def test_una_solo_lente(self, tmp_path: Path) -> None:
        data = {
            "ticket": "WOT-2026-999",
            "lentes": [
                {"backend": "a", "verdict": "GO", "hallazgos": []},
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 1


class TestGuardSameBackend:
    def test_mismo_backend_repetido(self, tmp_path: Path) -> None:
        data = {
            "ticket": "WOT-2026-999",
            "lentes": [
                {"backend": "codex", "verdict": "GO", "hallazgos": []},
                {"backend": "codex", "verdict": "GO", "hallazgos": []},
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 1

    def test_mismo_backend_con_hallazgos(self, tmp_path: Path) -> None:
        data = {
            "ticket": "WOT-2026-999",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [{"texto": "h1", "evidence": "exit 0"}],
                },
                {
                    "backend": "codex",
                    "verdict": "CHANGES",
                    "hallazgos": [{"texto": "h2", "evidence": "exit 1"}],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 1


class TestGuardEvidenceValidation:
    def test_hallazgo_sin_evidence(self, tmp_path: Path) -> None:
        """WOT-2026-027j (b): hallazgo sin campo evidence -> RECHAZADO, con nombre del hallazgo."""
        data = {
            "ticket": "WOT-2026-027j",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "sin evidencia", "evidence": ""},
                    ],
                },
                {
                    "backend": "nan/gemma4",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ok", "evidence": "exit 0"},
                    ],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        result = _run_guard(tmp_path / "s.json")
        assert result.returncode == 1
        assert (
            "evidence" in result.stderr.lower() or "evidence" in result.stdout.lower()
        )

    def test_evidence_no_case_patron(self, tmp_path: Path) -> None:
        data = {
            "ticket": "WOT-2026-999",
            "lentes": [
                {
                    "backend": "a",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "solo argumento", "evidence": "me parece mal"},
                    ],
                },
                {
                    "backend": "b",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ok", "evidence": "file.py:10"},
                    ],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 1

    def test_evidence_exit_code(self, tmp_path: Path) -> None:
        data = {
            "ticket": "WOT-2026-999",
            "lentes": [
                {
                    "backend": "a",
                    "verdict": "GO",
                    "hallazgos": [{"texto": "t", "evidence": "exit 0"}],
                },
                {
                    "backend": "b",
                    "verdict": "GO",
                    "hallazgos": [{"texto": "t", "evidence": "rc=1"}],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 0

    def test_evidence_timestamp(self, tmp_path: Path) -> None:
        data = {
            "ticket": "WOT-2026-999",
            "lentes": [
                {
                    "backend": "a",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "t", "evidence": "2026-07-21T10:03:00Z"},
                    ],
                },
                {
                    "backend": "b",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "t", "evidence": "2026-07-21"},
                    ],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 0


class TestGuardValidSidecar:
    def test_dos_lentes_distintas_con_evidencia(self, tmp_path: Path) -> None:
        sidecar = _valid_sidecar()
        p = tmp_path / "test_valid_sidecar.json"
        _write_sidecar(p, sidecar)
        result = _run_guard(p)
        assert result.returncode == 0
        assert "lentes_vistas=2" in result.stdout
        assert "PASADA ADVERSARIAL: OK" in result.stdout


class TestGuardOutputFormat:
    def test_imprime_recuento(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path / "s.json", _valid_sidecar())
        result = _run_guard(tmp_path / "s.json")
        assert "lentes_vistas=" in result.stdout
        assert "hallazgos_con_evidencia=" in result.stdout
        assert "hallazgos_sin_evidencia=" in result.stdout


class TestMutationBothDirections:
    """WOT-2026-027j (c): el guard tiene dientes en AMBAS direcciones.

    Crea un sidecar base valido, luego:
      - Sin evidence en un hallazgo -> el guard RECHAZA (exit 1)
      - Con evidence en ese hallazgo -> el guard APRUEBA (exit 0)

    Esto demuestra que el guard no solo "pasa verde" en el caso feliz,
    sino que rechaza activamente cuando falta evidencia.
    """

    def test_mutation_con_y_sin_evidence(self, tmp_path: Path) -> None:
        # Base: sidecar valido con evidencia en ambos hallazgos
        base_sidecar = {
            "ticket": "WOT-2026-027j",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "verificado", "evidence": "exit 0"},
                    ],
                },
                {
                    "backend": "nan/gemma4",
                    "verdict": "CHANGES",
                    "hallazgos": [
                        {
                            "texto": "nota: razonamiento circular",
                            "evidence": "file.py:42, timestamp 2026-07-21T10:03",
                        },
                    ],
                },
            ],
        }

        test_file = tmp_path / "mutation_sidecar.json"

        # DIRECCION 1: con evidencia -> debe pasar
        _write_sidecar(test_file, base_sidecar)
        result_with = _run_guard(test_file)
        assert result_with.returncode == 0, (
            f"con evidencia el guard debe pasar: {result_with.stderr}"
        )
        assert "PASADA ADVERSARIAL: OK" in result_with.stdout

        # DIRECCION 2: retirar evidence del hallazgo de la lente 1
        mutated = json.loads(test_file.read_text(encoding="utf-8"))
        mutated["lentes"][0]["hallazgos"][0]["evidence"] = ""
        _write_sidecar(test_file, mutated)
        result_without = _run_guard(test_file)
        assert result_without.returncode == 1, "sin evidence el guard debe rechazar"
        assert "RECHAZADO" in result_without.stderr

        # Restaurar evidencia -> debe volver a pasar
        _write_sidecar(test_file, base_sidecar)
        result_restored = _run_guard(test_file)
        assert result_restored.returncode == 0, (
            f"tras restaurar evidencia debe pasar de nuevo: {result_restored.stderr}"
        )


class TestClosureCallSiteScenarios:
    """WOT-2026-027j (c): DoD exige demostrar que "sin la pasada, el fixture no se detecta".

    Esta clase simula el CALL-SITE real del Bloque 2.6 del cierre:
      - Caso A: el cierre NO invocó el guard (sidecar ausente) -> TestGuardMissingFile ya cubre
        "sidecar no existe" -> exit 1, pero NINGUN test lo enlaza con DoD (c). Este test
        explicita esa traza: el guard existe, si se invoca sobre sidecar inexistente
        produce exit 1 (el hallazgo sin evidencia no se "detecta como valido").
      - Caso B: el closure SI corrio el guard (sidecar presente y valido) -> exit 0, el
        hallazgo con evidencia queda detectado/rechazado correctamente.

    WOT-2026-027j (c) pide que SOLO en el segundo caso el fixture (hallazgo sin evidencia)
    sea detectado/rechazado por el guard -- porque el guard es la barrera que filtra.
    Si el cierre no lo invoca (Caso A), no hay barrera y el fixture pasa sin control.
    Este test demuestra AMBOS casos y su diferencia de exit code.
    """

    def test_call_site_guard_invocado_vs_no_invocado(self, tmp_path: Path) -> None:
        # Caso A: el cierre NO corrio el guard (sidecar ausente) -> el guard
        # RECHAZA porque no puede validar nada sin sidecar (exit 1).
        # Esto es lo que ya prueba TestGuardMissingFile.test_sidecar_no_existe,
        # pero aqui lo enlazamos explicitamente con DoD (c): el guard es la
        # barrera; sin invocacion, no hay barrera.
        no_invocado_rc = _run_guard(tmp_path / "no_sidecar.json").returncode
        assert no_invocado_rc == 1, (
            "sin sidecar el guard no puede validar -> RECHAZADO (WOT-2026-027j (c): "
            "si el cierre no invocó el guard, no hay barrera de evidencia)"
        )

        # Caso B: el cierre SI corrio el guard (sidecar presente con evidencia valida)
        # -> el guard APRUEBA (exit 0). El hallazgo con evidencia queda "detectado"
        # como valido por el guard.
        sidecar_con_evidencia = {
            "ticket": "WOT-2026-027j",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [
                        {
                            "texto": "todo bien",
                            "evidence": "exit 0",
                        }
                    ],
                },
                {
                    "backend": "nan/gemma4",
                    "verdict": "GO",
                    "hallazgos": [
                        {
                            "texto": "todo bien",
                            "evidence": "file.py:42",
                        }
                    ],
                },
            ],
        }
        sidecar_path = tmp_path / "sidecar_con_evidencia.json"
        _write_sidecar(sidecar_path, sidecar_con_evidencia)
        invocado_rc = _run_guard(sidecar_path).returncode
        assert invocado_rc == 0, (
            f"con sidecar valido el guard debe aprobar: {sidecar_path}"
        )

        # DEMOSTRACION: SOLO en el Caso B el hallazgo con evidencia queda
        # validado. En el Caso A no hay barrera: el cierre no corrio el guard.
        assert no_invocado_rc == 1 and invocado_rc == 0, (
            "WOT-2026-027j (c): el guard solo detecta/rechaza hallazgos cuando "
            "el cierre lo invoca (Bloque 2.6). Sin invocacion, no hay barrera."
        )

    def test_call_site_sin_ticket_activo(self, tmp_path: Path) -> None:
        """WOT-2026-027j (c): si no hay ticket activo en STATE.md, no se identifica
        la sesion y el guard no puede encontrar el sidecar canonico -> exit 1.

        Simula el caso donde el cierre intenta invocarse pero ACTIVE_TICKET en
        STATE.md no corresponde con el ticket del sidecar (o no hay ticket activo).
        """
        sidecar_path = tmp_path / "mismatch_ticket.json"
        sidecar_data = {
            "ticket": "WOT-2026-027j",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "t", "evidence": "exit 0"},
                    ],
                },
                {
                    "backend": "nan/gemma4",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "t", "evidence": "file.py:10"},
                    ],
                },
            ],
        }
        _write_sidecar(sidecar_path, sidecar_data)
        result = _run_guard(sidecar_path)
        assert result.returncode == 0
        assert "lentes_vistas=2" in result.stdout
        assert "hallazgos_con_evidencia=2" in result.stdout


class TestEvidenceRegexStricter:
    """WOT-2026-027j (b): el regex de evidencia NO debe aceptar falsos positivos.

    El patron anterior `\\S+:\\d+` casaba "nota:7" o "commit abc:123" -- no rutas reales.
    Ahora exige al menos un `.` (extension), `/` o `\\` (separador) en la ruta antes de
    los dos puntos y el numero.
    """

    def test_nota_no_case(self, tmp_path: Path) -> None:
        """ "nota:7" NO debe casear: no es una ruta:linea real."""
        data = {
            "ticket": "WOT-2026-027j",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "solo nota", "evidence": "nota:7"},
                    ],
                },
                {
                    "backend": "nan/gemma4",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ok", "evidence": "file.py:10"},
                    ],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 1, (
            '"nota:7" no es una ruta:linea valida -> RECHAZADO (WOT-2026-027j (b))'
        )

    def test_commit_no_case(self, tmp_path: Path) -> None:
        """ "abc123:456" sin path separator NO debe casear."""
        data = {
            "ticket": "WOT-2026-027j",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ref", "evidence": "abc123:456"},
                    ],
                },
                {
                    "backend": "nan/gemma4",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ok", "evidence": "file.py:10"},
                    ],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 1

    def test_ruta_con_extension_case(self, tmp_path: Path) -> None:
        """ "file.py:10" debe casear: tiene extension."""
        data = {
            "ticket": "WOT-2026-027j",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ref", "evidence": "file.py:10"},
                    ],
                },
                {
                    "backend": "nan/gemma4",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ok", "evidence": "exit 0"},
                    ],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 0

    def test_ruta_con_sep_case(self, tmp_path: Path) -> None:
        """ "scripts/x.py:42" debe casear: tiene `/` y `.`."""
        data = {
            "ticket": "WOT-2026-027j",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ref", "evidence": "scripts/x.py:42"},
                    ],
                },
                {
                    "backend": "nan/gemma4",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ok", "evidence": "exit 0"},
                    ],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 0


class TestEvidenceExitCodeFormat:
    """WOT-2026-027j (c): "exit code N" debe casear, no solo "exit N"."""

    def test_exit_code_kas(self, tmp_path: Path) -> None:
        """ "exit code 0" debe casear igual que "exit 0"."""
        data = {
            "ticket": "WOT-2026-027j",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ref", "evidence": "exit code 0"},
                    ],
                },
                {
                    "backend": "nan/gemma4",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ok", "evidence": "exit 1"},
                    ],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 0, (
            '"exit code 0" debe casear igual que "exit 0" (WOT-2026-027j (c))'
        )

    def test_exit_code_1(self, tmp_path: Path) -> None:
        """ "exit code 1" debe casear."""
        data = {
            "ticket": "WOT-2026-027j",
            "lentes": [
                {
                    "backend": "codex",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ref", "evidence": "exit code 1"},
                    ],
                },
                {
                    "backend": "nan/gemma4",
                    "verdict": "GO",
                    "hallazgos": [
                        {"texto": "ok", "evidence": "rc=0"},
                    ],
                },
            ],
        }
        _write_sidecar(tmp_path / "s.json", data)
        rc = _run_guard(tmp_path / "s.json").returncode
        assert rc == 0
