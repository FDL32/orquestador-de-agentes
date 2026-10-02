"""Tests de `scripts/sandbox_launcher.ps1` (lanzador de agentes en AppContainer, sin admin).

Dos niveles:
  - ESTATICOS (siempre): portabilidad del fichero (ASCII, sin rutas de usuario) y sintaxis PowerShell valida.
  - INTEGRACION (solo con `RUN_SANDBOX_INTEGRATION=1`, en Windows): arrancan el contenedor DE VERDAD. Crean un perfil
    AppContainer en HKCU y ACE bajo una raiz temporal, y lo deshacen al terminar. Estan apagados por defecto porque
    mutan el sistema del usuario; el comportamiento que prueban (barrera, canario fail-closed, entorno limpio) es el
    que importa, asi que NO se sustituyen por greps del texto del script.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sandbox_launcher.ps1"
IS_WIN = sys.platform == "win32"
INTEGRATION = IS_WIN and os.environ.get("RUN_SANDBOX_INTEGRATION") == "1"


def _ps(
    *args: str, env: dict | None = None, timeout: int = 300
) -> subprocess.CompletedProcess:
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        *args,
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=env, check=False
    )


# --------------------------------------------------------------------------- estaticos
def test_script_es_ascii_y_sin_rutas_de_usuario():
    """Portabilidad: el motor se distribuye; nada de acentos (encoding guard) ni `C:\\Users\\<alguien>`."""
    raw = SCRIPT.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM: el guard de encoding lo rechaza"
    assert all(b < 128 for b in raw), "caracteres no ASCII en el script"
    text = raw.decode("ascii")
    assert not re.search(r"[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+", text), (
        "ruta de usuario fija en el script"
    )


@pytest.mark.skipif(not IS_WIN, reason="el parser de PowerShell 5.1 es de Windows")
def test_script_parsea_sin_errores_de_sintaxis():
    code = (
        "$e=$null;$t=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}',[ref]$t,[ref]$e)|Out-Null;"
        "if($e){$e|%{$_.Message};exit 1}"
    )
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr


# --------------------------------------------------------------------------- integracion
@pytest.fixture
def sbx(tmp_path):
    name = f"sbx_test_{uuid.uuid4().hex[:8]}"
    root = tmp_path / "root"
    base = ["-Root", str(root), "-ContainerName", name, "-Tools", "git"]

    def run(*extra: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return _ps(*extra, *base, env=env)

    try:
        yield run, root, name
    finally:
        run("down")


pytestmark_int = pytest.mark.skipif(
    not INTEGRATION,
    reason="define RUN_SANDBOX_INTEGRATION=1 (crea un perfil AppContainer real)",
)
CMD = r"C:\Windows\System32\cmd.exe"


@pytestmark_int
def test_up_run_dentro_si_fuera_no_y_down_limpia(sbx):
    run, root, _ = sbx
    up = run("up")
    assert up.returncode == 0, up.stdout + up.stderr

    # DENTRO se puede escribir; el canario ya paso (si no, run habria abortado)
    ok = run("run", "-Exe", CMD, "-ExeArgs", "/c echo dentro> hecho.txt", "-NullStdin")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert (root / "work" / "hecho.txt").exists()

    # FUERA no se puede escribir (y el fichero no aparece)
    fuera = run(
        "run",
        "-Exe",
        CMD,
        "-ExeArgs",
        f'/c echo intruso> "{root}\\outside\\hack.txt"',
        "-NullStdin",
    )
    assert fuera.returncode != 0
    assert not (root / "outside" / "hack.txt").exists()

    # down: perfil fuera y sin ACE del contenedor
    run("down")
    st = run("status")
    assert "perfil AppContainer: no existe" in st.stdout
    assert ": True" not in st.stdout, "quedan ACE del contenedor tras down"


@pytestmark_int
def test_entorno_limpio_y_control_positivo_de_passenv(sbx):
    run, _, _ = sbx
    env = {**os.environ, "SBXTEST_SECRET_KEY": "valor-secreto-123"}
    sin = run("run", "-Exe", CMD, "-ExeArgs", "/c set", "-NullStdin", env=env)
    assert sin.returncode == 0, sin.stdout + sin.stderr
    assert "SBXTEST_SECRET_KEY" not in sin.stdout, (
        "un secreto del entorno llego al hijo"
    )
    # stdout del lanzador = SOLO el del hijo (un agente ACP lee ese flujo); sus mensajes van a stderr
    assert "[sandbox]" not in sin.stdout
    assert "[sandbox]" in sin.stderr
    # control positivo: solo con -PassEnv explicito aparece (si no, el test anterior no probaria nada)
    con = run(
        "run",
        "-Exe",
        CMD,
        "-ExeArgs",
        "/c set",
        "-NullStdin",
        "-PassEnv",
        "SBXTEST_SECRET_KEY",
        env=env,
    )
    assert "SBXTEST_SECRET_KEY" in con.stdout


@pytestmark_int
def test_canario_aborta_si_la_barrera_esta_rota(sbx):
    run, root, _ = sbx
    assert run("up").returncode == 0
    assert run("verify").returncode == 0, "con la barrera sana verify debe dar 0"
    sid = run("sid").stdout.strip()
    assert sid.startswith("S-1-15-2-"), sid
    outside = root / "outside"
    grant = (
        f"$a=Get-Acl '{outside}';$s=New-Object System.Security.Principal.SecurityIdentifier('{sid}');"
        "$a.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule("
        "$s,'ReadAndExecute','ContainerInherit,ObjectInherit','None','Allow')));"
        f"Set-Acl '{outside}' $a"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", grant], check=True, timeout=60
    )
    rota = run(
        "run", "-Exe", CMD, "-ExeArgs", "/c echo no-debe-ejecutarse", "-NullStdin"
    )
    assert rota.returncode != 0, (
        "con la barrera rota el lanzador debe negarse a arrancar"
    )
    assert "no-debe-ejecutarse" not in rota.stdout
    assert "CANARIO" in (rota.stdout + rota.stderr)
    # el punto de entrada para IDE/CI tambien da rc != 0 con la barrera rota
    assert run("verify").returncode != 0
