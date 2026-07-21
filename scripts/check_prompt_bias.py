#!/usr/bin/env python3
"""Detector mecanico de sesgo de siembra en prompts de review (WOT-2026-026k).

Before: recibe el TEXTO de un prompt (str) que se enviara a un backend como
    review/auditoria. No requiere red, backend vivo ni LLM: es un analisis
    lexico/heuristico puro sobre el string de entrada.
During: aplica dos familias de patron, ambas mecanicas (allowlist + regex),
    NUNCA un oraculo semantico (NON-GOAL declarado en WOT-2026-025f):
    (1) frases-siembra: subcadenas normalizadas (casefold, sin acentos) que
        preinstalan la conclusion en la pregunta (p.ej. "(correcto)",
        "verdad?", "no hay problema", afirmaciones seguidas de peticion de
        confirmacion). (2) patron confirmar-vs-trazar: preguntas de la forma
        "confirma que <afirmacion>" en vez de "traza <afirmacion>" siembran
        la respuesta aunque no contengan ninguna frase-siembra literal.
After: retorna un dict con `sesgado: bool`, `hits: list[str]` (evidencia
    citable: patron + fragmento) y `motivo: str`. `main()` traduce esto a
    exit code: 1 si sesgado (PROMPT_SESGADO), 0 si limpio. Nunca lanza
    excepciones para entrada valida (str); TypeError si no es str.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata


# Frases-siembra: normalizadas (casefold + sin acentos) antes de comparar,
# asi "verdad?" y "Verdad?" o "correcto" y "Correcto" coinciden igual.
SEED_PHRASES = [
    "(correcto)",
    "verdad?",
    "no hay problema",
    "es correcto,",
    "no crees?",
    "cierto?",
    "esta bien, no?",
    "sin problema alguno",
]

# Patron confirmar-vs-trazar: "confirma que <algo>" siembra la conclusion
# porque pide ratificar una afirmacion en vez de pedir trazar/verificar el
# hecho desde cero. "traza" / "verifica" / "comprueba" no disparan.
CONFIRM_PATTERN = re.compile(r"\bconfirma(?:me)?\s+que\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    """Casefold + remueve diacriticos para comparacion tolerante a acentos."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def check_prompt_bias(prompt_text: str) -> dict:
    """Analiza `prompt_text` y devuelve veredicto mecanico de sesgo.

    Before: `prompt_text` es un str (el prompt completo a enviar). No hay
        precondicion de red ni de backend.
    During: normaliza el texto una vez; recorre `SEED_PHRASES` buscando cada
        frase normalizada como substring; aplica `CONFIRM_PATTERN` sobre el
        texto ORIGINAL (case-insensitive nativo del regex, no requiere la
        normalizacion de acentos). Cada hit se acumula con su patron y un
        fragmento de contexto (evidencia citable, no solo un booleano).
    After: retorna `{"sesgado": bool, "hits": [str, ...], "motivo": str}`.
        Lanza `TypeError` si `prompt_text` no es str (fail-closed sobre
        entrada de tipo incorrecto, nunca intenta castear en silencio).
    """
    if not isinstance(prompt_text, str):
        raise TypeError(f"prompt_text debe ser str, recibido {type(prompt_text)!r}")

    normalized = _normalize(prompt_text)
    hits: list[str] = []

    hits.extend(
        f"frase-siembra:{phrase!r}" for phrase in SEED_PHRASES if phrase in normalized
    )

    match = CONFIRM_PATTERN.search(prompt_text)
    if match:
        start = max(0, match.start() - 10)
        end = min(len(prompt_text), match.end() + 40)
        fragment = prompt_text[start:end].strip()
        hits.append(f"confirmar-vs-trazar:{fragment!r}")

    sesgado = bool(hits)
    motivo = (
        "prompt siembra la conclusion via " + "; ".join(hits)
        if sesgado
        else "sin patrones de siembra detectados (mecanico, no oraculo semantico)"
    )
    return {"sesgado": sesgado, "hits": hits, "motivo": motivo}


def main(argv: list[str] | None = None) -> int:
    """CLI: lee el prompt de --prompt-file o stdin, imprime veredicto JSON.

    Before: `argv` es la lista de argumentos (sin argv[0]); si se pasa
        `--prompt-file`, el fichero debe existir y ser legible como UTF-8.
    During: resuelve el texto del prompt (fichero o stdin), invoca
        `check_prompt_bias`, imprime un resumen legible a stdout.
    After: exit 1 si `sesgado` es True (PROMPT_SESGADO), exit 0 si limpio.
        `FileNotFoundError` al leer `--prompt-file` se propaga como exit 2
        (uso incorrecto), nunca se traga en silencio.
    """
    parser = argparse.ArgumentParser(
        description="Detecta sesgo de siembra mecanico en un prompt de review."
    )
    parser.add_argument(
        "--prompt-file",
        help="Ruta a un fichero de texto con el prompt; si se omite, lee stdin.",
    )
    args = parser.parse_args(argv)

    if args.prompt_file:
        try:
            from pathlib import Path

            prompt_text = Path(args.prompt_file).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            print(f"[check_prompt_bias] fichero no encontrado: {exc}", file=sys.stderr)
            return 2
    else:
        prompt_text = sys.stdin.read()

    result = check_prompt_bias(prompt_text)
    if result["sesgado"]:
        print(f"PROMPT_SESGADO: {result['motivo']}")
        return 1
    print(f"OK: {result['motivo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
