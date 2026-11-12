"""Tests del centinela manual de checklist de espera (WOT-2026-160p)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import espera_checklist_mode as mode


HOOK_DIR = Path(__file__).parent.parent.parent / ".agent" / "hooks"
sys.path.insert(0, str(HOOK_DIR))

import native_stop_hook as hook  # noqa: E402


def test_on_default_observe_escribe_json(tmp_path: Path) -> None:
    assert mode.main(["on", "--root", str(tmp_path)]) == 0
    data = json.loads((tmp_path / mode.SENTINEL_RELPATH).read_text(encoding="utf-8"))
    assert data["mode"] == "observe"
    datetime.fromisoformat(data["activated_at"])


def test_on_block_escribe_modo_block(tmp_path: Path) -> None:
    assert mode.main(["on", "--mode", "block", "--root", str(tmp_path)]) == 0
    data = json.loads((tmp_path / mode.SENTINEL_RELPATH).read_text(encoding="utf-8"))
    assert data["mode"] == "block"


def test_off_es_idempotente(tmp_path: Path, capsys) -> None:
    """Before: la raiz no tiene estado de espera.

    During: off escribe un estado durable y el segundo apagado es idempotente.
    After: on rearma observe y el centinela sigue siendo legible.
    MUTACION: reintroducir unlink, cambiar la salida del primer off, escribir una
    fecha naive o exigir activated_at en el guard idempotente cae.
    """
    assert mode.main(["off", "--root", str(tmp_path)]) == 0
    first = capsys.readouterr().out
    target = tmp_path / mode.SENTINEL_RELPATH
    assert first.startswith("espera_checklist_mode OFF (mode=off, ")
    assert str(target) in first
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["mode"] == "off"
    activated = datetime.fromisoformat(data["activated_at"])
    assert activated.tzinfo is not None
    assert activated.utcoffset() == timedelta(0)
    first_bytes = target.read_bytes()
    assert mode.main(["off", "--root", str(tmp_path)]) == 0
    assert "ya estaba OFF" in capsys.readouterr().out
    assert target.read_bytes() == first_bytes
    assert mode.main(["on", "--root", str(tmp_path)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["mode"] == "observe"
    capsys.readouterr()

    manual_root = tmp_path / "manual_sin_fecha"
    manual = manual_root / mode.SENTINEL_RELPATH
    manual.parent.mkdir(parents=True, exist_ok=True)
    manual.write_bytes(b'{"mode":"off"}')
    manual_bytes = manual.read_bytes()
    assert mode.main(["off", "--root", str(manual_root)]) == 0
    assert "ya estaba OFF" in capsys.readouterr().out
    assert manual.read_bytes() == manual_bytes


def test_status_off_legible_e_ilegible(tmp_path: Path, capsys) -> None:
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    assert "espera_checklist_mode: OFF" in capsys.readouterr().out
    assert mode.main(["on", "--mode", "block", "--root", str(tmp_path)]) == 0
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    assert "ON (mode=block" in capsys.readouterr().out
    (tmp_path / mode.SENTINEL_RELPATH).write_text("{roto", encoding="utf-8")
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    assert "ON pero ILEGIBLE" in capsys.readouterr().out


def test_cli_real_status(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(Path(mode.__file__)), "status", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "espera_checklist_mode: OFF"


def test_status_json_valido_no_dict_es_ilegible(tmp_path: Path, capsys) -> None:
    """JSON valido pero no-objeto (ronda 3 de lentes): tambien es ILEGIBLE,
    no solo el JSON roto que ya cubria test_status_off_legible_e_ilegible."""
    target = tmp_path / mode.SENTINEL_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("[1, 2, 3]", encoding="utf-8")
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    assert "ON pero ILEGIBLE" in capsys.readouterr().out


def test_status_centinela_vacio_es_inactivo(tmp_path: Path, capsys) -> None:
    """z-02: un `{}` no puede reportarse como ON a secas; es INACTIVO."""
    target = tmp_path / mode.SENTINEL_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "INACTIVO" in out
    assert "SIN-FECHA-LEGIBLE" in out
    assert "mode=?" not in out


def test_status_centinela_caducado_es_inactivo(tmp_path: Path, capsys) -> None:
    """z-01 lado status: la etiqueta EXPIRADO debe llegar al operador."""
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    target = tmp_path / mode.SENTINEL_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"mode": "observe", "activated_at": old}), encoding="utf-8"
    )
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "INACTIVO" in out
    assert "EXPIRADO" in out


def test_status_centinela_fresco_sigue_activo(tmp_path: Path, capsys) -> None:
    """CONTROL POSITIVO de z-01/z-02 lado status: fresco -> ON normal."""
    assert mode.main(["on", "--root", str(tmp_path)]) == 0
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "ON (mode=observe" in out
    assert "INACTIVO" not in out


def test_ruta_centinela_una_sola_fuente() -> None:
    """z-07: una sola definicion del literal, compartida con el gancho.

    CONTROL POSITIVO: si el script reintrodujera su propio literal (constante
    divergente), el censo combinado pasaria de 1 a 2 y este test se pone rojo.
    """
    assert mode.SENTINEL_RELPATH == hook.ESPERA_SENTINEL_RELPATH
    assert mode.SENTINEL_RELPATH is hook.ESPERA_SENTINEL_RELPATH
    combined = "".join(
        Path(path).read_text(encoding="utf-8")
        for path in (mode.__file__, hook.__file__)
    )
    assert combined.count("espera_checklist_mode.json") == 1


def test_turn_on_ante_oserror_devuelve_rc1(tmp_path: Path, monkeypatch, capsys) -> None:
    """Si escribir el centinela falla (OSError), turn_on no debe fingir
    exito: rc 1 y diagnostico en stderr."""

    def _boom(self, *args, **kwargs):
        raise OSError("disco lleno (simulado)")

    monkeypatch.setattr(Path, "write_text", _boom)
    assert mode.main(["on", "--root", str(tmp_path)]) == 1
    assert "no se pudo encender" in capsys.readouterr().err


def test_status_off_mode_is_coherent_not_on(tmp_path: Path, capsys) -> None:
    """Before: el centinela declara off, incluso con fecha antigua.

    During: status evalua off antes de la caducidad. After: imprime OFF sin ON.
    MUTACION: quitar la rama off devuelve ON pero INACTIVO y cae.
    """
    target = tmp_path / mode.SENTINEL_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"mode": "off"}), encoding="utf-8")
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("espera_checklist_mode: OFF")
    assert "ON" not in out

    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    target.write_text(
        json.dumps({"mode": "off", "activated_at": old}), encoding="utf-8"
    )
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("espera_checklist_mode: OFF")
    assert "ON" not in out

    assert mode.main(["on", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert mode.main(["status", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "ON (mode=observe" in out
    assert "INACTIVO" not in out


def test_off_sobrescribe_ilegible_y_otros_modos(tmp_path: Path, capsys) -> None:
    """Before: cada subdirectorio contiene un estado invalido o activo.

    During: off reemplaza todos los estados que no sean off legible.
    After: cada centinela existe y contiene off con fecha parseable.
    MUTACION: conservar observe, block, JSON roto, no-dict, vacio o {} cae.
    """
    when = datetime.now(timezone.utc)
    casos = {
        "observe_fresco": {"mode": "observe", "activated_at": when.isoformat()},
        "observe_caducado": {
            "mode": "observe",
            "activated_at": (when - timedelta(days=3)).isoformat(),
        },
        "block": {"mode": "block", "activated_at": when.isoformat()},
        "roto": "{roto",
        "no_dict": "[1,2,3]",
        "vacio": "",
        "sin_modo": "{}",
    }
    for nombre, previo in casos.items():
        root = tmp_path / nombre
        target = root / mode.SENTINEL_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            previo if isinstance(previo, str) else json.dumps(previo),
            encoding="utf-8",
        )
        assert mode.main(["off", "--root", str(root)]) == 0
        capsys.readouterr()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert data["mode"] == "off"
        datetime.fromisoformat(data["activated_at"])


def test_off_ante_oserror_devuelve_rc1(tmp_path: Path, monkeypatch, capsys) -> None:
    """Before: el filesystem simula un fallo al escribir.

    During: off intenta persistir el estado durable.
    After: devuelve rc 1 y explica el fallo en stderr.
    MUTACION: ocultar el OSError o devolver rc 0 deja el test en rojo.
    """

    def _boom(self, *args, **kwargs):
        raise OSError("disco lleno (simulado)")

    monkeypatch.setattr(Path, "write_text", _boom)
    assert mode.main(["off", "--root", str(tmp_path)]) == 1
    assert "no se pudo apagar" in capsys.readouterr().err


def test_off_durable_con_motivo(tmp_path: Path, capsys) -> None:
    """Before: el centinela puede registrar una razon de apagado.

    During: off conserva el motivo solo cuando se proporciona --reason.
    After: on y status ignoran --reason y mantienen su contrato.
    MUTACION: eliminar, inventar o consumir reason en on/status cae.
    """
    target = tmp_path / mode.SENTINEL_RELPATH
    assert (
        mode.main(["off", "--reason", "rotacion planificada", "--root", str(tmp_path)])
        == 0
    )
    capsys.readouterr()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["mode"] == "off"
    assert data["reason"] == "rotacion planificada"
    datetime.fromisoformat(data["activated_at"])

    assert mode.main(["on", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert mode.main(["off", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "reason" not in data

    assert mode.main(["on", "--reason", "x", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["mode"] == "observe"
    assert "reason" not in data
    assert mode.main(["status", "--reason", "x", "--root", str(tmp_path)]) == 0


def test_on_rearma_tras_off(tmp_path: Path, capsys) -> None:
    """Before: off deja un centinela durable.

    During: on vuelve a escribir observe y despues block de forma explicita.
    After: ambos modos solicitados quedan persistidos.
    MUTACION: hacer turn_on exclusivo y no sobrescribir off cae.
    """
    target = tmp_path / mode.SENTINEL_RELPATH
    assert mode.main(["off", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert mode.main(["on", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert json.loads(target.read_text(encoding="utf-8"))["mode"] == "observe"
    assert mode.main(["off", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert mode.main(["on", "--mode", "block", "--root", str(tmp_path)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["mode"] == "block"
