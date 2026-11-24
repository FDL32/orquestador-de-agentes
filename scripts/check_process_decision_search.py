#!/usr/bin/env python
"""Guard: una decision de proceso DECLARADA en un artefacto debe declarar su
busqueda previa de protocolo (AGENTS.md, WOT-2026-104b) o su recibo
mecanico PRIMARY_SOURCE_CHECK (WOT-2026-231a).

Que protege
-----------
AGENTS.md seccion "Decision de proceso sin instruccion exacta => BUSCA
protocolo documentado antes de suponer uno (2026-10-14)" y el contrato de
escalado A8 (.agent/rules/common/contract_full_read_and_process_search.md).
El guard cablea dos modos complementarios:
1. Modo retrocompatible 104b: cuando un artefacto se autodeclara con el
   marcador DECISION DE PROCESO:, exige BUSQUEDA-PREVIA: o un recibo valido.
2. Modo obligatorio (--mandatory, WOT-2026-231a): invocado directamente por
   entrypoints tipificados; exige la presencia y validez del recibo
   PRIMARY_SOURCE_CHECK independientemente de cualquier marcador.

Estructura de PRIMARY_SOURCE_CHECK
----------------------------------
El recibo vive dentro del artefacto auditado en formato estructurado (YAML)
y declara:
- estado: TIPIFICADA-FORMA o NO TIPIFICADA.
- universo: mapeo de raices declaradas a su conteo respectivo.
- conteo_total: suma entera de los conteos declarados.
- comando, cwd, root, fecha, rc: metadatos obligatorios de ejecucion.
- citas: lista de {ruta, linea, texto} comprobadas sobre ficheros versionados.
En caso de NO TIPIFICADA:
- conflicto: descripcion explicita del motivo.
- siguiente_peldano: escalado formal (supervisora, bucle_de_gobierno, usuario).
- control_positivo: estructura con el mismo universo y una cita comprobable.

ALCANCE DECLARADO (lo que este guard NO hace)
----------------------------------------------
Verifica que la forma y las citas existan y contengan el texto literal en el
universo versionado. La semantica de la cita queda fuera del checker y NO se
certifica (WOT-2026-231a).

Before / During / After
-----------------------
Before: recibe rutas de artefactos y opcionalmente el flag --mandatory.
During: elimina fences de codigo; valida el marcador y BUSQUEDA-PREVIA: en
    modo general, o parsea y valida exhaustivamente PRIMARY_SOURCE_CHECK:
    en modo obligatorio o cuando el recibo esta presente.
After: exit 0 si cumple; exit 1 con defecto exacto; exit 2 si la ruta no existe.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml


_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

_DECISION_MARKER_RE = re.compile(
    r"(?m)^[ 	]*(?:#{1,6}[ 	]*|[-*][ 	]*)?DECISION DE PROCESO\s*:",
    re.IGNORECASE,
)

_BUSQUEDA_MARKER_RE = re.compile(
    r"(?m)^[ 	]*(?:#{1,6}[ 	]*|[-*][ 	]*)?BUSQUEDA-PREVIA\s*:",
    re.IGNORECASE,
)

_PRIMARY_SOURCE_RE = re.compile(
    r"(?m)^[ 	]*(?:#{1,6}[ 	]*|[-*][ 	]*)?PRIMARY_SOURCE_CHECK\s*:",
    re.IGNORECASE,
)

_PROTOCOLO_ENCONTRADO_LABEL_RE = re.compile(r"(?i)PROTOCOLO ENCONTRADO\s*:")

_PROTOCOLO_ENCONTRADO_RE = re.compile(r"(?im)PROTOCOLO ENCONTRADO\s*:[ 	]*(\S.*)$")

_NO_ENCONTRE_RE = re.compile(r"(?i)NO ENCONTRE PROTOCOLO")

_EXCEPCION_TRIVIAL_RE = re.compile(
    r"(?im)EXCEPCION\s*:\s*trivial\b[ 	]*[-:]?[ 	]*(\S.*)?$"
)

SEMANTIC_DISCLAIMER = (
    "[PRIMARY_SOURCE_CHECK] NOTA: la forma verificable ha sido contrastada; "
    "la semantica de la cita queda fuera del checker y no se certifica."
)

ALLOWED_NEXT_STEPS = {"supervisora", "bucle_de_gobierno", "usuario"}


def _strip_fences(text: str) -> str:
    """Elimina bloques ```...``` para no disparar sobre ejemplos/documentacion."""
    return _FENCE_RE.sub("", text)


def has_decision_marker(text: str) -> bool:
    return bool(_DECISION_MARKER_RE.search(_strip_fences(text)))


def has_primary_source_receipt(text: str) -> bool:
    return bool(_PRIMARY_SOURCE_RE.search(_strip_fences(text)))


def busqueda_previa_defect(text: str) -> str | None:
    """Devuelve el defecto (str) si BUSQUEDA-PREVIA: no cumple, o None si OK."""
    scrubbed = _strip_fences(text)
    if not _BUSQUEDA_MARKER_RE.search(scrubbed):
        return (
            "falta la seccion 'BUSQUEDA-PREVIA:' (exige una de: "
            "'PROTOCOLO ENCONTRADO: <ruta>', 'NO ENCONTRE PROTOCOLO', "
            "'EXCEPCION: trivial <justificacion>')"
        )
    m = _PROTOCOLO_ENCONTRADO_RE.search(scrubbed)
    if m and m.group(1).strip():
        return None
    if _NO_ENCONTRE_RE.search(scrubbed):
        return None
    m = _EXCEPCION_TRIVIAL_RE.search(scrubbed)
    if m and (m.group(1) or "").strip():
        return None
    if m:
        return (
            "'EXCEPCION: trivial' declarada sin texto de justificacion "
            "(una etiqueta vacia no basta)"
        )
    if _PROTOCOLO_ENCONTRADO_LABEL_RE.search(scrubbed):
        return "'PROTOCOLO ENCONTRADO:' declarado sin ruta (texto vacio tras los dos puntos)"
    return (
        "'BUSQUEDA-PREVIA:' presente pero ninguna de las 3 formas validas "
        "('PROTOCOLO ENCONTRADO: <ruta>' / 'NO ENCONTRE PROTOCOLO' / "
        "'EXCEPCION: trivial <justificacion>') esta declarada"
    )


def extract_receipt_data(text: str) -> dict | None:
    """Extrae y parsea el bloque YAML de PRIMARY_SOURCE_CHECK si existe."""
    scrubbed = _strip_fences(text)
    m = _PRIMARY_SOURCE_RE.search(scrubbed)
    if not m:
        return None

    raw_lines = scrubbed[m.start() :].splitlines()
    yaml_lines = [raw_lines[0]]
    for line in raw_lines[1:]:
        stripped = line.strip()
        if not stripped:
            yaml_lines.append(line)
            continue
        if line.startswith((" ", "	")) or (
            line.startswith("- ") and not line.startswith("---")
        ):
            yaml_lines.append(line)
        elif re.match(r"^[a-zA-Z0-9_]+:\s*", line):
            break
        else:
            break

    block = chr(10).join(yaml_lines)
    try:
        parsed = yaml.safe_load(block)
        if isinstance(parsed, dict):
            if "PRIMARY_SOURCE_CHECK" in parsed and isinstance(
                parsed["PRIMARY_SOURCE_CHECK"], dict
            ):
                return parsed["PRIMARY_SOURCE_CHECK"]
            return parsed
    except Exception:
        return None
    return None


def _measure_root_count(root_name: str, base_dir: Path) -> int:
    """Mide el conteo de ficheros en una raiz declarada."""
    target = base_dir / root_name
    if not target.exists():
        try:
            out = subprocess.check_output(  # noqa: S603
                ["git", "ls-files", root_name],  # noqa: S607
                cwd=base_dir,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            files = [f for f in out.splitlines() if f.strip()]
            return len(files)
        except Exception:
            return 0

    if target.is_file():
        return 1
    if target.is_dir():
        try:
            out = subprocess.check_output(  # noqa: S603
                ["git", "ls-files", root_name],  # noqa: S607
                cwd=base_dir,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            files = [f for f in out.splitlines() if f.strip()]
            if files:
                return len(files)
        except (subprocess.SubprocessError, OSError):
            pass
        return len([f for f in target.rglob("*") if f.is_file()])
    return 0


def _is_path_in_universe(ruta_str: str, universe_roots: list[str]) -> bool:
    norm_ruta = Path(ruta_str).as_posix().lstrip("./")
    for r in universe_roots:
        norm_r = Path(r).as_posix().lstrip("./").rstrip("/")
        if norm_ruta == norm_r or norm_ruta.startswith(norm_r + "/"):
            return True
    return False


def _validate_citation(
    cita: dict, universe_roots: list[str], base_dir: Path
) -> str | None:
    """Comprueba la forma verificable de una cita de fuente primaria."""
    if not isinstance(cita, dict):
        return "la cita debe ser un objeto con ruta, linea y texto"
    for req in ["ruta", "linea", "texto"]:
        if req not in cita:
            return f"falta el campo obligatorio '{req}' en la cita"

    ruta = str(cita["ruta"])
    if not _is_path_in_universe(ruta, universe_roots):
        return f"la cita '{ruta}' esta fuera del universo declarado o es una fuente omitida"

    target_file = base_dir / ruta
    if not target_file.is_file():
        return f"la ruta citada '{ruta}' no existe en disco"

    try:
        linea = int(cita["linea"])
    except (ValueError, TypeError):
        return f"la linea declarada '{cita['linea']}' debe ser un entero"

    try:
        lines = target_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return f"error al leer '{ruta}': {e}"

    if linea < 1 or linea > len(lines):
        return f"la linea {linea} no existe en '{ruta}' (total lineas: {len(lines)})"

    texto = str(cita["texto"])
    if texto not in lines[linea - 1]:
        return f"la linea {linea} de '{ruta}' no contiene el texto citado '{texto}'"

    return None


def _check_receipt_metadata(receipt: dict) -> tuple[str | None, str]:
    """Verifica presencia de campos y estado."""
    if not isinstance(receipt, dict):
        return ("el bloque PRIMARY_SOURCE_CHECK no es un diccionario valido", "")

    if (
        receipt.get("semantica_certificada") is True
        or "certifica semantica" in str(receipt).lower()
    ):
        return (
            "la semantica de la cita no puede declararse como certificada (el checker solo verifica forma)",
            "",
        )

    required_fields = [
        "estado",
        "universo",
        "conteo_total",
        "comando",
        "cwd",
        "root",
        "fecha",
        "rc",
    ]
    for f in required_fields:
        if f not in receipt or receipt[f] is None:
            return (f"falta el campo obligatorio '{f}' en PRIMARY_SOURCE_CHECK", "")

    estado = str(receipt["estado"]).strip().upper()
    if estado not in {"TIPIFICADA-FORMA", "NO TIPIFICADA"}:
        return (
            f"estado '{receipt['estado']}' no valido (debe ser TIPIFICADA-FORMA o NO TIPIFICADA)",
            "",
        )

    return (None, estado)


def _check_universe_counts(
    universo: dict, conteo_total_raw: object, base_dir: Path
) -> tuple[str | None, list[str]]:
    """Verifica y mide las raices del universo declarado."""
    if not isinstance(universo, dict) or not universo:
        return ("el campo 'universo' debe ser un diccionario no vacio de raices", [])

    total_declared = 0
    universe_roots = list(universo.keys())
    for root_name, cnt in universo.items():
        if not isinstance(cnt, int) or isinstance(cnt, bool):
            return (f"el conteo de la raiz '{root_name}' debe ser un entero", [])
        if cnt < 0:
            return (f"el conteo de la raiz '{root_name}' debe ser entero >= 0", [])
        total_declared += cnt

    if not isinstance(conteo_total_raw, int) or isinstance(conteo_total_raw, bool):
        return ("el campo 'conteo_total' debe ser un entero", [])

    if conteo_total_raw != total_declared:
        return (
            f"conteo_total ({conteo_total_raw}) no coincide con la suma del universo ({total_declared})",
            [],
        )

    measured_total = 0
    for root_name in universe_roots:
        measured = _measure_root_count(root_name, base_dir)
        if measured == 0:
            return (
                f"la raiz declarada '{root_name}' esta vacia (0 ficheros encontrados)",
                [],
            )
        measured_total += measured

    if measured_total == 0:
        return ("el universo medido total es 0", [])

    return (None, universe_roots)


def _check_tipificada_receipt(
    receipt: dict, universe_roots: list[str], base_dir: Path
) -> str | None:
    citas = receipt.get("citas")
    if not isinstance(citas, list) or not citas:
        return "el recibo TIPIFICADA-FORMA exige una lista no vacia de 'citas'"
    for cita in citas:
        err = _validate_citation(cita, universe_roots, base_dir)
        if err:
            return err
    return None


def _check_no_tipificada_receipt(
    receipt: dict, universe_roots: list[str], base_dir: Path
) -> str | None:
    conflicto = receipt.get("conflicto")
    if not conflicto or not str(conflicto).strip():
        return "falta el campo obligatorio 'conflicto' en recibo NO TIPIFICADA"

    siguiente = str(receipt.get("siguiente_peldano", "")).strip().lower()
    if siguiente not in ALLOWED_NEXT_STEPS:
        return (
            f"el campo 'siguiente_peldano' ('{siguiente}') debe ser uno de: "
            f"{', '.join(sorted(ALLOWED_NEXT_STEPS))}"
        )

    cp = receipt.get("control_positivo")
    if not isinstance(cp, dict):
        return "el recibo NO TIPIFICADA exige 'control_positivo' estructurado"

    cp_universo = cp.get("universo")
    if not isinstance(cp_universo, dict) or set(cp_universo.keys()) != set(
        universe_roots
    ):
        return "el universo del control_positivo no coincide con las raices declaradas en el recibo"

    cp_cita = cp.get("cita")
    err = _validate_citation(cp_cita, universe_roots, base_dir)
    if err:
        return f"error en cita de control_positivo: {err}"

    return None


def validate_primary_source_receipt(
    receipt: dict, base_dir: Path
) -> tuple[str | None, str]:
    """Valida exhaustivamente un recibo PRIMARY_SOURCE_CHECK."""
    err, estado = _check_receipt_metadata(receipt)
    if err:
        return (err, estado)

    err, roots = _check_universe_counts(
        receipt["universo"], receipt["conteo_total"], base_dir
    )
    if err:
        return (err, estado)

    if estado == "TIPIFICADA-FORMA":
        err = _check_tipificada_receipt(receipt, roots, base_dir)
    else:
        err = _check_no_tipificada_receipt(receipt, roots, base_dir)

    return (err, estado)


def check_artifact(
    text: str,
    base_dir: Path | None = None,
    mandatory: bool = False,
) -> str | None:
    """None si OK/no-aplica; str con el defecto exacto si bloquea."""
    if base_dir is None:
        base_dir = Path(".")

    receipt = extract_receipt_data(text)
    if receipt is not None:
        defecto, _ = validate_primary_source_receipt(receipt, base_dir)
        return defecto

    if mandatory:
        return "modo obligatorio activado pero falta el recibo 'PRIMARY_SOURCE_CHECK:'"

    if not has_decision_marker(text):
        return None

    return busqueda_previa_defect(text)


def find_base_dir(path: Path) -> Path:
    """Resuelve la raiz del repositorio subiendo por los padres o via cwd/git."""
    curr = path.resolve()
    for parent in [curr, *list(curr.parents)]:
        if (parent / ".git").exists() or (parent / "AGENTS.md").is_file():
            return parent
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S607
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if top:
            return Path(top)
    except Exception:  # noqa: S110
        pass
    return Path.cwd()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Verifica que un artefacto que se autodeclara DECISION DE "
            "PROCESO: declare su BUSQUEDA-PREVIA: de protocolo (AGENTS.md, "
            "WOT-2026-104b) o su recibo PRIMARY_SOURCE_CHECK (WOT-2026-231a)."
        )
    )
    ap.add_argument(
        "--mandatory",
        action="store_true",
        help="Modo obligatorio: exige recibo PRIMARY_SOURCE_CHECK valido independientemente del marcador.",
    )
    ap.add_argument(
        "--base-dir",
        type=Path,
        default=None,
        help="Directorio raiz del repositorio (por defecto autodetectado buscando .git o AGENTS.md).",
    )
    ap.add_argument(
        "artefactos", nargs="+", help="ruta(s) del fichero a verificar (una o varias)"
    )
    args = ap.parse_args()

    worst = 0
    for raw in args.artefactos:
        path = Path(raw)
        if not path.is_file():
            print(
                f"[process-decision-search] ERROR: no encontrado: {path}",
                file=sys.stderr,
            )
            worst = max(worst, 2)
            continue

        base_dir = (
            args.base_dir.resolve()
            if args.base_dir is not None
            else find_base_dir(path)
        )
        text = path.read_text(encoding="utf-8", errors="replace")
        defect = check_artifact(
            text,
            base_dir=base_dir,
            mandatory=args.mandatory,
        )

        if defect is None:
            receipt = extract_receipt_data(text)
            if receipt is not None:
                estado = str(receipt.get("estado", "")).strip().upper()
                print(
                    f"[PRIMARY_SOURCE_CHECK] OK: {path.name} declara recibo valido ({estado})"
                )
                print(SEMANTIC_DISCLAIMER)
            elif has_decision_marker(text):
                print(
                    f"[process-decision-search] OK: {path.name} declara BUSQUEDA-PREVIA valida"
                )
            else:
                print(
                    f"[process-decision-search] OK: {path.name} no declara DECISION DE PROCESO: (no aplica)"
                )
            continue

        if args.mandatory or has_primary_source_receipt(text):
            print(
                f"[PRIMARY_SOURCE_CHECK] BLOQUEA: {path.name} {defect}.",
                file=sys.stderr,
            )
            print(SEMANTIC_DISCLAIMER, file=sys.stderr)
        else:
            print(
                f"[process-decision-search] BLOQUEA: {path.name} declara "
                f"'DECISION DE PROCESO:' y {defect}.",
                file=sys.stderr,
            )
            print(
                '\n  AGENTS.md: "antes de resolver una decision de proceso por '
                "razonamiento propio, comprueba primero si existe un protocolo YA "
                'ESCRITO" -- declara el resultado de esa busqueda antes de seguir.',
                file=sys.stderr,
            )
        worst = max(worst, 1)

    return worst


if __name__ == "__main__":
    sys.exit(main())
