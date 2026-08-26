#!/usr/bin/env python3
"""Genera prompts de EXTRACCION para el pool de lentes (WOT-2026-027q).

CAMBIO DE ROL, no de tamano del pool: las lentes dejan de ADJUDICAR (donde
convergen al mismo sesgo: rho->1, los 4 fallaron el mismo conteo y 2 el mismo
anclaje) y pasan a EXTRAER datos literales, que es donde aciertan.

El mecanismo anti-anclaje es ESTRUCTURAL antes que lexico: este generador NO
acepta un campo de premisa/hipotesis/contexto-de-sospecha. No hay donde
escribir la premisa, y el anclaje opera SOBRE la premisa. Lo lexico es la
segunda linea:

  - GATE DE ENTRADA (antes de generar, sobre el texto de --extract):
    (i) allowlist mecanica de PATRONES PROHIBIDOS -- agregativos (lo que el
        pool falla) y adjudicativos (lo que no le corresponde);
    (ii) `check_prompt_bias` sobre el MISMO texto. Sin (ii) una premisa del
        tipo "confirma que ..." no seria rechazable ANTES de generar, porque
        ese patron vive en CONFIRM_PATTERN y no en la allowlist.
  - GATE DE SALIDA (tras generar): `check_prompt_bias` sobre el prompt
    emitido, fail-closed.

LIMITE DECLARADO (NON-GOAL, no defecto): una premisa declarativa pura sin
verbo de siembra ("el bug esta en X; extrae el valor") atraviesa ambos gates.
Perseguir sinonimos, parafrasis y flexiones es el camino al oraculo semantico
que el repo prohibe explicitamente (WOT-2026-025f). La normalizacion cubre
mayusculas y acentos; nada mas.

Before: `target_file` es una ruta (no se lee: el prompt la NOMBRA, quien la
    lee es la lente o el brazo con FS); `anchor` es una linea o un simbolo;
    `extract` describe QUE dato literal se pide. Sin red, stdlib puro.
During: normaliza y aplica el gate de entrada; si pasa, compone el prompt de
    extraccion con la clausula solo-objeciones de WOT-2026-027o; aplica el
    gate de salida.
After: exit 0 e imprime el prompt por stdout; exit 1 con el patron que
    disparo (self-service) si cualquiera de los dos gates rechaza. NUNCA
    despacha: generar y despachar son fases distintas (el despacho es de
    ensemble_dispatch, superficie de otro ticket).
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import unicodedata
from pathlib import Path


_SCRIPTS_DIR = Path(__file__).resolve().parent


def _load_bias_checker():
    """Importa check_prompt_bias SIN modificarlo (superficie prohibida).

    Se registra en sys.modules antes de ejecutar el modulo, patron ya usado
    por filter_lens_output para el mismo tipo de reuso. Fail-closed: si el
    modulo no carga, este generador NO debe correr en modo degradado (seria
    emitir prompts sin gate).
    """
    path = _SCRIPTS_DIR / "check_prompt_bias.py"
    spec = importlib.util.spec_from_file_location("check_prompt_bias", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensivo
        raise ImportError(f"no se puede cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_prompt_bias"] = module
    spec.loader.exec_module(module)
    return module


# PATRONES PROHIBIDOS (12). No son solo verbos: hay formas compuestas y
# sustantivos. Dos familias, ambas justificadas por medicion, no por gusto:
#   - agregativos: el pool falla sistematicamente lo cuantitativo (conteos
#     medidos 573/548/500/688 frente a 1067 real).
#   - adjudicativos: el veredicto lo emite el brazo con FS o un gate
#     determinista, nunca el pool.
# Limite duro declarado en el contrato: 15 entradas. Crecer mas es sintoma de
# oraculo y obliga a PARAR.
AGGREGATIVE_PATTERNS = (
    "contar",
    "cuantos",
    "cuantas",
    "numero de",
    "total de",
    "porcentaje",
)
ADJUDICATIVE_PATTERNS = (
    "aprueba",
    "rechaza",
    "veredicto",
    "es correcto",
    "esta bien",
    "deberia",
)
FORBIDDEN_PATTERNS = AGGREGATIVE_PATTERNS + ADJUDICATIVE_PATTERNS


def _normalize(text: str) -> str:
    """Casefold + sin diacriticos: 'cuántos' y 'CUANTOS' colapsan al mismo.

    Misma normalizacion que check_prompt_bias, deliberadamente: dos varas
    distintas para el mismo tipo de match serian una incoherencia del gate.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def _looks_like_path(value: str) -> bool:
    """True si `value` tiene forma de PATH de fichero (UN token), no de frase.

    WOT-2026-039h item 4: el gate de ENTRADA aplica la allowlist de patrones
    prohibidos por SUBSTRING. Aplicarla a un `--target-file` cuyo basename
    contiene una palabra prohibida (`scripts/contar_lineas.py` -> 'contar')
    rechaza un path legitimo. Pero el discriminator debe ser ESTRICTO para no
    reabrir la evasion textual: una FRASE con espacios que CONTIENE una ruta
    (`"cuantas funciones hay en scripts/foo.py"`) tambien lleva `/`, asi que
    exigir solo separador/ext areina reabre el hueco que cierra (hallazgo
    confirmado por probe en el MANAGER_REVIEW de 039h). Solucion: un path es UN
    UNICO token SIN espacios; una frase lleva espacios y queda bajo la
    allowlist completa.
    """
    v = value.strip()
    if not v:
        return False
    if any(ch.isspace() for ch in v):
        return False  # una frase con espacios no es un path
    return "/" in v or "\\" in v or bool(re.search(r"\.\w{1,6}$", v))


def reject_reason(extract: str, *, skip_allowlist: bool = False) -> str | None:
    """Razon de rechazo del GATE DE ENTRADA, o None si el texto es admisible.

    Before: `extract` es el texto que el consumidor quiere preguntar.
        `skip_allowlist` (WOT-2026-039h item 4) salta la allowlist de patrones
        prohibidos y conserva SOLO check_prompt_bias: es el modo PATH de
        `--target-file`, donde el basename puede contener una palabra prohibida
        (`contar_lineas.py` -> 'contar') sin ser una pregunta de extraccion.
    During: (i) a menos que `skip_allowlist`, busca cada patron prohibido como
        substring del texto normalizado; (ii) si ninguno dispara, pasa el MISMO
        texto por check_prompt_bias (es lo que caza 'confirma que ...', ausente
        de la allowlist por diseno).
    After: retorna un string citable con el patron que disparo, o None. No
        lanza excepciones para entrada str; TypeError si no es str (via
        check_prompt_bias, fail-closed sobre tipo incorrecto).
    """
    if not skip_allowlist:
        normalized = _normalize(extract)
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in normalized:
                familia = (
                    "agregativo" if pattern in AGGREGATIVE_PATTERNS else "adjudicativo"
                )
                return f"patron-prohibido:{pattern!r} ({familia})"

    bias = _load_bias_checker().check_prompt_bias(extract)
    if bias["sesgado"]:
        return "; ".join(bias["hits"])
    return None


def build_extraction_prompt(
    target_file: str, anchor: str, extract: str, *, flow: bool = False
) -> str:
    """Compone el prompt de extraccion. NO valida (eso es reject_reason).

    Before: los tres argumentos son strings; `flow` pide ademas describir el
        flujo del dato. NO hay parametro de premisa/hipotesis: esa ausencia
        es el mecanismo anti-anclaje del ticket.
    During: compone texto plano, sin leer el fichero ni tocar la red.
    After: retorna el prompt. La instruccion pide EXTRAER literal y aplica la
        clausula solo-objeciones de WOT-2026-027o (una confirmacion es
        no-aportacion); nunca pide aprobar, rechazar ni contar.
    """
    flow_clause = (
        "\n4. Describe el FLUJO de ese dato: de donde viene y a donde va, "
        "citando las lineas que lo muestran."
        if flow
        else ""
    )
    return (
        "TAREA DE EXTRACCION (no de juicio).\n\n"
        f"Fichero: {target_file}\n"
        f"Ancla: {anchor}\n\n"
        f"1. Extrae, literalmente, {extract}.\n"
        "2. Cita el fragmento exacto que lo sostiene con su numero de linea.\n"
        "3. Si el dato no esta donde el ancla indica, di donde SI esta o di "
        "que no lo encuentras. No lo deduzcas.\n"
        f"{flow_clause}\n\n"
        "REGLAS DE SALIDA:\n"
        "- Responde en tabla compacta: | dato | valor literal | linea |.\n"
        "- Una valoracion generica es NO-APORTACION: solo el dato y su cita.\n"
        "- No cuentes, no midas, no valores completitud, no dictamines.\n"
        "- Si algo no es verificable con el fichero delante, marcalo HIPOTESIS."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Genera un prompt de EXTRACCION para el pool de lentes: pide datos "
            "literales, nunca veredictos ni conteos (WOT-2026-027q)."
        )
    )
    parser.add_argument("--target-file", required=True)
    parser.add_argument("--anchor", required=True, help="Linea o simbolo ancla.")
    parser.add_argument("--extract", required=True, help="Que dato literal se pide.")
    parser.add_argument(
        "--flow", action="store_true", help="Pide ademas describir el flujo del dato."
    )
    args = parser.parse_args(argv)

    # GATE DE ENTRADA sobre TODA la superficie de input, no solo --extract.
    # Hallazgo MAJOR del MANAGER_REVIEW (2026-07-22): cubrir solo --extract
    # dejaba --anchor y --target-file como vias de evasion con los patrones
    # LITERALES de la propia allowlist ('cuantas', 'aprueba', 'veredicto'),
    # que check_prompt_bias no conoce y por tanto el gate de salida tampoco
    # cazaba. No son sinonimos ni parafrasis (eso SI es NON-GOAL): es la
    # misma vara mecanica sin aplicar a los otros dos campos.
    #
    # WOT-2026-039h item 4: `--target-file` con FORMA DE PATH no se ofusca con
    # la allowlist por substring -- un path es una RUTA, no una pregunta de
    # extraccion. 'reject_reason' conserva check_prompt_bias en modo path,
    # asi que la evasion textual (frase con espacios) sigue cerrada.
    for field, value in (
        ("--extract", args.extract),
        ("--anchor", args.anchor),
        ("--target-file", args.target_file),
    ):
        skip_allowlist = field == "--target-file" and _looks_like_path(value)
        reason = reject_reason(value, skip_allowlist=skip_allowlist)
        if reason is not None:
            print(
                f"[extraction-prompt] RECHAZADO antes de generar "
                f"({field}): {reason}\n"
                "Reformula como EXTRACCION de un dato literal: 'el valor de "
                "retorno de la linea N', 'el patron regex declarado', 'el "
                "encoding usado al abrir el fichero'.",
                file=sys.stderr,
            )
            return 1

    # WOT-2026-039h item 5: asimetria con --extract (que si valida vacio).
    # Un ancla vacia o un path vacio generan prompts degenerados
    # ('Ancla: ' / 'Fichero: ' sin objeto): mismo gate que --extract.
    empty_fields = [
        field
        for field, value in (
            ("--extract", args.extract),
            ("--anchor", args.anchor),
            ("--target-file", args.target_file),
        )
        if not value.strip()
    ]
    if empty_fields:
        print(
            f"[extraction-prompt] RECHAZADO antes de generar "
            f"({', '.join(empty_fields)}): vacio. Un prompt sin objeto "
            "('Extrae, literalmente, .' / 'Ancla: ' / 'Fichero: ') no es "
            "una pregunta de extraccion.",
            file=sys.stderr,
        )
        return 1

    prompt = build_extraction_prompt(
        args.target_file, args.anchor, args.extract, flow=args.flow
    )

    # GATE DE SALIDA: el propio generador no puede emitir un prompt sesgado.
    bias = _load_bias_checker().check_prompt_bias(prompt)
    if bias["sesgado"]:
        # El gate de entrada ya rechazo lo que venia sesgado en los flags, asi
        # que llegar aqui significa que el sesgo lo introdujo la PLANTILLA:
        # eso si es defecto del generador. No se culpa al consumidor a ciegas
        # (hallazgo MINOR del MANAGER_REVIEW: el mensaje anterior mandaba al
        # usuario por la via equivocada cuando el sesgo era suyo).
        print(
            f"[extraction-prompt] BLOQUEADO: el prompt generado quedo sesgado "
            f"({bias['motivo']}). El gate de entrada no lo detecto en los "
            "flags, asi que el patron proviene de la plantilla: es un defecto "
            "del generador y conviene reportarlo.",
            file=sys.stderr,
        )
        return 1

    print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
