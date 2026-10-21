#!/usr/bin/env python
"""Dedupe de hallazgos de `repo_audit_multiagent.md` (Fase 3) y parser de tablas.

Que protege
-----------
Dos herramientas distintas (p.ej. `ruff -S` y `semgrep`, o `vulture` y
`deadcode`) pueden marcar la MISMA linea con la MISMA categoria desde lanes
distintos. Sin dedupe, esa linea se convierte en dos hallazgos `H-NN`
independientes y, si ambos se promueven, en dos tickets para arreglar lo
mismo -- el "29 tests vs 4 reales" de otra familia de errores, aplicado a
hallazgos de auditoria.

Este modulo es ademas la FUENTE UNICA del parser de tablas Markdown de los
hallazgos (`parse_tablas`, `normaliza_categoria`): `check_audit_report.py` lo
importa en vez de duplicar regex, porque dos parsers del mismo formato son la
familia de error que ese validador existe para cerrar.

Fingerprint
-----------
`(archivo, linea, categoria)`. Archivo normalizado a POSIX (`/`) para que
una ruta con `\\` (Windows) y otra con `/` fusionen igual. `linea` acepta un
rango (`"42-50"`) o un numero simple (`"42"`); el fingerprint usa el primer
numero del rango. `categoria` es la BASE del enum cerrado en mayusculas (el
calificador no entra: `SMELL (x)` y `SMELL` son la misma categoria).

Hallazgos de alcance modulo: una fila con la columna opcional `alcance` =
`modulo` no necesita linea; su fingerprint es `(archivo, "*", categoria)`.
Sin la columna, o con `alcance` = `simbolo`, rige la regla de linea de arriba
(retrocompatible: las tablas anteriores no la llevan).

Formato de entrada
-------------------
Lee uno o mas ficheros `HALLAZGOS_<lane>.md` (Markdown con una o mas tablas
GFM; las columnas se leen POR NOMBRE de cabecera: `id`, `categoria`,
`archivo`/`archivo:linea`, opcionalmente `calificador` y `alcance`). Parsing
deliberadamente TOLERANTE: una fila sin ancla reconocible no bloquea el resto,
se reporta aparte como "sin fingerprint" y pasa intacta (no se puede dedupear
lo que no se puede anclar). Un `|` literal en una celda se escribe `\\|` (como en
GFM); sin escapar, aunque este entre backticks, parte la fila y el validador lo
avisa como `FILA-ANCHO`.

Before: uno o mas paths a `HALLAZGOS_*.md` existentes, legibles en UTF-8.
During: parseo de tablas por cabecera, sin red, sin subprocess, sin escritura
    salvo el reporte de salida. La salida se fuerza a UTF-8 (una consola
    cp1252 de Windows revienta al imprimir un caracter no representable).
After: imprime un reporte con los grupos duplicados encontrados (si los hay)
    y el conteo final deduplicado. Exit 0 siempre (el dedupe informa, no
    bloquea) salvo error de lectura (exit 1).
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path


# Enum cerrado de `categoria` (Fase 2 del prompt). Orden irrelevante: el
# normalizador prueba de la mas larga a la mas corta para que
# `DEAD (unverified dynamic)` no se lea como `DEAD` + calificador.
CATEGORIAS = (
    "DEAD (unverified dynamic)",
    "DEAD",
    "ABANDONED",
    "LEGACY",
    "SMELL",
    "BUENAS-PRACTICAS",
    "PROCESO",
    "SECURITY-critica",
    "SECURITY-alta",
    "SECURITY-media",
    "SECURITY-baja",
)
ALCANCES = ("simbolo", "modulo")

ID_CANONICO_RE = re.compile(r"H-\d+")
ARCHIVO_LINEA_RE = re.compile(r"`?([^`:,\s]+\.\w+)[:,](\d+)")
ARCHIVO_RE = re.compile(r"`?([^`:,\s]+\.\w+)")
_SEPARADOR_CELDA_RE = re.compile(r"^:?-+:?$")
_PIPE_NO_ESCAPADO_RE = re.compile(r"(?<!\\)\|")
_BOM = chr(0xFEFF)
_FENCES = ("```", "~~~")


def _normaliza_archivo(archivo: str) -> str:
    return archivo.strip().strip("`").replace("\\", "/")


def normaliza_categoria(raw: str) -> tuple[str | None, str]:
    """Separa una celda `categoria` en (base del enum, calificador).

    Before: `raw` es el texto de la celda (puede llevar backticks).
    During: compara sin distinguir mayusculas contra `CATEGORIAS` (la mas
        larga primero); lo que sobra tras la base, entre parentesis o tras un
        guion, es el calificador.
    After: `(base, calificador)`; `base` es None si la celda no empieza por
        ninguna categoria del enum (el calificador conserva el texto crudo).
    """
    txt = raw.strip().strip("`").strip()
    low = txt.lower()
    for cat in sorted(CATEGORIAS, key=len, reverse=True):
        if not low.startswith(cat.lower()):
            continue
        resto = txt[len(cat) :].strip()
        if not resto:
            return cat, ""
        if resto.startswith("(") and resto.endswith(")"):
            return cat, resto[1:-1].strip()
        if resto[0] in ("-", chr(0x2014), chr(0x2013)):  # guion, raya, semiraya
            return cat, resto[1:].strip()
        if resto.startswith("("):
            return cat, resto.strip("() ")
    return None, txt


def _celdas(linea: str) -> list[str] | None:
    s = linea.strip()
    if not s.startswith("|"):
        return None
    s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    # `\|` es un pipe LITERAL en GFM (p.ej. `git grep "a\|b"` en una celda de
    # evidencia): no parte la celda y se entrega ya sin la barra de escape.
    return [c.strip().replace("\\|", "|") for c in _PIPE_NO_ESCAPADO_RE.split(s)]


def _es_separador(celdas: list[str] | None) -> bool:
    return bool(celdas) and all(_SEPARADOR_CELDA_RE.match(c) for c in celdas)


def _norm_col(nombre: str) -> str:
    n = nombre.strip().strip("`*").lower()
    # `categoría` (con acento) debe leerse igual que `categoria`: si no, la tabla entera
    # deja de reconocerse como tabla de hallazgos y su censo desaparece sin aviso.
    n = "".join(
        c for c in unicodedata.normalize("NFKD", n) if not unicodedata.combining(c)
    )
    return "archivo" if n.startswith("archivo") else n


def parse_tablas(contenido: str, fuente: str) -> list[dict]:
    """Extrae TODAS las filas de las tablas GFM de un Markdown, por cabecera.

    Before: `contenido` es el texto completo de un fichero Markdown.
    During: una tabla empieza en una linea `|...|` seguida de una linea
        separadora; las columnas se nombran por la cabecera normalizada
        (`archivo:linea` -> `archivo`). El ultimo encabezado `#` visto queda
        como `seccion` de cada fila.
    After: lista de dicts `{fuente, seccion, header, cols, n_linea, ancho_extra}`;
        `cols` mapea nombre de columna -> texto de celda y `ancho_extra` es True si
        la fila trae mas celdas que la cabecera (el dato sobrante no se lee). No
        filtra por formato de id. Un BOM inicial se ignora y lo que queda dentro de
        un bloque de codigo (``` o ~~~) NO se parsea: es un ejemplo citado.
    """
    lineas = contenido.lstrip(_BOM).splitlines()
    filas: list[dict] = []
    header: list[str] | None = None
    seccion = ""
    en_fence = False
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        if linea.lstrip().startswith(_FENCES):
            en_fence = not en_fence
            header = None
            i += 1
            continue
        if en_fence:
            i += 1
            continue
        if linea.lstrip().startswith("#"):
            seccion = linea.lstrip("# ").strip()
            header = None
            i += 1
            continue
        celdas = _celdas(linea)
        if celdas is None:
            header = None
            i += 1
            continue
        if header is None:
            siguiente = _celdas(lineas[i + 1]) if i + 1 < len(lineas) else None
            if _es_separador(siguiente):
                header = [_norm_col(c) for c in celdas]
                i += 2
                continue
            i += 1
            continue
        if not _es_separador(celdas):
            cols = {
                h: (celdas[k] if k < len(celdas) else "") for k, h in enumerate(header)
            }
            filas.append(
                {
                    "fuente": fuente,
                    "seccion": seccion,
                    "header": tuple(header),
                    "cols": cols,
                    "n_linea": i + 1,
                    "ancho_extra": len(celdas) > len(header),
                }
            )
        i += 1
    return filas


def extraer_filas(contenido: str, fuente: str) -> list[dict]:
    """Extrae filas de hallazgo (tablas con columnas `id` y `categoria`).

    Before: `contenido` es el texto completo de un `HALLAZGOS_<lane>.md`.
    During: usa `parse_tablas`; descarta las tablas sin `id`+`categoria` y las
        filas cuyo id no es `H-<digitos>` (el validador las reporta aparte).
    After: lista de dicts con `id`, `categoria` (celda cruda), `categoria_base`,
        `calificador`, `alcance`, `archivo`, `linea`, `fingerprint` (o None si
        no se pudo anclar) y `fuente`.
    """
    filas = []
    for fila in parse_tablas(contenido, fuente):
        cols = fila["cols"]
        if "id" not in cols or "categoria" not in cols:
            continue
        id_ = cols["id"].strip().strip("`*")
        if not ID_CANONICO_RE.fullmatch(id_):
            continue
        categoria = cols["categoria"].strip()
        base, calificador = normaliza_categoria(categoria)
        alcance = cols.get("alcance", "").strip().strip("`*").lower() or "simbolo"
        archivo_raw = cols.get("archivo", "").strip()

        archivo_norm = None
        linea = None
        fingerprint = None
        cat_fp = (base or categoria).upper()
        if alcance == "modulo":
            anclaje = ARCHIVO_RE.search(archivo_raw)
            if anclaje:
                archivo_norm = _normaliza_archivo(anclaje.group(1))
                linea = "*"
                fingerprint = (archivo_norm, "*", cat_fp)
        else:
            anclaje = ARCHIVO_LINEA_RE.search(archivo_raw)
            if anclaje:
                archivo_norm = _normaliza_archivo(anclaje.group(1))
                linea = anclaje.group(2)
                fingerprint = (archivo_norm, linea, cat_fp)

        filas.append(
            {
                "id": id_,
                "categoria": categoria,
                "categoria_base": base,
                "calificador": calificador,
                "alcance": alcance,
                "archivo": archivo_norm or archivo_raw,
                "linea": linea,
                "fingerprint": fingerprint,
                "fuente": fuente,
            }
        )
    return filas


def dedupe(filas: list[dict]) -> tuple[dict[tuple, list[dict]], list[dict]]:
    """Agrupa filas por fingerprint.

    Before: lista de filas de `extraer_filas` (puede venir de varios ficheros).
    During: agrupacion pura, sin I/O.
    After: `(grupos, sin_fingerprint)`. `grupos` solo contiene fingerprints con
        2+ filas (los duplicados reales); los de 1 fila no son duplicado y no
        se reportan como tal.
    """
    por_fingerprint: dict[tuple, list[dict]] = {}
    sin_fingerprint: list[dict] = []
    for fila in filas:
        if fila["fingerprint"] is None:
            sin_fingerprint.append(fila)
            continue
        por_fingerprint.setdefault(fila["fingerprint"], []).append(fila)

    duplicados = {
        fp: filas_dup for fp, filas_dup in por_fingerprint.items() if len(filas_dup) > 1
    }
    return duplicados, sin_fingerprint


def _forzar_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _forzar_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("hallazgos", nargs="+", help="Ruta(s) a HALLAZGOS_<lane>.md")
    args = parser.parse_args()

    todas_las_filas: list[dict] = []
    for ruta_str in args.hallazgos:
        ruta = Path(ruta_str)
        if not ruta.is_file():
            print(f"ERROR: no existe o no es fichero: {ruta}", file=sys.stderr)
            return 1
        try:
            contenido = ruta.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"ERROR: no se pudo leer {ruta}: {exc}", file=sys.stderr)
            return 1
        todas_las_filas.extend(extraer_filas(contenido, fuente=ruta.name))

    duplicados, sin_fingerprint = dedupe(todas_las_filas)

    total = len(todas_las_filas)
    total_duplicado = sum(len(filas) for filas in duplicados.values())
    total_unico = total - total_duplicado + len(duplicados)

    print(f"Filas leidas: {total} (de {len(args.hallazgos)} fichero(s))")
    print(f"Sin fingerprint (no anclables, pasan intactas): {len(sin_fingerprint)}")
    print(f"Grupos duplicados encontrados: {len(duplicados)}")
    print(f"Total tras dedupe: {total_unico}")
    print()

    if duplicados:
        print("--- Duplicados (mismo archivo+linea+categoria) ---")
        for (archivo, linea, categoria), filas_dup in sorted(duplicados.items()):
            ids = ", ".join(f"{f['id']} ({f['fuente']})" for f in filas_dup)
            print(f"  {archivo}:{linea} [{categoria}] -> {ids}")
    else:
        print("Sin duplicados cruzados entre los ficheros dados.")

    if sin_fingerprint:
        print()
        print("--- Sin fingerprint (archivo:linea no reconocible, revisar a mano) ---")
        for fila in sin_fingerprint:
            print(f"  {fila['id']} ({fila['fuente']}): archivo={fila['archivo']!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
