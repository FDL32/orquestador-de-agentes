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

# H8 (WOT-2026-039c): la NEGACION invertia el filtro. "Confirmado: no hay bug"
# matchea el marcador 'bug' y salia clasificado como objecion, que es lo
# contrario de lo que dice. Allowlist mecanica de negadores, acotada y
# declarada: si un marcador va precedido por uno de estos EN LA MISMA ORACION,
# no cuenta como objecion. Perseguir mas formas es parsing linguistico y es
# NON-GOAL declarado del ticket.
_NEGATORS = ("no", "sin", "ningun", "ninguna", "without")

# Segmentacion mecanica de oracion: corte en .;: y salto de linea. Definicion
# cerrada en el contrato (O6) para que "misma clausula" no sea interpretable.
_SENTENCE_SPLIT = re.compile(r"[.;:\n]")

# El negador 'sin' colisiona con el marcador 'sin embargo': ahi 'sin' NO niega,
# forma parte del propio marcador. Caso borde declarado en el contrato.
_NEGATOR_FALSE_FRIENDS = ("sin embargo",)

# Distancia maxima (caracteres) entre el fin de un negador y el inicio del
# marcador para considerarlo negado. Cubre "no hay bug", "no es incorrecto",
# "sin ningun bug"; NO cubre un marcador separado por media oracion, que casi
# siempre pertenece a otra clausula y NO esta negado.
#
# DE DONDE SALE EL 12 (barrido MEDIDO en el cierre 2026-07-22, sobre la suite
# real de este fichero -- no sobre fixtures ad-hoc):
#   W=4 -> 4 failed | W=6 -> 2 | W=8 -> 2 | W=10 -> 1 | W>=12 -> 26 passed
# 12 es el BORDE INFERIOR de una meseta ABIERTA: cualquier valor >=12 es
# indistinguible por los fixtures actuales. No es magia (hay un minimo real),
# pero tampoco un optimo: la COTA SUPERIOR no esta pinneada, asi que subirlo a
# 30 ampliaria la supresion sin que ningun test caiga. Fichado en F5 del cierre.
#
# FALSO POSITIVO INVERSO (medido, direccion que el residuo NO declaraba):
# "No parece haber bug" y "No creo que exista un bug" -> 'objection', porque la
# distancia negador-marcador (14 y 17) excede la ventana. Son NEGACIONES. Con la
# version anterior (resto-de-oracion) salian 'neutral'. La ventana no solo
# reduce el falso positivo original: MUEVE otro de sitio. Coste asimetrico y por
# eso se acepta: este lado gasta trabajo del brazo caro, el original PERDIA
# aportacion legitima. Ampliado en WOT-2026-039e (F4).
#
# RESIDUO DECLARADO (WOT-2026-039e, con tasa medida): la ventana es una
# heuristica de ADYACENCIA, no de alcance sintactico. Un negador que gobierna
# otro sujeto pero queda a menos de N caracteres de un marcador legitimo sigue
# suprimiendolo -- p.ej. "El guard no muerde, contradice el docstring". Cerrar
# ese resto exige analisis sintactico, que la STOP condition del contrato
# PROHIBE explicitamente ("si cerrar H8 exige parsing linguistico mas alla de
# la allowlist declarada -> PARAR y declarar el residuo como NON-GOAL con
# ticket"). Medicion del brazo lector-FS sobre 429 .md del corpus real:
# 5684 oraciones con marcador, 194 suprimidas = 3.4% ANTES de la ventana. La
# ventana reduce ese residuo (4 de los 6 casos medidos pasan a clasificar
# bien); el resto queda fichado, no escondido. Mitigante: la salida descartada
# se APPENDEA con discarded_reason, asi que es auditable y recuperable, nunca
# se pierde.
_NEGATION_WINDOW = 12

# Schema lens-answer/v1: bloque ```cite con path/line/quote. NO admite
# command/exit_code -- un receipt de EJECUCION emitido por una lente sin
# filesystem es fabricacion estructural (H9 cerrado por construccion en esta
# ruta: el call-site del ensemble es CITE-ONLY).
_RECEIPT_PRESENT_RE = re.compile(r"```receipt\s*\n", re.DOTALL)
_CITE_FENCE_RE = re.compile(r"```cite\s*\n(.*?)```", re.DOTALL)
_CITE_PATH_RE = re.compile(r"^path:\s*(.+)$", re.MULTILINE)
_CITE_LINE_RE = re.compile(r"^line:\s*(.+)$", re.MULTILINE)
_CITE_QUOTE_RE = re.compile(r"^quote:\s*(.+)$", re.MULTILINE)

# Longitud minima de `quote`. Un quote de 1-2 caracteres casaria con cualquier
# linea y convertiria la verificacion en un sello de goma (hueco cazado por
# Codex en el CF-audit).
_MIN_QUOTE_LEN = 8


def _strip_negated_markers(text: str) -> str:
    """Elimina los marcadores de objecion NEGADOS por un negador ADYACENTE.

    Before: `text` es la salida cruda de una lente.
    During: segmenta por oracion (corte mecanico en `.;:` y salto de linea) y
        suprime un marcador SOLO si un negador lo precede dentro de una
        VENTANA CORTA (`_NEGATION_WINDOW` caracteres). El negador 'sin' se
        ignora cuando forma parte de 'sin embargo' (que ES marcador, no
        negacion).
    After: retorna el texto con esos marcadores suprimidos, para que
        `_OBJECTION_MARKERS.search` sobre el resultado no los cuente.

    POR QUE VENTANA Y NO "RESTO DE LA ORACION" (falso positivo MEDIDO
    2026-07-22, antes de cerrar el ticket): suprimir todo lo que sigue al
    primer negador desclasificaba OBJECIONES LEGITIMAS en las que el negador
    niega OTRA cosa -- "No valida el encoding, por eso el modulo falla"
    (el negador niega 'valida', el marcador 'falla' NO esta negado) salia
    'neutral' y se descartaba. Un filtro que descarta trabajo bueno ensena al
    operador a apagarlo, y un filtro apagado no es barrera. La ventana es
    mecanica y declarada: lo que quede fuera de ella es NON-GOAL, no deuda
    oculta.
    """
    kept: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text):
        lowered = sentence.lower()
        for friend in _NEGATOR_FALSE_FRIENDS:
            lowered = lowered.replace(friend, " " * len(friend))
        negator_spans = [
            m.end()
            for negator in _NEGATORS
            for m in re.finditer(rf"\b{negator}\b", lowered)
        ]
        if not negator_spans:
            kept.append(sentence)
            continue

        def _suppress(match: re.Match, ends=negator_spans) -> str:
            near = any(0 <= match.start() - end <= _NEGATION_WINDOW for end in ends)
            return " " if near else match.group(0)

        kept.append(_OBJECTION_MARKERS.sub(_suppress, sentence))
    return "\n".join(kept)


def classify_verdict(text: str) -> str:
    """Clasifica la FORMA del veredicto: 'objection' | 'confirmation' | 'neutral'.

    Before: `text` es la salida cruda de una lente.
    During: (1) suprime los marcadores NEGADOS (H8: 'no hay bug' no es una
        objecion sobre un bug); (2) si queda algun marcador de objecion, es
        objecion -- una objecion precedida de cortesia sigue siendo objecion;
        (3) si no y el texto ABRE confirmando, es confirmacion; (4) si no es
        ninguna de las dos, es 'neutral'.
    After: retorna la etiqueta. El estado 'neutral' cierra H7: antes el
        default era 'objection', asi que RUIDO sin marcador ninguno se
        contaba como aportacion (fail-open del clasificador de forma). NO
        juzga si la objecion es BUENA (non-goal).
    """
    if _OBJECTION_MARKERS.search(_strip_negated_markers(text)):
        return "objection"
    if _CONFIRMATION_OPENERS.search(text):
        return "confirmation"
    return "neutral"


def validate_lens_cites(text: str, root: Path) -> tuple[bool, list[str]]:
    """Verifica los bloques ```cite del schema lens-answer/v1.

    Before: `text` es la salida cruda de una lente sin filesystem; `root` es
        el arbol contra el que se verifican las citas.
    During: por cada bloque ```cite exige `path:` relativo dentro de root y
        resoluble, `line:` entero existente en el fichero, y `quote:` de al
        menos `_MIN_QUOTE_LEN` caracteres que APAREZCA en esa linea. Todo
        read-only: abrir, leer, comparar substring. No ejecuta NADA (un
        `command:` en la salida de una lente se ignora como prosa).
    After: retorna `(ok, problems)`. `ok=False` con `problems` citables si no
        hay bloque cite ('missing_cite_block') o si alguna cita no verifica.
    """
    blocks = _CITE_FENCE_RE.findall(text)
    if not blocks:
        return False, ["missing_cite_block (schema lens-answer/v1 exige ```cite)"]

    problems: list[str] = []
    for block in blocks:
        problem = _validate_one_cite(block, root)
        if problem:
            problems.append(problem)
    return (not problems), problems


def _resolve_cited_path(rel: str, root: Path) -> tuple[Path | None, str | None]:
    """Resuelve una ruta citada dentro de `root`, o devuelve el problema.

    Una ruta absoluta o con `..` podria .exists() FUERA del repo y dar un
    falso verde de wrong-root: se rechaza antes de tocar disco.
    """
    cand = Path(rel)
    if cand.is_absolute():
        return None, f"cited path is absolute (must be relative): {rel}"
    try:
        resolved = (root / cand).resolve()
        root_r = root.resolve()
        inside = resolved == root_r or root_r in resolved.parents
    except (OSError, ValueError):
        inside = False
    if not inside:
        return None, f"cited path escapes root: {rel}"
    if not resolved.is_file():
        return None, f"cited path does not resolve: {rel}"
    return resolved, None


def _validate_one_cite(block: str, root: Path) -> str | None:
    """Valida UN bloque cite. Retorna el problema, o None si verifica."""
    path_m = _CITE_PATH_RE.search(block)
    line_m = _CITE_LINE_RE.search(block)
    quote_m = _CITE_QUOTE_RE.search(block)
    if not (path_m and line_m and quote_m):
        return "cite block incompleto: exige path:, line: y quote:"

    rel = path_m.group(1).strip()
    resolved, problem = _resolve_cited_path(rel, root)
    if problem:
        return problem

    try:
        lineno = int(line_m.group(1).strip())
    except ValueError:
        return f"line is not an integer: {line_m.group(1).strip()!r}"

    quote = quote_m.group(1).strip()
    if len(quote) < _MIN_QUOTE_LEN:
        return (
            f"quote too short ({len(quote)} < {_MIN_QUOTE_LEN} chars): "
            "casaria con cualquier linea"
        )

    lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
    if not (1 <= lineno <= len(lines)):
        return f"line {lineno} out of range in {rel} ({len(lines)} lines)"
    if quote not in lines[lineno - 1]:
        return (
            f"quote not found at {rel}:{lineno} (cita fabricada: la linea "
            "existe pero no dice lo que la lente afirma)"
        )
    return None


def filter_lens_output(
    text: str, root: Path, *, cite_only: bool = False
) -> tuple[bool, str, list[str]]:
    """Decide si la salida de una lente se acepta como APORTACION.

    Before: `text` es la salida cruda; `root` es el arbol contra el que se
        verifican las citas (el repo que la lente decia revisar).
        `cite_only=True` fuerza el schema lens-answer/v1 (bloque ```cite) e
        IGNORA cualquier bloque ```receipt como prosa: es el modo del
        call-site del ensemble, donde el emisor es una lente SIN filesystem y
        un receipt de ejecucion solo puede ser fabricado (H9). El default
        `False` conserva la conducta heredada del CLI standalone: receipt si
        existe, cite si no (brazos CON filesystem que si ejecutan).
    During: (1) verifica las CITAS -- fabricada (path que no resuelve, escapa
        del root, o quote que no esta en la linea) descarta la salida;
        (2) clasifica la FORMA del veredicto. Ambos mecanismos son
        INDEPENDIENTES: quitar uno no enmascara al otro (DoD (d)).
    After: retorna `(accepted, reason, problems)`. `reason` en
        {'accepted', 'fabricated_citation', 'confirmation_no_objection',
        'no_contribution'}.
    """
    if cite_only or not _RECEIPT_PRESENT_RE.search(text):
        ok, problems = validate_lens_cites(text, root)
        if not ok:
            missing = any(p.startswith("missing_cite_block") for p in problems)
            return (
                False,
                ("no_contribution" if missing else "fabricated_citation"),
                (problems),
            )
    else:
        validate_receipt = _load_receipt_validator()
        ok, problems = validate_receipt(text, root)
        if not ok:
            return False, "fabricated_citation", problems

    verdict = classify_verdict(text)
    if verdict == "confirmation":
        return False, "confirmation_no_objection", []
    if verdict == "neutral":
        # H7: sin marcador de objecion NI apertura de confirmacion, la salida
        # es RUIDO. Antes caia en el default 'objection' y se contaba como
        # aportacion: fail-open del clasificador de forma.
        return False, "no_contribution", ["veredicto neutro: no aporta objecion"]

    return True, "accepted", []


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
