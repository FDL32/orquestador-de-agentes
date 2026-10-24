#!/usr/bin/env python
r"""Guard: una lente de conformidad ve que el artefacto CUMPLE su contrato, no
que EFECTOS crea el artefacto que ningun contrato cubre (WOT-2026-043n).

Que protege
-----------
MEDIDO 2026-07-29: el prompt de arranque de WOT-2026-042q paso un bucle de 4
lentes (Codex + lector-FS) que encontro dos clausulas normativas omitidas y un
falso-conforme. Pero NINGUNA lente vio otras dos cosas que si caso un ejecutor
al leer el prompt en contexto fresco: (i) el prompt ordenaba ~20 llamadas de
fan-out a 5 backends externos -- el bundle SALIA de la maquina -- sin declarar
quien autorizaba esa publicacion (la autorizacion se habia dado de viva voz en
la sesion que lo redacto y no viajaba dentro del fichero); (ii) el prompt
ordenaba leer 1.070 lineas de contratos ANTES de una re-medicion read-only que
podia declarar el vuelo MOOT, gastando contexto en una rama que quiza no
existia. Un prompt que ordena dispatch externo es PERFECTAMENTE COHERENTE con
su propio contrato -- el contrato lo ordena -- asi que una auditoria de
CONFORMIDAD (coherencia artefacto-contrato) no puede verlo: hay que preguntar
que EFECTOS crea el artefacto, no si es fiel a si mismo.

Es la MISMA FAMILIA que `check_contract_clause_coverage.py` (WOT-2026-042y)
pero en el eje ORTOGONAL: 042y verifica que el artefacto CUBRA lo que un
contrato citado exige (lo que el artefacto OMITE); este guard verifica que el
artefacto DECLARE quien autoriza las acciones de alto impacto que el mismo
ORDENA (lo que el artefacto ANADE). Las lentes de conformidad de este
repositorio (bucles ensemble, CONTRACT_AUDIT, MANAGER_REVIEW, CLOSE) miran
hacia DENTRO del artefacto (coherencia); este guard mira hacia FUERA (efectos
no cubiertos por ningun contrato).

Que hace este guard
--------------------
Detecta, por patron ESTRUCTURAL (nunca analisis semantico de prosa, el muro
WOT-2026-025c ya midio 8 intentos fallidos de esa via), si el artefacto ORDENA
alguna de 4 categorias de accion que requieren OK humano no heredable:

  - `dispatch_externo`: fan-out o envio del bundle/prompt a backends o
    proveedores EXTERNOS (el contenido sale de la maquina);
  - `push`: publicar una rama (git push / "push a origin");
  - `borrado_irreversible`: `rm -rf`, borrado irreversible, force-push;
  - `gasto_desproporcionado`: ordenar leer un numero de lineas de 3+ digitos,
    o leer un contrato entero/completo, como paso previo declarado.

Y verifica que, si ORDENA alguna de esas 4, el artefacto tambien declare QUIEN
autoriza -- un campo `Autorizacion:`/`autorizado por <alguien>`/`con
autorizacion de <alguien>` en CUALQUIER lugar del texto (misma simplicidad que
042y: presencia literal, no proximidad ni atribucion por accion). No basta la
palabra "autorizacion" sola: "sin autorizacion" NO cuenta, porque el patron
exige una declaracion POSITIVA que NOMBRE a quien autoriza.

ALCANCE DECLARADO (lo que este guard NO hace)
----------------------------------------------
No es un juez LLM que decida que es "desproporcionado": el umbral de
`gasto_desproporcionado` es enumerable (3+ digitos de lineas, o "todo/entero/
completo" + "contrato(s)"), nunca una opinion. No analiza si la autorizacion
declarada es VALIDA o viene de quien corresponde -- solo que el artefacto la
declare, igual que 042y solo audita que un identificador NOMBRE, no que se
CUMPLA. Un artefacto que solo ordena acciones locales y read-only (sin ninguna
de las 4 categorias) nunca se bloquea, aunque no declare autorizacion alguna
-- si todo se marcara, la lente seria inservible y se le rodearia.

Before / During / After
------------------------
Before: recibe la ruta de un artefacto legible en UTF-8.
During: sin red, sin subprocess, sin escritura. Solo lectura y regex.
After: exit 0 si el artefacto no ordena ninguna de las 4 categorias, o si las
    ordena y declara quien autoriza; exit 1 nombrando cada categoria ordenada
    sin autorizacion declarada. No muta nada.

Nota de nombre de fichero (WOT-2026-043n): se evita deliberadamente la cadena
"auth" en el nombre de este modulo -- `.agent/hooks/guard_paths.py` tiene un
patron `r"auth"` SIN ANCLAR que bloquea CUALQUIER ruta que la contenga como
substring (incluida "autorizacion"), no solo credenciales/oauth. Es la misma
clase de sobre-match ya corregida para `\.git` (ver memoria
`guard-dotgit-substring-overmatch`); este modulo no la corrige (fuera de
alcance de este ticket) pero evita tropezar con ella.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


#  evita que una instruccion NEGADA ("no publica fuera de la maquina")
# cuente como una ORDEN: sin esta guarda, el anti-falso-positivo de DoD(c)
# fallaba sobre texto puramente local que solo MENCIONA la accion para
# descartarla. Lookbehind de ancho fijo (3 chars), aplicado a la posicion del
# verbo en CADA alternativa.
ACTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "dispatch_externo": re.compile(
        r"(?<!no )\bfan-?out\b[^.\n]{0,80}\b(backends?|proveedores?|modelos?)\s+externos?\b"
        r"|(?<!no )\benv[ií]a[^.\n]{0,80}\b(backends?|proveedores?)\s+externos?\b"
        r"|(?<!no )\bdispatch\s+externo\b"
        r"|(?<!no )\bpublica(r|ci[oó]n)?\b[^.\n]{0,40}\bfuera de la m[aá]quina\b",
        re.IGNORECASE,
    ),
    "push": re.compile(
        r"(?<!no )\bgit\s+push\b"
        r"|(?<!no )\bhaz(te)?\s+push\b"
        r"|(?<!no )\bpush(ea)?\s+(a|hacia)\s+(origin|el\s+remoto)\b",
        re.IGNORECASE,
    ),
    "borrado_irreversible": re.compile(
        r"(?<!no )\brm\s+-rf\b"
        r"|(?<!no )\bborrado\s+irreversible\b"
        r"|(?<!no )\bgit\s+push\s+--force\b"
        r"|(?<!no )\belimina(r)?\s+permanentemente\b",
        re.IGNORECASE,
    ),
    "gasto_desproporcionado": re.compile(
        r"(?<!no )\blee(r)?\s+[\d][\d.,]{2,}\s+l[ií]neas\b"
        r"|(?<!no )\blee(r)?\s+(todo|entero|completo)\b[^.\n]{0,40}\bcontratos?\b",
        re.IGNORECASE,
    ),
}

# Declaracion POSITIVA de quien autoriza. "sin autorizacion" no matchea: no
# lleva ":", ni "por <alguien>", ni "de <alguien>" en esa forma.
_CONSENT_CLAUSE_RE = re.compile(
    r"\bautorizaci[oó]n\s*:\s*\S+"
    r"|\bautoriza\s*:\s*\S+"
    r"|\bautorizado\s+por\s+\S+"
    r"|\bcon\s+autorizaci[oó]n\s+(expl[ií]cita\s+)?de\s+\S+"
    r"|\bquien\s+autoriza\s*:\s*\S+",
    re.IGNORECASE,
)


def detect_unauthorized_actions(text: str) -> dict[str, str]:
    """Categorias de accion que `text` ORDENA sin declarar quien autoriza.

    Devuelve un mapa categoria -> fragmento que disparo el patron. Vacio si no
    se ordena ninguna de las 4 categorias, o si se declara autorizacion en
    cualquier lugar del texto (cobertura global, no por-accion -- misma
    simplicidad que `check_contract_clause_coverage.check_clause_coverage`).
    """
    if _CONSENT_CLAUSE_RE.search(text):
        return {}
    found: dict[str, str] = {}
    for category, pattern in ACTION_PATTERNS.items():
        match = pattern.search(text)
        if match:
            found[category] = match.group(0).strip()
    return found


def check_action_consent(text: str) -> list[str]:
    """Lista de violaciones (vacia == conforme): una por categoria sin autorizar."""
    actions = detect_unauthorized_actions(text)
    return [
        f"{category}: ordena la accion sin declarar quien autoriza "
        f"(coincide con {snippet!r})"
        for category, snippet in actions.items()
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Verifica que un artefacto que ORDENA acciones de alto impacto "
            "(dispatch externo, push, borrado irreversible, gasto "
            "desproporcionado) declare quien las autoriza (WOT-2026-043n)."
        )
    )
    ap.add_argument("--artifact", required=True, help="ruta del artefacto auditado")
    args = ap.parse_args(argv)

    artifact_path = Path(args.artifact)
    if not artifact_path.is_file():
        print(
            f"[action-consent] ERROR: artefacto no encontrado: {artifact_path}",
            file=sys.stderr,
        )
        return 2

    text = artifact_path.read_text(encoding="utf-8", errors="replace")
    errors = check_action_consent(text)

    if errors:
        print(
            f"[action-consent] BLOQUEA: {artifact_path.name} ordena "
            f"{len(errors)} accion(es) de alto impacto sin declarar quien "
            "autoriza:",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print(
            "\n  Un artefacto que ordena publicar fuera de la maquina, hacer push,\n"
            "  borrar de forma irreversible o leer un volumen desproporcionado es\n"
            "  PERFECTAMENTE COHERENTE con su propio contrato -- una lente de\n"
            "  conformidad no puede verlo (WOT-2026-043n, medido 2026-07-29).\n"
            "  Declara quien autoriza (campo 'Autorizacion:' o 'autorizado por\n"
            "  <quien>') antes de enviar este artefacto.",
            file=sys.stderr,
        )
        return 1

    print(
        f"[action-consent] OK: {artifact_path.name} no ordena ninguna "
        "accion de alto impacto sin autorizacion declarada."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
