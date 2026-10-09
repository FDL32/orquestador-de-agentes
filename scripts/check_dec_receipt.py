#!/usr/bin/env python3
"""Barrera del recibo DEC: un `DEC-<id>` citado tiene que EXISTIR (WOT-2026-042x).

`WOT-2026-042w` introdujo la NORMA: las sesiones de DISENO consultan el registro
de decisiones y dejan un recibo estructurado en cada ficha/plan. Una norma que
nada verifica sigue siendo una norma -- este guard es la barrera.

Que valida (y que NO)
---------------------
Valida que el `DEC-<id>` que un recibo cita EXISTE en el registro QUE SU PROPIO
SCOPE DECLARA. Nada mas. En particular NO promete detectar contradiccion
SEMANTICA entre la adjudicacion y la DEC: eso exigiria un juez de prosa, no
converge (muro `WOT-2026-025c`) y seria irreproducible. La promesa exacta es:
*no pasa sin referencia verificable u override declarado*.

El scope NO es decorativo (endurecido en review, 2026-07-29)
-----------------------------------------------------------
La primera version fusionaba los dos registros y descartaba el scope: un recibo
`DEC-<id> (motor)` cuyo id solo existia en el DESTINO pasaba VERDE. Lo cazaron
tres lentes independientes del bucle L700 y lo confirmo la refutacion final de
Codex citando la clausula D5 del prompt de diseno que este mismo vuelo escribio:
*"un DEC-<id> que NO EXISTE en el registro que su propio scope declara es recibo
INVALIDO"*. La NORMA (`WOT-2026-042w`) y la BARRERA (`WOT-2026-042x`) no pueden
contradecirse -- si la barrera es mas laxa que la norma, la norma es decorativa.

ALCANCE DECLARADO (limitacion honesta, no defecto oculto)
---------------------------------------------------------
Este guard inspecciona las FICHAS (`*.tickets.md`) de los buzones que se le
pasan por `--inbox`. La clausula D5 pide recibo para "una ficha O UN PLAN", y
los PLANES de `flight_plans/queued/*.json` NO los mira nadie todavia: lo levanto
la refutacion final de Codex y es un hueco REAL, no un non-goal. Ademas los
buzones estan cableados por ruta fija, asi que un tercer buzon se ignoraria en
silencio. Follow-up con dueno: `WOT-2026-043a`.

Modo `--ticket-contracts` (WOT-2026-088g)
-----------------------------------------
El registro `ticket_contracts.md` NO es un buzon de fichas: es donde viven los
contratos `frozen` que el Builder ejecuta directamente, asi que una DEC
inexistente ahi es MAS grave (el Builder confia en el contrato como fuente de
verdad). El modo `--ticket-contracts <path>` (repetible) cierra ese hueco con
`check_ticket_contracts_file`: inspecciona SOLO los contratos `status: frozen`,
y por cada cita DEC (literal + ruta en el MISMO parentesis) decide OK / WARN /
ERROR. Reutiliza `load_motor_registry`/`load_destino_registry`/`is_grandfathered`
sin cambios; NO fusiona su patron con `_RE_SCOPED` (la forma de cita de los
contratos es literalmente distinta).

La funcion PURA
---------------
`receipt_is_valid(receipt, registry) -> bool` no hace I/O, no resuelve roots y no
sabe nada del transporte que la invoca. Es deliberado: el drenaje del paso 8.bis
que hoy nombra este criterio es 100% prompt-level y `WOT-2026-042u` va a
reescribirlo; una validacion embebida en el transporte moriria con el.

Topologia: el guard NO cruza repos
----------------------------------
El registro del motor sale de `docs/decisions/` del propio motor. El del destino
NO se descubre: entra como ARGUMENTO (`--destino-registry`) -- resolver la
topologia motor<->destino DENTRO del guard es una STOP condition del contrato.
Si NO se le pasa, una ficha con scope `(destino)` se marca NO VERIFICABLE con
motivo y NUNCA se da por buena.

Before / During / After
-----------------------
Before: existe `docs/decisions/` en el motor; opcionalmente un registro de
    destino pasado por argumento; cero o mas ficheros de ficha a inspeccionar.
During: lee los registros (una vez), extrae los ids, y clasifica cada ficha.
    Solo lectura: no escribe, no muta, no toca git ni red.
After: exit 0 = ninguna ficha bloqueante incumple. exit 1 = al menos un ERROR.
    Las fichas anteriores a `GRANDFATHER_CUTOFF` degradan a WARN (nunca ERROR).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from pathlib import Path


# Fecha de corte del grandfathering. FIJADA EN EL CONTRATO T-042X-001, no la
# decide el Builder: es la fecha del `Context Baseline Evidence` de ese contrato,
# cuando se midio el censo de 14/14 fichas SIN recibo.
#
# Es una CONSTANTE DECLARADA, deliberadamente NO calculada de `today()`: una
# fecha derivada del reloj haria que el gate cambiara de veredicto solo, sin que
# nadie tocara codigo -- la caducidad silenciosa que documenta `WOT-2026-024t`.
# Duena: WOT-2026-042x.
GRANDFATHER_CUTOFF = "2026-07-29"

# Codigo de salida del universo VACIO (WOT-2026-067x). Un `rc=0` en el vacio es
# indistinguible del de "valide y no hubo errores", asi que el agregador
# (`prepush_check.py::run_dec_receipt_check`) contaba el SKIP como PASS. El `3`
# no colisiona: `0` = ejecutado sin errores, `1` = al menos un ERROR, `2` =
# error de argparse (reservado). Es un rc DISTINGUIBLE, no parseo de texto.
EXIT_EMPTY_UNIVERSE = 3

# Las TRES formas exactas del recibo (contrato de 042w). El scope entre
# parentesis es obligatorio: dice contra QUE registro se resuelve el id.
_RE_SCOPED = re.compile(r"\bDEC-([A-Za-z0-9][A-Za-z0-9-]*?-\d+)\s*\((motor|destino)\)")
_RE_NO_APLICA = re.compile(r"\bDEC-no-aplica:\s*(\S.*)")

# `FP-YYYYMMDD-...` -> la fecha del nombre decide el grandfathering.
_RE_FP_DATE = re.compile(r"\bFP-(\d{4})(\d{2})(\d{2})")

# Registro del motor: un fichero por DEC, `DEC-<id>-<slug>.md`.
#
# El id NO es un solo segmento: es `<familia>-<numero>` (`008B-001`,
# `motor-charter-001`). Medido contra el registro vivo el 2026-07-29: un patron
# no-greedy de un segmento colapsaba `DEC-008B-001` y `DEC-008B-002` en `008B`
# (6 ficheros -> 5 ids) y habria RECHAZADO un recibo que cita el id completo.
# Por eso el id se ancla al ultimo grupo numerico, no al primer guion.
_RE_MOTOR_FILE = re.compile(r"^DEC-(.+?-\d+)-", re.IGNORECASE)
# Registro del destino: cabeceras `### DEC-<id> -- titulo`.
_RE_DESTINO_HEADING = re.compile(r"^#{1,6}\s+DEC-(.+?-\d+)\s*(?:--|$)")

# Candidata del diagnostico (WOT-2026-061e): MISMA forma que el cargador trata
# como intento de cabecera -- 1 a 6 `#`, espacio, `DEC-`. Sirve para publicar el
# DENOMINADOR (lineas candidatas), no solo las que efectivamente cargaron.
_RE_CANDIDATE_HEADING = re.compile(r"^#{1,6}\s+DEC-")

# --- Modo `ticket_contracts.md` (WOT-2026-088g, contrato T-088G-001) ----------
#
# El registro de contratos NUNCA usa la forma `DEC-<id> (motor)` de las fichas
# del inbox, asi que este modo NO reutiliza `_RE_SCOPED`: tiene su PROPIO patron
# (Forbidden Surface del contrato). Una "cita" (DEC-088G-001, Decision 1) es el
# literal `DEC-<id>` y la ruta `docs/decisions/DEC-<id2>-` DENTRO DEL MISMO
# PARENTESIS; una mencion de prosa sin ese parentesis con ruta se IGNORA.
#
# El patron estricto usa un BACKREFERENCE al grupo 1 para exigir que el id
# citado y el de la ruta SEAN EL MISMO. Una cita CRUZADA (prosa `DEC-086U-001`
# pero ruta `docs/decisions/DEC-086K-001-...`, en el mismo parentesis) NO casa
# con el patron estricto: por eso existe `_RE_CONTRACT_CITATION_SHAPE`, que
# captura ambos ids y permite contarla como "sin resolver" (nunca como silencio).
_RE_CONTRACT_CITATION = re.compile(
    r"\bDEC-([A-Za-z0-9][A-Za-z0-9-]*?-\d+)\b[^()\n]*\([^()\n]*?docs/decisions/DEC-\1-",
)
_RE_CONTRACT_CITATION_SHAPE = re.compile(
    r"\bDEC-([A-Za-z0-9][A-Za-z0-9-]*?-\d+)\b[^()\n]*"
    r"\([^()\n]*?docs/decisions/DEC-([A-Za-z0-9][A-Za-z0-9-]*?-\d+)-",
)

# Cabecera de un contrato en `ticket_contracts.md`: `## T-<ID>-001 -- ...` o
# `## WOT-2026-<id>`. Es el NOMBRE del contrato para el grandfathering por
# contrato individual (`is_grandfathered`), nunca el nombre del fichero entero.
_RE_CONTRACT_HEADER = re.compile(r"^##\s+(?:T-|WOT-)")

# Campo de status de un contrato. Anclado a columna 0 y solo con la PRIMERA
# palabra del valor: hay contratos con `draft (bloqueado por ...)` y menciones
# de prosa indentadas (`` `- **status:** <valor>` ``) que NO son el campo real.
_RE_CONTRACT_STATUS = re.compile(r"^-\s+\*\*status:\*\*\s+([A-Za-z][A-Za-z0-9_-]*)")


def receipt_is_valid(receipt: str, registry: Mapping[str, set[str]] | set[str]) -> bool:
    """Funcion PURA: el recibo cita un DEC que existe en el registro dado.

    NO resuelve topologia, NO hace I/O y NO conoce el mecanismo del drenaje que
    la invoca. El llamante construye el `registry` y se lo pasa ya resuelto.

    RESOLUCION POR SCOPE (WOT-2026-042x, endurecido tras el review): el scope
    entre parentesis dice contra QUE registro se resuelve el id, y esta funcion
    lo HONRA. Un `DEC-<id> (motor)` cuyo id solo exista en el registro del
    DESTINO es recibo INVALIDO, y viceversa. Antes resolvia contra la UNION, de
    modo que un scope mis-etiquetado pasaba en verde: lo cazo el bucle L700
    (tres lentes independientes) y lo confirmo la refutacion final de Codex
    contra la clausula D5 del prompt de diseno, que dice literal "un DEC-<id>
    que NO EXISTE en el registro que su propio scope declara es recibo
    INVALIDO". La NORMA (042w) y la BARRERA (042x) no podian contradecirse.

    Args:
        receipt: Texto del recibo (una linea o el cuerpo que lo contiene).
        registry: O bien un mapping `{"motor": {...}, "destino": {...}}` -- la
            forma que permite resolver POR SCOPE -- o bien un `set` plano, que
            se aplica a cualquier scope (util para tests de la forma del recibo
            y para llamantes que solo tienen un registro).

    Returns:
        True sii el recibo es `DEC-no-aplica: <motivo>` con motivo no vacio, o
        cita al menos un `DEC-<id>` y TODOS los ids citados existen en el
        registro QUE SU SCOPE DECLARA. False en cualquier otro caso (incluido
        recibo ausente).

        PRECEDENCIA: un `DEC-no-aplica` con motivo vale por si solo y NO se
        verifican los ids que el texto pueda citar ademas. Es coherente con la
        promesa ("override declarado"), pero significa que un id inventado que
        acompane a un no-aplica NO se caza.
    """
    no_aplica = _RE_NO_APLICA.search(receipt)
    if no_aplica and no_aplica.group(1).strip().lower() not in ("", "n/a", "na"):
        return True

    hits = [(m.group(1).upper(), m.group(2)) for m in _RE_SCOPED.finditer(receipt)]
    if not hits:
        return False

    def _ids_for(scope: str) -> set[str]:
        if isinstance(registry, Mapping):
            return registry.get(scope) or set()
        return registry

    return all(dec_id in _ids_for(scope) for dec_id, scope in hits)


def load_motor_registry(motor_root: Path) -> set[str]:
    """Ids de DEC del motor, derivados de `docs/decisions/DEC-<id>-<slug>.md`."""
    decisions_dir = motor_root / "docs" / "decisions"
    if not decisions_dir.is_dir():
        return set()
    ids: set[str] = set()
    for path in sorted(decisions_dir.glob("DEC-*.md")):
        match = _RE_MOTOR_FILE.match(path.name)
        if match:
            ids.add(match.group(1).upper())
    return ids


def load_destino_registry(registry_file: Path | None) -> set[str] | None:
    """Ids de DEC del destino, leidos del fichero PASADO COMO ARGUMENTO.

    Returns:
        None si no se paso registro o no existe -> el scope `(destino)` queda
        NO VERIFICABLE (nunca "valido por defecto"). Un set en caso contrario.
    """
    if registry_file is None or not registry_file.is_file():
        return None
    ids: set[str] = set()
    for line in registry_file.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        match = _RE_DESTINO_HEADING.match(line.strip())
        if match:
            ids.add(match.group(1).upper())
    return ids


def destino_heading_diagnostic(
    registry_file: Path | None,
) -> tuple[int, int, str | None]:
    r"""Diagnostico de solo lectura: cuantas cabeceras intento cargar el guard.

    ESPEJA a `load_destino_registry` (misma resolucion de ruta, misma lectura,
    mismas lineas candidatas) para publicar el DENOMINADOR que hoy no sale en
    ningun sitio: un registro con 12 cabeceras y 0 cargables no se distingue de
    uno con 0 cabeceras cuando el unico resumen es `destino=0`
    (WOT-2026-061e).

    Before: recibe la MISMA ruta que el cargador, o `None`.
    During: solo lectura. Cada linea `s = line.strip()` es CANDIDATA si casa
        `^#{1,6}\s+DEC-` (como el cargador: cuenta las de bloques de codigo y
        `####` a `######`; 7 o mas `#` no; sin manejo de BOM: limitacion
        declarada) y CARGABLE si ademas casa `_RE_DESTINO_HEADING`. `ejemplo`
        es la PRIMERA candidata no cargable, recortada a 100 caracteres.
    After: `(candidatas, cargables, ejemplo)`; con `None`, fichero ausente u
        `OSError` devuelve `(0, 0, None)` sin lanzar y sin mutar nada.
    """
    if registry_file is None or not registry_file.is_file():
        return (0, 0, None)
    try:
        text = registry_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return (0, 0, None)

    candidates = 0
    loadable = 0
    example: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if not _RE_CANDIDATE_HEADING.match(s):
            continue
        candidates += 1
        if _RE_DESTINO_HEADING.match(s):
            loadable += 1
        elif example is None:
            example = s[:100]
    return (candidates, loadable, example)


def is_grandfathered(name: str, cutoff: str = GRANDFATHER_CUTOFF) -> bool:
    """True si el `FP-<fecha>` del nombre es ANTERIOR al cutoff.

    Una ficha sin fecha parseable NO se grandfathering-ea: ante duda, se exige
    el recibo (fail-closed), que es la asimetria correcta para una barrera.
    """
    match = _RE_FP_DATE.search(name)
    if not match:
        return False
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" < cutoff


def check_file(
    path: Path,
    motor_registry: set[str],
    destino_registry: set[str] | None,
) -> tuple[str, str]:
    """Clasifica una ficha. Returns: (nivel, mensaje) con nivel OK|WARN|ERROR."""
    text = path.read_text(encoding="utf-8", errors="replace")

    has_destino_scope = any(m.group(2) == "destino" for m in _RE_SCOPED.finditer(text))
    if has_destino_scope and destino_registry is None:
        return (
            "ERROR",
            f"{path.name}: recibo con scope (destino) pero no se paso "
            "--destino-registry -> NO VERIFICABLE; un recibo que no se puede "
            "resolver nunca se da por bueno",
        )

    # POR SCOPE, no la union: un `DEC-<id> (motor)` cuyo id solo viva en el
    # registro del destino es INVALIDO (clausula D5 del prompt de diseno).
    registry = {
        "motor": set(motor_registry),
        "destino": set(destino_registry) if destino_registry is not None else set(),
    }

    if receipt_is_valid(text, registry):
        return ("OK", f"{path.name}: recibo valido")

    if is_grandfathered(path.name):
        return (
            "WARN",
            f"{path.name}: sin recibo valido, pero es ANTERIOR al cutoff "
            f"{GRANDFATHER_CUTOFF} -> grandfathered (WARN, no bloquea)",
        )

    return (
        "ERROR",
        f"{path.name}: sin recibo DEC valido. Formas aceptadas: "
        "'DEC-<id> (motor)', 'DEC-<id> (destino)', 'DEC-no-aplica: <motivo>'. "
        "Un DEC-<id> citado debe EXISTIR en el registro que su scope declara.",
    )


class _ContractBlock:
    """Un contrato de `ticket_contracts.md` y las citas DEC que le pertenecen.

    Clase PLANA (no `@dataclass`): el test de este modulo lo carga con
    `spec_from_file_location` sin registrarlo en `sys.modules`, y el decorador
    `@dataclass` revienta al resolver `sys.modules[cls.__module__]` en esa ruta.
    """

    __slots__ = ("citations", "header", "status")

    def __init__(self, header: str) -> None:
        self.header = header
        self.status: str | None = None
        self.citations: list[tuple[int, str, str]] = []


def _split_ticket_contract_blocks(lines: list[str]) -> list[_ContractBlock]:
    """Divide `ticket_contracts.md` en contratos.

    Cada contrato empieza en su cabecera `## T-...`/`## WOT-...` y se extiende
    hasta la siguiente. El status se lee del PRIMER campo `- **status:**` del
    bloque. Una cita se atribuye al contrato cuya cabecera la ANTECEDE (misma
    tecnica que exige el contrato para `is_grandfathered`).

    Cada cita se guarda como `(linea, id_citado, id_de_la_ruta)`: el segundo es
    el literal `DEC-<id>` y el tercero el id de `docs/decisions/DEC-<id2>-`. Son
    iguales en una cita limpia; distintos en una CRUZADA (que el patron estricto
    con backreference no casa, por eso `_RE_CONTRACT_CITATION_SHAPE` la detecta).
    """
    blocks: list[_ContractBlock] = []
    current: _ContractBlock | None = None
    for line_no, line in enumerate(lines, start=1):
        if _RE_CONTRACT_HEADER.match(line):
            current = _ContractBlock(header=line)
            blocks.append(current)
        if current is None:
            continue
        if current.status is None:
            match = _RE_CONTRACT_STATUS.match(line)
            if match:
                current.status = match.group(1).lower()
        for match in _RE_CONTRACT_CITATION.finditer(line):
            dec_id = match.group(1).upper()
            current.citations.append((line_no, dec_id, dec_id))
        for match in _RE_CONTRACT_CITATION_SHAPE.finditer(line):
            dec_id, path_id = match.group(1).upper(), match.group(2).upper()
            if dec_id != path_id:
                current.citations.append((line_no, dec_id, path_id))
    return blocks


def count_frozen_contracts(path: Path) -> int:
    """Numero de contratos con `status: frozen` en un `ticket_contracts.md`.

    Es el DENOMINADOR `contratos_inspeccionados` del resumen (DoD D5): un
    contrato `draft`/`invalidated`/otro status queda FUERA del universo que este
    modo inspecciona (DEC-088G-001, Decision 2). Solo lectura.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return sum(
        1 for block in _split_ticket_contract_blocks(lines) if block.status == "frozen"
    )


def _classify_contract_citation(
    file_label: str,
    line_no: int,
    header: str,
    dec_id: str,
    path_id: str,
    motor_registry: set[str],
    destino_registry: set[str] | None,
) -> tuple[str, str]:
    """Clasifica UNA cita de contrato. Returns: (nivel, mensaje) OK|WARN|ERROR."""
    if dec_id != path_id:
        return (
            "ERROR",
            f"{file_label}:{line_no}: cita CRUZADA `DEC-{dec_id}` con ruta "
            f"`docs/decisions/DEC-{path_id}-...` (ids distintos) -> SIN RESOLVER; "
            f"un contrato que cita un id y enlaza a otro nunca se da por bueno",
        )
    resolved = dec_id in motor_registry or (
        destino_registry is not None and dec_id in destino_registry
    )
    if resolved:
        return ("OK", f"{file_label}:{line_no}: cita `DEC-{dec_id}` resuelta")
    if is_grandfathered(header):
        return (
            "WARN",
            f"{file_label}:{line_no}: cita `DEC-{dec_id}` sin resolver, pero el "
            f"contrato '{header.strip()[:60]}' es ANTERIOR a {GRANDFATHER_CUTOFF} "
            f"-> grandfathered (WARN, no bloquea)",
        )
    return (
        "ERROR",
        f"{file_label}:{line_no}: cita `DEC-{dec_id}` NO resuelve a ningun "
        f"fichero docs/decisions/DEC-{dec_id}-*.md en el registro declarado",
    )


def check_ticket_contracts_file(
    path: Path,
    motor_registry: set[str],
    destino_registry: set[str] | None,
) -> list[tuple[str, str]]:
    """Clasifica las citas DEC de un `ticket_contracts.md`, UNA entrada por cita.

    Modo nuevo de WOT-2026-088g (contrato T-088G-001). Un contrato `frozen`
    puede citar una DEC inexistente y, hasta ahora, nada lo detectaba: la norma
    de `WOT-2026-042w`/`042x` solo cubria las fichas de los buzones.

    Before: `path` es un fichero existente; los dos registros ya resueltos.
    During: solo lectura. Divide el fichero en contratos, descarta los que NO
        declaran `status: frozen` (DEC-088G-001, Decision 2) y clasifica cada
        cita del universo restante: resuelta -> OK; id inexistente -> ERROR (o
        WARN si el contrato es anterior a `GRANDFATHER_CUTOFF`); cita cruzada
        (id citado != id de la ruta, en el mismo parentesis) -> ERROR.
    After: una lista de `(nivel, mensaje)` con nivel OK|WARN|ERROR, en orden de
        aparicion. Una entrada por CITA (no una por fichero): el fichero tiene
        90+ contratos y el mensaje debe senalar CUAL cita fallo.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    entries: list[tuple[str, str]] = []
    for block in _split_ticket_contract_blocks(lines):
        if block.status != "frozen":
            continue
        for line_no, dec_id, path_id in block.citations:
            entries.append(
                _classify_contract_citation(
                    path.name,
                    line_no,
                    block.header,
                    dec_id,
                    path_id,
                    motor_registry,
                    destino_registry,
                )
            )
    return entries


def _check_inbox_surface(
    files: list[Path],
    motor_registry: set[str],
    destino_registry: set[str] | None,
) -> int:
    """Clasifica las fichas de los buzones e imprime el resumen del inbox.

    Returns: numero de ERRORES de la superficie `--inbox`.
    """
    oks = warns = errors = 0
    for path in files:
        level, message = check_file(path, motor_registry, destino_registry)
        if level == "ERROR":
            errors += 1
            print(f"[dec-receipt] ERROR {message}")
        elif level == "WARN":
            warns += 1
            print(f"[dec-receipt] WARN  {message}")
        else:
            oks += 1
    print(
        f"[dec-receipt] {oks} ok / {warns} warn (grandfathered < "
        f"{GRANDFATHER_CUTOFF}) / {errors} error; "
        f"DEC motor={len(motor_registry)}, "
        f"destino={'no pasado' if destino_registry is None else len(destino_registry)}"
    )
    return errors


def _check_ticket_contracts_surface(
    ticket_contracts: list[Path],
    motor_registry: set[str],
    destino_registry: set[str] | None,
) -> int:
    """Procesa la superficie `--ticket-contracts` e imprime su denominador.

    Un `--ticket-contracts` que no existe como fichero es ERROR fail-closed
    (nunca silencio). El resumen publica los 4 denominadores del modo nuevo
    (DoD D5): `contratos_inspeccionados`, `citas_encontradas`,
    `citas_resueltas`, `citas_sin_resolver`.

    Returns: numero de ERRORES (citas sin resolver + ficheros ausentes).
    """
    insp = 0
    oks = warns = errors = 0
    missing = 0
    for tc_path in ticket_contracts:
        if not tc_path.is_file():
            missing += 1
            print(
                f"[dec-receipt] ERROR {tc_path}: --ticket-contracts no existe "
                "como fichero -> ERROR (fail-closed, nunca silencio)"
            )
            continue
        insp += count_frozen_contracts(tc_path)
        for level, message in check_ticket_contracts_file(
            tc_path, motor_registry, destino_registry
        ):
            if level == "ERROR":
                errors += 1
                print(f"[dec-receipt] ERROR {message}")
            elif level == "WARN":
                warns += 1
                print(f"[dec-receipt] WARN  {message}")
            else:
                oks += 1
    print(
        "[dec-receipt] ticket_contracts: "
        f"contratos_inspeccionados={insp}, "
        f"citas_encontradas={oks + warns + errors}, "
        f"citas_resueltas={oks}, "
        f"citas_sin_resolver={warns + errors}"
    )
    return errors + missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Valida el recibo DEC de las fichas de diseno contra el registro "
            "que el propio recibo declara por su scope (WOT-2026-042x)."
        )
    )
    parser.add_argument(
        "--motor-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Raiz del motor (contiene docs/decisions/).",
    )
    parser.add_argument(
        "--destino-registry",
        type=Path,
        default=None,
        help=(
            "Registro de decisiones del destino, PASADO COMO ARGUMENTO. El "
            "guard NO resuelve la topologia motor<->destino por su cuenta."
        ),
    )
    parser.add_argument(
        "--inbox",
        type=Path,
        action="append",
        default=None,
        help="Directorio de fichas a validar (repetible).",
    )
    parser.add_argument(
        "--ticket-contracts",
        type=Path,
        action="append",
        default=None,
        help=(
            "Fichero `ticket_contracts.md` a validar (repetible). Inspecciona "
            "solo los contratos `status: frozen` y valida cada cita DEC "
            "(WOT-2026-088g)."
        ),
    )
    args = parser.parse_args(argv)

    motor_registry = load_motor_registry(args.motor_root)
    destino_registry = load_destino_registry(args.destino_registry)

    # AVISO autoexplicativo (WOT-2026-061e): publica el DENOMINADOR (cabeceras
    # candidatas vs cargadas) sin cambiar ningun codigo de salida. El veredicto
    # sigue saliendo de los recibos; este WARN solo explica un `destino=0`.
    if args.destino_registry is not None:
        candidates, loadable, example = destino_heading_diagnostic(
            args.destino_registry
        )
        if candidates > loadable:
            print(
                f"[dec-receipt] WARN {args.destino_registry.name}: {loadable} de "
                f"{candidates} cabeceras 'DEC-' cargables; no cargable p.ej. "
                f"'{example}'; formato esperado: "
                f"'### DEC-<familia>-<NNN> -- <titulo>'"
            )

    inboxes = [d for d in (args.inbox or []) if d.is_dir()]
    files = sorted(f for d in inboxes for f in d.glob("*.tickets.md"))
    ticket_contracts = list(args.ticket_contracts or [])

    # El universo vacio se evalua por SUPERFICIE (DoD D2): solo cuando NINGUNA de
    # las dos superficies tiene materia se mantiene el SKIP con rc distinguible.
    # Si hay `--ticket-contracts`, el veredicto es de ESA superficie (no se
    # reimprime el SKIP de inbox vacio como si fuera el resultado final).
    if not files and not ticket_contracts:
        # El vacio publica su DENOMINADOR completo (Quality Bar + DEC-047S-001:
        # un verde con `inspeccionados == 0` solo es legitimo con la tupla y la
        # lista de saltados) y sale con un rc DISTINGUIBLE, no `0`.
        print(
            "[dec-receipt] SKIP EXPLICITO: 0 fichas a validar "
            "(inspeccionados=0, hits=0, saltados=0, lista_saltados=[]; "
            f"inboxes existentes: {len(inboxes)}). No es un PASS."
        )
        return EXIT_EMPTY_UNIVERSE

    errors = 0
    if files:
        errors += _check_inbox_surface(files, motor_registry, destino_registry)
    if ticket_contracts:
        errors += _check_ticket_contracts_surface(
            ticket_contracts, motor_registry, destino_registry
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
