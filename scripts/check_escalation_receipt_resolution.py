#!/usr/bin/env python3
"""Barrera: un RECIBO REEJECUTABLE con placeholder sin ruta resuelta es indeterminado (WOT-2026-054d).

Que protege
-----------
MEDIDO 2026-08-10: el bloque F-1 de una ficha de escalado del 2026-08-06
citaba `grep -c ... <DESTINO_ROOT>` en su `RECIBO REEJECUTABLE`. La sesion
del motor resolvio `<DESTINO_ROOT>` a su propio workspace y obtuvo 0 hits
(`exit_code: 1`); la sesion del destino Crear_Texto_LLM lo resolvio a SU
backlog y obtuvo 2 hits. Ninguna de las dos se equivocaba -- median ficheros
DISTINTOS porque el placeholder nunca declaro a QUE se resolvio -- pero
pasaron ~1 hora sosteniendo veredictos opuestos sobre la MISMA ficha antes
de que alguien lo notara. Un comando con placeholder no es portable: es
INDETERMINADO hasta que alguien dice a que ruta resolvio.

CONFIRMADO VIVO (no solo historico): `FP-20260908-escalado-crear-texto-llm-
014j-validate-batch-run.tickets.md`, ya drenada, cita
`python <MOTOR>/scripts/check_backlog_contract.py --project-root <destino>`
en su RECIBO REEJECUTABLE sin declarar a que resolvio ninguno de los dos
placeholders -- el mismo hueco, en una ficha real ya procesada.

Que hace este guard (y que NO)
-------------------------------
Dado un `*.tickets.md` de un buzon de escalado, localiza su seccion
`RECIBO REEJECUTABLE` y, SI esa seccion cita un placeholder de raiz
reconocido (`<MOTOR>`, `<MOTOR_ROOT>`, `<destino>`, `<DESTINO_ROOT>`,
`<destination_root>`, `<workspace>`, en cualquier combinacion de
mayusculas/minusculas), exige que la MISMA seccion declare tambien la
resolucion (la palabra "resuelto"/"resuelta" seguida de ":" o "a"). No
analiza si la ruta declarada es CORRECTA -- eso exigiria ejecutar el
comando y es responsabilidad de quien audita el hallazgo, no de este guard.
Es una barrera de FORMA (como `check_dec_receipt.py`, su hermano de
arquitectura): detecta la AUSENCIA de la declaracion, no su veracidad.

Una ficha SIN ningun placeholder de raiz en su RECIBO REEJECUTABLE (rutas ya
absolutas, o sin comando citado) pasa trivialmente: no hay nada que
resolver.

Grandfathering
--------------
Una ficha nombrada `FP-<fecha>-...` ANTERIOR a `GRANDFATHER_CUTOFF` degrada
a WARN (nunca bloquea): el contrato de redaccion no exigia esto antes de esa
fecha, y poner en rojo retroactivamente 2 meses de fichas ya drenadas no
cambia nada operativo. Mismo patron, misma razon declarada, que
`check_dec_receipt.py::GRANDFATHER_CUTOFF`.

Before / During / After
------------------------
Before: cero o mas rutas de directorio-buzon pasadas por `--inbox`.
During: para cada `*.tickets.md`, localiza su seccion `RECIBO REEJECUTABLE`
    (de la cabecera que la nombra a la siguiente cabecera o `---`) y busca
    los dos marcadores (placeholder de raiz, declaracion de resolucion)
    SOLO dentro de esa seccion. Solo lectura: no escribe, no muta.
After: exit 0 si ninguna ficha bloqueante incumple; exit 1 si al menos una
    ERROR; `EXIT_EMPTY_UNIVERSE` si no hay ninguna ficha que inspeccionar
    (SKIP explicito, nunca un PASS silencioso sobre universo vacio).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Fecha de corte del grandfathering. FIJA, nunca `date.today()` (la misma
# razon que WOT-2026-024u/042i: una fecha derivada del reloj deja el gate
# inerte el dia que corre, porque nada puede nacer "despues de hoy" hoy).
GRANDFATHER_CUTOFF = "2026-10-24"

# Mismo rc distinguible que `check_dec_receipt.py` para universo vacio: un
# `rc=0` ahi seria indistinguible de "valide y no hubo errores".
EXIT_EMPTY_UNIVERSE = 3

_RE_FP_DATE = re.compile(r"\bFP-(\d{4})(\d{2})(\d{2})")

#: Revisor (nan/glm5.3-flash, modo 3): una ficha REAL ya drenada
#: (`FP-20260829-escalado-crear-texto-llm-scope-vocabulary.tickets.md`)
#: nombra la seccion como linea plana `RECIBO REEJECUTABLE (del emisor):`,
#: SIN marcador `#` de heading. El `#{1,6}` es por tanto OPCIONAL, y se
#: tolera texto final (parentesis, dos puntos) tras el nombre de la seccion.
_RE_SECTION_HEADING = re.compile(
    r"^(?:#{1,6}\s*)?(?:\d+\.?\s*)?`?RECIBO\s+REEJECUTABLE`?\b.*$", re.IGNORECASE
)
_RE_ANY_HEADING = re.compile(r"^#{1,6}\s")
_RE_RULE = re.compile(r"^-{3,}\s*$")

_RE_ROOT_PLACEHOLDER = re.compile(
    r"<([A-Za-z_]*(?:MOTOR|DESTINO|DESTINATION|WORKSPACE)[A-Za-z_]*)>",
    re.IGNORECASE,
)
_RE_RESOLUTION_MARKER = re.compile(r"\bresuelt[oa]s?\s*(?::|a\b)", re.IGNORECASE)


def extract_receipt_section(text: str) -> str | None:
    """La seccion `RECIBO REEJECUTABLE` de una ficha, o None si no existe.

    Antes: `text` es el contenido entero de una ficha `*.tickets.md`.
    Durante: busca la cabecera que nombra la seccion (tolera numeracion
        `## 4. RECIBO REEJECUTABLE` y la forma sin numerar
        `## RECIBO REEJECUTABLE`, backticks opcionales) y recorta hasta la
        siguiente cabecera o regla horizontal `---`.
    Despues: el texto de la seccion (sin la cabecera), o None si la ficha no
        trae esa seccion -- una ficha sin RECIBO REEJECUTABLE es un defecto
        DISTINTO (seccion obligatoria ausente) que este guard no audita.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _RE_SECTION_HEADING.match(line.strip()):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for i in range(start, len(lines)):
        if _RE_ANY_HEADING.match(lines[i]) or _RE_RULE.match(lines[i]):
            end = i
            break
    return "\n".join(lines[start:end])


def receipt_resolution_is_declared(section_text: str) -> bool:
    """True sii la seccion no cita placeholder de raiz, o lo cita Y declara su resolucion.

    Funcion PURA: no hace I/O. `section_text` es el cuerpo ya recortado por
    `extract_receipt_section` (o cualquier texto equivalente en un test).
    """
    if not _RE_ROOT_PLACEHOLDER.search(section_text):
        return True
    return bool(_RE_RESOLUTION_MARKER.search(section_text))


def is_grandfathered(name: str, cutoff: str = GRANDFATHER_CUTOFF) -> bool:
    """True si el `FP-<fecha>` del nombre es ANTERIOR al cutoff.

    Un nombre sin fecha parseable NO se grandfathering-ea (fail-closed: ante
    duda, se exige la declaracion).
    """
    match = _RE_FP_DATE.search(name)
    if not match:
        return False
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" < cutoff


def check_file(path: Path) -> tuple[str, str]:
    """Clasifica una ficha. Returns: (nivel, mensaje) con nivel OK|WARN|ERROR."""
    text = path.read_text(encoding="utf-8", errors="replace")
    section = extract_receipt_section(text)
    if section is None:
        return (
            "OK",
            f"{path.name}: sin seccion RECIBO REEJECUTABLE detectable; "
            "fuera del alcance de este guard",
        )

    if receipt_resolution_is_declared(section):
        return ("OK", f"{path.name}: RECIBO REEJECUTABLE resuelto o sin placeholder")

    placeholders = sorted({m.group(0) for m in _RE_ROOT_PLACEHOLDER.finditer(section)})
    message = (
        f"{path.name}: RECIBO REEJECUTABLE cita {', '.join(placeholders)} sin "
        "declarar a que ruta resolvio ('resuelto:'/'resuelto a') -- un comando "
        "con placeholder sin resolucion declarada es INDETERMINADO, no portable "
        "(WOT-2026-054d: dos sesiones lo reprodujeron con resultados opuestos y "
        "ambas tenian razon, porque median ficheros distintos sin saberlo)"
    )
    if is_grandfathered(path.name):
        return (
            "WARN",
            f"{message} -- grandfathered (< {GRANDFATHER_CUTOFF}), no bloquea",
        )
    return ("ERROR", message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Valida que un RECIBO REEJECUTABLE con placeholder de raiz declare "
            "su resolucion (WOT-2026-054d)."
        )
    )
    parser.add_argument(
        "--inbox",
        type=Path,
        action="append",
        default=None,
        help="Directorio de fichas *.tickets.md a validar (repetible).",
    )
    args = parser.parse_args(argv)

    inboxes = [d for d in (args.inbox or []) if d.is_dir()]
    files = sorted(f for d in inboxes for f in d.glob("*.tickets.md"))

    if not files:
        print(
            "[escalation-receipt] SKIP EXPLICITO: 0 fichas a validar "
            f"(inboxes existentes: {len(inboxes)}). No es un PASS."
        )
        return EXIT_EMPTY_UNIVERSE

    oks = warns = errors = 0
    for path in files:
        level, message = check_file(path)
        if level == "ERROR":
            errors += 1
            print(f"[escalation-receipt] ERROR {message}")
        elif level == "WARN":
            warns += 1
            print(f"[escalation-receipt] WARN  {message}")
        else:
            oks += 1
    print(f"[escalation-receipt] {oks} ok / {warns} warn / {errors} error")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
