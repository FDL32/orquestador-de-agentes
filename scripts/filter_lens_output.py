"""Filtro de RUIDO sobre la SALIDA de una lente del ensemble (WOT-2026-027o).

Cierra dos huecos MEDIDOS sobre revisiones REALES (2026-07-21/22), no teoricos:

1. FABRICACION -- 2 de 3 nan produjeron reviews inventadas: una cito el fichero
   `tests/test_transport.py` y un commit que NO EXISTEN; otra la variable
   `mock_subprocess`, que NO esta en el fichero que decia revisar.
2. ANCLAJE -- ante una premisa FALSA, qwen y gemma citaron la LINEA CORRECTA
   que la refuta y aun asi abrieron con "Confirmado". Este es el peligroso:
   NINGUN filtro de "exige fichero:linea" lo detecta, porque el puntero es real.

Hoy el ejecutor acepta ambas salidas tal cual y las cuenta como aportacion.

REUSO, no subsistema nuevo: la verificacion de cita la hace
`check_bundle_receipts.validate_receipt`, que YA rechaza un path que no resuelve
y uno que escapa del root (probe 2026-07-22, exit 0). Este modulo la aplica a la
SALIDA de la lente en vez de al bundle de ENTRADA, y anade la clasificacion
confirmacion-vs-objecion. `check_bundle_receipts.py` NO se modifica: es
superficie prohibida de este grupo.

NON-GOAL (hard-stop declarado): NO se juzga la CALIDAD SEMANTICA de una
objecion -- eso es el brazo fuerte, y derivar ahi es diseno nuevo. Aqui se
clasifica FORMA (confirmacion vs objecion) y se VERIFICAN CITAS.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path


_SCRIPTS_DIR = Path(__file__).resolve().parent


def _load_receipt_validator():
    """Importa `validate_receipt` SIN modificar check_bundle_receipts.py.

    Before: `scripts/check_bundle_receipts.py` existe y define
        `validate_receipt(body, root)`.
    During: carga el modulo por ruta y lo REGISTRA en `sys.modules` antes de
        ejecutarlo -- un `@dataclass` del modulo lo exige (omitirlo fue una de
        las dos causas por las que el probe de diseno fallo dos veces, ninguna
        imputable al script).
    After: retorna la funcion. Lanza ImportError si el modulo no carga: sin
        verificador de citas este filtro NO debe correr en modo degradado
        (fail-closed).
    """
    path = _SCRIPTS_DIR / "check_bundle_receipts.py"
    spec = importlib.util.spec_from_file_location("check_bundle_receipts", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensivo
        raise ImportError(f"no se puede cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_bundle_receipts"] = module
    spec.loader.exec_module(module)
    return module.validate_receipt


# Aperturas de CONFIRMACION. Una lente que confirma no aporta: el ejecutor ya
# tenia esa hipotesis, y una confirmacion sin objecion no cambia ninguna
# decision. Se casa el ARRANQUE del veredicto, no cualquier aparicion, para que
# "confirmado que X esta roto" (una objecion) no se descarte por la palabra.
_CONFIRMATION_OPENERS = re.compile(
    r"^\s*(?:[-*>#\s]*)?"
    r"(confirmado|confirmo|de acuerdo|correcto|coincido|"
    r"la premisa (?:es|parece) correcta|"
    r"confirmed|i agree|agreed|looks good|lgtm)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Marcadores de OBJECION: la lente contradice, corrige o refuta.
_OBJECTION_MARKERS = re.compile(
    r"\b(pero|sin embargo|no obstante|en realidad|incorrecto|erroneo|"
    r"la premisa es falsa|refuta|contradice|falla|bug|riesgo|"
    r"however|actually|incorrect|wrong|disagree|refutes|contradicts)\b",
    re.IGNORECASE,
)


def classify_verdict(text: str) -> str:
    """Clasifica la FORMA del veredicto: 'objection' | 'confirmation'.

    Before: `text` es la salida cruda de una lente.
    During: si hay marcador de objecion en cualquier punto, es objecion (una
        objecion precedida de cortesia sigue siendo objecion). Si NO lo hay y
        el texto ABRE confirmando, es confirmacion.
    After: retorna la etiqueta. NO juzga si la objecion es BUENA (non-goal).
    """
    if _OBJECTION_MARKERS.search(text):
        return "objection"
    if _CONFIRMATION_OPENERS.search(text):
        return "confirmation"
    return "objection"


def filter_lens_output(text: str, root: Path) -> tuple[bool, str, list[str]]:
    """Decide si la salida de una lente se acepta como APORTACION.

    Before: `text` es la salida cruda; `root` es el arbol contra el que se
        verifican las citas (el repo que la lente decia revisar).
    During: (1) verifica las CITAS con `validate_receipt` -- una cita fabricada
        (path que no resuelve, o que escapa del root) descarta la salida;
        (2) clasifica la FORMA del veredicto. Ambos mecanismos son
        INDEPENDIENTES: quitar uno no enmascara al otro (DoD (d)).
    After: retorna `(accepted, reason, problems)`. `accepted=False` con
        `reason` en {'fabricated_citation', 'confirmation_no_objection'}.
    """
    validate_receipt = _load_receipt_validator()
    ok, problems = validate_receipt(text, root)
    if not ok:
        return False, "fabricated_citation", problems

    if classify_verdict(text) == "confirmation":
        return False, "confirmation_no_objection", []

    return True, "objection_with_verified_citation", []


def main(argv: list[str] | None = None) -> int:
    """CLI: filtra un fichero de salida de lente. rc 0 = aportacion aceptada."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lens-output", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        text = args.lens_output.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(f"[lens-filter] ERROR: cannot read {args.lens_output}: {exc}")
        return 2

    accepted, reason, problems = filter_lens_output(text, args.root)
    if args.json:
        print(
            json.dumps(
                {"accepted": accepted, "reason": reason, "problems": problems},
                ensure_ascii=False,
            )
        )
    else:
        verdict = "ACEPTADA" if accepted else "DESCARTADA"
        print(f"[lens-filter] {verdict}: {reason}")
        for problem in problems:
            print(f"[lens-filter]   - {problem}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
