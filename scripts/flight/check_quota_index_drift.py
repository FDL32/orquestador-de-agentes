#!/usr/bin/env python3
"""WOT-2026-136m: chequeo de deriva del indice de campos de `quota` contra el roster.

El protocolo de supervision (`docs/protocol/flight_supervision.md`) lleva la tabla
"Indice de campos de quota": una fotografia de las rutas completas del bloque `quota`
del roster. Nada la comparaba con el roster vivo, asi que una clave nueva o retirada
derivaba en silencio. Este chequeo es esa comparacion; SOLO LEE: no escribe el roster,
ni el protocolo, ni el registro.

Before: el roster resuelve por `--roster-path` y, si falta, por `FLIGHT_ROSTER_PATH`; el
    protocolo, por `--protocol-path` y, si falta, el del MOTOR derivado de `__file__`
    (`docs/protocol/flight_supervision.md`, aunque el cierre corra desde un destino).
During: aplana el bloque `quota` a sus rutas completas (nodos intermedios incluidos),
    extrae las filas de la subseccion del indice y compara ambos conjuntos. Las hijas de
    `quota.account_policy.provider_map` son un nombre de cuenta y de proveedor: el
    protocolo no las escribe, y se eximen por igualdad de ruta completa, sin comodin
    (`PROVIDER_MAP_HIJAS_EXENTAS`).
After: la PRIMERA linea de stdout es el contrato y el exit code la acompana:
    `OK ...` (rc 0) solo si se compararon claves en AMBOS lados y coinciden;
    `AVISO ...` (rc 0) con las claves discrepantes y el comando para revalidar;
    `NO VERIFICABLE ...` (rc 2) con el motivo: roster ausente o ilegible, sin bloque
    `quota`, o indice vacio o no parseable. Nunca imprime OK sin haber comparado nada.
    Nunca devuelve rc 3: en los `check_*` significa "no aplica", y aqui no hay N/A.

Copia gemela de la exencion: `tests/unit/test_session_relief_handoff_fields.py`
(`EXENTAS_POR_CLAVE`, de WOT-2026-136l) conserva una tupla PROPIA con las mismas claves,
por diseno de aquel test. Si cambia la exencion, hay que cambiar las dos.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


# Fuente UNICA de la exencion en este chequeo (el test nuevo la lee de aqui por importlib).
PROVIDER_MAP_HIJAS_EXENTAS: tuple[str, ...] = (
    "quota.account_policy.provider_map.claudeAgent",
    "quota.account_policy.provider_map.claudeAgent_alvarovans",
)

ENCABEZADO_INDICE = "Indice de campos de quota"
ROSTER_ENV = "FLIGHT_ROSTER_PATH"
DEFAULT_PROTOCOL_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "protocol" / "flight_supervision.md"
)
_COMANDO = "python scripts/flight/check_quota_index_drift.py"
_ENCABEZADO_RE = re.compile(
    r"^###\s+" + re.escape(ENCABEZADO_INDICE) + r"\s*$", re.MULTILINE
)
_FILA_RE = re.compile(r"\|\s*`([^`]+)`\s*\|.*\|")


class NoVerificableError(Exception):
    """Falta algo que comparar; el mensaje es el motivo que se imprime."""


def flatten_paths(quota: dict, prefix: str = "quota") -> set[str]:
    """Rutas completas de un bloque `quota`, nodos intermedios y hojas.

    Before: `quota` es un dict; `prefix` es la ruta de ese nodo.
    During: recorre solo dicts (las listas y escalares son hojas, no se descienden).
    After: el conjunto de rutas `prefix.clave` de todos los niveles; el nodo raiz no
        cuenta como ruta.
    """
    rutas: set[str] = set()
    for clave, valor in quota.items():
        ruta = f"{prefix}.{clave}"
        rutas.add(ruta)
        if isinstance(valor, dict):
            rutas |= flatten_paths(valor, ruta)
    return rutas


def load_roster_paths(roster_path: Path) -> set[str]:
    """Before: `roster_path` apunta a un flight_roster.json. During: lo lee y aplana su
    `quota`. After: el conjunto de rutas; `NoVerificableError` si falta, es ilegible, no es
    un objeto JSON, no tiene `quota` dict o este esta vacio."""
    try:
        raw = roster_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NoVerificableError(
            f"roster ausente o ilegible: {roster_path} ({exc})"
        ) from exc
    try:
        roster = json.loads(raw)
    except ValueError as exc:
        raise NoVerificableError(
            f"roster no es JSON valido: {roster_path} ({exc})"
        ) from exc
    quota = roster.get("quota") if isinstance(roster, dict) else None
    if not isinstance(quota, dict) or not quota:
        raise NoVerificableError(f"el roster no tiene un bloque `quota`: {roster_path}")
    return flatten_paths(quota)


def parse_index_keys(texto: str) -> set[str]:
    """Before: `texto` es el protocolo. During: aisla la subseccion del indice (hasta el
    siguiente encabezado) y toma las filas `| `ruta` | donde |`; una ruta entre comillas
    invertidas en la prosa no es fila. After: el conjunto de rutas del indice;
    `NoVerificableError` si falta la subseccion, hay filas malformadas o no hay ninguna."""
    m = _ENCABEZADO_RE.search(texto)
    if m is None:
        raise NoVerificableError(
            f"el protocolo no tiene la subseccion '{ENCABEZADO_INDICE}'"
        )
    cola = texto[m.end() :]
    siguiente = re.search(r"^#", cola, re.MULTILINE)
    seccion = cola[: siguiente.start()] if siguiente else cola
    lineas = [
        ln.strip() for ln in seccion.splitlines() if ln.lstrip().startswith("| `")
    ]
    claves = {f.group(1) for ln in lineas if (f := _FILA_RE.fullmatch(ln))}
    parseadas = sum(1 for ln in lineas if _FILA_RE.fullmatch(ln))
    if parseadas != len(lineas):
        raise NoVerificableError(
            f"el indice tiene {len(lineas) - parseadas} fila(s) malformada(s)"
        )
    if not claves:
        raise NoVerificableError("el indice no tiene ninguna fila parseable")
    return claves


def compare(
    roster: set[str], indice: set[str], exentas: tuple[str, ...]
) -> tuple[list[str], list[str]]:
    """Before: ambos conjuntos son no vacios. During: las exentas salen del lado del
    roster (igualdad exacta); una exenta escrita en el indice y presente en el roster no
    cuenta como discrepancia. After: (roster sin indice, indice sin roster), ordenadas."""
    sin_indice = sorted((roster - set(exentas)) - indice)
    sin_roster = sorted(indice - roster)
    return sin_indice, sin_roster


def check(roster_path: Path | None, protocol_path: Path) -> tuple[int, list[str]]:
    """Before: `roster_path` puede ser None (sin roster resuelto). During: carga ambos
    lados y los compara. After: (rc, lineas de stdout) con la primera linea como
    contrato: OK/AVISO rc 0, NO VERIFICABLE rc 2."""
    try:
        if roster_path is None:
            raise NoVerificableError(
                f"sin roster: ni --roster-path ni {ROSTER_ENV} resuelven una ruta"
            )
        roster = load_roster_paths(roster_path)
        try:
            texto = protocol_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise NoVerificableError(
                f"protocolo ausente o ilegible: {protocol_path} ({exc})"
            ) from exc
        indice = parse_index_keys(texto)
    except NoVerificableError as exc:
        return 2, [f"NO VERIFICABLE {exc}"]
    sin_indice, sin_roster = compare(roster, indice, PROVIDER_MAP_HIJAS_EXENTAS)
    if not sin_indice and not sin_roster:
        exentas = len(roster & set(PROVIDER_MAP_HIJAS_EXENTAS))
        return 0, [
            f"OK {len(indice)} claves del indice coinciden con el roster "
            f"({len(roster)} rutas, {exentas} exentas)"
        ]
    revalidar = f"{_COMANDO} --roster-path {roster_path}"
    if protocol_path != DEFAULT_PROTOCOL_PATH:
        revalidar += f" --protocol-path {protocol_path}"
    lineas = [
        f"AVISO deriva del indice de quota: {len(sin_indice)} clave(s) del roster "
        f"ausente(s) del indice, {len(sin_roster)} clave(s) del indice ausente(s) "
        "del roster (el chequeo avisa; no corrige ni el indice ni el roster)"
    ]
    lineas += [f"  roster-sin-indice: {k}" for k in sin_indice]
    lineas += [f"  indice-sin-roster: {k}" for k in sin_roster]
    lineas.append(f"Revalidar: {revalidar}")
    return 0, lineas


def main(argv: list[str] | None = None) -> int:
    """Before: argv trae `--roster-path` y `--protocol-path` opcionales. During: resuelve
    las rutas (flag, luego FLIGHT_ROSTER_PATH) y delega en `check`; cualquier excepcion
    inesperada se convierte en NO VERIFICABLE, nunca en traceback. After: rc 0 u rc 2."""
    parser = argparse.ArgumentParser(
        description="Compara el indice de campos de quota con el roster (solo lectura)."
    )
    parser.add_argument("--roster-path", default=None, help=f"o {ROSTER_ENV}")
    parser.add_argument(
        "--protocol-path",
        default=None,
        help="solo para tests; por defecto, el protocolo del motor",
    )
    args = parser.parse_args(argv)
    roster_str = args.roster_path or os.environ.get(ROSTER_ENV, "")
    roster_path = Path(roster_str).resolve() if roster_str else None
    protocol_path = (
        Path(args.protocol_path).resolve()
        if args.protocol_path
        else DEFAULT_PROTOCOL_PATH
    )
    try:
        rc, lineas = check(roster_path, protocol_path)
    except Exception as exc:
        rc, lineas = 2, [f"NO VERIFICABLE defecto del chequeo: {exc!r}"]
    print("\n".join(lineas))
    return rc


if __name__ == "__main__":
    sys.exit(main())
