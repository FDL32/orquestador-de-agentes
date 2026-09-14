"""WOT-2026-069e: resolucion compartida de ``delivery_authority``.

UN solo sitio decide como se lee el campo ``delivery_authority`` de un
``work_plan.md`` para la familia de guards de entrega
(``pre_handoff_guard``, ``run_pytest_safe``, ``delivery_hygiene_check``,
``collect_system_health``). Antes cada uno llevaba su copia del regex naive
``delivery_authority\\s*:?\\**\\s*(?:repo_destino|destino)`` medido sobre el
contenido COMPLETO: la prosa del plan podia anular el campo de Metadata
(defecto ``CG-WOT-2026-069a.md``, bloqueo del cierre de WOT-2026-069a).

Politica (contrato T-069E-001, decisiones de producto ya tomadas):

- El campo se resuelve EXCLUSIVAMENTE dentro de la seccion ``## Metadata``
  (del encabezado exacto al siguiente encabezado ``## `` o EOF).
- La busqueda del valor la hace el resolvedor CANONICO
  ``scope_gate.read_delivery_authority`` (reutilizado, no duplicado: cero
  regex nuevo del campo en los consumidores).
- Ambos valores son de primera clase: ``repo_motor`` y ``repo_destino``.
- El camino degradado nunca es un valor empobrecido silencioso: se devuelve
  el par ``(valor, motivo)`` con MOTIVO NOMBRADO
  (``metadata_field`` / ``no_field_in_metadata`` / ``no_metadata_section``)
  para que el consumidor distinga "la Metadata lo dijo" de "caimos al
  default".

Before:
    - ``content`` es la prosa cruda de un ``work_plan.md`` (puede venir vacia
      o sin seccion Metadata: legible, nunca lanza).
During:
    - Sin I/O, sin git, sin red: corte de seccion sobre listas de lineas y
      una llamada al canonico via el bootstrap ``__file__`` hacia el
      ``.agent/`` del motor.
After:
    - ``resolve_delivery_authority_from_content(content) -> tuple[str, str]`` con valor en
      {``repo_motor``, ``repo_destino``} y motivo nombrado. Nunca lanza por
      contenido malformado; un fallo del import canonico propaga (el
      resolvedor canónico es condicion de existencia del motor).
"""

from __future__ import annotations

import sys
from pathlib import Path


_BOOTSTRAP = Path(__file__).resolve().parent.parent

DEFAULT_AUTHORITY = "repo_motor"
REASON_METADATA_FIELD = "metadata_field"
REASON_NO_FIELD = "no_field_in_metadata"
REASON_NO_SECTION = "no_metadata_section"

_METADATA_HEADING = "Metadata"

_ABSENT = object()


def _import_scope_gate():
    """Importa el resolvedor canonico desde el ``.agent/`` del motor.

    Mismo patron de bootstrap que ``pre_handoff_guard._import_scope_gate``.
    """
    agent_dir = _BOOTSTRAP / ".agent"
    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    import scope_gate

    return scope_gate


def metadata_section(content: str) -> str | None:
    """Rebanada ``## Metadata`` del documento, o None si no existe.

    Before: ``content`` string (posible vacio).
    During: la seccion empieza por el encabezado EXACTO ``## Metadata``
    (comparado tras strip) y termina en la siguiente linea de nivel ``## ``.
    Los sub-encabezados ``### `` internos no la cortan.
    After: texto de la seccion (sin el encabezado iniciador) o None si el
    documento no declara ``## Metadata``.
    """
    section_lines: list[str] = []
    in_section = False
    for raw_line in (content or "").splitlines():
        stripped = raw_line.strip()
        if stripped == f"## {_METADATA_HEADING}":
            in_section = True
            continue
        if (
            in_section
            and stripped.startswith("## ")
            and not stripped.startswith("### ")
        ):
            break
        if in_section:
            section_lines.append(raw_line)
    if not in_section:
        return None
    return "\n".join(section_lines)


def resolve_delivery_authority_from_content(content: str) -> tuple[str, str]:
    """Devuelve ``(valor, motivo)`` del campo ``delivery_authority``.

    Before/After y politica: ver docstring del modulo. Motivo nombrado SIEMPRE:
    ``metadata_field`` cuando la Metadata declara el valor (uno u otro);
    ``no_field_in_metadata`` cuando habiendo seccion no hay campo;
    ``no_metadata_section`` cuando el documento no tiene ``## Metadata``. En
    los dos ultimos el valor es ``repo_motor`` (default historico de la
    familia) y el motivo impide que un consumidor lo confunda con una
    declaracion.
    """
    section = metadata_section(content)
    if section is None:
        return DEFAULT_AUTHORITY, REASON_NO_SECTION
    value = _import_scope_gate().read_delivery_authority(section, default=_ABSENT)
    if value is _ABSENT:
        return DEFAULT_AUTHORITY, REASON_NO_FIELD
    return value, REASON_METADATA_FIELD


def read_delivery_authority(content: str) -> str:
    """Version valor-unico para consumidores con firma ``-> str``."""
    return resolve_delivery_authority_from_content(content)[0]
