#!/usr/bin/env python
"""Guard: una decision de proceso DECLARADA en un artefacto debe declarar su
busqueda previa de protocolo (AGENTS.md, WOT-2026-104b).

Que protege
-----------
AGENTS.md seccion "Decision de proceso sin instruccion exacta => BUSCA
protocolo documentado antes de suponer uno (2026-10-14)" exige que, antes de
resolver una decision de proceso por razonamiento propio, el agente
compruebe primero si existe un protocolo ya escrito, y que declare
explicitamente cuando no encuentra nada. Esa seccion se autodeclaraba
"NORMA, no barrera" -- nadie la invocaba sola. Este guard la cablea para la
superficie donde se puede verificar mecanicamente sin inventar deteccion de
intencion: un artefacto que SE AUTODECLARA como decision de proceso.

Por que un marcador explicito y no deteccion de intencion
-----------------------------------------------------------
No existe oraculo que decida si un parrafo de prosa "es" una decision de
proceso sin leerlo con juicio humano (lo dice la propia norma: "fuera del
alcance de esta nota"). Este guard NO lo intenta. En vez de eso, igual que
`check_loop_bundle_protocol.py` exige CANAL:/ROL DE LA LENTE: como
propiedades AUTODECLARADAS del bundle, este guard activa su invariante
companero solo cuando el propio documento se etiqueta con el marcador
DECISION DE PROCESO: -- una propiedad detectable, no inferida.

Los dos invariantes
--------------------
1. Marcador de decision de proceso (DECISION DE PROCESO:), anclado a
   principio de linea (con o sin viñeta/encabezado markdown) para no
   disparar sobre una mencion inline entre comillas/backticks dentro de
   prosa que simplemente CITA el nombre del marcador (p.ej. esta misma
   documentacion). Limitacion declarada: una mencion inline que empiece la
   linea igual puede falsear-positivo; no se resuelve aqui (ver ALCANCE).
2. Si (1) esta presente fuera de un bloque de codigo con triple backtick,
   el documento DEBE declarar BUSQUEDA-PREVIA: (mismo anclaje) con AL MENOS
   una de tres formas validas:
     - PROTOCOLO ENCONTRADO: <ruta no vacia>
     - NO ENCONTRE PROTOCOLO
     - EXCEPCION: trivial <justificacion no vacia>

ALCANCE DECLARADO (lo que este guard NO hace)
----------------------------------------------
Verifica que las dos propiedades esten DECLARADAS, no que sean CIERTAS.
"NO ENCONTRE PROTOCOLO" sin haber buscado de verdad, o "PROTOCOLO
ENCONTRADO: <ruta inventada>", pasan el guard: es una barrera de FORMA, no
de semantica -- mismo limite declarado que su molde
`check_loop_bundle_protocol.py`. Tampoco detecta una decision de proceso
que el autor no etiqueto con el marcador: ese es el modo de fallo n=3 que
la norma original documenta, y sigue sin barrera mecanica (deuda abierta,
ver AGENTS.md). No sustituye a `check_contract_full_read.py` (dominio
distinto: aquel verifica LECTURA COMPLETA de un contrato YA CITADO; este
verifica BUSQUEDA PREVIA antes de decidir SIN contrato citado).

Before / During / After
-----------------------
Before: recibe la ruta de un artefacto de texto legible en UTF-8.
During: elimina bloques de codigo de triple backtick; busca el marcador (1)
    anclado a inicio de linea; si esta presente, busca BUSQUEDA-PREVIA: y
    clasifica su forma. Sin red, sin subprocess, sin escritura.
After: exit 0 si no hay marcador (1), o si hay marcador (1) y una forma
    valida de BUSQUEDA-PREVIA; exit 1 nombrando el defecto exacto.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

_DECISION_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?:#{1,6}[ \t]*|[-*][ \t]*)?DECISION DE PROCESO\s*:",
    re.IGNORECASE,
)

_BUSQUEDA_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?:#{1,6}[ \t]*|[-*][ \t]*)?BUSQUEDA-PREVIA\s*:",
    re.IGNORECASE,
)

_PROTOCOLO_ENCONTRADO_LABEL_RE = re.compile(r"(?i)PROTOCOLO ENCONTRADO\s*:")

_PROTOCOLO_ENCONTRADO_RE = re.compile(r"(?im)PROTOCOLO ENCONTRADO\s*:[ \t]*(\S.*)$")

_NO_ENCONTRE_RE = re.compile(r"(?i)NO ENCONTRE PROTOCOLO")

_EXCEPCION_TRIVIAL_RE = re.compile(
    r"(?im)EXCEPCION\s*:\s*trivial\b[ \t]*[-:]?[ \t]*(\S.*)?$"
)


def _strip_fences(text: str) -> str:
    """Elimina bloques ```...``` para no disparar sobre ejemplos/documentacion."""
    return _FENCE_RE.sub("", text)


def has_decision_marker(text: str) -> bool:
    return bool(_DECISION_MARKER_RE.search(_strip_fences(text)))


def busqueda_previa_defect(text: str) -> str | None:
    """Devuelve el defecto (str) si BUSQUEDA-PREVIA: no cumple, o None si OK."""
    scrubbed = _strip_fences(text)
    if not _BUSQUEDA_MARKER_RE.search(scrubbed):
        return (
            "falta la seccion 'BUSQUEDA-PREVIA:' (exige una de: "
            "'PROTOCOLO ENCONTRADO: <ruta>', 'NO ENCONTRE PROTOCOLO', "
            "'EXCEPCION: trivial <justificacion>')"
        )
    m = _PROTOCOLO_ENCONTRADO_RE.search(scrubbed)
    if m and m.group(1).strip():
        return None
    if _NO_ENCONTRE_RE.search(scrubbed):
        return None
    m = _EXCEPCION_TRIVIAL_RE.search(scrubbed)
    if m and (m.group(1) or "").strip():
        return None
    if m:
        return (
            "'EXCEPCION: trivial' declarada sin texto de justificacion "
            "(una etiqueta vacia no basta)"
        )
    if _PROTOCOLO_ENCONTRADO_LABEL_RE.search(scrubbed):
        return "'PROTOCOLO ENCONTRADO:' declarado sin ruta (texto vacio tras los dos puntos)"
    return (
        "'BUSQUEDA-PREVIA:' presente pero ninguna de las 3 formas validas "
        "('PROTOCOLO ENCONTRADO: <ruta>' / 'NO ENCONTRE PROTOCOLO' / "
        "'EXCEPCION: trivial <justificacion>') esta declarada"
    )


def check_artifact(text: str) -> str | None:
    """None si OK/no-aplica; str con el defecto exacto si bloquea."""
    if not has_decision_marker(text):
        return None
    return busqueda_previa_defect(text)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Verifica que un artefacto que se autodeclara DECISION DE "
            "PROCESO: declare su BUSQUEDA-PREVIA: de protocolo (AGENTS.md, "
            "WOT-2026-104b)."
        )
    )
    ap.add_argument(
        "artefactos", nargs="+", help="ruta(s) del fichero a verificar (una o varias)"
    )
    args = ap.parse_args()

    worst = 0
    for raw in args.artefactos:
        path = Path(raw)
        if not path.is_file():
            print(
                f"[process-decision-search] ERROR: no encontrado: {path}",
                file=sys.stderr,
            )
            worst = max(worst, 2)
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        defect = check_artifact(text)
        if defect is None:
            if has_decision_marker(text):
                print(
                    f"[process-decision-search] OK: {path.name} declara BUSQUEDA-PREVIA valida"
                )
            else:
                print(
                    f"[process-decision-search] OK: {path.name} no declara DECISION DE PROCESO: (no aplica)"
                )
            continue

        print(
            f"[process-decision-search] BLOQUEA: {path.name} declara "
            f"'DECISION DE PROCESO:' y {defect}.",
            file=sys.stderr,
        )
        print(
            '\n  AGENTS.md: "antes de resolver una decision de proceso por '
            "razonamiento propio, comprueba primero si existe un protocolo YA "
            'ESCRITO" -- declara el resultado de esa busqueda antes de seguir.',
            file=sys.stderr,
        )
        worst = max(worst, 1)

    return worst


if __name__ == "__main__":
    sys.exit(main())
