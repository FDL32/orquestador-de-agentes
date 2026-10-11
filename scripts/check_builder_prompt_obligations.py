#!/usr/bin/env python3
r"""Guard: un prompt de Builder derivado no puede omitir los verbos de cierre de su canonico.

EL FALLO QUE CIERRA (WOT-2026-067z, medido 2026-10-11)
------------------------------------------------------
El canonico `prompts/orchestrator_launch_builder.md` declara el handoff como la
UNICA salida valida del Builder ("El handoff solo existe cuando `--mark-ready`
completa con exito y deja evidencia canonica de `BUILDER_EXIT` + `STATE_CHANGED`
hacia `READY_FOR_REVIEW`") y declara `HANDOFF_IMPOSSIBLE` como codigo de parada
del cierre. Los prompts derivados (redactados por el Manager para un ticket
concreto) declaran `contract_id: cid-bui-implement-v1` pero pueden omitir esos
verbos: el Builder ejecuta un contrato incompleto y nadie avisa. Deuda medida
sobre el corpus del destino (2026-10-11, este guard): 25 prompts declaran el cid
y ~20 omiten al menos un verbo de cierre; 4 omiten `--mark-ready` por completo y
el prompt `arranque_20260905_vuelo_p0.md` lo menciona SOLO en contexto negativo.

DERIVACION DE LA LISTA (no curada a mano) Y EFECTO DE UN CAMBIO DEL CANONICO
----------------------------------------------------------------------------
La lista de verbos se DERIVA del canonico en cada ejecucion desde DOS anclajes
estructurales, ambos lexicos:

1. La frase "handoff solo existe cuando" del bloque "Contrato de handoff
   canonico": TODOS sus tokens backticked (unidos las lineas envueltas hasta el
   punto final) son las condiciones de existencia del handoff. En el canonico
   vigente produce `--mark-ready`, `BUILDER_EXIT`, `STATE_CHANGED`,
   `READY_FOR_REVIEW`.
2. La tabla "## Referencia rapida: codigos de parada": los codigos cuya columna
   de SECCION menciona "handoff" (subcadena, lexico; no semantica) son los
   codigos de fallo del cierre. En el canonico vigente produce
   `HANDOFF_IMPOSSIBLE`.

EFECTO DECLARADO DE UN CAMBIO DEL CANONICO: si el canonico anade, mueve o
reescribe codigos, la lista sigue al texto automaticamente (re-deriva en cada
ejecucion). Si el canonico reescribe cualquiera de los DOS anclajes (la frase de
existencia o la tabla de codigos), la derivacion FALLA CERRADA con exit 3
(familia CONTRACT_GAP): NUNCA se prosigue con una lista parcial o vacia, porque
una lista vacia dejaria pasar TODO el universo. Un cambio legitimo del canonico
se absorbe actualizando los anclajes de este guard con su ticket; uno que no lo
sea, se ficha como CG.

CONTROL CONTRARIO (implementado, NO degradado a omision total)
--------------------------------------------------------------
Una mencion del verbo NO transporta la obligacion cuando su contexto es:
- NEGACION: un disparador (`no`, `nunca`, `jamas`, `sin`, `ni`, `prohibido/a/s`)
  aparece a <= 2 tokens del verbo dentro de la misma clausula (particion por
  `; : . !`). "NO fabricar `BUILDER_EXIT`" no transporta. Caso real medido:
  `arranque_20260905_vuelo_p0.md` menciona `--mark-ready` solo bajo negacion.
- DATO: celdas NO-primeras de una fila pipe (bus logs copiados como evidencia,
  descripcion del disparador en la tabla de codigos). El codigo como VALOR no
  es la orden; el codigo en la PRIMERA celda (la columna del propio codigo)
  SI transporta, que es como `builder_prompt_WOT-2026-072b.md` transporta
  `HANDOFF_IMPOSSIBLE` copiando la tabla de codigos.
El verbo cuenta como transportado solo con al menos una mencion "pos" (las
demas clases no lo salvan; "solo negacion" y "solo dato" son hallazgo).

LIMITACION DECLARADA (precision, no cobertura): la clasificacion es lexica de
linea; una mencion partida entre dos lineas no se ve, y una instruccion
portadora escrita SOLO dentro del cuerpo de una fila pipe se reportaria ausente.
Distinguir sujeto no-humano o intencion exige analisis semantico (STOP de
degeneracion, mismo criterio que el FP declarado del hermano
`check_launch_prompt_paths.py`). Calibrado sobre el corpus real 2026-10-11: los
3 prompts bien formados del denominador auditado (`062e`, `070v`, `071a`) quedan
VERDES; los 2 bundles de verificacion del arranque quedan fuera del denominador
por contener `{{...}}` citado del canonico (en la calibracion previa, sin ese
filtro, tambien salieron verdes). 0 falsos positivos medidos.

PUNTO DE ENGANCHE (con degradacion DECLARADA del camino redaccion->lanzamiento)
-------------------------------------------------------------------------------
NO existe hoy un hook ejecutable ENTRE la redaccion del prompt (el Manager
escribe `<destino>/.agent/planning/staged/WOT-*/PROMPT_BUILDER_*.md`) y el
lanzamiento del Builder: el procedimiento de lanzamiento
(`prompts/orchestrator_prepare_and_launch_ticket.md`) es prosa, no mecanismo.
Por eso este guard se degrada, y se DECLARA, a detective en DOS puntos que si
existen:
1. TEMPRANO (manual, el que pide el DoD): el redactor ejecuta este CLI justo
   tras escribir el prompt y ANTES de lanzar al Builder. Un comando:
   `python scripts/check_builder_prompt_obligations.py --project-root <destino>`.
2. CIERRE (cableado): `scripts/prepush_check.py` lo invoca contra el destino en
   cada closeout (mismo punto que el hermano `check_launch_prompt_paths.py`);
   ahi nace WARN (is_blocking=False) porque la deuda historica del corpus ya
   existe (medida arriba) y bloquear el cierre con ella seria falso-rojo
   heredado. Criterio de endurecimiento a bloqueante: censo del universo vivo
   (los prompts staged de vuelos activos) en 0 hallazgos.
La degradacion es honesta: ni (1) ni (2) corren automaticamente entre la
redaccion y el lanzamiento; el DoD lo exige declarado y aqui queda declarado.

UNIVERSO (denominador, publicado SIEMPRE tambien en fallo)
----------------------------------------------------------
`<project_root>/.agent/planning/**/*.md` (rglob, sin `_archive`), cuyo contenido
declara el contract_id como linea propia (mismo discriminante por CONTENIDO que
el hermano; los prompts del vuelo viven hoy en `staged/WOT-*/` y en la raiz de
planning). Los ficheros con placeholders `{{...}}` son plantillas, no prompts
instanciados, y quedan fuera del denominador. Universo vacio = exit 1
(fail-closed), nunca un verde vacuo.

Exit codes (veredicto documentado, no "medicion fallida"; M1):
    0 = todos los prompts transportan todos los verbos derivados.
    1 = hallazgos de verbo ausente, prompt ilegible, o universo vacio.
    2 = canonico ilegible o inexistente.
    3 = derivacion imposible (anclaje ausente en el canonico) -> CONTRACT_GAP.

Before: `project_root` es una raiz de destino resoluble; el canonico existe
    (por defecto `<motor>/prompts/orchestrator_launch_builder.md` relativo a
    este fichero; overridable con `--canonical`).
During: deriva los verbos del canonico (fail-closed si falta un anclaje), lee
    los prompts del universo (read-only) y clasifica cada mencion de cada
    verbo (portadora / negacion / dato). Nunca muta nada.
After: imprime el denominador y los hallazgos; devuelve el exit code del
    contrato de arriba. Los errores de lectura de un prompt declarado son
    hallazgo propio (V0-ilegible), no se tragan.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Identificacion del universo: por CONTENIDO, no por nombre (el nombre fue el
# vector del fallo del hermano WOT-2026-067w: un tercer patron evade igual).
# El contrato de este guard acota el universo a los prompts que DECLARAN el
# contract_id del Builder como linea propia (no una mencion en prosa).
# ---------------------------------------------------------------------------
BUILDER_CONTRACT_DECL_RE = re.compile(
    r"^[ \t>*-]*`?contract_id`?\s*:\s*`?cid-bui-implement-v1`?\s*$",
    re.MULTILINE,
)

# Una plantilla sin instanciar no es un prompt de arranque (mismo criterio del
# hermano: las plantillas del motor DEBEN llevar `{{...}}` y no se auditan).
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")

# ---------------------------------------------------------------------------
# Anclajes de derivacion en el canonico (efecto de un cambio: ver docstring).
# ---------------------------------------------------------------------------
HANDOFF_EXISTENCE_ANCHOR = "handoff solo existe cuando"
STOP_CODES_HEADING = "## Referencia rapida: codigos de parada"
STOP_CODE_ROW_RE = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|([^|]+)\|")
HANDOFF_SECTION_HINT = "handoff"
MAX_SENTENCE_LINES = 5
BACKTICK_TOKEN_RE = re.compile(r"`([^`\n]+)`")

# ---------------------------------------------------------------------------
# Clasificacion de menciones (CONTROL CONTRARIO).
# ---------------------------------------------------------------------------
# Disparador como TOKEN completo (no subcadena: "nosotros" no es negacion).
NEGATION_TOKEN_RE = re.compile(
    r"^\W*(?:no|nunca|jamas|sin|ni|prohibid[oa]s?)\W*$",
    re.IGNORECASE,
)
# Un disparador seguido de uno de estos marcadores no niega al verbo
# ("sin embargo, ejecuta X"; "no solo X, tambien Y").
NEGATION_DISCOURSE_MARKERS = ("embargo", "solo", "obstante")
# Clausulas: el alcance de la negacion no cruza estos separadores.
CLAUSE_SPLIT_RE = re.compile(r"[;:.!]")
# El disparador debe quedar a <= NEGATION_WINDOW_TOKENS - 1 tokens del verbo.
NEGATION_WINDOW_TOKENS = 3

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_CANONICAL_UNREADABLE = 2
EXIT_DERIVATION_FAILED = 3

UNIVERSE_SUBDIR = (".agent", "planning")
SKIP_DIR_PARTS = {"_archive", "__pycache__", ".git", ".venv", "node_modules"}


class DerivationError(Exception):
    """El canonico ya no expone un anclaje derivable; fail-closed, nunca lista vacia."""


@dataclass(frozen=True)
class Finding:
    """Un hallazgo con su fichero, linea y motivo: sin esos tres no es accionable."""

    path: Path
    lineno: int
    rule: str
    line: str

    def render(self) -> str:
        return f"{self.path.name}:{self.lineno} [{self.rule}] {self.line.strip()[:110]}"


def _read(path: Path) -> str | None:
    """Lectura tolerante: None en OSError (el llamador lo reporta, no lo calla)."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Derivacion de la lista de verbos desde el canonico
# ---------------------------------------------------------------------------
def derive_closure_verbs(canonical_text: str) -> tuple[list[str], list[str]]:
    """Deriva (verbos de comando/evento, codigos de parada) del texto del canonico.

    Before: `canonical_text` es el contenido ENTERO del prompt canonico.
    During: anclaje 1 -- localiza la frase "handoff solo existe cuando" y une
        las lineas envueltas hasta el punto final; extrae TODOS sus tokens
        backticked. Anclaje 2 -- localiza la tabla de codigos de parada y
        selecciona los codigos cuya columna de SECCION menciona "handoff".
    After: (comandos_eventos, codigos_parada), ambos NO vacios; lanza
        `DerivationError` si un anclaje falta o no produce verbos (fail-closed:
        una derivacion vacia dejaria pasar todo el universo). Ordena sin
        duplicados preservando el orden de aparicion.
    """
    lines = canonical_text.splitlines()

    anchor = next(
        (i for i, line in enumerate(lines) if HANDOFF_EXISTENCE_ANCHOR in line),
        None,
    )
    if anchor is None:
        raise DerivationError(
            "anclaje 1 ausente: el canonico ya no contiene la frase "
            f"{HANDOFF_EXISTENCE_ANCHOR!r}; actualiza los anclajes de este guard "
            "con su ticket o ficha CG (nunca prosigas con una lista vacia)"
        )
    sentence = lines[anchor].strip().lstrip("-*").strip()
    j = anchor
    while (
        not sentence.endswith(".")
        and j + 1 < len(lines)
        and j - anchor < MAX_SENTENCE_LINES
    ):
        j += 1
        sentence += " " + lines[j].strip()
    commands = BACKTICK_TOKEN_RE.findall(sentence)
    if not commands or not any(token.startswith("--") for token in commands):
        raise DerivationError(
            "anclaje 1 degradado: la frase de existencia del handoff ya no "
            f"expone un comando backticked; frase reconstruida: {sentence!r}"
        )

    head = next(
        (
            i
            for i, line in enumerate(lines)
            if line.strip().startswith(STOP_CODES_HEADING)
        ),
        None,
    )
    if head is None:
        raise DerivationError(
            "anclaje 2 ausente: el canonico ya no contiene el encabezado "
            f"{STOP_CODES_HEADING!r}; actualiza los anclajes de este guard con "
            "su ticket o ficha CG"
        )
    stop_codes: list[str] = []
    for line in lines[head + 1 : head + 40]:
        if line.strip().startswith("## "):
            break
        row = STOP_CODE_ROW_RE.match(line)
        if (
            row
            and HANDOFF_SECTION_HINT in row.group(2).lower()
            and row.group(1) not in stop_codes
        ):
            stop_codes.append(row.group(1))
    if not stop_codes:
        raise DerivationError(
            "anclaje 2 degradado: ningun codigo de parada declara seccion "
            f"con la pista {HANDOFF_SECTION_HINT!r}; el verbo de fallo del "
            "cierre quedaria sin derivar"
        )
    return commands, stop_codes


def derive_verbs_from_file(canonical_path: Path) -> tuple[list[str], list[str]]:
    """Lee el canonico y deriva sus verbos; OSError se propaga al llamador.

    Before: `canonical_path` apunta al prompt canonico del motor.
    During: lee el fichero (UTF-8) y llama a `derive_closure_verbs`.
    After: el par de listas derivadas; `OSError`/`UnicodeDecodeError` suben sin
        capturar (main las clasifica como exit 2) y `DerivationError` tambien
        sube (main la clasifica como exit 3).
    """
    return derive_closure_verbs(canonical_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Clasificacion de menciones (CONTROL CONTRARIO)
# ---------------------------------------------------------------------------
def _pipe_first_cell_span(line: str) -> tuple[int, int] | None:
    """Devuelve el span (inicio, fin) de la PRIMERA celda de una fila pipe.

    Before: `line` es una linea del prompt.
    During: si la linea (sin espacios iniciales) empieza por `|`, localiza el
        cierre de la primera celda.
    After: el span absoluto en `line`, o None si no es fila pipe.
    """
    stripped = line.lstrip()
    if not stripped.startswith("|"):
        return None
    base = len(line) - len(stripped)
    end = stripped.find("|", 1)
    if end == -1:
        end = len(stripped)
    return (base + 1, base + end)


def _is_negated(tokens_before: list[str]) -> bool:
    """True si un disparador de negacion gobierna al verbo en esta clausula.

    Before: `tokens_before` son los tokens (whitespace) ANTERIORES al verbo
        dentro de su clausula, en orden.
    During: mira los ultimos `NEGATION_WINDOW_TOKENS` tokens; un token
        disparador niega, salvo que el token siguiente sea un marcador
        discursivo ("sin embargo", "no solo").
    After: True solo con negacion real; prosa descriptiva devuelve False.
    """
    window = tokens_before[-NEGATION_WINDOW_TOKENS:]
    for k, token in enumerate(window):
        if not NEGATION_TOKEN_RE.match(token):
            continue
        nxt = window[k + 1].lower() if k + 1 < len(window) else ""
        if any(marker in nxt for marker in NEGATION_DISCOURSE_MARKERS):
            continue
        return True
    return False


def mention_contexts(line: str, verb: str) -> set[str]:
    """Clasifica las menciones de `verb` en la linea: {'pos','neg','data'}.

    Before: `line` es una linea que contiene `verb` al menos una vez.
    During: por cada ocurrencia -- (1) si la linea es fila pipe y la ocurrencia
        cae fuera de la PRIMERA celda, es 'data' (el codigo como valor: bus log
        copiado, descripcion del disparador); (2) si no, recorta la clausula
        (particion por `; : . !`), toma los tokens anteriores a la ocurrencia
        y aplica `_is_negated` ('neg'); el resto es 'pos'.
    After: el conjunto de clases observadas; nunca vacio si el verbo aparece.
        Lexico puro, sin analisis de sujeto (limitacion declarada en el
        docstring del modulo).
    """
    contexts: set[str] = set()
    first_cell = _pipe_first_cell_span(line)
    for occurrence in re.finditer(re.escape(verb), line):
        if first_cell and not (first_cell[0] <= occurrence.start() < first_cell[1]):
            contexts.add("data")
            continue
        clause_start = max(
            (m.end() for m in CLAUSE_SPLIT_RE.finditer(line, 0, occurrence.start())),
            default=0,
        )
        before = line[clause_start : occurrence.start()]
        # Los tokens sin ningun caracter de palabra (la comilla invertida de
        # apertura, la barra de la tabla) no son prosa: contarlos desplazaria
        # al disparador fuera de la ventana por un artefacto de markup.
        tokens = [
            t.group()
            for t in re.finditer(r"\S+", before)
            if re.search(r"\w", t.group())
        ]
        contexts.add("neg" if _is_negated(tokens) else "pos")
    return contexts


# ---------------------------------------------------------------------------
# Auditoria del universo
# ---------------------------------------------------------------------------
def scan_prompt(path: Path, verbs: list[str]) -> list[Finding]:
    """Aplica la regla V1 a un prompt: cada verbo derivado debe transportarse.

    Before: `path` es un prompt que declara el contract_id del Builder;
        `verbs` es la lista derivada del canonico.
    During: lee el fichero y clasifica TODAS las menciones de cada verbo; un
        verbo esta ausente si ninguna mencion es 'pos'.
    After: hallazgos V1 (uno por verbo ausente, anclado a la linea del
        contract_id) mas V0-ilegible si la lectura fallo; nunca lanza.
    """
    text = _read(path)
    if text is None:
        return [Finding(path, 1, "V0-ilegible", "no se pudo leer")]
    lines = text.splitlines()
    cid_line = next(
        (
            lineno
            for lineno, line in enumerate(lines, 1)
            if BUILDER_CONTRACT_DECL_RE.search(line)
        ),
        1,
    )
    findings: list[Finding] = []
    for verb in verbs:
        contexts: set[str] = set()
        for line in lines:
            if verb in line:
                contexts |= mention_contexts(line, verb)
        if "pos" in contexts:
            continue
        if not contexts:
            detail = "0 menciones"
        else:
            detail = "solo " + " y ".join(sorted(contexts))
        findings.append(
            Finding(path, cid_line, "V1-verbo-cierre-ausente", f"{verb} ({detail})")
        )
    return findings


def audit_prompt_universe(
    project_root: Path, verbs: list[str]
) -> tuple[list[Finding], list[Path]]:
    """Audita el universo de prompts que declaran el contract_id del Builder.

    Before: `project_root` es la raiz del destino; `verbs` la lista derivada.
    During: recorre `<project_root>/.agent/planning/**/*.md` (read-only, sin
        `_archive`), excluye plantillas con `{{...}}` y selecciona los que
        declaran el contract_id como linea propia.
    After: (hallazgos, prompts_auditados); el segundo ES el denominador. Un
        prompt declarado ilegible produce hallazgo V0, nunca se salta en
        silencio.
    """
    planning = project_root.joinpath(*UNIVERSE_SUBDIR)
    findings: list[Finding] = []
    prompts: list[Path] = []
    if not planning.is_dir():
        return findings, prompts
    for path in sorted(planning.rglob("*.md")):
        if any(part in SKIP_DIR_PARTS for part in path.parts):
            continue
        text = _read(path)
        if text is None:
            # Un prompt declarado ilegible ES parte del denominador (se
            # audito, con veredicto V0): excluirlo en silencio seria un
            # denominador podrido.
            findings.append(Finding(path, 1, "V0-ilegible", "no se pudo leer"))
            prompts.append(path)
            continue
        if PLACEHOLDER_RE.search(text):
            continue
        if BUILDER_CONTRACT_DECL_RE.search(text):
            prompts.append(path)
            findings.extend(scan_prompt(path, verbs))
    return findings, prompts


def main(argv: list[str] | None = None) -> int:
    """CLI del guard. Exit codes documentados en el docstring del modulo.

    Before: `argv` estilo sys.argv[1:]; `--project-root` obligatorio.
    During: deriva los verbos del canonico (exit 2 ilegible, exit 3 sin
        anclajes), audita el universo y publica el denominador SIEMPRE,
        tambien en fallo.
    After: 0 sin hallazgos con universo no vacio; 1 con hallazgos o universo
        vacio (fail-closed); los hallazgos van a stdout y el rationale a
        stderr. Nunca muta nada.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Prompts de Builder derivados: transportan los verbos de cierre "
            "que su canonico declara obligatorios (WOT-2026-067z)."
        )
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="raiz del repo_destino cuyo .agent/planning/ se audita",
    )
    parser.add_argument(
        "--canonical",
        default=None,
        help=(
            "ruta del prompt canonico; por defecto "
            "<motor>/prompts/orchestrator_launch_builder.md relativo a este script"
        ),
    )
    args = parser.parse_args(argv)

    canonical = (
        Path(args.canonical)
        if args.canonical
        else Path(__file__).resolve().parent.parent
        / "prompts"
        / "orchestrator_launch_builder.md"
    )
    try:
        commands, stop_codes = derive_verbs_from_file(canonical)
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"[builder-prompt-obligations] ERROR: canonico ilegible: {canonical} ({exc})",
            file=sys.stderr,
        )
        return EXIT_CANONICAL_UNREADABLE
    except DerivationError as exc:
        print(
            "[builder-prompt-obligations] ERROR de derivacion (fail-closed, "
            f"CONTRACT_GAP): {exc}",
            file=sys.stderr,
        )
        return EXIT_DERIVATION_FAILED

    verbs = commands + stop_codes
    project_root = Path(args.project_root).resolve()
    findings, prompts = audit_prompt_universe(project_root, verbs)

    # El denominador y la lista derivada se publican SIEMPRE, incluso en fallo:
    # sin ellos no se distingue "0 hallazgos sobre 25" de "no mire nada".
    print(
        f"[builder-prompt-obligations] {len(prompts)} prompt(s) auditado(s), "
        f"{len(findings)} hallazgo(s), verbos derivados del canonico: "
        f"{', '.join(verbs)}"
    )

    if not prompts:
        print(
            "[builder-prompt-obligations] ERROR: universo VACIO en "
            f"{project_root / '.agent' / 'planning'}. Un exit 0 aqui seria un "
            "verde vacuo (fail-closed).",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    for finding in findings:
        print(f"  - {finding.render()}")
    if findings:
        print(
            "\nUn prompt que declara `contract_id: cid-bui-implement-v1` hereda "
            "las obligaciones de cierre de su canonico. Ejecuta el handoff "
            "canonico (--mark-ready con BUILDER_EXIT + STATE_CHANGED hacia "
            "READY_FOR_REVIEW) o declara el fallo con HANDOFF_IMPOSSIBLE; una "
            "mencion en contexto negativo o como dato no transporta la "
            "obligacion.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
