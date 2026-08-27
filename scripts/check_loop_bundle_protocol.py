#!/usr/bin/env python
"""Guard: el bundle de un bucle declara su protocolo de suficiencia.

Que protege
-----------
Una lente que recibe un encargo mal acotado no falla de forma ruidosa: **se
queda muda**. Medido en la sesion 2026-08-05 con la MISMA lente (`BA06`,
opencode/glm), el MISMO cwd y ficheros del MISMO repo:

    bundle SIN protocolo (cierre de sesion)  ->    106 bytes, sin veredicto
    bundle CON protocolo (fix F-3)           ->  4.708 bytes, informe completo

Lo que cambio no fue la residencia de los ficheros ni el modelo: fue el
ENCARGO. Una lente muda es indistinguible de una lente que no encontro nada
-- la misma familia que un `exit 0` que significa "no hice nada".

Por que un GUARD y no una nota en un prompt
--------------------------------------------
"Un guard que nadie invoca es una NORMA, no una barrera" (WOT-2026-024u).
Escribir el protocolo en un prompt lo deja a merced de que el redactor se
acuerde -- y el fallo original fue exactamente ese: se escribio "todo lo que
necesitas esta DENTRO de tu cwd" sin comprobarlo. Este guard lee el bundle
ANTES de gastar la ronda.

Los tres invariantes (derivados por contraste, no por opinion)
--------------------------------------------------------------
1. **Inventario de evidencia.** Por cada afirmacion a verificar, el bundle
   nombra el fichero que la sustenta. Si no se puede nombrar, el punto no es
   verificable y no debe pedirse.
2. **Salida declarada.** Instruccion explicita de reportar `NO VERIFICABLE`
   en vez de intentar salir o abortar. Es el invariante que convierte un
   aborto en un hallazgo, y el que mas peso tuvo en el contraste medido.
3. **Presupuesto de exploracion.** Un limite de ficheros/alcance. `BA06` no
   abandono por falta de material: abandono tras anunciar que iba a recopilar
   evidencia, sin nada que le dijera cuando parar.

ALCANCE DECLARADO (lo que este guard NO hace)
----------------------------------------------
Verifica que los invariantes esten DECLARADOS, no que sean CIERTOS. No puede
comprobar que el inventario sea completo ni que los ficheros existan: eso
exige juicio. Es una barrera de FORMA, y se declara asi en vez de venderse
como semantica -- el defecto que este repo llama "aplicate tu propia vara".

Before / During / After
-----------------------
Before: recibe la ruta de un fichero de bundle legible en UTF-8.
During: busca los marcadores de los tres invariantes. Sin red, sin subprocess,
    sin escritura.
After: exit 0 si los tres estan declarados; exit 1 nombrando los que faltan,
    con la correccion exacta. No muta nada.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Marcadores de cada invariante. Se aceptan variantes para no imponer una
# redaccion literal: el guard exige la PROPIEDAD, no una plantilla.
INVARIANTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "inventario_de_evidencia": (
        "por cada punto del encargo, nombrar el fichero que lo sustenta",
        ("INVENTARIO DE EVIDENCIA", "INVENTARIO DE LA EVIDENCIA"),
    ),
    "salida_declarada": (
        "instruir a la lente que reporte NO VERIFICABLE en vez de abortar",
        ("NO VERIFICABLE",),
    ),
    "presupuesto_exploracion": (
        "declarar un limite de exploracion (cuantos ficheros / cuando parar)",
        ("no explores mas de", "no mas de", "PRESUPUESTO", "y para"),
    ),
}


# ---------------------------------------------------------------------------
# WOT-2026-035a: REFUTACION PREVIA, la cuarta invariante.
# La norma "censo antes de tocar superficie gobernante" existia como PROSA y
# era NO EJECUTABLE: nada la verificaba. Se vuelve exigible, pero OPT-IN.
#
# Vive FUERA de INVARIANTS a proposito. Las tres natales BLOQUEAN siempre; esta
# solo bloquea cuando el encargo declara que toca superficie gobernante
# (`--requires-refutation`). Meterla en INVARIANTS habria convertido en rojo
# todos los bundles historicos de golpe -- un gate que nace bloqueando lo que
# ayer era legal no se adopta: se desactiva.
#
# Se exige como SECCION DECLARADA, no como keyword magico semantico: el guard
# verifica que el bundle DECLARE haber refutado, igual que hace con las otras
# tres. No puede (ni pretende) verificar que la refutacion sea CIERTA.
# ---------------------------------------------------------------------------
REFUTATION_INVARIANT = (
    "refutacion_previa",
    "censar y refutar lo que ya existe ANTES de tocar superficie gobernante",
    ("REFUTACION-PREVIA:", "REFUTACION PREVIA:"),
)


def has_refutation_section(text: str) -> bool:
    """True iff the bundle DECLARES its prior-refutation section."""
    upper = text.upper()
    return any(m.upper() in upper for m in REFUTATION_INVARIANT[2])


def check_bundle(text: str) -> list[str]:
    """Devuelve la lista de invariantes AUSENTES (vacia si el bundle cumple)."""
    upper = text.upper()
    missing = []
    for name, (_, markers) in INVARIANTS.items():
        if not any(m.upper() in upper for m in markers):
            missing.append(name)
    return missing


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verifica que un bundle de bucle declare su protocolo de suficiencia."
    )
    ap.add_argument("bundle", help="ruta del fichero de bundle")
    ap.add_argument(
        "--requires-refutation",
        action="store_true",
        help=(
            "el encargo declara que toca SUPERFICIE GOBERNANTE: exige la "
            "seccion REFUTACION-PREVIA: en el bundle (sin el flag, solo WARN)"
        ),
    )
    args = ap.parse_args()

    path = Path(args.bundle)
    if not path.is_file():
        print(f"[loop-bundle] ERROR: bundle no encontrado: {path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8", errors="replace")
    missing = check_bundle(text)

    # WOT-2026-035a: la cuarta invariante se evalua SIEMPRE, pero solo BLOQUEA
    # con el flag. Sin el flag avisa, para que la deuda sea visible sin
    # convertir en rojo natal todo bundle que hoy es legal.
    refutation_ok = has_refutation_section(text)
    if not refutation_ok:
        if args.requires_refutation:
            print(
                f"[loop-bundle] BLOQUEA: el encargo declara SUPERFICIE "
                f"GOBERNANTE y a {path.name} le falta la seccion "
                f"'REFUTACION-PREVIA:' ({REFUTATION_INVARIANT[1]}).",
                file=sys.stderr,
            )
            return 1
        print(
            f"[loop-bundle] WARN: {path.name} no declara 'REFUTACION-PREVIA:'. "
            f"Sin --requires-refutation esto NO bloquea; con el, si.",
            file=sys.stderr,
        )

    if not missing:
        print(f"[loop-bundle] OK: los 3 invariantes estan declarados en {path.name}")
        return 0

    print(
        f"[loop-bundle] BLOQUEA: al bundle {path.name} le faltan "
        f"{len(missing)} invariante(s) del protocolo.",
        file=sys.stderr,
    )
    for name in missing:
        print(f"  - {name}: {INVARIANTS[name][0]}", file=sys.stderr)
    print(
        "\n  Medido 2026-08-05: la MISMA lente devolvio 106 bytes sin protocolo\n"
        "  y 4708 CON el. Una lente muda es indistinguible de una que no\n"
        "  encontro nada. Corrige el bundle antes de gastar la ronda.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
