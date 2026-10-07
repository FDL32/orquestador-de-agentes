#!/usr/bin/env python
"""Guard: detecta contradicciones numericas internas en un documento.

Que protege
-----------
Un documento de arranque/continuidad puede afirmar el MISMO hecho medible con
DOS numeros distintos en secciones distintas -- p.ej. "52 commits POR DELANTE"
en una seccion y "51 commits POR DELANTE" en otra, sobre el mismo estado git.
MEDIDO 2026-10-07 (vuelo memoria v3): un lector con filesystem real
(deepseek-v4-flash via Kilo) lo caza re-ejecutando `git rev-list --count`; una
lente SIN filesystem (Codex, canal api/texto) no puede, y lo declara
honestamente `NO VERIFICABLE` -- pero el defecto pasa igual a la fase
siguiente si nadie mas lo mide. Este guard no necesita filesystem del HECHO
real: solo necesita leer el documento y comparar sus propias afirmaciones
entre si.

Por que un GUARD y no revision manual
--------------------------------------
Es aritmetica contra el propio texto, no juicio: un script determinista lo
cubre sin gastar una ronda de bucle adversarial ni una lente LLM. Sigue el
mismo principio que `check_loop_bundle_protocol.py`: barrera de FORMA
(coincidencia de patron), no de VERDAD (no sabe cual numero es el correcto).

Heuristica (derivada por bucle adversarial, Codex BA05, 2026-10-07)
---------------------------------------------------------------------
Dos menciones del mismo PREDICADO (p.ej. "commits por delante") con DOS
numeros DISTINTOS solo cuentan como contradiccion si las CINCO condiciones se
cumplen:

1. Mismo sujeto/metrica: el mismo predicado normalizado aparece en ambas.
2. Mismo predicado normalizado: minusculas, espacios colapsados.
3. Ninguna de las dos menciones lleva un CALIFICADOR TEMPORAL/TRANSICIONAL
   cerca (antes de la frase, en la misma oracion): "tras", "despues de",
   "sera", "seran", "historicamente", "antes era", "proximo", "siguiente".
   Un calificador asi indica PROYECCION o TRANSICION, no una afirmacion del
   estado actual, y dos valores distintos ahi NO son contradiccion.
4. Ninguna de las dos menciones esta dentro de una CITA atribuida a otra
   fuente (linea que empieza por `>` markdown, o entre comillas con atribucion
   "segun", "cito", "decia").
5. Ambas son afirmaciones de estado ACTUAL (se asume por defecto si pasan 3 y
   4 -- no hay forma barata de verificar "actualidad" mas alla de excluir
   proyeccion/transicion/cita).

ALCANCE DECLARADO (lo que este guard NO hace)
----------------------------------------------
No sabe CUAL numero es correcto -- eso exige re-ejecutar el comando real
contra el sistema (fuera del alcance de un guard de solo-texto). No cubre
numeros en formato indirecto ("cincuenta y uno"), unidades distintas, tablas,
ni contradicciones no numericas. Es una PRIMERA barrera barata, no sustituye
la re-verificacion con filesystem real quien cierre el documento.

Before / During / After
-----------------------
Before: recibe la ruta de un fichero de texto legible en UTF-8.
During: extrae todas las menciones `<numero> <predicado>` conocidas, agrupa
    por predicado normalizado, filtra las que llevan calificador o cita cerca,
    y compara los numeros restantes del mismo grupo.
After: exit 0 si no hay contradiccion tras el filtro; exit 1 listando cada
    grupo contradictorio con sus dos valores y las lineas donde aparecen. No
    muta nada.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Calificadores que convierten una mencion en PROYECCION/TRANSICION, no en
# afirmacion de estado actual. Se buscan en la MISMA linea que el numero.
_TEMPORAL_QUALIFIERS = (
    "tras el proximo",
    "tras el siguiente",
    "despues de",
    "despues del",
    "sera",
    "seran",
    "historicamente",
    "antes era",
    "antes eran",
    "proximo commit",
    "siguiente commit",
    "en el futuro",
    "quedara",
    "quedaran",
    "pasara a",
    "pasaran a",
)

# Una linea que es CITA atribuida a otra fuente no cuenta como afirmacion
# propia del documento.
_QUOTE_MARKERS = (">", "segun ", "cito ", "decia ", "afirmo ")

# Predicados a vigilar: (etiqueta legible, patron que captura el NUMERO antes
# del predicado). El patron exige el numero INMEDIATAMENTE antes del texto.
_PREDICATES: tuple[tuple[str, str], ...] = (
    ("commits por delante", r"(\d+)\s+commits?\s+por\s+delante"),
    ("commits adelante", r"(\d+)\s+commits?\s+adelante"),
    ("lineas", r"(\d+)\s+l[ií]neas?\b"),
)

# Un numero que es en realidad un IDENTIFICADOR (Paso N, seccion N, un rango
# N-M) no es un CONTEO y no debe entrar en la comparacion. MEDIDO: "Paso 0
# lineas 54-92" capturaba el "0" del numero de Paso como si fuera una cuenta
# de lineas -- falso positivo real contra arranque_borrador_v1.md, 2026-10-07.
_IDENTIFIER_PRECEDERS = ("paso", "seccion", "section", "fase", "step")


def _number_is_identifier(line: str, match: re.Match) -> bool:
    """True si el numero capturado es un identificador (Paso N), no un conteo."""
    before = line[: match.start(1)].strip().lower()
    words = before.split()
    last_word = words[-1].strip("()[]{}:;,.\"'") if words else ""
    return last_word in _IDENTIFIER_PRECEDERS


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _line_has_qualifier(line: str) -> bool:
    lowered = _normalize(line)
    return any(q in lowered for q in _TEMPORAL_QUALIFIERS)


def _line_is_quote(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith(">"):
        return True
    lowered = stripped.lower()
    return any(
        lowered.startswith(m) or f" {m}" in lowered for m in _QUOTE_MARKERS if m != ">"
    )


def find_contradictions(text: str) -> list[dict]:
    """Devuelve la lista de contradicciones encontradas (vacia si no hay).

    Cada entrada: {"predicate": str, "values": [(numero, linea_num, linea_texto), ...]}
    """
    lines = text.splitlines()
    by_predicate: dict[str, list[tuple[str, int, str]]] = {}

    for lineno, line in enumerate(lines, start=1):
        if _line_is_quote(line):
            continue
        if _line_has_qualifier(line):
            continue
        for label, pattern in _PREDICATES:
            for match in re.finditer(pattern, line, flags=re.IGNORECASE):
                if _number_is_identifier(line, match):
                    continue
                number = match.group(1)
                by_predicate.setdefault(label, []).append(
                    (number, lineno, line.strip())
                )

    contradictions = []
    for label, occurrences in by_predicate.items():
        distinct_values = {n for n, _, _ in occurrences}
        if len(distinct_values) > 1:
            contradictions.append({"predicate": label, "values": occurrences})
    return contradictions


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Detecta contradicciones numericas internas en un documento."
    )
    ap.add_argument("document", help="ruta del fichero a verificar")
    args = ap.parse_args()

    path = Path(args.document)
    if not path.is_file():
        print(
            f"[self-contradiction] ERROR: fichero no encontrado: {path}",
            file=sys.stderr,
        )
        return 2

    text = path.read_text(encoding="utf-8", errors="replace")
    contradictions = find_contradictions(text)

    if not contradictions:
        print(f"[self-contradiction] OK: sin contradicciones numericas en {path.name}")
        return 0

    print(
        f"[self-contradiction] BLOQUEA: {path.name} afirma el mismo predicado "
        f"con valores distintos en {len(contradictions)} caso(s).",
        file=sys.stderr,
    )
    for c in contradictions:
        values = sorted({n for n, _, _ in c["values"]})
        print(f"  - '{c['predicate']}': valores {values}", file=sys.stderr)
        for number, lineno, line in c["values"]:
            print(f"      linea {lineno}: ({number}) {line}", file=sys.stderr)
    print(
        "\n  Esto NO dice cual valor es correcto: re-ejecuta el comando real "
        "que produjo el dato y corrige el documento a un unico valor "
        "consistente antes de entregarlo.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
