"""Extrae MEDICIONES de tokens desde los bundles reales, sin conservar el texto.

Origen: bucle L1113 (2026-08-11). La lente de alternativas midio que "el texto es
ruido para la calibracion matematica": para barrer un umbral de entropia hace
falta la DISTRIBUCION (longitud, entropia, clases, veredicto), no la prosa. Cuatro
numeros no contienen datos personales, asi que el corpus resultante SI es
versionable -- que es lo que WOT-2026-041n no tiene.

Before: existe un directorio con bundles reales (`.agent/runtime/tmp/bundle_*.md`).
During: por cada token candidato replica la capa 3 del detector real
    (`ensemble_dispatch._OPAQUE_TOKEN` + entropia de Shannon + clases de caracter)
    y anota SOLO sus metricas. NUNCA escribe el token literal.
After: emite un JSONL con una fila por token medido. No borra nada, no toca git.

LIMITE DECLARADO: la columna `forma` es una HEURISTICA sobre la FORMA del token
(no sobre su naturaleza real). Sirve para separar candidatos, NO es una etiqueta
verificada de "secreto" vs "falso positivo": esa etiqueta exige criterio humano y
es trabajo de WOT-2026-041n, no de este extractor.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path


# Replica EXACTA de la capa 3 del detector (ensemble_dispatch.py).
OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9+=_-]{32,}")
ENTROPY_BITS_THRESHOLD = 4.0
MIN_CLASSES = 3

# Formas reconocibles, evaluadas EN ORDEN. Heuristica declarada, no veredicto.
FORMAS = [
    ("hex_puro", re.compile(r"^[0-9a-f]+$", re.I)),
    ("nombre_fichero_fechado", re.compile(r"^[A-Z]{2}-\d{8}-")),
    (
        "identificador_con_guiones",
        re.compile(r"^[A-Za-z][A-Za-z0-9]*(-[A-Za-z0-9]+){2,}$"),
    ),
    ("ruta_con_underscores", re.compile(r"^[a-z0-9]+(_[a-z0-9]+){2,}$", re.I)),
    ("base64_probable", re.compile(r"^[A-Za-z0-9+/=]+$")),
]


def entropy(text: str) -> float:
    """Entropia de Shannon en bits por caracter."""
    n = len(text)
    counts = Counter(text)
    return -sum((v / n) * math.log2(v / n) for v in counts.values())


def char_classes(text: str) -> int:
    """Numero de clases de caracter presentes (minus, mayus, digito, simbolo)."""
    return sum(
        [
            any(c.islower() for c in text),
            any(c.isupper() for c in text),
            any(c.isdigit() for c in text),
            any(c in "+=_-" for c in text),
        ]
    )


def clasificar_forma(token: str) -> str:
    """Etiqueta HEURISTICA por la forma del token. No es un veredicto."""
    for nombre, patron in FORMAS:
        if patron.match(token):
            return nombre
    return "mixto_sin_forma"


def reunir_fuentes(workspace: Path) -> list[Path]:
    """Bundles MAS las superficies que conservan los falsos positivos REALES.

    Medido 2026-08-11: barrer solo los bundles da 0 nombres-de-fichero entre los
    tokens bloqueados, y hoy fueron DOS nombres de fichero los que bloquearon un
    envio legitimo. Causa: el emisor los acorto en los bundles para que pasaran,
    asi que el corpus perdio justo los casos que documentaban el falso positivo.
    Las fichas del buzon y los prompts de arranque SI los conservan intactos.
    """
    tmp = workspace / ".agent" / "runtime" / "tmp"
    fuentes = sorted(tmp.glob("bundle_*.md"))
    fuentes += sorted(workspace.glob("ARRANQUE_*.md"))
    fuentes += sorted(
        (workspace / ".agent" / "collaboration" / "backlog_inbox").glob("*.md")
    )
    fuentes += sorted((workspace / "orchestrator_pipeline" / "reports").glob("*.md"))
    return sorted(set(fuentes))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="Raiz del workspace activo del que leer las superficies.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "metrics.jsonl",
        help="Fichero JSONL de salida.",
    )
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        parser.error(f"workspace no es un directorio: {workspace}")

    bundles = reunir_fuentes(workspace)
    filas: list[dict[str, object]] = []
    for idx, ruta in enumerate(bundles):
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        for match in OPAQUE_TOKEN.finditer(texto):
            token = match.group(0)
            ent = entropy(token)
            clases = char_classes(token)
            filas.append(
                {
                    "fuente_idx": idx,
                    "longitud": len(token),
                    "entropia": round(ent, 4),
                    "clases": clases,
                    "bloqueado_por_detector_actual": bool(
                        ent >= ENTROPY_BITS_THRESHOLD and clases >= MIN_CLASSES
                    ),
                    "forma": clasificar_forma(token),
                }
            )

    salida = args.out
    with open(salida, "w", encoding="utf-8", newline="\n") as fh:
        for fila in filas:
            fh.write(json.dumps(fila, ensure_ascii=True, sort_keys=True) + "\n")

    bloqueados = [f for f in filas if f["bloqueado_por_detector_actual"]]
    print(f"bundles leidos      : {len(bundles)}")
    print(f"tokens candidatos   : {len(filas)}")
    print(f"bloquearia el filtro: {len(bloqueados)}")
    print(f"salida              : {salida} ({salida.stat().st_size} bytes)")
    print("\n--- reparto por forma de los que BLOQUEARIA ---")
    for forma, n in Counter(f["forma"] for f in bloqueados).most_common():
        print(f"  {forma:<28} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
