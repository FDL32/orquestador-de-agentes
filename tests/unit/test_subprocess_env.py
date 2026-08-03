"""WOT-2026-048d: los backends externos no heredan las credenciales del motor.

Medido el 2026-08-03 en el entorno real del orquestador: 4 credenciales
(`GITHUB_PERSONAL_ACCESS_TOKEN`, `GITHUB_TOKEN`, `NAN_API_KEY`,
`POSTHOG_API_KEY`) viajaban a cada lente, porque `opencode_transport` partia de
`os.environ.copy()` y `_transport_agent` llamaba a `Popen` sin `env=`.

Los tests van sobre el ARGV/ENV construido, NO sobre la respuesta del backend:
aseverar sobre stdout mediria el backend, no el saneado.
"""

from __future__ import annotations

import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bus.subprocess_env import build_backend_env  # noqa: E402


def test_credentials_do_not_survive_the_allowlist():
    """Las 4 credenciales MEDIDAS en el entorno real no pasan el filtro.

    Mutation: convertir la allowlist en denylist (o devolver `dict(source)`)
    pone este test en ROJO.
    """
    source = {
        "PATH": "/usr/bin",
        "SYSTEMROOT": r"C:\Windows",
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_secreto",
        "GITHUB_TOKEN": "ghs_secreto",
        "NAN_API_KEY": "sk-secreto",
        "POSTHOG_API_KEY": "phc_secreto",
    }

    env = build_backend_env(source)

    for leaked in (
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "GITHUB_TOKEN",
        "NAN_API_KEY",
        "POSTHOG_API_KEY",
    ):
        assert leaked not in env, f"{leaked} viajo al subproceso"
    assert "secreto" not in "".join(env.values()), "un valor secreto sobrevivio"
    # Control POSITIVO: el filtro no vacia el entorno, deja lo necesario.
    assert env["PATH"] == "/usr/bin"
    assert env["SYSTEMROOT"] == r"C:\Windows"


def test_allowlist_blocks_the_variable_nobody_predicted():
    """Una credencial con nombre IMPREVISTO tampoco pasa.

    Es la diferencia con una denylist: un filtro por subcadenas
    (KEY/TOKEN/SECRET) dejaria pasar `ACME_CUSTOMER_PAT` o `DB_DSN`, que no
    contienen ninguna de esas palabras. La allowlist no necesita preverlas.
    """
    source = {
        "PATH": "/usr/bin",
        "ACME_CUSTOMER_PAT": "pat_imprevisto",
        "DB_DSN": "postgres://user:pass@host/db",
    }

    env = build_backend_env(source)

    assert "ACME_CUSTOMER_PAT" not in env
    assert "DB_DSN" not in env
    assert env == {"PATH": "/usr/bin"}


def test_home_and_encoding_survive_because_the_backends_need_them():
    """Probe funcional del 2026-08-03: la auth de los CLI vive en el HOME.

    Por eso NO hace falta pasar ninguna API key por entorno, y por eso HOME y
    sus equivalentes SI tienen que sobrevivir. Si este test cae, el saneado
    rompe la autenticacion de opencode/codex.
    """
    source = {
        "HOME": "/home/u",
        "USERPROFILE": r"C:\Users\u",
        "APPDATA": r"C:\Users\u\AppData\Roaming",
        "LOCALAPPDATA": r"C:\Users\u\AppData\Local",
        "XDG_DATA_HOME": "/home/u/.local/share",
        "PYTHONIOENCODING": "utf-8",
    }

    env = build_backend_env(source)

    assert env == source, "el saneado tumbo una variable que el backend necesita"


def test_overrides_are_not_filtered_but_extra_allow_is_explicit():
    """`overrides` es para valores FABRICADOS por el llamante, no para reenviar.

    Un HOME scratch no esta en `source` y debe poder inyectarse. En cambio, para
    reenviar una variable del proceso padre hay que DECLARARLA en `extra_allow`:
    asi cada ampliacion queda escrita en el call-site y es auditable.
    """
    source = {"PATH": "/usr/bin", "CODEX_EXECUTABLE": "/opt/codex"}

    sin_declarar = build_backend_env(source)
    assert "CODEX_EXECUTABLE" not in sin_declarar

    declarada = build_backend_env(source, extra_allow={"CODEX_EXECUTABLE"})
    assert declarada["CODEX_EXECUTABLE"] == "/opt/codex"

    fabricada = build_backend_env(source, overrides={"HOME": "/tmp/scratch"})
    assert fabricada["HOME"] == "/tmp/scratch"


def test_source_is_never_mutated():
    """El saneado no puede tener efectos laterales sobre el entorno real."""
    source = {"PATH": "/usr/bin", "NAN_API_KEY": "sk-secreto"}
    before = dict(source)

    build_backend_env(source, overrides={"HOME": "/tmp/x"})

    assert source == before, "build_backend_env muto su fuente"


def test_systemdrive_survives_or_windows_writes_the_literal():
    """`SYSTEMDRIVE` no es cosmetica: sin ella Windows escribe la cadena cruda.

    Medido 2026-08-03: un probe con entorno minimo SIN esta variable dejo un
    directorio literal `%SystemDrive%/ProgramData/...` en el cwd del motor, con
    4 caches de Windows dentro. No dio error -- solo basura en el arbol, que es
    peor porque pasa inadvertida y la caza una sesion hermana en su cierre.

    Mutation: sacar "SYSTEMDRIVE" de la allowlist pone este test en ROJO.
    """
    source = {"PATH": "/usr/bin", "SYSTEMDRIVE": "C:"}

    env = build_backend_env(source)

    assert env.get("SYSTEMDRIVE") == "C:", (
        "sin SYSTEMDRIVE, un subproceso en Windows escribe '%SystemDrive%' "
        "literal como directorio en el cwd"
    )
