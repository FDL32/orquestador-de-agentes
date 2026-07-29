#!/usr/bin/env python3
"""Barrera del recibo DEC: un `DEC-<id>` citado tiene que EXISTIR (WOT-2026-042x).

`WOT-2026-042w` introdujo la NORMA: las sesiones de DISENO consultan el registro
de decisiones y dejan un recibo estructurado en cada ficha/plan. Una norma que
nada verifica sigue siendo una norma -- este guard es la barrera.

Que valida (y que NO)
---------------------
Valida que el `DEC-<id>` que un recibo cita EXISTE en el registro que el PROPIO
recibo declara por su scope. Nada mas. En particular NO promete detectar
contradiccion SEMANTICA entre la adjudicacion y la DEC: eso exigiria un juez de
prosa, no converge (muro `WOT-2026-025c`) y seria irreproducible. La promesa
exacta es: *no pasa sin referencia verificable u override declarado*.

La funcion PURA
---------------
`receipt_is_valid(receipt, registry) -> bool` no hace I/O, no resuelve roots y no
sabe nada del transporte que la invoca. Es deliberado: el drenaje del paso 8.bis
que hoy nombra este criterio es 100% prompt-level y `WOT-2026-042u` va a
reescribirlo; una validacion embebida en el transporte moriria con el.

Topologia: el guard NO cruza repos
----------------------------------
El scope `(motor)` resuelve contra `docs/decisions/` del propio motor. El scope
`(destino)` resuelve contra el registro que se le pasa como ARGUMENTO
(`--destino-registry`). Si no se le pasa, el recibo `(destino)` se marca
NO VERIFICABLE con motivo y NUNCA se da por bueno. Resolver la topologia
motor<->destino DENTRO del guard es una STOP condition del contrato.

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


def receipt_is_valid(receipt: str, registry: set[str]) -> bool:
    """Funcion PURA: el recibo cita un DEC que existe en el registro dado.

    NO resuelve topologia, NO hace I/O y NO conoce el mecanismo del drenaje que
    la invoca. El llamante decide QUE registro corresponde al scope del recibo y
    se lo pasa ya resuelto.

    Args:
        receipt: Texto del recibo (una linea o el cuerpo que lo contiene).
        registry: Ids de DEC existentes en el registro contra el que se resuelve,
            normalizados en mayusculas.

    Returns:
        True sii el recibo es `DEC-no-aplica: <motivo>` con motivo no vacio, o
        cita al menos un `DEC-<id>` y TODOS los ids citados existen en
        `registry`. False en cualquier otro caso (incluido recibo ausente).
    """
    no_aplica = _RE_NO_APLICA.search(receipt)
    if no_aplica and no_aplica.group(1).strip().lower() not in ("", "n/a", "na"):
        return True

    ids = [m.group(1).upper() for m in _RE_SCOPED.finditer(receipt)]
    if not ids:
        return False
    return all(dec_id in registry for dec_id in ids)


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

    registry = set(motor_registry)
    if destino_registry is not None:
        registry |= destino_registry

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
    args = parser.parse_args(argv)

    motor_registry = load_motor_registry(args.motor_root)
    destino_registry = load_destino_registry(args.destino_registry)

    inboxes = [d for d in (args.inbox or []) if d.is_dir()]
    files = sorted(f for d in inboxes for f in d.glob("*.tickets.md"))

    if not files:
        print(
            "[dec-receipt] SKIP EXPLICITO: 0 fichas a validar "
            f"(inboxes existentes: {len(inboxes)}). No es un PASS."
        )
        return 0

    errors = warns = oks = 0
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
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
