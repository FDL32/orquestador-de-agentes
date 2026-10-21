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
  ID-NO-CANONICO   un id vacio o que no es `H-<digitos>` (p.ej. `H-30(ctx)`, `X-07`,
                   `h-3`): una fila con id no parseable se saldria del censo.
  ID-DUPLICADO     el mismo id en dos filas.
  CAT-FUERA-ENUM   una `categoria` que no empieza por ninguna del enum cerrado.
  CAT-CALIFICADOR  calificador embebido en la celda (`SMELL (x)`) sin columna
                   `calificador`: formato anterior, migrar.
  ALCANCE-INVALIDO valor de la columna `alcance` distinto de simbolo|modulo.
  HALLAZGOS-SIN-FILAS  fichero sin ninguna fila de hallazgo reconocida: ERROR si
                   alguna linea de tabla cita un `H-<n>` (tabla no reconocida,
                   p.ej. cabecera sin `categoria`), WARN si no cita ninguno.
  FENCE-SIN-CERRAR un bloque ``` o ~~~ que nunca se cierra: el parser ignora todo lo
                   que le sigue (tablas incluidas) y las filas perdidas no darian error.
  FILA-ANCHO       (WARN) fila con mas celdas que la cabecera: el dato sobrante no
                   se lee y un `|` literal en una celda desplaza las columnas.
Sobre el informe (`--informe`):
  ID-HUERFANO      id citado en prosa o tabla que no existe en ningun HALLAZGOS.
  ID-SUFIJO        variante con sufijo de un id (`H-30(x)`, `H-30b`, `H-30bis`,
                   `H-30-2`, `H-30_legacy`, `H-30.v2`). Un rango se escribe con
                   `H-30..H-35` o `H-30 a H-35`, nunca `H-30-31`.
  ID-NO-CANONICO   id en minusculas (`h-05`) fuera de un span de codigo.
  CAT-DIVERGE      la categoria del encabezado `###` (o de la columna `categoria`)
                   de la tabla donde aparece el id difiere de la de su fila: por
                   FAMILIA (DEAD/SMELL/...) y EXACTA para los niveles SECURITY.
                   Un encabezado agrupador (`### DEAD / ABANDONED`) admite cualquiera
                   de sus categorias.
  CAT-FUERA-ENUM   (tambien en el informe) una columna `categoria` fuera del enum.
  TALLY-AUSENTE    el informe no lleva el bloque `<!-- TALLY: {...} -->`.
  TALLY-MULTIPLE   el informe lleva mas de un bloque TALLY (cual manda?).
  TALLY-DESCUADRE  el bloque no coincide con el recuento recalculado de las tablas,
                   no es JSON o su estructura no es la esperada (`total` entero,
                   `por_categoria` y `veredictos` objetos de enteros).
  TALLY-SUMA       los veredictos del bloque no suman su `total`.

Limites declarados (no se ocultan):
  - comprueba los ids, las categorias y el bloque TALLY, NO las cifras escritas en
    prosa. La regla del prompt es que el Resumen COPIA el bloque que emite
    `--emit-tally`; un numero tecleado a mano fuera del bloque sigue sin detectarse.
  - la categoria de una tabla del informe SIN columna `categoria` se lee del
    encabezado `#` mas cercano; si ese encabezado no nombra ninguna categoria en
    MAYUSCULAS (`DEAD`, `SECURITY-alta`...) no hay nada contra lo que comparar y la
    tabla se acepta sin aviso.
  - una tabla de un HALLAZGOS que no lleve columnas `id` y `categoria` no se cuenta.
  - tampoco esta cableado a un hook: lo ejecuta quien audita antes de publicar el
    informe (ver `guard_wiring_policy.yaml`).

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
        fence_sin_cerrar,
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
        fence_sin_cerrar,
        normaliza_categoria,
        parse_tablas,
    )

VEREDICTOS = ("confirmado", "disputado", "refutado", "diferido_no_loop")
TALLY_RE = re.compile(r"<!--\s*TALLY:\s*(\{.*?\})\s*-->", re.DOTALL)
# Sufijo: `(texto)`, letras (`b`, `bis`, `legacy`) o `-`/`_`/`.` + alfanumerico
# (`-2`, `_legacy`, `.v2`). `H-30-H-35` (rango) no cuenta como sufijo.
ID_CITADO_RE = re.compile(
    r"\b[Hh]-(\d+)(\([^)\n]*\)|[A-Za-z][A-Za-z0-9_]*|[-_.](?!H-\d)[A-Za-z0-9]+)?"
)
# Categorias nombradas en un encabezado: en MAYUSCULAS (un `### Proceso de
# verificacion` o `### Deadline` no son categorias) y con frontera de palabra.
ENCABEZADO_CAT_RE = re.compile(
    r"(?<![\w-])(DEAD \(unverified dynamic\)|DEAD|ABANDONED|LEGACY|SMELL"
    r"|BUENAS-PRACTICAS|PROCESO|SECURITY(?:-(?:critica|alta|media|baja))?)(?![\w-])"
)
NIVEL_AGRUPADO_RE = re.compile(r"\s*/\s*(critica|alta|media|baja)\b")
LINEA_TABLA_CON_ID_RE = re.compile(r"^\s*\|.*\bH-\d", re.MULTILINE)


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


CAT_DEAD_DINAMICO = "DEAD (unverified dynamic)"


def _limpia(celda: str) -> str:
    return celda.strip().strip("`*").strip()


def _familia(texto: str) -> str:
    return re.split(r"[ -]", texto.strip(), maxsplit=1)[0].upper()


def _categorias_encabezado(seccion: str) -> set[str]:
    """Categorias en MAYUSCULAS que nombra un encabezado `#`.

    `SECURITY-media / baja` (niveles unidos por `/`, con o sin espacios) es un
    agrupador que admite exactamente esos niveles; si tras la `/` no hay un nivel
    reconocible se degrada a la familia `SECURITY`, que acepta cualquiera.
    """
    cats: set[str] = set()
    for m in ENCABEZADO_CAT_RE.finditer(seccion):
        nombre = m.group(1)
        pos = m.end()
        if nombre.startswith("SECURITY-"):
            while siguiente := NIVEL_AGRUPADO_RE.match(seccion, pos):
                cats.add(f"SECURITY-{siguiente.group(1)}")
                pos = siguiente.end()
            if seccion[pos:].lstrip().startswith("/"):  # agrupador no reconocido
                nombre = "SECURITY"
        cats.add(nombre)
    return cats


def _coincide(base: str, cats: set[str]) -> bool:
    """`base` (categoria de la fila) cabe en alguna de `cats` (las de la tabla).

    Exacta para los niveles SECURITY y para `DEAD (unverified dynamic)` (tienen
    implicacion de gobierno distinta de su familia); por familia para el resto.
    """
    if base.startswith("SECURITY-"):
        return base in cats or "SECURITY" in cats
    if base == CAT_DEAD_DINAMICO:
        return base in cats
    return _familia(base) in {_familia(c) for c in cats if c != CAT_DEAD_DINAMICO}


def _filas_hallazgo(hallazgos: dict[str, str]) -> list[dict]:
    filas = []
    for nombre, texto in hallazgos.items():
        for fila in parse_tablas(texto, nombre):
            cols = fila["cols"]
            if "id" in cols and "categoria" in cols:
                filas.append(fila)
    return filas


def _comprueba_ficheros_vacios(
    hallazgos: dict[str, str], filas: list[dict], res: AuditResult
) -> None:
    con_filas = {f["fuente"] for f in filas}
    for nombre, texto in hallazgos.items():
        if nombre in con_filas:
            continue
        # Una tabla que cita ids pero no se reconoce es un censo perdido (ERROR); un
        # lane sin ninguna cita puede ser legitimamente vacio (WARN).
        cita_ids = LINEA_TABLA_CON_ID_RE.search(texto) is not None
        res.add(
            "ERROR" if cita_ids else "WARN",
            "HALLAZGOS-SIN-FILAS",
            f"{nombre}: 0 filas de hallazgo reconocidas"
            + (
                " pero hay lineas de tabla que citan ids (cabecera sin `id`/`categoria`?)"
                if cita_ids
                else ""
            ),
        )


def _recolecta(hallazgos: dict[str, str], res: AuditResult) -> dict[str, str | None]:
    """Valida las filas de hallazgo y devuelve `id -> categoria base` (ids validos)."""
    categoria_de: dict[str, str | None] = {}
    vistos: dict[str, str] = {}
    filas = _filas_hallazgo(hallazgos)
    _comprueba_ficheros_vacios(hallazgos, filas, res)
    for fila in filas:
        cols = fila["cols"]
        origen = f"{fila['fuente']}:{fila['n_linea']}"
        if fila.get("ancho_extra"):
            res.add(
                "WARN",
                "FILA-ANCHO",
                f"{origen}: la fila tiene mas celdas que la cabecera (dato sobrante ignorado)",
            )
        id_ = _limpia(cols["id"])
        if not ID_CANONICO_RE.fullmatch(id_):
            res.add(
                "ERROR",
                "ID-NO-CANONICO",
                f"{origen}: id `{id_}` no es H-<digitos> (la fila queda fuera del censo)",
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


def _es_entero(valor: object) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _error_estructura_tally(tally: dict) -> str | None:
    """Por que el bloque declarado no tiene la forma `{total, por_categoria, veredictos}`.

    Un JSON bien formado pero mal tipado (`"veredictos": null`) NO es un fallo del
    parser de JSON: sin esta guarda reventaba con un traceback en vez de un ERROR.
    """
    if not _es_entero(tally.get("total")):
        return "`total` no es un entero"
    for clave in ("por_categoria", "veredictos"):
        valor = tally.get(clave)
        if not isinstance(valor, dict):
            return f"`{clave}` no es un objeto"
        if not all(_es_entero(v) for v in valor.values()):
            return f"`{clave}` tiene valores que no son enteros"
    desconocidas = sorted(set(tally["veredictos"]) - set(VEREDICTOS))
    if desconocidas:
        return f"`veredictos` con claves desconocidas: {desconocidas}"
    return None


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
    # Un sufijo (o una minuscula) DENTRO de un span de codigo es una cita literal del
    # defecto (p.ej. "el borrador decia `H-30(x)`"), no un id nuevo: el defecto real
    # es la celda de tabla o la prosa sin backticks.
    en_codigo = [m.span() for m in re.finditer(r"`[^`\n]*`", sin_bloque)]
    for m in ID_CITADO_RE.finditer(sin_bloque):
        id_ = f"H-{m.group(1)}"
        citado_en_codigo = any(a <= m.start() < b for a, b in en_codigo)
        if m.group(2):
            if citado_en_codigo:
                continue
            res.add(
                "ERROR",
                "ID-SUFIJO",
                f"variante con sufijo `{m.group(0)}` (usa el id existente `{id_}`)",
            )
        elif m.group(0)[0] == "h":
            if not citado_en_codigo:
                res.add(
                    "ERROR",
                    "ID-NO-CANONICO",
                    f"`{m.group(0)}` en minusculas; el id canonico es `{id_}`",
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
            if esperada is None:
                res.add(
                    "ERROR",
                    "CAT-FUERA-ENUM",
                    f"{id_}: la tabla del informe da la categoria `{cols['categoria'].strip()}`, "
                    "fuera del enum cerrado",
                )
                continue
            cats = {esperada}
        else:
            cats = _categorias_encabezado(fila["seccion"])
        if cats and not _coincide(base, cats):
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
    if len(TALLY_RE.findall(informe_text)) > 1:
        res.add(
            "ERROR",
            "TALLY-MULTIPLE",
            "el informe lleva mas de un bloque TALLY; deja uno solo (el de --emit-tally)",
        )
    if "__invalido__" in declarado:
        res.add("ERROR", "TALLY-DESCUADRE", "el bloque TALLY no es JSON valido")
        return
    estructura = _error_estructura_tally(declarado)
    if estructura:
        res.add(
            "ERROR",
            "TALLY-DESCUADRE",
            f"estructura del bloque TALLY invalida: {estructura}",
        )
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


def _comprueba_fences(
    hallazgos: dict[str, str], informe_text: str | None, res: AuditResult
) -> None:
    """Un bloque de codigo sin cerrar hace que el parser ignore TODO lo que le sigue."""
    textos = dict(hallazgos)
    if informe_text is not None:
        textos["informe"] = informe_text
    for nombre, texto in textos.items():
        linea = fence_sin_cerrar(texto)
        if linea is not None:
            res.add(
                "ERROR",
                "FENCE-SIN-CERRAR",
                f"{nombre}:{linea}: bloque de codigo sin cerrar; las tablas que le "
                "siguen se ignoran como codigo (las filas perdidas no darian error)",
            )


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
    _comprueba_fences(hallazgos, informe_text, res)
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
        return ruta.read_text(encoding="utf-8-sig")  # tolera el BOM de Windows
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
        ruta = Path(ruta_str)
        clave = ruta.name
        if clave in textos:  # dos `<lane>/HALLAZGOS.md`: no pisar el primero
            clave = f"{ruta.parent.name}/{ruta.name}"
        textos[clave] = texto
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
