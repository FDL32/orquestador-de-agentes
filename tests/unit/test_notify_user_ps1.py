"""Pruebas de scripts/flight/notify_user.ps1 (WOT-2026-153i, caja 1C, filas 75-77 del Anexo B).

Before: Windows con ``powershell.exe`` en su ruta absoluta; el ps1 vive junto a ``comms_alert.py``
    (o junto a la copia que apunta ``COMMS_ALERT_UNDER_TEST``, usada por el arnes de mutacion).
During: ejecuta el ps1 REAL sin ``-ExecutionPolicy Bypass`` y SIEMPRE con ``-NoFlash``: la prueba nunca
    parpadea ventanas ni pita. Tampoco hay prueba del toast correcto: mostraria un aviso real en la
    pantalla de quien corre la suite (limite declarado: el toast visible, el parpadeo real y el pitido
    quedan como prueba humana; aqui solo se comprueba la FORMA del codigo que los guarda).
After: asevera rc y salida del camino de fallo simulado, que ``-NoFlash`` no omite el toast y que el
    fichero no conserva ``-Banner`` ni ``NOTIFY_*``.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="notify_user.ps1 es solo Windows (D11)"
)

REPO = Path(__file__).resolve().parents[2]
PS1 = (
    Path(
        os.environ.get("COMMS_ALERT_UNDER_TEST")
        or REPO / "scripts" / "flight" / "comms_alert.py"
    )
    .resolve()
    .with_name("notify_user.ps1")
)
POWERSHELL = (
    Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)


def _cmd(*args):
    """Orden de la prueba A: PowerShell absoluto, sin perfil, SIN ExecutionPolicy Bypass (D26)."""
    return [
        str(POWERSHELL),
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(PS1),
        *args,
    ]


def _run(*args):
    return subprocess.run(
        _cmd(*args), capture_output=True, text=True, timeout=60, check=False
    )


def _src():
    return PS1.read_text(encoding="utf-8")


def test_fila75_toast_simulado_falla_sale_con_exit_3_y_lo_dice():
    """fila 75: -SimulateToastFailure suprime el toast, lo declara FALLO y sale con exit 3."""
    r = _run(
        "-Title",
        "prueba 153i",
        "-Message",
        "no es real",
        "-SimulateToastFailure",
        "-NoFlash",
    )
    assert r.returncode == 3
    assert "toast=FALLO(" in r.stdout
    assert "toast=ok" not in r.stdout


def test_fila75b_la_prueba_a_no_copia_el_bypass_de_la_politica():
    """D26: la orden de la prueba A no lleva ExecutionPolicy ni Bypass (el ps1 local corre con RemoteSigned)."""
    cmd = " ".join(_cmd("-Title", "t", "-Message", "m"))
    assert "Bypass" not in cmd
    assert "ExecutionPolicy" not in cmd


def test_fila76_noflash_omite_parpadeo_y_pitido_pero_no_el_toast():
    """fila 76: con -NoFlash no hay flash_ventanas ni flash=FALLO y el toast SI se intenta (rc 3 con fallo simulado)."""
    r = _run(
        "-Title",
        "prueba 153i",
        "-Message",
        "no es real",
        "-SimulateToastFailure",
        "-NoFlash",
    )
    assert "flash_ventanas=" not in r.stdout
    assert "flash=FALLO" not in r.stdout
    assert r.stdout.startswith("toast="), r.stdout
    assert r.returncode == 3


def test_fila76b_el_pitido_cuelga_de_noflash():
    """fila 76b: el pitido no suena en un test (no deja rastro en la salida), asi que se asevera la FORMA del guard."""
    assert re.search(
        r"^if \(-not \$NoFlash\) \{ \[console\]::beep\(880,250\); \[console\]::beep\(660,250\) \}$",
        _src(),
        re.MULTILINE,
    )


def test_fila77_sin_banner_ni_variables_notify_y_con_los_parametros_exactos():
    """fila 77 (censo del ps1): ni -Banner, ni banner.ps1, ni NOTIFY_*, ni Bypass; param exacto (D26)."""
    src = _src()
    for prohibido in ("Banner", "banner", "NOTIFY_", "Bypass", "ExecutionPolicy"):
        assert prohibido not in src, prohibido
    cabecera = src.splitlines()[0]
    assert cabecera.startswith("param(")
    nombres = re.findall(r"\]\$([A-Za-z]+)", cabecera)
    assert nombres == ["Title", "Message", "SimulateToastFailure", "NoFlash"]
    # sin Zone.Identifier (flujo alterno NTFS de un fichero descargado): el censo de D26
    with pytest.raises(OSError):
        open(f"{PS1}:Zone.Identifier", "rb").close()


def test_fila77b_ningun_script_prompt_o_skill_versionado_pasa_simulate_toast_failure():
    """D26: el parametro solo existe para pruebas; un llamador que lo pasara dejaria al usuario SIN aviso."""
    ofensores = []
    for carpeta in ("scripts", "prompts", "skills"):
        for p in (REPO / carpeta).rglob("*"):
            if (
                not p.is_file()
                or "__pycache__" in p.parts
                or p.name == "notify_user.ps1"
            ):
                continue
            if p.suffix not in {
                ".py",
                ".ps1",
                ".md",
                ".xml",
                ".json",
                ".yaml",
                ".yml",
                ".toml",
                ".txt",
            }:
                continue
            if "SimulateToastFailure" in p.read_text(
                encoding="utf-8", errors="replace"
            ):
                ofensores.append(p.relative_to(REPO).as_posix())
    assert ofensores == []
