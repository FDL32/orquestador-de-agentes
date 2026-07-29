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
