#!/usr/bin/env python
"""Validador del informe de `repo_audit_multiagent.md` contra sus tablas de hallazgos.

Que protege
-----------
La familia de errores de higiene medida en la primera corrida real completa del
prompt (auditoria de `Redes_Sociales`, 2026-10-21): cifras escritas de memoria
(total, por categoria, confirmados + diferidos), un id citado en prosa que nunca
tuvo fila, un id reutilizado con sufijo, el mismo hallazgo bajo dos categorias.
Todas se detectaron por revision humana o de lentes, no por una barrera.

Que comprueba (cada hallazgo lleva un codigo estable)
------------------------------------------------------
Sobre los `HALLAZGOS_<lane>.md`:
  ID-NO-CANONICO   un id que empieza por `H-` y no es `H-<digitos>` (p.ej. `H-30(ctx)`).
  ID-DUPLICADO     el mismo id en dos filas.
  CAT-FUERA-ENUM   una `categoria` que no empieza por ninguna del enum cerrado.
  CAT-CALIFICADOR  calificador embebido en la celda (`SMELL (x)`) sin columna
                   `calificador`: formato anterior, migrar.
  ALCANCE-INVALIDO valor de la columna `alcance` distinto de simbolo|modulo.
Sobre el informe (`--informe`):
  ID-HUERFANO      id citado en prosa o tabla que no existe en ningun HALLAZGOS.
  ID-SUFIJO        variante con sufijo de un id (`H-30(x)`, `H-30b`).
  CAT-DIVERGE      la familia de categoria del encabezado `###` (o de la columna
                   `categoria`) de la tabla donde aparece el id difiere de la de su fila.
  TALLY-AUSENTE    el informe no lleva el bloque `<!-- TALLY: {...} -->`.
  TALLY-DESCUADRE  el bloque no coincide con el recuento recalculado de las tablas.
  TALLY-SUMA       los veredictos del bloque no suman su `total`.

Limite declarado (no se oculta): comprueba los ids, las categorias y el bloque
TALLY, NO las cifras escritas en prosa. La regla del prompt es que el Resumen
COPIA el bloque que emite `--emit-tally`; un numero tecleado a mano fuera del
bloque sigue sin detectarse. Tampoco esta cableado a un hook: lo ejecuta quien
audita antes de publicar el informe (ver `guard_wiring_policy.yaml`).

Modos: por defecto informa (exit 0 aunque haya ERROR, para no dar rojo natal a
informes anteriores al formato); `--strict` sale con 1 si hay algun ERROR.

Before: ficheros `HALLAZGOS_*.md` e (opcional) el informe, legibles en UTF-8.
During: parseo con `dedupe_audit_findings.parse_tablas` (fuente unica del
    formato); sin red, sin subprocess, sin escritura. Salida forzada a UTF-8.
After: exit 0 informe (o limpio en --strict); 1 con ERROR en --strict;
    2 si una entrada no existe o no se puede leer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


try:  # importado como modulo del paquete (tests)
    from scripts.dedupe_audit_findings import (
        ALCANCES,
        ID_CANONICO_RE,
        normaliza_categoria,
        parse_tablas,
    )
except (
    ImportError
):  # lanzado por ruta: el directorio del script ya es el cwd del import
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dedupe_audit_findings import (  # type: ignore[no-redef]
        ALCANCES,
        ID_CANONICO_RE,
        normaliza_categoria,
        parse_tablas,
    )

VEREDICTOS = ("confirmado", "disputado", "refutado", "diferido_no_loop")
TALLY_RE = re.compile(r"<!--\s*TALLY:\s*(\{.*?\})\s*-->", re.DOTALL)
ID_CITADO_RE = re.compile(r"\bH-(\d+)(\([^)\n]*\)|[a-z]\b)?")
ENCABEZADO_FAMILIA_RE = re.compile(
    r"^(DEAD|ABANDONED|LEGACY|SMELL|SECURITY|BUENAS-PRACTICAS|PROCESO)", re.IGNORECASE
)


@dataclass(frozen=True)
class Finding:
    severity: str  # "ERROR" | "WARN"
    code: str
    message: str


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    tally: dict | None = None

    def add(self, severity: str, code: str, message: str) -> None:
        self.findings.append(Finding(severity, code, message))


def _limpia(celda: str) -> str:
    return celda.strip().strip("`*").strip()


def _familia(texto: str) -> str:
    return re.split(r"[ -]", texto.strip(), maxsplit=1)[0].upper()


def _filas_hallazgo(hallazgos: dict[str, str]) -> list[dict]:
    filas = []
    for nombre, texto in hallazgos.items():
        for fila in parse_tablas(texto, nombre):
            cols = fila["cols"]
            if "id" in cols and "categoria" in cols:
                filas.append(fila)
    return filas


def _recolecta(hallazgos: dict[str, str], res: AuditResult) -> dict[str, str | None]:
    """Valida las filas de hallazgo y devuelve `id -> categoria base` (ids validos)."""
    categoria_de: dict[str, str | None] = {}
    vistos: dict[str, str] = {}
    for fila in _filas_hallazgo(hallazgos):
        cols = fila["cols"]
        origen = f"{fila['fuente']}:{fila['n_linea']}"
        id_ = _limpia(cols["id"])
        if not ID_CANONICO_RE.fullmatch(id_):
            if id_.upper().startswith("H-"):
                res.add(
                    "ERROR", "ID-NO-CANONICO", f"{origen}: id `{id_}` no es H-<digitos>"
                )
            continue
        if id_ in vistos:
            res.add("ERROR", "ID-DUPLICADO", f"{id_} en {vistos[id_]} y en {origen}")
            continue
        vistos[id_] = origen
        base, calificador = normaliza_categoria(cols["categoria"])
        if base is None:
            res.add(
                "ERROR",
                "CAT-FUERA-ENUM",
                f"{id_} ({origen}): categoria `{cols['categoria'].strip()}` fuera del enum cerrado",
            )
        elif calificador and not _limpia(cols.get("calificador", "")):
            res.add(
                "ERROR",
                "CAT-CALIFICADOR",
                f"{id_} ({origen}): calificador `{calificador}` embebido en la categoria; "
                "muevelo a la columna `calificador`",
            )
        alcance = _limpia(cols.get("alcance", "")).lower()
        if alcance and alcance not in ALCANCES:
            res.add(
                "ERROR", "ALCANCE-INVALIDO", f"{id_} ({origen}): alcance `{alcance}`"
            )
        categoria_de[id_] = base
    return categoria_de


def _veredictos_de_tablas(informe_text: str, ids: set[str]) -> dict[str, str]:
    """`id -> veredicto` de las filas del informe con columna `veredicto_adversarial`."""
    out: dict[str, str] = {}
    for fila in parse_tablas(informe_text, "informe"):
        cols = fila["cols"]
        if "id" not in cols or "veredicto_adversarial" not in cols:
            continue
        id_ = _limpia(cols["id"])
        if id_ not in ids:
            continue
        palabra = re.split(
            r"\W", _limpia(cols["veredicto_adversarial"]).lower(), maxsplit=1
        )[0]
        for veredicto in VEREDICTOS:
            if veredicto.startswith(palabra) and palabra:
                out[id_] = veredicto
                break
    return out


def build_tally(hallazgos: dict[str, str], informe_text: str | None = None) -> dict:
    """Recalcula el bloque TALLY desde las tablas (nunca desde la prosa).

    Before: `hallazgos` mapea nombre de fichero -> texto; `informe_text` es opcional.
    During: cuenta ids validos y unicos por categoria base; los veredictos salen de
        las tablas del informe y `diferido_no_loop` es el resto hasta el total.
    After: `{total, por_categoria, veredictos}`; ids fuera del enum van a `SIN-ENUM`.
    """
    ignorado = AuditResult()
    categoria_de = _recolecta(hallazgos, ignorado)
    por_categoria = Counter((base or "SIN-ENUM") for base in categoria_de.values())
    veredictos = Counter(
        _veredictos_de_tablas(informe_text, set(categoria_de)).values()
        if informe_text
        else []
    )
    total = len(categoria_de)
    contados = sum(veredictos[v] for v in ("confirmado", "disputado", "refutado"))
    return {
        "total": total,
        "por_categoria": dict(sorted(por_categoria.items())),
        "veredictos": {
            "confirmado": veredictos["confirmado"],
            "disputado": veredictos["disputado"],
            "refutado": veredictos["refutado"],
            "diferido_no_loop": total - contados,
        },
    }


def format_tally_block(tally: dict) -> str:
    return f"<!-- TALLY: {json.dumps(tally, ensure_ascii=False, sort_keys=True)} -->"


def parse_tally_block(texto: str) -> dict | None:
    m = TALLY_RE.search(texto)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {"__invalido__": m.group(1)}


def _normaliza_tally(tally: dict) -> dict:
    veredictos = tally.get("veredictos", {})
    return {
        "total": tally.get("total"),
        "por_categoria": {k: v for k, v in tally.get("por_categoria", {}).items() if v},
        "veredictos": {v: veredictos.get(v, 0) for v in VEREDICTOS},
    }


def _comprueba_ids_citados(
    sin_bloque: str, categoria_de: dict[str, str | None], res: AuditResult
) -> None:
    huerfanos: set[str] = set()
    # Un sufijo DENTRO de un span de codigo es una cita literal del defecto (p.ej.
    # "el borrador decia `H-30(x)`"), no un id nuevo: el defecto real es la celda
    # de tabla o la prosa sin backticks.
    en_codigo = [m.span() for m in re.finditer(r"`[^`\n]*`", sin_bloque)]
    for m in ID_CITADO_RE.finditer(sin_bloque):
        id_ = f"H-{m.group(1)}"
        if m.group(2):
            if any(a <= m.start() < b for a, b in en_codigo):
                continue
            res.add(
                "ERROR",
                "ID-SUFIJO",
                f"variante con sufijo `{m.group(0)}` (usa el id existente `{id_}`)",
            )
        elif id_ not in categoria_de and id_ not in huerfanos:
            huerfanos.add(id_)
            res.add(
                "ERROR",
                "ID-HUERFANO",
                f"`{id_}` se cita en el informe y no tiene fila en los HALLAZGOS",
            )


def _comprueba_categoria_de_tablas(
    sin_bloque: str, categoria_de: dict[str, str | None], res: AuditResult
) -> None:
    for fila in parse_tablas(sin_bloque, "informe"):
        cols = fila["cols"]
        if "id" not in cols:
            continue
        id_ = _limpia(cols["id"])
        base = categoria_de.get(id_)
        if not base:
            continue
        if "categoria" in cols:
            esperada, _ = normaliza_categoria(cols["categoria"])
            familia_tabla = _familia(esperada) if esperada else None
        else:
            m = ENCABEZADO_FAMILIA_RE.match(fila["seccion"].strip())
            familia_tabla = _familia(m.group(1)) if m else None
        if familia_tabla and familia_tabla != _familia(base):
            res.add(
                "ERROR",
                "CAT-DIVERGE",
                f"{id_} es `{base}` en su fila y aparece bajo `{fila['seccion']}` en el informe",
            )


def _comprueba_tally(
    informe_text: str, hallazgos: dict[str, str], res: AuditResult
) -> None:
    declarado = parse_tally_block(informe_text)
    if declarado is None:
        res.add(
            "ERROR",
            "TALLY-AUSENTE",
            "el informe no lleva el bloque <!-- TALLY: {...} --> (usa --emit-tally)",
        )
        return
    if "__invalido__" in declarado:
        res.add("ERROR", "TALLY-DESCUADRE", "el bloque TALLY no es JSON valido")
        return
    esperado = build_tally(hallazgos, informe_text)
    if _normaliza_tally(declarado) != _normaliza_tally(esperado):
        res.add(
            "ERROR",
            "TALLY-DESCUADRE",
            f"declarado={json.dumps(_normaliza_tally(declarado), ensure_ascii=False, sort_keys=True)} "
            f"recalculado={json.dumps(_normaliza_tally(esperado), ensure_ascii=False, sort_keys=True)}",
        )
    suma = sum(declarado.get("veredictos", {}).get(v, 0) for v in VEREDICTOS)
    if suma != declarado.get("total"):
        res.add(
            "ERROR",
            "TALLY-SUMA",
            f"los veredictos suman {suma} y el total declarado es {declarado.get('total')}",
        )


def _comprueba_informe(
    informe_text: str,
    categoria_de: dict[str, str | None],
    hallazgos: dict[str, str],
    res: AuditResult,
) -> None:
    sin_bloque = TALLY_RE.sub("", informe_text)
    _comprueba_ids_citados(sin_bloque, categoria_de, res)
    _comprueba_categoria_de_tablas(sin_bloque, categoria_de, res)
    _comprueba_tally(informe_text, hallazgos, res)


def audit_report(
    hallazgos: dict[str, str], informe_text: str | None = None
) -> AuditResult:
    """Audita las tablas de hallazgos y, si se da, el informe.

    Before: `hallazgos` mapea nombre de fichero -> texto Markdown; `informe_text` opcional.
    During: valida filas (ids, enum, alcance) y cruza el informe (ids citados, familia de
        categoria, bloque TALLY). Sin I/O.
    After: `AuditResult` con la lista de `Finding` (codigo estable) y el tally recalculado.
    """
    res = AuditResult()
    categoria_de = _recolecta(hallazgos, res)
    if informe_text is not None:
        _comprueba_informe(informe_text, categoria_de, hallazgos, res)
    res.tally = build_tally(hallazgos, informe_text)
    return res


def _forzar_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _lee(ruta: Path) -> str | None:
    if not ruta.is_file():
        print(f"ERROR: no existe o no es fichero: {ruta}", file=sys.stderr)
        return None
    try:
        return ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: no se pudo leer {ruta}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    _forzar_utf8()
    ap = argparse.ArgumentParser(
        description="Valida el informe de repo-audit contra sus HALLAZGOS."
    )
    ap.add_argument("hallazgos", nargs="+", help="Ruta(s) a HALLAZGOS_<lane>.md")
    ap.add_argument("--informe", help="Ruta al informe (INFORME_FINAL.md)")
    ap.add_argument("--strict", action="store_true", help="exit 1 si hay algun ERROR")
    ap.add_argument(
        "--emit-tally",
        action="store_true",
        help="imprime SOLO el bloque TALLY recalculado",
    )
    args = ap.parse_args()

    textos: dict[str, str] = {}
    for ruta_str in args.hallazgos:
        texto = _lee(Path(ruta_str))
        if texto is None:
            return 2
        textos[Path(ruta_str).name] = texto
    informe_text = None
    if args.informe:
        informe_text = _lee(Path(args.informe))
        if informe_text is None:
            return 2

    if args.emit_tally:
        print(format_tally_block(build_tally(textos, informe_text)))
        return 0

    res = audit_report(textos, informe_text)
    for h in res.findings:
        print(f"[{h.severity}] {h.code}: {h.message}")
    errores = sum(1 for h in res.findings if h.severity == "ERROR")
    print(
        f"[check-audit-report] {errores} ERROR, {len(res.findings) - errores} WARN; total={res.tally['total']}"
    )
    if errores and not args.strict:
        print("[check-audit-report] modo informe: sin --strict no falla (exit 0).")
        return 0
    return 1 if errores else 0


if __name__ == "__main__":
    raise SystemExit(main())
