#!/usr/bin/env python3
"""Entorno MINIMO por ALLOWLIST para los subprocesos de backend (lentes).

WOT-2026-048d. Hasta este modulo, todo backend lanzado por el motor heredaba el
entorno COMPLETO del orquestador: `bus/opencode_transport.py` partia de
`os.environ.copy()` y `scripts/ensemble_dispatch.py::_transport_agent` invocaba
`subprocess.Popen` SIN `env=`, que hereda por defecto. Medido el 2026-08-03 en
el entorno real del orquestador: 4 credenciales viajaban a cada lente
(`GITHUB_PERSONAL_ACCESS_TOKEN`, `GITHUB_TOKEN`, `NAN_API_KEY`,
`POSTHOG_API_KEY`).

POR QUE ALLOWLIST Y NO DENYLIST. Una denylist (`del env["NAN_API_KEY"]`, o un
filtro por subcadenas como KEY/TOKEN/SECRET) es ENUMERATIVA: falla en silencio
con la variable que no se previo, y el fallo es invisible -- el subproceso
arranca igual. La allowlist invierte la asimetria: lo que no esta declarado no
viaja, y si falta algo el backend falla de forma RUIDOSA (no arranca), que es un
modo de fallo detectable. Es la misma regla que este repo aplica al vocabulario
cerrado del backlog.

POR QUE ESTO NO LO ARREGLA UN CONTENEDOR. La fuga entra por el ENTORNO, no por
el filesystem: un sandbox que no monte nada del host seguiria recibiendo las
variables si el proceso padre se las pasa. Por eso este saneado es previo e
independiente de WOT-2026-030a, y lo sigue siendo despues.

ALCANCE DECLARADO. Cierra el canal de HERENCIA. NO cierra la exfiltracion por el
canal API legitimo de la lente -- eso esta fuera del alcance de cualquier
sandbox y lo gobierna el filtro por contenido (WOT-2026-027s).

Before: el llamante tiene un entorno de proceso (por defecto `os.environ`).
During: filtra por allowlist, sin I/O ni efectos laterales.
After: devuelve un dict NUEVO; nunca muta el entorno del proceso llamante.
"""

from __future__ import annotations

import os
from collections.abc import Mapping


#: Variables que un backend CLI necesita para ARRANCAR en Windows y POSIX.
#: Verificado con probe funcional (2026-08-03): con solo estas, `opencode run
#: --model ...` y `codex exec` responden correctamente -- su autenticacion vive
#: en el HOME (`~/.local/share/opencode`, `~/.codex`), NO en variables.
#: Si se anade una variable aqui, hay que justificar por que un backend NO
#: arranca sin ella: cada entrada amplia lo que viaja a un proceso externo.
_BASE_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Resolucion de ejecutables e interprete de comandos
        "PATH",
        "PATHEXT",
        "COMSPEC",
        "SHELL",
        # Windows: sin SYSTEMROOT/WINDIR muchos binarios no arrancan.
        # SYSTEMDRIVE no es opcional aunque lo parezca: medido 2026-08-03, un
        # probe sin ella dejo un directorio literal `%SystemDrive%/` en el cwd
        # -- Windows no expandio la variable y escribio la cadena cruda. El
        # sintoma es basura en el arbol, no un error, asi que pasa inadvertido.
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "WINDIR",
        "OS",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        # Temporales
        "TEMP",
        "TMP",
        "TMPDIR",
        # HOME y sus equivalentes: es DONDE vive la auth de los CLI, y por eso
        # NO hace falta pasar ninguna API key por entorno.
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
        # Encoding: sin esto la consola cp1252 revienta con no-ASCII
        "PYTHONIOENCODING",
        "LANG",
        "LC_ALL",
    }
)


def build_backend_env(
    source: Mapping[str, str] | None = None,
    *,
    extra_allow: frozenset[str] | set[str] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Entorno saneado para lanzar un backend externo.

    Before: `source` es el entorno de origen (por defecto `os.environ`).
        `extra_allow` son nombres ADICIONALES que este llamante concreto
        justifica necesitar. `overrides` se aplica al final y NO pasa por la
        allowlist -- es para valores que el llamante FABRICA (p.ej. un HOME
        scratch), no para reenviar secretos del proceso padre.
    During: filtra `source` por allowlist (comparacion en mayusculas para
        tolerar la insensibilidad de Windows), sin tocar el entorno real.
    After: devuelve un dict NUEVO. Ninguna variable ausente de la allowlist
        sobrevive, incluidas las credenciales del orquestador.
    """
    env_source = os.environ if source is None else source
    allowed = _BASE_ALLOWLIST | frozenset(
        name.upper() for name in (extra_allow or frozenset())
    )
    result = {k: v for k, v in env_source.items() if k.upper() in allowed}
    if overrides:
        result.update(overrides)
    return result
