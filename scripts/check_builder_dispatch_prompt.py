#!/usr/bin/env python
"""Guard: el prompt de arranque de un Builder/lente nan declara leer AGENTS.md.

Que protege
-----------
Kilo (el CLI que invoca cualquier modelo del proveedor `nan` como Builder real
o como lente de canal `agent`) NO autocarga `AGENTS.md` ni ningun puntero de
capa 2 (verificado contra `prompts/doc_optimization.md` PASO 1 punto 4). Un
prompt despachado con `-f <prompt>.md` que no pida EXPRESAMENTE leer
`AGENTS.md` deja al backend trabajando a ciegas de las convenciones del repo,
con independencia de cuanto se reduzca el propio `AGENTS.md` -- no es un
problema de tamano, es de ausencia total de carga automatica
(WOT-2026-108b).

Por que un guard y no solo una nota en el contrato
---------------------------------------------------
Un guard que nadie invoca es una NORMA, no una barrera (`AGENTS.md`, "Barrera
cableada"). Este guard existe para que la comprobacion no dependa de que
quien redacta el prompt se acuerde: se ejecuta sobre el fichero ANTES de
gastar la llamada (`kilo run -f <prompt>`), igual que
`check_loop_bundle_protocol.py` hace con el bundle de un bucle de ensemble.

ALCANCE DECLARADO (lo que este guard NO hace)
----------------------------------------------
Verifica que la instruccion de leer `AGENTS.md` este DECLARADA en el texto
del prompt, no que el backend la obedezca de verdad: una lente puede leer
`AGENTS.md` y razonar mal igualmente (medido, `nan/gemma4`,
`obs-fs-reading-receipt-does-not-certify-correct-reasoning`). Es una barrera
de FORMA. Ademas NO esta cableada automaticamente: no existe en este repo un
punto de codigo que intercepte `kilo run` antes de ejecutarse (el despacho de
un Builder real es una invocacion manual de shell, no una llamada a traves de
un script de este motor) -- quien despacha debe invocar este guard el mismo
(`prompts/builder_invocation_contract.md` Seccion 1.6).

Deteccion por regex, no por substring literal (DESIGN_REVIEW WOT-2026-108b,
2026-10-20, 4 lentes independientes -- groq/qwen, mistral, gemini, cohere --
DECISION: CHANGES unanime): la primera version usaba una tupla de frases
literales (`"LEE AGENTS.MD"`, `"READ AGENTS.MD"`...) y bloqueaba redacciones
de buena fe tan naturales como "Lee el archivo AGENTS.md" o "Lea AGENTS.md
antes de actuar" -- un verbo de lectura con una palabra intermedia ya rompia
el match literal. El patron ahora tolera hasta 5 palabras entre el verbo y
el nombre del fichero.

Before / During / After
-----------------------
Before: recibe la ruta de un fichero de prompt legible en UTF-8.
During: busca el marcador de lectura de `AGENTS.md` (invariante natal, SIEMPRE
    bloquea su ausencia) y, si el prompt menciona memoria del proyecto, el
    marcador de lectura de sus punteros de capa 2 (invariante condicional,
    solo WARN). Sin red, sin subprocess, sin escritura.
After: exit 0 si el invariante natal esta declarado; exit 1 si falta, con la
    correccion exacta. No muta el prompt.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Invariante natal: BLOQUEA siempre. Exige la PROPIEDAD (un verbo de lectura
# seguido, a no mas de 5 palabras de distancia, del nombre del fichero), no
# una frase literal: un verbo con un articulo o sustantivo intermedio
# ("Lee el archivo AGENTS.md") es una redaccion natural, no una excepcion.
AGENTS_MD_INSTRUCTION_RE = re.compile(
    r"\b(LEE|LEELO|LEER|LEA|READ|CONSULTA|REVISA)\b(?:\s+\S+){0,5}?\s+AGENTS\.MD\b",
    re.IGNORECASE,
)

# Invariante condicional: solo se exige si el prompt menciona memoria del
# proyecto. Ausencia -> WARN, nunca bloqueo (la clausula de capa 2 de
# `builder_invocation_contract.md` Seccion 1 es condicional a que la tarea
# toque memoria, no universal). Markers con limite de palabra (`\b`) para no
# disparar con menciones genericas de ingenieria ("memoria RAM", "puntero
# nulo") que 3 de las 4 lentes de la DESIGN_REVIEW senalaron como falsos
# positivos de la version anterior (bare "MEMORIA"/"PUNTERO").
MEMORY_TOPIC_RE = re.compile(
    r"MEMORIA\s+DEL\s+PROYECTO|MEMORIA\s+PERSISTENTE|MEMORY\.MD|MEMORY_RULES"
    r"|MEMORY_PROFILE|CAPA\s+[23]\b|\bL[23]\b",
    re.IGNORECASE,
)

LAYER2_POINTER_RE = re.compile(
    r"MEMORY\.MD|MEMORY_RULES|MEMORY_PROFILE|PUNTEROS?\s+DE\s+CAPA\s+[23]|\bL[23]\b",
    re.IGNORECASE,
)


def has_agents_md_instruction(text: str) -> bool:
    """True si el prompt instruye expresamente leer AGENTS.md."""
    return bool(AGENTS_MD_INSTRUCTION_RE.search(text))


def mentions_memory_topic(text: str) -> bool:
    """True si el prompt menciona memoria del proyecto (activa el WARN)."""
    return bool(MEMORY_TOPIC_RE.search(text))


def has_layer2_pointer_instruction(text: str) -> bool:
    """True si el prompt instruye leer los punteros de capa 2 (MEMORY.md/L2/L3)."""
    return bool(LAYER2_POINTER_RE.search(text))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Verifica que un prompt de arranque de Builder/lente nan instruya "
            "leer AGENTS.md antes de 'kilo run -f <prompt>'."
        )
    )
    ap.add_argument("prompt", help="ruta del fichero de prompt de arranque")
    args = ap.parse_args()

    path = Path(args.prompt)
    if not path.is_file():
        print(
            f"[builder-dispatch] ERROR: prompt no encontrado: {path}",
            file=sys.stderr,
        )
        return 2

    text = path.read_text(encoding="utf-8", errors="replace")

    if not mentions_memory_topic(text):
        pass  # la clausula de capa 2 no aplica a este prompt.
    elif not has_layer2_pointer_instruction(text):
        print(
            f"[builder-dispatch] WARN: {path.name} menciona memoria del proyecto "
            f"pero no instruye leer sus punteros de capa 2 (MEMORY.md/"
            f"memory_rules.md/memory_profile.md). No bloquea.",
            file=sys.stderr,
        )

    if has_agents_md_instruction(text):
        print(f"[builder-dispatch] OK: {path.name} instruye leer AGENTS.md")
        return 0

    print(
        f"[builder-dispatch] BLOQUEA: {path.name} no instruye expresamente leer "
        f"AGENTS.md. Kilo no autocarga nada: anade una linea explicita, p.ej. "
        f"'Lee AGENTS.md entero antes de actuar' antes de dispachar con "
        f"'kilo run -f {path.name}'.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
